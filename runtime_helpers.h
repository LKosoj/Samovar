#ifndef RUNTIME_HELPERS_H
#define RUNTIME_HELPERS_H

#include "Samovar.h"

extern portMUX_TYPE timerMux;
extern portMUX_TYPE waterPulseMux;

inline bool runtime_state_lock(TickType_t timeout = pdMS_TO_TICKS(50)) {
  return xRuntimeStateSemaphore && xSemaphoreTake(xRuntimeStateSemaphore, timeout) == pdTRUE;
}

inline void runtime_state_unlock(bool locked) {
  if (locked) xSemaphoreGive(xRuntimeStateSemaphore);
}

inline void water_pulse_count_set(uint16_t value) {
  portENTER_CRITICAL(&waterPulseMux);
  WFpulseCount = value;
  portEXIT_CRITICAL(&waterPulseMux);
}

inline uint16_t water_pulse_count_get() {
  portENTER_CRITICAL(&waterPulseMux);
  uint16_t value = WFpulseCount;
  portEXIT_CRITICAL(&waterPulseMux);
  return value;
}

inline uint16_t water_pulse_count_take() {
  portENTER_CRITICAL(&waterPulseMux);
  uint16_t value = WFpulseCount;
  WFpulseCount = 0;
  portEXIT_CRITICAL(&waterPulseMux);
  return value;
}

inline bool pending_command_lock(TickType_t timeout = pdMS_TO_TICKS(50)) {
  return xPendingCommandSemaphore && xSemaphoreTake(xPendingCommandSemaphore, timeout) == pdTRUE;
}

inline void pending_command_unlock(bool locked) {
  if (locked) xSemaphoreGive(xPendingCommandSemaphore);
}

inline ProgramType program_type_at(uint8_t index) {
  if (index >= PROGRAM_MAX) return PROGRAM_TYPE_NONE;
  return program[index].WType;
}

inline ProgramType current_program_type() {
  return program_type_at(ProgramNum);
}

inline bool log_file_lock(TickType_t timeout = pdMS_TO_TICKS(50)) {
  return xLogFileSemaphore && xSemaphoreTake(xLogFileSemaphore, timeout) == pdTRUE;
}

inline void log_file_unlock(bool locked) {
  if (locked) xSemaphoreGive(xLogFileSemaphore);
}

inline const char* program_wait_type_text(ProgramWaitType waitType) {
  switch (waitType) {
    case PROGRAM_WAIT_STEAM: return "(пар)";
    case PROGRAM_WAIT_PIPE: return "(царга)";
    case PROGRAM_WAIT_DETECTOR: return "(Детектор)";
    case PROGRAM_WAIT_NONE:
    default: return "";
  }
}

inline bool copy_program_wait_type(ProgramWaitType& waitType, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  waitType = program_Wait_Type;
  runtime_state_unlock(true);
  return true;
}

inline bool copy_program_wait_type_text(String& text, TickType_t timeout = pdMS_TO_TICKS(50)) {
  ProgramWaitType waitType = PROGRAM_WAIT_NONE;
  if (!copy_program_wait_type(waitType, timeout)) return false;
  text = program_wait_type_text(waitType);
  return true;
}

inline bool program_wait_type_is(ProgramWaitType waitType, bool& matches, TickType_t timeout = pdMS_TO_TICKS(50)) {
  ProgramWaitType currentType = PROGRAM_WAIT_NONE;
  if (!copy_program_wait_type(currentType, timeout)) return false;
  matches = (currentType == waitType);
  return true;
}

inline bool set_program_wait_type(ProgramWaitType waitType, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  program_Wait_Type = waitType;
  runtime_state_unlock(true);
  return true;
}

inline bool copy_session_description(String& description, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  description = SessionDescription;
  runtime_state_unlock(true);
  return true;
}

inline bool set_session_description_value(const String& description, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  SessionDescription = description;
  runtime_state_unlock(true);
  return true;
}

inline bool copy_mqtt_session_description(String& description, TickType_t timeout = pdMS_TO_TICKS(500)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  description = SessionDescription;
  runtime_state_unlock(true);
  description.replace(",", ";");
  return true;
}

inline bool set_web_message_raw(const String& message, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  Msg = message;
  runtime_state_unlock(true);
  return true;
}

inline bool copy_web_message_raw(String& message, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  message = Msg;
  runtime_state_unlock(true);
  return true;
}

inline bool set_lua_status_value(const String& status, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  Lua_status = status;
  runtime_state_unlock(true);
  return true;
}

inline bool copy_lua_status(String& status, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  status = Lua_status;
  runtime_state_unlock(true);
  return true;
}

