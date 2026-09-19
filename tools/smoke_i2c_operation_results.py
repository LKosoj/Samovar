#!/usr/bin/env python3
"""v3 staging/ack test using real Samovar helpers extracted into a FakeWire harness."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
I2C = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
SAMOVAR = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"


def extracted(signature: str) -> str:
  return extract_function_body(I2C, signature)


def function(lookup: str, definition: str) -> str:
  return definition + " {" + extracted(lookup) + "}"


def require_source_contract() -> list[str]:
  errors = []
  for name, budget in (
      ("PendingI2CStepperCmd", 80), ("PendingI2CPumpCmd", 32),
      ("PendingI2CCalCmd", 20)):
    start = SAMOVAR.find(f"struct {name}")
    end = SAMOVAR.find("};", start)
    definition = SAMOVAR[start:end]
    if "uint8_t address;" not in definition:
      errors.append(f"{name} does not carry physical address")
    if f"sizeof({name}) <= {budget}" not in SAMOVAR:
      errors.append(f"{name} v3 budget is missing")
  stepper_definition = SAMOVAR[
      SAMOVAR.find("struct PendingI2CStepperCmd"):
      SAMOVAR.find("};", SAMOVAR.find("struct PendingI2CStepperCmd"))]
  for token in ("uint8_t relay;", "bool relayState;"):
    if token not in stepper_definition:
      errors.append(f"PendingI2CStepperCmd missing exact relay request: {token}")
  executor_at = SAMOVAR.rfind("static OperationError execute_pending_i2c_stepper")
  executor = extract_function_body(
      SAMOVAR[executor_at:], "static OperationError execute_pending_i2c_stepper")
  for token in (
      "i2c_stepper_device(command.address)", "confirm_i2c_candidate(candidate)",
      "*device = candidate;"):
    if token not in executor:
      errors.append(f"addressed executor missing {token}")
  if "i2cStepperPump" in executor or "i2cStepperMixer" in executor:
    errors.append("executor retains a singleton")
  require_ordered_tokens(
      "only draft commands copy config and motion",
      executor,
      [
          "I2CStepperDevice candidate = *device;",
          'strcmp(command.cmd, "apply") == 0',
          'strcmp(command.cmd, "save") == 0',
          'strcmp(command.cmd, "start") == 0',
          'strcmp(command.cmd, "calstart") == 0',
          "if (commandCarriesConfig)",
          "candidate.config = command.config;",
          "candidate.motion = command.motion;",
      ],
      errors,
  )
  if executor.find("candidate.config = command.config;") < executor.find("if (commandCarriesConfig)"):
    errors.append("executor copies command config before draft-command gate")
  require_ordered_tokens(
      "relay reads fresh mask then commits ACK without post-readback",
      executor,
      [
          'strcmp(command.cmd, "relay") == 0',
          'strcmp(command.cmd, "blynk_relay") == 0',
          "i2c_stepper_read_config(candidate)",
          "if (command.relayState)",
          "skipReadback = true;",
          "i2c_stepper_write_config(candidate)",
          "i2c_stepper_send_command(candidate, I2CSTEPPER_V3_CMD_RELAY)",
          "if (result == OPERATION_ERROR_NONE && !skipReadback) result = confirm_i2c_candidate(candidate);",
      ],
      errors,
  )
  for signature in (
      "static OperationError execute_pending_i2c_stepper",
      "static OperationError execute_pending_i2c_pump",
      "static OperationError execute_pending_i2c_calibration"):
    body = extract_function_body(SAMOVAR[SAMOVAR.rfind(signature):], signature)
    if "device->present" not in body:
      errors.append(f"{signature} can command a lost pinned device")
  return errors


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
bool fakeSemaphoreAvailable = true;
std::vector<TickType_t> semaphoreWaits;
int xSemaphoreTake(SemaphoreHandle_t, TickType_t wait) {
  semaphoreWaits.push_back(wait);
  return fakeSemaphoreAvailable ? pdTRUE : 0;
}
void xSemaphoreGive(SemaphoreHandle_t) {}
uint32_t fakeMillis = 0;
uint32_t millis() { return fakeMillis += 1; }
void vTaskDelay(uint32_t) {}

class String {
 public:
  String(const char*) {}
  String(uint8_t) {}
};
String operator+(const String&, uint8_t) { return String(""); }
#define F(value) value
enum { ALARM_MSG = 0 };
void SendMsg(const String&, int) {}

#define I2C_LOCK_WAIT_MS 1000
#define I2CSTEPPER_DEVICE_COUNT 10U
#define I2CSTEPPER_V3_TARGET_STEPS_MAX 2147483647UL
struct I2CStepperDevice {
  bool present;
  bool everPresent;
  uint8_t address;
  uint8_t capabilities;
  I2CStepperV3Config config;
  I2CStepperV3Motion motion;
  I2CStepperV3StatusSnapshot status;
  uint32_t lastStopEventSeq;
  uint32_t lastHeartbeatMs;
};
volatile uint32_t i2c_config_in_flight = 0;
uint32_t i2cStepperLastSentSeq[I2CSTEPPER_DEVICE_COUNT] = {};
bool i2c_stepper_config_busy(const I2CStepperDevice&) { return false; }
int refreshFailures = 0;
void i2c_stepper_note_refresh_failure(I2CStepperDevice& device) {
  refreshFailures++;
  device.present = false;
}
@CONFIG_BIT@
@COMMAND_BIT@
@COMMAND_BEGIN@
@COMMAND_END@

struct FakeNano {
  I2CStepperV3Config active{};
  I2CStepperV3Config staged{};
  I2CStepperV3Motion motion{};
  I2CStepperV3StatusSnapshot status{};
  uint8_t currentReg = 0;
  std::vector<uint8_t> tx;
  std::vector<uint8_t> rx;
  size_t readAt = 0;
  std::vector<uint8_t> writes;
  std::vector<uint32_t> commandSeqs;
  uint32_t processedSeq = 0;
  bool dropAckOnce = false;
  std::vector<uint8_t> executed;
  int failStatusReads = 0;
  int pendingReads = 0;
} nano;

class FakeWire {
 public:
  void beginTransmission(uint8_t) { nano.tx.clear(); }
  size_t write(uint8_t value) { nano.tx.push_back(value); return 1; }
  size_t write(const uint8_t* data, uint8_t size) {
    nano.tx.insert(nano.tx.end(), data, data + size); return size;
  }
  int endTransmission(bool = true) {
    if (nano.tx.empty()) return 4;
    nano.currentReg = nano.tx[0];
    if (nano.tx.size() == 1) return 0;
    const uint8_t* payload = nano.tx.data() + 1;
    const uint8_t size = uint8_t(nano.tx.size() - 1);
    nano.writes.push_back(nano.currentReg);
    if (nano.currentReg == I2CSTEPPER_V3_REG_CONFIG_A) {
      i2cstepper_v3_decode_config_a(payload, &nano.staged);
    } else if (nano.currentReg == I2CSTEPPER_V3_REG_CONFIG_B) {
      i2cstepper_v3_decode_config_b(payload, &nano.staged);
    } else if (nano.currentReg == I2CSTEPPER_V3_REG_MOTION) {
      i2cstepper_v3_decode_motion(payload, &nano.motion);
    } else if (nano.currentReg == I2CSTEPPER_V3_REG_COMMAND &&
               size == I2CSTEPPER_V3_COMMAND_SIZE) {
      I2CStepperV3CommandFrame command{};
      i2cstepper_v3_decode_command(payload, &command);
      nano.commandSeqs.push_back(command.commandSeq);
      if (command.commandSeq != nano.processedSeq &&
          command.command == I2CSTEPPER_V3_CMD_APPLY) {
        nano.active = nano.staged;
        nano.status.generation++;
      }
      if (command.commandSeq != nano.processedSeq) {
        nano.processedSeq = command.commandSeq;
        nano.executed.push_back(command.command);
      }
      nano.status.commandSeq = command.commandSeq;
      nano.status.commandResult = I2CSTEPPER_V3_RESULT_SUCCESS;
      nano.status.error = I2CSTEPPER_V3_ERR_NONE;
      if (nano.dropAckOnce) {
        nano.dropAckOnce = false;
      } else {
        nano.status.ackSeq = command.commandSeq;
      }
    }
    return 0;
  }
  uint8_t requestFrom(uint8_t, uint8_t len) {
    if (nano.failStatusReads > 0) {
      nano.failStatusReads--;
      return 0;
    }
    nano.rx.assign(len, 0);
    if (nano.currentReg == I2CSTEPPER_V3_REG_STATUS) {
      I2CStepperV3StatusSnapshot published = nano.status;
      if (nano.pendingReads > 0) {
        nano.pendingReads--;
        published.commandResult = I2CSTEPPER_V3_RESULT_PENDING;
      }
      i2cstepper_v3_encode_status(nano.rx.data(), &published);
    }
    nano.readAt = 0;
    return len;
  }
  int read() { return nano.readAt < nano.rx.size() ? nano.rx[nano.readAt++] : -1; }
} Wire;

@READ_BLOCK@
@WRITE_BLOCK@

bool i2c_stepper_refresh(I2CStepperDevice& device, bool = false,
                         TickType_t lockWaitMs = I2C_LOCK_WAIT_MS,
                         bool = true) {
  uint8_t frame[I2CSTEPPER_V3_STATUS_SIZE] = {};
  I2CStepperV3StatusSnapshot status{};
  if (!i2c_stepper_read_block(device.address, I2CSTEPPER_V3_REG_STATUS, frame,
                              sizeof(frame), lockWaitMs) ||
      !i2cstepper_v3_decode_status(frame, &status)) return false;
  device.status = status;
  device.present = true;
  return true;
}

@WRITE_CONFIG@
@WRITE_MOTION@
@NEXT_SEQ@
@SEND_COMMAND@
@HEARTBEAT@
@APPLY@
@START_FINITE@

static int failures = 0;
void check(bool value, const char* message) {
  if (!value) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}
bool saw(uint8_t reg) {
  for (uint8_t value : nano.writes) if (value == reg) return true;
  return false;
}

int main() {
  nano.active.address = nano.staged.address = nano.status.address = 2;
  nano.active.mode = nano.staged.mode = nano.status.mode = I2CSTEPPER_V3_MODE_FILLING;
  nano.active.stepsPerMl = nano.staged.stepsPerMl = 100;
  nano.status.generation = 7;
  I2CStepperDevice device{};
  device.address = 2;
  device.config = nano.active;
  device.status = nano.status;

  device.config.pumpMlHour = 321;
  check(i2c_stepper_write_config(device), "config staging write failed");
  check(nano.active.pumpMlHour == 0 && nano.staged.pumpMlHour == 321,
        "staging write changed active configuration");
  check(saw(I2CSTEPPER_V3_REG_CONFIG_A) && saw(I2CSTEPPER_V3_REG_CONFIG_B),
        "config must use both v3 frames");

  nano.dropAckOnce = true;
  check(i2c_stepper_apply(device), "APPLY acknowledgement/retry failed");
  check(nano.active.pumpMlHour == 321 && nano.status.generation == 8,
        "APPLY did not atomically publish staged configuration");
  check(nano.commandSeqs.size() == 2 && nano.commandSeqs[0] == nano.commandSeqs[1],
        "ambiguous ACK retry changed command sequence");

  nano.writes.clear();
  device.motion.mode = I2CSTEPPER_V3_MODE_FILLING;
  device.motion.direction = 1;
  device.motion.speedStepsPerSec = 123;
  device.motion.targetSteps = 125;
  check(i2c_stepper_start_finite(device), "finite start failed");
  check(nano.motion.targetSteps == 125 && nano.motion.speedStepsPerSec == 123,
        "finite target was rounded or changed");
  check(saw(I2CSTEPPER_V3_REG_MOTION) && saw(I2CSTEPPER_V3_REG_COMMAND),
        "finite start did not write motion and command frames");
  check(device.status.ackSeq == device.status.commandSeq &&
        device.status.commandResult == I2CSTEPPER_V3_RESULT_SUCCESS,
        "command result is not tied to matching ack sequence");
  check(i2c_stepper_command_begin(device), "cannot acquire command guard");
  const size_t writesBeforeCollision = nano.writes.size();
  check(!i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_STOP) &&
        nano.writes.size() == writesBeforeCollision,
        "overlapping command entered the same device transaction");
  i2c_stepper_command_end(device);
  const size_t commandsBeforeHeartbeat = nano.commandSeqs.size();
  nano.dropAckOnce = true;
  check(!i2c_stepper_send_heartbeat(device) &&
        nano.commandSeqs.size() == commandsBeforeHeartbeat + 1,
        "heartbeat timeout retried instead of yielding to the next address");
  check((i2c_config_in_flight & i2c_stepper_command_bit(device.address)) == 0,
        "heartbeat left the command guard held");
  nano.writes.clear();
  semaphoreWaits.clear();
  refreshFailures = 0;
  device.present = true;
  const size_t commandsBeforeBusyHeartbeat = nano.commandSeqs.size();
  fakeSemaphoreAvailable = false;
  check(!i2c_stepper_send_heartbeat(device),
        "heartbeat must yield when the I2C semaphore is busy");
  fakeSemaphoreAvailable = true;
  check(semaphoreWaits.size() == 1 && semaphoreWaits[0] == 0,
        "busy heartbeat waited for the I2C semaphore");
  check(nano.writes.empty() && nano.commandSeqs.size() == commandsBeforeBusyHeartbeat,
        "busy heartbeat was marked as a sent command");
  check(device.present && refreshFailures == 0,
        "busy heartbeat marked the Nano unavailable");

  // Heartbeat записан, но статус после него не прочитался: следующая команда обязана
  // получить НОВЫЙ номер, иначе Nano отбросит STOP как дубликат heartbeat.
  nano.executed.clear();
  nano.failStatusReads = 1;
  check(!i2c_stepper_send_heartbeat(device), "heartbeat without status readback succeeded");
  check(i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_STOP), "STOP after lost heartbeat status failed");
  check(nano.executed.size() == 2 && nano.executed[0] == I2CSTEPPER_V3_CMD_HEARTBEAT &&
        nano.executed[1] == I2CSTEPPER_V3_CMD_STOP,
        "STOP reused the heartbeat sequence and was dropped as a duplicate");

  // Отброшенная копия-кандидат не должна возвращать номер назад.
  I2CStepperDevice candidate = device;
  check(i2c_stepper_send_command(candidate, I2CSTEPPER_V3_CMD_RELAY), "candidate RELAY failed");
  nano.executed.clear();
  check(i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_STOP) &&
        nano.executed.size() == 1 && nano.executed[0] == I2CSTEPPER_V3_CMD_STOP,
        "command after a discarded candidate reused its sequence");

  // PENDING (Nano пишет EEPROM) - не отказ: ждём итоговый результат.
  nano.pendingReads = 3;
  check(i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_SAVE),
        "PENDING result was reported as a failed command");
  check(nano.pendingReads == 0, "PENDING polling stopped early");
  return failures == 0 ? 0 : 1;
}
'''


def main() -> int:
  errors = require_source_contract()
  source = HARNESS
  replacements = {
      "@READ_BLOCK@": function(
          "inline bool i2c_stepper_read_block",
          "inline bool i2c_stepper_read_block(uint8_t address, uint8_t reg, uint8_t* data, uint8_t len, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS, bool* lockBusy = nullptr)"),
      "@WRITE_BLOCK@": function(
          "inline bool i2c_stepper_write_block",
          "inline bool i2c_stepper_write_block(uint8_t address, uint8_t reg, const uint8_t* payload, uint8_t payloadSize, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)"),
      "@WRITE_CONFIG@": function(
          "inline bool i2c_stepper_write_config",
          "inline bool i2c_stepper_write_config(I2CStepperDevice& device)"),
      "@WRITE_MOTION@": function(
          "inline bool i2c_stepper_write_motion",
          "inline bool i2c_stepper_write_motion(I2CStepperDevice& device)"),
      "@NEXT_SEQ@": function(
          "inline uint32_t i2c_stepper_next_command_seq",
          "inline uint32_t i2c_stepper_next_command_seq(const I2CStepperDevice& device)"),
      "@SEND_COMMAND@": function(
          "inline bool i2c_stepper_send_command",
          "inline bool i2c_stepper_send_command(I2CStepperDevice& device, uint8_t command)"),
      "@HEARTBEAT@": function(
          "inline bool i2c_stepper_send_heartbeat",
          "inline bool i2c_stepper_send_heartbeat(I2CStepperDevice& device)"),
      "@APPLY@": function(
          "inline bool i2c_stepper_apply",
          "inline bool i2c_stepper_apply(I2CStepperDevice& device)"),
      "@START_FINITE@": function(
          "inline bool i2c_stepper_start_finite",
          "inline bool i2c_stepper_start_finite(I2CStepperDevice& device)"),
      "@CONFIG_BIT@": function(
          "inline uint32_t i2c_stepper_config_bit",
          "inline uint32_t i2c_stepper_config_bit(uint8_t address)"),
      "@COMMAND_BIT@": function(
          "inline uint32_t i2c_stepper_command_bit",
          "inline uint32_t i2c_stepper_command_bit(uint8_t address)"),
      "@COMMAND_BEGIN@": function(
          "inline bool i2c_stepper_command_begin",
          "inline bool i2c_stepper_command_begin(const I2CStepperDevice& device)"),
      "@COMMAND_END@": function(
          "inline void i2c_stepper_command_end",
          "inline void i2c_stepper_command_end(const I2CStepperDevice& device)"),
  }
  for token, value in replacements.items():
    source = source.replace(token, value)
  heartbeat_source = extracted("inline bool i2c_stepper_send_heartbeat")
  if "vTaskDelay" in heartbeat_source or "3000UL" in heartbeat_source:
    errors.append("heartbeat retains the blocking command retry window")
  if "I2C_LOCK_WAIT_MS" in heartbeat_source:
    errors.append("heartbeat retains the blocking I2C semaphore wait")
  def compile_and_run(candidate: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-v3-operation-") as temp:
      cpp = Path(temp) / "test.cpp"
      binary = Path(temp) / "test"
      cpp.write_text(candidate, encoding="utf-8")
      result = subprocess.run(
          ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL),
           str(cpp), "-o", str(binary)], capture_output=True, text=True, check=False)
      if result.returncode:
        return result.returncode, result.stderr
      ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
      return ran.returncode, ran.stdout + ran.stderr

  result_code, output = compile_and_run(source)
  if result_code:
    errors.append("FakeWire v3 harness failed:\n" + output)
  mutation = source.replace(
      "if (!i2c_stepper_command_begin(device)) return false;",
      "if (false) return false;",
      1)
  mutation_code, _ = compile_and_run(mutation)
  if mutation == source or mutation_code == 0:
    errors.append("command collision mutation survived")
  if errors:
    print("I2C v3 operation results smoke failed:")
    for error in errors:
      print(f" - {error}")
    return 1
  print("I2C v3 operation results smoke passed")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
