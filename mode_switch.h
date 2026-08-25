#pragma once

// PendingCommandLockGuard живёт в runtime_helpers.h - включаем явно, а не
// полагаемся на порядок склейки .ino (запинено smoke_pending_command_lock_guard.py).
#include "runtime_helpers.h"

// [T27b / SOLUTIONS_2026-08-24.md, А1] Автомат смены режима работы прибора.
//
// Раньше жил в WebServer.ino, хотя не является веб-логикой: обработчик HTTP
// (задача async_tcp, ядро 1, приоритет 5) выполняется в произвольный момент и
// может вытеснить loop() (ядро 1, но другая задача) на середине. Исполнительные
// механизмы (клапаны, насос, нагрев, степперы - местные и I2C) обязаны
// управляться только из loop()/SysTicker, а не из веб-задачи. Проверено при
// переносе: switch_samovar_mode() вызывается ровно из одного места -
// process_profile_operation() (Samovar.ino), т.е. уже из loop(). Из веб-задачи
// (WebServer.ino::queue_profile_operation) вызывается только постановка
// операции в очередь - самих приводов там больше нет.
//
// Барьер mode_switch_barrier_active ("не трогай железо, пока меняется режим")
// приватен для этого файла: наружу выставлены только mode_switch_begin(),
// mode_switch_end(), mode_switch_in_progress(). Прямая запись флага и
// clear_mode_switch_barrier_locked() (внутренний _locked-хелпер - вызывать
// только уже держа emergencyStopMux) не выходят за пределы mode_switch.h.
// Барьер снимается на КАЖДОМ пути switch_samovar_mode()/
// force_complete_mode_switch_failed(), включая аварийный (см. их тела ниже) -
// единственная точка входа снаружи после провала или успеха одна и та же:
// mode_switch_end().
//
// Почему mode_switch_barrier_active всё ещё extern (объявление осталось в
// samovar_api.h), а не static здесь: power_regulator.h, pumppwm.h,
// valve_buzzer.h читают этот флаг напрямую как общий предохранитель приводов
// (безопасность работает независимо от автомата смены режима) и подключаются
// (через logic.h/pumppwm.h) в Samovar.ino заведомо раньше точки, где в принципе
// мог бы стоять #include "mode_switch.h" (см. ниже, почему он не может стоять
// раньше). static здесь оборвал бы им видимость идентификатора. Эти три файла
// вне списка файлов, разрешённых к правке в этой задаче - честная граница:
// приватность здесь достигнута на уровне API автомата смены режима
// (WebServer.ino/Samovar.ino обязаны переходить на три публичные функции), а
// не на уровне линковки символа.
//
// Почему #include "mode_switch.h" стоит в WebServer.ino именно после
// discard_pending_mode_control_commands() (а не, например, в начале файла):
// тела функций ниже вызывают pending_mode_control_commands_locked() и
// discard_pending_mode_control_commands() - static-функции WebServer.ino
// (учёт "не барьер, а pending_*-флаги", отдельная задача А2/T39), которые
// определены чуть ВЫШЕ точки включения. Переставить включение раньше их
// определения - ошибка компиляции "was not declared in this scope". Всё
// остальное, что нужно телам ниже (I2CStepperDevice, mode_ops_by_mode,
// safety_mode_switch_*, discard_samovar_commands, i2c_stepper_*, ...), уже
// форвард-декларировано в samovar_api.h или определено раньше в Samovar.ino -
// и то, и другое видно с начала WebServer.ino.

static SafetyModeSwitchState modeSwitchState = {SAFETY_MODE_SWITCH_IDLE, 0, false, false, 0};

struct ModeActuatorCleanupState {
  bool initialized;
  bool mixerStopped;
  bool pumpStopped;
  uint32_t deadline;
};

static ModeActuatorCleanupState modeActuatorCleanup = {};

volatile bool mode_switch_barrier_active = false;

