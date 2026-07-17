#!/usr/bin/env python3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "power_regulator_numeric_input.h"

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>

#include "power_regulator_numeric_input.h"

namespace {

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

void check_invalid_kvic(const char* text, const char* message) {
  PowerRegulatorTelemetry telemetry = {7.0f, 8.0f, '2', true, true};
  unsigned char before[sizeof(telemetry)];
  std::memcpy(before, &telemetry, sizeof(telemetry));
  NumericParseResult result = parse_kvic_power_response(text, telemetry);
  check(!result.ok(), message);
  check(std::memcmp(before, &telemetry, sizeof(telemetry)) == 0,
        "invalid KVIC response changed output");
}

void test_kvic() {
  PowerRegulatorTelemetry telemetry = {};
  check(parse_kvic_power_response("T01F0000", telemetry).ok() &&
            telemetry.currentValue == 3.1f && telemetry.targetValue == 0.0f &&
            telemetry.mode == '0' && telemetry.hasTarget && telemetry.hasMode,
        "KVIC lower bounds failed");
  check(parse_kvic_power_response("T9F59F63", telemetry).ok() &&
            telemetry.currentValue == 254.9f && telemetry.targetValue == 255.0f &&
            telemetry.mode == '3' && telemetry.hasTarget && telemetry.hasMode,
        "KVIC upper bounds failed");
  check(parse_kvic_power_response("T01f00a2", telemetry).ok() &&
            telemetry.currentValue == 3.1f && telemetry.targetValue == 1.0f &&
            telemetry.mode == '2' && telemetry.hasTarget && telemetry.hasMode,
        "KVIC lowercase hex failed");

  // Ток валиден (реальный пакет) — target/mode повреждены по отдельности:
  // best-effort парсинг отбрасывает только повреждённое поле (hasTarget/hasMode=false),
  // но не бракует весь пакет (см. комментарий в power_regulator_numeric_input.h).
  telemetry = {};
  check(parse_kvic_power_response("T01F9F70", telemetry).ok() &&
            telemetry.currentValue == 3.1f && !telemetry.hasTarget &&
            telemetry.mode == '0' && telemetry.hasMode,
        "KVIC out-of-range target should be dropped best-effort, not reject packet");
  telemetry = {};
  check(parse_kvic_power_response("T01F0G00", telemetry).ok() &&
            telemetry.currentValue == 3.1f && !telemetry.hasTarget &&
            telemetry.mode == '0' && telemetry.hasMode,
        "KVIC malformed target hex should be dropped best-effort, not reject packet");
  telemetry = {};
  check(parse_kvic_power_response("T01F0004", telemetry).ok() &&
            telemetry.currentValue == 3.1f && telemetry.targetValue == 0.0f &&
            telemetry.hasTarget && !telemetry.hasMode,
        "KVIC out-of-range mode digit should be dropped best-effort, not reject packet");

  const char* invalid[] = {
    "", "T01F000", "T01F00000", "X01F0000", "T01E0000", "T9F60000", "T0G10000",
  };
  check_invalid_kvic(nullptr, "null KVIC response accepted");
  for (const char* text : invalid) check_invalid_kvic(text, "invalid KVIC response accepted");
}

void test_sem_mode() {
  char mode = 'x';
  for (char expected = '0'; expected <= '2'; expected++) {
    char text[2] = {expected, '\0'};
    check(parse_sem_power_mode_response(text, mode).ok() && mode == expected,
          "valid SEM mode rejected");
  }

  const char* invalid[] = {"", "3", "-1", "01", "1 ", " 1", "1x"};
  for (const char* text : invalid) {
    mode = 'x';
    NumericParseResult result = parse_sem_power_mode_response(text, mode);
    check(!result.ok() && mode == 'x', "invalid SEM mode changed output");
  }
}

void check_invalid_sem_value(
    const char* text,
    float heaterResistance,
    const char* message) {
  uint16_t value = 77;
  NumericParseResult result = parse_sem_power_value_response(
      text, heaterResistance, value);
  check(!result.ok() && value == 77, message);
}

void test_sem_value() {
  uint16_t value = 77;
  check(parse_sem_power_value_response("0", 10.0f, value).ok() && value == 0,
        "SEM zero value failed");
  check(parse_sem_power_value_response("5290", 10.0f, value).ok() && value == 5290,
        "SEM resistance-derived upper bound failed");
  check_invalid_sem_value("5291", 10.0f, "SEM dynamic overflow accepted");

  // Недоверенное R даёт ту же границу, что и заводское: 52900/15.2 = 3480 Вт. Раньше
  // здесь стоял плоский литерал 4000 Вт - единственный откат, не выраженный через
  // сопротивление. Пиним обе половины: и число, и то, что NAN неотличим от заводского.
  check(parse_sem_power_value_response("3480", NAN, value).ok() && value == 3480,
        "SEM fallback ceiling failed");
  check_invalid_sem_value("3481", NAN, "SEM fallback ceiling overflow accepted");
  check(parse_sem_power_value_response("3480", CONTROL_HEATER_R_DEFAULT, value).ok() &&
            value == 3480,
        "SEM factory-default ceiling must match the untrusted fallback");
  check_invalid_sem_value("3481", CONTROL_HEATER_R_DEFAULT,
                          "SEM factory-default ceiling overflow accepted");

  const char* invalid[] = {
    "", "-1", "+1", "1.0", "1 ", " 1", "1x", "999999999999999999999",
  };
  check_invalid_sem_value(nullptr, 10.0f, "null SEM value accepted");
  for (const char* text : invalid) {
    check_invalid_sem_value(text, 10.0f, "invalid SEM value changed output");
  }
}

}  // namespace

int main() {
  static_assert(sizeof(PowerRegulatorTelemetry) <= 12, "telemetry draft budget exceeded");
  test_kvic();
  test_sem_mode();
  test_sem_value();
  if (failures != 0) return 1;
  std::cout << "Power regulator numeric input checks passed\n";
  return 0;
}
'''


def main() -> int:
    source = HEADER.read_text(encoding="utf-8")
    for forbidden in ("Arduino.h", "String", "std::string", "new ", "throw "):
        if forbidden in source:
            print(f"power_regulator_numeric_input.h contains forbidden token: {forbidden}")
            return 1

    with tempfile.TemporaryDirectory(prefix="samovar-power-numeric-") as temp_dir:
        temp = Path(temp_dir)
        harness = temp / "power_regulator_numeric_test.cpp"
        harness.write_text(HARNESS, encoding="utf-8")
        binary = temp / "power_regulator_numeric_test"
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(ROOT),
                str(harness),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
