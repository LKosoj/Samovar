#!/usr/bin/env python3
"""Поведенческая проверка общего demand-gate протока в beer alarm-path."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <iostream>

static int beerCheckCoolingLimitsCalls = 0;
void beer_check_cooling_limits() { beerCheckCoolingLimitsCalls++; }

static int beerCheckWortOverheatLimitCalls = 0;
void beer_check_wort_overheat_limit() { beerCheckWortOverheatLimitCalls++; }

static int waterFlowEmergencyCalls = 0;
void mode_request_water_flow_emergency_if_needed() { waterFlowEmergencyCalls++; }

@MODE_ALARM_BEER@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  mode_alarm_beer();
  check(beerCheckCoolingLimitsCalls == 1,
        "beer alarm должен всегда проверять температурные пределы охлаждения");
  check(beerCheckWortOverheatLimitCalls == 1,
        "beer alarm должен всегда проверять верхний предел температуры сусла (T23.2)");
  check(waterFlowEmergencyCalls == 1,
        "beer alarm должен делегировать контроль протока общему demand-gate");
  if (failures != 0) return 1;
  std::cout << "beer flow alarm delegates to shared demand gate\n";
  return 0;
}
'''


# [T23.2] Второй харнесс: реальное тело beer_check_wort_overheat_limit(). Первый
# харнесс проверяет только диспетчеризацию (функция там замокана счётчиком), поэтому
# порог и guard по PowerOn остались бы без покрытия.
WORT_HARNESS = r"""
#include <iostream>
#include <string>

#define BOILING_TEMP 98.9f

struct DSSensor {
  float avgTemp;
  bool configured;
};

static DSSensor TankSensor = {20.0f, true};
static bool PowerOn = false;

bool sensor_temp_at_least(const DSSensor& sensor, float temp) {
  if (!sensor.configured) return false;
  return sensor.avgTemp >= temp;
}

static int emergencyCalls = 0;
static std::string lastReason;
void request_emergency_stop(const std::string& reason) {
  emergencyCalls++;
  lastReason = reason;
}

@BEER_CHECK_WORT_OVERHEAT@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // 1. Перегрев сусла при работающем нагреве - аварийный останов.
  PowerOn = true;
  TankSensor.configured = true;
  TankSensor.avgTemp = BOILING_TEMP + 6.0f;
  emergencyCalls = 0;
  beer_check_wort_overheat_limit();
  check(emergencyCalls == 1, "перегрев сусла обязан снимать нагрев");
  check(lastReason.find("сусла") != std::string::npos,
        "причина останова обязана называть температуру сусла");

  // 2. Тот же перегрев, но нагрев выключен - тревоги быть не должно.
  PowerOn = false;
  emergencyCalls = 0;
  beer_check_wort_overheat_limit();
  check(emergencyCalls == 0, "в простое (PowerOn=false) тревоги быть не должно");

  // 3. Температура ниже порога - тревоги нет.
  PowerOn = true;
  TankSensor.avgTemp = BOILING_TEMP + 4.0f;
  emergencyCalls = 0;
  beer_check_wort_overheat_limit();
  check(emergencyCalls == 0, "ниже порога BOILING_TEMP+5 тревоги быть не должно");

  // 4. Ненастроенный датчик не даёт ложную тревогу даже при абсурдном значении.
  TankSensor.configured = false;
  TankSensor.avgTemp = 200.0f;
  emergencyCalls = 0;
  beer_check_wort_overheat_limit();
  check(emergencyCalls == 0, "ненастроенный датчик не должен поднимать тревогу");

  if (failures != 0) return 1;
  std::cout << "beer wort overheat limit checks passed\n";
  return 0;
}
"""


def compile_and_run(source: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-flow-") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / "beer_flow.cpp"
        binary_path = temp / "beer_flow"
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source_path),
                "-o",
                str(binary_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode
        result = subprocess.run(
            [str(binary_path)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode


def main() -> int:
    source = (ROOT / "mode_registry.h").read_text(encoding="utf-8")
    body = extract_function_body(source, "inline void mode_alarm_beer()")
    function = "void mode_alarm_beer() {" + body + "}"
    if "water_pulse_count_set" in body:
        print("FAIL: beer alarm всё ещё подменяет реальные импульсы протока", file=sys.stderr)
        return 1
    status = compile_and_run(HARNESS_TEMPLATE.replace("@MODE_ALARM_BEER@", function))
    if status != 0:
        return status

    beer_source = (ROOT / "beer.h").read_text(encoding="utf-8")
    wort_body = extract_function_body(beer_source, "inline void beer_check_wort_overheat_limit()")
    wort_function = "void beer_check_wort_overheat_limit() {" + wort_body + "}"
    return compile_and_run(WORT_HARNESS.replace("@BEER_CHECK_WORT_OVERHEAT@", wort_function))


if __name__ == "__main__":
    raise SystemExit(main())
