#pragma once

#include <Arduino.h>

#include "Samovar.h"
#include "beer.h"
#include "program_io.h"
#include "runtime_helpers.h"

#ifndef CHEESE_PH_SAMPLE_INTERVAL_MS
#define CHEESE_PH_SAMPLE_INTERVAL_MS 1000UL
#endif

#ifndef CHEESE_PH_STALE_MS
#define CHEESE_PH_STALE_MS 5000UL
#endif

enum CheeseStageKind : uint8_t {
  CHEESE_STAGE_INVALID = 0,
  CHEESE_STAGE_HEAT_TO_TARGET,
  CHEESE_STAGE_TIMED_HOLD,
  CHEESE_STAGE_COOL,
  CHEESE_STAGE_MANUAL_WAIT,
  CHEESE_STAGE_AUTOTUNE,
  CHEESE_STAGE_LUA,
  CHEESE_STAGE_PH,
  CHEESE_STAGE_DRAIN,
};

enum CheesePhStageResult : uint8_t {
  CHEESE_PH_WAIT = 0,
  CHEESE_PH_REACHED,
  CHEESE_PH_INVALID,
  CHEESE_PH_TIMEOUT,
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

static CheeseLuaStageState cheeseLuaStage = {
    CHEESE_LUA_STAGE_IDLE, 0, PROGRAM_END};
static bool cheeseFinishPending = false;
static bool cheeseDrainOpen = false;
static bool cheeseDoserStarted = false;
static bool cheeseDoserCompleted = false;
static int cheesePhRaw = 0;
static float cheesePhValue = 0.0f;
static bool cheesePhValid = false;
static bool cheesePhSampled = false;
static unsigned long cheesePhSampleMs = 0;

inline CheeseStageKind cheese_stage_kind(ProgramType type) {
  switch (type) {
    case 'M': return CHEESE_STAGE_HEAT_TO_TARGET;
    case 'P':
    case 'Z':
    case 'f':
    case 'z':
    case 'd':
    case 's':
    case 'p':
    case 'v':
    case 'r': return CHEESE_STAGE_TIMED_HOLD;
    case 'C': return CHEESE_STAGE_COOL;
    case 'W': return CHEESE_STAGE_MANUAL_WAIT;
    case 'A': return CHEESE_STAGE_AUTOTUNE;
    case 'L': return CHEESE_STAGE_LUA;
    case 'n': return CHEESE_STAGE_PH;
    case 'S': return CHEESE_STAGE_DRAIN;
    case 'R': return CHEESE_STAGE_MANUAL_WAIT;
    default: return CHEESE_STAGE_INVALID;
  }
}

inline bool cheese_doser_stage(ProgramType type) {
  return type == 'Z' || type == 'f' || type == 'z' || type == 'd';
}

inline CheesePhStageResult cheese_ph_stage_result(
    bool valid, bool fresh, float value, float target, bool timedOut) {
  if (!valid || !fresh) return CHEESE_PH_INVALID;
  if (value <= target) return CHEESE_PH_REACHED;
  if (timedOut) return CHEESE_PH_TIMEOUT;
  return CHEESE_PH_WAIT;
}

#ifdef USE_LUA
inline bool cheese_lua_result_pending(LuaBeerJobResult result) {
  return result == LUA_BEER_JOB_LOCK_BUSY ||
         result == LUA_BEER_JOB_QUEUED ||
         result == LUA_BEER_JOB_RUNNING;
}
#endif

inline bool cheese_doser_motion_complete(
    bool started, bool moving, int32_t current, int32_t target) {
  return started && !moving && target > 0 && current >= target;
}

inline bool cheese_time_elapsed(
    unsigned long nowMs, unsigned long startedMs, float minutes) {
  return startedMs > 0 &&
         static_cast<float>(nowMs - startedMs) >= minutes * 60000.0f;
}

inline bool cheese_temperature_reached(
    const WProgram& row, const DSSensor& sensor) {
  return sensor.avgTemp >= row.Temp - sensor.SetTemp;
}

inline float cheese_calibrated_ph(int raw, float slope, float offset) {
  return slope * raw + offset;
}

inline int cheese_ph_raw() {
  return cheesePhRaw;
}

inline float cheese_ph_value() {
  return cheesePhValue;
}

inline bool cheese_ph_valid() {
  return cheesePhValid && millis() - cheesePhSampleMs <= CHEESE_PH_STALE_MS;
}

inline bool cheese_ph_raw_valid() {
  return cheesePhSampled && millis() - cheesePhSampleMs <= CHEESE_PH_STALE_MS;
}

inline void cheese_set_drain(bool open) {
  digitalWrite(RELE_CHANNEL4, open ? SamSetup.rele4 : !SamSetup.rele4);
  cheeseDrainOpen = open;
}

inline void cheese_sample_ph(unsigned long nowMs) {
  if (cheesePhSampleMs != 0 &&
      nowMs - cheesePhSampleMs < CHEESE_PH_SAMPLE_INTERVAL_MS) return;

  const int raw = analogRead(LUA_PIN);
  cheesePhRaw = raw;
  const float measured = cheese_calibrated_ph(
      raw, SamSetup.CheesePhSlope, SamSetup.CheesePhOffset);
  cheesePhSampleMs = nowMs;
  cheesePhSampled = true;
  if (!isfinite(measured) || measured < 0.0f || measured > 14.0f) {
    cheesePhValid = false;
    return;
  }

  if (!cheesePhValid) {
    cheesePhValue = measured;
  } else {
    const float oldWeight = constrain(
        static_cast<float>(SamSetup.CheesePhSmoothPercent), 0.0f, 99.0f) /
        100.0f;
    cheesePhValue = cheesePhValue * oldWeight + measured * (1.0f - oldWeight);
  }
  cheesePhValid = true;
}

inline void cheese_ph_tick() {
  if (Samovar_Mode == SAMOVAR_CHEESE_MODE) cheese_sample_ph(millis());
}

inline void cheese_start_doser() {
  stopService();
  stepper_safe_stop_reset();
#ifdef STEPPER_REVERSE
  stepper_safe_reverse(true);
#else
  stepper_safe_reverse(false);
#endif
  TargetStepps = SamSetup.CheeseDoserSteps;
  stepper_safe_set_motion(SamSetup.CheeseDoserSpeed, 0, TargetStepps);
  StepperMoving = true;
  stepper.enable();
  startService();
  cheeseDoserStarted = true;
}

inline void cheese_stop_doser() {
  stopService();
  stepper_safe_stop_reset();
  StepperMoving = false;
  TargetStepps = 0;
  cheeseDoserStarted = false;
  cheeseDoserCompleted = false;
}

inline bool cheese_tick_doser_stage(unsigned long nowMs) {
  if (!cheeseDoserStarted) {
    cheese_start_doser();
    return false;
  }
  if (!cheese_doser_motion_complete(
          cheeseDoserStarted,
          StepperMoving,
          stepper_safe_get_current(),
          TargetStepps)) return false;
  stopService();
  stepper_safe_stop();
  cheeseDoserStarted = false;
  cheeseDoserCompleted = true;
  begintime = nowMs;
  return true;
}

inline bool cheese_apply_safe_outputs(bool closeDrain) {
  bool applied = true;
  setHeaterPosition(false);
  if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) applied = false;
  if (set_mixer_state(false, false) != ACTUATOR_COMMAND_APPLIED) applied = false;
  cheese_stop_doser();
  if (closeDrain) cheese_set_drain(false);
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
  cheeseFinishPending = false;
  cheeseDrainOpen = false;
  cheeseDoserStarted = false;
  cheeseDoserCompleted = false;
  cheesePhRaw = 0;
  cheesePhValue = 0.0f;
  cheesePhValid = false;
  cheesePhSampled = false;
  cheesePhSampleMs = 0;
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
    const ActuatorCommandResult result =
        request_beer_lua_stop(cheeseLuaStage.ticket);
    if (result == ACTUATOR_COMMAND_PENDING) return false;
    if (result != ACTUATOR_COMMAND_APPLIED) {
      SendMsg("Ошибка Lua: не удалось запросить остановку job", ALARM_MSG);
      return false;
    }
    cheeseLuaStage.phase = CHEESE_LUA_STAGE_EXIT_QUEUED;
  }
  if (!beer_lua_job_idle(cheeseLuaStage.ticket)) return false;
  cheese_reset_lua_stage();
  return true;
