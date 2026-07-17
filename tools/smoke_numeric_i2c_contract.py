#!/usr/bin/env python3
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
web = strip_cpp_comments((ROOT / "WebServer.ino").read_text(encoding="utf-8", errors="ignore"))


def body(signature: str) -> str:
    try:
        return extract_function_body(web, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


patch_body = body("static NumericParseResult parse_i2c_stepper_patch")
stepper_body = body("static void handle_i2c_stepper_request")
pump_body = body("static void handle_i2c_pump_request")

require_ordered_tokens(
    "I2C patch is all-or-nothing",
    patch_body,
    [
        "I2CStepperDevice parsed = current;",
        'parse_i2c_stepper_u8(request, "mode", 1, 3, parsed.mode, errorField)',
        'parse_i2c_stepper_u8(request, "relayMask", 0, 15, parsed.relayMask, errorField)',
        'parse_i2c_stepper_u8(request, "sensorFlags", 0, 7, parsed.sensorFlags, errorField)',
        'parse_i2c_stepper_u16(request, "stepsPerMl", 1, UINT16_MAX, parsed.stepsPerMl, errorField)',
        "hasRelay != hasState",
        'command == "status" || command == "stop" || command == "calfinish"',
        'command == "calstart"',
        'request_param_count(request, "stepsPerMl") != 1',
        "candidate = parsed;",
    ],
    errors,
)
if patch_body.count("candidate = parsed;") != 1:
    errors.append("I2C patch must publish candidate exactly once")
for token in [".toInt()", ".toFloat()", "& 0x0F"]:
    if token in patch_body:
        errors.append(f"I2C patch contains unsafe conversion/mask: {token}")

require_ordered_tokens(
    "I2C stepper validates before queue",
    stepper_body,
    [
        "!i2c_stepper_known_param(param->name())",
        "request_param_count(request, param->name().c_str()) != 1",
        "command != \"status\"",
        "parse_i2c_stepper_patch(",
        "if (!result.ok())",
        "pendingCmd.staged = staged;",
        "OperationId operationId = 0;",
        "queue_pending_i2cstepper(",
        "pendingCmd, operationId)",
        "send_i2c_operation_accepted(request, operationId);",
    ],
    errors,
)
require_ordered_tokens(
    "I2C pump validates typed draft before queue",
    pump_body,
    [
        "stopCount == 1",
        "speedCount != 0 || volumeCount != 0",
        "speedCount != 1 || volumeCount != 1",
        "parse_control_i2c_pump(",
        "send_i2c_numeric_error(request, errorField, result.error);",
        "command.targetSteps = parsed.targetSteps;",
        "OperationId operationId = 0;",
        "queue_pending_i2cpump(",
        "command, operationId)",
        'send_no_store_response(request, 200, "text/plain", "OK");',
    ],
    errors,
)
# The stop branch and the speed/volume branch both end with the identical
# `send_no_store_response(request, 200, "text/plain", "OK");` literal, so an
# ordered-token scan over the whole pump_body would happily skip a mutated/
# missing stop-branch reply and match the untouched one further down in the
# speed/volume branch instead. Scope the check to just the `if (stopCount ==
# 1) { ... }` block so a mutation there cannot hide behind the other branch.
if pump_body:
    try:
        stop_branch_body, _ = extract_braced_block_after(pump_body, "if (stopCount == 1)")
        require_ordered_tokens(
            "I2C pump stop branch answers OK once queued",
            stop_branch_body,
            [
                "command.is_stop = true;",
                "OperationId operationId = 0;",
                "queue_pending_i2cpump(",
                "command, operationId)",
                'send_no_store_response(request, 200, "text/plain", "OK");',
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
for token in ["I2C_STEPPER_STEP_ML_DEFAULT", "i2c_stepper_steps_from_rate", ".toFloat()", ".toInt()"]:
    if token in pump_body:
        errors.append(f"I2C pump external path contains fallback/unsafe conversion: {token}")

# --- G8: relay/state errorField must name the actual failing cause, not a
#         collapsed hasRelay-based guess (duplicated "relay" was misreported
#         as "state"). Extract the REAL relayCount/stateCount block from
#         parse_i2c_stepper_patch and drive it with every failure cause.
RELAY_BLOCK_START = 'const uint8_t relayCount = request_param_count(request, "relay");'
RELAY_BLOCK_IF = 'if (hasRelay != hasState || relayCount > 1 || stateCount > 1) {'

relay_error_field_slice = ""
if patch_body:
    start = patch_body.find(RELAY_BLOCK_START)
    if start < 0:
        errors.append("parse_i2c_stepper_patch missing relay/state count block")
    else:
        try:
            _, end = extract_braced_block_after(patch_body, RELAY_BLOCK_IF)
            relay_error_field_slice = patch_body[start:end]
        except ValueError as exc:
            errors.append(str(exc))

RELAY_ERROR_FIELD_HARNESS = r'''
#include <cstdint>
#include <cstring>
#include <iostream>

#include "numeric_parse.h"

struct FakeRequest {};

static int relay_count_stub = 0;
static int state_count_stub = 0;

static uint8_t request_param_count(FakeRequest*, const char* name) {
  if (std::strcmp(name, "relay") == 0) return static_cast<uint8_t>(relay_count_stub);
  if (std::strcmp(name, "state") == 0) return static_cast<uint8_t>(state_count_stub);
  return 0;
}

static NumericParseResult run_case(FakeRequest* request, const char*& errorField) {
@SLICE@
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void expect_error(int relayCount, int stateCount, const char* expectedField, const char* what) {
  relay_count_stub = relayCount;
  state_count_stub = stateCount;
  FakeRequest request;
  const char* errorField = "sentinel";
  NumericParseResult result = run_case(&request, errorField);
  check(!result.ok(), what);
  check(std::strcmp(errorField, expectedField) == 0, what);
}

int main() {
  // Одна причина отказа — пропущен парный ключ.
  expect_error(0, 1, "relay", "missing relay must be reported as relay");
  expect_error(1, 0, "state", "missing state must be reported as state");

  // Баг из тикета: дублирующийся relay при валидном одиночном state
  // раньше репортился как "Invalid state".
  expect_error(2, 1, "relay", "duplicated relay must be reported as relay, not state");
  // Симметричный случай: дублирующийся state.
  expect_error(1, 2, "state", "duplicated state must be reported as state");

  // Валидные комбинации не должны попадать в этот блок вообще.
  {
    relay_count_stub = 1;
    state_count_stub = 1;
    FakeRequest request;
    const char* errorField = "sentinel";
    check(run_case(&request, errorField).ok(), "matched relay/state pair must not error");
  }
  {
    relay_count_stub = 0;
    state_count_stub = 0;
    FakeRequest request;
    const char* errorField = "sentinel";
    check(run_case(&request, errorField).ok(), "absent relay/state pair must not error");
  }

  if (failures != 0) return 1;
  std::cout << "I2C stepper patch relay/state errorField checks passed\n";
  return 0;
}
'''


def run_relay_error_field_check() -> None:
    if not relay_error_field_slice:
        return
    harness = RELAY_ERROR_FIELD_HARNESS.replace("@SLICE@", relay_error_field_slice)
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-relay-errorfield-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "relay_error_field_test.cpp"
        binary = temp / "relay_error_field_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append("relay/state errorField harness compile failed:\n" +
                           compile_result.stdout + compile_result.stderr)
            return
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if run_result.returncode != 0:
            errors.append("relay/state errorField runtime checks failed:\n" +
                           run_result.stdout + run_result.stderr)


run_relay_error_field_check()

if errors:
    print("Numeric I2C contract smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Numeric I2C contract smoke passed")
