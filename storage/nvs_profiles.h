#ifndef __SAMOVAR_NVS_PROFILES_H_
#define __SAMOVAR_NVS_PROFILES_H_

#include <Arduino.h>
#include <Preferences.h>

#include "Samovar.h"
#include "state/globals.h"
#include "support/safe_parse.h"

inline Preferences& nvs_preferences() {
  static Preferences prefs;
  return prefs;
}

inline const char* profile_namespace_by_mode(int mode) {
  return mode_profile_namespace((SAMOVAR_MODE)mode);
}

inline const char* current_profile_namespace() {
  int mode = (int)Samovar_CR_Mode;
  if (mode < SAMOVAR_RECTIFICATION_MODE || mode > SAMOVAR_LUA_MODE) {
    mode = SAMOVAR_RECTIFICATION_MODE;
  }
  return profile_namespace_by_mode(mode);
}

inline uint8_t read_last_mode_meta() {
  Preferences meta;
  if (!meta.begin("sam_meta", true)) {
    return (uint8_t)SAMOVAR_RECTIFICATION_MODE;
  }
  uint8_t lastMode = meta.getUChar("last_mode", (uint8_t)SAMOVAR_RECTIFICATION_MODE);
  meta.end();
  if (lastMode > (uint8_t)SAMOVAR_LUA_MODE) {
    lastMode = (uint8_t)SAMOVAR_RECTIFICATION_MODE;
  }
  return lastMode;
}

inline void write_last_mode_meta(uint8_t mode) {
  if (mode > (uint8_t)SAMOVAR_LUA_MODE) {
    mode = (uint8_t)SAMOVAR_RECTIFICATION_MODE;
  }
  Preferences meta;
  if (!meta.begin("sam_meta", false)) {
    return;
  }
  meta.putUChar("last_mode", mode);
  meta.end();
}

inline void saveStringIfChanged(const char* key, const char* value) {
  Preferences& prefs = nvs_preferences();
  String current = prefs.getString(key, "");
  if (current != String(value)) {
    prefs.putString(key, String(value));
  }
}

inline void saveBytesIfChanged(const char* key, const void* value, size_t len) {
  Preferences& prefs = nvs_preferences();
  uint8_t buf[len];
  size_t readLen = prefs.getBytes(key, buf, len);
  if (readLen != len || memcmp(buf, value, len) != 0) {
    prefs.putBytes(key, value, len);
  }
}

