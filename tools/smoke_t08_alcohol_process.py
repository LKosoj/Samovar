#!/usr/bin/env python3
"""T08: real A/S/P/R threshold gate keeps a running process on invalid ABV."""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]


def harness(source: str) -> str:
    threshold = extract_function_body(source, "inline bool program_threshold_row_done")
    return f'''#include <cmath>
#include <iostream>
typedef char ProgramType;
static constexpr ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram {{ ProgramType WType; float Speed; }};
struct Sensor {{ float avgTemp; float StartProgTemp; }} TankSensor;
static bool boil_started = true, distAlcoholEstimateWarningSent = false;
static int warnings = 0, processState = 7, heaterOutput = 1;
static const int WARNING_MSG = 3;
static const char* SendMsg(const char*, int) {{ ++warnings; return ""; }}
static bool alcohol_estimate_valid(float value) {{ return value >= 0 && value <= 100; }}
static float get_alcohol(float temperature) {{
  if (!boil_started || !std::isfinite(temperature) || temperature == 10) return -1;
  if (temperature == 20) return 0;
  return temperature;
}}
static float get_steam_alcohol(float temperature) {{
  if (!boil_started || !std::isfinite(temperature) || temperature == 10) return -1;
  if (temperature == 20) return 0;
  return temperature + 10;
}}
inline bool program_threshold_row_done(const WProgram& row) {{{threshold}}}
static int failures = 0;
static void check(bool ok, const char* name) {{ if (!ok) {{ std::cerr << "FAIL: " << name << '\\n'; ++failures; }} }}
static void invalid_case(char type, float current, float start, const char* name) {{
  TankSensor.avgTemp = current; TankSensor.StartProgTemp = start;
  const int state = processState, output = heaterOutput;
  check(!program_threshold_row_done({{type, 0.9f}}), name);
  check(processState == state && heaterOutput == output, "invalid leaves process and heat unchanged");
}}
int main() {{
  for (char type : {{'A', 'S', 'P', 'R'}}) invalid_case(type, 10, 60, "invalid current blocks each percentage row");
  invalid_case('S', 60, 10, "S invalid start blocks");
  invalid_case('R', 60, 10, "R invalid start blocks");
  invalid_case('S', 60, 20, "S zero denominator blocks");
  invalid_case('R', 60, 20, "R zero denominator blocks");
  check(warnings == 1, "one warning for invalid episode");
  invalid_case('A', 10, 60, "repeat invalid blocks");
  check(warnings == 1, "repeat invalid does not spam");
  TankSensor.avgTemp = 60; TankSensor.StartProgTemp = 60;
  check(!program_threshold_row_done({{'A', 50}}), "valid sample resumes ordinary comparison");
  check(!distAlcoholEstimateWarningSent, "valid sample resets warning episode");
  invalid_case('P', 10, 60, "new invalid episode blocks");
  check(warnings == 2, "new invalid episode warns once");
  boil_started = false; distAlcoholEstimateWarningSent = false; warnings = 0;
  invalid_case('A', 10, 60, "cold warmup blocks silently");
  check(warnings == 0, "cold warmup has no warning");
  boil_started = true; TankSensor.avgTemp = 60; TankSensor.StartProgTemp = 60;
  check(program_threshold_row_done({{'A', 70}}), "A valid threshold works");
  check(program_threshold_row_done({{'S', 1.1f}}), "S relative threshold uses start");
  check(program_threshold_row_done({{'P', 80}}), "P valid threshold works");
  check(program_threshold_row_done({{'R', 1.1f}}), "R relative threshold uses start");
  return failures ? 1 : 0;
}}'''


def run(code: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-t08-process-") as directory:
        cpp = Path(directory) / "test.cpp"
        binary = Path(directory) / "test"
        cpp.write_text(code, encoding="utf-8")
        compiled = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)], capture_output=True, text=True)
        if compiled.returncode:
            return compiled.returncode, "COMPILE FAIL:\n" + compiled.stderr
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr


