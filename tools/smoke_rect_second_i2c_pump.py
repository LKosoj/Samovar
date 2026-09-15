#!/usr/bin/env python3
"""Контракт второго I2C-насоса ректификации на закреплённом v3-адресе."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
LOGIC = (ROOT / "logic.h").read_text(encoding="utf-8")
I2C = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
SAMOVAR = (ROOT / "Samovar.ino").read_text(encoding="utf-8")


def body(source: str, signature: str) -> str:
  return extract_function_body(source, signature)


def require(condition: bool, message: str) -> None:
  if not condition:
    raise AssertionError(message)


enabled = body(LOGIC, "inline bool rect_second_i2c_pump_enabled()")
require("SamSetup.UseSecondI2CPump" in enabled,
        "second pump remains opt-in")
require("i2c_stepper_selected_pump()" in enabled,
        "second pump must use the session-pinned pump")
require("use_I2C_dev" not in enabled,
        "startup singleton must not select a v3 pump")

start = body(I2C, "inline bool start_second_i2c_pump(")
start_steps = body(I2C, "inline bool start_second_i2c_pump_steps(")
require("i2c_stepper_selected_pump()" in start,
        "start must resolve only selected pump")
require("volumeMl == 0" in start and "i2c_stepper_start_continuous" in start,
        "zero volume must use the explicit continuous command")
require("targetSteps" in start_steps and "i2c_stepper_start_finite" in start_steps,
        "finite volume must pass exact target steps")
require("uint64_t(volumeMl) * device->config.stepsPerMl" in start and
        "start_second_i2c_pump_steps(rateLitersPerHour, uint32_t(targetSteps))" in start,
        "finite target must be calculated in steps without ml rounding")

stop = body(I2C, "inline bool stop_second_i2c_pump()")
require("i2c_stepper_selected_pump()" in stop and "i2c_stepper_stop" in stop,
        "stop must target the pinned device")

apply_row = body(LOGIC, "inline bool rect_apply_second_pump_for_row(")
require("row.WType == 'H'" in apply_row,
        "heads row must run a finite filling")
require('program_type_one_of(row.WType, "BC")' in apply_row,
        "body and pre-flood remain continuous")
require("rect_stop_second_i2c_pump_if_running()" in apply_row,
        "non-pump rows must confirm a stop")
pause = body(LOGIC, "inline bool rect_pause_second_i2c_pump()")
resume = body(LOGIC, "inline bool rect_resume_second_i2c_pump()")
require("rectSecondPumpPausedVolume = pump->status.remainingSteps;" in pause,
        "pause must retain uint32 remaining steps exactly")
require("start_second_i2c_pump_steps(rate, rectSecondPumpPausedVolume)" in resume,
        "resume must not turn remaining steps back into ml")

PAUSE_HARNESS = r'''
#include <cstdint>
struct I2CStepperDevice {
  bool present;
  struct { uint32_t stepsPerMl; } config;
  struct { uint32_t remainingSteps; } status;
};
I2CStepperDevice pump = {};
I2CStepperDevice* i2c_stepper_selected_pump() { return &pump; }
bool i2c_stepper_refresh(I2CStepperDevice&, bool) { return true; }
bool rectSecondPumpRunning = true;
bool rectSecondPumpHeadsRow = true;
bool rectSecondPumpHeadsFilling = true;
bool rectSecondPumpPaused = false;
uint32_t rectSecondPumpPausedVolume = 0;
uint32_t rectSecondPumpTargetSteps = 0;
bool stop_second_i2c_pump() { return true; }
bool rect_second_i2c_pump_enabled() { return true; }
struct { float SecondI2CPumpRate; } SamSetup = {1.0f};
struct WProgram { float Speed; };
WProgram program[1] = {{2.5f}};
uint8_t ProgramNum = 0;
uint32_t resumedSteps = 0;
bool start_second_i2c_pump_steps(float, uint32_t steps) {
  resumedSteps = steps;
  return true;
}
bool start_second_i2c_pump(float, uint16_t) { return true; }
@PAUSE@
@RESUME@
int main() {
  pump.present = true;
  pump.status.remainingSteps = 100000;
  if (!rect_pause_second_i2c_pump() || rectSecondPumpPausedVolume != 100000) return 1;
  if (!rect_resume_second_i2c_pump()) return 2;
  return resumedSteps == 100000 ? 0 : 3;
}
'''

pause_function = "inline bool rect_pause_second_i2c_pump() {" + pause + "}"
resume_function = "inline bool rect_resume_second_i2c_pump() {" + resume + "}"
with tempfile.TemporaryDirectory(prefix="samovar-rect-v3-pause-") as temp_dir:
  temp = Path(temp_dir)
  cpp = temp / "pause.cpp"
  binary = temp / "pause"
  cpp.write_text(PAUSE_HARNESS.replace("@PAUSE@", pause_function)
                 .replace("@RESUME@", resume_function), encoding="utf-8")
  compiled = subprocess.run(
      ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
      capture_output=True, text=True, check=False)
  if compiled.returncode:
    raise AssertionError("pause/resume harness compile failed: " + compiled.stderr)
  resumed = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
  if resumed.returncode:
    raise AssertionError("pause/resume changed exact remaining steps")

run_program = body(LOGIC, "void run_program(uint8_t num)")
require("rect_apply_second_pump_for_row(program[num])" in run_program,
        "every rectification row must apply selected-pump routing")
require("rect_fail_second_i2c_pump" in run_program,
        "command failure remains visible to the process")

require(SAMOVAR.index('#include "I2CStepper.h"') <
        SAMOVAR.index('#include "logic.h"'),
        "v3 declarations must precede rectification helpers")

print("OK: rectification uses pinned v3 pump, finite target and explicit continuous mode")
