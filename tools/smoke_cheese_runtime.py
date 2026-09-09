#!/usr/bin/env python3
"""Source-derived checks for the universal Cheese runtime."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
CHEESE = ROOT / "cheese.h"

SIGNATURES = {
    "kind": "inline CheeseStageKind cheese_stage_kind(ProgramType type)",
    "elapsed": "inline bool cheese_time_elapsed(uint32_t nowMs, uint32_t startedMs,",
    "band": "inline bool cheese_in_temperature_band(float temperature, float target)",
    "confirm": "inline bool cheese_temperature_confirmed(uint32_t nowMs, bool inBand)",
    "ph_confirm": "inline bool cheese_ph_target_confirmed(uint32_t nowMs, bool reached)",
    "ph_invalid": "inline bool cheese_ph_invalid_too_long(uint32_t nowMs, bool valid)",
    "median": "inline int cheese_median3(int a, int b, int c)",
    "calibrate": "inline float cheese_calibrated_ph(int raw, float slope, float offset)",
    "sample": "inline void cheese_sample_ph(uint32_t nowMs)",
}

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
using std::isfinite;

#define CHEESE_TEMPERATURE_DELTA 0.3f
#define CHEESE_TEMPERATURE_CONFIRM_MS 10000UL
#define CHEESE_PH_CONFIRM_MS 30000UL
#define CHEESE_PH_INVALID_MS 10000UL
#define CHEESE_PH_SAMPLE_INTERVAL_MS 1000UL
#define LUA_PIN 0

typedef char ProgramType;
enum CheeseStageKind : uint8_t {
  CHEESE_STAGE_INVALID = 0, CHEESE_STAGE_HEAT, CHEESE_STAGE_HOLD,
  CHEESE_STAGE_COOL, CHEESE_STAGE_MIX, CHEESE_STAGE_DOSE, CHEESE_STAGE_PH,
  CHEESE_STAGE_WAIT, CHEESE_STAGE_DRAIN, CHEESE_STAGE_LUA,
};
struct CheeseRuntimeState {
  uint32_t enteredMs; uint32_t lastTickMs; uint32_t temperatureConfirmSinceMs;
  uint32_t holdAccumulatedMs; uint32_t mixerDeadlineMs; uint32_t phReachedSinceMs;
  uint32_t phInvalidSinceMs; float heatStartSetpoint; uint8_t mixerDevice;
  bool mixerRunning; bool mixerOneShotComplete; bool doserStarted;
  bool doserCompleted; bool drainOpen; bool temperatureConfirmActive;
  bool phReachedActive; bool phInvalidActive;
};
static CheeseRuntimeState cheeseRuntime = {};
struct Setup { float CheesePhSlope; float CheesePhOffset; } SamSetup = {0.001f, 0.0f};
static int cheesePhRaw = 0;
static float cheesePhValue = 0.0f;
static bool cheesePhValid = false;
static bool cheesePhSampled = false;
static uint32_t cheesePhSampleMs = 0;
static int analogValue = 0;
static int analogReads = 0;
int analogRead(int) { ++analogReads; return analogValue; }

@KIND@
@ELAPSED@
@BAND@
@CONFIRM@
@PH_CONFIRM@
@PH_INVALID@
@MEDIAN@
@CALIBRATE@
@SAMPLE@

static int failures = 0;
static void check(bool value, const char* text) {
  if (!value) { std::cerr << "FAIL: " << text << '\n'; ++failures; }
}

int main() {
  for (ProgramType type : {'H','P','C','M','D','N','W','S','L'}) {
    check(cheese_stage_kind(type) != CHEESE_STAGE_INVALID,
          "new Cheese operation was rejected");
  }
  for (ProgramType type : {'A','Z','f','z','d','s','p','v','r','n','R','B'}) {
    check(cheese_stage_kind(type) == CHEESE_STAGE_INVALID,
          "legacy Cheese operation was accepted");
  }
  check(cheese_time_elapsed(1000, 1, 0.0f), "zero timeout did not expire");
  check(!cheese_time_elapsed(60000, 1, 2.0f), "timeout expired too early");
  check(cheese_time_elapsed(120001, 1, 2.0f), "timeout did not expire");
  check(cheese_time_elapsed(2000, 0xfffffff0U, 0.0002f),
        "millis wrap broke timeout");
  check(cheese_in_temperature_band(20.30f, 20.0f), "plus delta was excluded");
  check(cheese_in_temperature_band(19.70f, 20.0f), "minus delta was excluded");
  check(!cheese_in_temperature_band(20.31f, 20.0f), "out of band was accepted");
  cheeseRuntime.temperatureConfirmSinceMs = 0;
  check(!cheese_temperature_confirmed(1000, true), "first in-band tick confirmed early");
  check(!cheese_temperature_confirmed(10500, true), "9.5 seconds confirmed early");
  check(cheese_temperature_confirmed(11000, true), "10 seconds did not confirm");
  check(!cheese_temperature_confirmed(11500, false), "out-of-band tick retained confirmation");
  check(!cheese_temperature_confirmed(12000, true), "reset confirmation resumed early");
  cheeseRuntime.temperatureConfirmActive = false;
  check(!cheese_temperature_confirmed(0, true), "millis zero temperature confirmed early");
  check(cheese_temperature_confirmed(10000, true), "millis zero temperature did not confirm");
  cheeseRuntime.temperatureConfirmActive = false;
  check(!cheese_temperature_confirmed(0xfffffff0U, true), "wrap temperature confirmed early");
  check(cheese_temperature_confirmed(9984U, true), "wrap temperature did not confirm");
  cheeseRuntime.phReachedSinceMs = 0;
  check(!cheese_ph_target_confirmed(1000, true), "first pH match confirmed early");
  check(!cheese_ph_target_confirmed(30500, true), "29.5 pH seconds confirmed early");
  check(cheese_ph_target_confirmed(31000, true), "30 pH seconds did not confirm");
  check(!cheese_ph_target_confirmed(32000, false), "bad pH did not reset confirmation");
  cheeseRuntime.phReachedActive = false;
  check(!cheese_ph_target_confirmed(0, true), "millis zero pH confirmed early");
  check(cheese_ph_target_confirmed(30000, true), "millis zero pH did not confirm");
  cheeseRuntime.phInvalidSinceMs = 0;
  check(!cheese_ph_invalid_too_long(1000, false), "first invalid pH failed early");
  check(!cheese_ph_invalid_too_long(10500, false), "9.5 invalid pH seconds failed early");
  check(cheese_ph_invalid_too_long(11000, false), "10 invalid pH seconds did not fail");
  cheeseRuntime.phInvalidActive = false;
  check(!cheese_ph_invalid_too_long(0, false), "millis zero invalid pH failed early");
  check(cheese_ph_invalid_too_long(10000, false), "millis zero invalid pH did not fail");
  cheeseRuntime.phReachedActive = false;
  check(!cheese_ph_target_confirmed(0xfffffff0U, true), "wrap pH confirmed early");
  check(cheese_ph_target_confirmed(29984U, true), "wrap pH did not confirm");
  cheeseRuntime.phInvalidActive = false;
  check(!cheese_ph_invalid_too_long(0xfffffff0U, false), "wrap invalid pH failed early");
  check(cheese_ph_invalid_too_long(9984U, false), "wrap invalid pH did not fail");
  check(cheese_median3(1, 9, 4) == 4, "median did not select middle value");
  check(cheese_median3(9, 1, 4) == 4, "median depended on order");
  check(cheese_median3(4, 9, 1) == 4, "median failed descending order");
  check(cheese_calibrated_ph(1000, -0.003f, 8.0f) == 5.0f,
        "pH calibration changed");
  cheesePhSampled = false; analogReads = 0; analogValue = 1000;
  cheese_sample_ph(0);
  check(analogReads == 3 && cheesePhRaw == 1000 && cheesePhValue == 1.0f,
        "pH sample at millis zero was not taken");
  analogValue = 900; cheese_sample_ph(500);
  check(analogReads == 3, "pH interval sampled too early after millis zero");
  cheese_sample_ph(1000);
  check(analogReads == 6 && cheesePhRaw == 900,
        "pH interval did not resume after millis zero");
  cheesePhSampled = false; analogReads = 0; analogValue = 800;
  cheese_sample_ph(0xfffffff0U); cheese_sample_ph(500);
  check(analogReads == 3, "pH interval broke before millis wrap elapsed");
  cheese_sample_ph(1000);
  check(analogReads == 6, "pH interval did not resume across millis wrap");
  check(CHEESE_PH_CONFIRM_MS == 30000UL, "pH confirmation is not 30 seconds");
  check(CHEESE_PH_INVALID_MS == 10000UL, "pH invalid timeout is not 10 seconds");
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(harness: str, label: str, expected_success: bool) -> bool:
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-runtime-") as tmp:
        source = Path(tmp) / "runtime.cpp"
        binary = Path(tmp) / "runtime"
        source.write_text(harness, encoding="utf-8")
        built = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if built.returncode != 0:
            print(f"FAIL: {label} did not compile\n{built.stderr}", file=sys.stderr)
            return False
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if (ran.returncode == 0) != expected_success:
            print(f"FAIL: {label}\n{ran.stdout}{ran.stderr}", file=sys.stderr)
            return False
        return True


def main() -> int:
    source = CHEESE.read_text(encoding="utf-8")
    errors: list[str] = []
    bodies: dict[str, str] = {}
    for name, signature in SIGNATURES.items():
        try:
            bodies[name] = extract_function_body(source, signature)
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        print("\n".join(f"FAIL: {error}" for error in errors), file=sys.stderr)
        return 1

    definitions = {
        "kind": "inline CheeseStageKind cheese_stage_kind(ProgramType type) {\n" + bodies["kind"] + "\n}",
        "elapsed": "inline bool cheese_time_elapsed(uint32_t nowMs, uint32_t startedMs, float minutes) {\n" + bodies["elapsed"] + "\n}",
        "band": "inline bool cheese_in_temperature_band(float temperature, float target) {\n" + bodies["band"] + "\n}",
        "confirm": "inline bool cheese_temperature_confirmed(uint32_t nowMs, bool inBand) {\n" + bodies["confirm"] + "\n}",
        "ph_confirm": "inline bool cheese_ph_target_confirmed(uint32_t nowMs, bool reached) {\n" + bodies["ph_confirm"] + "\n}",
        "ph_invalid": "inline bool cheese_ph_invalid_too_long(uint32_t nowMs, bool valid) {\n" + bodies["ph_invalid"] + "\n}",
        "median": "inline int cheese_median3(int a, int b, int c) {\n" + bodies["median"] + "\n}",
        "calibrate": "inline float cheese_calibrated_ph(int raw, float slope, float offset) {\n" + bodies["calibrate"] + "\n}",
        "sample": "inline void cheese_sample_ph(uint32_t nowMs) {\n" + bodies["sample"] + "\n}",
    }
    harness = HARNESS
    for name, definition in definitions.items():
        harness = harness.replace(f"@{name.upper()}@", definition)
    if not compile_and_run(harness, "universal Cheese decisions", True):
        return 1

    mutations = [
        ("CHEESE_TEMPERATURE_CONFIRM_MS 10000UL", "CHEESE_TEMPERATURE_CONFIRM_MS 9000UL", "10-second temperature confirmation"),
        ("CHEESE_TEMPERATURE_DELTA 0.3f", "CHEESE_TEMPERATURE_DELTA 0.2f", "temperature band"),
        ("CHEESE_PH_CONFIRM_MS 30000UL", "CHEESE_PH_CONFIRM_MS 29000UL", "30-second pH confirmation"),
        ("CHEESE_PH_INVALID_MS 10000UL", "CHEESE_PH_INVALID_MS 9000UL", "10-second invalid pH"),
        ("return b;", "return a;", "median pH"),
        ("cheesePhSampled &&", "false &&", "pH sample interval"),
    ]
    for old, new, label in mutations:
        mutant = harness.replace(old, new, 1)
        if mutant == harness:
            print(f"FAIL: mutation anchor missing: {label}", file=sys.stderr)
            return 1
        if not compile_and_run(mutant, f"mutation survived: {label}", False):
            return 1

    print("OK: universal Cheese runtime decisions and mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
