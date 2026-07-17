#include <asyncHTTPrequest.h>
//#include <ESPping.h>
#include <WiFi.h>

#include "Samovar.h"
#include "samovar_api.h"
#include "FS.h"
#include "sensorinit.h"
#include "column_math.h"
#include "control_numeric_input.h"
#include "string_utils.h"
#include "program_io.h"
#include "runtime_helpers.h"

extern float nbk_M;
extern float nbk_Mo;
extern float nbk_P;
extern float nbk_Po;

const AsyncWebParameter* get_request_param(AsyncWebServerRequest *request, const char *name);
static uint8_t request_param_count(AsyncWebServerRequest *request, const char *name);
bool is_valid_samovar_mode(long mode);

static void send_no_store_response(
    AsyncWebServerRequest *request,
    uint16_t status,
    const char *contentType,
    const String& body) {
  AsyncWebServerResponse *response = request->beginResponse(status, contentType, body);
  response->addHeader("Cache-Control", "no-store");
  request->send(response);
}

// Единый конверт ошибок API: error - код для машины, field - имя поля для подсветки в форме
// (null, если ошибка не про поле), message - текст для человека.
// И имя поля, и текст приходят из запроса, поэтому оба обязаны идти через toJsonString():
// параметр вида a"b иначе порвёт JSON, и клиент получит исключение разбора вместо ошибки.
static String build_error_envelope(const char *code, const char *field, const String& message) {
  String json = "{\"error\":";
  json += toJsonString(code ? code : "internal_error");
  json += ",\"field\":";
  if (field && *field) json += toJsonString(field);
  else json += "null";
  json += ",\"message\":";
  json += toJsonString(message);
  json += '}';
  return json;
}

bool i2c_stepper_mode_supported(const I2CStepperDevice& dev);

// bypassBarrier=true для recovery-команд (reboot/resetwifi): путь восстановления не должен
// зависеть от исправности барьерной логики. Если из-за будущего дефекта mode_switch_barrier_active
// всё же зависнет намертво, reboot/resetwifi обязаны проходить в обход — иначе 503 BUSY навсегда,
// а перезагрузка/сброс Wi-Fi становятся недостижимы никаким другим путём.
static bool queue_pending_flag(volatile bool& flag, bool bypassBarrier = false) {
  if (!bypassBarrier && mode_switch_in_progress()) return false;
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if ((!bypassBarrier && mode_switch_in_progress()) || flag) {
    pending_command_unlock(true);
    return false;
  }
  flag = true;
  pending_command_unlock(true);
  return true;
}

static const uint8_t LOG_FLUSH_READY = 0;
static const uint8_t LOG_FLUSH_QUEUED = 1;
static const uint8_t LOG_FLUSH_BUSY = 2;

static uint8_t schedule_log_flush_if_needed() {
  if (log_flush_seq >= log_write_seq) return LOG_FLUSH_READY;
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return LOG_FLUSH_BUSY;
  uint32_t writeSeq = log_write_seq;
  if (log_flush_seq < writeSeq) {
    pending_log_flush_seq = writeSeq;
    pending_log_flush_flag = true;
    pending_command_unlock(true);
    return LOG_FLUSH_QUEUED;
  }
  pending_command_unlock(true);
  return LOG_FLUSH_READY;
}

static bool queue_pending_nbk(const ControlNbkCommand& value) {
  if (mode_switch_in_progress()) return false;
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (mode_switch_in_progress() || pending_pnbk_flag) {
    pending_command_unlock(true);
    return false;
  }
  pending_pnbk_value = value;
  __sync_synchronize();
  pending_pnbk_flag = true;
  pending_command_unlock(true);
  return true;
}

#ifdef USE_LUA
bool queue_pending_string(volatile bool& flag, String& valueSlot, const String& value) {
  if (mode_switch_in_progress()) return false;
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (mode_switch_in_progress() || flag) {
    pending_command_unlock(true);
    return false;
  }
  valueSlot = value;
  __sync_synchronize();
  flag = true;
  pending_command_unlock(true);
  return true;
}
#endif

static OperationError queue_profile_operation(
    OperationKind kind,
    const SetupEEPROM* settings,
    uint8_t sensorResetMask,
    const ProgramDraft* programDraft,
    ProgramUpdateAction programAction,
    uint8_t metadataFlags,
    float boilerVolume,
    const char* description,
    bool requireProgramIdle,
    bool modeChange,
    SAMOVAR_MODE sourceMode,
    SAMOVAR_MODE targetMode,
    OperationId& operationId) {
  const uint8_t allowedMetadata = PROFILE_OPERATION_METADATA_VOLUME |
                                  PROFILE_OPERATION_METADATA_DESCRIPTION;
  if ((kind != OPERATION_KIND_SAVE && kind != OPERATION_KIND_PROGRAM) ||
      (kind == OPERATION_KIND_SAVE && !settings) ||
      (kind == OPERATION_KIND_SAVE && metadataFlags != 0) ||
      (kind == OPERATION_KIND_PROGRAM &&
       (settings || sensorResetMask != 0 || modeChange ||
        sourceMode != targetMode ||
        (programAction == PROGRAM_UPDATE_NONE && metadataFlags == 0))) ||
      (sensorResetMask & ~(PROFILE_SENSOR_RESET_STEAM |
                           PROFILE_SENSOR_RESET_PIPE |
                           PROFILE_SENSOR_RESET_WATER |
                           PROFILE_SENSOR_RESET_TANK |
                           PROFILE_SENSOR_RESET_ACP)) != 0 ||
      (programAction == PROGRAM_UPDATE_REPLACE && !programDraft) ||
      (programAction != PROGRAM_UPDATE_REPLACE && programDraft) ||
      (programAction != PROGRAM_UPDATE_NONE &&
       programAction != PROGRAM_UPDATE_REPLACE &&
       programAction != PROGRAM_UPDATE_CLEAR) ||
      (metadataFlags & ~allowedMetadata) != 0 ||
      (modeChange && !settings) ||
      !is_valid_samovar_mode(sourceMode) || !is_valid_samovar_mode(targetMode)) {
    return OPERATION_ERROR_INTERNAL;
  }
  size_t descriptionLength = 0;
  if ((metadataFlags & PROFILE_OPERATION_METADATA_DESCRIPTION) != 0) {
    if (!description) return OPERATION_ERROR_INTERNAL;
    descriptionLength = strnlen(description, sizeof(active_profile_operation.description));
    if (descriptionLength >= sizeof(active_profile_operation.description)) {
      return OPERATION_ERROR_INTERNAL;
    }
  }

  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return OPERATION_ERROR_LOCK_BUSY;
  if (profile_operation_phase_load() != PROFILE_OPERATION_EMPTY) {
    pending_command_unlock(true);
    return OPERATION_ERROR_LOCK_BUSY;
  }
  if (mode_switch_in_progress() ||
      (requireProgramIdle && program_update_session_active()) ||
      Samovar_Mode != sourceMode) {
    pending_command_unlock(true);
    return OPERATION_ERROR_CANCELLED;
  }

  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, kind, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    pending_command_unlock(true);
    return reserveError;
  }

  reset_profile_operation_slot();
  if (settings) {
    active_profile_operation.settings = *settings;
    active_profile_operation.flags |= PROFILE_OPERATION_HAS_SETTINGS;
  }
  if (programDraft) active_profile_operation.program = *programDraft;
  if (programAction != PROGRAM_UPDATE_NONE) {
    active_profile_operation.flags |= PROFILE_OPERATION_HAS_PROGRAM;
  }
  active_profile_operation.flags |= metadataFlags;
  if (modeChange) active_profile_operation.flags |= PROFILE_OPERATION_MODE_CHANGE;
  if (requireProgramIdle) {
    active_profile_operation.flags |= PROFILE_OPERATION_REQUIRE_PROGRAM_IDLE;
  }
  if ((metadataFlags & PROFILE_OPERATION_METADATA_DESCRIPTION) != 0) {
    memcpy(active_profile_operation.description, description, descriptionLength + 1);
  }
  active_profile_operation.id = reservedId;
  active_profile_operation.boilerVolume = boilerVolume;
  active_profile_operation.sensorResetMask = sensorResetMask;
  active_profile_operation.sourceMode = static_cast<uint8_t>(sourceMode);
  active_profile_operation.targetMode = static_cast<uint8_t>(targetMode);
  active_profile_operation.programAction = programAction;
  if (modeChange) {
    portENTER_CRITICAL(&emergencyStopMux);
    mode_switch_barrier_active = true;
    portEXIT_CRITICAL(&emergencyStopMux);
  }
  profile_operation_phase_store(PROFILE_OPERATION_QUEUED);
  operationId = reservedId;
  pending_command_unlock(true);
  return OPERATION_ERROR_NONE;
}

static void send_program_json_response(AsyncWebServerRequest *request, uint16_t statusCode, bool ok, const String& err, const String& programText) {
  String json;
  json.reserve(programText.length() + err.length() + 48);
  json += "{\"ok\":";
  json += ok ? "true" : "false";
  json += ",\"err\":";
  json += toJsonString(err);
  json += ",\"program\":";
  json += toJsonString(programText);
  json += "}";
  AsyncWebServerResponse *response = request->beginResponse(statusCode, "application/json", json);
  response->addHeader("Cache-Control", "no-store");
  request->send(response);
}

static void send_program_operation_accepted(
    AsyncWebServerRequest *request,
    const String& programText,
    OperationId operationId) {
  String json;
  json.reserve(programText.length() + 112);
  json += "{\"ok\":true,\"err\":\"\",\"program\":";
  json += toJsonString(programText);
  json += ",\"operationId\":";
  json += String(static_cast<unsigned long>(operationId));
  json += ",\"state\":\"queued\",\"error\":\"none\"}";
  AsyncWebServerResponse *response = request->beginResponse(
      202, "application/json", json);
  response->addHeader("Cache-Control", "no-store");
  request->send(response);
}

static void send_save_operation_accepted(
    AsyncWebServerRequest *request,
    OperationId operationId) {
  String json = "{\"operationId\":";
  json += String(static_cast<unsigned long>(operationId));
  json += ",\"state\":\"queued\",\"error\":\"none\"}";
  AsyncWebServerResponse *response = request->beginResponse(
      202, "application/json", json);
  response->addHeader("Cache-Control", "no-store");
  request->send(response);
}

static void send_i2c_operation_accepted(
    AsyncWebServerRequest *request,
    OperationId operationId) {
  String json = "{\"operationId\":";
  json += String(static_cast<unsigned long>(operationId));
  json += ",\"state\":\"queued\",\"error\":\"none\"}";
  AsyncWebServerResponse *response = request->beginResponse(
      202, "application/json", json);
  response->addHeader("Cache-Control", "no-store");
  request->send(response);
}

static OperationError queue_pending_i2cpump(
    PendingI2CPumpCmd command, OperationId& operationId) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return OPERATION_ERROR_LOCK_BUSY;
  if (mode_switch_in_progress() || pending_i2cpump_flag ||
      i2c_stepper_config_busy(i2cStepperPump)) {
    pending_command_unlock(true);
    return OPERATION_ERROR_LOCK_BUSY;
  }
  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, OPERATION_KIND_I2C_PUMP, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    pending_command_unlock(true);
    return reserveError;
  }
  command.operationId = reservedId;
  pending_i2cpump_buf = command;
  __sync_synchronize();
  pending_i2cpump_flag = true;
  operationId = reservedId;
  pending_command_unlock(true);
  return OPERATION_ERROR_NONE;
}

static OperationError queue_pending_i2cstepper(
    PendingI2CStepperCmd command, OperationId& operationId) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return OPERATION_ERROR_LOCK_BUSY;
  I2CStepperDevice& device = command.device_sel == 0
      ? i2cStepperMixer
      : i2cStepperPump;
  if (mode_switch_in_progress() || pending_i2cstepper_flag ||
      command.device_sel > 1 || i2c_stepper_config_busy(device)) {
    pending_command_unlock(true);
    return command.device_sel > 1
        ? OPERATION_ERROR_INTERNAL
        : OPERATION_ERROR_LOCK_BUSY;
  }
  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, OPERATION_KIND_I2C_STEPPER, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    pending_command_unlock(true);
    return reserveError;
  }
  command.operationId = reservedId;
  pending_i2cstepper_buf = command;
  __sync_synchronize();
  pending_i2cstepper_flag = true;
  operationId = reservedId;
  pending_command_unlock(true);
  return OPERATION_ERROR_NONE;
}

static OperationError queue_pending_i2ccal(
    PendingI2CCalCmd command, OperationId& operationId) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return OPERATION_ERROR_LOCK_BUSY;
  const bool calibrationStateValid = command.is_finish
      ? I2CPumpCalibrating && startval != 100
      : startval == 0 && !I2CPumpCalibrating;
  if (mode_switch_in_progress() || pending_i2ccal_flag || pending_local_cal_flag ||
      !calibrationStateValid || i2c_stepper_config_busy(i2cStepperPump)) {
    pending_command_unlock(true);
    return OPERATION_ERROR_LOCK_BUSY;
  }
  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, OPERATION_KIND_CALIBRATION, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    pending_command_unlock(true);
    return reserveError;
  }
  command.operationId = reservedId;
  pending_i2ccal_buf = command;
  __sync_synchronize();
  pending_i2ccal_flag = true;
  operationId = reservedId;
  pending_command_unlock(true);
  return OPERATION_ERROR_NONE;
}

static OperationError queue_pending_local_cal(
    PendingLocalCalCmd command, OperationId& operationId) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return OPERATION_ERROR_LOCK_BUSY;
  const bool calibrationStateValid = command.is_finish
      ? startval == 100 && !I2CPumpCalibrating
      : startval == 0 && !I2CPumpCalibrating;
  if (mode_switch_in_progress() || pending_local_cal_flag || pending_i2ccal_flag ||
      !calibrationStateValid) {
    pending_command_unlock(true);
    return OPERATION_ERROR_LOCK_BUSY;
  }
  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, OPERATION_KIND_CALIBRATION, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    pending_command_unlock(true);
    return reserveError;
  }
  command.operationId = reservedId;
  pending_local_cal_buf = command;
  __sync_synchronize();
  pending_local_cal_flag = true;
  operationId = reservedId;
  pending_command_unlock(true);
  return OPERATION_ERROR_NONE;
}

I2CStepperDevice* select_i2c_stepper_device(AsyncWebServerRequest *request) {
  const AsyncWebParameter *param = get_request_param(request, "device");
  String device = param ? param->value() : "pump";
  if (device == "mixer") return &i2cStepperMixer;
  if (device == "pump") return &i2cStepperPump;
  return nullptr;
}

static NumericParseResult parse_i2c_stepper_u8(
    AsyncWebServerRequest *request,
    const char *name,
    uint8_t minValue,
    uint8_t maxValue,
    uint8_t& target,
    const char*& errorField) {
  const uint8_t count = request_param_count(request, name);
  if (count == 0) return numeric_parse_result(NUMERIC_PARSE_OK);
  if (count != 1) {
    errorField = name;
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  const AsyncWebParameter *param = get_request_param(request, name);
  uint8_t parsed = 0;
  NumericParseResult result = param && !param->isFile()
      ? parse_bounded_uint8(param->value().c_str(), minValue, maxValue, parsed)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) {
    errorField = name;
    return result;
  }
  target = parsed;
  return result;
}

