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
    unsigned long startTime;           ///< Время начала текущей строки
    unsigned long processStartTime;    ///< Время фактического начала кипения
    float initialAlcohol;              ///< Начальное содержание спирта
    float initialTemp;                 ///< Начальная температура
    float lastTemp;                    ///< Последняя температура
    float tempChangeRate;              ///< Скорость изменения температуры
    unsigned long lastUpdateTime;      ///< Время последнего обновления
    float predictedTotalTime;          ///< Прогнозируемое общее время (мин)
    float remainingTime;               ///< Оставшееся время (мин)
    float initialSteamAlcohol;         ///< Начальная крепость пара (для строк 'P'/'R')
    float processInitialTemp;           ///< Температура на фронте кипения
    float processRemainingTime;         ///< Остаток процесса до DistTemp
    float rowPredictedTotalTime;        ///< Полная оценка текущей строки
    bool baselineValid;                 ///< Крепость и температура захвачены после кипения
    bool rowPredictionAvailable;
    bool processPredictionAvailable;
};

TimePredictor timePredictor = {};
// [П4.6] Время СТАРТА СЕССИИ дистилляции (не строки программы). timePredictor.startTime
// используется предиктором для скорости изменения показателей ВНУТРИ текущей строки и
// намеренно сбрасывается на каждом run_dist_program(); честное «Общее время» сессии
// требует отдельного таймера, который выставляется один раз — при (пере)старте.
unsigned long sessionStartTime = 0;
bool sessionTimerValid = false;
// Фронт-детектор начала кипения для перезахвата TankSensor.StartProgTemp (не static
// внутри функции — нужен сброс между сессиями дистилляции, см. resetTimePredictor()).
bool distBoilStartedPrev = false;
#ifdef SAMOVAR_USE_POWER
// [П4.4] Гейт однократного гашения BOOST-ТЭНа на первом переходе строки программы,
// которая явно задаёт Power (программа начинает управлять мощностью сама).
// Сбрасывается только при (пере)старте дистилляции — НЕ через resetTimePredictor(),
// иначе флаг обнулялся бы на КАЖДОМ переходе строки.
bool distBoostGated = false;
#endif
// Минимальные пороги, чтобы не делить на ноль и не спамить оценками
static constexpr float MIN_TEMP_RATE = 0.01f;    // °C/мин
static constexpr float MIN_ALC_RATE  = 0.001f;   // доля/мин
static constexpr unsigned long PREDICTOR_UPDATE_MS = 30000; // шаг пересчёта, мс

enum DistPredictionReason : uint8_t {
  DIST_PREDICTION_AWAITING_BOIL = 0,
  DIST_PREDICTION_COLLECTING,
  DIST_PREDICTION_READY,
  DIST_PREDICTION_NO_ACTIVE_ROW,
};

DistPredictionReason distRowPredictionReason = DIST_PREDICTION_AWAITING_BOIL;
DistPredictionReason distProcessPredictionReason = DIST_PREDICTION_AWAITING_BOIL;

/**
 * @brief Основной цикл обработки процесса дистилляции.
 *
 * Вызывает обработку текущего этапа, обновляет прогноз времени, контролирует аварии и переходы между этапами.
 */
