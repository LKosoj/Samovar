#!/usr/bin/env python3
"""G7: /i2cpump и calibrate_command обязаны использовать i2c_stepper_steps_per_ml()
(геттер с фолбэком на I2C_STEPPER_STEP_ML_DEFAULT), а не сырое SamSetup.StepperStepMlI2C.

На свежем устройстве StepperStepMlI2C == 0. Если передать это сырое поле
напрямую в parse_control_i2c_pump/checked_step_speed_to_mlh, обе функции
отбивают вызов (stepsPerMl == 0 — их собственная защитная ветка), и калибровку/
наполнение i2c-насоса невозможно запустить вообще. Тест компилирует и
запускает РЕАЛЬНЫЙ i2c_stepper_steps_per_ml() (I2CStepper.h) вместе с реальными
parse_control_i2c_pump/checked_step_speed_to_mlh (control_numeric_input.h,
numeric_parse.h) и поведенчески доказывает: через геттер калибровка/наполнение
проходят даже при StepperStepMlI2C == 0, а напрямую через сырое поле — нет
(так проявлялся баг).

Отдельно структурно проверяются реальные тела обработчиков в WebServer.ino:
handle_i2c_pump_request и calibrate_command обязаны звать геттер и не
содержать сырое поле; web_command (ветка /command?pnbk) — НАМЕРЕННО
оставлена как есть: НБК-насос требует уже подтверждённой калибровки (см.
Samovar.ino::set_lua_mode_value-соседний блок pnbk и checked_rate_to_step_speed
в Samovar.ino), поэтому там сырое поле — не баг, и его отсутствие геттера
фиксируется тестом как инвариант, а не как повод чинить.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]

errors: list[str] = []

i2c_text = (ROOT / "I2CStepper.h").read_text(encoding="utf-8", errors="ignore")
web_text = (ROOT / "WebServer.ino").read_text(encoding="utf-8", errors="ignore")
samovar_h_text = (ROOT / "Samovar.h").read_text(encoding="utf-8", errors="ignore")

default_match = re.search(r"#define I2C_STEPPER_STEP_ML_DEFAULT (\d+)", samovar_h_text)
if not default_match:
    errors.append("I2C_STEPPER_STEP_ML_DEFAULT not found in Samovar.h")
default_value = default_match.group(1) if default_match else "16000"

try:
    getter_body = extract_function_body(i2c_text, "inline uint16_t i2c_stepper_steps_per_ml()")
except ValueError as exc:
    errors.append(str(exc))
    getter_body = ""

# --- Структурные проверки реальных обработчиков WebServer.ino -------------

try:
    pump_body = extract_function_body(web_text, "static void handle_i2c_pump_request(AsyncWebServerRequest *request) {")
except ValueError as exc:
    errors.append(str(exc))
    pump_body = ""
if pump_body:
    require_ordered_tokens(
        "handle_i2c_pump_request uses effective stepsPerMl getter",
        pump_body,
        [
            "NumericParseResult result = parse_control_i2c_pump(",
            "i2c_stepper_steps_per_ml(),",
            "parsed,",
            "errorField);",
        ],
        errors,
    )
    if "SamSetup.StepperStepMlI2C" in pump_body:
        errors.append("handle_i2c_pump_request still reads raw SamSetup.StepperStepMlI2C")

try:
    calibrate_body = extract_function_body(web_text, "void calibrate_command(AsyncWebServerRequest *request) {")
except ValueError as exc:
    errors.append(str(exc))
    calibrate_body = ""
if calibrate_body:
    require_ordered_tokens(
        "calibrate_command uses effective stepsPerMl getter",
        calibrate_body,
        [
            "command.stepsPerMl = i2c_stepper_steps_per_ml();",
            "NumericParseResult result = checked_step_speed_to_mlh(",
        ],
        errors,
    )
    if "SamSetup.StepperStepMlI2C" in calibrate_body:
        errors.append("calibrate_command still reads raw SamSetup.StepperStepMlI2C")

# web_command (/command?pnbk) — инвариант: НАМЕРЕННО остаётся на сыром поле,
# т.к. НБК-насос обязан отказывать без подтверждённой калибровки (см. docstring).
try:
    web_command_body = extract_function_body(web_text, "void web_command(AsyncWebServerRequest *request) {")
except ValueError as exc:
    errors.append(str(exc))
    web_command_body = ""
if web_command_body:
    require_ordered_tokens(
        "pnbk keeps the deliberate raw-calibration gate",
        web_command_body,
        [
            'parse_control_nbk(',
            "SamSetup.StepperStepMlI2C, nbkCommand);",
            "nbkCommand.kind != CONTROL_NBK_STOP &&",
            "SamSetup.StepperStepMlI2C == 0) {",
        ],
        errors,
    )

# --- Поведенческая проверка: реальный геттер + реальные numeric-функции ---

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstring>
#include <iostream>

#define I2C_STEPPER_STEP_ML_DEFAULT @DEFAULT@

struct SamSetupType { uint16_t StepperStepMlI2C; };
static SamSetupType SamSetup;

static uint16_t i2c_stepper_steps_per_ml() {
@GETTER_BODY@
}

#include "control_numeric_input.h"

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // Свежее устройство: калибровка ещё не выполнялась.
  SamSetup.StepperStepMlI2C = 0;
  check(i2c_stepper_steps_per_ml() == I2C_STEPPER_STEP_ML_DEFAULT,
        "getter must fall back to the default on a fresh device");

  // /i2cpump (handle_i2c_pump_request), ПОСЛЕ фикса: через геттер.
  {
    ControlI2CPumpInput input = {};
    const char* errorField = "sentinel";
    check(parse_control_i2c_pump("3.6", "100", i2c_stepper_steps_per_ml(), input, errorField).ok(),
          "fixed /i2cpump call must succeed on an uncalibrated device");
  }
  // Тот же вызов ДО фикса: сырое поле — воспроизводит баг из тикета.
  {
    ControlI2CPumpInput input = {};
    const char* errorField = "sentinel";
    check(!parse_control_i2c_pump("3.6", "100", SamSetup.StepperStepMlI2C, input, errorField).ok() &&
              std::strcmp(errorField, "calibration") == 0,
          "raw field reproduces the pre-fix calibration deadlock");
  }

  // calibrate_command, ПОСЛЕ фикса: через геттер.
  {
    uint16_t mlh = 0;
    check(checked_step_speed_to_mlh(500, i2c_stepper_steps_per_ml(), mlh).ok(),
          "fixed calibrate_command call must be able to start calibration on a fresh device");
  }
  // Тот же вызов ДО фикса: сырое поле — воспроизводит баг из тикета.
  {
    uint16_t mlh = 0;
    check(!checked_step_speed_to_mlh(500, SamSetup.StepperStepMlI2C, mlh).ok(),
          "raw field reproduces the pre-fix calibration-start deadlock");
  }

  // Калиброванное устройство: геттер прозрачно возвращает сохранённое значение,
  // поведение калиброванных устройств фиксом не меняется.
  SamSetup.StepperStepMlI2C = 250;
  check(i2c_stepper_steps_per_ml() == 250,
        "getter must return the stored calibration once it is non-zero");

  if (failures != 0) return 1;
  std::cout << "I2C pump calibration default smoke checks passed\n";
  return 0;
}
'''


def run_behavioral_check() -> None:
    if not getter_body:
        return
    harness = HARNESS_TEMPLATE.replace("@DEFAULT@", default_value).replace("@GETTER_BODY@", getter_body)
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-pump-calibration-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "i2c_pump_calibration_test.cpp"
        binary = temp / "i2c_pump_calibration_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append("compile failed:\n" + compile_result.stdout + compile_result.stderr)
            return
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if run_result.returncode != 0:
            errors.append("runtime checks failed:\n" + run_result.stdout + run_result.stderr)


run_behavioral_check()

if errors:
    print("I2C pump calibration default smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("I2C pump calibration default smoke check passed")
