#include <Preferences.h>
#include <EEPROM.h>
#include <WiFi.h>
#include <nvs.h>
#include <nvs_flash.h>
#include "Samovar.h"

Preferences prefs;
static bool nvsProfileWriteFailed = false;

static void write_last_mode_meta(uint8_t mode);
static bool compact_samovar_nvs_namespaces();
static bool rebuild_full_nvs_partition();
static void load_profile_nvs_from_namespace(const char* ns);

static const char* const SAMOVAR_COMMON_PROFILE_NAMESPACE = "sam_cfg";

static const char* const SAMOVAR_LEGACY_PROFILE_NAMESPACES[] = {
  "sam_rect",
  "sam_dist",
  "sam_beer",
  "sam_bk",
  "sam_nbk",
  "sam_suvid",
  "sam_lua"
};

static const size_t SAMOVAR_LEGACY_PROFILE_NAMESPACE_COUNT =
  sizeof(SAMOVAR_LEGACY_PROFILE_NAMESPACES) / sizeof(SAMOVAR_LEGACY_PROFILE_NAMESPACES[0]);

static const char* const SAMOVAR_NVS_NAMESPACES[] = {
  "sam_meta",
  "sam_cfg",
  "sam_rect",
  "sam_dist",
  "sam_beer",
  "sam_bk",
  "sam_nbk",
  "sam_suvid",
  "sam_lua"
};

static const size_t SAMOVAR_NVS_NAMESPACE_COUNT =
  sizeof(SAMOVAR_NVS_NAMESPACES) / sizeof(SAMOVAR_NVS_NAMESPACES[0]);

static void markNvsProfileWriteFailed(const char* key) {
  nvsProfileWriteFailed = true;
  Serial.print(F("NVS: Failed to write profile key "));
  Serial.println(key);
}

static void loadBytesOrInvalid(const char* key, uint8_t* dst, size_t len) {
  if (prefs.getBytes(key, dst, len) != len) {
    memset(dst, 255, len);
  }
}

static String getColorOrDefault(const char* key, const char* defaultColor) {
  String color = prefs.getString(key, defaultColor);
  return color.length() > 0 ? color : String(defaultColor);
}

static const char* legacy_profile_namespace_by_mode(int mode) {
  switch (mode) {
    case SAMOVAR_BEER_MODE: return "sam_beer";
    case SAMOVAR_DISTILLATION_MODE: return "sam_dist";
    case SAMOVAR_BK_MODE: return "sam_bk";
    case SAMOVAR_NBK_MODE: return "sam_nbk";
    case SAMOVAR_SUVID_MODE: return "sam_suvid";
    case SAMOVAR_LUA_MODE: return "sam_lua";
    case SAMOVAR_RECTIFICATION_MODE:
    default:
      return "sam_rect";
  }
}

static bool profile_exists_in_namespace(const char* ns) {
  Preferences profilePrefs;
  if (!profilePrefs.begin(ns, true)) {
    return false;
  }
  uint8_t flag = profilePrefs.getUChar("flag", 255);
  profilePrefs.end();
  return flag <= 250;
}

bool profile_exists() {
  return profile_exists_in_namespace(SAMOVAR_COMMON_PROFILE_NAMESPACE);
}

void set_current_profile_mode(SAMOVAR_MODE mode) {
  int modeValue = (int)mode;
  if (modeValue < SAMOVAR_RECTIFICATION_MODE || modeValue > SAMOVAR_LUA_MODE) {
    modeValue = SAMOVAR_RECTIFICATION_MODE;
  }
  Samovar_CR_Mode = (SAMOVAR_MODE)modeValue;
  write_last_mode_meta((uint8_t)modeValue);
}

