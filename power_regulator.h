#pragma once

#include <Arduino.h>
#include "driver/uart.h"
#include "hal/uart_ll.h"
#include "Samovar.h"
#include "samovar_api.h"
#include "power_regulator_numeric_input.h"
#include "runtime_helpers.h"
#include "safety_transition.h"

struct PowerTransitionState {
  SafetyTransition transition;
  bool enqueueResetCommand;
  bool pendingPowerValueSet;
  float pendingPowerValue;
  uint64_t regulatorGeneration;
};

static PowerTransitionState powerTransition = {
  {SAFETY_TRANSITION_IDLE, 0},
  false,
  false,
  0,
  0,
};

static SafetyHeaterBarrierState heaterSafetyState = {false, false, false, 0};
static SafetyRegulatorRequestState regulatorRequestState = {};

#ifdef SAMOVAR_USE_SEM_AVR
static constexpr uint32_t POWER_REGULATOR_REQUEST_TIMEOUT_MS = 10000;
#else
static constexpr uint32_t POWER_REGULATOR_REQUEST_TIMEOUT_MS = 5000;
#endif
static constexpr TickType_t POWER_UART_TX_READY_TIMEOUT = pdMS_TO_TICKS(50);
static constexpr size_t POWER_UART_COMMAND_MAX = 32;

// Порог перехода WORK↔SLEEP: заданная мощность/напряжение ниже него → SLEEP.
// SEM_AVR оперирует ваттами (100), KVIC/RMVK — вольтами (40).
#ifdef SAMOVAR_USE_SEM_AVR
static constexpr float POWER_WORK_MODE_THRESHOLD = 100.0f;
#else
static constexpr float POWER_WORK_MODE_THRESHOLD = 40.0f;
#endif

#ifdef SAMOVAR_USE_POWER
static bool powerWorkerReady = false;
#endif

inline void notify_power_worker() {
#ifdef SAMOVAR_USE_POWER
  if (PowerStatusTask != nullptr) xTaskNotifyGive(PowerStatusTask);
#endif
}

inline bool power_transition_phase_is_off(SafetyTransitionPhase phase) {
  return phase == POWER_TRANSITION_OFF_REGULATOR_WAIT ||
         phase == POWER_TRANSITION_OFF_RESET_WAIT;
}

inline bool power_transition_start_pending_locked() {
  return powerTransition.transition.phase == POWER_TRANSITION_ON_SEM_WAIT ||
         powerTransition.transition.phase == POWER_TRANSITION_ON_REGULATOR_WAIT;
}

inline bool heater_outputs_enable_locked(uint8_t outputs, bool setPowerOn) {
  if (mode_switch_barrier_active) return false;
  if (!safety_heater_enable(heaterSafetyState, setPowerOn)) return false;
  PowerOn = heaterSafetyState.powerOn;
  if (outputs & SAFETY_HEATER_OUTPUT_MAIN) {
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
  }
  if (outputs & SAFETY_HEATER_OUTPUT_BOOST) {
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
  }
  return true;
}

inline uint64_t request_regulator_state_locked(
  SafetyRegulatorMode mode,
  bool hasVoltage,
  float voltage,
  bool force
) {
#ifndef SAMOVAR_USE_POWER
  // Релейная конфигурация без UART-регулятора: запросная машинерия не нужна.
  // Постановка запроса привела бы к ложному ALARM «Таймаут команды регулятора»
  // на каждой аварии (воркера, который их применяет, нет).
  (void)mode; (void)hasVoltage; (void)voltage; (void)force;
  return 0;
#else
  if (mode != SAFETY_REGULATOR_MODE_SLEEP &&
      (heaterSafetyState.emergencyLatched || mode_switch_barrier_active || !PowerOn)) return 0;
  return safety_regulator_request(
    regulatorRequestState,
    mode,
    hasVoltage,
    voltage,
    heaterSafetyState.generation,
    safety_deadline_after(millis(), POWER_REGULATOR_REQUEST_TIMEOUT_MS),
    force
  );
#endif
}

inline int heater_uart_tx_chars(void* context, const char* data, size_t length) {
  const uart_port_t port = *static_cast<const uart_port_t*>(context);
  // Регистровая запись в TX FIFO вместо uart_tx_chars(): последний берёт FreeRTOS
  // tx_mux с portMAX_DELAY — блокирующий вызов недопустим внутри
  // portENTER_CRITICAL(&emergencyStopMux) (прерывания выключены → риск
  // interrupt-watchdog). Место в FIFO гарантировано: heater_uart_enqueue() вызывает
  // uart_wait_tx_done() (опустошение FIFO) ДО входа в секцию, команда
  // ≤ POWER_UART_COMMAND_MAX (32) < SOC_UART_FIFO_LEN (128), единственный писатель —
  // PowerStatusTask. Epoch-барьер (safety_uart_commit_locked) отрабатывает ДО этого.
  uart_ll_write_txfifo(UART_LL_GET_HW(port), reinterpret_cast<const uint8_t*>(data), length);
  return static_cast<int>(length);
}

inline bool heater_uart_enqueue(
  uart_port_t port,
  const char* data,
  size_t length,
  uint64_t powerGeneration,
  bool energizing
) {
  if (length == 0 || length > POWER_UART_COMMAND_MAX) return false;
  if (uart_wait_tx_done(port, POWER_UART_TX_READY_TIMEOUT) != ESP_OK) return false;
  portENTER_CRITICAL(&emergencyStopMux);
  const bool queued = safety_uart_commit_locked(
    heaterSafetyState,
    powerGeneration,
    energizing,
    data,
    length,
    heater_uart_tx_chars,
    &port
  );
  portEXIT_CRITICAL(&emergencyStopMux);
  return queued;
}

