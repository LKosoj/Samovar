#!/usr/bin/env python3
"""Extracted v3 finite-target helper preserves selected address, direction and steps."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
BODY = extract_function_body(SOURCE, "inline bool set_stepper_target")
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"

HARNESS = r'''
#include <cstdint>
#include <I2CStepperV3.h>
struct I2CStepperDevice {
  bool present;
  uint8_t address;
  I2CStepperV3Config config;
  I2CStepperV3Motion motion;
};
I2CStepperDevice pump{};
I2CStepperDevice* selected = nullptr;
I2CStepperDevice* i2c_stepper_selected_pump() { return selected; }
I2CStepperDevice mixer{};
I2CStepperDevice* i2c_stepper_selected_mixer() { return &mixer; }
int starts = 0, stops = 0;
int continuous = 0;
bool i2c_stepper_start_finite(I2CStepperDevice&) { starts++; return true; }
bool i2c_stepper_start_continuous(I2CStepperDevice&) { continuous++; return true; }
bool i2c_stepper_stop(I2CStepperDevice&) { stops++; return true; }
@FUNCTION@
@TIME_FUNCTION@
int main() {
  pump.address = 2;
  pump.present = true;
  selected = &pump;
  if (!set_stepper_target(123, 1, 125, true)) return 1;
  if (starts != 1 || stops != 0 || pump.config.mode != I2CSTEPPER_V3_MODE_FILLING ||
      pump.motion.mode != I2CSTEPPER_V3_MODE_FILLING || pump.motion.direction != 1 ||
      pump.motion.speedStepsPerSec != 123 || pump.motion.targetSteps != 125) return 2;
  if (!set_stepper_target(0, 0, 0, true) || stops != 1) return 3;
  pump.present = false;
  if (set_stepper_target(123, 0, 125, true) || starts != 1) return 4;
  pump.present = true;
  selected = nullptr;
  if (set_stepper_target(123, 0, 125, true)) return 5;
  mixer.present = false;
  if (set_stepper_by_time(123, 1, 0) || continuous != 0) return 6;
  mixer.present = true;
  if (!set_stepper_by_time(123, 1, 0) || continuous != 1 || starts != 1 ||
      mixer.motion.targetSteps != 0) return 7;
  if (!set_stepper_by_time(123, 1, 2) || starts != 2 ||
      mixer.motion.targetSteps != 246) return 8;
  return 0;
}
'''


def main() -> int:
  function = (
      "inline bool set_stepper_target(uint32_t speedStepsPerSecond, uint8_t direction, "
      "uint32_t targetSteps, bool requireI2c) {" + BODY + "}")
  time_function = (
      "inline bool set_stepper_by_time(uint32_t speedStepsPerSecond, uint8_t direction, "
      "uint32_t seconds) {" + extract_function_body(SOURCE, "inline bool set_stepper_by_time") + "}")
  with tempfile.TemporaryDirectory(prefix="samovar-i2c-v3-target-") as temp:
    cpp = Path(temp) / "test.cpp"
    binary = Path(temp) / "test"
    cpp.write_text(HARNESS.replace("@FUNCTION@", function).replace("@TIME_FUNCTION@", time_function), encoding="utf-8")
    result = subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL),
         str(cpp), "-o", str(binary)], capture_output=True, text=True, check=False)
    if result.returncode:
      print(result.stderr, end="")
      return result.returncode
    return subprocess.run([str(binary)], check=False).returncode


if __name__ == "__main__":
  raise SystemExit(main())
