#ifndef __SAMOVAR_NBK_ALARM_H_
#define __SAMOVAR_NBK_ALARM_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/messages.h"
#include "io/actuators.h"

void set_pump_speed_pid(float temp);

inline void check_alarm_nbk() {
  // Если нагрев выключен и это не самотестирование и вода включена и Т воды на 20 и более гр. ниже уставки
  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= TARGET_WATER_TEMP - 20) {
    open_valve(false, true);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }

  if (!PowerOn) {
    return;
  }

  // сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  // Если нагрев включен и вода выключена и температура в бардоотводчике больше уставки включения воды
  if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true, true);
  }

#ifdef USE_WATER_PUMP
  if (valve_status) {
    if (ACPSensor.avgTemp > SamSetup.SetACPTemp && ACPSensor.avgTemp > WaterSensor.avgTemp) {
      set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
    } else {
      set_pump_speed_pid(WaterSensor.avgTemp);
    }
  }
#endif

#ifdef USE_WATERSENSOR
  if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
    set_buzzer(true);
    sam_command_sync = SAMOVAR_POWER;
    SendMsg(("Аварийное отключение! Прекращена подача воды."), ALARM_MSG);
  }
#endif

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    SendMsg(("Критическая температура воды!"), WARNING_MSG);
    alarm_t_min = millis() + 60000;
  }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

#endif
