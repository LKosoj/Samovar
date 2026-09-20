#!/usr/bin/env python3
"""Source-derived v3 address selection/pinning plus FakeWire atomicity gate."""

import subprocess
import re
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"
SCAN_MATCH = re.search(r"^#define I2CSTEPPER_SCAN_MS (\d+)UL$", SOURCE, re.MULTILINE)
if not SCAN_MATCH or int(SCAN_MATCH.group(1)) != 100:
  raise AssertionError("I2CStepper scan period must remain 100 ms")
SCAN_MS = SCAN_MATCH.group(1)


def function(lookup: str, definition: str) -> str:
  return definition + " {" + extract_function_body(SOURCE, lookup) + "}"


HARNESS = r'''
#include <cstdint>
#include <I2CStepperV3.h>
#define I2CSTEPPER_DEVICE_COUNT 10U
#define I2CSTEPPER_HEARTBEAT_MS 250UL
#define I2CSTEPPER_SCAN_MS @SCAN_MS@UL
struct I2CStepperDevice { bool present; uint8_t address; uint32_t lastHeartbeatMs; };
I2CStepperDevice i2cSteppers[10] = {};
uint32_t i2cStepperLastScanMs = 0;
volatile bool i2cStepperScanActive = true;
uint8_t i2cStepperSessionMixerAddress = 0;
uint8_t i2cStepperSessionPumpAddress = 0;
bool PowerOn = true;
int16_t startval = 1;
static constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;
@LOOKUP@
@LOWEST@
@SESSION@
@SESSION_END_FUNCTION@
@SESSION_ACTIVE@
@SELECTED_MIXER@
@SELECTED_PUMP@
@SESSION_END@
int scanCalls = 0;
void i2c_stepper_scan_step() { scanCalls++; }
uint32_t nowMs = 250;
uint32_t millis() { return nowMs; }
uint8_t heartbeatAddresses[10] = {};
uint8_t heartbeatCount = 0;
uint8_t heartbeatFailureAddress = 0;
int configSyncs = 0;
void i2c_stepper_sync_config(I2CStepperDevice&) { configSyncs++; }
bool i2c_stepper_send_heartbeat(I2CStepperDevice& device) {
  heartbeatAddresses[heartbeatCount++] = device.address;
  return device.address != heartbeatFailureAddress;
}
@TICK@
int main() {
  for (uint8_t address = 1; address <= 10; address++)
    i2cSteppers[address - 1].address = address;
  i2cSteppers[2].present = true;  // 3
  i2cSteppers[8].present = true;  // 9
  i2cSteppers[3].present = true;  // 4
  i2cSteppers[9].present = true;  // 10
  if (i2c_stepper_lowest_present(true)->address != 3) return 1;
  if (i2c_stepper_lowest_present(false)->address != 4) return 2;
  i2c_stepper_session_begin();
  if (i2cStepperSessionMixerAddress != 3 || i2cStepperSessionPumpAddress != 4) return 3;
  i2cSteppers[3].present = false; // selected address is lost; no automatic switch to 10
  if (i2c_stepper_selected_pump()->address != 4) return 4;
  startval = SAMOVAR_STARTVAL_IDLE;
  if (!i2c_stepper_session_active()) return 5;
  i2c_stepper_session_end_if_idle();
  if (i2cStepperSessionPumpAddress != 4) return 6;
  PowerOn = false;
  if (i2c_stepper_session_active()) return 7;
  i2c_stepper_session_end_if_idle();
  if (i2cStepperSessionPumpAddress != 0) return 8;
  if (i2c_stepper_selected_pump()->address != 10) return 9;
  if (i2c_stepper_selected_mixer()->address != 3) return 10;
  PowerOn = true;
  startval = 1;
  i2cSteppers[9].present = true;
  i2c_stepper_session_begin();
  if (i2cStepperSessionPumpAddress != 10) return 11;
  i2cSteppers[0].present = true;
  i2cSteppers[9].lastHeartbeatMs = 0;
  heartbeatFailureAddress = 9;
  i2c_stepper_tick();
  if (scanCalls != 1 || heartbeatCount != 4 || heartbeatAddresses[0] != 1 ||
      heartbeatAddresses[1] != 3 || heartbeatAddresses[2] != 9 ||
      heartbeatAddresses[3] != 10) return 12;
  if (i2cSteppers[0].lastHeartbeatMs != 250 ||
      i2cSteppers[2].lastHeartbeatMs != 250 ||
      i2cSteppers[8].lastHeartbeatMs != 0 ||
      i2cSteppers[9].lastHeartbeatMs != 250) return 13;
  for (uint8_t index = 0; index < 10; index++) i2cSteppers[index].present = false;
  i2cSteppers[0].present = true;
  i2cSteppers[0].lastHeartbeatMs = 50;
  nowMs = 300;
  i2c_stepper_tick();
  if (scanCalls != 1 || heartbeatCount != 5 ||
      i2cSteppers[0].lastHeartbeatMs != 300) return 14;
  i2cSteppers[0].present = false;
  nowMs = 350;
  i2c_stepper_tick();
  if (scanCalls != 2 || heartbeatCount != 5) return 15;
  i2cStepperLastScanMs = 0xFFFFFFFFUL - (I2CSTEPPER_SCAN_MS / 2);
  nowMs = (I2CSTEPPER_SCAN_MS / 2) - 2;
  i2c_stepper_tick();
  if (scanCalls != 2) return 16;
  nowMs = (I2CSTEPPER_SCAN_MS / 2) - 1;
  i2c_stepper_tick();
  return scanCalls == 3 ? 0 : 17;
}
'''


