#pragma once

#include <Arduino.h>

#include "Samovar.h"
#include "beer.h"
#include "program_io.h"
#include "runtime_helpers.h"

#ifndef CHEESE_TEMPERATURE_DELTA
#define CHEESE_TEMPERATURE_DELTA 0.3f
#endif
#define CHEESE_TEMPERATURE_CONFIRM_MS 10000UL
#define CHEESE_PH_CONFIRM_MS 30000UL
#define CHEESE_PH_INVALID_MS 10000UL
#define CHEESE_PH_SAMPLE_INTERVAL_MS 1000UL
#define CHEESE_PH_STALE_MS 5000UL

enum CheeseStageKind : uint8_t {
  CHEESE_STAGE_INVALID = 0,
  CHEESE_STAGE_HEAT,
  CHEESE_STAGE_HOLD,
  CHEESE_STAGE_COOL,
  CHEESE_STAGE_MIX,
  CHEESE_STAGE_DOSE,
  CHEESE_STAGE_PH,
  CHEESE_STAGE_WAIT,
  CHEESE_STAGE_DRAIN,
  CHEESE_STAGE_LUA,
};

enum CheeseLuaStagePhase : uint8_t {
  CHEESE_LUA_STAGE_IDLE = 0,
  CHEESE_LUA_STAGE_ENTER_QUEUED,
  CHEESE_LUA_STAGE_RUNNING,
  CHEESE_LUA_STAGE_EXIT_REQUESTED,
  CHEESE_LUA_STAGE_EXIT_QUEUED,
};

struct CheeseLuaStageState {
  CheeseLuaStagePhase phase;
  uint32_t ticket;
  uint8_t nextProgram;
};

struct CheeseRuntimeState {
  uint32_t enteredMs;
  uint32_t lastTickMs;
  uint32_t temperatureConfirmSinceMs;
  uint32_t holdAccumulatedMs;
  uint32_t mixerDeadlineMs;
  uint32_t phReachedSinceMs;
  uint32_t phInvalidSinceMs;
  float heatStartSetpoint;
  uint8_t mixerDevice;
  bool mixerRunning;
  bool mixerOneShotComplete;
  bool doserStarted;
  bool doserCompleted;
  bool drainOpen;
  bool temperatureConfirmActive;
  bool phReachedActive;
  bool phInvalidActive;
};

static CheeseLuaStageState cheeseLuaStage = {
    CHEESE_LUA_STAGE_IDLE, 0, PROGRAM_END};
static CheeseRuntimeState cheeseRuntime = {};
static bool cheeseFinishPending = false;
static bool cheesePairErrorPending = false;
static int cheesePhRaw = 0;
static float cheesePhValue = 0.0f;
static bool cheesePhValid = false;
static bool cheesePhSampled = false;
static uint32_t cheesePhSampleMs = 0;
static bool cheesePhSampleAttempted = false;
static uint32_t cheesePhLastAttemptMs = 0;
#ifdef USE_ADS1115
static bool cheesePhAds1115Ready = false;
#endif

inline CheeseStageKind cheese_stage_kind(ProgramType type) {
  switch (type) {
    case 'H': return CHEESE_STAGE_HEAT;
    case 'P': return CHEESE_STAGE_HOLD;
    case 'C': return CHEESE_STAGE_COOL;
    case 'M': return CHEESE_STAGE_MIX;
    case 'D': return CHEESE_STAGE_DOSE;
    case 'N': return CHEESE_STAGE_PH;
    case 'W': return CHEESE_STAGE_WAIT;
    case 'S': return CHEESE_STAGE_DRAIN;
    case 'L': return CHEESE_STAGE_LUA;
    default: return CHEESE_STAGE_INVALID;
  }
}

inline bool cheese_time_elapsed(uint32_t nowMs, uint32_t startedMs,
                                float minutes) {
  return static_cast<float>(nowMs - startedMs) >= minutes * 60000.0f;
}

inline float cheese_stage_timeout_minutes(const WProgram& row) {
  return cheese_stage_kind(row.WType) == CHEESE_STAGE_HOLD ? row.Param : row.Time;
}

inline bool cheese_runtime_active() {
  return Samovar_Mode == SAMOVAR_CHEESE_MODE &&
      SamovarStatusInt == SAMOVAR_STATUS_CHEESE && PowerOn &&
      startval > SAMOVAR_STARTVAL_CHEESE_START && !cheeseFinishPending &&
      ProgramNum < ProgramLen && ProgramNum < PROGRAM_END;
}

inline uint32_t cheese_stage_elapsed_ms() {
  return millis() - cheeseRuntime.enteredMs;
}

