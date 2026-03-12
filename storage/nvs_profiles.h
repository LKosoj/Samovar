#ifndef __SAMOVAR_NVS_PROFILES_H_
#define __SAMOVAR_NVS_PROFILES_H_

#include <Arduino.h>
#include <EEPROM.h>
#include <Preferences.h>

#include "Samovar.h"
#include "state/globals.h"
#include "support/safe_parse.h"

extern Preferences prefs;

inline const char* profile_namespace_by_mode(int mode) {
  switch (mode) {
    case SAMOVAR_RECTIFICATION_MODE: return "prf_rect";
    case SAMOVAR_DISTILLATION_MODE: return "prf_dist";
    case SAMOVAR_BEER_MODE:         return "prf_beer";
    case SAMOVAR_BK_MODE:           return "prf_bk";
    case SAMOVAR_NBK_MODE:          return "prf_nbk";
    case SAMOVAR_SUVID_MODE:        return "prf_suvid";
    case SAMOVAR_LUA_MODE:          return "prf_lua";
    default:                        return "prf_rect";
  }
}

inline const char* current_profile_namespace() {
  int mode = (int)SamSetup.Mode;
  if (mode < SAMOVAR_RECTIFICATION_MODE || mode > SAMOVAR_LUA_MODE) {
    mode = (int)Samovar_Mode;
  }
  return profile_namespace_by_mode(mode);
}

inline uint8_t read_last_mode_meta() {
  Preferences meta;
  uint8_t mode = SAMOVAR_RECTIFICATION_MODE;
  if (meta.begin("prf_meta", true)) {
    mode = meta.getUChar("last_mode", SAMOVAR_RECTIFICATION_MODE);
    meta.end();
  }
  if (mode > SAMOVAR_LUA_MODE) {
    mode = SAMOVAR_RECTIFICATION_MODE;
  }
  return mode;
}

inline void write_last_mode_meta(uint8_t mode) {
  Preferences meta;
  if (!meta.begin("prf_meta", false)) {
    Serial.println("NVS: Error opening prf_meta namespace for writing.");
    return;
  }
  meta.putUChar("last_mode", mode);
  meta.end();
}

inline void saveStringIfChanged(const char* key, const char* value) {
  String current = prefs.getString(key, "");
  if (current != value) {
    prefs.putString(key, value);
  }
}

inline void saveBytesIfChanged(const char* key, const void* value, size_t len) {
  uint8_t buf[8];
  size_t storedLen = prefs.getBytesLength(key);
  if (storedLen == len && len <= sizeof(buf)) {
    prefs.getBytes(key, buf, len);
    if (memcmp(buf, value, len) == 0) {
      return;
    }
  }
  prefs.putBytes(key, value, len);
}

