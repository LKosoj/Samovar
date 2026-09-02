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
// [П4.4/PKG-B п.4] Гейт однократного гашения BOOST-ТЭНа: либо на первом переходе
// строки программы, которая явно задаёт Power (run_dist_program), либо, если
// SamSetup.UseST выключен, раньше - по фронту начала кипения (distiller_proc()).
// Не под #ifdef SAMOVAR_USE_POWER: heater_boost_output_off() - обычная запись в
// GPIO (RELE_CHANNEL4, power_regulator.h), доступна во всех сборках, включая
// Samovar_no_power. Сбрасывается только при (пере)старте дистилляции — НЕ через
// resetTimePredictor(), иначе флаг обнулялся бы на КАЖДОМ переходе строки.
bool distBoostGated = false;
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

// [A1 п.6] Общее условие "плато" для дистилляции и БК: Т куба выше 90°C, нагрев
// включён, SamSetup.DistTimeF > 0 минут задано пользователем, и температура куба
// не растёт больше чем на 0.1°C за DistTimeF минут. Состояние (d_s_temp_finish/
// d_s_time_min, Samovar.h) общее для обоих режимов и сбрасывается в
// reset_process_state() (sensorinit.h) - здесь дополнительный сброс не нужен,
// функция самокорректируется за один тик при "чужом" наследии. Функция НЕ
// завершает процесс сама (у distiller.h и BK.h разные finish()) - вызывающий
// обязан сам вызвать свой *_finish() при true.
inline bool dist_plateau_finish_due() {
  if (!(TankSensor.avgTemp > 90 && PowerOn && SamSetup.DistTimeF > 0)) return false;
  if (abs(TankSensor.avgTemp - d_s_temp_finish) > 0.1) {
    d_s_temp_finish = TankSensor.avgTemp;
    d_s_time_min = millis();
    return false;
  }
  if ((millis() - d_s_time_min) > SamSetup.DistTimeF * 60 * 1000) {
    SendMsg(("В кубе не осталось спирта"), NOTIFY_MSG);
    return true;
  }
  return false;
}

