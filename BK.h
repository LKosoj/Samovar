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

  if (SamovarStatusInt != SAMOVAR_STATUS_BK) return;

  if (!sensor_valid(TankSensor) && process_sensor_failed("БК", "куба")) return;

  if (!PowerOn || mode_heating_start_pending(SAMOVAR_STATUS_BK)) {
    if (mode_run_heating_start(
          SAMOVAR_STATUS_BK,
          "Ошибка создания файла лога. Старт БК отменён.",
          "Описание сессии занято. Старт БК отменён.",
          String("BK"),
          "Включен нагрев бражной колонны",
          false) != MODE_HEATING_START_SUCCEEDED) return;
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

  if (mode_should_open_cooling(false, true, true)) {
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

  // [П4.1] check_boiling() должна вызываться безусловно каждый тик: если внутри if
  // ниже сработает короткое замыкание на Steam/Pipe>39 (режим мощности сменится
  // раньше), сам check_boiling() больше не вызовется и boil_started может навсегда
  // остаться false, из-за чего get_alcohol()/get_steam_alcohol() отдают заглушку 100.
  // check_boiling() возвращает true ТОЛЬКО в тот единственный вызов, когда кипение
  // обнаружено впервые (дальше boil_started=true и guard всегда отдаёт false) -
  // поэтому вызываем её РОВНО ОДИН раз за тик и переиспользуем результат ниже.
  bool boilingNow = check_boiling();

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  if (current_power_mode_is(POWER_SPEED_MODE) && (boilingNow || SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP || PipeSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP)) {
#ifdef SAMOVAR_USE_POWER
    set_current_power(SamSetup.BKPower);
#else
    set_current_power_mode_value(POWER_WORK_MODE);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }

  if (mode_should_close_cooling(SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE, false)) {
    open_valve(false, true);
    mode_stop_cooling_pump_if_started();
  }

  //Проверяем, что температурные параметры не вышли за предельные значения
  mode_request_overheat_emergency_if_needed();

  //Проверим, что вода подается
  mode_request_water_flow_emergency_if_needed();

  if (mode_water_pre_alarm_due()) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    SendMsg(("Критическая температура воды!"), WARNING_MSG);

#ifdef SAMOVAR_USE_POWER
    //Попробуем снизить мощность на 5 В/шагов регулятора, чтобы исключить перегрев колонны.
    mode_reduce_power_for_water_alarm_by_volts("Критическая температура воды! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt, 5);
#endif
    mode_set_alarm_pause_ms(30000);
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void bk_finish() {
  ProgramNum = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  stop_process("Работа бражной колонны завершена");
}
