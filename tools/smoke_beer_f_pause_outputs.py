#!/usr/bin/env python3
"""Production-derived regression for confirmed F-pause actuator shutdown."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "inline bool beer_pause_fermentation_outputs()"
SAFE_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_safe_lua_outputs()"
COOLING_PUMP_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_pump(bool active)"
COOLING_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_outputs(bool active)"

HARNESS_TEMPLATE = r'''
#include <iostream>

#define USE_WATER_PUMP

enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

static bool valve_status = false;
static bool beerCoolingPumpActive = false;
static bool heaterOutput = true;
static int heaterCalls = 0;
static int valveCalls = 0;
static int pumpCalls = 0;
static int mixerCalls = 0;
static ActuatorCommandResult valveResult = ACTUATOR_COMMAND_APPLIED;
static ActuatorCommandResult pumpResult = ACTUATOR_COMMAND_APPLIED;
static ActuatorCommandResult mixerResult = ACTUATOR_COMMAND_APPLIED;

void setHeaterPosition(bool state) {
  heaterOutput = state;
  heaterCalls++;
}

ActuatorCommandResult open_valve(bool state, bool) {
  valveCalls++;
  if (valveResult == ACTUATOR_COMMAND_APPLIED) valve_status = state;
  return valveResult;
}

ActuatorCommandResult set_pump_pwm(int) {
  pumpCalls++;
  return pumpResult;
}

ActuatorCommandResult set_mixer_state(bool, bool) {
  mixerCalls++;
  return mixerResult;
}

void request_emergency_stop(const char*) {}

@SAFE_OUTPUTS@

@HELPER@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  valve_status = true;
  beerCoolingPumpActive = true;
  heaterOutput = true;
  heaterCalls = valveCalls = pumpCalls = mixerCalls = 0;
  valveResult = pumpResult = mixerResult = ACTUATOR_COMMAND_APPLIED;
}

int main() {
  reset_fixture();
  check(beer_pause_fermentation_outputs(), "all acknowledged outputs must complete F pause");
  check(!heaterOutput && !valve_status && !beerCoolingPumpActive,
        "acknowledged F pause must leave safe outputs and clear cooling ownership");
  check(valveCalls == 1 && pumpCalls == 1 && mixerCalls == 1,
        "acknowledged F pause must command every actuator once");

  reset_fixture();
  valveResult = ACTUATOR_COMMAND_FAILED;
  check(!beer_pause_fermentation_outputs(), "valve failure must reject F pause");
  check(heaterCalls == 1 && valveCalls == 1 && pumpCalls == 2 && mixerCalls == 0,
        "valve failure must compensate pump shutdown and stop before mixer shutdown");
  check(beerCoolingPumpActive,
        "valve failure must not clear cooling ownership without pump acknowledgement");

  reset_fixture();
  pumpResult = ACTUATOR_COMMAND_FAILED;
  check(!beer_pause_fermentation_outputs(), "pump failure must reject F pause");
  check(valveCalls == 0 && pumpCalls == 1 && mixerCalls == 0,
        "pump failure must not attempt valve shutdown or advance to mixer shutdown");
  check(beerCoolingPumpActive,
        "pump failure must retain cooling ownership until APPLIED");

  reset_fixture();
  mixerResult = ACTUATOR_COMMAND_FAILED;
  check(!beer_pause_fermentation_outputs(), "mixer failure must reject F pause");
  check(!beerCoolingPumpActive,
        "confirmed pump shutdown must clear cooling ownership before mixer failure");

  return failures == 0 ? 0 : 1;
}
'''


def build_harness(source: str) -> str:
    helper = extract_function_body(source, SIGNATURE)
    safe_outputs = extract_function_body(source, SAFE_OUTPUTS_SIGNATURE)
    cooling_pump = extract_function_body(source, COOLING_PUMP_SIGNATURE)
    cooling_outputs = extract_function_body(source, COOLING_OUTPUTS_SIGNATURE)
    harness = HARNESS_TEMPLATE.replace(
        "@SAFE_OUTPUTS@",
        f"{COOLING_PUMP_SIGNATURE} {{\n{cooling_pump}\n}}\n\n"
        f"{COOLING_OUTPUTS_SIGNATURE} {{\n{cooling_outputs}\n}}\n\n"
        f"{SAFE_OUTPUTS_SIGNATURE} {{\n{safe_outputs}\n}}",
    )
    return harness.replace("@HELPER@", f"{SIGNATURE} {{\n{helper}\n}}")


def compile_and_run(harness: str, label: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-f-pause-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_f_pause_test.cpp"
        binary = temp / "beer_f_pause_test"
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


def main() -> int:
    beer = (ROOT / "beer.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(beer)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    code, _ = compile_and_run(harness, "beer F pause")
    if code:
        return 1

    mutation = harness.replace(
        "if (set_pump_pwm(active ? 1023 : 0) != ACTUATOR_COMMAND_APPLIED) {\n    return ACTUATOR_COMMAND_FAILED;\n  }\n  beerCoolingPumpActive = active;",
        "beerCoolingPumpActive = active;\n  if (set_pump_pwm(active ? 1023 : 0) != ACTUATOR_COMMAND_APPLIED) {\n    return ACTUATOR_COMMAND_FAILED;\n  }",
        1,
    )
    if mutation == harness:
        print("FAIL: could not build pump-ownership mutation", file=sys.stderr)
        return 1
    code, output = compile_and_run(mutation, "beer F pause ownership mutation", False)
    if code == 0 or "pump failure must retain cooling ownership until APPLIED" not in output:
        print("FAIL: pump-ownership mutation survived", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Beer F-pause mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
