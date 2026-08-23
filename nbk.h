#pragma once

// Отформатировано так, чтоб сворачивать блоки для меньшего пользования скроллом
 #include <Arduino.h>
 #include "Samovar.h"
 #include "samovar_api.h"
 #include "runtime_helpers.h"
 #include "mode_common.h"
 #include "program_io.h"
 #include "safety_transition.h"
struct { // Структура для статистики
  float avgSpeed;
  float avgActiveSpeed;
  float totalVolume;
  float activeVolume;
  uint32_t startTime;
  uint32_t lastVolumeUpdate;
  uint32_t activeFeedMs;
} stats;
// === Новые и переименованные параметры по ТЗ ===
#define NBK_COLUMN_INERTIA_DEFAULT 180 // Инерция колонны (Ин), по умолчанию 180 секунд
#define NBK_OVERFLOW_PRESSURE_DEFAULT 40  // Давление захлёба (Дз), по умолчанию 40 мм рт.ст.
#define NBK_TN_DEFAULT 98.5 // Тн — нижний предел температуры барды, по умолчанию 98.5°C
#define NBK_DT_DEFAULT 0.5 // Допустимая просадка Т барды (dT), по умолчанию 0.5°C
#define NBK_DM_DEFAULT 100 // шаг регулирования мощности
#define NBK_DP_DEFAULT 0.5 // шаг регулирования подачи
#define NBK_TP_DEFAULT 81 // предельная Т пара
#define NBK_OPERATING_RANGE 100 // отладочная, процент использования Mo и Po из оптимизации при переходе в работу.
#define NBK_HIGH_TB_HOLD_TICKS 3 // сколько тиков подряд Тб выше Тн+dT нужно выдержать перед повышением По (задача 2)
// Параметры из Samovar_ini.h
// #define NBK_MULT_PAUSE_OVERFLOW 2 // Количество инерций в качестве паузы после захлёба
// #define USE_NBK_DELTA_PRESSURE // Включение коррекции температуры барды по давлению в бардоотводчике
// #define NBK_PUMP_LIMIT 30 // максимальная производительность насоса браги для Оптимизации, л/ч

uint16_t nbk_column_inertia = NBK_COLUMN_INERTIA_DEFAULT; // Инерция колонны (Ин)
float nbk_overflow_pressure = NBK_OVERFLOW_PRESSURE_DEFAULT; // Давление захлёба (Дз)
// [П7] Счётчик неудачных чтений датчика давления, по образцу DSSensor.ErrCount
// (alarm.h). Растёт в обеих ветках чтения (XGZ/1-Wire, sensorinit.h) при
// неудаче, обнуляется при успехе - см. nbk_pressure_stale() ниже.
int pressure_err_count = 0;
float nbk_M = 0; // М — текущая мощность, Вт
float nbk_M_max = 3200; // Максимальная мощность ТЭН-а в режиме НБК
float nbk_Mo = 0;   // Мо — оптимальная мощность, Вт
float nbk_dM = NBK_DM_DEFAULT; // dM — шаг регулирования мощности
float nbk_P = 0;    // П — текущая подача браги, л/ч
float nbk_Po = 0;   // По — оптимальная подача, л/ч
float nbk_dP = 0; // dП — шаг регулирования подачи
float nbk_Tb = 0; // Тб — текущая температура барды
float nbk_Tn = NBK_TN_DEFAULT; // Тн — нижний предел температуры барды
float nbk_Tp = 0; // Тп — температура пара
float nbk_dD = 0; // dД — поправка к Тн по давлению (используется при #define USE_NBK_DELTA_PRESSURE)
float nbk_dT = NBK_DT_DEFAULT; // Допустимая просадка Т барды (dT)
float nbk_Tp_lim = NBK_TP_DEFAULT; // Предел температуры пара на этапе Работа
// === Переменные для этапа оптимизации ===
uint16_t nbk_opt_iter = 0;
uint32_t nbk_opt_next_time = 0;
uint32_t time_speed = 0; // для подсчета литража
bool nbk_opt_in_progress = false;
// === Переменные для этапа работы ===
uint32_t nbk_work_next_time = 0;
uint32_t nbk_overheat_start_time = 0;
bool nbk_work_in_pause = false;
uint8_t nbk_work_pause_stage = 0;
float nbk_Mo_temp = 0,
      nbk_Po_temp = 0; // временное хранилище на случай пропуска оптимизации
bool manual_overflow = false; // флаг начавшегося захлёба в работе
bool noDZ_message_sent = false; // флаг сообщения об отсутствии ДЗ
bool nbk_overflow_happened = false; // флаг: в текущей паузе после захлёба (stage W) снижение Mo/Po ещё не применялось
bool nbk_pause_overflow_repeat_latched = false; // [T1] подавление повторных SendMsg о захлёбе в паузе W
float nbk_Po_ceiling = 0; // [T2] потолок повышающей коррекции подачи в Работе
uint8_t nbk_high_temp_ticks = 0; // [T2] счётчик тиков подряд с Тб выше Тн+dT
uint32_t nbk_dry_steam_start_time = 0; // [T3] отсчёт времени перегрева пара на Ручной настройке
uint32_t nbk_pressure_stale_start_time = 0; // [П7] отсчёт устойчивой потери показаний ДД
bool nbk_work_entry_overflow_pending = false; // [T8] вход в Работу сразу после захлёба в конце Оптимизации
bool nbk_safe_waiting = false;
bool nbk_safe_wait_feed_stopped = false;
ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;

struct NbkSessionConfig {
  bool valid;
  uint16_t columnInertia;
  float deltaT;
  float tankTemp;
  float overflowPressure;
  float deltaPower;
  float deltaFeed;
  float steamTempLimit;
  float mainsVoltage;
  float heaterResistance;
  float maxPower;
};

static NbkSessionConfig nbkSessionConfig = {};
static const char* nbkSessionConfigError = ""; // [П70в] какое поле сорвало старт
static bool nbkHeaterResistanceInputValid = true;
static bool nbkMainsVoltageInputValid = true;
static bool nbkPreserveStartupInputValidity = false;

inline void nbk_preserve_startup_input_validity(
    float heaterResistance, float mainsVoltage) {
  nbkHeaterResistanceInputValid =
      heaterResistance >= CONTROL_HEATER_R_MIN &&
      heaterResistance <= CONTROL_HEATER_R_MAX;
  nbkMainsVoltageInputValid = mainsVoltage > 0 && mainsVoltage < 1000;
  nbkPreserveStartupInputValidity = true;
}

inline void nbk_capture_runtime_input_validity(
    float heaterResistance, float mainsVoltage) {
  if (nbkPreserveStartupInputValidity) {
    nbkPreserveStartupInputValidity = false;
    return;
  }
  nbkHeaterResistanceInputValid =
      heaterResistance >= CONTROL_HEATER_R_MIN &&
      heaterResistance <= CONTROL_HEATER_R_MAX;
  nbkMainsVoltageInputValid = mainsVoltage > 0 && mainsVoltage < 1000;
}

inline bool nbk_capture_session_config() {
  const float heaterResistance = SamSetup.HeaterResistant;
  // [П70в] Раньше все 12 полей сворачивались в один configValid - оператор
  // получал общее "некорректные настройки" без указания, что именно поправить.
  // Проверяем по очереди и запоминаем первое сломанное поле; пороги и порядок
  // условий не меняются, только форма записи.
  const char* reason = nullptr;
  if (!(SamSetup.NbkIn > 1)) reason = "инерция колонны Ин";
  else if (!(SamSetup.NbkDelta > 0)) reason = "поправка dT";
  else if (!(SamSetup.NbkTn > 0)) reason = "температура куба Тн";
  else if (!(SamSetup.NbkOwPress > 1)) reason = "давление захлёба ДД";
  else if (!(SamSetup.NbkDM > 1)) reason = "шаг мощности dM";
  else if (!(SamSetup.NbkDP > 0)) reason = "шаг подачи dП";
  else if (!(SamSetup.NbkSteamT > 80 && SamSetup.NbkSteamT <= 97)) reason = "предел температуры пара Тп";
  else if (!nbkMainsVoltageInputValid) reason = "напряжение сети (ввод не распознан)";
  else if (!nbkHeaterResistanceInputValid) reason = "сопротивление ТЭНа (ввод не распознан)";
  else if (!(SamSetup.MainsVoltage > 0 && SamSetup.MainsVoltage < 1000)) reason = "напряжение сети вне диапазона";
  else if (!(heaterResistance >= CONTROL_HEATER_R_MIN && heaterResistance <= CONTROL_HEATER_R_MAX)) reason = "сопротивление ТЭНа вне диапазона";
  if (reason != nullptr) {
    nbkSessionConfigError = reason;
    nbkSessionConfig = {};
    return false;
  }
  nbkSessionConfigError = "";
  nbkSessionConfig.columnInertia = SamSetup.NbkIn;
  nbkSessionConfig.deltaT = SamSetup.NbkDelta;
  nbkSessionConfig.tankTemp = SamSetup.NbkTn;
  nbkSessionConfig.overflowPressure = SamSetup.NbkOwPress;
  nbkSessionConfig.deltaPower = SamSetup.NbkDM;
  nbkSessionConfig.deltaFeed = SamSetup.NbkDP;
  nbkSessionConfig.steamTempLimit = SamSetup.NbkSteamT;
  nbkSessionConfig.mainsVoltage = SamSetup.MainsVoltage;
  nbkSessionConfig.heaterResistance = heaterResistance;
  nbkSessionConfig.maxPower = nbkSessionConfig.mainsVoltage *
      nbkSessionConfig.mainsVoltage / nbkSessionConfig.heaterResistance;
  nbkSessionConfig.valid = true;
  return true;
}