static uint8_t read_last_mode_meta() {
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

static void write_last_mode_meta(uint8_t mode) {
  if (mode > (uint8_t)SAMOVAR_LUA_MODE) {
    mode = (uint8_t)SAMOVAR_RECTIFICATION_MODE;
  }
  Preferences meta;
  if (!meta.begin("sam_meta", false)) {
    Serial.println(F("NVS: Failed to open sam_meta for writing last_mode"));
    return;
  }
  bool migrated = meta.getBool("migrated", false);
  if (meta.getUChar("last_mode", 255) == mode) {
    meta.end();
    return;
  }
  size_t written = meta.putUChar("last_mode", mode);
  uint8_t savedMode = meta.getUChar("last_mode", 255);
  if (written != 0 && savedMode == mode) {
    meta.end();
    return;
  }

  Serial.print(F("NVS: Repairing sam_meta, failed to write last_mode = "));
  Serial.println(mode);
  meta.clear();
  meta.putBool("migrated", migrated);
  written = meta.putUChar("last_mode", mode);
  savedMode = meta.getUChar("last_mode", 255);
  meta.end();

  if (written == 0 || savedMode != mode) {
    Serial.print(F("NVS: Failed to repair last_mode = "));
    Serial.println(mode);
    if (compact_samovar_nvs_namespaces()) {
      Preferences retryMeta;
      if (retryMeta.begin("sam_meta", false)) {
        retryMeta.putUChar("last_mode", mode);
        retryMeta.end();
      }
    }
  }
}

struct SamovarNvsEntryBackup {
  char ns[16];
  char key[16];
  nvs_type_t type;
  size_t len;
  union {
    uint8_t u8;
    int8_t i8;
    uint16_t u16;
    int16_t i16;
    uint32_t u32;
    int32_t i32;
    uint64_t u64;
    int64_t i64;
  } value;
  uint8_t* data;
};

static void free_samovar_nvs_backup(SamovarNvsEntryBackup* entries, size_t count) {
  if (!entries) return;
  for (size_t i = 0; i < count; i++) {
    free(entries[i].data);
    entries[i].data = nullptr;
  }
  free(entries);
}

static bool is_samovar_nvs_namespace(const char* ns) {
  if (!ns) return false;
  for (size_t i = 0; i < SAMOVAR_NVS_NAMESPACE_COUNT; i++) {
    if (strcmp(ns, SAMOVAR_NVS_NAMESPACES[i]) == 0) {
      return true;
    }
  }
  return false;
}

static bool is_legacy_profile_namespace(const char* ns) {
  if (!ns) return false;
  for (size_t i = 0; i < SAMOVAR_LEGACY_PROFILE_NAMESPACE_COUNT; i++) {
    if (strcmp(ns, SAMOVAR_LEGACY_PROFILE_NAMESPACES[i]) == 0) {
      return true;
    }
  }
  return false;
}

static bool namespace_has_entries(const char* ns) {
  nvs_iterator_t it = nvs_entry_find("nvs", ns, NVS_TYPE_ANY);
  if (!it) return false;
  nvs_release_iterator(it);
  return true;
}

static bool read_samovar_nvs_entry(nvs_handle_t handle, const nvs_entry_info_t& info, SamovarNvsEntryBackup& entry) {
  strncpy(entry.ns, info.namespace_name, sizeof(entry.ns) - 1);
  strncpy(entry.key, info.key, sizeof(entry.key) - 1);
  entry.type = info.type;

  switch (info.type) {
    case NVS_TYPE_U8:
      return nvs_get_u8(handle, info.key, &entry.value.u8) == ESP_OK;
    case NVS_TYPE_I8:
      return nvs_get_i8(handle, info.key, &entry.value.i8) == ESP_OK;
    case NVS_TYPE_U16:
      return nvs_get_u16(handle, info.key, &entry.value.u16) == ESP_OK;
    case NVS_TYPE_I16:
      return nvs_get_i16(handle, info.key, &entry.value.i16) == ESP_OK;
    case NVS_TYPE_U32:
      return nvs_get_u32(handle, info.key, &entry.value.u32) == ESP_OK;
    case NVS_TYPE_I32:
      return nvs_get_i32(handle, info.key, &entry.value.i32) == ESP_OK;
    case NVS_TYPE_U64:
      return nvs_get_u64(handle, info.key, &entry.value.u64) == ESP_OK;
    case NVS_TYPE_I64:
      return nvs_get_i64(handle, info.key, &entry.value.i64) == ESP_OK;
    case NVS_TYPE_STR: {
      size_t len = 0;
      if (nvs_get_str(handle, info.key, nullptr, &len) != ESP_OK || len == 0) return false;
      entry.data = (uint8_t*)malloc(len);
      if (!entry.data) return false;
      entry.len = len;
      return nvs_get_str(handle, info.key, (char*)entry.data, &entry.len) == ESP_OK;
    }
    case NVS_TYPE_BLOB: {
      size_t len = 0;
      if (nvs_get_blob(handle, info.key, nullptr, &len) != ESP_OK || len == 0) return false;
      entry.data = (uint8_t*)malloc(len);
      if (!entry.data) return false;
      entry.len = len;
      return nvs_get_blob(handle, info.key, entry.data, &entry.len) == ESP_OK;
    }
    default:
      return false;
  }
}

static esp_err_t write_samovar_nvs_entry(nvs_handle_t handle, const SamovarNvsEntryBackup& entry) {
  switch (entry.type) {
    case NVS_TYPE_U8:
      return nvs_set_u8(handle, entry.key, entry.value.u8);
    case NVS_TYPE_I8:
      return nvs_set_i8(handle, entry.key, entry.value.i8);
    case NVS_TYPE_U16:
      return nvs_set_u16(handle, entry.key, entry.value.u16);
    case NVS_TYPE_I16:
      return nvs_set_i16(handle, entry.key, entry.value.i16);
    case NVS_TYPE_U32:
      return nvs_set_u32(handle, entry.key, entry.value.u32);
    case NVS_TYPE_I32:
      return nvs_set_i32(handle, entry.key, entry.value.i32);
    case NVS_TYPE_U64:
      return nvs_set_u64(handle, entry.key, entry.value.u64);
    case NVS_TYPE_I64:
      return nvs_set_i64(handle, entry.key, entry.value.i64);
    case NVS_TYPE_STR:
      return entry.data ? nvs_set_str(handle, entry.key, (const char*)entry.data) : ESP_ERR_INVALID_ARG;
    case NVS_TYPE_BLOB:
      return entry.data ? nvs_set_blob(handle, entry.key, entry.data, entry.len) : ESP_ERR_INVALID_ARG;
    default:
      return ESP_ERR_NOT_SUPPORTED;
  }
}

static bool restore_nvs_entries(const SamovarNvsEntryBackup* entries, size_t count, bool samovarOnly) {
  for (size_t i = 0; i < count; i++) {
    if (is_legacy_profile_namespace(entries[i].ns)) {
      continue;
    }
    if (samovarOnly && !is_samovar_nvs_namespace(entries[i].ns)) {
      continue;
    }
    nvs_handle_t handle;
    esp_err_t err = nvs_open(entries[i].ns, NVS_READWRITE, &handle);
    if (err == ESP_OK) {
      err = write_samovar_nvs_entry(handle, entries[i]);
      if (err == ESP_OK) err = nvs_commit(handle);
      nvs_close(handle);
    }
    if (err != ESP_OK) {
      Serial.print(F("NVS: Failed to restore key "));
      Serial.print(entries[i].ns);
      Serial.print('/');
      Serial.println(entries[i].key);
      return false;
    }
  }
  return true;
}

static bool erase_nvs_partition_and_restore(const SamovarNvsEntryBackup* entries, size_t count) {
  Serial.println(F("NVS: Erasing full NVS partition for emergency rebuild"));
  nvs_flash_deinit();
  esp_err_t err = nvs_flash_erase();
  if (err == ESP_OK) {
    err = nvs_flash_init();
  }
  if (err != ESP_OK) {
    Serial.print(F("NVS: Full NVS erase/init failed, err = "));
    Serial.println((int)err);
    return false;
  }
  if (!restore_nvs_entries(entries, count, false)) {
    Serial.println(F("NVS: Full NVS restore failed"));
    return false;
  }
  Serial.println(F("NVS: Full NVS partition rebuilt"));
  return true;
}

static bool backup_all_nvs_entries(SamovarNvsEntryBackup* entries, size_t maxEntries, size_t& count) {
  count = 0;
  nvs_iterator_t it = nvs_entry_find("nvs", nullptr, NVS_TYPE_ANY);
  while (it) {
    if (count >= maxEntries) {
      Serial.println(F("NVS: Backup failed, too many keys"));
      return false;
    }

    nvs_entry_info_t info;
    nvs_entry_info(it, &info);
    nvs_iterator_t next = nvs_entry_next(it);

    nvs_handle_t handle;
    if (nvs_open(info.namespace_name, NVS_READONLY, &handle) == ESP_OK) {
      if (read_samovar_nvs_entry(handle, info, entries[count])) {
        count++;
      } else {
        Serial.print(F("NVS: Failed to backup key "));
        Serial.print(info.namespace_name);
        Serial.print('/');
        Serial.println(info.key);
        nvs_close(handle);
        return false;
      }
      nvs_close(handle);
    } else {
      Serial.print(F("NVS: Failed to open namespace for backup: "));
      Serial.println(info.namespace_name);
      return false;
    }
    it = next;
  }
  return true;
}

static bool rebuild_full_nvs_partition() {
  const size_t maxEntries = 512;
  SamovarNvsEntryBackup* entries = (SamovarNvsEntryBackup*)calloc(maxEntries, sizeof(SamovarNvsEntryBackup));
  if (!entries) {
    Serial.println(F("NVS: Full rebuild failed, no RAM"));
    return false;
  }

  size_t count = 0;
  bool ok = backup_all_nvs_entries(entries, maxEntries, count);
  if (ok) {
    Serial.print(F("NVS: Full rebuild backup keys = "));
    Serial.println(count);
    ok = erase_nvs_partition_and_restore(entries, count);
  }

  free_samovar_nvs_backup(entries, count);
  return ok;
}

static bool compact_samovar_nvs_namespaces() {
  static bool compacting = false;
  if (compacting) return false;
  compacting = true;

  const size_t maxEntries = 512;
  SamovarNvsEntryBackup* entries = (SamovarNvsEntryBackup*)calloc(maxEntries, sizeof(SamovarNvsEntryBackup));
  if (!entries) {
    Serial.println(F("NVS: Samovar namespace compaction failed, no RAM"));
    compacting = false;
    return false;
  }

  size_t count = 0;
  bool ok = backup_all_nvs_entries(entries, maxEntries, count);

  if (!ok) {
    free_samovar_nvs_backup(entries, count);
    compacting = false;
    return false;
  }

  Serial.print(F("NVS: Compacting Samovar namespaces, all keys = "));
  Serial.println(count);

  for (size_t nsIndex = 0; nsIndex < SAMOVAR_NVS_NAMESPACE_COUNT && ok; nsIndex++) {
    nvs_handle_t handle;
    esp_err_t err = nvs_open(SAMOVAR_NVS_NAMESPACES[nsIndex], NVS_READWRITE, &handle);
    if (err == ESP_OK) {
      err = nvs_erase_all(handle);
      if (err == ESP_OK) err = nvs_commit(handle);
      nvs_close(handle);
    }
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) {
      Serial.print(F("NVS: Failed to clear namespace: "));
      Serial.println(SAMOVAR_NVS_NAMESPACES[nsIndex]);
      ok = false;
    }
  }

  if (ok) {
    ok = restore_nvs_entries(entries, count, true);
  }

  if (!ok) {
    Serial.println(F("NVS: Samovar namespace compaction failed, trying full NVS rebuild"));
    ok = erase_nvs_partition_and_restore(entries, count);
  }

  free_samovar_nvs_backup(entries, count);
  compacting = false;

  if (ok) {
    Serial.println(F("NVS: Samovar namespaces compacted"));
  } else {
    Serial.println(F("NVS: Samovar namespace compaction failed"));
  }
  return ok;
}