inline bool consume_ajax_runtime_snapshot(String& crt, String& status, String& luaStatus, String& currentPowerMode,
                                          String& msg, uint8_t& level, bool& hasMessage,
                                          String& logMessage, bool& hasLog,
                                          TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  crt = Crt;
  status = SamovarStatus;
  luaStatus = Lua_status;
  currentPowerMode = current_power_mode;
  hasMessage = Msg.length() > 0;
  if (hasMessage) {
    msg = Msg;
    level = msg_level;
    Msg = "";
    msg_level = NONE_MSG;
  }
  hasLog = LogMsg.length() > 0;
  if (hasLog) {
    logMessage = LogMsg;
    LogMsg = "";
  }
  runtime_state_unlock(true);
  return true;
}

inline bool copy_current_power_mode_value(String& mode, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  mode = current_power_mode;
  runtime_state_unlock(true);
  return true;
}

inline String get_current_power_mode_value() {
  String mode;
  if (!copy_current_power_mode_value(mode)) return String();
  return mode;
}

inline bool current_power_mode_is(const String& mode) {
  return get_current_power_mode_value() == mode;
}

inline void set_current_power_mode_value(const String& mode) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(500));
  if (!locked) return;
  current_power_mode = mode;
  runtime_state_unlock(true);
}

inline float reduce_power_by_volts(float power, float volts) {
  return power - volts * PWR_FACTOR;
}

inline bool append_web_message(const String& message, MESSAGE_TYPE messageType) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(500));
  if (!locked) return false;
  if (Msg.length() > 0) {
    Msg += "; ";
    if (msg_level > messageType) msg_level = messageType;
  } else {
    msg_level = messageType;
  }
  Msg += message;
  if (Msg.length() > 250) {
    Msg = message;
    msg_level = messageType;
  }
  runtime_state_unlock(true);
  return true;
}

inline void append_console_log(const String& logMessage) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(500));
  if (!locked) return;
  if (LogMsg.length() > 0) {
    LogMsg = LogMsg + "; " + logMessage;
  } else {
    LogMsg = logMessage;
  }
  if (LogMsg.length() > 10000) {
    LogMsg = logMessage;
  }
  runtime_state_unlock(true);
}

#ifdef USE_HEAD_LEVEL_SENSOR
inline void head_level_sensor_tick() {
  bool locked = runtime_state_lock();
  if (!locked) return;
  whls.tick();
  runtime_state_unlock(true);
}

inline bool head_level_sensor_holded() {
  bool locked = runtime_state_lock();
  if (!locked) return false;
  whls.tick();
  bool holded = whls.isHolded();
  if (holded) whls.resetStates();
  runtime_state_unlock(true);
  return holded;
}
#endif

inline int32_t stepper_safe_get_target() {
  portENTER_CRITICAL(&timerMux);
  int32_t value = stepper.getTarget();
  portEXIT_CRITICAL(&timerMux);
  return value;
}

inline int32_t stepper_safe_get_current() {
  portENTER_CRITICAL(&timerMux);
  int32_t value = stepper.getCurrent();
  portEXIT_CRITICAL(&timerMux);
  return value;
}

inline float stepper_safe_get_speed() {
  portENTER_CRITICAL(&timerMux);
  float value = stepper.getSpeed();
  portEXIT_CRITICAL(&timerMux);
  return value;
}

inline bool stepper_safe_get_state() {
  portENTER_CRITICAL(&timerMux);
  bool value = stepper.getState();
  portEXIT_CRITICAL(&timerMux);
  return value;
}

inline void stepper_safe_set_max_speed(float speed) {
  portENTER_CRITICAL(&timerMux);
  stepper.setMaxSpeed(speed);
  portEXIT_CRITICAL(&timerMux);
}

inline void stepper_safe_set_current(int32_t current) {
  portENTER_CRITICAL(&timerMux);
  stepper.setCurrent(current);
  portEXIT_CRITICAL(&timerMux);
}

inline void stepper_safe_set_target(int32_t target) {
  portENTER_CRITICAL(&timerMux);
  stepper.setTarget(target);
  portEXIT_CRITICAL(&timerMux);
}

inline void stepper_safe_set_motion(float speed, int32_t current, int32_t target) {
  portENTER_CRITICAL(&timerMux);
  stepper.setMaxSpeed(speed);
  stepper.setCurrent(current);
  stepper.setTarget(target);
  portEXIT_CRITICAL(&timerMux);
}

inline void stepper_safe_stop() {
  portENTER_CRITICAL(&timerMux);
  stepper.brake();
  stepper.disable();
  portEXIT_CRITICAL(&timerMux);
}

inline void stepper_safe_stop_reset() {
  portENTER_CRITICAL(&timerMux);
  stepper.brake();
  stepper.disable();
  stepper.setCurrent(0);
  stepper.setTarget(0);
  portEXIT_CRITICAL(&timerMux);
}

#endif
