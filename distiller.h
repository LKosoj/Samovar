#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"
#include "program_io.h"

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

/**
 * @brief Структура для прогнозирования времени процесса дистилляции.
 */
struct TimePredictor {
    unsigned long startTime;           ///< Время начала процесса
    float initialAlcohol;              ///< Начальное содержание спирта
    float initialTemp;                 ///< Начальная температура
    float lastTemp;                    ///< Последняя температура
    float tempChangeRate;              ///< Скорость изменения температуры
    unsigned long lastUpdateTime;      ///< Время последнего обновления
    float predictedTotalTime;          ///< Прогнозируемое общее время (мин)
    float remainingTime;               ///< Оставшееся время (мин)
};

TimePredictor timePredictor = {0, 0, 0, 0, 0, 0, 0, 0};
// Минимальные пороги, чтобы не делить на ноль и не спамить оценками
static constexpr float MIN_TEMP_RATE = 0.01f;    // °C/мин
static constexpr float MIN_ALC_RATE  = 0.001f;   // доля/мин
static constexpr unsigned long PREDICTOR_UPDATE_MS = 30000; // шаг пересчёта, мс

/**
 * @brief Основной цикл обработки процесса дистилляции.
 *
 * Вызывает обработку текущего этапа, обновляет прогноз времени, контролирует аварии и переходы между этапами.
 */
void distiller_proc() {
//    SendMsg("Статус: " + String(SamovarStatusInt) + 
//            ", Режим: " + String(Samovar_Mode) + 
//            ", PowerOn: " + String(PowerOn), NOTIFY_MSG);
    
  if (SamovarStatusInt != 1000) return;

  if (!sensor_valid(TankSensor) && process_sensor_failed("Дистилляция", "куба")) return;

  if (!PowerOn || mode_heating_start_pending(1000)) {
    if (mode_run_heating_start(
          1000,
          "Ошибка создания файла лога. Старт дистилляции отменён.",
          "Описание сессии занято. Старт дистилляции отменён.",
          get_dist_program(),
          "Включен нагрев дистиллятора",
          true) != MODE_HEATING_START_SUCCEEDED) return;
    run_dist_program(0);
    d_s_temp_prev = WaterSensor.avgTemp;
#ifdef SAMOVAR_USE_POWER
    heater_enable_outputs(SAFETY_HEATER_OUTPUT_BOOST);
#endif
    // Инициализируем систему прогнозирования
    resetTimePredictor();
  }

  // Обновляем прогноз времени
  updateTimePredictor();

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    distiller_finish();
    return;
  }

  //Обрабатываем программу дистилляции (только если есть программы для выполнения)
  if (ProgramNum < ProgramLen && !program_type_empty(program[ProgramNum].WType)) {
    if (program[ProgramNum].WType == 'T' && program[ProgramNum].Speed <= TankSensor.avgTemp) {
      //Если температура куба превысила заданное в программе значение - переходим на следующую строку программы
      run_dist_program(ProgramNum + 1);
    } else if (program[ProgramNum].WType == 'A' && program[ProgramNum].Speed >= get_alcohol(TankSensor.avgTemp)) {
      //Если спиртуозность в кубе понизилась до заданного в программе значения - переходим на следующую строку программы
      run_dist_program(ProgramNum + 1);
    } else if (program[ProgramNum].WType == 'S') {
      float startAlcohol = get_alcohol(TankSensor.StartProgTemp);
      if (startAlcohol > 0 && program[ProgramNum].Speed >= get_alcohol(TankSensor.avgTemp) / startAlcohol) {
        run_dist_program(ProgramNum + 1);
      }
    } else if (program[ProgramNum].WType == 'P' && program[ProgramNum].Speed >= get_steam_alcohol(TankSensor.avgTemp)) {
      //Если спиртуозность в кубе понизилась до заданного в программе значения - переходим на следующую строку программы
      run_dist_program(ProgramNum + 1);
    } else if (program[ProgramNum].WType == 'R') {
      float startSteamAlcohol = get_steam_alcohol(TankSensor.StartProgTemp);
      if (startSteamAlcohol > 0 && program[ProgramNum].Speed >= get_steam_alcohol(TankSensor.avgTemp) / startSteamAlcohol) {
        run_dist_program(ProgramNum + 1);
      }
    }
  }


  //Если Т в кубе больше 90 градусов и включено напряжение и DistTimeF > 0, проверяем, что DistTimeF минут температура в кубе не меняется от последнего заполненного значения больше, чем на 0.1 градус
  if (TankSensor.avgTemp > 90 && PowerOn && SamSetup.DistTimeF > 0) {
    if (abs(TankSensor.avgTemp - d_s_temp_finish) > 0.1) {
      d_s_temp_finish = TankSensor.avgTemp;
      d_s_time_min = millis();
    } else if ((millis() - d_s_time_min) > SamSetup.DistTimeF * 60 * 1000) {
      SendMsg(("В кубе не осталось спирта"), NOTIFY_MSG);
      distiller_finish();
    }
  }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void distiller_finish() {
  ProgramNum = 0;
  startval = 0;
  String timeMsg = "Дистилляция завершена. Общее время: " + String(int((millis() - timePredictor.startTime) / 60000)) + " мин.";
  stop_process(timeMsg);
}


