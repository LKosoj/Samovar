#ifndef RUNTIME_HELPERS_H
#define RUNTIME_HELPERS_H

#include "Samovar.h"

extern portMUX_TYPE timerMux;

inline bool runtime_state_lock(TickType_t timeout = (TickType_t)(50 / portTICK_RATE_MS)) {
  return xRuntimeStateSemaphore && xSemaphoreTake(xRuntimeStateSemaphore, timeout) == pdTRUE;
}

inline void runtime_state_unlock(bool locked) {
  if (locked) xSemaphoreGive(xRuntimeStateSemaphore);
}

inline String get_current_power_mode_value() {
  bool locked = runtime_state_lock();
  String mode = current_power_mode;
  runtime_state_unlock(locked);
  return mode;
}

inline bool current_power_mode_is(const String& mode) {
  return get_current_power_mode_value() == mode;
}

inline void set_current_power_mode_value(const String& mode) {
  bool locked = runtime_state_lock();
  current_power_mode = mode;
  runtime_state_unlock(locked);
}

inline bool consume_web_message(String& msg, uint8_t& level) {
  bool locked = runtime_state_lock();
  bool hasMessage = Msg.length() > 0;
  if (hasMessage) {
    msg = Msg;
    level = msg_level;
    Msg = "";
    msg_level = NONE_MSG;
  }
  runtime_state_unlock(locked);
  return hasMessage;
}

inline void append_web_message(const String& message, MESSAGE_TYPE messageType) {
  bool locked = runtime_state_lock();
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
  runtime_state_unlock(locked);
}

inline bool consume_console_log(String& logMessage) {
  bool locked = runtime_state_lock();
  bool hasLog = LogMsg.length() > 0;
  if (hasLog) {
    logMessage = LogMsg;
    LogMsg = "";
  }
  runtime_state_unlock(locked);
  return hasLog;
}

inline void append_console_log(const String& logMessage) {
  bool locked = runtime_state_lock();
  if (LogMsg.length() > 0) {
    LogMsg = LogMsg + "; " + logMessage;
  } else {
    LogMsg = logMessage;
  }
  if (LogMsg.length() > 10000) {
    LogMsg = logMessage;
  }
  runtime_state_unlock(locked);
}

#ifdef USE_HEAD_LEVEL_SENSOR
inline void head_level_sensor_tick() {
  bool locked = runtime_state_lock();
  whls.tick();
  runtime_state_unlock(locked);
}

inline bool head_level_sensor_holded() {
  bool locked = runtime_state_lock();
  whls.tick();
  bool holded = whls.isHolded();
  if (holded) whls.resetStates();
  runtime_state_unlock(locked);
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
