#!/usr/bin/env python3
"""P02: реальные границы пар ожиданий Beer, Suvid и Cheese.

Проверка читает тела прошивки, а не копирует её условия: мутации каждого
принятого входа и каждого исхода должны быть пойманы содержательным assert-ом.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]


def require(name: str, body: str, tokens: list[str], errors: list[str]) -> None:
    require_ordered_tokens(name, body, tokens, errors)


def run_suvid_pair_edges(block: str, expected_success: bool) -> bool:
    """Исполняет извлечённую production-ветку q17 с stateful pair-заглушками."""
    harness = f'''\
#include <cstdint>
#include <cmath>
#define SUVID_HOLD_BAND_C 2.0f
enum {{ WARNING_MSG = 1, NOTIFY_MSG = 2 }};
enum UiWaitReason {{ UI_WAIT_SUVID_HOLD_OUTSIDE_BAND = 17 }};
enum RuntimePairOutcome {{ RUNTIME_PAIR_RESUMED }};
struct Hold {{ bool active; }} suvidHold{{true}};
struct Deviation {{ bool active; bool warningSent; uint32_t sinceMs; }} suvidDeviation{{}};
static uint32_t now = 0;
static int begins = 0, ends = 0;
static bool pairActive = false;
static void runtime_pair_begin(UiWaitReason, const char*, int) {{ if (!pairActive) {{ pairActive = true; ++begins; }} }}
static void runtime_pair_end(UiWaitReason, RuntimePairOutcome, const char*, int) {{ if (pairActive) {{ pairActive = false; ++ends; }} }}
static void SendMsg(const char*, int) {{}}
static void run(float deviation) {{
{block}
}}
int main() {{
  (void)&runtime_pair_begin;
  run(2.1f); if (begins != 1 || !pairActive || ends != 0) return 1;
  now = 61000; run(2.5f); if (begins != 1 || ends != 0) return 2;
  run(0.2f); if (ends != 1 || pairActive) return 3;
  run(2.2f); return begins == 2 && pairActive ? 0 : 4;
}}
'''
    with tempfile.TemporaryDirectory(prefix="samovar-pair-q17-") as temp:
        source, binary = Path(temp) / "pair.cpp", Path(temp) / "pair"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                                  str(source), "-o", str(binary)], capture_output=True, text=True)
        if compiled.returncode:
            print(f"FAIL: q17 harness compile\n{compiled.stderr}", file=sys.stderr)
            return False
        ran = subprocess.run([str(binary)], capture_output=True, text=True)
        return (ran.returncode == 0) == expected_success


def run_beer_hold_edges(block: str, expected_success: bool) -> bool:
    """Исполняет извлечённый q15-gate: invalid sensor не меняет пару или metadata."""
    harness = r'''
#include <cstdio>
enum { WARNING_MSG = 1, NOTIFY_MSG = 2, RUNTIME_PAIR_RESUMED = 0, UI_WAIT_BEER_HOLD_CLOCK_FREEZE = 15 };
#define BEER_TEMP_HYSTERESIS 0.5f
typedef char ProgramType;
struct DSSensor { float avgTemp; bool valid; } sensor;
struct Row { float Temp; } program[1] = {{70}};
static DSSensor* controlSensor = &sensor;
static const char* controlSensorName = "tank";
static unsigned ProgramNum = 0, begintime = 1;
static float temp = 0, tempDelta = 0; static unsigned long nowMs = 100;
static bool beerHoldClockFrozen = false, processCalled = false;
static int begins = 0, ends = 0, metadataUpdates = 0;
static bool sensor_valid(const DSSensor& value) { return value.valid; }
static char current_program_type() { return 'P'; }
static bool process_sensor_failed(const char*, const char*) { processCalled = true; return false; }
static void beer_update_stage_idle(char, float, float, unsigned long) { ++metadataUpdates; }
static void runtime_pair_begin(int, const char*, int) { ++begins; }
static void runtime_pair_end(int, int, const char*, int) { ++ends; }
static void tick() {
@BODY@
}
static bool check(bool value, const char* message) { if (!value) std::fprintf(stderr, "FAIL: %s\n", message); return value; }
int main() {
  sensor = {60, true}; tick();
  if (!check(begins == 1 && ends == 0 && beerHoldClockFrozen && metadataUpdates == 1, "valid cold P must BEGIN q15")) return 1;
  sensor = {75, false}; tick();
  if (!check(processCalled && begins == 1 && ends == 0 && beerHoldClockFrozen && metadataUpdates == 1, "invalid sensor must not change q15 or hold metadata")) return 2;
  sensor = {75, true}; tick();
  return check(ends == 1 && !beerHoldClockFrozen && metadataUpdates == 2, "valid warm P must END q15 as RESUMED") ? 0 : 3;
}
'''.replace("@BODY@", block)
    with tempfile.TemporaryDirectory(prefix="samovar-beer-hold-pair-") as temp:
        root = Path(temp)
        cpp, binary = root / "pair.cpp", root / "pair"
        cpp.write_text(harness, encoding="utf-8")
        build = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)], capture_output=True, text=True)
        if build.returncode:
            print(f"FAIL: beer q15 harness compile\n{build.stderr}", file=sys.stderr)
            return False
        run = subprocess.run([str(binary)], capture_output=True, text=True)
        return (run.returncode == 0) == expected_success


def main() -> int:
    errors: list[str] = []
    try:
        beer = (ROOT / "beer.h").read_text(encoding="utf-8")
        suvid = (ROOT / "suvid.h").read_text(encoding="utf-8")
        cheese = (ROOT / "cheese.h").read_text(encoding="utf-8")
        beer_run = extract_function_body(beer, "void run_beer_program(uint8_t num)")
        beer_tick_start = beer.find("void beer_stage_tick()")
        beer_tick = extract_function_body(beer[beer_tick_start:], "void beer_stage_tick()")
        beer_finish = extract_function_body(beer, "void beer_finish()")
        beer_abort = extract_function_body(beer, "void beer_abort_config_error(const String& reason) {")
        suvid_alarm = extract_function_body(suvid, "inline void check_alarm_suvid()")
        first_hold = suvid_alarm.find("if (suvidHold.active) {")
        suvid_hold_block, _ = extract_braced_block_after(
            suvid_alarm, "if (suvidHold.active)", first_hold + 1)
        cheese_prepare = extract_function_body(cheese, "inline bool cheese_prepare_stage(uint8_t targetProgram)")
        cheese_tick = extract_function_body(cheese, "void cheese_stage_tick()")
        cheese_abort = extract_function_body(cheese, "inline void cheese_abort(const String& reason)")
        cheese_finish = extract_function_body(cheese, "void cheese_finish() {")
        temp_confirm = extract_function_body(cheese, "inline bool cheese_temperature_confirmed(uint32_t nowMs, bool inBand)")
        ph_confirm = extract_function_body(cheese, "inline bool cheese_ph_target_confirmed(uint32_t nowMs, bool reached)")
    except ValueError as exc:
        print(f"FAIL: cannot extract production body: {exc}", file=sys.stderr)
        return 1
    hold_start = beer_tick.find("if (!sensor_valid(*controlSensor)) {")
    hold_end = beer_tick.find("if (beerManualPause &&", hold_start)
    if hold_start < 0 or hold_end < 0:
        print("FAIL: cannot extract Beer q15 validity block", file=sys.stderr)
        return 1
    beer_hold_block = beer_tick[hold_start:hold_end]

    # Beer: q14 stays live through deadline until an actually accepted row change.
    require("Beer q14 accepted confirmation", beer_run, [
        "beerSkipConfirmProgramNum = ProgramNum;",
        "runtime_pair_begin(UI_WAIT_BEER_SKIP_COOL_CONFIRM",
        "return;",
        "beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;",
        "beerSkipConfirmProgramNum = 0xFF;",
    ], errors)
    require("Beer q15 cold hold edges", beer_tick, [
        "if (!sensor_valid(*controlSensor))",
        "process_sensor_failed(\"Пиво\", controlSensorName);",
        "return;",
        "currentType == 'P' && begintime > 0",
        "temp < program[ProgramNum].Temp - tempDelta",
        "runtime_pair_begin(UI_WAIT_BEER_HOLD_CLOCK_FREEZE",
        "runtime_pair_end(UI_WAIT_BEER_HOLD_CLOCK_FREEZE, RUNTIME_PAIR_RESUMED",
    ], errors)
    require("Beer q16 q13 facts", beer_tick, [
        "begintime = millis();",
        "runtime_pair_begin(UI_WAIT_BEER_OPERATOR_WAIT",
        "startval = SAMOVAR_STARTVAL_BEER_WAIT_MALT;",
        "runtime_pair_begin(UI_WAIT_BEER_MALT",
    ], errors)
    require("Beer q23 result", beer_tick, [
        "result == LUA_BEER_JOB_SUCCEEDED",
        "runtime_pair_end(UI_WAIT_LUA_KNOWN, RUNTIME_PAIR_RESUMED",
    ], errors)
    require("Beer q23 accepted job", beer_run, [
        "request_program_lua_job(targetProgram, ticket)",
        "beerLuaStage.ticket = ticket;",
        "runtime_pair_close_mode(SAMOVAR_BEER_MODE, RUNTIME_PAIR_ROW_CHANGE",
        "runtime_pair_begin(UI_WAIT_LUA_KNOWN",
    ], errors)
    require("Beer ends after safe output", beer_finish, [
        "beer_safe_lua_outputs() == ACTUATOR_COMMAND_FAILED",
        "beerPairErrorPending ? RUNTIME_PAIR_ERROR : RUNTIME_PAIR_PROCESS_END",
    ], errors)
    require("Beer error metadata", beer_abort, [
        "beerPairErrorPending = true;",
        "beer_finish();",
    ], errors)

    # Suvid: active is independent of configured duration, including hold=0.
    require("Suvid q17 edges", suvid_alarm, [
        "if (suvidHold.active)",
        "if (deviation > SUVID_HOLD_BAND_C)",
        "if (!suvidDeviation.active)",
        "runtime_pair_begin(UI_WAIT_SUVID_HOLD_OUTSIDE_BAND",
        "if (suvidDeviation.active)",
        "runtime_pair_end(UI_WAIT_SUVID_HOLD_OUTSIDE_BAND, RUNTIME_PAIR_RESUMED",
    ], errors)
    require("Suvid stop outcome", suvid_alarm, [
        "alarm_event || suvidHold.reachTimeoutMsgSent",
        "RUNTIME_PAIR_ERROR",
        "suvidHold.fired ? RUNTIME_PAIR_PROCESS_END : RUNTIME_PAIR_USER_STOP",
        "runtime_pair_close_mode(SAMOVAR_SUVID_MODE, outcome",
    ], errors)

    # Cheese: only actual windows and successful local dose start may begin pairs.
    require("Cheese q19 q20 q23 accepted entries", cheese_prepare, [
        "request_program_lua_job(targetProgram, ticket)",
        "runtime_pair_begin(UI_WAIT_LUA_KNOWN",
        "!cheese_start_local_doser(row)) return false;",
        "row.WType == 'W'",
        "runtime_pair_begin(UI_WAIT_CHEESE_OPERATOR",
        "row.WType == 'D' && row.TempSensor == 2",
        "runtime_pair_begin(UI_WAIT_CHEESE_DOSE",
    ], errors)
    require("Cheese q18 q20 q21 outcomes", cheese_tick, [
        "runtime_pair_end(UI_WAIT_CHEESE_HOLD_CLOCK_FREEZE, RUNTIME_PAIR_RESUMED",
        "runtime_pair_begin(UI_WAIT_CHEESE_HOLD_CLOCK_FREEZE",
        "cheese_local_doser_complete()",
        "runtime_pair_end(UI_WAIT_CHEESE_DOSE, RUNTIME_PAIR_RESUMED",
        "runtime_pair_end(UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM",
    ], errors)
    require("Cheese q21 temperature window", temp_confirm, [
        "if (!inBand)", "temperatureConfirmActive = false;",
        "temperatureConfirmActive = true;",
        "runtime_pair_begin(UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM",
    ], errors)
    require("Cheese q21 pH window", ph_confirm, [
        "if (!reached)", "phReachedActive = false;",
        "phReachedActive = true;",
        "runtime_pair_begin(UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM",
    ], errors)
    require("Cheese error metadata", cheese_abort, ["cheesePairErrorPending = true;", "cheese_finish();"], errors)
    require("Cheese normal finish", cheese_finish, [
        "if (!cheese_apply_safe_outputs(true))",
        "cheesePairErrorPending ? RUNTIME_PAIR_ERROR : RUNTIME_PAIR_PROCESS_END",
    ], errors)

    if not run_suvid_pair_edges(suvid_hold_block, True):
        errors.append("Suvid q17: extracted runtime branch did not preserve pair edges")
    suvid_mutant = suvid_hold_block.replace(
        'runtime_pair_begin(UI_WAIT_SUVID_HOLD_OUTSIDE_BAND,\n'
        '                           "Выдержка приостановлена: температура вне полосы", WARNING_MSG);',
        "(void)0;", 1)
    if suvid_mutant == suvid_hold_block or not run_suvid_pair_edges(suvid_mutant, False):
        errors.append("Suvid q17: accepted-entry mutation survived the stateful harness")

    if not run_beer_hold_edges(beer_hold_block, True):
        errors.append("Beer q15: extracted valid/invalid sensor edges did not preserve pair state")
    beer_hold_mutant = beer_hold_block.replace(
        'process_sensor_failed("Пиво", controlSensorName);\n    return;',
        'process_sensor_failed("Пиво", controlSensorName);', 1)
    if beer_hold_mutant == beer_hold_block or not run_beer_hold_edges(beer_hold_mutant, False):
        errors.append("Beer q15: invalid-sensor early-return mutation survived the stateful harness")

    if errors:
        print("FAIL: P02 kettle runtime-pair contract", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1
    print("OK: P02 Beer/Suvid/Cheese pairs start and end only at runtime facts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