bool mode_switch_in_progress() {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool active = mode_switch_barrier_active;
  portEXIT_CRITICAL(&emergencyStopMux);
  return active;
}

// Единственная точка снятия барьера смены режима. Суффикс _locked (конвенция
// проекта): вызывать, уже держа портовую критическую секцию emergencyStopMux -
// сама функция секцию не открывает и не закрывает.
static inline void clear_mode_switch_barrier_locked() { mode_switch_barrier_active = false; }

// [T27b] Публичные обёртки барьера для вызывающих ВНЕ этого файла (WebServer.ino,
// Samovar.ino) - сами берут и отдают emergencyStopMux, снаружи лок держать не
// нужно (portMUX не рекурсивен - повторный вход тем же ядром до отдачи взорвёт
// сторож). switch_samovar_mode()/force_complete_mode_switch_failed() ставят и
// снимают флаг напрямую (см. ниже) - они уже держат ту же критическую секцию
// вместе с другими locked-операциями (safety_mode_switch_begin/_complete,
// force_heater_output_off_locked), и заворачивать их в mode_switch_begin/end
// означало бы либо вложенный вход в тот же спинлок, либо разрыв одной локальной
// секции на две - в обоих случаях это меняло бы поведение, а не только место в
// файле.
void mode_switch_begin() {
  portENTER_CRITICAL(&emergencyStopMux);
  mode_switch_barrier_active = true;
  portEXIT_CRITICAL(&emergencyStopMux);
}

void mode_switch_end() {
  portENTER_CRITICAL(&emergencyStopMux);
  clear_mode_switch_barrier_locked();
  portEXIT_CRITICAL(&emergencyStopMux);
}

static bool mode_control_queues_idle() {
  if (!samovar_command_queue_idle(pdMS_TO_TICKS(50))) return false;
  PendingCommandLockGuard guard;
  if (!guard) return false;
  return !pending_mode_control_commands_locked();
}

static void stop_local_mode_actuators() {
  digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  mixer_status = false;
  valve_status = false;
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
#endif
  stopService();
  stepper_safe_stop_reset();
  StepperMoving = false;
  CurrrentStepperSpeed = 0;
  TargetStepps = 0;
  I2CStepperSpeed = 0;
  I2CPumpCmdSpeed = 0;
  I2CPumpTargetSteps = 0;
  I2CPumpTargetMl = 0;
  set_heater_state_flag(false);
}

static bool stop_i2c_mode_actuator(I2CStepperDevice& dev, bool finishCalibration) {
  if (!i2c_stepper_config_begin(dev)) return false;
  if (!i2c_stepper_refresh(dev, true)) {
    i2c_stepper_config_end(dev);
    return false;
  }
  bool stopped = true;
  if (finishCalibration || (dev.status & I2CSTEPPER_STATUS_CALIBRATION)) {
    stopped = i2c_stepper_send_command(dev, I2CSTEP_CMD_CALIBRATE_FINISH);
  }
  if (stopped) stopped = i2c_stepper_stop(dev);
  if (stopped && (dev.caps & I2CSTEPPER_CAP_RELAY) && dev.relayMask != 0) {
    dev.relayMask = 0;
    stopped = i2c_stepper_write_config(dev) &&
              i2c_stepper_send_command(dev, I2CSTEP_CMD_RELAY);
  }
  if (stopped) {
    stopped = i2c_stepper_refresh(dev, true) &&
              (dev.status & (I2CSTEPPER_STATUS_RUNNING | I2CSTEPPER_STATUS_CALIBRATION)) == 0 &&
              dev.currentSpeed == 0 &&
              (!(dev.caps & I2CSTEPPER_CAP_RELAY) || dev.relayMask == 0);
  }
  i2c_stepper_config_end(dev);
  return stopped;
}

