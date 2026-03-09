#ifndef __SAMOVAR_PROCESS_COMMON_H_
#define __SAMOVAR_PROCESS_COMMON_H_

#include <Arduino.h>

#include "Samovar_ini.h"
#include "io/actuators.h"
#include "state/globals.h"
#include "support/process_math.h"

void set_power(bool On);
void reset_sensor_counter(void);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void stopService(void);
void startService(void);

#ifdef USE_WATER_PUMP
void set_pump_pwm(float duty);
#endif

inline void stop_process(String reason) {
  SamovarStatusInt = 0;
  set_power(false);
  reset_sensor_counter();
  SendMsg(reason, NOTIFY_MSG);
}

inline void stop_self_test(void);

inline void start_self_test(void) {
  is_self_test = true;
  SendMsg(("Запуск самотестирования."), NOTIFY_MSG);
  open_valve(true, true);
#ifdef USE_WATER_PUMP
  set_pump_pwm((PWM_START_VALUE + 20) * 10);
#endif
  stopService();
#ifdef USE_STEPPER_ACCELERATION
  stepper.setAcceleration(0);
#endif
  stepper.setMaxSpeed(get_speed_from_rate(1));
  TargetStepps = 100 * SamSetup.StepperStepMl;
  stepper.setCurrent(0);
  stepper.setTarget(TargetStepps);
  startService();
  set_capacity(1);
  while (capacity_num != 0 && capacity_num < 5) {
    vTaskDelay(3000 / portTICK_PERIOD_MS);
    next_capacity();
  }
  vTaskDelay(15000 / portTICK_PERIOD_MS);
  stop_self_test();
  SendMsg(("Самотестирование закончено."), NOTIFY_MSG);
}

inline void stop_self_test(void) {
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
#endif
  open_valve(false, true);
  set_capacity(0);
  stopService();
#ifdef USE_STEPPER_ACCELERATION
  stepper.setAcceleration(200);
#endif
  is_self_test = false;
  reset_sensor_counter();
}

#endif