inline uint32_t cheese_work_seconds() {
  if (!cheese_runtime_active()) return 0;
  return cheese_stage_kind(program[ProgramNum].WType) == CHEESE_STAGE_HOLD ?
      cheeseRuntime.holdAccumulatedMs / 1000UL : cheese_stage_elapsed_ms() / 1000UL;
}

inline uint32_t cheese_timeout_remaining_seconds() {
  if (!cheese_runtime_active()) return 0;
  const WProgram& row = program[ProgramNum];
  const float timeoutSeconds = row.WType == 'L'
      ? row.Time : cheese_stage_timeout_minutes(row) * 60.0f;
  const float remaining = timeoutSeconds -
      static_cast<float>(cheese_stage_elapsed_ms()) / 1000.0f;
  return remaining > 0.0f ? static_cast<uint32_t>(ceilf(remaining)) : 0;
}

inline bool cheese_in_temperature_band(float temperature, float target) {
  return fabsf(temperature - target) <= CHEESE_TEMPERATURE_DELTA;
}

inline bool cheese_temperature_confirmed(uint32_t nowMs, bool inBand) {
  if (!inBand) {
    cheeseRuntime.temperatureConfirmActive = false;
    return false;
  }
  if (!cheeseRuntime.temperatureConfirmActive) {
    cheeseRuntime.temperatureConfirmSinceMs = nowMs;
    cheeseRuntime.temperatureConfirmActive = true;
    runtime_pair_begin(UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM,
                       "Подтверждение температуры начато", NOTIFY_MSG);
    return false;
  }
  return nowMs - cheeseRuntime.temperatureConfirmSinceMs >=
      CHEESE_TEMPERATURE_CONFIRM_MS;
}

inline float cheese_calibrated_ph(int raw, float slope, float offset) {
  return slope * raw + offset;
}

inline bool cheese_ph_calibration_valid(float slope, float offset) {
  return isfinite(slope) && isfinite(offset) && slope >= -100.0f &&
      slope <= 100.0f && offset >= -100.0f && offset <= 100.0f &&
      slope != 0.0f;
}

inline int cheese_ph_raw() { return cheesePhRaw; }
inline float cheese_ph_value() { return cheesePhValue; }
inline bool cheese_ph_valid() {
  return cheesePhValid && millis() - cheesePhSampleMs <= CHEESE_PH_STALE_MS;
}
inline bool cheese_ph_raw_valid() {
  return cheesePhSampled && millis() - cheesePhSampleMs <= CHEESE_PH_STALE_MS;
}

inline int cheese_median3(int a, int b, int c) {
  if (a > b) { int t = a; a = b; b = t; }
  if (b > c) { int t = b; b = c; c = t; }
  if (a > b) { int t = a; a = b; b = t; }
  return b;
}

#ifdef USE_ADS1115
inline bool cheese_ads1115_configure() {
  // AIN0 относительно GND, диапазон ±4,096 В, непрерывное преобразование 128 раз/с.
  cheesePhAds1115Ready =
      i2c_stepper_write_u16(USE_ADS1115, 0x01, 0xC283);
  return cheesePhAds1115Ready;
}

inline bool cheese_ads1115_read_raw(int& raw) {
  uint16_t value = 0;
  if (!i2c_stepper_read_u16(USE_ADS1115, 0x00, value, 50)) {
    cheesePhAds1115Ready = false;
    return false;
  }
  raw = static_cast<int16_t>(value);
  cheesePhAds1115Ready = true;
  return true;
}
#endif

inline bool cheese_ph_prepare() {
#ifdef USE_ADS1115
  return cheesePhAds1115Ready || cheese_ads1115_configure();
#else
  return true;
#endif
}

inline void cheese_ph_init() {
  cheese_ph_prepare();
}

inline bool cheese_ph_available() {
#ifdef USE_ADS1115
  return cheesePhAds1115Ready;
#else
  return true;
#endif
}

inline int cheese_ph_ads1115_address() {
#ifdef USE_ADS1115
  return USE_ADS1115;
#else
  return 0;
#endif
}

inline bool cheese_read_ph_raw(int& raw) {
#ifdef USE_ADS1115
  return cheese_ph_prepare() && cheese_ads1115_read_raw(raw);
#else
  raw = cheese_median3(analogRead(LUA_PIN), analogRead(LUA_PIN),
                       analogRead(LUA_PIN));
  return true;
#endif
}

