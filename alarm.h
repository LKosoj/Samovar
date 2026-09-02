#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"
#include "safety_transition.h"

#ifndef EMERGENCY_STOP_REASON_LEN
#define EMERGENCY_STOP_REASON_LEN 192
#endif

extern portMUX_TYPE emergencyStopMux;
extern volatile bool pending_emergency_stop_flag;
extern volatile bool pending_emergency_stop_reason_flag;
extern char pending_emergency_stop_reason[EMERGENCY_STOP_REASON_LEN];
extern char latched_emergency_stop_reason[EMERGENCY_STOP_REASON_LEN];

// [T13] Латч "останов дозирующего насоса по I2C при аварии не подтверждён" -
// взводится, когда attempt_i2c_pump_emergency_stop() не смог гарантированно
// остановить насос (шина занята/плата не ответила), и снимается только
// подтверждённым нулём скорости. Пока взведён, секундный тикер (Samovar.ino,
// сразу после refresh_i2c_stepper_cache) повторяет попытку по свежему кэшу шины.
static volatile bool i2c_pump_stop_unconfirmed = false;

inline bool samovar_process_active() {
  return PowerOn || startval != SAMOVAR_STARTVAL_IDLE || SamovarStatusInt != SAMOVAR_STATUS_IDLE;
}

inline bool sensor_configured(const DSSensor& sensor) {
  return sensor.Sensor[0] != 0xFF;
}

// [П18] avgTemp/ErrCount пишутся из задачи опроса датчиков, а читаются здесь
// (аварийный надзор) как согласованная пара. Раздельные обращения к полям могут
// разъехаться (torn read): либо ложный останов на исправном датчике, либо, хуже,
// "показание валидно" на только что отказавшем. Лок сюда брать нельзя - аварийный
// путь обязан отработать всегда, а не ждать чужой захват. Вместо лока - seqlock без
// отдельного счётчика версии: читаем пару дважды подряд и доверяем ей, только если
// оба раза совпало; иначе запись пересеклась с окном чтения - повторяем. Запись
// идёт раз в секунду, поэтому на практике сходится с первой попытки.
inline bool sensor_reading_valid(const DSSensor& sensor) {
  for (uint8_t attempt = 0; attempt < 4; attempt++) {
    int e1 = sensor.ErrCount;
    float t1 = sensor.avgTemp;
    int e2 = sensor.ErrCount;
    float t2 = sensor.avgTemp;
    if (e1 == e2 && t1 == t2) {
      int errCount = e1;
      float avgTemp = t1;
      return errCount >= 0 && errCount <= 10 && avgTemp >= 2.0f && avgTemp < 126.0f;
    }
  }
  return false;  // не удалось согласовать снимок - трактуем как невалидное показание (fail-safe)
}

inline bool sensor_valid(const DSSensor& sensor) {
  return sensor_configured(sensor) && sensor_reading_valid(sensor);
}

inline bool optional_sensor_failed(const DSSensor& sensor) {
  return sensor_configured(sensor) && !sensor_reading_valid(sensor);
}

inline bool rectification_ds_sensors_assigned() {
  return sensor_configured(SteamSensor) &&
         sensor_configured(WaterSensor) &&
         sensor_configured(TankSensor);
}

inline void notify_rectification_sensors_unassigned() {
  SendMsg(
      "Датчики не назначены. Откройте настройки и привяжите датчики пара, воды и куба.",
      WARNING_MSG);
}

inline bool sensor_temp_at_least(const DSSensor& sensor, float temp) {
  if (!sensor_configured(sensor)) return false;
  for (uint8_t attempt = 0; attempt < 4; attempt++) {
    int e1 = sensor.ErrCount;
    float t1 = sensor.avgTemp;
    int e2 = sensor.ErrCount;
    float t2 = sensor.avgTemp;
    if (e1 == e2 && t1 == t2) {
      int errCount = e1;
      float avgTemp = t1;
      return errCount >= 0 && errCount <= 10 && avgTemp >= 2.0f && avgTemp < 126.0f && avgTemp >= temp;
    }
  }
  return false;
}

