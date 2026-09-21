#!/usr/bin/env python3
"""Source-derived startup and telemetry contract for the Cheese integration."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
CHEESE = (ROOT / "cheese.h").read_text(encoding="utf-8")
SAMOVAR = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
SAMOVAR_INI = (ROOT / "Samovar_ini.h").read_text(encoding="utf-8")


def body(signature: str) -> str:
    return extract_function_body(CHEESE, signature, strip_comments=False)


HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>

typedef char ProgramType;
enum CheeseStageKind : uint8_t {
  CHEESE_STAGE_INVALID = 0, CHEESE_STAGE_HEAT, CHEESE_STAGE_HOLD,
  CHEESE_STAGE_COOL, CHEESE_STAGE_MIX, CHEESE_STAGE_DOSE, CHEESE_STAGE_PH,
  CHEESE_STAGE_WAIT, CHEESE_STAGE_DRAIN, CHEESE_STAGE_LUA, CHEESE_STAGE_FLOC,
};
struct WProgram { ProgramType WType; float Time; float Param; };
struct CheeseRuntimeState { uint32_t enteredMs; uint32_t holdAccumulatedMs; } cheeseRuntime = {};
static WProgram program[20] = {};
static uint8_t ProgramNum = 0, ProgramLen = 1;
static const uint8_t PROGRAM_END = 20;
static const int SAMOVAR_CHEESE_MODE = 7;
static const int SAMOVAR_STATUS_CHEESE = 7000;
static const int SAMOVAR_STARTVAL_CHEESE_START = 7100;
static int Samovar_Mode = SAMOVAR_CHEESE_MODE;
static int SamovarStatusInt = SAMOVAR_STATUS_CHEESE;
static int startval = SAMOVAR_STARTVAL_CHEESE_START + 1;
static bool PowerOn = true, cheeseFinishPending = false;
static uint32_t fakeMs = 0;
uint32_t millis() { return fakeMs; }

inline CheeseStageKind cheese_stage_kind(ProgramType type) { @KIND@ }
inline float cheese_stage_timeout_minutes(const WProgram& row) { @TIMEOUT@ }
inline bool cheese_runtime_active() { @ACTIVE@ }
inline uint32_t cheese_stage_elapsed_ms() { @ELAPSED_MS@ }
inline uint32_t cheese_work_seconds() { @WORK@ }
inline uint32_t cheese_timeout_remaining_seconds() { @REMAINING@ }

static int failures = 0;
static void check(bool value, const char* text) {
  if (!value) { std::cerr << "FAIL: " << text << '\n'; ++failures; }
}

int main() {
  program[0] = {'H', 30.0f, 0.0f};
  cheeseRuntime.enteredMs = 0;
  fakeMs = 75000;
  check(cheese_work_seconds() == 75, "Cheese work seconds are wrong");
  check(cheese_timeout_remaining_seconds() == 1725,
        "H timeout remaining seconds are wrong");
  program[0] = {'P', 30.0f, 60.0f};
  cheeseRuntime.holdAccumulatedMs = 20000;
  check(cheese_work_seconds() == 20,
        "P work time must count only completed in-band hold");
  fakeMs = 120000;
  check(cheese_work_seconds() == 20,
        "P work time increased while temperature was outside the band");
  cheeseRuntime.holdAccumulatedMs = 25000;
  check(cheese_work_seconds() == 25,
        "P work time did not resume after returning to the band");
  fakeMs = 75000;
  check(cheese_timeout_remaining_seconds() == 3525,
        "P timeout must use the common timeout, not hold duration");
  program[0] = {'H', 30.0f, 0.0f};
  cheeseRuntime.enteredMs = 0xfffffff0UL;
  fakeMs = 984;
  check(cheese_work_seconds() == 1,
        "non-P work time is not safe across millis rollover");
  PowerOn = false;
  check(cheese_work_seconds() == 0 && cheese_timeout_remaining_seconds() == 0,
        "inactive Cheese must publish zero counters");
  return failures;
}
'''


PREFLIGHT_HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <climits>
#include <cstring>
#include <iostream>
#include <string>
@USE_LUA@
using std::isfinite;

class String {
 public:
  String(const char* text = "") : value_(text) {}
  String(uint8_t number) : value_(std::to_string(number)) {}
  String operator+(const char* text) const { return String(value_ + text); }
  String operator+(const String& text) const { return String(value_ + text.value_); }
  friend String operator+(const char* text, const String& value) {
    return String(std::string(text) + value.value_);
  }
 private:
  explicit String(const std::string& text) : value_(text) {}
  std::string value_;
};

typedef char ProgramType;
enum CheeseStageKind : uint8_t {
  CHEESE_STAGE_INVALID = 0, CHEESE_STAGE_HEAT, CHEESE_STAGE_HOLD,
  CHEESE_STAGE_COOL, CHEESE_STAGE_MIX, CHEESE_STAGE_DOSE, CHEESE_STAGE_PH,
  CHEESE_STAGE_WAIT, CHEESE_STAGE_DRAIN, CHEESE_STAGE_LUA, CHEESE_STAGE_FLOC,
};
struct WProgram {
  ProgramType WType; uint16_t Volume; float Speed; uint8_t capacity_num;
  float Temp; float Power; uint8_t TempSensor; float Time;
  float Param;
};
#define CHEESE_DOSER_STEP_SPEED 3200
struct DSSensor {};
struct Setup { uint16_t StepperStepMl; float CheesePhSlope; float CheesePhOffset; };
static Setup SamSetup = {4, 1.0f, 0.0f};
static WProgram program[20] = {};
static uint8_t ProgramLen = 1;
static const uint8_t PROGRAM_END = 20;
static bool i2cPresent = true, sensorPresent = true;
#ifdef USE_LUA
static bool luaPresent = true;
#endif

bool program_validate_cheese_row_semantics(
    ProgramType, float, float, long, long, long, long, long, float,
    const char*& error) { error = "semantic"; return true; }
uint32_t program_load_cheese_f_multiplier(const WProgram&) { return UINT32_MAX; }
uint32_t program_load_cheese_doser_steps(const WProgram& row) { uint32_t steps = 0; std::memcpy(&steps, &row.Param, sizeof(steps)); return steps; }
void program_store_cheese_doser_steps(WProgram& row, uint32_t steps) { std::memcpy(&row.Param, &steps, sizeof(steps)); }
bool beer_control_sensor(uint8_t, const DSSensor*& sensor, const char*&) {
  static DSSensor value;
  sensor = &value;
  return sensorPresent;
}
bool i2c_stepper_mixer_present() { return i2cPresent; }
// Как в I2CStepper.h: без подключённого откалиброванного насоса шагов и скорости нет.
#define I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC 20000
static uint16_t i2cPumpStepsPerMl = 0;
uint32_t i2c_get_step_by_liquid_volume(float ml) { return static_cast<uint32_t>(ml * i2cPumpStepsPerMl); }
float i2c_get_speed_from_rate(float litersPerHour) { return roundf(litersPerHour * 1000.0f * i2cPumpStepsPerMl / 3600.0f); }
#ifdef USE_LUA
bool exists(String) { return luaPresent; }
#endif

inline CheeseStageKind cheese_stage_kind(ProgramType type) { @KIND@ }
inline bool cheese_row_needs_sensor(CheeseStageKind kind) { @NEEDS_SENSOR@ }
inline bool cheese_local_doser_motion(const WProgram& row,
                                      uint32_t& targetSteps, float& speed) { @DOSER_MOTION@ }
inline bool cheese_i2c_doser_motion(const WProgram& row,
                                    uint32_t& targetSteps, float& rateLitersPerHour) { @I2C_DOSER_MOTION@ }
inline bool cheese_mixer_is_i2c(uint8_t device) { @IS_I2C@ }
inline bool cheese_validate_program(String& error) { @VALIDATE@ }

static int failures = 0;
static void check(bool value, const char* text) {
  if (!value) { std::cerr << "FAIL: " << text << '\n'; ++failures; }
}
static void reset(ProgramType type) {
  program[0] = {type, 0, 0.0f, 0, 2.5f, 0.0f, 0, 30.0f, 60.0f};
  SamSetup = {4, 1.0f, 0.0f};
  i2cPresent = sensorPresent = true;
#ifdef USE_LUA
  luaPresent = true;
#endif
}

int main() {
  String error;
  reset('M'); program[0].capacity_num = 2; program[0].Speed = 100.0f;
  i2cPresent = false;
  check(!cheese_validate_program(error), "I2C mixer absence passed preflight");
  i2cPresent = true;
  check(cheese_validate_program(error), "available I2C mixer failed preflight");
  program[0].capacity_num = 3; i2cPresent = false;
  check(!cheese_validate_program(error), "reversing I2C mixer absence passed preflight");
  i2cPresent = true;
  check(cheese_validate_program(error), "available reversing I2C mixer failed preflight");

  reset('D'); program[0].TempSensor = 4; program[0].Temp = 10.0f; program[0].Param = 30.0f;
  SamSetup.StepperStepMl = 4; i2cPumpStepsPerMl = 0;
  check(!cheese_validate_program(error),
        "I2C pump D without a connected calibrated pump passed preflight");
  i2cPumpStepsPerMl = 400; SamSetup.StepperStepMl = 0;
  check(cheese_validate_program(error), "valid I2C pump D failed preflight");

  reset('D'); program[0].TempSensor = 2;
  SamSetup.StepperStepMl = 0;
  check(!cheese_validate_program(error), "uncalibrated local D passed preflight");
  SamSetup.StepperStepMl = 4;
  check(cheese_validate_program(error), "valid local D failed preflight");
  program[0].Temp = 65535.0f; program[0].Param = 1440.0f;
  SamSetup.StepperStepMl = 65535;
  check(!cheese_validate_program(error), "overflowing local D conversion passed preflight");
  reset('D'); program[0].TempSensor = 3; program[0].Temp = 0.0f;
  program_store_cheese_doser_steps(program[0], 20000000UL); SamSetup.StepperStepMl = 0;
  check(cheese_validate_program(error), "valid direct-step D failed preflight");
  program_store_cheese_doser_steps(program[0], 0);
  check(!cheese_validate_program(error), "zero direct-step D passed preflight");

  reset('L');
#ifdef USE_LUA
  luaPresent = false;
  check(!cheese_validate_program(error), "missing /cheese.lua passed preflight");
  luaPresent = true;
  check(cheese_validate_program(error), "present /cheese.lua failed preflight");
#else
  check(!cheese_validate_program(error), "Lua stage passed preflight without USE_LUA");
#endif
  return failures;
}
'''


def build(timeout_body: str) -> str:
    values = {
        "@KIND@": body("inline CheeseStageKind cheese_stage_kind(ProgramType type)"),
        "@TIMEOUT@": timeout_body,
        "@ACTIVE@": body("inline bool cheese_runtime_active()"),
        "@ELAPSED_MS@": body("inline uint32_t cheese_stage_elapsed_ms()"),
        "@WORK@": body("inline uint32_t cheese_work_seconds()"),
        "@REMAINING@": body("inline uint32_t cheese_timeout_remaining_seconds()"),
    }
    result = HARNESS
    for marker, value in values.items():
        result = result.replace(marker, value)
    return result


def build_preflight(validate_body: str, use_lua: bool) -> str:
    values = {
        "@USE_LUA@": "#define USE_LUA" if use_lua else "",
        "@KIND@": body("inline CheeseStageKind cheese_stage_kind(ProgramType type)"),
        "@NEEDS_SENSOR@": body("inline bool cheese_row_needs_sensor(CheeseStageKind kind)"),
        "@DOSER_MOTION@": body("inline bool cheese_local_doser_motion(const WProgram& row,"),
        "@I2C_DOSER_MOTION@": body("inline bool cheese_i2c_doser_motion(const WProgram& row,"),
        "@IS_I2C@": body("inline bool cheese_mixer_is_i2c(uint8_t device)"),
        "@VALIDATE@": validate_body,
    }
    result = PREFLIGHT_HARNESS
    for marker, value in values.items():
        result = result.replace(marker, value)
    return result


def run(source: str, label: str, expect_success: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-integration-") as temp_dir:
        temp = Path(temp_dir)
        cpp, binary = temp / "test.cpp", temp / "test"
        cpp.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            raise AssertionError(f"{label}: compile failed\n{compiled.stderr}")
        completed = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if (completed.returncode == 0) != expect_success:
            raise AssertionError(f"{label}: {completed.stdout}{completed.stderr}")


def static_checks() -> list[str]:
    errors: list[str] = []
    if "#define CHEESE_DOSER_STEP_SPEED 8000" not in SAMOVAR_INI:
        errors.append("Samovar_ini.h has no direct-step Cheese doser speed")
    cheese_proc = extract_function_body(CHEESE, "void cheese_proc()")
    require_ordered_tokens(
        "Cheese preflight/session start order",
        cheese_proc,
        [
            "i2c_stepper_session_begin()",
            "cheese_validate_program(programError)",
            "power_transition_active() || heater_safety_latched()",
            "create_data()",
            "copy_start_session_description(sessionDescription, pdMS_TO_TICKS(50))",
            "session_begin(sessionDescription)",
            "set_power(true)",
            "run_cheese_program(0)",
        ],
        errors,
    )
    if cheese_proc.count("session_begin(sessionDescription)") != 1:
        errors.append("Cheese start must call session_begin exactly once")

    validate = extract_function_body(CHEESE, "inline bool cheese_validate_program(String& error)")
    for token in ("for (uint8_t i = 0; i < ProgramLen; i++)", "i2c_stepper_mixer_present()",
                  "cheese_local_doser_motion(row, targetSteps, speed)",
                  "exists(\"/cheese.lua\")",
                  "row.WType == 'D' && row.TempSensor == 3 ? 0.0 : row.Param"):
        if token not in validate:
            errors.append(f"Cheese preflight is missing {token}")

    snapshot = strip_cpp_comments(SAMOVAR)
    for token in (
        "uint32_t cheeseWorkSeconds;",
        "uint32_t cheeseTimeoutRemainingSeconds;",
        "snapshot.cheeseWorkSeconds = cheese_work_seconds();",
        "snapshot.cheeseTimeoutRemainingSeconds = cheese_timeout_remaining_seconds();",
        '"CheeseWorkSeconds", snapshot.cheeseWorkSeconds',
        '"CheeseTimeoutRemainingSeconds", snapshot.cheeseTimeoutRemainingSeconds',
    ):
        if token not in snapshot:
            errors.append(f"Cheese AJAX snapshot is missing {token}")
    return errors


def main() -> int:
    errors = static_checks()
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    try:
        timeout_body = body("inline float cheese_stage_timeout_minutes(const WProgram& row)")
        run(build(timeout_body), "Cheese integration getters", True)
        mutant = timeout_body.replace(
            "CHEESE_STAGE_HOLD ? row.Param : row.Time", "row.Time", 1
        )
        if mutant == timeout_body:
            raise AssertionError("timeout mutation anchor is missing")
        run(build(mutant), "P common-timeout mutation", False)
        validate_body = body("inline bool cheese_validate_program(String& error)")
        run(build_preflight(validate_body, True), "Cheese preflight availability", True)
        for old, new, label in (
            ("cheese_mixer_is_i2c(row.capacity_num) && !i2c_stepper_mixer_present()", "false",
             "I2C mixer availability mutation"),
            ("cheese_mixer_is_i2c(row.capacity_num) && !i2c_stepper_mixer_present()",
             "row.capacity_num == 2 && !i2c_stepper_mixer_present()",
             "reversing I2C mixer availability mutation"),
            ("!cheese_i2c_doser_motion(row, targetSteps, rate)",
             "false && !cheese_i2c_doser_motion(row, targetSteps, rate)",
             "I2C pump D availability mutation"),
            ("kind == CHEESE_STAGE_DOSE && row.TempSensor == 4",
             "kind == CHEESE_STAGE_DOSE && row.TempSensor == 2",
             "I2C pump D method mutation"),
            ("!cheese_local_doser_motion(row, targetSteps, speed)",
             "false && !cheese_local_doser_motion(row, targetSteps, speed)",
             "local D conversion mutation"),
            ("!exists(\"/cheese.lua\")", "false", "Lua file availability mutation"),
        ):
            mutant = validate_body.replace(old, new, 1)
            if mutant == validate_body:
                raise AssertionError(f"{label} anchor is missing")
            run(build_preflight(mutant, True), label, False)
        run(build_preflight(validate_body, False), "Cheese no-Lua preflight", True)
        no_lua_mutant = validate_body.replace(
            'error = "Lua недоступна в этой сборке";\n      return false;',
            'error = "Lua недоступна в этой сборке";\n      return true;',
            1,
        )
        if no_lua_mutant == validate_body:
            raise AssertionError("no-Lua validation mutation anchor is missing")
        run(build_preflight(no_lua_mutant, False), "no-Lua preflight mutation", False)
    except (AssertionError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("Cheese integration startup, snapshot and telemetry contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
