#!/usr/bin/env python3
"""Source-derived gate for boot-once and manually requested I2CStepper scans."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
HEADER = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
SAMOVAR = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
SERVER = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
SETUP = (ROOT / "data_raw" / "setup.htm").read_text(encoding="utf-8")
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"


def function(lookup: str, definition: str) -> str:
  return definition + " {" + extract_function_body(HEADER, lookup) + "}"


HARNESS = r'''
#include <cstdint>
#include <I2CStepperV3.h>
#define I2CSTEPPER_DEVICE_COUNT 10U
#define I2CSTEPPER_HEARTBEAT_MS 250UL
#define I2CSTEPPER_SCAN_MS 100UL
struct I2CStepperDevice { bool present; uint8_t address; uint32_t lastHeartbeatMs; };
I2CStepperDevice i2cSteppers[10] = {};
uint8_t i2cStepperScanAddress = I2CSTEPPER_V3_ADDRESS_MIN;
uint32_t i2cStepperLastScanMs = 0;
volatile bool i2cStepperScanActive = true;
@DEVICE@
uint8_t probed[20] = {};
uint8_t probeCount = 0;
bool probeLockBusy = false;
bool i2c_stepper_probe(I2CStepperDevice& device, bool* lockBusyOut) {
  *lockBusyOut = probeLockBusy;
  if (probeLockBusy) return false;
  probed[probeCount++] = device.address;
  return true;
}
@SCAN_BEGIN@
@SCAN_STEP@
uint32_t nowMs = 0;
uint32_t millis() { return nowMs; }
uint8_t heartbeatCount = 0;
bool i2c_stepper_send_heartbeat(I2CStepperDevice&) {
  heartbeatCount++;
  return true;
}
@TICK@
int main() {
  for (uint8_t address = 1; address <= 10; address++)
    i2cSteppers[address - 1].address = address;
  nowMs = 99;
  i2c_stepper_tick();
  if (probeCount != 0) return 1;
  for (nowMs = 100; nowMs <= 1000; nowMs += 100) i2c_stepper_tick();
  if (probeCount != 10 || i2cStepperScanActive) return 2;
  for (uint8_t index = 0; index < 10; index++) {
    if (probed[index] != index + 1) return 3;
  }
  nowMs = 5000;
  i2c_stepper_tick();
  if (probeCount != 10) return 4;
  i2c_stepper_scan_begin();
  if (!i2cStepperScanActive || i2cStepperScanAddress != 1) return 5;
  // Занятая шина не должна «съедать» адрес: он проверяется повторно.
  probeLockBusy = true;
  nowMs = 5001;
  i2c_stepper_tick();
  if (probeCount != 10 || i2cStepperScanAddress != 1 || !i2cStepperScanActive) return 8;
  probeLockBusy = false;
  nowMs = 5101;
  i2c_stepper_tick();
  if (probeCount != 11 || probed[10] != 1 || i2cStepperScanAddress != 2) return 6;
  i2cStepperScanActive = false;
  i2cSteppers[1].present = true;
  i2cSteppers[1].lastHeartbeatMs = 0;
  nowMs = 5251;
  i2c_stepper_tick();
  return probeCount == 11 && heartbeatCount == 1 ? 0 : 7;
}
'''


def main() -> int:
  errors = []
  executor = extract_function_body(
      SAMOVAR[SAMOVAR.rfind("static OperationError execute_pending_i2c_stepper"):],
      "static OperationError execute_pending_i2c_stepper")
  require_ordered_tokens(
      "scan starts in loop before addressed device validation",
      executor,
      ['strcmp(command.cmd, "scan") == 0', "i2c_stepper_scan_begin();",
       "i2c_stepper_device(command.address)", "device->present"],
      errors)
  for source, token in (
      (SERVER, 'command != "scan"'),
      (SERVER, 'command == "scan" && request->params() != addressCount + commandCount'),
      (SERVER, "i2cStepperScanActive ? 1 : 0"),
      (SETUP, "rescanSetupI2c"),
      (SETUP, "Пересканировать I2C-устройства"),
      (SETUP, "if (setupI2cScanning) throw new Error"),
  ):
    if token not in source:
      errors.append("missing manual-scan contract token: " + token)
  if "id='i2cStepperSetupTab' type='button' class=\"tablinks\" value=\"I2CStepper\" hidden" in SETUP:
    errors.append("I2CStepper setup tab remains hidden without a discovered device")

  source = HARNESS
  for token, value in {
      "@DEVICE@": function(
          "inline I2CStepperDevice* i2c_stepper_device",
          "inline I2CStepperDevice* i2c_stepper_device(uint8_t address)"),
      "@SCAN_BEGIN@": function(
          "inline void i2c_stepper_scan_begin",
          "inline void i2c_stepper_scan_begin()"),
      "@SCAN_STEP@": function(
          "inline void i2c_stepper_scan_step",
          "inline void i2c_stepper_scan_step()"),
      "@TICK@": function(
          "inline void i2c_stepper_tick",
          "inline void i2c_stepper_tick()"),
  }.items():
    source = source.replace(token, value)
  def compile_and_run(candidate: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-manual-scan-") as temp:
      cpp = Path(temp) / "test.cpp"
      binary = Path(temp) / "test"
      cpp.write_text(candidate, encoding="utf-8")
      built = subprocess.run(
          ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL),
           str(cpp), "-o", str(binary)], capture_output=True, text=True, check=False)
      if built.returncode:
        return built.returncode, built.stderr
      ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
      return ran.returncode, ran.stdout + ran.stderr

  result, output = compile_and_run(source)
  if result:
    errors.append(f"manual scan harness failed with {result}: {output}")
  for label, old, new in (
      ("continuous scan", "if (i2cStepperScanActive &&", "if ("),
      ("scan never completes", "i2cStepperScanActive = false;", "i2cStepperScanActive = true;"),
  ):
    mutated = source.replace(old, new, 1)
    if label == "continuous scan":
      mutated = mutated.replace("if (!i2cStepperScanActive) return;", "", 1)
    if mutated == source:
      errors.append("mutation setup failed: " + label)
      continue
    mutation_result, _ = compile_and_run(mutated)
    if mutation_result == 0:
      errors.append("mutation survived: " + label)
  if errors:
    raise SystemExit("\n".join(errors))
  print("I2CStepper boot-once and manual scan smoke passed")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
