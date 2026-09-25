#!/usr/bin/env python3
"""Проверка ускорения насоса при быстром росте температуры воды."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "mode_common.h").read_text(encoding="utf-8")
rise_body = extract_function_body(source, "inline bool mode_water_rising_fast()")
update_body = extract_function_body(source, "inline void mode_update_water_pump_pid(float acpBoostThreshold)")

HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#define USE_WATER_PUMP
struct Sensor { float avgTemp = 0; } WaterSensor, ACPSensor;
struct Setup { float SetWaterTemp = 55; } SamSetup;
static bool PowerOn = true;
static bool valve_status = true;
static uint32_t nowMs = 1000;
static uint32_t millis() { return nowMs; }
static float inputTemp = -1;
static bool softenInput = true;
static void set_pump_speed_pid(float temp, bool soften = true) {
  inputTemp = temp;
  softenInput = soften;
}
static bool mode_acp_above_boost_threshold(float threshold) {
  return ACPSensor.avgTemp > threshold;
}
static void mode_warn_acp_hot_once(bool, float) {}

inline bool mode_water_rising_fast() { @RISE@ }
inline void mode_update_water_pump_pid(float acpBoostThreshold) { @UPDATE@ }

static void check(bool condition, const char* message) {
  if (!condition) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
static void reset(uint32_t time, float setpoint, float temp) {
  PowerOn = false;
  mode_water_rising_fast();
  PowerOn = true;
  valve_status = true;
  nowMs = time;
  SamSetup.SetWaterTemp = setpoint;
  WaterSensor.avgTemp = temp;
  ACPSensor.avgTemp = 0;
}

int main() {
  reset(1000, 55, 50);
  mode_update_water_pump_pid(45);
  check(softenInput, "первое измерение не должно ускорять насос");
  nowMs += 5000;
  WaterSensor.avgTemp = 51.2f;
  mode_update_water_pump_pid(45);
  check(softenInput, "рост далеко ниже уставки не должен ускорять насос");

  reset(10000, 55, 53);
  mode_update_water_pump_pid(45);
  nowMs += 5000;
  WaterSensor.avgTemp = 54.2f;
  mode_update_water_pump_pid(45);
  check(inputTemp == WaterSensor.avgTemp && !softenInput,
        "рост воды у уставки должен отключать смягчение насоса");
  nowMs += 1000;
  WaterSensor.avgTemp = 54.3f;
  mode_update_water_pump_pid(45);
  check(!softenInput, "быстрый рост действует до следующего окна измерения");
  WaterSensor.avgTemp = 54.1f;
  mode_update_water_pump_pid(45);
  check(softenInput, "при падении температуры ускорение сразу прекращается");
  nowMs += 4000;
  WaterSensor.avgTemp = 54.4f;
  mode_update_water_pump_pid(45);
  check(softenInput, "после стабилизации обычное регулирование возвращается");

  reset(30000, 40, 38);
  mode_update_water_pump_pid(45);
  nowMs += 5000;
  WaterSensor.avgTemp = 39.3f;
  mode_update_water_pump_pid(45);
  check(!softenInput, "другая уставка воды тоже должна ускорять насос");
  valve_status = false;
  mode_update_water_pump_pid(45);
  valve_status = true;
  mode_update_water_pump_pid(45);
  check(softenInput, "закрытие клапана сбрасывает быстрый рост");

  reset(UINT32_MAX - 2500u, 55, 54);
  mode_update_water_pump_pid(45);
  nowMs += 5000;
  WaterSensor.avgTemp = 55.2f;
  mode_update_water_pump_pid(45);
  check(!softenInput, "переполнение millis не должно мешать реакции");

  ACPSensor.avgTemp = 60;
  mode_update_water_pump_pid(45);
  check(inputTemp == SamSetup.SetWaterTemp + 3 && !softenInput,
        "существующее усиление по ТСА должно сохраниться");
  return 0;
}
'''


def run(text: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="samovar-water-rise-") as directory:
        source_path = Path(directory) / "test.cpp"
        binary_path = Path(directory) / "test"
        source_path.write_text(text, encoding="utf-8")
        built = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            text=True, capture_output=True,
        )
        if built.returncode:
            return built
        return subprocess.run([str(binary_path)], text=True, capture_output=True)


harness = HARNESS.replace("@RISE@", rise_body).replace("@UPDATE@", update_body)
result = run(harness)
if result.returncode:
    raise SystemExit(result.stderr)
for name, old, new, expected in (
    ("growth threshold", ">= 1.0f", ">= 10.0f", "рост воды у уставки"),
    ("setpoint proximity", "SamSetup.SetWaterTemp - 2.0f", "SamSetup.SetWaterTemp + 2.0f", "рост воды у уставки"),
    ("PID softening", "!waterRisingFast", "waterRisingFast", "первое измерение"),
    ("falling temperature", "WaterSensor.avgTemp < windowStartTemp", "WaterSensor.avgTemp < -100", "при падении температуры"),
):
    if harness.count(old) != 1:
        raise SystemExit(f"FAIL: cannot mutate {name}")
    mutant = run(harness.replace(old, new, 1))
    if mutant.returncode == 0 or expected not in mutant.stderr:
        raise SystemExit(f"FAIL: mutation {name} was not caught by {expected}")
print("water pump fast rise passed")
