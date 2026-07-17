#pragma once

#include <stddef.h>
#include <stdint.h>

enum SafetyTransitionPhase : uint8_t {
  SAFETY_TRANSITION_IDLE = 0,
  POWER_TRANSITION_ON_SEM_WAIT,
  POWER_TRANSITION_ON_REGULATOR_WAIT,
  POWER_TRANSITION_OFF_REGULATOR_WAIT,
  POWER_TRANSITION_OFF_RESET_WAIT,
  MODE_HEATING_PHASE_WAIT_POWER,
  MODE_HEATING_PHASE_WAIT_STABILIZE,
  SELF_TEST_START,
  SELF_TEST_CAPACITY_ADVANCE,
  SELF_TEST_HOLD,
  SELF_TEST_STOP,
  NBK_TRANSITION_HEAT_WAIT_POWER,
  NBK_TRANSITION_HEAT_WAIT,
  NBK_TRANSITION_HEAT_CANCEL_WAIT_POWER_OFF,
  NBK_TRANSITION_FINISH_WAIT,
  NBK_TRANSITION_FINISH_WAIT_POWER_OFF,
};

struct SafetyTransition {
  SafetyTransitionPhase phase;
  uint32_t deadline;
};

enum SafetyHeaterOutputMask : uint8_t {
  SAFETY_HEATER_OUTPUT_NONE = 0,
  SAFETY_HEATER_OUTPUT_MAIN = 1,
  SAFETY_HEATER_OUTPUT_BOOST = 2,
};

struct SafetyHeaterBarrierState {
  bool emergencyLatched;
  bool powerOn;
  bool exclusiveOwnerActive;
  uint64_t generation;
};

enum SafetyRegulatorMode : uint8_t {
  SAFETY_REGULATOR_MODE_SLEEP = 0,
  SAFETY_REGULATOR_MODE_SPEED,
  SAFETY_REGULATOR_MODE_WORK,
};

enum SafetyRegulatorRequestStatus : uint8_t {
  SAFETY_REGULATOR_REQUEST_UNKNOWN = 0,
  SAFETY_REGULATOR_REQUEST_PENDING,
  SAFETY_REGULATOR_REQUEST_APPLIED,
  SAFETY_REGULATOR_REQUEST_FAILED,
  SAFETY_REGULATOR_REQUEST_TIMED_OUT,
  SAFETY_REGULATOR_REQUEST_SUPERSEDED,
};

enum SafetyRegulatorWorkerClaim : uint8_t {
  SAFETY_REGULATOR_WORKER_IDLE = 0,
  SAFETY_REGULATOR_WORKER_CLAIMED,
  SAFETY_REGULATOR_WORKER_TIMED_OUT,
};

enum SafetyRegulatorFailureAction : uint8_t {
  SAFETY_REGULATOR_FAILURE_NONE = 0,
  SAFETY_REGULATOR_FAILURE_FAIL_CLOSE,
  SAFETY_REGULATOR_FAILURE_TERMINATE_SLEEP,
};

// Машина запросов к регулятору мощности. Все поля пишутся/читаются ТОЛЬКО под спинлоком
// emergencyStopMux (см. power_regulator.h) — межзадачной синхронизации иным способом нет.
//
// Поля-поколения (монотонный uint64, источник — nextGeneration через
// safety_regulator_next_generation): фиксируют жизненный цикл ОДНОГО запроса состояния.
//   nextGeneration       — счётчик-эмиттер: инкрементируется, выдавая id новому запросу.
//   desiredGeneration    — id последнего ЗАПРОШЕННОГО состояния (что хотим применить).
//   processingGeneration — id запроса, который worker ВЗЯЛ в обработку (apply идёт).
//   completedGeneration  — id запроса, успешно применённого к регулятору.
//   failedGeneration     — id запроса, чей apply ЗАВЕРШИЛСЯ ОТКАЗОМ (fail-close).
//   timedOutGeneration   — id запроса, протухшего по дедлайну (не применён вовремя).
// Инварианты: desired >= processing >= {completed|failed|timedOut}; запрос «в полёте»,
// пока desired > max(completed, failed, timedOut). Барьер энергизации сверяет generation
// перед физической отправкой в UART: устаревший (superseded/аварийный) запрос не уходит.
// desiredPowerGeneration/appliedPowerGeneration — отдельная пара для уставки мощности
// (меняется чаще состояния, не требует полного цикла apply).
struct SafetyRegulatorRequestState {
  uint64_t nextGeneration;
  uint64_t desiredGeneration;
  uint64_t processingGeneration;
  uint64_t completedGeneration;
  uint64_t failedGeneration;
  uint64_t timedOutGeneration;
  SafetyRegulatorMode desiredMode;
  SafetyRegulatorMode appliedMode;
  uint64_t desiredPowerGeneration;
  uint64_t appliedPowerGeneration;
  uint32_t desiredDeadline;
  float desiredVoltage;
  float appliedVoltage;
  bool desiredHasVoltage;
  bool appliedHasVoltage;
  bool pending;
  bool workerBusy;
};

