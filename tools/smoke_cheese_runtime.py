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
    "ph_median": "inline int cheese_ph_median()",
    "calibrate": "inline float cheese_calibrated_ph(int raw, float slope, float offset)",
    "calibration_valid": "inline bool cheese_ph_calibration_valid(float slope, float offset)",
    "read": "inline bool cheese_read_ph_raw(int& raw)",
    "sample": "inline void cheese_sample_ph(uint32_t nowMs)",
    "reset": "inline void cheese_reset_stage_state()",
}

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
using std::isfinite;

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum UiWaitReason { UI_WAIT_CHEESE_TEMPERATURE_OR_PH_CONFIRM = 21 };
static void runtime_pair_begin(UiWaitReason, const char*, MESSAGE_TYPE) {}

#define CHEESE_TEMPERATURE_DELTA 0.3f
#define CHEESE_TEMPERATURE_CONFIRM_MS 10000UL
#define CHEESE_PH_CONFIRM_MS 30000UL
#define CHEESE_PH_INVALID_MS 10000UL
#define LUA_PIN 0
@CONSTANTS@

typedef char ProgramType;
enum CheeseStageKind : uint8_t {
  CHEESE_STAGE_INVALID = 0, CHEESE_STAGE_HEAT, CHEESE_STAGE_HOLD,
  CHEESE_STAGE_COOL, CHEESE_STAGE_MIX, CHEESE_STAGE_DOSE, CHEESE_STAGE_PH,
  CHEESE_STAGE_WAIT, CHEESE_STAGE_DRAIN, CHEESE_STAGE_LUA, CHEESE_STAGE_FLOC,
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
static bool cheesePhSampleAttempted = false;
static uint32_t cheesePhLastAttemptMs = 0;
static bool cheesePairErrorPending = false;
static bool cheeseFinishPending = false;
static void cheese_reset_lua_stage() {}
static int analogValue = 0;
static int adsValue = 0;
static int analogReads = 0;
int analogRead(int) { ++analogReads; return analogValue; }
@FILTER_STATE@

#ifdef USE_ADS1115
static bool adsPrepareResult = true;
static bool adsReadResult = true;
static int adsPrepareCalls = 0;
static int adsReadCalls = 0;
inline bool cheese_ph_prepare() { ++adsPrepareCalls; return adsPrepareResult; }
inline bool cheese_ads1115_read_raw(int& raw) {
  ++adsReadCalls;
  if (!adsReadResult) return false;
  raw = adsValue;
  return true;
}
#endif

static void set_raw(int raw) {
  analogValue = raw;
  adsValue = raw;
}

@KIND@
@ELAPSED@
@BAND@
@CONFIRM@
@PH_CONFIRM@
@PH_INVALID@
@MEDIAN@
@PH_MEDIAN@
@CALIBRATE@
@CALIBRATION_VALID@
@READ@
@SAMPLE@
@RESET@

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
  check(cheese_ph_calibration_valid(0.003f, 7.0f) &&
            cheese_ph_calibration_valid(-0.003f, 7.0f),
        "both pH calibration polarities must stay valid");
  check(!cheese_ph_calibration_valid(0.0f, 7.0f) &&
            !cheese_ph_calibration_valid(NAN, 7.0f) &&
            !cheese_ph_calibration_valid(0.003f, INFINITY),
        "zero or non-finite pH calibration must be invalid");
  cheese_reset_stage_state();
  SamSetup.CheesePhSlope = 0.01f; SamSetup.CheesePhOffset = 0.0f;
#ifdef USE_ADS1115
  adsPrepareResult = true; adsReadResult = true;
#endif
  set_raw(100);
  cheese_sample_ph(0);
  check(cheesePhRaw == 100 && !cheesePhValid && cheesePhFilter.count == 1,
        "pH warmup accepted the first sample");
  check(cheesePhValue == 0.0f, "pH value changed before filter warmup");
  const int warmup[] = {200, 300, 400, 500};
  for (int i = 0; i < 4; ++i) {
    set_raw(warmup[i]);
    cheese_sample_ph(static_cast<uint32_t>(i + 1) * 1000U);
    check(cheesePhValid == (i == 3), "pH became ready before five samples");
  }
  check(cheesePhValid && cheesePhValue == 3.0f && cheese_ph_median() == 300,
        "five-sample pH median did not become ready");
  check(cheesePhRaw == 500, "raw pH did not remain the newest sample");

