#ifndef __SAMOVAR_NVS_MIGRATION_H_
#define __SAMOVAR_NVS_MIGRATION_H_

#include <Arduino.h>
#include <EEPROM.h>

#include "Samovar.h"
#include "state/globals.h"
#include "storage/nvs_profiles.h"

inline void reset_migration_flag() {
  Preferences& prefs = nvs_preferences();
  prefs.begin("sam_meta", false);
  prefs.remove("migrated");
  prefs.end();
  Serial.println("NVS: Migration flag reset. Reboot to test migration again.");
}

inline void migrate_from_eeprom() {
  Preferences& prefs = nvs_preferences();
  prefs.begin("sam_meta", true);
  bool migrated = prefs.getBool("migrated", false);
  prefs.end();

  if (migrated) {
    Serial.println("NVS: Migration already done in previous boot.");
    return;
  }

  Serial.println("NVS: Checking for old EEPROM data...");
  EEPROM.begin(sizeof(SetupEEPROM));
  SetupEEPROM temp;
  EEPROM.get(0, temp);

  if (temp.flag <= 250) {
    Serial.print("NVS: Found valid EEPROM data (flag=");
    Serial.print(temp.flag);
    Serial.println("). Migrating to NVS...");

    SetupEEPROM backup = SamSetup;
    SAMOVAR_MODE backupMode = Samovar_CR_Mode;
    SamSetup = temp;
    if (SamSetup.Mode > SAMOVAR_LUA_MODE) {
      SamSetup.Mode = SAMOVAR_RECTIFICATION_MODE;
    }
    Samovar_CR_Mode = (SAMOVAR_MODE)SamSetup.Mode;

    save_profile_nvs();

    SamSetup = backup;
    Samovar_CR_Mode = backupMode;

    prefs.begin("sam_meta", false);
    prefs.putBool("migrated", true);
    prefs.end();
    Serial.println("NVS: Migration completed successfully!");
  } else {
    Serial.print("NVS: EEPROM is empty or invalid (flag=");
    Serial.print(temp.flag);
    Serial.println("). Skipping migration.");
    prefs.begin("sam_meta", false);
    prefs.putBool("migrated", true);
    prefs.end();
  }
  EEPROM.end();
}

#endif