inline void cheese_sample_ph(uint32_t nowMs) {
  if (cheesePhSampleAttempted &&
      nowMs - cheesePhLastAttemptMs < CHEESE_PH_SAMPLE_INTERVAL_MS) return;
  cheesePhSampleAttempted = true;
  cheesePhLastAttemptMs = nowMs;
  int raw = 0;
  if (!cheese_read_ph_raw(raw)) {
    cheesePhSampled = false;
    cheesePhValid = false;
    return;
  }
  cheesePhRaw = raw;
  cheesePhSampleMs = nowMs;
  cheesePhSampled = true;
  const float measured = cheese_calibrated_ph(
      raw, SamSetup.CheesePhSlope, SamSetup.CheesePhOffset);
  cheesePhValid = cheese_ph_calibration_valid(
      SamSetup.CheesePhSlope, SamSetup.CheesePhOffset) &&
      isfinite(measured) && measured >= 0.0f && measured <= 14.0f;
  if (cheesePhValid) cheesePhValue = measured;
}

inline void cheese_ph_tick() {
  if (Samovar_Mode == SAMOVAR_CHEESE_MODE) cheese_sample_ph(millis());
}

inline void cheese_set_drain(bool open) {
  digitalWrite(RELE_CHANNEL4, open ? SamSetup.rele4 : !SamSetup.rele4);
  cheeseRuntime.drainOpen = open;
}

inline bool cheese_mixer_start(const WProgram& row) {
  if (row.capacity_num == 1) {
    digitalWrite(RELE_CHANNEL2, SamSetup.rele2);
  } else if (row.capacity_num == 2) {
    if (!i2c_stepper_mixer_present() ||
        !set_stepper_by_time(static_cast<uint16_t>(fabsf(row.Speed)),
                             row.Speed < 0.0f, row.Volume)) return false;
  } else if (row.capacity_num != 0) {
    return false;
  }
  cheeseRuntime.mixerRunning = row.capacity_num != 0;
  mixer_status = cheeseRuntime.mixerRunning;
  return true;
}

inline bool cheese_mixer_stop() {
  if (cheeseRuntime.mixerDevice == 1) {
    digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  } else if (cheeseRuntime.mixerDevice == 2 &&
             !set_stepper_by_time(0, false, 0)) {
    return false;
  }
  cheeseRuntime.mixerRunning = false;
  mixer_status = false;
  return true;
}

inline bool cheese_configure_mixer(const WProgram& row, uint32_t nowMs) {
  cheeseRuntime.mixerDevice = row.capacity_num;
  cheeseRuntime.mixerOneShotComplete = false;
  cheeseRuntime.mixerDeadlineMs = 0;
  if (row.capacity_num == 0) return true;
  if (!cheese_mixer_start(row)) return false;
  if (row.Volume > 0) cheeseRuntime.mixerDeadlineMs = nowMs + row.Volume * 1000UL;
  return true;
}

inline bool cheese_mixer_tick(const WProgram& row, uint32_t nowMs) {
  if (cheeseRuntime.mixerDevice == 0 || row.Volume == 0) return true;
  if (cheeseRuntime.mixerRunning &&
      static_cast<int32_t>(nowMs - cheeseRuntime.mixerDeadlineMs) >= 0) {
    if (!cheese_mixer_stop()) return false;
    if (row.Power == 0.0f) {
      cheeseRuntime.mixerOneShotComplete = true;
      return true;
    }
    cheeseRuntime.mixerDeadlineMs = nowMs +
        static_cast<uint32_t>(row.Power * 1000.0f);
    return true;
  }
  if (!cheeseRuntime.mixerRunning && !cheeseRuntime.mixerOneShotComplete &&
      static_cast<int32_t>(nowMs - cheeseRuntime.mixerDeadlineMs) >= 0) {
    if (!cheese_mixer_start(row)) return false;
    cheeseRuntime.mixerDeadlineMs = nowMs + row.Volume * 1000UL;
  }
  return true;
}

inline bool cheese_ph_target_confirmed(uint32_t nowMs, bool reached) {
  if (!reached) {
    cheeseRuntime.phReachedActive = false;
    return false;
  }
  if (!cheeseRuntime.phReachedActive) {
    cheeseRuntime.phReachedSinceMs = nowMs;
    cheeseRuntime.phReachedActive = true;
    runtime_pair_begin(UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM,
                       "Подтверждение pH начато", NOTIFY_MSG);
    return false;
  }
  return nowMs - cheeseRuntime.phReachedSinceMs >= CHEESE_PH_CONFIRM_MS;
}

inline bool cheese_ph_invalid_too_long(uint32_t nowMs, bool valid) {
  if (valid) {
    cheeseRuntime.phInvalidActive = false;
    return false;
  }
  if (!cheeseRuntime.phInvalidActive) {
    cheeseRuntime.phInvalidSinceMs = nowMs;
    cheeseRuntime.phInvalidActive = true;
    return false;
  }
  return nowMs - cheeseRuntime.phInvalidSinceMs >= CHEESE_PH_INVALID_MS;
}

