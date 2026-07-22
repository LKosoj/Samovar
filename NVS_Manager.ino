#include <Preferences.h>
#include <EEPROM.h>

#include <limits>
#include <type_traits>

#include "Samovar.h"
#include "samovar_api.h"
#include "profile_store.h"

static const char* const SAMOVAR_PROFILE_NAMESPACE = "sam_cfg";
static const char* const SAMOVAR_PROFILE_KEY = "profile";
static const uint16_t SAMOVAR_PROFILE_FORMAT_VERSION = 1;
static const size_t SAMOVAR_PROFILE_PAYLOAD_SIZE_V1 = 516;
static const size_t SAMOVAR_PROFILE_CANONICAL_BYTES_V1 = 515;

static_assert(sizeof(SetupEEPROM) == 532,
              "SetupEEPROM v1 ABI changed; bump the profile format version");
static_assert(std::is_trivially_copyable<SetupEEPROM>::value,
              "SetupEEPROM must remain trivially copyable");
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559,
              "profile v1 requires IEEE-754 binary32 float");
static_assert(sizeof(int) == 4, "profile v1 requires 32-bit int");

using ProfileCodec = ProfileBlobCodec<
    SAMOVAR_PROFILE_PAYLOAD_SIZE_V1,
    SAMOVAR_PROFILE_FORMAT_VERSION>;

enum ProfileValueResult : uint8_t {
  PROFILE_VALUE_FOUND = 0,
  PROFILE_VALUE_ABSENT,
  PROFILE_VALUE_ERROR,
};

static bool encode_setup_payload(
    const SetupEEPROM& candidate,
    uint8_t* payload) {
  CanonicalProfileWriter<SAMOVAR_PROFILE_PAYLOAD_SIZE_V1> writer(payload);
  const bool encoded =
      writer.put_u8(candidate.flag) &&
      writer.put_float(candidate.DeltaSteamTemp) &&
      writer.put_float(candidate.DeltaPipeTemp) &&
      writer.put_float(candidate.DeltaWaterTemp) &&
      writer.put_float(candidate.DeltaTankTemp) &&
      writer.put_u16(candidate.StepperStepMl) &&
      writer.put_float(candidate.SetSteamTemp) &&
      writer.put_float(candidate.SetPipeTemp) &&
      writer.put_float(candidate.SetWaterTemp) &&
      writer.put_float(candidate.SetTankTemp) &&
      writer.put_bool(candidate.UsePreccureCorrect) &&
      writer.put_u16(candidate.SteamDelay) &&
      writer.put_u16(candidate.PipeDelay) &&
      writer.put_u16(candidate.WaterDelay) &&
      writer.put_u16(candidate.TankDelay) &&
      writer.put_u8(candidate.TimeZone) &&
      writer.put_float(candidate.HeaterResistant) &&
      writer.put_u8(candidate.LogPeriod) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.SteamColor), sizeof(candidate.SteamColor)) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.PipeColor), sizeof(candidate.PipeColor)) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.WaterColor), sizeof(candidate.WaterColor)) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.TankColor), sizeof(candidate.TankColor)) &&
      writer.put_bool(candidate.rele1) &&
      writer.put_bool(candidate.rele2) &&
      writer.put_bool(candidate.rele3) &&
      writer.put_bool(candidate.rele4) &&
      writer.put_bytes(candidate.SteamAdress, sizeof(candidate.SteamAdress)) &&
      writer.put_bytes(candidate.PipeAdress, sizeof(candidate.PipeAdress)) &&
      writer.put_bytes(candidate.WaterAdress, sizeof(candidate.WaterAdress)) &&
      writer.put_bytes(candidate.TankAdress, sizeof(candidate.TankAdress)) &&
      writer.put_bool(candidate.useautospeed) &&
      writer.put_bool(candidate.useDetectorOnHeads) &&
      writer.put_u8(candidate.autospeed) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.blynkauth), sizeof(candidate.blynkauth)) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.videourl), sizeof(candidate.videourl)) &&
      writer.put_float(candidate.DistTemp) &&
      writer.put_i32(int32_t(candidate.Mode)) &&
      writer.put_bytes(candidate.ACPAdress, sizeof(candidate.ACPAdress)) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.ACPColor), sizeof(candidate.ACPColor)) &&
      writer.put_float(candidate.DeltaACPTemp) &&
      writer.put_float(candidate.SetACPTemp) &&
      writer.put_u16(candidate.ACPDelay) &&
      writer.put_float(candidate.Kp) &&
      writer.put_float(candidate.Ki) &&
      writer.put_float(candidate.Kd) &&
      writer.put_float(candidate.StbVoltage) &&
      writer.put_bool(candidate.ChangeProgramBuzzer) &&
      writer.put_bool(candidate.UseBuzzer) &&
      writer.put_bool(candidate.CheckPower) &&
      writer.put_bool(candidate.UseBBuzzer) &&
      writer.put_bool(candidate.UseWS) &&
      writer.put_float(candidate.BVolt) &&
      writer.put_bool(candidate.UseST) &&
      writer.put_u8(candidate.DistTimeF) &&
      writer.put_bool(candidate.UseHLS) &&
      writer.put_float(candidate.MaxPressureValue) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.tg_token), sizeof(candidate.tg_token)) &&
      writer.put_bytes(reinterpret_cast<const uint8_t*>(candidate.tg_chat_id), sizeof(candidate.tg_chat_id)) &&
      writer.put_float(candidate.NbkIn) &&
      writer.put_float(candidate.NbkDelta) &&
      writer.put_float(candidate.NbkDM) &&
      writer.put_float(candidate.NbkDP) &&
      writer.put_float(candidate.NbkSteamT) &&
      writer.put_float(candidate.NbkOwPress) &&
      writer.put_float(candidate.ColDiam) &&
      writer.put_float(candidate.ColHeight) &&
      writer.put_u8(candidate.PackDens) &&
      writer.put_u16(candidate.StepperStepMlI2C) &&
      writer.put_float(candidate.NbkTn) &&
      writer.put_float(candidate.BKPower) &&
      writer.put_float(candidate.MainsVoltage) &&
      writer.put_float(candidate.SuvidTemp);
  return encoded && writer.size() == SAMOVAR_PROFILE_CANONICAL_BYTES_V1 &&
         writer.finish();
}

