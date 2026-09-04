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
  PendingCommandLockGuard guard;
  if (!guard) return false;
  if ((!bypassBarrier && mode_switch_in_progress()) || flag) return false;
  flag = true;
  return true;
}

static const uint8_t LOG_FLUSH_READY = 0;
static const uint8_t LOG_FLUSH_QUEUED = 1;
static const uint8_t LOG_FLUSH_BUSY = 2;

static uint8_t schedule_log_flush_if_needed() {
  if (log_flush_seq >= log_write_seq) return LOG_FLUSH_READY;
  PendingCommandLockGuard guard;
  if (!guard) return LOG_FLUSH_BUSY;
  uint32_t writeSeq = log_write_seq;
  if (log_flush_seq < writeSeq) {
    pending_log_flush_seq = writeSeq;
    pending_log_flush_flag = true;
    return LOG_FLUSH_QUEUED;
  }
  return LOG_FLUSH_READY;
}

static bool queue_pending_nbk(const ControlNbkCommand& value) {
  if (mode_switch_in_progress()) return false;
  PendingCommandLockGuard guard;
  if (!guard) return false;
  if (mode_switch_in_progress() || pending_pnbk_flag) return false;
  pending_pnbk_value = value;
  __sync_synchronize();
  pending_pnbk_flag = true;
  return true;
}

#ifdef USE_LUA
// Не инстанс queue_pending_value<String>: valueSlot там volatile T&, а у класса
// String (WString.h ядра ESP32) нет ни одного volatile-квалифицированного метода,
// в т.ч. operator= — volatile String& не скомпилируется на valueSlot = value.
// Поэтому здесь обычная String& (pending_lua_str/pending_lua_file объявлены не volatile).
bool queue_pending_string(volatile bool& flag, String& valueSlot, const String& value) {
  if (mode_switch_in_progress()) return false;
  PendingCommandLockGuard guard;
  if (!guard) return false;
  if (mode_switch_in_progress() || flag) return false;
  valueSlot = value;
  __sync_synchronize();
  flag = true;
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

  PendingCommandLockGuard guard;
  if (!guard) return OPERATION_ERROR_LOCK_BUSY;
  if (profile_operation_phase_load() != PROFILE_OPERATION_EMPTY) {
    return OPERATION_ERROR_LOCK_BUSY;
  }
  if (mode_switch_in_progress() ||
      (requireProgramIdle && program_update_session_active()) ||
      Samovar_Mode != sourceMode) {
    return OPERATION_ERROR_CANCELLED;
  }

  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, kind, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
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
    mode_switch_begin();
  }
  profile_operation_phase_store(PROFILE_OPERATION_QUEUED);
  operationId = reservedId;
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

static void send_operation_accepted(
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
  PendingCommandLockGuard guard;
  if (!guard) return OPERATION_ERROR_LOCK_BUSY;
  if (mode_switch_in_progress() || pending_i2cpump_flag ||
      i2c_stepper_config_busy(i2cStepperPump)) {
    return OPERATION_ERROR_LOCK_BUSY;
  }
  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, OPERATION_KIND_I2C_PUMP, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    return reserveError;
  }
  command.operationId = reservedId;
  pending_i2cpump_buf = command;
  __sync_synchronize();
  pending_i2cpump_flag = true;
  operationId = reservedId;
  return OPERATION_ERROR_NONE;
}

static OperationError queue_pending_i2cstepper(
    PendingI2CStepperCmd command, OperationId& operationId) {
  PendingCommandLockGuard guard;
  if (!guard) return OPERATION_ERROR_LOCK_BUSY;
  I2CStepperDevice& device = command.device_sel == 0
      ? i2cStepperMixer
      : i2cStepperPump;
  if (mode_switch_in_progress() || pending_i2cstepper_flag ||
      command.device_sel > 1 || i2c_stepper_config_busy(device)) {
    return command.device_sel > 1
        ? OPERATION_ERROR_INTERNAL
        : OPERATION_ERROR_LOCK_BUSY;
  }
  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, OPERATION_KIND_I2C_STEPPER, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    return reserveError;
  }
  command.operationId = reservedId;
  pending_i2cstepper_buf = command;
  __sync_synchronize();
  pending_i2cstepper_flag = true;
  operationId = reservedId;
  return OPERATION_ERROR_NONE;
}

static OperationError queue_pending_i2ccal(
    PendingI2CCalCmd command, OperationId& operationId) {
  PendingCommandLockGuard guard;
  if (!guard) return OPERATION_ERROR_LOCK_BUSY;
  const bool calibrationStateValid = command.is_finish
      ? I2CPumpCalibrating && startval != SAMOVAR_STARTVAL_CALIBRATION
      : startval == SAMOVAR_STARTVAL_IDLE && !I2CPumpCalibrating;
  if (mode_switch_in_progress() || pending_i2ccal_flag || pending_local_cal_flag ||
      !calibrationStateValid || i2c_stepper_config_busy(i2cStepperPump)) {
    return OPERATION_ERROR_LOCK_BUSY;
  }
  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, OPERATION_KIND_CALIBRATION, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    return reserveError;
  }
  command.operationId = reservedId;
  pending_i2ccal_buf = command;
  __sync_synchronize();
  pending_i2ccal_flag = true;
  operationId = reservedId;
  return OPERATION_ERROR_NONE;
}

static OperationError queue_pending_local_cal(
    PendingLocalCalCmd command, OperationId& operationId) {
  PendingCommandLockGuard guard;
  if (!guard) return OPERATION_ERROR_LOCK_BUSY;
  const bool calibrationStateValid = command.is_finish
      ? startval == SAMOVAR_STARTVAL_CALIBRATION && !I2CPumpCalibrating
      : startval == SAMOVAR_STARTVAL_IDLE && !I2CPumpCalibrating;
  if (mode_switch_in_progress() || pending_local_cal_flag || pending_i2ccal_flag ||
      !calibrationStateValid) {
    return OPERATION_ERROR_LOCK_BUSY;
  }
  OperationId reservedId = 0;
  const OperationError reserveError = operation_store_reserve_locked(
      operationStore, OPERATION_KIND_CALIBRATION, reservedId);
  if (reserveError != OPERATION_ERROR_NONE) {
    return reserveError;
  }
  command.operationId = reservedId;
  pending_local_cal_buf = command;
  __sync_synchronize();
  pending_local_cal_flag = true;
  operationId = reservedId;
  return OPERATION_ERROR_NONE;
}

I2CStepperDevice* select_i2c_stepper_device(AsyncWebServerRequest *request) {
  const AsyncWebParameter *param = get_request_param(request, "device");
  String device = param ? param->value() : "pump";
  if (device == "mixer") return &i2cStepperMixer;
  if (device == "pump") return &i2cStepperPump;
  return nullptr;
}

#include "web_i2c_stepper_parse.h"

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
  NumericParseResult result = parse_i2c_stepper_bounded<uint8_t>(request, "mode", 1, 3, parsed.mode, errorField, parse_bounded_uint8);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint8_t>(request, "relayMask", 0, 15, parsed.relayMask, errorField, parse_bounded_uint8);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint8_t>(request, "sensorFlags", 0, 7, parsed.sensorFlags, errorField, parse_bounded_uint8);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint8_t>(request, "optionFlags", 0, 7, parsed.optionFlags, errorField, parse_bounded_uint8);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint16_t>(request, "mixerRpm", 0, UINT16_MAX, parsed.mixerRpm, errorField, parse_bounded_uint16);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint16_t>(request, "mixerRunSec", 0, UINT16_MAX, parsed.mixerRunSec, errorField, parse_bounded_uint16);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint16_t>(request, "mixerPauseSec", 0, UINT16_MAX, parsed.mixerPauseSec, errorField, parse_bounded_uint16);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint16_t>(request, "pumpMlHour", 0, UINT16_MAX, parsed.pumpMlHour, errorField, parse_bounded_uint16);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint16_t>(request, "pumpPauseSec", 0, UINT16_MAX, parsed.pumpPauseSec, errorField, parse_bounded_uint16);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint16_t>(request, "fillingMl", 0, UINT16_MAX, parsed.fillingMl, errorField, parse_bounded_uint16);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint16_t>(request, "fillingMlHour", 0, UINT16_MAX, parsed.fillingMlHour, errorField, parse_bounded_uint16);
  if (!result.ok()) return result;
  result = parse_i2c_stepper_bounded<uint16_t>(request, "stepsPerMl", 1, UINT16_MAX, parsed.stepsPerMl, errorField, parse_bounded_uint16);
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
  send_operation_accepted(request, operationId);
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
    send_operation_accepted(request, operationId);
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
  send_operation_accepted(request, operationId);
}

static bool column_diam_allowed(float diamInches) {
  return diamInches == 1.5f || diamInches == 2.0f || diamInches == 3.0f;
}

