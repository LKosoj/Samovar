#ifndef __SAMOVAR_DIST_ALARM_H_
#define __SAMOVAR_DIST_ALARM_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/messages.h"
#include "io/actuators.h"
#include "io/power_control.h"

void set_pump_speed_pid(float temp);

inline void check_alarm_distiller() {
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  if (!valve_status) {
    if (ACPSensor.avgTemp >= MAX_ACP_TEMP - 5) {
      set_buzzer(true);
      open_valve(true, true);
    } else if (TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP && PowerOn) {
      set_buzzer(true);
      open_valve(true, true);
    }
  }

  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE) {
    open_valve(false, true);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }

  check_boiling();

#ifdef USE_WATER_PUMP
  if (valve_status) {
    if (ACPSensor.avgTemp > SamSetup.SetACPTemp && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
    else
      set_pump_speed_pid(WaterSensor.avgTemp);
  }
#endif

  if ((WaterSensor.avgTemp >= MAX_WATER_TEMP || ACPSensor.avgTemp >= MAX_ACP_TEMP) && PowerOn) {
    set_buzzer(true);
    set_power(false);
    String s = "";
    if (WaterSensor.avgTemp >= MAX_WATER_TEMP)
      s = s + " Воды";
    else if (ACPSensor.avgTemp >= MAX_ACP_TEMP)
      s = s + " ТСА";
    SendMsg("Аварийное отключение! Превышена максимальная температура" + s, ALARM_MSG);
  }

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

#ifdef SAMOVAR_USE_POWER
    check_power_error();
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      set_buzzer(true);
      SendMsg("Критическая температура воды! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt, ALARM_MSG);
      set_current_power(target_power_volt - 5);
    }
#endif
    alarm_t_min = millis() + 30000;
  }

#ifdef USE_WATER_VALVE
  if (WaterSensor.avgTemp >= SamSetup.SetWaterTemp + 1) {
    digitalWrite(WATER_PUMP_PIN, USE_WATER_VALVE);
  } else if (WaterSensor.avgTemp <= SamSetup.SetWaterTemp - 1) {
    digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
  }
#endif
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

#endif
