#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"

#ifndef EMERGENCY_STOP_REASON_LEN
#define EMERGENCY_STOP_REASON_LEN 192
#endif

extern portMUX_TYPE emergencyStopMux;
extern volatile bool pending_emergency_stop_flag;
extern volatile bool pending_emergency_stop_reason_flag;
extern char pending_emergency_stop_reason[EMERGENCY_STOP_REASON_LEN];

inline bool samovar_process_active() {
  return PowerOn || startval != 0 || SamovarStatusInt != 0;
}

inline bool sensor_configured(const DSSensor& sensor) {
  return sensor.Sensor[0] != 0xFF;
}

inline bool sensor_reading_valid(const DSSensor& sensor) {
  return sensor.ErrCount >= 0 && sensor.ErrCount <= 10 &&
         sensor.avgTemp >= 2.0f && sensor.avgTemp < 126.0f;
}

inline bool sensor_valid(const DSSensor& sensor) {
  return sensor_configured(sensor) && sensor_reading_valid(sensor);
}

inline bool optional_sensor_failed(const DSSensor& sensor) {
  return sensor_configured(sensor) && !sensor_reading_valid(sensor);
}

inline bool sensor_temp_at_least(const DSSensor& sensor, float temp) {
  return sensor_configured(sensor) && sensor_reading_valid(sensor) && sensor.avgTemp >= temp;
}

void request_emergency_stop(const String& reason) {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool first_alarm = !alarm_event;
  alarm_event = true;
  if (first_alarm && reason.length() > 0) {
    copyStringSafe(pending_emergency_stop_reason, reason);
    pending_emergency_stop_reason_flag = true;
  }
  pending_emergency_stop_flag = true;
  portEXIT_CRITICAL(&emergencyStopMux);

  set_buzzer(true);
}

void perform_emergency_stop() {
  char reason[EMERGENCY_STOP_REASON_LEN];
  reason[0] = '\0';
  bool send_reason = false;

  portENTER_CRITICAL(&emergencyStopMux);
  pending_emergency_stop_flag = false;
  alarm_event = true;
  if (pending_emergency_stop_reason_flag) {
    memcpy(reason, pending_emergency_stop_reason, sizeof(reason));
    reason[sizeof(reason) - 1] = '\0';
    pending_emergency_stop_reason[0] = '\0';
    pending_emergency_stop_reason_flag = false;
    send_reason = true;
  }
  portEXIT_CRITICAL(&emergencyStopMux);

  if (send_reason) SendMsg(String(reason), ALARM_MSG);

  if (Samovar_Mode == SAMOVAR_NBK_MODE) nbk_emergency_finish();

  if (PowerOn) {
    set_power(false);
  } else {
    if (!queue_samovar_reset_command()) SendMsg("Очередь команд занята: аварийный reset не поставлен", ALARM_MSG);
  }
  open_valve(false, true);
  stopService();
  set_stepper_target(0, 0, 0);
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
#endif
}

bool process_sensor_failed(const char* modeName, const char* sensorName) {
  request_emergency_stop(String("Аварийное отключение! ") + modeName + ": нет данных датчика " + sensorName);
  return true;
}

// Установить сигнализацию
void set_alarm() {
  request_emergency_stop("Аварийное отключение!");
}