// [9b] Условие завершения строки программы для типов T/A/S/P/R - общее для
// дистилляции и БК (program_io.h::PROGRAM_FORMAT_DIST/PROGRAM_FORMAT_BK делят
// один и тот же набор типов строк). Возвращает true РОВНО когда порог row
// достигнут по TankSensor - переход на следующую строку делает вызывающий
// (run_dist_program/run_bk_program), не эта функция.
inline bool program_threshold_row_done(const WProgram& row) {
  if (row.WType == 'T') return row.Speed <= TankSensor.avgTemp;
  if (row.WType == 'A') return row.Speed >= get_alcohol(TankSensor.avgTemp);
  if (row.WType == 'S') {
    float startAlcohol = get_alcohol(TankSensor.StartProgTemp);
    return startAlcohol > 0 && row.Speed >= get_alcohol(TankSensor.avgTemp) / startAlcohol;
  }
  if (row.WType == 'P') return row.Speed >= get_steam_alcohol(TankSensor.avgTemp);
  if (row.WType == 'R') {
    float startSteamAlcohol = get_steam_alcohol(TankSensor.StartProgTemp);
    return startSteamAlcohol > 0 && row.Speed >= get_steam_alcohol(TankSensor.avgTemp) / startSteamAlcohol;
  }
  return false;
}

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

  // [PKG-B, П3] До первого включения нагрева (PowerOn == false) невалидный или
  // не назначенный датчик куба - это отказ КОМАНДЫ СТАРТА, а не авария процесса:
  // process_sensor_failed() взводит аварийную защёлку (heater_safety_latched()),
  // снимаемую только перезагрузкой, а нагрев ещё ни разу не включался. Отказываем
  // тем же путём, что и остальные предусловия mode_begin_heating_session
  // (mode_cancel_process_start) - одно сообщение и возврат в SAMOVAR_STATUS_IDLE;
  // повторный тик не спамит, так как первая строка функции остановит выполнение
  // по несовпадению статуса. При PowerOn == true (процесс уже идёт) - без изменений.
  // [ревью] Если защёлка УЖЕ взведена (heater_safety_latched(), снимается только
  // перезагрузкой), настоящая причина отказа - она, а не датчик; в этом случае
  // не перехватываем сообщение здесь, а даём исполнению дойти до
  // mode_begin_heating_session ниже, который штатно откажет с сообщением про
  // защёлку (см. mode_common.h, ветки heater_safety_latched()).
  if (PowerOn) {
    if (!sensor_valid(TankSensor) && process_sensor_failed("Дистилляция", "куба")) return;
  } else if (!sensor_valid(TankSensor) && !heater_safety_latched()) {
    mode_cancel_process_start(
        "Дистилляция не запущена: датчик куба не назначен или не отвечает. "
        "Откройте настройки и проверьте привязку датчика куба.");
    return;
  }

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
#endif
    distBoostGated = false;
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
    // [PKG-B, П4] SamSetup.UseST == false - пользователь не хочет держать разгонный
    // ТЭН включённым во время кипения. Раньше ТЭН гасился только на первом переходе
    // строки программы (run_dist_program, num > 0 ниже) - если программа состоит
    // из одной строки или первый переход случается намного позже закипания, ТЭН
    // продолжал греть вопреки настройке. Гасим по фронту кипения, если ещё не
    // погашен переходом строки; при UseST == true поведение не меняется.
    if (!SamSetup.UseST && !distBoostGated) {
      heater_boost_output_off();
      distBoostGated = true;
    }
  }
  distBoilStartedPrev = boil_started;

  // Обновляем прогноз времени
  updateTimePredictor();

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    distiller_finish();
    return;
  }

  //Обрабатываем программу дистилляции (только если есть программы для выполнения)
  if (ProgramNum < ProgramLen && !program_type_empty(program[ProgramNum].WType) &&
      program_threshold_row_done(program[ProgramNum])) {
    run_dist_program(ProgramNum + 1);
  }


  if (dist_plateau_finish_due()) {
    distiller_finish();
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
    set_buzzer(true);
    open_valve(true, true);
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
  // [fix П10] Ёмкость и напряжение строки num-1 (той, что только что завершилась)
  // применяются ЗДЕСЬ, ДО проверки границ ниже. Раньше этот блок стоял после
  // проверки и не выполнялся для завершающего вызова run_dist_program(ProgramLen) -
  // в результате параметры ПОСЛЕДНЕЙ строки программы никогда не применялись,
  // и хвосты отбора продолжали течь в ёмкость предпоследней строки.
  // num > 0 НЕ гарантирует, что num-1 - реальная строка текущей программы: помимо
  // distiller_proc() (где ProgramNum < ProgramLen), сюда приходит и
  // SAMOVAR_DIST_NEXT из веб-интерфейса (Samovar.ino, case SAMOVAR_DIST_NEXT), и
  // короткое нажатие физической кнопки (mode_dispatch_button_press ->
  // mode_button_press_dist, mode_registry.h) - оба вызывают
  // run_dist_program(ProgramNum + 1) без проверки границ - при повторном
  // нажатии/команде после завершения программы num-1 указывает на строку ЗА
  // пределами ProgramLen (данные от прошлой, более длинной программы, а при
  // ProgramLen == PROGRAM_MAX - вовсе за границей массива program[]). Поэтому
  // явно проверяем num - 1 < ProgramLen ниже.
  if (num > 0 && num - 1 < ProgramLen) {
    if (!program_type_empty(program[num - 1].WType)) {
      set_capacity(program[num - 1].capacity_num);
#ifdef SAMOVAR_USE_POWER
      apply_program_power_row(program[num - 1].Power);
#endif
    }
  }

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
  timePredictor.lastUpdateTime = millis();
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

#ifdef SAMOVAR_USE_POWER
  // [П4.4] BOOST горит с самого старта дистилляции (см. distiller_proc()) и без
  // явного гашения — до конца сессии. Гасим один раз при первом переходе между
  // строками программы (num > 0), независимо от Power покидаемой строки: Power == 0
  // означает "не трогать регулятор" (сквозной режим), а не "мощность не задана".
  if (num > 0 && !distBoostGated) {
    heater_boost_output_off();
    distBoostGated = true;
  }
#endif
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
    timePredictor.lastUpdateTime = now;
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
    timePredictor.lastUpdateTime = currentTime;

    // Обновляем прогноз по спирту (используем долю, а не %)
    float alcoholDelta = timePredictor.initialAlcohol - currentAlcohol;
    float alcoholChangeRate = (dtMin > 0) ? (alcoholDelta / ((currentTime - timePredictor.startTime) / 60000.0f)) : 0; // доля/мин
    float steamAlcoholDelta = timePredictor.initialSteamAlcohol - currentSteamAlcohol;
    float steamAlcoholChangeRate = (dtMin > 0) ? (steamAlcoholDelta / ((currentTime - timePredictor.startTime) / 60000.0f)) : 0; // доля/мин (пар)
    // [PKG-B, П7] Скорость нагрева куба - среднее с начала СТРОКИ, как у веток
    // A/S/P/R выше, а не окно в 30 с (было: tempChangeRate). У DS18B20 шаг
    // квантования 0.0625 °C: на медленном участке 30-секундное окно то не видит
    // изменения совсем (оценка "сбор данных"), то ловит квант целиком и завышает
    // скорость в разы. Среднее с начала строки сглаживает этот шум.
    float tempChangeRateRow = (dtMin > 0)
        ? (currentTemp - timePredictor.initialTemp) / ((currentTime - timePredictor.startTime) / 60000.0f)
        : 0;

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
        } else if (tempChangeRateRow > MIN_TEMP_RATE) {
            remaining = dT / tempChangeRateRow;
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