  cheese_reset_stage_state();
  const int outliers[] = {500, 900, 510, 520, 530};
  for (int i = 0; i < 5; ++i) {
    set_raw(outliers[i]);
    cheese_sample_ph(static_cast<uint32_t>(i) * 1000U);
  }
  check(cheesePhValid && cheese_ph_median() == 520 && cheesePhValue == 5.2f,
        "pH median did not reject an isolated outlier");
  cheese_reset_stage_state();
  const int twoOutliers[] = {500, 900, 510, 800, 520};
  for (int i = 0; i < 5; ++i) {
    set_raw(twoOutliers[i]);
    cheese_sample_ph(static_cast<uint32_t>(i) * 1000U);
  }
  check(cheesePhValid && cheese_ph_median() == 520 && cheesePhValue == 5.2f,
        "pH median did not reject two outliers");
  cheese_reset_stage_state();
  const int rollover[] = {540, 550, 560, 570, 580};
  for (int i = 0; i < 5; ++i) {
    set_raw(rollover[i]);
    cheese_sample_ph(5000U + static_cast<uint32_t>(i) * 1000U);
  }
  check(cheese_ph_median() == 560 && cheesePhValue == 5.6f,
        "pH ring buffer did not roll over");
  const int stepped[] = {800, 800, 800};
  for (int i = 0; i < 3; ++i) {
    const int raw = stepped[i];
    set_raw(raw);
    cheese_sample_ph(10000U + static_cast<uint32_t>(i) * 1000U);
  }
  check(cheese_ph_median() == 800 && cheesePhValue == 8.0f,
        "pH step did not reach the median after three new samples");

  cheese_reset_stage_state();
  SamSetup.CheesePhSlope = -0.01f; SamSetup.CheesePhOffset = 10.0f;
  const int negative[] = {500, 510, 520, 530, 540};
  for (int i = 0; i < 5; ++i) {
    set_raw(negative[i]);
    cheese_sample_ph(static_cast<uint32_t>(i) * 1000U);
  }
  check(cheesePhValid && cheesePhValue == 4.8f,
        "negative pH calibration slope was not filtered");

  cheese_reset_stage_state();
  SamSetup.CheesePhSlope = 0.01f; SamSetup.CheesePhOffset = 0.0f;
  analogReads = 0;
#ifdef USE_ADS1115
  adsReadCalls = 0;
#endif
  set_raw(500);
  cheese_sample_ph(0); cheese_sample_ph(500);
  check(cheesePhRaw == 500, "pH sampled before one second elapsed");
#ifdef USE_ADS1115
  check(adsReadCalls == 1, "ADS1115 pH interval sampled too early");
#else
  check(analogReads == 3, "analog pH interval sampled too early");
#endif
  set_raw(510);
  cheese_sample_ph(1000);
  check(cheesePhRaw == 510, "pH did not sample at one-second interval");
#ifdef USE_ADS1115
  check(adsReadCalls == 2, "ADS1115 pH interval did not resume");
#else
  check(analogReads == 6, "analog pH interval did not resume");
#endif
  cheese_reset_stage_state();
  analogReads = 0;
#ifdef USE_ADS1115
  adsReadCalls = 0;
#endif
  set_raw(500);
  cheese_sample_ph(0xfffffff0U); cheese_sample_ph(0x000001d8U);
  check(cheesePhRaw == 500, "pH interval broke across millis wrap");
#ifdef USE_ADS1115
  check(adsReadCalls == 1, "ADS1115 sampled too early across millis wrap");
#else
  check(analogReads == 3, "analog pH sampled too early across millis wrap");
#endif
  cheese_sample_ph(0x000003e8U);
  check(cheesePhRaw == 500, "pH sampled too early across millis wrap");
#ifdef USE_ADS1115
  check(adsReadCalls == 2, "ADS1115 did not sample after millis wrap interval");
#else
  check(analogReads == 6, "analog pH did not sample after millis wrap interval");
#endif

  cheese_reset_stage_state();
  SamSetup.CheesePhSlope = 0.01f; SamSetup.CheesePhOffset = 0.0f;
  set_raw(500);
  for (int i = 0; i < 5; ++i) cheese_sample_ph(static_cast<uint32_t>(i) * 1000U);
  SamSetup.CheesePhSlope = 0.02f;
  cheese_sample_ph(5000);
  check(!cheesePhValid && cheesePhRaw == 500,
        "slope change did not restart pH warmup");
  for (int i = 0; i < 4; ++i) cheese_sample_ph(6000U + static_cast<uint32_t>(i) * 1000U);
  SamSetup.CheesePhOffset = 1.0f;
  cheese_sample_ph(10000);
  check(!cheesePhValid, "offset change did not restart pH warmup");
  for (int i = 0; i < 4; ++i) cheese_sample_ph(11000U + static_cast<uint32_t>(i) * 1000U);
  cheese_sample_ph(20001);
  check(!cheesePhValid, "stale pH sample did not restart warmup");

