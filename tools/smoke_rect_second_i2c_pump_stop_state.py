#!/usr/bin/env python3
"""Проверяет сохранение состояния второго насоса до подтверждённого STOP."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
LOGIC = (ROOT / "logic.h").read_text(encoding="utf-8")

ENABLED_BODY = extract_function_body(
    LOGIC, "inline bool rect_second_i2c_pump_enabled()"
)
STOP_BODY = extract_function_body(
    LOGIC, "inline bool rect_stop_second_i2c_pump_if_running()"
)
APPLY_BODY = extract_function_body(
    LOGIC, "inline bool rect_apply_second_pump_for_row(const WProgram& row)"
)

HARNESS = r'''
#include <cstdint>
#include <iostream>

constexpr uint8_t I2CSTEPPER_PUMP_ADDR = 2;

struct Setup {
  bool UseSecondI2CPump = true;
  float SecondI2CPumpRate = 1.0f;
} SamSetup;

struct WProgram {
  char WType;
  float Speed;
  uint16_t Volume;
};

static uint8_t use_I2C_dev = I2CSTEPPER_PUMP_ADDR;
static bool rectSecondPumpRunning = false;
static bool rectSecondPumpHeadsRow = false;
static bool rectSecondPumpHeadsFilling = false;
static bool rectSecondPumpPaused = false;
static uint16_t rectSecondPumpPausedVolume = 0;
static uint32_t rectSecondPumpTargetSteps = 0;

static bool stopResult = true;
static int stopCalls = 0;
static bool startResult = true;
static int startCalls = 0;

bool stop_second_i2c_pump() {
  stopCalls++;
  return stopResult;
}

bool start_second_i2c_pump(float, uint16_t) {
  startCalls++;
  return startResult;
}

uint16_t i2c_stepper_steps_per_ml() { return 100; }

bool program_type_one_of(char type, const char* values) {
  for (const char* value = values; *value != '\0'; value++) {
    if (type == *value) return true;
  }
  return false;
}

inline bool rect_second_i2c_pump_enabled() {
@ENABLED_BODY@
}

inline bool rect_stop_second_i2c_pump_if_running() {
@STOP_BODY@
}

inline bool rect_apply_second_pump_for_row(const WProgram& row) {
@APPLY_BODY@
}

static int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  rectSecondPumpRunning = true;
  stopResult = false;
  check(!rect_stop_second_i2c_pump_if_running(),
        "unconfirmed STOP must report failure");
  check(rectSecondPumpRunning,
        "unconfirmed STOP must preserve running state for retry");
  check(stopCalls == 1, "first STOP attempt must reach the physical pump");

  stopResult = true;
  check(rect_stop_second_i2c_pump_if_running(),
        "confirmed retry must succeed");
  check(!rectSecondPumpRunning,
        "only confirmed STOP may clear running state");
  check(stopCalls == 2, "confirmed retry must send STOP again");

  SamSetup.UseSecondI2CPump = false;
  rectSecondPumpRunning = true;
  rectSecondPumpHeadsRow = false;
  rectSecondPumpPaused = true;
  stopResult = false;
  WProgram bodyRow{'B', 0.0f, 0};
  check(!rect_apply_second_pump_for_row(bodyRow),
        "disabling during B/C must fail until physical STOP is confirmed");
  check(rectSecondPumpRunning,
        "disabling during B/C must preserve running state after failed STOP");

  stopResult = true;
  check(rect_apply_second_pump_for_row(bodyRow),
        "disabling during B/C must allow a confirmed STOP retry");
  check(!rectSecondPumpRunning,
        "confirmed STOP after disabling must clear running state");
  check(!rectSecondPumpPaused,
        "confirmed STOP after disabling may clear pause bookkeeping");
  check(startCalls == 0,
        "disabled setting must never restart the pump while stopping it");

  if (failures != 0) return 1;
  std::cout << "rect second I2C pump stop-state checks passed\n";
  return 0;
}
'''


def compile_and_run(
    compiler: str, directory: Path, stop_body: str, apply_body: str, name: str
) -> subprocess.CompletedProcess[str]:
    source = (
        HARNESS.replace("@ENABLED_BODY@", ENABLED_BODY)
        .replace("@STOP_BODY@", stop_body)
        .replace("@APPLY_BODY@", apply_body)
    )
    source_path = directory / f"{name}.cpp"
    binary_path = directory / name
    source_path.write_text(source, encoding="utf-8")
    compiled = subprocess.run(
        [
            compiler,
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source_path),
            "-o",
            str(binary_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        return compiled
    return subprocess.run(
        [str(binary_path)], capture_output=True, text=True, check=False
    )


def require_mutation_failure(
    result: subprocess.CompletedProcess[str], expected: str, mutation: str
) -> bool:
    output = result.stdout + result.stderr
    if result.returncode == 0:
        print(f"FAIL: {mutation} mutation survived", file=sys.stderr)
        return False
    if expected not in output:
        print(f"FAIL: {mutation} mutation failed for an unrelated reason", file=sys.stderr)
        print(output, file=sys.stderr)
        return False
    return True


def main() -> int:
    compiler = shutil.which("g++")
    if compiler is None:
        print("FAIL: g++ is required for second-pump stop-state smoke", file=sys.stderr)
        return 1

    stop_anchor = "if (!stop_second_i2c_pump()) return false;"
    apply_anchor = "if (!rect_stop_second_i2c_pump_if_running()) return false;"
    if STOP_BODY.count(stop_anchor) != 1:
        print("FAIL: STOP-state mutation anchor is missing", file=sys.stderr)
        return 1
    if APPLY_BODY.count(apply_anchor) != 1:
        print("FAIL: disabled-setting mutation anchor is missing", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-rect-second-pump-") as tmp:
        directory = Path(tmp)
        result = compile_and_run(
            compiler, directory, STOP_BODY, APPLY_BODY, "stop_state"
        )
        if result.returncode != 0:
            print("FAIL: second-pump stop-state harness failed", file=sys.stderr)
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1

        mutated_stop = STOP_BODY.replace(
            stop_anchor, "if (!stop_second_i2c_pump()) return true;", 1
        )
        stop_result = compile_and_run(
            compiler, directory, mutated_stop, APPLY_BODY, "stop_state_mutated"
        )
        if not require_mutation_failure(
            stop_result,
            "unconfirmed STOP must report failure",
            "unconfirmed STOP",
        ):
            return 1

        mutated_apply = APPLY_BODY.replace(
            apply_anchor, "rect_stop_second_i2c_pump_if_running();", 1
        )
        apply_result = compile_and_run(
            compiler, directory, STOP_BODY, mutated_apply, "disabled_stop_mutated"
        )
        if not require_mutation_failure(
            apply_result,
            "disabling during B/C must fail until physical STOP is confirmed",
            "disabled-setting STOP",
        ):
            return 1

        print(result.stdout, end="")
        return 0


sys.exit(main())
