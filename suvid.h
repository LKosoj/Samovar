#pragma once

#include <Arduino.h>
#include <math.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"

// Уставка термостата: 0 в настройках — поле не задано, работаем от дефолта 60°.
inline float suvid_target_temp() {
  return SamSetup.SuvidTemp > 0 ? SamSetup.SuvidTemp : 60.0f;
}

// Выдержка Сувида учитывает только подтверждённое время внутри полосы
// setpoint±HEAT_DELTA. active остаётся взведённым между выходами из полосы,
// чтобы накопленное время не терялось; inBand отделяет текущий зачёт интервала.
struct SuvidHoldState {
  bool active;
  bool fired;
  bool inBand;
  bool completionWarningSent;
  uint32_t accumulatedMs;
  uint32_t lastTickMs;
};
static SuvidHoldState suvidHold;

struct SuvidDeviationState { bool active; bool warningSent; uint32_t sinceMs; };
static SuvidDeviationState suvidDeviation;

// Остаток выдержки в секундах; -1, если отсчёт не идёт (см. tick_status_fsm в logic.h).
inline int32_t suvid_hold_remaining_sec() {
  if (!suvidHold.active || SamSetup.SuvidHoldMinutes == 0) return -1;
  const uint32_t totalMs = (uint32_t)SamSetup.SuvidHoldMinutes * 60000UL;
  return suvidHold.accumulatedMs >= totalMs
      ? 0
      : (int32_t)((totalMs - suvidHold.accumulatedMs) / 1000UL);
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
  // Вода и ТСА в Сувиде опциональны (термостат работает и без охлаждения контура) —
  // авария только если датчик заявлен и невалиден. Куб (TankSensor) обязателен:
  // без него термостату не по чему регулировать нагрев.
  if (PowerOn) {
    if (optional_sensor_failed(WaterSensor) && process_sensor_failed("Сувид", "воды")) return;
    if (optional_sensor_failed(ACPSensor) && process_sensor_failed("Сувид", "ТСА")) return;
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
    suvidHold = {false, false, false, false, 0, 0};
    suvidDeviation = {false, false, 0};
    return;
  }
  const float setpoint = suvid_target_temp();
  if (TankSensor.avgTemp <= setpoint - HEAT_DELTA) suvidHeaterOn = true;
  else if (TankSensor.avgTemp >= setpoint + HEAT_DELTA) suvidHeaterOn = false;
  heater_state = suvidHeaterOn;  // для строки статуса и mode_actuators_idle()
  setHeaterPosition(suvidHeaterOn);

  const uint32_t now = millis();
  const float deviation = fabsf(TankSensor.avgTemp - setpoint);
  if (deviation > 2.0f) {
    if (!suvidDeviation.active) {
      suvidDeviation.active = true;
      suvidDeviation.sinceMs = now;
    }
    if (!suvidDeviation.warningSent &&
        (uint32_t)(now - suvidDeviation.sinceMs) >= 60000UL) {
      SendMsg("Сувид: температура отклоняется от уставки более чем на 2° уже 60 сек.", WARNING_MSG);
      suvidDeviation.warningSent = true;
    }
  } else {
    suvidDeviation = {false, false, 0};
  }

  const uint32_t holdMs = (uint32_t)SamSetup.SuvidHoldMinutes * 60000UL;
  const bool inHoldBand = deviation <= HEAT_DELTA;
  if (holdMs > 0 && !suvidHold.fired) {
    if (!suvidHold.active && inHoldBand) {
      suvidHold.active = true;
      suvidHold.inBand = true;
      suvidHold.lastTickMs = now;
    } else if (suvidHold.active) {
      if (inHoldBand) {
        if (suvidHold.inBand) suvidHold.accumulatedMs += now - suvidHold.lastTickMs;
        suvidHold.inBand = true;
        suvidHold.lastTickMs = now;
      } else {
        suvidHold.inBand = false;
      }
    }

    if (suvidHold.active && suvidHold.accumulatedMs >= holdMs) {
      set_buzzer(true);
      if (queue_samovar_command(SAMOVAR_POWER)) {
        SendMsg("Сувид: выдержка завершена, нагрев выключен.", NOTIFY_MSG);
        suvidHold.fired = true;
      } else if (!suvidHold.completionWarningSent) {
        SendMsg("Сувид: выдержка завершена, но штатное выключение не поставлено: очередь команд занята.", WARNING_MSG);
        suvidHold.completionWarningSent = true;
      }
    }
  }
}
