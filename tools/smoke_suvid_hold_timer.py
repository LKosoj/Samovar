#!/usr/bin/env python3
"""Production-extracted behavioural contract for Suvid S1-S3."""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors = []

HARNESS = r'''
#include <cstdint>
#include <math.h>
#include <iostream>

@HEAT_DELTA@

struct Setup { float SuvidTemp; uint16_t SuvidHoldMinutes; };
static Setup SamSetup{};
struct Tank { float avgTemp; };
static Tank TankSensor{};
@HOLD_STATE@
@DEVIATION_STATE@

static bool PowerOn = true;
static bool heater_state = false;
static uint32_t fakeMillis = 0;
static uint32_t millis() { return fakeMillis; }
static int heaterCalls = 0;
static bool lastHeater = false;
static void setHeaterPosition(bool value) { heaterCalls++; lastHeater = value; }
static int messages = 0;
static int warnings = 0;
static void SendMsg(const char*, int type) { messages++; if (type == 1) warnings++; }
static int buzzerCalls = 0;
static void set_buzzer(bool) { buzzerCalls++; }
enum { SAMOVAR_POWER = 1, NOTIFY_MSG = 2, WARNING_MSG = 1 };
static int queueCalls = 0;
static bool queueSucceeds = true;
static bool queue_samovar_command(int) { queueCalls++; return queueSucceeds; }
static float suvid_target_temp() { return SamSetup.SuvidTemp > 0 ? SamSetup.SuvidTemp : 60.0f; }

static void tick() {
@BODY@
}

static int failures = 0;
static void check(bool value, const char* text) {
  if (!value) { std::cerr << "FAIL: " << text << '\n'; failures++; }
}
static void reset(uint16_t hold = 0) {
  PowerOn = false; tick();
  SamSetup = {60.0f, hold}; TankSensor.avgTemp = 60.0f; PowerOn = true;
  suvidHold = {}; suvidDeviation = {}; fakeMillis = 0; heaterCalls = 0;
  lastHeater = false; messages = 0; warnings = 0; buzzerCalls = 0;
  queueCalls = 0; queueSucceeds = true; heater_state = false;
}
static void test_symmetric_band() {
  reset(); TankSensor.avgTemp = 60.0f + HEAT_DELTA + 0.1f; tick();
  check(!lastHeater, "above symmetric band must disable heater");
  TankSensor.avgTemp = 60.0f; tick();
  check(!lastHeater, "inside symmetric band must retain an initially-off heater");
  TankSensor.avgTemp = 60.0f - HEAT_DELTA - 0.1f; tick();
  check(lastHeater, "below setpoint-HEAT_DELTA must enable heater");
  TankSensor.avgTemp = 60.0f; tick();
  check(lastHeater, "inside symmetric band must retain heater state");
  TankSensor.avgTemp = 61.1f; tick();
  check(!lastHeater, "above setpoint+HEAT_DELTA must disable heater");
}
static void test_hold_counts_only_band_time() {
  reset(1); fakeMillis = 1000; tick();
  fakeMillis = 31000; tick();
  check(suvidHold.accumulatedMs == 30000, "first in-band interval must be counted");
  TankSensor.avgTemp = 62.1f; fakeMillis = 61000; tick();
  check(suvidHold.accumulatedMs == 30000, "out-of-band time must not be counted");
  TankSensor.avgTemp = 60.0f; fakeMillis = 91000; tick();
  check(queueCalls == 0,
        "return to the band must not count the preceding out-of-band interval");
  fakeMillis = 121000; tick();
  check(queueCalls == 1 && suvidHold.fired,
        "two confirmed 30-second in-band intervals must complete one-minute hold");
}
static void test_zero_hold_is_indefinite() {
  reset(0); for (int i = 0; i < 100; i++) { fakeMillis += 1000; tick(); }
  check(!suvidHold.active && queueCalls == 0,
        "SuvidHoldMinutes=0 must keep an indefinite thermostat without completion");
}
static void test_deviation_warning_is_continuous() {
  reset(); TankSensor.avgTemp = 62.1f; tick();
  fakeMillis = 59999; tick(); check(warnings == 0, "warning must not fire before 60 seconds");
  fakeMillis = 60000; tick(); check(warnings == 1, "continuous >2C deviation must warn at 60 seconds");
  fakeMillis = 120000; tick(); check(warnings == 1, "continuous deviation must warn only once");
  TankSensor.avgTemp = 61.0f; fakeMillis = 121000; tick();
  TankSensor.avgTemp = 62.1f; fakeMillis = 122000; tick();
  fakeMillis = 182000; tick(); check(warnings == 2, "return to tolerance must re-arm warning");
}
static void test_timers_wrap_across_uint32_max() {
  reset(1);
  fakeMillis = UINT32_MAX - 30000U;
  tick();
  fakeMillis = 10000U;
  tick();
  check(suvidHold.accumulatedMs == 40001U,
        "hold must count the in-band interval across uint32 millis wrap");
  fakeMillis = 30000U;
  tick();
  check(queueCalls == 1 && suvidHold.fired,
        "hold must complete after the remaining in-band interval across wrap");

  reset();
  TankSensor.avgTemp = 62.1f;
  fakeMillis = UINT32_MAX - 30000U;
  tick();
  fakeMillis = 29999U;
  tick();
  check(warnings == 1,
        "continuous deviation must warn after 60 seconds across uint32 millis wrap");
}
static void test_queue_failure_is_explicit_without_fallback() {
  reset(1); fakeMillis = 1000; tick(); fakeMillis = 61000; queueSucceeds = false; tick();
  check(queueCalls == 1 && !suvidHold.fired && warnings == 1,
        "busy completion queue must warn and retain pending completion");
  fakeMillis = 62000; queueSucceeds = true; tick();
  check(queueCalls == 2 && suvidHold.fired,
        "pending completion must retry the same graceful command, not a fallback action");
}
int main() {
  test_symmetric_band(); test_hold_counts_only_band_time(); test_zero_hold_is_indefinite();
  test_deviation_warning_is_continuous(); test_timers_wrap_across_uint32_max();
  test_queue_failure_is_explicit_without_fallback();
  return failures == 0 ? 0 : 1;
}
'''