inline bool cheese_set_cooling_outputs(bool active, bool highFlow) {
#ifdef USE_WATER_PUMP
  if (!active) return beer_set_cooling_outputs(false) == ACTUATOR_COMMAND_APPLIED;
  if (beer_set_cooling_outputs(true) != ACTUATOR_COMMAND_APPLIED) return false;
  if (!highFlow && set_pump_pwm(PWM_LOW_VALUE * 10) != ACTUATOR_COMMAND_APPLIED) {
    return false;
  }
  return true;
#elif defined(USE_WATER_VALVE)
  if (!active) {
    digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
    return open_valve(false, false) == ACTUATOR_COMMAND_APPLIED;
  }
  if (open_valve(true, false) != ACTUATOR_COMMAND_APPLIED) return false;
  digitalWrite(WATER_PUMP_PIN, highFlow ? USE_WATER_VALVE : !USE_WATER_VALVE);
  return true;
#else
  if (!active) return true;
  (void)highFlow;
  return false;
#endif
}

inline bool cheese_apply_safe_outputs(bool closeDrain) {
  bool applied = true;
  setHeaterPosition(false);
  if (!cheese_set_cooling_outputs(false, false)) applied = false;
  if (!cheese_mixer_stop()) applied = false;
  stopService();
  stepper_safe_stop_reset();
  startService();
  StepperMoving = false;
  TargetStepps = 0;
  cheeseRuntime.doserStarted = false;
  cheeseRuntime.doserCompleted = false;
  if (closeDrain) cheese_set_drain(false);
  if (!applied) {
    request_emergency_stop("Аварийное отключение: не удалось выключить оборудование сыроварения");
  }
  return applied;
}

inline void cheese_reset_lua_stage() {
  cheeseLuaStage.phase = CHEESE_LUA_STAGE_IDLE;
  cheeseLuaStage.ticket = 0;
  cheeseLuaStage.nextProgram = PROGRAM_END;
}

inline bool cheese_lua_stop_pending() {
  return cheeseFinishPending && cheeseLuaStage.phase != CHEESE_LUA_STAGE_IDLE;
}

inline void cheese_reset_stage_state() {
  cheeseRuntime = {};
  cheesePairErrorPending = false;
  cheesePhRaw = 0;
  cheesePhValue = 0.0f;
  cheesePhValid = false;
  cheesePhSampled = false;
  cheesePhSampleMs = 0;
  cheesePhSampleAttempted = false;
  cheesePhLastAttemptMs = 0;
  cheeseFinishPending = false;
  cheese_reset_lua_stage();
}

inline bool cheese_request_lua_exit(uint8_t targetProgram) {
  if (!cheese_apply_safe_outputs(true)) return false;
  cheeseLuaStage.nextProgram = targetProgram;
  cheeseLuaStage.phase = CHEESE_LUA_STAGE_EXIT_REQUESTED;
  return true;
}

inline bool cheese_finish_lua_exit() {
  if (cheeseLuaStage.phase == CHEESE_LUA_STAGE_IDLE) return true;
#ifdef USE_LUA
  if (cheeseLuaStage.phase != CHEESE_LUA_STAGE_EXIT_QUEUED) {
    const ActuatorCommandResult result = request_beer_lua_stop(cheeseLuaStage.ticket);
    if (result == ACTUATOR_COMMAND_PENDING) return false;
    if (result != ACTUATOR_COMMAND_APPLIED) return false;
    cheeseLuaStage.phase = CHEESE_LUA_STAGE_EXIT_QUEUED;
  }
  if (!beer_lua_job_idle(cheeseLuaStage.ticket)) return false;
  cheese_reset_lua_stage();
  return true;
#else
  return false;
#endif
}

inline const char* cheese_stage_name(ProgramType type) {
  switch (type) {
    case 'H': return "Нагрев";
    case 'P': return "Выдержка";
    case 'C': return "Охлаждение";
    case 'M': return "Перемешивание";
    case 'D': return "Дозирование";
    case 'N': return "Ожидание pH";
    case 'W': return "Ручное действие";
    case 'S': return "Слив";
    case 'L': return "Lua";
    default: return "Неизвестная операция";
  }
}

void cheese_finish();
void run_cheese_program(uint8_t num);

inline void cheese_abort(const String& reason) {
  cheesePairErrorPending = true;
  SendMsg("Строка " + String(ProgramNum + 1) + ": " + reason, ALARM_MSG);
  cheese_finish();
}

inline bool cheese_row_needs_sensor(CheeseStageKind kind) {
  return kind == CHEESE_STAGE_HEAT || kind == CHEESE_STAGE_HOLD ||
      kind == CHEESE_STAGE_COOL || kind == CHEESE_STAGE_PH;
}

