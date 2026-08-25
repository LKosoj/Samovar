#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "program_io.h"
#include "SamovarMqtt.h"
#include "pumppwm.h"

#define TEMP_HISTORY_SIZE 10  // Размер буфера истории температур (точек)
#define BOILING_DETECT_THRESHOLD 0.08  // Порог по стандартному отклонению, °C
#define MIN_BOILING_TEMP 98.0  // Минимальная температура кипения (с учетом погрешности)
#define STABLE_WINDOWS_REQUIRED 5 // Кол-во стабильных окон подряд для фиксации кипения
#define MAX_TREND_ABS_PER_SEC 0.02 // Макс. модуль тренда в °C/с для стабильности

// [П13] Таймауты-предохранители для строк 'B' и 'C': если физический процесс
// не продвигается (не удаётся зафиксировать кипение / не удаётся остыть до
// цели), варка не должна греть/лить воду бесконечно. Значения ориентировочные,
// подлежат проверке на реальном оборудовании.
#define BEER_BOIL_TIMEOUT_MS (120UL * 60UL * 1000UL)  // макс. время разгона до кипения на строке 'B'
#define BEER_COOL_TIMEOUT_MS (120UL * 60UL * 1000UL)  // макс. время остывания на строке 'C'

#ifndef BEER_TEMP_HYSTERESIS
#define BEER_TEMP_HYSTERESIS 0.3f  // [P2 п.2] Ширина гистерезиса вокруг уставки для M/P/F (было: controlSensor->SetTemp — чужая величина датчика)
#endif

// [Дефект 2 code review] Момент начала текущего непрерывного простоя ручной
// паузы для расписания мешалки (check_mixer_state()), 0 = простоя нет сейчас.
// Симметрично beerStageIdleSinceMs/beerStageIdleAccumMs, но своим накопителем:
// alarm_c_min/alarm_c_low_min - АБСОЛЮТНЫЕ метки millis(), не относительное
// время, поэтому компенсация - это сдвиг обеих меток при выходе из паузы
// (см. check_mixer_state()), а не вычитание из прошедшего времени.
static unsigned long beerMixerPauseSinceMs = 0;

struct BoilingDetector {
    float tempHistory[TEMP_HISTORY_SIZE];
    uint8_t historyIndex = 0;
    uint8_t samplesFilled = 0;
    bool isBoiling = false;
    unsigned long lastUpdateTime = 0;
    uint8_t stableCount = 0;
};

BoilingDetector boilingDetector;

enum BeerLuaStagePhase : uint8_t {
  BEER_LUA_STAGE_IDLE = 0,
  BEER_LUA_STAGE_ENTER_QUEUED,
  BEER_LUA_STAGE_RUNNING,
  BEER_LUA_STAGE_EXIT_QUEUED,
};

struct BeerLuaStageState {
  BeerLuaStagePhase phase;
  uint32_t ticket;
  uint8_t nextProgram;
};

BeerLuaStageState beerLuaStage = {BEER_LUA_STAGE_IDLE, 0, PROGRAM_END};

#ifdef USE_WATER_PUMP
// [P2 п.1] Гонка насоса охлаждения ('C'/'F') и планового выключения насоса
// по расписанию мешалки (set_mixer_state OFF-ветка, ниже) — новый флаг не
// даёт плановому выключению заглушить активное охлаждение.
static bool beerCoolingPumpActive = false;
#endif

inline bool beer_cooling_pump_demanded() {
#ifdef USE_WATER_PUMP
  return beerCoolingPumpActive;
#else
  return false;
#endif
}

inline ActuatorCommandResult beer_set_cooling_pump(bool active) {
#ifdef USE_WATER_PUMP
  if (set_pump_pwm(active ? 1023 : 0) != ACTUATOR_COMMAND_APPLIED) {
    return ACTUATOR_COMMAND_FAILED;
  }
  beerCoolingPumpActive = active;
#else
  (void)active;
#endif
  return ACTUATOR_COMMAND_APPLIED;
}

inline ActuatorCommandResult beer_set_cooling_outputs(bool active) {
  if (active) {
    if (!valve_status &&
        open_valve(true, false) != ACTUATOR_COMMAND_APPLIED) {
      request_emergency_stop("Аварийное отключение: не удалось открыть охлаждение");
      return ACTUATOR_COMMAND_FAILED;
    }
    if (beer_set_cooling_pump(true) == ACTUATOR_COMMAND_APPLIED) {
      return ACTUATOR_COMMAND_APPLIED;
    }
    if (valve_status &&
        open_valve(false, false) != ACTUATOR_COMMAND_APPLIED) {
      request_emergency_stop("Аварийное отключение: не удалось вернуть охлаждение в безопасное состояние");
    } else {
      request_emergency_stop("Аварийное отключение: не удалось включить насос охлаждения");
    }
    return ACTUATOR_COMMAND_FAILED;
  }

  if (beer_set_cooling_pump(false) != ACTUATOR_COMMAND_APPLIED) {
    request_emergency_stop("Аварийное отключение: не удалось выключить насос охлаждения");
    return ACTUATOR_COMMAND_FAILED;
  }
  if (!valve_status ||
      open_valve(false, false) == ACTUATOR_COMMAND_APPLIED) {
    return ACTUATOR_COMMAND_APPLIED;
  }
  if (beer_set_cooling_pump(true) != ACTUATOR_COMMAND_APPLIED) {
    request_emergency_stop("Аварийное отключение: не удалось вернуть охлаждение в рабочее состояние");
  } else {
    request_emergency_stop("Аварийное отключение: не удалось закрыть охлаждение");
  }
  return ACTUATOR_COMMAND_FAILED;
}

#ifndef BEER_SKIP_CONFIRM_WINDOW_MS
#define BEER_SKIP_CONFIRM_WINDOW_MS 10000UL  // окно повторного нажатия для подтверждения пропуска горячего охлаждения
#endif
// [P2 п.9] Без static: значение читает logic.h::get_beer_status_text через
// локальную extern-декларацию (logic.h подключается в Samovar.ino раньше beer.h).
uint8_t beerSkipConfirmProgramNum = 0xFF;    // строка, для которой ждём подтверждения (0xFF = нет ожидания)
unsigned long beerSkipConfirmDeadlineMs = 0; // окно подтверждения истекает после этого millis()
// [Ревью 24.08, дефект 2] true, если последний beer_finish() не смог сразу
// отработать из-за ACTUATOR_COMMAND_PENDING (занят лок). run_beer_program()
// при активной строке 'L' сам получает повторный тик по кнопке "далее", а вот
// beer_finish() извне (SAMOVAR_POWER/SAMOVAR_POWER_OFF, кнопка "стоп") зовётся
// ОДИН раз - без этого флага PENDING тут молча терял бы сигнал завершения
// варки насовсем (startval/SamovarStatusInt не меняются, значит beer_proc()/
// beer_stage_tick() продолжат вести варку как ни в чём не бывало). Флаг гасится
// каждым входом в beer_finish() и взводится заново, если снова получили PENDING.
bool beerFinishPending = false;

inline ActuatorCommandResult beer_safe_lua_outputs() {
  setHeaterPosition(false);
  if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) {
    return ACTUATOR_COMMAND_FAILED;
  }
  return set_mixer_state(false, false);
}

// [П12] Имя осталось историческим: функция вызывается из единой точки входа
// ручной паузы для всех типов строк (M/P/B/C/F), не только для 'F'.
inline bool beer_pause_fermentation_outputs() {
  return beer_safe_lua_outputs() == ACTUATOR_COMMAND_APPLIED;
}

inline void beer_reset_lua_stage() {
  beerLuaStage.phase = BEER_LUA_STAGE_IDLE;
  beerLuaStage.ticket = 0;
  beerLuaStage.nextProgram = PROGRAM_END;
}