def definition(source, token):
    start = source.find(token)
    if start < 0:
        raise ValueError(f"missing {token}")
    end = source.find("};", start)
    if end < 0:
        raise ValueError(f"unterminated {token}")
    return source[start:end + 2]


def main():
    source = (ROOT / "suvid.h").read_text(encoding="utf-8")
    ini = (ROOT / "Samovar_ini.h").read_text(encoding="utf-8")
    body = extract_function_body(source, "inline void check_alarm_suvid")
    start = body.find("static bool suvidHeaterOn = false;")
    if start < 0:
        raise ValueError("thermostat anchor missing")
    snippet = body[start:]
    require_ordered_tokens("Suvid S1-S3 order", snippet, [
        "if (!PowerOn)", "suvidHold = {false, false, false, false, 0, 0};",
        "setpoint - HEAT_DELTA", "setpoint + HEAT_DELTA", "deviation > 2.0f",
        "now - suvidDeviation.sinceMs", "holdMs > 0", "inHoldBand",
        "suvidHold.accumulatedMs", "queue_samovar_command(SAMOVAR_POWER)",
    ], errors)
    if "program[" in snippet:
        errors.append("Suvid hold must not read the shared program buffer")
    if "request_emergency_stop" in snippet:
        errors.append("Suvid hold must not use an emergency fallback")
    if errors:
        for error in errors: print(f"FAIL: {error}", file=sys.stderr)
        return 1
    heat = next(line.strip() for line in ini.splitlines() if line.startswith("#define HEAT_DELTA"))
    code = HARNESS.replace("@HEAT_DELTA@", heat)
    code = code.replace("@HOLD_STATE@", definition(source, "struct SuvidHoldState") + "\nstatic SuvidHoldState suvidHold;")
    code = code.replace("@DEVIATION_STATE@", definition(source, "struct SuvidDeviationState") + "\nstatic SuvidDeviationState suvidDeviation;")
    code = code.replace("@BODY@", snippet)
    with tempfile.TemporaryDirectory(prefix="samovar-suvid-s1-s3-") as temp:
        temp_path = Path(temp)

        def compile_and_run(name, source_code, show_output=True):
            cpp = temp_path / f"{name}.cpp"
            binary = temp_path / name
            cpp.write_text(source_code, encoding="utf-8")
            result = subprocess.run(
                ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                 str(cpp), "-o", str(binary)],
                capture_output=True,
                text=True,
            )
            if result.returncode:
                sys.stderr.write(result.stderr)
                return result.returncode
            return subprocess.run(
                [str(binary)],
                capture_output=not show_output,
                text=True,
            ).returncode

        result = compile_and_run("production", code)
        if result:
            return result

        mutant = code.replace(
            "if (TankSensor.avgTemp <= setpoint - HEAT_DELTA) suvidHeaterOn = true;",
            "if (TankSensor.avgTemp <= setpoint) suvidHeaterOn = true;",
            1,
        )
        if compile_and_run("mutant_band_lower_limit", mutant, False) == 0:
            print("FAIL: lower-band mutation survived Suvid S1 harness", file=sys.stderr)
            return 1
        mutant = code.replace(
            "suvidHold.inBand = false;",
            "suvidHold.inBand = suvidHold.inBand;",
            1,
        )
        if compile_and_run("mutant_hold_pause", mutant, False) == 0:
            print("FAIL: out-of-band hold pause mutation survived Suvid S1 harness", file=sys.stderr)
            return 1
        mutant = code.replace(
            "suvidHold.accumulatedMs += now - suvidHold.lastTickMs;",
            "suvidHold.accumulatedMs += now >= suvidHold.lastTickMs ? now - suvidHold.lastTickMs : 0;",
            1,
        )
        if mutant == code:
            print("FAIL: unable to build Suvid hold wrap mutation", file=sys.stderr)
            return 1
        if compile_and_run("mutant_hold_wrap", mutant, False) == 0:
            print("FAIL: hold wrap mutation survived Suvid S1 harness", file=sys.stderr)
            return 1
        mutant = code.replace(
            "(uint32_t)(now - suvidDeviation.sinceMs)",
            "(now >= suvidDeviation.sinceMs ? now - suvidDeviation.sinceMs : 0U)",
            1,
        )
        if mutant == code:
            print("FAIL: unable to build Suvid deviation wrap mutation", file=sys.stderr)
            return 1
        if compile_and_run("mutant_deviation_wrap", mutant, False) == 0:
            print("FAIL: deviation wrap mutation survived Suvid S1 harness", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