static NumericParseResult parse_i2c_stepper_u16(
    AsyncWebServerRequest *request,
    const char *name,
    uint16_t minValue,
    uint16_t maxValue,
    uint16_t& target,
    const char*& errorField) {
  const uint8_t count = request_param_count(request, name);
  if (count == 0) return numeric_parse_result(NUMERIC_PARSE_OK);
  if (count != 1) {
    errorField = name;
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  const AsyncWebParameter *param = get_request_param(request, name);
  uint16_t parsed = 0;
  NumericParseResult result = param && !param->isFile()
      ? parse_bounded_uint16(param->value().c_str(), minValue, maxValue, parsed)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) {
    errorField = name;
    return result;
  }
  target = parsed;
  return result;
}

static bool i2c_stepper_config_param(const String& name) {
  return name == "mode" || name == "relayMask" || name == "sensorFlags" ||
         name == "optionFlags" || name == "mixerRpm" ||
         name == "mixerRunSec" || name == "mixerPauseSec" ||
         name == "pumpMlHour" || name == "pumpPauseSec" ||
         name == "fillingMl" || name == "fillingMlHour" ||
         name == "stepsPerMl";
}

static bool i2c_stepper_known_param(const String& name) {
  return name == "device" || name == "cmd" || name == "relay" ||
         name == "state" || i2c_stepper_config_param(name);
}