def predictor_harness(source: str) -> str:
    predictor = extract_function_body(source, "void updateTimePredictor")
    return f'''#include <cmath>
#include <cstdint>
#include <iostream>
typedef char ProgramType;
static constexpr ProgramType PROGRAM_TYPE_NONE = 0;
struct WProgram {{ ProgramType WType; float Speed; }};
struct Sensor {{ float avgTemp; float StartProgTemp; }} TankSensor;
struct {{ float DistTemp; }} SamSetup = {{90}};
struct TimePredictor {{ unsigned long startTime, processStartTime, lastUpdateTime; float initialAlcohol, initialSteamAlcohol, initialTemp, processInitialTemp, remainingTime, processRemainingTime, rowPredictedTotalTime, predictedTotalTime; bool baselineValid, rowPredictionAvailable, processPredictionAvailable; }} timePredictor;
static WProgram program[1]; static unsigned char ProgramNum = 0, ProgramLen = 1;
static bool sessionTimerValid = true; static unsigned long sessionStartTime = 0, now = 60000;
static constexpr float MIN_TEMP_RATE = .01f, MIN_ALC_RATE = .001f; static constexpr unsigned long PREDICTOR_UPDATE_MS = 30000;
enum {{ DIST_PREDICTION_AWAITING_BOIL, DIST_PREDICTION_NO_ACTIVE_ROW, DIST_PREDICTION_COLLECTING, DIST_PREDICTION_READY }};
static int distRowPredictionReason, distProcessPredictionReason;
static unsigned long millis() {{ return now; }}
static bool program_type_empty(ProgramType type) {{ return type == 0; }}
static float max(float a, float b) {{ return a > b ? a : b; }}
static bool alcohol_estimate_valid(float value) {{ return value >= 0 && value <= 100; }}
static float get_alcohol(float t) {{ return t == 39 ? -1 : t; }}
static float get_steam_alcohol(float t) {{ return t == 39 ? -1 : t + 10; }}
static bool calculate_dist_process_remaining(float current, float target, float initial, float elapsed, float& remaining) {{ if (current >= target || elapsed <= 0) return false; remaining = (target - current) / ((current - initial) / elapsed); return remaining > 0; }}
void updateTimePredictor() {{{predictor}}}
static int failures = 0;
static void check(bool ok, const char* name) {{ if (!ok) {{ std::cerr << "FAIL: " << name << '\\n'; ++failures; }} }}
static void prepare(char type, float start) {{
  program[0] = {{type, 50}}; TankSensor.avgTemp = 60; TankSensor.StartProgTemp = start;
  timePredictor = {{0, 0, 0, 70, 80, 50, 50, 0, 0, 0, 0, true, false, false}};
}}
int main() {{
  prepare('A', 39); updateTimePredictor();
  check(timePredictor.rowPredictionAvailable, "A forecast uses its absolute target");
  prepare('P', 39); updateTimePredictor();
  check(timePredictor.rowPredictionAvailable, "P forecast uses its absolute target");
  prepare('S', 60); program[0].Speed = .8f; updateTimePredictor();
  check(timePredictor.rowPredictionAvailable, "S forecast uses StartProgTemp relatively");
  prepare('R', 60); program[0].Speed = .8f; updateTimePredictor();
  check(timePredictor.rowPredictionAvailable, "R forecast uses StartProgTemp relatively");
  prepare('T', 39); program[0].Speed = 80; updateTimePredictor();
  check(timePredictor.rowPredictionAvailable, "temperature forecast remains available");
  prepare('A', 60); timePredictor.initialAlcohol = -1; updateTimePredictor();
  check(!timePredictor.rowPredictionAvailable, "invalid alcohol baseline does not predict");
  prepare('P', 60); timePredictor.initialSteamAlcohol = -1; updateTimePredictor();
  check(!timePredictor.rowPredictionAvailable, "invalid steam baseline does not predict");
  return failures ? 1 : 0;
}}'''


