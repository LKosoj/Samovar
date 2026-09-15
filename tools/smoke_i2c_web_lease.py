#!/usr/bin/env python3
"""Browser lease must stop only the leased address after three missed renewals."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "Samovar.ino").read_text(encoding="utf-8", errors="ignore")
errors: list[str] = []


def body(signature: str) -> str:
    try:
        return extract_function_body(SOURCE, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


begin = body("static void i2c_stepper_web_lease_begin")
touch = body("void i2c_stepper_web_lease_touch")
clear = body("static void i2c_stepper_web_lease_clear")
tick = body("static void tick_i2c_stepper_web_lease")
if "6000UL" not in tick or "i2c_stepper_stop(device)" not in tick or "STATUS_CALIBRATION" not in tick:
    errors.append("browser lease must use the six-second deadline and STOP")

HARNESS = r'''
#include <cstdint>
#include <iostream>

static const uint8_t I2CSTEPPER_DEVICE_COUNT = 10;
static const uint8_t I2CSTEPPER_V3_ADDRESS_MIN = 1;
static const uint8_t I2CSTEPPER_V3_ADDRESS_MAX = 10;
static const uint32_t I2CSTEPPER_V3_STATUS_CALIBRATION = 2;
struct I2CStepperStatus { uint32_t status; };
struct I2CStepperDevice { bool present; I2CStepperStatus status; };
static volatile uint32_t i2cStepperWebLeaseMs[I2CSTEPPER_DEVICE_COUNT] = {};
static volatile bool i2cStepperWebLeaseActive[I2CSTEPPER_DEVICE_COUNT] = {};
static I2CStepperDevice i2cSteppers[I2CSTEPPER_DEVICE_COUNT] = {};
static uint32_t fakeMillis = 0;
static uint32_t stopCalls = 0;
static bool stopSucceeds = true;
static uint32_t millis() { return fakeMillis; }
static bool i2cstepper_v3_address_valid(uint8_t address) {
  return address >= I2CSTEPPER_V3_ADDRESS_MIN && address <= I2CSTEPPER_V3_ADDRESS_MAX;
}
static bool i2c_stepper_stop(I2CStepperDevice&) { stopCalls++; return stopSucceeds; }

static void i2c_stepper_web_lease_begin(uint8_t address) {@BEGIN@}
void i2c_stepper_web_lease_touch(uint8_t address) {@TOUCH@}
static void i2c_stepper_web_lease_clear(uint8_t address) {@CLEAR@}
static void tick_i2c_stepper_web_lease() {@TICK@}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}
int main() {
  i2cSteppers[1].present = true;
  i2cSteppers[1].status.status = I2CSTEPPER_V3_STATUS_CALIBRATION;
  i2cSteppers[3].present = true;
  i2cSteppers[3].status.status = I2CSTEPPER_V3_STATUS_CALIBRATION;
  fakeMillis = 100;
  i2c_stepper_web_lease_touch(2);
  check(!i2cStepperWebLeaseActive[1], "a page cannot create a calibration lease");
  i2c_stepper_web_lease_begin(2);
  i2c_stepper_web_lease_touch(2);
  fakeMillis = 200;
  i2c_stepper_web_lease_begin(4);
  check(i2cStepperWebLeaseActive[1], "address 2 must become leased");
  fakeMillis = 6100;
  tick_i2c_stepper_web_lease();
  check(stopCalls == 0 && i2cStepperWebLeaseActive[1], "exact six seconds is not three missed renewals");
  fakeMillis = 6101;
  tick_i2c_stepper_web_lease();
  check(stopCalls == 1 && !i2cStepperWebLeaseActive[1] && i2cStepperWebLeaseActive[3],
        "expired lease must STOP only its address");
  i2c_stepper_web_lease_clear(4);
  fakeMillis = 7000;
  i2c_stepper_web_lease_begin(2);
  stopSucceeds = false;
  fakeMillis = 13001;
  tick_i2c_stepper_web_lease();
  check(stopCalls == 2 && i2cStepperWebLeaseActive[1], "failed STOP must retain the lease for retry");
  stopSucceeds = true;
  i2cSteppers[1].status.status = 0;
  tick_i2c_stepper_web_lease();
  check(stopCalls == 2 && !i2cStepperWebLeaseActive[1], "stale lease must not stop later normal motion");
  i2cSteppers[3].status.status = I2CSTEPPER_V3_STATUS_CALIBRATION;
  i2c_stepper_web_lease_begin(4);
  i2c_stepper_web_lease_clear(4);
  fakeMillis = 20000;
  tick_i2c_stepper_web_lease();
  check(stopCalls == 2 && !i2cStepperWebLeaseActive[3], "successful finish must clear its lease");
  i2c_stepper_web_lease_touch(11);
  check(!i2cStepperWebLeaseActive[0], "invalid address must not lease another slot");
  return failures ? 1 : 0;
}
'''


if begin and touch and clear and tick:
    source = (HARNESS.replace("@BEGIN@", begin).replace("@TOUCH@", touch)
              .replace("@CLEAR@", clear).replace("@TICK@", tick))
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-web-lease-") as directory:
        path = Path(directory)
        cpp = path / "lease.cpp"
        binary = path / "lease"
        cpp.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode:
            errors.append("lease harness compile failed:\n" + compiled.stderr)
        else:
            executed = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
            if executed.returncode:
                errors.append("lease harness failed:\n" + executed.stderr)

if errors:
    print("I2C web lease smoke failed:")
    for error in errors:
        print(" - " + error)
    sys.exit(1)
print("I2C web lease smoke passed")