static bool decode_setup_payload(
    const uint8_t* payload,
    SetupEEPROM& candidate) {
  SetupEEPROM decoded{};
  int32_t mode = 0;
  CanonicalProfileReader<SAMOVAR_PROFILE_PAYLOAD_SIZE_V1> reader(payload);
  const bool decodedFields =
      reader.get_u8(decoded.flag) &&
      reader.get_float(decoded.DeltaSteamTemp) &&
      reader.get_float(decoded.DeltaPipeTemp) &&
      reader.get_float(decoded.DeltaWaterTemp) &&
      reader.get_float(decoded.DeltaTankTemp) &&
      reader.get_u16(decoded.StepperStepMl) &&
      reader.get_float(decoded.SetSteamTemp) &&
      reader.get_float(decoded.SetPipeTemp) &&
      reader.get_float(decoded.SetWaterTemp) &&
      reader.get_float(decoded.SetTankTemp) &&
      reader.get_bool(decoded.UsePreccureCorrect) &&
      reader.get_u16(decoded.SteamDelay) &&
      reader.get_u16(decoded.PipeDelay) &&
      reader.get_u16(decoded.WaterDelay) &&
      reader.get_u16(decoded.TankDelay) &&
      reader.get_u8(decoded.TimeZone) &&
      reader.get_float(decoded.HeaterResistant) &&
      reader.get_u8(decoded.LogPeriod) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.SteamColor), sizeof(decoded.SteamColor)) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.PipeColor), sizeof(decoded.PipeColor)) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.WaterColor), sizeof(decoded.WaterColor)) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.TankColor), sizeof(decoded.TankColor)) &&
      reader.get_bool(decoded.rele1) &&
      reader.get_bool(decoded.rele2) &&
      reader.get_bool(decoded.rele3) &&
      reader.get_bool(decoded.rele4) &&
      reader.get_bytes(decoded.SteamAdress, sizeof(decoded.SteamAdress)) &&
      reader.get_bytes(decoded.PipeAdress, sizeof(decoded.PipeAdress)) &&
      reader.get_bytes(decoded.WaterAdress, sizeof(decoded.WaterAdress)) &&
      reader.get_bytes(decoded.TankAdress, sizeof(decoded.TankAdress)) &&
      reader.get_bool(decoded.useautospeed) &&
      reader.get_bool(decoded.useDetectorOnHeads) &&
      reader.get_u8(decoded.autospeed) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.blynkauth), sizeof(decoded.blynkauth)) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.videourl), sizeof(decoded.videourl)) &&
      reader.get_float(decoded.DistTemp) &&
      reader.get_i32(mode) &&
      reader.get_bytes(decoded.ACPAdress, sizeof(decoded.ACPAdress)) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.ACPColor), sizeof(decoded.ACPColor)) &&
      reader.get_float(decoded.DeltaACPTemp) &&
      reader.get_float(decoded.SetACPTemp) &&
      reader.get_u16(decoded.ACPDelay) &&
      reader.get_float(decoded.Kp) &&
      reader.get_float(decoded.Ki) &&
      reader.get_float(decoded.Kd) &&
      reader.get_float(decoded.StbVoltage) &&
      reader.get_bool(decoded.ChangeProgramBuzzer) &&
      reader.get_bool(decoded.UseBuzzer) &&
      reader.get_bool(decoded.CheckPower) &&
      reader.get_bool(decoded.UseBBuzzer) &&
      reader.get_bool(decoded.UseWS) &&
      reader.get_float(decoded.BVolt) &&
      reader.get_bool(decoded.UseST) &&
      reader.get_u8(decoded.DistTimeF) &&
      reader.get_bool(decoded.UseHLS) &&
      reader.get_float(decoded.MaxPressureValue) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.tg_token), sizeof(decoded.tg_token)) &&
      reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.tg_chat_id), sizeof(decoded.tg_chat_id)) &&
      reader.get_float(decoded.NbkIn) &&
      reader.get_float(decoded.NbkDelta) &&
      reader.get_float(decoded.NbkDM) &&
      reader.get_float(decoded.NbkDP) &&
      reader.get_float(decoded.NbkSteamT) &&
      reader.get_float(decoded.NbkOwPress) &&
      reader.get_float(decoded.ColDiam) &&
      reader.get_float(decoded.ColHeight) &&
      reader.get_u8(decoded.PackDens) &&
      reader.get_u16(decoded.StepperStepMlI2C) &&
      reader.get_float(decoded.NbkTn) &&
      reader.get_float(decoded.BKPower) &&
      reader.get_float(decoded.MainsVoltage) &&
      reader.get_float(decoded.SuvidTemp);
  if (!decodedFields ||
      reader.size() != SAMOVAR_PROFILE_CANONICAL_BYTES_V1 ||
      !reader.finish()) {
    return false;
  }
  decoded.Mode = int(mode);
  candidate = decoded;
  return true;
}