inline void set_power_worker_ready(bool ready) {
#ifdef SAMOVAR_USE_POWER
  portENTER_CRITICAL(&emergencyStopMux);
  powerWorkerReady = ready;
  portEXIT_CRITICAL(&emergencyStopMux);
#else
  (void)ready;
#endif
}

inline void apply_heater_outputs_off_locked() {
  digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
  PowerOn = false;
  acceleration_heater = false;
  target_power_volt = 0;
  current_power_volt = 0;
#ifdef SAMOVAR_USE_POWER
  current_power_p = 0;
#endif
  powerTransition.pendingPowerValueSet = false;
  powerTransition.regulatorGeneration = 0;
}

inline void force_heater_output_off_locked(bool requestSleep) {
  safety_heater_force_off(heaterSafetyState);
  apply_heater_outputs_off_locked();
  safety_regulator_invalidate_energizing(regulatorRequestState);
  if (power_transition_start_pending_locked()) safety_transition_cancel(powerTransition.transition);
  if (requestSleep) {
    request_regulator_state_locked(SAFETY_REGULATOR_MODE_SLEEP, false, 0, true);
  }
}

inline bool emergency_trip_heater_outputs_locked() {
  const bool firstRequest = safety_heater_emergency_trip(heaterSafetyState);
  alarm_event = true;
  apply_heater_outputs_off_locked();
  safety_transition_cancel(powerTransition.transition);
  request_regulator_state_locked(SAFETY_REGULATOR_MODE_SLEEP, false, 0, firstRequest);
  return firstRequest;
}

inline bool heater_safety_latched() {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool latched = heaterSafetyState.emergencyLatched;
  portEXIT_CRITICAL(&emergencyStopMux);
  return latched;
}

inline bool heater_power_on() {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool powerOn = heaterSafetyState.powerOn;
  portEXIT_CRITICAL(&emergencyStopMux);
  return powerOn;
}

inline bool heater_enable_outputs(uint8_t outputs) {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool enabled = heater_outputs_enable_locked(outputs, false);
  portEXIT_CRITICAL(&emergencyStopMux);
  return enabled;
}

inline bool power_transition_start_pending() {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool pending = power_transition_start_pending_locked();
  portEXIT_CRITICAL(&emergencyStopMux);
  return pending;
}

inline bool power_transition_active() {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool active = safety_transition_active(powerTransition.transition);
  portEXIT_CRITICAL(&emergencyStopMux);
  return active;
}

inline bool safety_owner_generation_acquire(uint64_t& generation) {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool allowed = !heaterSafetyState.emergencyLatched &&
                       !mode_switch_barrier_active &&
                       !heaterSafetyState.powerOn &&
                       !safety_transition_active(powerTransition.transition) &&
                       safety_heater_owner_acquire(heaterSafetyState, generation);
  if (!allowed) generation = 0;
  portEXIT_CRITICAL(&emergencyStopMux);
  return allowed;
}

inline bool safety_owner_generation_valid(uint64_t generation) {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool allowed = safety_heater_owner_valid(heaterSafetyState, generation) &&
                       !mode_switch_barrier_active &&
                       !safety_transition_active(powerTransition.transition);
  portEXIT_CRITICAL(&emergencyStopMux);
  return allowed;
}

inline void safety_owner_generation_release(uint64_t generation) {
  portENTER_CRITICAL(&emergencyStopMux);
  safety_heater_owner_release(heaterSafetyState, generation);
  portEXIT_CRITICAL(&emergencyStopMux);
}

inline void finish_power_off_transition(bool enqueueResetCommand) {
  if (enqueueResetCommand && mode_switch_in_progress()) return;
  if (enqueueResetCommand && !queue_samovar_reset_command()) {
    SendMsg("Очередь команд занята: reset после выключения нагрева не поставлен", WARNING_MSG);
  }
}

inline void fail_close_regulator_locked(uint32_t now, bool enqueueResetCommand) {
  force_heater_output_off_locked(true);
  if (enqueueResetCommand) powerTransition.enqueueResetCommand = true;
  safety_transition_advance(
    powerTransition.transition,
    POWER_TRANSITION_OFF_REGULATOR_WAIT,
    now
  );
}

inline void terminate_sleep_fault_locked(uint32_t now) {
  force_heater_output_off_locked(false);
  safety_transition_advance(
    powerTransition.transition,
    POWER_TRANSITION_OFF_RESET_WAIT,
    safety_deadline_after(now, 200)
  );
}

