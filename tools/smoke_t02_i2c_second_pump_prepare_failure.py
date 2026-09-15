#!/usr/bin/env python3
"""Extracted second-pump helper rejects preparation failure and splits finite/continuous."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
BODY = extract_function_body(SOURCE, "inline bool start_second_i2c_pump_steps")
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"

HARNESS = r'''
#include <cstdint>
#include <I2CStepperV3.h>
struct I2CStepperDevice {
  bool present;
  I2CStepperV3Config config;
  I2CStepperV3Motion motion;
};
I2CStepperDevice pump{};
I2CStepperDevice* selected = &pump;
I2CStepperDevice* i2c_stepper_selected_pump() { return selected; }
float i2c_get_speed_from_rate(float rate) { return rate * 10.0f; }
int finite = 0;
bool i2c_stepper_start_finite(I2CStepperDevice&) { finite++; return true; }
@FUNCTION@
int main() {
  pump.present = true;
  pump.config.stepsPerMl = 100;
  if (!start_second_i2c_pump_steps(2.0f, 1300) || finite != 1 ||
      pump.motion.mode != I2CSTEPPER_V3_MODE_FILLING || pump.motion.targetSteps != 1300) return 2;
  if (start_second_i2c_pump_steps(2.0f, 0)) return 3;
  selected = nullptr;
  return start_second_i2c_pump_steps(2.0f, 1300) ? 4 : 0;
}
'''


def main() -> int:
  function = "inline bool start_second_i2c_pump_steps(float rateLitersPerHour, uint32_t targetSteps) {" + BODY + "}"
  with tempfile.TemporaryDirectory(prefix="samovar-i2c-v3-second-pump-") as temp:
    cpp = Path(temp) / "test.cpp"
    binary = Path(temp) / "test"
    cpp.write_text(HARNESS.replace("@FUNCTION@", function), encoding="utf-8")
    result = subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL),
         str(cpp), "-o", str(binary)], capture_output=True, text=True, check=False)
    if result.returncode:
      print(result.stderr, end="")
      return result.returncode
    return subprocess.run([str(binary)], check=False).returncode


if __name__ == "__main__":
  raise SystemExit(main())