void beer_abort_config_error(const String& reason);

static inline void resetBoilingDetector() {
    boilingDetector.historyIndex = 0;
    boilingDetector.samplesFilled = 0;
    boilingDetector.stableCount = 0;
    boilingDetector.isBoiling = false;
    boilingDetector.lastUpdateTime = 0;
    for (int i = 0; i < TEMP_HISTORY_SIZE; i++) boilingDetector.tempHistory[i] = 0;
}

// [Решение владельца 25.08] Полный сброс СОСТОЯНИЯ варки: ни приводов, ни локов,
// ни I2C - только поля. Вынесен из хвоста beer_finish() потому, что у того есть
// ранние выходы (job Lua подтверждает остановку лишь на следующем тике, лок занят,
// исполнитель не отключился), после которых хвост не выполнялся вовсе. Эту же
// функцию зовёт reset_process_state() (sensorinit.h), поэтому после сброса процесса
// состояние варки всегда такое же, как после штатного завершения. Без этого ручная
// пауза beerManualPause переживала бы сброс, и следующая варка сразу вставала бы на
// гейте строк M/P/B/C/F (beer_stage_tick), а накопители простоя/разгона и детектор
// кипения приходили бы в новую сессию с чужими значениями.
inline void beer_reset_stage_state() {
  beerFinishPending = false;
  beer_reset_lua_stage();
  resetBoilingDetector();
  beerBoilActiveAccumMs = 0;
  beerManualPause = false;
  beerStageIdleAccumMs = 0;
  beerStageIdleSinceMs = 0;
  beerMixerPauseSinceMs = 0;
  beerSkipConfirmProgramNum = 0xFF;
}

/**
 * @brief Проверяет, началось ли кипение по истории температур.
 *        Алгоритм: раз в секунду добавляет измерение, после заполнения окна
 *        считает среднее, стандартное отклонение и тренд; при малой дисперсии
 *        и малом тренде фиксирует стабильность, после N стабильных окон — кипение.
 * @param currentTemp Текущая температура
 * @return true, если кипение началось, иначе false
 */
bool isBoilingStarted(float currentTemp) {
    unsigned long currentTime = millis();

    // Обновляем историю не чаще раза в секунду
    if (currentTime - boilingDetector.lastUpdateTime < 1000) {
        return boilingDetector.isBoiling;
    }
    boilingDetector.lastUpdateTime = currentTime;

    // Добавляем точку в кольцевой буфер
    boilingDetector.tempHistory[boilingDetector.historyIndex] = currentTemp;
    if (boilingDetector.samplesFilled < TEMP_HISTORY_SIZE) boilingDetector.samplesFilled++;
    boilingDetector.historyIndex = (boilingDetector.historyIndex + 1) % TEMP_HISTORY_SIZE;

    // До заполнения окна и/или пока ниже порога кипения — не детектируем
    if (boilingDetector.samplesFilled < TEMP_HISTORY_SIZE || currentTemp < MIN_BOILING_TEMP) {
        boilingDetector.stableCount = 0;
        return false;
    }

    // Средняя температура окна
    float sum = 0.0f;
    for (int i = 0; i < TEMP_HISTORY_SIZE; i++) sum += boilingDetector.tempHistory[i];
    float avg = sum / TEMP_HISTORY_SIZE;

    // Стандартное отклонение
    float varSum = 0.0f;
    for (int i = 0; i < TEMP_HISTORY_SIZE; i++) {
        float d = boilingDetector.tempHistory[i] - avg;
        varSum += d * d;
    }
    float stddev = sqrtf(varSum / TEMP_HISTORY_SIZE);

    // Тренд: разница между последней и самой старой точкой, сек ~ размер окна-1
    int lastIdx = (boilingDetector.historyIndex + TEMP_HISTORY_SIZE - 1) % TEMP_HISTORY_SIZE;
    int firstIdx = boilingDetector.historyIndex; // самая старая точка
    float slope = (boilingDetector.tempHistory[lastIdx] - boilingDetector.tempHistory[firstIdx]) /
                  float(TEMP_HISTORY_SIZE - 1);

    bool stableNow = (stddev <= BOILING_DETECT_THRESHOLD) && (fabsf(slope) <= MAX_TREND_ABS_PER_SEC);
    if (stableNow) {
        if (boilingDetector.stableCount < 255) boilingDetector.stableCount++;
    } else {
        boilingDetector.stableCount = 0;
    }

    if (boilingDetector.stableCount >= STABLE_WINDOWS_REQUIRED) {
        boilingDetector.isBoiling = true;
        return true;
    }

    return boilingDetector.isBoiling;
}

inline bool beer_control_sensor(uint8_t sensorId, const DSSensor*& sensor, const char*& sensorName) {
  switch (sensorId) {
    case 0:
      sensor = &TankSensor;
      sensorName = "куба";
      return true;
    case 1:
      sensor = &WaterSensor;
      sensorName = "воды";
      return true;
    case 2:
      sensor = &PipeSensor;
      sensorName = "царги";
      return true;
    case 3:
      sensor = &SteamSensor;
      sensorName = "пара";
      return true;
    case 4:
      sensor = &ACPSensor;
      sensorName = "ТСА";
      return true;
    default:
      sensor = nullptr;
      sensorName = "";
      return false;
  }
}

/**
 * @brief Проверяет ВСЕ заполненные строки программы затирания при старте: тип
 *        этапа (MPBCFWLA) и корректность номера датчика температуры.
 *        НЕ проверяет физическую доступность датчика (sensor_valid) — это
 *        аппаратная авария, остаётся рантайм-проверкой (process_sensor_failed).
 */
inline bool beer_validate_program(String& errorMessage) {
  if (ProgramLen == 0 || program_type_empty(program[0].WType)) {
    errorMessage = "Ошибка программы Пиво: строка не задана";
    return false;
  }
  for (uint8_t i = 0; i < ProgramLen && i < PROGRAM_END; i++) {
    if (program_type_empty(program[i].WType)) break;
    if (!program_type_one_of(program[i].WType, beer_program_parse_spec().allowedTypes)) {
      errorMessage = "Ошибка программы: неверный тип этапа в строке " + String(i + 1);
      return false;
    }
    const char* semanticError = nullptr;
    if (!program_validate_beer_row_semantics(
            program[i].WType, program[i].Temp, program[i].Time,
            program[i].capacity_num, static_cast<long>(program[i].Speed),
            program[i].Volume, program[i].Power, program[i].TempSensor,
            semanticError)) {
      errorMessage = String(semanticError ? semanticError : "Ошибка программы") +
                     " в строке " + String(i + 1);
      return false;
    }
    const DSSensor* rowSensor = nullptr;
    const char* rowSensorName = "";
    if (!beer_control_sensor(program[i].TempSensor, rowSensor, rowSensorName)) {
      errorMessage = "Ошибка программы: неверный датчик температуры в строке " + String(i + 1);
      return false;
    }
  }
  return true;
}

/**
 * @brief Основной цикл запуска процесса затирания. Инициализация и старт программы.
 */