static bool mode_actuators_idle() {
  bool idle = !valve_status && !mixer_status && !heater_state &&
              !stepper_safe_get_state() && stepper_safe_get_target() == 0 &&
              CurrrentStepperSpeed == 0 && I2CStepperSpeed == 0 &&
              I2CPumpCmdSpeed == 0 && I2CPumpTargetSteps == 0 &&
              I2CPumpTargetMl == 0 && !I2CPumpCalibrating;
#ifdef USE_WATER_PUMP
  idle = idle && !pump_started && water_pump_speed == 0;
#endif
  return idle && modeActuatorCleanup.mixerStopped &&
         modeActuatorCleanup.pumpStopped;
}

static bool tick_mode_actuator_cleanup(bool luaIdle) {
  stop_local_mode_actuators();
  if (!modeActuatorCleanup.initialized) {
    modeActuatorCleanup.initialized = true;
    modeActuatorCleanup.mixerStopped = !(i2cStepperMixer.present || i2c_stepper_cache.mixer_present);
    modeActuatorCleanup.pumpStopped = !(i2cStepperPump.present || i2c_stepper_cache.pump_present);
    modeActuatorCleanup.deadline = safety_deadline_after(millis(), 30000);
    set_capacity(0);
  }
  if (!modeActuatorCleanup.mixerStopped) {
    const bool stopped = stop_i2c_mode_actuator(i2cStepperMixer, false);
    modeActuatorCleanup.mixerStopped = luaIdle && stopped;
  }
  if (!modeActuatorCleanup.pumpStopped) {
    const bool stopped = stop_i2c_mode_actuator(
      i2cStepperPump,
      I2CPumpCalibrating
    );
    modeActuatorCleanup.pumpStopped = luaIdle && stopped;
    if (stopped) I2CPumpCalibrating = false;
  }
  if (!luaIdle) return false;
  return mode_actuators_idle();
}

void stop_active_process_for_mode() {
  if (self_test_active()) stop_self_test();
  const bool ownerActive = heater_power_on() || SamovarStatusInt != SAMOVAR_STATUS_IDLE ||
                           startval != SAMOVAR_STARTVAL_IDLE || ProgramNum != 0;
  if (!ownerActive) {
    SamovarStatusInt = SAMOVAR_STATUS_IDLE;
    startval = SAMOVAR_STARTVAL_IDLE;
    ProgramNum = 0;
    return;
  }

  // [WP17 п.40] Раньше здесь был switch(Samovar_Mode), заново перечислявший режимы
  // (имена функций завершения совпадали с .finish в mode_registry.h у DIST/BEER/BK/NBK
  // случайно - реестр их не читал). Теперь читаем .stopProcess из реестра; у RECT это
  // отдельная функция (run_program(PROGRAM_END) - не то же самое, что .finish==nullptr,
  // который используется для команды SAMOVAR_POWER), у SUVID/LUA — nullptr, и они, как и
  // прежде, идут по общей ветке ниже.
  const ModeOps* ops = mode_ops_by_mode(Samovar_Mode);
  if (ops != nullptr && ops->stopProcess != nullptr) {
    ops->stopProcess();
    return;
  }
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
  ProgramNum = 0;
  set_power(false);
}

// Провал смены режима больше не запирает автомат в терминальной фазе: нагрев
// принудительно снимается, SafetyModeSwitchState возвращается в IDLE, а барьер
// mode_switch_barrier_active снимается ровно как на успехе. Строка предупреждения
// передаётся вызывающей стороной литералом — без промежуточного буфера, чтобы
// длинное сообщение в UTF-8 не обрезалось молча (см. snprintf-ловушку).
static ModeSwitchResult force_complete_mode_switch_failed(const char* warning) {
  portENTER_CRITICAL(&emergencyStopMux);
  force_heater_output_off_locked(true);
  safety_mode_switch_complete(modeSwitchState);
  clear_mode_switch_barrier_locked();
  portEXIT_CRITICAL(&emergencyStopMux);
  notify_power_worker();
  modeActuatorCleanup = {};
  SendMsg(warning, WARNING_MSG);
  return MODE_SWITCH_FAILED;
}