inline bool cheese_local_doser_motion(const WProgram& row,
                                      uint32_t& targetSteps, float& speed) {
  const double target = static_cast<double>(row.Temp) * SamSetup.StepperStepMl;
  const double requestedSpeed =
      static_cast<double>(row.Param) * SamSetup.StepperStepMl / 60.0;
  if (!isfinite(target) || !isfinite(requestedSpeed) || target <= 0.0 ||
      target > INT32_MAX || requestedSpeed <= 0.0 || requestedSpeed > UINT16_MAX) {
    return false;
  }
  targetSteps = static_cast<uint32_t>(target);
  if (targetSteps < 1) return false;
  speed = static_cast<float>(requestedSpeed);
  return true;
}

inline bool cheese_validate_program(String& error) {
  if (ProgramLen == 0 || ProgramLen > PROGRAM_END) {
    error = "Ошибка программы Сыр: строка не задана";
    return false;
  }
  for (uint8_t i = 0; i < ProgramLen; i++) {
    const WProgram& row = program[i];
    const CheeseStageKind kind = cheese_stage_kind(row.WType);
    const char* semanticError = nullptr;
    if (kind == CHEESE_STAGE_INVALID ||
        !program_validate_cheese_row_semantics(
            row.WType, row.Temp, row.Time, row.capacity_num,
            static_cast<long>(row.Speed), row.Volume,
            static_cast<long>(row.Power), row.TempSensor, row.Param,
            semanticError)) {
      error = String(semanticError ? semanticError : "Ошибка программы") +
          " в строке " + String(i + 1);
      return false;
    }
    if (cheese_row_needs_sensor(kind)) {
      const DSSensor* sensor = nullptr;
      const char* sensorName = "";
      if (!beer_control_sensor(row.TempSensor, sensor, sensorName)) {
        error = "Ошибка датчика температуры в строке " + String(i + 1);
        return false;
      }
    }
    if (row.capacity_num == 2 && !i2c_stepper_mixer_present()) {
      error = "I2C-мешалка недоступна в строке " + String(i + 1);
      return false;
    }
    if (kind == CHEESE_STAGE_DOSE && row.TempSensor == 2) {
      uint32_t targetSteps = 0;
      float speed = 0.0f;
      if (!cheese_local_doser_motion(row, targetSteps, speed)) {
        error = "Локальный дозатор недоступен в строке " + String(i + 1);
        return false;
      }
    }
    if (kind == CHEESE_STAGE_COOL) {
#if !defined(USE_WATER_PUMP) && !defined(USE_WATER_VALVE)
      error = "Охлаждение недоступно в этой сборке";
      return false;
#endif
    }
    if (kind == CHEESE_STAGE_PH &&
        (!isfinite(SamSetup.CheesePhSlope) || !isfinite(SamSetup.CheesePhOffset))) {
      error = "Калибровка pH недопустима в строке " + String(i + 1);
      return false;
    }
    if (kind == CHEESE_STAGE_LUA) {
#ifndef USE_LUA
      error = "Lua недоступна в этой сборке";
      return false;
#else
      if (!exists("/cheese.lua")) {
        error = "Lua-файл /cheese.lua не найден в строке " + String(i + 1);
        return false;
      }
#endif
    }
  }
  return true;
}

inline bool cheese_start_local_doser(const WProgram& row) {
  uint32_t targetSteps = 0;
  float speed = 0.0f;
  if (!cheese_local_doser_motion(row, targetSteps, speed)) return false;
  stopService();
  stepper_safe_stop_reset();
#ifdef STEPPER_REVERSE
  stepper_safe_reverse(true);
#else
  stepper_safe_reverse(false);
#endif
  TargetStepps = static_cast<unsigned int>(targetSteps);
  stepper_safe_set_motion(speed, 0,
                          static_cast<int32_t>(TargetStepps));
  StepperMoving = true;
  stepper.enable();
  startService();
  cheeseRuntime.doserStarted = true;
  return true;
}

inline bool cheese_local_doser_complete() {
  return cheeseRuntime.doserStarted && !StepperMoving && TargetStepps > 0 &&
      stepper_safe_get_current() >= static_cast<int32_t>(TargetStepps);
}