void beer_proc() {
  if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return;

  // [Ревью 24.08, дефект 2] Если активная строка 'L' держит startval на
  // SAMOVAR_STARTVAL_BEER_START (run_beer_program() не successfully добежал до
  // бампа startval, пока job активен), а beer_finish() перед этим упёрся в
  // PENDING - обычная ветка ниже (условие startval==BEER_START && !PowerOn)
  // не сработает, т.к. PowerOn ещё true. Без этого ретрая тут не было бы вообще
  // ни одного места, которое повторит зависший finish.
  if (beerFinishPending) {
    beer_finish();
    vTaskDelay(10 / portTICK_PERIOD_MS);
    return;
  }

  if (startval == SAMOVAR_STARTVAL_BEER_START && !PowerOn) {
    String programError;
    if (!beer_validate_program(programError)) {
      mode_cancel_process_start(programError);
      return;
    }
    const DSSensor* controlSensor = nullptr;
    const char* controlSensorName = "";
    beer_control_sensor(program[0].TempSensor, controlSensor, controlSensorName);
    if (!sensor_valid(*controlSensor) && process_sensor_failed("Пиво", controlSensorName)) return;

    // [PKG-B п.4] Пока не завершён OFF-переход нагрева, set_power(true) молча откажет,
    // а create_data() каждый тик зря перезапишет SPIFFS-лог (+MQTT). Отменяем старт.
    if (power_transition_active()) {
      mode_cancel_process_start("Выключение нагрева ещё не завершено. Старт затирания отменён.");
      return;
    }

    // [P2 п.4] Защёлка безопасности нагрева взведена - старт нагрева всё равно
    // молча провалится (see set_power/heater_safety_latched), но create_data()
    // и MQTT-сессия уже успеют создаться. Отменяем старт раньше.
    if (heater_safety_latched()) {
      mode_cancel_process_start("Защёлка безопасности нагрева активна. Старт затирания отменён.");
      return;
    }

    // Сброс детектора кипения при запуске процесса
    resetBoilingDetector();
    if (!create_data()) {
      mode_cancel_process_start("Ошибка создания файла лога. Старт затирания отменён.");
      return;
    }
#ifdef USE_MQTT
    String sessionDescription;
    if (!copy_mqtt_session_description(sessionDescription, pdMS_TO_TICKS(50))) {
      mode_cancel_process_start("Описание сессии занято. Старт затирания отменён.");
      mode_warn_log_close_failed();
      return;
    }
    MqttSendMsg(String(chipId) + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_beer_program() + "," + sessionDescription, "st");
#endif
    set_power(true);
    if (!PowerOn) {
      mode_cancel_process_start("Не удалось включить питание нагрева. Старт затирания отменён.");
      mode_warn_log_close_failed();
      return;
    }
    run_beer_program(0);
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Переход к этапу программы с номером num, обработка сообщений и сброс переменных этапа.
 * @param num Номер этапа программы
 */
void run_beer_program(uint8_t num) {
  if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;

  // [P2 п.9] Пропуск охлаждения, пока сусло ещё горячее цели, рискован для
  // следующего этапа. Автопереход сюда не долетает — к его моменту
  // температура уже в цели, поэтому проверка температуры ниже его не задержит.
  // Не завязываемся на begintime: пока он ещё не выставлен (первый такт
  // beer_stage_tick после входа в строку 'C'), ручное "дальше" тоже должно
  // спросить подтверждение, если сусло горячее цели.
  if (program[ProgramNum].WType == 'C') {
    const DSSensor* confirmSensor = nullptr;
    const char* confirmSensorName = "";
    if (beer_control_sensor(program[ProgramNum].TempSensor, confirmSensor, confirmSensorName) &&
        sensor_valid(*confirmSensor) && confirmSensor->avgTemp > program[ProgramNum].Temp) {
      unsigned long nowMsConfirm = millis();
      if (beerSkipConfirmProgramNum != ProgramNum || nowMsConfirm > beerSkipConfirmDeadlineMs) {
        beerSkipConfirmProgramNum = ProgramNum;
        beerSkipConfirmDeadlineMs = nowMsConfirm + BEER_SKIP_CONFIRM_WINDOW_MS;
        SendMsg("Сусло ещё не остыло до цели. Повторите переход в течение 10 секунд для подтверждения.", WARNING_MSG);
        return;
      }
    }
  }
  beerSkipConfirmProgramNum = 0xFF;

  uint8_t targetProgram = num;
  if (ProgramLen == 0 || targetProgram >= ProgramLen || targetProgram >= PROGRAM_END) {
    targetProgram = PROGRAM_END;
    SetScriptOff = 1;
  }

  if (program[ProgramNum].WType == 'L' && beerLuaStage.phase != BEER_LUA_STAGE_IDLE) {
    if (beer_safe_lua_outputs() == ACTUATOR_COMMAND_FAILED) {
      beer_abort_config_error("Ошибка Lua: не удалось выключить мешалку перед переходом");
      return;
    }
#ifdef USE_LUA
    if (beerLuaStage.phase != BEER_LUA_STAGE_EXIT_QUEUED) {
      const ActuatorCommandResult stopResult = request_beer_lua_stop(beerLuaStage.ticket);
      // [Дефект 2] PENDING - RUNTIME_STATE занят на короткий миг, не ошибка.
      // Тикет и фаза (RUNNING/ENTER_QUEUED) не трогаются - job продолжает
      // числиться активным с валидным тикетом, следующий тик run_beer_program
      // (по кнопке "далее" или по автопереходу) повторит запрос сам. Пользователя
      // предупреждаем без ALARM_MSG: это не авария, а "нажмите ещё раз через миг" -
      // WARNING_MSG уже используется в этом файле для той же семантики (см. выше
      // подтверждение пропуска охлаждения). Спама нет: PENDING сюда попадает только
      // из явного нажатия "далее"/автоперехода, тик beer_stage_tick() для активной
      // строки 'L' request_beer_lua_stop() повторно не зовёт (см. ветку ниже по
      // phase == RUNNING - там опрашивается только beer_lua_job_result()).
      if (stopResult == ACTUATOR_COMMAND_PENDING) {
        SendMsg("Не удалось сразу остановить job Lua - блокировка занята. Повторите переход через секунду.", WARNING_MSG);
        return;
      }
      if (stopResult != ACTUATOR_COMMAND_APPLIED) {
        beer_abort_config_error("Ошибка Lua: не удалось запросить остановку job");
        return;
      }
      beerLuaStage.phase = BEER_LUA_STAGE_EXIT_QUEUED;
      beerLuaStage.nextProgram = targetProgram;
    }
#else
    beer_abort_config_error("Ошибка программы: тип L требует USE_LUA");
#endif
    return;
  }

  if (targetProgram == PROGRAM_END) {
    beer_finish();
    return;
  }

  if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;

  if (startval == SAMOVAR_STARTVAL_BEER_START) startval = SAMOVAR_STARTVAL_BEER_HEATING;
  ProgramNum = targetProgram;
  begintime = 0;
  msgfl = true;

  // [п.11] Несмежная строка 'B' — это НОВОЕ кипячение на остывшей жидкости:
  // сбрасываем накопленную историю/стабильность детектора. Смежные 'B'->'B'
  // (продолжение одного кипячения ради разных всыпок хмеля) детектор не трогаем.
  if (program[ProgramNum].WType == 'B' &&
      (ProgramNum == 0 || program_type_at(ProgramNum - 1) != 'B')) {
    resetBoilingDetector();
    // [П13] Новое (несмежное) кипячение - таймаут разгона до кипения тоже с нуля.
    beerBoilActiveAccumMs = 0;
  }

  if (program[ProgramNum].WType == 'A') {
    StartAutoTune();
  }

  if (program[ProgramNum].WType == 'L') {
    if (beer_safe_lua_outputs() == ACTUATOR_COMMAND_FAILED) {
      beer_abort_config_error("Ошибка Lua: не удалось выключить мешалку перед запуском");
      return;
    }
#ifdef USE_LUA
    uint32_t ticket = 0;
    if (!request_beer_lua_job(ticket)) {
      beer_abort_config_error("Ошибка Lua: job не принят к запуску");
      return;
    }
    beerLuaStage.phase = BEER_LUA_STAGE_ENTER_QUEUED;
    beerLuaStage.ticket = ticket;
    beerLuaStage.nextProgram = PROGRAM_END;
#else
    beer_abort_config_error("Ошибка программы: тип L требует USE_LUA");
    return;
#endif
  }

  String msg = "Переход к строке программы №" + String((ProgramNum + 1));
  if (program[ProgramNum].WType == 'M') {
    msg += "; Нагрев до температуры засыпи солода: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == 'P') {
    msg += "; Температурная пауза: " + String(program[ProgramNum].Temp) + "°, время: " + String(program[ProgramNum].Time) + " мин";
  } else if (program[ProgramNum].WType == 'B') {
    msg += "; Кипячение, время: " + String(program[ProgramNum].Time) + " мин";
  } else if (program[ProgramNum].WType == 'C') {
    msg += "; Охлаждение до температуры: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == 'F') {
    msg += "; Ферментация, поддержание температуры: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == 'W') {
    msg += "; Режим ожидания";
  }

  if (SamSetup.ChangeProgramBuzzer) {
    set_buzzer(true);
    SendMsg(msg, ALARM_MSG);
  } else {
    SendMsg(msg, NOTIFY_MSG);
  }

  //сбрасываем переменные для мешалки и насоса
  alarm_c_low_min = 0;  //мешалка вкл
  alarm_c_min = 0;  //мешалка пауза
  currentstepcnt = 0; //счетчик циклов мешалки
  // [Дефект 2 code review] Метки нового цикла мешалки не переживают переход
  // строки - если тут остался незакрытый простой с предыдущей строки (не
  // должен, т.к. переход возможен только вне паузы), не даём ему сдвинуть
  // свежевыставленные alarm_c_min/alarm_c_low_min.
  beerMixerPauseSinceMs = 0;

  // [P2 п.5+6] Накопитель простоя считается только для текущей строки P/B.
  beerStageIdleAccumMs = 0;
  beerStageIdleSinceMs = 0;
}

/**
 * @brief Завершает процесс затирания: выключает насос, нагрев, клапаны, сбрасывает состояния.
 */
void beer_finish() {
  // [Ревью 24.08, дефект 2] Гасим флаг оптимистично на каждый вход - если этот
  // вызов снова упрётся в PENDING ниже, взведём заново. Если полностью пройдёт
  // (в т.ч. когда beerLuaStage.phase уже IDLE и блок ниже не выполняется вовсе),
  // флаг корректно останется снятым.
  beerFinishPending = false;
  if (beerLuaStage.phase != BEER_LUA_STAGE_IDLE) {
    if (beer_safe_lua_outputs() == ACTUATOR_COMMAND_FAILED) {
      SendMsg("Ошибка завершения варки: не удалось отключить исполнитель", ALARM_MSG);
      return;
    }
#ifdef USE_LUA
    if (beerLuaStage.phase != BEER_LUA_STAGE_EXIT_QUEUED) {
      const ActuatorCommandResult stopResult = request_beer_lua_stop(beerLuaStage.ticket);
      // [Дефект 2] PENDING - лок занят на короткий миг, не настоящая ошибка;
      // тикет/фаза не трогаются. В отличие от run_beer_program() у beer_finish()
      // может не быть НИКАКОГО внешнего повторного триггера (SAMOVAR_POWER/
      // SAMOVAR_POWER_OFF и кнопка "стоп" зовут его РОВНО один раз через реестр
      // режимов) - без beerFinishPending сигнал завершения варки терялся бы
      // насовсем: startval/SamovarStatusInt не поменяются, и beer_proc()/
      // beer_stage_tick() продолжат вести варку как ни в чём не бывало. Поэтому
      // здесь не просто "return", а взвод флага - его подхватят beer_proc()/
      // beer_stage_tick() на следующем же тике и повторят вызов сами.
      if (stopResult == ACTUATOR_COMMAND_PENDING) {
        beerFinishPending = true;
        return;
      }
      if (stopResult != ACTUATOR_COMMAND_APPLIED) {
        SendMsg("Ошибка Lua: не удалось запросить остановку job", ALARM_MSG);
        return;
      }
      beerLuaStage.phase = BEER_LUA_STAGE_EXIT_QUEUED;
      beerLuaStage.nextProgram = PROGRAM_END;
    }
    if (!beer_lua_job_idle(beerLuaStage.ticket)) return;
#else
    SendMsg("Ошибка Lua: job активен без USE_LUA", ALARM_MSG);
    return;
#endif
  }
  beer_reset_lua_stage();
  if (beer_safe_lua_outputs() == ACTUATOR_COMMAND_FAILED) {
    SendMsg("Ошибка завершения варки: не удалось отключить исполнитель", ALARM_MSG);
    return;
  }
  // Детектор кипения, накопитель таймаута разгона [П13], ручная пауза и накопители
  // простоя строки [P2 п.5+6], метка простоя мешалки и ожидание подтверждения
  // пропуска охлаждения [P2 п.9] не переживают завершение процесса. Все они
  // сбрасываются одной beer_reset_stage_state(), которую зовёт и reset_process_state()
  // (sensorinit.h) - чтобы сброс процесса приводил варку в то же состояние, даже
  // когда сюда не дошли из-за раннего выхода выше.
  beer_reset_stage_state();
  set_heater_state_flag(false);
  // begintime=0 защищает от протухшего значения при новом запуске.
  begintime = 0;
  ProgramNum = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  stop_process("Программа затирания завершена");
}

/**
 * @brief Штатно останавливает варку из-за ОШИБКИ КОНФИГУРАЦИИ программы,
 *        обнаруженной в рантайме. В отличие от request_emergency_stop НЕ взводит
 *        аварийную защёлку: достаточно поправить программу и запустить заново.
 */
void beer_abort_config_error(const String& reason) {
  SendMsg(reason, ALARM_MSG);
  beer_finish();
}

/**
 * @brief Проверяет превышение предельных температур воды/ТСА на этапах охлаждения
 *        ('C' и 'F' - оба реально гоняют воду через тракт охлаждения)
 *        и инициирует аварийный останов. Надзорная функция alarm-пути (mode_alarm_beer),
 *        работает независимо от каденции beer_stage_tick() в loop().
 */
inline void beer_check_cooling_limits() {
  if (current_program_type() != 'C' && current_program_type() != 'F') return;
  mode_request_overheat_emergency_if_needed();
}

/**
 * @brief Верхний предел температуры сусла в кубе - надзор на ВСЕХ типах строк
 *        (M/P/B/L/A/C/F), в отличие от beer_check_cooling_limits(), которая
 *        покрывает только 'C'/'F'. Порог совпадает с уставкой нагрева на
 *        кипячении (см. set_heater_state(BOILING_TEMP + 5, temp) выше).
 */
inline void beer_check_wort_overheat_limit() {
  if (!PowerOn) return;
  if (sensor_temp_at_least(TankSensor, BOILING_TEMP + 5)) {
    request_emergency_stop("Аварийное отключение! Превышена максимальная температура сусла");
  }
}

/**
 * @brief Обновляет накопитель простоя строки P/B/C: время ручной паузы, а также
 *        время вне полосы гистерезиса на 'P', не должно засчитываться в
 *        выдержку строки (см. проверки в beer_stage_tick()).
 */
inline void beer_update_stage_idle(ProgramType currentType, float temp, float tempDelta, unsigned long nowMs) {
  bool idleNow = false;
  if (currentType == 'P' || currentType == 'B' || currentType == 'C') {
    // [П1] begintime > 0: пока строка ещё не стартовала, паузу не копим -
    // иначе накопитель простоя может обогнать реально прошедшее время
    // (см. beer_stage_elapsed_ms ниже).
    if (beerManualPause && begintime > 0) {
      idleNow = true;
    } else if (currentType == 'P' && begintime > 0 &&
               (temp < program[ProgramNum].Temp - tempDelta || temp > program[ProgramNum].Temp + tempDelta)) {
      idleNow = true;
    }
  }
  if (idleNow) {
    if (beerStageIdleSinceMs == 0) beerStageIdleSinceMs = nowMs;
  } else if (beerStageIdleSinceMs > 0) {
    beerStageIdleAccumMs += nowMs - beerStageIdleSinceMs;
    beerStageIdleSinceMs = 0;
  }
}

/**
 * @brief [П1] Прошедшее активное время текущей строки P/B/C в миллисекундах:
 *        millis() минус момент старта строки минус накопленный простой.
 *        Каждое слагаемое приводится к float ОТДЕЛЬНО, до вычитания (как в
 *        logic.h::get_beer_status_text) - иначе, если накопленный простой
 *        (beerStageIdleAccumMs) больше прошедшего с begintime времени,
 *        беззнаковое вычитание unsigned long заворачивается в ~4.29e9 мс и
 *        любой порог по времени "проходит" мгновенно. Результат не может
 *        быть отрицательным.
 * @param nowMs Текущее значение millis()
 * @return Прошедшее активное время строки, мс (>= 0)
 */
inline float beer_stage_elapsed_ms(unsigned long nowMs) {
  float elapsed = (float)nowMs - (float)begintime - (float)beerStageIdleAccumMs;
  if (elapsed < 0) elapsed = 0;
  return elapsed;
}


/**
 * @brief Проверяет и управляет состоянием процесса затирания, включая нагрев, охлаждение, паузы и кипячение.
 *        Каденция 1 Гц через внутренний гейт по millis(). Раньше жила в
 *        check_alarm_beer(), вызываемой из SysTicker (ядро 0, alarm-путь);
 *        теперь это beer_stage_tick(), вызываемая из loop() (ядро 1) через
 *        dispatch_loop. Надзор за аварийными температурными лимитами вынесен в
 *        beer_check_cooling_limits() и остаётся в alarm-пути (mode_alarm_beer).
 */
void beer_stage_tick() {
  static unsigned long lastBeerTickMs = 0;
  const unsigned long nowMs = millis();
  if (nowMs - lastBeerTickMs < 1000) return;
  lastBeerTickMs = nowMs;

  // [Ревью 24.08, дефект 2] Зависший beer_finish() (PENDING) повторяем ДО гейтов
  // heater_safety_latched()/startval ниже - незавершённый останов по кнопке
  // "стоп" не должен зависеть от того, латчит ли в этот момент защёлка нагрева
  // или на какой строке программы застряли.
  if (beerFinishPending) {
    beer_finish();
    return;
  }

  if (heater_safety_latched()) return;
  if (startval <= SAMOVAR_STARTVAL_BEER_START) return;

  float temp = 0;
  float tempDelta = 0;
  const DSSensor* controlSensor = nullptr;
  const char* controlSensorName = "";
  if (!beer_control_sensor(program[ProgramNum].TempSensor, controlSensor, controlSensorName)) {
    beer_abort_config_error("Ошибка программы: неверный датчик температуры в строке " + String(ProgramNum + 1));
    return;
  }
  if (!sensor_valid(*controlSensor) && process_sensor_failed("Пиво", controlSensorName)) return;
  temp = controlSensor->avgTemp;
  tempDelta = BEER_TEMP_HYSTERESIS;
  ProgramType currentType = current_program_type();
  beer_update_stage_idle(currentType, temp, tempDelta, nowMs);

  // [П12] Единая точка входа ручной паузы: гейтит ВСЕ варочные строки
  // (M/P/B/C/F) одним вызовом - выключает нагрев/клапан/насос/мешалку и не
  // даёт строке продвинуться дальше, пока пауза активна. Вызывается ПОСЛЕ
  // beer_update_stage_idle() (простой строки продолжает копиться), но ДО
  // разбора по типам строки ниже - локальные проверки beerManualPause в
  // ветках M/P/F/B стали недостижимы и убраны. 'L' (Lua) и 'A' (автотюнинг)
  // сюда намеренно не входят - см. отчёт по П12.
  if (beerManualPause && (currentType == 'M' || currentType == 'P' || currentType == 'B' ||
                           currentType == 'C' || currentType == 'F')) {
    // [Дефект 2 code review] check_mixer_state() тоже не вызывается, пока
    // строка на этом гейте - её метки alarm_c_min/alarm_c_low_min (АБСОЛЮТНОЕ
    // millis(), без накопителя простоя типа beerStageIdleAccumMs) иначе сдвигаются
    // паузой. Запоминаем момент начала простоя один раз на весь непрерывный
    // простой (симметрично beerStageIdleSinceMs) - компенсация применяется при
    // выходе из паузы, см. beerMixerPauseSinceMs и check_mixer_state().
    if (beerMixerPauseSinceMs == 0) beerMixerPauseSinceMs = nowMs;
    if (!beer_pause_fermentation_outputs()) {
      beer_abort_config_error("Ошибка ручной паузы: не удалось выключить исполнитель");
    }
    return;
  }

  //Обрабатываем программу

  //Проверяем, что клапан воды охлаждения не открыт, когда не нужно
  if (currentType != 'C' && currentType != 'F' && currentType != 'L' &&
      currentType != 'W' && (valve_status || beer_cooling_pump_demanded()) && PowerOn) {
    if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;
  }

  //Если тип программы неизвестен или пуст - безопасно выключаем нагрев
  if (currentType != 'L' && currentType != 'W' &&
      currentType != 'A' && currentType != 'M' &&
      currentType != 'P' && currentType != 'F' &&
      currentType != 'C' && currentType != 'B') {
    beer_abort_config_error("Ошибка программы: неизвестный тип этапа в строке " + String(ProgramNum + 1));
    return;
  }

  // Lua-этап принимает управление только после подтверждённого periodic job.
  if (currentType == 'L') {
#ifdef USE_LUA
    if (beerLuaStage.phase == BEER_LUA_STAGE_EXIT_QUEUED) {
      if (beer_safe_lua_outputs() == ACTUATOR_COMMAND_FAILED) {
        beer_abort_config_error("Ошибка Lua: не удалось выключить мешалку при остановке job");
        return;
      }
      if (!beer_lua_job_idle(beerLuaStage.ticket)) return;
      const uint8_t nextProgram = beerLuaStage.nextProgram;
      beer_reset_lua_stage();
      run_beer_program(nextProgram);
      return;
    }
    const LuaBeerJobResult result = beer_lua_job_result(beerLuaStage.ticket);
    // [Дефект 2] LOCK_BUSY - RUNTIME_STATE занят на короткий миг, не провал
    // job'а: опрашиваем результат снова на следующем тике, как QUEUED/RUNNING.
    if (result == LUA_BEER_JOB_LOCK_BUSY || result == LUA_BEER_JOB_QUEUED ||
        result == LUA_BEER_JOB_RUNNING) {
      if (beer_safe_lua_outputs() == ACTUATOR_COMMAND_FAILED) {
        beer_abort_config_error("Ошибка Lua: не удалось выключить мешалку перед подтверждением job");
      }
      return;
    }
    if (result == LUA_BEER_JOB_SUCCEEDED) {
      beerLuaStage.phase = BEER_LUA_STAGE_RUNNING;
      return;
    }
    beer_abort_config_error(result == LUA_BEER_JOB_FAILED_INIT
        ? "Ошибка Lua: job не подтвердил запуск"
        : "Ошибка Lua: job завершился с ошибкой");
#else
    beer_abort_config_error("Ошибка программы: тип L требует USE_LUA");
#endif
    return;
  }

  //Если программа - ожидание - ждем, ничего не делаем
  if (currentType == 'W') {
    if (begintime == 0) {
      setHeaterPosition(false);
      if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;
      begintime = millis();
    }
    check_mixer_state(); // Управление мешалкой и насосом по параметрам программы
    return;
  }

  //Если режим Автотюнинг
  if (currentType == 'A') {
    if (tuning) {
      set_heater_state(program[ProgramNum].Temp, temp);
    } else if (!queue_samovar_command(SAMOVAR_BEER_NEXT)) {
      // [P2 п.7] Очередь команд временно занята — не аварийный останов всего
      // процесса, а просто повтор на следующем такте (1 Гц).
      SendMsg("Очередь команд занята: завершение автотюнинга пива будет повторено", WARNING_MSG);
    }
    return;
  }

  //Если режим Засыпь солода или Пауза
  if (currentType == 'M' || currentType == 'P') {
    // [П12] Ручная пауза обрабатывается единой точкой входа выше по функции.
    set_heater_state(program[ProgramNum].Temp, temp);
  }

  //Если режим Брага
  if (currentType == 'F') {
    // [П12] Ручная пауза обрабатывается единой точкой входа выше по функции.
    //Если температура меньше целевой - греем, иначе охлаждаем.
    if (temp < program[ProgramNum].Temp - tempDelta) {
      if ((valve_status || beer_cooling_pump_demanded()) &&
          beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;
      //Поддерживаем целевую температуру
      set_heater_state(program[ProgramNum].Temp, temp);
    } else if (temp > program[ProgramNum].Temp + tempDelta) {
      //Отключаем нагреватель
      setHeaterPosition(false);
      // [П14] Мягкий пуск насоса охлаждения (pumppwm.h::set_pump_pwm)
      // рассчитан на вызов КАЖДЫЙ тик, пока охлаждение должно быть активно -
      // раньше beer_set_cooling_outputs(true) звался один раз на входе в
      // этот диапазон температур, из-за чего скважность насоса застревала
      // на стартовом значении.
      if (beer_set_cooling_outputs(true) != ACTUATOR_COMMAND_APPLIED) return;
    } else {
      //Так как находимся в пределах температурной уставки, не нужно ни греть, ни охлаждать
      //Отключаем нагреватель
      setHeaterPosition(false);
      //Закрываем клапан воды, если температура в кубе чуть меньше температурной уставки, чтобы часто не щелкать клапаном
      if ((temp < program[ProgramNum].Temp + tempDelta - 0.1) && valve_status && PowerOn) {
        if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;
      }
    }
  }

  if (currentType == 'M' && temp >= program[ProgramNum].Temp - tempDelta) {
    //Достигли температуры засыпи солода. Пишем об этом. Продолжаем поддерживать температуру. Переход с этой строки программы на следующую возможен только в ручном режиме
    if (startval == SAMOVAR_STARTVAL_BEER_HEATING) {
      set_buzzer(true);
      SendMsg(("Достигнута температура засыпи солода!"), NOTIFY_MSG);
    }
    startval = SAMOVAR_STARTVAL_BEER_WAIT_MALT;
  }

  if (currentType == 'P' && temp >= program[ProgramNum].Temp - tempDelta) {
    if (begintime == 0) {
      //Засекаем время для отсчета, сколько держать паузу
      begintime = millis();
      SendMsg("Достигнута температурная пауза " + String(program[ProgramNum].Temp) + "°. Ждем " + String(program[ProgramNum].Time) + " минут.", NOTIFY_MSG);
    }
  }

  //Если программа - охлаждение - ждем, когда температура в кубе упадет ниже заданной, и управляем водой для охлаждения
  if (currentType == 'C') {
    if (begintime == 0) {
      setHeaterPosition(false);
      if (beer_set_cooling_outputs(true) != ACTUATOR_COMMAND_APPLIED) return;
      begintime = millis();
    } else if (temp > program[ProgramNum].Temp) {
      // [П14] Мягкий пуск насоса охлаждения (pumppwm.h::set_pump_pwm)
      // рассчитан на вызов КАЖДЫЙ тик, пока охлаждение ещё нужно - раньше
      // beer_set_cooling_outputs(true) звался один раз на входе в строку, из-за
      // чего скважность насоса застревала на стартовом значении. Гейт по
      // temp > program[].Temp, чтобы не включать охлаждение повторно на том
      // же тике, где ниже температура уже упала и мы его выключаем.
      if (beer_set_cooling_outputs(true) != ACTUATOR_COMMAND_APPLIED) return;
    }
    if (temp <= program[ProgramNum].Temp) {
      //Если температура упала
      if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;
      //запускаем следующую программу
      run_beer_program(ProgramNum + 1);
    } else if (beer_stage_elapsed_ms(millis()) >= BEER_COOL_TIMEOUT_MS) {
      // [П13] Таймаут остывания: датчик куба может врать, охлаждающая вода
      // может быть перекрыта или недостаточна, либо program[].Temp недостижим
      // при текущих условиях. else-ветка от достижения цели (как в 'B') -
      // если температура упала до цели ровно на тике истечения таймаута,
      // это успех, а не авария.
      beer_abort_config_error("Не удалось охладить куб до целевой температуры за 120 минут. Проверьте датчик куба, подачу охлаждающей воды и клапан охлаждения.");
      return;
    }
  }

  //Если программа - кипячение
  if (currentType == 'B') {
    //Если предыдущая программа была программой кипячения - просто продолжаем кипятить.
    if (begintime == 0 && ProgramNum > 0 && program_type_at(ProgramNum - 1) == 'B') begintime = millis();

    if (begintime == 0) {
      //Определяем начало кипения
      if (isBoilingStarted(temp)) {
        msgfl = true;
        begintime = millis();
        SendMsg(("Начался режим кипячения"), NOTIFY_MSG);
      } else {
        // [П13] Таймаут разгона до кипения: тик сюда попадает, только если
        // строка не на ручной паузе (см. единую точку входа выше), поэтому
        // накопитель растёт исключительно активное время. Не удалось
        // зафиксировать начало кипения за BEER_BOIL_TIMEOUT_MS - вероятно,
        // датчик куба врёт, объём жидкости мал, не закрыта крышка, либо
        // порог кипения (MIN_BOILING_TEMP) недостижим из-за низкого давления.
        beerBoilActiveAccumMs += 1000;
        if (beerBoilActiveAccumMs >= BEER_BOIL_TIMEOUT_MS) {
          beer_abort_config_error("Не удалось зафиксировать начало кипения за 120 минут. Проверьте датчик куба, объём жидкости, крышку и достижимость порога кипения (низкое давление).");
          return;
        }
      }
    }

    //Греем до температуры кипения, исходя из того, что датчик в кубе врет не сильно
    if (begintime == 0) {
      // [П12] Ручная пауза обрабатывается единой точкой входа выше по функции.
      set_heater_state(BOILING_TEMP + 5, temp);
    } else {
      //Иначе поддерживаем температуру
      set_heater_state_flag(true);
#ifdef SAMOVAR_USE_POWER
      //Устанавливаем заданное напряжение
      set_current_power(SamSetup.BVolt);
#else
      // [P2 п.10] Скважность реле по SamSetup.BVolt (0-100%), а не постоянное
      // 100% включение - симметрично SAMOVAR_USE_POWER-ветке выше (set_current_power(SamSetup.BVolt)).
      set_current_power_mode_value(POWER_WORK_MODE);
      set_heater(constrain(SamSetup.BVolt, 0.0f, 100.0f) / 100.0);
#endif
      if (SamSetup.UseST) {
        heater_enable_outputs(SAFETY_HEATER_OUTPUT_BOOST);
      } else {
        heater_boost_output_off();
      }
    }

    //Проверяем, что еще нужно держать паузу. За 30 секунд до окончания шлем сообщение
    // [П68] Условие на тип следующей строки снято: flame-out (внесение хмеля
    // на выключение варки, без второй строки 'B' после текущей) - штатный
    // приём, а не ошибка программы. От повторного срабатывания защищает
    // флаг msgfl (взводится при входе в строку, гасится ниже).
    if (begintime > 0 && msgfl && (beer_stage_elapsed_ms(millis()) / 1000 / 60 + 0.5 >= program[ProgramNum].Time)) {
      set_buzzer(true);
      msgfl = false;
      SendMsg(("Засыпьте хмель!"), NOTIFY_MSG);
#ifdef __SAMOVAR_DEBUG
      Serial.println("Засыпьте хмель!");
#endif
      HopStepperStep();
    }
  }

  //Проверяем, что еще нужно держать паузу
  if (begintime > 0 && (currentType == 'B' || currentType == 'P') && (beer_stage_elapsed_ms(millis()) / 60000.0f >= program[ProgramNum].Time)) {
    //Запускаем следующую программу
    run_beer_program(ProgramNum + 1);
  }
  
  //Обрабатываем мешалку и насос
  check_mixer_state();

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Управляет состоянием мешалки и насоса в зависимости от этапа программы и времени.
 */
void check_mixer_state() {
  if (heater_safety_latched()) return;
  // [Дефект 2 code review] alarm_c_min/alarm_c_low_min - АБСОЛЮТНЫЕ метки
  // millis(); вызов этой функции целиком пропускается, пока строка на ручной
  // паузе (см. гейт в beer_stage_tick()), поэтому при выходе из паузы обе
  // метки нужно сдвинуть на длительность простоя - иначе расписание мешалки
  // "плывёт": короткая пауза недокручивает фазу цикла, длинная - обе метки
  // оказываются в прошлом, и цикл считается завершённым и тут же
  // перезапускается с нуля, теряя часть выдержки.
  if (beerMixerPauseSinceMs > 0) {
    const unsigned long mixerIdleMs = millis() - beerMixerPauseSinceMs;
    if (alarm_c_low_min > 0) alarm_c_low_min += mixerIdleMs;
    if (alarm_c_min > 0) alarm_c_min += mixerIdleMs;
    beerMixerPauseSinceMs = 0;
  }
  if (program[ProgramNum].capacity_num > 0) {
    //обрабатываем время включения и управляем мешалкой и насосом

    if (alarm_c_min > 0 && (int32_t)(millis() - alarm_c_min) >= 0) {  // [C-13] overflow-safe
      //завершили паузу мешалки
      alarm_c_min = 0;
      alarm_c_low_min = 0;
      if (set_mixer_state(false, false) == ACTUATOR_COMMAND_FAILED) {
        alarm_c_min = millis() + 1000;
        return;
      }
    }

    if ((alarm_c_low_min > 0) && ((int32_t)(millis() - alarm_c_low_min) >= 0)) {  // [C-13] overflow-safe
      //выключаем мешалку, если alarm_c_min > millis()
      alarm_c_low_min = 0;
      if (alarm_c_min > 0)
        if (set_mixer_state(false, false) == ACTUATOR_COMMAND_FAILED) {
          alarm_c_low_min = millis() + 1000;
          return;
        }
    }

    if (alarm_c_low_min == 0 && alarm_c_min == 0) {
      //включаем мешалку
      alarm_c_low_min = millis() + program[ProgramNum].Volume * 1000;
      if (program[ProgramNum].Power > 0) alarm_c_min = alarm_c_low_min + program[ProgramNum].Power * 1000;
      const int candidateStepCount = currentstepcnt + 1;
      bool dir = false;
      if (candidateStepCount % 2 == 0 && program[ProgramNum].Speed < 0) dir = true;
      if (set_mixer_state(true, dir) == ACTUATOR_COMMAND_FAILED) {
        alarm_c_low_min = 0;
        alarm_c_min = 0;
        return;
      }
      currentstepcnt = candidateStepCount;
    }

  } else {
    if (mixer_status) {
      //если мешалка или насос работают, их нужно выключить, так как в этой строке программы они не нужны
      set_mixer_state(false, false);
    }
  }
}

/**
 * @brief Включает или выключает мешалку и насос, а также управляет направлением вращения.
 * @param state true — включить, false — выключить
 * @param dir true — реверс, false — прямое вращение
 */
ActuatorCommandResult set_mixer_state(bool state, bool dir) {
  if (state) {
    bool mixerRelayEnabled = false;
    bool mixerStepperStarted = false;
    //включаем мешалку
    if (BitIsSet(program[ProgramNum].capacity_num, 0)) {
      //включаем реле 2
      digitalWrite(RELE_CHANNEL2, SamSetup.rele2);
      mixerRelayEnabled = true;
      //включаем I2CStepper шаговик
      if (i2c_stepper_mixer_present()) {
	        int tm = abs(program[ProgramNum].Volume);
	        if (tm == 0) tm = 10;
	        if (!set_stepper_by_time(20, dir, tm)) {
          if (mixerRelayEnabled) digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
          return ACTUATOR_COMMAND_FAILED;
        }
        mixerStepperStarted = true;
	      }
    }
    if (BitIsSet(program[ProgramNum].capacity_num, 1)) {
#ifdef USE_WATER_PUMP
      //включаем SSD реле
      if (set_pump_pwm(1023) != ACTUATOR_COMMAND_APPLIED) {
	        bool rollbackFailed = mixerStepperStarted && !set_stepper_by_time(0, 0, 0);
	        if (mixerRelayEnabled) digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
	        if (rollbackFailed) {
          request_emergency_stop("Аварийное отключение: не удалось вернуть состояние мешалки");
        }
	        return ACTUATOR_COMMAND_FAILED;
      }
	      //включаем I2CStepper реле 1
	      if (i2c_stepper_mixer_present() || i2c_stepper_pump_present()) {
	        if (!set_mixer_pump_target(1)) {
          bool rollbackFailed = set_pump_pwm(0) != ACTUATOR_COMMAND_APPLIED;
          if (mixerStepperStarted && !set_stepper_by_time(0, 0, 0)) rollbackFailed = true;
          if (mixerRelayEnabled) digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
	          if (rollbackFailed) {
            request_emergency_stop("Аварийное отключение: не удалось вернуть состояние мешалки");
          }
          return ACTUATOR_COMMAND_FAILED;
        }
	      }
#else
      if (!set_mixer_pump_target(1)) {
        bool rollbackFailed = false;
        if (mixerStepperStarted) {
          rollbackFailed = !set_stepper_by_time(0, 0, 0);
        }
        if (mixerRelayEnabled) digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
        if (rollbackFailed) {
          request_emergency_stop("Аварийное отключение: не удалось вернуть состояние мешалки");
        }
        return ACTUATOR_COMMAND_FAILED;
      }
#endif
    }
  } else {
    bool stopFailed = false;
    //выключаем реле 2
    digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
#ifdef USE_WATER_PUMP
    //выключаем SSD реле, но не глушим активное охлаждение 'C'/'F' плановым
    //выключением насоса по расписанию мешалки [P2 п.1]
    if (!beerCoolingPumpActive &&
        set_pump_pwm(0) != ACTUATOR_COMMAND_APPLIED) stopFailed = true;
#endif
	    //выключаем I2CStepper шаговик
	    if (i2c_stepper_mixer_present()) {
	      if (!set_stepper_by_time(0, 0, 0)) stopFailed = true;
	    }
	    //выключаем I2CStepper реле 1
	    if (i2c_stepper_mixer_present() || i2c_stepper_pump_present()) {
	      if (!set_mixer_pump_target(0)) stopFailed = true;
	    }
    if (stopFailed) return ACTUATOR_COMMAND_FAILED;
  }
  mixer_status = state;
  return ACTUATOR_COMMAND_APPLIED;
}

/**
 * @brief Управляет состоянием нагревателя по ПИД-регулятору и логике разгона.
 * @param setpoint Целевая температура
 * @param temp Текущая температура
 */
void set_heater_state(float setpoint, float temp) {
#ifdef SAMOVAR_USE_POWER
  //Если дельта большая и не тюнинг, включаем разгонный тэн, иначе выключаем
  if (setpoint - temp > ACCELERATION_HEATER_DELTA && !tuning) {
    if (!acceleration_heater) {
      acceleration_heater = heater_enable_outputs(SAFETY_HEATER_OUTPUT_BOOST);
    }
  } else {
    if (acceleration_heater) {
      heater_boost_output_off();
      acceleration_heater = false;
	        }
	      }
#endif

  if (setpoint - temp > HEAT_DELTA && !tuning) {
    set_heater_state_flag(true);
#ifdef SAMOVAR_USE_POWER
    vTaskDelay(5 / portTICK_PERIOD_MS);
    set_current_power(SamSetup.BVolt);
#else
    set_current_power_mode_value(POWER_WORK_MODE);
    heater_enable_outputs(SAFETY_HEATER_OUTPUT_MAIN | SAFETY_HEATER_OUTPUT_BOOST);
#endif
  } else {
    heaterPID.SetMode(AUTOMATIC);
    Setpoint = setpoint;
    Input = temp;

    if (tuning)  // run the auto-tuner
    {
      if (aTune.Runtime())  // returns 'true' when done
      {
        FinishAutoTune();
      }
    } else  // Execute control algorithm
    {
      heaterPID.Compute();
    }
    double dutyCycle = constrain(Output / 100.0, 0.0, 1.0);
#ifdef SAMOVAR_USE_POWER
    set_heater_regulator(dutyCycle);
#else
    set_heater(dutyCycle);
#endif
  }
}

#ifdef SAMOVAR_USE_POWER
/**
 * @brief Управляет UART-регулятором по доле мощности PID без медленного on/off ШИМ.
 * @param dutyCycle Доля мощности (0.0 - 1.0)
 */
inline void set_heater_regulator(double dutyCycle) {
  dutyCycle = constrain(dutyCycle, 0.0, 1.0);
  if (dutyCycle <= 0.0 || SamSetup.StbVoltage <= 0) {
    setHeaterPosition(false);
    return;
  }

#ifdef SAMOVAR_USE_SEM_AVR
  float regulatorTarget = SamSetup.StbVoltage * dutyCycle;
#else
  // PID задает долю мощности; для регулятора напряжения P ~= V^2 / R.
  float regulatorTarget = SamSetup.StbVoltage * sqrtf((float)dutyCycle);
#endif

  set_heater_state_flag(true);
  set_current_power(regulatorTarget);
  if (current_power_mode_is(POWER_SLEEP_MODE)) {
    set_heater_state_flag(false);
    return;
  }
  check_power_error();
}
#endif

/**
 * @brief Устанавливает скважность ШИМ для нагревателя.
 * @param dutyCycle Скважность (0.0 - 1.0)
 */
void set_heater(double dutyCycle) {
  static uint32_t oldTime = 0;
  static uint32_t periodTime = 0;

  uint32_t newTime = millis();
  uint32_t offTime = periodInSeconds * 1000 * (dutyCycle);

  if (newTime < oldTime) {
    periodTime += (UINT32_MAX - oldTime + newTime);
  } else {
    periodTime += (newTime - oldTime);
  }
  oldTime = newTime;

  if (periodTime < offTime) {
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else if (periodTime >= periodInSeconds * 1000) {
    periodTime = 0;
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else {
    setHeaterPosition(false);
  }
}

// Единственная точка записи heater_state. Актуацией не занимается: реле/регулятором
// управляют вызывающие (setHeaterPosition/set_heater_regulator/прямой set_current_power)
// по разным путям (StbVoltage/BVolt/скважность ПИД).
void set_heater_state_flag(bool state) {
  heater_state = state;
}

/**
 * @brief Включает или выключает нагреватель (реле).
 * @param state true — включить, false — выключить
 */
void setHeaterPosition(bool state) {
  set_heater_state_flag(state);

  if (state) {
#ifdef SAMOVAR_USE_POWER
    //Устанавливаем заданное напряжение
    set_current_power(SamSetup.StbVoltage);

    check_power_error();
#else
    set_current_power_mode_value(POWER_WORK_MODE);
    heater_boost_output_off();
    heater_enable_outputs(SAFETY_HEATER_OUTPUT_MAIN);
    vTaskDelay(50 / portTICK_PERIOD_MS);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    if (!current_power_mode_is(POWER_SLEEP_MODE)) {
      set_power_mode(POWER_SLEEP_MODE);
    }
#else
    set_current_power_mode_value(POWER_WORK_MODE);
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
    heater_boost_output_off();
#endif
  }
}

/**
 * @brief Возвращает строковое описание текущей программы затирания.
 * @return Строка с описанием программы
 */
String get_beer_program() {
  return program_serialize_rows(0, PROGRAM_END, program_append_beer_row);
}

/**
 * @brief Запускает автотюнинг ПИД-регулятора.
 */
void StartAutoTune() {
  // REmember the mode we were in
  ATuneModeRemember = heaterPID.GetMode();

  Output = 50;

  aTune.SetControlType(1);

  // set up the auto-tune parameters
  aTune.SetNoiseBand(aTuneNoise);
  aTune.SetOutputStep(aTuneStep);
  aTune.SetLookbackSec((int)aTuneLookBack);
  tuning = true;
}

/**
 * @brief Завершает автотюнинг ПИД-регулятора, применяет параметры и сохраняет профиль.
 */
void FinishAutoTune() {
  aTune.Cancel();
  tuning = false;

  SetupEEPROM profileCandidate{};
  profileCandidate = SamSetup;
  profileCandidate.Kp = aTune.GetKp();
  profileCandidate.Ki = aTune.GetKi();
  profileCandidate.Kd = aTune.GetKd();

  const PersistResult persistResult = save_profile_nvs(profileCandidate);
  if (persistResult == PERSIST_OK) {
    // [T29] см. configMux в Samovar.ino - без спинлока async_tcp мог бы
    // прочитать SamSetup наполовину скопированной.
    portENTER_CRITICAL(&configMux);
    SamSetup = profileCandidate;
    portEXIT_CRITICAL(&configMux);
    WriteConsoleLog("Kp = " + (String)SamSetup.Kp);
    WriteConsoleLog("Ki = " + (String)SamSetup.Ki);
    WriteConsoleLog("Kd = " + (String)SamSetup.Kd);
  } else {
    String message = "PID autotune не сохранён: ";
    message += persist_result_code(persistResult);
    SendMsg(message, ALARM_MSG);
  }

  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  heaterPID.SetOutputLimits(0, 100);
  heaterPID.SetSampleTime(1000);
  set_heater_state(0, 50);
  heaterPID.SetMode(ATuneModeRemember);
}

/**
 * @brief Включает или выключает мешалку (обертка для set_mixer_state).
 * @param On true — включить, false — выключить
 */
ActuatorCommandResult set_mixer(bool On) {
  return set_mixer_state(On, false);
}

/**
 * @brief Совершает шаг шаговым двигателем для засыпи хмеля.
 */
void HopStepperStep() {
  stopService();
  stepper_safe_stop();
  stepper_safe_set_max_speed(200); //скорость движения шагового двигателя
  //stepper.setSpeed(200);    //скорость движения шагового двигателя, должна быть равна предыдущей
  TargetStepps = 360 / 1.8 * 16 / 20;  //16 - множитель на драйвере двигателя. 20 - количество отверстий по целому кругу (если бы они занимали всю окружность)
  stepper_safe_set_current(0);
  stepper_safe_set_target(TargetStepps);
  stepper.enable();
  startService();
}