static void handle_column_params_request(AsyncWebServerRequest *request) {
  uint8_t material = 2;
  float diamInches = SamSetup.ColDiam;
  bool haveMat = false;
  bool haveDiam = false;
  const size_t paramCount = request->params();
  for (size_t index = 0; index < paramCount; index++) {
    const AsyncWebParameter *input = request->getParam(index);
    if (!input || input->isFile() || input->isPost()) {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope("argument", nullptr, "Invalid request"));
      return;
    }
    if (input->name() == "mat") {
      if (haveMat) {
        send_no_store_response(
            request, 400, "application/json",
            build_error_envelope("argument", "mat", "Invalid mat"));
        return;
      }
      haveMat = true;
      const int32_t allowed[] = {0, 1, 2};
      int32_t parsed = 0;
      NumericParseResult result = parse_exact_enum(input->value().c_str(), allowed, 3, parsed);
      if (!result.ok()) {
        send_no_store_response(
            request, 400, "application/json",
            build_error_envelope(numeric_parse_error_code(result.error), "mat", "Invalid mat"));
        return;
      }
      material = uint8_t(parsed);
    } else if (input->name() == "diam") {
      if (haveDiam) {
        send_no_store_response(
            request, 400, "application/json",
            build_error_envelope("argument", "diam", "Invalid diam"));
        return;
      }
      haveDiam = true;
      float parsed = 0;
      NumericParseResult result = parse_bounded_float(input->value().c_str(), 1.5f, 3.0f, parsed);
      if (!result.ok() || !column_diam_allowed(parsed)) {
        send_no_store_response(
            request, 400, "application/json",
            build_error_envelope("argument", "diam", "Invalid diam"));
        return;
      }
      diamInches = parsed;
    } else {
      send_no_store_response(
          request, 400, "application/json",
          build_error_envelope("not_allowed", input->name().c_str(), "Invalid request field"));
      return;
    }
  }

  ColumnResults res = calculate_column_etalon(material, diamInches);
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
  json += "\"tailsPowerW\":" + String(res.tailsPowerW, 0) + ",";
  // [В8] Признаки, что рекомендация упёрлась в потолок сечения колонны - дальнейшие
  // изменения параметров формы её не сдвинут, пока не изменится диаметр/высота/насадка.
  json += "\"headsSpeedClamped\":" + String(res.headsSpeedClamped ? "true" : "false") + ",";
  json += "\"bodySpeedClamped\":" + String(res.bodySpeedClamped ? "true" : "false");
  json += "}";
  send_no_store_response(request, 200, "application/json", json);
}

// filter out specific headers from the incoming request
AsyncHeaderFilterMiddleware headerFilter;

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
  // chart.htm - страница наблюдения, кнопок Lua не выводит (нет %btn_list% и #lua_btn в
  // разметке) - не берём мьютекс runtime_state и не копируем список впустую.
  bool pageUsesLuaButtons = strcmp(spiffsPath, "/chart.htm") != 0;
  if (pageUsesLuaButtons && !copy_lua_button_list_cache(luaButtonList)) {
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
  // [WP7 п.5] Раньше здесь Samovar_Mode принудительно перезаписывался значением
  // SamSetup.Mode на каждой отдаче страницы - см. change_samovar_mode() (mode_switch.h)
  // про причину удаления и куда перенесена синхронизация. Живой Samovar_Mode уже корректен без этой
  // записи: страница просто показывает текущий активный режим как есть.
  send_index_template_response(request, get_index_page_path(), "no-cache, no-store, must-revalidate");
}

// Прямой GET /distiller.htm|beer.htm|… иначе отдаётся через serveStatic без шаблонизатора — %WProgram% не подставляется, в UI «тип программы» пустой.
void send_mode_specific_htm(AsyncWebServerRequest *request, const char *spiffsPath, SAMOVAR_MODE requiredMode) {
  // [WP7 п.5] Редирект теперь сверяется с живым Samovar_Mode (а не с SamSetup.Mode) и
  // ничего в него не пишет - см. change_samovar_mode(). Если открыта страница чужого
  // активного режима, пользователя просто отправляют на /index.htm.
  if (Samovar_Mode != requiredMode) {
    request->redirect("/index.htm");
    return;
  }
  send_index_template_response(request, spiffsPath, "no-cache, no-store, must-revalidate");
}

struct CachedStaticFile {
  const char *path;
  const char *cacheControl;
};

static void send_cached_static_file(
    AsyncWebServerRequest *request, const char *path, const char *cacheControl) {
  if (!SPIFFS.exists(path)) {
    request->send(404, "text/plain", String("Missing ") + path);
    return;
  }
  AsyncWebServerResponse *response = request->beginResponse(SPIFFS, path, emptyString, false, nullptr);
  response->addHeader("Cache-Control", cacheControl);
  request->send(response);
}

void WebServerInit(void) {
  FS_register_web_handlers();

  server.on("/", HTTP_GET | HTTP_POST, [](AsyncWebServerRequest* request) {
    request->redirect("/index.htm");
  });
  
  // style.css уезжает только сжатым: serveStatic сам найдёт .gz и проставит Content-Encoding.
  server.serveStatic("/style.css", SPIFFS, "/style.css").setCacheControl("max-age=5000");
  static const CachedStaticFile cachedStaticFiles[] = {
      {"/minus.png", "max-age=604800"},
      {"/plus.png", "max-age=614800"},
      {"/favicon.ico", "max-age=624800"},
      {"/Red_light.gif", "max-age=634800"},
      {"/Green.png", "max-age=644800"},
  };
  for (const CachedStaticFile &entry : cachedStaticFiles) {
    server.on(entry.path, HTTP_GET, [entry](AsyncWebServerRequest *request) {
      send_cached_static_file(request, entry.path, entry.cacheControl);
    });
  }

  server.serveStatic("/alarm.mp3", SPIFFS, "/alarm.mp3");
  server.serveStatic("/resetreason.css", SPIFFS, "/resetreason.css").setCacheControl("max-age=1");
  server.serveStatic("/data_old.csv", SPIFFS, "/data_old.csv").setCacheControl("max-age=1");
  server.serveStatic("/prg.csv", SPIFFS, "/prg.csv").setCacheControl("max-age=1");
  server.serveStatic("/state.csv", SPIFFS, "/state.csv").setCacheControl("max-age=1");
  // [WP7 п.35] .addMiddleware(&headerFilter) на динамических (шаблонизированных) страницах:
  // без него ESPAsyncWebServer может ответить браузеру 304 по If-Modified-Since от статичного
  // .htm-файла на диске, даже когда подставляемые в шаблон живые значения уже другие -
  // пользователь правит вчерашние настройки, думая что видит текущие. headerFilter
  // вырезает этот заголовок из запроса, так и не подключённый к обработчикам изначально.
  // На /style.css и прочую статику (js/css/картинки) он НЕ вешается - их кэшировать нужно.
  server.serveStatic("/program.htm", SPIFFS, "/program.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1").addMiddleware(&headerFilter);
  server.on("/chart.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_index_template_response(request, "/chart.htm", "max-age=1");
  }).addMiddleware(&headerFilter);
  server.serveStatic("/calibrate.htm", SPIFFS, "/calibrate.htm").setTemplateProcessor(calibrateKeyProcessor).setCacheControl("no-store").addMiddleware(&headerFilter);
  server.serveStatic("/i2cstepper.htm", SPIFFS, "/i2cstepper.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1").addMiddleware(&headerFilter);
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
  server.serveStatic("/program_bk.txt", SPIFFS, "/program_bk.txt").setCacheControl("max-age=1");
  server.serveStatic("/program_grain.txt", SPIFFS, "/program_grain.txt").setCacheControl("max-age=1");
  server.serveStatic("/program_shugar.txt", SPIFFS, "/program_shugar.txt").setCacheControl("max-age=1");
  server.serveStatic("/brewxml.htm", SPIFFS, "/brewxml.htm").setCacheControl("max-age=1").addMiddleware(&headerFilter);
  server.serveStatic("/test.txt", SPIFFS, "/test.txt").setTemplateProcessor(indexKeyProcessor).addMiddleware(&headerFilter);
  server.serveStatic("/setup.htm", SPIFFS, "/setup.htm").setTemplateProcessor(setupKeyProcessor).setCacheControl("max-age=1").addMiddleware(&headerFilter);
  // SPIFFSEditor уже обрабатывает /edit с поддержкой gzip в FS.ino

  server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_index_page(request);
  }).addMiddleware(&headerFilter);

  server.on("/rrlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(SPIFFS, "/resetreason.css", String());
  });
  // GET|HEAD: chart page и браузеры могут запрашивать HEAD; только GET давал 501 «Handler did not handle».
  // Если лога ещё нет — beginResponse(nullptr) → тот же 501; отдаём пустой CSV с заголовком как в FS.ino.
  server.on("/data.csv", (WebRequestMethodComposite)(HTTP_GET | HTTP_HEAD), [](AsyncWebServerRequest *request) {
    // 503 только если не удалось даже поставить flush в очередь (лок команд занят).
    // LOG_FLUSH_QUEUED раньше тоже давал 503 — график на первом открытии всегда
    // ловил «HTTP 503» и требовал «Повторить»: запрос ставил flush, а SysTicker
    // после flush сразу пишет новую строку лога, и следующее чтение снова не READY.
    // На диске лежит согласованный CSV до последнего flush; свежие точки догоняет ajax.
    if (schedule_log_flush_if_needed() == LOG_FLUSH_BUSY) {
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
    // Имя файла (param->value()) намеренно не ограничивается по составу/расширению -
    // осознанный выбор владельца. Соответствующая честная оговорка про readString() -
    // у get_lua_script() (lua.h).
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
    handleSave(request);
  });

  headerFilter.filter("If-Modified-Since");

  server.on("/distiller.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/distiller.htm", SAMOVAR_DISTILLATION_MODE);
  }).addMiddleware(&headerFilter);
  server.on("/beer.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/beer.htm", SAMOVAR_BEER_MODE);
  }).addMiddleware(&headerFilter);
  server.on("/bk.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/bk.htm", SAMOVAR_BK_MODE);
  }).addMiddleware(&headerFilter);
  server.on("/nbk.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/nbk.htm", SAMOVAR_NBK_MODE);
  }).addMiddleware(&headerFilter);

  // Автоматическая раздача всех файлов из SPIFFS
  server.serveStatic("/", SPIFFS, "/");
  
  server.begin();
#ifdef __SAMOVAR_DEBUG
  Serial.println("HTTP server started");
#endif
}

// [WP7 п.21] Экранирование пользовательских строк для HTML-контекста (в отличие от
// json_write_escaped из string_utils.h, который экранирует для JSON/<script>). Описание
// программы и цвета датчиков подставляются шаблонизатором в страницу как есть; значение
// вида "</textarea><h1>" рвёт разметку у ВСЕХ, кто потом откроет страницу, а почини это
// может только повторная отправка корректного значения. '&' экранируем первым, чтобы не
// задвоить экранирование уже вставленных сущностей.
static String html_escape(const String &s) {
  String out;
  out.reserve(s.length());
  for (unsigned int i = 0; i < s.length(); i++) {
    switch (s.charAt(i)) {
      case '&': out += F("&amp;"); break;
      case '<': out += F("&lt;"); break;
      case '>': out += F("&gt;"); break;
      case '"': out += F("&quot;"); break;
      case '\'': out += F("&#39;"); break;
      default: out += s.charAt(i); break;
    }
  }
  return out;
}

