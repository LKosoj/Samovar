#!/usr/bin/env python3
"""Pinned v3 presence loss uses extracted source and emits one address-specific alarm."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
BODY = extract_function_body(SOURCE, "inline void i2c_stepper_note_refresh_failure")

HARNESS = r'''
#include <cstdint>
#include <iostream>
class String {
 public:
  String(const char*) {}
  String(uint8_t) {}
};
String operator+(const String&, uint8_t) { return String(""); }
#define F(value) value
enum { ALARM_MSG = 0 };
int messages = 0;
void SendMsg(const String&, int) { messages++; }
struct I2CStepperDevice { bool present; uint8_t address; };
uint8_t i2cStepperSessionMixerAddress = 0;
uint8_t i2cStepperSessionPumpAddress = 0;
@FUNCTION@
int main() {
  I2CStepperDevice selected{true, 2};
  i2cStepperSessionPumpAddress = 2;
  i2c_stepper_note_refresh_failure(selected);
  if (selected.present || messages != 1) return 1;
  i2c_stepper_note_refresh_failure(selected);
  if (messages != 1) return 2;
  I2CStepperDevice unrelated{true, 4};
  i2c_stepper_note_refresh_failure(unrelated);
  return (!unrelated.present && messages == 1) ? 0 : 3;
}
'''


def main() -> int:
  function = "inline void i2c_stepper_note_refresh_failure(I2CStepperDevice& device) {" + BODY + "}"
  with tempfile.TemporaryDirectory(prefix="samovar-i2c-v3-presence-") as temp:
    cpp = Path(temp) / "test.cpp"
    binary = Path(temp) / "test"
    cpp.write_text(HARNESS.replace("@FUNCTION@", function), encoding="utf-8")
    result = subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
        capture_output=True, text=True, check=False)
    if result.returncode:
      print(result.stderr, end="")
      return result.returncode
    return subprocess.run([str(binary)], check=False).returncode


if __name__ == "__main__":
  raise SystemExit(main())