inline void request_emergency_stop(const String& reason) {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool first_alarm = emergency_trip_heater_outputs_locked();
  if (first_alarm) {
    // Причина живёт столько же, сколько защёлка (до перезагрузки). SendMsg в кольцо
    // событий может вытеснить Lua/логом; оператор всё равно должен видеть, почему
    // нагрев заблокирован.
    const char* text = "Аварийное отключение!";
    size_t length = sizeof("Аварийное отключение!") - 1U;
    if (reason.length() > 0) {
      text = reason.c_str();
      length = reason.length();
    }
    if (length >= EMERGENCY_STOP_REASON_LEN) length = EMERGENCY_STOP_REASON_LEN - 1U;
    memcpy(latched_emergency_stop_reason, text, length);
    latched_emergency_stop_reason[length] = '\0';
    memcpy(pending_emergency_stop_reason, latched_emergency_stop_reason, length + 1U);
    pending_emergency_stop_reason_flag = true;
  }
  pending_emergency_stop_flag = true;
  portEXIT_CRITICAL(&emergencyStopMux);

  notify_power_worker();
  set_buzzer(true);
}

// [T13] Пытается остановить дозирующий насос по I2C с обязательным
// подтверждением (stop_i2c_pump_confirmed). Неудача взводит латч и один раз
// пишет код отказа в журнал; удача снимает латч. Общая точка входа для
// perform_emergency_stop() (первая попытка) и retry_i2c_pump_stop_if_unconfirmed()
// (повторы из секундного тикера).
inline void attempt_i2c_pump_emergency_stop() {
  if (stop_i2c_pump_confirmed()) {
    i2c_pump_stop_unconfirmed = false;
    return;
  }
  if (!i2c_pump_stop_unconfirmed) WriteConsoleLog(F("i2c_pump_stop_unconfirmed"));
  i2c_pump_stop_unconfirmed = true;
}

// [T13] Повтор из секундного тикера: пока латч взведён, насос мог остаться
// включённым - повторяем останов по свежему кэшу I2C, пока плата не подтвердит.
inline void retry_i2c_pump_stop_if_unconfirmed() {
  if (i2c_pump_stop_unconfirmed) attempt_i2c_pump_emergency_stop();
}

