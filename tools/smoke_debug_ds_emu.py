#!/usr/bin/env python3
"""Эмуляция DS18B20 при __SAMOVAR_DEBUG: адреса, валидные показания, рост с нагревом."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

using DeviceAddress = uint8_t[8];

enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE
};

struct DSSensor {
  DeviceAddress Sensor;
  volatile float avgTemp;
  float PrevTemp;
  volatile int ErrCount;
};

struct SetupEEPROM {
  uint8_t SteamAdress[8];
  uint8_t PipeAdress[8];
  uint8_t WaterAdress[8];
  uint8_t TankAdress[8];
  uint8_t ACPAdress[8];
  float MainsVoltage;
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
static bool PowerOn = false;
static bool heater_state = false;
static bool acceleration_heater = false;
static bool valve_status = false;
static float current_power_volt = 0.0f;
static float target_power_volt = 0.0f;
static SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;

#define __SAMOVAR_DEBUG
#include "debug_ds_emu.h"

static int failures = 0;

static void fail(const std::string& message) {
  std::cerr << "FAIL: " << message << '\n';
  failures++;
}

static void check(bool ok, const std::string& message) {
  if (!ok) fail(message);
}

static void reset_sensors_unassigned() {
  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
    for (uint8_t j = 0; j < 8; j++) sensorList[i]->Sensor[j] = 0xFF;
    sensorList[i]->avgTemp = 0;
    sensorList[i]->PrevTemp = 0;
    sensorList[i]->ErrCount = 10;
  }
  for (uint8_t j = 0; j < 8; j++) {
    SamSetup.SteamAdress[j] = 0xFF;
    SamSetup.PipeAdress[j] = 0xFF;
    SamSetup.WaterAdress[j] = 0xFF;
    SamSetup.TankAdress[j] = 0xFF;
    SamSetup.ACPAdress[j] = 0xFF;
  }
  SamSetup.MainsVoltage = 220.0f;
  PowerOn = false;
  heater_state = false;
  acceleration_heater = false;
  valve_status = false;
  current_power_volt = 0.0f;
  target_power_volt = 0.0f;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
}

static void ticks(int n) {
  for (int i = 0; i < n; i++) debug_ds_emulate_temperatures();
}

int main() {
  DeviceAddress found[6];
  for (uint8_t i = 0; i < 6; i++)
    for (uint8_t j = 0; j < 8; j++) found[i][j] = 0xFF;
  uint8_t dc = 0;
  debug_ds_fill_missing_found_addresses(found, dc);
  check(dc == DS_SENSOR_COUNT, "fill must provide five emulated DS addresses");
  check(found[0][0] == 0x28 && found[4][0] == 0x28, "emulated ROM family must be DS18B20");
  check(found[0][7] != found[1][7], "emulated addresses must be unique");

  reset_sensors_unassigned();
  debug_ds_bind_runtime_sensors();
  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
    check(sensorList[i]->Sensor[0] != 0xFF, "bind must configure every sensor");
    check(sensorList[i]->avgTemp >= 2.0f, "bind must start with a valid temperature");
    check(sensorList[i]->ErrCount == 0, "bind must clear ErrCount");
  }
  check(SamSetup.TankAdress[0] != 0xFF, "bind must fill SamSetup tank address");

  reset_sensors_unassigned();
  debug_ds_bind_runtime_sensors();
  const float idleTank = TankSensor.avgTemp;
  ticks(30);
  check(std::fabs(TankSensor.avgTemp - idleTank) < 0.5f,
        "without heat tank temperature must stay near ambient");

  reset_sensors_unassigned();
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  PowerOn = true;
  current_power_volt = 220.0f;
  target_power_volt = 220.0f;
  ticks(40);
  const float rectTank = TankSensor.avgTemp;
  const float rectSteam = SteamSensor.avgTemp;
  check(rectTank > idleTank + 5.0f, "rectification + voltage must heat the tank");
  check(WaterSensor.avgTemp < 70.0f, "water must stay below alarm threshold");
  check(ACPSensor.avgTemp < 70.0f, "ACP must stay below alarm threshold");
  check(rectSteam < 98.8f, "rectification steam must stay below MAX_STEAM_TEMP");

  reset_sensors_unassigned();
  PowerOn = true;
  current_power_volt = 110.0f;
  target_power_volt = 110.0f;
  ticks(40);
  const float lowVoltTank = TankSensor.avgTemp;

  reset_sensors_unassigned();
  PowerOn = true;
  current_power_volt = 220.0f;
  target_power_volt = 220.0f;
  ticks(40);
  check(TankSensor.avgTemp > lowVoltTank + 1.0f,
        "higher voltage must heat the tank faster");

  SAMOVAR_MODE modes[] = {
      SAMOVAR_DISTILLATION_MODE,
      SAMOVAR_BEER_MODE,
      SAMOVAR_BK_MODE,
      SAMOVAR_NBK_MODE,
      SAMOVAR_SUVID_MODE,
  };
  for (SAMOVAR_MODE mode : modes) {
    reset_sensors_unassigned();
    Samovar_Mode = mode;
    PowerOn = true;
    current_power_volt = 200.0f;
    target_power_volt = 200.0f;
    if (mode == SAMOVAR_BEER_MODE || mode == SAMOVAR_SUVID_MODE) heater_state = true;
    ticks(40);
    if (!(TankSensor.avgTemp > 30.0f)) {
      fail(std::string("mode ") + std::to_string((int)mode) + " tank did not rise with voltage");
    }
  }

  reset_sensors_unassigned();
  PowerOn = true;
  current_power_volt = 0.0f;
  target_power_volt = 0.0f;
  ticks(20);
  check(TankSensor.avgTemp > 25.0f, "PowerOn without regulator voltage must still heat");

  if (failures != 0) return 1;
  std::cout << "debug DS emulation checks passed\n";
  return 0;
}
'''


def source_contract() -> list[str]:
    errors = []
    sensorinit = (ROOT / "sensorinit.h").read_text(encoding="utf-8")
    samovar_ino = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    header = (ROOT / "Samovar.h").read_text(encoding="utf-8")
    if '#include "debug_ds_emu.h"' not in sensorinit:
        errors.append("sensorinit.h must include debug_ds_emu.h")
    for token in (
        "debug_ds_fill_missing_found_addresses(foundAddr, dc);",
        "debug_ds_emulate_temperatures();",
        "debug_ds_bind_runtime_sensors();",
    ):
        if token not in sensorinit:
            errors.append(f"sensorinit.h missing {token}")
    if "debug_ds_bind_runtime_sensors();" not in samovar_ino:
        errors.append("apply_setup_sensor_fields must re-bind emulated sensors")
    if "__SAMOVAR_DEBUG" not in header:
        errors.append("Samovar.h lost __SAMOVAR_DEBUG")
    return errors


def main() -> int:
    errors = source_contract()
    if errors:
        for item in errors:
            print(f"FAIL: {item}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-debug-ds-emu-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "debug_ds_emu_test.cpp"
        binary = temp / "debug_ds_emu_test"
        source.write_text(HARNESS, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{ROOT}",
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
