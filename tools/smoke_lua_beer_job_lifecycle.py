#!/usr/bin/env python3
"""Production-derived Lua Beer-job readiness, terminal-state and failure checks."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
SIGNATURES = [
    "inline bool lua_chunk_ref_valid(int ref)",
    "inline bool consume_lua_periodic_start_request(bool& accepted)",
    "inline void finish_beer_lua_periodic_result(bool periodicFailed, bool periodicTimedOut)",
    "inline bool request_beer_lua_job(uint32_t& ticket)",
    "inline LuaBeerJobResult beer_lua_job_result(uint32_t ticket)",
    "inline ActuatorCommandResult request_beer_lua_stop(uint32_t ticket)",
]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

using TickType_t = int;
constexpr TickType_t portMAX_DELAY = -1;
constexpr int LUA_NOREF = -2;
constexpr int LUA_REFNIL = -1;

static TickType_t pdMS_TO_TICKS(int value) { return value; }

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  size_t length() const { return value_.length(); }
  void clear() { value_.clear(); }

 private:
  std::string value_;
};

enum LuaBeerJobResult : uint8_t {
  LUA_BEER_JOB_IDLE = 0,
  LUA_BEER_JOB_QUEUED,
  LUA_BEER_JOB_RUNNING,
  LUA_BEER_JOB_SUCCEEDED,
  LUA_BEER_JOB_STOPPED,
  LUA_BEER_JOB_FAILED_INIT,
  LUA_BEER_JOB_FAILED_RUNTIME,
  LUA_BEER_JOB_FAILED_TIMEOUT,
  // [Дефект 2] занятый RUNTIME_STATE на короткий миг чтения/записи - не то же
  // самое, что настоящий сбой job'а.
  LUA_BEER_JOB_LOCK_BUSY,
};

// [Дефект 2] единый результат исполнительной команды (safety_transition.h) -
// используется вместо голого bool, чтобы отличить временную занятость лока
// от настоящей ошибки согласования тикета.
enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

static bool lockAvailable = true;
static TickType_t lastLockTimeout = 0;
bool runtime_state_lock(TickType_t timeout = pdMS_TO_TICKS(50)) {
  lastLockTimeout = timeout;
  return lockAvailable;
}
void runtime_state_unlock(bool) {}

static bool modeSwitchInProgress = false;
bool mode_switch_in_progress() { return modeSwitchInProgress; }

static bool lua_runtime_ready = false;
static bool lua_finished = true;
static bool lua_start_requested = false;
static bool loop_lua_fl = false;
static bool SetScriptOff = false;
static String script2;
static int script2_ref = LUA_NOREF;
static uint32_t lua_beer_job_next_ticket = 0;
static uint32_t lua_beer_job_ticket = 0;
static LuaBeerJobResult lua_beer_job_result = LUA_BEER_JOB_IDLE;

@FUNCTIONS@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  lockAvailable = true;
  lastLockTimeout = 0;
  modeSwitchInProgress = false;
  lua_runtime_ready = true;
  lua_finished = true;
  lua_start_requested = false;
  loop_lua_fl = false;
  SetScriptOff = false;
  script2 = String("beer-stage");
  script2_ref = 17;
  lua_beer_job_next_ticket = 0;
  lua_beer_job_ticket = 0;
  lua_beer_job_result = LUA_BEER_JOB_IDLE;
}

static void test_init_failure_blocks_job() {
  reset_fixture();
  lua_runtime_ready = false;
  uint32_t ticket = 999;
  check(!request_beer_lua_job(ticket), "failed Lua init must reject Beer job");
  check(lua_beer_job_result == LUA_BEER_JOB_FAILED_INIT,
        "failed Lua init must publish FAILED_INIT terminal state");
  check(ticket == 999, "failed Lua init must not issue a ticket");
}

static void test_compile_failure_blocks_job() {
  reset_fixture();
  script2.clear();
  uint32_t ticket = 999;
  check(!request_beer_lua_job(ticket), "empty compiled Beer script must reject job");
  check(lua_beer_job_result == LUA_BEER_JOB_FAILED_INIT,
        "empty compiled Beer script must publish FAILED_INIT");

  reset_fixture();
  script2_ref = LUA_NOREF;
  check(!request_beer_lua_job(ticket), "invalid compiled Beer chunk ref must reject job");
  check(lua_beer_job_result == LUA_BEER_JOB_FAILED_INIT,
        "invalid compiled Beer chunk ref must publish FAILED_INIT");
}

static uint32_t start_running_job() {
  reset_fixture();
  uint32_t ticket = 0;
  check(request_beer_lua_job(ticket), "valid Beer job must be accepted");
  bool accepted = false;
  check(consume_lua_periodic_start_request(accepted) && accepted,
        "accepted Beer job must become periodic work");
  check(lua_beer_job_result == LUA_BEER_JOB_RUNNING,
        "periodic Beer job must publish RUNNING before execution");
  return ticket;
}

static void test_periodic_failures_are_terminal() {
  uint32_t ticket = start_running_job();
  finish_beer_lua_periodic_result(true, false);
  check(beer_lua_job_result(ticket) == LUA_BEER_JOB_FAILED_RUNTIME,
        "periodic runtime error must publish FAILED_RUNTIME terminal state");

  ticket = start_running_job();
  finish_beer_lua_periodic_result(true, true);
  check(beer_lua_job_result(ticket) == LUA_BEER_JOB_FAILED_TIMEOUT,
        "periodic timeout must publish FAILED_TIMEOUT terminal state");
}

static void test_script1_only_failure_reported_as_not_failed_does_not_fail_job() {
  // T18: do_lua_script() (lua.h) раньше делил ОДНУ пару periodicFailed/
  // periodicTimedOut между общим script.lua (script1) и режимным/пивным
  // скриптом (script2) - ошибка в пустяковом script.lua протекала сюда как
  // periodicFailed=true и ошибочно обрывала идущий пивной job. Правильное
  // поведение do_lua_script() - при сбое ТОЛЬКО script1 звать эту функцию с
  // periodicFailed=false (проверено отдельно, на реальном do_lua_script(), в
  // smoke_lua_periodic_failure_stop.py). Здесь фиксируем ответственность
  // finish_beer_lua_periodic_result() за свою половину контракта: получив
  // periodicFailed=false, она обязана публиковать успешный, а не проваленный
  // терминальный статус.
  uint32_t ticket = start_running_job();
  finish_beer_lua_periodic_result(false, false);
  check(beer_lua_job_result(ticket) == LUA_BEER_JOB_SUCCEEDED,
        "periodicFailed=false (e.g. a script1-only failure correctly excluded by do_lua_script()) "
        "must publish SUCCEEDED, not a FAILED_* terminal state");
}

static void test_stop_is_latched_and_terminal() {
  reset_fixture();
  uint32_t ticket = 0;
  check(request_beer_lua_job(ticket), "Beer job setup for stop must succeed");
  check(request_beer_lua_stop(ticket) == ACTUATOR_COMMAND_APPLIED,
        "Beer job stop must latch under production lock");
  // [T30a] Было lastLockTimeout == portMAX_DELAY - request_beer_lua_stop()
  // достижима из loop() через beer.h, поэтому ждать RUNTIME_STATE вечно
  // нельзя; таймаут теперь конечный (дефолт runtime_state_lock()).
  check(lastLockTimeout != portMAX_DELAY,
        "Beer job stop must wait for runtime lock with a bounded timeout, not portMAX_DELAY");
  check(SetScriptOff && !loop_lua_fl && !lua_start_requested,
        "Beer job stop must block queued and future periodic execution");
  check(beer_lua_job_result(ticket) == LUA_BEER_JOB_STOPPED,
        "Beer job stop must publish STOPPED terminal state");
}

// [Дефект 2] Занятый лок - временная помеха, не сбой job'а: caller (beer.h)
// не должен аварийно прекращать варку, а обязан повторить попытку позже.
// Никакие поля job'а (SetScriptOff/loop_lua_fl/lua_start_requested/тикет) не
// должны меняться - job всё ещё RUNNING, повторный опрос не должен спутать
// PENDING с ошибкой.
static void test_stop_lock_busy_is_pending_without_side_effects() {
  uint32_t ticket = start_running_job();
  const bool scriptOffBefore = SetScriptOff;
  const bool loopLuaFlBefore = loop_lua_fl;
  const bool startRequestedBefore = lua_start_requested;
  lockAvailable = false;
  check(request_beer_lua_stop(ticket) == ACTUATOR_COMMAND_PENDING,
        "Beer job stop must report ACTUATOR_COMMAND_PENDING when RUNTIME_STATE is busy, not a failure");
  check(SetScriptOff == scriptOffBefore && loop_lua_fl == loopLuaFlBefore &&
            lua_start_requested == startRequestedBefore,
        "Beer job stop must not touch queued/periodic state while the lock is busy");
  lockAvailable = true;
  check(beer_lua_job_result(ticket) == LUA_BEER_JOB_RUNNING,
        "Beer job must remain RUNNING after a lock-busy stop attempt - not silently aborted");
}

// [Дефект 2] Чужой тикет - настоящая ошибка согласования (не временная
// помеха) - обязана вернуть ACTUATOR_COMMAND_FAILED, а не PENDING (иначе
// caller будет бесконечно повторять заведомо обречённую попытку).
static void test_stop_wrong_ticket_is_failed() {
  reset_fixture();
  uint32_t ticket = 0;
  check(request_beer_lua_job(ticket), "Beer job setup for wrong-ticket stop must succeed");
  check(request_beer_lua_stop(ticket + 1) == ACTUATOR_COMMAND_FAILED,
        "Beer job stop with a foreign ticket must report ACTUATOR_COMMAND_FAILED");
  check(!SetScriptOff && loop_lua_fl && lua_start_requested,
        "Beer job stop with a foreign ticket must not touch the unrelated running job's state");
}

int main() {
  test_init_failure_blocks_job();
  test_compile_failure_blocks_job();
  test_periodic_failures_are_terminal();
  test_script1_only_failure_reported_as_not_failed_does_not_fail_job();
  test_stop_is_latched_and_terminal();
  test_stop_lock_busy_is_pending_without_side_effects();
  test_stop_wrong_ticket_is_failed();
  return failures == 0 ? 0 : 1;
}
'''


def build_harness(source: str) -> str:
    definitions = []
    for signature in SIGNATURES:
        body = extract_function_body(source, signature)
        definitions.append(f"{signature} {{\n{body}\n}}")
    return HARNESS_TEMPLATE.replace("@FUNCTIONS@", "\n\n".join(definitions))


def compile_and_run(harness: str, label: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-lua-beer-job-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "lua_beer_job_test.cpp"
        binary = temp / "lua_beer_job_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
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


def require_mutation(harness: str, old: str, new: str, expected: str) -> bool:
    mutant = harness.replace(old, new, 1)
    if mutant == harness:
        print(f"FAIL: cannot construct mutation for {expected}", file=sys.stderr)
        return False
    code, output = compile_and_run(mutant, expected, False)
    if code == 0 or expected not in output:
        print(f"FAIL: {expected} mutation survived", file=sys.stderr)
        sys.stderr.write(output)
        return False
    return True


def main() -> int:
    lua = (ROOT / "lua.h").read_text(encoding="utf-8")
    errors: list[str] = []
    try:
        init_body = extract_function_body(lua, "void lua_init()")
        load_body = extract_function_body(lua, "bool load_lua_script()")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    require_ordered_tokens(
        "Lua init readiness",
        init_body,
        ["lua_runtime_ready = false;", "lua_boot_init_ready = initOk && watchdogReady;", "load_lua_script();"],
        errors,
    )
    require_ordered_tokens(
        "Lua compile readiness",
        load_body,
        ["lua_compile_chunk_locked", "lua_compile_chunk_locked", "const bool ready = lua_boot_init_ready", "lua_runtime_ready = ready;"],
        errors,
    )
    beer_stop_body = extract_function_body(
        lua, "inline ActuatorCommandResult request_beer_lua_stop(uint32_t ticket)"
    )
    # [T30a] Было runtime_state_lock(portMAX_DELAY) - вызывается из beer.h при
    # смене строки программы, достижимо из loop(). Отказ уже обрабатывался
    # штатно (return false), поэтому таймаут заменён на дефолтный,
    # ограниченный runtime_state_lock() (pdMS_TO_TICKS(50)).
    if "bool locked = runtime_state_lock();" not in beer_stop_body:
        errors.append("Beer Lua stop must wait on runtime_state_lock() with a bounded default timeout")
    if "portMAX_DELAY" in beer_stop_body:
        errors.append(
            "T30a: request_beer_lua_stop() снова ждёт RUNTIME_STATE portMAX_DELAY - "
            "loop() может зависнуть через beer.h при смене строки программы"
        )
    # [Дефект 2] Занятый лок и чужой тикет обязаны различаться - иначе caller
    # (beer.h) не сможет отличить временную помеху от настоящего сбоя.
    if "return ACTUATOR_COMMAND_PENDING;" not in beer_stop_body:
        errors.append(
            "[Дефект 2] request_beer_lua_stop() обязана вернуть "
            "ACTUATOR_COMMAND_PENDING на занятом локе, а не сливать это с реальным сбоем"
        )
    if "return ACTUATOR_COMMAND_FAILED;" not in beer_stop_body:
        errors.append(
            "[Дефект 2] request_beer_lua_stop() обязана вернуть "
            "ACTUATOR_COMMAND_FAILED на чужом тикете (это настоящая ошибка, не помеха)"
        )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    try:
        harness = build_harness(lua)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    code, _ = compile_and_run(harness, "Lua Beer job lifecycle")
    if code:
        return 1
    mutations = [
        (
            "const bool modeScriptReady = lua_runtime_ready && script2.length() > 0 &&",
            "const bool modeScriptReady = true && script2.length() > 0 &&",
            "failed Lua init must reject Beer job",
        ),
        (
            "lua_beer_job_result = LUA_BEER_JOB_STOPPED;",
            "lua_beer_job_result = LUA_BEER_JOB_SUCCEEDED;",
            "Beer job stop must publish STOPPED terminal state",
        ),
        (
            "periodicFailed ? LUA_BEER_JOB_FAILED_RUNTIME : LUA_BEER_JOB_SUCCEEDED;",
            "periodicFailed ? LUA_BEER_JOB_SUCCEEDED : LUA_BEER_JOB_SUCCEEDED;",
            "periodic runtime error must publish FAILED_RUNTIME terminal state",
        ),
        (
            "periodicFailed ? LUA_BEER_JOB_FAILED_RUNTIME : LUA_BEER_JOB_SUCCEEDED;",
            "periodicFailed ? LUA_BEER_JOB_FAILED_RUNTIME : LUA_BEER_JOB_FAILED_RUNTIME;",
            "must publish SUCCEEDED, not a FAILED_* terminal state",
        ),
        # [Дефект 2] МУТАЦИЯ 1: занятый лок снова сливается с реальной ошибкой -
        # тест обязан упасть (caller не сможет отличить помеху от сбоя и
        # аварийно прервёт варку на любой микро-задержке лока).
        (
            "if (!locked) return ACTUATOR_COMMAND_PENDING;",
            "if (!locked) return ACTUATOR_COMMAND_FAILED;",
            "must report ACTUATOR_COMMAND_PENDING when RUNTIME_STATE is busy, not a failure",
        ),
        # [Дефект 2] МУТАЦИЯ 2: чужой тикет становится "временной помехой" -
        # тест обязан упасть (caller будет бесконечно повторять заведомо
        # обречённую попытку остановки чужого/устаревшего job'а).
        (
            "    runtime_state_unlock(true);\n    return ACTUATOR_COMMAND_FAILED;",
            "    runtime_state_unlock(true);\n    return ACTUATOR_COMMAND_PENDING;",
            "must report ACTUATOR_COMMAND_FAILED",
        ),
    ]
    for old, new, expected in mutations:
        if not require_mutation(harness, old, new, expected):
            return 1
    print("Lua Beer job lifecycle mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
