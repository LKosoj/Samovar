#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "safety_transition.h"

static SafetyTransition selfTestTransition = {SAFETY_TRANSITION_IDLE, 0};
static bool selfTestCompleted = false;
static uint64_t selfTestOwnerGeneration = 0;
enum SelfTestDevice { SELF_TEST_ALL, SELF_TEST_VALVE, SELF_TEST_WATER_PUMP,
                      SELF_TEST_STEPPER, SELF_TEST_CAPACITY };
static uint8_t selfTestDevice = SELF_TEST_ALL;
struct SelfTestSnapshot {
  uint8_t device;
  bool active;
};
static SelfTestSnapshot selfTestSnapshot = {SELF_TEST_ALL, false};
static portMUX_TYPE selfTestMux = portMUX_INITIALIZER_UNLOCKED;

inline SelfTestSnapshot copy_self_test_snapshot() {
  portENTER_CRITICAL(&selfTestMux);
  const SelfTestSnapshot snapshot = selfTestSnapshot;
  portEXIT_CRITICAL(&selfTestMux);
  return snapshot;
}

inline void publish_self_test_state(bool active) {
  portENTER_CRITICAL(&selfTestMux);
  selfTestSnapshot = {selfTestDevice, active};
  portEXIT_CRITICAL(&selfTestMux);
}

inline bool self_test_uses(uint8_t device) {
  return selfTestDevice == SELF_TEST_ALL || selfTestDevice == device;
}
#ifdef USE_WATER_PUMP
static uint32_t selfTestPumpTickMs = 0;
#endif

inline void finish_self_test_now(bool completed) {
  if (heater_power_on() || PowerOn) set_power(false, false);
#ifdef USE_WATER_PUMP
  if (self_test_uses(SELF_TEST_WATER_PUMP)) set_pump_pwm(0);
#endif
  if (self_test_uses(SELF_TEST_VALVE)) open_valve(false, true);
  if (self_test_uses(SELF_TEST_CAPACITY)) set_capacity(0);
  if (self_test_uses(SELF_TEST_STEPPER)) {
    stopService();
    if (selfTestDevice != SELF_TEST_ALL) {
      stepper_safe_stop_reset();
      TargetStepps = 0;
      ActualVolumePerHour = 0;
    }
  }
#ifdef USE_STEPPER_ACCELERATION
  if (self_test_uses(SELF_TEST_STEPPER)) {
    portENTER_CRITICAL(&timerMux);
    stepper.setAcceleration(200);
    portEXIT_CRITICAL(&timerMux);
  }
#endif
  is_self_test = false;
  if (selfTestDevice == SELF_TEST_ALL) reset_sensor_counter();
  safety_transition_cancel(selfTestTransition);
  publish_self_test_state(false);
  selfTestCompleted = false;
  safety_owner_generation_release(selfTestOwnerGeneration);
  selfTestOwnerGeneration = 0;
  if (completed) SendMsg((TR(SELF_FINISHED, "Самотестирование закончено.")), NOTIFY_MSG);
}

inline bool abort_self_test_if_owner_lost() {
  if (!mode_switch_in_progress() &&
      safety_owner_generation_valid(selfTestOwnerGeneration)) return false;
  finish_self_test_now(false);
  return true;
}

inline bool self_test_active() {
  return is_self_test || safety_transition_active(selfTestTransition);
}

inline void start_self_test(uint8_t device) {
  if (is_self_test || safety_transition_active(selfTestTransition)) return;
  if (samovar_process_active() || mode_switch_in_progress() ||
      !safety_owner_generation_acquire(selfTestOwnerGeneration)) {
    SendMsg(TR(SELF_REJECTED, "Самотестирование отклонено: активен процесс или смена режима"), WARNING_MSG);
    selfTestOwnerGeneration = 0;
    return;
  }
  selfTestDevice = device;
  selfTestCompleted = false;
  if (!safety_transition_begin(selfTestTransition, SELF_TEST_START, 0)) {
    safety_owner_generation_release(selfTestOwnerGeneration);
    selfTestOwnerGeneration = 0;
  } else {
    publish_self_test_state(true);
  }
}