static NumericParseResult parse_i2c_stepper_patch(
    AsyncWebServerRequest *request,
    const String& command,
    const I2CStepperDevice& current,
    I2CStepperDevice& candidate,
    const char*& errorField) {
  I2CStepperDevice parsed = current;
  NumericParseResult result = parse_i2c_stepper_u8(request, "mode", 1, 3, parsed.mode, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u8(request, "relayMask", 0, 15, parsed.relayMask, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u8(request, "sensorFlags", 0, 7, parsed.sensorFlags, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u8(request, "optionFlags", 0, 7, parsed.optionFlags, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u16(request, "mixerRpm", 0, UINT16_MAX, parsed.mixerRpm, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u16(request, "mixerRunSec", 0, UINT16_MAX, parsed.mixerRunSec, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u16(request, "mixerPauseSec", 0, UINT16_MAX, parsed.mixerPauseSec, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u16(request, "pumpMlHour", 0, UINT16_MAX, parsed.pumpMlHour, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u16(request, "pumpPauseSec", 0, UINT16_MAX, parsed.pumpPauseSec, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u16(request, "fillingMl", 0, UINT16_MAX, parsed.fillingMl, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u16(request, "fillingMlHour", 0, UINT16_MAX, parsed.fillingMlHour, errorField);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_u16(request, "stepsPerMl", 1, UINT16_MAX, parsed.stepsPerMl, errorField);
  if (!result.ok()) return result;

  const uint8_t relayCount = request_param_count(request, "relay");
  const uint8_t stateCount = request_param_count(request, "state");
  const bool hasRelay = relayCount != 0;
  const bool hasState = stateCount != 0;
  if (hasRelay != hasState || relayCount > 1 || stateCount > 1) {
    errorField = hasRelay != hasState ? (hasRelay ? "state" : "relay")
        : (relayCount > 1 ? "relay" : "state");
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  if (hasRelay) {
    uint8_t relay = 0;
    bool state = false;
    const AsyncWebParameter *relayParam = get_request_param(request, "relay");
    const AsyncWebParameter *stateParam = get_request_param(request, "state");
    result = relayParam
        ? parse_bounded_uint8(relayParam->value().c_str(), 1, 4, relay)
        : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    if (!result.ok()) {
      errorField = "relay";
      return result;
    }
    result = stateParam
        ? parse_exact_bool(stateParam->value().c_str(), state)
        : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    if (!result.ok()) {
      errorField = "state";
      return result;
    }
    if (state) parsed.relayMask |= uint8_t(1U << (relay - 1));
    else parsed.relayMask &= uint8_t(~(1U << (relay - 1)));
  }

  bool hasConfig = false;
  for (size_t index = 0; index < request->params(); index++) {
    const AsyncWebParameter *param = request->getParam(index);
    if (param && i2c_stepper_config_param(param->name())) hasConfig = true;
  }
  if ((command == "status" || command == "stop" || command == "calfinish") &&
      (hasConfig || hasRelay || hasState)) {
    errorField = "cmd";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (command == "relay" && (!hasRelay || hasConfig)) {
    errorField = "relay";
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  if (command != "relay" && (hasRelay || hasState)) {
    errorField = "relay";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (current.address == I2CSTEPPER_MIXER_ADDR &&
      (request_param_count(request, "pumpMlHour") != 0 ||
       request_param_count(request, "pumpPauseSec") != 0 ||
       request_param_count(request, "fillingMl") != 0 ||
       request_param_count(request, "fillingMlHour") != 0 ||
       request_param_count(request, "stepsPerMl") != 0)) {
    errorField = "device";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (current.address == I2CSTEPPER_PUMP_ADDR &&
      (request_param_count(request, "mixerRpm") != 0 ||
       request_param_count(request, "mixerRunSec") != 0 ||
       request_param_count(request, "mixerPauseSec") != 0)) {
    errorField = "device";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  const bool validatesConfig = command == "apply" || command == "save" ||
      command == "start" || command == "calstart";
  if (validatesConfig && current.address == I2CSTEPPER_MIXER_ADDR &&
      parsed.mode != I2CSTEP_MODE_MIXER) {
    errorField = "mode";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (validatesConfig && current.address == I2CSTEPPER_PUMP_ADDR &&
      parsed.mode != I2CSTEP_MODE_PUMP && parsed.mode != I2CSTEP_MODE_FILLING) {
    errorField = "mode";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (validatesConfig && !i2c_stepper_mode_supported(parsed)) {
    errorField = "mode";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (hasConfig && parsed.sensorFlags != 0 &&
      (parsed.caps & I2CSTEPPER_CAP_SENSOR) == 0) {
    errorField = "sensorFlags";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (((hasConfig && parsed.relayMask != 0) || command == "relay") &&
      (parsed.caps & I2CSTEPPER_CAP_RELAY) == 0) {
    errorField = command == "relay" ? "relay" : "relayMask";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if ((command == "apply" || command == "save" || command == "start" || command == "calstart") &&
      parsed.address == I2CSTEPPER_PUMP_ADDR && parsed.stepsPerMl == 0) {
    errorField = "stepsPerMl";
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  if (command == "start") {
    const bool validStart = parsed.mode == I2CSTEP_MODE_MIXER ? parsed.mixerRpm > 0
        : parsed.mode == I2CSTEP_MODE_PUMP ? parsed.pumpMlHour > 0
        : parsed.fillingMl > 0 && parsed.fillingMlHour > 0;
    if (!validStart) {
      errorField = "mode";
      return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
    }
  }
  if ((command == "calstart" || command == "calfinish") &&
      (parsed.address != I2CSTEPPER_PUMP_ADDR ||
       (parsed.caps & I2CSTEPPER_CAP_FILLING) == 0)) {
    errorField = "cmd";
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (command == "calstart") {
    if (request_param_count(request, "stepsPerMl") != 1) {
      errorField = "stepsPerMl";
      return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    }
    const bool hasRate = parsed.mode == I2CSTEP_MODE_PUMP
        ? request_param_count(request, "pumpMlHour") == 1 && parsed.pumpMlHour > 0
        : request_param_count(request, "fillingMlHour") == 1 && parsed.fillingMlHour > 0;
    if (!hasRate) {
      errorField = parsed.mode == I2CSTEP_MODE_PUMP ? "pumpMlHour" : "fillingMlHour";
      return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    }
  }
  candidate = parsed;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

bool i2c_stepper_mode_supported(const I2CStepperDevice& dev) {
  if (dev.mode == I2CSTEP_MODE_MIXER) return (dev.caps & I2CSTEPPER_CAP_MIXER) != 0;
  if (dev.mode == I2CSTEP_MODE_PUMP) return (dev.caps & I2CSTEPPER_CAP_PUMP) != 0;
  if (dev.mode == I2CSTEP_MODE_FILLING) return (dev.caps & I2CSTEPPER_CAP_FILLING) != 0;
  return false;
}

bool i2c_stepper_command_supported(const I2CStepperDevice& dev, const String& cmd) {
  if (cmd == "status") return true;
  if (cmd == "relay") return (dev.caps & I2CSTEPPER_CAP_RELAY) != 0;
  if (cmd == "calstart" || cmd == "calfinish") return (dev.caps & I2CSTEPPER_CAP_FILLING) != 0;
  if (cmd == "apply" || cmd == "save" || cmd == "start") return i2c_stepper_mode_supported(dev);
  if (cmd == "stop") return (dev.caps & (I2CSTEPPER_CAP_MIXER | I2CSTEPPER_CAP_PUMP | I2CSTEPPER_CAP_FILLING)) != 0;
  return false;
}

void send_i2c_stepper_json(AsyncWebServerRequest *request, I2CStepperDevice& dev) {
  AsyncResponseStream *response = request->beginResponseStream("application/json");
  response->addHeader("Cache-Control", "no-store");
  response->print('{');
  response->print("\"present\":"); response->print(dev.present ? 1 : 0);
  response->print(",\"address\":"); response->print(dev.address);
  response->print(",\"role\":"); response->print(dev.role);
  response->print(",\"mode\":"); response->print(dev.mode);
  response->print(",\"caps\":"); response->print(dev.caps);
  response->print(",\"status\":"); response->print(dev.status);
  response->print(",\"error\":"); response->print(dev.error);
  response->print(",\"relayMask\":"); response->print(dev.relayMask);
  response->print(",\"sensorFlags\":"); response->print(dev.sensorFlags);
  response->print(",\"optionFlags\":"); response->print(dev.optionFlags);
  response->print(",\"mixerRpm\":"); response->print(dev.mixerRpm);
  response->print(",\"mixerRunSec\":"); response->print(dev.mixerRunSec);
  response->print(",\"mixerPauseSec\":"); response->print(dev.mixerPauseSec);
  response->print(",\"pumpMlHour\":"); response->print(dev.pumpMlHour);
  response->print(",\"pumpPauseSec\":"); response->print(dev.pumpPauseSec);
  response->print(",\"fillingMl\":"); response->print(dev.fillingMl);
  response->print(",\"fillingMlHour\":"); response->print(dev.fillingMlHour);
  response->print(",\"stepsPerMl\":"); response->print(dev.stepsPerMl);
  response->print(",\"remaining\":"); response->print(dev.remaining);
  response->print(",\"currentSpeed\":"); response->print(dev.currentSpeed);
  response->print('}');
  request->send(response);
}

static void send_i2c_numeric_error(
    AsyncWebServerRequest *request,
    const char *field,
    NumericParseError error) {
  String message = "Invalid ";
  message += field ? field : "request";
  send_no_store_response(
      request, 400, "application/json",
      build_error_envelope(numeric_parse_error_code(error), field, message));
}

static void handle_i2c_stepper_request(AsyncWebServerRequest *request) {
  for (size_t index = 0; index < request->params(); index++) {
    const AsyncWebParameter *param = request->getParam(index);
    if (!param || param->isFile() || param->isPost() ||
        !i2c_stepper_known_param(param->name()) ||
        request_param_count(request, param->name().c_str()) != 1) {
      send_i2c_numeric_error(
          request,
          param ? param->name().c_str() : "request",
          NUMERIC_PARSE_INVALID_ARGUMENT);
      return;
    }
  }

  const uint8_t deviceCount = request_param_count(request, "device");
  const uint8_t commandCount = request_param_count(request, "cmd");
  if (deviceCount > 1 || commandCount > 1) {
    send_i2c_numeric_error(
        request,
        deviceCount > 1 ? "device" : "cmd",
        NUMERIC_PARSE_INVALID_ARGUMENT);
    return;
  }
  const AsyncWebParameter *commandParam = get_request_param(request, "cmd");
  String command = commandParam ? commandParam->value() : "status";
  // /i2cstepper регистронезависима (STATUS ≡ status): протокол устройства и все сравнения
  // ниже используют нижний регистр, поэтому нормализуем команду один раз здесь.
  command.toLowerCase();
  if (command != "status" && command != "apply" && command != "save" &&
      command != "start" && command != "stop" && command != "calstart" &&
      command != "calfinish" && command != "relay") {
    send_i2c_numeric_error(request, "cmd", NUMERIC_PARSE_NOT_ALLOWED);
    return;
  }
  if (command != "status" && (deviceCount != 1 || commandCount != 1)) {
    send_i2c_numeric_error(
        request,
        deviceCount != 1 ? "device" : "cmd",
        NUMERIC_PARSE_INVALID_ARGUMENT);
    return;
  }

  I2CStepperDevice* dev = select_i2c_stepper_device(request);
  if (!dev) {
    send_i2c_numeric_error(request, "device", NUMERIC_PARSE_NOT_ALLOWED);
    return;
  }
  if (command == "status") {
    if (request->params() != deviceCount + commandCount) {
      send_i2c_numeric_error(request, "cmd", NUMERIC_PARSE_NOT_ALLOWED);
      return;
    }
    send_i2c_stepper_json(request, *dev);
    return;
  }
  if (!dev->present) {
    send_no_store_response(
        request, 404, "application/json",
        build_error_envelope("unavailable", nullptr, "I2C device not available"));
    return;
  }

  I2CStepperDevice staged = *dev;
  const char *errorField = "request";
  NumericParseResult result = parse_i2c_stepper_patch(
      request, command, *dev, staged, errorField);
  if (!result.ok()) {
    send_i2c_numeric_error(request, errorField, result.error);
    return;
  }
  if (!i2c_stepper_command_supported(staged, command)) {
    send_i2c_numeric_error(request, "cmd", NUMERIC_PARSE_NOT_ALLOWED);
    return;
  }

  PendingI2CStepperCmd pendingCmd = {};
  pendingCmd.staged = staged;
  pendingCmd.device_sel = dev == &i2cStepperMixer ? 0 : 1;
  strncpy(pendingCmd.cmd, command.c_str(), sizeof(pendingCmd.cmd) - 1);
  OperationId operationId = 0;
  const OperationError queueError = queue_pending_i2cstepper(
      pendingCmd, operationId);
  if (queueError != OPERATION_ERROR_NONE) {
    const char *code = queueError == OPERATION_ERROR_LOCK_BUSY
        ? "BUSY"
        : operation_error_code(queueError);
    send_no_store_response(
        request, 503, "application/json", build_error_envelope(code, nullptr, code));
    return;
  }
  send_i2c_operation_accepted(request, operationId);
}

static void handle_i2c_pump_request(AsyncWebServerRequest *request) {
  for (size_t index = 0; index < request->params(); index++) {
    const AsyncWebParameter *param = request->getParam(index);
    const bool known = param &&
        (param->name() == "stop" || param->name() == "speed" || param->name() == "volume");
    if (!known || param->isFile() || param->isPost() ||
        request_param_count(request, param->name().c_str()) != 1) {
      send_i2c_numeric_error(request, "request", NUMERIC_PARSE_INVALID_ARGUMENT);
      return;
    }
  }

  const uint8_t stopCount = request_param_count(request, "stop");
  const uint8_t speedCount = request_param_count(request, "speed");
  const uint8_t volumeCount = request_param_count(request, "volume");
  if (stopCount == 1) {
    if (speedCount != 0 || volumeCount != 0 || request->params() != 1) {
      send_i2c_numeric_error(request, "stop", NUMERIC_PARSE_INVALID_ARGUMENT);
      return;
    }
    if (!i2cStepperPump.present) {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope("unavailable", nullptr, "I2C pump not available"));
      return;
    }
    PendingI2CPumpCmd command = {};
    command.is_stop = true;
    OperationId operationId = 0;
    const OperationError queueError = queue_pending_i2cpump(
        command, operationId);
    if (queueError != OPERATION_ERROR_NONE) {
      const char *code = queueError == OPERATION_ERROR_LOCK_BUSY
          ? "BUSY"
          : operation_error_code(queueError);
      send_no_store_response(
          request, 503, "application/json", build_error_envelope(code, nullptr, code));
      return;
    }
    send_no_store_response(request, 200, "text/plain", "OK");
    return;
  }
  if (stopCount != 0 || speedCount != 1 || volumeCount != 1 || request->params() != 2) {
    send_i2c_numeric_error(request, "request", NUMERIC_PARSE_INVALID_ARGUMENT);
    return;
  }

  const AsyncWebParameter *speedParam = get_request_param(request, "speed");
  const AsyncWebParameter *volumeParam = get_request_param(request, "volume");
  ControlI2CPumpInput parsed = {};
  const char *errorField = "request";
  NumericParseResult result = parse_control_i2c_pump(
      speedParam ? speedParam->value().c_str() : nullptr,
      volumeParam ? volumeParam->value().c_str() : nullptr,
      i2c_stepper_steps_per_ml(),
      parsed,
      errorField);
  if (!result.ok()) {
    send_i2c_numeric_error(request, errorField, result.error);
    return;
  }
  if (!i2cStepperPump.present ||
      (i2cStepperPump.caps & I2CSTEPPER_CAP_FILLING) == 0) {
    send_no_store_response(
        request, 400, "application/json",
        build_error_envelope("unavailable", nullptr, "I2C filling mode not available"));
    return;
  }

  PendingI2CPumpCmd command = {};
  command.speedSteps = parsed.speedSteps;
  command.targetSteps = parsed.targetSteps;
  command.targetMl = parsed.targetMl;
  command.fillingMl = parsed.fillingMl;
  command.fillingMlHour = parsed.fillingMlHour;
  command.stepsPerMl = parsed.stepsPerMl;
  OperationId operationId = 0;
  const OperationError queueError = queue_pending_i2cpump(
      command, operationId);
  if (queueError != OPERATION_ERROR_NONE) {
    const char *code = queueError == OPERATION_ERROR_LOCK_BUSY
        ? "BUSY"
        : operation_error_code(queueError);
    send_no_store_response(
        request, 503, "application/json", build_error_envelope(code, nullptr, code));
    return;
  }
  send_no_store_response(request, 200, "text/plain", "OK");
}

static void handle_column_params_request(AsyncWebServerRequest *request) {
  uint8_t material = 2;
  const uint8_t count = request_param_count(request, "mat");
  const AsyncWebParameter *input = count == 1 ? get_request_param(request, "mat") : nullptr;
  if (count > 1 || request->params() != count ||
      (input && (input->isFile() || input->isPost()))) {
    send_no_store_response(
        request, 400, "application/json",
        build_error_envelope("argument", "mat", "Invalid mat"));
    return;
  }
  if (count == 1) {
    const int32_t allowed[] = {0, 1, 2};
    int32_t parsed = 0;
    NumericParseResult result = input
        ? parse_exact_enum(input->value().c_str(), allowed, 3, parsed)
        : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    if (!result.ok()) {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope(numeric_parse_error_code(result.error), "mat", "Invalid mat"));
      return;
    }
    material = uint8_t(parsed);
  }

  ColumnResults res = calculate_column_etalon(material);
  String json = "{";
  json += "\"floodPowerW\":" + String(res.floodPowerW, 0) + ",";
  json += "\"workingPowerW\":" + String(res.workingPowerW, 0) + ",";
  json += "\"maxFlowMlH\":" + String(res.maxFlowMlH, 0) + ",";
  json += "\"theoreticalPlates\":" + String(res.theoreticalPlates, 1) + ",";
  json += "\"headsFlowMlH\":" + String(res.headsFlowMlH, 0) + ",";
  json += "\"bodyFlowMinMlH\":" + String(res.bodyFlowMinMlH, 0) + ",";
  json += "\"bodyFlowMaxMlH\":" + String(res.bodyFlowMaxMlH, 0) + ",";
  json += "\"bodyEndFlowMlH\":" + String(res.bodyEndFlowMlH, 0) + ",";
  json += "\"tailsFlowMlH\":" + String(res.tailsFlowMlH, 0) + ",";
  json += "\"headsPowerW\":" + String(res.headsPowerW, 0) + ",";
  json += "\"bodyEndPowerW\":" + String(res.bodyEndPowerW, 0) + ",";
  json += "\"tailsPowerW\":" + String(res.tailsPowerW, 0);
  json += "}";
  send_no_store_response(request, 200, "application/json", json);
}

// filter out specific headers from the incoming request
AsyncHeaderFilterMiddleware headerFilter;

void change_samovar_mode() {
  if (!is_valid_samovar_mode(Samovar_Mode)) {
    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  }
  Samovar_CR_Mode = Samovar_Mode;
}

const char* get_index_page_path() {
  return mode_page_path(Samovar_Mode);
}

void send_index_template_response(AsyncWebServerRequest *request, const char *spiffsPath, const char *cacheControl) {
  String description;
  if (!copy_session_description(description)) {
    request->send(503, "text/plain", "Runtime state busy");
    return;
  }
  String luaButtonList;
  if (!copy_lua_button_list_cache(luaButtonList)) {
    request->send(503, "text/plain", "Runtime state busy");
    return;
  }
  AsyncWebServerResponse *response = request->beginResponse(SPIFFS, spiffsPath, "text/html", false, [description, luaButtonList](const String &var) -> String {
    return indexKeyProcessorWithSnapshots(var, description, luaButtonList);
  });
  response->addHeader("Cache-Control", cacheControl);
  request->send(response);
}

void send_index_page(AsyncWebServerRequest *request) {
  // Главная страница должна соответствовать сохранённому режиму (SamSetup.Mode).
  // Samovar_Mode может временно расходиться (например, после web_command без обновления SamSetup).
  {
    uint16_t cfgMode = SamSetup.Mode;
    if (cfgMode > (uint16_t)SAMOVAR_LUA_MODE) {
      cfgMode = (uint16_t)SAMOVAR_RECTIFICATION_MODE;
    }
    Samovar_Mode = (SAMOVAR_MODE)cfgMode;
  }
  change_samovar_mode();
  send_index_template_response(request, get_index_page_path(), "no-cache, no-store, must-revalidate");
}

// Прямой GET /distiller.htm|beer.htm|… иначе отдаётся через serveStatic без шаблонизатора — %WProgram% не подставляется, в UI «тип программы» пустой.
void send_mode_specific_htm(AsyncWebServerRequest *request, const char *spiffsPath, SAMOVAR_MODE requiredMode) {
  uint16_t m = SamSetup.Mode;
  if (m > (uint16_t)SAMOVAR_LUA_MODE) {
    m = (uint16_t)SAMOVAR_RECTIFICATION_MODE;
  }
  if (m != (uint16_t)requiredMode) {
    request->redirect("/index.htm");
    return;
  }
  Samovar_Mode = (SAMOVAR_MODE)m;
  change_samovar_mode();
  send_index_template_response(request, spiffsPath, "no-cache, no-store, must-revalidate");
}

void WebServerInit(void) {
  FS_register_web_handlers();

//  HeaderFreeMiddleware spiffsHeaderFree;
//  spiffsHeaderFree.keep("If-Modified-Since");
//  spiffsHeaderFree.keep("Host");
//  // Add any other headers you need to keep
//
//  // Then either add it globally
//  server.addMiddleware(&spiffsHeaderFree);


  server.on("/", HTTP_GET | HTTP_POST, [](AsyncWebServerRequest* request) {
    request->redirect("/index.htm");
  });
  
  // style.css уезжает только сжатым: serveStatic сам найдёт .gz и проставит Content-Encoding.
  server.serveStatic("/style.css", SPIFFS, "/style.css").setCacheControl("max-age=5000");
  server.on("/minus.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/minus.png")) { request->send(404, "text/plain", "Missing /minus.png"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/minus.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=604800");
    request->send(response);
  });
  server.on("/plus.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/plus.png")) { request->send(404, "text/plain", "Missing /plus.png"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/plus.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=614800");
    request->send(response);
  });
  server.on("/favicon.ico", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/favicon.ico")) { request->send(404, "text/plain", "Missing /favicon.ico"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/favicon.ico", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=624800");
    request->send(response);
  });

  server.on("/Red_light.gif", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/Red_light.gif")) { request->send(404, "text/plain", "Missing /Red_light.gif"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/Red_light.gif", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=634800");
    request->send(response);
  });
  server.on("/Green.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/Green.png")) { request->send(404, "text/plain", "Missing /Green.png"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/Green.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=644800");
    request->send(response);
  });

  //  server.serveStatic("/style.css", SPIFFS, "/style.css");
  //  server.serveStatic("/Red_light.gif", SPIFFS, "/Red_light.gif");
  //  server.serveStatic("/Green.png", SPIFFS, "/Green.png");
  //  server.serveStatic("/minus.png", SPIFFS, "/minus.png");
  //  server.serveStatic("/plus.png", SPIFFS, "/plus.png");
  //  server.serveStatic("/favicon.ico", SPIFFS, "/favicon.ico");

  server.serveStatic("/alarm.mp3", SPIFFS, "/alarm.mp3");
  server.serveStatic("/resetreason.css", SPIFFS, "/resetreason.css").setCacheControl("max-age=1");
  server.serveStatic("/data_old.csv", SPIFFS, "/data_old.csv").setCacheControl("max-age=1");
  server.serveStatic("/prg.csv", SPIFFS, "/prg.csv").setCacheControl("max-age=1");
  server.serveStatic("/state.csv", SPIFFS, "/state.csv").setCacheControl("max-age=1");
  server.serveStatic("/program.htm", SPIFFS, "/program.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.on("/chart.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_index_template_response(request, "/chart.htm", "max-age=1");
  });
  server.serveStatic("/calibrate.htm", SPIFFS, "/calibrate.htm").setTemplateProcessor(calibrateKeyProcessor).setCacheControl("no-store");
  server.serveStatic("/i2cstepper.htm", SPIFFS, "/i2cstepper.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.serveStatic("/manual.htm", SPIFFS, "/manual.htm").setCacheControl("max-age=800");
  server.on("/pong.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "text/html; charset=utf-8",
      F("<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        "<title>Samovar alarm</title><link rel=\"stylesheet\" href=\"style.css\">"
        "</head><body><main><h1>Samovar alarm</h1>"
        "<audio controls autoplay src=\"/alarm.mp3\"></audio>"
        "</main></body></html>"));
  });
  server.serveStatic("/program_fruit.txt", SPIFFS, "/program_fruit.txt").setCacheControl("max-age=1");
  server.serveStatic("/program_grain.txt", SPIFFS, "/program_grain.txt").setCacheControl("max-age=1");
  server.serveStatic("/program_shugar.txt", SPIFFS, "/program_shugar.txt").setCacheControl("max-age=1");
  server.serveStatic("/brewxml.htm", SPIFFS, "/brewxml.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.serveStatic("/test.txt", SPIFFS, "/test.txt").setTemplateProcessor(indexKeyProcessor);
  server.serveStatic("/setup.htm", SPIFFS, "/setup.htm").setTemplateProcessor(setupKeyProcessor).setCacheControl("max-age=1");
  //server.serveStatic("/edit", SPIFFS, "/edit.htm");
  // SPIFFSEditor уже обрабатывает /edit с поддержкой gzip в FS.ino

  //#ifdef USE_LUA
  //  server.serveStatic("/btn_button1.lua", SPIFFS, "/btn_button1.lua");
  //  server.serveStatic("/btn_button2.lua", SPIFFS, "/btn_button2.lua");
  //  server.serveStatic("/btn_button3.lua", SPIFFS, "/btn_button3.lua");
  //  server.serveStatic("/btn_button4.lua", SPIFFS, "/btn_button4.lua");
  //  server.serveStatic("/btn_button5.lua", SPIFFS, "/btn_button5.lua");
  //#endif

  server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_index_page(request);
  });

  server.on("/rrlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(SPIFFS, "/resetreason.css", String());
  });
  // GET|HEAD: chart page и браузеры могут запрашивать HEAD; только GET давал 501 «Handler did not handle».
  // Если лога ещё нет — beginResponse(nullptr) → тот же 501; отдаём пустой CSV с заголовком как в FS.ino.
  server.on("/data.csv", (WebRequestMethodComposite)(HTTP_GET | HTTP_HEAD), [](AsyncWebServerRequest *request) {
    if (schedule_log_flush_if_needed() != LOG_FLUSH_READY) {
      request->send(503, "text/plain", "BUSY");
      return;
    }
    if (!SPIFFS.exists("/data.csv")) {
#ifdef WRITE_PROGNUM_IN_LOG
      request->send(200, "text/csv; charset=utf-8", "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\r\n");
#else
      request->send(200, "text/csv; charset=utf-8", "Date,Steam,Pipe,Water,Tank,Pressure\r\n");
#endif
      return;
    }
    request->send(SPIFFS, "/data.csv", "text/csv; charset=utf-8");
  });
  server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_ajax_json(request);
  });
  server.on("/command", HTTP_POST, [](AsyncWebServerRequest *request) {
    web_command(request);
  });
  server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request) {
    web_program(request);
  });
  server.on("/ajax_col_params", HTTP_GET, [](AsyncWebServerRequest *request) {
    handle_column_params_request(request);
  });
  server.on("/calibrate", HTTP_GET, [](AsyncWebServerRequest *request) {
    calibrate_command(request);
  });
  server.on("/i2cpump", HTTP_GET, [](AsyncWebServerRequest *request) {
    handle_i2c_pump_request(request);
  });
  server.on("/i2cstepper", HTTP_GET, [](AsyncWebServerRequest *request) {
    handle_i2c_stepper_request(request);
  });
  server.on("/getlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    get_data_log(request, "data.csv");
  });
  server.on("/getoldlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    get_data_log(request, "data_old.csv");
  });
#ifdef USE_LUA
  server.on("/lua", HTTP_GET, [](AsyncWebServerRequest *request) {
    const size_t paramCount = request->params();
    if (paramCount == 0) {
      if (!queue_pending_flag(pending_lua_start_flag)) {
        send_no_store_response(
            request, 503, "application/json",
            build_error_envelope("BUSY", nullptr, "BUSY"));
        return;
      }
      send_no_store_response(request, 200, "text/html", "OK");
      return;
    }

    if (paramCount != 1) {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope("BAD_REQUEST", nullptr, "BAD_REQUEST"));
      return;
    }
    const AsyncWebParameter *param = request->getParam(0);
    if (!param || param->name() != "script" || param->isPost() || param->isFile()) {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope("BAD_REQUEST", nullptr, "BAD_REQUEST"));
      return;
    }
    if (!queue_pending_string(pending_lua_file_flag, pending_lua_file, param->value())) {
      send_no_store_response(
          request, 503, "application/json",
          build_error_envelope("BUSY", nullptr, "BUSY"));
      return;
    }
    send_no_store_response(request, 200, "text/html", "OK");
  });
#endif

  server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request) {
    //Serial.println("SAVE");
    handleSave(request);
  });

  headerFilter.filter("If-Modified-Since");
  //  DefaultHeaders::Instance().addHeader("Cache-Control", "no-cache");
  //  DefaultHeaders::Instance().addHeader("Pragma", "no-cache");
  //  DefaultHeaders::Instance().addHeader("Expires", "Thu, 01 Jan 1970 00:00:00 UTC");
  //  DefaultHeaders::Instance().addHeader("Last-Modified", "Mon, 03 Jan 2050 00:00:00 UTC");
  
  server.on("/distiller.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/distiller.htm", SAMOVAR_DISTILLATION_MODE);
  });
  server.on("/beer.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/beer.htm", SAMOVAR_BEER_MODE);
  });
  server.on("/bk.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/bk.htm", SAMOVAR_BK_MODE);
  });
  server.on("/nbk.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/nbk.htm", SAMOVAR_NBK_MODE);
  });

  // Автоматическая раздача всех файлов из SPIFFS
  server.serveStatic("/", SPIFFS, "/");
  
  server.begin();