inline bool cheese_prepare_stage(uint8_t targetProgram) {
  if (!cheese_apply_safe_outputs(true)) return false;
  alarm_c_min = 0;
  alarm_c_low_min = 0;
  currentstepcnt = 0;
  beerMixerPauseSinceMs = 0;
  const uint32_t nowMs = millis();
  ProgramNum = targetProgram;
  begintime = nowMs;
  msgfl = true;
  cheeseRuntime = {};
  const WProgram& row = program[ProgramNum];
  if (row.WType == 'L') {
#ifdef USE_LUA
    uint32_t ticket = 0;
    if (!request_program_lua_job(targetProgram, ticket)) return false;
    cheeseLuaStage.phase = CHEESE_LUA_STAGE_ENTER_QUEUED;
    cheeseLuaStage.ticket = ticket;
    cheeseLuaStage.nextProgram = PROGRAM_END;
    runtime_pair_begin(UI_WAIT_LUA_KNOWN, "Lua-задача принята", NOTIFY_MSG);
#else
    return false;
#endif
  } else {
    if (row.WType != 'S' && !cheese_configure_mixer(row, nowMs)) return false;
    if (row.WType == 'D' && row.TempSensor == 2 &&
        !cheese_start_local_doser(row)) return false;
    if (row.WType == 'S') cheese_set_drain(true);
  }
  cheeseRuntime.enteredMs = nowMs;
  cheeseRuntime.lastTickMs = nowMs;
  cheeseRuntime.heatStartSetpoint = NAN;
  startval = SAMOVAR_STARTVAL_CHEESE_START + 1;
  runtime_pair_close_mode(SAMOVAR_CHEESE_MODE, RUNTIME_PAIR_ROW_CHANGE,
                          "Переход к следующей строке", NOTIFY_MSG);
  if (row.WType == 'W') {
    runtime_pair_begin(UI_WAIT_CHEESE_OPERATOR, "Ожидание действия оператора", NOTIFY_MSG);
  } else if (row.WType == 'D' && row.TempSensor == 2) {
    runtime_pair_begin(UI_WAIT_CHEESE_DOSE, "Дозатор запущен", NOTIFY_MSG);
  }
  SendMsg("Строка " + String(ProgramNum + 1) + "; " +
          cheese_stage_name(row.WType), NOTIFY_MSG);
  return true;
}

void run_cheese_program(uint8_t num) {
  if (Samovar_Mode != SAMOVAR_CHEESE_MODE || !PowerOn) return;
  const uint8_t targetProgram = num < ProgramLen && num < PROGRAM_END
      ? num : PROGRAM_END;
  if (cheeseLuaStage.phase != CHEESE_LUA_STAGE_IDLE) {
    if (!cheese_request_lua_exit(targetProgram)) {
      cheese_abort("Ошибка Lua: не удалось выключить выходы");
    }
    return;
  }
  if (targetProgram == PROGRAM_END) {
    cheese_finish();
    return;
  }
  if (!cheese_prepare_stage(targetProgram)) {
    cheese_abort("Ошибка перехода к строке сырной программы");
  }
}

inline bool cheese_lua_stage_tick(uint32_t nowMs, const WProgram& row) {
#ifdef USE_LUA
  if (static_cast<uint32_t>(nowMs - cheeseRuntime.enteredMs) >=
      static_cast<uint32_t>(row.Time) * 1000UL) {
    cheese_abort("Lua не завершила операцию до тайм-аута");
    return true;
  }
  if (cheeseLuaStage.phase == CHEESE_LUA_STAGE_EXIT_REQUESTED ||
      cheeseLuaStage.phase == CHEESE_LUA_STAGE_EXIT_QUEUED) {
    const uint8_t nextProgram = cheeseLuaStage.nextProgram;
    if (!cheese_finish_lua_exit()) return true;
    runtime_pair_end(UI_WAIT_LUA_KNOWN, RUNTIME_PAIR_RESUMED,
                     "Lua-задача завершена", NOTIFY_MSG);
    if (nextProgram == PROGRAM_END) cheese_finish();
    else if (!cheese_prepare_stage(nextProgram)) cheese_abort("Ошибка перехода после Lua");
    return true;
  }
  const LuaBeerJobResult result = beer_lua_job_result(cheeseLuaStage.ticket);
  if (result == LUA_BEER_JOB_LOCK_BUSY || result == LUA_BEER_JOB_QUEUED ||
      result == LUA_BEER_JOB_RUNNING) return true;
  cheese_abort(result == LUA_BEER_JOB_SUCCEEDED
      ? "Lua завершилась без перехода к следующей строке"
      : "Lua завершилась с ошибкой");
#else
  (void)nowMs;
  (void)row;
  cheese_abort("Lua недоступна в этой сборке");
#endif
  return true;
}