struct SafetyRegulatorRequestSnapshot {
  uint64_t generation;
  uint64_t powerGeneration;
  uint32_t deadline;
  SafetyRegulatorMode mode;
  float voltage;
  bool hasVoltage;
};

enum SafetyModeSwitchPhase : uint8_t {
  SAFETY_MODE_SWITCH_IDLE = 0,
  SAFETY_MODE_SWITCH_STOP_REQUESTED,
  SAFETY_MODE_SWITCH_WAIT_CLEANUP,
};

struct SafetyModeSwitchState {
  SafetyModeSwitchPhase phase;
  uint8_t requestedMode;
  bool logCloseRequested;
};

typedef int (*SafetyUartEnqueueFn)(void* context, const char* data, size_t length);

inline bool safety_deadline_expired(uint32_t now, uint32_t deadline) {
  return (int32_t)(now - deadline) >= 0;
}

inline uint32_t safety_deadline_after(uint32_t now, uint32_t delayMs) {
  return now + delayMs;
}

inline bool safety_transition_active(const SafetyTransition& transition) {
  return transition.phase != SAFETY_TRANSITION_IDLE;
}

inline bool safety_transition_begin(SafetyTransition& transition, SafetyTransitionPhase phase, uint32_t deadline) {
  if (safety_transition_active(transition)) return false;
  transition.phase = phase;
  transition.deadline = deadline;
  return true;
}

inline void safety_transition_advance(SafetyTransition& transition, SafetyTransitionPhase phase, uint32_t deadline) {
  transition.phase = phase;
  transition.deadline = deadline;
}

inline bool safety_transition_due(const SafetyTransition& transition, uint32_t now) {
  return safety_transition_active(transition) && safety_deadline_expired(now, transition.deadline);
}

inline bool safety_transition_cancel(SafetyTransition& transition) {
  const bool wasActive = safety_transition_active(transition);
  transition.phase = SAFETY_TRANSITION_IDLE;
  transition.deadline = 0;
  return wasActive;
}

inline bool safety_heater_enable(
  SafetyHeaterBarrierState& state,
  bool setPowerOn
) {
  if (state.emergencyLatched || state.exclusiveOwnerActive) return false;
  if (setPowerOn && !state.powerOn) {
    state.powerOn = true;
    state.generation++;
  }
  if (!state.powerOn) return false;
  return true;
}

inline void safety_heater_force_off(SafetyHeaterBarrierState& state) {
  if (state.powerOn) {
    state.powerOn = false;
    state.generation++;
  }
}

inline bool safety_heater_emergency_trip(SafetyHeaterBarrierState& state) {
  const bool firstRequest = !state.emergencyLatched;
  state.emergencyLatched = true;
  state.powerOn = false;
  state.exclusiveOwnerActive = false;
  state.generation++;
  return firstRequest;
}

inline bool safety_heater_owner_acquire(
  SafetyHeaterBarrierState& state,
  uint64_t& ownerGeneration
) {
  if (state.emergencyLatched || state.powerOn || state.exclusiveOwnerActive) return false;
  state.exclusiveOwnerActive = true;
  state.generation++;
  ownerGeneration = state.generation;
  return true;
}

inline bool safety_heater_owner_valid(
  const SafetyHeaterBarrierState& state,
  uint64_t ownerGeneration
) {
  return state.exclusiveOwnerActive && !state.emergencyLatched &&
         !state.powerOn && state.generation == ownerGeneration;
}

inline bool safety_heater_owner_release(
  SafetyHeaterBarrierState& state,
  uint64_t ownerGeneration
) {
  if (!safety_heater_owner_valid(state, ownerGeneration)) return false;
  state.exclusiveOwnerActive = false;
  state.generation++;
  return true;
}

