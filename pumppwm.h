#pragma once
#include "Samovar.h"
#include "safety_transition.h"
#ifdef USE_WATER_PUMP
#include <Arduino.h>
//#define PID_OPTIMIZED_I
#include <GyverPID.h>
#if USE_ADAPTIVE_PID
#include "adaptive_pid.h"
#endif

#ifndef PUMP_PWM_FREQ
#define PUMP_PWM_FREQ 15
#else
#pragma message ("CUSTOM PUMP_PWM_FREQ")
#endif

static ESP32PWM pump_pwm;
static GyverPID pump_regulator(6.5, 0.3, 30, 1023);
#if USE_ADAPTIVE_PID
static AdaptivePumpState adaptivePumpState = {};
#endif

void init_pump_pwm(uint8_t pin, int freq) {
  pump_pwm.attachPin(pin, freq, 10);
  pump_regulator.setDirection(REVERSE);                // направление регулирования (NORMAL/REVERSE). ПО УМОЛЧАНИЮ СТОИТ NORMAL
  pump_regulator.setLimits(PWM_LOW_VALUE * 10, 1023);  // пределы (ставим для 8 битного ШИМ). ПО УМОЛЧАНИЮ СТОЯТ 0 И 255
  //pump_regulator.setMode(ON_RATE);
  pump_regulator.setpoint = SamSetup.SetWaterTemp;     // сообщаем регулятору температуру, которую он должен поддерживать
  pump_started = false;
#if USE_ADAPTIVE_PID
  adaptive_pump_reset(adaptivePumpState, PWM_LOW_VALUE / 100.0f);
#endif
}

ActuatorCommandResult set_pump_pwm(float duty) {
  duty = constrain(duty, 0, 1023);

  // Во время смены режима приводами распоряжается только процедура переключения (см.
  // valve_buzzer.h::open_valve): иначе check_alarm_bk (BK.h) включает насос охлаждения
  // наперегонки со stop_local_mode_actuators() из loop(), а mode_actuators_idle()
  // (!pump_started && water_pump_speed == 0) не сходится — переключение срывается в
  // принудительное завершение по дедлайну. Выключение (duty == 0) проходит всегда.
  if (duty > 0 && mode_switch_barrier_active) return ACTUATOR_COMMAND_FAILED;

  // [П14/A2 п.3] Мягкий пуск не должен зависеть от конкретного числа duty.
  // PWM_START_VALUE*10 и PWM_LOW_VALUE*40 случайно равны 400 (40*10 == 10*40) -
  // раньше от этого совпадения зависело, сработает ли разгон: при duty == 400
  // функция сразу писала duty (незаметно, т.к. 400 и есть стартовое значение),
  // а для ЛЮБОГО другого duty (Пиво, самотест, PID-регулятор насоса) счётчик
  // wp_count < 10 фактически не работал - уже второй подряд вызов писал duty
  // напрямую, минуя разгон. Теперь старт одинаков для любого duty > 0: первый
  // вызов после включения и все последующие, пока wp_count < 10, пишут
  // PWM_START_VALUE*10; запрошенное duty применяется, только когда счётчик
  // исчерпан.
  if (!pump_started && duty > 0) {
    wp_count = 0;
    pump_pwm.write(PWM_START_VALUE * 10);
    water_pump_speed = PWM_START_VALUE * 10;
    pump_started = true;
    return ACTUATOR_COMMAND_APPLIED;
  }
  if (duty > 0 && wp_count < 10 && pump_started) {
    pump_pwm.write(PWM_START_VALUE * 10);
    water_pump_speed = PWM_START_VALUE * 10;
    wp_count++;
    return ACTUATOR_COMMAND_APPLIED;
  }
  if (duty == 0) pump_started = false;
  pump_pwm.write(duty);
  water_pump_speed = duty;
  return ACTUATOR_COMMAND_APPLIED;
}

#if USE_ADAPTIVE_PID
inline void set_pump_speed_pid_control(
    float controlTemp, float measuredTemp, bool learningAllowed) {
  const float minimumDuty = PWM_LOW_VALUE / 100.0f;
  if (!pump_started) adaptive_pump_reset(adaptivePumpState, minimumDuty);
  const bool canLearn = learningAllowed && pump_started && wp_count >= 10;
  const uint32_t nowMs = millis();
  const float duty = adaptive_pump_step(
      adaptivePumpState, SamSetup.SetWaterTemp, controlTemp, measuredTemp,
      minimumDuty, nowMs, canLearn);
  const ActuatorCommandResult result = set_pump_pwm(duty * 1023.0f);
  adaptive_pump_note_command(
      adaptivePumpState, nowMs,
      canLearn && result == ACTUATOR_COMMAND_APPLIED);
}

inline void set_pump_speed_pid(float temp) {
  set_pump_speed_pid_control(temp, temp, true);
}
#else
void set_pump_speed_pid(float temp) {
  pump_regulator.setpoint = SamSetup.SetWaterTemp;
  pump_regulator.input = temp;
  set_pump_pwm(pump_regulator.getResultNow());
}
#endif
#endif
