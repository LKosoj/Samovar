#!/usr/bin/env python3
"""Проверяет подтверждаемую подачу и lifecycle составной команды НБК."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SETSPEED_HARNESS = r'''
#include <cstdint>
#include <iostream>

using ProgramType = char;
enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
struct PumpProbe { uint16_t currentSpeed; };
static PumpProbe i2cStepperPump = {40};
static bool i2cAvailable = true;
static bool driverSucceeds = true;
static bool lastRequireI2c = false;
static int driverCalls = 0;
static uint32_t fakeMillis = 0;
static uint32_t time_speed = 0;
static float nbk_P = 4.0f;
struct StatsProbe {
  float totalVolume;
  float activeVolume;
  uint32_t activeFeedMs;
};
static StatsProbe stats = {};

uint32_t millis() { return fakeMillis; }
ProgramType current_program_type() { return 'W'; }
bool i2c_stepper_refresh(PumpProbe&) { return i2cAvailable; }
float i2c_get_liquid_rate_by_step(uint16_t speed) {
  return float(speed) / 10.0f;
}
float i2c_stepper_steps_from_rate(float rate) { return rate * 10.0f; }
bool set_stepper_target(uint16_t speed, uint8_t, uint32_t, bool requireI2c) {
  driverCalls++;
  lastRequireI2c = requireI2c;
  if (!requireI2c || !driverSucceeds) return false;
  i2cStepperPump.currentSpeed = speed;
  return true;
}

ActuatorCommandResult SetSpeed(float Speed) {
@BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  i2cStepperPump.currentSpeed = 40;
  i2cAvailable = true;
  driverSucceeds = true;
  lastRequireI2c = false;
  driverCalls = 0;
  fakeMillis = 200;
  time_speed = 100;
  nbk_P = 4.0f;
  stats = {3.0f, 3.0f, 50};
}

int main() {
  reset_fixture();
  i2cAvailable = false;
  check(SetSpeed(7.0f) == ACTUATOR_COMMAND_FAILED,
        "отсутствующий I2C-насос обязан дать FAILED");
  check(driverCalls == 0, "при отсутствии I2C локальный привод вызываться не должен");
  check(time_speed == 100 && nbk_P == 4.0f,
        "отказ обнаружения не должен коммитить время или подачу");
  check(stats.totalVolume == 3.0f && stats.activeVolume == 3.0f &&
            stats.activeFeedMs == 50,
        "отказ обнаружения не должен менять статистику");

  reset_fixture();
  driverSucceeds = false;
  check(SetSpeed(7.0f) == ACTUATOR_COMMAND_FAILED,
        "отказ I2C-команды обязан дать FAILED");
  check(driverCalls == 1 && lastRequireI2c,
        "NBK обязан запросить именно I2C-only команду");
  check(time_speed == 100 && nbk_P == 4.0f,
        "отказ драйвера не должен коммитить время или подачу");

  reset_fixture();
  fakeMillis = 300;
  check(SetSpeed(7.0f) == ACTUATOR_COMMAND_APPLIED,
        "подтверждённая I2C-команда обязана дать APPLIED");
  check(lastRequireI2c, "успешная команда НБК не должна разрешать local fallback");
  check(time_speed == 300 && nbk_P == 7.0f,
        "APPLIED обязан коммитить время и новую подачу");
  check(stats.totalVolume > 3.0f && stats.activeVolume > 3.0f &&
            stats.activeFeedMs == 250,
        "APPLIED обязан учесть предыдущий подтверждённый интервал");
  return failures == 0 ? 0 : 1;
}
'''

FSM_HARNESS = r'''
#include <cstdint>
#include <iostream>

#define SAMOVAR_USE_POWER

enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
enum NbkActuatorDeadlineTarget : uint8_t {
  NBK_ACTUATOR_NO_DEADLINE = 0,
  NBK_ACTUATOR_OPTIMIZATION_DEADLINE,
  NBK_ACTUATOR_WORK_DEADLINE,
};
struct String { String(const char*) {} };
struct NbkActuatorCommandState {
@STATE_BODY@
};

static NbkActuatorCommandState nbkActuatorCommand = {};
static constexpr uint32_t NBK_ACTUATOR_TIMEOUT_MS = 15000;
static uint32_t fakeMillis = 1000;
static bool PowerOn = true;
static bool startPending = false;
static ActuatorCommandResult powerStartResult = ACTUATOR_COMMAND_PENDING;
static ActuatorCommandResult powerPollResult = ACTUATOR_COMMAND_PENDING;
static ActuatorCommandResult pumpResult = ACTUATOR_COMMAND_APPLIED;
static int safeWaitCalls = 0;
static float nbk_M = 11;
static float nbk_P = 12;
static float nbk_Mo = 13;
static float nbk_Po = 14;
static float nbk_Po_ceiling = 15;
static uint16_t nbk_opt_iter = 16;
static uint32_t nbk_opt_next_time = 17;
static uint32_t nbk_work_next_time = 18;
static uint8_t ProgramNum = 2;
static uint8_t nbk_high_temp_ticks = 4;
// [T1-2026-09-03] счётчик тиков высокого давления - коммит обязан сбрасывать
// его так же, как nbk_high_temp_ticks (тот же блок 1.5).
static uint8_t nbk_high_pressure_ticks = 5;
static uint8_t nbk_work_pause_stage = 9; // сентинел: нетронут вне commitKeepsOptimum
static bool nbk_pause_overflow_repeat_latched = true;
static bool nbk_work_in_pause = true;
static bool nbk_overflow_happened = true;
static bool nbk_safe_waiting = false;
static bool nbk_safe_wait_feed_stopped = false;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;

uint32_t millis() { return fakeMillis; }
uint32_t safety_deadline_after(uint32_t now, uint32_t delay) {
  return now + delay;
}
bool safety_deadline_expired(uint32_t now, uint32_t deadline) {
  return int32_t(now - deadline) >= 0;
}
bool power_transition_start_pending() { return startPending; }
ActuatorCommandResult nbk_set_power(float, uint64_t* generation) {
  *generation = 41;
  return powerStartResult;
}
ActuatorCommandResult current_power_command_status(uint64_t generation) {
  if (generation != 41) return ACTUATOR_COMMAND_FAILED;
  return powerPollResult;
}
ActuatorCommandResult SetSpeed(float speed) {
  if (pumpResult == ACTUATOR_COMMAND_APPLIED) nbk_P = speed;
  return pumpResult;
}
void nbk_enter_safe_wait(const String&) {
  safeWaitCalls++;
  nbkActuatorCommand = {};
  nbk_safe_waiting = true;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
}

inline void nbk_reset_actuator_command() {
@RESET_BODY@
}
inline bool nbk_schedule_actuator_command(
    float candidateM,
    float candidateP,
    NbkActuatorDeadlineTarget deadlineTarget,
    uint32_t nextDelayMs,
    uint16_t iteration,
    bool commitProgram = false,
    uint8_t candidateProgramNum = 0,
    bool commitKeepsOptimum = false) {
@SCHEDULE_BODY@
}
inline void tick_nbk_actuator_command() {
@TICK_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static void reset_fixture() {
  nbkActuatorCommand = {};
  fakeMillis = 1000;
  PowerOn = true;
  startPending = false;
  powerStartResult = ACTUATOR_COMMAND_PENDING;
  powerPollResult = ACTUATOR_COMMAND_PENDING;
  pumpResult = ACTUATOR_COMMAND_APPLIED;
  safeWaitCalls = 0;
  nbk_M = 11; nbk_P = 12; nbk_Mo = 13; nbk_Po = 14;
  nbk_Po_ceiling = 15; nbk_opt_iter = 16;
  nbk_opt_next_time = 17; nbk_work_next_time = 18;
  ProgramNum = 2;
  nbk_high_temp_ticks = 4;
  nbk_high_pressure_ticks = 5;
  nbk_pause_overflow_repeat_latched = true;
  nbk_work_in_pause = true;
  nbk_work_pause_stage = 9;
  nbk_overflow_happened = true;
  nbk_safe_waiting = false;
  nbk_safe_wait_feed_stopped = false;
}

int main() {
  reset_fixture();
  check(nbk_schedule_actuator_command(
            900, 6, NBK_ACTUATOR_WORK_DEADLINE, 5000, 23, true, 3),
        "валидная команда должна быть принята");
  check(nbkActuatorCommand.result == ACTUATOR_COMMAND_ACCEPTED,
        "schedule должен публиковать ACCEPTED");
  check(nbk_M == 11 && nbk_P == 12 && ProgramNum == 2,
        "ACCEPTED не должен коммитить процесс");

  startPending = true;
  tick_nbk_actuator_command();
  check(nbkActuatorCommand.result == ACTUATOR_COMMAND_ACCEPTED,
        "ожидание старта нагрева должно сохранять ACCEPTED");
  startPending = false;
  tick_nbk_actuator_command();
  check(nbkActuatorCommand.result == ACTUATOR_COMMAND_PENDING &&
            nbkActuatorCommand.generation == 41,
        "регулятор должен опубликовать PENDING с поколением");
  check(nbk_M == 11 && nbk_P == 12 && nbk_work_next_time == 18 &&
            ProgramNum == 2,
        "PENDING не должен коммитить M/P/deadline/program");

  tick_nbk_actuator_command();
  check(nbk_M == 11 && nbk_P == 12 && nbk_work_next_time == 18,
        "повторный PENDING не должен коммитить процесс");
  powerPollResult = ACTUATOR_COMMAND_APPLIED;
  tick_nbk_actuator_command();
  check(!nbkActuatorCommand.active && nbk_M == 900 && nbk_P == 6,
        "только APPLIED обоих приводов должен коммитить M/P");
  check(nbk_work_next_time == 6000 && nbk_opt_iter == 16,
        "APPLIED должен коммитить выбранный deadline, не чужую iteration");
  check(ProgramNum == 3 && nbk_Mo == 900 && nbk_Po == 6 &&
            nbk_Po_ceiling == 6,
        "подтверждённый W должен коммитить строку и optimum");
  check(!nbk_work_in_pause,
        "коммит без commitKeepsOptimum обязан снять паузу (nbk_work_in_pause=false)");

  // [Ремонт-2026-09-02 П1] commitKeepsOptimum=true: коммит переводит Работу в
  // паузу автовхода и НЕ переписывает nbk_Mo/nbk_Po кандидатами (в отличие от
  // сценария выше, где commitKeepsOptimum не передан).
  reset_fixture();
  check(nbk_schedule_actuator_command(
            555, 3, NBK_ACTUATOR_WORK_DEADLINE, 4000, 21, true, 5, true),
        "keepsOptimum-команда должна быть принята");
  powerStartResult = ACTUATOR_COMMAND_APPLIED;
  tick_nbk_actuator_command();
  check(!nbkActuatorCommand.active && nbk_M == 555 && nbk_P == 3,
        "keepsOptimum обязан всё равно подтвердить М/П приводов");
  check(ProgramNum == 5 && nbk_Mo == 13 && nbk_Po == 14,
        "commitKeepsOptimum НЕ должен переписывать nbk_Mo/nbk_Po кандидатами");
  check(nbk_work_in_pause && nbk_work_pause_stage == 1,
        "commitKeepsOptimum обязан перевести Работу в паузу stage=1");
  check(!nbk_overflow_happened && !nbk_pause_overflow_repeat_latched,
        "commitKeepsOptimum обязан снять флаги захлёба/повторного захлёба");
  check(nbk_Po_ceiling == nbk_Po && nbk_high_temp_ticks == 0,
        "commitKeepsOptimum обязан синхронизировать потолок По и сбросить счётчик");
  check(nbk_high_pressure_ticks == 0,
        "commit обязан сбросить счётчик тиков высокого давления так же, как temp");

  reset_fixture();
  check(nbk_schedule_actuator_command(
            700, 5, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, 3000, 17),
        "optimization command должна быть принята");
  powerStartResult = ACTUATOR_COMMAND_FAILED;
  tick_nbk_actuator_command();
  check(safeWaitCalls == 1 && nbk_M == 11 && nbk_P == 12 &&
            nbk_opt_iter == 16 && nbk_opt_next_time == 17,
        "FAILED регулятора должен уйти в safe-wait без коммита");

  reset_fixture();
  check(nbk_schedule_actuator_command(
            700, 5, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, 3000, 17),
        "pump-failure command должна быть принята");
  powerStartResult = ACTUATOR_COMMAND_APPLIED;
  pumpResult = ACTUATOR_COMMAND_FAILED;
  tick_nbk_actuator_command();
  check(safeWaitCalls == 1 && nbk_M == 11 && nbk_P == 12 &&
            nbk_opt_iter == 16 && nbk_opt_next_time == 17,
        "частичный отказ насоса должен уйти в safe-wait без коммита");
  return failures == 0 ? 0 : 1;
}
'''

SAFE_WAIT_HARNESS = r'''
#include <cstdint>
#include <iostream>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1 };
enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
struct String { String(const char*) {} };
static bool PowerOn = true;
static bool transitionActive = false;
static bool setPowerTurnsOff = true;
static ActuatorCommandResult feedResult = ACTUATOR_COMMAND_APPLIED;
static float nbk_M = 800;
static float nbk_P = 6;
static bool nbk_safe_waiting = false;
static bool nbk_safe_wait_feed_stopped = false;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
static int resetCalls = 0;
static int powerOffCalls = 0;

void nbk_reset_actuator_command() { resetCalls++; }
ActuatorCommandResult SetSpeed(float speed) {
  if (feedResult == ACTUATOR_COMMAND_APPLIED) nbk_P = speed;
  return feedResult;
}
void set_power(bool on, bool) {
  powerOffCalls++;
  if (!on && setPowerTurnsOff) PowerOn = false;
}
bool power_transition_active() { return transitionActive; }
void SendMsg(const String&, MESSAGE_TYPE) {}

inline void nbk_enter_safe_wait(const String& reason) {
@ENTER_BODY@
}
inline void tick_nbk_safe_wait() {
@SAFE_TICK_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static void reset_fixture() {
  PowerOn = true;
  transitionActive = false;
  setPowerTurnsOff = true;
  feedResult = ACTUATOR_COMMAND_APPLIED;
  nbk_M = 800;
  nbk_P = 6;
  nbk_safe_waiting = false;
  nbk_safe_wait_feed_stopped = false;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  resetCalls = 0;
  powerOffCalls = 0;
}
int main() {
  reset_fixture();
  transitionActive = true;
  nbk_enter_safe_wait(String("safe"));
  check(nbk_safe_waiting && nbk_safe_wait_result == ACTUATOR_COMMAND_PENDING,
        "подтверждённый насос и незавершённый power-off должны дать PENDING");
  check(nbk_P == 0 && nbk_M == 800,
        "safe-wait не должен коммитить M=0 до завершения power-off");
  tick_nbk_safe_wait();
  check(nbk_safe_wait_result == ACTUATOR_COMMAND_PENDING && nbk_M == 800,
        "PENDING power-off должен сохранять прежнюю подтверждённую M");
  transitionActive = false;
  tick_nbk_safe_wait();
  check(nbk_safe_wait_result == ACTUATOR_COMMAND_APPLIED && nbk_M == 0,
        "safe-wait APPLIED допустим только после feed=0 и завершённого power-off");

  reset_fixture();
  transitionActive = true;
  feedResult = ACTUATOR_COMMAND_FAILED;
  nbk_enter_safe_wait(String("safe"));
  check(nbk_safe_wait_result == ACTUATOR_COMMAND_FAILED && nbk_P == 6,
        "неподтверждённый stop насоса должен дать terminal FAILED");
  transitionActive = false;
  tick_nbk_safe_wait();
  check(nbk_safe_wait_result == ACTUATOR_COMMAND_FAILED && nbk_M == 0,
        "после отказа насоса нагрев всё равно должен завершить выключение");

  reset_fixture();
  setPowerTurnsOff = false;
  nbk_enter_safe_wait(String("safe"));
  check(nbk_safe_wait_result == ACTUATOR_COMMAND_FAILED && nbk_M == 800,
        "неподтверждённое выключение нагрева не должно публиковать APPLIED");
  check(resetCalls == 1 && powerOffCalls == 1,
        "safe-wait обязан отменить pending-команду и запросить power-off");
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(source: str, prefix: str, emit: bool = True) -> int:
    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
        temp = Path(temp_dir)
        cpp = temp / "test.cpp"
        binary = temp / "test"
        cpp.write_text(source, encoding="utf-8")
        build = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if build.returncode:
            if emit:
                sys.stderr.write(build.stderr)
            return build.returncode
        execution = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(execution.stdout)
            sys.stderr.write(execution.stderr)
        return execution.returncode


def set_speed_source(body: str) -> str:
    return SETSPEED_HARNESS.replace("@BODY@", body.replace("\r\n", "\n"))


def main() -> int:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    try:
        set_speed = extract_function_body(
            source, "ActuatorCommandResult SetSpeed(float Speed) {"
        )
        state_body, _ = extract_braced_block_after(
            source, "struct NbkActuatorCommandState {"
        )
        reset = extract_function_body(source, "inline void nbk_reset_actuator_command() {")
        schedule = extract_function_body(
            source, "inline bool nbk_schedule_actuator_command("
        )
        tick = extract_function_body(source, "inline void tick_nbk_actuator_command() {")
        enter_safe = extract_function_body(source, "inline void nbk_enter_safe_wait(")
        tick_safe = extract_function_body(source, "inline void tick_nbk_safe_wait() {")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(
        set_speed_source(set_speed), "samovar-nbk-setspeed-"
    ) != 0:
        return 1

    mutations = (
        set_speed.replace(
            "if (!i2c_stepper_refresh(i2cStepperPump)) return ACTUATOR_COMMAND_FAILED;",
            "if (false && !i2c_stepper_refresh(i2cStepperPump)) return ACTUATOR_COMMAND_FAILED;",
            1,
        ),
        set_speed.replace(", true)", ", false)"),
        set_speed.replace(
            "if (!applied) return ACTUATOR_COMMAND_FAILED;",
            "if (!applied) return ACTUATOR_COMMAND_APPLIED;",
            1,
        ),
    )
    if any(mutation == set_speed for mutation in mutations):
        print("FAIL: SetSpeed mutation anchor missing", file=sys.stderr)
        return 1
    for mutation in mutations:
        if compile_and_run(
            set_speed_source(mutation), "samovar-nbk-setspeed-mutation-", False
        ) == 0:
            print("FAIL: SetSpeed confirmation mutation survived", file=sys.stderr)
            return 1

    fsm = FSM_HARNESS
    fsm = fsm.replace("@STATE_BODY@", state_body.replace("\r\n", "\n"))
    fsm = fsm.replace("@RESET_BODY@", reset.replace("\r\n", "\n"))
    fsm = fsm.replace("@SCHEDULE_BODY@", schedule.replace("\r\n", "\n"))
    fsm = fsm.replace("@TICK_BODY@", tick.replace("\r\n", "\n"))
    if compile_and_run(fsm, "samovar-nbk-actuator-fsm-") != 0:
        return 1

    # [Ремонт-2026-09-02 П1] Мутация: снять "!" - меняет местами ветки
    # commitKeepsOptimum. Ломает ОБА новых assert'а: обычный коммит (Mo/Po
    # ожидались перезаписанными) больше их не перезапишет, а keepsOptimum-коммит
    # (Mo/Po ожидались нетронутыми) теперь их перезапишет.
    commit_keeps_optimum_mutation = tick.replace(
        "if (!nbkActuatorCommand.commitKeepsOptimum) {",
        "if (nbkActuatorCommand.commitKeepsOptimum) {",
        1,
    )
    if commit_keeps_optimum_mutation == tick:
        print("FAIL: commitKeepsOptimum Mo/Po mutation anchor missing", file=sys.stderr)
        return 1
    mutated_fsm = FSM_HARNESS
    mutated_fsm = mutated_fsm.replace("@STATE_BODY@", state_body.replace("\r\n", "\n"))
    mutated_fsm = mutated_fsm.replace("@RESET_BODY@", reset.replace("\r\n", "\n"))
    mutated_fsm = mutated_fsm.replace("@SCHEDULE_BODY@", schedule.replace("\r\n", "\n"))
    mutated_fsm = mutated_fsm.replace(
        "@TICK_BODY@", commit_keeps_optimum_mutation.replace("\r\n", "\n")
    )
    if compile_and_run(mutated_fsm, "samovar-nbk-actuator-fsm-mutation-", False) == 0:
        print("FAIL: commitKeepsOptimum Mo/Po mutation survived", file=sys.stderr)
        return 1

    # Отдельная мутация: коммит с keepsOptimum перестаёт ставить паузу/stage=1
    # (только nbk_work_in_pause/stage, Mo/Po-ветка не мутирована).
    pause_stage_mutation = tick.replace(
        "nbk_work_in_pause = nbkActuatorCommand.commitKeepsOptimum;\n"
        "    if (nbkActuatorCommand.commitKeepsOptimum) nbk_work_pause_stage = 1;",
        "nbk_work_in_pause = false;",
        1,
    )
    if pause_stage_mutation == tick:
        print("FAIL: commitKeepsOptimum pause/stage mutation anchor missing", file=sys.stderr)
        return 1
    mutated_pause_fsm = FSM_HARNESS
    mutated_pause_fsm = mutated_pause_fsm.replace("@STATE_BODY@", state_body.replace("\r\n", "\n"))
    mutated_pause_fsm = mutated_pause_fsm.replace("@RESET_BODY@", reset.replace("\r\n", "\n"))
    mutated_pause_fsm = mutated_pause_fsm.replace("@SCHEDULE_BODY@", schedule.replace("\r\n", "\n"))
    mutated_pause_fsm = mutated_pause_fsm.replace(
        "@TICK_BODY@", pause_stage_mutation.replace("\r\n", "\n")
    )
    if compile_and_run(mutated_pause_fsm, "samovar-nbk-actuator-fsm-pause-mutation-", False) == 0:
        print("FAIL: commitKeepsOptimum pause/stage mutation survived", file=sys.stderr)
        return 1

    safe_wait = SAFE_WAIT_HARNESS
    safe_wait = safe_wait.replace(
        "@ENTER_BODY@", enter_safe.replace("\r\n", "\n")
    )
    safe_wait = safe_wait.replace(
        "@SAFE_TICK_BODY@", tick_safe.replace("\r\n", "\n")
    )
    if compile_and_run(safe_wait, "samovar-nbk-safe-wait-") != 0:
        return 1
    safe_mutation = source.replace(
        "nbk_safe_wait_feed_stopped && !PowerOn",
        "!PowerOn",
        1,
    )
    if safe_mutation == source:
        print("FAIL: safe-wait mutation anchor missing", file=sys.stderr)
        return 1
    mutated_enter = extract_function_body(
        safe_mutation, "inline void nbk_enter_safe_wait("
    )
    mutated_tick = extract_function_body(
        safe_mutation, "inline void tick_nbk_safe_wait() {"
    )
    mutated_safe_wait = SAFE_WAIT_HARNESS
    mutated_safe_wait = mutated_safe_wait.replace(
        "@ENTER_BODY@", mutated_enter.replace("\r\n", "\n")
    )
    mutated_safe_wait = mutated_safe_wait.replace(
        "@SAFE_TICK_BODY@", mutated_tick.replace("\r\n", "\n")
    )
    if compile_and_run(
        mutated_safe_wait, "samovar-nbk-safe-wait-mutation-", False
    ) == 0:
        print("FAIL: safe-wait feed confirmation mutation survived", file=sys.stderr)
        return 1
    print("nbk actuator confirmation and lifecycle checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