// switch_samovar_mode вызывается только из process_profile_operation().
ModeSwitchResult switch_samovar_mode(SAMOVAR_MODE requestedMode) {
  portENTER_CRITICAL(&emergencyStopMux);
  const bool accepted = safety_mode_switch_begin(modeSwitchState, (uint8_t)requestedMode);
  if (accepted) mode_switch_barrier_active = true;
  portEXIT_CRITICAL(&emergencyStopMux);
  if (!accepted) return MODE_SWITCH_PENDING;
  tick_mode_actuator_cleanup(false);

  if (modeSwitchState.phase == SAFETY_MODE_SWITCH_STOP_REQUESTED) {
    stop_active_process_for_mode();

    bool stopRequested = true;
#ifdef USE_LUA
    stopRequested = request_lua_mode_stop();
#endif
    const bool queueWasIdle = samovar_command_queue_idle(pdMS_TO_TICKS(50));
    const bool queueDiscarded = discard_samovar_commands(pdMS_TO_TICKS(50));
    bool pendingCancelled = false;
    const bool pendingDiscarded = discard_pending_mode_control_commands(pendingCancelled);
    if (!stopRequested || !queueDiscarded || !pendingDiscarded) {
      if (safety_deadline_expired(millis(), modeActuatorCleanup.deadline)) {
        return force_complete_mode_switch_failed(
            !stopRequested
                ? "Смена режима завершена принудительно: не подтвердился Lua"
                : "Смена режима завершена принудительно: не подтвердился очередь");
      }
      return MODE_SWITCH_PENDING;
    }
    if (!queueWasIdle || pendingCancelled) {
      SendMsg("Отложенные управляющие команды отменены сменой режима", WARNING_MSG);
    }
    safety_mode_switch_wait_cleanup(modeSwitchState);
    return MODE_SWITCH_PENDING;
  }

  bool luaIdle = true;
#ifdef USE_LUA
  luaIdle = lua_mode_owner_idle();
#endif
  const bool actuatorsIdle = tick_mode_actuator_cleanup(luaIdle);
  const bool queuesIdle = mode_control_queues_idle();
  const bool logClosePending = data_log_close_pending();

  const bool heaterPowerOn = heater_power_on();
  const bool powerTransitionActive = power_transition_active();
  const bool nbkTransitionActive = nbk_transition_active();
  const bool modeHeatingActive = mode_heating_start_active();
  const bool selfTestActive = self_test_active();
  const bool ownerIdle = mode_runtime_owner_idle();

  const bool cleanupReady = safety_mode_switch_cleanup_ready(
        modeSwitchState,
        heaterPowerOn,
        powerTransitionActive,
        nbkTransitionActive,
        modeHeatingActive,
        selfTestActive,
        logClosePending,
        ownerIdle,
        actuatorsIdle,
        luaIdle,
        queuesIdle
      );

  if (safety_deadline_expired(millis(), modeActuatorCleanup.deadline) && !cleanupReady) {
    const char* warning = "Смена режима завершена принудительно: не подтвердилась готовность";
    if (!modeSwitchState.logCloseRequested || logClosePending) {
      warning = "Смена режима завершена принудительно: не подтвердился лог";
    } else if (!luaIdle) {
      warning = "Смена режима завершена принудительно: не подтвердился Lua";
    } else if (!queuesIdle) {
      warning = "Смена режима завершена принудительно: не подтвердился очередь";
    } else if (!actuatorsIdle) {
      warning = "Смена режима завершена принудительно: не подтвердился привод";
    } else if (heaterPowerOn) {
      warning = "Смена режима завершена принудительно: не подтвердился нагрев";
    } else if (powerTransitionActive) {
      warning = "Смена режима завершена принудительно: не подтвердился переход мощности";
    } else if (nbkTransitionActive) {
      warning = "Смена режима завершена принудительно: не подтвердился переход НБК";
    } else if (modeHeatingActive) {
      warning = "Смена режима завершена принудительно: не подтвердился старт нагрева";
    } else if (selfTestActive) {
      warning = "Смена режима завершена принудительно: не подтвердился самотест";
    } else if (!ownerIdle) {
      warning = "Смена режима завершена принудительно: не подтвердился владелец режима";
    }
    return force_complete_mode_switch_failed(warning);
  }

  if (!modeSwitchState.logCloseRequested) {
    if (request_data_log_close()) {
      safety_mode_switch_mark_log_close_requested(modeSwitchState);
    }
    return MODE_SWITCH_PENDING;
  }

  if (!cleanupReady) return MODE_SWITCH_PENDING;

  if (!modeSwitchState.commitDone) {
    // commitError фиксируется в terminalError, но НЕ обрывает функцию сразу:
    // до сих пор commit_profile_operation() при modeChange=true (единственный
    // путь сюда) применяет режим/скрипт-имя в RAM целиком независимо от
    // отказа NVS - возврат до перечитывания Lua-скрипта оставил бы новый режим
    // работать на скрипте СТАРОГО. Итоговый провал/причина решаются ниже, уже
    // после попытки перечитать Lua.
    const OperationError commitError = commit_profile_operation();
    if (commitError != OPERATION_ERROR_NONE) {
      active_profile_operation.terminalError = commitError;
    }
    modeSwitchState.commitDone = true;
  }
#ifdef USE_LUA
  if (!load_lua_script()) {
    if (++modeSwitchState.luaReloadAttempts >= 10) {
      if (active_profile_operation.terminalError == OPERATION_ERROR_NONE) {
        active_profile_operation.terminalError = OPERATION_ERROR_MODE_SWITCH_FAILED;
      }
      return force_complete_mode_switch_failed(
          "Смена режима завершена принудительно: скрипт Lua не перечитан");
    }
    return MODE_SWITCH_PENDING;
  }
#endif
  if (active_profile_operation.terminalError != OPERATION_ERROR_NONE) {
    return force_complete_mode_switch_failed(
        "Смена режима завершена принудительно: профиль не сохранён");
  }
  portENTER_CRITICAL(&emergencyStopMux);
  safety_mode_switch_complete(modeSwitchState);
  clear_mode_switch_barrier_locked();
  portEXIT_CRITICAL(&emergencyStopMux);
  modeActuatorCleanup = {};
  return MODE_SWITCH_SUCCEEDED;
}