String indexKeyProcessor(const String &var) {
  if (var == "SteamColor") return html_escape((String)SamSetup.SteamColor);
  else if (var == "v")
    return SAMOVAR_VERSION;
  else if (var == "PipeColor")
    return html_escape((String)SamSetup.PipeColor);
  else if (var == "WaterColor")
    return html_escape((String)SamSetup.WaterColor);
  else if (var == "TankColor")
    return html_escape((String)SamSetup.TankColor);
  else if (var == "ACPColor")
    return html_escape((String)SamSetup.ACPColor);
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
    return html_escape(description);
  } else if (var == "videourl")
    return html_escape((String)SamSetup.videourl);
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
  else if (var == "MainsVoltage")
    return String(SamSetup.MainsVoltage, 2);
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
  if (var == "Descr") return html_escape(description);
  if (var == "btn_list") return toJsonString(luaButtonList);
  return indexKeyProcessor(var);
}

struct GetFloat2Field { const char* var; float SetupEEPROM::* member; };
struct GetFloat2NanSafeField { const char* var; float SetupEEPROM::* member; };
struct GetFloat3Field { const char* var; float SetupEEPROM::* member; };
struct GetFloatDirectField { const char* var; float SetupEEPROM::* member; };
struct GetU16Field { const char* var; uint16_t SetupEEPROM::* member; };
struct GetU8Field { const char* var; uint8_t SetupEEPROM::* member; };
struct GetCheckboxField { const char* var; bool SetupEEPROM::* member; };
struct GetModeSelectField { const char* var; SAMOVAR_MODE mode; };
struct GetRelaySelectField { const char* var; bool SetupEEPROM::* member; bool expected; };
struct GetColToleranceField { const char* var; float SetupEEPROM::* member; float target; };
struct GetDsAddrField { const char* var; uint8_t (SetupEEPROM::* member)[8]; };
struct GetColorField { const char* var; char (SetupEEPROM::* member)[20]; };

static const GetFloat2Field kGetFloat2Fields[] = {
    {"DeltaSteamTemp", &SetupEEPROM::DeltaSteamTemp},
    {"DeltaPipeTemp", &SetupEEPROM::DeltaPipeTemp},
    {"DeltaWaterTemp", &SetupEEPROM::DeltaWaterTemp},
    {"DeltaTankTemp", &SetupEEPROM::DeltaTankTemp},
    {"DeltaACPTemp", &SetupEEPROM::DeltaACPTemp},
    {"SetSteamTemp", &SetupEEPROM::SetSteamTemp},
    {"SuvidTemp", &SetupEEPROM::SuvidTemp},
    {"DistTemp", &SetupEEPROM::DistTemp},
};

static const GetFloat2NanSafeField kGetFloat2NanSafeFields[] = {
    {"SetPipeTemp", &SetupEEPROM::SetPipeTemp},
    {"SetWaterTemp", &SetupEEPROM::SetWaterTemp},
    {"SetTankTemp", &SetupEEPROM::SetTankTemp},
    {"SetACPTemp", &SetupEEPROM::SetACPTemp},
};

static const GetFloat3Field kGetFloat3Fields[] = {
    {"Kp", &SetupEEPROM::Kp},
    {"Ki", &SetupEEPROM::Ki},
    {"Kd", &SetupEEPROM::Kd},
    {"HeaterR", &SetupEEPROM::HeaterResistant},
};

static const GetFloatDirectField kGetFloatDirectFields[] = {
    {"StbVoltage", &SetupEEPROM::StbVoltage},
    {"MainsVoltage", &SetupEEPROM::MainsVoltage},
    {"BVolt", &SetupEEPROM::BVolt},
    {"BKPower", &SetupEEPROM::BKPower},
    {"MaxPressureValue", &SetupEEPROM::MaxPressureValue},
    {"NbkIn", &SetupEEPROM::NbkIn},
    {"NbkDelta", &SetupEEPROM::NbkDelta},
    {"NbkDM", &SetupEEPROM::NbkDM},
    {"NbkDP", &SetupEEPROM::NbkDP},
    {"NbkSteamT", &SetupEEPROM::NbkSteamT},
    {"NbkOwPress", &SetupEEPROM::NbkOwPress},
    {"NbkTn", &SetupEEPROM::NbkTn},
};

static const GetU16Field kGetU16Fields[] = {
    {"SuvidHoldMinutes", &SetupEEPROM::SuvidHoldMinutes},
    {"StepperStepMl", &SetupEEPROM::StepperStepMl},
    {"StepperStepMlI2C", &SetupEEPROM::StepperStepMlI2C},
    {"SteamDelay", &SetupEEPROM::SteamDelay},
    {"PipeDelay", &SetupEEPROM::PipeDelay},
    {"WaterDelay", &SetupEEPROM::WaterDelay},
    {"TankDelay", &SetupEEPROM::TankDelay},
    {"ACPDelay", &SetupEEPROM::ACPDelay},
};

static const GetU8Field kGetU8Fields[] = {
    {"TimeZone", &SetupEEPROM::TimeZone},
    {"LogPeriod", &SetupEEPROM::LogPeriod},
    {"DistTimeF", &SetupEEPROM::DistTimeF},
    {"autospeed", &SetupEEPROM::autospeed},
    {"PackDens", &SetupEEPROM::PackDens},
};

static const GetCheckboxField kGetCheckboxFields[] = {
    {"Checked", &SetupEEPROM::UsePreccureCorrect},
    {"FLChecked", &SetupEEPROM::UseHLS},
    {"UASChecked", &SetupEEPROM::useautospeed},
    {"UASDetectorChecked", &SetupEEPROM::useDetector},
    {"CPBuzz", &SetupEEPROM::ChangeProgramBuzzer},
    {"CUBuzz", &SetupEEPROM::UseBuzzer},
    {"CUBBuzz", &SetupEEPROM::UseBBuzzer},
    {"UseWS", &SetupEEPROM::UseWS},
    {"UseST", &SetupEEPROM::UseST},
    {"ChckPwr", &SetupEEPROM::CheckPower},
};

static const GetModeSelectField kGetModeSelectFields[] = {
    {"RECT", SAMOVAR_RECTIFICATION_MODE},
    {"DIST", SAMOVAR_DISTILLATION_MODE},
    {"BEER", SAMOVAR_BEER_MODE},
    {"BK", SAMOVAR_BK_MODE},
    {"NBK", SAMOVAR_NBK_MODE},
    {"SUVID", SAMOVAR_SUVID_MODE},
    {"LUA_MODE", SAMOVAR_LUA_MODE},
};

static const GetRelaySelectField kGetRelaySelectFields[] = {
    {"RAL", &SetupEEPROM::rele1, false},
    {"RAH", &SetupEEPROM::rele1, true},
    {"RBL", &SetupEEPROM::rele2, false},
    {"RBH", &SetupEEPROM::rele2, true},
    {"RCL", &SetupEEPROM::rele3, false},
    {"RCH", &SetupEEPROM::rele3, true},
    {"RDL", &SetupEEPROM::rele4, false},
    {"RDH", &SetupEEPROM::rele4, true},
};

static const GetColToleranceField kGetColToleranceFields[] = {
    {"ColDiam_1.5", &SetupEEPROM::ColDiam, 1.5f},
    {"ColDiam_2.0", &SetupEEPROM::ColDiam, 2.0f},
    {"ColDiam_3.0", &SetupEEPROM::ColDiam, 3.0f},
    {"ColHeight_0.50", &SetupEEPROM::ColHeight, 0.50f},
    {"ColHeight_0.75", &SetupEEPROM::ColHeight, 0.75f},
    {"ColHeight_1.00", &SetupEEPROM::ColHeight, 1.00f},
    {"ColHeight_1.25", &SetupEEPROM::ColHeight, 1.25f},
    {"ColHeight_1.50", &SetupEEPROM::ColHeight, 1.50f},
    {"ColHeight_1.75", &SetupEEPROM::ColHeight, 1.75f},
    {"ColHeight_2.00", &SetupEEPROM::ColHeight, 2.00f},
    {"ColHeight_2.25", &SetupEEPROM::ColHeight, 2.25f},
    {"ColHeight_2.50", &SetupEEPROM::ColHeight, 2.50f},
};

static const GetDsAddrField kGetDsAddrFields[] = {
    {"SteamAddr", &SetupEEPROM::SteamAdress},
    {"PipeAddr", &SetupEEPROM::PipeAdress},
    {"WaterAddr", &SetupEEPROM::WaterAdress},
    {"TankAddr", &SetupEEPROM::TankAdress},
    {"ACPAddr", &SetupEEPROM::ACPAdress},
};

static const GetColorField kGetColorFields[] = {
    {"SteamColor", &SetupEEPROM::SteamColor},
    {"PipeColor", &SetupEEPROM::PipeColor},
    {"WaterColor", &SetupEEPROM::WaterColor},
    {"TankColor", &SetupEEPROM::TankColor},
    {"ACPColor", &SetupEEPROM::ACPColor},
};

