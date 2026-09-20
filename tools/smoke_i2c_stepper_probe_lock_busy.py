#!/usr/bin/env python3
"""Source-derived probe regression: a busy I2C lock is not a lost Nano."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"


def function(lookup: str, definition: str) -> str:
  return definition + " {" + extract_function_body(SOURCE, lookup) + "}"


HARNESS = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <vector>
#include <I2CStepperV3.h>

using TickType_t = uint32_t;
using SemaphoreHandle_t = int*;
static int fakeSemaphore;
static SemaphoreHandle_t xI2CSemaphore = &fakeSemaphore;
static const int pdTRUE = 1;
static const int portTICK_PERIOD_MS = 1;
int takeCalls = 0;
int busyOnTake = 0;
std::vector<TickType_t> semaphoreWaits;
int xSemaphoreTake(SemaphoreHandle_t, TickType_t wait) {
  semaphoreWaits.push_back(wait);
  takeCalls++;
  return takeCalls == busyOnTake ? 0 : pdTRUE;
}
void xSemaphoreGive(SemaphoreHandle_t) {}

#define I2C_LOCK_WAIT_MS 1000
#define I2C_CACHE_LOCK_WAIT_MS 10
struct I2CStepperDevice {
  bool present;
  bool everPresent;
  uint8_t address;
  uint8_t capabilities;
  I2CStepperV3Config config;
  I2CStepperV3StatusSnapshot status;
  uint32_t lastStopEventSeq;
  uint32_t configGeneration;
};
int notedFailures = 0;
void i2c_stepper_note_refresh_failure(I2CStepperDevice& device) {
  notedFailures++;
  device.present = false;
}

class FakeWire {
 public:
  uint8_t currentReg = 0;
  std::vector<uint8_t> rx;
  size_t readAt = 0;
  bool failRead = false;

  void beginTransmission(uint8_t) {}
  size_t write(uint8_t value) { currentReg = value; return 1; }
  int endTransmission(bool = true) { return 0; }
  uint8_t requestFrom(uint8_t, uint8_t len) {
    if (failRead) return 0;
    rx.assign(len, 0);
    I2CStepperV3Identity identity{};
    identity.address = 2;
    identity.capabilities = I2CSTEPPER_V3_CAP_PUMP | I2CSTEPPER_V3_CAP_FILLING;
    I2CStepperV3Config config{};
    config.address = 2;
    config.mode = I2CSTEPPER_V3_MODE_PUMP;
    config.stepsPerMl = 100;
    I2CStepperV3StatusSnapshot status{};
    status.address = 2;
    status.mode = I2CSTEPPER_V3_MODE_PUMP;
    status.generation = 1;
    if (currentReg == I2CSTEPPER_V3_REG_IDENTITY)
      i2cstepper_v3_encode_identity(rx.data(), &identity);
    else if (currentReg == I2CSTEPPER_V3_REG_CONFIG_A)
      i2cstepper_v3_encode_config_a(rx.data(), &config);
    else if (currentReg == I2CSTEPPER_V3_REG_CONFIG_B)
      i2cstepper_v3_encode_config_b(rx.data(), &config);
    else if (currentReg == I2CSTEPPER_V3_REG_STATUS)
      i2cstepper_v3_encode_status(rx.data(), &status);
    readAt = 0;
    return len;
  }
  int read() { return readAt < rx.size() ? rx[readAt++] : -1; }
} Wire;

@READ_BLOCK@
@READ_IDENTITY@
@READ_CONFIG@
bool i2c_stepper_refresh(I2CStepperDevice&, bool, TickType_t, bool, bool*) {
  return true;
}
@PROBE@

int main() {
  I2CStepperDevice device{};
  device.address = 2;
  device.present = true;

  // Identity is read first; the following config read sees the occupied semaphore.
  busyOnTake = 2;
  bool lockBusy = false;
  if (i2c_stepper_probe(device, &lockBusy) || !lockBusy) return 1;
  if (!device.present || notedFailures != 0 || semaphoreWaits.size() != 2 ||
      semaphoreWaits[0] != I2C_CACHE_LOCK_WAIT_MS ||
      semaphoreWaits[1] != I2C_CACHE_LOCK_WAIT_MS) return 2;

  takeCalls = 0;
  busyOnTake = 0;
  semaphoreWaits.clear();
  notedFailures = 0;
  device.present = true;
  Wire.failRead = true;
  lockBusy = true;
  if (i2c_stepper_probe(device, &lockBusy) || lockBusy) return 3;
  return !device.present && notedFailures == 1 ? 0 : 4;
}
'''


def build_source() -> str:
  source = HARNESS
  replacements = {
      "@READ_BLOCK@": function(
          "inline bool i2c_stepper_read_block",
          "inline bool i2c_stepper_read_block(uint8_t address, uint8_t reg, uint8_t* data, uint8_t len, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS, bool* lockBusy = nullptr)"),
      "@READ_IDENTITY@": function(
          "inline bool i2c_stepper_read_identity",
          "inline bool i2c_stepper_read_identity(I2CStepperDevice& device, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS, bool* lockBusy = nullptr)"),
      "@READ_CONFIG@": function(
          "inline bool i2c_stepper_read_config",
          "inline bool i2c_stepper_read_config(I2CStepperDevice& device, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS, bool* lockBusy = nullptr)"),
      "@PROBE@": function(
          "inline bool i2c_stepper_probe",
          "inline bool i2c_stepper_probe(I2CStepperDevice& device, bool* lockBusyOut = nullptr)"),
  }
  for token, value in replacements.items():
    source = source.replace(token, value)
  return source


def compile_and_run(source: str) -> tuple[int, str]:
  with tempfile.TemporaryDirectory(prefix="samovar-i2c-v3-probe-") as temp:
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
  errors = []
  source = build_source()
  code, output = compile_and_run(source)
  if code:
    errors.append("FakeSemaphore probe harness failed:\n" + output)
  mutation = source.replace(
      "if (!lockBusy) i2c_stepper_note_refresh_failure(device);",
      "i2c_stepper_note_refresh_failure(device);")
  mutation_code, _ = compile_and_run(mutation)
  if mutation == source or mutation_code == 0:
    errors.append("busy-lock presence mutation survived")
  if errors:
    print("I2CStepper probe lock-busy smoke failed:")
    for error in errors:
      print(" - " + error)
    return 1
  print("I2CStepper probe lock-busy FakeSemaphore smoke passed")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