  SamSetup.CheesePhSlope = 0.0f;
  cheese_sample_ph(21001);
  check(!cheesePhValid && cheesePhFilter.count == 0,
        "invalid pH calibration was not rejected");
  SamSetup.CheesePhSlope = 0.01f; SamSetup.CheesePhOffset = 0.0f;
  set_raw(500);
  for (int i = 0; i < 5; ++i) cheese_sample_ph(22001U + static_cast<uint32_t>(i) * 1000U);
  set_raw(2000);
  cheese_sample_ph(27001);
  check(!cheesePhValid && cheesePhFilter.count == 0,
        "out-of-range pH was not rejected");
#ifdef USE_ADS1115
  adsReadResult = true; set_raw(500);
  for (int i = 0; i < 5; ++i) cheese_sample_ph(28000U + static_cast<uint32_t>(i) * 1000U);
  adsReadResult = false;
  cheese_sample_ph(33000);
  check(!cheesePhValid && cheesePhFilter.count == 0 && adsReadCalls > 0,
        "ADS1115 read failure did not reset pH");
  adsReadResult = true;
  for (int i = 0; i < 5; ++i) {
    cheese_sample_ph(34000U + static_cast<uint32_t>(i) * 1000U);
    check(cheesePhValid == (i == 4),
          "pH filter did not require five samples after ADS1115 recovery");
  }
#endif
  SamSetup.CheesePhSlope = 0.01f; SamSetup.CheesePhOffset = 0.0f;
  set_raw(500);
  for (int i = 0; i < 5; ++i) cheese_sample_ph(40000U + static_cast<uint32_t>(i) * 1000U);
  check(cheesePhValid, "pH setup for stage reset did not become ready");
  cheese_reset_stage_state();
  check(cheesePhFilter.count == 0 && !cheesePhValid,
        "stage reset did not reset pH filter");
  check(CHEESE_PH_CONFIRM_MS == 30000UL, "pH confirmation is not 30 seconds");
  check(CHEESE_PH_INVALID_MS == 10000UL, "pH invalid timeout is not 10 seconds");
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(
    harness: str, label: str, expected_success: bool, expected_fail_text: str = ""
) -> bool:
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
        if expected_success and ran.returncode != 0:
            print(f"FAIL: {label}\n{ran.stdout}{ran.stderr}", file=sys.stderr)
            return False
        if not expected_success:
            if ran.returncode == 0:
                print(f"FAIL: {label} survived", file=sys.stderr)
                return False
            if expected_fail_text not in ran.stderr:
                print(
                    f"FAIL: {label} failed without expected assertion {expected_fail_text!r}\n"
                    f"{ran.stdout}{ran.stderr}", file=sys.stderr,
                )
                return False
            print(f"CONFIRMED FAIL: {label}: {expected_fail_text}")
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

    constant_names = (
        "CHEESE_PH_SAMPLE_INTERVAL_MS", "CHEESE_PH_STALE_MS",
    )
    constants = "\n".join(
        line for line in source.splitlines()
        if any(line.startswith(f"#define {name} ") for name in constant_names)
    )
    filter_start = source.find("static struct {\n  int samples[5];")
    filter_end = source.find(";", source.find("} cheesePhFilter", filter_start))
    if filter_start < 0 or filter_end < 0:
        print("FAIL: pH filter state declaration not found", file=sys.stderr)
        return 1
    filter_state = source[filter_start:filter_end + 1]

