#!/usr/bin/env python3
"""Production-derived smoke для переходов Beer P/B/C -> Lua -> Beer."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]

RUN_BEER_PROGRAM_SIGNATURE = "void run_beer_program(uint8_t num)"
BEER_STAGE_TICK_SIGNATURE = "void beer_stage_tick()"
BEER_SAFE_LUA_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_safe_lua_outputs()"
COOLING_PUMP_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_pump(bool active)"
COOLING_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_outputs(bool active)"
BEER_RESET_LUA_STAGE_SIGNATURE = "inline void beer_reset_lua_stage()"
PROGRAM_TYPE_AT_SIGNATURE = "inline ProgramType program_type_at(uint8_t index)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define USE_LUA
#define USE_WATER_PUMP

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String(int value) : value_(std::to_string(value)) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  String(float value) : value_(std::to_string(value)) {}
  String operator+(const char* text) const {
    return String(value_ + (text ? text : ""));
  }
  String operator+(const String& other) const {
    return String(value_ + other.value_);
  }
  String& operator+=(const char* text) {
    value_ += text ? text : "";
    return *this;
  }
  String& operator+=(const String& other) {
    value_ += other.value_;
    return *this;
  }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

static String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG, NOTIFY_MSG };
enum SAMOVAR_MODE { SAMOVAR_RECTIFICATION_MODE = 0, SAMOVAR_BEER_MODE };
enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
enum LuaBeerJobResult : uint8_t {
  LUA_BEER_JOB_IDLE = 0,
  LUA_BEER_JOB_QUEUED,
  LUA_BEER_JOB_RUNNING,
  LUA_BEER_JOB_SUCCEEDED,
  LUA_BEER_JOB_FAILED_INIT,
  LUA_BEER_JOB_FAILED_RUNTIME,
  LUA_BEER_JOB_FAILED_TIMEOUT,
  // [Дефект 2] занятый RUNTIME_STATE на короткий миг чтения - не то же самое,
  // что настоящий сбой job'а; beer_stage_tick() опрашивает снова на следующем
  // такте вместо того, чтобы аварийно прерывать варку.
  LUA_BEER_JOB_LOCK_BUSY,
};
enum BeerLuaStagePhase : uint8_t {
  BEER_LUA_STAGE_IDLE = 0,
  BEER_LUA_STAGE_ENTER_QUEUED,
  BEER_LUA_STAGE_RUNNING,
  BEER_LUA_STAGE_EXIT_QUEUED,
};

using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_MAX = 8;
constexpr uint8_t PROGRAM_END = PROGRAM_MAX;
constexpr int16_t SAMOVAR_STARTVAL_BEER_START = 2000;
constexpr int16_t SAMOVAR_STARTVAL_BEER_HEATING = 2001;

struct WProgram {
  ProgramType WType = PROGRAM_TYPE_NONE;
  uint16_t Volume = 0;
  float Speed = 0;
  uint8_t capacity_num = 0;
  float Temp = 0;
  float Power = 0;
  uint8_t TempSensor = 0;
  float Time = 0;
};

struct SetupEEPROM {
  bool ChangeProgramBuzzer = false;
};

struct DSSensor {
  float avgTemp = 0;
  bool alarm = false;
};

struct BeerLuaStageState {
  BeerLuaStagePhase phase;
  uint32_t ticket;
  uint8_t nextProgram;
};

static WProgram program[PROGRAM_MAX];
static SetupEEPROM SamSetup;
static DSSensor TankSensor;
static BeerLuaStageState beerLuaStage = {
    BEER_LUA_STAGE_IDLE, 0, PROGRAM_END};

static volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_BEER_MODE;
static volatile bool PowerOn = true;
static volatile int16_t startval = SAMOVAR_STARTVAL_BEER_HEATING;
static volatile uint8_t ProgramNum = 0;
static volatile uint8_t ProgramLen = 0;
static volatile bool SetScriptOff = false;
static bool msgfl = false;
static unsigned long begintime = 0;
static int currentstepcnt = 0;
static unsigned long alarm_c_min = 0;
static unsigned long alarm_c_low_min = 0;
static unsigned long beerStageIdleAccumMs = 0;
static unsigned long beerStageIdleSinceMs = 0;
static unsigned long beerBoilActiveAccumMs = 0;  // [П13] см. beer.h - таймаут разгона до кипения
static unsigned long beerMixerPauseSinceMs = 0;  // [Дефект 2 code review] см. beer.h
static bool beerCoolingPumpActive = false;
static bool valve_status = false;
static bool mixer_status = false;
static bool heaterOutput = false;

static unsigned long fakeMillis = 1000;
unsigned long millis() { return fakeMillis; }

#ifndef BEER_SKIP_CONFIRM_WINDOW_MS
#define BEER_SKIP_CONFIRM_WINDOW_MS 10000UL
#endif
static uint8_t beerSkipConfirmProgramNum = 0xFF;
static unsigned long beerSkipConfirmDeadlineMs = 0;

static bool sensor_valid(const DSSensor&) { return true; }
static bool beer_control_sensor(
    uint8_t, const DSSensor*& sensor, const char*& name) {
  sensor = &TankSensor;
  name = "куба";
  return true;
}

static int heaterCalls = 0;
void setHeaterPosition(bool state) {
  heaterOutput = state;
  heaterCalls++;
}

static int valveCalls = 0;
ActuatorCommandResult open_valve(bool state, bool) {
  valve_status = state;
  valveCalls++;
  return ACTUATOR_COMMAND_APPLIED;
}

void request_emergency_stop(const char*) {}

static int pumpCalls = 0;
static float lastPumpPwm = -1;
ActuatorCommandResult set_pump_pwm(float duty) {
  lastPumpPwm = duty;
  pumpCalls++;
  return ACTUATOR_COMMAND_APPLIED;
}

static int mixerCalls = 0;
static ActuatorCommandResult mixerResult = ACTUATOR_COMMAND_APPLIED;
ActuatorCommandResult set_mixer_state(bool state, bool) {
  mixerCalls++;
  if (mixerResult == ACTUATOR_COMMAND_APPLIED) mixer_status = state;
  return mixerResult;
}

static int resetBoilingDetectorCalls = 0;
void resetBoilingDetector() { resetBoilingDetectorCalls++; }
static int startAutoTuneCalls = 0;
void StartAutoTune() { startAutoTuneCalls++; }
static int beerFinishCalls = 0;
void beer_finish() { beerFinishCalls++; }
static int sendMsgCalls = 0;
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }
static int buzzerCalls = 0;
void set_buzzer(bool) { buzzerCalls++; }

static int abortCalls = 0;
static std::string abortReason;
void beer_abort_config_error(const String& reason) {
  abortCalls++;
  abortReason = reason.value();
}

static bool acceptLuaJob = true;
static ActuatorCommandResult luaStopResult = ACTUATOR_COMMAND_APPLIED;
static bool luaJobIdle = false;
static uint32_t nextTicket = 40;
static int requestJobCalls = 0;
static int requestStopCalls = 0;
static uint32_t lastStopTicket = 0;
static LuaBeerJobResult luaJobResult = LUA_BEER_JOB_QUEUED;

bool request_beer_lua_job(uint32_t& ticket) {
  requestJobCalls++;
  if (!acceptLuaJob) return false;
  ticket = ++nextTicket;
  luaJobResult = LUA_BEER_JOB_QUEUED;
  return true;
}

LuaBeerJobResult beer_lua_job_result(uint32_t ticket) {
  if (ticket != beerLuaStage.ticket) return LUA_BEER_JOB_FAILED_RUNTIME;
  return luaJobResult;
}

ActuatorCommandResult request_beer_lua_stop(uint32_t ticket) {
  requestStopCalls++;
  lastStopTicket = ticket;
  return luaStopResult;
}

bool beer_lua_job_idle(uint32_t ticket) {
  return ticket == beerLuaStage.ticket && luaJobIdle;
}

inline ProgramType program_type_at(uint8_t index) {
@PROGRAM_TYPE_AT_BODY@
}

inline ActuatorCommandResult beer_set_cooling_pump(bool active) {
@COOLING_PUMP_BODY@
}

inline ActuatorCommandResult beer_set_cooling_outputs(bool active) {
@COOLING_OUTPUTS_BODY@
}

inline ActuatorCommandResult beer_safe_lua_outputs() {
@BEER_SAFE_LUA_OUTPUTS_BODY@
}

inline void beer_reset_lua_stage() {
@BEER_RESET_LUA_STAGE_BODY@
}

@RUN_BEER_PROGRAM_BODY@

static void beer_lua_stage_tick_only() {
  if (program_type_at(ProgramNum) == 'L') {
@L_STAGE_BRANCH@
  }
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(ProgramType sourceType) {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  program[0].WType = sourceType;
  program[0].Temp = 20;
  program[1].WType = 'L';
  program[2].WType = 'P';
  ProgramLen = 3;
  ProgramNum = 0;
  Samovar_Mode = SAMOVAR_BEER_MODE;
  PowerOn = true;
  startval = SAMOVAR_STARTVAL_BEER_HEATING;
  SetScriptOff = false;
  msgfl = false;
  begintime = 777;
  currentstepcnt = 9;
  alarm_c_min = 123;
  alarm_c_low_min = 456;
  beerStageIdleAccumMs = 99;
  beerStageIdleSinceMs = 88;
  beerBoilActiveAccumMs = 0;
  beerMixerPauseSinceMs = 0;
  beerSkipConfirmProgramNum = 0xFF;
  beerSkipConfirmDeadlineMs = 0;
  TankSensor.avgTemp = 10;
  beerLuaStage = {BEER_LUA_STAGE_IDLE, 0, PROGRAM_END};
  heaterOutput = true;
  valve_status = true;
  mixer_status = true;
  beerCoolingPumpActive = true;
  heaterCalls = 0;
  valveCalls = 0;
  pumpCalls = 0;
  lastPumpPwm = -1;
  mixerCalls = 0;
  mixerResult = ACTUATOR_COMMAND_APPLIED;
  resetBoilingDetectorCalls = 0;
  startAutoTuneCalls = 0;
  beerFinishCalls = 0;
  sendMsgCalls = 0;
  buzzerCalls = 0;
  abortCalls = 0;
  abortReason.clear();
  acceptLuaJob = true;
  luaStopResult = ACTUATOR_COMMAND_APPLIED;
  luaJobIdle = false;
  nextTicket = 40;
  requestJobCalls = 0;
  requestStopCalls = 0;
  lastStopTicket = 0;
  luaJobResult = LUA_BEER_JOB_QUEUED;
}

static void check_safe_lua_entry_outputs() {
  check(!heaterOutput, "Lua entry left heater enabled");
  check(!valve_status, "Lua entry left cooling valve open");
  check(lastPumpPwm == 0, "Lua entry did not stop water pump");
  check(!beerCoolingPumpActive, "Lua entry retained cooling ownership");
  check(!mixer_status, "Lua entry left mixer enabled");
}

static void test_heating_stages_enter_lua_with_real_ticket() {
  const ProgramType sources[] = {'P', 'B', 'C'};
  for (ProgramType source : sources) {
    reset_fixture(source);
    run_beer_program(1);

    check(ProgramNum == 1, "P/B/C -> L did not commit Lua ProgramNum");
    check(requestJobCalls == 1, "P/B/C -> L did not request exactly one Lua job");
    check(beerLuaStage.phase == BEER_LUA_STAGE_ENTER_QUEUED,
          "P/B/C -> L did not enter ENTER_QUEUED");
    check(beerLuaStage.ticket == 41,
          "P/B/C -> L did not retain the accepted job ticket");
    check(beerLuaStage.nextProgram == PROGRAM_END,
          "Lua entry retained a stale next program");
    check(abortCalls == 0, "valid P/B/C -> L transition aborted");
    check_safe_lua_entry_outputs();
  }
}

static void enter_lua_stage() {
  reset_fixture('P');
  run_beer_program(1);
}

static void test_queue_and_running_hold_lua_program() {
  enter_lua_stage();
  const LuaBeerJobResult results[] = {
      LUA_BEER_JOB_QUEUED, LUA_BEER_JOB_RUNNING};
  for (LuaBeerJobResult result : results) {
    luaJobResult = result;
    heaterOutput = true;
    valve_status = true;
    mixer_status = true;
    beerCoolingPumpActive = true;
    lastPumpPwm = -1;

    beer_lua_stage_tick_only();

    check(ProgramNum == 1, "queued/running Lua job advanced ProgramNum");
    check(beerLuaStage.phase == BEER_LUA_STAGE_ENTER_QUEUED,
          "queued/running Lua job changed stage phase");
    check(abortCalls == 0, "queued/running Lua job aborted");
    check_safe_lua_entry_outputs();
  }
}

static void test_success_then_confirmed_exit_advances_once() {
  enter_lua_stage();
  luaJobResult = LUA_BEER_JOB_SUCCEEDED;
  beer_lua_stage_tick_only();
  check(beerLuaStage.phase == BEER_LUA_STAGE_RUNNING,
        "SUCCEEDED job did not enter RUNNING phase");
  check(ProgramNum == 1, "SUCCEEDED job advanced ProgramNum before exit");

  run_beer_program(2);
  check(ProgramNum == 1, "Lua stop request advanced ProgramNum immediately");
  check(beerLuaStage.phase == BEER_LUA_STAGE_EXIT_QUEUED,
        "Lua stop request did not enter EXIT_QUEUED");
  check(beerLuaStage.nextProgram == 2,
        "Lua stop request did not retain next ProgramNum");
  check(requestStopCalls == 1 && lastStopTicket == 41,
        "Lua stop request used the wrong ticket");

  luaJobIdle = false;
  beer_lua_stage_tick_only();
  check(ProgramNum == 1, "non-idle Lua owner advanced ProgramNum");

  luaJobIdle = true;
  beer_lua_stage_tick_only();
  check(ProgramNum == 2, "idle Lua owner did not advance to retained ProgramNum");
  check(beerLuaStage.phase == BEER_LUA_STAGE_IDLE,
        "confirmed Lua exit did not reset stage state");
  check(beerLuaStage.ticket == 0,
        "confirmed Lua exit retained the completed ticket");
  check(requestStopCalls == 1, "confirmed Lua exit requested stop twice");
}

static void test_failed_results_abort_without_advance() {
  // T18: FAILED_INIT (job ни разу не подтвердил запуск) обязан получать СВОЙ
  // текст, отличный от FAILED_RUNTIME/FAILED_TIMEOUT (job запускался, но упал
  // уже в процессе) - иначе при диагностике нельзя отличить "скрипт вообще не
  // завёлся" от "скрипт упал на середине".
  enter_lua_stage();
  luaJobResult = LUA_BEER_JOB_FAILED_INIT;
  beer_lua_stage_tick_only();
  check(abortCalls == 1, "FAILED_INIT did not raise an orderly error");
  check(ProgramNum == 1, "FAILED_INIT advanced ProgramNum");
  check(abortReason.find("не подтвердил запуск") != std::string::npos,
        "FAILED_INIT must report the 'job never confirmed start' text");
  const std::string initReason = abortReason;

  const LuaBeerJobResult genericFailures[] = {
      LUA_BEER_JOB_FAILED_RUNTIME,
      LUA_BEER_JOB_FAILED_TIMEOUT,
  };
  for (LuaBeerJobResult result : genericFailures) {
    enter_lua_stage();
    luaJobResult = result;
    beer_lua_stage_tick_only();

    check(abortCalls == 1, "failed Lua result did not raise an orderly error");
    check(ProgramNum == 1, "failed Lua result advanced ProgramNum");
    check(abortReason.find("завершился с ошибкой") != std::string::npos,
          "FAILED_RUNTIME/FAILED_TIMEOUT must report the generic 'job завершился с ошибкой' text");
    check(abortReason != initReason,
          "FAILED_RUNTIME/FAILED_TIMEOUT must not reuse FAILED_INIT's error text");
  }
}

// [Дефект 2] LOCK_BUSY - RUNTIME_STATE занят на короткий миг чтения, не
// провал job'а: beer_stage_tick() обязан опросить снова на следующем такте,
// как и для QUEUED/RUNNING, а не аварийно прерывать варку.
static void test_lock_busy_result_polls_again_without_abort() {
  enter_lua_stage();
  luaJobResult = LUA_BEER_JOB_LOCK_BUSY;
  heaterOutput = true;
  valve_status = true;
  mixer_status = true;
  beerCoolingPumpActive = true;
  lastPumpPwm = -1;

  beer_lua_stage_tick_only();

  check(ProgramNum == 1, "LOCK_BUSY result advanced ProgramNum");
  check(beerLuaStage.phase == BEER_LUA_STAGE_ENTER_QUEUED,
        "LOCK_BUSY result changed stage phase");
  check(abortCalls == 0, "LOCK_BUSY result aborted the brew on a transient lock");
  check_safe_lua_entry_outputs();
}

// [Дефект 2] request_beer_lua_stop() занятым локом (ACTUATOR_COMMAND_PENDING)
// не должен прерывать варку - run_beer_program() обязан тихо вернуться и
// оставить тикет/фазу как есть, чтобы следующий вызов (по кнопке или
// автопереходу) повторил запрос сам.
static void test_exit_stop_lock_busy_returns_quietly_without_abort() {
  enter_lua_stage();
  luaJobResult = LUA_BEER_JOB_SUCCEEDED;
  beer_lua_stage_tick_only();
  check(beerLuaStage.phase == BEER_LUA_STAGE_RUNNING,
        "SUCCEEDED job did not enter RUNNING phase before exit test");

  luaStopResult = ACTUATOR_COMMAND_PENDING;
  run_beer_program(2);

  check(abortCalls == 0, "PENDING Lua stop request aborted the brew on a transient lock");
  check(ProgramNum == 1, "PENDING Lua stop request advanced ProgramNum");
  check(beerLuaStage.phase == BEER_LUA_STAGE_RUNNING,
        "PENDING Lua stop request must leave the stage phase untouched (retry expected)");
  check(beerLuaStage.ticket == 41,
        "PENDING Lua stop request must not drop the still-active job ticket");
  check(requestStopCalls == 1, "PENDING Lua stop request was not attempted");
}

// [Дефект 2] Настоящий отказ (не занятый лок) обязан по-прежнему аварийно
// прерывать варку - иначе распад PENDING/FAILED в одну сторону замаскирует
// реальную ошибку согласования.
static void test_exit_stop_real_failure_still_aborts() {
  enter_lua_stage();
  luaJobResult = LUA_BEER_JOB_SUCCEEDED;
  beer_lua_stage_tick_only();

  luaStopResult = ACTUATOR_COMMAND_FAILED;
  run_beer_program(2);

  check(abortCalls == 1, "real Lua stop failure did not raise an orderly error");
  check(abortReason.find("не удалось запросить остановку job") != std::string::npos,
        "real Lua stop failure must report the 'stop request failed' text");
  check(beerLuaStage.phase == BEER_LUA_STAGE_RUNNING,
        "real Lua stop failure must not advance the stage into EXIT_QUEUED");
}

int main() {
  test_heating_stages_enter_lua_with_real_ticket();
  test_queue_and_running_hold_lua_program();
  test_success_then_confirmed_exit_advances_once();
  test_failed_results_abort_without_advance();
  test_lock_busy_result_polls_again_without_abort();
  test_exit_stop_lock_busy_returns_quietly_without_abort();
  test_exit_stop_real_failure_still_aborts();
  if (failures != 0) return 1;
  std::cout << "Beer Lua stage transition checks passed\n";
  return 0;
}
'''


def build_harness(beer_source: str, runtime_source: str) -> str:
    run_body = extract_function_body(beer_source, RUN_BEER_PROGRAM_SIGNATURE)
    cooling_pump_body = extract_function_body(beer_source, COOLING_PUMP_SIGNATURE)
    cooling_outputs_body = extract_function_body(beer_source, COOLING_OUTPUTS_SIGNATURE)
    safe_body = extract_function_body(beer_source, BEER_SAFE_LUA_OUTPUTS_SIGNATURE)
    reset_body = extract_function_body(beer_source, BEER_RESET_LUA_STAGE_SIGNATURE)
    program_type_body = extract_function_body(runtime_source, PROGRAM_TYPE_AT_SIGNATURE)
    stage_body = extract_function_body(beer_source, BEER_STAGE_TICK_SIGNATURE)
    l_branch, _ = extract_braced_block_after(stage_body, "if (currentType == 'L') {")

    harness = HARNESS_TEMPLATE.replace(
        "@RUN_BEER_PROGRAM_BODY@", "void run_beer_program(uint8_t num) {" + run_body + "}"
    )
    harness = harness.replace("@BEER_SAFE_LUA_OUTPUTS_BODY@", safe_body)
    harness = harness.replace("@COOLING_PUMP_BODY@", cooling_pump_body)
    harness = harness.replace("@COOLING_OUTPUTS_BODY@", cooling_outputs_body)
    harness = harness.replace("@BEER_RESET_LUA_STAGE_BODY@", reset_body)
    harness = harness.replace("@PROGRAM_TYPE_AT_BODY@", program_type_body)
    harness = harness.replace("@L_STAGE_BRANCH@", l_branch)
    return harness


def compile_and_run(harness: str, label: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-lua-stage-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_lua_stage_test.cpp"
        binary = temp / "beer_lua_stage_test"
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


def require_rejected_mutation(
    harness: str, old: str, new: str, label: str, expected_failure: str
) -> bool:
    mutant = harness.replace(old, new, 1)
    if mutant == harness:
        print(f"FAIL: could not build {label} mutation", file=sys.stderr)
        return False
    returncode, output = compile_and_run(mutant, label, show_output=False)
    if returncode == 0:
        print(f"FAIL: {label} mutation survived smoke", file=sys.stderr)
        return False
    if expected_failure not in output:
        print(
            f"FAIL: {label} mutation was not rejected by the expected assert",
            file=sys.stderr,
        )
        sys.stderr.write(output)
        return False
    return True


def main() -> int:
    beer_source = (ROOT / "beer.h").read_text(encoding="utf-8")
    runtime_source = (ROOT / "runtime_helpers.h").read_text(encoding="utf-8")

    # [Дефект 2] beer_finish() - симметричный run_beer_program() второй вызов
    # request_beer_lua_stop() (beer.h, завершение варки по PROGRAM_END). Сама
    # функция трогает слишком много не связанного с Lua состояния (детектор
    # кипения, ручную паузу, сброс нагревателя и т.д.), чтобы извлекать её
    # целиком в этот харнесс - вместо поведенческого теста здесь только
    # структурная проверка РЕАЛЬНОГО текста: PENDING обязан возвращаться тихо
    # (без SendMsg/ALARM_MSG), а настоящий отказ - по-прежнему аварийно.
    # [Ревью 24.08, дефект 2] beer_finish() зовётся ИЗВНЕ (SAMOVAR_POWER/
    # SAMOVAR_POWER_OFF, кнопка "стоп") ровно один раз через реестр режимов -
    # в отличие от run_beer_program() у него нет естественного повторного
    # триггера. Поэтому PENDING здесь не просто "return", а взвод
    # beerFinishPending - его подхватят beer_proc()/beer_stage_tick() на
    # следующем тике и повторят вызов сами (иначе сигнал завершения варки
    # терялся бы насовсем).
    try:
        finish_body = extract_function_body(beer_source, "void beer_finish() {")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    finish_errors: list[str] = []
    require_ordered_tokens(
        "beer_finish",
        finish_body,
        [
            "const ActuatorCommandResult stopResult = request_beer_lua_stop(beerLuaStage.ticket);",
            "if (stopResult == ACTUATOR_COMMAND_PENDING) {",
            "beerFinishPending = true;",
            "if (stopResult != ACTUATOR_COMMAND_APPLIED) {",
            'SendMsg("Ошибка Lua: не удалось запросить остановку job", ALARM_MSG);',
            "beerLuaStage.phase = BEER_LUA_STAGE_EXIT_QUEUED;",
        ],
        finish_errors,
    )
    if finish_errors:
        for error in finish_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    # МУТАЦИЯ: сама структурная проверка выше обязана ловить откат PENDING-
    # ветки в beer_finish() - иначе это молчаливая, никогда не срабатывающая
    # проверка. Мутируем ТОЛЬКО извлечённое тело beer_finish() (не весь
    # beer_source) - убираем взвод флага, оставляя тихий return (так выглядела
    # бы регрессия к дефекту 2, где сигнал завершения варки терялся насовсем).
    mutant_finish_body = finish_body.replace(
        "beerFinishPending = true;\n        return;", "return;", 1
    )
    if mutant_finish_body == finish_body:
        print("FAIL: could not build beer_finish() PENDING mutation", file=sys.stderr)
        return 1
    mutation_errors: list[str] = []
    require_ordered_tokens(
        "beer_finish (mutated)",
        mutant_finish_body,
        [
            "const ActuatorCommandResult stopResult = request_beer_lua_stop(beerLuaStage.ticket);",
            "if (stopResult == ACTUATOR_COMMAND_PENDING) {",
            "beerFinishPending = true;",
            "if (stopResult != ACTUATOR_COMMAND_APPLIED) {",
            'SendMsg("Ошибка Lua: не удалось запросить остановку job", ALARM_MSG);',
            "beerLuaStage.phase = BEER_LUA_STAGE_EXIT_QUEUED;",
        ],
        mutation_errors,
    )
    if not mutation_errors:
        print(
            "FAIL: beer_finish() PENDING mutation survived - structural check does not bite",
            file=sys.stderr,
        )
        return 1

    try:
        harness = build_harness(beer_source, runtime_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    returncode, _ = compile_and_run(harness, "beer Lua stage")
    if returncode != 0:
        return 1

    mutations = [
        (
            "beerLuaStage.ticket = ticket;",
            "beerLuaStage.ticket = 0;",
            "ticket retention",
            "did not retain the accepted job ticket",
        ),
        (
            "ProgramNum = targetProgram;",
            "ProgramNum = ProgramNum;",
            "ProgramNum entry",
            "did not commit Lua ProgramNum",
        ),
        (
            'beer_abort_config_error(result == LUA_BEER_JOB_FAILED_INIT\n'
            '        ? "Ошибка Lua: job не подтвердил запуск"\n'
            '        : "Ошибка Lua: job завершился с ошибкой");',
            'beer_abort_config_error("Ошибка Lua: job завершился с ошибкой");',
            "FAILED_INIT distinct error text",
            "FAILED_INIT must report the 'job never confirmed start' text",
        ),
        (
            "beerLuaStage.nextProgram = targetProgram;",
            "beerLuaStage.nextProgram = PROGRAM_END;",
            "next ProgramNum retention",
            "did not retain next ProgramNum",
        ),
        # [Дефект 2] МУТАЦИЯ: run_beer_program() снова сливает занятый лок с
        # реальным отказом - тест обязан упасть (варка аварийно прервётся на
        # любой микро-задержке RUNTIME_STATE). beer_finish() в этот харнесс не
        # извлекается (см. комментарий выше про структурную проверку) - токен
        # с фигурными скобками встречается в тексте харнесса только один раз.
        (
            'if (stopResult == ACTUATOR_COMMAND_PENDING) {\n'
            '        SendMsg("Не удалось сразу остановить job Lua - блокировка занята. Повторите переход через секунду.", WARNING_MSG);\n'
            '        return;\n'
            '      }',
            "if (false) return;",
            "exit PENDING does not abort",
            "PENDING Lua stop request aborted the brew on a transient lock",
        ),
        # [Дефект 2] МУТАЦИЯ: beer_stage_tick() перестаёт опрашивать LOCK_BUSY
        # повторно - тест обязан упасть (варка аварийно прервётся на любой
        # микро-задержке RUNTIME_STATE при опросе результата job'а).
        (
            "if (result == LUA_BEER_JOB_LOCK_BUSY || result == LUA_BEER_JOB_QUEUED ||",
            "if (false || result == LUA_BEER_JOB_QUEUED ||",
            "L dispatch LOCK_BUSY polls again",
            "LOCK_BUSY result aborted the brew on a transient lock",
        ),
    ]
    for old, new, label, expected_failure in mutations:
        if not require_rejected_mutation(
            harness, old, new, label, expected_failure
        ):
            return 1

    print("Beer Lua stage mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
