#ifndef RUNTIME_HELPERS_H
#define RUNTIME_HELPERS_H

#include "Samovar.h"
#include "runtime_event_log.h"

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

bool mode_switch_in_progress();

template <typename T>
inline bool queue_pending_value(volatile bool& flag, volatile T& valueSlot, T value) {
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

// [PKG-F] Приватный Lua-курсор по кольцу событий. Трогается только из задачи
// do_lua_script (одиночный писатель): Msg-геттер продвигает его, старт one-shot
// job сбрасывает. Кольцо общее с веб-клиентами (у них свой курсор в
// copy_ajax_runtime_snapshot), поэтому Lua читает «прочитал-и-стёр» приватно.
static uint32_t lua_message_cursor = 0;

// [PKG-F] Возвращает следующее непрочитанное ЭТИМ Lua-читателем сообщение (или "",
// если новых нет), продвигая приватный курсор. Console-события пропускаются.
inline bool copy_web_message_raw(String& message, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  message = "";
  uint32_t localCursor = lua_message_cursor;
  for (uint8_t guard = 0; guard <= RUNTIME_EVENT_DESCRIPTOR_CAPACITY; guard++) {
    RuntimeEventDescriptor selected{};
    const RuntimeEventSelectResult selectResult =
        runtime_event_select_locked(runtimeEventRing, localCursor, selected);
    if (selectResult == RUNTIME_EVENT_SELECT_NONE) break;  // новых событий нет
    if (selectResult != RUNTIME_EVENT_SELECT_FOUND) {       // corrupt
      runtime_state_unlock(true);
      return false;
    }
    localCursor = selected.sequence;                        // продвигаем за это событие
    if (selected.kind != RUNTIME_EVENT_MESSAGE) continue;   // console пропускаем
    if (runtime_event_copy_text_locked(runtimeEventRing, selected, message) !=
        RUNTIME_EVENT_SNAPSHOT_OK) {
      runtime_state_unlock(true);
      return false;
    }
    break;
  }
  lua_message_cursor = localCursor;
  runtime_state_unlock(true);
  return true;
}

// [PKG-F] Сброс Lua-курсора на новейшее событие («с текущего момента»), чтобы
// свежий one-shot job не переигрывал бэклог сообщений.
inline bool reset_lua_message_cursor(TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  lua_message_cursor = runtime_event_latest_sequence_locked(runtimeEventRing);
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

enum RuntimeAjaxQueryKind : uint8_t {
  RUNTIME_AJAX_QUERY_OPERATION = 0,
  RUNTIME_AJAX_QUERY_TELEMETRY,
  RUNTIME_AJAX_QUERY_INVALID_OPERATION,
  RUNTIME_AJAX_QUERY_BAD_REQUEST,
};

struct RuntimeAjaxQuery {
  RuntimeAjaxQueryKind kind;
  uint32_t value;
};

enum RuntimeAjaxSnapshotResult : uint8_t {
  RUNTIME_AJAX_SNAPSHOT_OK = 0,
  RUNTIME_AJAX_SNAPSHOT_LOCK_BUSY,
  RUNTIME_AJAX_SNAPSHOT_NO_MEMORY,
  RUNTIME_AJAX_SNAPSHOT_CORRUPT,
};

inline RuntimeAjaxSnapshotResult copy_ajax_runtime_snapshot(
    String& crt, String& status, String& luaStatus, String& currentPowerMode,
    uint32_t cursor, String& eventText, RuntimeEventDescriptor& event,
    bool& hasEvent, uint32_t& latestSequence, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return RUNTIME_AJAX_SNAPSHOT_LOCK_BUSY;
  crt = Crt;
  status = SamovarStatus;
  luaStatus = Lua_status;
  currentPowerMode = current_power_mode;
  latestSequence = runtime_event_latest_sequence_locked(runtimeEventRing);
  const RuntimeEventSelectResult selectResult =
      runtime_event_select_locked(runtimeEventRing, cursor, event);
  if (selectResult == RUNTIME_EVENT_SELECT_CORRUPT) {
    runtime_state_unlock(true);
    return RUNTIME_AJAX_SNAPSHOT_CORRUPT;
  }
  hasEvent = selectResult == RUNTIME_EVENT_SELECT_FOUND;
  if (hasEvent) {
    const RuntimeEventSnapshotResult copyResult =
        runtime_event_copy_text_locked(runtimeEventRing, event, eventText);
    if (copyResult != RUNTIME_EVENT_SNAPSHOT_OK) {
      runtime_state_unlock(true);
      return copyResult == RUNTIME_EVENT_SNAPSHOT_NO_MEMORY
                 ? RUNTIME_AJAX_SNAPSHOT_NO_MEMORY
                 : RUNTIME_AJAX_SNAPSHOT_CORRUPT;
    }
  }
  runtime_state_unlock(true);
  return RUNTIME_AJAX_SNAPSHOT_OK;
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

enum RuntimeEventPublishResult : uint8_t {
  RUNTIME_EVENT_PUBLISH_OK = 0,
  RUNTIME_EVENT_PUBLISH_EMPTY,
  RUNTIME_EVENT_PUBLISH_LOCK_BUSY,
  RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG,
  RUNTIME_EVENT_PUBLISH_CORRUPT,
};

inline RuntimeEventPublishResult append_runtime_event(
    RuntimeEventKind kind, const String& text, uint8_t level,
    TickType_t timeout = pdMS_TO_TICKS(500)) {
  if (text.length() == 0) return RUNTIME_EVENT_PUBLISH_EMPTY;
  if (text.length() > RUNTIME_EVENT_MAX_TEXT_BYTES) {
    return RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG;
  }
  // Задача 6: SendMsg/WriteConsoleLog зовутся из SysTicker и PowerStatusTask — обе жёстко
  // запинены на core0 (xTaskCreatePinnedToCore в Samovar.ino) и обязаны укладываться в свой
  // секундный/UART-цикл. Долгое ожидание лока (по умолчанию 500мс) стопорит эти циклы.
  // async_tcp тут ни при чём: он запинен на CONFIG_ASYNC_TCP_RUNNING_CORE=1 (platformio.ini)
  // и сегодня не вызывает SendMsg/WriteConsoleLog напрямую — только через pending_*-флаги,
  // разбираемые в loop(). Раньше клэмп держался на xPortGetCoreID()==0, что верно совпадало
  // с этими двумя задачами лишь случайно и ломалось при любой перепиновке core в будущем.
  // Сравниваем хэндл текущей задачи явно, а не номер ядра, чтобы клэмп бил точно по своим
  // владельцам короткого таймаута. loopTask и все прочие задачи сохраняют полный таймаут.
  const TaskHandle_t currentRuntimeEventTask = xTaskGetCurrentTaskHandle();
  const bool isShortTimeoutTask =
      (currentRuntimeEventTask == SysTickerTask1)
#ifdef SAMOVAR_USE_POWER
      || (currentRuntimeEventTask == PowerStatusTask)
#endif
      ;
  if (isShortTimeoutTask && timeout > pdMS_TO_TICKS(50)) {
    timeout = pdMS_TO_TICKS(50);
  }
  bool locked = runtime_state_lock(timeout);
  if (!locked) return RUNTIME_EVENT_PUBLISH_LOCK_BUSY;
  RuntimeEventAppendResult result = runtime_event_append_locked(
      runtimeEventRing, kind, level, text.c_str(), text.length());
  // Задача 2: кольцо повреждено. Единственный писатель уже держит runtime_state_lock,
  // поэтому чиним здесь же (повторно лок НЕ берём): реинициализируем кольцо, оставляем
  // маркер восстановления и повторяем исходную запись. Rate-limit защищает от бесконечного
  // реинита при устойчивой порче — не чаще раза в 5с (первый раз — всегда), overflow-safe.
  if (result == RUNTIME_EVENT_APPEND_CORRUPT) {
    static const char kRingRecoveryMarker[] =
        "Журнал событий переинициализирован после повреждения";
    constexpr uint32_t RUNTIME_EVENT_RESET_MIN_INTERVAL_MS = 5000U;
    static uint32_t lastRingResetMs = 0;
    static bool ringResetSeen = false;
    const uint32_t nowMs = millis();
    if (!ringResetSeen ||
        (int32_t)(nowMs - lastRingResetMs) >=
            (int32_t)RUNTIME_EVENT_RESET_MIN_INTERVAL_MS) {
      ringResetSeen = true;
      lastRingResetMs = nowMs;
      runtime_event_init(runtimeEventRing);
      runtime_event_append_locked(runtimeEventRing, RUNTIME_EVENT_MESSAGE,
                                  static_cast<uint8_t>(WARNING_MSG),
                                  kRingRecoveryMarker,
                                  sizeof(kRingRecoveryMarker) - 1);
      result = runtime_event_append_locked(
          runtimeEventRing, kind, level, text.c_str(), text.length());
    }
  }
  runtime_state_unlock(true);
  switch (result) {
    case RUNTIME_EVENT_APPEND_OK: return RUNTIME_EVENT_PUBLISH_OK;
    case RUNTIME_EVENT_APPEND_EMPTY: return RUNTIME_EVENT_PUBLISH_EMPTY;
    case RUNTIME_EVENT_TEXT_TOO_LONG: return RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG;
    case RUNTIME_EVENT_APPEND_INVALID_ARGUMENT:
    case RUNTIME_EVENT_APPEND_CORRUPT:
    default: return RUNTIME_EVENT_PUBLISH_CORRUPT;
  }
}

inline RuntimeEventPublishResult append_web_message(
    const String& message, MESSAGE_TYPE messageType) {
  return append_runtime_event(
      RUNTIME_EVENT_MESSAGE, message, static_cast<uint8_t>(messageType));
}

inline RuntimeEventPublishResult append_console_log(const String& logMessage) {
  return append_runtime_event(RUNTIME_EVENT_CONSOLE, logMessage, NONE_MSG);
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
