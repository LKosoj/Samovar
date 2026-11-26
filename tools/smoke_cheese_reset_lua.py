#!/usr/bin/env python3
"""Reset Cheese/L waits for the ticketed Lua owner to confirm idle."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
menu = strip_cpp_comments((ROOT / "Menu.ino").read_text(encoding="utf-8"))
cheese = strip_cpp_comments((ROOT / "cheese.h").read_text(encoding="utf-8"))
errors: list[str] = []


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


reset_body = body(menu, "void samovar_reset()")
pending_body = body(cheese, "inline bool cheese_lua_stop_pending()")
finish_body = body(cheese, "void cheese_finish() {")
finish_lua_body = body(cheese, "inline bool cheese_finish_lua_exit()")
tick_body = body(cheese, "void cheese_stage_tick()")

require_ordered_tokens(
    "Cheese reset defers destructive state reset",
    reset_body,
    [
        "stop_active_process_for_mode();",
        "Samovar_Mode == SAMOVAR_CHEESE_MODE && cheese_lua_stop_pending()",
        "return;",
        "request_lua_mode_stop()",
        "reset_sensor_counter();",
    ],
    errors,
)
require_ordered_tokens(
    "Cheese finish confirms Lua idle before clearing stage",
    finish_lua_body,
    [
        "request_beer_lua_stop(cheeseLuaStage.ticket)",
        "beer_lua_job_idle(cheeseLuaStage.ticket)",
        "cheese_reset_lua_stage();",
    ],
    errors,
)
require_ordered_tokens(
    "Cheese finish preserves state until Lua confirmation",
    finish_body,
    [
        "cheeseFinishPending = true;",
        "if (!cheese_finish_lua_exit()) return;",
        "cheese_reset_stage_state();",
        "stop_process(",
    ],
    errors,
)
require_ordered_tokens(
    "Cheese tick retries pending finish",
    tick_body,
    [
        "if (cheeseFinishPending)",
        "cheese_finish();",
        "return;",
    ],
    errors,
)


HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>
#include "@ROOT@/i18n.h"

#define USE_LUA

class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
 private:
  std::string value_;
};

enum SAMOVAR_MODE { SAMOVAR_BEER_MODE, SAMOVAR_CHEESE_MODE };
enum CheeseLuaStagePhase { CHEESE_LUA_STAGE_IDLE, CHEESE_LUA_STAGE_RUNNING };
struct CheeseLuaStageState { CheeseLuaStagePhase phase; };
enum MessageType { WARNING_MSG };
static const int16_t SAMOVAR_STATUS_IDLE = 0;
static const int16_t SAMOVAR_STARTVAL_IDLE = 0;

SAMOVAR_MODE Samovar_Mode = SAMOVAR_BEER_MODE;
CheeseLuaStageState cheeseLuaStage = {CHEESE_LUA_STAGE_IDLE};
bool cheeseFinishPending = false;
int16_t SamovarStatusInt = 0;
int16_t startval = 0;
char startval_text_val[16] = {};
char* power_text_ptr = nullptr;

int stopCalls = 0;
int genericLuaStopCalls = 0;
int resetCounterCalls = 0;
int messages = 0;

template <size_t Size>
void copyStringSafe(char (&)[Size], const String&) {}
void reset_focus() {}
void set_menu_screen(int) {}
void stop_active_process_for_mode() { stopCalls++; }
bool request_lua_mode_stop() { genericLuaStopCalls++; return true; }
void SendMsg(const char*, MessageType) { messages++; }
void reset_sensor_counter() { resetCounterCalls++; }

inline bool cheese_lua_stop_pending() {
@PENDING_BODY@
}

void samovar_reset() {
@RESET_BODY@
}

int failures = 0;
void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

void clear_counts() {
  stopCalls = 0;
  genericLuaStopCalls = 0;
  resetCounterCalls = 0;
  messages = 0;
}

int main() {
  Samovar_Mode = SAMOVAR_CHEESE_MODE;
  cheeseFinishPending = true;
  cheeseLuaStage.phase = CHEESE_LUA_STAGE_RUNNING;
  clear_counts();
  samovar_reset();
  check(stopCalls == 1, "Cheese reset did not request normal mode finish");
  check(genericLuaStopCalls == 0, "Cheese reset used the generic Lua fallback");
  check(resetCounterCalls == 0, "Cheese reset erased state before Lua became idle");

  cheeseLuaStage.phase = CHEESE_LUA_STAGE_IDLE;
  cheeseFinishPending = false;
  clear_counts();
  samovar_reset();
  check(genericLuaStopCalls == 1, "confirmed Cheese reset did not preserve normal reset tail");
  check(resetCounterCalls == 1, "confirmed Cheese reset did not finish state reset");

  Samovar_Mode = SAMOVAR_BEER_MODE;
  cheeseFinishPending = true;
  cheeseLuaStage.phase = CHEESE_LUA_STAGE_RUNNING;
  clear_counts();
  samovar_reset();
  check(genericLuaStopCalls == 1 && resetCounterCalls == 1,
        "Cheese guard changed reset behavior of another mode");
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(reset: str, expect_success: bool) -> bool:
    source = HARNESS.replace("@ROOT@", ROOT.as_posix()).replace("@PENDING_BODY@", pending_body).replace("@RESET_BODY@", reset)
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-reset-") as temp_dir:
        path = Path(temp_dir)
        cpp = path / "test.cpp"
        binary = path / "test"
        cpp.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            sys.stderr.write(compiled.stdout + compiled.stderr)
            return False
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if expect_success:
            sys.stdout.write(ran.stdout)
            sys.stderr.write(ran.stderr)
            return ran.returncode == 0
        return ran.returncode != 0


if errors:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    raise SystemExit(1)

if not compile_and_run(reset_body, True):
    raise SystemExit(1)

mutated = reset_body.replace(
    "if (Samovar_Mode == SAMOVAR_CHEESE_MODE && cheese_lua_stop_pending()) return;",
    "if (false) return;",
    1,
)
if mutated == reset_body:
    print("FAIL: reset mutation target not found", file=sys.stderr)
    raise SystemExit(1)
if not compile_and_run(mutated, False):
    print("FAIL: reset test did not catch early state erasure", file=sys.stderr)
    raise SystemExit(1)

print("OK: Cheese/L reset waits for confirmed Lua idle and mutation is rejected")

FINISH_HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>
#include "@ROOT@/i18n.h"

class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
 private:
  std::string value_;
};

enum SAMOVAR_MODE { SAMOVAR_CHEESE_MODE = 5 };
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum RuntimePairOutcome { RUNTIME_PAIR_PROCESS_END = 3, RUNTIME_PAIR_ERROR = 4 };
static const int16_t SAMOVAR_STARTVAL_IDLE = 0;

static bool cheeseFinishPending = false;
static bool cheesePairErrorPending = false;
static unsigned long begintime = 123;
static uint8_t ProgramNum = 2;
static int16_t startval = 5;
static bool heaterState = true;

static bool safeOutputsOk = true;
static int safeOutputsCalls = 0;
static int emergencyCalls = 0;
static int sendMsgCalls = 0;
static int luaExitTicksRemaining = 0;
static int runtimePairCloseCalls = 0;
static RuntimePairOutcome lastPairOutcome = RUNTIME_PAIR_PROCESS_END;
static MESSAGE_TYPE lastPairMsgType = NOTIFY_MSG;
static int stopProcessCalls = 0;

static void request_emergency_stop(const char*) { emergencyCalls++; }
void SendMsg(const char*, MESSAGE_TYPE) { sendMsgCalls++; }
static bool cheese_apply_safe_outputs(bool) {
  safeOutputsCalls++;
  if (!safeOutputsOk) {
    request_emergency_stop("estop");
    return false;
  }
  return true;
}
static bool cheese_finish_lua_exit() {
  if (luaExitTicksRemaining > 0) {
    luaExitTicksRemaining--;
    return false;
  }
  return true;
}
static void runtime_pair_close_mode(SAMOVAR_MODE, RuntimePairOutcome outcome, const char*, MESSAGE_TYPE msgType) {
  runtimePairCloseCalls++;
  lastPairOutcome = outcome;
  lastPairMsgType = msgType;
}
static void cheese_reset_stage_state() {
  cheesePairErrorPending = false;
  cheeseFinishPending = false;
}
static void set_heater_state_flag(bool state) { heaterState = state; }
static void stop_process(const char*) { stopProcessCalls++; }

void cheese_finish() {
@FINISH_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_finish_fixture() {
  cheeseFinishPending = false;
  cheesePairErrorPending = false;
  begintime = 123;
  ProgramNum = 2;
  startval = 5;
  heaterState = true;
  safeOutputsOk = true;
  safeOutputsCalls = 0;
  emergencyCalls = 0;
  sendMsgCalls = 0;
  luaExitTicksRemaining = 0;
  runtimePairCloseCalls = 0;
  lastPairOutcome = RUNTIME_PAIR_PROCESS_END;
  lastPairMsgType = NOTIFY_MSG;
  stopProcessCalls = 0;
}

int main() {
  // Non-Lua case with I2C disconnect: single emergency stop, no 1 Hz flood,
  // error pair outcome, and clean completion (cheeseFinishPending == false).
  reset_finish_fixture();
  safeOutputsOk = false;
  luaExitTicksRemaining = 0;
  cheese_finish();
  check(safeOutputsCalls == 1 && emergencyCalls == 1,
        "non-Lua I2C disconnect must trigger request_emergency_stop exactly once");
  check(sendMsgCalls == 0,
        "non-Lua I2C disconnect must not emit duplicate SendMsg alarm");
  check(runtimePairCloseCalls == 1 && lastPairOutcome == RUNTIME_PAIR_ERROR &&
        lastPairMsgType == ALARM_MSG,
        "non-Lua I2C disconnect must close runtime pair with RUNTIME_PAIR_ERROR");
  check(stopProcessCalls == 1 && !cheeseFinishPending && startval == SAMOVAR_STARTVAL_IDLE,
        "non-Lua I2C disconnect must complete shutdown cleanly");

  // Lua-pending case with I2C disconnect: 3 pending ticks + 1 final tick.
  // Must call cheese_apply_safe_outputs/request_emergency_stop ONLY once (no 1 Hz flood).
  reset_finish_fixture();
  safeOutputsOk = false;
  luaExitTicksRemaining = 3;
  for (int i = 0; i < 3; i++) {
    cheese_finish();
    check(emergencyCalls == 1,
          "Lua-pending I2C disconnect must not flood request_emergency_stop on retries");
    check(safeOutputsCalls == 1,
          "Lua-pending I2C disconnect must not re-run cheese_apply_safe_outputs on retries");
    check(sendMsgCalls == 0,
          "Lua-pending I2C disconnect must not flood SendMsg alarms");
    check(cheeseFinishPending && cheesePairErrorPending && stopProcessCalls == 0,
          "Lua-pending I2C disconnect must wait for Lua exit while keeping error latch");
  }
  cheese_finish();
  check(emergencyCalls == 1 && safeOutputsCalls == 1,
        "final Lua-exit tick must not re-trigger emergency stop");
  check(runtimePairCloseCalls == 1 && lastPairOutcome == RUNTIME_PAIR_ERROR &&
        lastPairMsgType == ALARM_MSG,
        "final Lua-exit tick must close runtime pair with RUNTIME_PAIR_ERROR");
  check(stopProcessCalls == 1 && !cheeseFinishPending && !cheesePairErrorPending,
        "final Lua-exit tick must clear cheeseFinishPending and finish shutdown");

  // Normal finish path (safeOutputsOk == true): no emergency stop, NOTIFY_MSG / RUNTIME_PAIR_PROCESS_END.
  reset_finish_fixture();
  safeOutputsOk = true;
  luaExitTicksRemaining = 0;
  cheese_finish();
  check(safeOutputsCalls == 1 && emergencyCalls == 0 && sendMsgCalls == 0,
        "normal finish must call cheese_apply_safe_outputs once with zero emergency stops");
  check(runtimePairCloseCalls == 1 && lastPairOutcome == RUNTIME_PAIR_PROCESS_END &&
        lastPairMsgType == NOTIFY_MSG,
        "normal finish must close runtime pair with RUNTIME_PAIR_PROCESS_END and NOTIFY_MSG");
  check(stopProcessCalls == 1 && !cheeseFinishPending && !cheesePairErrorPending &&
        startval == SAMOVAR_STARTVAL_IDLE,
        "normal finish must clear cheeseFinishPending and complete shutdown");

  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run_finish(body_src: str, expect_success: bool) -> bool:
    source = FINISH_HARNESS.replace("@ROOT@", ROOT.as_posix()).replace("@FINISH_BODY@", body_src)
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-finish-") as temp_dir:
        path = Path(temp_dir)
        cpp = path / "test.cpp"
        binary = path / "test"
        cpp.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            if expect_success:
                sys.stderr.write(compiled.stdout + compiled.stderr)
            return False
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if expect_success:
            sys.stdout.write(ran.stdout)
            sys.stderr.write(ran.stderr)
            return ran.returncode == 0
        return ran.returncode != 0


if not compile_and_run_finish(finish_body, True):
    raise SystemExit(1)

finish_mutant = finish_body.replace(
    "if (firstAttempt) {",
    "if (true) { (void)firstAttempt;",
    1,
)
if finish_mutant == finish_body:
    print("FAIL: finish mutation target not found", file=sys.stderr)
    raise SystemExit(1)
if not compile_and_run_finish(finish_mutant, False):
    print("FAIL: finish test did not catch 1 Hz retry flood mutation", file=sys.stderr)
    raise SystemExit(1)

print("OK: Cheese finish handles I2C disconnect without 1 Hz flood (non-Lua and Lua-pending)")