static void clear_legacy_profile_namespaces() {
  for (size_t i = 0; i < SAMOVAR_LEGACY_PROFILE_NAMESPACE_COUNT; i++) {
    if (!namespace_has_entries(SAMOVAR_LEGACY_PROFILE_NAMESPACES[i])) {
      continue;
    }
    nvs_handle_t handle;
    esp_err_t err = nvs_open(SAMOVAR_LEGACY_PROFILE_NAMESPACES[i], NVS_READWRITE, &handle);
    if (err == ESP_OK) {
      err = nvs_erase_all(handle);
      if (err == ESP_OK) {
        err = nvs_commit(handle);
      }
      nvs_close(handle);
    }
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) {
      Serial.print(F("NVS: Failed to clear legacy namespace "));
      Serial.println(SAMOVAR_LEGACY_PROFILE_NAMESPACES[i]);
    }
  }
}

static bool migrate_legacy_profile_to_common_nvs() {
  if (profile_exists_in_namespace(SAMOVAR_COMMON_PROFILE_NAMESPACE)) {
    clear_legacy_profile_namespaces();
    return true;
  }

  uint8_t lastMode = read_last_mode_meta();
  const char* legacyNs = legacy_profile_namespace_by_mode(lastMode);
  if (!profile_exists_in_namespace(legacyNs)) {
    for (int mode = SAMOVAR_RECTIFICATION_MODE; mode <= SAMOVAR_LUA_MODE; mode++) {
      const char* candidateNs = legacy_profile_namespace_by_mode(mode);
      if (profile_exists_in_namespace(candidateNs)) {
        legacyNs = candidateNs;
        lastMode = (uint8_t)mode;
        break;
      }
    }
  }

  if (!profile_exists_in_namespace(legacyNs)) {
    return false;
  }

  Serial.print(F("NVS: Migrating legacy profile to common namespace from "));
  Serial.println(legacyNs);

  load_profile_nvs_from_namespace(legacyNs);

  SamSetup.Mode = lastMode;
  Samovar_Mode = (SAMOVAR_MODE)lastMode;
  Samovar_CR_Mode = (SAMOVAR_MODE)lastMode;

  save_profile_nvs();
  if (!profile_exists_in_namespace(SAMOVAR_COMMON_PROFILE_NAMESPACE)) {
    Serial.println(F("NVS: Failed to migrate legacy profile to common namespace"));
    return false;
  }

  write_last_mode_meta(lastMode);
  clear_legacy_profile_namespaces();
  Serial.println(F("NVS: Legacy profile migration completed"));
  return true;
}