def run_selection() -> tuple[int, str]:
  source = HARNESS
  replacements = {
      "@SCAN_MS@": SCAN_MS,
      "@LOOKUP@": function(
          "inline I2CStepperDevice* i2c_stepper_device",
          "inline I2CStepperDevice* i2c_stepper_device(uint8_t address)"),
      "@LOWEST@": function(
          "inline I2CStepperDevice* i2c_stepper_lowest_present",
          "inline I2CStepperDevice* i2c_stepper_lowest_present(bool mixer)"),
      "@SESSION@": function(
          "inline void i2c_stepper_session_begin",
          "inline void i2c_stepper_session_begin()"),
      "@SELECTED_PUMP@": function(
      "inline I2CStepperDevice* i2c_stepper_selected_pump",
      "inline I2CStepperDevice* i2c_stepper_selected_pump()"),
      "@SESSION_ACTIVE@": function(
      "inline bool i2c_stepper_session_active",
      "inline bool i2c_stepper_session_active()"),
      "@SELECTED_MIXER@": function(
          "inline I2CStepperDevice* i2c_stepper_selected_mixer",
          "inline I2CStepperDevice* i2c_stepper_selected_mixer()"),
      "@SESSION_END@": function(
          "inline void i2c_stepper_session_end_if_idle",
          "inline void i2c_stepper_session_end_if_idle()"),
      "@SESSION_END_FUNCTION@": function(
          "inline void i2c_stepper_session_end",
          "inline void i2c_stepper_session_end()"),
      "@TICK@": function(
          "inline void i2c_stepper_tick",
          "inline void i2c_stepper_tick()"),
  }
  for token, value in replacements.items():
    source = source.replace(token, value)
  with tempfile.TemporaryDirectory(prefix="samovar-i2c-v3-select-") as temp:
    cpp = Path(temp) / "test.cpp"
    binary = Path(temp) / "test"
    cpp.write_text(source, encoding="utf-8")
    built = subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL),
         str(cpp), "-o", str(binary)], capture_output=True, text=True, check=False)
    if built.returncode:
      return built.returncode, built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
    return ran.returncode, ran.stdout + ran.stderr


def main() -> int:
  code, output = run_selection()
  if code:
    print(output, end="", file=sys.stderr)
    return code
  atomic = subprocess.run(
      [sys.executable, str(ROOT / "tools/smoke_i2c_operation_results.py")],
      capture_output=True, text=True, check=False)
  if atomic.returncode:
    print(atomic.stdout + atomic.stderr, end="", file=sys.stderr)
    return atomic.returncode
  print("I2CStepper v3 selection and atomic FakeWire smoke passed")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
