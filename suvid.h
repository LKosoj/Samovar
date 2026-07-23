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

// Таймер выдержки Сувида: отсчёт от первого достижения уставки, до истечения
// program[0].Time минут. fired — защёлка, не даёт запустить отсчёт заново
// после штатного завершения в той же сессии (сброс — только на !PowerOn).
struct SuvidHoldState { bool active; bool fired; uint32_t deadlineMs; };
static SuvidHoldState suvidHold;

// Остаток выдержки в секундах; -1, если отсчёт не идёт (см. tick_status_fsm в logic.h).
inline int32_t suvid_hold_remaining_sec() {
  if (!suvidHold.active) return -1;
  // [C-13] overflow-safe: millis() читаем один раз, как и в остальных остатках (logic.h).
  int32_t remMs = (int32_t)(suvidHold.deadlineMs - millis());
  return remMs > 0 ? remMs / 1000 : 0;
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
    suvidHold = {false, false, 0};  // сброс таймера выдержки для следующей сессии
    return;
  }
  const float setpoint = suvid_target_temp();
  if (TankSensor.avgTemp <= setpoint - HEAT_DELTA) suvidHeaterOn = true;
  else if (TankSensor.avgTemp >= setpoint) suvidHeaterOn = false;
  heater_state = suvidHeaterOn;  // для строки статуса и mode_actuators_idle()
  setHeaterPosition(suvidHeaterOn);

  // Таймер выдержки: program[0].Time (мин) — сколько держать температуру после
  // первого достижения уставки. WType != PROGRAM_TYPE_NONE отличает заданную
  // строку Сувида от «чужого» значения, оставшегося в общем буфере program[0]
  // от другого режима (если пользователь сменил режим без пересылки программы).
  const float holdMinutes = program[0].Time;
  if (program[0].WType != PROGRAM_TYPE_NONE && holdMinutes > 0 && !suvidHold.fired) {
    if (!suvidHold.active && TankSensor.avgTemp >= setpoint) {
      suvidHold.active = true;
      suvidHold.deadlineMs = safety_deadline_after(millis(), (uint32_t)(holdMinutes * 60000.0f));
    }
    if (suvidHold.active && safety_deadline_expired(millis(), suvidHold.deadlineMs)) {
      set_buzzer(true);
      SendMsg("Сувид: выдержка завершена, нагрев выключен.", NOTIFY_MSG);
      // Останов только через очередь команд (штатно выключает питание режима);
      // при занятой очереди — fallback на аварийный останов, как в nbk.h.
      if (!queue_samovar_command(SAMOVAR_POWER)) {
        request_emergency_stop("Аварийное отключение! Не удалось штатно завершить выдержку Сувида");
      }
      suvidHold.fired = true;
    }
  }
}