// -------------------------------------------------------------------------------------------------
// Wi-Fi креды (используем стандартный namespace ESP32, как ESPAsyncWiFiManager):
// ESP32 автоматически сохраняет креденшалы при вызове WiFi.begin(ssid, password) с WiFi.persistent(true)
// Для чтения используем WiFi.SSID() и WiFi.begin() без параметров
// -------------------------------------------------------------------------------------------------

bool load_wifi_credentials(char *ssid, size_t ssid_len, char *pass, size_t pass_len) {
  if (!ssid || !pass || ssid_len == 0 || pass_len == 0) return false;
  ssid[0] = '\0';
  pass[0] = '\0';

  // Используем тот же подход, что и ESPAsyncWiFiManager:
  // WiFi.SSID() возвращает сохраненный SSID из стандартного namespace
  String saved_ssid = WiFi.SSID();
  
  if (saved_ssid.length() > 0) {
    size_t n = saved_ssid.length();
    if (n >= ssid_len) n = ssid_len - 1;
    if (n > 0) memcpy(ssid, saved_ssid.c_str(), n);
    ssid[n] = '\0';
    // Пароль нельзя получить через WiFi API без подключения,
    // но это не проблема - WiFi.begin() без параметров использует сохраненный пароль автоматически
    return true;
  }

  return false;
}

