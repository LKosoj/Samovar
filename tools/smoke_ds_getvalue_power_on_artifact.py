#!/usr/bin/env python3
"""Поведенческая проверка [T32]: заводской артефакт DS18B20 "85.0°C сразу
после сбоя питания" отбрасывается, но НЕ ценой ослепления датчика на реальных
85°C в кубе и не ценой протухания показания на холодном старте.

До правки DS_getvalue() (sensorinit.h) принимал 85.0 как обычную температуру:
после сброса питания датчик застревал бы на 85.0 навсегда, а авария "нет
данных с датчика" не срабатывала бы (ErrCount не рос). Тест вытаскивает
РЕАЛЬНОЕ тело DS_getvalue() (extract_braced_block_after от
"struct SensorDeltaField {" до конца функции - тот же приём, что и в
smoke_ds_getvalue_sensor_deltas.py / smoke_sensor_errcount_no_gate.py) и
подставляет в минимальный host-харнесс. Логика не переписывается.

Отдельно (сценарии 6-8) проверяется ОТКРЫТЫЙ ВОПРОС из задачи T32: raw[i] в
DS_getvalue() уже содержит поправку на атмосферное давление (correctT) для
части датчиков, а дельта пользователя (SamSetup.Delta*Temp) добавляется
отдельно. Если реализация ошибочно сравнивает с 85.0 уже подправленное
значение, проверка становится МЁРТВОЙ при ненулевой поправке/дельте - именно
это ловят сценарии 6 и 7. Сценарий 8 проверяет, что скачок >10°C считается
именно ПРОТИВ итогового (с поправками) значения, а не против сырого - иначе
при ненулевой дельте порог скачка сам даёт неверный вердикт.
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
// kSensorDeltaFields осталась бы незамеченной.
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

static void reset_sensors() {
  SteamSensor = DSSensor();
  PipeSensor = DSSensor();
  WaterSensor = DSSensor();
  TankSensor = DSSensor();
  ACPSensor = DSSensor();
  SteamSensor.Sensor[0] = 0;
  PipeSensor.Sensor[0] = 1;
  WaterSensor.Sensor[0] = 2;
  TankSensor.Sensor[0] = 3;
  ACPSensor.Sensor[0] = 4;
  SamSetup = SetupEEPROM();
  PowerOn = false;
  bme_pressure = 0.0f;
  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) sensors.readings[i] = 0.0f;
}

int main() {
  // --- 1: датчик сбросился на 60, пришло 85.0 (скачок 25°C) -> отклонено ---
  reset_sensors();
  SteamSensor.avgTemp = 60.0f;
  sensors.readings[0] = 85.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 60.0f) < 1e-4,
        "сценарий 1: скачок 60->85 обязан быть отклонён, avgTemp должен остаться 60.0");
  check(SteamSensor.ErrCount == 1,
        "сценарий 1: отклонённое чтение обязано растить ErrCount");

  // --- 2: куб реально нагрет до 84, пришло 85.0 (скачок 1°C) -> принято ---
  reset_sensors();
  SteamSensor.avgTemp = 84.0f;
  sensors.readings[0] = 85.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 85.0f) < 1e-4,
        "сценарий 2: реальные 85°C в кубе (скачок 1°C) обязаны быть приняты");
  check(SteamSensor.ErrCount == 0,
        "сценарий 2: принятое чтение обязано обнулить ErrCount");

  // --- 3: холодный старт (avgTemp не набран), пришло 85.0 -> принято ---
  reset_sensors();
  sensors.readings[0] = 85.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 85.0f) < 1e-4,
        "сценарий 3: холодный старт обязан принять первое чтение 85.0, иначе avgTemp никогда не наберётся");
  check(SteamSensor.ErrCount == 0,
        "сценарий 3: принятое чтение обязано обнулить ErrCount");

  // --- 4: цепочка 25 -> 85 -> 25: итог avgTemp=25.0, 85 не зафиксировалось базой ---
  reset_sensors();
  sensors.readings[0] = 25.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 25.0f) < 1e-4, "цепочка 25->85->25, такт1: ожидался 25.0");
  sensors.readings[0] = 85.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 25.0f) < 1e-4,
        "цепочка 25->85->25, такт2: 85 отклонён, avgTemp должен остаться 25.0");
  check(SteamSensor.ErrCount == 1, "цепочка 25->85->25, такт2: ErrCount должен вырасти");
  sensors.readings[0] = 25.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 25.0f) < 1e-4, "цепочка 25->85->25, такт3: итог должен остаться 25.0");
  check(SteamSensor.ErrCount == 0, "цепочка 25->85->25, такт3: ErrCount должен обнулиться");

  // --- 5: цепочка 84 -> 85 -> 86: все приняты, итог avgTemp=86.0 ---
  reset_sensors();
  sensors.readings[0] = 84.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 84.0f) < 1e-4, "цепочка 84->85->86, такт1: ожидался 84.0");
  sensors.readings[0] = 85.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 85.0f) < 1e-4, "цепочка 84->85->86, такт2: 85 принят (скачок 1)");
  sensors.readings[0] = 86.0f;
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 86.0f) < 1e-4, "цепочка 84->85->86, такт3: 86 принят, итог 86.0");
  check(SteamSensor.ErrCount == 0, "цепочка 84->85->86: ErrCount должен быть 0 в конце");

  // --- 6 (ОТКРЫТЫЙ ВОПРОС T32): сравнение с 85.0 обязано идти по СЫРОМУ
  // значению (до дельты пользователя). Дельта=3: (85+дельта)=88 не близко к
  // 85.0, поэтому наивная проверка "по подправленному значению" была бы
  // мёртвой и приняла бы артефакт как настоящий скачок на 88. ---
  reset_sensors();
  SamSetup.DeltaSteamTemp = 3.0f;
  SteamSensor.avgTemp = 63.0f;  // прежде принято: сырое 60 + дельта 3
  sensors.readings[0] = 85.0f;  // сырое ровно 85.0 - артефакт
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 63.0f) < 1e-4,
        "сценарий 6 (дельта): артефакт обязан ловиться по сырому значению, а не по (85+дельта)=88; avgTemp должен остаться 63.0");
  check(SteamSensor.ErrCount == 1, "сценарий 6 (дельта): отклонённое чтение обязано растить ErrCount");

  // --- 7 (ОТКРЫТЫЙ ВОПРОС T32): то же самое для поправки на атмосферное
  // давление (correctT), которая применяется РАНЬШЕ дельты. ---
  reset_sensors();
  SamSetup.UsePreccureCorrect = true;
  PowerOn = true;
  bme_pressure = 730.0f;  // correctT = (760-730)*0.037 = 1.11
  SteamSensor.avgTemp = 60.0f;
  sensors.readings[0] = 85.0f;  // сырое ровно 85.0 - артефакт, до correctT
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 60.0f) < 1e-4,
        "сценарий 7 (давление): артефакт обязан ловиться по сырому значению, а не по (85+correctT)=86.11; avgTemp должен остаться 60.0");
  check(SteamSensor.ErrCount == 1, "сценарий 7 (давление): отклонённое чтение обязано растить ErrCount");

  // --- 8: скачок >10°C обязан считаться С УЧЁТОМ дельты (против итогового
  // значения), а не по сырому raw[i] - иначе порог скачка сам ошибается. ---
  reset_sensors();
  SamSetup.DeltaSteamTemp = 15.0f;
  SteamSensor.avgTemp = 96.0f;  // прежде принято: сырое 81 + дельта 15
  sensors.readings[0] = 85.0f;  // сырое 85.0 похоже на артефакт, но с дельтой скачок мал: |85+15-96|=4
  DS_getvalue();
  check(std::fabs(SteamSensor.avgTemp - 100.0f) < 1e-4,
        "сценарий 8: скачок обязан считаться с учётом дельты (4°C, малый) и быть принят, avgTemp должен стать 100.0");
  check(SteamSensor.ErrCount == 0, "сценарий 8: принятое чтение обязано обнулить ErrCount");

  if (failures != 0) return 1;
  std::cout << "DS_getvalue 85.0 power-on artifact checks passed\n";
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
    with tempfile.TemporaryDirectory(prefix="samovar-ds-getvalue-artifact-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "ds_getvalue_power_on_artifact_test.cpp"
        binary = temp / "ds_getvalue_power_on_artifact_test"
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
