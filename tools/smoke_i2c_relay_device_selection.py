#!/usr/bin/env python3
"""Проверяет выбор реле среди закреплённых v3-устройств из реального исходника."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_INCLUDE = ROOT / "libraries" / "I2CStepperProtocol" / "src"

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <I2CStepperV3.h>

struct I2CStepperDevice {
  bool present;
  uint8_t capabilities;
};

I2CStepperDevice* mixer = nullptr;
I2CStepperDevice* pump = nullptr;
I2CStepperDevice* i2c_stepper_selected_mixer() { return mixer; }
I2CStepperDevice* i2c_stepper_selected_pump() { return pump; }

@FUNCTION@

static int failures = 0;
static void check(bool value, const char* text) {
  if (!value) { std::cerr << "FAIL: " << text << '\n'; failures++; }
}

int main() {
  I2CStepperDevice mixerDevice{true, I2CSTEPPER_V3_CAP_RELAY};
  I2CStepperDevice pumpDevice{true, I2CSTEPPER_V3_CAP_RELAY};

  mixer = &mixerDevice;
  pump = &pumpDevice;
  check(select_relay_capable_device() == &mixerDevice,
        "закреплённая мешалка с relay имеет приоритет");

  mixerDevice.capabilities = 0;
  check(select_relay_capable_device() == &pumpDevice,
        "закреплённый насос выбирается, если у мешалки нет relay");

  mixer = nullptr;
  pump = nullptr;
  check(select_relay_capable_device() == nullptr,
        "нет закреплённого устройства — нет скрытого fallback");

  return failures == 0 ? 0 : 1;
}
'''


def main() -> int:
  source = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
  signature = "inline I2CStepperDevice* select_relay_capable_device()"
  try:
    body = extract_function_body(source, signature)
  except ValueError as exc:
    print(f"FAIL: {exc}", file=sys.stderr)
    return 1
  function = "I2CStepperDevice* select_relay_capable_device() {" + body + "}"
  with tempfile.TemporaryDirectory(prefix="samovar-i2c-relay-") as temp_dir:
    source_path = Path(temp_dir) / "test.cpp"
    binary_path = Path(temp_dir) / "test"
    source_path.write_text(HARNESS.replace("@FUNCTION@", function), encoding="utf-8")
    compiled = subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
         "-I", str(PROTOCOL_INCLUDE), str(source_path), "-o", str(binary_path)],
        capture_output=True, text=True, check=False)
    if compiled.returncode:
      sys.stderr.write(compiled.stdout + compiled.stderr)
      return compiled.returncode
    return subprocess.run([str(binary_path)], check=False).returncode


if __name__ == "__main__":
  raise SystemExit(main())