#else
  SendMsg("Ошибка Lua: job активен без USE_LUA", ALARM_MSG);
  return false;
#endif
}

inline const char* cheese_stage_name(ProgramType type) {
  switch (type) {
    case 'M': return "Нагрев";
    case 'P': return "Температурная пауза";
    case 'C': return "Охлаждение";
    case 'W': return "Ожидание";
    case 'A': return "Автонастройка PID";
    case 'L': return "Lua";
    case 'Z': return "Внесение защитной культуры";
    case 'f': return "Внесение фермента";
    case 'z': return "Внесение закваски";
    case 'd': return "Внесение дополнительного ингредиента";
    case 's': return "Стуфатура";
    case 'p': return "Пастеризация";
    case 'v': return "Вымешивание";
    case 'r': return "Резка калье";
    case 'n': return "Набор кислотности";
    case 'S': return "Слив рассола";
    case 'R': return "Переворот сыра";
    default: return "Неизвестный этап";
  }
}

void cheese_finish();
void run_cheese_program(uint8_t num);

inline void cheese_abort(const String& reason) {
  SendMsg(reason, ALARM_MSG);
  cheese_finish();
}

inline bool cheese_validate_program(String& error) {
  if (ProgramLen == 0 || ProgramLen > PROGRAM_END) {
    error = "Ошибка программы Сыроварение: строка не задана";
    return false;
  }
  for (uint8_t i = 0; i < ProgramLen; i++) {
    const WProgram& row = program[i];
    if (program_type_empty(row.WType) ||
        !program_type_one_of(row.WType, cheese_program_parse_spec().allowedTypes)) {
      error = "Ошибка программы: неверный тип этапа в строке " + String(i + 1);
      return false;
    }
    const char* semanticError = nullptr;
    if (!program_validate_cheese_row_semantics(
            row.WType, row.Temp, row.Time, row.capacity_num,
            static_cast<long>(row.Speed), row.Volume,
            static_cast<long>(row.Power), row.TempSensor, row.Param,
            semanticError)) {
      error = String(semanticError ? semanticError : "Ошибка программы") +
              " в строке " + String(i + 1);
      return false;
    }
    const DSSensor* rowSensor = nullptr;
    const char* rowSensorName = "";
    if (!beer_control_sensor(row.TempSensor, rowSensor, rowSensorName)) {
      error = "Ошибка программы: неверный датчик температуры в строке " +
              String(i + 1);
      return false;
    }
    if (cheese_doser_stage(row.WType) &&
        (SamSetup.CheeseDoserSpeed == 0 || SamSetup.CheeseDoserSteps == 0)) {
      error = "Ошибка дозатора: скорость и число шагов должны быть больше нуля";
      return false;
    }
  }
  return true;
}