inline void set_power(bool On, bool enqueueResetCommand) {
  if (On) {
    bool started = false;
    bool workerReady = true;
    bool blockedEmergency = false;
    bool blockedOffTransition = false;
    bool blockedExclusiveOwner = false;
    bool blockedModeSwitch = false;
#ifndef SAMOVAR_USE_POWER
    bool updatePowerMode = false;
#endif
    portENTER_CRITICAL(&emergencyStopMux);
#ifdef SAMOVAR_USE_POWER
    workerReady = powerWorkerReady && PowerStatusTask != nullptr;
#endif
    blockedEmergency = heaterSafetyState.emergencyLatched;
    blockedOffTransition = power_transition_phase_is_off(powerTransition.transition.phase);
    blockedExclusiveOwner = heaterSafetyState.exclusiveOwnerActive;
    blockedModeSwitch = mode_switch_barrier_active;
    if (workerReady && !heaterSafetyState.emergencyLatched &&
        !heaterSafetyState.exclusiveOwnerActive && !mode_switch_barrier_active && !PowerOn &&
        !power_transition_start_pending_locked() &&
        !power_transition_phase_is_off(powerTransition.transition.phase)) {
      if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) reset_heat_loss_calculation();
      started = heater_outputs_enable_locked(SAFETY_HEATER_OUTPUT_MAIN, true);
      if (started) {
        reg_online = false;
        last_reg_online = millis();
        powerTransition.pendingPowerValueSet = false;
        powerTransition.regulatorGeneration = 0;

#ifdef SAMOVAR_USE_SEM_AVR
        safety_transition_begin(
          powerTransition.transition,
          POWER_TRANSITION_ON_SEM_WAIT,
          safety_deadline_after(millis(), 3000)
        );
#elif defined(SAMOVAR_USE_POWER)
        safety_transition_begin(
          powerTransition.transition,
          POWER_TRANSITION_ON_REGULATOR_WAIT,
          safety_deadline_after(millis(), SAMOVAR_USE_POWER_START_TIME)
        );
#else
        heater_outputs_enable_locked(SAFETY_HEATER_OUTPUT_BOOST, false);
        updatePowerMode = true;
#endif
      }
    }
    portEXIT_CRITICAL(&emergencyStopMux);
    if (!started) {
      // Причина отказа — конкретным сообщением (раньше отказ был молчаливым).
      // alreadyOn / start_pending — идемпотентные ветки, не сообщаем.
      if (!workerReady) SendMsg("Нагрев отклонён: задача регулятора не запущена", ALARM_MSG);
      else if (blockedEmergency) SendMsg("Нагрев заблокирован аварийной защитой, требуется перезагрузка", ALARM_MSG);
      else if (blockedOffTransition) SendMsg("Нагрев отклонён: выполняется выключение нагрева, повторите позже", WARNING_MSG);
      else if (blockedExclusiveOwner) SendMsg("Нагрев отклонён: активна эксклюзивная операция (самотест/калибровка)", WARNING_MSG);
      else if (blockedModeSwitch) SendMsg("Нагрев отклонён: идёт переключение режима", WARNING_MSG);
      return;
    }
#ifndef SAMOVAR_USE_POWER
    if (updatePowerMode) set_current_power_mode_value(POWER_SPEED_MODE);
#endif
    set_menu_screen(2);
    power_text_ptr = (char *)"OFF";
    return;
  }

  bool finishImmediately = false;
  bool finishEnqueueReset = false;
#ifndef SAMOVAR_USE_POWER
  bool updatePowerMode = false;
#endif
  portENTER_CRITICAL(&emergencyStopMux);
  force_heater_output_off_locked(false);
  if (power_transition_phase_is_off(powerTransition.transition.phase)) {
    if (enqueueResetCommand) powerTransition.enqueueResetCommand = true;
  } else {
    powerTransition.enqueueResetCommand = enqueueResetCommand;
#ifdef SAMOVAR_USE_POWER
    safety_transition_begin(
      powerTransition.transition,
      POWER_TRANSITION_OFF_REGULATOR_WAIT,
      safety_deadline_after(millis(), 700)
    );
#else
    power_text_ptr = (char *)"ON";
    reg_online = false;
    last_reg_online = 0;
    updatePowerMode = true;
    finishImmediately = true;
    finishEnqueueReset = powerTransition.enqueueResetCommand;
    powerTransition.enqueueResetCommand = false;
#endif
  }
  portEXIT_CRITICAL(&emergencyStopMux);

#ifndef SAMOVAR_USE_POWER
  if (updatePowerMode) set_current_power_mode_value(POWER_SLEEP_MODE);
#endif
  if (finishImmediately) finish_power_off_transition(finishEnqueueReset);
}

