#!/usr/bin/env python3
"""Поведенческая проверка DS_getvalue(): своя дельта у каждого датчика.

DS_getvalue() (sensorinit.h) раньше был пятью почти одинаковыми if/else
блоками ("ss = ...; SteamSensor.avgTemp = ss + SamSetup.DeltaSteamTemp; ...").
Свёртка в цикл по kSensorDeltaFields/sensorList легко могла бы перепутать
пары (датчик, дельта) местами - тест ловит именно это, а не общий факт, что
"какая-то дельта прибавилась".

Тест вытаскивает из РЕАЛЬНОГО sensorinit.h связку struct SensorDeltaField +
kSensorDeltaFields + DS_getvalue() целиком (extract_braced_block_after до
конца DS_getvalue), не переписывая логику, и подставляет в минимальный
host-харнесс. Заглушка sensors.getTempC() не константа - она возвращает
значение по метке в Sensor[0], поэтому каждый датчик получает СВОЁ сырое
показание, а не одно и то же число (иначе перестановка датчиков местами
осталась бы незамеченной).

Два раунда с разными наборами дельт и показаний (правило AGENTS.md: тест на
одном наборе значений может пройти от случайного совпадения/хардкода).
SamSetup.UsePreccureCorrect=false и PowerOn=false фиксируют correctT=0, чтобы
тест бил строго по применению дельты, а не по барометрической коррекции.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

STRUCT_MARKER = "struct SensorDeltaField {"
FUNCTION_MARKER = "void DS_getvalue(void)"

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <sstream>
#include <string>

using DeviceAddress = uint8_t[8];

struct DSSensor {
  DeviceAddress Sensor = {0, 0, 0, 0, 0, 0, 0, 0};
  float avgTemp = 0.0f;
  float PrevTemp = 0.0f;
  int ErrCount = 0;
};

struct SetupEEPROM {
  float DeltaSteamTemp = 0.0f;
  float DeltaPipeTemp = 0.0f;
  float DeltaWaterTemp = 0.0f;
  float DeltaTankTemp = 0.0f;
  float DeltaACPTemp = 0.0f;
  bool UsePreccureCorrect = false;
};

static const uint8_t DS_SENSOR_COUNT = 5;

static DSSensor SteamSensor;
static DSSensor PipeSensor;
static DSSensor WaterSensor;
static DSSensor TankSensor;
static DSSensor ACPSensor;

DSSensor* const sensorList[DS_SENSOR_COUNT] = {
    &SteamSensor, &PipeSensor, &WaterSensor, &TankSensor, &ACPSensor};

static SetupEEPROM SamSetup;
static float bme_pressure = 0.0f;
static bool PowerOn = false;
static volatile uint32_t DSUpdateCounter = 0;

// Заглушка датчиков: значение читаем по метке, записанной в Sensor[0], а не
// возвращаем константу - иначе перестановка датчиков местами в
// kSensorDeltaFields осталась бы незамеченной (все получили бы одно число).
struct SensorsStub {
  float readings[DS_SENSOR_COUNT] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
  float getTempC(const uint8_t* addr) { return readings[addr[0]]; }
  void requestTemperatures() {}
};
static SensorsStub sensors;

@BODY@

static int failures = 0;

static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void set_sensor_labels() {
  SteamSensor.Sensor[0] = 0;
  PipeSensor.Sensor[0] = 1;
  WaterSensor.Sensor[0] = 2;
  TankSensor.Sensor[0] = 3;
  ACPSensor.Sensor[0] = 4;
}

struct RoundExpectation {
  const char* label;
  const char* sensorName;
  DSSensor* sensor;
  float delta;
  float raw;
  float expectedAvg;
};

static void run_round(const char* label,
                       float dSteam, float dPipe, float dWater, float dTank, float dAcp,
                       float rSteam, float rPipe, float rWater, float rTank, float rAcp,
                       float eSteam, float ePipe, float eWater, float eTank, float eAcp) {
  SamSetup.DeltaSteamTemp = dSteam;
  SamSetup.DeltaPipeTemp = dPipe;
  SamSetup.DeltaWaterTemp = dWater;
  SamSetup.DeltaTankTemp = dTank;
  SamSetup.DeltaACPTemp = dAcp;
  SamSetup.UsePreccureCorrect = false;
  PowerOn = false;
  bme_pressure = 0.0f;

  sensors.readings[0] = rSteam;
  sensors.readings[1] = rPipe;
  sensors.readings[2] = rWater;
  sensors.readings[3] = rTank;
  sensors.readings[4] = rAcp;

  SteamSensor.avgTemp = 0.0f;
  PipeSensor.avgTemp = 0.0f;
  WaterSensor.avgTemp = 0.0f;
  TankSensor.avgTemp = 0.0f;
  ACPSensor.avgTemp = 0.0f;

  DS_getvalue();

  RoundExpectation expectations[DS_SENSOR_COUNT] = {
      {label, "Steam", &SteamSensor, dSteam, rSteam, eSteam},
      {label, "Pipe", &PipeSensor, dPipe, rPipe, ePipe},
      {label, "Water", &WaterSensor, dWater, rWater, eWater},
      {label, "Tank", &TankSensor, dTank, rTank, eTank},
      {label, "ACP", &ACPSensor, dAcp, rAcp, eAcp},
  };

  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
    const RoundExpectation& e = expectations[i];
    std::ostringstream where;
    where << e.label << ": " << e.sensorName << " avgTemp ожидался " << e.expectedAvg
          << " (сырое=" << e.raw << ", дельта=" << e.delta << "), получено "
          << e.sensor->avgTemp;
    check(std::fabs(e.sensor->avgTemp - e.expectedAvg) < 1e-4, where.str());

    std::ostringstream prevWhere;
    prevWhere << e.label << ": " << e.sensorName << " PrevTemp должен совпасть с avgTemp";
    check(std::fabs(e.sensor->PrevTemp - e.sensor->avgTemp) < 1e-4, prevWhere.str());

    std::ostringstream errWhere;
    errWhere << e.label << ": " << e.sensorName << " ErrCount должен обнулиться при валидном чтении";
    check(e.sensor->ErrCount == 0, errWhere.str());
  }
}

int main() {
  set_sensor_labels();

  // Раунд 1: дельты 1.5/-2.0/0.0/3.25/-0.75, сырые 60/61/62/63/64.
  run_round("round1",
            1.5f, -2.0f, 0.0f, 3.25f, -0.75f,
            60.0f, 61.0f, 62.0f, 63.0f, 64.0f,
            61.5f, 59.0f, 62.0f, 66.25f, 63.25f);

  // Раунд 2: дельты -4.0/0.5/2.0/-1.25/5.0, сырые 70/71/72/73/74.
  run_round("round2",
            -4.0f, 0.5f, 2.0f, -1.25f, 5.0f,
            70.0f, 71.0f, 72.0f, 73.0f, 74.0f,
            66.0f, 71.5f, 74.0f, 71.75f, 79.0f);

  if (failures != 0) return 1;
  std::cout << "DS_getvalue per-sensor delta application checks passed\n";
  return 0;
}
'''


def build_harness(sensorinit_path: Path) -> str:
    source = sensorinit_path.read_text(encoding="utf-8")
    struct_start = source.find(STRUCT_MARKER)
    if struct_start < 0:
        raise ValueError(f"marker not found: {STRUCT_MARKER}")
    _, end = extract_braced_block_after(source, FUNCTION_MARKER)
    block = source[struct_start:end]
    return HARNESS_TEMPLATE.replace("@BODY@", block)


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-ds-getvalue-deltas-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "ds_getvalue_sensor_deltas_test.cpp"
        binary = temp / "ds_getvalue_sensor_deltas_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        harness = build_harness(ROOT / "sensorinit.h")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return compile_and_run(harness, "sensorinit.h")


if __name__ == "__main__":
    raise SystemExit(main())
