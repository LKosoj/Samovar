#!/usr/bin/env python3
"""Поведенческий контракт повторной semantic-проверки beer перед стартом."""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
PROGRAM_IO = (ROOT / "program_io.h").read_text(encoding="utf-8")
BEER = (ROOT / "beer.h").read_text(encoding="utf-8")

SEMANTIC = extract_function_body(PROGRAM_IO, "inline bool program_validate_beer_row_semantics")
VALIDATE = extract_function_body(BEER, "inline bool beer_validate_program")

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

using ProgramType = char;
#define BitIsSet(reg, bit) ((reg & (1 << bit)) != 0)
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_END = 8;

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}
  String& operator=(const char* value) { value_ = value ? value : ""; return *this; }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  String operator+(const char* other) const { return String(value_ + (other ? other : "")); }
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};
String operator+(const char* left, const String& right) {
  return String(std::string(left ? left : "") + right.value());
}

struct WProgram {
  ProgramType WType;
  float Temp;
  float Time;
  uint8_t capacity_num;
  float Speed;
  float Param;
  uint16_t Volume;
  uint16_t Power;
  uint8_t TempSensor;
};
static WProgram program[PROGRAM_END];
static uint8_t ProgramLen = 0;

struct ParseSpec { const char* allowedTypes; };
const ParseSpec& beer_program_parse_spec() {
  static const ParseSpec spec = {"MPBCFWLA"};
  return spec;
}
bool program_type_empty(ProgramType type) { return type == PROGRAM_TYPE_NONE; }
bool program_type_one_of(ProgramType type, const char* allowed) {
  for (const char* cursor = allowed; *cursor; cursor++) if (*cursor == type) return true;
  return false;
}
struct DSSensor {};
bool beer_control_sensor(uint8_t sensor, const DSSensor*& out, const char*& name) {
  static DSSensor value;
  if (sensor > 4) return false;
  out = &value;
  name = "test";
  return true;
}
static bool mixerPresent = false;
static bool pumpPresent = false;
static bool relayPresent = false;
bool i2c_stepper_mixer_present() { return mixerPresent; }
bool i2c_stepper_pump_present() { return pumpPresent; }
bool select_relay_capable_device() { return relayPresent; }

inline bool program_validate_beer_row_semantics(
    ProgramType type, float temp, float timeMin, long devType, long mixerRpm,
    long pumpMlHour, long onTime, long offTime, long sensor, const char*& errorMessage) {
@SEMANTIC@
}

inline bool beer_validate_program(String& errorMessage) {
@VALIDATE@
}

int failures = 0;
void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}
void reset() {
  for (auto& row : program) row = {};
  ProgramLen = 1;
  mixerPresent = false;
  pumpPresent = false;
  relayPresent = false;
}