String get_wifi_ssid() {
  // Используем WiFi.SSID() для получения сохраненного SSID (как ESPAsyncWiFiManager)
  return WiFi.SSID();
}

void save_wifi_credentials(const char *ssid, const char *pass) {
  if (!ssid) return;
  
  // WiFi.persistent(true) включает автоматическое сохранение в стандартный namespace
  // WiFi.begin(ssid, pass) сохраняет креденшалы автоматически
  WiFi.persistent(true);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, pass ? pass : "");
  WiFi.persistent(false);
  
  Serial.print(F("WiFi credentials saved. SSID: "));
  Serial.println(ssid);
}

void clear_wifi_credentials() {
  // Используем WiFi.disconnect(true) для очистки сохраненных креденшалов
  // true означает, что нужно также очистить сохраненные креденшалы из стандартного namespace
  WiFi.disconnect(true);
  
  Serial.println(F("WiFi credentials cleared from standard namespace"));
}

// Хелпер для сохранения строк (char array -> String -> NVS)
void saveStringIfChanged(const char* key, const char* value) {
  String current = prefs.getString(key, "");
  if (current != String(value)) {
    if (prefs.putString(key, String(value)) == 0) {
      markNvsProfileWriteFailed(key);
    }
  }
}

// Хелпер для сохранения массивов (адреса датчиков)
void saveBytesIfChanged(const char* key, const void* value, size_t len) {
  uint8_t buf[len];
  size_t readLen = prefs.getBytes(key, buf, len);
  if (readLen != len || memcmp(buf, value, len) != 0) {
    if (prefs.putBytes(key, value, len) != len) {
      markNvsProfileWriteFailed(key);
    }
  }
}

void saveUCharIfChanged(const char* key, uint8_t value) {
  if (!prefs.isKey(key) || prefs.getUChar(key, 0) != value) {
    if (prefs.putUChar(key, value) == 0) {
      markNvsProfileWriteFailed(key);
    }
  }
}

void saveUShortIfChanged(const char* key, uint16_t value) {
  if (!prefs.isKey(key) || prefs.getUShort(key, 0) != value) {
    if (prefs.putUShort(key, value) == 0) {
      markNvsProfileWriteFailed(key);
    }
  }
}