inline void perform_emergency_stop() {
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

  set_power(false);
  // [П67] Решение владельца от 23.08.2026: воду охлаждения при аварийном останове
  // ЗАКРЫВАЕМ (не оставляем открытой). Мотив - защита от залива помещения при
  // обрыве шланга/отказе клапана, который сам мог стать причиной этой аварии.
  // Известный побочный эффект: при останове именно по перегреву горячая колонна
  // остаётся без дефлегмации, и пар какое-то время идёт в помещение. Компромисс
  // осознанный; менять поведение без нового решения владельца нельзя.
  open_valve(false, true);
  stopService();
  attempt_i2c_pump_emergency_stop();
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
#endif

  // Мешалка (beer.h): обе штатные точки её выключения - beer_stage_tick() и
  // check_mixer_state() - начинаются с проверки взведённого аварийного латча
  // и в аварии (латч уже взведён) не выполнятся, поэтому set_mixer_state(false,...)
  // не вызвать. Повторяем ровно ту же запись реле, что и штатное выключение
  // (beer.h::set_mixer_state), чтобы полярность реле осталась настраиваемой.
  digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  mixer_status = false;

  reset_process_state();
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
  static bool unassignedSensorsHandled = false;
  //сбросим паузу события безопасности
  mode_clear_alarm_pause_if_expired();

  if (!PowerOn) {
    unassignedSensorsHandled = false;
  } else if (!rectification_ds_sensors_assigned()) {
    // Не назначены (адрес 0xFF) — это конфигурация, не отказ датчика в процессе.
    // Сирена и аварийная защёлка здесь мешают открыть настройки. Нагрев гасим
    // штатной командой; emergency только если очередь команд не приняла POWER_OFF.
    if (!unassignedSensorsHandled) {
      notify_rectification_sensors_unassigned();
      if (!queue_samovar_command(SAMOVAR_POWER_OFF)) {
        request_emergency_stop("Аварийное отключение! Ректификация: датчики не назначены");
      }
      unassignedSensorsHandled = true;
    }
    return;
  } else {
    if (optional_sensor_failed(SteamSensor) && process_sensor_failed("Ректификация", "пара")) return;
    if (!mode_check_powered_cooling_sensors("Ректификация")) return;
    if (optional_sensor_failed(TankSensor) && process_sensor_failed("Ректификация", "куба")) return;
  }

#ifdef SAMOVAR_USE_POWER
  //управляем разгонным тэном
  // [L-34] avgTemp >= 2 — идиома «датчик подключён» (аналогично check_boiling).
  // При отсутствующем/замёрзшем датчике куба (avgTemp == 0 или < 2) разгонный ТЭН
  // НЕ управляется — иначе он не выключится никогда.
  if (SamovarStatusInt == SAMOVAR_STATUS_RECT_ACCEL && TankSensor.avgTemp >= 2 && TankSensor.avgTemp <= OPEN_VALVE_TANK_TEMP && PowerOn) {
    if (!acceleration_heater) {
      //включаем разгонный тэн
      acceleration_heater = heater_enable_outputs(SAFETY_HEATER_OUTPUT_BOOST);
    }
  } else {
    if (acceleration_heater) {
      //выключаем разгонный тэн
      heater_boost_output_off();
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
      // [T14 п.1] Нижняя граница - без неё уход ниже порога SLEEP бесшумно гасит нагрев.
      set_current_power(max(target_power_volt - target_power_volt / 100 * 3, power_work_mode_threshold()));
#else
      set_current_power(max(target_power_volt - 1 * PWR_FACTOR, power_work_mode_threshold()));
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
    set_buzzer(true);
    open_valve(true, true);
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
  // [Б8] Оставлено отключённым намеренно (решение владельца): в ректификации момент
  // кипения фиксируется раньше и надёжнее - при переходе разгон -> стабилизация
  // set_boiling() вызывается напрямую (ниже, ветка SAMOVAR_STATUS_RECT_STABILIZING
  // && !boil_started). Кроме того, check_boiling() (logic.h) требует valve_status
  // (открытый клапан воды), а он открывается только при TankSensor.avgTemp >=
  // OPEN_VALVE_TANK_TEMP (77 C) - то есть до конца разгона возвращала бы false вхолостую.

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
      if (!queue_samovar_command(SAMOVAR_POWER)) {
        //Штатное завершение не поставлено: очередь занята или не создалась при старте.
        //Ждать следующего цикла нельзя - условие TankSensor.avgTemp >= DistTemp удерживает
        //нас в этой ветке, else с аварийным стопом уже недостижим, и нагрев остался бы
        //включённым до выкипания. Глушим напрямую: хуже по UX, но единственное безопасное
        //направление отказа.
        request_emergency_stop("Аварийное отключение! Не удалось штатно завершить программу по температуре куба");
      }
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
      SendMsg("Критическая температура воды! Ошибка подачи воды. " + (String)PWR_MSG + " снижаем с " + (String)mode_water_alarm_power_base(), ALARM_MSG);
      // [T14 п.1] Нижняя граница - см. симметричный клэмп в reduce_power_by_volts().
      set_current_power(max(mode_water_alarm_power_base() - mode_water_alarm_power_base() / 100 * 8, power_work_mode_threshold()));
    }
#else
    //Попробуем снизить напряжение регулятора на 5 вольт, чтобы исключить перегрев колонны.
    mode_reduce_power_for_water_alarm_by_volts("Критическая температура воды! Ошибка подачи воды. " + (String)PWR_MSG + " снижаем с " + (String)mode_water_alarm_power_base(), 5);
#endif
#endif
    mode_set_alarm_pause_ms(30000);
  }

  if (SamovarStatusInt == SAMOVAR_STATUS_RECT_ACCEL && SteamSensor.avgTemp >= CHANGE_POWER_MODE_STEAM_TEMP) {
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
        SamovarStatusInt = SAMOVAR_STATUS_RECT_STABILIZING;

        // Инициализируем переменные для проверки стабилизации
        acceleration_temp = 0;

#ifdef COLUMN_WETTING
        // Помечаем, что после стабилизации нужно автоматически перейти к головам
        wetting_autostart = (startval == SAMOVAR_STARTVAL_IDLE);
#endif

        SendMsg("Разгон завершён. Стабилизация/работа на себя.", NOTIFY_MSG);
        set_buzzer(true);
#ifdef SAMOVAR_USE_POWER
        apply_program_power_row(program[0].Power);
#else
        set_current_power_mode_value(POWER_WORK_MODE);
        heater_boost_output_off();
#endif
    }
  }

  // [Б6.4] Фиксация кипения периодическая, а не одноразовая. Обычный сценарий: колонна
  // прогревается ДО отбора, переход RECT_ACCEL -> RECT_STABILIZING (выше) уже требует
  // SteamSensor.avgTemp >= CHANGE_POWER_MODE_STEAM_TEMP, поэтому в RECT_STABILIZING кипение
  // фиксируется сразу. Но при раннем старте отбора (оператор нажал "Старт" ДО конца
  // стабилизации - браузер только предупреждает и просит подтверждение, не запрещает)
  // статус RECT_STABILIZING проскакивается и сразу становится RECT_WITHDRAWAL: без разрешения
  // фиксировать кипение и в этом статусе boil_started остался бы false до конца перегона, а
  // get_alcohol()/get_steam_alcohol() отдавали бы заглушку 100% вместо реальной крепости.
  // Порог по температуре пара здесь ОБЯЗАТЕЛЕН: он единственное, что не даёт зафиксировать
  // кипение по ХОЛОДНОЙ колонне в RECT_WITHDRAWAL - иначе set_boiling() запомнит заниженную
  // текущую температуру куба как температуру кипения, и вся спиртуозность будет неверной.
  // В RECT_STABILIZING порог поведение не меняет (см. обоснование выше).
  if ((SamovarStatusInt == SAMOVAR_STATUS_RECT_STABILIZING || SamovarStatusInt == SAMOVAR_STATUS_RECT_WITHDRAWAL) &&
      !boil_started && SteamSensor.avgTemp >= CHANGE_POWER_MODE_STEAM_TEMP) {
    set_boiling();
    if (boil_started) {
      SendMsg("Спиртуозность " + format_float(alcohol_s, 1), WARNING_MSG);
    }
  }

  //Разгон и стабилизация завершены - шесть минут температура пара не меняется больше, чем на 0.1 градус:
  //https://alcodistillers.ru/forum/viewtopic.php?id=137 - указано 3 замера раз в три минуты.
  if (SamovarStatusInt == SAMOVAR_STATUS_RECT_STABILIZING && SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
    static float prev_stable_temp = 0;  // Предыдущая температура для проверки стабилизации
    float d = SteamSensor.avgTemp - prev_stable_temp;
    d = abs(d);
    if (d < 0.1) {
      acceleration_temp += 1;
      // >= вместо == : acceleration_temp доступна Lua на запись (диапазон 0..UINT16_MAX,
      // см. lua.h) и может "перескочить" 360, тогда == никогда не станет истинным.
      if (acceleration_temp >= 60 * 6) {
        SamovarStatusInt = SAMOVAR_STATUS_RECT_STABLE;
        acceleration_temp = 0;  // Сбрасываем счетчик после установки статуса стабилизации
        prev_stable_temp = 0;  // Сбрасываем предыдущую температуру
        set_buzzer(true);
        SendMsg(("Стабилизация завершена, колонна работает стабильно."), NOTIFY_MSG);
#ifdef COLUMN_WETTING
        if (wetting_autostart && startval == SAMOVAR_STARTVAL_IDLE) {
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