void check_alarm() {
  static bool close_valve_message_sent = false;
  //сбросим паузу события безопасности
  mode_clear_alarm_pause_if_expired();

  if (PowerOn) {
    if (!sensor_valid(SteamSensor) && process_sensor_failed("Ректификация", "пара")) return;
    if (!mode_check_powered_cooling_sensors("Ректификация")) return;
    if (!sensor_valid(TankSensor) && process_sensor_failed("Ректификация", "куба")) return;
  }

#ifdef SAMOVAR_USE_POWER
  //управляем разгонным тэном
  // [L-34] avgTemp >= 2 — идиома «датчик подключён» (аналогично check_boiling).
  // При отсутствующем/замёрзшем датчике куба (avgTemp == 0 или < 2) разгонный ТЭН
  // НЕ управляется — иначе он не выключится никогда.
  if (SamovarStatusInt == 50 && TankSensor.avgTemp >= 2 && TankSensor.avgTemp <= OPEN_VALVE_TANK_TEMP && PowerOn) {
    if (!acceleration_heater) {
      //включаем разгонный тэн
      digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
      acceleration_heater = true;
    }
  } else {
    if (acceleration_heater) {
      //выключаем разгонный тэн
      digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      acceleration_heater = false;
    }
  }
#endif

  //Если используется датчик уровня флегмы в голове
#ifdef USE_HEAD_LEVEL_SENSOR
  if (SamSetup.UseHLS && PowerOn) {
    ProgramType currentType = current_program_type();
    if (head_level_sensor_holded() && alarm_h_min == 0) {
      if (currentType != 'C') {
        set_buzzer(true);
        SendMsg(("Сработал датчик захлёба!"), ALARM_MSG);
#ifdef SAMOVAR_USE_POWER
        alarm_c_min = 0;
        alarm_c_low_min = 0;
        prev_target_power_volt = 0;
#endif
      } else {
#ifdef SAMOVAR_USE_POWER
        //запускаем счетчик - TIME_C/5 минут, нужен для возврата заданного напряжения
        alarm_c_min = millis() + 1000 * 60 * TIME_C / 5;
        //счетчик для повышения напряжения сбрасываем
        alarm_c_low_min = 0;
        if (prev_target_power_volt == 0) prev_target_power_volt = target_power_volt;
#endif
      }
#ifdef SAMOVAR_USE_POWER
      SendMsg((String)PWR_MSG + " снижаем с " + (String)target_power_volt, NOTIFY_MSG);
#ifdef SAMOVAR_USE_SEM_AVR
      set_current_power(target_power_volt - target_power_volt / 100 * 3);
#else
      set_current_power(target_power_volt - 1 * PWR_FACTOR);
#endif
#endif
      //Если уже реагировали - надо подождать 40 секунд, так как процесс инерционный
      alarm_h_min = millis() + 1000 * 40;
    }

    // [C-13] overflow-safe
    if (alarm_h_min > 0 && (int32_t)(millis() - alarm_h_min) >= 0) {
      alarm_h_min = 0;
    }
#ifdef SAMOVAR_USE_POWER
    //Если программа - предзахлеб, и сброс напряжения был больше TIME_C минут назад, то возвращаем напряжение к последнему сохраненному - 0.5
    // [C-13] overflow-safe
    if (alarm_c_min > 0 && (int32_t)(millis() - alarm_c_min) >= 0) {
      if (currentType == 'C') {
        if (prev_target_power_volt == 0) {
#ifdef SAMOVAR_USE_SEM_AVR
          prev_target_power_volt = target_power_volt + target_power_volt / 100 * 4;
#else
          prev_target_power_volt = target_power_volt + 2 * PWR_FACTOR;
#endif
        }
#ifdef SAMOVAR_USE_SEM_AVR
        set_current_power(prev_target_power_volt - target_power_volt / 100 * 3);
#else
        set_current_power(prev_target_power_volt - 1 * PWR_FACTOR);
#endif
        SendMsg((String)PWR_MSG + " повышаем до " + (String)target_power_volt, NOTIFY_MSG);
        prev_target_power_volt = 0;
        //запускаем счетчик - TIME_C минут, нужен для повышения текущего напряжения чтобы поймать предзахлеб
        alarm_c_low_min = millis() + 1000 * 60 * TIME_C;
      }
      alarm_c_min = 0;
    }
    //Если программа предзахлеб и давно не было срабатывания датчика - повышаем напряжение
    if (currentType == 'C') {
      // [C-13] overflow-safe
      if (alarm_c_low_min > 0 && (int32_t)(millis() - alarm_c_low_min) >= 0) {
#ifdef SAMOVAR_USE_SEM_AVR
        set_current_power(target_power_volt + target_power_volt / 100 * 1);
#else
        set_current_power(target_power_volt + 0.5 * PWR_FACTOR);
#endif
        alarm_c_low_min = millis() + 1000 * 60 * TIME_C;
      } else if (alarm_c_low_min == 0 && alarm_c_min == 0) {
        alarm_c_low_min = millis() + 1000 * 60 * TIME_C;
      }
    } else alarm_c_low_min = 0;

#endif
  }
  //Если используется датчик уровня флегмы в голове
#endif


#ifdef SAMOVAR_USE_POWER
  check_power_error();
#endif

  if (mode_should_open_cooling(false, true, true)) {
    if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP - 5)) {
      set_buzzer(true);
      open_valve(true, true);
    } else if (TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP && PowerOn) {
      set_buzzer(true);
      open_valve(true, true);
    }
  }

  if (mode_should_close_cooling(SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE, true)) {
    if (!close_valve_message_sent) {
      open_valve(false, true);
      set_buzzer(true);
      close_valve_message_sent = true;
    }
    mode_stop_cooling_pump_if_started();
  }
  if (valve_status && close_valve_message_sent)  {
    close_valve_message_sent = false;
  }

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  //check_boiling();

  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  mode_update_water_pump_pid(39.0f);

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((SteamSensor.avgTemp >= MAX_STEAM_TEMP || WaterSensor.avgTemp >= MAX_WATER_TEMP || TankSensor.avgTemp >= SamSetup.DistTemp || sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP)) && PowerOn) {
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    String s = "";
    if (SteamSensor.avgTemp >= MAX_STEAM_TEMP) s = s + " Пара";
    else if (WaterSensor.avgTemp >= MAX_WATER_TEMP)
      s = s + " Воды";
    else if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP))
      s = s + " ТСА";

    if (TankSensor.avgTemp >= SamSetup.DistTemp) {
      //Если температура в кубе превысила заданную, штатно завершаем ректификацию.
      SendMsg(("Лимит максимальной температуры куба. Программа завершена."), NOTIFY_MSG);
      if (!queue_samovar_command(SAMOVAR_POWER)) SendMsg("Очередь команд занята: завершение ректификации не поставлено", WARNING_MSG);
    } else
      request_emergency_stop("Аварийное отключение! Превышена максимальная температура" + s);
  }

  //Проверим, что вода подается
  mode_request_water_flow_emergency_if_needed();

  if (mode_water_pre_alarm_due()) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    SendMsg(("Критическая температура воды!"), WARNING_MSG);