static const char* legacy_profile_namespace_by_mode(uint8_t mode) {
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

static uint8_t nvs_value_result(esp_err_t error) {
  if (error == ESP_OK) return PROFILE_VALUE_FOUND;
  return error == ESP_ERR_NVS_NOT_FOUND
      ? PROFILE_VALUE_ABSENT
      : PROFILE_VALUE_ERROR;
}

static uint8_t nvs_blob_size(
    nvs_handle_t handle,
    const char* key,
    size_t& size) {
  size = 0;
  return nvs_value_result(nvs_get_blob(handle, key, nullptr, &size));
}

static uint8_t nvs_read_blob(
    nvs_handle_t handle,
    const char* key,
    void* value,
    size_t& size) {
  return nvs_value_result(nvs_get_blob(handle, key, value, &size));
}

static uint8_t nvs_read_u8(
    nvs_handle_t handle,
    const char* key,
    uint8_t& value) {
  uint8_t stored = 0;
  const uint8_t result = nvs_value_result(
      nvs_get_u8(handle, key, &stored));
  if (result == PROFILE_VALUE_FOUND) value = stored;
  return result;
}

static uint8_t nvs_read_u16(
    nvs_handle_t handle,
    const char* key,
    uint16_t& value) {
  uint16_t stored = 0;
  const uint8_t result = nvs_value_result(
      nvs_get_u16(handle, key, &stored));
  if (result == PROFILE_VALUE_FOUND) value = stored;
  return result;
}

static uint8_t nvs_read_bool(
    nvs_handle_t handle,
    const char* key,
    bool& value) {
  uint8_t stored = 0;
  const uint8_t result = nvs_read_u8(handle, key, stored);
  if (result != PROFILE_VALUE_FOUND) return result;
  if (stored > 1U) return PROFILE_VALUE_ERROR;
  value = stored != 0;
  return PROFILE_VALUE_FOUND;
}

static uint8_t nvs_read_float(
    nvs_handle_t handle,
    const char* key,
    float& value) {
  size_t storedSize = 0;
  uint8_t result = nvs_blob_size(handle, key, storedSize);
  if (result != PROFILE_VALUE_FOUND) return result;
  if (storedSize != sizeof(float)) return PROFILE_VALUE_ERROR;
  float stored = 0;
  size_t readSize = sizeof(stored);
  result = nvs_read_blob(handle, key, &stored, readSize);
  if (result != PROFILE_VALUE_FOUND || readSize != sizeof(stored)) {
    return PROFILE_VALUE_ERROR;
  }
  value = stored;
  return PROFILE_VALUE_FOUND;
}

static uint8_t nvs_read_bytes(
    nvs_handle_t handle,
    const char* key,
    uint8_t* value,
    size_t expectedSize) {
  size_t storedSize = 0;
  uint8_t result = nvs_blob_size(handle, key, storedSize);
  if (result != PROFILE_VALUE_FOUND) return result;
  if (storedSize != expectedSize) return PROFILE_VALUE_ERROR;
  size_t readSize = expectedSize;
  result = nvs_read_blob(handle, key, value, readSize);
  return result == PROFILE_VALUE_FOUND && readSize == expectedSize
      ? PROFILE_VALUE_FOUND
      : PROFILE_VALUE_ERROR;
}

static uint8_t nvs_read_string(
    nvs_handle_t handle,
    const char* key,
    char* value,
    size_t capacity) {
  size_t storedSize = 0;
  uint8_t result = nvs_value_result(
      nvs_get_str(handle, key, nullptr, &storedSize));
  if (result != PROFILE_VALUE_FOUND) return result;
  if (storedSize == 0 || storedSize > capacity) return PROFILE_VALUE_ERROR;
  size_t readSize = storedSize;
  result = nvs_value_result(nvs_get_str(handle, key, value, &readSize));
  if (result != PROFILE_VALUE_FOUND || readSize != storedSize ||
      value[storedSize - 1] != '\0') {
    return PROFILE_VALUE_ERROR;
  }
  return PROFILE_VALUE_FOUND;
}

static PersistResult persist_codec_result(ProfileCodecResult result) {
  switch (result) {
    case PROFILE_CODEC_OK: return PERSIST_OK;
    case PROFILE_CODEC_MAGIC: return PERSIST_READBACK_MAGIC;
    case PROFILE_CODEC_VERSION: return PERSIST_READBACK_VERSION;
    case PROFILE_CODEC_PAYLOAD_SIZE: return PERSIST_READBACK_PAYLOAD_SIZE;
    case PROFILE_CODEC_CRC: return PERSIST_READBACK_CRC;
    case PROFILE_CODEC_STORED_SIZE: return PERSIST_STORED_SIZE_MISMATCH;
  }
  return PERSIST_READ_FAILED;
}

static ProfileLoadResult load_codec_result(ProfileCodecResult result) {
  switch (result) {
    case PROFILE_CODEC_OK: return PROFILE_LOAD_OK;
    case PROFILE_CODEC_MAGIC: return PROFILE_LOAD_MAGIC;
    case PROFILE_CODEC_VERSION: return PROFILE_LOAD_VERSION;
    case PROFILE_CODEC_PAYLOAD_SIZE: return PROFILE_LOAD_PAYLOAD_SIZE;
    case PROFILE_CODEC_CRC: return PROFILE_LOAD_CRC;
    case PROFILE_CODEC_STORED_SIZE: return PROFILE_LOAD_STORED_SIZE_MISMATCH;
  }
  return PROFILE_LOAD_READ_FAILED;
}

const char* persist_result_code(PersistResult result) {
  switch (result) {
    case PERSIST_OK: return "ok";
    case PERSIST_OPEN_FAILED: return "open_failed";
    case PERSIST_WRITE_FAILED: return "write_failed";
    case PERSIST_SHORT_WRITE: return "short_write";
    case PERSIST_REOPEN_FAILED: return "reopen_failed";
    case PERSIST_STORED_SIZE_MISMATCH: return "stored_size_mismatch";
    case PERSIST_READ_FAILED: return "read_failed";
    case PERSIST_SHORT_READ: return "short_read";
    case PERSIST_READBACK_MAGIC: return "readback_magic";
    case PERSIST_READBACK_VERSION: return "readback_version";
    case PERSIST_READBACK_PAYLOAD_SIZE: return "readback_payload_size";
    case PERSIST_READBACK_CRC: return "readback_crc";
    case PERSIST_READBACK_PAYLOAD_ENCODING: return "readback_payload_encoding";
    case PERSIST_READBACK_MISMATCH: return "readback_mismatch";
  }
  return "read_failed";
}

const char* profile_load_result_code(ProfileLoadResult result) {
  switch (result) {
    case PROFILE_LOAD_OK: return "ok";
    case PROFILE_LOAD_NOT_FOUND: return "not_found";
    case PROFILE_LOAD_OPEN_FAILED: return "open_failed";
    case PROFILE_LOAD_STORED_SIZE_MISMATCH: return "stored_size_mismatch";
    case PROFILE_LOAD_READ_FAILED: return "read_failed";
    case PROFILE_LOAD_SHORT_READ: return "short_read";
    case PROFILE_LOAD_MAGIC: return "magic";
    case PROFILE_LOAD_VERSION: return "version";
    case PROFILE_LOAD_PAYLOAD_SIZE: return "payload_size";
    case PROFILE_LOAD_CRC: return "crc";
    case PROFILE_LOAD_PAYLOAD_ENCODING: return "payload_encoding";
    case PROFILE_LOAD_LEGACY_INVALID: return "legacy_invalid";
    case PROFILE_LOAD_EEPROM_OPEN_FAILED: return "eeprom_open_failed";
  }
  return "read_failed";
}

void print_nvs_stats(const char* context) {
  nvs_stats_t stats;
  const esp_err_t error = nvs_get_stats("nvs", &stats);
  if (error != ESP_OK) {
    Serial.print(F("NVS: Failed to read stats, err = "));
    Serial.println((int)error);
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

void set_default_setup_profile(SetupEEPROM& candidate) {
  candidate = {};

  candidate.flag = 2;
  candidate.Mode = SAMOVAR_RECTIFICATION_MODE;
  candidate.TimeZone = 3;
  candidate.HeaterResistant = 15.2;
  candidate.LogPeriod = 3;
  candidate.SetSteamTemp = 0;
  candidate.SetPipeTemp = 0;
  candidate.SetWaterTemp = 0;
  candidate.SetTankTemp = 0;
  candidate.SetACPTemp = 0;
  candidate.DistTemp = DEFAULT_DIST_TEMP;
  candidate.DeltaSteamTemp = 0.1;
  candidate.DeltaPipeTemp = 0.2;
  candidate.DeltaWaterTemp = 0;
  candidate.DeltaTankTemp = 0;
  candidate.DeltaACPTemp = 0;
  candidate.SteamDelay = 20;
  candidate.PipeDelay = 20;
  candidate.WaterDelay = 20;
  candidate.TankDelay = 20;
  candidate.ACPDelay = 20;
  candidate.StepperStepMl = STEPPER_STEP_ML;
  candidate.StepperStepMlI2C = I2C_STEPPER_STEP_ML_DEFAULT;
  candidate.useautospeed = false;
  candidate.useDetectorOnHeads = false;
  candidate.autospeed = 0;
  candidate.UseWS = true;
  candidate.Kp = 150.0;
  candidate.Ki = 1.4;
  candidate.Kd = 1.4;
  candidate.StbVoltage = 100.0;
  candidate.BVolt = 230.0;
#ifndef SAMOVAR_USE_SEM_AVR
  candidate.BKPower = 45.0f;
#else
  candidate.BKPower = 200.0f;
#endif
  candidate.MainsVoltage = 230.0f;
  candidate.CheckPower = false;
  candidate.UseST = true;
  candidate.rele1 = false;
  candidate.rele2 = false;
  candidate.rele3 = false;
  candidate.rele4 = false;
  memset(candidate.SteamAdress, 255, sizeof(candidate.SteamAdress));
  memset(candidate.PipeAdress, 255, sizeof(candidate.PipeAdress));
  memset(candidate.WaterAdress, 255, sizeof(candidate.WaterAdress));
  memset(candidate.TankAdress, 255, sizeof(candidate.TankAdress));
  memset(candidate.ACPAdress, 255, sizeof(candidate.ACPAdress));
  copyStringSafe(candidate.SteamColor, "#ff0000");
  copyStringSafe(candidate.PipeColor, "#0000ff");
  copyStringSafe(candidate.WaterColor, "#00bfff");
  copyStringSafe(candidate.TankColor, "#008000");
  copyStringSafe(candidate.ACPColor, "#800080");
  candidate.blynkauth[0] = '\0';
  candidate.videourl[0] = '\0';
  candidate.tg_token[0] = '\0';
  candidate.tg_chat_id[0] = '\0';
  candidate.UsePreccureCorrect = true;
  candidate.ChangeProgramBuzzer = false;
  candidate.UseBuzzer = false;
  candidate.UseBBuzzer = false;
  candidate.DistTimeF = 16;
  candidate.UseHLS = true;
  candidate.MaxPressureValue = 0;
  candidate.NbkIn = 0;
  candidate.NbkDelta = 0;
  candidate.NbkDM = 0;
  candidate.NbkDP = 0;
  candidate.NbkSteamT = 0;
  candidate.NbkOwPress = 0;
  candidate.ColDiam = 2.0f;
  candidate.ColHeight = 0.5f;
  candidate.PackDens = 80;
}

PersistResult save_profile_nvs(const SetupEEPROM& candidate) {
  uint8_t payload[ProfileCodec::PAYLOAD_SIZE] = {};
  if (!encode_setup_payload(candidate, payload)) {
    return PERSIST_READBACK_PAYLOAD_ENCODING;
  }
  ProfileCodec::Blob encoded{};
  ProfileCodec::encode(payload, encoded);

  Preferences writer;
  if (!writer.begin(SAMOVAR_PROFILE_NAMESPACE, false)) {
    return PERSIST_OPEN_FAILED;
  }
  const size_t written = writer.putBytes(
      SAMOVAR_PROFILE_KEY, encoded.bytes, ProfileCodec::BLOB_SIZE);
  writer.end();
  if (written == 0) return PERSIST_WRITE_FAILED;
  if (written != ProfileCodec::BLOB_SIZE) return PERSIST_SHORT_WRITE;

  nvs_handle_t readHandle;
  const esp_err_t openError = nvs_open(
      SAMOVAR_PROFILE_NAMESPACE, NVS_READONLY, &readHandle);
  if (openError != ESP_OK) return PERSIST_REOPEN_FAILED;

  size_t storedSize = 0;
  const uint8_t sizeResult = nvs_blob_size(
      readHandle, SAMOVAR_PROFILE_KEY, storedSize);
  if (sizeResult != PROFILE_VALUE_FOUND) {
    nvs_close(readHandle);
    return PERSIST_READ_FAILED;
  }
  if (storedSize != ProfileCodec::BLOB_SIZE) {
    nvs_close(readHandle);
    return PERSIST_STORED_SIZE_MISMATCH;
  }

  ProfileCodec::Blob readBack{};
  size_t readSize = ProfileCodec::BLOB_SIZE;
  const uint8_t readResult = nvs_read_blob(
      readHandle, SAMOVAR_PROFILE_KEY, readBack.bytes, readSize);
  nvs_close(readHandle);
  if (readResult != PROFILE_VALUE_FOUND) return PERSIST_READ_FAILED;
  if (readSize != ProfileCodec::BLOB_SIZE) return PERSIST_SHORT_READ;

  const PersistResult validation = persist_codec_result(ProfileCodec::decode(
      readBack.bytes, ProfileCodec::BLOB_SIZE, payload));
  if (validation != PERSIST_OK) return validation;
  if (memcmp(encoded.bytes, readBack.bytes, ProfileCodec::BLOB_SIZE) != 0) {
    return PERSIST_READBACK_MISMATCH;
  }
  return PERSIST_OK;
}

ProfileLoadResult load_profile_nvs(SetupEEPROM& candidate) {
  nvs_handle_t readHandle;
  const esp_err_t openError = nvs_open(
      SAMOVAR_PROFILE_NAMESPACE, NVS_READONLY, &readHandle);
  if (openError == ESP_ERR_NVS_NOT_FOUND) return PROFILE_LOAD_NOT_FOUND;
  if (openError != ESP_OK) return PROFILE_LOAD_OPEN_FAILED;

  size_t storedSize = 0;
  const uint8_t sizeResult = nvs_blob_size(
      readHandle, SAMOVAR_PROFILE_KEY, storedSize);
  if (sizeResult == PROFILE_VALUE_ABSENT) {
    nvs_close(readHandle);
    return PROFILE_LOAD_NOT_FOUND;
  }
  if (sizeResult == PROFILE_VALUE_ERROR) {
    nvs_close(readHandle);
    return PROFILE_LOAD_READ_FAILED;
  }
  if (storedSize != ProfileCodec::BLOB_SIZE) {
    nvs_close(readHandle);
    return PROFILE_LOAD_STORED_SIZE_MISMATCH;
  }

  ProfileCodec::Blob encoded{};
  size_t readSize = ProfileCodec::BLOB_SIZE;
  const uint8_t readResult = nvs_read_blob(
      readHandle, SAMOVAR_PROFILE_KEY, encoded.bytes, readSize);
  nvs_close(readHandle);
  if (readResult != PROFILE_VALUE_FOUND) return PROFILE_LOAD_READ_FAILED;
  if (readSize != ProfileCodec::BLOB_SIZE) return PROFILE_LOAD_SHORT_READ;

  uint8_t payload[ProfileCodec::PAYLOAD_SIZE] = {};
  const ProfileLoadResult validation = load_codec_result(ProfileCodec::decode(
      encoded.bytes, ProfileCodec::BLOB_SIZE, payload));
  if (validation != PROFILE_LOAD_OK) return validation;
  if (!decode_setup_payload(payload, candidate)) {
    return PROFILE_LOAD_PAYLOAD_ENCODING;
  }
  return PROFILE_LOAD_OK;
}

static ProfileLoadResult load_legacy_profile_namespace(
    const char* namespaceName,
    uint8_t mode,
    SetupEEPROM& candidate) {
  nvs_handle_t handle;
  const esp_err_t openError = nvs_open(namespaceName, NVS_READONLY, &handle);
  if (openError == ESP_ERR_NVS_NOT_FOUND) return PROFILE_LOAD_NOT_FOUND;
  if (openError != ESP_OK) return PROFILE_LOAD_OPEN_FAILED;

  SetupEEPROM loaded{};
  set_default_setup_profile(loaded);
  const uint8_t flagResult = nvs_read_u8(handle, "flag", loaded.flag);
  if (flagResult == PROFILE_VALUE_ABSENT) {
    nvs_close(handle);
    return PROFILE_LOAD_NOT_FOUND;
  }
  if (flagResult == PROFILE_VALUE_ERROR) {
    nvs_close(handle);
    return PROFILE_LOAD_READ_FAILED;
  }
  if (loaded.flag > 250) {
    nvs_close(handle);
    return PROFILE_LOAD_LEGACY_INVALID;
  }

  const bool readable =
      nvs_read_u8(handle, "TimeZone", loaded.TimeZone) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "HeaterR", loaded.HeaterResistant) != PROFILE_VALUE_ERROR &&
      nvs_read_u8(handle, "LogPeriod", loaded.LogPeriod) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "SetSteam", loaded.SetSteamTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "SetPipe", loaded.SetPipeTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "SetWater", loaded.SetWaterTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "SetTank", loaded.SetTankTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "SetACP", loaded.SetACPTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "DistTemp", loaded.DistTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "DeltaSteam", loaded.DeltaSteamTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "DeltaPipe", loaded.DeltaPipeTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "DeltaWater", loaded.DeltaWaterTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "DeltaTank", loaded.DeltaTankTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "DeltaACP", loaded.DeltaACPTemp) != PROFILE_VALUE_ERROR &&
      nvs_read_u16(handle, "SteamDelay", loaded.SteamDelay) != PROFILE_VALUE_ERROR &&
      nvs_read_u16(handle, "PipeDelay", loaded.PipeDelay) != PROFILE_VALUE_ERROR &&
      nvs_read_u16(handle, "WaterDelay", loaded.WaterDelay) != PROFILE_VALUE_ERROR &&
      nvs_read_u16(handle, "TankDelay", loaded.TankDelay) != PROFILE_VALUE_ERROR &&
      nvs_read_u16(handle, "ACPDelay", loaded.ACPDelay) != PROFILE_VALUE_ERROR &&
      nvs_read_u16(handle, "StepMl", loaded.StepperStepMl) != PROFILE_VALUE_ERROR &&
      nvs_read_u16(handle, "StepMlI2C", loaded.StepperStepMlI2C) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "AutoSpeed", loaded.useautospeed) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "DetOnHeads", loaded.useDetectorOnHeads) != PROFILE_VALUE_ERROR &&
      nvs_read_u8(handle, "SpeedPerc", loaded.autospeed) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "UseWS", loaded.UseWS) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "Kp", loaded.Kp) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "Ki", loaded.Ki) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "Kd", loaded.Kd) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "StbVolt", loaded.StbVoltage) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "BVolt", loaded.BVolt) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "CheckPwr", loaded.CheckPower) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "UseST", loaded.UseST) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "rele1", loaded.rele1) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "rele2", loaded.rele2) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "rele3", loaded.rele3) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "rele4", loaded.rele4) != PROFILE_VALUE_ERROR &&
      nvs_read_bytes(handle, "SteamAddr", loaded.SteamAdress, sizeof(loaded.SteamAdress)) != PROFILE_VALUE_ERROR &&
      nvs_read_bytes(handle, "PipeAddr", loaded.PipeAdress, sizeof(loaded.PipeAdress)) != PROFILE_VALUE_ERROR &&
      nvs_read_bytes(handle, "WaterAddr", loaded.WaterAdress, sizeof(loaded.WaterAdress)) != PROFILE_VALUE_ERROR &&
      nvs_read_bytes(handle, "TankAddr", loaded.TankAdress, sizeof(loaded.TankAdress)) != PROFILE_VALUE_ERROR &&
      nvs_read_bytes(handle, "ACPAddr", loaded.ACPAdress, sizeof(loaded.ACPAdress)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "SteamCol", loaded.SteamColor, sizeof(loaded.SteamColor)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "PipeCol", loaded.PipeColor, sizeof(loaded.PipeColor)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "WaterCol", loaded.WaterColor, sizeof(loaded.WaterColor)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "TankCol", loaded.TankColor, sizeof(loaded.TankColor)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "ACPCol", loaded.ACPColor, sizeof(loaded.ACPColor)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "blynk", loaded.blynkauth, sizeof(loaded.blynkauth)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "video", loaded.videourl, sizeof(loaded.videourl)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "tg_tok", loaded.tg_token, sizeof(loaded.tg_token)) != PROFILE_VALUE_ERROR &&
      nvs_read_string(handle, "tg_id", loaded.tg_chat_id, sizeof(loaded.tg_chat_id)) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "Preccure", loaded.UsePreccureCorrect) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "PrgBuzz", loaded.ChangeProgramBuzzer) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "UseBuzz", loaded.UseBuzzer) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "UseBBuzz", loaded.UseBBuzzer) != PROFILE_VALUE_ERROR &&
      nvs_read_u8(handle, "DistTimeF", loaded.DistTimeF) != PROFILE_VALUE_ERROR &&
      nvs_read_bool(handle, "UseHLS", loaded.UseHLS) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "MaxPress", loaded.MaxPressureValue) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "NbkIn", loaded.NbkIn) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "NbkDelta", loaded.NbkDelta) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "NbkDM", loaded.NbkDM) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "NbkDP", loaded.NbkDP) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "NbkSteamT", loaded.NbkSteamT) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "NbkOwPress", loaded.NbkOwPress) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "ColDiam", loaded.ColDiam) != PROFILE_VALUE_ERROR &&
      nvs_read_float(handle, "ColHeight", loaded.ColHeight) != PROFILE_VALUE_ERROR &&
      nvs_read_u8(handle, "PackDens", loaded.PackDens) != PROFILE_VALUE_ERROR;
  nvs_close(handle);
  if (!readable) return PROFILE_LOAD_READ_FAILED;
  loaded.Mode = mode;
  candidate = loaded;
  return PROFILE_LOAD_OK;
}