    definitions = {
        "kind": "inline CheeseStageKind cheese_stage_kind(ProgramType type) {\n" + bodies["kind"] + "\n}",
        "elapsed": "inline bool cheese_time_elapsed(uint32_t nowMs, uint32_t startedMs, float minutes) {\n" + bodies["elapsed"] + "\n}",
        "band": "inline bool cheese_in_temperature_band(float temperature, float target) {\n" + bodies["band"] + "\n}",
        "confirm": "inline bool cheese_temperature_confirmed(uint32_t nowMs, bool inBand) {\n" + bodies["confirm"] + "\n}",
        "ph_confirm": "inline bool cheese_ph_target_confirmed(uint32_t nowMs, bool reached) {\n" + bodies["ph_confirm"] + "\n}",
        "ph_invalid": "inline bool cheese_ph_invalid_too_long(uint32_t nowMs, bool valid) {\n" + bodies["ph_invalid"] + "\n}",
        "median": "inline int cheese_median3(int a, int b, int c) {\n" + bodies["median"] + "\n}",
        "ph_median": "inline int cheese_ph_median() {\n" + bodies["ph_median"] + "\n}",
        "calibrate": "inline float cheese_calibrated_ph(int raw, float slope, float offset) {\n" + bodies["calibrate"] + "\n}",
        "calibration_valid": "inline bool cheese_ph_calibration_valid(float slope, float offset) {\n" + bodies["calibration_valid"] + "\n}",
        "read": "inline bool cheese_read_ph_raw(int& raw) {\n" + bodies["read"] + "\n}",
        "sample": "inline void cheese_sample_ph(uint32_t nowMs) {\n" + bodies["sample"] + "\n}",
        "reset": "inline void cheese_reset_stage_state() {\n" + bodies["reset"] + "\n}",
    }
    harness = HARNESS
    harness = harness.replace("@CONSTANTS@", constants)
    harness = harness.replace("@FILTER_STATE@", filter_state)
    for name, definition in definitions.items():
        harness = harness.replace(f"@{name.upper()}@", definition)
    mutations = [
        ("CHEESE_TEMPERATURE_CONFIRM_MS 10000UL", "CHEESE_TEMPERATURE_CONFIRM_MS 9000UL", "10-second temperature confirmation", "9.5 seconds confirmed early"),
        ("CHEESE_TEMPERATURE_DELTA 0.3f", "CHEESE_TEMPERATURE_DELTA 0.2f", "temperature band", "plus delta was excluded"),
        ("CHEESE_PH_CONFIRM_MS 30000UL", "CHEESE_PH_CONFIRM_MS 29000UL", "30-second pH confirmation", "29.5 pH seconds confirmed early"),
        ("CHEESE_PH_INVALID_MS 10000UL", "CHEESE_PH_INVALID_MS 9000UL", "10-second invalid pH", "9.5 invalid pH seconds failed early"),
        ("return b;", "return a;", "median pH", "median did not select middle value"),
        ("cheesePhSampleAttempted &&", "false &&", "pH sample interval", "pH interval sampled too early"),
        ("cheesePhFilter.slope != SamSetup.CheesePhSlope", "false", "slope pH reset", "slope change did not restart pH warmup"),
        ("slope != 0.0f", "true", "zero pH slope", "zero or non-finite pH calibration must be invalid"),
        ("return sorted[2];", "return sorted[1];", "five-sample median", "five-sample pH median did not become ready"),
        ("cheesePhFilter.count == 5", "cheesePhFilter.count == 4", "five-sample readiness", "pH became ready before five samples"),
        ("cheese_ph_median(), SamSetup.CheesePhSlope", "cheesePhRaw, SamSetup.CheesePhSlope", "filtered pH value", "pH median did not reject an isolated outlier"),
        ("nowMs - cheesePhSampleMs > CHEESE_PH_STALE_MS", "false", "stale pH reset", "stale pH sample did not restart warmup"),
        ("cheesePhFilter.offset != SamSetup.CheesePhOffset", "false", "offset pH reset", "offset change did not restart pH warmup"),
        ("if (!cheesePhValid) {\n    cheesePhFilter = {};", "if (!cheesePhValid) {", "invalid pH reset", "out-of-range pH was not rejected"),
        ("cheesePhLastAttemptMs = 0;\n  cheesePhFilter = {};", "cheesePhLastAttemptMs = 0;", "stage pH reset", "stage reset did not reset pH filter"),
        ("cheesePhFilter = {};\n    return;", "return;", "read failure pH reset", "ADS1115 read failure did not reset pH"),
    ]
    for use_ads in (False, True):
        mode_harness = harness
        if use_ads:
            mode_harness = "#define USE_ADS1115 0x48\n" + mode_harness
        if not compile_and_run(mode_harness, "ADS1115" if use_ads else "analog pH", True):
            return 1
        for old, new, label, expected_fail_text in mutations:
            if label == "read failure pH reset" and not use_ads:
                continue
            mutant = mode_harness.replace(old, new, 1)
            if mutant == mode_harness:
                print(f"FAIL: mutation anchor missing: {label}", file=sys.stderr)
                return 1
            if not compile_and_run(
                mutant, f"mutation survived ({'ADS1115' if use_ads else 'analog'}): {label}",
                False, expected_fail_text,
            ):
                return 1

    print("OK: universal Cheese runtime decisions and mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
