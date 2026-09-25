#!/usr/bin/env python3
"""Проверка показания воды в предупреждении из mode_common.h."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "mode_common.h").read_text()
DUE = extract_function_body(SOURCE, "inline bool mode_water_pre_alarm_due")
WARN = extract_function_body(SOURCE, "inline void mode_warn_water_hot")

HARNESS = r'''
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#define ALARM_WATER_TEMP 70
#define WARNING_MSG 1
#define String std::to_string

struct Sensor { float avgTemp = 0; } WaterSensor;
bool PowerOn = false;
unsigned long alarm_t_min = 0;
int buzzerCalls = 0;
std::vector<std::string> messages;

void set_buzzer(bool) { ++buzzerCalls; }
void SendMsg(const std::string& message, int) { messages.push_back(message); }
std::string format_float(float value, int digits) {
  std::ostringstream out;
  out << std::fixed << std::setprecision(digits) << value;
  return out.str();
}

inline bool mode_water_pre_alarm_due() {@DUE@}
inline void mode_warn_water_hot() {@WARN@}

int main() {
  auto check = [](bool valid, const char* reason) {
    if (!valid) { std::cerr << "FAIL: " << reason << '\n'; std::exit(1); }
  };
  PowerOn = true;
  WaterSensor.avgTemp = 55.1f;
  check(!mode_water_pre_alarm_due(), "55.1 C must not warn at the 65 C threshold");
  WaterSensor.avgTemp = 65.1f;
  check(mode_water_pre_alarm_due(), "65.1 C must trigger warning");
  mode_warn_water_hot();
  check(messages.size() == 1 && buzzerCalls == 1 &&
        messages[0].find("65.1") != std::string::npos &&
        messages[0].find("порог предупреждения 65") != std::string::npos,
        "first warning must show trigger reading and threshold");
  alarm_t_min = 123;
  check(!mode_water_pre_alarm_due(), "cooldown must defer warning");
  alarm_t_min = 0;
  WaterSensor.avgTemp = 70.4f;
  check(mode_water_pre_alarm_due(), "70.4 C must trigger warning after cooldown");
  mode_warn_water_hot();
  check(messages.size() == 2 && buzzerCalls == 2 &&
        messages[1].find("70.4") != std::string::npos,
        "repeat warning must show the new reading");
  std::cout << "water warning reading checks passed\n";
}
'''


def run(warn_body: str):
    code = HARNESS.replace("@DUE@", DUE).replace("@WARN@", warn_body)
    with tempfile.TemporaryDirectory(prefix="samovar-water-warning-") as name:
        source = Path(name) / "warning.cpp"
        binary = Path(name) / "warning"
        source.write_text(code)
        subprocess.run(["g++", "-std=c++17", str(source), "-o", str(binary)], check=True)
        return subprocess.run([str(binary)], capture_output=True, text=True)


actual = run(WARN)
if actual.returncode != 0:
    raise AssertionError(actual.stderr)
print(actual.stdout.strip())

reading = "format_float(WaterSensor.avgTemp, 1)"
if WARN.count(reading) != 1:
    raise AssertionError("water warning reading mutation anchor missing")
mutated = run(WARN.replace(reading, "format_float(55.0f, 1)"))
if mutated.returncode == 0 or "first warning must show trigger reading and threshold" not in mutated.stderr:
    raise AssertionError("water warning reading mutation did not fail meaningfully")
print("water warning reading mutation: failed as expected")