// "Последний режим" из sam_meta - только подсказка, с какого неймспейса начинать
// перебор в migrate_from_eeprom(): сам перебор всё равно обойдёт все режимы.
// Поэтому любой отказ здесь молча оставляет режим по умолчанию, выставленный
// первой строкой, и провалить им миграцию нельзя.
static void read_legacy_last_mode(uint8_t& mode) {
  mode = uint8_t(SAMOVAR_RECTIFICATION_MODE);
  nvs_handle_t handle;
  if (nvs_open("sam_meta", NVS_READONLY, &handle) != ESP_OK) return;
  uint8_t storedMode = mode;
  const uint8_t result = nvs_read_u8(handle, "last_mode", storedMode);
  nvs_close(handle);
  if (result == PROFILE_VALUE_FOUND && storedMode <= uint8_t(SAMOVAR_LUA_MODE)) {
    mode = storedMode;
  }
}

ProfileLoadResult migrate_from_eeprom(SetupEEPROM& candidate) {
  uint8_t lastMode = uint8_t(SAMOVAR_RECTIFICATION_MODE);
  read_legacy_last_mode(lastMode);

  // Непригодный источник не обрывает перебор: битый профиль в одном неймспейсе
  // не значит, что целого нет в соседнем (load_legacy_profile_namespace()
  // пишет в candidate только при полном успехе, так что неудачная попытка
  // ничего не портит). Но если не подойдёт никто, вернуть надо ПЕРВУЮ настоящую
  // причину, а не NOT_FOUND: setup() трактует NOT_FOUND как "мигрировать было
  // нечего" и молча кладёт дефолты без report_degraded_boot(), из-за чего потеря
  // настроек станет неотличима от первого запуска.
  ProfileLoadResult firstError = PROFILE_LOAD_NOT_FOUND;

  ProfileLoadResult result = load_legacy_profile_namespace(
      SAMOVAR_PROFILE_NAMESPACE, lastMode, candidate);
  if (result == PROFILE_LOAD_OK) return result;
  if (firstError == PROFILE_LOAD_NOT_FOUND) firstError = result;

  const char* selectedNamespace = legacy_profile_namespace_by_mode(lastMode);
  result = load_legacy_profile_namespace(selectedNamespace, lastMode, candidate);
  if (result == PROFILE_LOAD_OK) return result;
  if (firstError == PROFILE_LOAD_NOT_FOUND) firstError = result;

  for (uint8_t mode = uint8_t(SAMOVAR_RECTIFICATION_MODE);
       mode <= uint8_t(SAMOVAR_LUA_MODE);
       mode++) {
    const char* namespaceName = legacy_profile_namespace_by_mode(mode);
    if (strcmp(namespaceName, selectedNamespace) == 0) continue;
    result = load_legacy_profile_namespace(namespaceName, mode, candidate);
    if (result == PROFILE_LOAD_OK) return result;
    if (firstError == PROFILE_LOAD_NOT_FOUND) firstError = result;
  }

  if (!EEPROM.begin(sizeof(SetupEEPROM))) {
    return PROFILE_LOAD_EEPROM_OPEN_FAILED;
  }
  SetupEEPROM legacyEeprom{};
  EEPROM.get(0, legacyEeprom);
  EEPROM.end();
  // 255 в сыром EEPROM - байт стёртой страницы, то есть "сюда никогда не писали"
  // (аналог отсутствующего ключа в NVS). Это единственный выход, который иначе
  // проглотил бы найденную при переборе ошибку, поэтому только он и отдаёт
  // firstError; остальные и так возвращают настоящую причину. 251..254 стиранием
  // получиться не может - это настоящая порча.
  if (legacyEeprom.flag == 255) return firstError;
  if (legacyEeprom.flag > 250) return PROFILE_LOAD_LEGACY_INVALID;
  if (legacyEeprom.Mode < SAMOVAR_RECTIFICATION_MODE ||
      legacyEeprom.Mode > SAMOVAR_LUA_MODE) {
    legacyEeprom.Mode = SAMOVAR_RECTIFICATION_MODE;
  }
  candidate = legacyEeprom;
  return PROFILE_LOAD_OK;
}

