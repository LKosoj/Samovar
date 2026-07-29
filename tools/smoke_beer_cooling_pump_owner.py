#!/usr/bin/env python3
"""Production-derived C/F ownership contract for the Beer cooling pump."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body


ROOT = Path(__file__).resolve().parents[1]
COOLING_PUMP_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_pump(bool active)"
COOLING_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_outputs(bool active)"
COOLING_DEMAND_SIGNATURE = "inline bool beer_cooling_pump_demanded()"

HARNESS_TEMPLATE = r'''
#include <iostream>

#define USE_WATER_PUMP

enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

struct WProgram { float Temp = 0; };
static WProgram program[1];
static unsigned char ProgramNum = 0;
static bool valve_status = false;
static bool PowerOn = true;
static bool beerCoolingPumpActive = false;
static bool beerManualPause = false;
static unsigned long begintime = 0;
static float temp = 0;
static float tempDelta = 0.3f;
unsigned long millis() { return 1000; }

static ActuatorCommandResult pumpResult = ACTUATOR_COMMAND_APPLIED;
static int pumpCalls = 0;
static float lastPumpPwm = -1;
ActuatorCommandResult set_pump_pwm(float duty) {
  pumpCalls++;
  lastPumpPwm = duty;
  return pumpResult;
}

static int valveCalls = 0;
static ActuatorCommandResult valveResult = ACTUATOR_COMMAND_APPLIED;
ActuatorCommandResult open_valve(bool state, bool) {
  valveCalls++;
  if (valveResult == ACTUATOR_COMMAND_APPLIED) valve_status = state;
  return valveResult;
}

void setHeaterPosition(bool) {}
void set_heater_state(float, float) {}
bool beer_pause_fermentation_outputs() { return true; }
static int abortCalls = 0;
void beer_abort_config_error(const char*) { abortCalls++; }
static int emergencyCalls = 0;
static bool heaterSafetyLatched = false;
void request_emergency_stop(const char*) {
  emergencyCalls++;
  heaterSafetyLatched = true;
}
bool heater_safety_latched() { return heaterSafetyLatched; }
static int runBeerCalls = 0;
void run_beer_program(unsigned char) { runBeerCalls++; }

@COOLING_PUMP@

@COOLING_DEMAND@

@COOLING_OUTPUTS@

static void run_f_branch() {
@F_BRANCH@
}

static void run_c_branch() {
@C_BRANCH@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  program[0].Temp = 20;
  valve_status = false;
  PowerOn = true;
  beerCoolingPumpActive = false;
  beerManualPause = false;
  begintime = 0;
  temp = 25;
  tempDelta = 0.3f;
  pumpResult = ACTUATOR_COMMAND_APPLIED;
  valveResult = ACTUATOR_COMMAND_APPLIED;
  pumpCalls = 0;
  lastPumpPwm = -1;
  valveCalls = 0;
  abortCalls = 0;
  emergencyCalls = 0;
  heaterSafetyLatched = false;
  runBeerCalls = 0;
}

int main() {
  reset_fixture();
  check(beer_set_cooling_outputs(true) == ACTUATOR_COMMAND_APPLIED &&
            valve_status && beerCoolingPumpActive && lastPumpPwm == 1023,
        "подтверждённый старт охлаждения не опубликовал оба выхода");

  reset_fixture();
  valveResult = ACTUATOR_COMMAND_FAILED;
  check(beer_set_cooling_outputs(true) == ACTUATOR_COMMAND_FAILED &&
            !valve_status && !beerCoolingPumpActive && emergencyCalls == 1,
        "неподтверждённое открытие клапана не остановило охлаждение аварийно");

  reset_fixture();
  pumpResult = ACTUATOR_COMMAND_FAILED;
  check(beer_set_cooling_outputs(true) == ACTUATOR_COMMAND_FAILED &&
            !valve_status && !beerCoolingPumpActive && emergencyCalls == 1,
        "неподтверждённый старт насоса не откатил клапан аварийно");

  reset_fixture();
  valve_status = true;
  beerCoolingPumpActive = true;
  check(beer_set_cooling_outputs(false) == ACTUATOR_COMMAND_APPLIED &&
            !valve_status && !beerCoolingPumpActive,
        "подтверждённая остановка охлаждения не сбросила оба выхода");

  reset_fixture();
  valve_status = true;
  beerCoolingPumpActive = true;
  pumpResult = ACTUATOR_COMMAND_FAILED;
  check(beer_set_cooling_outputs(false) == ACTUATOR_COMMAND_FAILED &&
            valve_status && beerCoolingPumpActive && emergencyCalls == 1,
        "неподтверждённая остановка насоса скрыла активное охлаждение");

  reset_fixture();
  valve_status = true;
  beerCoolingPumpActive = true;
  valveResult = ACTUATOR_COMMAND_FAILED;
  check(beer_set_cooling_outputs(false) == ACTUATOR_COMMAND_FAILED &&
            valve_status && beerCoolingPumpActive && emergencyCalls == 1,
        "неподтверждённое закрытие клапана не восстановило насос аварийно");

  reset_fixture();
  run_f_branch();
  check(valve_status && beerCoolingPumpActive && emergencyCalls == 0,
        "F не зафиксировал подтверждённый запуск охлаждения");

  reset_fixture();
  valveResult = ACTUATOR_COMMAND_FAILED;
  run_f_branch();
  check(!valve_status && !beerCoolingPumpActive && emergencyCalls == 1,
        "F продолжил работу после неподтверждённого открытия клапана");

  reset_fixture();
  pumpResult = ACTUATOR_COMMAND_FAILED;
  run_f_branch();
  check(!valve_status && !beerCoolingPumpActive && emergencyCalls == 1,
        "F продолжил работу после неподтверждённого запуска насоса");

  reset_fixture();
  temp = 25;
  run_c_branch();
  check(valve_status && beerCoolingPumpActive && begintime != 0 &&
            emergencyCalls == 0 && runBeerCalls == 0,
        "C не зафиксировал подтверждённый старт без перехода строки");

  reset_fixture();
  temp = 25;
  valveResult = ACTUATOR_COMMAND_FAILED;
  run_c_branch();
  check(!valve_status && !beerCoolingPumpActive && begintime == 0 &&
            emergencyCalls == 1 && runBeerCalls == 0,
        "C изменил таймер или строку после неподтверждённого открытия клапана");

  reset_fixture();
  temp = 25;
  pumpResult = ACTUATOR_COMMAND_FAILED;
  run_c_branch();
  check(!valve_status && !beerCoolingPumpActive && begintime == 0 &&
            emergencyCalls == 1 && runBeerCalls == 0,
        "C изменил таймер или строку после неподтверждённого старта насоса");

  reset_fixture();
  begintime = 1;
  temp = 20;
  valve_status = true;
  beerCoolingPumpActive = true;
  run_c_branch();
  check(!valve_status && !beerCoolingPumpActive && emergencyCalls == 0 && runBeerCalls == 1,
        "C не перешёл после подтверждённой остановки");

  reset_fixture();
  begintime = 1;
  temp = 20;
  valve_status = true;
  beerCoolingPumpActive = true;
  pumpResult = ACTUATOR_COMMAND_FAILED;
  run_c_branch();
  check(valve_status && beerCoolingPumpActive && emergencyCalls == 1 && runBeerCalls == 0,
        "C перешёл после неподтверждённой остановки");

  reset_fixture();
  begintime = 1;
  temp = 20;
  valve_status = true;
  beerCoolingPumpActive = true;
  valveResult = ACTUATOR_COMMAND_FAILED;
  run_c_branch();
  check(valve_status && beerCoolingPumpActive && emergencyCalls == 1 && runBeerCalls == 0,
        "C перешёл после неподтверждённого закрытия клапана");

  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(harness: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-cooling-owner-") as temp_dir:
        source = Path(temp_dir) / "beer_cooling_owner.cpp"
        binary = Path(temp_dir) / "beer_cooling_owner"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            return compiled.returncode, compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def main() -> int:
    beer = (ROOT / "beer.h").read_text(encoding="utf-8")
    try:
        stage = extract_function_body(beer, "void beer_stage_tick()")
        if "lastBeerTickMs = nowMs;\n\n  if (heater_safety_latched()) return;" not in stage:
            print("FAIL: beer_stage_tick должен прекращать обработку после аварии исполнительного механизма", file=sys.stderr)
            return 1
        f_branch, _ = extract_braced_block_after(stage, "if (currentType == 'F') {")
        c_branch, _ = extract_braced_block_after(stage, "if (currentType == 'C') {")
        helper = extract_function_body(beer, COOLING_PUMP_SIGNATURE)
        demand_helper = extract_function_body(beer, COOLING_DEMAND_SIGNATURE)
        outputs_helper = extract_function_body(beer, COOLING_OUTPUTS_SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = HARNESS_TEMPLATE.replace(
        "@COOLING_PUMP@", f"{COOLING_PUMP_SIGNATURE} {{\n{helper}\n}}"
    ).replace(
        "@COOLING_DEMAND@", f"{COOLING_DEMAND_SIGNATURE} {{\n{demand_helper}\n}}"
    ).replace(
        "@COOLING_OUTPUTS@", f"{COOLING_OUTPUTS_SIGNATURE} {{\n{outputs_helper}\n}}"
    ).replace("@F_BRANCH@", f_branch).replace("@C_BRANCH@", c_branch)
    code, output = compile_and_run(harness)
    sys.stdout.write(output)
    if code:
        return code

    mutant = harness.replace(
        "if (set_pump_pwm(active ? 1023 : 0) != ACTUATOR_COMMAND_APPLIED) {\n    return ACTUATOR_COMMAND_FAILED;\n  }\n  beerCoolingPumpActive = active;",
        "beerCoolingPumpActive = active;\n  if (set_pump_pwm(active ? 1023 : 0) != ACTUATOR_COMMAND_APPLIED) {\n    return ACTUATOR_COMMAND_FAILED;\n  }",
        1,
    )
    if mutant == harness:
        print("FAIL: не удалось создать мутацию ownership насоса", file=sys.stderr)
        return 1
    code, output = compile_and_run(mutant)
    if code == 0 or "неподтверждённый старт насоса не откатил клапан" not in output:
        print("FAIL: мутация ownership насоса пережила тест", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Beer cooling-pump ownership mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