inline void tick_power_transition() {
  const uint32_t now = millis();
  bool finishOff = false;
  bool finishEnqueueReset = false;
  bool reportApplyFailure = false;
  bool reportSuperseded = false;
  bool reportTimeout = false;
  bool notifyWorker = false;

  portENTER_CRITICAL(&emergencyStopMux);
#ifdef SAMOVAR_USE_POWER
  const uint64_t desiredGeneration = regulatorRequestState.desiredGeneration;
  const SafetyRegulatorMode desiredMode = regulatorRequestState.desiredMode;
  if (desiredGeneration != 0 &&
      safety_regulator_expire_request(regulatorRequestState, desiredGeneration, now)) {
    reportTimeout = true;
    if (heaterSafetyState.powerOn) {
      if (desiredMode == SAFETY_REGULATOR_MODE_SLEEP) {
        terminate_sleep_fault_locked(now);
      } else {
        fail_close_regulator_locked(now, true);
        notifyWorker = true;
      }
    }
  }
#endif
  const SafetyTransitionPhase phase = powerTransition.transition.phase;

  if (phase == POWER_TRANSITION_ON_SEM_WAIT) {
    if (heaterSafetyState.emergencyLatched || !PowerOn) {
      safety_transition_cancel(powerTransition.transition);
    } else if (safety_transition_due(powerTransition.transition, now)) {
#ifdef SAMOVAR_USE_POWER
      safety_transition_advance(
        powerTransition.transition,
        POWER_TRANSITION_ON_REGULATOR_WAIT,
        safety_deadline_after(now, SAMOVAR_USE_POWER_START_TIME)
      );
#else
      heater_outputs_enable_locked(SAFETY_HEATER_OUTPUT_BOOST, false);
      safety_transition_cancel(powerTransition.transition);
#endif
    }
    portEXIT_CRITICAL(&emergencyStopMux);
    if (notifyWorker) notify_power_worker();
    if (reportTimeout) SendMsg("Таймаут команды регулятора; нагрев отключён", ALARM_MSG);
    return;
  }

  if (phase == POWER_TRANSITION_ON_REGULATOR_WAIT) {
    if (heaterSafetyState.emergencyLatched || !PowerOn) {
      safety_transition_cancel(powerTransition.transition);
      powerTransition.regulatorGeneration = 0;
    } else if (powerTransition.regulatorGeneration == 0) {
      if (!safety_transition_due(powerTransition.transition, now)) {
        portEXIT_CRITICAL(&emergencyStopMux);
        if (reportTimeout) SendMsg("Таймаут команды регулятора; нагрев отключён", ALARM_MSG);
        return;
      }
#ifdef SAMOVAR_USE_POWER
      powerTransition.regulatorGeneration = request_regulator_state_locked(
        SAFETY_REGULATOR_MODE_SPEED, false, 0, false
      );
      notifyWorker = powerTransition.regulatorGeneration != 0;
      powerTransition.transition.deadline = regulatorRequestState.desiredDeadline;
#else
      safety_transition_cancel(powerTransition.transition);
#endif
    } else {
#ifdef SAMOVAR_USE_POWER
      const SafetyRegulatorRequestStatus status = safety_regulator_request_status(
        regulatorRequestState, powerTransition.regulatorGeneration
      );
      if (status == SAFETY_REGULATOR_REQUEST_APPLIED) {
        if (powerTransition.pendingPowerValueSet) {
          const float pendingPower = powerTransition.pendingPowerValue;
          powerTransition.pendingPowerValueSet = false;
          const float threshold = POWER_WORK_MODE_THRESHOLD;
          powerTransition.regulatorGeneration = request_regulator_state_locked(
            pendingPower < threshold ? SAFETY_REGULATOR_MODE_SLEEP : SAFETY_REGULATOR_MODE_WORK,
            pendingPower >= threshold,
            pendingPower,
            false
          );
          notifyWorker = powerTransition.regulatorGeneration != 0;
          powerTransition.transition.deadline = regulatorRequestState.desiredDeadline;
          if (powerTransition.regulatorGeneration == 0) {
            reportApplyFailure = true;
            fail_close_regulator_locked(now, true);
            notifyWorker = true;
          }
        } else {
          powerTransition.regulatorGeneration = 0;
          safety_transition_cancel(powerTransition.transition);
        }
      } else if (status == SAFETY_REGULATOR_REQUEST_FAILED) {
        reportApplyFailure = true;
        fail_close_regulator_locked(now, true);
        notifyWorker = true;
      } else if (status == SAFETY_REGULATOR_REQUEST_TIMED_OUT) {
        reportTimeout = true;
        fail_close_regulator_locked(now, true);
        notifyWorker = true;
      } else if (status == SAFETY_REGULATOR_REQUEST_SUPERSEDED) {
        reportSuperseded = true;
        fail_close_regulator_locked(now, true);
        notifyWorker = true;
      }
#endif
    }
    portEXIT_CRITICAL(&emergencyStopMux);
    if (notifyWorker) notify_power_worker();
    if (reportApplyFailure) SendMsg("Команда запуска регулятора завершилась ошибкой", ALARM_MSG);
    if (reportTimeout) SendMsg("Таймаут команды запуска регулятора; нагрев отключён", ALARM_MSG);
    if (reportSuperseded) SendMsg("Команда запуска регулятора была явно отменена новой командой", ALARM_MSG);
    return;
  }

  if (phase == POWER_TRANSITION_OFF_REGULATOR_WAIT) {
    if (powerTransition.regulatorGeneration == 0) {
      if (!safety_transition_due(powerTransition.transition, now)) {
        portEXIT_CRITICAL(&emergencyStopMux);
        if (reportTimeout) SendMsg("Таймаут команды регулятора при выключенных реле", ALARM_MSG);
        return;
      }
#ifdef SAMOVAR_USE_POWER
      powerTransition.regulatorGeneration = request_regulator_state_locked(
        SAFETY_REGULATOR_MODE_SLEEP, false, 0, false
      );
      notifyWorker = powerTransition.regulatorGeneration != 0;
      powerTransition.transition.deadline = regulatorRequestState.desiredDeadline;
#else
      safety_transition_advance(
        powerTransition.transition,
        POWER_TRANSITION_OFF_RESET_WAIT,
        safety_deadline_after(now, 200)
      );
#endif
    } else {
#ifdef SAMOVAR_USE_POWER
      const SafetyRegulatorRequestStatus status = safety_regulator_request_status(
        regulatorRequestState, powerTransition.regulatorGeneration
      );
      if (status == SAFETY_REGULATOR_REQUEST_APPLIED ||
          status == SAFETY_REGULATOR_REQUEST_FAILED ||
          status == SAFETY_REGULATOR_REQUEST_TIMED_OUT ||
          status == SAFETY_REGULATOR_REQUEST_SUPERSEDED) {
        reportApplyFailure = status == SAFETY_REGULATOR_REQUEST_FAILED;
        reportTimeout = status == SAFETY_REGULATOR_REQUEST_TIMED_OUT;
        reportSuperseded = status == SAFETY_REGULATOR_REQUEST_SUPERSEDED;
        powerTransition.regulatorGeneration = 0;
        safety_transition_advance(
          powerTransition.transition,
          POWER_TRANSITION_OFF_RESET_WAIT,
          safety_deadline_after(now, 200)
        );
      }
#endif
    }
    portEXIT_CRITICAL(&emergencyStopMux);
    if (notifyWorker) notify_power_worker();
    if (reportApplyFailure) SendMsg("Команда выключения регулятора завершилась ошибкой", ALARM_MSG);
    if (reportTimeout) SendMsg("Таймаут команды выключения регулятора при снятых локальных реле", ALARM_MSG);
    if (reportSuperseded) SendMsg("Команда выключения регулятора была явно отменена новой командой", ALARM_MSG);
    return;
  }

  if (phase == POWER_TRANSITION_OFF_RESET_WAIT && safety_transition_due(powerTransition.transition, now)) {
    safety_transition_cancel(powerTransition.transition);
    power_text_ptr = (char *)"ON";
    reg_online = false;
    last_reg_online = 0;
    finishOff = true;
    finishEnqueueReset = powerTransition.enqueueResetCommand;
    powerTransition.enqueueResetCommand = false;
  }
  portEXIT_CRITICAL(&emergencyStopMux);
  if (notifyWorker) notify_power_worker();
  if (reportTimeout) SendMsg("Таймаут команды регулятора при снятых локальных реле", ALARM_MSG);
  if (finishOff) finish_power_off_transition(finishEnqueueReset);
}