// Зеркало ключей, которые читает load_legacy_profile_namespace(): именно они и
// остаются мусором после миграции. Списки обязаны совпадать - расхождение молча
// оставит часть ключей в NVS, поэтому его пинит
// tools/smoke_nvs_legacy_cleanup_contract.py.
static const char* const SAMOVAR_LEGACY_PROFILE_KEYS[] = {
  "flag", "TimeZone", "HeaterR", "LogPeriod",
  "SetSteam", "SetPipe", "SetWater", "SetTank",
  "SetACP", "DistTemp", "DeltaSteam", "DeltaPipe",
  "DeltaWater", "DeltaTank", "DeltaACP", "SteamDelay",
  "PipeDelay", "WaterDelay", "TankDelay", "ACPDelay",
  "StepMl", "StepMlI2C", "AutoSpeed", "DetOnHeads",
  "SpeedPerc", "UseWS", "Kp", "Ki",
  "Kd", "StbVolt", "BVolt", "CheckPwr",
  "UseST", "rele1", "rele2", "rele3",
  "rele4", "SteamAddr", "PipeAddr", "WaterAddr",
  "TankAddr", "ACPAddr", "SteamCol", "PipeCol",
  "WaterCol", "TankCol", "ACPCol", "blynk",
  "video", "tg_tok", "tg_id", "Preccure",
  "PrgBuzz", "UseBuzz", "UseBBuzz", "DistTimeF",
  "UseHLS", "MaxPress", "NbkIn", "NbkDelta",
  "NbkDM", "NbkDP", "NbkSteamT", "NbkOwPress",
  "ColDiam", "ColHeight", "PackDens",
};
static const size_t SAMOVAR_LEGACY_PROFILE_KEY_COUNT =
    sizeof(SAMOVAR_LEGACY_PROFILE_KEYS) / sizeof(SAMOVAR_LEGACY_PROFILE_KEYS[0]);