inline bool safety_heater_epoch_allows(
  const SafetyHeaterBarrierState& heater,
  uint64_t expectedGeneration
) {
  return !heater.emergencyLatched && heater.powerOn &&
         heater.generation == expectedGeneration;
}

inline bool safety_uart_commit_locked(
  const SafetyHeaterBarrierState& heater,
  uint64_t expectedGeneration,
  bool energizing,
  const char* data,
  size_t length,
  SafetyUartEnqueueFn enqueue,
  void* context
) {
  if (data == nullptr || length == 0 || enqueue == nullptr) return false;
  if (energizing && !safety_heater_epoch_allows(heater, expectedGeneration)) return false;
  return enqueue(context, data, length) == (int)length;
}

inline uint64_t safety_regulator_next_generation(SafetyRegulatorRequestState& state) {
  state.nextGeneration++;
  return state.nextGeneration;
}

inline bool safety_regulator_request_matches(
  const SafetyRegulatorRequestState& state,
  SafetyRegulatorMode mode,
  bool hasVoltage,
  float voltage,
  uint64_t powerGeneration
) {
  if (state.desiredMode != mode || state.desiredHasVoltage != hasVoltage ||
      state.desiredPowerGeneration != powerGeneration) return false;
  return !hasVoltage || state.desiredVoltage == voltage;
}

inline uint64_t safety_regulator_request(
  SafetyRegulatorRequestState& state,
  SafetyRegulatorMode mode,
  bool hasVoltage,
  float voltage,
  uint64_t powerGeneration,
  uint32_t deadline,
  bool force
) {
  if (!force && state.pending &&
      safety_regulator_request_matches(state, mode, hasVoltage, voltage, powerGeneration)) {
    return state.desiredGeneration;
  }
  if (!force && !state.pending && state.completedGeneration != 0 &&
      state.appliedMode == mode && state.appliedHasVoltage == hasVoltage &&
      state.appliedPowerGeneration == powerGeneration &&
      (!hasVoltage || state.appliedVoltage == voltage)) {
    return state.completedGeneration;
  }
  state.desiredGeneration = safety_regulator_next_generation(state);
  state.desiredMode = mode;
  state.desiredPowerGeneration = powerGeneration;
  state.desiredDeadline = deadline;
  state.desiredHasVoltage = hasVoltage;
  state.desiredVoltage = voltage;
  state.pending = true;
  return state.desiredGeneration;
}

inline bool safety_regulator_begin_apply(
  SafetyRegulatorRequestState& state,
  SafetyRegulatorRequestSnapshot& snapshot
) {
  if (!state.pending || state.workerBusy) return false;
  snapshot.generation = state.desiredGeneration;
  snapshot.powerGeneration = state.desiredPowerGeneration;
  snapshot.deadline = state.desiredDeadline;
  snapshot.mode = state.desiredMode;
  snapshot.voltage = state.desiredVoltage;
  snapshot.hasVoltage = state.desiredHasVoltage;
  state.processingGeneration = snapshot.generation;
  state.workerBusy = true;
  return true;
}

inline bool safety_regulator_expire_request(
  SafetyRegulatorRequestState& state,
  uint64_t generation,
  uint32_t now
) {
  if (!state.pending || state.desiredGeneration != generation ||
      !safety_deadline_expired(now, state.desiredDeadline)) return false;
  state.pending = false;
  state.timedOutGeneration = generation;
  return true;
}

inline SafetyRegulatorWorkerClaim safety_regulator_worker_claim(
  SafetyRegulatorRequestState& state,
  uint32_t now,
  SafetyRegulatorRequestSnapshot& snapshot
) {
  if (!state.pending || state.workerBusy) return SAFETY_REGULATOR_WORKER_IDLE;
  const uint64_t generation = state.desiredGeneration;
  if (safety_regulator_expire_request(state, generation, now)) {
    return SAFETY_REGULATOR_WORKER_TIMED_OUT;
  }
  return safety_regulator_begin_apply(state, snapshot)
    ? SAFETY_REGULATOR_WORKER_CLAIMED
    : SAFETY_REGULATOR_WORKER_IDLE;
}

inline bool safety_regulator_snapshot_allowed(
  const SafetyRegulatorRequestSnapshot& snapshot,
  const SafetyHeaterBarrierState& heater
) {
  return snapshot.mode == SAFETY_REGULATOR_MODE_SLEEP ||
         safety_heater_epoch_allows(heater, snapshot.powerGeneration);
}