void cheese_stage_tick() {
  static uint32_t lastCheeseTickMs = 0;
  const uint32_t nowMs = millis();
  if (nowMs - lastCheeseTickMs < 1000UL) return;
  lastCheeseTickMs = nowMs;
  if (cheeseFinishPending) { cheese_finish(); return; }
  if (!PowerOn || ProgramNum >= ProgramLen || ProgramNum >= PROGRAM_END) return;
  const WProgram& row = program[ProgramNum];
  const CheeseStageKind kind = cheese_stage_kind(row.WType);
  if (kind == CHEESE_STAGE_INVALID) {
    cheese_abort("Ошибка программы: неизвестная операция");
    return;
  }
  if (kind == CHEESE_STAGE_LUA) { cheese_lua_stage_tick(nowMs, row); return; }
  const bool sensorRequired = kind == CHEESE_STAGE_HEAT ||
      kind == CHEESE_STAGE_HOLD || kind == CHEESE_STAGE_COOL ||
      kind == CHEESE_STAGE_PH;
  const DSSensor* sensor = nullptr;
  const char* sensorName = "";
  if (sensorRequired && (!beer_control_sensor(row.TempSensor, sensor, sensorName) ||
      (!sensor_valid(*sensor) && process_sensor_failed("Сыр", sensorName)))) {
    cheese_abort("Ошибка датчика температуры");
    return;
  }
  if (!cheese_mixer_tick(row, nowMs)) {
    cheese_abort("Ошибка мешалки");
    return;
  }
  if (cheese_time_elapsed(nowMs, cheeseRuntime.enteredMs,
      cheese_stage_timeout_minutes(row)) &&
      kind != CHEESE_STAGE_HOLD && kind != CHEESE_STAGE_MIX) {
    cheese_abort("Тайм-аут операции сырной программы");
    return;
  }
  switch (kind) {
    case CHEESE_STAGE_HEAT: {
      if (!isfinite(cheeseRuntime.heatStartSetpoint)) {
        cheeseRuntime.heatStartSetpoint = sensor->avgTemp;
      }
      const float target = min(row.Temp, cheeseRuntime.heatStartSetpoint +
          row.Param * static_cast<float>(nowMs - cheeseRuntime.enteredMs) / 60000.0f);
      set_heater_state(target, sensor->avgTemp);
      if (cheese_temperature_confirmed(nowMs,
          cheese_in_temperature_band(sensor->avgTemp, row.Temp))) {
        runtime_pair_end(UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM,
                         RUNTIME_PAIR_RESUMED, "Температура подтверждена", NOTIFY_MSG);
        run_cheese_program(ProgramNum + 1);
      }
      return;
    }
    case CHEESE_STAGE_HOLD: {
      set_heater_state(row.Temp, sensor->avgTemp);
      const uint32_t elapsed = nowMs - cheeseRuntime.lastTickMs;
      cheeseRuntime.lastTickMs = nowMs;
      if (cheese_in_temperature_band(sensor->avgTemp, row.Temp)) {
        cheeseRuntime.holdAccumulatedMs += elapsed;
        runtime_pair_end(UI_WAIT_CHEESE_HOLD_CLOCK_FREEZE, RUNTIME_PAIR_RESUMED,
                         "Выдержка продолжена", NOTIFY_MSG);
      } else {
        runtime_pair_begin(UI_WAIT_CHEESE_HOLD_CLOCK_FREEZE,
                           "Выдержка приостановлена: температура вне полосы", WARNING_MSG);
      }
      if (static_cast<float>(cheeseRuntime.holdAccumulatedMs) >= row.Time * 60000.0f) {
        run_cheese_program(ProgramNum + 1);
      } else if (cheese_time_elapsed(nowMs, cheeseRuntime.enteredMs,
          cheese_stage_timeout_minutes(row))) {
        cheese_abort("Тайм-аут выдержки");
      }
      return;
    }
    case CHEESE_STAGE_COOL: {
      setHeaterPosition(false);
      const bool coolNeeded = sensor->avgTemp > row.Temp;
      const bool highFlow = sensor->avgTemp > row.Temp + 1.0f;
      if (!cheese_set_cooling_outputs(coolNeeded, highFlow)) {
        cheese_abort("Ошибка охлаждения");
        return;
      }
      if (cheese_temperature_confirmed(nowMs,
          cheese_in_temperature_band(sensor->avgTemp, row.Temp))) {
        if (!cheese_set_cooling_outputs(false, false)) cheese_abort("Не удалось выключить охлаждение");
        else {
          runtime_pair_end(UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM,
                           RUNTIME_PAIR_RESUMED, "Температура подтверждена", NOTIFY_MSG);
          run_cheese_program(ProgramNum + 1);
        }
      }
      return;
    }
    case CHEESE_STAGE_MIX:
      if (cheeseRuntime.mixerOneShotComplete ||
          cheese_time_elapsed(nowMs, cheeseRuntime.enteredMs, row.Time)) run_cheese_program(ProgramNum + 1);
      return;
    case CHEESE_STAGE_DOSE:
      if (row.TempSensor == 2 && cheese_local_doser_complete()) {
        stepper_safe_stop();
        cheeseRuntime.doserCompleted = true;
        runtime_pair_end(UI_WAIT_CHEESE_DOSE, RUNTIME_PAIR_RESUMED,
                         "Дозирование завершено", NOTIFY_MSG);
        run_cheese_program(ProgramNum + 1);
      }
      return;
    case CHEESE_STAGE_PH:
      set_heater_state(row.Temp, sensor->avgTemp);
      cheese_ph_tick();
      if (!cheese_ph_valid()) {
        cheese_ph_target_confirmed(nowMs, false);
        if (cheese_ph_invalid_too_long(nowMs, false)) {
          cheese_abort("pH недостоверен 10 секунд");
        }
        return;
      }
      cheese_ph_invalid_too_long(nowMs, true);
      if (cheese_ph_target_confirmed(nowMs, cheesePhValue <= row.Param)) {
        runtime_pair_end(UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM,
                         RUNTIME_PAIR_RESUMED, "pH подтверждён", NOTIFY_MSG);
        run_cheese_program(ProgramNum + 1);
      }
      return;
    case CHEESE_STAGE_WAIT:
      return;
    case CHEESE_STAGE_DRAIN:
      return;
    case CHEESE_STAGE_INVALID:
    case CHEESE_STAGE_LUA:
      return;
  }
}