//////////////////////////////////////////////////////////////////////////////////////////////////////////////
// SAMOVAR_USE_POWER
//////////////////////////////////////////////////////////////////////////////////////////////////////////////
#ifdef SAMOVAR_USE_POWER

void clear_serial_in_buff() { // Быстрая очистка буфера (максимум 100 символов)
  uint8_t cleared = 0;
  while (Serial2.available() && cleared < 100) {
      Serial2.read();
      cleared++;
  }
}

#ifdef SAMOVAR_USE_SEM_AVR
static constexpr const char* SEM_AVR_SAMOVAR_AT_PREFIX = "\xD0\x90\xD0\xA2";

static inline void sem_avr_print_samovar_command(const char* suffix) {
  // SEM_AVR distinguishes Samovar power commands from RMVK voltage commands by
  // the legacy UTF-8 Cyrillic A/T prefix bytes. Keep the bytes explicit.
  Serial2.print(SEM_AVR_SAMOVAR_AT_PREFIX);
  Serial2.print(suffix);
}

static inline bool sem_avr_write_samovar_command(
  const char* suffix,
  uint64_t powerGeneration,
  bool energizing
) {
  char command[POWER_UART_COMMAND_MAX];
  const int length = snprintf(
    command,
    sizeof(command),
    "%s%s",
    SEM_AVR_SAMOVAR_AT_PREFIX,
    suffix
  );
  return length > 0 && (size_t)length < sizeof(command) &&
         heater_uart_enqueue(
           UART_NUM_2,
           command,
           (size_t)length,
           powerGeneration,
           energizing
         );
}
#endif

static constexpr uint32_t POWER_RESPONSE_ERROR_INTERVAL_MS = 5000;

static inline void report_power_response_error(
    const char* responseName,
    NumericParseResult result) {
  // Раздельный rate-limit по типу ответа: ошибка одного типа (KVIC / +SS? / +VO? /
  // +VS?) не должна глушить репорт другого на POWER_RESPONSE_ERROR_INTERVAL_MS.
  static const char* names[4] = {nullptr, nullptr, nullptr, nullptr};
  static uint32_t lastReport[4] = {0, 0, 0, 0};
  const uint32_t now = millis();
  int slot = -1;
  for (int i = 0; i < 4; i++) {
    if (names[i] != nullptr && strcmp(names[i], responseName) == 0) { slot = i; break; }
  }
  if (slot < 0) {
    for (int i = 0; i < 4; i++) {
      if (names[i] == nullptr) { names[i] = responseName; slot = i; break; }
    }
  }
  if (slot < 0) slot = 0;  // типов ≤ 4; страховка от переполнения таблицы
  if (lastReport[slot] != 0 && now - lastReport[slot] < POWER_RESPONSE_ERROR_INTERVAL_MS) return;
  lastReport[slot] = now;
  String message = "Invalid power response ";
  message += responseName;
  message += ": ";
  message += numeric_parse_error_code(result.error);
  SendMsg(message, WARNING_MSG);
}

static inline void mark_power_regulator_online() {
  reg_online = true;
  last_reg_online = millis();
}

static inline void commit_kvic_power_response(const PowerRegulatorTelemetry& parsed) {
  // Ток валиден по факту разбора пакета; target/mode применяем только если валидны
  // (best-effort). reg_online держим по факту получения пакета.
  current_power_volt = parsed.currentValue;
  if (parsed.hasTarget) target_power_volt = parsed.targetValue;
  if (parsed.hasMode) set_current_power_mode_value(String(parsed.mode));
  mark_power_regulator_online();
}

static inline void commit_sem_power_mode_response(char mode) {
  set_current_power_mode_value(String(mode));
  mark_power_regulator_online();
}

static inline void commit_sem_current_power_response(uint16_t value) {
  current_power_volt = value;
  mark_power_regulator_online();
}

static inline void commit_sem_target_power_response(uint16_t value) {
  // Транзиентный «0» от +VS? игнорируем (HEAD-семантика): не обнуляем уставку,
  // но связь считаем живой.
  if (value != 0) target_power_volt = value;
  mark_power_regulator_online();
}