inline void save_profile_nvs() {
  if (!prefs.begin(current_profile_namespace(), false)) {
    Serial.println("NVS: Error opening profile namespace for writing.");
    return;
  }

  saveBytesIfChanged("flag", &SamSetup.flag, sizeof(SamSetup.flag));
  saveBytesIfChanged("Mode", &SamSetup.Mode, sizeof(SamSetup.Mode));
  saveBytesIfChanged("SteamDelay", &SamSetup.SteamDelay, sizeof(SamSetup.SteamDelay));
  saveBytesIfChanged("PipeDelay", &SamSetup.PipeDelay, sizeof(SamSetup.PipeDelay));
  saveBytesIfChanged("WaterDelay", &SamSetup.WaterDelay, sizeof(SamSetup.WaterDelay));
  saveBytesIfChanged("TankDelay", &SamSetup.TankDelay, sizeof(SamSetup.TankDelay));
  saveBytesIfChanged("ACPDelay", &SamSetup.ACPDelay, sizeof(SamSetup.ACPDelay));
  saveBytesIfChanged("SetSteamTemp", &SamSetup.SetSteamTemp, sizeof(SamSetup.SetSteamTemp));
  saveBytesIfChanged("SetPipeTemp", &SamSetup.SetPipeTemp, sizeof(SamSetup.SetPipeTemp));
  saveBytesIfChanged("SetWaterTemp", &SamSetup.SetWaterTemp, sizeof(SamSetup.SetWaterTemp));
  saveBytesIfChanged("SetTankTemp", &SamSetup.SetTankTemp, sizeof(SamSetup.SetTankTemp));
  saveBytesIfChanged("SetACPTemp", &SamSetup.SetACPTemp, sizeof(SamSetup.SetACPTemp));
  saveBytesIfChanged("DeltaSteamTemp", &SamSetup.DeltaSteamTemp, sizeof(SamSetup.DeltaSteamTemp));
  saveBytesIfChanged("DeltaPipeTemp", &SamSetup.DeltaPipeTemp, sizeof(SamSetup.DeltaPipeTemp));
  saveBytesIfChanged("DeltaWaterTemp", &SamSetup.DeltaWaterTemp, sizeof(SamSetup.DeltaWaterTemp));
  saveBytesIfChanged("bme_temp", &SamSetup.bme_temp, sizeof(SamSetup.bme_temp));
  saveBytesIfChanged("HeaterResistant", &SamSetup.HeaterResistant, sizeof(SamSetup.HeaterResistant));
  saveBytesIfChanged("TimeZone", &SamSetup.TimeZone, sizeof(SamSetup.TimeZone));
  saveBytesIfChanged("LogPeriod", &SamSetup.LogPeriod, sizeof(SamSetup.LogPeriod));
  saveBytesIfChanged("autospeed", &SamSetup.autospeed, sizeof(SamSetup.autospeed));
  saveBytesIfChanged("ChangeProgramBuzzer", &SamSetup.ChangeProgramBuzzer, sizeof(SamSetup.ChangeProgramBuzzer));
  saveBytesIfChanged("UseBBuzzer", &SamSetup.UseBBuzzer, sizeof(SamSetup.UseBBuzzer));
  saveBytesIfChanged("UseWS", &SamSetup.UseWS, sizeof(SamSetup.UseWS));
  saveBytesIfChanged("UseST", &SamSetup.UseST, sizeof(SamSetup.UseST));
  saveBytesIfChanged("UseWaterValve", &SamSetup.UseWaterValve, sizeof(SamSetup.UseWaterValve));
  saveBytesIfChanged("UseHLS", &SamSetup.UseHLS, sizeof(SamSetup.UseHLS));
  saveBytesIfChanged("SteamAdress", SamSetup.SteamAdress, sizeof(SamSetup.SteamAdress));
  saveBytesIfChanged("PipeAdress", SamSetup.PipeAdress, sizeof(SamSetup.PipeAdress));
  saveBytesIfChanged("WaterAdress", SamSetup.WaterAdress, sizeof(SamSetup.WaterAdress));
  saveBytesIfChanged("TankAdress", SamSetup.TankAdress, sizeof(SamSetup.TankAdress));
  saveBytesIfChanged("ACPAdress", SamSetup.ACPAdress, sizeof(SamSetup.ACPAdress));
  saveBytesIfChanged("Kp", &SamSetup.Kp, sizeof(SamSetup.Kp));
  saveBytesIfChanged("Ki", &SamSetup.Ki, sizeof(SamSetup.Ki));
  saveBytesIfChanged("Kd", &SamSetup.Kd, sizeof(SamSetup.Kd));
  saveBytesIfChanged("StbVoltage", &SamSetup.StbVoltage, sizeof(SamSetup.StbVoltage));
  saveBytesIfChanged("BVolt", &SamSetup.BVolt, sizeof(SamSetup.BVolt));
  saveBytesIfChanged("DistTimeF", &SamSetup.DistTimeF, sizeof(SamSetup.DistTimeF));
  saveBytesIfChanged("MaxPressureValue", &SamSetup.MaxPressureValue, sizeof(SamSetup.MaxPressureValue));
  saveBytesIfChanged("ColDiam", &SamSetup.ColDiam, sizeof(SamSetup.ColDiam));
  saveBytesIfChanged("ColHeight", &SamSetup.ColHeight, sizeof(SamSetup.ColHeight));
  saveBytesIfChanged("PackDens", &SamSetup.PackDens, sizeof(SamSetup.PackDens));
  saveBytesIfChanged("StepperStepMl", &SamSetup.StepperStepMl, sizeof(SamSetup.StepperStepMl));
  saveBytesIfChanged("StepperStepMlI2C", &SamSetup.StepperStepMlI2C, sizeof(SamSetup.StepperStepMlI2C));
  saveBytesIfChanged("Power", &SamSetup.Power, sizeof(SamSetup.Power));
  saveBytesIfChanged("UsePreccureCorrect", &SamSetup.UsePreccureCorrect, sizeof(SamSetup.UsePreccureCorrect));
  saveBytesIfChanged("UseTCorrect", &SamSetup.UseTCorrect, sizeof(SamSetup.UseTCorrect));
  saveBytesIfChanged("UseStepmash", &SamSetup.UseStepmash, sizeof(SamSetup.UseStepmash));
  saveBytesIfChanged("UseBeerCapasity", &SamSetup.UseBeerCapasity, sizeof(SamSetup.UseBeerCapasity));
  saveBytesIfChanged("UsePumpCorrect", &SamSetup.UsePumpCorrect, sizeof(SamSetup.UsePumpCorrect));
  saveBytesIfChanged("UseExernalAlarm", &SamSetup.UseExernalAlarm, sizeof(SamSetup.UseExernalAlarm));
  saveBytesIfChanged("CheckPower", &SamSetup.CheckPower, sizeof(SamSetup.CheckPower));
  saveBytesIfChanged("UsePause", &SamSetup.UsePause, sizeof(SamSetup.UsePause));
  saveBytesIfChanged("DistTemp", &SamSetup.DistTemp, sizeof(SamSetup.DistTemp));
  saveBytesIfChanged("DistTime", &SamSetup.DistTime, sizeof(SamSetup.DistTime));
  saveBytesIfChanged("DistVol", &SamSetup.DistVol, sizeof(SamSetup.DistVol));
  saveBytesIfChanged("DistProc", &SamSetup.DistProc, sizeof(SamSetup.DistProc));
  saveBytesIfChanged("DistPipeTemp", &SamSetup.DistPipeTemp, sizeof(SamSetup.DistPipeTemp));
  saveBytesIfChanged("DistDelta", &SamSetup.DistDelta, sizeof(SamSetup.DistDelta));
  saveBytesIfChanged("DistSpeed", &SamSetup.DistSpeed, sizeof(SamSetup.DistSpeed));
  saveBytesIfChanged("StepperSpeed", &SamSetup.StepperSpeed, sizeof(SamSetup.StepperSpeed));
  saveBytesIfChanged("MaxPumpSpeed", &SamSetup.MaxPumpSpeed, sizeof(SamSetup.MaxPumpSpeed));
  saveBytesIfChanged("MinPumpSpeed", &SamSetup.MinPumpSpeed, sizeof(SamSetup.MinPumpSpeed));
  saveBytesIfChanged("AlarmMP3", &SamSetup.AlarmMP3, sizeof(SamSetup.AlarmMP3));
  saveBytesIfChanged("I2CPumpAddress", &SamSetup.I2CPumpAddress, sizeof(SamSetup.I2CPumpAddress));
  saveBytesIfChanged("UseExernalNpg", &SamSetup.UseExernalNpg, sizeof(SamSetup.UseExernalNpg));

  saveStringIfChanged("videourl", SamSetup.videourl);
  saveStringIfChanged("blynkauth", SamSetup.blynkauth);
  saveStringIfChanged("tg_token", SamSetup.tg_token);
  saveStringIfChanged("tg_chat_id", SamSetup.tg_chat_id);

  prefs.end();
  write_last_mode_meta((uint8_t)SamSetup.Mode);
  Serial.println("NVS: Profile saved.");
}

