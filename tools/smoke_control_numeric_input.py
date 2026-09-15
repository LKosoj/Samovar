#!/usr/bin/env python3
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_INCLUDE = ROOT / "libraries/I2CStepperProtocol/src"
PUMP_SIGNATURE = "inline NumericParseResult parse_control_i2c_pump("

HARNESS = r'''
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <iostream>

#include "control_numeric_input.h"

namespace {

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

void test_power_and_scalars() {
  float limit = -1.0f;
  check(control_power_input_max(false, NAN, limit).ok() && limit == 230.0f,
        "non-SEM power limit failed");
  check(control_power_input_max(true, 10.0f, limit).ok() && limit == 5290.0f,
        "SEM resistance power limit failed");

  // Недоверенное R обязано считаться РОВНО как заводское - это и есть смысл единой
  // точки правды. Сверяем с границей для заводского R, а не с числом: так тест ловит
  // подмену отката (раньше здесь был плоский литерал 4000 Вт мимо всяких настроек),
  // но не ломается от смены самого заводского значения.
  float trusted = -1.0f;
  check(control_power_input_max(true, CONTROL_HEATER_R_DEFAULT, trusted).ok(),
        "SEM default resistance limit failed");
  for (float untrusted : {NAN, 0.0f, -5.0f, 1.9f, 65.1f, 10000.0f, INFINITY}) {
    limit = -1.0f;
    check(control_power_input_max(true, untrusted, limit).ok() && limit == trusted,
          "SEM untrusted resistance must fall back to the factory default");
  }

  // Границы диапазона включительны с обеих сторон.
  check(control_power_input_max(true, CONTROL_HEATER_R_MIN, limit).ok() &&
            limit == 52900.0f / CONTROL_HEATER_R_MIN && limit != trusted,
        "SEM lower resistance bound must be trusted");
  check(control_power_input_max(true, CONTROL_HEATER_R_MAX, limit).ok() &&
            limit == 52900.0f / CONTROL_HEATER_R_MAX && limit != trusted,
        "SEM upper resistance bound must be trusted");

  // R2 (решение владельца: расширить диапазон до 65 Ом). Проверки границ выше
  // сверяются с САМИМИ символами CONTROL_HEATER_R_MIN/MAX, поэтому сужение
  // потолка обратно они не поймают: символ просто станет другим числом, и обе
  // проверки останутся зелёными. Значение внутри расширенного диапазона ловит
  // это прямо: 50 Ом до R2 отвергалось как недоверенное и молча считалось по
  // заводским 15.2 Ом - то есть пользователь высокоомного ТЭНа получал чужой
  // предел мощности, ничего об этом не узнав.
  check(control_power_input_max(true, 50.0f, limit).ok() &&
            limit == 52900.0f / 50.0f && limit != trusted,
        "50 Ohm heater must stay inside the trusted range (owner widened it to 65)");

  // Делить на результат безопасно всегда - ради этого функция и существует.
  for (float hostile : {NAN, 0.0f, -1.0f, INFINITY, -INFINITY}) {
    const float r = trusted_heater_resistance(hostile);
    check(std::isfinite(r) && r > 0.0f,
          "trusted_heater_resistance must never return a value unsafe to divide by");
  }

  check(control_power_input_max(true, 7.3f, limit).ok(),
        "dynamic SEM power limit failed");
  char rendered_limit[32] = {};
  std::snprintf(rendered_limit, sizeof(rendered_limit), "%.9f", limit);
  float rendered_power = 0.0f;
  check(parse_control_power(rendered_limit, limit, rendered_power).ok() &&
            rendered_power == limit,
        "nine-decimal rendered dynamic maximum did not round-trip");
  const float above_limit = std::nextafter(limit, INFINITY);
  char rendered_above[32] = {};
  std::snprintf(rendered_above, sizeof(rendered_above), "%.9f", above_limit);
  rendered_power = 77.0f;
  check(!parse_control_power(rendered_above, limit, rendered_power).ok() &&
            rendered_power == 77.0f,
        "value above rendered dynamic maximum was accepted");

  float power = 77.0f;
  check(parse_control_power("230", 230.0f, power).ok() && power == 230.0f,
        "power upper bound failed");
  power = 77.0f;
  check(!parse_control_power("230.001", 230.0f, power).ok() && power == 77.0f,
        "power overflow changed output");

  uint16_t pwm = 55;
  check(parse_control_water_pwm("1023", pwm).ok() && pwm == 1023,
        "PWM upper bound failed");
  pwm = 55;
  check(!parse_control_water_pwm("1023.1", pwm).ok() && pwm == 55,
        "fractional PWM changed output");
  check(!parse_control_water_pwm("1024", pwm).ok() && pwm == 55,
        "PWM overflow changed output");

  float vless = 8.0f;
  check(parse_control_vless("0.001", vless).ok() && vless == 0.001f,
        "vless lower bound failed");
  check(parse_control_vless("10000", vless).ok() && vless == 10000.0f,
        "vless upper bound failed");
  vless = 8.0f;
  check(!parse_control_vless("0", vless).ok() && vless == 8.0f,
        "invalid vless changed output");
}

void test_rates_and_nbk() {
  uint16_t steps = 99;
  check(parse_control_rate_steps("3.6", 1000, steps).ok() && steps == 1000,
        "control rate conversion failed");
  steps = 99;
  check(!parse_control_rate_steps("3.6", 0, steps).ok() && steps == 99,
        "zero calibration changed rate output");

  ControlNbkCommand command = {CONTROL_NBK_INCREMENT, 321};
  check(parse_control_nbk("0", 100, command).ok() && command.kind == CONTROL_NBK_STOP,
        "NBK stop failed");
  check(parse_control_nbk("8000", 100, command).ok() && command.kind == CONTROL_NBK_DECREMENT,
        "NBK decrement failed");
  check(parse_control_nbk("9000", 100, command).ok() && command.kind == CONTROL_NBK_INCREMENT,
        "NBK increment failed");
  check(parse_control_nbk("3.6", 1000, command).ok() &&
            command.kind == CONTROL_NBK_ABSOLUTE && command.stepSpeed == 1000,
        "NBK absolute rate failed");
  check(parse_control_nbk("7999.9999", 1, command).ok() &&
            command.kind == CONTROL_NBK_ABSOLUTE && command.stepSpeed == 2222,
        "NBK value below sentinel was rounded into a tag or rejected");
  check(parse_control_rate_steps("10000", 1, steps).ok() && steps == 2778,
        "general rate parser incorrectly uses the NBK domain cap");
  const char* invalid[] = {
      "-1", "8000.0", "8000.0001", "8999", "8999.9999",
      "9000.0", "9000.0001", "nan", "inf"};
  for (const char* text : invalid) {
    command = {CONTROL_NBK_INCREMENT, 321};
    check(!parse_control_nbk(text, 1000, command).ok() &&
              command.kind == CONTROL_NBK_INCREMENT && command.stepSpeed == 321,
          "invalid NBK command changed output");
  }
}

void test_i2c_pump() {
  ControlI2CPumpInput input = {7, 8, 9.0f, 12};
  const char* error_field = "sentinel";
  check(parse_control_i2c_pump("3.6", "100", 1000, input, error_field).ok(),
        "valid I2C pump input failed");
  check(input.speedSteps == 1000 && input.targetSteps == 100000 &&
            input.targetMl == 100.0f && input.stepsPerMl == 1000,
        "I2C pump typed draft mismatch");

  input = {7, 8, 9.0f, 12};
  error_field = "sentinel";
  check(parse_control_i2c_pump("6.48", "12.5", 2000, input, error_field).ok() &&
            input.speedSteps == 3600 && input.targetSteps == 25000 &&
            input.targetMl == 12.5f && input.stepsPerMl == 2000,
        "second I2C pump input pair mismatch");

  const char* invalid_speed[] = {"", "0", "nan", "inf", "1x", "999999"};
  for (const char* text : invalid_speed) {
    input = {7, 8, 9.0f, 12};
    error_field = "sentinel";
    check(!parse_control_i2c_pump(text, "100", 1000, input, error_field).ok() &&
              input.speedSteps == 7 && input.targetSteps == 8 && input.targetMl == 9.0f,
          "invalid I2C speed changed output");
    check(std::strcmp(error_field, "speed") == 0, "I2C speed error field mismatch");
  }
  char too_large_volume[32] = {};
  std::snprintf(too_large_volume, sizeof(too_large_volume), "%lu",
                static_cast<unsigned long>(I2CSTEPPER_V3_TARGET_STEPS_MAX / 1000UL + 1UL));
  const char* invalid_volume[] = {"", "0", too_large_volume, "-1", "1x"};
  for (const char* text : invalid_volume) {
    input = {7, 8, 9.0f, 12};
    error_field = "sentinel";
    check(!parse_control_i2c_pump("3.6", text, 1000, input, error_field).ok() &&
              input.speedSteps == 7 && input.targetSteps == 8 && input.targetMl == 9.0f,
          "invalid I2C volume changed output");
    check(std::strcmp(error_field, "volume") == 0, "I2C volume error field mismatch");
  }

  // /i2cpump принимает дробные мл (усечение/масштабирование, как HEAD toFloat):
  // объём не бракуется, targetSteps считается от полного (нецелого) значения мл.
  input = {7, 8, 9.0f, 12};
  error_field = "sentinel";
  check(parse_control_i2c_pump("3.6", "1.5", 1000, input, error_field).ok() &&
            input.targetSteps == 1500 && input.targetMl == 1.5f && input.stepsPerMl == 1000,
        "fractional I2C volume rejected");

  input = {7, 8, 9.0f, 12};
  error_field = "sentinel";
  check(!parse_control_i2c_pump("3.6", "100", 0, input, error_field).ok() &&
            input.speedSteps == 7 && std::strcmp(error_field, "calibration") == 0,
        "zero I2C calibration changed output");
}

}  // namespace

int main() {
  static_assert(sizeof(ControlI2CPumpInput) == sizeof(uint32_t) * 3 + sizeof(float),
                "I2C numeric draft must retain exactly four fields");
  test_power_and_scalars();
  test_rates_and_nbk();
  test_i2c_pump();
  if (failures != 0) return 1;
  std::cout << "Control numeric input behavioral checks passed\n";
  return 0;
}
'''


