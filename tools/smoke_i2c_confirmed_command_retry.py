#!/usr/bin/env python3
"""Исполняет текущую v3 i2c_stepper_send_command() с повтором одного frame."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"
SIGNATURE = "inline bool i2c_stepper_send_command(I2CStepperDevice& device, uint8_t command)"


def compile_and_run(body: str, name: str) -> subprocess.CompletedProcess[str]:
    compiler = shutil.which("g++")
    assert compiler is not None, "g++ is required"
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-command-") as directory:
        source = Path(directory) / f"{name}.cpp"
        binary = Path(directory) / name
        source.write_text(HARNESS.replace("@BODY@", body), encoding="utf-8")
        built = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL),
             str(source), "-o", str(binary)], capture_output=True, text=True, check=False)
        if built.returncode != 0:
            return built
        return subprocess.run([str(binary)], capture_output=True, text=True, check=False)


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <vector>
#include <I2CStepperV3.h>

using TickType_t = int;
#define portTICK_PERIOD_MS 1

struct I2CStepperDevice {
  uint8_t address = 2;
  I2CStepperV3StatusSnapshot status = {};
};
struct Write { uint8_t reg; std::vector<uint8_t> bytes; };
static std::vector<Write> writes;
static uint32_t now = 0;
static int ack_on_send = 0;
static int sends = 0;

bool i2c_stepper_command_begin(const I2CStepperDevice&) { return true; }
void i2c_stepper_command_end(const I2CStepperDevice&) {}
bool i2c_stepper_write_block(uint8_t, uint8_t reg, const uint8_t* bytes, uint8_t count) {
  writes.push_back({reg, std::vector<uint8_t>(bytes, bytes + count)});
  sends++;
  return true;
}
bool i2c_stepper_refresh(I2CStepperDevice& device, bool) {
  if (ack_on_send > 0 && sends >= ack_on_send) {
    device.status.ackSeq = i2cstepper_v3_read_u32_be(&writes.back().bytes[2]);
    device.status.commandResult = I2CSTEPPER_V3_RESULT_SUCCESS;
    device.status.error = I2CSTEPPER_V3_ERR_NONE;
  }
  return true;
}
uint32_t millis() { return now; }
void vTaskDelay(TickType_t delay) { now += uint32_t(delay); }

inline bool i2c_stepper_send_command(I2CStepperDevice& device, uint8_t command) {
@BODY@
}

static void reset(int ack) {
  writes.clear(); now = 0; sends = 0; ack_on_send = ack;
}
static void check_frames(uint8_t command, uint32_t sequence, int count) {
  assert(sends == count && int(writes.size()) == count);
  for (const Write& write : writes) {
    assert(write.reg == I2CSTEPPER_V3_REG_COMMAND);
    assert(write.bytes.size() == I2CSTEPPER_V3_COMMAND_SIZE);
    assert(write.bytes[0] == 2 && write.bytes[1] == command);
    assert(i2cstepper_v3_read_u32_be(&write.bytes[2]) == sequence);
  }
}
int main() {
  I2CStepperDevice device = {};
  device.status.commandSeq = 7;
  reset(1);
  assert(i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_RELAY));
  check_frames(I2CSTEPPER_V3_CMD_RELAY, 8, 1);

  device.status.commandSeq = 0xFFFFFFFFUL;
  reset(4);
  assert(i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_START_FINITE));
  check_frames(I2CSTEPPER_V3_CMD_START_FINITE, 1, 4);

  device.status.commandSeq = 9;
  reset(0);
  assert(!i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_STOP));
  assert(sends > 1);
  check_frames(I2CSTEPPER_V3_CMD_STOP, 10, sends);
  return 0;
}
'''


def main() -> int:
    try:
        body = extract_function_body(
            (ROOT / "I2CStepper.h").read_text(encoding="utf-8", errors="ignore"), SIGNATURE)
    except ValueError as error:
        print(f"FAIL: v3 command helper missing: {error}", file=sys.stderr)
        return 1
    result = compile_and_run(body, "command_retry")
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        return 1
    mutated = body.replace("device.status.ackSeq == frame.commandSeq", "false", 1)
    if mutated == body:
        print("FAIL: ACK mutation anchor missing", file=sys.stderr)
        return 1
    mutation = compile_and_run(mutated, "command_retry_mutated")
    if mutation.returncode == 0 or "Assertion" not in mutation.stdout + mutation.stderr:
        print("FAIL: ACK mutation survived or failed outside assertion", file=sys.stderr)
        return 1
    print("i2c v3 command retry/ACK smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
