#ifndef RUNTIME_HELPERS_H
#define RUNTIME_HELPERS_H

#include "Samovar.h"
#include "runtime_event_log.h"

extern portMUX_TYPE timerMux;
extern portMUX_TYPE waterPulseMux;

// ПОРЯДОК ЗАХВАТА ЗАМКОВ.
// Если задаче нужно держать два замка одновременно, брать их можно только
// сверху вниз по этому списку. Обратный порядок в двух разных задачах даёт
// взаимную блокировку: каждая держит то, чего ждёт другая, и обе стоят вечно.
// Снаружи - долгие внешние операции (обмен по UART, HTTP, файл), внутри -
// короткие копирования переменных. Проверяется tools/smoke_lock_order.py;
// таблица ниже - единственный источник правды, тест читает ранги отсюда.
//
//   LOCK_ORDER: 10  RMVK_UART        xSemaphore                   обмен по UART с регулятором РМВК
//   LOCK_ORDER: 15  AVR              xSemaphoreAVR                обмен по UART с регулятором СЕМ
//   LOCK_ORDER: 18  BLYNK            xBlynkSemaphore              обращения к библиотеке Blynk (не потокобезопасна) - самый внешний из сетевых
//   LOCK_ORDER: 20  HTTP_REQUEST     httpRequestLock              один исходящий HTTP-запрос за раз
//   LOCK_ORDER: 30  LUA_STATE        xLuaSemaphore                состояние интерпретатора Lua
//   LOCK_ORDER: 40  MQTT             xMqttSemaphore               публикация в MQTT
//   LOCK_ORDER: 50  LOG_FILE         xLogFileSemaphore            файл журнала на ФС
//   LOCK_ORDER: 60  PENDING_COMMAND  xPendingCommandSemaphore     очередь отложенных команд
//   LOCK_ORDER: 70  CMD_QUEUE        samovar_command_queue_mutex  очередь команд самовара
//   LOCK_ORDER: 80  I2C              xI2CSemaphore                шина I2C
//   LOCK_ORDER: 90  MSG              xMsgSemaphore                отправка сообщений
//   LOCK_ORDER: 100 RUNTIME_STATE    xRuntimeStateSemaphore       копирование переменных состояния
//
// Известные вложенности (все идут сверху вниз, порядок соблюдён):
//   LOG_FILE > PENDING_COMMAND  - FS.ino, create_data_log()
//   LUA_STATE > RUNTIME_STATE   - lua.h, load_lua_script()/do_lua_script()
//   AVR > RUNTIME_STATE         - power_regulator_sem.h, triggerPowerStatus()

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

// RAII-страж замка отложенных команд: берёт замок в конструкторе, отдаёт в
// деструкторе. Нужен, чтобы ни один ранний return не мог оставить замок
// захваченным. release() - для мест, где под замком только снимают данные, а
// долгую работу (SendMsg, ответ HTTP, обращение к железу) делают уже без него.
struct PendingCommandLockGuard {
  bool acquired;

  explicit PendingCommandLockGuard(TickType_t timeout = pdMS_TO_TICKS(50))
      : acquired(pending_command_lock(timeout)) {}
  ~PendingCommandLockGuard() { pending_command_unlock(acquired); }

  PendingCommandLockGuard(const PendingCommandLockGuard&) = delete;
  PendingCommandLockGuard& operator=(const PendingCommandLockGuard&) = delete;

  void release() {
    pending_command_unlock(acquired);
    acquired = false;
  }

  explicit operator bool() const { return acquired; }
};

#ifdef SAMOVAR_USE_BLYNK
inline bool blynk_lock(TickType_t timeout) {
  return xBlynkSemaphore && xSemaphoreTake(xBlynkSemaphore, timeout) == pdTRUE;
}

inline void blynk_unlock(bool locked) {
  if (locked) xSemaphoreGive(xBlynkSemaphore);
}

// RAII-страж замка Blynk: библиотека Blynk не потокобезопасна, а её дёргают из
// tick_blynk() (loop(), core 1) и из задачи GetClockTicker. Таймаут задаётся явно
// на каждом месте вызова (в loop() короткий - не взяли лок, пропускаем такт; в
// GetClockTicker длиннее). Обработчики BLYNK_WRITE/BLYNK_READ в Blynk.ino вызываются
// изнутри Blynk.run(), то есть уже под этим локом - брать его повторно там не нужно
// (и нельзя: мьютекс нерекурсивный).
struct BlynkLockGuard {
  bool acquired;

  explicit BlynkLockGuard(TickType_t timeout)
      : acquired(blynk_lock(timeout)) {}
  ~BlynkLockGuard() { blynk_unlock(acquired); }