def compile_and_run(header_override: str | None = None, emit: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-control-numeric-") as temp_dir:
        temp = Path(temp_dir)
        if header_override is not None:
            (temp / "control_numeric_input.h").write_text(header_override, encoding="utf-8")
        source = temp / "control_numeric_test.cpp"
        source.write_text(HARNESS, encoding="utf-8")
        binary = temp / "control_numeric_test"
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(ROOT),
                "-I",
                str(PROTOCOL_INCLUDE),
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            output = compile_result.stdout + compile_result.stderr
            if emit:
                sys.stderr.write(output)
            return compile_result.returncode, output
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        output = run_result.stdout + run_result.stderr
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode, output


def source_mutant(source: str, old: str, new: str) -> str:
    body = extract_function_body(source, PUMP_SIGNATURE, strip_comments=False)
    if body.count(old) != 1:
        raise ValueError(f"I2C pump mutation token is not unique: {old}")
    mutated_body = body.replace(old, new, 1)
    start = source.find(PUMP_SIGNATURE)
    body_start = source.find("{", start) + 1
    body_end = body_start + len(body)
    return source[:body_start] + mutated_body + source[body_end:]


def main() -> int:
    baseline, _ = compile_and_run()
    if baseline != 0:
        return baseline

    source = (ROOT / "control_numeric_input.h").read_text(encoding="utf-8")
    mutations = (
        (
            "speed ceiling",
            "speed > I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC",
            "false",
            "invalid I2C speed changed output",
        ),
        (
            "target steps ceiling",
            "parsed.targetSteps > I2CSTEPPER_V3_TARGET_STEPS_MAX",
            "false",
            "invalid I2C volume changed output",
        ),
    )
    for name, old, new, expected in mutations:
        try:
            mutated = source_mutant(source, old, new)
        except ValueError as error:
            print(f"FAIL: {error}", file=sys.stderr)
            return 1
        status, output = compile_and_run(mutated, emit=False)
        if status == 0 or f"FAIL: {expected}" not in output:
            print(f"FAIL: I2C pump {name} mutation survived: {output.strip()}",
                  file=sys.stderr)
            return 1
    print("Control numeric input behavioural checks passed (source-derived mutations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
