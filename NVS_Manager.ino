#include <Preferences.h>
#include <EEPROM.h>
#include <nvs.h>
#include <nvs_flash.h>
#include "Samovar.h"

Preferences prefs;
static bool nvsProfileWriteFailed = false;

static void write_last_mode_meta(uint8_t mode);
static bool compact_samovar_nvs_namespaces();
static bool recover_pending_samovar_nvs_compaction();
static void load_profile_nvs_from_namespace(const char* ns);
struct SamovarNvsEntryBackup;
struct SamovarNvsBackupDiskHeader;
struct SamovarNvsEntryDiskHeader;
static void free_samovar_nvs_backup(SamovarNvsEntryBackup* entries, size_t count);
static bool read_samovar_nvs_entry(nvs_handle_t handle, const nvs_entry_info_t& info, SamovarNvsEntryBackup& entry);
static esp_err_t write_samovar_nvs_entry(nvs_handle_t handle, const SamovarNvsEntryBackup& entry);
static bool restore_samovar_nvs_entries(const SamovarNvsEntryBackup* entries, size_t count);
static bool backup_samovar_nvs_entries(SamovarNvsEntryBackup* entries, size_t maxEntries, size_t& count);
static bool save_samovar_nvs_compaction_backup(const SamovarNvsEntryBackup* entries, size_t count);
static bool load_samovar_nvs_compaction_backup(SamovarNvsEntryBackup*& entries, size_t& count);
static void clear_samovar_nvs_compaction_backup();
static bool nvs_find_first_entry(const char* partName, const char* ns, nvs_type_t type, nvs_iterator_t* outIt);
static esp_err_t nvs_advance_iterator(nvs_iterator_t* it);

static const char* const SAMOVAR_COMMON_PROFILE_NAMESPACE = "sam_cfg";
static const char* const SAMOVAR_NVS_COMPACTION_BACKUP_NAMESPACE = "sam_tmp";
static const char* const SAMOVAR_NVS_COMPACTION_BACKUP_DATA_KEY = "data";
static const char* const SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC_KEY = "magic";
static const uint32_t SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC = 0x534E5653; // SNVS
static const uint16_t SAMOVAR_NVS_COMPACTION_BACKUP_VERSION = 1;
static const size_t SAMOVAR_NVS_BACKUP_MAX_ENTRIES = 128;

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

void print_nvs_stats(const char* context) {
  nvs_stats_t stats;
  esp_err_t err = nvs_get_stats("nvs", &stats);
  if (err != ESP_OK) {
    Serial.print(F("NVS: Failed to read stats, err = "));
    Serial.println((int)err);
    return;
  }

  Serial.print(F("NVS: Stats"));
  if (context && context[0] != '\0') {
    Serial.print(F(" ("));
    Serial.print(context);
    Serial.print(F(")"));
  }
  Serial.print(F(": used="));
  Serial.print(stats.used_entries);
  Serial.print(F(", free="));
  Serial.print(stats.free_entries);
  Serial.print(F(", total="));
  Serial.print(stats.total_entries);
  Serial.print(F(", namespaces="));
  Serial.println(stats.namespace_count);
}