#ifndef SAMOVAR_USE_RMVK
void triggerPowerStatus(void *parameter) {
  static String buffer;
  const uint16_t MAX_BUFFER_SIZE = 50; // Ограничение размера буфера (5 пакетов по 9 символов + запас)
  while (true) {
    process_pending_power_request();
    ulTaskNotifyTake(pdTRUE, 500 / portTICK_PERIOD_MS);
    buffer = "";
    uint16_t readCount = 0;
    // Читаем данные с ограничением размера буфера
    while (Serial2.available() && readCount < MAX_BUFFER_SIZE) {
        char c = Serial2.read();
        buffer += c;
        readCount++;
    }
    // Если накопилось больше лимита - оставляем только последние символы
    if (buffer.length() > MAX_BUFFER_SIZE) {
        buffer = buffer.substring(buffer.length() - MAX_BUFFER_SIZE);
    }

    // Если в буфере есть данные
    if (buffer.length() >= 9) { // Минимум 9 символов для полного пакета (T1234567\r)
        // Находим все позиции \r в буфере
        int crPositions[5]; // Массив для позиций \r (максимум 5 пакетов)
        int crCount = 0;
        for (int i = 0; i < buffer.length() && crCount < 5; i++) {
            if (buffer.charAt(i) == '\r') {
                crPositions[crCount] = i;
                crCount++;
            }
        }

        // Проверяем пакеты от последнего к первому
        bool packetFound = false;
        for (int i = crCount - 1; i >= 0 && !packetFound; i--) {
            int crPos = crPositions[i];
            // Проверяем, что перед \r есть минимум 8 символов
            if (crPos >= 8) {
                // Берем 8 символов перед \r (формат T1234567)
                String data = buffer.substring(crPos - 8, crPos);

                PowerRegulatorTelemetry parsed = {};
                NumericParseResult result = parse_kvic_power_response(data.c_str(), parsed);
                if (result.ok()) {
                    commit_kvic_power_response(parsed);
                    packetFound = true;
#ifdef __SAMOVAR_DEBUG
                    Serial.println("KVIC: " + data);
#endif
                } else {
                    report_power_response_error("KVIC", result);
                }
            }
        }
    }
    // Если давно не было ответа от регулятора — считаем его оффлайн.
    // Таймаут с запасом, т.к. запросы идут пачкой и с задержками.
    if (reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 15000UL) {
      reg_online = false;
    }
  }
}
#else
void triggerPowerStatus(void *parameter) {
  String resp;
  while (true) {
    process_pending_power_request();
    if (PowerOn) {
#ifdef SAMOVAR_USE_SEM_AVR
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        clear_serial_in_buff();
        vTaskDelay(5 / portTICK_RATE_MS);
        sem_avr_print_samovar_command("+SS?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            resp = Serial2.readStringUntil('\r');
            char mode = '\0';
            NumericParseResult result = parse_sem_power_mode_response(resp.c_str(), mode);
            if (result.ok()) commit_sem_power_mode_response(mode);
            else report_power_response_error("SEM +SS?", result);
#ifdef __SAMOVAR_DEBUG
            if (result.ok()) WriteConsoleLog("CPM=" + get_current_power_mode_value());
#endif
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        clear_serial_in_buff();
        vTaskDelay(5 / portTICK_RATE_MS);
        sem_avr_print_samovar_command("+VO?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            resp = Serial2.readStringUntil('\r');
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("CPV=" + resp);
#endif
            uint16_t value = 0;
            NumericParseResult result = parse_sem_power_value_response(
                resp.c_str(), SamSetup.HeaterResistant, value, /*telemetry=*/true);
            if (result.ok()) commit_sem_current_power_response(value);
            else report_power_response_error("SEM +VO?", result);
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        clear_serial_in_buff();
        vTaskDelay(5 / portTICK_RATE_MS);
        sem_avr_print_samovar_command("+VS?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            resp = Serial2.readStringUntil('\r');
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("TPV=" + resp);
#endif
            uint16_t value = 0;
            NumericParseResult result = parse_sem_power_value_response(
                resp.c_str(), SamSetup.HeaterResistant, value, /*telemetry=*/true);
            if (result.ok()) commit_sem_target_power_response(value);
            else report_power_response_error("SEM +VS?", result);
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
#else
      current_power_volt = RMVK_get_out_voltge();
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      uint16_t v = RMVK_get_store_out_voltge();
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      rmvk.on = RMVK_get_state() > 0;
      if (v != 0) {
        target_power_volt = v;
      }
#endif
    }
    // Если давно не было ответа от регулятора — считаем его оффлайн.
    // Таймаут с запасом, т.к. запросы идут пачкой и с задержками.
    if (reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 5000UL) {
      reg_online = false;
    }
    ulTaskNotifyTake(pdTRUE, RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
  }
}
#endif

void check_power_error() {
#ifndef __SAMOVAR_DEBUG
  if (SamSetup.CheckPower && PowerOn) {
    // 1) Потеря связи с регулятором: отключаем нагрев при длительном отсутствии ответа.
    // [L-10] Аварийный таймаут здесь — 15000 мс.
    // В triggerPowerStatus() reg_online сбрасывается с разными таймаутами намеренно:
    //   Serial2-ветка (#ifndef SAMOVAR_USE_RMVK): 15000 мс (пакеты идут пассивно, нужен запас);
    //   RMVK-ветка   (#else):                      5000 мс (опрос активный, детект быстрее).
    // Таймаут здесь (15000 мс) выставлен с запасом поверх обоих значений.
    if (!reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 15000UL && !current_power_mode_is(POWER_SLEEP_MODE)) {
      power_err_cnt++;
      if (power_err_cnt == 2) {
        SendMsg(("Нет связи с регулятором!"), ALARM_MSG);
      }
      if (power_err_cnt > 6) {
        request_emergency_stop("Аварийное отключение! Нет связи с регулятором нагрева.");
      }
      return;
    }

    // 2) Проверим, что заданное напряжение/мощность не сильно отличается от реального
    // (наличие связи с регулятором, пробой семистора и т.п.)
    if (current_power_mode_is(POWER_WORK_MODE) && current_power_volt > 0 && target_power_volt > 0 &&
        abs((current_power_volt - target_power_volt) / target_power_volt) > 0.2f) {
      power_err_cnt++;
      //if (power_err_cnt == 2) SendMsg(("Ошибка регулятора!"), ALARM_MSG);
      if (power_err_cnt > 6) set_current_power(target_power_volt);
      if (power_err_cnt > 12) {
        request_emergency_stop("Аварийное отключение! Ошибка управления нагревателем.");
      }
      return;
    }
  }
#endif
  power_err_cnt = 0;
}


//получаем текущие параметры работы регулятора напряжения
void get_current_power() {
  if (!PowerOn) {
    current_power_volt = 0;
    target_power_volt = 0;
    set_current_power_mode_value("N");
    current_power_p = 0;
    return;
  }
  if (current_power_mode_is(POWER_SLEEP_MODE)) {
    current_power_volt = 0;
    target_power_volt = 0;
    current_power_p = 0;
    return;
  }
#ifndef SAMOVAR_USE_SEM_AVR
  //Считаем мощность V*V*K/R, K = 0,98~1
  current_power_p = current_power_volt * current_power_volt /
                    trusted_heater_resistance(SamSetup.HeaterResistant);
#else
  current_power_p = target_power_volt;
#endif
}

inline bool regulator_mode_from_string(const String& modeText, SafetyRegulatorMode& mode) {
  if (modeText == POWER_SLEEP_MODE) {
    mode = SAFETY_REGULATOR_MODE_SLEEP;
    return true;
  }
  if (modeText == POWER_SPEED_MODE) {
    mode = SAFETY_REGULATOR_MODE_SPEED;
    return true;
  }
  if (modeText == POWER_WORK_MODE) {
    mode = SAFETY_REGULATOR_MODE_WORK;
    return true;
  }
  return false;
}

inline String regulator_mode_text(SafetyRegulatorMode mode) {
  switch (mode) {
    case SAFETY_REGULATOR_MODE_SLEEP: return String(POWER_SLEEP_MODE);
    case SAFETY_REGULATOR_MODE_SPEED: return String(POWER_SPEED_MODE);
    case SAFETY_REGULATOR_MODE_WORK: return String(POWER_WORK_MODE);
  }
  return String();
}

inline bool apply_regulator_voltage_blocking(float Volt, uint64_t powerGeneration) {
#ifdef __SAMOVAR_DEBUG
  WriteConsoleLog("Set current power =" + (String)Volt);
#endif
  vTaskDelay(100 / portTICK_PERIOD_MS);
#ifdef SAMOVAR_USE_RMVK
#ifndef SAMOVAR_USE_SEM_AVR
  if (RMVK_set_out_voltge(Volt, powerGeneration) == RMVK_ERROR) return false;
#else
  if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
    String Cmd;
    int V = Volt;
    if (V < 100) Cmd = "0";
    else
      Cmd = "";
    Cmd = Cmd + (String)V;
    vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
    const bool queued = sem_avr_write_samovar_command(
      (String("+VS=") + Cmd + "\r").c_str(),
      powerGeneration,
      true
    );
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
    xSemaphoreGive(xSemaphoreAVR);
    if (!queued) return false;
  } else return false;
#endif
#else
  String hexString = String((int)(Volt * 10), HEX);
  const String command = "S" + hexString + "\r";
  if (!heater_uart_enqueue(
        UART_NUM_2,
        command.c_str(),
        command.length(),
        powerGeneration,
        true
      )) return false;
#endif
  target_power_volt = Volt;
  return true;
}

inline bool apply_regulator_mode_blocking(SafetyRegulatorMode mode, uint64_t powerGeneration) {
  const String Mode = regulator_mode_text(mode);
  if (Mode.length() == 0) return false;
  vTaskDelay(50 / portTICK_PERIOD_MS);
#ifdef SAMOVAR_USE_RMVK
  if (mode == SAFETY_REGULATOR_MODE_SLEEP) {
#ifdef SAMOVAR_USE_SEM_AVR
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
      const bool queued = sem_avr_write_samovar_command("+ON=0\r", 0, false);
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      xSemaphoreGive(xSemaphoreAVR);
      if (!queued) return false;
    } else return false;
#else
    if (RMVK_set_on(0, 0) == RMVK_ERROR) return false;
#endif
  } else if (mode == SAFETY_REGULATOR_MODE_SPEED) {
#ifdef __SAMOVAR_DEBUG
    WriteConsoleLog("Set power mode=" + Mode);
#endif
#ifdef SAMOVAR_USE_SEM_AVR
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 7) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 6 / portTICK_PERIOD_MS);
      const bool queued = sem_avr_write_samovar_command(
        "+ON=1\r", powerGeneration, true
      );
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      xSemaphoreGive(xSemaphoreAVR);
      if (!queued) return false;
    } else return false;
#else
    if (RMVK_set_on(1, powerGeneration) == RMVK_ERROR) return false;
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
    if (RMVK_set_out_voltge(MAX_VOLTAGE, powerGeneration) == RMVK_ERROR) return false;
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
#endif
  }