String setupKeyProcessor(const String &var) {
  static String s;
  s = "";
  for (const GetFloat2Field &f : kGetFloat2Fields) {
    if (var == f.var) {
      s = format_float(SamSetup.*f.member, 2);
      return s;
    }
  }
  for (const GetFloat2NanSafeField &f : kGetFloat2NanSafeFields) {
    if (var == f.var) {
      float v = isnan(SamSetup.*f.member) ? 0 : SamSetup.*f.member;
      s = format_float(v, 2);
      return s;
    }
  }
  for (const GetFloat3Field &f : kGetFloat3Fields) {
    if (var == f.var) {
      s = format_float(SamSetup.*f.member, 3);
      return s;
    }
  }
  for (const GetFloatDirectField &f : kGetFloatDirectFields) {
    if (var == f.var) {
      s = SamSetup.*f.member;
      return s;
    }
  }
  for (const GetU16Field &f : kGetU16Fields) {
    if (var == f.var) {
      s = SamSetup.*f.member;
      return s;
    }
  }
  for (const GetU8Field &f : kGetU8Fields) {
    if (var == f.var) {
      s = SamSetup.*f.member;
      return s;
    }
  }
  for (const GetCheckboxField &f : kGetCheckboxFields) {
    if (var == f.var) return (SamSetup.*f.member) ? "checked='true'" : "";
  }
  for (const GetModeSelectField &f : kGetModeSelectFields) {
    if (var == f.var) {
      // [WP17 п.45] Режим, недоступный в этой сборке (нет регулятора мощности для
      // НБК, нет USE_LUA для Lua-режима) - не должен появляться в списке выбора.
      // [fix] Если недоступный режим — это уже СОХРАНЁННЫЙ режим
      // пользователя, его нужно не только скрыть, но и оставить выбранным
      // ("hidden selected") - иначе ни один <option> не помечен selected, браузер сам
      // выберет первый пункт списка ("Ректификация"), и сохранение ЛЮБОЙ другой
      // настройки молча подменит режим пользователя (форма /setup.htm
      // отправляется целиком). Браузеры показывают текст выбранного <option>
      // в закрытом <select> даже если у него есть hidden - в списке выбора он при этом не появится.
      const bool isCurrentMode = (SAMOVAR_MODE)SamSetup.Mode == f.mode;
      if (!mode_available_in_build(f.mode)) return isCurrentMode ? "hidden selected" : "hidden";
      return isCurrentMode ? "selected" : "";
    }
  }
  for (const GetRelaySelectField &f : kGetRelaySelectFields) {
    if (var == f.var) return (SamSetup.*f.member == f.expected) ? "selected" : "";
  }
  for (const GetColToleranceField &f : kGetColToleranceFields) {
    if (var == f.var) return (abs(SamSetup.*f.member - f.target) < 0.01f) ? "selected" : "";
  }
  for (const GetDsAddrField &f : kGetDsAddrFields) {
    if (var == f.var) return get_DSAddressList(getDSAddress(SamSetup.*f.member));
  }
  for (const GetColorField &f : kGetColorFields) {
    if (var == f.var) {
      // [WP7 п.21] Цвета датчиков редактируются пользователем и подставляются в
      // value='%...%'/style="..." без своих кавычек - см. html_escape().
      s = html_escape(String(SamSetup.*f.member));
      return s;
    }
  }
  if (var == "WProgram") {
    return serialize_program_for_mode(Samovar_Mode);
#ifdef IGNORE_HEAD_LEVEL_SENSOR_SETTING
  } else if (var == "IgnFL") {
    return F("style="
             "display: none"
             "");
#endif
  } else if (var == "videourl") {
    s = html_escape(String(SamSetup.videourl));
    return s;
  } else if (var == "blynkauth") {
    s = html_escape(String(SamSetup.blynkauth));
    return s;
  } else if (var == "tgtoken") {
    s = html_escape(String(SamSetup.tg_token));
    return s;
  } else if (var == "tgchatid") {
    s = html_escape(String(SamSetup.tg_chat_id));
    return s;
  } else if (var == "ColDiam") {
    return String(SamSetup.ColDiam, 1);
  } else if (var == "ColHeight") {
    return String(SamSetup.ColHeight, 2);
  } else if (var == "BKPowerFloor") {
    // [T16] Рабочий порог регулятора (power_work_mode_threshold()): значение
    // BKPower ниже него уводит регулятор в спящий режим после закипания.
    // Отдаём порог странице setup.htm для клиентской проверки (setupNumericSchema).
    return String(power_work_mode_threshold(), 2);
  } else if (var == "I2CStepperTab") {
    // [W-3] Читаем из кэша (обновляется в SysTicker), без I2C в async.
    return (i2c_stepper_cache.mixer_present || i2c_stepper_cache.pump_present) ? "inline-block" : "none";
  } else if (var == "I2CPumpTab") {
    return i2c_stepper_cache.pump_present ? "inline-block" : "none";
  }
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
    return startval == SAMOVAR_STARTVAL_CALIBRATION || I2CPumpCalibrating ? "1" : "0";
  else if (var == "CalibrationPump")
    return I2CPumpCalibrating ? "i2c" : "local";

  return String();
}

bool is_valid_samovar_mode(long mode) {
  return mode >= SAMOVAR_RECTIFICATION_MODE && mode <= SAMOVAR_LUA_MODE;
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
  PendingCommandLockGuard guard;
  if (!guard) return false;
  cancelled = pending_mode_control_commands_locked();
  pending_rescan_ds_flag = false;
  pending_stop_self_test_flag = false;
  pending_mixer_flag = false;
  pending_water_temp_flag = false;
  pending_pump_speed_flag = false;
  pending_nbkopt_flag = false;
  // Очистка идёт ДО КОНЦА даже при отказе I2C-ветки: ранний return оставлял
  // pnbk/voltage/lua-флаги взведёнными, а смена режима всё равно могла завершиться
  // по дедлайну (force_complete_mode_switch_failed) - команда старого режима
  // применялась уже в новом. Результат I2C-ветки возвращается неизменным.
  const bool i2cDiscarded = cancel_queued_i2c_operations_locked(cancelled);
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
  return i2cDiscarded;
}

#include "mode_switch.h"

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

// [T35 п.4в] В отличие от parse_save_long_arg (общая, зовётся ещё и вне этих трёх
// циклов - см. блок stepperstepml), эти три функции apply_save_*_arg
// используются ТОЛЬКО циклами по kSaveU16Fields/kSaveFloatFields/kSaveU8Fields в
// handleSave, поэтому не шлют ответ сами: handleSave копит имена всех неверных полей
// вместо разрыва на первом же (request_param_count(...)!=1 для каждого параметра уже
// проверен раньше, в самом начале handleSave, - здесь остаётся только разбор значения).
static bool apply_save_u8_arg(AsyncWebServerRequest *request, const char *name, uint8_t& target, long minValue, long maxValue) {
  if (!request->hasArg(name)) return true;
  const AsyncWebParameter *param = get_request_param(request, name);
  long value = 0;
  NumericParseResult result = param && !param->isFile()
      ? parse_bounded_long(param->value().c_str(), minValue, maxValue, value)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) return false;
  target = (uint8_t)value;
  return true;
}

static bool apply_save_u16_arg(AsyncWebServerRequest *request, const char *name, uint16_t& target, long minValue, long maxValue) {
  if (!request->hasArg(name)) return true;
  const AsyncWebParameter *param = get_request_param(request, name);
  long value = 0;
  NumericParseResult result = param && !param->isFile()
      ? parse_bounded_long(param->value().c_str(), minValue, maxValue, value)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) return false;
  target = (uint16_t)value;
  return true;
}

// [T35 п.4в] Копит имена всех полей вне диапазона вместо ответа по первому же -
// пользователь видит сразу весь список, а не отправляет форму заново на каждый отказ
// по очереди. Приём - как в sanitize_setup_profile_ranges() (String, копящая имена через
// запятую), только сразу в виде готовых элементов JSON-массива. Строка растёт в куче,
// поэтому имена ограничены SAVE_RANGE_ERROR_FIELD_LIMIT; badFieldsCount считает все
// отказы, даже сверх предела, - клиент не должен решить, что полей меньше, чем есть.
static const uint8_t SAVE_RANGE_ERROR_FIELD_LIMIT = 8;

static void collect_save_bad_field(
    const char *name, String& badFieldsJson, String& firstBadField, uint8_t& badFieldsCount) {
  if (badFieldsCount == 0) firstBadField = name;
  if (badFieldsCount < SAVE_RANGE_ERROR_FIELD_LIMIT) {
    if (badFieldsJson.length()) badFieldsJson += ",";
    badFieldsJson += toJsonString(name);
  }
  badFieldsCount++;
}

// Тот же конверт, что build_error_envelope() (field/message - для обратной
// совместимости, первое плохое поле), плюс "fields" - имена ВСЕХ полей вне диапазона.
// build_error_envelope() саму не трогаем - она общая для остальных обработчиков и
// запинена smoke_api_error_envelope.py.
static String build_save_range_errors_envelope(const String& firstBadField, const String& badFieldsJson) {
  String message = "Invalid ";
  message += firstBadField;
  // Единственный сборщик конверта ошибок - build_error_envelope() (см.
  // check_single_envelope_builder в smoke_api_error_envelope.py) - второе место, которое
  // вручную начинает JSON-объект ошибки, заводить нельзя. Здесь только дописываем
  // ключ fields перед закрывающей скобкой её результата - но сперва проверяем, что
  // вырезаемый символ действительно '}': если build_error_envelope() когда-нибудь
  // допишет хвост после скобки, слепой substring() молча испортит JSON. При несовпадении
  // отдаём исходный конверт как есть - без fields, но валидным JSON (smoke_save_range_errors.py).
  String json = build_error_envelope("range", firstBadField.c_str(), message);
  if (!json.length() || json.charAt(json.length() - 1) != '}') return json;
  json = json.substring(0, json.length() - 1);
  json += ",\"fields\":[";
  json += badFieldsJson;
  json += "]}";
  return json;
}

#include "web_save_string_arg.h"

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

// [T35 п.4в] Как apply_save_u8_arg/apply_save_u16_arg выше - используется только циклом
// по kSaveFloatFields, ответ на отказ шлёт вызывающий (копит поле, не обрывает сразу).
static bool apply_save_float_arg(AsyncWebServerRequest *request, const char *name, float& target, float minValue, float maxValue) {
  if (!request->hasArg(name)) return true;
  const AsyncWebParameter *param = get_request_param(request, name);
  float value = 0;
  NumericParseResult result = param && !param->isFile()
      ? parse_bounded_float(param->value().c_str(), minValue, maxValue, value)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) return false;
  target = value;
  return true;
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