void change_samovar_mode() {
  if (!is_valid_samovar_mode(Samovar_Mode)) {
    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  }
  Samovar_CR_Mode = Samovar_Mode;
  // [WP7 п.5] Раньше SamSetup.Mode подтягивался К Samovar_Mode при КАЖДОЙ отдаче страницы
  // (send_index_page/send_mode_specific_htm) - записью Samovar_Mode прямо из веб-задачи
  // (async_tcp, другое ядро, произвольный момент, в т.ч. при активном процессе). Но
  // mode_dispatch_alarm() (SysTicker) выбирает набор аварийных проверок по Samovar_Mode, а
  // mode_dispatch_loop() - по SamovarStatusInt; открытие "не той" страницы во время работы
  // молча переключало часть аварийного надзора на чужой режим. Направление синхронизации
  // развёрнуто: change_samovar_mode() уже вызывается ровно в момент старта режима
  // (mode_registry.h::mode_apply_power_on_command) и при загрузке (Samovar.ino) - здесь
  // Samovar_Mode достоверен, и SamSetup.Mode подтягивается К НЕМУ, а не наоборот. Веб-
  // обработчики страниц больше НЕ пишут Samovar_Mode вообще (см. send_index_page/
  // send_mode_specific_htm в WebServer.ino).
  SamSetup.Mode = (int)Samovar_Mode;
}