inline bool cheese_prepare_stage(uint8_t targetProgram) {
  if (!cheese_apply_safe_outputs(true)) return false;
  alarm_c_min = 0;
  alarm_c_low_min = 0;
  currentstepcnt = 0;
  beerMixerPauseSinceMs = 0;
  ProgramNum = targetProgram;
  begintime = 0;
  msgfl = true;
  cheeseDoserStarted = false;
  cheeseDoserCompleted = false;

  const ProgramType type = program[ProgramNum].WType;
  if (type == 'A') StartAutoTune();
  if (type == 'L') {
#ifdef USE_LUA
    uint32_t ticket = 0;
    if (!request_beer_lua_job(ticket)) return false;
    cheeseLuaStage.phase = CHEESE_LUA_STAGE_ENTER_QUEUED;
    cheeseLuaStage.ticket = ticket;
    cheeseLuaStage.nextProgram = PROGRAM_END;
#else
    return false;
#endif
  }
  startval = SAMOVAR_STARTVAL_CHEESE_START + 1;

  String message = "Переход к строке программы №" + String(ProgramNum + 1) +
      "; " + cheese_stage_name(type);
  if (SamSetup.ChangeProgramBuzzer) set_buzzer(true);
  SendMsg(message, SamSetup.ChangeProgramBuzzer ? ALARM_MSG : NOTIFY_MSG);
  return true;
}

void run_cheese_program(uint8_t num) {
  if (Samovar_Mode != SAMOVAR_CHEESE_MODE || !PowerOn) return;
  const uint8_t targetProgram =
      ProgramLen == 0 || num >= ProgramLen || num >= PROGRAM_END
          ? PROGRAM_END : num;

  if (cheeseLuaStage.phase != CHEESE_LUA_STAGE_IDLE) {
    if (!cheese_request_lua_exit(targetProgram)) {
      cheese_abort("Ошибка Lua: не удалось безопасно выключить исполнитель");
    }
    return;
  }
  if (targetProgram == PROGRAM_END) {
    cheese_finish();
    return;
  }
  if (!cheese_prepare_stage(targetProgram)) {
    cheese_abort(program[targetProgram].WType == 'L'
        ? "Ошибка Lua: job не принят к запуску"
        : "Ошибка перехода на этап сыроварения");
  }
}

