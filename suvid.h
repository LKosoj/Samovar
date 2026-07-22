#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"

// Уставка термостата: 0 в настройках — поле не задано, работаем от дефолта 60°.
inline float suvid_target_temp() {
  return SamSetup.SuvidTemp > 0 ? SamSetup.SuvidTemp : 60.0f;
}

/**
 * @brief Режим Су-вид: надзор датчиков/аварий + релейный термостат по TankSensor.
 * Вызывается из mode_dispatch_alarm (SysTicker, core 0, 1 Гц). У режима нет
 * собственного _proc()/finish() (mode_registry.h: activeStatus=0, как у простоя
 * Ректификации) — поэтому и надзор, и управление нагревом целиком в этом обработчике.
 */
inline void check_alarm_suvid() {
  mode_clear_alarm_pause_if_expired();

  // Датчики проверяем только при активном процессе (PowerOn) — иначе неподключённый
  // датчик куба порол бы аварийный останов каждую секунду в простое (см. check_alarm()
  // в alarm.h для Ректификации — тот же принцип для режима с activeStatus=0).
  if (PowerOn) {
    if (!mode_check_powered_cooling_sensors("Сувид")) return;
    if (!sensor_valid(TankSensor) && process_sensor_failed("Сувид", "куба")) return;
  }

#ifdef SAMOVAR_USE_POWER
  check_power_error();
#endif

  mode_request_overheat_emergency_if_needed();
  mode_request_water_flow_emergency_if_needed();

  // Релейный термостат с гистерезисом HEAT_DELTA (Samovar_ini.h).
  static bool suvidHeaterOn = false;
  if (!PowerOn) {
    suvidHeaterOn = false;  // холодный старт следующей сессии: не наследовать состояние реле
    heater_state = false;
    return;
  }
  const float setpoint = suvid_target_temp();
  if (TankSensor.avgTemp <= setpoint - HEAT_DELTA) suvidHeaterOn = true;
  else if (TankSensor.avgTemp >= setpoint) suvidHeaterOn = false;
  heater_state = suvidHeaterOn;  // для строки статуса и mode_actuators_idle()
  setHeaterPosition(suvidHeaterOn);
}