inline void nbk_clear_session_config() {
  nbkSessionConfig = {};
}

struct NbkTransitionState {
  SafetyTransition transition;
  uint8_t programNum;
  bool powerOffCleanupStarted; // reset_sensor_counter + сообщение о занятом логе — однократно на фазу *_WAIT_POWER_OFF
};

static NbkTransitionState nbkTransition = {{SAFETY_TRANSITION_IDLE, 0}, 0, false};

inline bool nbk_transition_blocks_process() {
  return nbkTransition.transition.phase == NBK_TRANSITION_HEAT_WAIT_POWER ||
         nbkTransition.transition.phase == NBK_TRANSITION_HEAT_WAIT ||
         nbkTransition.transition.phase == NBK_TRANSITION_HEAT_CANCEL_WAIT_POWER_OFF;
}

inline bool nbk_transition_active() {
  return safety_transition_active(nbkTransition.transition);
}

// [P7 F4] Отчётные блоки power_regulator.h (fail_close_regulator_locked → owner reset)
// используют этот предикат вместо nbk_transition_active(), чтобы не глушить свой
// SendMsg на фазах мягкого финиша (FINISH_WAIT/FINISH_WAIT_POWER_OFF) - там
// tick_nbk_transition() ничего не сообщает сам (finish-ветки return-ят молча).
// true - ТОЛЬКО на фазах старта нагрева, где heatStageValid-ветка tick_nbk_transition()
// сама шлёт сообщение о прерывании (“Запуск нагрева НБК прерван...”) - совпадает с
// nbk_transition_blocks_process() по построению (одни и те же фазы).
inline bool nbk_transition_reports_interruption() {
  return nbk_transition_blocks_process();
}

inline bool nbk_finish_transition_active() {
  return nbkTransition.transition.phase == NBK_TRANSITION_FINISH_WAIT ||
         nbkTransition.transition.phase == NBK_TRANSITION_FINISH_WAIT_POWER_OFF;
}

inline void cancel_nbk_transition() {
  safety_transition_cancel(nbkTransition.transition);
  nbkTransition.powerOffCleanupStarted = false;
}

//  === Прототипы функций для этапов ===
void handle_nbk_stage_heatup();
void handle_nbk_stage_manual();
void handle_nbk_stage_optimization();
void handle_nbk_stage_work();
void handle_overflow(const String& msg, bool finish = true, uint32_t pause_ms = 0, bool graceful = false);
inline bool nbk_close_data_log();

// [П7] «Несвежие» показания ДД — порог 10 подряд неудач, как у температурных
// датчиков (sensor_reading_valid в alarm.h). pressure_err_count наращивается
// по-разному в зависимости от того, какой датчик давления выбран в
// Samovar_ini.h (sensorinit.h):
// - без USE_PRESSURE_XGZ/_MPX/_1WIRE вовсе — счётчик нигде не трогается,
//   здесь всегда false.
// - USE_PRESSURE_XGZ: use_pressure_sensor==true, только если сенсор отозвался
//   при инициализации; pressure_sensor_get() начинается с `if
//   (!use_pressure_sensor) return;`, так что при неудачной инициализации
//   счётчик не растёт. Если инициализация удалась — растёт при реальных
//   сбоях чтения (I2C/семафор) и сбрасывается в 0 при успехе.
// - USE_PRESSURE_MPX: use_pressure_sensor всегда true, но сама ветка чтения
//   в pressure_sensor_get() не умеет отличать удачное чтение АЦП от
//   неудачного и pressure_err_count вообще не трогает — здесь тоже всегда
//   false, независимо от того, подключён ли физически датчик.
// - USE_PRESSURE_1WIRE: use_pressure_sensor принудительно true при
//   инициализации НЕЗАВИСИМО от того, отвечает ли физический датчик, а
//   чтение в DS_getvalue() (не pressure_sensor_get()!) не имеет ранней
//   проверки use_pressure_sensor и честно наращивает счётчик при каждой
//   неудаче — устойчивый обрыв (в т.ч. если провод вообще не подключён, а
//   макрос всё равно включён) даёт аварийный останов НБК через ~60 с. Судя
//   по всему, это намеренное fail-safe поведение для этой конфигурации.
inline bool nbk_pressure_stale() {
  return pressure_err_count > 10;
}

bool overflow(){
  if (PowerOn) {
   #ifdef USE_HEAD_LEVEL_SENSOR
      if (head_level_sensor_holded()) return true;
   #endif
    // [П7] Без свежих данных ДД нельзя отличить «всё хорошо» от «идёт
    // захлёб» — безопаснее остановить рост мощности/подачи, как при
    // реальном захлёбе.
    if (nbk_pressure_stale()) return true;
    if (pressure_value >= nbk_overflow_pressure) return true;
  }
  return false;
}

// [Ревью П1, находка 3] какой датчик вызвал срабатывание overflow() — те же условия, без побочных эффектов
inline const char* nbk_overflow_source() {
  if (PowerOn) {
   #ifdef USE_HEAD_LEVEL_SENSOR
      if (head_level_sensor_holded()) return "ДЗ";
   #endif
    // [П7] Отдельный текст: несвежие данные — не то же самое, что реальный
    // захлёб по ДД, сообщение не должно врать оператору.
    if (nbk_pressure_stale()) return "нет данных ДД";
    if (pressure_value >= nbk_overflow_pressure) return "ДД";
  }
  return "?";
}

ActuatorCommandResult SetSpeed(float Speed) { // Прокладка для подсчета статистики
  if (!(Speed >= 0.0f)) return ACTUATOR_COMMAND_FAILED;
  if (!i2c_stepper_refresh(i2cStepperPump)) return ACTUATOR_COMMAND_FAILED;
  const float previousRate =
      i2c_get_liquid_rate_by_step(i2cStepperPump.currentSpeed);
  const uint16_t requestedSpeed = Speed == 0
      ? 0
      : uint16_t(i2c_stepper_steps_from_rate(Speed));
  const bool applied = Speed == 0
      ? set_stepper_target(0, 0, 0, true)
      : set_stepper_target(requestedSpeed, 0, 2147483640, true);
  if (!applied) return ACTUATOR_COMMAND_FAILED;
  uint32_t now = millis();
  if (time_speed == 0) {
    time_speed = now;
  }
  ProgramType currentType = current_program_type();
  if (currentType != 'H') { //Иначе в среднюю скорость попадает 1л/ч прогрева
    const uint32_t elapsed = now - time_speed;
    const float volume = previousRate * elapsed / 3600000.0f;
    stats.totalVolume += volume;
    if (previousRate > 0) {
      stats.activeVolume += volume;
      stats.activeFeedMs += elapsed;
    }
  }
  time_speed = now;
  nbk_P = Speed;
  return ACTUATOR_COMMAND_APPLIED;
}

inline ActuatorCommandResult nbk_set_power(float watts, uint64_t* generation = nullptr) {
#ifdef SAMOVAR_USE_POWER
  return set_current_power(fromPower(watts), generation);
#else
  (void)watts;
  if (generation != nullptr) *generation = 0;
  return ACTUATOR_COMMAND_FAILED;
#endif
}

enum NbkActuatorDeadlineTarget : uint8_t {
  NBK_ACTUATOR_NO_DEADLINE = 0,
  NBK_ACTUATOR_OPTIMIZATION_DEADLINE,
  NBK_ACTUATOR_WORK_DEADLINE,
};

struct NbkActuatorCommandState {
  bool active;
  ActuatorCommandResult result;
  uint64_t generation;
  float candidateM;
  float candidateP;
  uint32_t deadline;
  uint32_t nextDelayMs;
  uint16_t iteration;
  NbkActuatorDeadlineTarget deadlineTarget;
  bool commitProgram;
  uint8_t candidateProgramNum;
};

static NbkActuatorCommandState nbkActuatorCommand = {};
static constexpr uint32_t NBK_ACTUATOR_TIMEOUT_MS = 15000;

inline void nbk_reset_actuator_command() {
  nbkActuatorCommand = {};
}

inline void nbk_enter_safe_wait(const String& reason) {
  nbk_reset_actuator_command();
  const ActuatorCommandResult feedResult = SetSpeed(0);
  set_power(false, false);
  nbk_safe_wait_feed_stopped =
      feedResult == ACTUATOR_COMMAND_APPLIED;
  nbk_safe_waiting = true;
  if (power_transition_active()) {
    nbk_safe_wait_result = nbk_safe_wait_feed_stopped
        ? ACTUATOR_COMMAND_PENDING
        : ACTUATOR_COMMAND_FAILED;
  } else if (!PowerOn) {
    nbk_M = 0;
    nbk_safe_wait_result = nbk_safe_wait_feed_stopped
        ? ACTUATOR_COMMAND_APPLIED
        : ACTUATOR_COMMAND_FAILED;
  } else {
    nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  }
  SendMsg(reason, nbk_safe_wait_result == ACTUATOR_COMMAND_APPLIED
      ? WARNING_MSG
      : ALARM_MSG);
}

inline void tick_nbk_safe_wait() {
  if (!nbk_safe_waiting || power_transition_active()) return;
  if (!PowerOn) nbk_M = 0;
  nbk_safe_wait_result =
      nbk_safe_wait_feed_stopped && !PowerOn
          ? ACTUATOR_COMMAND_APPLIED
          : ACTUATOR_COMMAND_FAILED;
}