inline bool cheese_lua_stage_tick() {
#ifdef USE_LUA
  if (cheeseLuaStage.phase == CHEESE_LUA_STAGE_EXIT_REQUESTED ||
      cheeseLuaStage.phase == CHEESE_LUA_STAGE_EXIT_QUEUED) {
    const uint8_t nextProgram = cheeseLuaStage.nextProgram;
    if (!cheese_finish_lua_exit()) return true;
    if (nextProgram == PROGRAM_END) cheese_finish();
    else if (!cheese_prepare_stage(nextProgram)) {
      cheese_abort("Ошибка перехода после остановки Lua");
    }
    return true;
  }

  const LuaBeerJobResult result = beer_lua_job_result(cheeseLuaStage.ticket);
  if (cheese_lua_result_pending(result)) {
    if (!cheese_apply_safe_outputs(true)) {
      cheese_abort("Ошибка Lua: не удалось выключить исполнитель");
    }
    return true;
  }
  if (result == LUA_BEER_JOB_SUCCEEDED) {
    cheeseLuaStage.phase = CHEESE_LUA_STAGE_RUNNING;
    return true;
  }
  cheese_abort(result == LUA_BEER_JOB_FAILED_INIT
      ? "Ошибка Lua: job не подтвердил запуск"
      : "Ошибка Lua: job завершился с ошибкой");
#else
  cheese_abort("Ошибка программы: тип L требует USE_LUA");
#endif
  return true;
}

