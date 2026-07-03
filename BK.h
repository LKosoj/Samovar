#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

/**
 * @brief Установить температуру воды (ШИМ).
 * @param duty Значение ШИМ
 */
void set_water_temp(float duty) {
#ifdef USE_WATER_PUMP
  bk_pwm = duty;
  if (pump_started) {
    pump_pwm.write(bk_pwm);
    water_pump_speed = bk_pwm;
  }
#else
  SendMsg(("Управление насосом не поддерживается вашим оборудованием"), NOTIFY_MSG);
#endif
}

/**
 * @brief Основной цикл работы бражной колонны. Запускает нагрев, проверяет условия завершения.
 */
void bk_proc() {

  if (SamovarStatusInt != 3000) return;

  if (!sensor_valid(TankSensor) && process_sensor_failed("БК", "куба")) return;

  if (!PowerOn) {
    if (!mode_start_heating_session(
      3000,
      "Ошибка создания файла лога. Старт БК отменён.",
      "Описание сессии занято. Старт БК отменён.",
      String("BK"),
      "Включен нагрев бражной колонны",
      false
    )) return;
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    bk_finish();
    return;
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Проверка и обработка аварийных ситуаций в работе бражной колонны.
 */
void check_alarm_bk() {
  //сбросим паузу события безопасности
  mode_clear_alarm_pause_if_expired();

  if (PowerOn && !mode_check_powered_cooling_sensors("БК")) return;

#ifdef SAMOVAR_USE_POWER
  check_power_error();
#endif

#ifdef USE_WATER_PUMP
  bool coolingOpenedThisTick = false;
#endif

  if (mode_should_open_cooling(true, true, true)) {
    open_valve(true, true);
#ifdef USE_WATER_PUMP
    set_pump_pwm(bk_pwm);
    coolingOpenedThisTick = true;
#endif
  }

#ifdef USE_WATER_PUMP
  if (!coolingOpenedThisTick && valve_status && pump_started && bk_pwm != PWM_LOW_VALUE * 40 && wp_count < 10) {
    set_pump_pwm(bk_pwm);
  }
#endif

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  if (current_power_mode_is(POWER_SPEED_MODE) && (check_boiling() || SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP || PipeSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP)) {
#ifdef SAMOVAR_USE_POWER
#ifndef SAMOVAR_USE_SEM_AVR
    set_current_power(45);
#else
    set_current_power(200);
#endif
#else
    set_current_power_mode_value(POWER_WORK_MODE);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }

  if (mode_should_close_cooling(TARGET_WATER_TEMP - 20, false)) {
    open_valve(false, true);
    mode_stop_cooling_pump_if_started();
  }

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((WaterSensor.avgTemp >= MAX_WATER_TEMP || sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP)) && PowerOn) {
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    String s = "";
    if (WaterSensor.avgTemp >= MAX_WATER_TEMP)
      s = s + " воды охлаждения";
    if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP))
      s = s + " ТСА";
    request_emergency_stop("Аварийное отключение! Превышена максимальная температура" + s);
  }

  //Проверим, что вода подается
  mode_request_water_flow_emergency_if_needed();

  if (mode_water_pre_alarm_due()) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный

#ifdef SAMOVAR_USE_POWER
    //Попробуем снизить мощность на 5 В/шагов регулятора, чтобы исключить перегрев колонны.
    mode_reduce_power_for_water_alarm_by_volts("Критическая температура воды! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt, 5);
#else
    SendMsg(("Критическая температура воды!"), WARNING_MSG);
#endif
    mode_set_alarm_pause_ms(30000);
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void bk_finish() {
  stop_process("Работа бражной колонны завершена");
}