inline bool nbk_schedule_actuator_command(
    float candidateM,
    float candidateP,
    NbkActuatorDeadlineTarget deadlineTarget,
    uint32_t nextDelayMs,
    uint16_t iteration,
    bool commitProgram = false,
    uint8_t candidateProgramNum = 0) {
  if (nbkActuatorCommand.active ||
      !(candidateM >= 0.0f) ||
      !(candidateP >= 0.0f)) {
    return false;
  }
  nbkActuatorCommand.active = true;
  nbkActuatorCommand.result = ACTUATOR_COMMAND_ACCEPTED;
  nbkActuatorCommand.generation = 0;
  nbkActuatorCommand.candidateM = candidateM;
  nbkActuatorCommand.candidateP = candidateP;
  nbkActuatorCommand.deadline =
      safety_deadline_after(millis(), NBK_ACTUATOR_TIMEOUT_MS);
  nbkActuatorCommand.nextDelayMs = nextDelayMs;
  nbkActuatorCommand.iteration = iteration;
  nbkActuatorCommand.deadlineTarget = deadlineTarget;
  nbkActuatorCommand.commitProgram = commitProgram;
  nbkActuatorCommand.candidateProgramNum = candidateProgramNum;
  return true;
}

inline void tick_nbk_actuator_command() {
  if (!nbkActuatorCommand.active) return;
  if (safety_deadline_expired(millis(), nbkActuatorCommand.deadline)) {
    nbk_enter_safe_wait(
        "Таймаут подтверждения приводов НБК. Безопасное ожидание.");
    return;
  }

  if (nbkActuatorCommand.result == ACTUATOR_COMMAND_ACCEPTED) {
    if (!PowerOn) {
      nbk_enter_safe_wait(
          "Команда приводов НБК отклонена при выключенном нагреве.");
      return;
    }
    if (power_transition_start_pending()) return;
    nbkActuatorCommand.result = nbk_set_power(
        nbkActuatorCommand.candidateM,
        &nbkActuatorCommand.generation);
  } else if (nbkActuatorCommand.result == ACTUATOR_COMMAND_PENDING) {
#ifdef SAMOVAR_USE_POWER
    nbkActuatorCommand.result =
        current_power_command_status(nbkActuatorCommand.generation);
#else
    nbkActuatorCommand.result = ACTUATOR_COMMAND_FAILED;
#endif
  }

  if (nbkActuatorCommand.result == ACTUATOR_COMMAND_PENDING) return;
  if (nbkActuatorCommand.result != ACTUATOR_COMMAND_APPLIED) {
    nbk_enter_safe_wait(
        "Регулятор не подтвердил команду НБК. Безопасное ожидание.");
    return;
  }
  if (SetSpeed(nbkActuatorCommand.candidateP) != ACTUATOR_COMMAND_APPLIED) {
    nbk_enter_safe_wait(
        "Насос НБК не подтвердил команду. Нагрев выключен.");
    return;
  }

  nbk_M = nbkActuatorCommand.candidateM;
  if (nbkActuatorCommand.deadlineTarget ==
      NBK_ACTUATOR_OPTIMIZATION_DEADLINE) {
    nbk_opt_iter = nbkActuatorCommand.iteration;
    nbk_opt_next_time = safety_deadline_after(
        millis(), nbkActuatorCommand.nextDelayMs);
  } else if (nbkActuatorCommand.deadlineTarget ==
             NBK_ACTUATOR_WORK_DEADLINE) {
    nbk_work_next_time = safety_deadline_after(
        millis(), nbkActuatorCommand.nextDelayMs);
  }
  if (nbkActuatorCommand.commitProgram) {
    ProgramNum = nbkActuatorCommand.candidateProgramNum;
    nbk_Mo = nbkActuatorCommand.candidateM;
    nbk_Po = nbkActuatorCommand.candidateP;
    nbk_Po_ceiling = nbk_Po;
    nbk_high_temp_ticks = 0;
    nbk_pause_overflow_repeat_latched = false;
    nbk_work_in_pause = false;
    nbk_overflow_happened = false;
    nbk_safe_waiting = false;
    nbk_safe_wait_feed_stopped = false;
    nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  }
  nbk_reset_actuator_command();
}

float toPower(float value) { // конвертер в мощность ( V | W ) => W
 #ifdef SAMOVAR_USE_SEM_AVR
    return value; // если нечто иное возвращаем неизменным
 #else
      const float R = nbkSessionConfig.heaterResistance;
      return value * value / R; //если от kvic или RVMK пересчитываем в P
 #endif
  }
float fromPower(float value) { // конвертер из мощности: W => ( V | W )
 #ifdef SAMOVAR_USE_SEM_AVR
    return value;
 #else
      return sqrtf(value * nbkSessionConfig.heaterResistance);
 #endif
  }

bool nbk_stage_sensors_valid(ProgramType wtype) {
  if (wtype == 'H') {
    if (!sensor_valid(SteamSensor) && process_sensor_failed("НБК", "пара")) return false;
  }
  if (wtype == 'O' || wtype == 'W') {
    if (!sensor_valid(SteamSensor) && process_sensor_failed("НБК", "пара")) return false;
    if (!sensor_valid(TankSensor) && process_sensor_failed("НБК", "куба")) return false;
  }
  return true;
}

