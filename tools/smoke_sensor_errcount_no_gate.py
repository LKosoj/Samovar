#!/usr/bin/env python3
"""Поведенческая проверка [П17]: датчик, ни разу не ответивший с самого
старта, обязан набирать ErrCount, а не застревать на 0 навсегда.

sensorinit.h::DS_getvalue() раньше растил DSSensor.ErrCount только под
условием "sensor.PrevTemp > 0" - датчик, у которого PrevTemp==0 (ни разу не
было успешного чтения), никогда не набирал ErrCount, и защита держалась
только на побочном эффекте avgTemp==0 (alarm.h::sensor_reading_valid требует
avgTemp>=2.0f). Тест вытаскивает РЕАЛЬНОЕ тело DS_getvalue() (sensorinit.h) и
sensor_reading_valid()/sensor_valid() (alarm.h) через smoke_helpers и
подставляет в минимальный host-харнесс (тот же приём, что и в
smoke_ds_getvalue_sensor_deltas.py) - логика не переписывается, только
подставляется заглушка sensors.getTempC(), различающая датчики по метке.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

STRUCT_MARKER = "struct SensorDeltaField {"
DS_GETVALUE_MARKER = "void DS_getvalue(void)"
VALID_SIGNATURE = "inline bool sensor_reading_valid"

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

// Заглушка датчика: значение читаем по метке (Sensor[0]), не константа.
struct SensorsStub {
  float readings[DS_SENSOR_COUNT] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
  float getTempC(const uint8_t* addr) { return readings[addr[0]]; }
  void requestTemperatures() {}
};
static SensorsStub sensors;

@DS_GETVALUE_BODY@

inline bool sensor_reading_valid(const DSSensor& sensor) {@VALID_BODY@}

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

static void reset_all(float raw) {
  SteamSensor = DSSensor();
  PipeSensor = DSSensor();
  WaterSensor = DSSensor();
  TankSensor = DSSensor();
  ACPSensor = DSSensor();
  set_sensor_labels();
  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) sensors.readings[i] = raw;
}

int main() {
  set_sensor_labels();

  // --- РЕГРЕСС: датчик, ни разу не ответивший с самого старта (PrevTemp==0
  // изначально), обязан набирать ErrCount, а не застревать на 0 навсегда. ---
  reset_all(-55.0f);  // < -10 => неудачное чтение для всех пяти датчиков
  for (int tick = 1; tick <= 11; tick++) {
    DS_getvalue();
    check(SteamSensor.ErrCount == tick,
          "датчик, ни разу не ответивший, обязан копить ErrCount на каждом тике");
  }
  check(SteamSensor.ErrCount > 10, "после 11 неудач подряд ErrCount обязан превысить порог 10");

  // --- Регрессия отсутствует: sensor_valid()/sensor_reading_valid() и до, и
  // после правки возвращают false на каждом тике (наблюдаемое поведение не
  // изменилось - до правки это держалось на avgTemp==0, теперь ещё и на
  // ErrCount). ---
  reset_all(-55.0f);
  for (int tick = 1; tick <= 11; tick++) {
    DS_getvalue();
    check(!sensor_reading_valid(SteamSensor),
          "невалидный датчик обязан оставаться невалидным на каждом тике (регрессия)");
  }

  // --- Обычный сценарий: успех -> 3 сбоя -> успех обнуляет счётчик. ---
  reset_all(60.0f);
  DS_getvalue();
  check(SteamSensor.ErrCount == 0, "успешное чтение должно дать ErrCount==0");
  check(sensor_reading_valid(SteamSensor), "успешное чтение с валидной температурой обязано быть валидным");

  sensors.readings[0] = -55.0f;
  for (int tick = 1; tick <= 3; tick++) {
    DS_getvalue();
    check(SteamSensor.ErrCount == tick, "3 сбоя подряд после успеха должны копиться с нуля");
  }

  sensors.readings[0] = 61.0f;
  DS_getvalue();
  check(SteamSensor.ErrCount == 0, "успешное чтение после серии сбоев обязано обнулить ErrCount");
  check(sensor_reading_valid(SteamSensor), "после восстановления датчик снова обязан быть валидным");

  if (failures != 0) return 1;
  std::cout << "sensor ErrCount no-gate behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    sensorinit_source = (ROOT / "sensorinit.h").read_text(encoding="utf-8")
    alarm_source = (ROOT / "alarm.h").read_text(encoding="utf-8")

    struct_start = sensorinit_source.find(STRUCT_MARKER)
    if struct_start < 0:
        raise ValueError(f"marker not found: {STRUCT_MARKER}")
    _, end = extract_braced_block_after(sensorinit_source, DS_GETVALUE_MARKER)
    ds_getvalue_block = sensorinit_source[struct_start:end]

    valid_body = extract_function_body(alarm_source, VALID_SIGNATURE)

    harness = HARNESS_TEMPLATE.replace("@DS_GETVALUE_BODY@", ds_getvalue_block)
    harness = harness.replace("@VALID_BODY@", valid_body)
    return harness


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-sensor-errcount-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "sensor_errcount_no_gate_test.cpp"
        binary = temp / "sensor_errcount_no_gate_test"
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
            sys.stderr.write("compile failed:\n")
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