void distiller_proc() {
//    SendMsg("Статус: " + String(SamovarStatusInt) + 
//            ", Режим: " + String(Samovar_Mode) + 
//            ", PowerOn: " + String(PowerOn), NOTIFY_MSG);
    
  if (SamovarStatusInt != SAMOVAR_STATUS_DISTILLATION) return;

  if (!sensor_valid(TankSensor) && process_sensor_failed("Дистилляция", "куба")) return;

  if (!PowerOn || mode_heating_start_pending(SAMOVAR_STATUS_DISTILLATION)) {
    if (mode_run_heating_start(
          SAMOVAR_STATUS_DISTILLATION,
          "Ошибка создания файла лога. Старт дистилляции отменён.",
          "Описание сессии занято. Старт дистилляции отменён.",
          get_dist_program(),
          "Включен нагрев дистиллятора",
          true) != MODE_HEATING_START_SUCCEEDED) return;
    run_dist_program(0);
    d_s_temp_prev = WaterSensor.avgTemp;
#ifdef SAMOVAR_USE_POWER
    heater_enable_outputs(SAFETY_HEATER_OUTPUT_BOOST);
    distBoostGated = false;
#endif
    // Инициализируем систему прогнозирования
    distBoilStartedPrev = false;
    resetTimePredictor();
    sessionStartTime = millis();
    sessionTimerValid = true;
  }

  // [distiller-cold-start] get_alcohol()/get_steam_alcohol() гейтятся текущим
  // boil_started, а TankSensor.StartProgTemp по умолчанию захватывается при входе
  // в строку программы (run_dist_program), в т.ч. до закипания. Если кипение
  // началось внутри уже идущей строки (без перехода на новую), перезахватываем
  // StartProgTemp по фронту boil_started, чтобы полином не считался по холодной температуре.
  if (boil_started && !distBoilStartedPrev) {
    TankSensor.StartProgTemp = TankSensor.avgTemp;
    resetTimePredictor();
  }
  distBoilStartedPrev = boil_started;

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
  startval = SAMOVAR_STARTVAL_IDLE;
  String timeMsg = "Дистилляция завершена.";
  if (sessionTimerValid) {
    timeMsg += " Общее время: " +
        String(int((millis() - sessionStartTime) / 60000)) + " мин.";
  }
  sessionTimerValid = false;
  sessionStartTime = 0;
  distBoilStartedPrev = false;
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
  mode_request_overheat_emergency_if_needed();

  //Проверим, что вода подается
  mode_request_water_flow_emergency_if_needed();

  mode_handle_water_pre_alarm_if_due();

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
  // Переход строки сбрасывает только строковый baseline. Процессный baseline,
  // захваченный по фактическому фронту кипения, сохраняется до конца сессии.
  timePredictor.startTime = millis();
  timePredictor.initialAlcohol =
      timePredictor.baselineValid ? get_alcohol(TankSensor.avgTemp) : 0.0f;
  timePredictor.initialSteamAlcohol =
      timePredictor.baselineValid ? get_steam_alcohol(TankSensor.avgTemp) : 0.0f;
  timePredictor.initialTemp = TankSensor.avgTemp;
  timePredictor.lastTemp = TankSensor.avgTemp;
  timePredictor.lastUpdateTime = millis();
  timePredictor.tempChangeRate = 0.0f;
  timePredictor.remainingTime = 0.0f;
  timePredictor.rowPredictedTotalTime = 0.0f;
  timePredictor.rowPredictionAvailable = false;
  distRowPredictionReason = timePredictor.baselineValid
      ? DIST_PREDICTION_COLLECTING
      : DIST_PREDICTION_AWAITING_BOIL;

  //запоминаем текущие значения температур
  SteamSensor.StartProgTemp = SteamSensor.avgTemp;
  PipeSensor.StartProgTemp = PipeSensor.avgTemp;
  WaterSensor.StartProgTemp = WaterSensor.avgTemp;
  TankSensor.StartProgTemp = TankSensor.avgTemp;

  if (num > 0) {
    set_capacity(program[num - 1].capacity_num);
    if (!program_type_empty(program[num - 1].WType)) {
#ifdef SAMOVAR_USE_POWER
      apply_program_power_row(program[num - 1].Power);
#endif
    }
  }

#ifdef SAMOVAR_USE_POWER
  // [П4.4] BOOST горит с самого старта дистилляции (см. distiller_proc()) и без
  // явного гашения — до конца сессии. Гасим один раз, когда программа впервые
  // начинает сама управлять мощностью (Power предыдущей строки задан).
  if (num > 0 && !distBoostGated && program[num - 1].Power != 0) {
    heater_boost_output_off();
    distBoostGated = true;
  }
#endif
}

ProgramParseResult set_dist_program(const String& WProgram) {
  return program_parse_lines(WProgram, dist_program_parse_spec());
}

String get_dist_program() {
  return program_serialize_rows(0, PROGRAM_END, program_append_dist_row);
}

void resetTimePredictor() {
    const unsigned long now = millis();
    timePredictor.startTime = now;
    timePredictor.processStartTime = boil_started ? now : 0;
    timePredictor.initialAlcohol = boil_started ? get_alcohol(TankSensor.avgTemp) : 0.0f;
    timePredictor.initialSteamAlcohol =
        boil_started ? get_steam_alcohol(TankSensor.avgTemp) : 0.0f;
    timePredictor.initialTemp = TankSensor.avgTemp;
    timePredictor.processInitialTemp = TankSensor.avgTemp;
    timePredictor.lastTemp = TankSensor.avgTemp;
    timePredictor.lastUpdateTime = now;
    timePredictor.tempChangeRate = 0;
    timePredictor.predictedTotalTime = 0;
    timePredictor.remainingTime = 0;
    timePredictor.processRemainingTime = 0;
    timePredictor.rowPredictedTotalTime = 0;
    timePredictor.baselineValid = boil_started;
    timePredictor.rowPredictionAvailable = false;
    timePredictor.processPredictionAvailable = false;
    distRowPredictionReason = boil_started
        ? DIST_PREDICTION_COLLECTING
        : DIST_PREDICTION_AWAITING_BOIL;
    distProcessPredictionReason = distRowPredictionReason;
}

inline bool calculate_dist_process_remaining(
    float currentTemp,
    float targetTemp,
    float initialTemp,
    float elapsedMinutes,
    float& remainingMinutes) {
    const float delta = targetTemp - currentTemp;
    if (delta <= 0.0f) {
        remainingMinutes = 0.0f;
        return true;
    }
    if (elapsedMinutes <= 0.0f) return false;
    const float rate = (currentTemp - initialTemp) / elapsedMinutes;
    if (rate <= MIN_TEMP_RATE) return false;
    remainingMinutes = delta / rate;
    return true;
}