void saveFloatIfChanged(const char* key, float value) {
  if (!prefs.isKey(key) || prefs.getFloat(key, 0.0f) != value) {
    if (prefs.putFloat(key, value) == 0) {
      markNvsProfileWriteFailed(key);
    }
  }
}

void saveBoolIfChanged(const char* key, bool value) {
  if (!prefs.isKey(key) || prefs.getBool(key, !value) != value) {
    if (prefs.putBool(key, value) == 0) {
      markNvsProfileWriteFailed(key);
    }
  }
}

void save_profile_nvs() {
  static bool retryingProfileSave = false;
  static bool rebuildingProfileSave = false;
  nvsProfileWriteFailed = false;

  if (!prefs.begin(SAMOVAR_COMMON_PROFILE_NAMESPACE, false)) {
    Serial.println("NVS: Failed to open namespace for writing!");
    if (!compact_samovar_nvs_namespaces() || !prefs.begin(SAMOVAR_COMMON_PROFILE_NAMESPACE, false)) {
      Serial.println("NVS: Failed to open namespace for writing after compaction!");
      return;
    }
  }

  // --- Основные настройки ---
  saveUCharIfChanged("flag", SamSetup.flag);
  saveUShortIfChanged("Mode", SamSetup.Mode);
  saveUCharIfChanged("TimeZone", SamSetup.TimeZone);
  saveFloatIfChanged("HeaterR", SamSetup.HeaterResistant);
  saveUCharIfChanged("LogPeriod", SamSetup.LogPeriod);
  
  // --- Температурные настройки (Set) ---
  saveFloatIfChanged("SetSteam", SamSetup.SetSteamTemp);
  saveFloatIfChanged("SetPipe", SamSetup.SetPipeTemp);
  saveFloatIfChanged("SetWater", SamSetup.SetWaterTemp);
  saveFloatIfChanged("SetTank", SamSetup.SetTankTemp);
  saveFloatIfChanged("SetACP", SamSetup.SetACPTemp);
  saveFloatIfChanged("DistTemp", SamSetup.DistTemp);

  // --- Температурные настройки (Delta) ---
  saveFloatIfChanged("DeltaSteam", SamSetup.DeltaSteamTemp);
  saveFloatIfChanged("DeltaPipe", SamSetup.DeltaPipeTemp);
  saveFloatIfChanged("DeltaWater", SamSetup.DeltaWaterTemp);
  saveFloatIfChanged("DeltaTank", SamSetup.DeltaTankTemp);
  saveFloatIfChanged("DeltaACP", SamSetup.DeltaACPTemp);

  // --- Задержки (Delays) ---
  saveUShortIfChanged("SteamDelay", SamSetup.SteamDelay);
  saveUShortIfChanged("PipeDelay", SamSetup.PipeDelay);
  saveUShortIfChanged("WaterDelay", SamSetup.WaterDelay);
  saveUShortIfChanged("TankDelay", SamSetup.TankDelay);
  saveUShortIfChanged("ACPDelay", SamSetup.ACPDelay);

  // --- Шаговик и настройки насоса ---
  saveUShortIfChanged("StepMl", SamSetup.StepperStepMl);
  saveUShortIfChanged("StepMlI2C", SamSetup.StepperStepMlI2C);
  saveBoolIfChanged("AutoSpeed", SamSetup.useautospeed);
  saveBoolIfChanged("DetOnHeads", SamSetup.useDetectorOnHeads);
  saveUCharIfChanged("SpeedPerc", SamSetup.autospeed);
  saveBoolIfChanged("UseWS", SamSetup.UseWS); // Датчик воды

  // --- PID и Power ---
  saveFloatIfChanged("Kp", SamSetup.Kp);
  saveFloatIfChanged("Ki", SamSetup.Ki);
  saveFloatIfChanged("Kd", SamSetup.Kd);
  saveFloatIfChanged("StbVolt", SamSetup.StbVoltage);
  saveFloatIfChanged("BVolt", SamSetup.BVolt);
  saveBoolIfChanged("CheckPwr", SamSetup.CheckPower);
  saveBoolIfChanged("UseST", SamSetup.UseST); // Разгонный тэн

  // --- Реле ---
  saveBoolIfChanged("rele1", SamSetup.rele1);
  saveBoolIfChanged("rele2", SamSetup.rele2);
  saveBoolIfChanged("rele3", SamSetup.rele3);
  saveBoolIfChanged("rele4", SamSetup.rele4);

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
  saveBoolIfChanged("Preccure", SamSetup.UsePreccureCorrect);
  saveBoolIfChanged("PrgBuzz", SamSetup.ChangeProgramBuzzer);
  saveBoolIfChanged("UseBuzz", SamSetup.UseBuzzer);
  saveBoolIfChanged("UseBBuzz", SamSetup.UseBBuzzer);
  saveUCharIfChanged("DistTimeF", SamSetup.DistTimeF);
  saveBoolIfChanged("UseHLS", SamSetup.UseHLS);
  saveFloatIfChanged("MaxPress", SamSetup.MaxPressureValue);

  // --- НБК настройки ---
  saveFloatIfChanged("NbkIn", SamSetup.NbkIn);
  saveFloatIfChanged("NbkDelta", SamSetup.NbkDelta);
  saveFloatIfChanged("NbkDM", SamSetup.NbkDM);
  saveFloatIfChanged("NbkDP", SamSetup.NbkDP);
  saveFloatIfChanged("NbkSteamT", SamSetup.NbkSteamT);
  saveFloatIfChanged("NbkOwPress", SamSetup.NbkOwPress);

  // --- Параметры колонны ---
  saveFloatIfChanged("ColDiam", SamSetup.ColDiam);
  saveFloatIfChanged("ColHeight", SamSetup.ColHeight);
  saveUCharIfChanged("PackDens", SamSetup.PackDens);

  prefs.end();
  if (nvsProfileWriteFailed) {
    if (!retryingProfileSave) {
      Serial.println(F("NVS: Profile write failed, compacting and retrying"));
      retryingProfileSave = true;
      if (compact_samovar_nvs_namespaces()) {
        save_profile_nvs();
      }
      if (nvsProfileWriteFailed && !rebuildingProfileSave) {
        Serial.println(F("NVS: Profile write still failed, full rebuild and retrying"));
        rebuildingProfileSave = true;
        if (rebuild_full_nvs_partition()) {
          save_profile_nvs();
        }
        rebuildingProfileSave = false;
      }
      retryingProfileSave = false;
    } else if (rebuildingProfileSave) {
      Serial.println(F("NVS: Profile write failed after full rebuild"));
    } else {
      Serial.println(F("NVS: Profile write failed after compaction"));
    }
  }
  //Serial.println("Profile saved to NVS");
}