void cheese_stage_tick() {
  static unsigned long lastCheeseTickMs = 0;
  const unsigned long nowMs = millis();
  if (nowMs - lastCheeseTickMs < 1000) return;
  lastCheeseTickMs = nowMs;

  if (cheeseFinishPending) {
    cheese_finish();
    return;
  }
  if (!PowerOn || ProgramNum >= ProgramLen || ProgramNum >= PROGRAM_END) return;

  const WProgram& row = program[ProgramNum];
  const CheeseStageKind kind = cheese_stage_kind(row.WType);
  if (kind == CHEESE_STAGE_INVALID) {
    cheese_abort("Ошибка программы: неизвестный тип этапа в строке " +
        String(ProgramNum + 1));
    return;
  }
  if (kind == CHEESE_STAGE_LUA) {
    cheese_lua_stage_tick();
    return;
  }

  const bool sensorRequired = kind == CHEESE_STAGE_HEAT_TO_TARGET ||
      kind == CHEESE_STAGE_TIMED_HOLD || kind == CHEESE_STAGE_COOL ||
      kind == CHEESE_STAGE_AUTOTUNE || kind == CHEESE_STAGE_PH;
  const DSSensor* sensor = nullptr;
  const char* sensorName = "";
  if (sensorRequired &&
      (!beer_control_sensor(row.TempSensor, sensor, sensorName) ||
       (!sensor_valid(*sensor) && process_sensor_failed("Сыроварение", sensorName)))) {
    cheese_abort("Ошибка датчика температуры на этапе сыроварения");
    return;
  }

  switch (kind) {
    case CHEESE_STAGE_HEAT_TO_TARGET:
      set_heater_state(row.Temp, sensor->avgTemp);
      check_mixer_state();
      if (cheese_temperature_reached(row, *sensor)) {
        run_cheese_program(ProgramNum + 1);
      }
      return;

    case CHEESE_STAGE_TIMED_HOLD:
      set_heater_state(row.Temp, sensor->avgTemp);
      check_mixer_state();
      if (!cheese_temperature_reached(row, *sensor)) return;
      if (cheese_doser_stage(row.WType) && !cheeseDoserCompleted) {
        if (SamSetup.CheeseDoserSpeed == 0 || SamSetup.CheeseDoserSteps == 0) {
          cheese_abort("Ошибка дозатора: скорость и число шагов должны быть больше нуля");
          return;
        }
        cheese_tick_doser_stage(nowMs);
        return;
      }
      if (begintime == 0) begintime = nowMs;
      if (cheese_time_elapsed(nowMs, begintime, row.Time)) {
        run_cheese_program(ProgramNum + 1);
      }
      return;

    case CHEESE_STAGE_COOL:
      setHeaterPosition(false);
      if (beer_set_cooling_outputs(true) != ACTUATOR_COMMAND_APPLIED) return;
      check_mixer_state();
      if (begintime == 0) begintime = nowMs;
      if (sensor->avgTemp <= row.Temp) {
        if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;
        run_cheese_program(ProgramNum + 1);
      } else if (cheese_time_elapsed(
                     nowMs, begintime, BEER_COOL_TIMEOUT_MS / 60000.0f)) {
        cheese_abort("Ошибка охлаждения: температура не достигнута за допустимое время");
      }
      return;

    case CHEESE_STAGE_MANUAL_WAIT:
      if (!cheese_apply_safe_outputs(true)) {
        cheese_abort("Ошибка ожидания: не удалось безопасно выключить исполнитель");
      }
      return;

    case CHEESE_STAGE_AUTOTUNE:
      if (tuning) set_heater_state(row.Temp, sensor->avgTemp);
      else run_cheese_program(ProgramNum + 1);
      return;

    case CHEESE_STAGE_PH: {
      set_heater_state(row.Temp, sensor->avgTemp);
      check_mixer_state();
      cheese_ph_tick();
      const bool fresh = cheesePhValid &&
          nowMs - cheesePhSampleMs <= CHEESE_PH_STALE_MS;
      if (!cheesePhValid || !fresh) {
        cheese_abort("Ошибка pH: измерение недостоверно или устарело");
        return;
      }
      if (!cheese_temperature_reached(row, *sensor)) return;
      if (begintime == 0) begintime = nowMs;
      const CheesePhStageResult result = cheese_ph_stage_result(
          cheesePhValid,
          fresh,
          cheesePhValue,
          row.Param,
          cheese_time_elapsed(nowMs, begintime, row.Time));
      if (result == CHEESE_PH_REACHED) {
        run_cheese_program(ProgramNum + 1);
      } else if (result == CHEESE_PH_INVALID) {
        cheese_abort("Ошибка pH: измерение недостоверно или устарело");
      } else if (result == CHEESE_PH_TIMEOUT) {
        cheese_abort("Ошибка pH: целевое значение не достигнуто за допустимое время");
      }
      return;
    }

    case CHEESE_STAGE_DRAIN:
      if (!cheeseDrainOpen) {
        if (!cheese_apply_safe_outputs(false)) {
          cheese_abort("Ошибка слива: не удалось безопасно выключить исполнитель");
          return;
        }
        cheese_set_drain(true);
        begintime = nowMs;
      }
      if (cheese_time_elapsed(nowMs, begintime, row.Time)) {
        cheese_set_drain(false);
        run_cheese_program(ProgramNum + 1);
      }
      return;

    case CHEESE_STAGE_LUA:
    case CHEESE_STAGE_INVALID:
      return;
  }
}

void cheese_finish() {
  cheeseFinishPending = true;
  if (!cheese_apply_safe_outputs(true)) {
    SendMsg("Ошибка завершения сыроварения: не удалось выключить исполнитель", ALARM_MSG);
    return;
  }
  if (!cheese_finish_lua_exit()) return;
  cheese_reset_stage_state();
  begintime = 0;
  ProgramNum = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  set_heater_state_flag(false);
  stop_process("Программа сыроварения завершена");
}

void cheese_proc() {
  if (SamovarStatusInt != SAMOVAR_STATUS_CHEESE) return;
  if (cheeseFinishPending) {
    cheese_finish();
    return;
  }
  if (startval != SAMOVAR_STARTVAL_CHEESE_START || PowerOn) return;
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
  cheesePhRaw = 0;
  cheesePhValue = 0.0f;
  cheesePhValid = false;
  cheesePhSampled = false;
  cheesePhSampleMs = 0;
  pinMode(LUA_PIN, INPUT);
  cheese_set_drain(false);
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

inline bool cheese_cooling_pump_demanded() {
  return beer_cooling_pump_demanded();
}

String get_cheese_program() {
  return serialize_program_for_mode(SAMOVAR_CHEESE_MODE);
}

String get_cheese_status_text() {
  if (!PowerOn || ProgramNum >= ProgramLen) return "Ожидание";
  String status = cheese_stage_name(program[ProgramNum].WType);
  status += "; строка ";
  status += String(ProgramNum + 1);
  if (program[ProgramNum].WType == 'n' && cheesePhValid) {
    status += "; pH ";
    status += String(cheesePhValue, 2);
  }
  return status;
}
