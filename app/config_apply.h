#ifndef __SAMOVAR_CONFIG_APPLY_H_
#define __SAMOVAR_CONFIG_APPLY_H_

#include "Samovar.h"
#include "state/globals.h"

void load_profile_nvs();
void CopyDSAddress(const uint8_t* DevSAddress, uint8_t* DevTAddress);
void init_impurity_detector();

void read_config() {
  load_profile_nvs();
  SteamSensor.SetTemp = SamSetup.SetSteamTemp;
  PipeSensor.SetTemp = SamSetup.SetPipeTemp;
  WaterSensor.SetTemp = SamSetup.SetWaterTemp;
  TankSensor.SetTemp = SamSetup.SetTankTemp;
  ACPSensor.SetTemp = SamSetup.SetACPTemp;
  SteamSensor.Delay = SamSetup.SteamDelay;
  PipeSensor.Delay = SamSetup.PipeDelay;
  WaterSensor.Delay = SamSetup.WaterDelay;
  TankSensor.Delay = SamSetup.TankDelay;
  ACPSensor.Delay = SamSetup.ACPDelay;
  if (SamSetup.HeaterResistant == 0) SamSetup.HeaterResistant = 10;
  if (SamSetup.LogPeriod == 0) SamSetup.LogPeriod = 3;
  if (SamSetup.autospeed >= 100) SamSetup.autospeed = 0;
  CopyDSAddress(SamSetup.SteamAdress, SteamSensor.Sensor);
  CopyDSAddress(SamSetup.PipeAdress, PipeSensor.Sensor);
  CopyDSAddress(SamSetup.WaterAdress, WaterSensor.Sensor);
  CopyDSAddress(SamSetup.TankAdress, TankSensor.Sensor);
  CopyDSAddress(SamSetup.ACPAdress, ACPSensor.Sensor);

  if (SamSetup.Mode > SAMOVAR_LUA_MODE) SamSetup.Mode = 0;
  Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;

  if (SamSetup.videourl[0] == 255) SamSetup.videourl[0] = '\0';
#ifdef SAMOVAR_USE_BLYNK
  if (strlen(SamSetup.videourl) > 0) Blynk.setProperty(V20, "url", (String)SamSetup.videourl);
  Blynk.virtualWrite(V15, ipst);
#else
  SamSetup.blynkauth[0] = '\0';
#endif

  if (isnan(SamSetup.Kp)) {
    SamSetup.Kp = 150;
  }
  if (isnan(SamSetup.Ki)) {
    SamSetup.Ki = 1.4;
  }
  if (isnan(SamSetup.Kd)) {
    SamSetup.Kd = 1.4;
  }
  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  if (isnan(SamSetup.StbVoltage)) {
    SamSetup.StbVoltage = 100;
  }

  if (isnan(SamSetup.BVolt)) {
    SamSetup.BVolt = 230;
  }

  if (isnan(SamSetup.SetWaterTemp) || SamSetup.SetWaterTemp == 0) SamSetup.SetWaterTemp = TARGET_WATER_TEMP;
  if (isnan(SamSetup.SetACPTemp) || SamSetup.SetACPTemp == 0) SamSetup.SetACPTemp = 43;
  if (isnan(SamSetup.DistTimeF)) {
    SamSetup.DistTimeF = 16;
  }
  if (isnan(SamSetup.MaxPressureValue)) {
    SamSetup.MaxPressureValue = 0;
  }

#ifdef USE_WATER_PUMP
  pump_regulator.setpoint = SamSetup.SetWaterTemp;
#endif

#ifdef IGNORE_HEAD_LEVEL_SENSOR_SETTING
  SamSetup.UseHLS = true;
#endif

#ifdef USE_TELEGRAM
  if (SamSetup.tg_token[0] == 255) {
    SamSetup.tg_token[0] = '\0';
  }
  if (SamSetup.tg_chat_id[0] == 255) {
    SamSetup.tg_chat_id[0] = '\0';
  }
#else
  SamSetup.tg_token[0] = '\0';
  SamSetup.tg_chat_id[0] = '\0';
#endif
  init_impurity_detector();
}

#endif