static void load_profile_nvs_from_namespace(const char* ns) {
  uint8_t lastMode = read_last_mode_meta();
  Samovar_CR_Mode = (SAMOVAR_MODE)lastMode;

  if (!prefs.begin(ns, true)) { // Read-only
    Serial.println("NVS: Failed to open namespace for reading!");
    return;
  }

  // Читаем с дефолтными значениями. Для flag используем 255, чтобы определить "пустой NVS"
  SamSetup.flag = prefs.getUChar("flag", 255);
  SamSetup.Mode = prefs.getUShort("Mode", 0);
  SamSetup.TimeZone = prefs.getUChar("TimeZone", 3);
  SamSetup.HeaterResistant = prefs.getFloat("HeaterR", 15.2);
  SamSetup.LogPeriod = prefs.getUChar("LogPeriod", 3);

  SamSetup.SetSteamTemp = prefs.getFloat("SetSteam", 0);
  SamSetup.SetPipeTemp = prefs.getFloat("SetPipe", 0);
  SamSetup.SetWaterTemp = prefs.getFloat("SetWater", 0);
  SamSetup.SetTankTemp = prefs.getFloat("SetTank", 0);
  SamSetup.SetACPTemp = prefs.getFloat("SetACP", 0);
  SamSetup.DistTemp = prefs.getFloat("DistTemp", DEFAULT_DIST_TEMP);

  SamSetup.DeltaSteamTemp = prefs.getFloat("DeltaSteam", 0.1);
  SamSetup.DeltaPipeTemp = prefs.getFloat("DeltaPipe", 0.2);
  SamSetup.DeltaWaterTemp = prefs.getFloat("DeltaWater", 0);
  SamSetup.DeltaTankTemp = prefs.getFloat("DeltaTank", 0);
  SamSetup.DeltaACPTemp = prefs.getFloat("DeltaACP", 0);

  SamSetup.SteamDelay = prefs.getUShort("SteamDelay", 20);
  SamSetup.PipeDelay = prefs.getUShort("PipeDelay", 20);
  SamSetup.WaterDelay = prefs.getUShort("WaterDelay", 20);
  SamSetup.TankDelay = prefs.getUShort("TankDelay", 20);
  SamSetup.ACPDelay = prefs.getUShort("ACPDelay", 20);

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

  // Чтение массивов
  loadBytesOrInvalid("SteamAddr", SamSetup.SteamAdress, 8);
  loadBytesOrInvalid("PipeAddr", SamSetup.PipeAdress, 8);
  loadBytesOrInvalid("WaterAddr", SamSetup.WaterAdress, 8);
  loadBytesOrInvalid("TankAddr", SamSetup.TankAdress, 8);
  loadBytesOrInvalid("ACPAddr", SamSetup.ACPAdress, 8);

  // Чтение строк (в буферы структуры)
  copyStringSafe(SamSetup.SteamColor, getColorOrDefault("SteamCol", "#ff0000"));
  copyStringSafe(SamSetup.PipeColor, getColorOrDefault("PipeCol", "#0000ff"));
  copyStringSafe(SamSetup.WaterColor, getColorOrDefault("WaterCol", "#00bfff"));
  copyStringSafe(SamSetup.TankColor, getColorOrDefault("TankCol", "#008000"));
  copyStringSafe(SamSetup.ACPColor, getColorOrDefault("ACPCol", "#800080"));
  
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

  // --- Параметры колонны ---
  SamSetup.ColDiam = prefs.getFloat("ColDiam", 2.0f);
  SamSetup.ColHeight = prefs.getFloat("ColHeight", 0.5f);
  SamSetup.PackDens = prefs.getUChar("PackDens", 80);

  prefs.end();
  SamSetup.Mode = lastMode;
  //Serial.println("Profile loaded from NVS");
}