void set_default_setup_profile() {
  memset(&SamSetup, 0, sizeof(SamSetup));

  SamSetup.flag = 2;
  SamSetup.Mode = SAMOVAR_RECTIFICATION_MODE;
  SamSetup.TimeZone = 3;
  SamSetup.HeaterResistant = 15.2;
  SamSetup.LogPeriod = 3;

  SamSetup.SetSteamTemp = 0;
  SamSetup.SetPipeTemp = 0;
  SamSetup.SetWaterTemp = 0;
  SamSetup.SetTankTemp = 0;
  SamSetup.SetACPTemp = 0;
  SamSetup.DistTemp = DEFAULT_DIST_TEMP;

  SamSetup.DeltaSteamTemp = 0.1;
  SamSetup.DeltaPipeTemp = 0.2;
  SamSetup.DeltaWaterTemp = 0;
  SamSetup.DeltaTankTemp = 0;
  SamSetup.DeltaACPTemp = 0;

  SamSetup.SteamDelay = 20;
  SamSetup.PipeDelay = 20;
  SamSetup.WaterDelay = 20;
  SamSetup.TankDelay = 20;
  SamSetup.ACPDelay = 20;

  SamSetup.StepperStepMl = STEPPER_STEP_ML;
  SamSetup.StepperStepMlI2C = I2C_STEPPER_STEP_ML_DEFAULT;
  SamSetup.useautospeed = false;
  SamSetup.useDetectorOnHeads = false;
  SamSetup.autospeed = 0;
  SamSetup.UseWS = true;

  SamSetup.Kp = 150.0;
  SamSetup.Ki = 1.4;
  SamSetup.Kd = 1.4;
  SamSetup.StbVoltage = 100.0;
  SamSetup.BVolt = 230.0;
  SamSetup.CheckPower = false;
  SamSetup.UseST = true;

  SamSetup.rele1 = false;
  SamSetup.rele2 = false;
  SamSetup.rele3 = false;
  SamSetup.rele4 = false;

  memset(SamSetup.SteamAdress, 255, sizeof(SamSetup.SteamAdress));
  memset(SamSetup.PipeAdress, 255, sizeof(SamSetup.PipeAdress));
  memset(SamSetup.WaterAdress, 255, sizeof(SamSetup.WaterAdress));
  memset(SamSetup.TankAdress, 255, sizeof(SamSetup.TankAdress));
  memset(SamSetup.ACPAdress, 255, sizeof(SamSetup.ACPAdress));

  copyStringSafe(SamSetup.SteamColor, "#ff0000");
  copyStringSafe(SamSetup.PipeColor, "#0000ff");
  copyStringSafe(SamSetup.WaterColor, "#00bfff");
  copyStringSafe(SamSetup.TankColor, "#008000");
  copyStringSafe(SamSetup.ACPColor, "#800080");
  SamSetup.blynkauth[0] = '\0';
  SamSetup.videourl[0] = '\0';
  SamSetup.tg_token[0] = '\0';
  SamSetup.tg_chat_id[0] = '\0';

  SamSetup.UsePreccureCorrect = true;
  SamSetup.ChangeProgramBuzzer = false;
  SamSetup.UseBuzzer = false;
  SamSetup.UseBBuzzer = false;
  SamSetup.DistTimeF = 16;
  SamSetup.UseHLS = true;
  SamSetup.MaxPressureValue = 0;

  SamSetup.NbkIn = 0;
  SamSetup.NbkDelta = 0;
  SamSetup.NbkDM = 0;
  SamSetup.NbkDP = 0;
  SamSetup.NbkSteamT = 0;
  SamSetup.NbkOwPress = 0;

  SamSetup.ColDiam = 2.0f;
  SamSetup.ColHeight = 0.5f;
  SamSetup.PackDens = 80;
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

struct SamovarNvsBackupDiskHeader {
  uint32_t magic;
  uint16_t version;
  uint16_t count;
  uint32_t totalLen;
};

struct SamovarNvsEntryDiskHeader {
  char ns[16];
  char key[16];
  uint8_t type;
  uint32_t len;
  uint8_t value[8];
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

static bool nvs_find_first_entry(const char* partName, const char* ns, nvs_type_t type, nvs_iterator_t* outIt) {
  if (!outIt) return false;
  *outIt = nullptr;
#if defined(ESP_IDF_VERSION_MAJOR) && (ESP_IDF_VERSION_MAJOR >= 5)
  return (nvs_entry_find(partName, ns, type, outIt) == ESP_OK) && (*outIt != nullptr);
#else
  *outIt = nvs_entry_find(partName, ns, type);
  return *outIt != nullptr;
#endif
}

static esp_err_t nvs_advance_iterator(nvs_iterator_t* it) {
  if (!it || !*it) return ESP_ERR_INVALID_ARG;
#if defined(ESP_IDF_VERSION_MAJOR) && (ESP_IDF_VERSION_MAJOR >= 5)
  return nvs_entry_next(it);
#else
  *it = nvs_entry_next(*it);
  return *it ? ESP_OK : ESP_ERR_NVS_NOT_FOUND;
#endif
}

static bool namespace_has_entries(const char* ns) {
  nvs_iterator_t it = nullptr;
  if (!nvs_find_first_entry("nvs", ns, NVS_TYPE_ANY, &it)) return false;
  nvs_release_iterator(it);
  return true;
}

static bool read_samovar_nvs_entry(nvs_handle_t handle, const nvs_entry_info_t& info, SamovarNvsEntryBackup& entry) {
  strncpy(entry.ns, info.namespace_name, sizeof(entry.ns) - 1);
  entry.ns[sizeof(entry.ns) - 1] = '\0';
  strncpy(entry.key, info.key, sizeof(entry.key) - 1);
  entry.key[sizeof(entry.key) - 1] = '\0';
  entry.type = info.type;
  entry.len = 0;
  entry.data = nullptr;

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
      if (nvs_get_str(handle, info.key, (char*)entry.data, &entry.len) != ESP_OK) {
        free(entry.data);
        entry.data = nullptr;
        entry.len = 0;
        return false;
      }
      return true;
    }
    case NVS_TYPE_BLOB: {
      size_t len = 0;
      if (nvs_get_blob(handle, info.key, nullptr, &len) != ESP_OK || len == 0) return false;
      entry.data = (uint8_t*)malloc(len);
      if (!entry.data) return false;
      entry.len = len;
      if (nvs_get_blob(handle, info.key, entry.data, &entry.len) != ESP_OK) {
        free(entry.data);
        entry.data = nullptr;
        entry.len = 0;
        return false;
      }
      return true;
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

static bool restore_samovar_nvs_entries(const SamovarNvsEntryBackup* entries, size_t count) {
  for (size_t i = 0; i < count; i++) {
    if (!is_samovar_nvs_namespace(entries[i].ns) || is_legacy_profile_namespace(entries[i].ns)) {
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

static bool backup_samovar_nvs_entries(SamovarNvsEntryBackup* entries, size_t maxEntries, size_t& count) {
  count = 0;
  nvs_iterator_t it = nullptr;
  if (!nvs_find_first_entry("nvs", nullptr, NVS_TYPE_ANY, &it)) {
    return true;
  }

  while (it) {
    nvs_entry_info_t info;
    nvs_entry_info(it, &info);
    esp_err_t nextErr = nvs_advance_iterator(&it);
    if (nextErr != ESP_OK && nextErr != ESP_ERR_NVS_NOT_FOUND) {
      Serial.println(F("NVS: Failed to iterate NVS entries"));
      if (it) nvs_release_iterator(it);
      return false;
    }

    nvs_handle_t handle;
    if (!is_samovar_nvs_namespace(info.namespace_name) || is_legacy_profile_namespace(info.namespace_name)) {
      if (nextErr == ESP_ERR_NVS_NOT_FOUND) {
        it = nullptr;
      }
      continue;
    }

    if (count >= maxEntries) {
      Serial.println(F("NVS: Backup failed, too many Samovar keys"));
      if (it) nvs_release_iterator(it);
      return false;
    }

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
    if (nextErr == ESP_ERR_NVS_NOT_FOUND) {
      it = nullptr;
    }
  }
  return true;
}

static size_t samovar_nvs_backup_entry_serialized_len(const SamovarNvsEntryBackup& entry) {
  size_t len = sizeof(SamovarNvsEntryDiskHeader);
  if (entry.type == NVS_TYPE_STR || entry.type == NVS_TYPE_BLOB) {
    len += entry.len;
  }
  return len;
}

static bool save_samovar_nvs_compaction_backup(const SamovarNvsEntryBackup* entries, size_t count) {
  if (!entries && count > 0) return false;
  size_t totalLen = sizeof(SamovarNvsBackupDiskHeader);
  for (size_t i = 0; i < count; i++) {
    totalLen += samovar_nvs_backup_entry_serialized_len(entries[i]);
  }

  uint8_t* blob = (uint8_t*)malloc(totalLen);
  if (!blob) {
    Serial.println(F("NVS: Compaction backup failed, no RAM for blob"));
    return false;
  }

  SamovarNvsBackupDiskHeader header = {};
  header.magic = SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC;
  header.version = SAMOVAR_NVS_COMPACTION_BACKUP_VERSION;
  header.count = (uint16_t)count;
  header.totalLen = (uint32_t)totalLen;

  uint8_t* cursor = blob;
  memcpy(cursor, &header, sizeof(header));
  cursor += sizeof(header);

  for (size_t i = 0; i < count; i++) {
    SamovarNvsEntryDiskHeader entryHeader = {};
    strncpy(entryHeader.ns, entries[i].ns, sizeof(entryHeader.ns) - 1);
    strncpy(entryHeader.key, entries[i].key, sizeof(entryHeader.key) - 1);
    entryHeader.type = (uint8_t)entries[i].type;
    entryHeader.len = (uint32_t)entries[i].len;
    memcpy(entryHeader.value, &entries[i].value, sizeof(entryHeader.value));

    memcpy(cursor, &entryHeader, sizeof(entryHeader));
    cursor += sizeof(entryHeader);
    if (entries[i].type == NVS_TYPE_STR || entries[i].type == NVS_TYPE_BLOB) {
      if (!entries[i].data || entries[i].len == 0) {
        free(blob);
        Serial.println(F("NVS: Compaction backup failed, empty dynamic value"));
        return false;
      }
      memcpy(cursor, entries[i].data, entries[i].len);
      cursor += entries[i].len;
    }
  }

  nvs_handle_t handle;
  esp_err_t err = nvs_open(SAMOVAR_NVS_COMPACTION_BACKUP_NAMESPACE, NVS_READWRITE, &handle);
  if (err == ESP_OK) {
    err = nvs_erase_all(handle);
    if (err == ESP_OK) err = nvs_commit(handle);
    if (err == ESP_OK) err = nvs_set_blob(handle, SAMOVAR_NVS_COMPACTION_BACKUP_DATA_KEY, blob, totalLen);
    if (err == ESP_OK) err = nvs_set_u32(handle, SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC_KEY, SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
  }
  free(blob);

  if (err != ESP_OK) {
    Serial.print(F("NVS: Compaction backup write failed, err = "));
    Serial.println((int)err);
    clear_samovar_nvs_compaction_backup();
    return false;
  }
  return true;
}

static bool load_samovar_nvs_compaction_backup(SamovarNvsEntryBackup*& entries, size_t& count) {
  entries = nullptr;
  count = 0;

  nvs_handle_t handle;
  esp_err_t err = nvs_open(SAMOVAR_NVS_COMPACTION_BACKUP_NAMESPACE, NVS_READONLY, &handle);
  if (err != ESP_OK) {
    return false;
  }

  uint32_t magic = 0;
  err = nvs_get_u32(handle, SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC_KEY, &magic);
  if (err != ESP_OK || magic != SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC) {
    nvs_close(handle);
    return false;
  }

  size_t blobLen = 0;
  err = nvs_get_blob(handle, SAMOVAR_NVS_COMPACTION_BACKUP_DATA_KEY, nullptr, &blobLen);
  if (err != ESP_OK || blobLen < sizeof(SamovarNvsBackupDiskHeader)) {
    nvs_close(handle);
    return false;
  }

  uint8_t* blob = (uint8_t*)malloc(blobLen);
  if (!blob) {
    nvs_close(handle);
    Serial.println(F("NVS: Compaction backup restore failed, no RAM"));
    return false;
  }

  err = nvs_get_blob(handle, SAMOVAR_NVS_COMPACTION_BACKUP_DATA_KEY, blob, &blobLen);
  nvs_close(handle);
  if (err != ESP_OK) {
    free(blob);
    return false;
  }

  SamovarNvsBackupDiskHeader header;
  memcpy(&header, blob, sizeof(header));
  if (header.magic != SAMOVAR_NVS_COMPACTION_BACKUP_MAGIC ||
      header.version != SAMOVAR_NVS_COMPACTION_BACKUP_VERSION ||
      header.totalLen != blobLen ||
      header.count > SAMOVAR_NVS_BACKUP_MAX_ENTRIES) {
    free(blob);
    Serial.println(F("NVS: Compaction backup restore failed, invalid header"));
    return false;
  }

  SamovarNvsEntryBackup* loaded = (SamovarNvsEntryBackup*)calloc(header.count, sizeof(SamovarNvsEntryBackup));
  if (!loaded && header.count > 0) {
    free(blob);
    Serial.println(F("NVS: Compaction backup restore failed, no RAM for entries"));
    return false;
  }

  const uint8_t* cursor = blob + sizeof(SamovarNvsBackupDiskHeader);
  const uint8_t* end = blob + blobLen;
  for (size_t i = 0; i < header.count; i++) {
    if ((size_t)(end - cursor) < sizeof(SamovarNvsEntryDiskHeader)) {
      free_samovar_nvs_backup(loaded, i);
      free(blob);
      Serial.println(F("NVS: Compaction backup restore failed, truncated entry"));
      return false;
    }

    SamovarNvsEntryDiskHeader entryHeader;
    memcpy(&entryHeader, cursor, sizeof(entryHeader));
    cursor += sizeof(entryHeader);

    strncpy(loaded[i].ns, entryHeader.ns, sizeof(loaded[i].ns) - 1);
    strncpy(loaded[i].key, entryHeader.key, sizeof(loaded[i].key) - 1);
    loaded[i].type = (nvs_type_t)entryHeader.type;
    loaded[i].len = entryHeader.len;
    memcpy(&loaded[i].value, entryHeader.value, sizeof(entryHeader.value));

    if (!is_samovar_nvs_namespace(loaded[i].ns) || is_legacy_profile_namespace(loaded[i].ns)) {
      free_samovar_nvs_backup(loaded, i + 1);
      free(blob);
      Serial.println(F("NVS: Compaction backup restore failed, invalid namespace"));
      return false;
    }

    if (loaded[i].type == NVS_TYPE_STR || loaded[i].type == NVS_TYPE_BLOB) {
      if (loaded[i].len == 0 || (size_t)(end - cursor) < loaded[i].len) {
        free_samovar_nvs_backup(loaded, i + 1);
        free(blob);
        Serial.println(F("NVS: Compaction backup restore failed, invalid dynamic value"));
        return false;
      }
      loaded[i].data = (uint8_t*)malloc(loaded[i].len);
      if (!loaded[i].data) {
        free_samovar_nvs_backup(loaded, i + 1);
        free(blob);
        Serial.println(F("NVS: Compaction backup restore failed, no RAM for value"));
        return false;
      }
      memcpy(loaded[i].data, cursor, loaded[i].len);
      cursor += loaded[i].len;
    }
  }

  if (cursor != end) {
    free_samovar_nvs_backup(loaded, header.count);
    free(blob);
    Serial.println(F("NVS: Compaction backup restore failed, trailing data"));
    return false;
  }

  free(blob);
  entries = loaded;
  count = header.count;
  return true;
}

static void clear_samovar_nvs_compaction_backup() {
  nvs_handle_t handle;
  esp_err_t err = nvs_open(SAMOVAR_NVS_COMPACTION_BACKUP_NAMESPACE, NVS_READWRITE, &handle);
  if (err == ESP_OK) {
    nvs_erase_all(handle);
    nvs_commit(handle);
    nvs_close(handle);
  }
}

static bool recover_pending_samovar_nvs_compaction() {
  SamovarNvsEntryBackup* entries = nullptr;
  size_t count = 0;
  if (!load_samovar_nvs_compaction_backup(entries, count)) {
    return true;
  }

  Serial.print(F("NVS: Restoring interrupted compaction backup, keys = "));
  Serial.println(count);
  bool ok = restore_samovar_nvs_entries(entries, count);
  free_samovar_nvs_backup(entries, count);
  if (ok) {
    clear_samovar_nvs_compaction_backup();
    Serial.println(F("NVS: Interrupted compaction backup restored"));
  } else {
    Serial.println(F("NVS: Interrupted compaction backup restore failed; backup kept"));
  }
  return ok;
}

bool recover_pending_nvs_compaction() {
  return recover_pending_samovar_nvs_compaction();
}

static bool compact_samovar_nvs_namespaces() {
  static bool compacting = false;
  if (compacting) return false;
  compacting = true;

  if (!recover_pending_samovar_nvs_compaction()) {
    compacting = false;
    return false;
  }

  SamovarNvsEntryBackup* entries = (SamovarNvsEntryBackup*)calloc(SAMOVAR_NVS_BACKUP_MAX_ENTRIES, sizeof(SamovarNvsEntryBackup));
  if (!entries) {
    Serial.println(F("NVS: Samovar namespace compaction failed, no RAM"));
    compacting = false;
    return false;
  }

  size_t count = 0;
  bool ok = backup_samovar_nvs_entries(entries, SAMOVAR_NVS_BACKUP_MAX_ENTRIES, count);

  if (!ok) {
    free_samovar_nvs_backup(entries, count);
    compacting = false;
    return false;
  }

  Serial.print(F("NVS: Compacting Samovar namespaces, all keys = "));
  Serial.println(count);

  if (!save_samovar_nvs_compaction_backup(entries, count)) {
    Serial.println(F("NVS: Samovar namespace compaction aborted, backup not durable"));
    free_samovar_nvs_backup(entries, count);
    compacting = false;
    return false;
  }

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
    ok = restore_samovar_nvs_entries(entries, count);
  }

  free_samovar_nvs_backup(entries, count);
  compacting = false;

  if (ok) {
    clear_samovar_nvs_compaction_backup();
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

// Хелпер для сохранения строк (char array -> String -> NVS)
void saveStringIfChanged(const char* key, const char* value) {
  String current = prefs.getString(key, "");
  if (current != String(value)) {
    if (prefs.putString(key, String(value)) == 0 && value[0] != '\0') {
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
      retryingProfileSave = false;
      if (nvsProfileWriteFailed) {
        Serial.println(F("NVS: Profile write failed after compaction; full NVS rebuild is disabled"));
        print_nvs_stats("profile save failed");
      }
    } else {
      Serial.println(F("NVS: Profile write failed after compaction"));
      print_nvs_stats("profile save failed");
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

  set_default_setup_profile();

  // Читаем с дефолтными значениями. Для flag используем 255, чтобы определить "пустой NVS"
  SamSetup.flag = prefs.getUChar("flag", 255);
  SamSetup.Mode = prefs.getUShort("Mode", SamSetup.Mode);
  SamSetup.TimeZone = prefs.getUChar("TimeZone", SamSetup.TimeZone);
  SamSetup.HeaterResistant = prefs.getFloat("HeaterR", SamSetup.HeaterResistant);
  SamSetup.LogPeriod = prefs.getUChar("LogPeriod", SamSetup.LogPeriod);

  SamSetup.SetSteamTemp = prefs.getFloat("SetSteam", SamSetup.SetSteamTemp);
  SamSetup.SetPipeTemp = prefs.getFloat("SetPipe", SamSetup.SetPipeTemp);
  SamSetup.SetWaterTemp = prefs.getFloat("SetWater", SamSetup.SetWaterTemp);
  SamSetup.SetTankTemp = prefs.getFloat("SetTank", SamSetup.SetTankTemp);
  SamSetup.SetACPTemp = prefs.getFloat("SetACP", SamSetup.SetACPTemp);
  SamSetup.DistTemp = prefs.getFloat("DistTemp", SamSetup.DistTemp);

  SamSetup.DeltaSteamTemp = prefs.getFloat("DeltaSteam", SamSetup.DeltaSteamTemp);
  SamSetup.DeltaPipeTemp = prefs.getFloat("DeltaPipe", SamSetup.DeltaPipeTemp);
  SamSetup.DeltaWaterTemp = prefs.getFloat("DeltaWater", SamSetup.DeltaWaterTemp);
  SamSetup.DeltaTankTemp = prefs.getFloat("DeltaTank", SamSetup.DeltaTankTemp);
  SamSetup.DeltaACPTemp = prefs.getFloat("DeltaACP", SamSetup.DeltaACPTemp);

  SamSetup.SteamDelay = prefs.getUShort("SteamDelay", SamSetup.SteamDelay);
  SamSetup.PipeDelay = prefs.getUShort("PipeDelay", SamSetup.PipeDelay);
  SamSetup.WaterDelay = prefs.getUShort("WaterDelay", SamSetup.WaterDelay);
  SamSetup.TankDelay = prefs.getUShort("TankDelay", SamSetup.TankDelay);
  SamSetup.ACPDelay = prefs.getUShort("ACPDelay", SamSetup.ACPDelay);

  SamSetup.StepperStepMl = prefs.getUShort("StepMl", SamSetup.StepperStepMl);
  SamSetup.StepperStepMlI2C = prefs.getUShort("StepMlI2C", SamSetup.StepperStepMlI2C);
  SamSetup.useautospeed = prefs.getBool("AutoSpeed", SamSetup.useautospeed);
  SamSetup.useDetectorOnHeads = prefs.getBool("DetOnHeads", SamSetup.useDetectorOnHeads);
  SamSetup.autospeed = prefs.getUChar("SpeedPerc", SamSetup.autospeed);
  SamSetup.UseWS = prefs.getBool("UseWS", SamSetup.UseWS);

  SamSetup.Kp = prefs.getFloat("Kp", SamSetup.Kp);
  SamSetup.Ki = prefs.getFloat("Ki", SamSetup.Ki);
  SamSetup.Kd = prefs.getFloat("Kd", SamSetup.Kd);
  SamSetup.StbVoltage = prefs.getFloat("StbVolt", SamSetup.StbVoltage);
  SamSetup.BVolt = prefs.getFloat("BVolt", SamSetup.BVolt);
  SamSetup.CheckPower = prefs.getBool("CheckPwr", SamSetup.CheckPower);
  SamSetup.UseST = prefs.getBool("UseST", SamSetup.UseST);

  SamSetup.rele1 = prefs.getBool("rele1", SamSetup.rele1);
  SamSetup.rele2 = prefs.getBool("rele2", SamSetup.rele2);
  SamSetup.rele3 = prefs.getBool("rele3", SamSetup.rele3);
  SamSetup.rele4 = prefs.getBool("rele4", SamSetup.rele4);

  // Чтение массивов
  loadBytesOrInvalid("SteamAddr", SamSetup.SteamAdress, 8);
  loadBytesOrInvalid("PipeAddr", SamSetup.PipeAdress, 8);
  loadBytesOrInvalid("WaterAddr", SamSetup.WaterAdress, 8);
  loadBytesOrInvalid("TankAddr", SamSetup.TankAdress, 8);
  loadBytesOrInvalid("ACPAddr", SamSetup.ACPAdress, 8);

  // Чтение строк (в буферы структуры)
  copyStringSafe(SamSetup.SteamColor, getColorOrDefault("SteamCol", SamSetup.SteamColor));
  copyStringSafe(SamSetup.PipeColor, getColorOrDefault("PipeCol", SamSetup.PipeColor));
  copyStringSafe(SamSetup.WaterColor, getColorOrDefault("WaterCol", SamSetup.WaterColor));
  copyStringSafe(SamSetup.TankColor, getColorOrDefault("TankCol", SamSetup.TankColor));
  copyStringSafe(SamSetup.ACPColor, getColorOrDefault("ACPCol", SamSetup.ACPColor));
  
  copyStringSafe(SamSetup.blynkauth, prefs.getString("blynk", ""));
  copyStringSafe(SamSetup.videourl, prefs.getString("video", ""));
  copyStringSafe(SamSetup.tg_token, prefs.getString("tg_tok", ""));
  copyStringSafe(SamSetup.tg_chat_id, prefs.getString("tg_id", ""));

  SamSetup.UsePreccureCorrect = prefs.getBool("Preccure", SamSetup.UsePreccureCorrect);
  SamSetup.ChangeProgramBuzzer = prefs.getBool("PrgBuzz", SamSetup.ChangeProgramBuzzer);
  SamSetup.UseBuzzer = prefs.getBool("UseBuzz", SamSetup.UseBuzzer);
  SamSetup.UseBBuzzer = prefs.getBool("UseBBuzz", SamSetup.UseBBuzzer);
  SamSetup.DistTimeF = prefs.getUChar("DistTimeF", SamSetup.DistTimeF);
  SamSetup.UseHLS = prefs.getBool("UseHLS", SamSetup.UseHLS);
  SamSetup.MaxPressureValue = prefs.getFloat("MaxPress", SamSetup.MaxPressureValue);

  SamSetup.NbkIn = prefs.getFloat("NbkIn", SamSetup.NbkIn);
  SamSetup.NbkDelta = prefs.getFloat("NbkDelta", SamSetup.NbkDelta);
  SamSetup.NbkDM = prefs.getFloat("NbkDM", SamSetup.NbkDM);
  SamSetup.NbkDP = prefs.getFloat("NbkDP", SamSetup.NbkDP);
  SamSetup.NbkSteamT = prefs.getFloat("NbkSteamT", SamSetup.NbkSteamT);
  SamSetup.NbkOwPress = prefs.getFloat("NbkOwPress", SamSetup.NbkOwPress);

  // --- Параметры колонны ---
  SamSetup.ColDiam = prefs.getFloat("ColDiam", SamSetup.ColDiam);
  SamSetup.ColHeight = prefs.getFloat("ColHeight", SamSetup.ColHeight);
  SamSetup.PackDens = prefs.getUChar("PackDens", SamSetup.PackDens);

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
