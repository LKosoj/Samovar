#pragma once

#include <math.h>
#include <stdint.h>

#ifdef __SAMOVAR_DEBUG

#ifndef DEBUG_DS_AMBIENT_TEMP
#define DEBUG_DS_AMBIENT_TEMP 22.0f
#endif

inline float debug_ds_clamp(float value, float lo, float hi) {
  if (value < lo) return lo;
  if (value > hi) return hi;
  return value;
}

inline float debug_ds_quantize(float tempC) {
  return floorf(tempC * 16.0f + 0.5f) / 16.0f;
}

inline float debug_ds_approach(float current, float target, float rate) {
  rate = debug_ds_clamp(rate, 0.0f, 1.0f);
  return current + (target - current) * rate;
}

inline void debug_ds_copy_fake_address(uint8_t* dest, uint8_t index) {
  static const uint8_t kFake[5][8] = {
      {0x28, 0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01},
      {0x28, 0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02},
      {0x28, 0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03},
      {0x28, 0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x04},
      {0x28, 0xD1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05},
  };
  if (dest == nullptr || index >= DS_SENSOR_COUNT) return;
  for (uint8_t j = 0; j < 8; j++) dest[j] = kFake[index][j];
}

inline void debug_ds_fill_missing_found_addresses(DeviceAddress foundAddr[], uint8_t& dc) {
  while (dc < DS_SENSOR_COUNT) {
    debug_ds_copy_fake_address(foundAddr[dc], dc);
    dc++;
  }
}

inline void debug_ds_bind_runtime_sensors() {
  uint8_t* setupAddrs[DS_SENSOR_COUNT] = {
      SamSetup.SteamAdress,
      SamSetup.PipeAdress,
      SamSetup.WaterAdress,
      SamSetup.TankAdress,
      SamSetup.ACPAdress,
  };
  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
    if (sensorList[i]->Sensor[0] == 0xFF) {
      debug_ds_copy_fake_address(sensorList[i]->Sensor, i);
      debug_ds_copy_fake_address(setupAddrs[i], i);
    }
    if (sensorList[i]->avgTemp < 2.0f) {
      const float ambient = DEBUG_DS_AMBIENT_TEMP;
      sensorList[i]->avgTemp = ambient;
      sensorList[i]->PrevTemp = ambient;
      sensorList[i]->ErrCount = 0;
    }
  }
}

inline float debug_ds_heat_fraction() {
  float heat = 0.0f;
  if (PowerOn) {
    float volt = current_power_volt;
    if (volt < 1.0f) volt = target_power_volt;
    float scale = SamSetup.MainsVoltage;
    if (scale < 50.0f) scale = 220.0f;
    if (volt < 1.0f) heat = 1.0f;
    else heat = debug_ds_clamp(volt / scale, 0.0f, 1.0f);
  }
  if (heater_state && heat < 0.6f) heat = 0.6f;
  if (acceleration_heater) heat = 1.0f;
  return heat;
}

inline void debug_ds_mode_limits(
    float& tankMax,
    float& steamMax,
    float& pipeMax,
    float& tankRate,
    float& steamRate,
    float& pipeRate) {
  switch (Samovar_Mode) {
    case SAMOVAR_BEER_MODE:
    case SAMOVAR_SUVID_MODE:
      tankMax = 100.0f;
      steamMax = 78.0f;
      pipeMax = 70.0f;
      tankRate = 0.038f;
      steamRate = 0.012f;
      pipeRate = 0.010f;
      break;
    case SAMOVAR_DISTILLATION_MODE:
      tankMax = 99.4f;
      steamMax = 95.0f;
      pipeMax = 88.0f;
      tankRate = 0.032f;
      steamRate = 0.022f;
      pipeRate = 0.018f;
      break;
    case SAMOVAR_NBK_MODE:
      tankMax = 99.0f;
      steamMax = 93.0f;
      pipeMax = 86.0f;
      tankRate = 0.030f;
      steamRate = 0.020f;
      pipeRate = 0.016f;
      break;
    case SAMOVAR_BK_MODE:
      tankMax = 98.5f;
      steamMax = 92.0f;
      pipeMax = 85.0f;
      tankRate = 0.030f;
      steamRate = 0.018f;
      pipeRate = 0.015f;
      break;
    case SAMOVAR_RECTIFICATION_MODE:
    case SAMOVAR_LUA_MODE:
    default:
      tankMax = 96.0f;
      steamMax = 79.0f;
      pipeMax = 82.0f;
      tankRate = 0.028f;
      steamRate = 0.016f;
      pipeRate = 0.014f;
      break;
  }
}

inline void debug_ds_emulate_temperatures() {
  debug_ds_bind_runtime_sensors();

  const float heat = debug_ds_heat_fraction();
  float tankMax, steamMax, pipeMax, tankRate, steamRate, pipeRate;
  debug_ds_mode_limits(tankMax, steamMax, pipeMax, tankRate, steamRate, pipeRate);

  float tankTarget = DEBUG_DS_AMBIENT_TEMP;
  float steamTarget = DEBUG_DS_AMBIENT_TEMP;
  float pipeTarget = DEBUG_DS_AMBIENT_TEMP;
  float waterTarget = DEBUG_DS_AMBIENT_TEMP;
  float acpTarget = DEBUG_DS_AMBIENT_TEMP;
  float waterRate = 0.008f;
  float acpRate = 0.008f;

  if (heat > 0.0f) {
    tankTarget = DEBUG_DS_AMBIENT_TEMP + heat * (tankMax - DEBUG_DS_AMBIENT_TEMP);
    const float tankNow = TankSensor.avgTemp;
    const float steamGate = debug_ds_clamp((tankNow - 35.0f) / 50.0f, 0.0f, 1.0f);
    steamTarget = DEBUG_DS_AMBIENT_TEMP + heat * steamGate * (steamMax - DEBUG_DS_AMBIENT_TEMP);
    pipeTarget = DEBUG_DS_AMBIENT_TEMP + heat * steamGate * (pipeMax - DEBUG_DS_AMBIENT_TEMP);
    if (valve_status) {
      waterTarget = DEBUG_DS_AMBIENT_TEMP + 8.0f + heat * 18.0f;
      waterRate = 0.025f;
    } else {
      waterTarget = DEBUG_DS_AMBIENT_TEMP + heat * 28.0f;
      waterRate = 0.010f;
    }
    acpTarget = DEBUG_DS_AMBIENT_TEMP + heat * 10.0f + steamGate * heat * 12.0f;
    acpRate = 0.012f;
  } else {
    tankRate = steamRate = pipeRate = 0.010f;
  }

  TankSensor.avgTemp = debug_ds_quantize(debug_ds_approach(TankSensor.avgTemp, tankTarget, tankRate));
  SteamSensor.avgTemp = debug_ds_quantize(debug_ds_approach(SteamSensor.avgTemp, steamTarget, steamRate));
  PipeSensor.avgTemp = debug_ds_quantize(debug_ds_approach(PipeSensor.avgTemp, pipeTarget, pipeRate));
  WaterSensor.avgTemp = debug_ds_quantize(debug_ds_approach(WaterSensor.avgTemp, waterTarget, waterRate));
  ACPSensor.avgTemp = debug_ds_quantize(debug_ds_approach(ACPSensor.avgTemp, acpTarget, acpRate));

  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
    sensorList[i]->PrevTemp = sensorList[i]->avgTemp;
    sensorList[i]->ErrCount = 0;
  }
}

#endif
