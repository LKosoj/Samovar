#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"

void start_self_test(void) {
  is_self_test = true;
  SendMsg(("Запуск самотестирования."), NOTIFY_MSG);
  open_valve(true, true);
#ifdef USE_WATER_PUMP
  //включаем насос воды
  set_pump_pwm((PWM_START_VALUE + 20) * 10);
#endif
  //включаем шаговый двигатель
  stopService();
#ifdef USE_STEPPER_ACCELERATION
  // В самотестировании отключаем плавный разгон/торможение, чтобы мотор сразу крутился
  // с заданной скоростью (даже если в целом акселерация включена).
  portENTER_CRITICAL(&timerMux);
  stepper.setAcceleration(0);
  portEXIT_CRITICAL(&timerMux);
#endif
  stepper_safe_set_max_speed(get_speed_from_rate(1));
  //stepper.setSpeed(get_speed_from_rate(1));
  TargetStepps = 100 * SamSetup.StepperStepMl;
  stepper_safe_set_current(0);
  stepper_safe_set_target(TargetStepps);
  startService();
  //включаем сервопривод
  set_capacity(1);
  while (capacity_num != 0 && capacity_num < 5) {
    vTaskDelay(3000 / portTICK_PERIOD_MS);
    next_capacity();
  }
  vTaskDelay(15000 / portTICK_PERIOD_MS);
  stop_self_test();
  SendMsg(("Самотестирование закончено."), NOTIFY_MSG);
}

void stop_self_test(void) {
#ifdef USE_WATER_PUMP
  //выключаем насос воды
  set_pump_pwm(0);
#endif
  open_valve(false, true);
  set_capacity(0);
  stopService();
#ifdef USE_STEPPER_ACCELERATION
  // Возвращаем ускорение библиотеки по умолчанию, чтобы остальные режимы работали штатно
  portENTER_CRITICAL(&timerMux);
  stepper.setAcceleration(200);
  portEXIT_CRITICAL(&timerMux);
#endif
  is_self_test = false;
  reset_sensor_counter();
}