#ifdef __SAMOVAR_DEBUG
  Serial.println("HTTP server started");
#endif

#ifndef NOT_USE_INTERFACE_UPDATE
  get_web_interface();
#endif
}

String indexKeyProcessor(const String &var) {
  if (var == "SteamColor") return (String)SamSetup.SteamColor;
  else if (var == "v")
    return SAMOVAR_VERSION;
  else if (var == "PipeColor")
    return (String)SamSetup.PipeColor;
  else if (var == "WaterColor")
    return (String)SamSetup.WaterColor;
  else if (var == "TankColor")
    return (String)SamSetup.TankColor;
  else if (var == "ACPColor")
    return (String)SamSetup.ACPColor;
  else if (var == "SteamHide") {
    if (SteamSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "PipeHide") {
    if (PipeSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "WaterHide") {
    if (WaterSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "TankHide") {
    if (TankSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "PressureHide") {
    if (bme_pressure > 0) return "false";
    else return "true";
  } else if (var == "ProgNumHide") {
    if (ProgramNum > 0) return "false";
    else return "true";
  } else if (var == "WProgram") {
    return serialize_program_for_mode(Samovar_Mode);
  } else if (var == "Descr") {
    String description;
    if (!copy_session_description(description)) return F("Runtime state busy");
    return description;
  } else if (var == "videourl")
    return (String)SamSetup.videourl;
  else if (var == "PWM_LV")
    return (String)(PWM_LOW_VALUE * 10);
  else if (var == "PWM_V")
    return (String)bk_pwm;
  else if (var == "pwr_unit")
    return PWR_TYPE;
  else if (var == "HeaterMaxPower") {
    float maxValue = 0.0f;
    NumericParseResult result = control_power_input_max(
#ifdef SAMOVAR_USE_SEM_AVR
        true,
#else
        false,
#endif
        SamSetup.HeaterResistant,
        maxValue);
    return result.ok() ? String(maxValue, 9) : String();
  }
  else if (var == "pwr_unit_v_only")
    return (String(PWR_TYPE) == "V") ? "block" : "none";
  else if (var == "btn_list") {
#ifdef USE_LUA
    String cachedList;
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      cachedList = lua_script_list_cache;
      runtime_state_unlock(true);
    }
    return toJsonString(cachedList);
#else
    return toJsonString(String());
#endif
  } else if (var == "showvideo") {
    if (strlen(SamSetup.videourl) > 0) return "inline";
    else
      return "none";
  } else if (var == "ColDiam")
    return String(SamSetup.ColDiam, 1);
  else if (var == "ColHeight")
    return String(SamSetup.ColHeight, 2);
  else if (var == "PackDens")
    return String(SamSetup.PackDens);
  else if (var == "HeaterR")
    return String(SamSetup.HeaterResistant, 9);
  else if (var == "I2CStepperTab")
    // [W-3] Читаем из кэша (обновляется в SysTicker), без I2C в async.
    return (i2c_stepper_cache.mixer_present || i2c_stepper_cache.pump_present) ? "inline-block" : "none";
  else if (var == "I2CPumpTab")
    return i2c_stepper_cache.pump_present ? "inline-block" : "none";
  return "";
}

bool copy_lua_button_list_cache(String &buttonList) {
#ifdef USE_LUA
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  buttonList = lua_script_list_cache;
  runtime_state_unlock(true);
#else
  buttonList = String();
#endif
  return true;
}

String indexKeyProcessorWithSnapshots(const String &var, const String &description, const String &luaButtonList) {
  if (var == "Descr") return description;
  if (var == "btn_list") return toJsonString(luaButtonList);
  return indexKeyProcessor(var);
}

String setupKeyProcessor(const String &var) {
  static String s;
  s = "";
  if (var == "DeltaSteamTemp") {
    s = format_float(SamSetup.DeltaSteamTemp, 2);
    return s;
  } else if (var == "DeltaPipeTemp") {
    s = format_float(SamSetup.DeltaPipeTemp, 2);
    return s;
  } else if (var == "DeltaWaterTemp") {
    s = format_float(SamSetup.DeltaWaterTemp, 2);
    return s;
  } else if (var == "DeltaTankTemp") {
    s = format_float(SamSetup.DeltaTankTemp, 2);
    return s;
  } else if (var == "DeltaACPTemp") {
    s = format_float(SamSetup.DeltaACPTemp, 2);
    return s;
  } else if (var == "SetSteamTemp") {
    s = format_float(SamSetup.SetSteamTemp, 2);
    return s;
  } else if (var == "SetPipeTemp") {
    float setPipeTemp = isnan(SamSetup.SetPipeTemp) ? 0 : SamSetup.SetPipeTemp;
    s = format_float(setPipeTemp, 2);
    return s;
  } else if (var == "SetWaterTemp") {
    float setWaterTemp = isnan(SamSetup.SetWaterTemp) ? 0 : SamSetup.SetWaterTemp;
    s = format_float(setWaterTemp, 2);
    return s;
  } else if (var == "SetTankTemp") {
    float setTankTemp = isnan(SamSetup.SetTankTemp) ? 0 : SamSetup.SetTankTemp;
    s = format_float(setTankTemp, 2);
    return s;
  } else if (var == "SetACPTemp") {
    float setACPTemp = isnan(SamSetup.SetACPTemp) ? 0 : SamSetup.SetACPTemp;
    s = format_float(setACPTemp, 2);
    return s;
  } else if (var == "StepperStepMl") {
    s = SamSetup.StepperStepMl;
    return s;
  } else if (var == "StepperStepMlI2C") {
    s = SamSetup.StepperStepMlI2C;
    return s;
  } else if (var == "WProgram") {
    return serialize_program_for_mode(Samovar_Mode);
  } else if (var == "Kp") {
    s = format_float(SamSetup.Kp, 3);
    return s;
  } else if (var == "Ki") {
    s = format_float(SamSetup.Ki, 3);
    return s;
  } else if (var == "Kd") {
    s = format_float(SamSetup.Kd, 3);
    return s;
  } else if (var == "StbVoltage") {
    s = SamSetup.StbVoltage;
    return s;
  } else if (var == "SteamDelay") {
    s = SamSetup.SteamDelay;
    return s;
  } else if (var == "PipeDelay") {
    s = SamSetup.PipeDelay;
    return s;
  } else if (var == "WaterDelay") {
    s = SamSetup.WaterDelay;
    return s;
  } else if (var == "TankDelay") {
    s = SamSetup.TankDelay;
    return s;
  } else if (var == "ACPDelay") {
    s = SamSetup.ACPDelay;
    return s;
  } else if (var == "TimeZone") {
    s = SamSetup.TimeZone;
    return s;
  } else if (var == "LogPeriod") {
    s = SamSetup.LogPeriod;
    return s;
  } else if (var == "HeaterR") {
    s = format_float(SamSetup.HeaterResistant, 3);
    return s;
  } else if (var == "videourl") {
    s = SamSetup.videourl;
    return s;
  } else if (var == "blynkauth") {
    s = SamSetup.blynkauth;
    return s;
  } else if (var == "tgtoken") {
    s = SamSetup.tg_token;
    return s;
  } else if (var == "tgchatid") {
    s = SamSetup.tg_chat_id;
    return s;
  } else if (var == "BVolt") {
    s = SamSetup.BVolt;
    return s;
  } else if (var == "DistTimeF") {
    s = SamSetup.DistTimeF;
    return s;
  } else if (var == "MaxPressureValue") {
    s = SamSetup.MaxPressureValue;
    return s;
  } else if (var == "NbkIn") {
    s = SamSetup.NbkIn;
    return s;
  } else if (var == "NbkDelta") {
    s = SamSetup.NbkDelta;
    return s;
  } else if (var == "NbkDM") {
    s = SamSetup.NbkDM;
    return s;
  } else if (var == "NbkDP") {
    s = SamSetup.NbkDP;
    return s;
  } else if (var == "NbkSteamT") {
    s = SamSetup.NbkSteamT;
    return s;
  } else if (var == "NbkOwPress") {
    s = SamSetup.NbkOwPress;
    return s;
  } else if (var == "Checked") {
    if (SamSetup.UsePreccureCorrect) return "checked='true'";
    else
      return "";
  } else if (var == "FLChecked") {
    if (SamSetup.UseHLS) return "checked='true'";
    else
      return "";
#ifdef IGNORE_HEAD_LEVEL_SENSOR_SETTING
  } else if (var == "IgnFL") {
    return F("style="
             "display: none"
             "");
#endif
  } else if (var == "UASChecked") {
    if (SamSetup.useautospeed) return "checked='true'";
    else
      return "";
  } else if (var == "UASHeadsChecked") {
    if (SamSetup.useDetectorOnHeads) return "checked='true'";
    else
      return "";
  } else if (var == "CPBuzz") {
    if (SamSetup.ChangeProgramBuzzer) return "checked='true'";
    else
      return "";
  } else if (var == "CUBuzz") {
    if (SamSetup.UseBuzzer) return "checked='true'";
    else
      return "";
  } else if (var == "CUBBuzz") {
    if (SamSetup.UseBBuzzer) return "checked='true'";
    else
      return "";
  } else if (var == "UseWS") {
    if (SamSetup.UseWS) return "checked='true'";
    else
      return "";
  } else if (var == "UseST") {
    if (SamSetup.UseST) return "checked='true'";
    else
      return "";
  } else if (var == "ChckPwr") {
    if (SamSetup.CheckPower) return "checked='true'";
    else
      return "";
  } else if (var == "autospeed") {
    s = SamSetup.autospeed;
    return s;
  } else if (var == "DistTemp") {
    s = format_float(SamSetup.DistTemp, 2);
    return s;
  } else if (var == "SteamColor") {
    s = SamSetup.SteamColor;
    return s;
  } else if (var == "PipeColor") {
    s = SamSetup.PipeColor;
    return s;
  } else if (var == "WaterColor") {
    s = SamSetup.WaterColor;
    return s;
  } else if (var == "TankColor") {
    s = SamSetup.TankColor;
    return s;
  } else if (var == "ACPColor") {
    s = SamSetup.ACPColor;
    return s;
  } else if (var == "RECT" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_RECTIFICATION_MODE)
    return "selected";
  else if (var == "DIST" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_DISTILLATION_MODE)
    return "selected";
  else if (var == "BEER" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_BEER_MODE)
    return "selected";
  else if (var == "BK" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_BK_MODE)
    return "selected";
  else if (var == "NBK" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_NBK_MODE)
    return "selected";
  else if (var == "SUVID" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_SUVID_MODE)
    return "selected";
  else if (var == "LUA_MODE" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_LUA_MODE)
    return "selected";
  else if (var == "RAL" && !SamSetup.rele1)
    return "selected";
  else if (var == "RAH" && SamSetup.rele1)
    return "selected";
  else if (var == "RBL" && !SamSetup.rele2)
    return "selected";
  else if (var == "RBH" && SamSetup.rele2)
    return "selected";
  else if (var == "RCL" && !SamSetup.rele3)
    return "selected";
  else if (var == "RCH" && SamSetup.rele3)
    return "selected";
  else if (var == "RDL" && !SamSetup.rele4)
    return "selected";
  else if (var == "RDH" && SamSetup.rele4)
    return "selected";
  else if (var == "SteamAddr")
    return get_DSAddressList(getDSAddress(SamSetup.SteamAdress));
  else if (var == "PipeAddr")
    return get_DSAddressList(getDSAddress(SamSetup.PipeAdress));
  else if (var == "WaterAddr")
    return get_DSAddressList(getDSAddress(SamSetup.WaterAdress));
  else if (var == "TankAddr")
    return get_DSAddressList(getDSAddress(SamSetup.TankAdress));
  else if (var == "ACPAddr")
    return get_DSAddressList(getDSAddress(SamSetup.ACPAdress));
  else if (var == "ColDiam")
    return String(SamSetup.ColDiam, 1);
  else if (var == "ColDiam_1.5") {
    if (abs(SamSetup.ColDiam - 1.5f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColDiam_2.0") {
    if (abs(SamSetup.ColDiam - 2.0f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColDiam_3.0") {
    if (abs(SamSetup.ColDiam - 3.0f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight")
    return String(SamSetup.ColHeight, 2);
  else if (var == "ColHeight_0.50") {
    if (abs(SamSetup.ColHeight - 0.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_0.75") {
    if (abs(SamSetup.ColHeight - 0.75f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.00") {
    if (abs(SamSetup.ColHeight - 1.00f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.25") {
    if (abs(SamSetup.ColHeight - 1.25f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.50") {
    if (abs(SamSetup.ColHeight - 1.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.75") {
    if (abs(SamSetup.ColHeight - 1.75f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.00") {
    if (abs(SamSetup.ColHeight - 2.00f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.25") {
    if (abs(SamSetup.ColHeight - 2.25f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.50") {
    if (abs(SamSetup.ColHeight - 2.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "PackDens")
    return String(SamSetup.PackDens);
  else if (var == "I2CStepperTab")
    // [W-3] Читаем из кэша (обновляется в SysTicker), без I2C в async.
    return (i2c_stepper_cache.mixer_present || i2c_stepper_cache.pump_present) ? "inline-block" : "none";
  else if (var == "I2CPumpTab")
    return i2c_stepper_cache.pump_present ? "inline-block" : "none";
  return "";
}

const AsyncWebParameter* get_request_param(AsyncWebServerRequest *request, const char *name) {
  if (!request || !name) return nullptr;
  const AsyncWebParameter *param = request->getParam(name, true);
  if (param) return param;
  return request->getParam(name, false);
}

static uint8_t request_param_count(AsyncWebServerRequest *request, const char *name) {
  if (!request || !name) return 0;
  uint8_t count = 0;
  for (size_t i = 0; i < request->params(); i++) {
    const AsyncWebParameter *param = request->getParam(i);
    if (param && param->name() == name && count < UINT8_MAX) count++;
  }
  return count;
}

String calibrateKeyProcessor(const String &var) {
  if (var == "StepperStep") return (String)STEPPER_MAX_SPEED;
  else if (var == "StepperStepMl")
    return (String)(SamSetup.StepperStepMl * 100);
  else if (var == "StepperStepMlI2C")
    return (String)(SamSetup.StepperStepMlI2C * 100);
  else if (var == "I2CPumpTab")
    // [W-3] Читаем из кэша (обновляется в SysTicker), без I2C в async.
    return i2c_stepper_cache.pump_present ? "inline-block" : "none";
  else if (var == "CalibrationRunning")
    return startval == 100 || I2CPumpCalibrating ? "1" : "0";
  else if (var == "CalibrationPump")
    return I2CPumpCalibrating ? "i2c" : "local";

  return String();
}

bool is_valid_samovar_mode(long mode) {
  return mode >= SAMOVAR_RECTIFICATION_MODE && mode <= SAMOVAR_LUA_MODE;
}

static SafetyModeSwitchState modeSwitchState = {SAFETY_MODE_SWITCH_IDLE, 0, false};

struct ModeActuatorCleanupState {
  bool initialized;
  bool mixerStopped;
  bool pumpStopped;
  uint32_t deadline;
};

static ModeActuatorCleanupState modeActuatorCleanup = {};

bool mode_switch_in_progress() {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool active = mode_switch_barrier_active;
  portEXIT_CRITICAL(&emergencyStopMux);
  return active;
}

static bool pending_mode_control_commands_locked() {
  bool pending = pending_rescan_ds_flag || pending_stop_self_test_flag ||
                 pending_mixer_flag || pending_water_temp_flag ||
                 pending_pump_speed_flag || pending_nbkopt_flag ||
                 pending_i2cstepper_flag || pending_i2cpump_flag ||
                 pending_i2ccal_flag || pending_local_cal_flag || pending_pnbk_flag;
#ifdef SAMOVAR_USE_POWER
  pending = pending || pending_voltage_flag;
#endif
#ifdef USE_LUA
  pending = pending || pending_lua_start_flag || pending_lua_file_flag ||
            pending_lua_flag || pending_lua_reload_flag;
#endif
  return pending;
}

static bool discard_pending_mode_control_commands(bool& cancelled) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  cancelled = pending_mode_control_commands_locked();
  pending_rescan_ds_flag = false;
  pending_stop_self_test_flag = false;
  pending_mixer_flag = false;
  pending_water_temp_flag = false;
  pending_pump_speed_flag = false;
  pending_nbkopt_flag = false;
  if (!cancel_queued_i2c_operations_locked(cancelled)) {
    pending_command_unlock(true);
    return false;
  }
  pending_pnbk_flag = false;
#ifdef SAMOVAR_USE_POWER
  pending_voltage_flag = false;
#endif
#ifdef USE_LUA
  pending_lua_start_flag = false;
  pending_lua_file_flag = false;
  pending_lua_flag = false;
  pending_lua_reload_flag = false;
  pending_lua_file = "";
  pending_lua_str = "";
#endif
  pending_command_unlock(true);
  return true;
}

static bool mode_control_queues_idle() {
  if (!samovar_command_queue_idle(pdMS_TO_TICKS(50))) return false;
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  const bool idle = !pending_mode_control_commands_locked();
  pending_command_unlock(true);
  return idle;
}

static void stop_local_mode_actuators() {
  digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  mixer_status = false;
  valve_status = false;
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
#endif
  stopService();
  stepper_safe_stop_reset();
  StepperMoving = false;
  CurrrentStepperSpeed = 0;
  TargetStepps = 0;
  I2CStepperSpeed = 0;
  I2CPumpCmdSpeed = 0;
  I2CPumpTargetSteps = 0;
  I2CPumpTargetMl = 0;
  heater_state = false;
}

static bool stop_i2c_mode_actuator(I2CStepperDevice& dev, bool finishCalibration) {
  if (!i2c_stepper_config_begin(dev)) return false;
  if (!i2c_stepper_refresh(dev, true)) {
    i2c_stepper_config_end(dev);
    return false;
  }
  bool stopped = true;
  if (finishCalibration || (dev.status & I2CSTEPPER_STATUS_CALIBRATION)) {
    stopped = i2c_stepper_send_command(dev, I2CSTEP_CMD_CALIBRATE_FINISH);
  }
  if (stopped) stopped = i2c_stepper_stop(dev);
  if (stopped && (dev.caps & I2CSTEPPER_CAP_RELAY) && dev.relayMask != 0) {
    dev.relayMask = 0;
    stopped = i2c_stepper_write_config(dev) &&
              i2c_stepper_send_command(dev, I2CSTEP_CMD_RELAY);
  }
  if (stopped) {
    stopped = i2c_stepper_refresh(dev, true) &&
              (dev.status & (I2CSTEPPER_STATUS_RUNNING | I2CSTEPPER_STATUS_CALIBRATION)) == 0 &&
              dev.currentSpeed == 0 &&
              (!(dev.caps & I2CSTEPPER_CAP_RELAY) || dev.relayMask == 0);
  }
  i2c_stepper_config_end(dev);
  return stopped;
}

static bool mode_actuators_idle() {
  bool idle = !valve_status && !mixer_status && !heater_state &&
              !stepper_safe_get_state() && stepper_safe_get_target() == 0 &&
              CurrrentStepperSpeed == 0 && I2CStepperSpeed == 0 &&
              I2CPumpCmdSpeed == 0 && I2CPumpTargetSteps == 0 &&
              I2CPumpTargetMl == 0 && !I2CPumpCalibrating;
#ifdef USE_WATER_PUMP
  idle = idle && !pump_started && water_pump_speed == 0;
#endif
  return idle && modeActuatorCleanup.mixerStopped &&
         modeActuatorCleanup.pumpStopped;
}

static bool tick_mode_actuator_cleanup(bool luaIdle) {
  stop_local_mode_actuators();
  if (!modeActuatorCleanup.initialized) {
    modeActuatorCleanup.initialized = true;
    modeActuatorCleanup.mixerStopped = !(i2cStepperMixer.present || i2c_stepper_cache.mixer_present);
    modeActuatorCleanup.pumpStopped = !(i2cStepperPump.present || i2c_stepper_cache.pump_present);
    modeActuatorCleanup.deadline = safety_deadline_after(millis(), 30000);
    set_capacity(0);
  }
  if (!modeActuatorCleanup.mixerStopped) {
    const bool stopped = stop_i2c_mode_actuator(i2cStepperMixer, false);
    modeActuatorCleanup.mixerStopped = luaIdle && stopped;
  }
  if (!modeActuatorCleanup.pumpStopped) {
    const bool stopped = stop_i2c_mode_actuator(
      i2cStepperPump,
      I2CPumpCalibrating
    );
    modeActuatorCleanup.pumpStopped = luaIdle && stopped;
    if (stopped) I2CPumpCalibrating = false;
  }
  if (!luaIdle) return false;
  return mode_actuators_idle();
}

void stop_active_process_for_mode() {
  if (self_test_active()) stop_self_test();
  const bool ownerActive = heater_power_on() || SamovarStatusInt != 0 ||
                           startval != 0 || ProgramNum != 0;
  if (!ownerActive) {
    SamovarStatusInt = 0;
    startval = 0;
    ProgramNum = 0;
    return;
  }

  switch (Samovar_Mode) {
    case SAMOVAR_RECTIFICATION_MODE:
      run_program(PROGRAM_END);
      break;
    case SAMOVAR_DISTILLATION_MODE:
      distiller_finish();
      break;
    case SAMOVAR_BEER_MODE:
      beer_finish();
      break;
    case SAMOVAR_BK_MODE:
      bk_finish();
      break;
    case SAMOVAR_NBK_MODE:
      nbk_finish();
      break;
    case SAMOVAR_SUVID_MODE:
    case SAMOVAR_LUA_MODE:
    default:
      SamovarStatusInt = 0;
      startval = 0;
      ProgramNum = 0;
      set_power(false);
      break;
  }
}

// Провал смены режима больше не запирает автомат в терминальной фазе: нагрев
// принудительно снимается, SafetyModeSwitchState возвращается в IDLE, а барьер
// mode_switch_barrier_active снимается ровно как на успехе. Строка предупреждения
// передаётся вызывающей стороной литералом — без промежуточного буфера, чтобы
// длинное сообщение в UTF-8 не обрезалось молча (см. snprintf-ловушку).
static ModeSwitchResult force_complete_mode_switch_failed(const char* warning) {
  portENTER_CRITICAL(&emergencyStopMux);
  force_heater_output_off_locked(true);
  safety_mode_switch_complete(modeSwitchState);
  mode_switch_barrier_active = false;
  portEXIT_CRITICAL(&emergencyStopMux);
  notify_power_worker();
  modeActuatorCleanup = {};
  SendMsg(warning, WARNING_MSG);
  return MODE_SWITCH_FAILED;
}

// switch_samovar_mode вызывается только из process_profile_operation().
ModeSwitchResult switch_samovar_mode(SAMOVAR_MODE requestedMode) {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool accepted = safety_mode_switch_begin(modeSwitchState, (uint8_t)requestedMode);
  if (accepted) mode_switch_barrier_active = true;
  portEXIT_CRITICAL(&emergencyStopMux);
  if (!accepted) return MODE_SWITCH_PENDING;
  tick_mode_actuator_cleanup(false);

  if (modeSwitchState.phase == SAFETY_MODE_SWITCH_STOP_REQUESTED) {
    stop_active_process_for_mode();

    bool stopRequested = true;
#ifdef USE_LUA
    stopRequested = request_lua_mode_stop();
#endif
    const bool queueWasIdle = samovar_command_queue_idle(pdMS_TO_TICKS(50));
    const bool queueDiscarded = discard_samovar_commands(pdMS_TO_TICKS(50));
    bool pendingCancelled = false;
    const bool pendingDiscarded = discard_pending_mode_control_commands(pendingCancelled);
    if (!stopRequested || !queueDiscarded || !pendingDiscarded) {
      if (safety_deadline_expired(millis(), modeActuatorCleanup.deadline)) {
        return force_complete_mode_switch_failed(
            !stopRequested
                ? "Смена режима завершена принудительно: не подтвердился Lua"
                : "Смена режима завершена принудительно: не подтвердился очередь");
      }
      return MODE_SWITCH_PENDING;
    }
    if (!queueWasIdle || pendingCancelled) {
      SendMsg("Отложенные управляющие команды отменены сменой режима", WARNING_MSG);
    }
    safety_mode_switch_wait_cleanup(modeSwitchState);
    return MODE_SWITCH_PENDING;
  }

  bool luaIdle = true;
#ifdef USE_LUA
  luaIdle = lua_mode_owner_idle();
#endif
  const bool actuatorsIdle = tick_mode_actuator_cleanup(luaIdle);
  const bool queuesIdle = mode_control_queues_idle();
  const bool logClosePending = data_log_close_pending();

  const bool heaterPowerOn = heater_power_on();
  const bool powerTransitionActive = power_transition_active();
  const bool nbkTransitionActive = nbk_transition_active();
  const bool modeHeatingActive = mode_heating_start_active();
  const bool selfTestActive = self_test_active();
  const bool ownerIdle = mode_runtime_owner_idle();

  const bool cleanupReady = safety_mode_switch_cleanup_ready(
        modeSwitchState,
        heaterPowerOn,
        powerTransitionActive,
        nbkTransitionActive,
        modeHeatingActive,
        selfTestActive,
        logClosePending,
        ownerIdle,
        actuatorsIdle,
        luaIdle,
        queuesIdle
      );

  if (safety_deadline_expired(millis(), modeActuatorCleanup.deadline) && !cleanupReady) {
    const char* warning = "Смена режима завершена принудительно: не подтвердилась готовность";
    if (!modeSwitchState.logCloseRequested || logClosePending) {
      warning = "Смена режима завершена принудительно: не подтвердился лог";
    } else if (!luaIdle) {
      warning = "Смена режима завершена принудительно: не подтвердился Lua";
    } else if (!queuesIdle) {
      warning = "Смена режима завершена принудительно: не подтвердился очередь";
    } else if (!actuatorsIdle) {
      warning = "Смена режима завершена принудительно: не подтвердился привод";
    } else if (heaterPowerOn) {
      warning = "Смена режима завершена принудительно: не подтвердился нагрев";
    } else if (powerTransitionActive) {
      warning = "Смена режима завершена принудительно: не подтвердился переход мощности";
    } else if (nbkTransitionActive) {
      warning = "Смена режима завершена принудительно: не подтвердился переход НБК";
    } else if (modeHeatingActive) {
      warning = "Смена режима завершена принудительно: не подтвердился старт нагрева";
    } else if (selfTestActive) {
      warning = "Смена режима завершена принудительно: не подтвердился самотест";
    } else if (!ownerIdle) {
      warning = "Смена режима завершена принудительно: не подтвердился владелец режима";
    }
    return force_complete_mode_switch_failed(warning);
  }

  if (!modeSwitchState.logCloseRequested) {
    if (request_data_log_close()) {
      safety_mode_switch_mark_log_close_requested(modeSwitchState);
    }
    return MODE_SWITCH_PENDING;
  }

  if (!cleanupReady) return MODE_SWITCH_PENDING;

  const OperationError commitError = commit_profile_operation();
  if (commitError != OPERATION_ERROR_NONE) {
    active_profile_operation.terminalError = commitError;
    return force_complete_mode_switch_failed(
        "Смена режима завершена принудительно: профиль не сохранён");
  }
  portENTER_CRITICAL(&emergencyStopMux);
  safety_mode_switch_complete(modeSwitchState);
  mode_switch_barrier_active = false;
  portEXIT_CRITICAL(&emergencyStopMux);
  modeActuatorCleanup = {};
  return MODE_SWITCH_SUCCEEDED;
}

void update_checkbox_arg(AsyncWebServerRequest *request, const char* name, bool& value, bool fullSetupForm) {
  if (fullSetupForm || request->hasArg(name)) value = request->hasArg(name);
}

static void send_save_parse_error(
    AsyncWebServerRequest *request,
    const char *name,
    NumericParseError error) {
  String message = "Invalid ";
  message += name;
  send_no_store_response(
      request, 400, "application/json",
      build_error_envelope(numeric_parse_error_code(error), name, message));
}

static bool parse_save_long_arg(AsyncWebServerRequest *request, const char *name, long minValue, long maxValue, long& value) {
  if (request_param_count(request, name) != 1) {
    send_save_parse_error(request, name, NUMERIC_PARSE_INVALID_ARGUMENT);
    return false;
  }
  const AsyncWebParameter *param = get_request_param(request, name);
  NumericParseResult result = param && !param->isFile()
      ? parse_bounded_long(param->value().c_str(), minValue, maxValue, value)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) {
    send_save_parse_error(request, name, result.error);
    return false;
  }
  return true;
}

static bool parse_save_float_arg(AsyncWebServerRequest *request, const char *name, float minValue, float maxValue, float& value) {
  if (request_param_count(request, name) != 1) {
    send_save_parse_error(request, name, NUMERIC_PARSE_INVALID_ARGUMENT);
    return false;
  }
  const AsyncWebParameter *param = get_request_param(request, name);
  NumericParseResult result = param && !param->isFile()
      ? parse_bounded_float(param->value().c_str(), minValue, maxValue, value)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) {
    send_save_parse_error(request, name, result.error);
    return false;
  }
  return true;
}

static bool apply_save_u8_arg(AsyncWebServerRequest *request, const char *name, uint8_t& target, long minValue, long maxValue) {
  if (!request->hasArg(name)) return true;
  long value = 0;
  if (!parse_save_long_arg(request, name, minValue, maxValue, value)) return false;
  target = (uint8_t)value;
  return true;
}

static bool apply_save_u16_arg(AsyncWebServerRequest *request, const char *name, uint16_t& target, long minValue, long maxValue) {
  if (!request->hasArg(name)) return true;
  long value = 0;
  if (!parse_save_long_arg(request, name, minValue, maxValue, value)) return false;
  target = (uint16_t)value;
  return true;
}

static bool apply_save_bool01_arg(AsyncWebServerRequest *request, const char *name, bool& target) {
  if (!request->hasArg(name)) return true;
  if (request_param_count(request, name) != 1) {
    send_save_parse_error(request, name, NUMERIC_PARSE_INVALID_ARGUMENT);
    return false;
  }
  const AsyncWebParameter *param = get_request_param(request, name);
  bool value = false;
  NumericParseResult result = param && !param->isFile()
      ? parse_exact_bool(param->value().c_str(), value)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) {
    send_save_parse_error(request, name, result.error);
    return false;
  }
  target = value;
  return true;
}

static bool apply_save_float_arg(AsyncWebServerRequest *request, const char *name, float& target, float minValue, float maxValue) {
  if (!request->hasArg(name)) return true;
  float value = 0;
  if (!parse_save_float_arg(request, name, minValue, maxValue, value)) return false;
  target = value;
  return true;
}

template <size_t N>
static void apply_save_string_arg(AsyncWebServerRequest *request, const char *name, char (&target)[N]) {
  if (request->hasArg(name)) copyStringSafe(target, request->arg(name));
}

static bool apply_save_ds_addr_arg(
    AsyncWebServerRequest *request,
    const char *name,
    const DSAddressSnapshot& snapshot,
    uint8_t (&target)[8],
    uint8_t resetBit,
    uint8_t& resetMask) {
  if (!request->hasArg(name)) return true;
  long idx = 0;
  if (!parse_save_long_arg(request, name, -1, SAMOVAR_DS_ADDRESS_MAX - 1, idx)) return false;
  DeviceAddress selectedAddress;
  if (idx == -1) {
    set_invalid_ds_address(selectedAddress);
  } else if (idx >= snapshot.count) {
    send_save_parse_error(request, name, NUMERIC_PARSE_OUT_OF_RANGE);
    return false;
  } else {
    CopyDSAddress(snapshot.addr[idx], selectedAddress);
  }
  if (!ds_address_equal(target, selectedAddress)) {
    CopyDSAddress(selectedAddress, target);
    resetMask |= resetBit;
  }
  return true;
}

static bool save_param_name_allowed(const String& name) {
  return name == "fullsetup" || name == "save" || name == "clear" || name == "mode" ||
      name == "WProgram" || name == "SteamDelay" || name == "PipeDelay" ||
      name == "WaterDelay" || name == "TankDelay" || name == "ACPDelay" ||
      name == "DeltaSteamTemp" || name == "DeltaPipeTemp" ||
      name == "DeltaWaterTemp" || name == "DeltaTankTemp" ||
      name == "DeltaACPTemp" || name == "SetSteamTemp" ||
      name == "SetPipeTemp" || name == "SetWaterTemp" ||
      name == "SetTankTemp" || name == "SetACPTemp" || name == "Kp" ||
      name == "Ki" || name == "Kd" || name == "StbVoltage" ||
      name == "BVolt" || name == "DistTimeF" ||
      name == "MaxPressureValue" || name == "StepperStepMl" ||
      name == "StepperStepMlI2C" || name == "stepperstepml" ||
      name == "useflevel" || name == "usepressure" ||
      name == "useautospeed" || name == "useDetectorOnHeads" ||
      name == "ChangeProgramBuzzer" || name == "UseBuzzer" ||
      name == "UseBBuzzer" || name == "UseWS" || name == "UseST" ||
      name == "CheckPower" || name == "autospeed" || name == "DistTemp" ||
      name == "TimeZone" || name == "LogPeriod" || name == "HeaterR" ||
      name == "NbkIn" || name == "NbkDelta" || name == "NbkDM" ||
      name == "NbkDP" || name == "NbkSteamT" || name == "NbkOwPress" ||
      name == "videourl" || name == "blynkauth" || name == "tgtoken" ||
      name == "tgchatid" || name == "SteamColor" || name == "PipeColor" ||
      name == "WaterColor" || name == "TankColor" || name == "ACPColor" ||
      name == "rele1" || name == "rele2" || name == "rele3" ||
      name == "rele4" || name == "SteamAddr" || name == "PipeAddr" ||
      name == "WaterAddr" || name == "TankAddr" || name == "ACPAddr" ||
      name == "ColDiam" || name == "ColHeight" || name == "PackDens";
}

void handleSave(AsyncWebServerRequest *request) {
  if (!request) {
    return;
  }
  for (size_t index = 0; index < request->params(); index++) {
    const AsyncWebParameter *param = request->getParam(index);
    if (!param || !save_param_name_allowed(param->name())) {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope(
              "not_allowed", param ? param->name().c_str() : nullptr,
              "Invalid request field"));
      return;
    }
    if (!param->isPost() || param->isFile() ||
        request_param_count(request, param->name().c_str()) != 1) {
      send_save_parse_error(
          request, param->name().c_str(), NUMERIC_PARSE_INVALID_ARGUMENT);
      return;
    }
  }
  if (request_param_count(request, "clear") != 0) {
    send_no_store_response(
        request, 400, "application/json",
        build_error_envelope(
            "not_allowed", "WProgram",
            "Program clear is supported only by /program clear=1"));
    return;
  }
  const uint8_t wProgramCount = request_param_count(request, "WProgram");
  if (wProgramCount > 1) {
    send_no_store_response(
        request, 400, "application/json",
        build_error_envelope("argument", "WProgram", "Duplicate WProgram"));
    return;
  }
  const AsyncWebParameter *wProgramParam =
      wProgramCount == 1 ? get_request_param(request, "WProgram") : nullptr;
  if (wProgramCount == 1 && (!wProgramParam || wProgramParam->isFile())) {
    send_no_store_response(
        request, 400, "application/json",
        build_error_envelope("argument", "WProgram", "WProgram must be a text parameter"));
    return;
  }
  /*
       int params = request->params();
        for(int i=0;i<params;i++){
          AsyncWebParameter* p = request->getParam(i);
          Serial.print(p->name().c_str());
          Serial.print("=");
          Serial.println(p->value().c_str());
        }
        //return;
  */

  const SAMOVAR_MODE sourceMode = Samovar_Mode;
  const int sourceProfileMode = SamSetup.Mode;
  bool fullSetupForm = request->hasArg("fullsetup");
  bool modeRequested = false;
  SAMOVAR_MODE requestedMode = sourceMode;
  {
    const uint8_t modeCount = request_param_count(request, "mode");
    if (modeCount > 1) {
      send_save_parse_error(request, "mode", NUMERIC_PARSE_INVALID_ARGUMENT);
      return;
    }
    const AsyncWebParameter *modeParam = get_request_param(request, "mode");
    if (modeParam) {
      if (modeParam->isFile()) {
        send_save_parse_error(request, "mode", NUMERIC_PARSE_INVALID_ARGUMENT);
        return;
      }
      const int32_t allowedModes[] = {0, 1, 2, 3, 4, 5, 6};
      int32_t requestedModeValue = 0;
      NumericParseResult result = parse_exact_enum(
          modeParam->value().c_str(), allowedModes, 7, requestedModeValue);
      if (!result.ok()) {
        send_save_parse_error(request, "mode", result.error);
        return;
      }
      modeRequested = true;
      requestedMode = (SAMOVAR_MODE)requestedModeValue;
    }
  }

  SetupEEPROM staged = SamSetup;
  uint8_t sensorResetMask = 0;
  DSAddressSnapshot dsSnapshot;
  copy_ds_address_snapshot(dsSnapshot);
  if (modeRequested) {
    staged.Mode = (int)requestedMode;
  }

  if (!apply_save_u16_arg(request, "SteamDelay", staged.SteamDelay, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "PipeDelay", staged.PipeDelay, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "WaterDelay", staged.WaterDelay, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "TankDelay", staged.TankDelay, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "ACPDelay", staged.ACPDelay, 0, 65535)) return;

  if (!apply_save_float_arg(request, "DeltaSteamTemp", staged.DeltaSteamTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "DeltaPipeTemp", staged.DeltaPipeTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "DeltaWaterTemp", staged.DeltaWaterTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "DeltaTankTemp", staged.DeltaTankTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "DeltaACPTemp", staged.DeltaACPTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "SetSteamTemp", staged.SetSteamTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "SetPipeTemp", staged.SetPipeTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "SetWaterTemp", staged.SetWaterTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "SetTankTemp", staged.SetTankTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "SetACPTemp", staged.SetACPTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "Kp", staged.Kp, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "Ki", staged.Ki, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "Kd", staged.Kd, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "StbVoltage", staged.StbVoltage, 0.0f, 10000.0f)) return;
  if (!apply_save_float_arg(request, "BVolt", staged.BVolt, 0.0f, 10000.0f)) return;
  if (!apply_save_u8_arg(request, "DistTimeF", staged.DistTimeF, 0, 255)) return;
  if (!apply_save_float_arg(request, "MaxPressureValue", staged.MaxPressureValue, 0.0f, 10000.0f)) return;
  if (!apply_save_u16_arg(request, "StepperStepMl", staged.StepperStepMl, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "StepperStepMlI2C", staged.StepperStepMlI2C, 0, 65535)) return;
  if (request->hasArg("stepperstepml")) {
    if (request->hasArg("StepperStepMl")) {
      send_save_parse_error(request, "stepperstepml", NUMERIC_PARSE_INVALID_ARGUMENT);
      return;
    }
    long stepsPer100Ml = 0;
    if (!parse_save_long_arg(request, "stepperstepml", 0, 6553500, stepsPer100Ml)) return;
    if ((stepsPer100Ml % 100) != 0) {
      send_save_parse_error(request, "stepperstepml", NUMERIC_PARSE_NOT_ALLOWED);
      return;
    }
    staged.StepperStepMl = (uint16_t)(stepsPer100Ml / 100);
  }

  update_checkbox_arg(request, "useflevel", staged.UseHLS, fullSetupForm);
  update_checkbox_arg(request, "usepressure", staged.UsePreccureCorrect, fullSetupForm);
  update_checkbox_arg(request, "useautospeed", staged.useautospeed, fullSetupForm);
  update_checkbox_arg(request, "useDetectorOnHeads", staged.useDetectorOnHeads, fullSetupForm);
  update_checkbox_arg(request, "ChangeProgramBuzzer", staged.ChangeProgramBuzzer, fullSetupForm);
  update_checkbox_arg(request, "UseBuzzer", staged.UseBuzzer, fullSetupForm);
  update_checkbox_arg(request, "UseBBuzzer", staged.UseBBuzzer, fullSetupForm);
  update_checkbox_arg(request, "UseWS", staged.UseWS, fullSetupForm);
  update_checkbox_arg(request, "UseST", staged.UseST, fullSetupForm);
  update_checkbox_arg(request, "CheckPower", staged.CheckPower, fullSetupForm);

  if (!apply_save_u8_arg(request, "autospeed", staged.autospeed, 0, 99)) return;
  if (!apply_save_float_arg(request, "DistTemp", staged.DistTemp, 0.0f, 150.0f)) return;
  if (!apply_save_u8_arg(request, "TimeZone", staged.TimeZone, 0, 23)) return;
  if (!apply_save_u8_arg(request, "LogPeriod", staged.LogPeriod, 1, 255)) return;
  if (!apply_save_float_arg(request, "HeaterR", staged.HeaterResistant, CONTROL_HEATER_R_MIN, CONTROL_HEATER_R_MAX)) return;
  if (!apply_save_float_arg(request, "NbkIn", staged.NbkIn, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "NbkDelta", staged.NbkDelta, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "NbkDM", staged.NbkDM, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "NbkDP", staged.NbkDP, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "NbkSteamT", staged.NbkSteamT, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "NbkOwPress", staged.NbkOwPress, 0.0f, 100000.0f)) return;

  apply_save_string_arg(request, "videourl", staged.videourl);
  apply_save_string_arg(request, "blynkauth", staged.blynkauth);
  apply_save_string_arg(request, "tgtoken", staged.tg_token);
  apply_save_string_arg(request, "tgchatid", staged.tg_chat_id);
  apply_save_string_arg(request, "SteamColor", staged.SteamColor);
  apply_save_string_arg(request, "PipeColor", staged.PipeColor);
  apply_save_string_arg(request, "WaterColor", staged.WaterColor);
  apply_save_string_arg(request, "TankColor", staged.TankColor);
  apply_save_string_arg(request, "ACPColor", staged.ACPColor);

  if (!apply_save_bool01_arg(request, "rele1", staged.rele1)) return;
  if (!apply_save_bool01_arg(request, "rele2", staged.rele2)) return;
  if (!apply_save_bool01_arg(request, "rele3", staged.rele3)) return;
  if (!apply_save_bool01_arg(request, "rele4", staged.rele4)) return;

  if (!apply_save_ds_addr_arg(request, "SteamAddr", dsSnapshot, staged.SteamAdress, PROFILE_SENSOR_RESET_STEAM, sensorResetMask)) return;
  if (!apply_save_ds_addr_arg(request, "PipeAddr", dsSnapshot, staged.PipeAdress, PROFILE_SENSOR_RESET_PIPE, sensorResetMask)) return;
  if (!apply_save_ds_addr_arg(request, "WaterAddr", dsSnapshot, staged.WaterAdress, PROFILE_SENSOR_RESET_WATER, sensorResetMask)) return;
  if (!apply_save_ds_addr_arg(request, "TankAddr", dsSnapshot, staged.TankAdress, PROFILE_SENSOR_RESET_TANK, sensorResetMask)) return;
  if (!apply_save_ds_addr_arg(request, "ACPAddr", dsSnapshot, staged.ACPAdress, PROFILE_SENSOR_RESET_ACP, sensorResetMask)) return;

  if (!apply_save_float_arg(request, "ColDiam", staged.ColDiam, 0.1f, 10.0f)) return;
  if (!apply_save_float_arg(request, "ColHeight", staged.ColHeight, 0.01f, 10.0f)) return;
  if (!apply_save_u8_arg(request, "PackDens", staged.PackDens, 0, 100)) return;

  const bool hasSwitchMode = modeRequested &&
      (sourceProfileMode != static_cast<int>(requestedMode) ||
       sourceMode != requestedMode);
  ProgramDraft programDraft{};
  const ProgramDraft* programDraftPtr = nullptr;
  if (wProgramParam) {
    ProgramParseResult result = prepare_program_for_mode(
        requestedMode,
        wProgramParam->value(),
        programDraft);
    if (!result.ok()) {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope("program", "WProgram", format_program_parse_error(result)));
      return;
    }
    programDraftPtr = &programDraft;
  } else if (hasSwitchMode) {
    ProgramParseResult result = prepare_default_program_for_mode(
        requestedMode, programDraft);
    if (!result.ok()) {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope("program", "WProgram", format_program_parse_error(result)));
      return;
    }
    programDraftPtr = &programDraft;
  }

  OperationId operationId = 0;
  const OperationError queueError = queue_profile_operation(
      OPERATION_KIND_SAVE,
      &staged,
      sensorResetMask,
      programDraftPtr,
      programDraftPtr ? PROGRAM_UPDATE_REPLACE : PROGRAM_UPDATE_NONE,
      0,
      0.0f,
      nullptr,
      wProgramCount == 1,
      hasSwitchMode,
      sourceMode,
      requestedMode,
      operationId);
  if (queueError != OPERATION_ERROR_NONE) {
    const uint16_t statusCode = queueError == OPERATION_ERROR_CANCELLED ? 409 : 503;
    send_no_store_response(
        request, statusCode, "text/plain", operation_error_code(queueError));
    return;
  }

  get_task_stack_usage();
  send_save_operation_accepted(request, operationId);
  // is_reboot обрабатывается в loop() — рестарт выполнится после отправки ответа.
}

static bool web_command_name_allowed(const String& name) {
  if (name == "start" || name == "power" || name == "setbodytemp" ||
      name == "reset" || name == "reboot" || name == "resetwifi" ||
      name == "startst" || name == "rescands" || name == "stopst" ||
      name == "mixer" || name == "pnbk" || name == "nbkopt" ||
      name == "distiller" || name == "startbk" || name == "startnbk" ||
      name == "watert" || name == "pumpspeed" || name == "pause") return true;
#ifdef SAMOVAR_USE_POWER
  if (name == "voltage") return true;
#endif
#ifdef USE_LUA
  if (name == "lua" || name == "luastr") return true;
#endif
  return false;
}

static bool get_web_command_action(
    AsyncWebServerRequest *request,
    String& name,
    const AsyncWebParameter*& param) {
  if (!request || request->params() != 1) return false;
  param = request->getParam(0);
  if (!param || !param->isPost() || param->isFile()) return false;
  // /command регистронезависима (Mixer/STATUS ≡ mixer/status): нормализуем имя команды
  // к нижнему регистру ДО allowlist и последующих сравнений. Значение параметра
  // (actionParam->value()) не трогаем — регистр значений может быть значим (Lua-скрипты и т.п.).
  name = param->name();
  name.toLowerCase();
  if (!web_command_name_allowed(name)) return false;
  return true;
}

// /command - токенный протокол: сервер отдаёт машинный токен (BUSY/IGNORED/POWER_OFF/...),
// а человеческий текст и уровень подбирает клиент по COMMAND_TOKENS. Успех - не ошибка,
// поэтому 2xx уходит текстом как раньше; отказ уходит конвертом, где тот же токен лежит
// в error, и клиент выбирает по нему ровно как выбирал по телу ответа.
static void send_web_command_response(AsyncWebServerRequest *request, int status, const char *text) {
  if (status >= 200 && status < 300) {
    send_no_store_response(request, status, "text/plain", text);
    return;
  }
  send_no_store_response(
      request, status, "application/json", build_error_envelope(text, nullptr, text));
}

void web_command(AsyncWebServerRequest *request) {
  static uint32_t last_command_time = 0;
  static String last_command_key;
  String action;
  const AsyncWebParameter *actionParam = nullptr;
  if (!get_web_command_action(request, action, actionParam)) {
    send_web_command_response(request, 400, "BAD_REQUEST");
    return;
  }

  bool boolValue = false;
  uint16_t waterPwm = 0;
  uint16_t pumpSpeedSteps = 0;
  ControlNbkCommand nbkCommand = {};
#ifdef SAMOVAR_USE_POWER
  float voltage = 0.0f;
#endif
  NumericParseResult parseResult = numeric_parse_result(NUMERIC_PARSE_OK);
  if (action == "mixer" || action == "distiller" ||
      action == "startbk" || action == "startnbk") {
    parseResult = parse_exact_bool(actionParam->value().c_str(), boolValue);
  } else if (action == "watert") {
    parseResult = parse_control_water_pwm(actionParam->value().c_str(), waterPwm);
  } else if (action == "pumpspeed") {
    parseResult = parse_control_rate_steps(
        actionParam->value().c_str(), SamSetup.StepperStepMl, pumpSpeedSteps);
  } else if (action == "pnbk") {
    parseResult = parse_control_nbk(
        actionParam->value().c_str(), SamSetup.StepperStepMlI2C, nbkCommand);
    if (parseResult.ok() && nbkCommand.kind != CONTROL_NBK_STOP &&
        SamSetup.StepperStepMlI2C == 0) {
      parseResult = numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    }
  }
#ifdef SAMOVAR_USE_POWER
  else if (action == "voltage") {
    float maxValue = 0.0f;
    parseResult = control_power_input_max(
#ifdef SAMOVAR_USE_SEM_AVR
        true,
#else
        false,
#endif
        SamSetup.HeaterResistant,
        maxValue);
    if (parseResult.ok()) {
      parseResult = parse_control_power(actionParam->value().c_str(), maxValue, voltage);
    }
  }
#endif
  if (!parseResult.ok()) {
    send_web_command_response(request, 400, "BAD_REQUEST");
    return;
  }

  String commandKey = action;
  if (action == "mixer" || action == "distiller" ||
      action == "startbk" || action == "startnbk") {
    commandKey += boolValue ? "=1" : "=0";
  } else if (action == "watert") {
    commandKey += "=" + String(waterPwm);
  } else if (action == "pumpspeed") {
    commandKey += "=" + String(pumpSpeedSteps);
  } else if (action == "pnbk") {
    commandKey += "=" + String(uint8_t(nbkCommand.kind));
    commandKey += ":" + String(nbkCommand.stepSpeed);
  }
#ifdef SAMOVAR_USE_POWER
  else if (action == "voltage") {
    commandKey += "=" + String(voltage, 6);
  }
#endif
#ifdef USE_LUA
  else if (action == "lua" || action == "luastr") {
    commandKey += "=" + actionParam->value();
  }
#endif

  bool bypassThrottle = action == "reset" || action == "reboot" || action == "resetwifi";
  if (!bypassThrottle && commandKey.length() > 0 && commandKey == last_command_key && millis() - last_command_time < 1500) {
    send_web_command_response(request, 429, "IGNORED");
    return;
  }
  auto markAccepted = [&]() {
    if (!bypassThrottle && commandKey.length() > 0) {
      last_command_key = commandKey;
      last_command_time = millis();
    }
  };

  if (action == "start") {
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    SamovarCommands command = mode_start_command(Samovar_Mode);
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "power") {
    SamovarCommands command = SAMOVAR_POWER;
    if (!PowerOn) command = mode_power_on_command(Samovar_Mode);
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "setbodytemp") {
    if (!queue_samovar_command(SAMOVAR_SETBODYTEMP)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "reset") {
    if (!queue_samovar_reset_command()) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "reboot") {
    if (!queue_pending_flag(is_reboot, /*bypassBarrier=*/true)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
    markAccepted();
    send_web_command_response(request, 200, "OK");
    return;
  } else if (action == "resetwifi") {
    if (!queue_pending_flag(pending_reset_wifi_flag, /*bypassBarrier=*/true)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
    markAccepted();
    send_web_command_response(request, 200, "OK");
    return;
  } else if (action == "startst") {
    if (!queue_samovar_command(SAMOVAR_SELF_TEST)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "rescands") {
    if (samovar_process_active()) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
    if (!queue_pending_flag(pending_rescan_ds_flag)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "stopst") {
    if (!queue_pending_flag(pending_stop_self_test_flag)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "mixer") {
    if (!queue_pending_value(pending_mixer_flag, pending_mixer_on, boolValue)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "pnbk") {
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    if (!queue_pending_nbk(nbkCommand)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "nbkopt") {
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    if (!queue_pending_flag(pending_nbkopt_flag)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "distiller") {
    SamovarCommands command = boolValue ? SAMOVAR_DISTILLATION : SAMOVAR_POWER;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "startbk") {
    SamovarCommands command = boolValue ? SAMOVAR_BK : SAMOVAR_POWER;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "startnbk") {
    SamovarCommands command = boolValue ? SAMOVAR_NBK : SAMOVAR_POWER;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "watert") {
    if (!queue_pending_value(pending_water_temp_flag, pending_water_temp_value, waterPwm)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "pumpspeed") {
    if (!queue_pending_value(pending_pump_speed_flag, pending_pump_speed_steps, pumpSpeedSteps)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "pause") {
    SamovarCommands command = PauseOn ? SAMOVAR_CONTINUE : SAMOVAR_PAUSE;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  }
#ifdef SAMOVAR_USE_POWER
  else if (action == "voltage") {
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    if (!queue_pending_value(pending_voltage_flag, pending_voltage_value, voltage)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  }
#endif
#ifdef USE_LUA
  else if (action == "lua") {
    if (!queue_pending_string(pending_lua_file_flag, pending_lua_file, actionParam->value())) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "luastr") {
    String lstr = expandLuaCaretEscapes(actionParam->value());
    if (!queue_pending_string(pending_lua_flag, pending_lua_str, lstr)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  }
#endif
  else {
    send_web_command_response(request, 400, "BAD_REQUEST");
    return;
  }
  markAccepted();
  send_web_command_response(request, 200, "OK");
}
void web_program(AsyncWebServerRequest *request) {
  if (!request) return;
  const SAMOVAR_MODE sourceMode = Samovar_Mode;

  for (size_t index = 0; index < request->params(); index++) {
    const AsyncWebParameter *param = request->getParam(index);
    const bool known = param && (param->name() == "clear" ||
        param->name() == "WProgram" || param->name() == "vless" ||
        param->name() == "Descr");
    if (!known || !param->isPost() || param->isFile() ||
        request_param_count(request, param->name().c_str()) != 1) {
      send_program_json_response(
          request, 400, false, F("Invalid request parameter"), String());
      return;
    }
  }

  const uint8_t clearCount = request_param_count(request, "clear");
  const uint8_t wProgramCount = request_param_count(request, "WProgram");
  const uint8_t vlessCount = request_param_count(request, "vless");
  const uint8_t descriptionCount = request_param_count(request, "Descr");
  if (wProgramCount > 1 || vlessCount > 1 || descriptionCount > 1) {
    send_program_json_response(
        request,
        400,
        false,
        F("Числовые и текстовые параметры должны быть единственными"),
        String());
    return;
  }
  const AsyncWebParameter *wProgramParam =
      wProgramCount == 1 ? get_request_param(request, "WProgram") : nullptr;
  if (wProgramCount == 1 && (!wProgramParam || wProgramParam->isFile())) {
    send_program_json_response(
        request,
        400,
        false,
        F("WProgram должен быть текстовым параметром"),
        String());
    return;
  }
  if (clearCount > 0) {
    const AsyncWebParameter *clearParam = get_request_param(request, "clear");
    if (clearCount != 1 || !clearParam || clearParam->value() != "1") {
      send_program_json_response(
          request,
          400,
          false,
          F("Очистка программы требует ровно clear=1"),
          String());
      return;
    }
    if (wProgramCount != 0 || request->params() != 1) {
      send_program_json_response(
          request,
          400,
          false,
          F("Очистка программы должна быть отдельным действием"),
          String());
      return;
    }
  }

  ProgramDraft programDraft{};
  const ProgramDraft* programDraftPtr = nullptr;
  ProgramUpdateAction programAction = PROGRAM_UPDATE_NONE;
  const bool hasProgramAction = clearCount == 1 || wProgramCount == 1;
  if (clearCount == 1) {
    programAction = PROGRAM_UPDATE_CLEAR;
  } else if (wProgramCount == 1) {
    ProgramParseResult result = prepare_program_for_mode(
        sourceMode,
        wProgramParam->value(),
        programDraft);
    if (!result.ok()) {
      send_program_json_response(
          request,
          400,
          false,
          format_program_parse_error(result),
          String());
      return;
    }
    programDraftPtr = &programDraft;
    programAction = PROGRAM_UPDATE_REPLACE;
  }

  uint8_t metadataFlags = 0;
  float boilerVolume = 0.0f;
  char descriptionValue[251] = "";
  const AsyncWebParameter *vlessParam = vlessCount == 1
      ? get_request_param(request, "vless")
      : nullptr;
  if (vlessParam) {
    NumericParseResult result = vlessParam->isFile()
        ? numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT)
        : parse_control_vless(vlessParam->value().c_str(), boilerVolume);
    if (!result.ok()) {
      String error = "Invalid vless: ";
      error += numeric_parse_error_code(result.error);
      send_program_json_response(request, 400, false, error, String());
      return;
    }
    metadataFlags |= PROFILE_OPERATION_METADATA_VOLUME;
  }

  const AsyncWebParameter *descriptionParam = descriptionCount == 1
      ? get_request_param(request, "Descr")
      : nullptr;
  if (descriptionParam) {
    if (descriptionParam->isFile()) {
      send_program_json_response(
          request, 400, false, F("Invalid Descr: argument"), String());
      return;
    }
    const String& description = descriptionParam->value();
    if (description.length() > 250) {
      send_program_json_response(
          request, 400, false, F("Invalid Descr: range"), String());
      return;
    }
    memcpy(descriptionValue, description.c_str(), description.length());
    descriptionValue[description.length()] = '\0';
    metadataFlags |= PROFILE_OPERATION_METADATA_DESCRIPTION;
  }

  const bool hasMetadata = metadataFlags != 0;
  String responseProgram = serialize_program_for_mode(sourceMode);
  if (!hasProgramAction && !hasMetadata) {
    send_program_json_response(
        request, 200, true, String(), responseProgram);
    return;
  }

  OperationId operationId = 0;
  const OperationError queueError = queue_profile_operation(
      OPERATION_KIND_PROGRAM,
      nullptr,
      0,
      programDraftPtr,
      programAction,
      metadataFlags,
      boilerVolume,
      (metadataFlags & PROFILE_OPERATION_METADATA_DESCRIPTION) != 0
          ? descriptionValue
          : nullptr,
      true,
      false,
      sourceMode,
      sourceMode,
      operationId);
  if (queueError != OPERATION_ERROR_NONE) {
    send_program_json_response(
        request,
        queueError == OPERATION_ERROR_CANCELLED ? 409 : 503,
        false,
        operation_error_code(queueError),
        String());
    return;
  }
  send_program_operation_accepted(request, responseProgram, operationId);
}

void calibrate_command(AsyncWebServerRequest *request) {
  auto sendBadRequest = [&](const char *field, NumericParseError error) {
    String message = "BAD_REQUEST: ";
    message += field;
    send_no_store_response(
        request, 400, "application/json",
        build_error_envelope(numeric_parse_error_code(error), field, message));
  };
  for (size_t index = 0; index < request->params(); index++) {
    const AsyncWebParameter *param = request->getParam(index);
    const bool known = param && (param->name() == "pump" || param->name() == "start" ||
        param->name() == "finish" || param->name() == "stpstep");
    if (!known || param->isFile() || param->isPost() ||
        request_param_count(request, param->name().c_str()) != 1) {
      sendBadRequest(param ? param->name().c_str() : "request", NUMERIC_PARSE_INVALID_ARGUMENT);
      return;
    }
  }

  const uint8_t startCount = request_param_count(request, "start");
  const uint8_t finishCount = request_param_count(request, "finish");
  const uint8_t speedCount = request_param_count(request, "stpstep");
  const uint8_t pumpCount = request_param_count(request, "pump");
  if (startCount + finishCount != 1 || pumpCount > 1 ||
      (startCount == 1 ? speedCount != 1 : speedCount != 0)) {
    sendBadRequest(startCount + finishCount != 1 ? "action" : "stpstep",
                   NUMERIC_PARSE_INVALID_ARGUMENT);
    return;
  }

  const AsyncWebParameter *pumpParam = get_request_param(request, "pump");
  const String pump = pumpParam ? pumpParam->value() : "local";
  if (pump != "local" && pump != "i2c") {
    sendBadRequest("pump", NUMERIC_PARSE_NOT_ALLOWED);
    return;
  }
  const bool isI2C = pump == "i2c";
  uint16_t speed = 0;
  if (startCount == 1) {
    const AsyncWebParameter *speedParam = get_request_param(request, "stpstep");
    NumericParseResult result = speedParam
        ? parse_control_calibration_speed(speedParam->value().c_str(), speed)
        : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    if (!result.ok()) {
      sendBadRequest("stpstep", result.error);
      return;
    }
  }

  const bool isFinish = finishCount == 1;
  const bool localCalibrating = startval == 100;
  const bool i2cCalibrating = I2CPumpCalibrating;
  const bool invalidState = isFinish
      ? (isI2C ? !i2cCalibrating || localCalibrating
               : !localCalibrating || i2cCalibrating)
      : startval != 0 || i2cCalibrating;
  if (invalidState) {
    send_no_store_response(
        request, 503, "application/json", build_error_envelope("BUSY", nullptr, "BUSY"));
    return;
  }
  OperationId operationId = 0;
  OperationError queueError = OPERATION_ERROR_NONE;
  if (!isI2C) {
    PendingLocalCalCmd command = {};
    command.is_finish = isFinish;
    command.speed = speed;
    queueError = queue_pending_local_cal(command, operationId);
  } else {
    if (!i2cStepperPump.present ||
        (i2cStepperPump.caps & I2CSTEPPER_CAP_FILLING) == 0) {
      sendBadRequest("pump", NUMERIC_PARSE_NOT_ALLOWED);
      return;
    }
    PendingI2CCalCmd command = {};
    command.is_finish = isFinish;
    if (!isFinish) {
      command.stepsPerMl = i2c_stepper_steps_per_ml();
      NumericParseResult result = checked_step_speed_to_mlh(
          speed, command.stepsPerMl, command.pumpMlHour);
      if (!result.ok()) {
        sendBadRequest("stpstep", result.error);
        return;
      }
      command.cmdSpeed = speed;
    }
    queueError = queue_pending_i2ccal(command, operationId);
  }
  if (queueError != OPERATION_ERROR_NONE) {
    const char *code = queueError == OPERATION_ERROR_LOCK_BUSY
        ? "BUSY"
        : operation_error_code(queueError);
    send_no_store_response(
        request, 503, "application/json", build_error_envelope(code, nullptr, code));
    return;
  }
  send_i2c_operation_accepted(request, operationId);
}

void get_data_log(AsyncWebServerRequest *request, String fn) {
  if (schedule_log_flush_if_needed() != LOG_FLUSH_READY) {
    request->send(503, "text/plain", "BUSY");
    return;
  }
  AsyncWebServerResponse *response;
  if (SPIFFS.exists("/" + fn)) {
    response = request->beginResponse(SPIFFS, "/" + fn, String(), true);
  } else {
    response = request->beginResponse(400, "text/plain", "");
  }
  response->addHeader(F("Content-Type"), F("application/octet-stream"));
  response->addHeader(F("Content-Description"), F("File Transfer"));
  response->addHeader(F("Content-Disposition"), "attachment; filename=\"" + fn + "\"");
  response->addHeader(F("Pragma"), F("public"));
  response->addHeader(F("Cache-Control"), F("no-cache"));
  request->send(response);
}

static void normalize_web_if_version_string(String& v) {
  v.trim();
  v.replace("\r", "");
}

static bool write_web_file_atomic(const String& path, const String& content) {
  String tmpPath = path + ".tmp";
  String backupPath = path + ".bak";

  SPIFFS.remove(tmpPath);
  SPIFFS.remove(backupPath);

  File wf = SPIFFS.open(tmpPath, FILE_WRITE);
  if (!wf) {
    Serial.println("WEB interface write failed, open tmp: " + tmpPath);
    SPIFFS.remove(tmpPath);
    return false;
  }

  size_t written = wf.write((const uint8_t*)content.c_str(), content.length());
  wf.close();
  if (written != content.length()) {
    Serial.println("WEB interface write failed, partial tmp: " + tmpPath);
    SPIFFS.remove(tmpPath);
    return false;
  }

  File rf = SPIFFS.open(tmpPath, FILE_READ);
  if (!rf) {
    Serial.println("WEB interface write failed, reopen tmp: " + tmpPath);
    SPIFFS.remove(tmpPath);
    return false;
  }
  size_t tmpSize = rf.size();
  rf.close();
  if (tmpSize != content.length()) {
    Serial.println("WEB interface write failed, tmp size: " + tmpPath);
    SPIFFS.remove(tmpPath);
    return false;
  }

  bool hadFinal = SPIFFS.exists(path);
  if (hadFinal && !SPIFFS.rename(path, backupPath)) {
    Serial.println("WEB interface write failed, backup final: " + path);
    SPIFFS.remove(tmpPath);
    return false;
  }

  if (!SPIFFS.rename(tmpPath, path)) {
    Serial.println("WEB interface write failed, install tmp: " + path);
    SPIFFS.remove(tmpPath);
    if (hadFinal && !SPIFFS.rename(backupPath, path)) {
      Serial.println("WEB interface rollback failed: " + path);
    }
    return false;
  }

  if (hadFinal) {
    SPIFFS.remove(backupPath);
  }
  return true;
}

static bool web_file_content_empty_invalid(const String& fn, get_web_type type, const String& content) {
  if (content.length() != 0) {
    return false;
  }
  if (type == GET_CONTENT || type == SAVE_FILE_OVERRIDE || type == SAVE_FILE_IF_NOT_EXIST) {
    Serial.println("WEB interface download failed, empty body: " + fn);
    return true;
  }
  return false;
}

void get_web_interface() {
  String version;
  String local_version;

  version = get_web_file("version.txt", GET_CONTENT);
  if (version == "<ERR>") {
    Serial.println("WEB interface update failed on version.txt");
    return;
  }
  normalize_web_if_version_string(version);

  Serial.print(F("WEB interface version = "));
  Serial.println(version);

  File fn = SPIFFS.open("/version.txt", FILE_READ);
  if (fn) {
    local_version = fn.readString();
    fn.close();
    normalize_web_if_version_string(local_version);
  }
  Serial.print(F("Local interface version = "));
  Serial.println(local_version);
  if (version != local_version) {
    bool updateOk = true;
    auto updateFile = [&](String fn, get_web_type type) {
      if (!updateOk) return;
      String result = get_web_file(fn, type);
      if (result == "<ERR>") {
        Serial.println("WEB interface update failed on " + fn);
        updateOk = false;
      }
    };

    updateFile("index.htm", SAVE_FILE_OVERRIDE);
    updateFile("Green.png", SAVE_FILE_OVERRIDE);
    updateFile("Red_light.gif", SAVE_FILE_OVERRIDE);
    updateFile("alarm.mp3", SAVE_FILE_OVERRIDE);
    updateFile("favicon.ico", SAVE_FILE_OVERRIDE);
    updateFile("minus.png", SAVE_FILE_OVERRIDE);
    updateFile("plus.png", SAVE_FILE_OVERRIDE);

    //s += get_web_file("style.css", SAVE_FILE_OVERRIDE);
    updateFile("style.css.gz", SAVE_FILE_OVERRIDE);

    updateFile("beer.htm", SAVE_FILE_OVERRIDE);
    updateFile("bk.htm", SAVE_FILE_OVERRIDE);
    updateFile("nbk.htm", SAVE_FILE_OVERRIDE);
    updateFile("brewxml.htm", SAVE_FILE_OVERRIDE);
    updateFile("calibrate.htm", SAVE_FILE_OVERRIDE);
    updateFile("chart.htm", SAVE_FILE_OVERRIDE);
    updateFile("distiller.htm", SAVE_FILE_OVERRIDE);
    updateFile("i2cstepper.htm.gz", SAVE_FILE_OVERRIDE);
    //s += get_web_file("edit.htm", SAVE_FILE_OVERRIDE);
    updateFile("edit.htm.gz", SAVE_FILE_OVERRIDE);

    updateFile("program.htm", SAVE_FILE_OVERRIDE);
    updateFile("setup.htm", SAVE_FILE_OVERRIDE);

    updateFile("app.js.gz", SAVE_FILE_OVERRIDE);
    updateFile("chart.js.gz", SAVE_FILE_OVERRIDE);

    updateFile("beer.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("bk.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("nbk.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("dist.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("init.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("rectificat.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("script.lua", SAVE_FILE_IF_NOT_EXIST);

    updateFile("btn_rect_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_rect_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_beer_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_beer_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_dist_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_dist_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_bk_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_bk_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_nbk_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_nbk_button2.lua", SAVE_FILE_IF_NOT_EXIST);



    updateFile("program_fruit.txt", SAVE_FILE_IF_NOT_EXIST);
    updateFile("program_grain.txt", SAVE_FILE_IF_NOT_EXIST);
    updateFile("program_shugar.txt", SAVE_FILE_IF_NOT_EXIST);

    if (updateOk) {
      // Версию уже скачали в начале функции — записываем нормализованную строку, без повторного HTTP.
      String versionMarker = version + "\n";
      if (!write_web_file_atomic("/version.txt", versionMarker)) {
        Serial.println("WEB interface update failed on version marker; local version marker was not changed.");
        updateOk = false;
      }
    }

    if (!updateOk) {
      Serial.println("WEB interface update aborted; local version marker was not changed.");
    }
  }
}

String get_web_file(String fn, get_web_type type) {
  if (type == SAVE_FILE_IF_NOT_EXIST && SPIFFS.exists("/" + fn)) {
    Serial.println("File " + fn + " already exist.");
    return "";
  }

  String url = "http://web.samovar-tool.ru/" + String(SAMOVAR_VERSION) + "/" + fn + "?" + micros();
  Serial.print("url = ");
  Serial.println(url);

  String s = http_sync_request_get(url);

  if (s == "<ERR>") {
    return s;
  } else if (web_file_content_empty_invalid(fn, type, s)) {
    return "<ERR>";
  } else {
    if (type == GET_CONTENT) {
      return s;
    } else {
      if (!write_web_file_atomic("/" + fn, s)) {
        return "<ERR>";
      }
      //Serial.print("responseText = ");
      //Serial.println(s);
    }
    Serial.println("Done (L=" + String(s.length()) + ")");
  }

  return "";
}

static void abort_http_request(void* requestPtr) {
  asyncHTTPrequest* request = static_cast<asyncHTTPrequest*>(requestPtr);
  request->abort();

  uint32_t abortStartTime = millis();
  while (request->readyState() != 4 && millis() - abortStartTime < 1000) {
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
}

String http_sync_request_get(String url) {
  asyncHTTPrequest request;
  request.setDebug(false);
  const uint32_t timeoutMs = 8000;
  request.setTimeout(8); // Таймаут восемь секунд (внутренний по отсутствию активности)
  if (!request.open("GET", url.c_str())) {
    Serial.println("HTTP GET open() failed");
    return "<ERR>";
  }
  
  unsigned long startTime = millis();
  while (request.readyState() < 1) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: readyState never reached 1");
      abort_http_request(&request);
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  if (!request.send()) {
    Serial.println("HTTP GET send() failed");
    abort_http_request(&request);
    return "<ERR>";
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  // Таймаут для ожидания завершения запроса (readyState == 4)
  startTime = millis();
  while (request.readyState() != 4) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: request not completed within 8 seconds");
      abort_http_request(&request);
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  if (request.responseHTTPcode() >= 0) {
    if (request.responseHTTPcode() != 200) {
      Serial.print(F("responseHTTPcode = "));
      Serial.println(request.responseHTTPcode());
      Serial.println("Content " + url + " download error");
      return "<ERR>";
    }
    String response = request.responseText();
    size_t expectedLength = request.responseLength();
    if (expectedLength > 0 && response.length() != expectedLength) {
      Serial.println("Content " + url + " incomplete: " + String(response.length()) + "/" + String(expectedLength));
      return "<ERR>";
    }
    return response;
  } else {
    Serial.print(F("responseHTTPcode = "));
    Serial.println(request.responseHTTPcode());
    Serial.println("Content " + url + " download error (2)");
    return "<ERR>";
  }  
  return "";
}

String http_sync_request_post(String url, String body, String ContentType) {
  asyncHTTPrequest request;
  request.setDebug(false);
  const uint32_t timeoutMs = 8000;
  request.setTimeout(8);  //Таймаут восемь секунд (внутренний по отсутствию активности)

  if (!request.open("POST", url.c_str())) {  //URL
    Serial.println("HTTP POST open() failed");
    return "<ERR>";
  }
  unsigned long startTime = millis();
  while (request.readyState() < 1) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: readyState never reached 1");
      abort_http_request(&request);
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  request.setReqHeader("Content-Type", getValue(ContentType, ':', 1).c_str());
  if (!request.send(body)) {
    Serial.println("HTTP POST send() failed");
    abort_http_request(&request);
    return "<ERR>";
  }

  vTaskDelay(150 / portTICK_PERIOD_MS);
  // Таймаут для ожидания завершения запроса (readyState == 4)
  startTime = millis();
  while (request.readyState() != 4) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: request not completed within 8 seconds");
      abort_http_request(&request);
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  if (request.responseHTTPcode() >= 0) {
    return request.responseText();
  } else {
    return "<ERR>";
  }
}