// Единый источник истины для сохраняемых полей #setupform: каждая таблица описывает
// имя параметра формы, поле SetupEEPROM (через указатель на член) и границы валидации.
// save_param_name_allowed() и handleSave() читают ОДНИ И ТЕ ЖЕ таблицы, поэтому имя,
// добавленное в применение, автоматически становится допустимым (и наоборот).
struct SaveFloatField { const char* name; float SetupEEPROM::* member; float minValue; float maxValue; };
struct SaveU16Field { const char* name; uint16_t SetupEEPROM::* member; long minValue; long maxValue; };
struct SaveU8Field  { const char* name; uint8_t  SetupEEPROM::* member; long minValue; long maxValue; };
struct SaveCheckboxField { const char* name; bool SetupEEPROM::* member; };
struct SaveBool01Field   { const char* name; bool SetupEEPROM::* member; };
struct SaveColorField    { const char* name; char (SetupEEPROM::* member)[20]; };
struct SaveDsAddrField   { const char* name; uint8_t (SetupEEPROM::* member)[8]; uint8_t resetBit; };

static const SaveU16Field kSaveU16Fields[] = {
    {"SteamDelay", &SetupEEPROM::SteamDelay, 0, 65535},
    {"PipeDelay", &SetupEEPROM::PipeDelay, 0, 65535},
    {"WaterDelay", &SetupEEPROM::WaterDelay, 0, 65535},
    {"TankDelay", &SetupEEPROM::TankDelay, 0, 65535},
    {"ACPDelay", &SetupEEPROM::ACPDelay, 0, 65535},
    {"SuvidHoldMinutes", &SetupEEPROM::SuvidHoldMinutes, 0, 65535},
    // [Б1.2] Нижняя граница поднята с 0: при StepperStepMl==0 цель TargetStepps =
    // Volume * StepperStepMl всегда 0, и строка программы ректификации не завершается
    // никогда (переход по температуре в ректификации намеренно не используется).
    // validate_rect_program_startable() блокирует лишь СТАРТ, а не сохранение формы.
    {"StepperStepMl", &SetupEEPROM::StepperStepMl, 1, 65535},
    {"StepperStepMlI2C", &SetupEEPROM::StepperStepMlI2C, 0, 65535},
};

static const SaveFloatField kSaveFloatFields[] = {
    {"DeltaSteamTemp", &SetupEEPROM::DeltaSteamTemp, -1000.0f, 1000.0f},
    {"DeltaPipeTemp", &SetupEEPROM::DeltaPipeTemp, -1000.0f, 1000.0f},
    {"DeltaWaterTemp", &SetupEEPROM::DeltaWaterTemp, -1000.0f, 1000.0f},
    {"DeltaTankTemp", &SetupEEPROM::DeltaTankTemp, -1000.0f, 1000.0f},
    {"DeltaACPTemp", &SetupEEPROM::DeltaACPTemp, -1000.0f, 1000.0f},
    {"SetSteamTemp", &SetupEEPROM::SetSteamTemp, 0.0f, 150.0f},
    {"SetPipeTemp", &SetupEEPROM::SetPipeTemp, 0.0f, 150.0f},
    {"SetWaterTemp", &SetupEEPROM::SetWaterTemp, 0.0f, 150.0f},
    {"SetTankTemp", &SetupEEPROM::SetTankTemp, 0.0f, 150.0f},
    {"SetACPTemp", &SetupEEPROM::SetACPTemp, 0.0f, 150.0f},
    {"SuvidTemp", &SetupEEPROM::SuvidTemp, 0.0f, 100.0f},
    {"Kp", &SetupEEPROM::Kp, 0.0f, 100000.0f},
    {"Ki", &SetupEEPROM::Ki, 0.0f, 100000.0f},
    {"Kd", &SetupEEPROM::Kd, 0.0f, 100000.0f},
    {"StbVoltage", &SetupEEPROM::StbVoltage, 0.0f, 10000.0f},
    {"BVolt", &SetupEEPROM::BVolt, 0.0f, 10000.0f},
    // [T16] Нижняя граница поднята с 0: BKPower - мощность БК (BK.h::check_alarm_bk)
    // после закипания. Если задать её ниже рабочего порога регулятора
    // (power_work_mode_threshold()), регулятор уйдёт в спящий режим и нагрев
    // тихо остановится - без этой границы форма примет такое значение молча.
    {"BKPower", &SetupEEPROM::BKPower, power_work_mode_threshold(), 10000.0f},
    {"MaxPressureValue", &SetupEEPROM::MaxPressureValue, 0.0f, 10000.0f},
    // [WP7 п.11] Нижняя граница поднята с 0: условие окончания - TankSensor.avgTemp >=
    // DistTemp (distiller.h/BK.h/alarm.h) - при DistTemp=0 выполняется на первой же
    // секунде и обрывает дистилляцию/БК/ректификацию без внятной причины в сообщении.
    // 30°C заведомо ниже любой рабочей температуры куба, но выше комнатной - случайно
    // ввести ноль (или пустое поле, парсящееся в 0) больше не получится незаметно.
    {"DistTemp", &SetupEEPROM::DistTemp, 30.0f, 150.0f},
    {"HeaterR", &SetupEEPROM::HeaterResistant, CONTROL_HEATER_R_MIN, CONTROL_HEATER_R_MAX},
    {"MainsVoltage", &SetupEEPROM::MainsVoltage, 0.0f, 1000.0f},
    {"NbkIn", &SetupEEPROM::NbkIn, 0.0f, 100000.0f},
    {"NbkDelta", &SetupEEPROM::NbkDelta, 0.0f, 100000.0f},
    {"NbkDM", &SetupEEPROM::NbkDM, 0.0f, 100000.0f},
    {"NbkDP", &SetupEEPROM::NbkDP, 0.0f, 100000.0f},
    {"NbkSteamT", &SetupEEPROM::NbkSteamT, 0.0f, 150.0f},
    {"NbkOwPress", &SetupEEPROM::NbkOwPress, 0.0f, 100000.0f},
    {"NbkTn", &SetupEEPROM::NbkTn, 0.0f, 150.0f},
    {"ColDiam", &SetupEEPROM::ColDiam, 0.1f, 10.0f},
    {"ColHeight", &SetupEEPROM::ColHeight, 0.01f, 10.0f},
};

static const SaveU8Field kSaveU8Fields[] = {
    {"DistTimeF", &SetupEEPROM::DistTimeF, 0, 255},
    {"autospeed", &SetupEEPROM::autospeed, 0, 99},
    {"TimeZone", &SetupEEPROM::TimeZone, 0, 23},
    {"LogPeriod", &SetupEEPROM::LogPeriod, 1, 255},
    // [Б9] Нижняя граница поднята с 0 до 60: HTML-слайдер в setup.htm уже ограничен
    // 60-100 (подпись "(60-100)"), сервер разрешал 0..100 - рассинхрон.
    {"PackDens", &SetupEEPROM::PackDens, 60, 100},
};

static const SaveCheckboxField kSaveCheckboxFields[] = {
    {"useflevel", &SetupEEPROM::UseHLS},
    {"usepressure", &SetupEEPROM::UsePreccureCorrect},
    {"useautospeed", &SetupEEPROM::useautospeed},
    {"useDetector", &SetupEEPROM::useDetector},
    {"ChangeProgramBuzzer", &SetupEEPROM::ChangeProgramBuzzer},
    {"UseBuzzer", &SetupEEPROM::UseBuzzer},
    {"UseBBuzzer", &SetupEEPROM::UseBBuzzer},
    {"UseWS", &SetupEEPROM::UseWS},
    {"UseST", &SetupEEPROM::UseST},
    {"CheckPower", &SetupEEPROM::CheckPower},
};

static const SaveBool01Field kSaveBool01Fields[] = {
    {"rele1", &SetupEEPROM::rele1},
    {"rele2", &SetupEEPROM::rele2},
    {"rele3", &SetupEEPROM::rele3},
    {"rele4", &SetupEEPROM::rele4},
};

static const SaveColorField kSaveColorFields[] = {
    {"SteamColor", &SetupEEPROM::SteamColor},
    {"PipeColor", &SetupEEPROM::PipeColor},
    {"WaterColor", &SetupEEPROM::WaterColor},
    {"TankColor", &SetupEEPROM::TankColor},
    {"ACPColor", &SetupEEPROM::ACPColor},
};

static const SaveDsAddrField kSaveDsAddrFields[] = {
    {"SteamAddr", &SetupEEPROM::SteamAdress, PROFILE_SENSOR_RESET_STEAM},
    {"PipeAddr", &SetupEEPROM::PipeAdress, PROFILE_SENSOR_RESET_PIPE},
    {"WaterAddr", &SetupEEPROM::WaterAdress, PROFILE_SENSOR_RESET_WATER},
    {"TankAddr", &SetupEEPROM::TankAdress, PROFILE_SENSOR_RESET_TANK},
    {"ACPAddr", &SetupEEPROM::ACPAdress, PROFILE_SENSOR_RESET_ACP},
};

// Строки разного размера (copyStringSafe шаблонный по N) и служебные параметры,
// меняющие поток управления в handleSave, не табличятся по значению — но их имена
// обязаны попадать в тот же источник истины для allowlist.
static const char* const kSaveMiscStringNames[] = {"videourl", "blynkauth", "tgtoken", "tgchatid"};
static const char* const kSaveSpecialNames[] = {"fullsetup", "save", "clear", "mode", "WProgram", "stepperstepml"};