inline void save_profile_nvs() {
  Preferences& prefs = nvs_preferences();
  if (!prefs.begin(current_profile_namespace(), false)) {
    Serial.println("NVS: Failed to open namespace for writing!");
    return;
  }

  // --- Основные настройки ---
  prefs.putUChar("flag", SamSetup.flag);
  prefs.putUShort("Mode", SamSetup.Mode);
  prefs.putUChar("TimeZone", SamSetup.TimeZone);
  prefs.putFloat("HeaterR", SamSetup.HeaterResistant);
  prefs.putUChar("LogPeriod", SamSetup.LogPeriod);

  // --- Температурные настройки (Set) ---
  prefs.putFloat("SetSteam", SamSetup.SetSteamTemp);
  prefs.putFloat("SetPipe", SamSetup.SetPipeTemp);
  prefs.putFloat("SetWater", SamSetup.SetWaterTemp);
  prefs.putFloat("SetTank", SamSetup.SetTankTemp);
  prefs.putFloat("SetACP", SamSetup.SetACPTemp);
  prefs.putFloat("DistTemp", SamSetup.DistTemp);

  // --- Температурные настройки (Delta) ---
  prefs.putFloat("DeltaSteam", SamSetup.DeltaSteamTemp);
  prefs.putFloat("DeltaPipe", SamSetup.DeltaPipeTemp);
  prefs.putFloat("DeltaWater", SamSetup.DeltaWaterTemp);
  prefs.putFloat("DeltaTank", SamSetup.DeltaTankTemp);
  prefs.putFloat("DeltaACP", SamSetup.DeltaACPTemp);

  // --- Задержки (Delays) ---
  prefs.putUShort("SteamDelay", SamSetup.SteamDelay);
  prefs.putUShort("PipeDelay", SamSetup.PipeDelay);
  prefs.putUShort("WaterDelay", SamSetup.WaterDelay);
  prefs.putUShort("TankDelay", SamSetup.TankDelay);
  prefs.putUShort("ACPDelay", SamSetup.ACPDelay);

  // --- Шаговик и настройки насоса ---
  prefs.putUShort("StepMl", SamSetup.StepperStepMl);
  prefs.putUShort("StepMlI2C", SamSetup.StepperStepMlI2C);
  prefs.putBool("AutoSpeed", SamSetup.useautospeed);
  prefs.putBool("DetOnHeads", SamSetup.useDetectorOnHeads);
  prefs.putUChar("SpeedPerc", SamSetup.autospeed);
  prefs.putBool("UseWS", SamSetup.UseWS);

  // --- PID и Power ---
  prefs.putFloat("Kp", SamSetup.Kp);
  prefs.putFloat("Ki", SamSetup.Ki);
  prefs.putFloat("Kd", SamSetup.Kd);
  prefs.putFloat("StbVolt", SamSetup.StbVoltage);
  prefs.putFloat("BVolt", SamSetup.BVolt);
  prefs.putBool("CheckPwr", SamSetup.CheckPower);
  prefs.putBool("UseST", SamSetup.UseST);

  // --- Реле ---
  prefs.putBool("rele1", SamSetup.rele1);
  prefs.putBool("rele2", SamSetup.rele2);
  prefs.putBool("rele3", SamSetup.rele3);
  prefs.putBool("rele4", SamSetup.rele4);

  // --- Адреса датчиков (Bytes) ---
  saveBytesIfChanged("SteamAddr", SamSetup.SteamAdress, 8);
  saveBytesIfChanged("PipeAddr", SamSetup.PipeAdress, 8);
  saveBytesIfChanged("WaterAddr", SamSetup.WaterAdress, 8);
  saveBytesIfChanged("TankAddr", SamSetup.TankAdress, 8);
  saveBytesIfChanged("ACPAddr", SamSetup.ACPAdress, 8);

  // --- Строки (Цвета, URL, Токены) ---
  saveStringIfChanged("SteamCol", SamSetup.SteamColor);
  saveStringIfChanged("PipeCol", SamSetup.PipeColor);
  saveStringIfChanged("WaterCol", SamSetup.WaterColor);
  saveStringIfChanged("TankCol", SamSetup.TankColor);
  saveStringIfChanged("ACPCol", SamSetup.ACPColor);

  saveStringIfChanged("blynk", SamSetup.blynkauth);
  saveStringIfChanged("video", SamSetup.videourl);
  saveStringIfChanged("tg_tok", SamSetup.tg_token);
  saveStringIfChanged("tg_id", SamSetup.tg_chat_id);

  // --- Доп настройки ---
  prefs.putBool("Preccure", SamSetup.UsePreccureCorrect);
  prefs.putBool("PrgBuzz", SamSetup.ChangeProgramBuzzer);
  prefs.putBool("UseBuzz", SamSetup.UseBuzzer);
  prefs.putBool("UseBBuzz", SamSetup.UseBBuzzer);
  prefs.putUChar("DistTimeF", SamSetup.DistTimeF);
  prefs.putBool("UseHLS", SamSetup.UseHLS);
  prefs.putFloat("MaxPress", SamSetup.MaxPressureValue);

  // --- НБК настройки ---
  prefs.putFloat("NbkIn", SamSetup.NbkIn);
  prefs.putFloat("NbkDelta", SamSetup.NbkDelta);
  prefs.putFloat("NbkDM", SamSetup.NbkDM);
  prefs.putFloat("NbkDP", SamSetup.NbkDP);
  prefs.putFloat("NbkSteamT", SamSetup.NbkSteamT);
  prefs.putFloat("NbkOwPress", SamSetup.NbkOwPress);

  // --- Параметры колонны ---
  prefs.putFloat("ColDiam", SamSetup.ColDiam);
  prefs.putFloat("ColHeight", SamSetup.ColHeight);
  prefs.putUChar("PackDens", SamSetup.PackDens);

  prefs.end();
  write_last_mode_meta((uint8_t)SamSetup.Mode);
  //Serial.println("Profile saved to NVS");
}