void cheese_finish() {
  cheeseFinishPending = true;
  if (!cheese_apply_safe_outputs(true)) {
    SendMsg("Ошибка завершения сыроварения: выходы не выключены", ALARM_MSG);
    return;
  }
  if (!cheese_finish_lua_exit()) return;
  runtime_pair_close_mode(SAMOVAR_CHEESE_MODE,
                          cheesePairErrorPending ? RUNTIME_PAIR_ERROR : RUNTIME_PAIR_PROCESS_END,
                          cheesePairErrorPending ? "Сыроварение остановлено из-за ошибки"
                                                : "Сыроварение завершено",
                          cheesePairErrorPending ? ALARM_MSG : NOTIFY_MSG);
  cheese_reset_stage_state();
  begintime = 0;
  ProgramNum = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  set_heater_state_flag(false);
  stop_process("Программа сыроварения завершена");
}

void cheese_proc() {
  if (SamovarStatusInt != SAMOVAR_STATUS_CHEESE ||
      startval != SAMOVAR_STARTVAL_CHEESE_START || PowerOn) return;
  if (!cheese_ph_prepare()) {
    mode_cancel_process_start("ADS1115 не найден. Старт сыроварения отменён.");
    return;
  }
  String programError;
  if (!cheese_validate_program(programError)) {
    mode_cancel_process_start(programError);
    return;
  }
  if (power_transition_active() || heater_safety_latched()) {
    mode_cancel_process_start("Нагрев недоступен. Старт сыроварения отменён.");
    return;
  }
  if (!create_data()) {
    mode_cancel_process_start("Ошибка создания файла лога. Старт сыроварения отменён.");
    return;
  }
  String sessionDescription;
  if (!copy_start_session_description(sessionDescription, pdMS_TO_TICKS(50))) {
    mode_cancel_process_start("Описание сессии занято. Старт сыроварения отменён.");
    mode_warn_log_close_failed();
    return;
  }
#ifndef USE_ADS1115
  pinMode(LUA_PIN, INPUT);
#endif
  cheese_reset_stage_state();
  cheese_set_drain(false);
  session_begin(sessionDescription);
  set_power(true);
  if (!PowerOn) {
    mode_cancel_process_start("Не удалось включить питание нагрева. Старт сыроварения отменён.");
    mode_warn_log_close_failed();
    return;
  }
  run_cheese_program(0);
}

inline void cheese_check_cooling_limits() {
  beer_check_cooling_limits();
  beer_check_wort_overheat_limit();
}

inline bool cheese_cooling_pump_demanded() { return beer_cooling_pump_demanded(); }

String get_cheese_program() { return serialize_program_for_mode(SAMOVAR_CHEESE_MODE); }

String get_cheese_status_text() {
  if (!PowerOn || ProgramNum >= ProgramLen) return "Ожидание";
  String status = cheese_stage_name(program[ProgramNum].WType);
  status += "; строка ";
  status += String(ProgramNum + 1);
  if (program[ProgramNum].WType == 'N' && cheese_ph_valid()) {
    status += "; pH ";
    status += String(cheesePhValue, 2);
  }
  return status;
}