// Зеркало legacy_profile_namespace_by_mode(): по-режимные неймспейсы прошивок до
// перехода на общий профиль. Новый код в них не пишет, поэтому их можно стирать
// целиком - в отличие от sam_cfg, см. ниже.
static const char* const SAMOVAR_LEGACY_MODE_NAMESPACES[] = {
  "sam_rect", "sam_dist", "sam_beer", "sam_bk", "sam_nbk", "sam_suvid", "sam_lua",
};
static const size_t SAMOVAR_LEGACY_MODE_NAMESPACE_COUNT =
    sizeof(SAMOVAR_LEGACY_MODE_NAMESPACES) / sizeof(SAMOVAR_LEGACY_MODE_NAMESPACES[0]);

// Стирает legacy-остатки после миграции. Вызывать ТОЛЬКО когда save_profile_nvs()
// для нового профиля уже вернул PERSIST_OK: стирание до подтверждённой записи
// оставило бы окно, в котором пропадание питания уничтожает настройки насовсем,
// а обновление с прошлой прошивки идёт именно через эту миграцию.
//
// sam_cfg - смешанный: там и новый блоб profile, и старые по-полевые ключи,
// откуда migrate_from_eeprom() их и читает. nvs_erase_all() по нему стёр бы
// только что записанный профиль, поэтому ключи удаляются поимённо.
//
// Отказ стирания не мешает загрузке: мусор в NVS - это лишь занятое место.
void clear_migrated_legacy_profile_data() {
  nvs_handle_t cfgHandle;
  const esp_err_t cfgError =
      nvs_open(SAMOVAR_PROFILE_NAMESPACE, NVS_READWRITE, &cfgHandle);
  if (cfgError != ESP_OK) {
    Serial.print(F("NVS: legacy cleanup skipped, open failed, err = "));
    Serial.println((int)cfgError);
  } else {
    for (size_t i = 0; i < SAMOVAR_LEGACY_PROFILE_KEY_COUNT; i++) {
      const esp_err_t eraseError =
          nvs_erase_key(cfgHandle, SAMOVAR_LEGACY_PROFILE_KEYS[i]);
      // Одна битая запись не должна останавливать очистку остальных.
      if (eraseError != ESP_OK && eraseError != ESP_ERR_NVS_NOT_FOUND) {
        Serial.print(F("NVS: failed to erase legacy key "));
        Serial.println(SAMOVAR_LEGACY_PROFILE_KEYS[i]);
      }
    }
    if (nvs_commit(cfgHandle) != ESP_OK) {
      Serial.println(F("NVS: legacy key cleanup commit failed"));
    }
    nvs_close(cfgHandle);
  }

  for (size_t i = 0; i < SAMOVAR_LEGACY_MODE_NAMESPACE_COUNT; i++) {
    const char* namespaceName = SAMOVAR_LEGACY_MODE_NAMESPACES[i];
    // Проба на чтение: nvs_open(..., NVS_READWRITE, ...) СОЗДАЛ бы неймспейс,
    // которого нет, то есть насорил бы вместо очистки.
    nvs_handle_t probeHandle;
    if (nvs_open(namespaceName, NVS_READONLY, &probeHandle) != ESP_OK) continue;
    nvs_close(probeHandle);

    nvs_handle_t handle;
    if (nvs_open(namespaceName, NVS_READWRITE, &handle) != ESP_OK) {
      Serial.print(F("NVS: failed to open legacy namespace "));
      Serial.println(namespaceName);
      continue;
    }
    esp_err_t clearError = nvs_erase_all(handle);
    if (clearError == ESP_OK) clearError = nvs_commit(handle);
    nvs_close(handle);
    if (clearError != ESP_OK) {
      Serial.print(F("NVS: failed to clear legacy namespace "));
      Serial.println(namespaceName);
    }
  }
}
