#!/usr/bin/env python3
"""P02: реальные парные ожидания БК и НБК не подменяются условиями датчиков."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]


def run_nbk_tick(body: str) -> tuple[int, str]:
    source = r'''
#include <cstdint>
#include <cstdio>
#define SAMOVAR_USE_POWER
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum UiWaitReason { UI_WAIT_NBK_TRANSITION = 11, UI_WAIT_NBK_SAFE = 12 };
enum RuntimePairOutcome { RUNTIME_PAIR_RESUMED = 0, RUNTIME_PAIR_ERROR = 4 };
enum ActuatorCommandResult : uint8_t { ACTUATOR_COMMAND_ACCEPTED, ACTUATOR_COMMAND_PENDING, ACTUATOR_COMMAND_APPLIED, ACTUATOR_COMMAND_FAILED };
enum NbkActuatorDeadlineTarget : uint8_t { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };
struct NbkActuatorCommandState {
  bool active; ActuatorCommandResult result; uint64_t generation; float candidateM; float candidateP;
  uint32_t deadline; uint32_t nextDelayMs; uint16_t iteration; NbkActuatorDeadlineTarget deadlineTarget;
  bool commitProgram; uint8_t candidateProgramNum; bool commitKeepsOptimum; bool closeSafeWaitPair; bool closeTransitionPair;
};
static NbkActuatorCommandState nbkActuatorCommand = {};
static bool PowerOn = true;
static ActuatorCommandResult powerResult = ACTUATOR_COMMAND_APPLIED;
static ActuatorCommandResult speedResult = ACTUATOR_COMMAND_APPLIED;
static int safeWaitCalls = 0, safePairEndCalls = 0, transitionPairEndCalls = 0, transitionErrors = 0;
static float nbk_M = 0, nbk_Mo = 0, nbk_Po = 0, nbk_Po_ceiling = 0;
static uint8_t nbkUiPowerSource = 0, nbkUiFeedSource = 0, ProgramNum = 0;
static bool nbkUiPowerApplied = false, nbkUiFeedApplied = false, nbk_safe_waiting = false, nbk_safe_wait_feed_stopped = false, nbk_pause_overflow_repeat_latched = false, nbk_work_in_pause = false, nbk_overflow_happened = false;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
static uint16_t nbk_opt_iter = 0;
static uint32_t nbk_opt_next_time = 0, nbk_work_next_time = 0;
static uint8_t nbk_high_temp_ticks = 0, nbk_high_pressure_ticks = 0, nbk_work_pause_stage = 0;
static uint32_t millis() { return 10; }
static bool safety_deadline_expired(uint32_t, uint32_t) { return false; }
static bool power_transition_start_pending() { return false; }
static ActuatorCommandResult nbk_set_power(float, uint64_t* generation) { *generation = 1; return powerResult; }
static ActuatorCommandResult current_power_command_status(uint64_t) { return powerResult; }
static ActuatorCommandResult SetSpeed(float) { return speedResult; }
static uint32_t safety_deadline_after(uint32_t, uint32_t delay) { return delay; }
static void nbk_enter_safe_wait(const char*) { safeWaitCalls++; nbk_safe_waiting = true; }
static void runtime_pair_end(UiWaitReason reason, RuntimePairOutcome outcome, const char*, MESSAGE_TYPE) { if (reason == UI_WAIT_NBK_SAFE) ++safePairEndCalls; else { ++transitionPairEndCalls; if (outcome == RUNTIME_PAIR_ERROR) ++transitionErrors; } }
static void nbk_reset_actuator_command() { nbkActuatorCommand = {}; }
static void tick() {
@BODY@
}
static int check(bool condition, const char* message) {
  if (condition) return 0;
  std::fprintf(stderr, "FAIL: %s\n", message);
  return 1;
}
static void reset(ActuatorCommandResult result, bool transitionPair) {
  nbkActuatorCommand = {};
  nbkActuatorCommand.active = true;
  nbkActuatorCommand.result = ACTUATOR_COMMAND_ACCEPTED;
  nbkActuatorCommand.candidateM = 700;
  nbkActuatorCommand.candidateP = 4;
  nbkActuatorCommand.closeSafeWaitPair = true;
  nbkActuatorCommand.closeTransitionPair = transitionPair;
  PowerOn = true; powerResult = result; speedResult = ACTUATOR_COMMAND_APPLIED;
  safeWaitCalls = safePairEndCalls = transitionPairEndCalls = transitionErrors = 0;
}
int main() {
  reset(ACTUATOR_COMMAND_APPLIED, false); tick();
  if (check(safePairEndCalls == 1 && transitionPairEndCalls == 0 && safeWaitCalls == 0, "APPLIED должен закрыть q12 как RESUMED")) return 1;
  reset(ACTUATOR_COMMAND_PENDING, false); tick();
  if (check(safePairEndCalls == 0 && transitionPairEndCalls == 0 && safeWaitCalls == 0, "PENDING не должен закрывать q12")) return 2;
  reset(ACTUATOR_COMMAND_FAILED, false); tick();
  if (check(safePairEndCalls == 0 && transitionPairEndCalls == 0 && safeWaitCalls == 1, "FAILED обязан остаться в safe wait без RESUMED")) return 3;
  reset(ACTUATOR_COMMAND_APPLIED, true); tick();
  if (check(transitionPairEndCalls == 1 && safeWaitCalls == 0, "APPLIED power and feed must close q11 as RESUMED")) return 4;
  reset(ACTUATOR_COMMAND_PENDING, true); tick();
  if (check(transitionPairEndCalls == 0 && safeWaitCalls == 0, "PENDING must not close q11")) return 5;
  reset(ACTUATOR_COMMAND_FAILED, true); tick();
  if (check(transitionPairEndCalls == 0 && safeWaitCalls == 1, "FAILED q11 must enter safe wait without RESUMED")) return 6;
  return 0;
}
'''.replace("@BODY@", body)
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-pair-") as temp:
        path = Path(temp)
        cpp, binary = path / "test.cpp", path / "test"
        cpp.write_text(source, encoding="utf-8")
        build = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)], capture_output=True, text=True)
        if build.returncode:
            return build.returncode, build.stderr
        run = subprocess.run([str(binary)], capture_output=True, text=True)
        return run.returncode, run.stdout + run.stderr


def require_order(body: str, tokens: list[str], label: str) -> bool:
    position = -1
    for token in tokens:
        found = body.find(token, position + 1)
        if found < 0:
            print(f"FAIL: {label}: нет ожидаемого факта {token!r}")
            return False
        position = found
    return True


def run_nbk_collector(block: str) -> tuple[int, str]:
    source = r'''
#include <cstdint>
#include <cstdio>
enum { SAMOVAR_NBK_MODE = 4, UI_WAIT_NBK_TRANSITION = 11, UI_WAIT_NBK_SAFE = 12,
       UI_CONTINUATION_ACTUATOR = 3 };
struct Wait { uint8_t reason; uint8_t continuation; };
struct UiStateDescriptor { Wait waits[2]; uint8_t waitCount; };
struct NbkActuatorCommandState { bool active; bool closeTransitionPair; bool closeSafeWaitPair; } nbkActuatorCommand;
static bool nbk_safe_waiting = false, transition = false;
static bool nbk_transition_active() { return transition; }
static UiStateDescriptor value = {};
static void collect() {
@BODY@
}
static bool check(bool value, const char* message) { if (!value) std::fprintf(stderr, "FAIL: %s\n", message); return value; }
static void reset() { value = {}; nbkActuatorCommand = {}; nbk_safe_waiting = transition = false; }
int main() {
  reset(); nbkActuatorCommand = {true, true, false}; collect();
  if (!check(value.waitCount == 1 && value.waits[0].reason == UI_WAIT_NBK_TRANSITION && value.waits[0].continuation == UI_CONTINUATION_ACTUATOR, "pending q11 marker must publish actuator wait")) return 1;
  reset(); nbkActuatorCommand = {true, false, true}; collect();
  if (!check(value.waitCount == 1 && value.waits[0].reason == UI_WAIT_NBK_SAFE && value.waits[0].continuation == UI_CONTINUATION_ACTUATOR, "pending q12 marker must publish actuator wait")) return 2;
  reset(); transition = true; collect();
  return check(value.waitCount == 1 && value.waits[0].reason == UI_WAIT_NBK_TRANSITION, "active heat transition must retain q11 wait") ? 0 : 3;
}
'''.replace("@BODY@", block)
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-collector-") as temp:
        root = Path(temp)
        cpp, binary = root / "collector.cpp", root / "collector"
        cpp.write_text(source, encoding="utf-8")
        build = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)], capture_output=True, text=True)
        if build.returncode:
            return build.returncode, build.stderr
        run = subprocess.run([str(binary)], capture_output=True, text=True)
        return run.returncode, run.stdout + run.stderr


def main() -> int:
    bk = (ROOT / "BK.h").read_text(encoding="utf-8")
    nbk = (ROOT / "nbk.h").read_text(encoding="utf-8")
    dist = (ROOT / "distiller.h").read_text(encoding="utf-8")
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")

    try:
        bk_apply = extract_function_body(bk, "static void bk_apply_work_power()")
        bk_proc = extract_function_body(bk, "void bk_proc()")
        bk_finish = extract_function_body(bk, "void bk_finish()")
        safe_wait = extract_function_body(nbk, "inline void nbk_enter_safe_wait(const String& reason)")
        resume = extract_function_body(nbk, "inline void nbk_resume_work_after_safe_wait()")
        run = extract_function_body(nbk, "void run_nbk_program(uint8_t num, bool workConfirmed, bool optimumEntry)")
        transition = extract_function_body(nbk, "inline void tick_nbk_transition()")
        actuator_tick = extract_function_body(nbk, "inline void tick_nbk_actuator_command()")
        finish = extract_function_body(nbk, "inline void nbk_finish()")
        emergency_finish = extract_function_body(nbk, "inline void nbk_emergency_finish()")
        collector_nbk, _ = extract_braced_block_after(
            samovar, "if (mode == SAMOVAR_NBK_MODE && PowerOn)")
    except ValueError as exc:
        print(f"FAIL: source extraction: {exc}")
        return 1

    checks = [
        require_order(
            bk_proc,
            ["bk_work_power_pending = true;", "runtime_pair_begin(", "UI_WAIT_BK_WORK_POWER"],
            "BK q10 begin after accepted work-power wait"),
        require_order(
            bk_apply,
            ["bk_work_power_pending = false;", "runtime_pair_end(", "RUNTIME_PAIR_RESUMED"],
            "BK q10 end after applied work power"),
        require_order(
            bk_finish,
            ["runtime_pair_close_mode(", "RUNTIME_PAIR_PROCESS_END", "ProgramNum = 0;"],
            "BK finish closes active pair before state clear"),
        require_order(
            safe_wait,
            ["set_power(false, false);", "nbk_safe_waiting = true;", "UI_WAIT_NBK_TRANSITION", "RUNTIME_PAIR_ERROR", "runtime_pair_begin(", "UI_WAIT_NBK_SAFE"],
            "NBK q11 failure closes ERROR before q12 safe wait begins"),
        require_order(
            resume,
            ["nbk_set_stream_clean();", "nbk_safe_waiting = false;", "nbk_schedule_actuator_command(", "true))"],
            "NBK q12 resume marks the existing command, without a premature END"),
        require_order(
            run,
            ["UI_WAIT_NBK_SAFE", "RUNTIME_PAIR_USER_STOP", "nbk_finish();"],
            "NBK q12 operator stop is distinct from process end"),
        require_order(
            run,
            ["safety_transition_begin(", "runtime_pair_begin(", "UI_WAIT_NBK_TRANSITION"],
            "NBK q11 begins at real heat transition"),
        require_order(
            transition,
            ["set_power(false, false);", "runtime_pair_end(", "RUNTIME_PAIR_ERROR", "ProgramNum = 0;"],
            "NBK q11 error follows heater off and precedes state clear"),
        require_order(
            transition,
            ["nbk_schedule_actuator_command(", "true))", "safety_transition_cancel("],
            "NBK q11 only cancels transition after accepted actuator command"),
        require_order(
            finish,
            ["set_power(false, false);", "runtime_pair_close_mode(", "RUNTIME_PAIR_PROCESS_END", "cancel_nbk_transition();"],
            "NBK normal finish closes before transition/state clear"),
        require_order(
            emergency_finish,
            ["set_power(false, false);", "runtime_pair_close_mode(", "RUNTIME_PAIR_ERROR", "cancel_nbk_transition();"],
            "NBK emergency turns heater off before ERROR close"),
    ]
    if not all(checks):
        return 1

    tick_result, tick_output = run_nbk_tick(actuator_tick)
    if tick_result:
        print("FAIL: NBK actuator pair harness:\n" + tick_output)
        return 1
    early_end = '''if (nbkActuatorCommand.result == ACTUATOR_COMMAND_PENDING) return;'''
    mutant = actuator_tick.replace(
        early_end,
        '''if (nbkActuatorCommand.closeTransitionPair) {
    runtime_pair_end(UI_WAIT_NBK_TRANSITION, RUNTIME_PAIR_RESUMED, "early", NOTIFY_MSG);
  }
  if (nbkActuatorCommand.result == ACTUATOR_COMMAND_PENDING) return;''',
        1)
    if mutant == actuator_tick:
        print("FAIL: не удалось построить мутацию преждевременного q11 RESUMED")
        return 1
    mutant_result, mutant_output = run_nbk_tick(mutant)
    meaningful_failures = (
        "APPLIED power and feed must close q11 as RESUMED",
        "PENDING must not close q11",
    )
    if mutant_result == 0 or not any(text in mutant_output for text in meaningful_failures):
        print("FAIL: мутация раннего q11 RESUMED не дала смысловой assert:\n" + mutant_output)
        return 1
    print("NBK q11 early-RESUMED mutation rejected by the PENDING assert")

    collector_waits = collector_nbk[:collector_nbk.find("if (currentType == 'H')")]
    collector_result, collector_output = run_nbk_collector(collector_waits)
    if collector_result:
        print("FAIL: NBK collector harness:\n" + collector_output)
        return 1
    collector_mutant = collector_waits.replace(
        "nbkActuatorCommand.closeTransitionPair", "false", 1)
    mutant_result, mutant_output = run_nbk_collector(collector_mutant)
    if mutant_result == 0 or "pending q11 marker must publish actuator wait" not in mutant_output:
        print("FAIL: pending q11 collector mutation survived semantic assert:\n" + mutant_output)
        return 1
    print("NBK pending collector marker mutation rejected")

    # Два разных реальных факта P01 намеренно не получают пары: это наблюдения,
    # а не самостоятельные блокирующие состояния. Мутации должны падать по тексту.
    forbidden = ["UI_WAIT_DIST_HEATING", "UI_WAIT_DIST_INVALID_ALCOHOL", "UI_WAIT_BK_BOIL"]
    if any(token in dist or token in bk for token in forbidden):
        print("FAIL: датчиковое условие DIST/BK ошибочно стало парным ожиданием")
        return 1
    print("ui column pair hooks smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