void load_profile_nvs() {
  load_profile_nvs_from_namespace(SAMOVAR_COMMON_PROFILE_NAMESPACE);
}

// Функция для сброса флага миграции (для тестирования)
void reset_migration_flag() {
  prefs.begin("sam_meta", false);
  prefs.remove("migrated");
  prefs.end();
  Serial.println("NVS: Migration flag reset. Reboot to test migration again.");
}

void migrate_from_eeprom() {
  migrate_legacy_profile_to_common_nvs();

  // Проверяем, была ли миграция
  prefs.begin("sam_meta", true);
  bool migrated = prefs.getBool("migrated", false);
  prefs.end();

  if (migrated) {
    Serial.println("NVS: Migration already done in previous boot.");
    return;
  }

  Serial.println("NVS: Checking for old EEPROM data...");
  EEPROM.begin(sizeof(SetupEEPROM)); // Открываем эмуляцию EEPROM
  SetupEEPROM temp;
  EEPROM.get(0, temp);
  
  // Простая проверка валидности: флаг должен быть не пустым (не 255)
  // В вашем коде используется проверка if (SamSetup.flag > 250) SamSetup.flag = 2;
  // Значит, если флаг <= 250, там, вероятно, есть данные.
  if (temp.flag <= 250) {
    Serial.print("NVS: Found valid EEPROM data (flag=");
    Serial.print(temp.flag);
    Serial.println("). Migrating to NVS...");
    
    // Копируем во временную глобальную переменную, чтобы использовать функцию сохранения
    SetupEEPROM backup = SamSetup; // Сохраняем текущее состояние (на всякий случай)
    SAMOVAR_MODE backupMode = Samovar_CR_Mode;
    SamSetup = temp;               // Подменяем на данные из EEPROM
    if (SamSetup.Mode > SAMOVAR_LUA_MODE) {
      SamSetup.Mode = SAMOVAR_RECTIFICATION_MODE;
    }
    Samovar_CR_Mode = (SAMOVAR_MODE)SamSetup.Mode;
    
    save_profile_nvs();            // Сохраняем в NVS
    
    SamSetup = backup;             // Возвращаем как было (хотя дальше все равно будет load)
    Samovar_CR_Mode = backupMode;
    
    // Ставим флаг миграции
    prefs.begin("sam_meta", false);
    prefs.putBool("migrated", true);
    prefs.end();
    Serial.println("NVS: Migration completed successfully!");
  } else {
    Serial.print("NVS: EEPROM is empty or invalid (flag=");
    Serial.print(temp.flag);
    Serial.println("). Skipping migration.");
    // Если EEPROM пустой, просто ставим флаг, чтобы не проверять каждый раз
    prefs.begin("sam_meta", false);
    prefs.putBool("migrated", true);
    prefs.end();
  }
  EEPROM.end();
}