#else
  const String command = "M" + Mode + "\r";
  if (!heater_uart_enqueue(
        UART_NUM_2,
        command.c_str(),
        command.length(),
        powerGeneration,
        mode != SAFETY_REGULATOR_MODE_SLEEP
      )) return false;
  vTaskDelay(300 / portTICK_PERIOD_MS);
#endif
  set_current_power_mode_value(Mode);
  if (mode == SAFETY_REGULATOR_MODE_SLEEP) {
    target_power_volt = 0;
    current_power_volt = 0;
    current_power_p = 0;
  }
  return true;
}

inline void set_current_power(float Volt) {
  // Отрицательная уставка физически бессмысленна и в вольтах, и в ваттах: трактуем
  // как ноль. Сравнение через !(Volt >= 0) заодно ловит NaN — он тоже уходит в ноль,
  // то есть в SLEEP, а не в непредсказуемое состояние регулятора.
  if (!(Volt >= 0.0f)) Volt = 0.0f;
#ifdef SAMOVAR_USE_SEM_AVR
  // Клампим уставку к границе 230-эквивалента: 230² = 52900.
  const float maxPower =
    (230.0f * 230.0f / trusted_heater_resistance(SamSetup.HeaterResistant));
  if (Volt > maxPower) Volt = maxPower;
#else
  if (Volt > 230.0f) Volt = 230.0f;
#endif
  const float threshold = POWER_WORK_MODE_THRESHOLD;

  portENTER_CRITICAL(&emergencyStopMux);
  if (!PowerOn || heaterSafetyState.emergencyLatched || mode_switch_barrier_active) {
    portEXIT_CRITICAL(&emergencyStopMux);
    return;
  }
  if (power_transition_start_pending_locked()) {
    target_power_volt = Volt;
    powerTransition.pendingPowerValue = Volt;
    powerTransition.pendingPowerValueSet = true;
    portEXIT_CRITICAL(&emergencyStopMux);
    return;
  }
  request_regulator_state_locked(
    Volt < threshold ? SAFETY_REGULATOR_MODE_SLEEP : SAFETY_REGULATOR_MODE_WORK,
    Volt >= threshold,
    Volt,
    false
  );
  if (Volt < threshold) target_power_volt = 0;
  portEXIT_CRITICAL(&emergencyStopMux);
  notify_power_worker();
}