static bool save_param_name_allowed(const String& name) {
  for (const SaveU16Field &f : kSaveU16Fields) if (name == f.name) return true;
  for (const SaveFloatField &f : kSaveFloatFields) if (name == f.name) return true;
  for (const SaveU8Field &f : kSaveU8Fields) if (name == f.name) return true;
  for (const SaveCheckboxField &f : kSaveCheckboxFields) if (name == f.name) return true;
  for (const SaveBool01Field &f : kSaveBool01Fields) if (name == f.name) return true;
  for (const SaveColorField &f : kSaveColorFields) if (name == f.name) return true;
  for (const SaveDsAddrField &f : kSaveDsAddrFields) if (name == f.name) return true;
  for (const char* n : kSaveMiscStringNames) if (name == n) return true;
  for (const char* n : kSaveSpecialNames) if (name == n) return true;
  return false;
}

// [T28] Мигрированный из EEPROM профиль (migrate_from_eeprom() в NVS_Manager.ino)
// проверяет только flag и Mode - остальные ~30 числовых полей уходят в NVS как есть,
// и мусор из битого сектора молча становится рабочими настройками на годы. Переиспользуем
// те же таблицы диапазонов, что и проверка формы /save (kSaveU16Fields/kSaveFloatFields/kSaveU8Fields),
// вместо отдельного набора границ.
bool sanitize_setup_profile_ranges(SetupEEPROM& profile, String& fixedFieldsOut) {
  SetupEEPROM defaults{};
  set_default_setup_profile(defaults);
  bool changed = false;
  // [Б1.2] Раньше эта таблица не обходилась, потому что у всех её полей границы
  // совпадали с полным диапазоном uint16_t. StepperStepMl сузил границы первым.
  for (const SaveU16Field &f : kSaveU16Fields) {
    long v = profile.*f.member;
    if (v < f.minValue || v > f.maxValue) {
      profile.*f.member = defaults.*f.member;
      if (fixedFieldsOut.length()) fixedFieldsOut += ",";
      fixedFieldsOut += f.name;
      changed = true;
    }
  }
  for (const SaveFloatField &f : kSaveFloatFields) {
    float v = profile.*f.member;
    if (!isfinite(v) || v < f.minValue || v > f.maxValue) {
      profile.*f.member = defaults.*f.member;
      if (fixedFieldsOut.length()) fixedFieldsOut += ",";
      fixedFieldsOut += f.name;
      changed = true;
    }
  }
  for (const SaveU8Field &f : kSaveU8Fields) {
    long v = profile.*f.member;
    if (v < f.minValue || v > f.maxValue) {
      profile.*f.member = defaults.*f.member;
      if (fixedFieldsOut.length()) fixedFieldsOut += ",";
      fixedFieldsOut += f.name;
      changed = true;
    }
  }
  return changed;
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
      requestedMode = (SAMOVAR_MODE)requestedModeValue;
      // [WP17 п.45] Режим существует в enum (allowedModes выше), но может быть не
      // скомпилирован в этой сборке (НБК без регулятора мощности, Lua без USE_LUA) -
      // раньше это отбивалось только в момент СТАРТА режима, без внятного сообщения
      // на сохранении настроек.
      // [fix] Отбиваем только РЕАЛЬНУЮ попытку переключиться на недоступный режим.
      // Форма /setup.htm отправляется целиком - сохранение ЛЮБОЙ другой настройки
      // тоже присылает поле mode с уже сохранённым значением; если этот уже
      // сохранённый режим стал недоступен (сменили прошивку), отбивать такую
      // повторную присылку нельзя - иначе пользователь не сможет сохранить
      // вообще ничего, пока не переключит режим.
      if (!mode_available_in_build(requestedMode) &&
          requestedMode != (SAMOVAR_MODE)sourceProfileMode) {
        const char* reason = mode_unavailable_reason(requestedMode);
        send_no_store_response(
            request, 400, "application/json",
            build_error_envelope(
                "not_allowed", "mode",
                reason ? String(reason) : String("Режим недоступен в этой сборке прошивки")));
        return;
      }
      modeRequested = true;
    }
  }

  // [T29] async_tcp может вытеснить loop() посреди присваивания SamSetup
  // (commit_profile_operation() и др.) - без спинлока это чтение могло бы
  // застать структуру наполовину скопированной.
  portENTER_CRITICAL(&configMux);
  SetupEEPROM staged = SamSetup;
  portEXIT_CRITICAL(&configMux);
  uint8_t sensorResetMask = 0;
  DSAddressSnapshot dsSnapshot;
  copy_ds_address_snapshot(dsSnapshot);
  if (modeRequested) {
    staged.Mode = (int)requestedMode;
  }

  // [T35 п.4в] Три цикла ниже (kSaveU16Fields/kSaveFloatFields/kSaveU8Fields) копят
  // имена полей вне диапазона вместо ответа по первому же отказу - см. проверку
  // badFieldsCount после цикла по kSaveU8Fields. Остальные проверки в handleSave
  // (allowlist, дубликаты параметров, stepperstepml, цвет длиннее буфера и т.д.)
  // остаются структурными и по-прежнему обрывают сразу - это не про диапазон значения,
  // а про форму самого запроса.
  String saveBadFieldsJson;
  String saveFirstBadField;
  uint8_t saveBadFieldsCount = 0;

  for (const SaveU16Field &f : kSaveU16Fields) {
    if (!apply_save_u16_arg(request, f.name, staged.*f.member, f.minValue, f.maxValue)) {
      collect_save_bad_field(f.name, saveBadFieldsJson, saveFirstBadField, saveBadFieldsCount);
    }
  }
  if (request->hasArg("stepperstepml")) {
    if (request->hasArg("StepperStepMl")) {
      send_save_parse_error(request, "stepperstepml", NUMERIC_PARSE_INVALID_ARGUMENT);
      return;
    }
    long stepsPer100Ml = 0;
    if (!parse_save_long_arg(request, "stepperstepml", 100, 6553500, stepsPer100Ml)) return;
    if ((stepsPer100Ml % 100) != 0) {
      send_save_parse_error(request, "stepperstepml", NUMERIC_PARSE_NOT_ALLOWED);
      return;
    }
    staged.StepperStepMl = (uint16_t)(stepsPer100Ml / 100);
  }

  for (const SaveFloatField &f : kSaveFloatFields) {
    if (!apply_save_float_arg(request, f.name, staged.*f.member, f.minValue, f.maxValue)) {
      collect_save_bad_field(f.name, saveBadFieldsJson, saveFirstBadField, saveBadFieldsCount);
    }
  }

  for (const SaveU8Field &f : kSaveU8Fields) {
    if (!apply_save_u8_arg(request, f.name, staged.*f.member, f.minValue, f.maxValue)) {
      collect_save_bad_field(f.name, saveBadFieldsJson, saveFirstBadField, saveBadFieldsCount);
    }
  }

  if (saveBadFieldsCount > 0) {
    send_no_store_response(
        request, 400, "application/json",
        build_save_range_errors_envelope(saveFirstBadField, saveBadFieldsJson));
    return;
  }

  for (const SaveCheckboxField &f : kSaveCheckboxFields) {
    update_checkbox_arg(request, f.name, staged.*f.member, fullSetupForm);
  }

  if (!apply_save_string_arg(request, "videourl", staged.videourl)) return;
  if (!apply_save_string_arg(request, "blynkauth", staged.blynkauth)) return;
  if (!apply_save_string_arg(request, "tgtoken", staged.tg_token)) return;
  if (!apply_save_string_arg(request, "tgchatid", staged.tg_chat_id)) return;

  for (const SaveColorField &f : kSaveColorFields) {
    if (!apply_save_string_arg(request, f.name, staged.*f.member)) return;
  }

  for (const SaveBool01Field &f : kSaveBool01Fields) {
    if (!apply_save_bool01_arg(request, f.name, staged.*f.member)) return;
  }

  for (const SaveDsAddrField &f : kSaveDsAddrFields) {
    if (!apply_save_ds_addr_arg(request, f.name, dsSnapshot, staged.*f.member, f.resetBit, sensorResetMask)) return;
  }

  const bool hasSwitchMode = modeRequested &&
      (sourceProfileMode != static_cast<int>(requestedMode) ||
       sourceMode != requestedMode);
  if (hasSwitchMode && PowerOn) {
    send_no_store_response(request, 409, "text/plain", operation_error_code(OPERATION_ERROR_CANCELLED));
    return;
  }
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
  send_operation_accepted(request, operationId);
  // is_reboot обрабатывается в loop() — рестарт выполнится после отправки ответа.
}

