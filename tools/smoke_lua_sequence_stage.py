#!/usr/bin/env python3
"""Behavioural contract for lua_sequence_stage_* and distiller/BK finish reset."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <iostream>

constexpr uint8_t PROGRAM_END = 255;

enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

enum LuaBeerJobResult : uint8_t {
  LUA_BEER_JOB_IDLE = 0,
  LUA_BEER_JOB_LOCK_BUSY,
  LUA_BEER_JOB_QUEUED,
  LUA_BEER_JOB_RUNNING,
  LUA_BEER_JOB_SUCCEEDED,
  LUA_BEER_JOB_FAILED,
  LUA_BEER_JOB_STOPPED,
};

enum LuaSequenceStageResult : uint8_t {
  LUA_SEQUENCE_STAGE_ACTIVE = 0,
  LUA_SEQUENCE_STAGE_ADVANCE,
  LUA_SEQUENCE_STAGE_TIMEOUT,
  LUA_SEQUENCE_STAGE_FAILED,
};

struct LuaSequenceStageState {
  uint32_t ticket;
  uint32_t enteredMs;
  uint8_t nextProgram;
  LuaSequenceStageResult exitResult;
  bool active;
  bool stopRequested;
};

static LuaSequenceStageState luaSequenceStage = {};
static bool SetScriptOff = false;

static bool nextBeginOk = true;
static uint32_t nextTicket = 42;
static LuaBeerJobResult currentJobResult = LUA_BEER_JOB_RUNNING;
static ActuatorCommandResult nextStopResult = ACTUATOR_COMMAND_APPLIED;
static bool currentJobIdle = true;
static int stopCalls = 0;
static uint32_t lastStopTicket = 0;

static bool request_program_lua_job(uint8_t, uint32_t& ticket) {
  if (!nextBeginOk) return false;
  ticket = nextTicket;
  return true;
}

static LuaBeerJobResult beer_lua_job_result(uint32_t) {
  return currentJobResult;
}

static ActuatorCommandResult request_beer_lua_stop(uint32_t ticket) {
  stopCalls++;
  lastStopTicket = ticket;
  return nextStopResult;
}

static bool beer_lua_job_idle(uint32_t) {
  return currentJobIdle;
}

inline bool lua_sequence_stage_begin(uint8_t rowIndex, uint32_t nowMs) {
@BEGIN_BODY@
}

inline bool lua_sequence_stage_request_exit(
    uint8_t nextProgram,
    LuaSequenceStageResult result = LUA_SEQUENCE_STAGE_ADVANCE) {
@REQUEST_EXIT_BODY@
}

inline LuaSequenceStageResult lua_sequence_stage_tick(
    uint32_t nowMs, uint16_t timeoutSeconds, uint8_t& nextProgram) {
@TICK_BODY@
}

inline void lua_sequence_stage_reset() {
@RESET_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  luaSequenceStage = {};
  SetScriptOff = false;
  nextBeginOk = true;
  nextTicket = 42;
  currentJobResult = LUA_BEER_JOB_RUNNING;
  nextStopResult = ACTUATOR_COMMAND_APPLIED;
  currentJobIdle = true;
  stopCalls = 0;
  lastStopTicket = 0;
}

int main() {
  // 1. PENDING stop keeps stage active and preserves state.
  reset_fixture();
  check(lua_sequence_stage_begin(1, 1000), "begin should succeed");
  check(lua_sequence_stage_request_exit(2), "request_exit should succeed");
  nextStopResult = ACTUATOR_COMMAND_PENDING;
  uint8_t nextProgram = 99;
  check(lua_sequence_stage_tick(1100, 60, nextProgram) == LUA_SEQUENCE_STAGE_ACTIVE,
        "PENDING stop must keep stage active");
  check(luaSequenceStage.active && stopCalls == 1 && lastStopTicket == 42,
        "PENDING stop must keep active flag and call stop with ticket");

  // 2. FAILED stop (e.g. stale/mismatched ticket) must fail and reset stage instead of spinning forever.
  reset_fixture();
  check(lua_sequence_stage_begin(1, 1000), "begin should succeed (FAILED case)");
  check(lua_sequence_stage_request_exit(2), "request_exit should succeed (FAILED case)");
  nextStopResult = ACTUATOR_COMMAND_FAILED;
  nextProgram = 2;
  check(lua_sequence_stage_tick(1100, 60, nextProgram) == LUA_SEQUENCE_STAGE_FAILED,
        "FAILED stop must return LUA_SEQUENCE_STAGE_FAILED");
  check(nextProgram == PROGRAM_END,
        "FAILED stop must set nextProgram = PROGRAM_END");
  check(!luaSequenceStage.active && luaSequenceStage.ticket == 0,
        "FAILED stop must clear luaSequenceStage");

  // 3. APPLIED stop waits for idle, then advances and clears stage.
  reset_fixture();
  check(lua_sequence_stage_begin(1, 1000), "begin should succeed (APPLIED case)");
  check(lua_sequence_stage_request_exit(3), "request_exit should succeed (APPLIED case)");
  nextStopResult = ACTUATOR_COMMAND_APPLIED;
  currentJobIdle = false;
  nextProgram = 99;
  check(lua_sequence_stage_tick(1100, 60, nextProgram) == LUA_SEQUENCE_STAGE_ACTIVE,
        "APPLIED stop with busy job must stay active until idle");
  check(luaSequenceStage.active, "busy job must remain active");
  currentJobIdle = true;
  check(lua_sequence_stage_tick(1200, 60, nextProgram) == LUA_SEQUENCE_STAGE_ADVANCE,
        "APPLIED stop with idle job must return LUA_SEQUENCE_STAGE_ADVANCE");
  check(nextProgram == 3 && !luaSequenceStage.active,
        "APPLIED stop with idle job must deliver nextProgram and clear stage");

  // 4. lua_sequence_stage_reset(): inactive does nothing.
  reset_fixture();
  lua_sequence_stage_reset();
  check(stopCalls == 0 && !SetScriptOff && !luaSequenceStage.active,
        "reset while inactive must not call stop or set SetScriptOff");

  // 5. lua_sequence_stage_reset(): active + APPLIED stops ticket and clears without forcing SetScriptOff.
  reset_fixture();
  nextTicket = 77;
  check(lua_sequence_stage_begin(0, 500), "begin should succeed (reset APPLIED)");
  nextStopResult = ACTUATOR_COMMAND_APPLIED;
  lua_sequence_stage_reset();
  check(stopCalls == 1 && lastStopTicket == 77,
        "reset while active must call request_beer_lua_stop with active ticket");
  check(!SetScriptOff && !luaSequenceStage.active && luaSequenceStage.ticket == 0,
        "reset with APPLIED stop must clear stage without extra SetScriptOff");

  // 6. lua_sequence_stage_reset(): active + PENDING sets SetScriptOff = true and clears stage.
  reset_fixture();
  nextTicket = 88;
  check(lua_sequence_stage_begin(0, 500), "begin should succeed (reset PENDING)");
  nextStopResult = ACTUATOR_COMMAND_PENDING;
  lua_sequence_stage_reset();
  check(stopCalls == 1 && lastStopTicket == 88,
        "reset with PENDING must call request_beer_lua_stop with active ticket");
  check(SetScriptOff,
        "reset with PENDING stop must set SetScriptOff = true");
  check(!luaSequenceStage.active && luaSequenceStage.ticket == 0,
        "reset with PENDING stop must still clear luaSequenceStage");

  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(
    begin_body: str,
    request_exit_body: str,
    tick_body: str,
    reset_body: str,
    expect_success: bool,
) -> bool:
    code = (
        HARNESS.replace("@BEGIN_BODY@", begin_body)
        .replace("@REQUEST_EXIT_BODY@", request_exit_body)
        .replace("@TICK_BODY@", tick_body)
        .replace("@RESET_BODY@", reset_body)
    )
    with tempfile.TemporaryDirectory(prefix="samovar-lua-seq-") as temp_dir:
        path = Path(temp_dir)
        cpp = path / "test.cpp"
        binary = path / "test"
        cpp.write_text(code, encoding="utf-8")
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


def main() -> int:
    errors: list[str] = []
    lua_src = strip_cpp_comments((ROOT / "lua.h").read_text(encoding="utf-8"))
    dist_src = strip_cpp_comments((ROOT / "distiller.h").read_text(encoding="utf-8"))
    bk_src = strip_cpp_comments((ROOT / "BK.h").read_text(encoding="utf-8"))

    begin_body = extract_function_body(lua_src, "inline bool lua_sequence_stage_begin")
    request_exit_body = extract_function_body(lua_src, "inline bool lua_sequence_stage_request_exit")
    tick_body = extract_function_body(lua_src, "inline LuaSequenceStageResult lua_sequence_stage_tick")
    reset_body = extract_function_body(lua_src, "inline void lua_sequence_stage_reset()")

    dist_finish_body = extract_function_body(dist_src, "void distiller_finish()")
    bk_finish_body = extract_function_body(bk_src, "void bk_finish()")

    require_ordered_tokens(
        "distiller_finish resets lua_sequence_stage before stop_process",
        dist_finish_body,
        ["#ifdef USE_LUA", "lua_sequence_stage_reset();", "#endif", "stop_process("],
        errors,
    )
    require_ordered_tokens(
        "bk_finish resets lua_sequence_stage before stop_process",
        bk_finish_body,
        ["#ifdef USE_LUA", "lua_sequence_stage_reset();", "#endif", "stop_process("],
        errors,
    )

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    if not compile_and_run(begin_body, request_exit_body, tick_body, reset_body, True):
        return 1

    # Mutation 1: non-APPLIED/non-PENDING stop returns ACTIVE instead of FAILED.
    tick_mutant = tick_body.replace(
        "return LUA_SEQUENCE_STAGE_FAILED;",
        "return LUA_SEQUENCE_STAGE_ACTIVE;",
    )
    if tick_mutant == tick_body:
        print("FAIL: tick FAILED mutation anchor not found", file=sys.stderr)
        return 1
    if not compile_and_run(begin_body, request_exit_body, tick_mutant, reset_body, False):
        print("FAIL: tick FAILED mutation survived", file=sys.stderr)
        return 1

    # Mutation 2: reset skips SetScriptOff = true on PENDING.
    reset_mutant = reset_body.replace("SetScriptOff = true;", "(void)0;", 1)
    if reset_mutant == reset_body:
        print("FAIL: reset PENDING mutation anchor not found", file=sys.stderr)
        return 1
    if not compile_and_run(begin_body, request_exit_body, tick_body, reset_mutant, False):
        print("FAIL: reset PENDING mutation survived", file=sys.stderr)
        return 1

    print("OK: lua_sequence_stage_* behaviour, mutations, and distiller/BK finish reset checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
