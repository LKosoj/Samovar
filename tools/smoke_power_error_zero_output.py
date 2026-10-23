#!/usr/bin/env python3
"""Проверка нулевого выхода РМ через настоящее тело check_power_error()."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import I18N_INCLUDE, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cmath>
#include <iostream>
#include <string>
using String = std::string;
using std::abs;
constexpr int ALARM_MSG = 0;
constexpr const char* POWER_SLEEP_MODE = "SLEEP";
constexpr const char* POWER_WORK_MODE = "WORK";
struct { bool CheckPower = true; } SamSetup;
bool PowerOn = true;
bool reg_online = true;
unsigned long last_reg_online = 1;
unsigned long millis() { return 20000; }
String mode = POWER_WORK_MODE;
bool current_power_mode_is(const char* value) { return mode == value; }
float current_power_volt = 0;
float target_power_volt = 0;
float requestedVoltage = 0;
int power_err_cnt = 0;
int stops = 0;
String reason;
void set_current_power(float value) { requestedVoltage = value; }
void SendMsg(const String&, int) {}
void request_emergency_stop(const String& value) {
  stops++;
  reason = value;
  PowerOn = false;
}
void check_power_error() {
@BODY@
}
int failures = 0;
void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}
void reset(float target, float actual) {
  PowerOn = true;
  SamSetup.CheckPower = true;
  reg_online = true;
  mode = POWER_WORK_MODE;
  target_power_volt = target;
  current_power_volt = actual;
  power_err_cnt = 0;
  stops = 0;
  requestedVoltage = 0;
  reason.clear();
}
int main() {
  for (float target : {100.0f, 200.0f}) {
    reset(target, 0);
    for (int attempt = 0; attempt < 12; attempt++) check_power_error();
    check(stops == 0, "нулевой выход не должен обходить штатную выдержку ошибки");
    check(requestedVoltage == target, "повтор команды должен использовать текущую уставку");
    check_power_error();
    check(stops == 1 && !PowerOn,
          "нулевой выход при ненулевой уставке обязан вызвать аварийное отключение");
    check(reason == "Аварийное отключение! Ошибка управления нагревателем.",
          "нулевой выход должен сообщать об ошибке управления нагревателем");

    reset(target, target * 0.9f);
    for (int attempt = 0; attempt < 15; attempt++) check_power_error();
    check(stops == 0 && power_err_cnt == 0, "допустимое отклонение не должно давать аварию");
  }
  for (int disabled = 0; disabled < 5; disabled++) {
    reset(150, 0);
    if (disabled == 0) target_power_volt = 0;
    if (disabled == 1) mode = POWER_SLEEP_MODE;
    if (disabled == 2) PowerOn = false;
    if (disabled == 3) SamSetup.CheckPower = false;
    if (disabled == 4) current_power_volt = -1;
    for (int attempt = 0; attempt < 15; attempt++) check_power_error();
    check(stops == 0 && power_err_cnt == 0, "отключённый нагрев или контроль не должны давать аварию");
  }
  if (failures) return 1;
  std::cout << "power regulator zero output checks passed\n";
}
'''


def build_harness() -> str:
    body = extract_function_body(
        (ROOT / "power_regulator.h").read_text(encoding="utf-8"),
        "void check_power_error()")
    return I18N_INCLUDE + "\n" + HARNESS.replace("@BODY@", body)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-power-zero-") as directory:
        source = Path(directory) / "test.cpp"
        binary = Path(directory) / "test"
        source.write_text(build_harness(), encoding="utf-8")
        subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                        str(source), "-o", str(binary)], check=True)
        return subprocess.run([str(binary)], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