inline void set_power_mode(String Mode) {
  SafetyRegulatorMode regulatorMode;
  if (!regulator_mode_from_string(Mode, regulatorMode)) {
    SendMsg("Неизвестный режим регулятора: " + Mode, ALARM_MSG);
    return;
  }
  portENTER_CRITICAL(&emergencyStopMux);
  const uint64_t generation = request_regulator_state_locked(
    regulatorMode, false, 0, regulatorMode == SAFETY_REGULATOR_MODE_SLEEP
  );
  portEXIT_CRITICAL(&emergencyStopMux);
  if (generation != 0) notify_power_worker();
  if (generation == 0) {
    SendMsg("Команда включения регулятора отклонена safety-barrier", ALARM_MSG);
  }
}

inline void process_pending_power_request() {
  SafetyRegulatorRequestSnapshot snapshot = {};
  bool hasRequest = false;
  bool notifyWorker = false;
  bool reportFailure = false;
  bool reportTimeout = false;

  portENTER_CRITICAL(&emergencyStopMux);
  const uint32_t claimTime = millis();
  const SafetyRegulatorMode desiredMode = regulatorRequestState.desiredMode;
  const SafetyRegulatorWorkerClaim claim = safety_regulator_worker_claim(
    regulatorRequestState,
    claimTime,
    snapshot
  );
  if (claim == SAFETY_REGULATOR_WORKER_TIMED_OUT) {
    reportTimeout = true;
    if (heaterSafetyState.powerOn) {
      if (desiredMode == SAFETY_REGULATOR_MODE_SLEEP) {
        terminate_sleep_fault_locked(claimTime);
      } else {
        fail_close_regulator_locked(claimTime, true);
        notifyWorker = true;
      }
    }
  } else hasRequest = claim == SAFETY_REGULATOR_WORKER_CLAIMED;
  if (hasRequest && heaterSafetyState.emergencyLatched &&
      snapshot.mode != SAFETY_REGULATOR_MODE_SLEEP) {
    request_regulator_state_locked(SAFETY_REGULATOR_MODE_SLEEP, false, 0, true);
    safety_regulator_finish_apply(regulatorRequestState, snapshot, false);
    hasRequest = false;
  }
  portEXIT_CRITICAL(&emergencyStopMux);
  if (notifyWorker) notify_power_worker();
  if (reportTimeout) SendMsg("Таймаут команды регулятора; локальные реле сняты", ALARM_MSG);
  if (!hasRequest) return;

  portENTER_CRITICAL(&emergencyStopMux);
  const bool allowedBefore = safety_regulator_snapshot_allowed(snapshot, heaterSafetyState);
  portEXIT_CRITICAL(&emergencyStopMux);
  bool success = allowedBefore;
  if (success) success = apply_regulator_mode_blocking(snapshot.mode, snapshot.powerGeneration);
  if (success && snapshot.hasVoltage) {
    success = apply_regulator_voltage_blocking(snapshot.voltage, snapshot.powerGeneration);
  }

  portENTER_CRITICAL(&emergencyStopMux);
  const bool timedOut = safety_regulator_expire_request(
    regulatorRequestState, snapshot.generation, millis()
  );
  const bool allowedAfter = safety_regulator_snapshot_allowed(snapshot, heaterSafetyState);
  success = success && allowedAfter && !timedOut;
  safety_regulator_finish_apply(regulatorRequestState, snapshot, success);
  const SafetyRegulatorFailureAction failureAction = safety_regulator_failure_action(
    snapshot,
    success,
    heaterSafetyState.emergencyLatched,
    heaterSafetyState.powerOn
  );
  if (failureAction == SAFETY_REGULATOR_FAILURE_TERMINATE_SLEEP) {
    terminate_sleep_fault_locked(millis());
  } else if (failureAction == SAFETY_REGULATOR_FAILURE_FAIL_CLOSE) {
      fail_close_regulator_locked(millis(), true);
      notifyWorker = true;
  }
  reportTimeout = timedOut;
  reportFailure = !success && !timedOut && allowedBefore && allowedAfter &&
                  !heaterSafetyState.emergencyLatched;
  portEXIT_CRITICAL(&emergencyStopMux);

  if (notifyWorker) notify_power_worker();
  if (reportTimeout) SendMsg("Таймаут фонового применения команды регулятора", ALARM_MSG);
  if (reportFailure) SendMsg("Фоновое применение команды регулятора завершилось ошибкой", ALARM_MSG);
}

#endif