static bool web_command_name_allowed(const String& name) {
  if (name == "start" || name == "power" || name == "setbodytemp" ||
      name == "reset" || name == "reboot" || name == "resetwifi" ||
      name == "startst" || name == "rescands" || name == "stopst" ||
      name == "mixer" || name == "pnbk" || name == "nbkopt" ||
      name == "distiller" || name == "startbk" || name == "startnbk" ||
      name == "watert" || name == "pumpspeed" || name == "pause" ||
      name == "waterauto") return true;
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
  bool powerValueGiven = false;
  uint16_t waterPwm = 0;
  uint16_t pumpSpeedSteps = 0;
  ControlNbkCommand nbkCommand = {};
#ifdef SAMOVAR_USE_POWER
  float voltage = 0.0f;
#endif
  NumericParseResult parseResult = numeric_parse_result(NUMERIC_PARSE_OK);
  String commandKeySuffix;
  if (action == "mixer" || action == "distiller" ||
      action == "startbk" || action == "startnbk") {
    parseResult = parse_exact_bool(actionParam->value().c_str(), boolValue);
    commandKeySuffix = boolValue ? "=1" : "=0";
  } else if (action == "power") {
    // Пустое значение (голый power - так дёргают URL внешние интеграции и
    // старые закладки; страницы прошивки шлют power=0/1) - это НЕ ошибка,
    // а сигнал "использовать старое поведение-переключатель" (powerValueGiven=false).
    if (actionParam->value().length() > 0) {
      parseResult = parse_exact_bool(actionParam->value().c_str(), boolValue);
      powerValueGiven = parseResult.ok();
      commandKeySuffix = boolValue ? "=1" : "=0";
    }
  } else if (action == "watert") {
    parseResult = parse_control_water_pwm(actionParam->value().c_str(), waterPwm);
    commandKeySuffix = "=" + String(waterPwm);
  } else if (action == "waterauto") {
    // [9b] "Автомат" - только включатель (значение обязано быть "1"); чтобы
    // выключить авторежим, штатный путь - ручная правка watert (см. set_water_temp).
    parseResult = parse_exact_bool(actionParam->value().c_str(), boolValue);
    if (parseResult.ok() && !boolValue) {
      parseResult = numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
    }
    commandKeySuffix = "=1";
  } else if (action == "pumpspeed") {
    parseResult = parse_control_rate_steps(
        actionParam->value().c_str(), SamSetup.StepperStepMl, pumpSpeedSteps);
    commandKeySuffix = "=" + String(pumpSpeedSteps);
  } else if (action == "pnbk") {
    parseResult = parse_control_nbk(
        actionParam->value().c_str(), SamSetup.StepperStepMlI2C, nbkCommand);
    if (parseResult.ok() && nbkCommand.kind != CONTROL_NBK_STOP &&
        SamSetup.StepperStepMlI2C == 0) {
      parseResult = numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    }
    commandKeySuffix = "=" + String(uint8_t(nbkCommand.kind));
    commandKeySuffix += ":" + String(nbkCommand.stepSpeed);
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
    commandKeySuffix = "=" + String(voltage, 6);
  }
#endif
#ifdef USE_LUA
  else if (action == "lua" || action == "luastr") {
    commandKeySuffix = "=" + actionParam->value();
  }
#endif
  if (!parseResult.ok()) {
    send_web_command_response(request, 400, "BAD_REQUEST");
    return;
  }

  String commandKey = action;
  commandKey += commandKeySuffix;

  bool bypassThrottle = action == "reset" || action == "reboot" || action == "resetwifi" ||
      action == "lua" || action == "luastr";
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
    SamovarCommands command = SAMOVAR_NONE;
    if (!powerValueGiven) {
      command = SAMOVAR_POWER;                                         // голый power: старое поведение-переключатель
      if (!PowerOn) command = mode_power_on_command(Samovar_Mode);
    } else if (boolValue) {
      if (!PowerOn) command = mode_power_on_command(Samovar_Mode);      // уже включено -> no-op
    } else {
      command = SAMOVAR_POWER_OFF;                                     // всегда выключить
    }
    if (command != SAMOVAR_NONE && !queue_samovar_command(command)) {
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
    SamovarCommands command = boolValue ? SAMOVAR_DISTILLATION : SAMOVAR_POWER_OFF;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "startbk") {
    SamovarCommands command = boolValue ? SAMOVAR_BK : SAMOVAR_POWER_OFF;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "startnbk") {
    SamovarCommands command = boolValue ? SAMOVAR_NBK : SAMOVAR_POWER_OFF;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "watert") {
    if (Samovar_Mode == SAMOVAR_BK_MODE && PowerOn && waterPwm < PWM_LOW_VALUE * 10) {
      send_web_command_response(request, 409, "PWM_TOO_LOW");
      return;
    }
    if (!queue_pending_value(pending_water_temp_flag, pending_water_temp_value, waterPwm)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "waterauto") {
#ifndef USE_WATER_PUMP
    send_web_command_response(request, 409, "NO_PUMP");
    return;
#else
    if (Samovar_Mode != SAMOVAR_BK_MODE || !PowerOn || ProgramNum >= ProgramLen) {
      send_web_command_response(request, 409, "NOT_RUNNING");
      return;
    }
    if (program[ProgramNum].Temp == 0) {
      send_web_command_response(request, 409, "NO_SETPOINT");
      return;
    }
    if (!queue_pending_flag(pending_water_auto_flag)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
#endif
  } else if (action == "pumpspeed") {
    if (!queue_pending_value(pending_pump_speed_flag, pending_pump_speed_steps, pumpSpeedSteps)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "pause") {
    // [Пиво 02.09 C1] PauseOn ИЛИ beerManualPause — как Blynk.ino:317, Menu.ino:440.
    SamovarCommands command = (PauseOn || beerManualPause) ? SAMOVAR_CONTINUE : SAMOVAR_PAUSE;
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
          request, 400, false, F("Описание длиннее 250 байт"), String());
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
  const bool localCalibrating = startval == SAMOVAR_STARTVAL_CALIBRATION;
  const bool i2cCalibrating = I2CPumpCalibrating;
  const bool invalidState = isFinish
      ? (isI2C ? !i2cCalibrating || localCalibrating
               : !localCalibrating || i2cCalibrating)
      : startval != SAMOVAR_STARTVAL_IDLE || i2cCalibrating;
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
  send_operation_accepted(request, operationId);
}

void get_data_log(AsyncWebServerRequest *request, String fn) {
  if (schedule_log_flush_if_needed() != LOG_FLUSH_READY) {
    request->send(503, "text/plain", "BUSY");
    return;
  }
  bool locked = log_file_lock();
  if (!locked) {
    request->send(503, "text/plain", "BUSY");
    return;
  }
  // [WP7 п.36] Раньше заголовки вложения (Content-Disposition: attachment) уходили ВМЕСТЕ
  // с 400 при отсутствующем файле - браузер молча скачивал пустой файл вместо показа
  // сообщения об ошибке. Теперь при отсутствии файла заголовки вложения не отправляются.
  if (!SPIFFS.exists("/" + fn)) {
    log_file_unlock(true);
    request->send(400, "text/plain", "Log file not found: " + fn);
    return;
  }
  // Честная граница: AsyncFileResponse открывает файл и читает его размер синхронно
  // внутри beginResponse() ниже, а отдаёт содержимое уже асинхронно, после возврата из
  // этой функции. Лок защищает только момент открытия (совпадение с ротацией лога), а не
  // всю передачу целиком - держать лок на всю передачу заблокировало бы штатную запись
  // показаний на секунды. Это осознанный размен.
  AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/" + fn, String(), true);
  log_file_unlock(true);
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

// Комплект data/ почти заполняет раздел LittleFS, поэтому файлы качаются по одному
// и пишутся сразу в конечный путь: без *.tmp/*.bak и без rename (LittleFS не
// переименовывает открытый файл). Тело ответа не копится в RAM — чанки сливаются
// во флеш, пока запрос ещё идёт; иначе program.htm (~80 КБ) рвёт TCP
// (HTTPCODE_CONNECTION_LOST). Обрыв на файле N удаляет его неполный хвост, 1..N-1
// уже новые, N+1 старые; маркер версии не пишется, обновление можно повторить.
static bool write_web_file(const String& path, const String& content) {
  File wf = SPIFFS.open(path, FILE_WRITE);
  if (!wf) {
    Serial.println("WEB interface write failed, open: " + path);
    return false;
  }

  const size_t written = wf.write((const uint8_t*)content.c_str(), content.length());
  wf.close();
  if (written != content.length()) {
    Serial.println("WEB interface write failed, partial: " + path);
    SPIFFS.remove(path);
    return false;
  }
  return true;
}

static bool web_file_content_empty_invalid(const String& fn, get_web_type type, const String& content) {
  if (content.length() != 0) {
    return false;
  }
  if (type == GET_CONTENT) {
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

    // Порядок: сначала общие ресурсы, затем HTML. При обрыве на файле N цикл
    // останавливается — лучше оставить старую страницу, чем битый общий ресурс.
    static const char* const kWebOverrideFiles[] = {
        "Green.png", "Red_light.gif", "alarm.mp3", "favicon.ico",
        "minus.png", "plus.png",
        "style.css.gz", "app.js.gz", "chart.js.gz",
        "index.htm", "beer.htm", "bk.htm", "nbk.htm", "brewxml.htm.gz", "calibrate.htm",
        "chart.htm", "distiller.htm", "i2cstepper.htm.gz", "edit.htm.gz",
        "program.htm", "setup.htm",
    };
    static const size_t kWebOverrideFileCount = sizeof(kWebOverrideFiles) / sizeof(kWebOverrideFiles[0]);

    // used_byte заполняется только в setup_finalize_boot_display(); к этому моменту
    // загрузка ещё не дошла туда, поэтому спрашиваем SPIFFS напрямую.
    static const uint32_t WEB_UPDATE_FREE_SPACE_MARGIN_BYTES = 65536;
    uint32_t freeBytes = SPIFFS.totalBytes() - SPIFFS.usedBytes();
    if (freeBytes < WEB_UPDATE_FREE_SPACE_MARGIN_BYTES) {
      Serial.println("WEB interface update aborted: not enough free space");
      SendMsg("Обновление веб-интерфейса отменено: мало места на диске", ALARM_MSG);
      updateOk = false;
    }

    for (size_t i = 0; i < kWebOverrideFileCount; i++) {
      updateFile(kWebOverrideFiles[i], SAVE_FILE_OVERRIDE);
      if (!updateOk) break;
    }

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
    updateFile("program_bk.txt", SAVE_FILE_IF_NOT_EXIST);
    updateFile("program_grain.txt", SAVE_FILE_IF_NOT_EXIST);
    updateFile("program_shugar.txt", SAVE_FILE_IF_NOT_EXIST);

    if (updateOk) {
      // Версию уже скачали в начале функции — записываем нормализованную строку, без повторного HTTP.
      String versionMarker = version + "\n";
      if (!write_web_file("/version.txt", versionMarker)) {
        Serial.println("WEB interface update failed on version marker; local version marker was not changed.");
        updateOk = false;
      }
    }

    if (!updateOk) {
      Serial.println("WEB interface update aborted; local version marker was not changed.");
      SendMsg("Обновление веб-интерфейса не завершено, версия не изменилась", WARNING_MSG);
    }
  }
}

// Один объект запроса на всю прошивку, живёт всё время работы.
// Почему не локальный на стеке: lwIP не умеет отменять начатый DNS-резолв, и колбэк с
// именем хоста приходит уже после нашего таймаута. Разрушенный объект в этот момент —
// обращение в освобождённую память (панику InstrFetchProhibited сразу за строкой
// "Timeout: readyState never reached 1" ловили пользователи при пропаже интернета).
// У долгоживущего объекта опоздавший колбэк попадает в живую память.
static asyncHTTPrequest sharedHttpRequest;

// Мьютекс сериализует обращения: объект один, а зовут его из задачи уведомлений и из
// загрузки веб-интерфейса. Ждать освобождения долго незачем — запрос всё равно
// блокирующий, поэтому занятость возвращаем как обычную ошибку запроса.
static const TickType_t HTTP_REQUEST_LOCK_WAIT = pdMS_TO_TICKS(2000);
static StaticSemaphore_t httpRequestLockBuffer;
static SemaphoreHandle_t httpRequestLock = xSemaphoreCreateMutexStatic(&httpRequestLockBuffer);

struct HttpRequestLockGuard {
  bool acquired;

  HttpRequestLockGuard()
    : acquired(httpRequestLock != nullptr && xSemaphoreTake(httpRequestLock, HTTP_REQUEST_LOCK_WAIT) == pdTRUE) {}

  ~HttpRequestLockGuard() {
    if (acquired) xSemaphoreGive(httpRequestLock);
  }
};

static void abort_http_request(void* requestPtr) {
  asyncHTTPrequest* request = static_cast<asyncHTTPrequest*>(requestPtr);
  request->abort();

  uint32_t abortStartTime = millis();
  while (request->readyState() != 4 && millis() - abortStartTime < 1000) {
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
}

static bool drain_http_body_to_file(asyncHTTPrequest& request, File& wf, size_t& total) {
  uint8_t buf[512];
  while (true) {
    const size_t avail = request.available();
    if (avail == 0) {
      return true;
    }
    const size_t chunk = avail < sizeof(buf) ? avail : sizeof(buf);
    const size_t got = request.responseRead(buf, chunk);
    if (got == 0) {
      return true;
    }
    if (wf.write(buf, got) != got) {
      Serial.println("WEB interface write failed, partial: " + String(wf.name()));
      return false;
    }
    total += got;
  }
}

// Общая часть трёх http_sync_request_*: открыть соединение, дождаться готовности,
// при необходимости выставить заголовок Content-Type, отправить запрос и дождаться
// завершения (readyState() == 4). bodySink — опционально сливать тело во файл по мере
// прихода, не копя его в xbuf. При неудаче печатает диагностику, зовёт
// abort_http_request() и возвращает false.
static bool http_sync_request_connect_and_send(const String& method, const String& url,
                                               const String& body, const String& contentType,
                                               bool alwaysSetContentTypeHeader, bool alwaysSendBody,
                                               uint32_t timeoutMs,
                                               File* bodySink = nullptr,
                                               size_t* bodyWritten = nullptr) {
  if (!sharedHttpRequest.open(method.c_str(), url.c_str())) {
    Serial.println("HTTP " + method + " open() failed, readyState = " + String(sharedHttpRequest.readyState()));
    return false;
  }

  unsigned long startTime = millis();
  while (sharedHttpRequest.readyState() < 1) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: readyState never reached 1");
      abort_http_request(&sharedHttpRequest);
      return false;
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  if (alwaysSetContentTypeHeader || contentType.length() > 0) {
    sharedHttpRequest.setReqHeader("Content-Type", getValue(contentType, ':', 1).c_str());
  }
  const bool sent = (alwaysSendBody || body.length() > 0) ? sharedHttpRequest.send(body) : sharedHttpRequest.send();
  if (!sent) {
    Serial.println("HTTP " + method + " send() failed");
    abort_http_request(&sharedHttpRequest);
    return false;
  }

  vTaskDelay(150 / portTICK_PERIOD_MS);
  startTime = millis();
  while (sharedHttpRequest.readyState() != 4) {
    if (millis() - startTime > timeoutMs) {
      Serial.println("Timeout: sharedHttpRequest not completed within " + String(timeoutMs / 1000) + " seconds");
      abort_http_request(&sharedHttpRequest);
      return false;
    }
    if (bodySink != nullptr && bodyWritten != nullptr) {
      if (!drain_http_body_to_file(sharedHttpRequest, *bodySink, *bodyWritten)) {
        abort_http_request(&sharedHttpRequest);
        return false;
      }
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  if (bodySink != nullptr && bodyWritten != nullptr) {
    if (!drain_http_body_to_file(sharedHttpRequest, *bodySink, *bodyWritten)) {
      return false;
    }
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  return true;
}

static bool http_sync_complete_get(asyncHTTPrequest& request, const String& url, uint32_t timeoutMs) {
  request.setTimeout(timeoutMs / 1000U);
  if (!http_sync_request_connect_and_send("GET", url, "", "", false, false, timeoutMs)) {
    return false;
  }
  if (request.responseHTTPcode() < 0) {
    Serial.print(F("responseHTTPcode = "));
    Serial.println(request.responseHTTPcode());
    Serial.println("Content " + url + " download error (2)");
    return false;
  }
  if (request.responseHTTPcode() != 200) {
    Serial.print(F("responseHTTPcode = "));
    Serial.println(request.responseHTTPcode());
    Serial.println("Content " + url + " download error");
    return false;
  }
  return true;
}

String http_sync_request_get(String url) {
  HttpRequestLockGuard lockGuard;
  if (!lockGuard.acquired) {
    Serial.println("HTTP GET skipped: request object is busy");
    return "<ERR>";
  }
  asyncHTTPrequest& request = sharedHttpRequest;
  request.setDebug(false);
  const uint32_t timeoutMs = 8000;
  if (!http_sync_complete_get(request, url, timeoutMs)) {
    return "<ERR>";
  }
  const size_t availableBefore = request.available();
  String response = request.responseText();
  size_t expectedLength = request.responseLength();
  if (expectedLength > 0 && response.length() != expectedLength) {
    Serial.println("Content " + url + " incomplete: " + String(response.length()) + "/" + String(expectedLength));
    Serial.println(
        "HTTP GET body not copied to String: available=" + String(availableBefore) +
        " heap=" + String(ESP.getFreeHeap()) +
        " maxAlloc=" + String(ESP.getMaxAllocHeap()) +
        " http=" + String(request.responseHTTPcode()));
    return "<ERR>";
  }
  return response;
}

static bool http_sync_download_file(const String& url, const String& path) {
  HttpRequestLockGuard lockGuard;
  if (!lockGuard.acquired) {
    Serial.println("HTTP GET skipped: request object is busy");
    return false;
  }
  asyncHTTPrequest& request = sharedHttpRequest;
  request.setDebug(false);
  const uint32_t timeoutMs = 20000;
  request.setTimeout(timeoutMs / 1000U);

  File wf = SPIFFS.open(path, FILE_WRITE);
  if (!wf) {
    Serial.println("WEB interface write failed, open: " + path);
    return false;
  }

  size_t written = 0;
  const bool transferred = http_sync_request_connect_and_send(
      "GET", url, "", "", false, false, timeoutMs, &wf, &written);
  wf.close();
  if (!transferred) {
    SPIFFS.remove(path);
    return false;
  }

  if (request.responseHTTPcode() < 0) {
    Serial.print(F("responseHTTPcode = "));
    Serial.println(request.responseHTTPcode());
    Serial.println("Content " + url + " download error (2)");
    SPIFFS.remove(path);
    return false;
  }
  if (request.responseHTTPcode() != 200) {
    Serial.print(F("responseHTTPcode = "));
    Serial.println(request.responseHTTPcode());
    Serial.println("Content " + url + " download error");
    SPIFFS.remove(path);
    return false;
  }

  const size_t expectedLength = request.responseLength();
  if (expectedLength == 0 || written == 0 || written != expectedLength) {
    Serial.println(
        "Content " + url + " incomplete: " + String(written) + "/" + String(expectedLength) +
        " heap=" + String(ESP.getFreeHeap()) +
        " maxAlloc=" + String(ESP.getMaxAllocHeap()));
    SPIFFS.remove(path);
    return false;
  }

  Serial.println("Done (L=" + String(written) + ")");
  return true;
}

String get_web_file(String fn, get_web_type type) {
  if (type == SAVE_FILE_IF_NOT_EXIST && SPIFFS.exists("/" + fn)) {
    Serial.println("File " + fn + " already exist.");
    return "";
  }

  String url = "http://web.samovar-tool.ru/" + String(SAMOVAR_VERSION) + "/" + fn + "?" + micros();
  Serial.print("url = ");
  Serial.println(url);

  if (type != GET_CONTENT) {
    if (!http_sync_download_file(url, "/" + fn)) {
      return "<ERR>";
    }
    return "";
  }

  String s = http_sync_request_get(url);
  if (s == "<ERR>") {
    return s;
  }
  if (web_file_content_empty_invalid(fn, type, s)) {
    return "<ERR>";
  }
  return s;
}

// Вариант для Lua-обёртки: метод, тело и Content-Type задаёт скрипт, таймаут короче, чем у
// загрузки веб-интерфейса. Тот же долгоживущий объект под тем же мьютексом, что и у
// http_sync_request_get/post — локальный asyncHTTPrequest на стеке Lua-задачи разрушался
// раньше, чем приходил опоздавший колбэк lwIP, и это давало панику при пропаже интернета.
String http_sync_request_custom(const String& method, const String& url, const String& body, const String& contentType) {
  HttpRequestLockGuard lockGuard;
  if (!lockGuard.acquired) {
    Serial.println("HTTP " + method + " skipped: request object is busy");
    return "<ERR>";
  }
  asyncHTTPrequest& request = sharedHttpRequest;
  request.setDebug(false);
  const uint32_t timeoutMs = 2000;
  request.setTimeout(2);  //Таймаут две секунды (внутренний по отсутствию активности)

  if (!http_sync_request_connect_and_send(method, url, body, contentType, false, false, timeoutMs)) {
    return "<ERR>";
  }
  if (request.responseHTTPcode() > 0) {
    return request.responseText();
  }
  return "<ERR>";
}
