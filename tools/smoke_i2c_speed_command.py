#!/usr/bin/env python3
"""Команда «скорость» вкладки I2CStepper: свободный привод запускается, занятый процессом
получает новую скорость вместо программной. Единицы: об/мин мешалки, мл/ч и мл насоса."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
SIGNATURE = "static bool apply_i2c_speed_command"
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <I2CStepperV3.h>
struct I2CStepperDevice {
  bool present;
  uint8_t address;
  I2CStepperV3Config config;
  I2CStepperV3Motion motion;
  struct { uint8_t status; uint32_t remainingSteps; } status;
};
uint8_t i2cStepperSessionMixerAddress = 0;
uint8_t i2cStepperSessionPumpAddress = 0;
float i2cStepperPumpRateOverride = 0.0f;
bool rectSecondPumpHeadsRow = false;
float ActualVolumePerHour = 0.0f;
int applies = 0, finiteStarts = 0, continuous = 0, mixerOverrides = 0, pumpOverrides = 0;
int lastCommand = 0;
int lastOverrideDirection = -1;
#define I2CSTEPPER_OPTION_DIRECTION 0x04U
bool linkOk = true;
uint32_t freshRemainingSteps = 0;
bool i2c_stepper_refresh(I2CStepperDevice& device, bool) { device.status.remainingSteps = freshRemainingSteps; return linkOk; }
bool i2c_stepper_apply(I2CStepperDevice&) { applies++; return linkOk; }
bool i2c_stepper_send_command(I2CStepperDevice&, uint8_t command) { lastCommand = command; return linkOk; }
bool i2c_stepper_start_finite(I2CStepperDevice&) { finiteStarts++; return linkOk; }
bool i2c_stepper_start_continuous(I2CStepperDevice&) { continuous++; return linkOk; }
bool i2c_stepper_override_mixer_rpm(uint16_t, uint8_t direction) { mixerOverrides++; lastOverrideDirection = direction; return true; }
bool i2c_stepper_override_pump_rate(float rate, uint8_t direction) { pumpOverrides++; lastOverrideDirection = direction; i2cStepperPumpRateOverride = rate; return true; }
static bool apply_i2c_speed_command(I2CStepperDevice& device, const I2CStepperV3Config& config,
                                    uint8_t direction) {@BODY@}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

int main() {
  I2CStepperDevice mixer{};
  mixer.present = true; mixer.address = 1;
  mixer.config.mixerRunSec = 30; mixer.config.mixerPauseSec = 20;
  I2CStepperV3Config request{};
  request.mixerRpm = 45;
  check(apply_i2c_speed_command(mixer, request, 0) && applies == 1 &&
        lastCommand == I2CSTEPPER_V3_CMD_START_CONFIGURED && mixerOverrides == 0 &&
        mixer.config.mode == I2CSTEPPER_V3_MODE_MIXER && mixer.config.mixerRpm == 45 &&
        mixer.config.mixerRunSec == 0 && mixer.config.mixerPauseSec == 0,
        "free mixer must start continuously at the requested rpm");
  check(apply_i2c_speed_command(mixer, request, 2) && (mixer.config.optionFlags & I2CSTEPPER_OPTION_DIRECTION) &&
        apply_i2c_speed_command(mixer, request, 0) && (mixer.config.optionFlags & I2CSTEPPER_OPTION_DIRECTION) &&
        apply_i2c_speed_command(mixer, request, 1) && !(mixer.config.optionFlags & I2CSTEPPER_OPTION_DIRECTION),
        "free mixer direction: 2 = reverse, 1 = forward, 0 = keep");
  applies = 1;
  linkOk = false;
  request.mixerRpm = 60;
  check(!apply_i2c_speed_command(mixer, request, 2) && mixer.config.mixerRpm == 45 &&
        !(mixer.config.optionFlags & I2CSTEPPER_OPTION_DIRECTION),
        "failed mixer start must not change the cached settings");
  linkOk = true;
  i2cStepperSessionMixerAddress = 1;
  applies = 0;
  check(apply_i2c_speed_command(mixer, request, 2) && mixerOverrides == 1 && applies == 0 &&
        lastOverrideDirection == 2,
        "mixer owned by a process must get the speed through the program override");

  I2CStepperDevice pump{};
  pump.present = true; pump.address = 2; pump.config.stepsPerMl = 100;
  I2CStepperV3Config pumpRequest{};
  pumpRequest.pumpMlHour = 1800;  // 1.8 л/ч * 100 шаг/мл / 3600 = 50 шаг/с
  check(apply_i2c_speed_command(pump, pumpRequest, 2) && continuous == 1 && finiteStarts == 0 &&
        pump.motion.direction == 1 &&
        pump.motion.speedStepsPerSec == 50 && pump.motion.targetSteps == 0 &&
        pump.config.mode == I2CSTEPPER_V3_MODE_PUMP,
        "free pump without a volume must run continuously at l/h converted to steps");
  pumpRequest.fillingMl = 250;
  check(apply_i2c_speed_command(pump, pumpRequest, 1) && finiteStarts == 1 && pump.motion.direction == 0 &&
        pump.motion.targetSteps == 25000 && pump.config.mode == I2CSTEPPER_V3_MODE_FILLING,
        "free pump with a volume must dose that volume");
  // Насос отмеряет объём, оператор меняет только скорость: докачиваем остаток, а не всё заново
  // и не превращаем дозу в бесконечную работу.
  pump.status.status = I2CSTEPPER_V3_STATUS_RUNNING;
  freshRemainingSteps = 7000;
  pumpRequest.fillingMl = 0;
  pumpRequest.pumpMlHour = 3600;
  check(apply_i2c_speed_command(pump, pumpRequest, 0) && finiteStarts == 2 && continuous == 1 &&
        pump.motion.targetSteps == 7000 && pump.motion.speedStepsPerSec == 100,
        "speed change during dosing must keep the remaining volume");
  pump.status.status = 0;
  pumpRequest.fillingMl = 250;
  finiteStarts = 1;
  pumpRequest.pumpMlHour = 1;  // меньше одного шага в секунду
  check(!apply_i2c_speed_command(pump, pumpRequest, 0) && finiteStarts == 1,
        "speed below one step per second must be rejected");
  pump.config.stepsPerMl = 0;
  pumpRequest.pumpMlHour = 1800;
  check(!apply_i2c_speed_command(pump, pumpRequest, 0), "uncalibrated pump must be rejected");
  pump.config.stepsPerMl = 100;
  i2cStepperSessionPumpAddress = 2;
  rectSecondPumpHeadsRow = true;
  check(apply_i2c_speed_command(pump, pumpRequest, 1) && pumpOverrides == 1 && lastOverrideDirection == 1 &&
        finiteStarts == 1 &&
        continuous == 1 && ActualVolumePerHour == 1.8f,
        "pump owned by a process must get the speed through the program override");
  if (failures) return 1;
  std::cout << "I2C speed command checks passed\n";
  return 0;
}
'''


def run(body: str, quiet: bool = False) -> int:
  with tempfile.TemporaryDirectory(prefix="samovar-i2c-speed-command-") as temp:
    cpp = Path(temp) / "test.cpp"
    binary = Path(temp) / "test"
    cpp.write_text(HARNESS.replace("@BODY@", body), encoding="utf-8")
    result = subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL),
         str(cpp), "-o", str(binary)], capture_output=True, text=True, check=False)
    if result.returncode:
      print(result.stderr, end="")
      return 2
    return subprocess.run([str(binary)], capture_output=quiet, check=False).returncode


def main() -> int:
  body = extract_function_body(SOURCE, SIGNATURE)
  status = run(body)
  if status:
    return status
  # Мутация: занятый процессом привод запускается напрямую, минуя программу.
  owned = "device.address == i2cStepperSessionMixerAddress"
  if body.count(owned) != 1 or run(body.replace(owned, owned + " && false"), quiet=True) != 1:
    print("FAIL: mutation of the process ownership check was not rejected")
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