void updateTimePredictor() {
    if (!timePredictor.baselineValid || !sessionTimerValid) {
        timePredictor.rowPredictionAvailable = false;
        timePredictor.processPredictionAvailable = false;
        distRowPredictionReason = DIST_PREDICTION_AWAITING_BOIL;
        distProcessPredictionReason = DIST_PREDICTION_AWAITING_BOIL;
        return;
    }

    unsigned long currentTime = millis();
    float currentTemp = TankSensor.avgTemp;
    float currentAlcohol = get_alcohol(currentTemp);
    float currentSteamAlcohol = get_steam_alcohol(currentTemp);

    unsigned long dtMs = currentTime - timePredictor.lastUpdateTime;
    if (dtMs < PREDICTOR_UPDATE_MS) return; // считаем не чаще, чем нужно

    float dtMin = dtMs / 60000.0f;
    timePredictor.tempChangeRate = (currentTemp - timePredictor.lastTemp) / dtMin; // °C/мин
    timePredictor.lastTemp = currentTemp;
    timePredictor.lastUpdateTime = currentTime;

    // Обновляем прогноз по спирту (используем долю, а не %)
    float alcoholDelta = timePredictor.initialAlcohol - currentAlcohol;
    float alcoholChangeRate = (dtMin > 0) ? (alcoholDelta / ((currentTime - timePredictor.startTime) / 60000.0f)) : 0; // доля/мин
    float steamAlcoholDelta = timePredictor.initialSteamAlcohol - currentSteamAlcohol;
    float steamAlcoholChangeRate = (dtMin > 0) ? (steamAlcoholDelta / ((currentTime - timePredictor.startTime) / 60000.0f)) : 0; // доля/мин (пар)

    float remaining = 0;
    const bool hasActiveRow =
        ProgramNum < ProgramLen && !program_type_empty(program[ProgramNum].WType);
    ProgramType wtype =
        hasActiveRow ? program[ProgramNum].WType : PROGRAM_TYPE_NONE;

    if (!hasActiveRow) {
        timePredictor.remainingTime = 0;
        timePredictor.rowPredictedTotalTime = 0;
        timePredictor.rowPredictionAvailable = false;
        distRowPredictionReason = DIST_PREDICTION_NO_ACTIVE_ROW;
    } else if (wtype == 'T') {
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
        float target = program[ProgramNum].Speed;
        if (wtype == 'R') {
            target *= get_steam_alcohol(TankSensor.StartProgTemp);
        }
        float dS = currentSteamAlcohol - target;
        if (dS <= 0) {
            remaining = 0;
        } else if (steamAlcoholChangeRate > MIN_ALC_RATE) {
            remaining = dS / steamAlcoholChangeRate;
        }
    } else {
        // Для прочих шагов оставляем 0 — нет метрики для прогноза
        remaining = 0;
    }

    if (hasActiveRow) {
        timePredictor.remainingTime = max(0.0f, remaining);
        timePredictor.rowPredictionAvailable = remaining > 0.0f;
        if (timePredictor.rowPredictionAvailable) {
            const float rowElapsed =
                (currentTime - timePredictor.startTime) / 60000.0f;
            timePredictor.rowPredictedTotalTime =
                rowElapsed + timePredictor.remainingTime;
            distRowPredictionReason = DIST_PREDICTION_READY;
        } else {
            timePredictor.rowPredictedTotalTime = 0.0f;
            distRowPredictionReason = DIST_PREDICTION_COLLECTING;
        }
    }

    const float processElapsed =
        (currentTime - timePredictor.processStartTime) / 60000.0f;
    float processRemaining = 0.0f;
    if (calculate_dist_process_remaining(
          currentTemp,
          SamSetup.DistTemp,
          timePredictor.processInitialTemp,
          processElapsed,
          processRemaining)) {
        timePredictor.processRemainingTime = processRemaining;
        timePredictor.processPredictionAvailable = true;
        distProcessPredictionReason = DIST_PREDICTION_READY;
    } else {
        timePredictor.processRemainingTime = 0.0f;
        timePredictor.processPredictionAvailable = false;
        distProcessPredictionReason = DIST_PREDICTION_COLLECTING;
    }

    if (timePredictor.processPredictionAvailable) {
        const float sessionElapsed =
            (currentTime - sessionStartTime) / 60000.0f;
        timePredictor.predictedTotalTime =
            sessionElapsed + timePredictor.processRemainingTime;
    } else {
        timePredictor.predictedTotalTime = 0.0f;
    }
}

float get_dist_remaining_time() {
    return timePredictor.remainingTime;
}

float get_dist_predicted_total_time() {
    return timePredictor.predictedTotalTime;
}

float get_dist_process_remaining_time() {
    return timePredictor.processRemainingTime;
}

float get_dist_row_predicted_total_time() {
    return timePredictor.rowPredictedTotalTime;
}

bool dist_row_prediction_available() {
    return timePredictor.rowPredictionAvailable;
}

bool dist_process_prediction_available() {
    return timePredictor.processPredictionAvailable;
}