void nbk_proc() { //главный цикл НБК
  if (nbk_safe_waiting) {
    tick_nbk_safe_wait();
    if (startval != SAMOVAR_STARTVAL_NBK_START ||
        nbk_safe_wait_result != ACTUATOR_COMMAND_APPLIED) {
      return;
    }
    nbk_safe_waiting = false;
    nbk_safe_wait_feed_stopped = false;
    nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  }
  if (nbkActuatorCommand.active) {
    tick_nbk_actuator_command();
    return;
  }
  if (startval == SAMOVAR_STARTVAL_NBK_START) {
    run_nbk_program(0);
    return;
  }
  if (!nbkSessionConfig.valid) {
    nbk_enter_safe_wait("Конфигурация сессии НБК не зафиксирована.");
    return;
  }
  nbk_column_inertia = nbkSessionConfig.columnInertia;
  nbk_dT = nbkSessionConfig.deltaT;
  nbk_Tn = nbkSessionConfig.tankTemp;
  nbk_overflow_pressure = nbkSessionConfig.overflowPressure;
  nbk_dM = nbkSessionConfig.deltaPower;
  nbk_dP = nbkSessionConfig.deltaFeed;
  nbk_Tp_lim = nbkSessionConfig.steamTempLimit;
  nbk_M_max = nbkSessionConfig.maxPower;

  if (nbk_transition_blocks_process()) return;

  if (ProgramNum >= NBK_PROGRAM_MAX || ProgramNum >= ProgramLen || ProgramNum >= PROGRAM_MAX) {
    request_emergency_stop("Ошибка программы НБК: номер строки вне диапазона");
    return;
  }

  ProgramType wtype = program[ProgramNum].WType; // Выбор и обработка этапа
  if (program_type_empty(wtype)) {
    request_emergency_stop("Ошибка программы НБК: строка не задана");
    return;
  }
  if (!nbk_stage_sensors_valid(wtype)) return;

  if (wtype == 'H') {
    handle_nbk_stage_heatup();
    return;
  } else if (wtype == 'S') {
    handle_nbk_stage_manual();
    return;
  } else if (wtype == 'O') {
    handle_nbk_stage_optimization();
    return;
  } else if (wtype == 'W') {
    handle_nbk_stage_work();
    return;
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}


// === Реализация функций этапов ===
// =================================

// 1) "Разгон" - разгон парогенератора до Тп > 75°C.
void handle_nbk_stage_heatup() {
    nbk_Tp = SteamSensor.avgTemp; // обновляем
  //- разгон парогенератора до Тп > 75°C.
  if (nbk_Tp >= 75) {
    run_nbk_program(ProgramNum + 1);
    return;
  }
  //Если захлёб (пользователь задал слишком большие М и П), М=0, П=0 (обнуляем нагрев и подачу),
  //выводим сообщение "Захлёб колонны! Останов программы".
 if (overflow()){
    handle_overflow(
      "На прогреве заданы слишком большие " + String(PWR_MSG) + " и/или подача! Останов программы.", true, 0, true);
}
  vTaskDelay(200 / portTICK_PERIOD_MS);
}


//2) "Ручная настройка" - определение Ин, Тн, Мо и По вручную (в инструкции)
 //Время не ограничено, переход к следующей строке по кнопке "Следующая программа",
 //при переходе передаём в Оптимизацию текущие М и П.
void handle_nbk_stage_manual() { //Если захлёб, выводим сообщение "Захлёб колонны!", М=1/2, П=1/3 (оставляем от подачи треть, половиним мощность).
  bool hasOverflow = overflow();
  if (hasOverflow && !manual_overflow) {
      const float candidateP = nbk_P / 3;
      const float candidateM = toPower(target_power_volt) / 2;
      if (!nbk_schedule_actuator_command(
              candidateM,
              candidateP,
              NBK_ACTUATOR_NO_DEADLINE,
              0,
              nbk_opt_iter)) {
        nbk_enter_safe_wait(
            "Снижение приводов НБК после захлёба не принято.");
        return;
      }
      manual_overflow = true;
      SendMsg("Захлёб по " + String(nbk_overflow_source()) + ". Подача 1/3, мощность 1/2.", ALARM_MSG);
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
  } else if (!hasOverflow) manual_overflow = false;
  vTaskDelay(200 / portTICK_PERIOD_MS);
}


//3) "Оптимизация" - автоматическое определение Мо и По.
void handle_nbk_stage_optimization() {
  if (!nbk_opt_in_progress) { // Ждем 30 сек чтобы пользователь успел пропустить Оптимизацию если захочет,
    //в этом случае передаём полученные от Ручной настройки М и П в Работу как Мо и По
    if ((millis() - begintime) < 30000) {  // [C-13] overflow-safe: ещё в пределах 30 с от begintime
      if (overflow()) { // [T1] опрос захлёба во время ожидания пропуска Оптимизации
        handle_overflow(
          "Ещё до начала Оптимизации — заданные на Настройке " + String(PWR_MSG) + " и подача слишком велики. Останов.",
          true, 0);
        return;
      }
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
    }

    #ifndef USE_HEAD_LEVEL_SENSOR //даём время пользователю задать вручную параметры в "Работе", если не задал - передадутся те, что были в Настройке
      if (!noDZ_message_sent) {
        SendMsg("Оптимизация невозможна - отсутствует датчик захлёба. Установите вручную нужные параметры в программе этапа Работа и нажмите кнопку Следующая программа. Автоматический переход к Работе произойдёт через 10 минут", ALARM_MSG);
      }
      noDZ_message_sent = true;
      if ((millis() - begintime) < 600000) {  // [C-13] overflow-safe: ещё в пределах 10 мин от begintime
        if (overflow()) { // [T1] опрос захлёба во время ожидания ручного перехода к Работе
          handle_overflow(
            "При ожидании ручного перехода к Работе — заданные " + String(PWR_MSG) + " и подача слишком велики. Останов.",
            true, 0);
          return;
        }
        vTaskDelay(200 / portTICK_PERIOD_MS);
        return;
      }
      run_nbk_program(ProgramNum + 1);
      return;
    #endif

    nbk_opt_in_progress = true; // Пауза на пропуск Оптимизации закончена
    begintime = 0; // Сбрасываем отсчет для корректной обработки разницы окончания оптимизации, по захлёбу или нет

    // второй этап инициализации Оптимизации
    // Мо=0, По=0 М и П - из строки программы или по-умолчанию: М = разгоннная*0.3 П = 10 л/ч
      nbk_Mo_temp = 0; //пропуск оптимизации не состоялся, сброс значений
      nbk_Po_temp = 0;
      nbk_Mo = 0; //Мо=0, По=0
      nbk_Po = 0;
      //передаём в Оптимизацию текущие М и П. (те, что сложились после манипуляций пользователя в Настройке)
      float candidateM = toPower(target_power_volt) > 100
          ? toPower(target_power_volt)
          : 0.3 * nbk_M_max;
      float candidateP = get_stepper_speed() > 0
          ? i2c_get_liquid_rate_by_step(get_stepper_speed())
          : 10;
      if (program[ProgramNum].Power > 0) {
        candidateM = toPower(program[ProgramNum].Power);
      }
      if (program[ProgramNum].Speed > 0) {
        candidateP = program[ProgramNum].Speed;
      }
      if (!nbk_schedule_actuator_command(
              candidateM,
              candidateP,
              NBK_ACTUATOR_OPTIMIZATION_DEADLINE,
              uint32_t(nbk_column_inertia *
                  NBK_MULT_PAUSE_OVERFLOW / 3.0f * 1000),
              0)) {
        nbk_enter_safe_wait(
            "Начальные параметры Оптимизации НБК не приняты.");
        return;
      }
#ifdef SAMOVAR_USE_POWER
     SendMsg("Оптимизация принята с: " + String(fromPower(candidateM),0) + String(PWR_SIGN) + ",  " + String(candidateP,1) + " л/ч ", NOTIFY_MSG);
#endif
  }

  // Собственно цикл оптимизации
  if (nbk_opt_in_progress) {
     if (nbk_opt_iter >= 300) {
       run_nbk_program(ProgramNum + 1);
       return;
     }
     if (overflow()) { // Если захлёб по ДЗ или ДД
        if (nbk_Mo == 0 && nbk_Po == 0) {
          // Если захлёб на первых же итерациях  (когда Мо или По равны нулю)
          handle_overflow("Заданные параметры " + String(PWR_MSG) + " и Скорость слишком велики — оптимизация невозможна. Останов.", true, 0);
        } else {
          // Если захлёб после нескольких итераций (Мо или По найдены) - мы
          // оптимизировались. Переход к строке Работа через паузу MULT*Ин (для
          // успокоения колонны после захлёба)
          nbk_Po *= NBK_OPERATING_RANGE / 100.0f; // отладочная корректировка после захлёба
          nbk_Mo *= NBK_OPERATING_RANGE / 100.0f;
#ifdef SAMOVAR_USE_POWER
          SendMsg(" Оптимум: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN) + ",  " +
          String(nbk_Po,1) + " л/ч", WARNING_MSG);
#endif
          nbk_work_entry_overflow_pending = true; // [T8] снижение будет применено ДО перехода строки
          handle_overflow(
            "Оптимизация завершена.",
            false, NBK_MULT_PAUSE_OVERFLOW * nbk_column_inertia * 1000); // Сначала снижение...
          run_nbk_program(ProgramNum + 1); // ...потом переход строки (флаг выше подавит полные Мо/По при входе в W)
        }
        return;
     }

    if (safety_deadline_expired(millis(), nbk_opt_next_time)) {//Если пауза на инерцию вышла
    nbk_Tb = TankSensor.avgTemp;
    // Ядро оптимизации
    // 3.3) если Тб >= Тн то (По=П, Мо=М, новая П = П + dП, переход на 3.1) //увеличили подачу,
    // иначе (новые П = П*0.9, М = М + dM, переход на 3.1) // уменьшили подачу, увеличили мощность
    #ifdef USE_NBK_DELTA_PRESSURE
      if (pressure_value != -1) {
          nbk_dD = 0.00001913 * pressure_value * pressure_value + 0.03694 * pressure_value; // Поправка по давлению если включена в Samovar_ini.h
      }
    #endif

    const float currentM = nbk_M;
    const float currentP = nbk_P;
    float candidateM = currentM;
    float candidateP = currentP;
    nbk_Tp = SteamSensor.avgTemp; // обновляем
    if ((nbk_Tb >= nbk_Tn + nbk_dD) && (nbk_Tp >= nbk_Tp_lim)) { // если по барде и пару всё Ок
      nbk_Po = currentP;
      nbk_Mo = currentM;
      candidateP += nbk_dP;
      if (candidateP > NBK_PUMP_LIMIT) {
#ifdef SAMOVAR_USE_POWER
        SendMsg("Достигнута предельная подача (" + String(NBK_PUMP_LIMIT) + " л/ч). Результат: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN), WARNING_MSG);
#endif
        run_nbk_program(ProgramNum + 1);
        return;
      }
      String msg; msg.reserve(128);
      msg += "Оптимизация: Тб >= Тн (";
      msg += String(nbk_Tn + nbk_dD, 1);
      msg += "), увеличиваем подачу. Итерация ";
      msg += uint16_t(nbk_opt_iter + 1);
      SendMsg(msg, NOTIFY_MSG);
    } else {
      if ((currentM + nbk_dM) > nbk_M_max) {
        SendMsg("Достигнута предельная мощность. (" + String(currentM ,0) + "+dM>" + String(nbk_M_max,0)  + " Вт.). Результат: " + String(nbk_Po,1) + " л/ч.", WARNING_MSG);
        run_nbk_program(ProgramNum + 1);
        return;
      }
      candidateP *= 0.9f;
      candidateM += nbk_dM;
      if (nbk_Tp < nbk_Tp_lim) {
        String msg; msg.reserve(128);
        msg += "Оптимизация: Тп < Тп мин(";
        msg += String(nbk_Tp_lim,1);
        msg += "), увеличиваем ";
        msg += PWR_MSG;
        msg += ". Итерация ";
        msg += uint16_t(nbk_opt_iter + 1);
        SendMsg(msg, NOTIFY_MSG);
      } else {
        String msg; msg.reserve(128);
        msg += "Оптимизация: Тб < Тн(";
        msg += String(nbk_Tn + nbk_dD,1);
        msg += "), увеличиваем ";
        msg += PWR_MSG;
        msg += ". Итерация ";
        msg += uint16_t(nbk_opt_iter + 1);
        SendMsg(msg, NOTIFY_MSG);
      }
    }
    const uint16_t nextIteration = uint16_t(nbk_opt_iter + 1);
    if (!nbk_schedule_actuator_command(
            candidateM,
            candidateP,
            NBK_ACTUATOR_OPTIMIZATION_DEADLINE,
            uint32_t(nbk_column_inertia) * 1000,
            nextIteration)) {
      nbk_enter_safe_wait(
          "Коррекция Оптимизации НБК не принята.");
      return;
    }
    if (nextIteration >= 300) {
#ifdef SAMOVAR_USE_POWER
      SendMsg("Достигнут лимит итераций. Результат: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN) + ", " + String(nbk_Po,1) + " л/ч", WARNING_MSG);
#endif
    }
  }
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}


//4) "Работа" - основной режим
void handle_nbk_stage_work() {
 //  4.1) Ждем время Ин - (первая пауза наследована от оптимизации Ин или MULT*Ин если был захлёб)
 //  4.1) если Тб<Тн-dT+dД, то П=П-dП/10, переход на 4.1)
 //  4.2) если захлёб, выводим сообщение "Захлёб колонны!", М=1/2, П=0, ждём время MULT*Ин. После этого Мо=Мо-dM/10. М=Мо, П=По, ждём время 2*Ин, переход на 4.1)
  if (!nbk_work_in_pause ) {// если не на паузе по захлёбу
    // 4.2) если захлёб, выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время MULT*Ин. После этого Мо=Мо-dM/10. М=Мо, П=По, ждём время 2*Ин, переход на 4.1)
    if (overflow()) {
      handle_overflow("Временное снижение подачи и нагрева.", false, NBK_MULT_PAUSE_OVERFLOW * nbk_column_inertia * 1000); //выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время MULT*Ин.
      return;
    }
    if (safety_deadline_expired(millis(), nbk_work_next_time))  {// если пауза на инерцию вышла
    nbk_Tp = SteamSensor.avgTemp; // обновляем
    nbk_Tb = TankSensor.avgTemp;
    #ifdef USE_NBK_DELTA_PRESSURE
      if (pressure_value != -1) {
        nbk_dD = 0.00001913 * pressure_value * pressure_value + 0.03694 * pressure_value; // Поправка по давлению если включена в Samovar_ini.h
      }
    #endif
    const float currentM = nbk_M;
    const float currentP = nbk_P;
    float candidateM = currentM;
    float candidateP = currentP;
    bool commandNeeded = false;
    //  4.1) если Тб<Тн-dT+dД, то П=П-dП/10, переход на 4.1)
    // 4.1.1) если Т пара ниже предела, то П=П-dП/10 (нововведение), ограничение спиртуозности выхода на случай вранья датчика Тб.
     // чем выше Т, тем ниже % спирта, нам надо снижать %, значит Т поднимать.
                               // 60% это примерно 81 гр.Ц., 50% - 84,4 гр.Ц., 40% - 87.7 гр.Ц
    if ((nbk_Tb < nbk_Tn - nbk_dT + nbk_dD) || (nbk_Tp < nbk_Tp_lim)) {
        if ((currentP > nbk_Po-0.1) && (currentP < nbk_Po+0.1) && (currentM > nbk_Mo-5) && (currentM < nbk_Mo+5)) {// если небыло вмешательств TODO теперь из-за преобразований мощность-напряжение-мощность придётся и по мощности сравнение делать с допустимым отклонением
          nbk_Po -= nbk_dP / 10.0;
          if (nbk_Po < 0) nbk_Po = 0; // По — подача не может быть отрицательной (по аналогии с 497-498)
        }
      candidateP = nbk_Po > 0 ? nbk_Po : 0;
      candidateM = nbk_Mo;
      commandNeeded = true;
    } else if (nbk_Tb > nbk_Tn + nbk_dT + nbk_dD) { // [T2] Тб держится выше Тн+dT — колонна недогружена, можно повысить подачу
      if ((currentP > nbk_Po-0.1) && (currentP < nbk_Po+0.1) && (currentM > nbk_Mo-5) && (currentM < nbk_Mo+5)) { // не было вмешательств
        nbk_high_temp_ticks++;
        if (nbk_high_temp_ticks >= NBK_HIGH_TB_HOLD_TICKS) {
          nbk_Po += nbk_dP / 10.0;
          if (nbk_Po > nbk_Po_ceiling) nbk_Po = nbk_Po_ceiling; // не выше По из Оптимизации/Настройки
          nbk_high_temp_ticks = 0;
        }
      } else {
        nbk_high_temp_ticks = 0;
      }
      candidateP = nbk_Po;
      candidateM = nbk_Mo;
      commandNeeded = true;
    } else {
      nbk_high_temp_ticks = 0;
    }
    if (nbk_Tb < nbk_Tn - nbk_dT + nbk_dD) {
      String msg; msg.reserve(128);
      msg += "Работа: Тб < Тн-dT (";
      msg += String(nbk_Tn - nbk_dT + nbk_dD, 1);
      msg += "), снижаем подачу на ";
      msg += String(nbk_dP / 10.0, 1);
      msg += ", до: ";
      msg += String(candidateP, 1);
      msg += " л/ч";
      SendMsg(msg, NOTIFY_MSG);
    } else if (nbk_Tp < nbk_Tp_lim) {
      String msg; msg.reserve(128);
      msg += "Работа: Тп ниже предела (";
      msg += String(nbk_Tp_lim, 1);
      msg += "), снижаем подачу на ";
      msg += String(nbk_dP / 10.0, 1);
      msg += ", до: ";
      msg += String(candidateP, 1);
      msg += " л/ч";
      SendMsg(msg, NOTIFY_MSG);
    } else if (nbk_Tb > nbk_Tn + nbk_dT + nbk_dD) { // [T2]
      String msg; msg.reserve(128);
      msg += "Работа: Тб > Тн+dT (";
      msg += String(nbk_Tn + nbk_dT + nbk_dD, 1);
      msg += "), увеличиваем подачу на ";
      msg += String(nbk_dP / 10.0, 1);
      msg += ", до: ";
      msg += String(candidateP, 1);
      msg += " л/ч";
      SendMsg(msg, NOTIFY_MSG);
    }
    if (commandNeeded) {
      if (!nbk_schedule_actuator_command(
              candidateM,
              candidateP,
              NBK_ACTUATOR_WORK_DEADLINE,
              uint32_t(nbk_column_inertia) * 1000,
              nbk_opt_iter)) {
        nbk_enter_safe_wait(
            "Коррекция Работы НБК не принята.");
      }
    } else {
      nbk_work_next_time = safety_deadline_after(
          millis(), uint32_t(nbk_column_inertia) * 1000);
    }
  }
 }
  // Обработка паузы после захлёба
  if (nbk_work_in_pause) {
    if (overflow()) { // [T1] повторный захлёб во время паузы W — пауза продлевается, мощность снижается вдвое от Мо
      if (!nbk_pause_overflow_repeat_latched) {
        SendMsg("Повторный захлёб по " + String(nbk_overflow_source()) + " во время паузы. Пауза продлена, мощность снижена вдвое.", WARNING_MSG);
        nbk_pause_overflow_repeat_latched = true;
      }
      nbk_work_pause_stage = 1;
      nbk_overflow_happened = true;
      if (!nbk_schedule_actuator_command(
              nbk_Mo / 2,
              nbk_P,
              NBK_ACTUATOR_WORK_DEADLINE,
              uint32_t(NBK_MULT_PAUSE_OVERFLOW) *
                  nbk_column_inertia * 1000,
              nbk_opt_iter)) {
        nbk_enter_safe_wait(
            "Повторное снижение мощности НБК не принято.");
      }
      return;
    }
    nbk_pause_overflow_repeat_latched = false;
    if (safety_deadline_expired(millis(), nbk_work_next_time)) {
    if (nbk_work_pause_stage == 1) {
      // После 3*Ин: После этого Мо=Мо-dM/10. М=Мо, П=По,
      if (nbk_overflow_happened && !nbk_work_entry_overflow_pending) { // снижаем Mo/Po только если пауза вызвана захлёбом в самой Работе, а не входом в неё сразу после захлёба в конце Оптимизации (там уже снижено)
        nbk_Mo -= nbk_dM / 10.0; // на 1/10 шага убавляем мощность
        nbk_Po -= nbk_dP / 10.0; // на 1/10 шага убавляем подачу;
      }
      nbk_overflow_happened = false; // сброс флага в любом случае
      nbk_work_entry_overflow_pending = false; // одноразовый, потребили
      if (nbk_Mo < 0) nbk_Mo = 0;
      if (nbk_Po < 0) nbk_Po = 0;
      if (!nbk_schedule_actuator_command(
              nbk_Mo,
              nbk_Po,
              NBK_ACTUATOR_WORK_DEADLINE,
              uint32_t(2.0f * NBK_MULT_PAUSE_OVERFLOW / 3.0f *
                  nbk_column_inertia * 1000),
              nbk_opt_iter)) {
        nbk_enter_safe_wait(
            "Возобновление Работы НБК не принято.");
        return;
      }

      String msg; msg.reserve(128);
      msg += "Работа: возобновление после захлёба, скорректированные параметры: ";
      msg += String(fromPower(nbk_Mo),0);
#ifdef SAMOVAR_USE_POWER
      msg += PWR_SIGN;
#endif
      msg += ", ";
      msg += String(nbk_Po,1);
      msg += " л/ч";
      SendMsg(msg, NOTIFY_MSG);
      nbk_work_pause_stage = 2; // ждём время 2*NBK_MULT_PAUSE_OVERFLOW/3 * Ин
    } else if (nbk_work_pause_stage == 2) { // после MULT*Ин: продолжаем работу
      nbk_work_in_pause = false;
      nbk_work_pause_stage = 0;
      nbk_work_next_time = safety_deadline_after(millis(), (uint32_t)nbk_column_inertia * 1000); // ждем время Ин
      SendMsg("Работа: продолжаем цикл после паузы.", NOTIFY_MSG);
    }
    }
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
// [П2] Общая часть шести идентичных отказов старта/перехода строки НБК:
// alarm-сообщение + возврат в IDLE (mode_cancel_process_start, как в beer.h) +
// сброс текущей строки программы. Закрытие лога (nbk_close_data_log /
// mode_warn_log_close_failed) вызывающий код добавляет явно ПОСЛЕ этого
// хелпера — у площадок разный хвост (два разных текста WARNING при занятости
// лога, C/F vs E) и не у всех он вообще есть (A/B/D) — сводить это в один bool
// нельзя, не теряя различие сообщений.
inline void nbk_cancel_program_start(const String& message) {
  mode_cancel_process_start(message);
  ProgramNum = 0;
}

// [П9] Возобновление Работы НБК после безопасного ожидания, вызванного сбоем
// подтверждения приводов ПОСРЕДИ Работы (не при первом входе в неё - для этого
// есть отдельная явная ветка WType=='W' в run_nbk_program). Работа - последняя
// строка программы: обычный run_nbk_program(ProgramNum+1) уходит прямиком в
// nbk_finish() и теряет весь накопленный nbk_Mo/nbk_Po. Возобновляем ЖИВЫМИ
// nbk_Mo/nbk_Po (а не program[].Power/Speed), без автозапуска - только по
// повторному нажатию "Следующая программа" и только если причина устранена.
inline void nbk_resume_work_after_safe_wait() {
  if (heater_safety_latched()) {
    SendMsg("Возобновление Работы НБК невозможно: авария зафиксирована.", ALARM_MSG);
    return;
  }
  if (!nbkSessionConfig.valid) {
    SendMsg("Возобновление Работы НБК невозможно: нет снимка конфигурации сессии.", ALARM_MSG);
    return;
  }
  if (!nbk_stage_sensors_valid('W')) return; // сообщение об ошибке датчика формирует сама функция
  if (nbkActuatorCommand.active) {
    SendMsg("Возобновление Работы НБК отклонено: предыдущая команда приводов ещё выполняется.", WARNING_MSG);
    return;
  }
  tick_nbk_safe_wait();
  if (nbk_safe_wait_result == ACTUATOR_COMMAND_PENDING) {
    SendMsg("Работа НБК ожидает завершения выключения нагрева.", WARNING_MSG);
    return;
  }
  if (nbk_safe_wait_result != ACTUATOR_COMMAND_APPLIED) {
    SendMsg("Возобновление Работы НБК недоступно: останов насоса не был подтверждён.", ALARM_MSG);
    return;
  }
  set_power(true);
  if (!PowerOn) {
    nbk_enter_safe_wait("Нагрев НБК не включён при попытке возобновления Работы.");
    return;
  }
  nbk_safe_waiting = false;
  nbk_safe_wait_feed_stopped = false;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  if (!nbk_schedule_actuator_command(
          nbk_Mo,
          nbk_Po,
          NBK_ACTUATOR_WORK_DEADLINE,
          uint32_t(nbk_column_inertia) * 1000,
          nbk_opt_iter)) {
    nbk_enter_safe_wait("Возобновление Работы НБК: параметры не приняты приводами.");
    return;
  }
  // [Дефект 2] nbk_enter_safe_wait() при входе в безопасное
  // ожидание НЕ трогает состояние паузы захлёба (оно просто замораживается как
  // было). Без явного сброса здесь handle_nbk_stage_work() на следующем тике
  // снова войдёт в ветку nbk_work_pause_stage==1 и повторно отправит уже
  // отправленную команду nbk_Mo/nbk_Po. Раз команда выше принята приводами -
  // пауза по захлёбу завершена, возвращаемся в обычный цикл Работы (как при
  // штатном выходе из stage==2): снимаем флаг паузы и обнуляем её стадию и
  // накопленные флаги захлёба, чтобы они не «дожили» из старой паузы.
  nbk_work_in_pause = false;
  nbk_work_pause_stage = 0;
  nbk_overflow_happened = false;
  nbk_pause_overflow_repeat_latched = false;
#ifdef SAMOVAR_USE_POWER
  SendMsg("Работа НБК возобновлена: М=" + String(fromPower(nbk_Mo),0) + String(PWR_SIGN) +
          ", П=" + String(nbk_Po,1) + " л/ч", NOTIFY_MSG);
#endif
}

// Смена программы
void run_nbk_program(uint8_t num, bool workConfirmed) {
 // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; //dranek: лишняя проверка, ломает запуск
#ifndef SAMOVAR_USE_POWER
  if (num == 0) {
    nbk_reset_actuator_command();
    const ActuatorCommandResult feedResult = SetSpeed(0);
    set_power(false, false);
    cancel_nbk_transition();
    SendMsg(
        "Запуск НБК отклонён: регулятор мощности недоступен в этой сборке.",
        ALARM_MSG);
    if (feedResult != ACTUATOR_COMMAND_APPLIED) {
      SendMsg(
          "Останов насоса НБК в недоступной конфигурации не подтверждён.",
          ALARM_MSG);
    }
    ProgramNum = 0;
    startval = SAMOVAR_STARTVAL_IDLE;
    SamovarStatusInt = SAMOVAR_STATUS_IDLE;
    if (!PowerOn) nbk_M = 0;
    nbk_safe_waiting = false;
    nbk_safe_wait_feed_stopped =
        feedResult == ACTUATOR_COMMAND_APPLIED;
    nbk_safe_wait_result =
        nbk_safe_wait_feed_stopped && !PowerOn
            ? ACTUATOR_COMMAND_APPLIED
            : ACTUATOR_COMMAND_FAILED;
    nbk_clear_session_config();
    nbk_close_data_log();
    return;
  }
#endif
  if (nbk_finish_transition_active()) return;
  if (nbk_transition_blocks_process() && nbkTransition.programNum == num) return;
  if (nbk_transition_blocks_process()) {
    SendMsg("Переход строки НБК отклонён: запуск нагрева ещё не завершён", WARNING_MSG);
    return;
  }
  t_min = 0;
  alarm_c_min = 0;
  msgfl = true;
  if (num == 0) {
    nbk_overheat_start_time = 0;
    nbk_dry_steam_start_time = 0; // [Ревью П1, находка 2] симметрично nbk_overheat_start_time
    nbk_pressure_stale_start_time = 0; // [П7] симметрично
  }
  // [П9] "Следующая программа" во время безопасного ожидания на строке Работы -
  // это просьба возобновить, а не перейти к несуществующей следующей строке.
  if (nbk_safe_waiting && num == uint16_t(ProgramNum) + 1 &&
      ProgramNum < ProgramLen && program[ProgramNum].WType == 'W') {
    nbk_resume_work_after_safe_wait();
    return;
  }
  if (num >= PROGRAM_END || num >= NBK_PROGRAM_MAX) {
    nbk_finish();
    return;
  }
  if (num >= ProgramLen || program_type_empty(program[num].WType)) {
    request_emergency_stop(num == 0 ? "Программа НБК не задана" : "Ошибка программы НБК: строка не задана");
    return;
  }
  if (!nbk_stage_sensors_valid(program[num].WType)) return;
  if (program[num].WType == 'W') {
    if (!nbkSessionConfig.valid) {
      nbk_enter_safe_wait(
          "Переход к Работе НБК отклонён: нет снимка конфигурации сессии.");
      return;
    }
    if (!workConfirmed) {
      nbk_enter_safe_wait(
          "Автоматический переход к Работе НБК запрещён. "
          "Задайте Power/Speed строки W и нажмите «Следующая программа».");
      return;
    }
    if (program[num].Power <= 0 || program[num].Speed <= 0) {
      nbk_enter_safe_wait(
          "Строка W требует явно заданные ненулевые Power и Speed.");
      return;
    }
    if (nbk_safe_waiting) {
      tick_nbk_safe_wait();
      if (nbk_safe_wait_result == ACTUATOR_COMMAND_PENDING) {
        SendMsg(
            "Работа НБК ожидает завершения выключения нагрева.",
            WARNING_MSG);
        return;
      }
      if (nbk_safe_wait_result != ACTUATOR_COMMAND_APPLIED) {
        SendMsg(
            "Работа НБК недоступна: останов насоса не был подтверждён.",
            ALARM_MSG);
        return;
      }
      set_power(true);
      if (!PowerOn) {
        nbk_enter_safe_wait(
            "Нагрев НБК не включён по явной команде перехода к Работе.");
        return;
      }
      nbk_safe_waiting = false;
      nbk_safe_wait_feed_stopped = false;
      nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
    }
    if (!PowerOn) {
      SendMsg(
          "Нагрев НБК выключен. Переход к Работе отклонён.",
          ALARM_MSG);
      return;
    }
    const float candidateM = toPower(program[num].Power);
    const float candidateP = program[num].Speed;
    if (!nbk_schedule_actuator_command(
            candidateM,
            candidateP,
            NBK_ACTUATOR_WORK_DEADLINE,
            uint32_t(nbk_column_inertia) * 1000,
            nbk_opt_iter,
            true,
            num)) {
      nbk_enter_safe_wait(
          "Параметры строки W не приняты приводами НБК.");
      return;
    }
    SendMsg(
        "Явный переход к Работе НБК принят: М=" +
            String(candidateM, 0) + " Вт, П=" +
            String(candidateP, 1) + " л/ч",
        NOTIFY_MSG);
    return;
  }
  if (!PowerOn && power_transition_active()) {
    nbk_cancel_program_start("Выключение нагрева ещё не завершено. Старт НБК отменён.");
    return;
  }
  if (num > 0 && !PowerOn) { // [T5] нагрев уже выключен (не переходный процесс) — переход строки НБК запрещён
    nbk_cancel_program_start("Нагрев НБК выключен. Переход к строке №" + String(num + 1) + " отменён.");
    return;
  }
  if (num == 0) {
    if (!nbk_capture_session_config()) {
      nbk_cancel_program_start(
          "Запуск НБК отклонён: некорректная настройка - " + String(nbkSessionConfigError) + ".");
      nbk_close_data_log();
      return;
    }
    nbk_safe_waiting = false;
    nbk_safe_wait_feed_stopped = false;
    nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  }
  ProgramNum = num;
  if (num == 0 && startval == SAMOVAR_STARTVAL_NBK_START) {
    startval = SAMOVAR_STARTVAL_NBK_RUNNING;
  }
 // Сообщение о переходе между этапами
  if (ProgramNum == 0) {
    time_speed = millis();
    stats.startTime = millis();
    stats.avgSpeed = 0;
    stats.avgActiveSpeed = 0;
    stats.totalVolume = 0;
    stats.activeVolume = 0;
    stats.activeFeedMs = 0;
    nbk_work_entry_overflow_pending = false; // [П8] сброс на старте сессии
    if (!create_data()) {
      nbk_cancel_program_start("Ошибка создания файла лога. Старт НБК отменён.");
      return;
    }
    SendMsg("Запуск программы НБК. Прогрев", NOTIFY_MSG);
    #ifdef USE_MQTT
    String sessionDescription;
    if (!copy_mqtt_session_description(sessionDescription, pdMS_TO_TICKS(50))) {
      nbk_cancel_program_start("Описание сессии занято. Старт НБК отменён.");
      mode_warn_log_close_failed();
      return;
    }
    MqttSendMsg(String(chipId) + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_nbk_program() + "," + sessionDescription, "st");
    #endif
  } else {
    SendMsg("Переход к строке №" + (String)(num + 1) + ". Тип: " + program_type_to_string(program[num].WType), NOTIFY_MSG);
  }
  // при переходе на Разгон
  if (program[ProgramNum].WType == 'H') {
    begintime = 0;
    set_power(true);   // Если М и П не заданы в строке, то умолчания:М = разгонная П = 1 л/ч
    if (!PowerOn) {
      nbk_cancel_program_start("Нагрев НБК не включён. Старт отменён.");
      nbk_close_data_log();
      return;
    }
    nbkTransition.programNum = ProgramNum;
    const bool powerStartPending = power_transition_start_pending();
    safety_transition_begin(
      nbkTransition.transition,
      powerStartPending ? NBK_TRANSITION_HEAT_WAIT_POWER : NBK_TRANSITION_HEAT_WAIT,
      powerStartPending ? 0 : safety_deadline_after(millis(), 2500)
    );
  }
  // при переходе на Настройку
   //2) "Ручная настройка" - определение Ин, Тн, Мо и По вручную (инструкция будет)
   //Время не ограничено, переход к следующей строке по кнопке "Следующая программа",
   //при переходе передаём в Оптимизацию текущие М и П.
  if (program[ProgramNum].WType == 'S') {
    begintime = 0;
    time_speed = millis(); // [T10] точка отсчёта статистики объёма — прогрев (H) не должен в неё попадать
    // если параметры есть в строке берём их, иначе минимальные
    const float candidateM = program[ProgramNum].Power > 0
        ? toPower(program[ProgramNum].Power)
        : 0;
    const float candidateP = program[ProgramNum].Speed > 0
        ? program[ProgramNum].Speed
        : 0;
    //set_power(true);
    if (candidateM <= 0 || candidateP <= 0) {
      nbk_enter_safe_wait("Ручная настройка НБК требует ненулевые мощность и подачу.");
      return;
    }
    if (!nbk_schedule_actuator_command(
            candidateM,
            candidateP,
            NBK_ACTUATOR_NO_DEADLINE,
            0,
            nbk_opt_iter)) {
      nbk_enter_safe_wait(
          "Параметры Ручной настройки НБК не приняты.");
    }
  }
  // при переходе на Оптимизацию
 if (program[ProgramNum].WType == 'O') {
      nbk_opt_iter = 0; // в начале оптимизации обнуляем счетчик итераций
      nbk_opt_in_progress = false; // включили паузу перед оптимизацией
      begintime = millis(); // засекли время для паузы перед оптимизацией
      nbk_Mo_temp = toPower(target_power_volt); //запомним на случай пропуска Оптимизации пользователем или по отсутствию ДЗ
      nbk_Po_temp = i2c_get_liquid_rate_by_step(get_stepper_speed());
      noDZ_message_sent = false;
 }
}


// === Проверка критических аварий ===
bool check_nbk_critical_alarms() { //вызывается циклично из этого модуля
 /*ТЗ: В строках "Оптимизация", "Работа":
 Тп > 98°C = "Кончилась брага", М=0, П=0, выключить нагрев ИСПРАВИЛ на 98
 В строке "Ручная настройка" это условие не проверяем, т.к. в инструкции будет юстировка датчика Тб по воде*/
  if (SamovarStatusInt != SAMOVAR_STATUS_NBK || !PowerOn || startval < SAMOVAR_STARTVAL_NBK_RUNNING) {
    nbk_overheat_start_time = 0;
    nbk_dry_steam_start_time = 0; // [Ревью П1, находка 2] симметрично nbk_overheat_start_time
    nbk_pressure_stale_start_time = 0; // [П7] симметрично
    return false;
  }
  if (heater_safety_latched()) { //если авария - в НБК не делаем ничего
    return true;
  }

  if (!mode_check_powered_cooling_sensors("НБК")) return true;

  if (ProgramNum >= NBK_PROGRAM_MAX || ProgramNum >= ProgramLen || ProgramNum >= PROGRAM_END) {
    request_emergency_stop("Ошибка программы НБК: номер строки вне диапазона");
    return true;
  }
  ProgramType currentType = current_program_type();
  if (program_type_empty(currentType)) {
    request_emergency_stop("Ошибка программы НБК: пустая строка программы");
    return true;
  }

  if (currentType != 'S') { // если не Ручная настройка
    if (SteamSensor.avgTemp > 98.0) { // если Т пара больше 98
      SendMsg("Кончилась брага. Программа НБК завершена.", NOTIFY_MSG);
      if (!queue_samovar_command(SAMOVAR_POWER)) {
        request_emergency_stop("Аварийное отключение! Не удалось штатно завершить программу НБК (кончилась брага)");
      }
      return true; //возвращаем аварию
    }
    nbk_dry_steam_start_time = 0; // [T3] предел действует только на Ручной настройке
  } else if (SteamSensor.avgTemp >= 100.0) { // [T3] верхний предел Тп на Ручной настройке — защита от сухого хода парогенератора
    if (nbk_dry_steam_start_time == 0) nbk_dry_steam_start_time = millis();
    if (millis() - nbk_dry_steam_start_time > 60000) {
      SendMsg("Т пара выше предела 60 секунд на Ручной настройке. Возможен сухой ход парогенератора. Программа НБК завершена.", NOTIFY_MSG);
      if (!queue_samovar_command(SAMOVAR_POWER)) {
        request_emergency_stop("Аварийное отключение! Не удалось штатно завершить программу НБК (перегрев пара на Ручной настройке)");
      }
      return true;
    }
  } else {
    nbk_dry_steam_start_time = 0;
  }
    //ТЗ: Во всех "Разгон", "Ручная настройка", "Оптимизация", "Работа":
    //    Ттса > 60°C или Тводы > 70°C в течении 60 сек подряд = "Недостаточное охлаждение" (штатное)
    if (sensor_temp_at_least(ACPSensor, 60.0f) || WaterSensor.avgTemp > MAX_WATER_TEMP) {
      if (nbk_overheat_start_time == 0) nbk_overheat_start_time = millis();
      if (millis() - nbk_overheat_start_time > 60000) {//ждем 60 сек
        request_emergency_stop("Недостаточное охлаждение! Останов.");
        return true;
      }
    } else {
      nbk_overheat_start_time = 0; // сброс счетчика времени, ситуация выправилась
    }

    // [П7] Устойчивая потеря показаний ДД дольше 60 с — отдельный аварийный
    // останов по аналогии с "Недостаточное охлаждение" выше: пока данные
    // несвежие, overflow() уже трактует это как захлёб (с. выше), но отказ
    // датчика сам по себе не должен молча удерживать процесс бесконечно.
    if (nbk_pressure_stale()) {
      if (nbk_pressure_stale_start_time == 0) nbk_pressure_stale_start_time = millis();
      if (millis() - nbk_pressure_stale_start_time > 60000) {//ждем 60 сек
        request_emergency_stop("Отказ датчика давления! Нет показаний более 60 секунд. Останов.");
        return true;
      }
    } else {
      nbk_pressure_stale_start_time = 0; // сброс счетчика времени, показания снова свежие
    }

  return false;
}


// === Тоже Проверка критических аварий === в основном по воде
void check_alarm_nbk() {// вызывается из Samovar.ino, надо разобраться что оставить, я уже кой чего поубирал
  // Если нагрев выключен и это не самотестирование и вода включена и Т воды на 20 и более гр. ниже уставки
  if (mode_should_close_cooling(TARGET_WATER_TEMP - 20, false)) {
    open_valve(false, true); //призыв закрыть воду либо закрытие клапана
    mode_stop_cooling_pump_if_started(); // стоп водяной насос
  }

  if (!PowerOn) { // нет нагрева - больше ничего не проверяем
    return;
  }

  //сбросим паузу события безопасности
  mode_clear_alarm_pause_if_expired();

#ifdef SAMOVAR_USE_POWER
  // [PKG-B п.3] Единая с прочими режимами проверка регулятора: потеря связи/пробой семистора —
  // в сторону выключения нагрева.
  check_power_error();
#endif

  // Если нагрев включен и вода и температура в бардоотвотчике больше уставки включения воды
  if (mode_should_open_cooling(true, false, true)) {
    open_valve(true, true); // призыв включить воду или открытие клапана
  }

  // регулируем водяной насос
  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  // Если Т в ТСА больше предела и Т в ТСА больше Т воды (?) - крутим водяной насос усерднее, будто Т воды выше на 3 гр.
  mode_update_water_pump_pid(SamSetup.SetACPTemp);

  //Проверим, что вода подается
  mode_request_water_flow_emergency_if_needed(); //датчик протока сломался уже

  if (mode_water_pre_alarm_due()) {
    set_buzzer(true);
    SendMsg(("Критическая температура воды!"), WARNING_MSG);
    mode_set_alarm_pause_ms(60000);
  }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}


inline bool nbk_close_data_log() {
  if (request_data_log_close()) return true;
  SendMsg("Файл лога занят: закрытие не выполнено", WARNING_MSG);
  return false;
}

inline void tick_nbk_transition() {
  const SafetyTransitionPhase phase = nbkTransition.transition.phase;
  if (phase == SAFETY_TRANSITION_IDLE) return;

  if (nbk_finish_transition_active()) {
    const bool finishOwnerValid = Samovar_Mode == SAMOVAR_NBK_MODE &&
      SamovarStatusInt == SAMOVAR_STATUS_IDLE && startval == SAMOVAR_STARTVAL_IDLE;
    if (!finishOwnerValid && phase != NBK_TRANSITION_FINISH_WAIT_POWER_OFF) {
      set_power(false, false);
      safety_transition_advance(
        nbkTransition.transition,
        NBK_TRANSITION_FINISH_WAIT_POWER_OFF,
        0
      );
      return;
    }
  }

  if (phase == NBK_TRANSITION_FINISH_WAIT) {
    if (!safety_transition_due(nbkTransition.transition, millis())) return;
    set_power(false);
    safety_transition_advance(
      nbkTransition.transition,
      NBK_TRANSITION_FINISH_WAIT_POWER_OFF,
      0
    );
    return;
  }

  if (phase == NBK_TRANSITION_FINISH_WAIT_POWER_OFF ||
      phase == NBK_TRANSITION_HEAT_CANCEL_WAIT_POWER_OFF) {
    if (power_transition_active()) return;
    if (!nbkTransition.powerOffCleanupStarted) {
      // [PKG-B п.5] Однократно на фазу: сброс счётчика датчиков и (при занятом логе)
      // одно уведомление оператора. Повторные попытки закрытия — тихо, без спама на каждый loop.
      reset_sensor_counter();
      nbkTransition.powerOffCleanupStarted = true;
      if (!nbk_close_data_log()) return;
    } else if (!request_data_log_close()) {
      return;
    }
    cancel_nbk_transition();
    return;
  }

  const bool heatStageValid = !heater_safety_latched() && PowerOn && SamovarStatusInt == SAMOVAR_STATUS_NBK &&
    ProgramNum == nbkTransition.programNum && ProgramNum < ProgramLen &&
    ProgramNum < NBK_PROGRAM_MAX && program[ProgramNum].WType == 'H';
  if (!heatStageValid) {
    // [PKG-B п.1] Запуск нагрева НБК сорвался (авария/снятие питания/смена статуса).
    // Гасим нагрев И полностью сбрасываем состояние процесса, иначе UI показывает
    // «процесс идёт» при выключенном нагреве (зомби-состояние).
    const bool resetOwnerState = SamovarStatusInt == SAMOVAR_STATUS_NBK;
    set_power(false, false);
    SendMsg("Запуск нагрева НБК прерван: условие старта нарушено, процесс остановлен.", ALARM_MSG);
    if (resetOwnerState) {
      ProgramNum = 0;
      startval = SAMOVAR_STARTVAL_IDLE;
      SamovarStatusInt = SAMOVAR_STATUS_IDLE;
    }
    safety_transition_advance(
      nbkTransition.transition,
      NBK_TRANSITION_HEAT_CANCEL_WAIT_POWER_OFF,
      0
    );
    return;
  }

  if (phase == NBK_TRANSITION_HEAT_WAIT_POWER) {
    if (power_transition_start_pending()) return;
    safety_transition_advance(
      nbkTransition.transition,
      NBK_TRANSITION_HEAT_WAIT,
      safety_deadline_after(millis(), 2500)
    );
    return;
  }

  if (!safety_transition_due(nbkTransition.transition, millis())) return;
  safety_transition_cancel(nbkTransition.transition);
  const float candidateM = program[ProgramNum].Power > 0
      ? toPower(program[ProgramNum].Power)
      : nbk_M_max;
  const float candidateP = program[ProgramNum].Speed > 0
      ? program[ProgramNum].Speed
      : 0;
  if (candidateP <= 0 ||
      !nbk_schedule_actuator_command(
          candidateM,
          candidateP,
          NBK_ACTUATOR_NO_DEADLINE,
          0,
          nbk_opt_iter)) {
    nbk_enter_safe_wait(
        "Разгон НБК требует подтверждаемую ненулевую подачу.");
  }
}

void nbk_finish_common(bool resetWorkState) {
  SendMsg("Работа НБК завершена", NOTIFY_MSG);
  nbk_reset_actuator_command();
  if (SetSpeed(0) != ACTUATOR_COMMAND_APPLIED) {
    SendMsg(
        "Останов насоса НБК не подтверждён при завершении.",
        ALARM_MSG);
  }
  nbk_overheat_start_time = 0;
  // Вычислить и отправить статистику
  uint32_t totalTime = stats.startTime > 0 ? (millis() - stats.startTime) / 1000 : 0; // в секундах
  if (totalTime > 0) {
    stats.avgSpeed = (stats.totalVolume * 3600.0) / (float)totalTime;
  } else {
    stats.avgSpeed = 0;
  }
  stats.avgActiveSpeed = stats.activeFeedMs > 0
      ? stats.activeVolume * 3600000.0f / stats.activeFeedMs
      : 0;

  if (stats.startTime > 0) {
    String summary = "";//"Итоги работы НБК:\n";
    summary += "Пропущено браги " + String(stats.totalVolume, 2) + " л ";
    summary += "со средней скоростью сессии " + String(stats.avgSpeed, 2) + " л/ч ";
    summary += "и средней скоростью подачи " + String(stats.avgActiveSpeed, 2) + " л/ч ";
    summary += "за: " + String(totalTime / 3600.0, 2) + " ч.";
    SendMsg(summary, NOTIFY_MSG);
  }
  ProgramNum = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  if (resetWorkState) {
    nbk_M = 0;
    nbk_P = 0;
  }
  stats.startTime = 0;
  stats.avgSpeed = 0;
  stats.avgActiveSpeed = 0;
  stats.totalVolume = 0;
  stats.activeVolume = 0;
  stats.activeFeedMs = 0;
  nbk_safe_waiting = false;
  nbk_safe_wait_feed_stopped = false;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  nbk_clear_session_config();
}

// Окончание программы НБК
inline void nbk_finish() {
  if (nbk_finish_transition_active()) return;
  const bool heatStartupPending = nbk_transition_blocks_process();
  if (heatStartupPending) set_power(false, false);
  cancel_nbk_transition();
  nbk_finish_common(false);
  safety_transition_begin(
    nbkTransition.transition,
    heatStartupPending ? NBK_TRANSITION_FINISH_WAIT_POWER_OFF : NBK_TRANSITION_FINISH_WAIT,
    heatStartupPending ? 0 : safety_deadline_after(millis(), 1000)
  );
}

inline void nbk_emergency_finish() {
  // [PKG-B п.6б] Если переход был в фазе с открытым логом (finish/heat-cancel), запомним
  // это ДО отмены перехода — иначе ранний выход отменит retry закрытия и бросит файл открытым.
  const SafetyTransitionPhase transitionPhase = nbkTransition.transition.phase;
  const bool logClosePending =
    transitionPhase == NBK_TRANSITION_FINISH_WAIT ||
    transitionPhase == NBK_TRANSITION_FINISH_WAIT_POWER_OFF ||
    transitionPhase == NBK_TRANSITION_HEAT_CANCEL_WAIT_POWER_OFF;
  cancel_nbk_transition();
  if (stats.startTime == 0 && startval < SAMOVAR_STARTVAL_NBK_RUNNING && !PowerOn) {
    nbk_reset_actuator_command();
    ProgramNum = 0;
    startval = SAMOVAR_STARTVAL_IDLE;
    SamovarStatusInt = SAMOVAR_STATUS_IDLE;
    nbk_M = 0;
    nbk_P = 0;
    if (logClosePending) nbk_close_data_log();
    return;
  }

  nbk_finish_common(true);
  nbk_close_data_log();
}
// === Централизованная обработка захлёба ===
void handle_overflow(const String& msg, bool finish, uint32_t pause_ms, bool graceful) {
  const float candidateP = nbk_P / 3;
  SendMsg("Захлёб по " + String(nbk_overflow_source()) + ". " + msg, graceful ? NOTIFY_MSG : ALARM_MSG); // [Ревью П1, находка 3] восстановлена дифференциация по датчику
  if (finish) {
    if (SetSpeed(candidateP) != ACTUATOR_COMMAND_APPLIED) {
      SendMsg(
          "Снижение подачи НБК при захлёбе не подтверждено.",
          ALARM_MSG);
    }
    if (graceful) {
      if (!queue_samovar_command(SAMOVAR_POWER)) {
        request_emergency_stop("Аварийное отключение! Не удалось штатно завершить программу НБК (захлёб)");
      }
    } else {
      request_emergency_stop("");
    }
  } else if (pause_ms > 0) { // Для этапа W: пауза и переход к восстановлению
    if (!nbk_schedule_actuator_command(
            nbk_Mo / 2,
            candidateP,
            NBK_ACTUATOR_WORK_DEADLINE,
            pause_ms,
            nbk_opt_iter)) {
      nbk_enter_safe_wait(
          "Снижение приводов НБК при захлёбе не принято.");
      return;
    }
    nbk_work_in_pause = true;
    nbk_work_pause_stage = 1;
    nbk_overflow_happened = true; // захлёб зафиксирован — guard по снижению Mo/Po должен сработать
    nbk_pause_overflow_repeat_latched = false; // [T1] новая пауза W — не подавлять первое сообщение о повторном захлёбе
  }
}


ProgramParseResult set_nbk_program(const String& WProgram) {
  return program_parse_lines(WProgram, nbk_program_parse_spec());
}


String get_nbk_program() {
  return program_serialize_rows(0, PROGRAM_END, program_append_nbk_row);
}
