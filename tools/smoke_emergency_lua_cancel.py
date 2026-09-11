#!/usr/bin/env python3
"""F02: авария отменяет ожидающий и уже выполняемый Lua без запрета GPIO вообще."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

using TickType_t = int;
constexpr int portTICK_PERIOD_MS = 1;
#define pdMS_TO_TICKS(value) (value)
#define USE_LUA 1

struct lua_State {};
using String = std::string;
static uint32_t lua_next_execution_ticket = 0;
static uint32_t lua_active_execution_ticket = 0;
static uint32_t lua_cancelled_execution_ticket = 0;
static bool lua_emergency_stop_requested = false;
static bool runtimeLockAvailable = true;
static bool pendingLockAvailable = true;
static volatile bool pending_emergency_actions_cancel = false;
static bool SetScriptOff = false;
static bool loop_lua_fl = false;
static bool lua_start_requested = false;
static String lua_job_script;
enum LuaJobType { LUA_JOB_NONE, LUA_JOB_INLINE };
static LuaJobType lua_job_type = LUA_JOB_NONE;
static bool lua_program_job = false;
static int32_t luaDelayArgument = 100;
static int lastDelay = -1;
static int delayCalls = 0;
static int luaErrors = 0;
static std::string lastError;

static bool mode_switch_in_progress() { return false; }
static bool runtime_state_lock(int) { return runtimeLockAvailable; }
static void runtime_state_unlock(bool) {}
struct PendingCommandLockGuard {
  operator bool() const { return pendingLockAvailable; }
};
static bool cancel_queued_i2c_operations_locked(bool& cancelled) {
  cancelled = false;
  return true;
}
static bool discard_samovar_commands() { return true; }
static void discard_pending_lua_commands_locked() {}
static int32_t lua_check_index_arg(lua_State*, int, int, int, const char*) {
  return luaDelayArgument;
}
static void vTaskDelay(int ticks) {
  lastDelay = ticks;
  delayCalls++;
  if (ticks > 0) lua_emergency_stop_requested = true;
}
static int luaL_error(lua_State*, const char* text) {
  luaErrors++;
  lastError = text;
  return -1;
}

@FUNCTIONS@

@TICK@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  lua_next_execution_ticket = 0;
  lua_active_execution_ticket = 0;
  lua_cancelled_execution_ticket = 0;
  lua_emergency_stop_requested = false;
  runtimeLockAvailable = true;
  pendingLockAvailable = true;
  pending_emergency_actions_cancel = false;
  SetScriptOff = false;
  loop_lua_fl = false;
  lua_start_requested = false;
  lua_job_script.clear();
  lua_job_type = LUA_JOB_INLINE;
  lua_program_job = true;
  luaDelayArgument = 100;
  lastDelay = -1;
  delayCalls = 0;
  luaErrors = 0;
  lastError.clear();
}

static void test_native_side_effect_gate_rejects_after_emergency() {
  reset_fixture();
  check(lua_claim_execution_locked(), "old Lua run must receive a ticket before execution");
  check(lua_state_mutation_allowed(), "normal Lua side effect must stay allowed");
  check(request_lua_emergency_stop(), "emergency must cancel the claimed old Lua run");
  check(!lua_state_mutation_allowed(),
        "emergency must reject a next native state-changing wrapper");
  check(lua_reject_state_mutation(nullptr) == -1 && luaErrors == 1 &&
            lastError == "Lua execution cancelled by emergency",
        "emergency rejection must abort the old Lua chunk explicitly");
}

static void test_new_run_does_not_inherit_old_cancellation() {
  reset_fixture();
  check(lua_claim_execution_locked(), "old Lua run must receive a ticket");
  const uint32_t oldTicket = lua_active_execution_ticket;
  check(request_lua_emergency_stop(), "emergency cancellation must complete");
  check(lua_cancelled_execution_ticket == oldTicket,
        "emergency must mark the active old ticket, not a global Lua ban");
  lua_finish_execution_locked();
  check(lua_claim_execution_locked() && lua_active_execution_ticket != oldTicket,
        "new explicit Lua run must receive a distinct ticket");
  check(lua_state_mutation_allowed(),
        "new explicit Lua run must be allowed after old cancellation");
}

static void test_lock_busy_immediately_blocks_claimed_old_run() {
  reset_fixture();
  check(lua_claim_execution_locked(), "old Lua run must receive a ticket");
  runtimeLockAvailable = false;
  check(!request_lua_emergency_stop(), "lock-busy cancellation must request a retry");
  check(!lua_state_mutation_allowed(),
        "lock-busy emergency must immediately block the claimed old Lua run");
  runtimeLockAvailable = true;
  check(request_lua_emergency_stop(), "retry must mark the old active ticket");
}

static void test_pending_lock_busy_still_cancels_claimed_old_run() {
  reset_fixture();
  check(lua_claim_execution_locked(), "old Lua run must receive a ticket");
  pending_emergency_actions_cancel = true;
  pendingLockAvailable = false;
  tick_pending_emergency_actions();
  check(!lua_state_mutation_allowed(),
        "pending-lock busy emergency must immediately block the claimed old Lua run");
  check(pending_emergency_actions_cancel,
        "pending-lock busy cancellation must stay queued for cleanup retry");
}

static void test_delay_detects_emergency_before_next_instruction() {
  reset_fixture();
  check(lua_claim_execution_locked(), "Lua delay must belong to a claimed run");
  check(lua_wrapper_delay(nullptr) == -1 && lastDelay == 10 && delayCalls == 1 && luaErrors == 1 &&
            lastError == "Lua execution cancelled by emergency",
        "Lua delay must abort when emergency arrives while it sleeps");
}

static void test_zero_delay_keeps_scheduler_yield() {
  reset_fixture();
  check(lua_claim_execution_locked(), "Lua delay must belong to a claimed run");
  luaDelayArgument = 0;
  check(lua_wrapper_delay(nullptr) == 0 && lastDelay == 0 && delayCalls == 1 && luaErrors == 0,
        "Lua delay(0) must yield once without losing its successful result");
}

int main() {
  test_native_side_effect_gate_rejects_after_emergency();
  test_new_run_does_not_inherit_old_cancellation();
  test_lock_busy_immediately_blocks_claimed_old_run();
  test_pending_lock_busy_still_cancels_claimed_old_run();
  test_delay_detects_emergency_before_next_instruction();
  test_zero_delay_keeps_scheduler_yield();
  return failures == 0 ? 0 : 1;
}
'''

PENDING_HARNESS = r'''
#include <iostream>
#include <string>

using String = std::string;
static bool pending_lua_start_flag = false;
static bool pending_lua_file_flag = false;
static bool pending_lua_flag = false;
static String pending_lua_file;
static String pending_lua_str;

static void discard_pending_lua_commands_locked() {
@BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  pending_lua_start_flag = true;
  pending_lua_file_flag = true;
  pending_lua_flag = true;
  pending_lua_file = "old.lua";
  pending_lua_str = "setPumpPwm(1)";
  discard_pending_lua_commands_locked();
  check(!pending_lua_start_flag && !pending_lua_file_flag && !pending_lua_flag,
        "emergency must discard every accepted pending Lua command");
  check(pending_lua_file.empty() && pending_lua_str.empty(),
        "emergency must discard pending Lua payloads with their flags");

  discard_pending_lua_commands_locked();
  check(!pending_lua_start_flag && !pending_lua_file_flag && !pending_lua_flag &&
            pending_lua_file.empty() && pending_lua_str.empty(),
        "discarding an already-idle Lua bridge must stay idle");
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(source: str, label: str, show_output: bool = True) -> tuple[int, str]:
  with tempfile.TemporaryDirectory(prefix="samovar-emergency-lua-") as temp_dir:
    temp = Path(temp_dir)
    path = temp / "emergency_lua.cpp"
    binary = temp / "emergency_lua"
    path.write_text(source, encoding="utf-8")
    compiled = subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(binary)],
        capture_output=True, text=True, check=False)
    if compiled.returncode:
      output = compiled.stdout + compiled.stderr
      if show_output:
        sys.stderr.write(f"[{label}] compile failed:\n{output}")
      return compiled.returncode, output
    ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
    output = ran.stdout + ran.stderr
    if show_output:
      sys.stdout.write(ran.stdout)
      sys.stderr.write(ran.stderr)
    return ran.returncode, output


def main() -> int:
  lua = (ROOT / "lua.h").read_text(encoding="utf-8")
  errors: list[str] = []
  signatures = (
      "inline bool lua_active_execution_cancelled()",
      "inline bool lua_state_mutation_allowed()",
      "inline int lua_reject_state_mutation(lua_State* lua_state)",
      "inline bool lua_claim_execution_locked()",
      "inline void lua_finish_execution_locked()",
      "inline bool request_lua_emergency_stop()",
      "static int lua_wrapper_delay(lua_State *lua_state)",
  )
  try:
    functions = "\n\n".join(
        f"{signature} {{\n{extract_function_body(lua, signature)}\n}}"
        for signature in signatures)
    hook = extract_function_body(lua, "static void lua_timeout_hook(lua_State* L, lua_Debug*)")
    pump = extract_function_body(lua, "static int lua_wrapper_set_pump_pwm(lua_State *lua_state)")
    emergency_stop = extract_function_body(lua, "inline bool request_lua_emergency_stop()")
    emergency_tick = extract_function_body(
        (ROOT / "Samovar.ino").read_text(encoding="utf-8"),
        "inline void tick_pending_emergency_actions()")
  except ValueError as error:
    print(f"FAIL: {error}", file=sys.stderr)
    return 1

  require_ordered_tokens(
      "Lua hook aborts an active chunk after emergency",
      hook,
      ["lua_active_execution_cancelled()", 'luaL_error(L, "Lua execution cancelled by emergency")'],
      errors)
  require_ordered_tokens(
      "setPumpPwm uses the common emergency gate before output",
      pump,
      ["lua_state_mutation_allowed()", "set_pump_pwm("], errors)
  require_ordered_tokens(
      "emergency Lua cancellation drops queued and periodic work",
      emergency_stop,
      ["lua_emergency_stop_requested = true;", "lua_cancelled_execution_ticket = activeTicket;",
       "SetScriptOff = true;", "loop_lua_fl = false;", "lua_start_requested = false;",
       "lua_job_type = LUA_JOB_NONE;", "lua_program_job = false;"], errors)
  require_ordered_tokens(
      "pending-lock busy emergency first cancels active Lua",
      emergency_tick,
      ["request_lua_emergency_stop();", "PendingCommandLockGuard guard;", "if (!guard) return;"],
      errors)
  if errors:
    for error in errors:
      print(f"FAIL: {error}", file=sys.stderr)
    return 1

  harness = (HARNESS.replace("@FUNCTIONS@", functions)
                    .replace("@TICK@", "inline void tick_pending_emergency_actions() {\n" + emergency_tick + "\n}"))
  code, _ = compile_and_run(harness, "emergency Lua cancellation")
  if code:
    return 1
  mutations = (
      ("return activeTicket != 0 &&\n         (lua_emergency_stop_requested ||\n          lua_cancelled_execution_ticket == activeTicket);",
       "return lua_emergency_stop_requested ||\n         (activeTicket != 0 && lua_cancelled_execution_ticket == 0);",
       "next native state-changing wrapper"),
      ('      if (lua_active_execution_cancelled()) {\n        return luaL_error(lua_state, "Lua execution cancelled by emergency");\n      }\n    }\n  }\n#endif',
       "    }\n  }\n#endif", "Lua delay must abort"),
  )
  for old, new, expected in mutations:
    mutant = harness.replace(old, new, 1)
    if mutant == harness:
      print(f"FAIL: cannot construct mutation for {expected}", file=sys.stderr)
      return 1
    code, output = compile_and_run(mutant, expected, False)
    if code == 0 or expected not in output:
      print(f"FAIL: mutation survived: {expected}", file=sys.stderr)
      sys.stderr.write(output)
      return 1
  tick_mutant = harness.replace(
      "  const bool luaCancelled = request_lua_emergency_stop();\n",
      "  const bool luaCancelled = true;\n", 1)
  if tick_mutant == harness:
    print("FAIL: cannot construct mutation for pending-lock busy Lua cancellation", file=sys.stderr)
    return 1
  code, output = compile_and_run(tick_mutant, "pending-lock busy Lua cancellation", False)
  if code == 0 or "pending-lock busy emergency" not in output:
    print("FAIL: mutation survived: pending-lock busy Lua cancellation", file=sys.stderr)
    sys.stderr.write(output)
    return 1
  zero_delay_mutant = harness.replace("    vTaskDelay(0);\n", "    /* mutation */\n", 1)
  if zero_delay_mutant == harness:
    print("FAIL: cannot construct mutation for Lua delay(0) scheduler yield", file=sys.stderr)
    return 1
  code, output = compile_and_run(zero_delay_mutant, "Lua delay(0) scheduler yield", False)
  if code == 0 or "Lua delay(0) must yield once" not in output:
    print("FAIL: mutation survived: Lua delay(0) scheduler yield", file=sys.stderr)
    sys.stderr.write(output)
    return 1
  try:
    pending_body = extract_function_body(
        (ROOT / "Samovar.ino").read_text(encoding="utf-8"),
        "static void discard_pending_lua_commands_locked()")
  except ValueError as error:
    print(f"FAIL: {error}", file=sys.stderr)
    return 1
  pending_harness = PENDING_HARNESS.replace("@BODY@", pending_body)
  code, _ = compile_and_run(pending_harness, "pending Lua bridge cancellation")
  if code:
    return 1
  mutant = pending_harness.replace("\n  pending_lua_flag = false;\n", "\n  /* mutation */\n", 1)
  code, output = compile_and_run(mutant, "pending Lua bridge cancellation mutation", False)
  if code == 0 or "accepted pending Lua command" not in output:
    print("FAIL: mutation survived: pending Lua bridge cancellation", file=sys.stderr)
    sys.stderr.write(output)
    return 1
  print("emergency Lua cancellation smoke passed; mutations were rejected")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