inline void tick_self_test(void) {
  if (!safety_transition_active(selfTestTransition)) return;
  if (selfTestTransition.phase != SELF_TEST_STOP && abort_self_test_if_owner_lost()) return;

#ifdef USE_WATER_PUMP
  // Продолжаем пуск раз в секунду, затем держим тестовую скорость независимо от воды.
  if (is_self_test && self_test_uses(SELF_TEST_WATER_PUMP) && selfTestTransition.phase != SELF_TEST_STOP &&
      (uint32_t)(millis() - selfTestPumpTickMs) >= 1000) {
    selfTestPumpTickMs = millis();
    set_pump_pwm((PWM_START_VALUE + 20) * 10);
  }
#endif

  if (selfTestTransition.phase == SELF_TEST_START) {
    is_self_test = true;
    SendMsg((TR(SELF_STARTING, "Запуск самотестирования.")), NOTIFY_MSG);
    if (abort_self_test_if_owner_lost()) return;
    if (self_test_uses(SELF_TEST_VALVE)) open_valve(true, true);
    if (abort_self_test_if_owner_lost()) return;
#ifdef USE_WATER_PUMP
    if (self_test_uses(SELF_TEST_WATER_PUMP)) {
      selfTestPumpTickMs = millis();
      set_pump_pwm((PWM_START_VALUE + 20) * 10);
    }
    if (abort_self_test_if_owner_lost()) return;
#endif
    if (self_test_uses(SELF_TEST_STEPPER)) {
      stopService();
#ifdef USE_STEPPER_ACCELERATION
      portENTER_CRITICAL(&timerMux);
      stepper.setAcceleration(0);
      portEXIT_CRITICAL(&timerMux);
#endif
      stepper_safe_set_max_speed(get_speed_from_rate(1));
      TargetStepps = 100 * SamSetup.StepperStepMl;
      stepper_safe_set_current(0);
      stepper_safe_set_target(TargetStepps);
      if (abort_self_test_if_owner_lost()) return;
      startService();
    }
    if (abort_self_test_if_owner_lost()) return;
    if (self_test_uses(SELF_TEST_CAPACITY)) set_capacity(1);
    if (abort_self_test_if_owner_lost()) return;
    safety_transition_advance(
      selfTestTransition,
      self_test_uses(SELF_TEST_CAPACITY) ? SELF_TEST_CAPACITY_ADVANCE : SELF_TEST_HOLD,
      safety_deadline_after(millis(), self_test_uses(SELF_TEST_CAPACITY) ? 3000 : 15000)
    );
    return;
  }

  if (selfTestTransition.phase == SELF_TEST_CAPACITY_ADVANCE) {
    if (!safety_transition_due(selfTestTransition, millis())) return;
    if (abort_self_test_if_owner_lost()) return;
    if (capacity_num != 0 && capacity_num < 5) next_capacity();
    if (abort_self_test_if_owner_lost()) return;
    if (capacity_num != 0 && capacity_num < 5) {
      selfTestTransition.deadline = safety_deadline_after(millis(), 3000);
    } else {
      safety_transition_advance(
        selfTestTransition,
        SELF_TEST_HOLD,
        safety_deadline_after(millis(), 15000)
      );
    }
    return;
  }

  if (selfTestTransition.phase == SELF_TEST_HOLD) {
    if (!safety_transition_due(selfTestTransition, millis())) return;
    if (abort_self_test_if_owner_lost()) return;
    selfTestCompleted = true;
    safety_transition_advance(selfTestTransition, SELF_TEST_STOP, 0);
  }

  if (selfTestTransition.phase == SELF_TEST_STOP) {
    finish_self_test_now(selfTestCompleted);
  }
}

inline void stop_self_test(void) {
  if (!is_self_test && !safety_transition_active(selfTestTransition)) return;
  selfTestCompleted = false;
  if (!is_self_test && selfTestTransition.phase == SELF_TEST_START) {
    safety_transition_cancel(selfTestTransition);
    publish_self_test_state(false);
    safety_owner_generation_release(selfTestOwnerGeneration);
    selfTestOwnerGeneration = 0;
    return;
  }
  if (!safety_transition_active(selfTestTransition)) {
    safety_transition_begin(selfTestTransition, SELF_TEST_STOP, 0);
  } else {
    safety_transition_advance(selfTestTransition, SELF_TEST_STOP, 0);
  }
  tick_self_test();
}