int main() {
  String error;
  reset();
  program[0] = {'P', 65, 1, 0, 0, 0, 0, 0, 0};
  check(beer_validate_program(error), "valid P row rejected before start");

  reset();
  program[0] = {'P', 65, 1, 0, -100, 0, 2, 3, 0};
  check(!beer_validate_program(error), "stale P row with schedule and no device passed start validation");
  check(error.value().find("устройство") != std::string::npos,
        "start validation lost semantic error context");

  reset();
  program[0] = {'M', 0, 0, 0, 0, 0, 0, 0, 0};
  check(!beer_validate_program(error), "zero-temperature M row passed start validation");

  reset();
  program[0] = {'W', 0, 0, 1, -100, 0, 2, 0, 0};
  mixerPresent = true;
  check(beer_validate_program(error), "continuous W mixer schedule rejected before start");

  reset();
  program[0] = {'W', 0, 0, 1, -100, 0, 2, 0, 4};
  mixerPresent = true;
  check(beer_validate_program(error), "W row with sensor 4 rejected before start");

  reset();
  program[0] = {'W', 0, 0, 1, 100, 0, 2, 0, 0};
  check(!beer_validate_program(error), "I2C mixer row passed without a connected mixer");
  mixerPresent = true;
  check(beer_validate_program(error), "I2C mixer row was rejected with a connected mixer");

  reset();
  program[0] = {'W', 0, 0, 2, 0, 1200, 2, 0, 0};
  check(!beer_validate_program(error), "I2C pump row passed without a connected pump");
  pumpPresent = true;
  check(beer_validate_program(error), "I2C pump row was rejected with a connected pump");

  reset();
  program[0] = {'W', 0, 0, 3, 100, 0, 2, 0, 0};
  mixerPresent = true;
  check(!beer_validate_program(error), "relay pump row passed without a relay");
  relayPresent = true;
  check(beer_validate_program(error), "mixer and relay pump on one board were rejected");

  reset();
  program[0] = {'W', 0, 0, 2, 0, 0, 2, 0, 0};
  relayPresent = true;
  check(beer_validate_program(error), "relay pump without a mixer was rejected");

  reset();
  program[0] = {'W', 0, 0, 3, 0, 1200, 2, 0, 0};
  pumpPresent = true;
  check(!beer_validate_program(error), "relay mixer row passed without a relay");
  relayPresent = true;
  check(beer_validate_program(error), "relay mixer and stepper pump on one board were rejected");

  reset();
  program[0] = {'W', 0, 0, 3, 0, 0, 2, 0, 0};
  pumpPresent = true;
  relayPresent = true;
  check(!beer_validate_program(error), "mixer and pump both assigned to relay 1 passed");

  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(harness: str, label: str, show_output: bool = True) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-start-validation-") as temp_dir:
        source = Path(temp_dir) / "beer_start_validation.cpp"
        binary = Path(temp_dir) / "beer_start_validation"
        source.write_text(harness, encoding="utf-8")
        result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            if show_output:
                sys.stderr.write(f"[{label}] compile failed\n")
                sys.stderr.write(result.stderr)
            return result.returncode
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if show_output:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
        return result.returncode


def main() -> int:
    harness = HARNESS.replace("@SEMANTIC@", SEMANTIC).replace("@VALIDATE@", VALIDATE)
    if compile_and_run(harness, "production") != 0:
        return 1

    mutated_validate = VALIDATE.replace(
        "if (!program_validate_beer_row_semantics(",
        "if (false && !program_validate_beer_row_semantics(", 1,
    )
    mutation_harness = HARNESS.replace("@SEMANTIC@", SEMANTIC).replace(
        "@VALIDATE@", mutated_validate
    )
    if compile_and_run(mutation_harness, "semantic-recheck mutation", False) == 0:
        print("FAIL: start validation did not catch a removed semantic recheck", file=sys.stderr)
        return 1
    print("Beer start semantic recheck mutation was rejected as expected")

    mixer_mutation = VALIDATE.replace(
        "if (program[i].Speed != 0 && !i2c_stepper_mixer_present()) {",
        "if (false && program[i].Speed != 0 && !i2c_stepper_mixer_present()) {",
        1,
    )
    if mixer_mutation == VALIDATE:
        print("FAIL: could not build I2C mixer availability mutation", file=sys.stderr)
        return 1
    mixer_mutation_harness = HARNESS.replace("@SEMANTIC@", SEMANTIC).replace(
        "@VALIDATE@", mixer_mutation
    )
    if compile_and_run(mixer_mutation_harness, "I2C mixer availability mutation", False) == 0:
        print("FAIL: missing I2C mixer validation mutation survived", file=sys.stderr)
        return 1
    print("Beer I2C mixer availability mutation was rejected as expected")

    mutated_semantic = SEMANTIC.replace(
        "if (zeroTempTime) return true;",
        "if (zeroTempTime && sensor == 0) return true;",
        1,
    )
    if mutated_semantic == SEMANTIC:
        print("FAIL: could not build W sensor-range mutation", file=sys.stderr)
        return 1
    sensor_mutation_harness = HARNESS.replace(
        "@SEMANTIC@", mutated_semantic
    ).replace("@VALIDATE@", VALIDATE)
    if compile_and_run(sensor_mutation_harness, "W sensor mutation", False) == 0:
        print("FAIL: W sensor-range mutation survived start validation", file=sys.stderr)
        return 1
    print("Beer W sensor-range mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