inline SafetyRegulatorFailureAction safety_regulator_failure_action(
  const SafetyRegulatorRequestSnapshot& snapshot,
  bool success,
  bool emergencyLatched,
  bool powerOn
) {
  if (success || emergencyLatched) return SAFETY_REGULATOR_FAILURE_NONE;
  if (snapshot.mode == SAFETY_REGULATOR_MODE_SLEEP) {
    return powerOn
      ? SAFETY_REGULATOR_FAILURE_TERMINATE_SLEEP
      : SAFETY_REGULATOR_FAILURE_NONE;
  }
  return SAFETY_REGULATOR_FAILURE_FAIL_CLOSE;
}

inline void safety_regulator_finish_apply(
  SafetyRegulatorRequestState& state,
  const SafetyRegulatorRequestSnapshot& snapshot,
  bool success
) {
  if (state.processingGeneration == snapshot.generation) state.processingGeneration = 0;
  state.workerBusy = false;
  if (state.timedOutGeneration == snapshot.generation) return;
  if (state.desiredGeneration != snapshot.generation) return;
  state.pending = false;
  if (!success) {
    state.failedGeneration = snapshot.generation;
    return;
  }
  state.appliedMode = snapshot.mode;
  state.appliedPowerGeneration = snapshot.powerGeneration;
  state.appliedHasVoltage = snapshot.hasVoltage;
  state.appliedVoltage = snapshot.voltage;
  state.completedGeneration = snapshot.generation;
}

inline void safety_regulator_invalidate_energizing(SafetyRegulatorRequestState& state) {
  if (state.desiredMode == SAFETY_REGULATOR_MODE_SLEEP) return;
  state.desiredGeneration = safety_regulator_next_generation(state);
  state.desiredMode = SAFETY_REGULATOR_MODE_SLEEP;
  state.desiredPowerGeneration = 0;
  state.desiredDeadline = 0;
  state.desiredHasVoltage = false;
  state.desiredVoltage = 0;
  state.pending = false;
}

inline SafetyRegulatorRequestStatus safety_regulator_request_status(
  const SafetyRegulatorRequestState& state,
  uint64_t generation
) {
  if (generation == 0) return SAFETY_REGULATOR_REQUEST_UNKNOWN;
  if (state.completedGeneration == generation) return SAFETY_REGULATOR_REQUEST_APPLIED;
  if (state.failedGeneration == generation) return SAFETY_REGULATOR_REQUEST_FAILED;
  if (state.timedOutGeneration == generation) return SAFETY_REGULATOR_REQUEST_TIMED_OUT;
  if (state.desiredGeneration == generation || state.processingGeneration == generation) {
    return SAFETY_REGULATOR_REQUEST_PENDING;
  }
  return SAFETY_REGULATOR_REQUEST_SUPERSEDED;
}

inline bool safety_mode_switch_begin(SafetyModeSwitchState& state, uint8_t requestedMode) {
  if (state.phase != SAFETY_MODE_SWITCH_IDLE) return state.requestedMode == requestedMode;
  state.requestedMode = requestedMode;
  state.logCloseRequested = false;
  state.phase = SAFETY_MODE_SWITCH_STOP_REQUESTED;
  return true;
}

inline void safety_mode_switch_wait_cleanup(SafetyModeSwitchState& state) {
  state.phase = SAFETY_MODE_SWITCH_WAIT_CLEANUP;
}

inline void safety_mode_switch_mark_log_close_requested(SafetyModeSwitchState& state) {
  state.logCloseRequested = true;
}

inline bool safety_mode_switch_cleanup_ready(
  const SafetyModeSwitchState& state,
  bool powerOn,
  bool powerTransitionActive,
  bool nbkTransitionActive,
  bool modeHeatingActive,
  bool selfTestActive,
  bool logClosePending,
  bool ownerIdle,
  bool actuatorsIdle,
  bool luaIdle,
  bool commandQueuesIdle
) {
  return state.phase == SAFETY_MODE_SWITCH_WAIT_CLEANUP && !powerOn &&
         !powerTransitionActive && !nbkTransitionActive &&
         !modeHeatingActive && !selfTestActive && state.logCloseRequested &&
         !logClosePending && ownerIdle && actuatorsIdle && luaIdle &&
         commandQueuesIdle;
}

inline void safety_mode_switch_complete(SafetyModeSwitchState& state) {
  state.phase = SAFETY_MODE_SWITCH_IDLE;
  state.requestedMode = 0;
  state.logCloseRequested = false;
}
