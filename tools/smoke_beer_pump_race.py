#!/usr/bin/env python3
"""Поведенческая проверка [P2 п.1] в beer.h::set_mixer_state() и связанной с
ней находки в beer_finish().

Плановое выключение насоса по расписанию мешалки (OFF-ветка set_mixer_state,
вызываемая из check_mixer_state()) не должно глушить насос, если охлаждение
('C'/'F' в beer_stage_tick()) активно прямо сейчас — иначе гонка между двумя
источниками управления насосом обрывает охлаждение раньше времени.

[Находка] beer_finish() обязан сбрасывать beerCoolingPumpActive: иначе при
ручной остановке пива во время активного 'C'/'F' флаг остаётся true до
следующего старта, и если в этот промежуток set_mixer(false) дёрнут из
другого режима/Lua, set_pump_pwm(0) внутри set_mixer_state молча не
выполнится из-за устаревшего флага.

Тест вытаскивает РЕАЛЬНЫЕ тела set_mixer_state() и beer_finish() из beer.h
через extract_function_body — без переписывания логики.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
)

ROOT = Path(__file__).resolve().parents[1]

SET_MIXER_STATE_SIGNATURE = "ActuatorCommandResult set_mixer_state(bool state, bool dir)"
CHECK_MIXER_STATE_SIGNATURE = "void check_mixer_state()"
BEER_SAFE_LUA_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_safe_lua_outputs()"
COOLING_PUMP_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_pump(bool active)"
COOLING_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_outputs(bool active)"
BEER_PAUSE_F_OUTPUTS_SIGNATURE = "inline bool beer_pause_fermentation_outputs()"
BEER_FINISH_SIGNATURE = "void beer_finish()"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdlib>
#include <iostream>

#define BitIsSet(reg, bit) ((reg & (1 << bit)) != 0)
#define RELE_CHANNEL2 2
#define USE_WATER_PUMP

enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

struct WProgram {
  uint8_t capacity_num = 0;
  int Volume = 0;
  int Speed = 0;
  int Power = 0;
};

struct SetupEEPROM {
  bool rele2 = false;
};

constexpr uint8_t PROGRAM_MAX = 8;

static WProgram program[PROGRAM_MAX];
static SetupEEPROM SamSetup;
static uint8_t ProgramNum = 0;
static bool mixer_status = false;
static unsigned long alarm_c_min = 0;
static unsigned long alarm_c_low_min = 0;
static int currentstepcnt = 0;
static unsigned long fakeMillis = 1000;
unsigned long millis() { return fakeMillis; }
static bool beerCoolingPumpActive = false;
static bool pump_started = false;
static bool heaterSafetyLatched = false;
static int emergencyCalls = 0;
bool heater_safety_latched() { return heaterSafetyLatched; }
void request_emergency_stop(const char*) {
  emergencyCalls++;
  heaterSafetyLatched = true;
}

static int digitalWriteCalls = 0;
static bool lastRelayState = false;
void digitalWrite(int, bool state) {
  digitalWriteCalls++;
  lastRelayState = state;
}

static int pumpPwmCalls = 0;
static float lastPumpPwm = -1;
static ActuatorCommandResult pumpPwmResult = ACTUATOR_COMMAND_APPLIED;
static ActuatorCommandResult pumpPwmStopResult = ACTUATOR_COMMAND_APPLIED;
ActuatorCommandResult set_pump_pwm(float duty) {
  lastPumpPwm = duty;
  pumpPwmCalls++;
  return duty == 0 ? pumpPwmStopResult : pumpPwmResult;
}

static bool mixerStepperPresent = false;
static bool pumpStepperPresent = false;
static bool stepperCommandResult = true;
static bool stepperStopCommandResult = true;
static bool mixerPumpCommandResult = true;
static int stepperCalls = 0;
static int lastStepperSpeed = -1;
static bool lastStepperDirection = false;
static int mixerPumpCalls = 0;
static int lastMixerPumpTarget = -1;
bool i2c_stepper_mixer_present() { return mixerStepperPresent; }
bool i2c_stepper_pump_present() { return pumpStepperPresent; }
bool set_stepper_by_time(int speed, bool direction, int) {
  stepperCalls++;
  lastStepperSpeed = speed;
  lastStepperDirection = direction;
  return speed == 0 ? stepperStopCommandResult : stepperCommandResult;
}
bool set_mixer_pump_target(int target) {
  mixerPumpCalls++;
  lastMixerPumpTarget = target;
  return mixerPumpCommandResult;
}

// --- Зависимости beer_finish(), не относящиеся к гонке насоса/мешалки ---
static bool valve_status = false;
static int openValveCalls = 0;
ActuatorCommandResult open_valve(bool val, bool /*msg*/) {
  valve_status = val;
  openValveCalls++;
  return ACTUATOR_COMMAND_APPLIED;
}

static int resetBoilingDetectorCalls = 0;
void resetBoilingDetector() { resetBoilingDetectorCalls++; }

static bool heater_state = true;
static bool heaterOutput = true;
static int setHeaterPositionCalls = 0;
void setHeaterPosition(bool state) { heaterOutput = state; setHeaterPositionCalls++; }

static bool beerManualPause = false;
static unsigned long beerStageIdleAccumMs = 0;
static unsigned long beerStageIdleSinceMs = 0;
static uint8_t beerSkipConfirmProgramNum = 0xFF;
static unsigned long begintime = 0;

constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;
static int16_t startval = 5;

enum BeerLuaStagePhase { BEER_LUA_STAGE_IDLE = 0 };
struct BeerLuaStageState { BeerLuaStagePhase phase; unsigned long ticket; unsigned char nextProgram; };
static BeerLuaStageState beerLuaStage = {BEER_LUA_STAGE_IDLE, 0, 0};
bool request_beer_lua_stop(unsigned long) { return true; }
void beer_reset_lua_stage() { beerLuaStage.phase = BEER_LUA_STAGE_IDLE; }

static int stopProcessCalls = 0;
void stop_process(const char*) { stopProcessCalls++; }
constexpr int ALARM_MSG = 0;
static int sendMsgCalls = 0;
void SendMsg(const char*, int) { sendMsgCalls++; }

ActuatorCommandResult set_mixer_state(bool state, bool dir);

@CHECK_MIXER_STATE_BODY@

@SET_MIXER_STATE_BODY@

@COOLING_PUMP_BODY@

@COOLING_OUTPUTS_BODY@

@BEER_SAFE_LUA_OUTPUTS_BODY@

@BEER_FINISH_BODY@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  program[0].capacity_num = 0b10;  // насос (бит 1) назначен этой ёмкости
  ProgramNum = 0;
  mixer_status = true;
  alarm_c_min = 0;
  alarm_c_low_min = 0;
  currentstepcnt = 0;
  fakeMillis = 1000;
  digitalWriteCalls = 0;
  lastRelayState = false;
  pumpPwmCalls = 0;
  lastPumpPwm = -1;
  pumpPwmResult = ACTUATOR_COMMAND_APPLIED;
  pumpPwmStopResult = ACTUATOR_COMMAND_APPLIED;
  pump_started = false;
  heaterSafetyLatched = false;
  emergencyCalls = 0;
  mixerStepperPresent = false;
  pumpStepperPresent = false;
  stepperCommandResult = true;
  stepperStopCommandResult = true;
  mixerPumpCommandResult = true;
  stepperCalls = 0;
  lastStepperSpeed = -1;
  lastStepperDirection = false;
  mixerPumpCalls = 0;
  lastMixerPumpTarget = -1;
  valve_status = false;
  openValveCalls = 0;
  resetBoilingDetectorCalls = 0;
  heater_state = true;
  heaterOutput = true;
  setHeaterPositionCalls = 0;
  beerManualPause = false;
  beerStageIdleAccumMs = 0;
  beerStageIdleSinceMs = 0;
  beerSkipConfirmProgramNum = 0xFF;
  begintime = 0;
  startval = 5;
  stopProcessCalls = 0;
  sendMsgCalls = 0;
}

// Передача управления Lua в строке L всегда обезвреживает наследованные
// выходы P/B/C. Реальная функция извлечена из beer.h.
static void test_lua_entry_safes_outputs_for_all_heating_stages() {
  const char* stages[] = {"P", "B", "C"};
  for (const char* stage : stages) {
    reset_fixture();
    heaterOutput = true;
    valve_status = true;
    pump_started = true;
    beerCoolingPumpActive = true;
    mixer_status = true;

    check(beer_safe_lua_outputs() == ACTUATOR_COMMAND_APPLIED,
          "Lua entry safe-output command was not confirmed");

    check(!heaterOutput, "Lua entry left heater output enabled");
    check(!valve_status, "Lua entry left cooling valve open");
    check(!beerCoolingPumpActive,
          "Lua entry left cooling ownership active");
    check(lastPumpPwm == 0, "Lua entry did not write zero pump PWM");
    check(!mixer_status, "Lua entry left mixer enabled");
    (void)stage;
  }
}

// Активное охлаждение 'C'/'F' - плановое выключение мешалки/насоса НЕ должно
// глушить насос: set_pump_pwm(0) не должен вызываться вовсе.
static void test_active_cooling_blocks_planned_pump_off() {
  reset_fixture();
  beerCoolingPumpActive = true;

  set_mixer_state(false, false);

  check(mixer_status == false, "set_mixer_state должен был обновить mixer_status");
  check(pumpPwmCalls == 0,
        "РЕГРЕСС: плановое выключение заглушило насос активного охлаждения (set_pump_pwm вызван)");
}

// Охлаждение неактивно - плановое выключение мешалки штатно глушит насос.
static void test_no_cooling_allows_planned_pump_off() {
  reset_fixture();
  beerCoolingPumpActive = false;

  set_mixer_state(false, false);

  check(mixer_status == false, "set_mixer_state должен был обновить mixer_status");
  check(pumpPwmCalls == 1, "плановое выключение без активного охлаждения должно было выключить насос");
  check(lastPumpPwm == 0, "плановое выключение должно было установить скважность насоса в 0");
}

static void test_local_pump_start_is_applied_without_i2c_target() {
  reset_fixture();
  program[0].capacity_num = 0b10;
  mixer_status = false;

  check(set_mixer_state(true, false) == ACTUATOR_COMMAND_APPLIED,
        "локальный PWM-насос без I2C target не вернул APPLIED");
  check(mixer_status, "локальный PWM-насос не опубликовал mixer_status=true");
  check(pumpPwmCalls == 1 && lastPumpPwm == 1023,
        "локальный PWM-насос не получил команду запуска");
}

static void test_partial_mixer_start_failure_is_compensated() {
  reset_fixture();
  program[0].capacity_num = 0b11;
  program[0].Volume = 7;
  mixer_status = false;
  mixerStepperPresent = true;
  pumpStepperPresent = true;
  mixerPumpCommandResult = false;

  check(set_mixer_state(true, false) == ACTUATOR_COMMAND_FAILED,
        "частичный отказ запуска мешалки не вернул FAILED");
  check(!mixer_status, "FAILED запуска не должен публиковать mixer_status=true");
  check(lastPumpPwm == 0 && pumpPwmCalls == 2,
        "частичный отказ не компенсировал уже включённый PWM насоса");
  check(lastStepperSpeed == 0 && stepperCalls == 2,
        "частичный отказ не остановил уже запущенный шаговик мешалки");
  check(lastRelayState == !SamSetup.rele2,
        "частичный отказ не выключил реле мешалки");
}

static void test_mixer_stop_attempts_every_required_actuator() {
  reset_fixture();
  program[0].capacity_num = 0b11;
  mixer_status = true;
  mixerStepperPresent = true;
  pumpStepperPresent = true;
  stepperStopCommandResult = false;
  mixerPumpCommandResult = false;

  check(set_mixer_state(false, false) == ACTUATOR_COMMAND_FAILED,
        "частичный отказ остановки мешалки не вернул FAILED");
  check(mixer_status, "FAILED остановки не должен публиковать mixer_status=false");
  check(lastPumpPwm == 0, "остановка не попыталась выключить PWM насоса");
  check(stepperCalls == 1 && lastStepperSpeed == 0,
        "остановка не попыталась выключить шаговик");
  check(mixerPumpCalls == 1 && lastMixerPumpTarget == 0,
        "отказ шаговика помешал попытке выключить I2C-реле насоса");
}

static void test_failed_start_rollback_latches_and_stops_schedule_retry() {
  reset_fixture();
  program[0].capacity_num = 0b11;
  mixerStepperPresent = true;
  pumpPwmResult = ACTUATOR_COMMAND_FAILED;
  stepperStopCommandResult = false;

  check_mixer_state();
  check(emergencyCalls == 1 && heaterSafetyLatched,
        "неподтверждённый rollback старта мешалки не взвёл аварийную защёлку");
  check(currentstepcnt == 0 && alarm_c_low_min == 0 && alarm_c_min == 0,
        "неподтверждённый rollback закоммитил расписание мешалки");
  const int pumpCallsAfterFailure = pumpPwmCalls;
  check_mixer_state();
  check(pumpPwmCalls == pumpCallsAfterFailure,
        "после аварийной защёлки расписание повторило старт мешалки");
}

static void test_failed_pump_rollback_latches_and_stops_schedule_retry() {
  reset_fixture();
  program[0].capacity_num = 0b11;
  mixerStepperPresent = true;
  pumpStepperPresent = true;
  mixerPumpCommandResult = false;
  pumpPwmStopResult = ACTUATOR_COMMAND_FAILED;

  check_mixer_state();
  check(emergencyCalls == 1 && heaterSafetyLatched,
        "неподтверждённый rollback PWM насоса не взвёл аварийную защёлку");
  check(currentstepcnt == 0 && alarm_c_low_min == 0 && alarm_c_min == 0,
        "неподтверждённый rollback PWM закоммитил расписание мешалки");
  const int pumpCallsAfterFailure = pumpPwmCalls;
  check_mixer_state();
  check(pumpPwmCalls == pumpCallsAfterFailure,
        "после rollback PWM расписание повторило старт мешалки");
}

static void test_schedule_state_commits_only_after_applied_start() {
  reset_fixture();
  program[0].capacity_num = 0b01;
  program[0].Volume = 5;
  program[0].Speed = -10;
  mixer_status = false;
  mixerStepperPresent = true;
  stepperCommandResult = false;

  check_mixer_state();
  check(currentstepcnt == 0,
        "FAILED запуска сдвинул счётчик расписания мешалки");
  check(alarm_c_low_min == 0 && alarm_c_min == 0,
        "FAILED запуска сдвинул таймеры расписания мешалки");

  stepperCommandResult = true;
  check_mixer_state();
  check(currentstepcnt == 1,
        "APPLIED запуска не закоммитил счётчик расписания");
  check(!lastStepperDirection,
        "первая успешная попытка ошибочно получила реверс после FAILED");
}

// [Находка] beer_finish() во время активного 'C'/'F' обязан сбросить
// beerCoolingPumpActive, иначе он остаётся true до следующего старта пива.
static void test_beer_finish_resets_cooling_pump_flag() {
  reset_fixture();
  beerCoolingPumpActive = true;
  pump_started = true;
  valve_status = true;

  beer_finish();

  check(beerCoolingPumpActive == false,
        "РЕГРЕСС: beer_finish не сбросил beerCoolingPumpActive");
  check(lastPumpPwm == 0, "beer_finish должен был подтвердить выключение насоса");
}

// Поведенческий сценарий: после beer_finish() устаревший флаг больше не
// должен глушить последующий set_mixer_state(false, false), вызванный извне
// (другим режимом или Lua через set_mixer(false)).
static void test_beer_finish_then_external_mixer_off_mutes_pump() {
  reset_fixture();
  beerCoolingPumpActive = true;
  pump_started = true;
  valve_status = true;

  beer_finish();

  // Сбрасываем счётчики, чтобы проверить именно СЛЕДУЮЩИЙ, внешний вызов -
  // не побочный эффект самого beer_finish().
  pumpPwmCalls = 0;
  lastPumpPwm = -1;

  set_mixer_state(false, false);

  check(pumpPwmCalls == 1,
        "РЕГРЕСС: устаревший beerCoolingPumpActive после beer_finish заблокировал внешний set_mixer_state(false)");
  check(lastPumpPwm == 0, "внешний set_mixer_state(false) после beer_finish должен был обнулить скважность насоса");
}

int main() {
  test_lua_entry_safes_outputs_for_all_heating_stages();
  test_active_cooling_blocks_planned_pump_off();
  test_no_cooling_allows_planned_pump_off();
  test_local_pump_start_is_applied_without_i2c_target();
  test_partial_mixer_start_failure_is_compensated();
  test_mixer_stop_attempts_every_required_actuator();
  test_failed_start_rollback_latches_and_stops_schedule_retry();
  test_failed_pump_rollback_latches_and_stops_schedule_retry();
  test_schedule_state_commits_only_after_applied_start();
  test_beer_finish_resets_cooling_pump_flag();
  test_beer_finish_then_external_mixer_off_mutes_pump();
  if (failures != 0) return 1;
  std::cout << "beer.h set_mixer_state pump race behaviour checks passed\n";
  return 0;
}
'''


NO_LOCAL_HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

#define BitIsSet(reg, bit) ((reg & (1 << bit)) != 0)
#define RELE_CHANNEL2 2

enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

struct WProgram { uint8_t capacity_num = 0; int Volume = 0; };
struct SetupEEPROM { bool rele2 = false; };

static WProgram program[1];
static SetupEEPROM SamSetup;
static uint8_t ProgramNum = 0;
static bool mixer_status = false;
static int relayWrites = 0;
static bool relayState = false;
void digitalWrite(int, bool state) { relayWrites++; relayState = state; }
void request_emergency_stop(const char*) {}

static bool mixerStepperPresent = false;
static bool pumpStepperPresent = false;
static bool mixerPumpCommandResult = true;
static int mixerPumpCalls = 0;
bool i2c_stepper_mixer_present() { return mixerStepperPresent; }
bool i2c_stepper_pump_present() { return pumpStepperPresent; }
bool set_stepper_by_time(int, bool, int) { return true; }
bool set_mixer_pump_target(int) {
  mixerPumpCalls++;
  return (mixerStepperPresent || pumpStepperPresent) && mixerPumpCommandResult;
}

@SET_MIXER_STATE_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  program[0] = WProgram{};
  program[0].capacity_num = 0b10;
  mixer_status = false;
  relayWrites = 0;
  relayState = false;
  mixerStepperPresent = false;
  pumpStepperPresent = false;
  mixerPumpCommandResult = true;
  mixerPumpCalls = 0;
}

static void test_no_local_or_i2c_target_fails_without_status_change() {
  reset_fixture();
  check(set_mixer_state(true, false) == ACTUATOR_COMMAND_FAILED,
        "насос без локального PWM и I2C target не вернул FAILED");
  check(!mixer_status, "FAILED насос без target изменил mixer_status");
  check(relayWrites == 0, "FAILED насос без target тронул реле мешалки");
}

static void test_mixer_relay_is_rolled_back_without_stepper() {
  reset_fixture();
  program[0].capacity_num = 0b11;
  check(set_mixer_state(true, false) == ACTUATOR_COMMAND_FAILED,
        "мешалка с недоступным pump target не вернула FAILED");
  check(!mixer_status, "FAILED мешалка с недоступным pump target изменила mixer_status");
  check(relayWrites == 2 && relayState == !SamSetup.rele2,
        "FAILED мешалка оставила включённым реле без I2C-шаговика");
}

static void test_i2c_target_start_is_applied_without_local_pwm() {
  reset_fixture();
  pumpStepperPresent = true;
  check(set_mixer_state(true, false) == ACTUATOR_COMMAND_APPLIED,
        "доступный I2C target без локального PWM не вернул APPLIED");
  check(mixer_status, "доступный I2C target не опубликовал mixer_status=true");
  check(mixerPumpCalls == 1, "доступный I2C target не получил команду запуска");
}

int main() {
  test_no_local_or_i2c_target_fails_without_status_change();
  test_mixer_relay_is_rolled_back_without_stepper();
  test_i2c_target_start_is_applied_without_local_pwm();
  return failures == 0 ? 0 : 1;
}
'''


def build_harness(beer_source: str) -> str:
    check_mixer_body = extract_function_body(beer_source, CHECK_MIXER_STATE_SIGNATURE)
    check_mixer_fn = "void check_mixer_state() {" + check_mixer_body + "}"
    mixer_body = extract_function_body(beer_source, SET_MIXER_STATE_SIGNATURE)
    mixer_fn = "ActuatorCommandResult set_mixer_state(bool state, bool dir) {" + mixer_body + "}"
    cooling_pump_body = extract_function_body(beer_source, COOLING_PUMP_SIGNATURE)
    cooling_pump_fn = "inline ActuatorCommandResult beer_set_cooling_pump(bool active) {" + cooling_pump_body + "}"
    cooling_outputs_body = extract_function_body(beer_source, COOLING_OUTPUTS_SIGNATURE)
    cooling_outputs_fn = "inline ActuatorCommandResult beer_set_cooling_outputs(bool active) {" + cooling_outputs_body + "}"
    safe_outputs_body = extract_function_body(beer_source, BEER_SAFE_LUA_OUTPUTS_SIGNATURE)
    safe_outputs_fn = "inline ActuatorCommandResult beer_safe_lua_outputs() {" + safe_outputs_body + "}"
    finish_body = extract_function_body(beer_source, BEER_FINISH_SIGNATURE)
    finish_fn = "void beer_finish() {" + finish_body + "}"
    harness = HARNESS_TEMPLATE.replace("@CHECK_MIXER_STATE_BODY@", check_mixer_fn)
    harness = harness.replace("@SET_MIXER_STATE_BODY@", mixer_fn)
    harness = harness.replace("@COOLING_PUMP_BODY@", cooling_pump_fn)
    harness = harness.replace("@COOLING_OUTPUTS_BODY@", cooling_outputs_fn)
    harness = harness.replace("@BEER_SAFE_LUA_OUTPUTS_BODY@", safe_outputs_fn)
    harness = harness.replace("@BEER_FINISH_BODY@", finish_fn)
    return harness


def build_no_local_harness(beer_source: str) -> str:
    mixer_body = extract_function_body(beer_source, SET_MIXER_STATE_SIGNATURE)
    mixer_fn = "ActuatorCommandResult set_mixer_state(bool state, bool dir) {" + mixer_body + "}"
    return NO_LOCAL_HARNESS_TEMPLATE.replace("@SET_MIXER_STATE_BODY@", mixer_fn)


def compile_and_run(
    harness: str, label: str, show_output: bool = True
) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-pump-race-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_pump_race_test.cpp"
        binary = temp / "beer_pump_race_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            output = compile_result.stdout + compile_result.stderr
            if show_output:
                sys.stderr.write(f"[{label}] compile failed:\n{output}")
            return compile_result.returncode, output
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        output = run_result.stdout + run_result.stderr
        if show_output:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode, output


def main() -> int:
    beer_source = (ROOT / "beer.h").read_text(encoding="utf-8")
    errors: list[str] = []
    try:
        stage_body = extract_function_body(beer_source, "void beer_stage_tick()")
        f_branch, _ = extract_braced_block_after(
            stage_body, "if (currentType == 'F') {"
        )
        pause_branch, _ = extract_braced_block_after(
            f_branch, "if (beerManualPause) {"
        )
        require_ordered_tokens(
            "beer F pause",
            pause_branch,
            [
                "if (!beer_pause_fermentation_outputs()) {",
                'beer_abort_config_error("Ошибка паузы F: не удалось выключить исполнитель");',
                "return;",
            ],
            errors,
        )
        pause_outputs = extract_function_body(
            beer_source, BEER_PAUSE_F_OUTPUTS_SIGNATURE
        )
        require_ordered_tokens(
            "beer F pause outputs",
            pause_outputs,
            ["return beer_safe_lua_outputs() == ACTUATOR_COMMAND_APPLIED;"],
            errors,
        )
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1
        mutated_pause = pause_branch.replace(
            "if (!beer_pause_fermentation_outputs()) {",
            "if (false && !beer_pause_fermentation_outputs()) {",
            1,
        )
        mutation_errors: list[str] = []
        require_ordered_tokens(
            "beer F pause mutation",
            mutated_pause,
            ["if (!beer_pause_fermentation_outputs()) {"],
            mutation_errors,
        )
        if not mutation_errors:
            print("FAIL: F-pause result mutation survived smoke", file=sys.stderr)
            return 1
        harness = build_harness(beer_source)
        no_local_harness = build_no_local_harness(beer_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    returncode, _ = compile_and_run(harness, "beer.h")
    if returncode != 0:
        return 1

    returncode, _ = compile_and_run(no_local_harness, "beer.h no-local feature matrix")
    if returncode != 0:
        return 1

    no_target_mutant = no_local_harness.rsplit(
        "if (!set_mixer_pump_target(1)) {", 1
    )
    no_target_mutant = "if (false && !set_mixer_pump_target(1)) {".join(no_target_mutant)
    if no_target_mutant == no_local_harness:
        print("FAIL: could not build no-target mixer mutation", file=sys.stderr)
        return 1
    returncode, output = compile_and_run(
        no_target_mutant, "mixer no-target mutation", show_output=False
    )
    if returncode == 0 or "насос без локального PWM и I2C target" not in output:
        print("FAIL: mixer no-target mutation survived smoke", file=sys.stderr)
        sys.stderr.write(output)
        return 1

    relay_rollback_mutant = no_local_harness.rsplit(
        "if (mixerRelayEnabled) digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);", 1
    )
    relay_rollback_mutant = (
        "if (false && mixerRelayEnabled) digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);"
        .join(relay_rollback_mutant)
    )
    if relay_rollback_mutant == no_local_harness:
        print("FAIL: could not build mixer relay rollback mutation", file=sys.stderr)
        return 1
    returncode, output = compile_and_run(
        relay_rollback_mutant, "mixer relay rollback mutation", show_output=False
    )
    if returncode == 0 or "FAILED мешалка оставила включённым реле" not in output:
        print("FAIL: mixer relay rollback mutation survived smoke", file=sys.stderr)
        sys.stderr.write(output)
        return 1

    compensation_mutant = harness.replace(
        "if (mixerStepperStarted && !set_stepper_by_time(0, 0, 0)) rollbackFailed = true;",
        "if (false && mixerStepperStarted && !set_stepper_by_time(0, 0, 0)) rollbackFailed = true;",
    )
    if compensation_mutant == harness:
        print("FAIL: could not build mixer compensation mutation", file=sys.stderr)
        return 1
    returncode, output = compile_and_run(
        compensation_mutant, "mixer compensation mutation", show_output=False
    )
    if returncode == 0:
        print("FAIL: mixer compensation mutation survived smoke", file=sys.stderr)
        return 1
    if "частичный отказ не остановил уже запущенный шаговик мешалки" not in output:
        print(
            "FAIL: mixer compensation mutation was not rejected by the expected assert",
            file=sys.stderr,
        )
        sys.stderr.write(output)
        return 1

    counter_mutant = harness.replace(
        "currentstepcnt = candidateStepCount;", "", 1
    )
    if counter_mutant == harness:
        print("FAIL: could not build mixer counter mutation", file=sys.stderr)
        return 1
    returncode, output = compile_and_run(
        counter_mutant, "mixer counter mutation", show_output=False
    )
    if returncode == 0:
        print("FAIL: mixer counter mutation survived smoke", file=sys.stderr)
        return 1
    if "APPLIED запуска не закоммитил счётчик расписания" not in output:
        print(
            "FAIL: mixer counter mutation was not rejected by the expected assert",
            file=sys.stderr,
        )
        sys.stderr.write(output)
        return 1

    emergency_mutant = harness.replace(
        'request_emergency_stop("Аварийное отключение: не удалось вернуть состояние мешалки");',
        "(void)0;",
        1,
    )
    if emergency_mutant == harness:
        print("FAIL: could not build mixer rollback emergency mutation", file=sys.stderr)
        return 1
    returncode, output = compile_and_run(
        emergency_mutant, "mixer rollback emergency mutation", show_output=False
    )
    if returncode == 0 or "неподтверждённый rollback старта мешалки" not in output:
        print("FAIL: mixer rollback emergency mutation survived smoke", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Beer mixer result mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
