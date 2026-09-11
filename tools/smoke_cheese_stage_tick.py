#!/usr/bin/env python3
"""Stateful execution of the extracted universal Cheese stage dispatcher."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cheese.h").read_text(encoding="utf-8")


def extracted(signature: str) -> str:
    return extract_function_body(SOURCE, signature, strip_comments=False)


HARNESS = r'''
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
using std::isfinite;
using std::min;
#define USE_LUA
#define CHEESE_TEMPERATURE_DELTA 0.3f
#define CHEESE_TEMPERATURE_CONFIRM_MS 10000UL
#define CHEESE_PH_CONFIRM_MS 30000UL
#define CHEESE_PH_INVALID_MS 10000UL
typedef char ProgramType;
enum UiWaitReason { UI_WAIT_CHEESE_HOLD_CLOCK_FREEZE=18, UI_WAIT_CHEESE_DOSE=20,
                    UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM=21,
                    UI_WAIT_LUA_KNOWN=23 };
enum RuntimePairOutcome { RUNTIME_PAIR_RESUMED, RUNTIME_PAIR_ROW_CHANGE,
                          RUNTIME_PAIR_USER_STOP, RUNTIME_PAIR_PROCESS_END,
                          RUNTIME_PAIR_ERROR };
enum { ALARM_MSG=0, WARNING_MSG=1, NOTIFY_MSG=2 };
static void runtime_pair_begin(UiWaitReason, const char*, int) {}
static void runtime_pair_end(UiWaitReason, RuntimePairOutcome, const char*, int) {}
enum CheeseStageKind : uint8_t { CHEESE_STAGE_INVALID=0, CHEESE_STAGE_HEAT, CHEESE_STAGE_HOLD, CHEESE_STAGE_COOL, CHEESE_STAGE_MIX, CHEESE_STAGE_DOSE, CHEESE_STAGE_PH, CHEESE_STAGE_WAIT, CHEESE_STAGE_DRAIN, CHEESE_STAGE_LUA };
struct WProgram { ProgramType WType; float Temp; float Time; float Param; uint8_t TempSensor; };
struct DSSensor { float avgTemp; } sensor;
struct CheeseRuntimeState { uint32_t enteredMs,lastTickMs,temperatureConfirmSinceMs,holdAccumulatedMs,mixerDeadlineMs,phReachedSinceMs,phInvalidSinceMs; float heatStartSetpoint; uint8_t mixerDevice; bool mixerRunning,mixerOneShotComplete,doserStarted,doserCompleted,drainOpen,temperatureConfirmActive,phReachedActive,phInvalidActive; } cheeseRuntime = {};
enum CheeseLuaStagePhase : uint8_t { CHEESE_LUA_STAGE_IDLE=0, CHEESE_LUA_STAGE_ENTER_QUEUED, CHEESE_LUA_STAGE_RUNNING, CHEESE_LUA_STAGE_EXIT_REQUESTED, CHEESE_LUA_STAGE_EXIT_QUEUED };
struct CheeseLuaStageState { CheeseLuaStagePhase phase; uint32_t ticket; uint8_t nextProgram; } cheeseLuaStage = {CHEESE_LUA_STAGE_IDLE, 0, 20};
enum LuaBeerJobResult : uint8_t { LUA_BEER_JOB_LOCK_BUSY, LUA_BEER_JOB_QUEUED, LUA_BEER_JOB_RUNNING, LUA_BEER_JOB_SUCCEEDED, LUA_BEER_JOB_FAILED };
static WProgram program[20]; static uint8_t ProgramNum=0, ProgramLen=1; static const uint8_t PROGRAM_END=20;
static uint32_t fakeMs=0; uint32_t millis() { return fakeMs; }
static bool PowerOn=true, cheeseFinishPending=false, sensorOk=true, mixerOk=true, coolingOk=true, localDone=false, phOk=true, luaExitConfirmed=true, prepareOk=true;
static float cheesePhValue=7.0f; static int transitions=0, aborts=0, heaterCalls=0, coolingCalls=0, preparedProgram=-1;
static LuaBeerJobResult luaResult=LUA_BEER_JOB_RUNNING;
inline CheeseStageKind cheese_stage_kind(ProgramType type) { @KIND@ }
inline bool cheese_time_elapsed(uint32_t nowMs, uint32_t startedMs, float minutes) { @ELAPSED@ }
inline float cheese_stage_timeout_minutes(const WProgram& row) { @TIMEOUT@ }
inline bool cheese_in_temperature_band(float temperature, float target) { @BAND@ }
inline bool cheese_temperature_confirmed(uint32_t nowMs, bool inBand) { @TEMP_CONFIRM@ }
inline bool cheese_ph_target_confirmed(uint32_t nowMs, bool reached) { @PH_CONFIRM@ }
inline bool cheese_ph_invalid_too_long(uint32_t nowMs, bool valid) { @PH_INVALID@ }
bool beer_control_sensor(uint8_t, const DSSensor*& out, const char*&) { out=&sensor; return sensorOk; }
bool sensor_valid(const DSSensor&) { return sensorOk; }
bool process_sensor_failed(const char*, const char*) { return false; }
bool cheese_mixer_tick(const WProgram&, uint32_t) { return mixerOk; }
bool cheese_set_cooling_outputs(bool, bool) { ++coolingCalls; return coolingOk; }
bool cheese_local_doser_complete() { return cheeseRuntime.doserStarted && localDone; }
void stepper_safe_stop() {}
void setHeaterPosition(bool) { ++heaterCalls; }
void set_heater_state(float, float) { ++heaterCalls; }
void cheese_ph_tick() {}
bool cheese_ph_valid() { return phOk; }
void cheese_abort(const char*) { ++aborts; }
void run_cheese_program(uint8_t target) { ++transitions; ProgramNum = target; }
bool cheese_finish_lua_exit() { return luaExitConfirmed; }
bool cheese_prepare_stage(uint8_t target) { preparedProgram = target; return prepareOk; }
LuaBeerJobResult beer_lua_job_result(uint32_t) { return luaResult; }
void cheese_finish() { ++aborts; }
inline bool cheese_lua_stage_tick(uint32_t nowMs, const WProgram& row) { @LUA_TICK@ }
void cheese_stage_tick() { @TICK@ }
static int failures=0; static void check(bool ok, const char* text) { if (!ok) { std::cerr << "FAIL: " << text << '\n'; ++failures; } }
static void reset(ProgramType type) { program[0]={type,20.0f,100.0f,1.0f,0}; ProgramNum=0; ProgramLen=1; PowerOn=true; cheeseFinishPending=false; sensorOk=true; mixerOk=true; coolingOk=true; localDone=false; phOk=true; luaExitConfirmed=true; prepareOk=true; luaResult=LUA_BEER_JOB_RUNNING; cheeseLuaStage={CHEESE_LUA_STAGE_IDLE, 77, PROGRAM_END}; cheesePhValue=7.0f; cheeseRuntime={}; cheeseRuntime.enteredMs=fakeMs; cheeseRuntime.lastTickMs=fakeMs; transitions=aborts=heaterCalls=coolingCalls=0; preparedProgram=-1; }
static void tick() { fakeMs += 1000; cheese_stage_tick(); }
int main() {
  fakeMs=0;
  reset('H'); sensor.avgTemp=15; tick(); sensor.avgTemp=20; for(int i=0;i<11;i++) tick(); tick(); check(transitions==1 && aborts==0 && heaterCalls>0,"H success/one transition");
  reset('H'); program[0].Time=.001f; sensor.avgTemp=10; cheeseRuntime.enteredMs=fakeMs-1000; tick(); check(aborts==1,"H timeout");
  reset('P'); program[0].Time=.06f; program[0].Param=10; sensor.avgTemp=20; tick(); check(transitions==0,"P completed before required hold"); sensor.avgTemp=19; tick(); check(transitions==0,"P advanced after leaving band"); sensor.avgTemp=20; tick(); tick(); check(transitions==0,"P did not pause accumulation outside band"); tick(); check(transitions==1 && aborts==0,"P pauses outside band then resumes");
  reset('P'); program[0].Param=.001f; sensor.avgTemp=10; cheeseRuntime.enteredMs=fakeMs-1000; tick(); check(aborts==1,"P overall timeout");
  reset('C'); sensor.avgTemp=20; for(int i=0;i<11;i++) tick(); tick(); check(transitions==1 && coolingCalls>0,"C success/one transition");
  reset('C'); coolingOk=false; sensor.avgTemp=25; tick(); check(aborts==1,"C actuator failure");
  reset('C'); sensor.avgTemp=25; program[0].Time=.001f; cheeseRuntime.enteredMs=fakeMs-1000; tick(); check(aborts==1,"C timeout");
  reset('M'); cheeseRuntime.mixerOneShotComplete=true; tick(); tick(); check(transitions==1,"M one-shot success");
  reset('M'); program[0].Time=.001f; tick(); tick(); check(transitions==1 && aborts==0,"M duration transition");
  reset('M'); mixerOk=false; tick(); check(aborts==1,"M mixer-device failure");
  reset('D'); program[0].TempSensor=2; cheeseRuntime.doserStarted=true; tick(); check(transitions==0 && aborts==0,"D moved before local doser completion"); localDone=true; tick(); tick(); check(transitions==1,"D local post-start completion");
  reset('D'); program[0].TempSensor=2; cheeseRuntime.doserStarted=true; program[0].Time=.001f; cheeseRuntime.enteredMs=fakeMs-1000; tick(); check(aborts==1,"D local timeout after start");
  reset('D'); program[0].TempSensor=1; program[0].Time=.001f; cheeseRuntime.enteredMs=fakeMs-1000; tick(); check(aborts==1,"D manual timeout");
  reset('N'); program[0].Param=6.5f; cheesePhValue=6.5f; sensor.avgTemp=20; for(int i=0;i<15;i++) tick(); cheesePhValue=7.0f; tick(); cheesePhValue=6.5f; for(int i=0;i<31;i++) tick(); tick(); check(transitions==1,"N resets the 30-second pH window");
  reset('N'); phOk=false; sensor.avgTemp=20; for(int i=0;i<11;i++) tick(); check(aborts==1,"N invalid pH failure");
  reset('N'); program[0].Param=6.5f; cheesePhValue=7.0f; sensor.avgTemp=20; program[0].Time=.001f; cheeseRuntime.enteredMs=fakeMs-1000; tick(); check(aborts==1,"N overall timeout");
  reset('W'); tick(); check(transitions==0 && aborts==0,"W advanced without manual confirmation"); run_cheese_program(1); tick(); check(transitions==1,"W manual confirmation did not transition");
  reset('S'); tick(); check(transitions==0 && aborts==0,"S advanced without manual confirmation"); run_cheese_program(1); tick(); check(transitions==1,"S manual confirmation did not transition");
  reset('L'); program[0].Time=.001f; cheeseRuntime.enteredMs=fakeMs-1000; cheeseLuaStage.phase=CHEESE_LUA_STAGE_RUNNING; tick(); check(aborts==1,"L timeout");
  reset('L'); cheeseLuaStage.phase=CHEESE_LUA_STAGE_RUNNING; luaResult=LUA_BEER_JOB_FAILED; tick(); check(aborts==1,"L error result");
  reset('L'); cheeseLuaStage.phase=CHEESE_LUA_STAGE_RUNNING; luaResult=LUA_BEER_JOB_SUCCEEDED; tick(); check(aborts==1,"L completion without next did not stop");
  reset('L'); cheeseLuaStage.phase=CHEESE_LUA_STAGE_EXIT_REQUESTED; cheeseLuaStage.nextProgram=1; tick(); check(aborts==0 && preparedProgram==1,"L confirmed requested exit did not prepare next row");
  fakeMs=0xfffffff0UL; reset('P'); program[0].Param=10; sensor.avgTemp=20; tick(); check(cheeseRuntime.holdAccumulatedMs==1000,"P hold did not accumulate across millis rollover"); sensor.avgTemp=19; tick(); check(cheeseRuntime.holdAccumulatedMs==1000,"P hold grew outside the band"); sensor.avgTemp=20; tick(); check(cheeseRuntime.holdAccumulatedMs==2000,"P hold did not resume after the band");
  return failures;
}
'''


def build(tick_body: str, lua_body: str) -> str:
    replacements = {
        "@KIND@": extracted("inline CheeseStageKind cheese_stage_kind(ProgramType type)"),
        "@ELAPSED@": extracted("inline bool cheese_time_elapsed(uint32_t nowMs, uint32_t startedMs,"),
        "@TIMEOUT@": extracted("inline float cheese_stage_timeout_minutes(const WProgram& row)"),
        "@BAND@": extracted("inline bool cheese_in_temperature_band(float temperature, float target)"),
        "@TEMP_CONFIRM@": extracted("inline bool cheese_temperature_confirmed(uint32_t nowMs, bool inBand)"),
        "@PH_CONFIRM@": extracted("inline bool cheese_ph_target_confirmed(uint32_t nowMs, bool reached)"),
        "@PH_INVALID@": extracted("inline bool cheese_ph_invalid_too_long(uint32_t nowMs, bool valid)"),
        "@LUA_TICK@": lua_body,
        "@TICK@": tick_body,
    }
    result = HARNESS
    for marker, content in replacements.items():
        result = result.replace(marker, content)
    return result


def run(cpp_source: str, label: str, expect_success: bool) -> bool:
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-stage-") as tmp:
        path = Path(tmp)
        cpp, binary = path / "stage.cpp", path / "stage"
        cpp.write_text(cpp_source, encoding="utf-8")
        compiled = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)], capture_output=True, text=True, check=False)
        if compiled.returncode != 0:
            print(f"FAIL: {label} compile\n{compiled.stderr}", file=sys.stderr)
            return False
        finished = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if (finished.returncode == 0) != expect_success:
            print(f"FAIL: {label}\n{finished.stdout}{finished.stderr}", file=sys.stderr)
            return False
    return True


def main() -> int:
    try:
        tick_body = extracted("void cheese_stage_tick()")
        lua_body = extracted("inline bool cheese_lua_stage_tick(uint32_t nowMs, const WProgram& row)")
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    harness = build(tick_body, lua_body)
    if not run(harness, "universal stage dispatcher", True):
        return 1
    for old, new, label in [
        ("cheese_temperature_confirmed(nowMs,", "false && cheese_temperature_confirmed(nowMs,", "H/C confirmation"),
        ("cheeseRuntime.holdAccumulatedMs += elapsed;", "cheeseRuntime.holdAccumulatedMs -= elapsed;", "P accumulation"),
        ("if (row.TempSensor == 2 && cheese_local_doser_complete())", "if (false)", "D completion"),
        ("kind != CHEESE_STAGE_HOLD && kind != CHEESE_STAGE_MIX", "false", "C timeout"),
        ("case CHEESE_STAGE_WAIT:\n      return;", "case CHEESE_STAGE_WAIT:\n      run_cheese_program(ProgramNum + 1); return;", "W manual transition"),
        ("case CHEESE_STAGE_DRAIN:\n      return;", "case CHEESE_STAGE_DRAIN:\n      run_cheese_program(ProgramNum + 1); return;", "S manual transition"),
        ("cheesePhValue <= row.Param", "cheesePhValue < row.Param", "N inclusive threshold"),
    ]:
        mutant = tick_body.replace(old, new, 1)
        if mutant == tick_body or not run(build(mutant, lua_body), f"mutation {label}", False):
            return 1
    for old, new, label in [
        ("result == LUA_BEER_JOB_LOCK_BUSY", "result == LUA_BEER_JOB_SUCCEEDED", "L completion outcome"),
        ("if (!cheese_finish_lua_exit()) return true;", "if (true) return true;", "L confirmed exit"),
    ]:
        mutant = lua_body.replace(old, new, 1)
        if mutant == lua_body or not run(build(tick_body, mutant), f"mutation {label}", False):
            return 1
    print("OK: source-derived Cheese stage tick covers H/P/C/M/D/N/W/S/L and mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