#ifdef SAMOVAR_USE_POWER
#ifdef SAMOVAR_USE_SEM_AVR
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      set_buzzer(true);
      SendMsg("Критическая температура воды! Ошибка подачи воды. " + (String)PWR_MSG + " снижаем с " + (String)target_power_volt, ALARM_MSG);
      set_current_power(target_power_volt - target_power_volt / 100 * 8);
    }
#else
    //Попробуем снизить напряжение регулятора на 5 вольт, чтобы исключить перегрев колонны.
    mode_reduce_power_for_water_alarm_by_volts("Критическая температура воды! Ошибка подачи воды. " + (String)PWR_MSG + " снижаем с " + (String)target_power_volt, 5);
#endif
#endif
    mode_set_alarm_pause_ms(30000);
  }

  if (SamovarStatusInt == 50 && SteamSensor.avgTemp >= CHANGE_POWER_MODE_STEAM_TEMP) {
#ifdef USE_WATER_PUMP
    //Сбросим счетчик насоса охлаждения, что приведет к увеличению потока воды. Дальше уже будет штатно работать PID
    wp_count = -5;
#endif

    bool column_wetting_result = true;
#ifdef COLUMN_WETTING
    // Смачивание насадки колонны
    column_wetting_result = column_wetting();
#endif

    if (column_wetting_result) {

        //достигли заданной температуры на разгоне и смочили насадку (если используется эта функция), переходим на рабочий режим, устанавливаем заданную температуру, зовем оператора
        SamovarStatusInt = 51;

        // Инициализируем переменные для проверки стабилизации
        acceleration_temp = 0;

#ifdef COLUMN_WETTING
        // Помечаем, что после стабилизации нужно автоматически перейти к головам
        wetting_autostart = (startval == 0);
#endif

        SendMsg("Разгон завершён. Стабилизация/работа на себя.", NOTIFY_MSG);
        set_buzzer(true);
#ifdef SAMOVAR_USE_POWER
        set_current_power(program[0].Power);
#else
        set_current_power_mode_value(POWER_WORK_MODE);
        digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
    }
  }

  if (SamovarStatusInt == 51 && !boil_started) {
    set_boiling();
    if (boil_started) {
      SendMsg("Спиртуозность " + format_float(alcohol_s, 1), WARNING_MSG);
    }
  }

  //Разгон и стабилизация завершены - шесть минут температура пара не меняется больше, чем на 0.1 градус:
  //https://alcodistillers.ru/forum/viewtopic.php?id=137 - указано 3 замера раз в три минуты.
  if (SamovarStatusInt == 51 && SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
    static float prev_stable_temp = 0;  // Предыдущая температура для проверки стабилизации
    float d = SteamSensor.avgTemp - prev_stable_temp;
    d = abs(d);
    if (d < 0.1) {
      acceleration_temp += 1;
      if (acceleration_temp == 60 * 6) {
        SamovarStatusInt = 52;
        acceleration_temp = 0;  // Сбрасываем счетчик после установки статуса стабилизации
        prev_stable_temp = 0;  // Сбрасываем предыдущую температуру
        set_buzzer(true);
        SendMsg(("Стабилизация завершена, колонна работает стабильно."), NOTIFY_MSG);
#ifdef COLUMN_WETTING
        if (wetting_autostart && startval == 0) {
          wetting_autostart = false;
          menu_samovar_start();  // Автостарт голов после стабилизации
        }
#endif
      }
    } else {
      acceleration_temp = 0;
      prev_stable_temp = SteamSensor.avgTemp;  // Обновляем предыдущую температуру только при изменении
    }
  }
  mode_update_water_valve_by_setpoint();
}