void check_alarm_distiller() {
  //сбросим паузу события безопасности
  mode_clear_alarm_pause_if_expired();

  if (PowerOn && !mode_check_powered_cooling_sensors("Дистилляция")) return;

#ifdef SAMOVAR_USE_POWER
  check_power_error();
#endif

  if (mode_should_open_cooling(false, true, true)) {
    if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP - 5)) {
      set_buzzer(true);
      open_valve(true, true);
    }
    else if (TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP && PowerOn) {
      set_buzzer(true);
      open_valve(true, true);
    }
  }

  if (mode_should_close_cooling(SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE, false)) {
    open_valve(false, true);
    mode_stop_cooling_pump_if_started();
  }

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  check_boiling();

  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  mode_update_water_pump_pid(SamSetup.SetACPTemp);

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((WaterSensor.avgTemp >= MAX_WATER_TEMP || sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP)) && PowerOn) {
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    String s = "";
    if (WaterSensor.avgTemp >= MAX_WATER_TEMP)
      s = s + " Воды";
    if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP))
      s = s + " ТСА";
    request_emergency_stop("Аварийное отключение! Превышена максимальная температура" + s);
  }

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

  mode_update_water_valve_by_setpoint();
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void run_dist_program(uint8_t num) {
  // Проверяем, что номер программы не превышает количество программ
  if (num >= ProgramLen || program_type_empty(program[num].WType)) {
    // Программы закончились - устанавливаем ProgramNum = ProgramLen, чтобы условие ProgramNum < ProgramLen стало ложным
    if (ProgramNum < ProgramLen) {
      ProgramNum = ProgramLen;
      SendMsg("Выполнение программ закончилось, продолжение отбора", NOTIFY_MSG);
    }
    return;
  }

  ProgramNum = num;

  SendMsg("Переход к строке программы №" + (String)(num + 1), NOTIFY_MSG);
  // Сбрасываем прогноз при переходе к новой программе
  resetTimePredictor();

  //запоминаем текущие значения температур
  SteamSensor.StartProgTemp = SteamSensor.avgTemp;
  PipeSensor.StartProgTemp = PipeSensor.avgTemp;
  WaterSensor.StartProgTemp = WaterSensor.avgTemp;
  TankSensor.StartProgTemp = TankSensor.avgTemp;

  if (num > 0) {
    set_capacity(program[num - 1].capacity_num);
    if (!program_type_empty(program[num - 1].WType)) {
#ifdef SAMOVAR_USE_POWER
#ifdef SAMOVAR_USE_SEM_AVR
      if (abs(program[num - 1].Power) > 400 && program[num - 1].Power > 0) {
#else
      if (abs(program[num - 1].Power) > 40 && program[num - 1].Power > 0) {
#endif
        set_current_power(program[num - 1].Power);
      } else if (program[num - 1].Power != 0) {
        set_current_power(target_power_volt + program[num - 1].Power);
      }
#endif
    }
  }

}

ProgramParseResult set_dist_program(const String& WProgram) {
  return program_parse_lines(WProgram, dist_program_parse_spec());
}

String get_dist_program() {
  return program_serialize_rows(0, PROGRAM_END, program_append_dist_row);
}

void resetTimePredictor() {
    timePredictor.startTime = millis();
    timePredictor.initialAlcohol = get_alcohol(TankSensor.avgTemp);
    timePredictor.initialTemp = TankSensor.avgTemp;
    timePredictor.lastTemp = TankSensor.avgTemp;
    timePredictor.lastUpdateTime = millis();
    timePredictor.tempChangeRate = 0;
    timePredictor.predictedTotalTime = 0;
    timePredictor.remainingTime = 0;
}

void updateTimePredictor() {
    unsigned long currentTime = millis();
    float currentTemp = TankSensor.avgTemp;
    float currentAlcohol = get_alcohol(currentTemp);

    unsigned long dtMs = currentTime - timePredictor.lastUpdateTime;
    if (dtMs < PREDICTOR_UPDATE_MS) return; // считаем не чаще, чем нужно

    float dtMin = dtMs / 60000.0f;
    timePredictor.tempChangeRate = (currentTemp - timePredictor.lastTemp) / dtMin; // °C/мин
    timePredictor.lastTemp = currentTemp;
    timePredictor.lastUpdateTime = currentTime;

    // Обновляем прогноз по спирту (используем долю, а не %)
    float alcoholDelta = timePredictor.initialAlcohol - currentAlcohol;
    float alcoholChangeRate = (dtMin > 0) ? (alcoholDelta / ((currentTime - timePredictor.startTime) / 60000.0f)) : 0; // доля/мин

    // Если программы закончились, не делаем прогноз
    if (ProgramNum >= ProgramLen || program_type_empty(program[ProgramNum].WType)) {
        timePredictor.remainingTime = 0;
        float elapsedMinutes = (currentTime - timePredictor.startTime) / 60000.0f;
        timePredictor.predictedTotalTime = elapsedMinutes;
        return;
    }

    float remaining = 0;
    ProgramType wtype = program[ProgramNum].WType;

    if (wtype == 'T') {
        float targetTemp = program[ProgramNum].Speed;
        float dT = targetTemp - currentTemp;
        if (dT <= 0) {
            remaining = 0;
        } else if (timePredictor.tempChangeRate > MIN_TEMP_RATE) {
            remaining = dT / timePredictor.tempChangeRate;
        }
    } else if (wtype == 'A' || wtype == 'S') {
        float targetAlcohol = program[ProgramNum].Speed;
        if (wtype == 'S') {
            targetAlcohol *= get_alcohol(TankSensor.StartProgTemp);
        }
        float dA = currentAlcohol - targetAlcohol;
        if (dA <= 0) {
            remaining = 0;
        } else if (alcoholChangeRate > MIN_ALC_RATE) {
            remaining = dA / alcoholChangeRate;
        }
    } else if (wtype == 'P' || wtype == 'R') {
        // Ориентируемся на крепость пара
        float currentSteamAlcohol = get_steam_alcohol(currentTemp);
        float target = program[ProgramNum].Speed;
        if (wtype == 'R') {
            target *= get_steam_alcohol(TankSensor.StartProgTemp);
        }
        float dS = currentSteamAlcohol - target;
        if (dS <= 0) {
            remaining = 0;
        } else if (alcoholChangeRate > MIN_ALC_RATE) {
            remaining = dS / alcoholChangeRate;
        }
    } else {
        // Для прочих шагов оставляем 0 — нет метрики для прогноза
        remaining = 0;
    }

    timePredictor.remainingTime = max(0.0f, remaining);
    float elapsedMinutes = (currentTime - timePredictor.startTime) / 60000.0f;
    timePredictor.predictedTotalTime = elapsedMinutes + timePredictor.remainingTime;
}

float get_dist_remaining_time() {
    return timePredictor.remainingTime;
}

float get_dist_predicted_total_time() {
    return timePredictor.predictedTotalTime;
}