inline void load_profile_nvs() {
  uint8_t lastMode = read_last_mode_meta();
  SamSetup.Mode = lastMode;

  if (!prefs.begin(current_profile_namespace(), true)) {
    Serial.println("NVS: Error opening profile namespace for reading.");
    return;
  }

  prefs.getBytes("flag", &SamSetup.flag, sizeof(SamSetup.flag));
  SamSetup.Mode = prefs.getUChar("Mode", SamSetup.Mode);
  SamSetup.SteamDelay = prefs.getFloat("SteamDelay", 0);
  SamSetup.PipeDelay = prefs.getFloat("PipeDelay", 0);
  SamSetup.WaterDelay = prefs.getFloat("WaterDelay", 0);
  SamSetup.TankDelay = prefs.getFloat("TankDelay", 0);
  SamSetup.ACPDelay = prefs.getFloat("ACPDelay", 0);
  SamSetup.SetSteamTemp = prefs.getFloat("SetSteamTemp", 0);
  SamSetup.SetPipeTemp = prefs.getFloat("SetPipeTemp", 0);
  SamSetup.SetWaterTemp = prefs.getFloat("SetWaterTemp", 0);
  SamSetup.SetTankTemp = prefs.getFloat("SetTankTemp", 0);
  SamSetup.SetACPTemp = prefs.getFloat("SetACPTemp", 0);
  SamSetup.DeltaSteamTemp = prefs.getFloat("DeltaSteamTemp", 0);
  SamSetup.DeltaPipeTemp = prefs.getFloat("DeltaPipeTemp", 0);
  SamSetup.DeltaWaterTemp = prefs.getFloat("DeltaWaterTemp", 0);
  SamSetup.bme_temp = prefs.getFloat("bme_temp", 0);
  SamSetup.HeaterResistant = prefs.getFloat("HeaterResistant", 0);
  SamSetup.TimeZone = prefs.getLong("TimeZone", 0);
  SamSetup.LogPeriod = prefs.getULong("LogPeriod", 0);
  SamSetup.autospeed = prefs.getUChar("autospeed", 0);
  SamSetup.ChangeProgramBuzzer = prefs.getBool("ChangeProgramBuzzer", true);
  SamSetup.UseBBuzzer = prefs.getBool("UseBBuzzer", false);
  SamSetup.UseWS = prefs.getBool("UseWS", false);
  SamSetup.UseST = prefs.getBool("UseST", false);
  SamSetup.UseWaterValve = prefs.getBool("UseWaterValve", false);
  SamSetup.UseHLS = prefs.getBool("UseHLS", false);
  prefs.getBytes("SteamAdress", SamSetup.SteamAdress, sizeof(SamSetup.SteamAdress));
  prefs.getBytes("PipeAdress", SamSetup.PipeAdress, sizeof(SamSetup.PipeAdress));
  prefs.getBytes("WaterAdress", SamSetup.WaterAdress, sizeof(SamSetup.WaterAdress));
  prefs.getBytes("TankAdress", SamSetup.TankAdress, sizeof(SamSetup.TankAdress));
  prefs.getBytes("ACPAdress", SamSetup.ACPAdress, sizeof(SamSetup.ACPAdress));
  SamSetup.Kp = prefs.getFloat("Kp", NAN);
  SamSetup.Ki = prefs.getFloat("Ki", NAN);
  SamSetup.Kd = prefs.getFloat("Kd", NAN);
  SamSetup.StbVoltage = prefs.getFloat("StbVoltage", NAN);
  SamSetup.BVolt = prefs.getFloat("BVolt", NAN);
  SamSetup.DistTimeF = prefs.getFloat("DistTimeF", NAN);
  SamSetup.MaxPressureValue = prefs.getFloat("MaxPressureValue", NAN);
  SamSetup.ColDiam = prefs.getFloat("ColDiam", 0);
  SamSetup.ColHeight = prefs.getFloat("ColHeight", 0);
  SamSetup.PackDens = prefs.getUShort("PackDens", 0);
  SamSetup.StepperStepMl = prefs.getUShort("StepperStepMl", 0);
  SamSetup.StepperStepMlI2C = prefs.getUShort("StepperStepMlI2C", 0);
  SamSetup.Power = prefs.getULong("Power", 0);
  SamSetup.UsePreccureCorrect = prefs.getBool("UsePreccureCorrect", false);
  SamSetup.UseTCorrect = prefs.getBool("UseTCorrect", false);
  SamSetup.UseStepmash = prefs.getBool("UseStepmash", false);
  SamSetup.UseBeerCapasity = prefs.getBool("UseBeerCapasity", false);
  SamSetup.UsePumpCorrect = prefs.getBool("UsePumpCorrect", false);
  SamSetup.UseExernalAlarm = prefs.getBool("UseExernalAlarm", false);
  SamSetup.CheckPower = prefs.getBool("CheckPower", false);
  SamSetup.UsePause = prefs.getBool("UsePause", false);
  SamSetup.DistTemp = prefs.getFloat("DistTemp", 0);
  SamSetup.DistTime = prefs.getULong("DistTime", 0);
  SamSetup.DistVol = prefs.getULong("DistVol", 0);
  SamSetup.DistProc = prefs.getUChar("DistProc", 0);
  SamSetup.DistPipeTemp = prefs.getFloat("DistPipeTemp", 0);
  SamSetup.DistDelta = prefs.getFloat("DistDelta", 0);
  SamSetup.DistSpeed = prefs.getFloat("DistSpeed", 0);
  SamSetup.StepperSpeed = prefs.getULong("StepperSpeed", 0);
  SamSetup.MaxPumpSpeed = prefs.getULong("MaxPumpSpeed", 0);
  SamSetup.MinPumpSpeed = prefs.getULong("MinPumpSpeed", 0);
  SamSetup.AlarmMP3 = prefs.getBool("AlarmMP3", false);
  SamSetup.I2CPumpAddress = prefs.getUChar("I2CPumpAddress", 0);
  SamSetup.UseExernalNpg = prefs.getBool("UseExernalNpg", false);

  String tmp;
  tmp = prefs.getString("videourl", "");
  copyStringSafe(SamSetup.videourl, sizeof(SamSetup.videourl), tmp.c_str());
  tmp = prefs.getString("blynkauth", "");
  copyStringSafe(SamSetup.blynkauth, sizeof(SamSetup.blynkauth), tmp.c_str());
  tmp = prefs.getString("tg_token", "");
  copyStringSafe(SamSetup.tg_token, sizeof(SamSetup.tg_token), tmp.c_str());
  tmp = prefs.getString("tg_chat_id", "");
  copyStringSafe(SamSetup.tg_chat_id, sizeof(SamSetup.tg_chat_id), tmp.c_str());

  prefs.end();
  Serial.println("NVS: Profile loaded.");
}

inline void reset_migration_flag() {
  Preferences migration;
  if (migration.begin("migration", false)) {
    migration.putBool("done", false);
    migration.end();
  }
}

inline void migrate_from_eeprom() {
  Preferences migration;
  bool migrationDone = false;
  if (migration.begin("migration", true)) {
    migrationDone = migration.getBool("done", false);
    migration.end();
  }

  if (migrationDone) {
    Serial.println("NVS: Migration already completed.");
    return;
  }

  EEPROM.begin(2048);
  EEPROM.get(0, SamSetup);

  if (SamSetup.flag != SAMOVAR_PROFILE_FLAG) {
    Serial.println("EEPROM: No valid legacy profile found, skipping migration.");
    EEPROM.end();
    return;
  }

  Serial.println("EEPROM: Valid legacy profile found, migrating to NVS...");
  save_profile_nvs();

  if (!migration.begin("migration", false)) {
    Serial.println("NVS: Error opening migration namespace.");
    EEPROM.end();
    return;
  }
  migration.putBool("done", true);
  migration.end();

  EEPROM.end();
  Serial.println("NVS: Migration from EEPROM completed.");
}

#endif
