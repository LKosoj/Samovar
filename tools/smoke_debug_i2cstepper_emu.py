#!/usr/bin/env python3
"""Эмулятор плат I2CStepper для сборки с __SAMOVAR_DEBUG: мешалка на адресе 1, насос на 2.
Проверяется обмен теми же кадрами, что шлёт Самовар, и «вращение» по времени."""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"
TRANSPORT = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")

HARNESS = r'''
#define __SAMOVAR_DEBUG
#include <iostream>
#include "debug_i2cstepper_emu.h"

static int failures = 0;
static uint32_t seq = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static I2CStepperV3StatusSnapshot status(uint8_t address, uint32_t now) {
  uint8_t bytes[I2CSTEPPER_V3_STATUS_SIZE] = {};
  bool ok = false;
  I2CStepperV3StatusSnapshot snapshot{};
  check(debug_i2c_emu_read(address, I2CSTEPPER_V3_REG_STATUS, bytes, sizeof(bytes), now, ok) && ok &&
        i2cstepper_v3_decode_status(bytes, &snapshot), "status frame must decode");
  return snapshot;
}

static bool command(uint8_t address, uint8_t code, uint32_t now, bool newSeq = true) {
  I2CStepperV3CommandFrame frame{};
  frame.address = address;
  frame.command = code;
  frame.commandSeq = newSeq ? ++seq : seq;
  uint8_t bytes[I2CSTEPPER_V3_COMMAND_SIZE] = {};
  i2cstepper_v3_encode_command(bytes, &frame);
  bool ok = false;
  debug_i2c_emu_write(address, I2CSTEPPER_V3_REG_COMMAND, bytes, sizeof(bytes), now, ok);
  const I2CStepperV3StatusSnapshot snapshot = status(address, now);
  return ok && snapshot.ackSeq == frame.commandSeq &&
         snapshot.commandResult == I2CSTEPPER_V3_RESULT_SUCCESS;
}

static I2CStepperV3Config read_config(uint8_t address) {
  uint8_t a[I2CSTEPPER_V3_CONFIG_A_SIZE] = {}, b[I2CSTEPPER_V3_CONFIG_B_SIZE] = {};
  bool ok = false;
  I2CStepperV3Config config{};
  debug_i2c_emu_read(address, I2CSTEPPER_V3_REG_CONFIG_A, a, sizeof(a), 0, ok);
  debug_i2c_emu_read(address, I2CSTEPPER_V3_REG_CONFIG_B, b, sizeof(b), 0, ok);
  i2cstepper_v3_decode_config_a(a, &config);
  i2cstepper_v3_decode_config_b(b, &config);
  return config;
}

static void write_config(const I2CStepperV3Config& config) {
  uint8_t a[I2CSTEPPER_V3_CONFIG_A_SIZE] = {}, b[I2CSTEPPER_V3_CONFIG_B_SIZE] = {};
  bool ok = false;
  i2cstepper_v3_encode_config_a(a, &config);
  i2cstepper_v3_encode_config_b(b, &config);
  debug_i2c_emu_write(config.address, I2CSTEPPER_V3_REG_CONFIG_A, a, sizeof(a), 0, ok);
  debug_i2c_emu_write(config.address, I2CSTEPPER_V3_REG_CONFIG_B, b, sizeof(b), 0, ok);
}

int main() {
  uint8_t identityBytes[I2CSTEPPER_V3_IDENTITY_SIZE] = {};
  bool ok = false;
  I2CStepperV3Identity identity{};
  check(debug_i2c_emu_read(2, I2CSTEPPER_V3_REG_IDENTITY, identityBytes, sizeof(identityBytes), 0, ok) &&
        ok && i2cstepper_v3_decode_identity(identityBytes, &identity) && identity.address == 2 &&
        (identity.capabilities & I2CSTEPPER_V3_CAP_PUMP), "address 2 must answer as a pump");
  check(!debug_i2c_emu_read(3, I2CSTEPPER_V3_REG_IDENTITY, identityBytes, sizeof(identityBytes), 0, ok) &&
        !debug_i2c_emu_read(0x48, I2CSTEPPER_V3_REG_IDENTITY, identityBytes, 2, 0, ok),
        "other addresses must go to the real bus");
  check(status(1, 0).mode == I2CSTEPPER_V3_MODE_MIXER && status(2, 0).mode == I2CSTEPPER_V3_MODE_PUMP,
        "address 1 is a mixer, address 2 is a pump");

  // Мешалка: 30 об/мин * 400 / 60 = 200 шаг/с, цикл 10 с работы и 5 с паузы.
  I2CStepperV3Config mixer = read_config(1);
  mixer.mixerRpm = 30; mixer.mixerRunSec = 10; mixer.mixerPauseSec = 5;
  write_config(mixer);
  const uint32_t generation = status(1, 0).generation;
  check(command(1, I2CSTEPPER_V3_CMD_APPLY, 0) && status(1, 0).generation == generation + 1 &&
        read_config(1).mixerRpm == 30, "APPLY must activate the config and bump the generation");
  check(command(1, I2CSTEPPER_V3_CMD_START_CONFIGURED, 1000), "configured mixer start");
  I2CStepperV3StatusSnapshot s = status(1, 6000);
  check((s.status & I2CSTEPPER_V3_STATUS_RUNNING) && s.currentSpeedStepsPerSec == 200 &&
        s.remainingSteps == 1000, "mixer must run by time: 5 s of 10 s left = 1000 steps");
  s = status(1, 12000);
  check(!(s.status & I2CSTEPPER_V3_STATUS_RUNNING) && (s.status & I2CSTEPPER_V3_STATUS_PAUSED) &&
        s.currentSpeedStepsPerSec == 0, "mixer must pause after the run phase");
  check(status(1, 17500).status & I2CSTEPPER_V3_STATUS_RUNNING, "mixer must start the next cycle");
  check(command(1, I2CSTEPPER_V3_CMD_STOP, 18000) && status(1, 18000).status == 0 &&
        status(1, 18000).stopReason == I2CSTEPPER_V3_STOP_REMOTE, "STOP must stop the mixer");
  check(status(1, 60000).status == 0, "stopped mixer must not restart by itself");

  // Насос: доза 5000 шагов со скоростью 100 шаг/с = 50 с.
  I2CStepperV3Config pump = read_config(2);
  pump.mode = I2CSTEPPER_V3_MODE_FILLING;
  write_config(pump);
  check(command(2, I2CSTEPPER_V3_CMD_APPLY, 0), "pump mode change");
  I2CStepperV3Motion motion{};
  motion.mode = I2CSTEPPER_V3_MODE_FILLING; motion.speedStepsPerSec = 100; motion.targetSteps = 5000;
  uint8_t motionBytes[I2CSTEPPER_V3_MOTION_SIZE] = {};
  i2cstepper_v3_encode_motion(motionBytes, &motion);
  debug_i2c_emu_write(2, I2CSTEPPER_V3_REG_MOTION, motionBytes, sizeof(motionBytes), 0, ok);
  check(command(2, I2CSTEPPER_V3_CMD_START_FINITE, 0), "finite pump start");
  check(command(2, I2CSTEPPER_V3_CMD_START_FINITE, 20000, false) && status(2, 20000).remainingSteps == 3000,
        "repeated frame with the same number must not restart the dose");
  s = status(2, 50000);
  check(s.status == 0 && s.remainingSteps == 0 && s.stopReason == I2CSTEPPER_V3_STOP_COMPLETE,
        "dose must complete by itself");
  check(!command(2, I2CSTEPPER_V3_CMD_START_CONTINUOUS, 50000) &&
        status(2, 50000).error == I2CSTEPPER_V3_ERR_UNSUPPORTED_MODE,
        "continuous start in FILLING mode must be rejected like on the Nano");
  motion.speedStepsPerSec = 0;
  i2cstepper_v3_encode_motion(motionBytes, &motion);
  debug_i2c_emu_write(2, I2CSTEPPER_V3_REG_MOTION, motionBytes, sizeof(motionBytes), 0, ok);
  check(!command(2, I2CSTEPPER_V3_CMD_START_FINITE, 50000), "zero speed must be rejected");

  // Реле и калибровка: 100 мл/ч * 16000 / 3600 = 444 шаг/с, за 100 с = 44400 шагов = 444 шаг/мл.
  pump = read_config(2);
  pump.mode = I2CSTEPPER_V3_MODE_PUMP; pump.relayMask = 0x05;
  write_config(pump);
  check(command(2, I2CSTEPPER_V3_CMD_RELAY, 50000) && read_config(2).relayMask == 0x05 &&
        read_config(2).mode == I2CSTEPPER_V3_MODE_FILLING, "RELAY must apply only the relay mask");
  check(command(2, I2CSTEPPER_V3_CMD_APPLY, 50000), "back to PUMP mode");
  check(command(2, I2CSTEPPER_V3_CMD_CALIBRATE_START, 100000) &&
        (status(2, 100000).status & I2CSTEPPER_V3_STATUS_CALIBRATION), "calibration start");
  check(command(2, I2CSTEPPER_V3_CMD_CALIBRATE_FINISH, 200000) && read_config(2).stepsPerMl == 444 &&
        status(2, 200000).status == 0, "calibration must recalculate steps per ml");
  check(!command(1, I2CSTEPPER_V3_CMD_CALIBRATE_START, 200000), "mixer has no calibration");

  pump = read_config(2);
  pump.stepsPerMl = 0;
  write_config(pump);
  check(!command(2, I2CSTEPPER_V3_CMD_APPLY, 200000) && read_config(2).stepsPerMl == 444,
        "invalid config must be rejected and must not replace the active one");
  if (failures) return 1;
  std::cout << "I2CStepper debug emulator checks passed\n";
  return 0;
}
'''


def main() -> int:
  # Эмулятор бесполезен, если обмен по шине его не спрашивает, и вреден вне отладочной сборки.
  for hook in ("debug_i2c_emu_read(address, reg, data, len, millis(), emulated)",
               "debug_i2c_emu_write(address, reg, payload, payloadSize, millis(), emulated)"):
    before = TRANSPORT.split(hook)[0]
    if TRANSPORT.count(hook) != 1 or before.rfind("#ifdef __SAMOVAR_DEBUG") < before.rfind("#endif"):
      print(f"FAIL: transport hook is missing or not under __SAMOVAR_DEBUG: {hook}")
      return 1
  with tempfile.TemporaryDirectory(prefix="samovar-i2c-emu-") as temp:
    cpp = Path(temp) / "test.cpp"
    binary = Path(temp) / "test"
    cpp.write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL), "-I", str(ROOT),
         str(cpp), "-o", str(binary)], capture_output=True, text=True, check=False)
    if result.returncode:
      print(result.stderr, end="")
      return 2
    return subprocess.run([str(binary)], check=False).returncode


if __name__ == "__main__":
  sys.exit(main())
