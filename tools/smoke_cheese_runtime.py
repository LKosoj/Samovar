#!/usr/bin/env python3
"""Source-derived smoke checks for the cheese runtime state decisions."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
CHEESE = ROOT / "cheese.h"

CLASSIFY_SIGNATURE = "inline CheeseStageKind cheese_stage_kind(ProgramType type)"
PH_SIGNATURE = "inline CheesePhStageResult cheese_ph_stage_result("
LUA_WAIT_SIGNATURE = (
    "inline bool cheese_lua_result_pending(LuaBeerJobResult result)"
)
DOSER_DONE_SIGNATURE = "inline bool cheese_doser_motion_complete("
CALIBRATE_SIGNATURE = "inline float cheese_calibrated_ph("
SAMPLE_SIGNATURE = "inline void cheese_sample_ph(unsigned long nowMs)"
PH_TICK_SIGNATURE = "inline void cheese_ph_tick()"
PROGRAM_IO = ROOT / "program_io.h"

HARNESS = r'''
#include <cstdint>
#include <cmath>
#include <iostream>

using std::isfinite;

#define CHEESE_PH_SAMPLE_INTERVAL_MS 1000UL
#define CHEESE_PH_STALE_MS 5000UL
#define LUA_PIN 34

using ProgramType = char;

enum SAMOVAR_MODE : uint8_t {
  SAMOVAR_BEER_MODE = 6,
  SAMOVAR_CHEESE_MODE = 7,
};

enum LuaBeerJobResult : uint8_t {
  LUA_BEER_JOB_IDLE = 0,
  LUA_BEER_JOB_QUEUED,
  LUA_BEER_JOB_RUNNING,
  LUA_BEER_JOB_SUCCEEDED,
  LUA_BEER_JOB_STOPPED,
  LUA_BEER_JOB_FAILED_INIT,
  LUA_BEER_JOB_FAILED_RUNTIME,
  LUA_BEER_JOB_FAILED_TIMEOUT,
  LUA_BEER_JOB_LOCK_BUSY,
};

enum CheeseStageKind : uint8_t {
  CHEESE_STAGE_INVALID = 0,
  CHEESE_STAGE_HEAT_TO_TARGET,
  CHEESE_STAGE_TIMED_HOLD,
  CHEESE_STAGE_COOL,
  CHEESE_STAGE_MANUAL_WAIT,
  CHEESE_STAGE_AUTOTUNE,
  CHEESE_STAGE_LUA,
  CHEESE_STAGE_PH,
  CHEESE_STAGE_DRAIN,
};

enum CheesePhStageResult : uint8_t {
  CHEESE_PH_WAIT = 0,
  CHEESE_PH_REACHED,
  CHEESE_PH_INVALID,
  CHEESE_PH_TIMEOUT,
};

struct SetupEEPROM {
  float CheesePhSlope = 1.0f;
  float CheesePhOffset = 0.0f;
  uint8_t CheesePhSmoothPercent = 0;
};

static SetupEEPROM SamSetup;
static int cheesePhRaw = 0;
static float cheesePhValue = 0.0f;
static bool cheesePhValid = false;
static unsigned long cheesePhSampleMs = 0;
static int fakeRaw = 0;
static unsigned long fakeMillis = 0;
static SAMOVAR_MODE Samovar_Mode = SAMOVAR_BEER_MODE;

static int analogRead(int) { return fakeRaw; }
static unsigned long millis() { return fakeMillis; }

template <typename T>
static T constrain(T value, T low, T high) {
  return value < low ? low : value > high ? high : value;
}

inline CheeseStageKind cheese_stage_kind(ProgramType type) {
@CLASSIFY@
}

inline CheesePhStageResult cheese_ph_stage_result(
    bool valid, bool fresh, float value, float target, bool timedOut) {
@PH@
}

inline bool cheese_lua_result_pending(LuaBeerJobResult result) {
@LUA_WAIT@
}

inline bool cheese_doser_motion_complete(
    bool started, bool moving, int32_t current, int32_t target) {
@DOSER_DONE@
}

inline float cheese_calibrated_ph(int raw, float slope, float offset) {
@CALIBRATE@
}

inline int cheese_ph_raw() {
@PH_RAW_GETTER@
}

inline float cheese_ph_value() {
@PH_VALUE_GETTER@
}

inline bool cheese_ph_valid() {
@PH_VALID_GETTER@
}

inline void cheese_sample_ph(unsigned long nowMs) {
@SAMPLE@
}

inline void cheese_ph_tick() {
@PH_TICK@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    failures++;
  }
}

int main() {
  check(cheese_stage_kind('M') == CHEESE_STAGE_HEAT_TO_TARGET,
        "M stage classification changed");
  const ProgramType timed[] = {'P', 'Z', 'f', 'z', 'd', 's', 'p', 'v', 'r'};
  for (ProgramType type : timed) {
    check(cheese_stage_kind(type) == CHEESE_STAGE_TIMED_HOLD,
          "timed cheese stage classification changed");
  }
  check(cheese_stage_kind('C') == CHEESE_STAGE_COOL,
        "C stage classification changed");
  check(cheese_stage_kind('W') == CHEESE_STAGE_MANUAL_WAIT,
        "W stage classification changed");
  check(cheese_stage_kind('R') == CHEESE_STAGE_MANUAL_WAIT,
        "R stage classification changed");
  check(cheese_stage_kind('A') == CHEESE_STAGE_AUTOTUNE,
        "A stage classification changed");
  check(cheese_stage_kind('L') == CHEESE_STAGE_LUA,
        "L stage classification changed");
  check(cheese_stage_kind('n') == CHEESE_STAGE_PH,
        "n stage classification changed");
  check(cheese_stage_kind('S') == CHEESE_STAGE_DRAIN,
        "S stage classification changed");
  check(cheese_stage_kind('B') == CHEESE_STAGE_INVALID,
        "unsupported cheese stage was accepted");

  check(cheese_ph_stage_result(false, true, 5.1f, 5.2f, false) ==
            CHEESE_PH_INVALID,
        "invalid pH sample did not fail n stage");
  check(cheese_ph_stage_result(true, false, 5.1f, 5.2f, false) ==
            CHEESE_PH_INVALID,
        "stale pH sample did not fail n stage");
  check(cheese_ph_stage_result(true, true, 5.20f, 5.20f, false) ==
            CHEESE_PH_REACHED,
        "equal pH target did not complete n stage");
  check(cheese_ph_stage_result(true, true, 4.75f, 4.80f, false) ==
            CHEESE_PH_REACHED,
        "lower second pH value did not complete n stage");
  check(cheese_ph_stage_result(true, true, 5.21f, 5.20f, false) ==
            CHEESE_PH_WAIT,
        "pH above target completed n stage");
  check(cheese_ph_stage_result(true, true, 5.21f, 5.20f, true) ==
            CHEESE_PH_TIMEOUT,
        "n timeout did not fail explicitly");
  check(cheese_ph_stage_result(true, true, 5.20f, 5.20f, true) ==
            CHEESE_PH_REACHED,
        "pH success at deadline lost to timeout");

  check(cheese_lua_result_pending(LUA_BEER_JOB_QUEUED),
        "queued Lua job did not hold L stage");
  check(cheese_lua_result_pending(LUA_BEER_JOB_RUNNING),
        "running Lua job did not hold L stage");
  check(cheese_lua_result_pending(LUA_BEER_JOB_LOCK_BUSY),
        "transient Lua lock did not hold L stage");
  check(!cheese_lua_result_pending(LUA_BEER_JOB_SUCCEEDED),
        "successful Lua job was treated as pending");
  check(!cheese_lua_result_pending(LUA_BEER_JOB_FAILED_RUNTIME),
        "failed Lua job was hidden as pending");

  check(!cheese_doser_motion_complete(false, false, 120, 120),
        "never-started doser completed");
  check(!cheese_doser_motion_complete(true, true, 120, 120),
        "moving doser completed");
  check(!cheese_doser_motion_complete(true, false, 119, 120),
        "short doser movement completed");
  check(cheese_doser_motion_complete(true, false, 120, 120),
        "exact first dose did not complete");
  check(cheese_doser_motion_complete(true, false, 321, 320),
        "completed second dose did not complete");

  check(cheese_calibrated_ph(1000, -0.003f, 8.0f) == 5.0f,
        "first raw pH calibration changed");
  check(cheese_calibrated_ph(500, 0.01f, 1.0f) == 6.0f,
        "second raw pH calibration changed");

  SamSetup.CheesePhSlope = -0.003f;
  SamSetup.CheesePhOffset = 8.0f;
  fakeRaw = 1000;
  fakeMillis = 1000;
  cheese_sample_ph(1000);
  check(cheese_ph_raw() == 1000, "first raw pH sample was not retained");
  check(cheese_ph_value() == 5.0f && cheese_ph_valid(),
        "first raw pH sample was not calibrated");
  SamSetup.CheesePhSlope = 0.01f;
  SamSetup.CheesePhOffset = 1.0f;
  fakeRaw = 500;
  fakeMillis = 2000;
  cheese_sample_ph(2000);
  check(cheese_ph_raw() == 500, "second raw pH sample was not retained");
  check(cheese_ph_value() == 6.0f && cheese_ph_valid(),
        "second raw pH sample was not calibrated");

  fakeRaw = 700;
  fakeMillis = 3000;
  cheese_ph_tick();
  check(cheese_ph_raw() == 500,
        "idle non-cheese mode sampled the pH input");
  Samovar_Mode = SAMOVAR_CHEESE_MODE;
  cheese_ph_tick();
  check(cheese_ph_raw() == 700,
        "active cheese mode did not sample the pH input");
  check(cheese_ph_value() == 8.0f && cheese_ph_valid(),
        "cheese pH tick did not publish calibrated live pH");
  fakeMillis = 8001;
  check(!cheese_ph_valid(), "stale live pH remained valid after five seconds");

  if (failures != 0) return 1;
  std::cout << "Cheese runtime decision checks passed\n";
  return 0;
}
'''

VALIDATION_HARNESS = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

using ProgramType = char;
static constexpr uint8_t PROGRAM_END = 20;

class String {
 public:
  String() = default;
  String(const char* text) : value(text ? text : "") {}
  String(unsigned value) : value(std::to_string(value)) {}
  String operator+(const char* rhs) const { return String((value + rhs).c_str()); }
  String operator+(const String& rhs) const {
    return String((value + rhs.value).c_str());
  }
  String& operator=(const char* rhs) {
    value = rhs;
    return *this;
  }
  std::string value;
};

static String operator+(const char* lhs, const String& rhs) {
  return String((std::string(lhs) + rhs.value).c_str());
}

struct WProgram {
  ProgramType WType = 0;
  float Temp = 1.0f;
  float Time = 1.0f;
  uint8_t capacity_num = 0;
  float Speed = 0.0f;
  uint16_t Volume = 0;
  float Power = 0.0f;
  uint8_t TempSensor = 0;
  float Param = 0.0f;
};

struct SetupEEPROM {
  uint16_t CheeseDoserSpeed = 100;
  uint32_t CheeseDoserSteps = 200;
};

struct DSSensor {};
struct ProgramParseSpec { const char* allowedTypes; };

static WProgram program[PROGRAM_END];
static uint8_t ProgramLen = 0;
static SetupEEPROM SamSetup;
static int semanticCalls = 0;
static int sensorCalls = 0;

static bool program_type_empty(ProgramType type) { return type == 0; }
static bool program_type_one_of(ProgramType type, const char* allowed) {
  return std::strchr(allowed, type) != nullptr;
}
static const ProgramParseSpec& cheese_program_parse_spec() {
  static const ProgramParseSpec spec{"MPCWALZfzdspvrnSR"};
  return spec;
}
static bool program_validate_cheese_row_semantics(
    ProgramType, float temp, float, long, long, long, long, long, float,
    const char*& error) {
  semanticCalls++;
  if (temp >= 0.0f) return true;
  error = "semantic failure";
  return false;
}
static bool beer_control_sensor(
    uint8_t sensorId, const DSSensor*& sensor, const char*& sensorName) {
  static DSSensor selected;
  sensorCalls++;
  sensor = &selected;
  sensorName = "sensor";
  return sensorId <= 4;
}

inline bool cheese_doser_stage(ProgramType type) {
@DOSER_STAGE@
}

inline bool cheese_validate_program(String& error) {
@VALIDATE@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    failures++;
  }
}

static void valid_row(uint8_t index, ProgramType type, uint8_t sensor = 0) {
  program[index] = WProgram{};
  program[index].WType = type;
  program[index].TempSensor = sensor;
}

int main() {
  String error;
  ProgramLen = 3;
  valid_row(0, 'M');
  valid_row(1, 'P');
  valid_row(2, 'C', 4);
  check(cheese_validate_program(error), "valid multi-row program was rejected");
  check(semanticCalls == 3 && sensorCalls == 3,
        "validation did not visit every program row");

  semanticCalls = sensorCalls = 0;
  program[2].Temp = -1.0f;
  check(!cheese_validate_program(error),
        "semantic failure in later row was accepted");
  check(semanticCalls == 3, "later-row semantics were not evaluated");

  program[2].Temp = 1.0f;
  program[2].TempSensor = 5;
  semanticCalls = sensorCalls = 0;
  check(!cheese_validate_program(error),
        "invalid later-row temperature sensor was accepted");
  check(sensorCalls == 3, "later-row temperature sensor was not evaluated");

  program[2].TempSensor = 0;
  program[1].WType = 0;
  check(!cheese_validate_program(error), "empty row inside ProgramLen was accepted");

  valid_row(1, 'Z');
  SamSetup.CheeseDoserSpeed = 0;
  check(!cheese_validate_program(error),
        "doser row with zero configured speed was accepted");

  if (failures != 0) return 1;
  std::cout << "Cheese full-program validation checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    bodies = {
        "@CLASSIFY@": extract_function_body(source, CLASSIFY_SIGNATURE),
        "@PH@": extract_function_body(source, PH_SIGNATURE),
        "@LUA_WAIT@": extract_function_body(source, LUA_WAIT_SIGNATURE),
        "@DOSER_DONE@": extract_function_body(source, DOSER_DONE_SIGNATURE),
        "@CALIBRATE@": extract_function_body(source, CALIBRATE_SIGNATURE),
        "@PH_RAW_GETTER@": extract_function_body(
            source, "inline int cheese_ph_raw()"
        ),
        "@PH_VALUE_GETTER@": extract_function_body(
            source, "inline float cheese_ph_value()"
        ),
        "@PH_VALID_GETTER@": extract_function_body(
            source, "inline bool cheese_ph_valid()"
        ),
        "@SAMPLE@": extract_function_body(source, SAMPLE_SIGNATURE),
        "@PH_TICK@": extract_function_body(source, PH_TICK_SIGNATURE),
    }
    harness = HARNESS
    for marker, body in bodies.items():
        harness = harness.replace(marker, body)
    return harness


def build_validation_harness(source: str) -> str:
    return (
        VALIDATION_HARNESS.replace(
            "@DOSER_STAGE@",
            extract_function_body(
                source, "inline bool cheese_doser_stage(ProgramType type)"
            ),
        ).replace(
            "@VALIDATE@",
            extract_function_body(
                source, "inline bool cheese_validate_program(String& error)"
            ),
        )
    )


def compile_and_run(
    source: str, label: str, show_failure: bool = True
) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-runtime-") as tmp_dir:
        tmp = Path(tmp_dir)
        cpp = tmp / "cheese_runtime.cpp"
        binary = tmp / "cheese_runtime"
        cpp.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                str(cpp), "-o", str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            output = compile_result.stdout + compile_result.stderr
            if show_failure:
                print(f"FAIL: {label} compile failed\n{output}", file=sys.stderr)
            return compile_result.returncode, output
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        output = run_result.stdout + run_result.stderr
        if show_failure and run_result.returncode != 0:
            print(f"FAIL: {label} execution failed\n{output}", file=sys.stderr)
        return run_result.returncode, output


def mutation_must_fail(
    harness: str, old: str, new: str, label: str, expected: str
) -> bool:
    mutant = harness.replace(old, new, 1)
    if mutant == harness:
        print(f"FAIL: mutation anchor missing: {label}", file=sys.stderr)
        return False
    returncode, output = compile_and_run(mutant, label, show_failure=False)
    if returncode == 0:
        print(f"FAIL: mutation survived: {label}", file=sys.stderr)
        return False
    if expected not in output:
        print(f"FAIL: mutation failed for wrong reason: {label}\n{output}", file=sys.stderr)
        return False
    return True


def main() -> int:
    if not CHEESE.exists():
        print("FAIL: cheese.h is missing", file=sys.stderr)
        return 1
    source = CHEESE.read_text(encoding="utf-8")
    program_io_source = PROGRAM_IO.read_text(encoding="utf-8")
    try:
        harness = build_harness(source)
        validation_harness = build_validation_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    errors: list[str] = []
    for label, signature, tokens in [
        (
            "run_cheese_program L cleanup",
            "void run_cheese_program(uint8_t num) {",
            [
                "cheese_request_lua_exit(targetProgram)",
                "return;",
                "cheese_prepare_stage(targetProgram)",
            ],
        ),
        (
            "cheese S runtime",
            "void cheese_stage_tick() {",
            [
                "case CHEESE_STAGE_DRAIN:",
                "cheese_set_drain(true)",
                "cheese_set_drain(false)",
            ],
        ),
        (
            "cheese R/W runtime",
            "void cheese_stage_tick() {",
            [
                "case CHEESE_STAGE_MANUAL_WAIT:",
                "cheese_apply_safe_outputs(true)",
            ],
        ),
        (
            "cheese finish cleanup",
            "void cheese_finish() {",
            [
                "cheeseFinishPending = true;",
                "cheese_apply_safe_outputs(true)",
                "cheese_finish_lua_exit()",
                "stop_process(",
            ],
        ),
        (
            "cheese doser once",
            "inline bool cheese_tick_doser_stage(unsigned long nowMs)",
            [
                "if (!cheeseDoserStarted)",
                "cheese_start_doser()",
                "cheese_doser_motion_complete(",
                "cheeseDoserCompleted = true;",
                "begintime = nowMs;",
            ],
        ),
        (
            "cheese pH sampling",
            "inline void cheese_sample_ph(unsigned long nowMs)",
            [
                "const int raw = analogRead(LUA_PIN);",
                "cheesePhRaw = raw;",
                "cheese_calibrated_ph(",
                "cheesePhSampleMs = nowMs;",
                "cheesePhValid = true;",
            ],
        ),
        (
            "cheese live pH tick",
            "inline void cheese_ph_tick()",
            [
                "Samovar_Mode == SAMOVAR_CHEESE_MODE",
                "cheese_sample_ph(millis())",
            ],
        ),
        (
            "cheese n-stage pH tick",
            "void cheese_stage_tick() {",
            [
                "case CHEESE_STAGE_PH:",
                "cheese_ph_tick();",
                "cheese_ph_stage_result(",
            ],
        ),
        (
            "cheese full-program validation",
            "inline bool cheese_validate_program(String& error)",
            [
                "ProgramLen == 0 || ProgramLen > PROGRAM_END",
                "for (uint8_t i = 0; i < ProgramLen; i++)",
                "cheese_program_parse_spec().allowedTypes",
                "program_validate_cheese_row_semantics(",
                "beer_control_sensor(row.TempSensor",
            ],
        ),
    ]:
        try:
            body = extract_function_body(source, signature, strip_comments=False)
            require_ordered_tokens(label, body, tokens, errors)
        except ValueError as error:
            errors.append(str(error))
    try:
        parser_body = extract_function_body(
            program_io_source,
            "inline bool program_parse_cheese_row(",
            strip_comments=False,
        )
        require_ordered_tokens(
            "cheese row semantics before runtime",
            parser_body,
            [
                "parse_bounded_long(tokSensor, 0, 4, sensor)",
                "program_validate_cheese_row_semantics(",
                "row.TempSensor = (uint8_t)sensor;",
            ],
            errors,
        )
    except ValueError as error:
        errors.append(str(error))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    returncode, output = compile_and_run(harness, "cheese runtime")
    if returncode != 0:
        return 1
    sys.stdout.write(output)

    returncode, output = compile_and_run(
        validation_harness, "cheese full-program validation"
    )
    if returncode != 0:
        return 1
    sys.stdout.write(output)

    mutations = [
        (
            "case 'L': return CHEESE_STAGE_LUA;",
            "case 'L': return CHEESE_STAGE_INVALID;",
            "L classification",
            "L stage classification changed",
        ),
        (
            "case 'n': return CHEESE_STAGE_PH;",
            "case 'n': return CHEESE_STAGE_TIMED_HOLD;",
            "n classification",
            "n stage classification changed",
        ),
        (
            "case 'S': return CHEESE_STAGE_DRAIN;",
            "case 'S': return CHEESE_STAGE_MANUAL_WAIT;",
            "S classification",
            "S stage classification changed",
        ),
        (
            "case 'R': return CHEESE_STAGE_MANUAL_WAIT;",
            "case 'R': return CHEESE_STAGE_TIMED_HOLD;",
            "R classification",
            "R stage classification changed",
        ),
        (
            "if (value <= target) return CHEESE_PH_REACHED;",
            "if (value < target) return CHEESE_PH_REACHED;",
            "pH inclusive target",
            "equal pH target did not complete n stage",
        ),
        (
            "result == LUA_BEER_JOB_LOCK_BUSY",
            "false",
            "Lua lock wait",
            "transient Lua lock did not hold L stage",
        ),
        (
            "current >= target",
            "current > target",
            "doser exact completion",
            "exact first dose did not complete",
        ),
        (
            "return slope * raw + offset;",
            "return slope * raw - offset;",
            "pH two-point calibration",
            "first raw pH calibration changed",
        ),
        (
            "cheesePhRaw = raw;",
            "cheesePhRaw = 0;",
            "pH raw retention",
            "first raw pH sample was not retained",
        ),
        (
            "millis() - cheesePhSampleMs <= CHEESE_PH_STALE_MS",
            "true",
            "stale pH getter",
            "stale live pH remained valid after five seconds",
        ),
        (
            "Samovar_Mode == SAMOVAR_CHEESE_MODE",
            "Samovar_Mode != SAMOVAR_CHEESE_MODE",
            "idle cheese pH gate",
            "idle non-cheese mode sampled the pH input",
        ),
    ]
    for old, new, label, expected in mutations:
        if not mutation_must_fail(harness, old, new, label, expected):
            return 1
    validation_mutations = [
        (
            "i < ProgramLen",
            "i < 1",
            "all cheese rows",
            "semantic failure in later row was accepted",
        ),
        (
            "if (!program_validate_cheese_row_semantics(",
            "if (false && !program_validate_cheese_row_semantics(",
            "cheese semantic validation",
            "semantic failure in later row was accepted",
        ),
        (
            "if (!beer_control_sensor(row.TempSensor, rowSensor, rowSensorName))",
            "if (false && !beer_control_sensor(row.TempSensor, rowSensor, rowSensorName))",
            "cheese temperature sensor validation",
            "invalid later-row temperature sensor was accepted",
        ),
    ]
    for old, new, label, expected in validation_mutations:
        if not mutation_must_fail(
            validation_harness, old, new, label, expected
        ):
            return 1
    print("Cheese runtime mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