inline void load_profile_nvs() {
  Preferences& prefs = nvs_preferences();
  uint8_t lastMode = read_last_mode_meta();
  Samovar_CR_Mode = (SAMOVAR_MODE)lastMode;

  if (!prefs.begin(current_profile_namespace(), true)) {
    Serial.println("NVS: Failed to open namespace for reading!");
    return;
  }

  // Читаем с дефолтными значениями. Для flag используем 255, чтобы определить "пустой NVS"
  SamSetup.flag = prefs.getUChar("flag", 255);
  SamSetup.Mode = prefs.getUShort("Mode", 0);
  SamSetup.TimeZone = prefs.getUChar("TimeZone", 3);
  SamSetup.HeaterResistant = prefs.getFloat("HeaterR", 10.0);
  SamSetup.LogPeriod = prefs.getUChar("LogPeriod", 3);

  SamSetup.SetSteamTemp = prefs.getFloat("SetSteam", 0);
  SamSetup.SetPipeTemp = prefs.getFloat("SetPipe", 0);
  SamSetup.SetWaterTemp = prefs.getFloat("SetWater", 0);
  SamSetup.SetTankTemp = prefs.getFloat("SetTank", 0);
  SamSetup.SetACPTemp = prefs.getFloat("SetACP", 0);
  SamSetup.DistTemp = prefs.getFloat("DistTemp", 0);

  SamSetup.DeltaSteamTemp = prefs.getFloat("DeltaSteam", 0);
  SamSetup.DeltaPipeTemp = prefs.getFloat("DeltaPipe", 0);
  SamSetup.DeltaWaterTemp = prefs.getFloat("DeltaWater", 0);
  SamSetup.DeltaTankTemp = prefs.getFloat("DeltaTank", 0);
  SamSetup.DeltaACPTemp = prefs.getFloat("DeltaACP", 0);

  SamSetup.SteamDelay = prefs.getUShort("SteamDelay", 0);
  SamSetup.PipeDelay = prefs.getUShort("PipeDelay", 0);
  SamSetup.WaterDelay = prefs.getUShort("WaterDelay", 0);
  SamSetup.TankDelay = prefs.getUShort("TankDelay", 0);
  SamSetup.ACPDelay = prefs.getUShort("ACPDelay", 0);

  SamSetup.StepperStepMl = prefs.getUShort("StepMl", STEPPER_STEP_ML);
  SamSetup.StepperStepMlI2C = prefs.getUShort("StepMlI2C", I2C_STEPPER_STEP_ML_DEFAULT);
  SamSetup.useautospeed = prefs.getBool("AutoSpeed", false);
  SamSetup.useDetectorOnHeads = prefs.getBool("DetOnHeads", false);
  SamSetup.autospeed = prefs.getUChar("SpeedPerc", 0);
  SamSetup.UseWS = prefs.getBool("UseWS", true);

  SamSetup.Kp = prefs.getFloat("Kp", 150.0);
  SamSetup.Ki = prefs.getFloat("Ki", 1.4);
  SamSetup.Kd = prefs.getFloat("Kd", 1.4);
  SamSetup.StbVoltage = prefs.getFloat("StbVolt", 100.0);
  SamSetup.BVolt = prefs.getFloat("BVolt", 230.0);
  SamSetup.CheckPower = prefs.getBool("CheckPwr", false);
  SamSetup.UseST = prefs.getBool("UseST", true);

  SamSetup.rele1 = prefs.getBool("rele1", false);
  SamSetup.rele2 = prefs.getBool("rele2", false);
  SamSetup.rele3 = prefs.getBool("rele3", false);
  SamSetup.rele4 = prefs.getBool("rele4", false);

  prefs.getBytes("SteamAddr", SamSetup.SteamAdress, 8);
  prefs.getBytes("PipeAddr", SamSetup.PipeAdress, 8);
  prefs.getBytes("WaterAddr", SamSetup.WaterAdress, 8);
  prefs.getBytes("TankAddr", SamSetup.TankAdress, 8);
  prefs.getBytes("ACPAddr", SamSetup.ACPAdress, 8);

  copyStringSafe(SamSetup.SteamColor, prefs.getString("SteamCol", ""));
  copyStringSafe(SamSetup.PipeColor, prefs.getString("PipeCol", ""));
  copyStringSafe(SamSetup.WaterColor, prefs.getString("WaterCol", ""));
  copyStringSafe(SamSetup.TankColor, prefs.getString("TankCol", ""));
  copyStringSafe(SamSetup.ACPColor, prefs.getString("ACPCol", ""));

  copyStringSafe(SamSetup.blynkauth, prefs.getString("blynk", ""));
  copyStringSafe(SamSetup.videourl, prefs.getString("video", ""));
  copyStringSafe(SamSetup.tg_token, prefs.getString("tg_tok", ""));
  copyStringSafe(SamSetup.tg_chat_id, prefs.getString("tg_id", ""));

  SamSetup.UsePreccureCorrect = prefs.getBool("Preccure", true);
  SamSetup.ChangeProgramBuzzer = prefs.getBool("PrgBuzz", false);
  SamSetup.UseBuzzer = prefs.getBool("UseBuzz", false);
  SamSetup.UseBBuzzer = prefs.getBool("UseBBuzz", false);
  SamSetup.DistTimeF = prefs.getUChar("DistTimeF", 16);
  SamSetup.UseHLS = prefs.getBool("UseHLS", true);
  SamSetup.MaxPressureValue = prefs.getFloat("MaxPress", 0);

  SamSetup.NbkIn = prefs.getFloat("NbkIn", 0);
  SamSetup.NbkDelta = prefs.getFloat("NbkDelta", 0);
  SamSetup.NbkDM = prefs.getFloat("NbkDM", 0);
  SamSetup.NbkDP = prefs.getFloat("NbkDP", 0);
  SamSetup.NbkSteamT = prefs.getFloat("NbkSteamT", 0);
  SamSetup.NbkOwPress = prefs.getFloat("NbkOwPress", 0);

  SamSetup.ColDiam = prefs.getFloat("ColDiam", 2.0f);
  SamSetup.ColHeight = prefs.getFloat("ColHeight", 0.5f);
  SamSetup.PackDens = prefs.getUChar("PackDens", 80);

  prefs.end();
  SamSetup.Mode = lastMode;
  //Serial.println("Profile loaded from NVS");
}

#endif
