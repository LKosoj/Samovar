#!/usr/bin/env python3
"""[T02/F03] START второго I2C-насоса возможен только после подготовки."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "inline bool start_second_i2c_pump(float rateLitersPerHour, uint16_t volumeMl)"

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>

using std::round;

constexpr uint8_t I2CSTEPPER_PUMP_ADDR = 2;
constexpr uint8_t I2CSTEPPER_FLAG_DIRECTION = 0x01;
constexpr uint8_t I2CSTEP_MODE_FILLING = 3;
constexpr uint8_t I2CSTEP_MODE_PUMP = 4;
constexpr uint8_t I2CSTEP_CMD_START = 5;

struct Setup { uint16_t StepperStepMlI2C = 100; } SamSetup;
struct Device {
  uint16_t stepsPerMl = 0;
  uint8_t optionFlags = I2CSTEPPER_FLAG_DIRECTION;
  uint8_t mode = 0;
  uint16_t fillingMl = 0;
  uint16_t fillingMlHour = 0;
  uint16_t pumpMlHour = 0;
} i2cStepperPump;

static uint8_t use_I2C_dev = I2CSTEPPER_PUMP_ADDR;
static bool configBeginResult = true;
static bool writeConfigResult = true;
static bool confirmedResult = true;
static int configBeginCalls = 0;
static int writeConfigCalls = 0;
static int startCalls = 0;
static int configEndCalls = 0;

static bool i2c_stepper_config_begin(const Device&) {
  configBeginCalls++;
  return configBeginResult;
}
static void i2c_stepper_config_end(const Device&) { configEndCalls++; }
static bool i2c_stepper_write_config(Device&) {
  writeConfigCalls++;
  return writeConfigResult;
}
static bool i2c_stepper_send_confirmed_command(Device&, uint8_t command) {
  if (command == I2CSTEP_CMD_START) startCalls++;
  return confirmedResult;
}
static uint16_t i2c_stepper_steps_per_ml() { return SamSetup.StepperStepMlI2C; }

static bool start_second_i2c_pump(float rateLitersPerHour, uint16_t volumeMl) {
@BODY@
}

static int failures = 0;
static void check(bool value, const char* message) {
  if (!value) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static void reset_fixture() {
  use_I2C_dev = I2CSTEPPER_PUMP_ADDR;
  configBeginResult = true;
  writeConfigResult = true;
  confirmedResult = true;
  configBeginCalls = 0;
  writeConfigCalls = 0;
  startCalls = 0;
  configEndCalls = 0;
}
static void test_busy_owner_never_starts() {
  reset_fixture();
  configBeginResult = false;
  check(!start_second_i2c_pump(1.2f, 0), "занятый владелец должен вернуть false");
  check(startCalls == 0, "занятый владелец не должен посылать START");
  check(writeConfigCalls == 0, "занятый владелец не должен писать конфигурацию");
  check(configEndCalls == 0, "незахваченный владелец нельзя освобождать");
}
static void test_write_failure_releases_without_start() {
  reset_fixture();
  writeConfigResult = false;
  check(!start_second_i2c_pump(1.2f, 0), "ошибка записи должна вернуть false");
  check(startCalls == 0, "ошибка записи не должна посылать START");
  check(configEndCalls == 1, "после ошибки записи владелец освобождается ровно раз");
}
static void test_success_starts_once_and_releases() {
  reset_fixture();
  check(start_second_i2c_pump(1.2f, 25), "успешная подготовка и подтверждение должны вернуть true");
  check(startCalls == 1, "после успешной подготовки START посылается ровно раз");
  check(configEndCalls == 1, "после успеха владелец освобождается ровно раз");
}
static void test_confirmation_failure_is_not_success() {
  reset_fixture();
  confirmedResult = false;
  check(!start_second_i2c_pump(1.2f, 0), "отказ подтверждения START должен вернуть false");
  check(startCalls == 1, "отказ подтверждения происходит после одной попытки START");
  check(configEndCalls == 1, "после отказа подтверждения владелец освобождается");
}
int main() {
  test_busy_owner_never_starts();
  test_write_failure_releases_without_start();
  test_success_starts_once_and_releases();
  test_confirmation_failure_is_not_success();
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(body: str, name: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="samovar-t02-i2c-pump-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / f"{name}.cpp"
        binary = temp / name
        source.write_text(HARNESS.replace("@BODY@", body), encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            return compiled
        return subprocess.run([str(binary)], capture_output=True, text=True, check=False)


def require_mutant_fails(body: str, anchor: str, replacement: str, message: str) -> None:
    if body.count(anchor) != 1:
        raise AssertionError(f"мутационный якорь отсутствует: {anchor}")
    result = compile_and_run(body.replace(anchor, replacement, 1), "mutant")
    output = result.stdout + result.stderr
    if result.returncode == 0 or message not in output:
        raise AssertionError(f"мутант пережил проверку {message}: {output}")


def main() -> int:
    if shutil.which("g++") is None:
        print("FAIL: для T02 нужен g++", file=sys.stderr)
        return 1
    source = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
    body = extract_function_body(source, SIGNATURE)
    result = compile_and_run(body, "t02")
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        return 1
    try:
        require_mutant_fails(
            body, "if (!configOwned) return false;", "if (!configOwned && false) return false;",
            "занятый владелец не должен посылать START",
        )
        require_mutant_fails(
            body,
            "if (!i2c_stepper_write_config(i2cStepperPump)) {\n    i2c_stepper_config_end(i2cStepperPump);\n    return false;\n  }",
            "if (!i2c_stepper_write_config(i2cStepperPump) && false) {\n    i2c_stepper_config_end(i2cStepperPump);\n    return false;\n  }",
            "ошибка записи не должна посылать START",
        )
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("T02: подготовка второго I2C-насоса проверена")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