  BlynkLockGuard(const BlynkLockGuard&) = delete;
  BlynkLockGuard& operator=(const BlynkLockGuard&) = delete;

  explicit operator bool() const { return acquired; }
};
#endif

bool mode_switch_in_progress();

template <typename T>
inline bool queue_pending_value(volatile bool& flag, volatile T& valueSlot, T value) {
  if (mode_switch_in_progress()) return false;
  PendingCommandLockGuard guard;
  if (!guard) return false;
  if (mode_switch_in_progress() || flag) return false;
  valueSlot = value;
  __sync_synchronize();
  flag = true;
  return true;
}

template <typename T>
inline bool take_pending_value(volatile bool& flag, volatile T& valueSlot, T& out) {
  PendingCommandLockGuard guard;
  bool has = false;
  if (guard && flag) {
    out = valueSlot;
    flag = false;
    has = true;
  }
  return has;
}

inline bool take_pending_flag(volatile bool& flag) {
  PendingCommandLockGuard guard;
  bool has = false;
  if (guard && flag) {
    flag = false;
    has = true;
  }
  return has;
}

template <typename T>
inline bool assign_locked_runtime_field(T& destination, const T& value, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  destination = value;
  runtime_state_unlock(true);
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

inline bool set_program_wait_type(ProgramWaitType waitType, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = runtime_state_lock(timeout);
  if (!locked) return false;
  program_Wait_Type = waitType;
  runtime_state_unlock(true);
  return true;
}

inline bool copy_session_description(String& description, TickType_t timeout = pdMS_TO_TICKS(50)) {
  return assign_locked_runtime_field(description, SessionDescription, timeout);
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
  return assign_locked_runtime_field(Lua_status, status, timeout);
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
  return assign_locked_runtime_field(mode, current_power_mode, timeout);
}

inline String get_current_power_mode_value() {
  String mode;
  if (!copy_current_power_mode_value(mode)) return String();
  return mode;
}

inline bool current_power_mode_is(const String& mode) {
  return get_current_power_mode_value() == mode;
}

// [T14 п.29] Возвращает признак успеха: занятый лок -> false. Это не отказ
// регулятора (железо к этому моменту уже приняло команду) - вызывающий из
// power_regulator_*.h взводит отложенный повтор записи через
// arm_pending_power_mode_retry() вместо эскалации в fail-close.
inline bool set_current_power_mode_value(const String& mode) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(500));
  if (!locked) return false;
  current_power_mode = mode;
  runtime_state_unlock(true);
  return true;
}

// [T14 п.29] Отложенный повтор записи кэша режима регулятора. Замок runtime-
// состояния в set_current_power_mode_value() занят максимум 500 мс - при
// проигрыше гонки значение раньше терялось молча и уводило кэш в рассинхрон
// с реальным состоянием регулятора. Теперь неудачную запись повторяет
// process_pending_power_request() (power_regulator.h).
// SAFETY_REGULATOR_MODE_SLEEP == 0 - валидное значение режима, поэтому
// "заявки нет" кодируется отдельным флагом, а не значением 0.
// Однопоточный доступ без лока: пишет apply_regulator_mode_blocking(), читает
// и снимает только process_pending_power_request() - обе стороны выполняются
// последовательно в одной задаче регулятора (см. LOCK_ORDER выше - здесь его
// нет намеренно, конкурентного доступа не бывает).
static SafetyRegulatorMode pendingPowerModeRetryValue = SAFETY_REGULATOR_MODE_SLEEP;
static bool pendingPowerModeRetryArmed = false;

inline void arm_pending_power_mode_retry(SafetyRegulatorMode mode) {
  pendingPowerModeRetryValue = mode;
  pendingPowerModeRetryArmed = true;
}

inline bool pending_power_mode_retry_armed() {
  return pendingPowerModeRetryArmed;
}

inline SafetyRegulatorMode pending_power_mode_retry_value() {
  return pendingPowerModeRetryValue;
}

inline void clear_pending_power_mode_retry() {
  pendingPowerModeRetryArmed = false;
}

// [T14 п.1] Нижняя граница - порог WORK↔SLEEP: ниже него set_current_power()
// бесшумно схлопывает мощность в SLEEP (target_power_volt = 0).
inline float reduce_power_by_volts(float power, float volts) {
  float reduced = power - volts * PWR_FACTOR;
  if (reduced < power_work_mode_threshold()) reduced = power_work_mode_threshold();
  return reduced;
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

// Меняет физическую полярность вывода DIR (не трогает позицию/цель) - используется
// для передачи направления в локальный (без I2C-платы) путь set_stepper_target().
inline void stepper_safe_reverse(bool val) {
  portENTER_CRITICAL(&timerMux);
  stepper.reverse(val);
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