def boiling_harness(source: str) -> str:
    boiling = extract_function_body(source, "void set_boiling")
    return f'''#include <iostream>
struct Sensor {{ float avgTemp; }} TankSensor;
static bool boil_started = false;
static float boil_temp = -1, alcohol_s = -1;
static float get_alcohol(float temperature) {{ return temperature == 100 ? 0 : 42; }}
void set_boiling() {{{boiling}}}
static int failures = 0;
static void check(bool ok, const char* name) {{ if (!ok) {{ std::cerr << "FAIL: " << name << '\\n'; ++failures; }} }}
int main() {{
  TankSensor.avgTemp = 0; set_boiling();
  check(boil_started && boil_temp == 0 && alcohol_s == -1, "missing tank keeps unavailable sentinel");
  boil_started = false; boil_temp = -1; alcohol_s = -1; TankSensor.avgTemp = 100; set_boiling();
  check(boil_started && boil_temp == 100 && alcohol_s == 0, "real water is valid zero alcohol");
  return failures ? 1 : 0;
}}'''


def main() -> int:
    source = (ROOT / "distiller.h").read_text(encoding="utf-8")
    result, output = run(harness(source))
    sys.stdout.write(output)
    if result:
        return 1
    mutations = [
        ("invalid gate", source.replace("if (!alcohol_estimate_valid(currentAlcohol)) goto alcohol_unavailable;", "if (false) goto alcohol_unavailable;", 1), "FAIL: invalid current blocks each percentage row"),
        ("relative denominator", source.replace("startAlcohol <= 0.0f || ", "false || ", 1), "FAIL: one warning for invalid episode"),
    ]
    for name, mutant, expected in mutations:
        if mutant == source:
            raise AssertionError(f"{name} mutation anchor missing")
        result, output = run(harness(mutant))
        if result == 0 or expected not in output or "COMPILE FAIL:" in output:
            print(f"FAIL: {name} mutation was not meaningfully rejected:\n{output}", file=sys.stderr)
            return 1
        print(f"{name} mutation rejected:\n{output}", end="")
    result, output = run(predictor_harness(source))
    sys.stdout.write(output)
    if result:
        return 1
    predictor_mutant = source.replace(
        "(wtype != 'S' || (alcohol_estimate_valid(startAlcohol) && startAlcohol > 0.0f))",
        "(alcohol_estimate_valid(startAlcohol) && startAlcohol > 0.0f)", 1)
    if predictor_mutant == source:
        raise AssertionError("absolute target mutation anchor missing")
    result, output = run(predictor_harness(predictor_mutant))
    if result == 0 or "FAIL: A forecast uses its absolute target" not in output or "COMPILE FAIL:" in output:
        raise AssertionError(f"absolute target mutation was not meaningfully rejected: {output}")
    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")
    result, output = run(boiling_harness(logic_source))
    sys.stdout.write(output)
    if result:
        return 1
    sentinel_mutant = logic_source.replace("alcohol_s = -1.0f;", "alcohol_s = 0.0f;", 1)
    if sentinel_mutant == logic_source:
        raise AssertionError("missing tank mutation anchor missing")
    result, output = run(boiling_harness(sentinel_mutant))
    if result == 0 or "FAIL: missing tank keeps unavailable sentinel" not in output or "COMPILE FAIL:" in output:
        raise AssertionError(f"missing tank mutation was not meaningfully rejected: {output}")
    alarm_source = (ROOT / "alarm.h").read_text(encoding="utf-8")
    alarm_block, _ = extract_braced_block_after(alarm_source, "if (boil_started)", alarm_source.find("SAMOVAR_STATUS_RECT_STABILIZING"))
    if "alcohol_estimate_valid(alcohol_s)" not in alarm_block:
        print("FAIL: boiling message must reject unavailable alcohol", file=sys.stderr)
        return 1
    bk_source = (ROOT / "BK.h").read_text(encoding="utf-8")
    dist_start = source[source.find("distAlcoholEstimateWarningSent = false;", source.find("mode_run_heating_start")):]
    if not dist_start.startswith("distAlcoholEstimateWarningSent = false;"):
        print("FAIL: DIST new-process warning reset absent", file=sys.stderr)
        return 1
    if "distAlcoholEstimateWarningSent = false;" not in extract_function_body(bk_source, "static void bk_apply_work_power"):
        print("FAIL: BK new-process warning reset absent", file=sys.stderr)
        return 1
    print("T08 alcohol process: A/S/P/R gate, episode warnings and resets passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
