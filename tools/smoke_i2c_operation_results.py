#!/usr/bin/env python3
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"missing file: {name}")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


def definition_body(source: str, signature: str) -> str:
    start = source.rfind(signature)
    if start < 0:
        errors.append(f"function definition not found: {signature}")
        return ""
    return body(source[start:], signature)


def definition(source: str, token: str) -> str:
    start = source.find(token)
    if start < 0:
        raise ValueError(f"definition not found: {token}")
    end = source.find("};", start)
    if end < 0:
        raise ValueError(f"definition is not closed: {token}")
    return source[start:end + 2]


def wrapped(signature: str, source: str, source_signature: str) -> str:
    return signature + " {\n" + extract_function_body(source, source_signature) + "\n}\n"


def wrapped_definition(signature: str, source: str, source_signature: str) -> str:
    start = source.rfind(source_signature)
    if start < 0:
        raise ValueError(f"function definition not found: {source_signature}")
    return wrapped(signature, source[start:], source_signature)


def executor_fake_headers() -> dict[str, str]:
    return {
        "Arduino.h": textwrap.dedent(
            r"""
            #pragma once
            #include <cmath>
            #include <cstddef>
            #include <cstdint>
            #include <string>

            using TickType_t = int;
            using SemaphoreHandle_t = int;
            using std::round;

            extern SemaphoreHandle_t xI2CSemaphore;
            int xSemaphoreTake(SemaphoreHandle_t, TickType_t);
            void xSemaphoreGive(SemaphoreHandle_t);
            void vTaskDelay(TickType_t);

            #define pdTRUE 1
            #define portTICK_RATE_MS 1
            #define portTICK_PERIOD_MS 1
            #define bitRead(value, bit) (((value) >> (bit)) & 0x01)

            class String {
             public:
              String() = default;
              String(const char* value) : value_(value ? value : "") {}
              String(uint8_t value) : value_(std::to_string(value)) {}
              String& operator+=(const String& value) {
                value_ += value.value_;
                return *this;
              }

             private:
              std::string value_;
            };
            """
        ),
        "Wire.h": textwrap.dedent(
            r"""
            #pragma once
            #include <cstdint>

            void fake_wire_begin(uint8_t address);
            size_t fake_wire_write(uint8_t value);
            int fake_wire_end(bool stop);
            uint8_t fake_wire_request(uint8_t address, uint8_t len);
            int fake_wire_read();

            class FakeWire {
             public:
              void beginTransmission(uint8_t address) { fake_wire_begin(address); }
              size_t write(uint8_t value) { return fake_wire_write(value); }
              int endTransmission(bool stop = true) { return fake_wire_end(stop); }
              uint8_t requestFrom(uint8_t address, uint8_t len) {
                return fake_wire_request(address, len);
              }
              int read() { return fake_wire_read(); }
            };

            extern FakeWire Wire;
            """
        ),
        "Samovar.h": textwrap.dedent(
            r"""
            #pragma once
            #include "Arduino.h"

            #define I2C_STEPPER_STEP_ML_DEFAULT 100

            struct SetupEEPROM {
              uint16_t StepperStepMl;
              uint16_t StepperStepMlI2C;
            };

            extern SetupEEPROM SamSetup;
            extern volatile uint16_t CurrrentStepperSpeed;
            extern volatile uint16_t I2CStepperSpeed;
            extern volatile uint16_t I2CPumpCmdSpeed;
            extern volatile uint32_t I2CPumpTargetSteps;
            extern volatile float I2CPumpTargetMl;
            extern uint8_t use_I2C_dev;

            uint8_t fake_i2c_read(uint8_t address, uint8_t reg);
            uint8_t fake_i2c_write(uint8_t address, uint8_t reg, uint8_t value);

            class FakeI2C2 {
             public:
              uint8_t readByte(uint8_t address, uint8_t reg) {
                return fake_i2c_read(address, reg);
              }
              uint8_t writeByte(uint8_t address, uint8_t reg, uint8_t value) {
                return fake_i2c_write(address, reg, value);
              }
            };

            extern FakeI2C2 I2C2;

            void stopService();
            void startService();
            void stepper_safe_set_motion(uint16_t speed, uint8_t direction,
                                         uint32_t target);
            void stepper_safe_stop_reset();
            uint32_t stepper_safe_get_target();
            float get_liquid_volume_by_step(int steps);
            float get_speed_from_rate(float rate);
            """
        ),
        "samovar_api.h": textwrap.dedent(
            r"""
            #pragma once

            enum PersistResult : uint8_t {
              PERSIST_OK = 0,
              PERSIST_OPEN_FAILED,
            };

            enum PumpCalibrationResult : uint8_t {
              PUMP_CALIBRATION_OK = 0,
              PUMP_CALIBRATION_INVALID_STATE,
              PUMP_CALIBRATION_INVALID_RESULT,
              PUMP_CALIBRATION_PROFILE_PERSIST_FAILED,
            };

            PersistResult save_profile_nvs(const SetupEEPROM& candidate);
            PumpCalibrationResult pump_calibrate(int speed);
            void WriteConsoleLog(const String& message);
            """
        ),
    }


def build_executor_harness() -> str:
    samovar_source = read("Samovar.ino")
    dto_definitions = "\n".join(
        definition(samovar_source, f"struct {name}")
        for name in (
            "PendingI2CStepperCmd",
            "PendingI2CPumpCmd",
            "PendingI2CCalCmd",
            "PendingLocalCalCmd",
        )
    )
    owner_functions = "\n".join(
        (
            wrapped(
                "static OperationError i2c_command_result(\n"
                "    bool commandSucceeded,\n"
                "    const I2CStepperDevice& candidate)",
                samovar_source,
                "static OperationError i2c_command_result(",
            ),
            wrapped(
                "static OperationError confirm_i2c_candidate("
                "I2CStepperDevice& candidate)",
                samovar_source,
                "static OperationError confirm_i2c_candidate(",
            ),
            wrapped_definition(
                "static OperationError execute_pending_i2c_stepper(\n"
                "    const PendingI2CStepperCmd& command)",
                samovar_source,
                "static OperationError execute_pending_i2c_stepper(",
            ),
            wrapped_definition(
                "static OperationError execute_pending_i2c_pump(\n"
                "    const PendingI2CPumpCmd& command)",
                samovar_source,
                "static OperationError execute_pending_i2c_pump(",
            ),
            wrapped_definition(
                "static OperationError execute_pending_i2c_calibration(\n"
                "    const PendingI2CCalCmd& command)",
                samovar_source,
                "static OperationError execute_pending_i2c_calibration(",
            ),
            wrapped_definition(
                "static OperationError execute_pending_local_calibration(\n"
                "    const PendingLocalCalCmd& command)",
                samovar_source,
                "static OperationError execute_pending_local_calibration(",
            ),
        )
    )
    harness = r'''
#include <cstdint>
#include <cstring>
#include <iostream>

#include "operation_store.h"
#include "I2CStepper.h"

@DTO_DEFINITIONS@

SetupEEPROM SamSetup{};
volatile uint16_t CurrrentStepperSpeed = 0;
volatile uint16_t I2CStepperSpeed = 0;
volatile uint16_t I2CPumpCmdSpeed = 0;
volatile uint32_t I2CPumpTargetSteps = 0;
volatile float I2CPumpTargetMl = 0;
bool I2CPumpCalibrating = false;
uint8_t use_I2C_dev = 0;
SemaphoreHandle_t xI2CSemaphore = 1;
FakeWire Wire;
FakeI2C2 I2C2;

struct FakeBusState {
  uint8_t registers[256];
  int writeCalls;
  int failWriteAt;
  int commandWrites;
  int probeCalls;
  int failProbeAt;
  bool ackEnabled;
  uint8_t txRegister;
  uint8_t readRegister;
  bool txHasRegister;
};

static FakeBusState bus{};
static PersistResult persistResult = PERSIST_OK;
static int persistCalls = 0;
static PumpCalibrationResult calibrationResult = PUMP_CALIBRATION_OK;
static int calibrationCalls = 0;

int xSemaphoreTake(SemaphoreHandle_t, TickType_t) { return pdTRUE; }
void xSemaphoreGive(SemaphoreHandle_t) {}
void vTaskDelay(TickType_t) {}

void fake_wire_begin(uint8_t) {
  bus.txHasRegister = false;
}

size_t fake_wire_write(uint8_t value) {
  bus.txRegister = value;
  bus.txHasRegister = true;
  return 1;
}

int fake_wire_end(bool stop) {
  if (stop && !bus.txHasRegister) {
    bus.probeCalls++;
    if (bus.failProbeAt != 0 && bus.probeCalls == bus.failProbeAt) return 4;
  }
  return 0;
}

uint8_t fake_wire_request(uint8_t, uint8_t len) {
  bus.readRegister = bus.txRegister;
  return len;
}

int fake_wire_read() {
  return bus.registers[bus.readRegister++];
}

uint8_t fake_i2c_read(uint8_t, uint8_t reg) {
  return bus.registers[reg];
}

uint8_t fake_i2c_write(uint8_t, uint8_t reg, uint8_t value) {
  bus.writeCalls++;
  if (bus.failWriteAt != 0 && bus.writeCalls == bus.failWriteAt) return 1;
  bus.registers[reg] = value;
  if (reg == I2CSTEP_REG_COMMAND) bus.commandWrites++;
  if (reg == I2CSTEP_REG_COMMAND_SEQ && bus.ackEnabled) {
    bus.registers[I2CSTEP_REG_ACK_SEQ] = value;
  }
  return 0;
}

void stopService() {}
void startService() {}
void stepper_safe_set_motion(uint16_t, uint8_t, uint32_t) {}
void stepper_safe_stop_reset() {}
uint32_t stepper_safe_get_target() { return 0; }
float get_liquid_volume_by_step(int) { return 0; }
float get_speed_from_rate(float) { return 0; }
void WriteConsoleLog(const String&) {}

PersistResult save_profile_nvs(const SetupEEPROM&) {
  persistCalls++;
  return persistResult;
}

PumpCalibrationResult pump_calibrate(int) {
  calibrationCalls++;
  return calibrationResult;
}

@OWNER_FUNCTIONS@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static bool same_device(
    const I2CStepperDevice& left,
    const I2CStepperDevice& right) {
  return std::memcmp(&left, &right, sizeof(left)) == 0;
}

static void set_u16(uint8_t reg, uint16_t value) {
  bus.registers[reg] = static_cast<uint8_t>(value >> 8);
  bus.registers[reg + 1] = static_cast<uint8_t>(value & 0xff);
}

static void reset_fixture() {
  bus = {};
  bus.ackEnabled = true;
  bus.registers[I2CSTEP_REG_MAGIC] = I2CSTEPPER_MAGIC;
  bus.registers[I2CSTEP_REG_VERSION] = I2CSTEPPER_PROTO_VERSION;
  bus.registers[I2CSTEP_REG_CAPS] =
      I2CSTEPPER_CAP_PUMP | I2CSTEPPER_CAP_FILLING;
  bus.registers[I2CSTEP_REG_ROLE] = I2CSTEPPER_PUMP_ADDR;
  bus.registers[I2CSTEP_REG_MODE] = I2CSTEP_MODE_FILLING;
  set_u16(I2CSTEP_REG_STEPS_PER_ML_H, 40);

  i2cStepperMixer = make_i2c_stepper_device(I2CSTEPPER_MIXER_ADDR);
  i2cStepperMixer.present = true;
  i2cStepperPump = make_i2c_stepper_device(I2CSTEPPER_PUMP_ADDR);
  i2cStepperPump.present = true;
  i2cStepperPump.caps =
      I2CSTEPPER_CAP_PUMP | I2CSTEPPER_CAP_FILLING;
  i2cStepperPump.mode = I2CSTEP_MODE_FILLING;
  i2cStepperPump.stepsPerMl = 40;
  i2c_config_in_flight = 0;

  SamSetup = {25, 40};
  CurrrentStepperSpeed = 17;
  I2CStepperSpeed = 0;
  I2CPumpCmdSpeed = 19;
  I2CPumpTargetSteps = 29;
  I2CPumpTargetMl = 39;
  I2CPumpCalibrating = false;
  persistResult = PERSIST_OK;
  persistCalls = 0;
  calibrationResult = PUMP_CALIBRATION_OK;
  calibrationCalls = 0;
}

static PendingI2CStepperCmd stepper_command(const char* name) {
  PendingI2CStepperCmd command{};
  command.staged = i2cStepperPump;
  command.device_sel = 1;
  std::strncpy(command.cmd, name, sizeof(command.cmd) - 1);
  return command;
}

static void test_config_and_transport_failures() {
  reset_fixture();
  PendingI2CStepperCmd command = stepper_command("apply");
  const I2CStepperDevice beforeBusy = i2cStepperPump;
  i2c_config_in_flight = I2CSTEP_CONFIG_PUMP;
  check(execute_pending_i2c_stepper(command) ==
            OPERATION_ERROR_I2C_CONFIG_BUSY,
        "config busy error was not returned");
  check(bus.writeCalls == 0 && same_device(beforeBusy, i2cStepperPump),
        "config busy mutated hardware or confirmed device");

  reset_fixture();
  command = stepper_command("apply");
  const I2CStepperDevice beforePartial = i2cStepperPump;
  bus.failWriteAt = 4;
  check(execute_pending_i2c_stepper(command) ==
            OPERATION_ERROR_I2C_COMMAND_FAILED,
        "partial config write was not a command failure");
  check(bus.commandWrites == 0 && same_device(beforePartial, i2cStepperPump),
        "partial config write committed candidate or command");
  check(i2c_config_in_flight == 0, "partial write leaked config ownership");

  reset_fixture();
  command = stepper_command("stop");
  const I2CStepperDevice beforeAck = i2cStepperPump;
  bus.ackEnabled = false;
  check(execute_pending_i2c_stepper(command) ==
            OPERATION_ERROR_I2C_COMMAND_FAILED,
        "ACK timeout was not a command failure");
  check(bus.commandWrites == 1 && same_device(beforeAck, i2cStepperPump),
        "ACK timeout duplicated command or committed candidate");
  check(i2c_config_in_flight == 0, "ACK timeout leaked config ownership");

  reset_fixture();
  command = stepper_command("stop");
  const I2CStepperDevice beforeDeviceError = i2cStepperPump;
  bus.registers[I2CSTEP_REG_ERROR] = 7;
  check(execute_pending_i2c_stepper(command) ==
            OPERATION_ERROR_I2C_DEVICE_ERROR,
        "device error byte was not reported");
  check(same_device(beforeDeviceError, i2cStepperPump),
        "device error committed candidate");

  reset_fixture();
  command = stepper_command("stop");
  const I2CStepperDevice beforeRefresh = i2cStepperPump;
  bus.failProbeAt = 2;
  check(execute_pending_i2c_stepper(command) ==
            OPERATION_ERROR_I2C_REFRESH_FAILED,
        "forced confirm refresh failure was not reported");
  check(bus.commandWrites == 1 && same_device(beforeRefresh, i2cStepperPump),
        "confirm refresh failure duplicated command or committed candidate");
  check(i2c_config_in_flight == 0, "refresh failure leaked config ownership");
}

static void test_generic_calibration_has_no_profile_side_effects() {
  reset_fixture();
  PendingI2CStepperCmd command = stepper_command("calstart");
  check(execute_pending_i2c_stepper(command) == OPERATION_ERROR_NONE,
        "generic calstart failed");
  check(persistCalls == 0 && !I2CPumpCalibrating,
        "generic calstart persisted or changed calibration owner state");

  reset_fixture();
  command = stepper_command("calfinish");
  check(execute_pending_i2c_stepper(command) == OPERATION_ERROR_NONE,
        "generic calfinish failed");
  check(persistCalls == 0 && !I2CPumpCalibrating,
        "generic calfinish persisted or changed calibration owner state");
}

static void test_pump_runtime_commit() {
  reset_fixture();
  PendingI2CPumpCmd command{};
  command.speedSteps = 81;
  command.targetSteps = 910;
  command.targetMl = 12.5f;
  command.fillingMl = 13;
  command.fillingMlHour = 140;
  command.stepsPerMl = 40;
  check(execute_pending_i2c_pump(command) == OPERATION_ERROR_NONE,
        "pump start failed");
  check(I2CPumpCmdSpeed == 81 && I2CPumpTargetSteps == 910 &&
            I2CPumpTargetMl == 12.5f,
        "pump start did not commit runtime state");

  reset_fixture();
  command = {};
  command.speedSteps = 81;
  command.targetSteps = 910;
  command.targetMl = 12.5f;
  command.fillingMl = 13;
  command.fillingMlHour = 140;
  command.stepsPerMl = 40;
  const I2CStepperDevice beforeFailure = i2cStepperPump;
  bus.ackEnabled = false;
  check(execute_pending_i2c_pump(command) ==
            OPERATION_ERROR_I2C_COMMAND_FAILED,
        "pump ACK failure was not reported");
  check(I2CPumpCmdSpeed == 19 && I2CPumpTargetSteps == 29 &&
            I2CPumpTargetMl == 39 && same_device(beforeFailure, i2cStepperPump),
        "failed pump start committed runtime state");

  reset_fixture();
  command = {};
  command.is_stop = true;
  check(execute_pending_i2c_pump(command) == OPERATION_ERROR_NONE,
        "pump stop failed");
  check(I2CPumpCmdSpeed == 0 && I2CPumpTargetMl == 0,
        "pump stop did not clear confirmed runtime state");
}

static void test_i2c_calibration_persistence() {
  reset_fixture();
  PendingI2CCalCmd command{};
  command.pumpMlHour = 120;
  command.stepsPerMl = 44;
  command.cmdSpeed = 55;
  check(execute_pending_i2c_calibration(command) == OPERATION_ERROR_NONE,
        "I2C calibration start failed");
  check(persistCalls == 0 && I2CPumpCalibrating &&
            I2CPumpCmdSpeed == 55 && I2CPumpTargetMl == 0,
        "I2C calibration start committed wrong owner state");

  reset_fixture();
  I2CPumpCalibrating = true;
  set_u16(I2CSTEP_REG_STEPS_PER_ML_H, 77);
  command = {};
  command.is_finish = true;
  check(execute_pending_i2c_calibration(command) == OPERATION_ERROR_NONE,
        "I2C calibration finish failed");
  check(persistCalls == 1 && SamSetup.StepperStepMlI2C == 77 &&
            i2cStepperPump.stepsPerMl == 77 && !I2CPumpCalibrating,
        "I2C calibration finish did not persist and commit exactly once");

  // Отказ записи в NVS не отменяет уже совершённую железом калибровку: значение,
  // подтверждённое насосом, обязано попасть в RAM, иначе ESP считает дозу по
  // старому коэффициенту. Второе значение (88 против 77 выше) отличает реальное
  // применение от хардкода.
  reset_fixture();
  I2CPumpCalibrating = true;
  set_u16(I2CSTEP_REG_STEPS_PER_ML_H, 88);
  persistResult = PERSIST_OPEN_FAILED;
  command = {};
  command.is_finish = true;
  check(execute_pending_i2c_calibration(command) ==
            OPERATION_ERROR_PROFILE_PERSIST_FAILED,
        "I2C calibration persist failure was not reported");
  check(persistCalls == 1 && SamSetup.StepperStepMlI2C == 88 &&
            i2cStepperPump.stepsPerMl == 88 && !I2CPumpCalibrating,
        "persist failure did not commit confirmed calibration to RAM");
  check(i2c_config_in_flight == 0, "persist failure leaked config ownership");
}

static void test_local_calibration_result_mapping() {
  const PumpCalibrationResult pumpResults[] = {
      PUMP_CALIBRATION_INVALID_STATE,
      PUMP_CALIBRATION_INVALID_RESULT,
      PUMP_CALIBRATION_PROFILE_PERSIST_FAILED,
  };
  const OperationError operationResults[] = {
      OPERATION_ERROR_RUNTIME_BUSY,
      OPERATION_ERROR_CALIBRATION_INVALID_RESULT,
      OPERATION_ERROR_PROFILE_PERSIST_FAILED,
  };
  for (size_t index = 0; index < 3; index++) {
    reset_fixture();
    PendingLocalCalCmd command{};
    command.speed = 123;
    calibrationResult = pumpResults[index];
    check(execute_pending_local_calibration(command) == operationResults[index],
          "local calibration result mapping drifted");
    check(calibrationCalls == 1 && CurrrentStepperSpeed == 17,
          "failed local calibration changed confirmed speed");
  }

  reset_fixture();
  PendingLocalCalCmd command{};
  command.speed = 123;
  check(execute_pending_local_calibration(command) == OPERATION_ERROR_NONE,
        "local calibration start failed");
  check(calibrationCalls == 1 && CurrrentStepperSpeed == 123,
        "successful local calibration did not commit speed");
}

int main() {
  test_config_and_transport_failures();
  test_generic_calibration_has_no_profile_side_effects();
  test_pump_runtime_commit();
  test_i2c_calibration_persistence();
  test_local_calibration_result_mapping();
  if (failures != 0) return 1;
  std::cout << "executor harness passed\n";
  return 0;
}
'''
    return (
        harness.replace("@DTO_DEFINITIONS@", dto_definitions)
        .replace("@OWNER_FUNCTIONS@", owner_functions)
    )


def build_lifecycle_harness() -> str:
    samovar_source = read("Samovar.ino")
    dto_definitions = "\n".join(
        definition(samovar_source, f"struct {name}")
        for name in (
            "PendingI2CStepperCmd",
            "PendingI2CPumpCmd",
            "PendingI2CCalCmd",
            "PendingLocalCalCmd",
            "PendingOperationResult",
        )
    )
    owner_definition = definition(
        samovar_source, "enum PendingI2COperationOwner")
    lifecycle_functions = "\n".join(
        (
            wrapped(
                "static bool pending_i2c_operation_matches_locked("
                "OperationId id)",
                samovar_source,
                "static bool pending_i2c_operation_matches_locked(",
            ),
            wrapped(
                "static bool clear_pending_i2c_operation_locked(OperationId id)",
                samovar_source,
                "static bool clear_pending_i2c_operation_locked(",
            ),
            wrapped(
                "static void publish_pending_i2c_result(\n"
                "    OperationId id,\n"
                "    OperationState state,\n"
                "    OperationError error)",
                samovar_source,
                "static void publish_pending_i2c_result(",
            ),
            wrapped(
                "static bool cancel_queued_i2c_operations_locked("
                "bool& cancelled)",
                samovar_source,
                "static bool cancel_queued_i2c_operations_locked(",
            ),
            wrapped(
                "static void process_pending_i2c_operations()",
                samovar_source,
                "static void process_pending_i2c_operations()",
            ),
        )
    )
    harness = r'''
#include <cstdint>
#include <cstring>
#include <deque>
#include <iostream>

#include "operation_store.h"

#define pdMS_TO_TICKS(value) (value)
using TickType_t = int;

struct I2CStepperDevice {
  uint8_t marker;
};

@DTO_DEFINITIONS@
@OWNER_DEFINITION@

OperationStore operationStore{};
PendingI2CStepperCmd pending_i2cstepper_buf{};
volatile bool pending_i2cstepper_flag = false;
PendingI2CPumpCmd pending_i2cpump_buf{};
volatile bool pending_i2cpump_flag = false;
PendingI2CCalCmd pending_i2ccal_buf{};
volatile bool pending_i2ccal_flag = false;
PendingLocalCalCmd pending_local_cal_buf{};
volatile bool pending_local_cal_flag = false;
PendingOperationResult pending_i2c_operation_result{};

static std::deque<bool> pendingLockResults;
static bool modeSwitchInProgress = false;
static int unlockCalls = 0;
static OperationError executorResults[5] = {};
static int executorCalls[5] = {};

static bool pending_command_lock(TickType_t) {
  if (pendingLockResults.empty()) return true;
  const bool result = pendingLockResults.front();
  pendingLockResults.pop_front();
  return result;
}

static void pending_command_unlock(bool) { unlockCalls++; }
static bool mode_switch_in_progress() { return modeSwitchInProgress; }

static OperationError execute_pending_i2c_stepper(
    const PendingI2CStepperCmd&) {
  executorCalls[PENDING_I2C_OPERATION_STEPPER]++;
  return executorResults[PENDING_I2C_OPERATION_STEPPER];
}

static OperationError execute_pending_i2c_pump(const PendingI2CPumpCmd&) {
  executorCalls[PENDING_I2C_OPERATION_PUMP]++;
  return executorResults[PENDING_I2C_OPERATION_PUMP];
}

static OperationError execute_pending_local_calibration(
    const PendingLocalCalCmd&) {
  executorCalls[PENDING_I2C_OPERATION_LOCAL_CALIBRATION]++;
  return executorResults[PENDING_I2C_OPERATION_LOCAL_CALIBRATION];
}

static OperationError execute_pending_i2c_calibration(
    const PendingI2CCalCmd&) {
  executorCalls[PENDING_I2C_OPERATION_I2C_CALIBRATION]++;
  return executorResults[PENDING_I2C_OPERATION_I2C_CALIBRATION];
}

@LIFECYCLE_FUNCTIONS@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static OperationRecord record_for(OperationId id) {
  OperationRecord record{};
  check(operation_store_copy_locked(operationStore, id, record) ==
            OPERATION_ERROR_NONE,
        "operation record missing");
  return record;
}

static void reset_fixture() {
  operationStore = {};
  pending_i2cstepper_buf = {};
  pending_i2cstepper_flag = false;
  pending_i2cpump_buf = {};
  pending_i2cpump_flag = false;
  pending_i2ccal_buf = {};
  pending_i2ccal_flag = false;
  pending_local_cal_buf = {};
  pending_local_cal_flag = false;
  pending_i2c_operation_result = {};
  pendingLockResults.clear();
  modeSwitchInProgress = false;
  unlockCalls = 0;
  for (size_t index = 0; index < 5; index++) {
    executorResults[index] = OPERATION_ERROR_NONE;
    executorCalls[index] = 0;
  }
}

static OperationId queue_fixture(PendingI2COperationOwner owner) {
  OperationKind kind = OPERATION_KIND_CALIBRATION;
  if (owner == PENDING_I2C_OPERATION_STEPPER) {
    kind = OPERATION_KIND_I2C_STEPPER;
  } else if (owner == PENDING_I2C_OPERATION_PUMP) {
    kind = OPERATION_KIND_I2C_PUMP;
  }
  OperationId id = 0;
  check(operation_store_reserve_locked(operationStore, kind, id) ==
            OPERATION_ERROR_NONE,
        "fixture reserve failed");
  switch (owner) {
    case PENDING_I2C_OPERATION_STEPPER:
      pending_i2cstepper_buf.operationId = id;
      pending_i2cstepper_flag = true;
      break;
    case PENDING_I2C_OPERATION_PUMP:
      pending_i2cpump_buf.operationId = id;
      pending_i2cpump_flag = true;
      break;
    case PENDING_I2C_OPERATION_LOCAL_CALIBRATION:
      pending_local_cal_buf.operationId = id;
      pending_local_cal_flag = true;
      break;
    case PENDING_I2C_OPERATION_I2C_CALIBRATION:
      pending_i2ccal_buf.operationId = id;
      pending_i2ccal_flag = true;
      break;
    case PENDING_I2C_OPERATION_NONE:
      check(false, "invalid fixture owner");
      break;
  }
  return id;
}

static bool owner_pending(PendingI2COperationOwner owner) {
  switch (owner) {
    case PENDING_I2C_OPERATION_STEPPER: return pending_i2cstepper_flag;
    case PENDING_I2C_OPERATION_PUMP: return pending_i2cpump_flag;
    case PENDING_I2C_OPERATION_LOCAL_CALIBRATION:
      return pending_local_cal_flag;
    case PENDING_I2C_OPERATION_I2C_CALIBRATION: return pending_i2ccal_flag;
    case PENDING_I2C_OPERATION_NONE: return false;
  }
  return false;
}

static void test_each_owner_lifecycle() {
  for (int rawOwner = PENDING_I2C_OPERATION_STEPPER;
       rawOwner <= PENDING_I2C_OPERATION_I2C_CALIBRATION; rawOwner++) {
    reset_fixture();
    const PendingI2COperationOwner owner =
        static_cast<PendingI2COperationOwner>(rawOwner);
    const OperationId id = queue_fixture(owner);
    process_pending_i2c_operations();
    check(record_for(id).state == OPERATION_STATE_RUNNING,
          "owner did not transition to RUNNING");
    check(executorCalls[owner] == 1 && pending_i2c_operation_result.pending,
          "owner did not execute once and publish terminal draft");
    process_pending_i2c_operations();
    check(record_for(id).state == OPERATION_STATE_SUCCEEDED,
          "owner did not publish success");
    check(executorCalls[owner] == 1 && !owner_pending(owner) &&
              !pending_i2c_operation_result.pending,
          "success publication repeated side effect or retained DTO");
  }

  reset_fixture();
  const OperationId id = queue_fixture(PENDING_I2C_OPERATION_PUMP);
  executorResults[PENDING_I2C_OPERATION_PUMP] =
      OPERATION_ERROR_I2C_COMMAND_FAILED;
  process_pending_i2c_operations();
  process_pending_i2c_operations();
  const OperationRecord failed = record_for(id);
  check(failed.state == OPERATION_STATE_FAILED &&
            failed.error == OPERATION_ERROR_I2C_COMMAND_FAILED,
        "executor failure did not reach terminal record");
}

static void test_mode_barrier_and_discard() {
  reset_fixture();
  const OperationId barrierId = queue_fixture(PENDING_I2C_OPERATION_PUMP);
  modeSwitchInProgress = true;
  process_pending_i2c_operations();
  check(record_for(barrierId).state == OPERATION_STATE_QUEUED &&
            executorCalls[PENDING_I2C_OPERATION_PUMP] == 0 &&
            pending_i2cpump_flag,
        "mode barrier claimed or discarded queued operation");

  reset_fixture();
  const OperationId queuedId = queue_fixture(PENDING_I2C_OPERATION_STEPPER);
  bool cancelled = false;
  check(cancel_queued_i2c_operations_locked(cancelled),
        "queued cancellation returned failure");
  const OperationRecord queued = record_for(queuedId);
  check(cancelled && queued.state == OPERATION_STATE_FAILED &&
            queued.error == OPERATION_ERROR_CANCELLED &&
            !pending_i2cstepper_flag,
        "queued cancellation did not fail and clear DTO");

  reset_fixture();
  const OperationId runningId = queue_fixture(PENDING_I2C_OPERATION_PUMP);
  check(operation_store_mark_running_locked(operationStore, runningId) ==
            OPERATION_ERROR_NONE,
        "running fixture transition failed");
  cancelled = false;
  check(cancel_queued_i2c_operations_locked(cancelled),
        "running discard returned failure");
  check(cancelled && record_for(runningId).state == OPERATION_STATE_RUNNING &&
            pending_i2cpump_flag,
        "running discard cleared an owned operation");
}

static void test_terminal_retry_has_no_duplicate_side_effect() {
  reset_fixture();
  const OperationId id = queue_fixture(PENDING_I2C_OPERATION_PUMP);
  process_pending_i2c_operations();
  check(executorCalls[PENDING_I2C_OPERATION_PUMP] == 1 &&
            record_for(id).state == OPERATION_STATE_RUNNING,
        "retry fixture did not execute once");

  pendingLockResults.push_back(false);
  process_pending_i2c_operations();
  check(executorCalls[PENDING_I2C_OPERATION_PUMP] == 1 &&
            record_for(id).state == OPERATION_STATE_RUNNING &&
            pending_i2c_operation_result.pending && pending_i2cpump_flag,
        "failed terminal lock lost draft or repeated side effect");

  process_pending_i2c_operations();
  check(executorCalls[PENDING_I2C_OPERATION_PUMP] == 1 &&
            record_for(id).state == OPERATION_STATE_SUCCEEDED &&
            !pending_i2c_operation_result.pending && !pending_i2cpump_flag,
        "terminal retry did not complete exactly once");
}

static void test_clear_targets_only_matching_owner() {
  reset_fixture();
  const OperationId first = queue_fixture(PENDING_I2C_OPERATION_STEPPER);
  const OperationId second = queue_fixture(PENDING_I2C_OPERATION_PUMP);
  check(clear_pending_i2c_operation_locked(first),
        "matching clear returned false");
  check(!pending_i2cstepper_flag && pending_i2cpump_flag &&
            pending_i2cpump_buf.operationId == second,
        "clear changed an unrelated owner");
}

int main() {
  test_each_owner_lifecycle();
  test_mode_barrier_and_discard();
  test_terminal_retry_has_no_duplicate_side_effect();
  test_clear_targets_only_matching_owner();
  if (failures != 0) return 1;
  std::cout << "lifecycle harness passed\n";
  return 0;
}
'''
    return (
        harness.replace("@DTO_DEFINITIONS@", dto_definitions)
        .replace("@OWNER_DEFINITION@", owner_definition)
        .replace("@LIFECYCLE_FUNCTIONS@", lifecycle_functions)
    )


def compile_and_run_harness(
    name: str,
    source: str,
    extra_files: dict[str, str] | None = None,
    copy_i2c_header: bool = False,
) -> None:
    compiler = shutil.which("g++")
    if compiler is None:
        errors.append("g++ is required for A-02 behavioral harnesses")
        return
    with tempfile.TemporaryDirectory(prefix=f"samovar-a02-{name}-") as tmp:
        tmp_path = Path(tmp)
        if extra_files:
            for relative_name, contents in extra_files.items():
                (tmp_path / relative_name).write_text(contents, encoding="utf-8")
        if copy_i2c_header:
            shutil.copy2(ROOT / "I2CStepper.h", tmp_path / "I2CStepper.h")
        source_path = tmp_path / f"{name}.cpp"
        binary_path = tmp_path / name
        source_path.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(
            [
                compiler,
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(tmp_path),
                "-I",
                str(ROOT),
                str(source_path),
                "-o",
                str(binary_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append(
                f"{name} harness compile failed:\n{compile_result.stderr.strip()}"
            )
            return
        run_result = subprocess.run(
            [str(binary_path)], capture_output=True, text=True, check=False
        )
        if run_result.returncode != 0:
            output = "\n".join(
                part for part in (run_result.stdout.strip(), run_result.stderr.strip())
                if part
            )
            errors.append(f"{name} harness failed:\n{output}")


operation_store = strip_cpp_comments(read("operation_store.h"))
samovar = strip_cpp_comments(read("Samovar.ino"))
web = strip_cpp_comments(read("WebServer.ino"))
api = strip_cpp_comments(read("samovar_api.h"))
logic = strip_cpp_comments(read("logic.h"))
i2c_page = read("data_raw/i2cstepper.htm")
calibrate_page = read("data_raw/calibrate.htm")

for token in (
    "OPERATION_ERROR_I2C_CONFIG_BUSY",
    'return "i2c_config_busy";',
    "OPERATION_ERROR_I2C_COMMAND_FAILED",
    'return "i2c_command_failed";',
    "OPERATION_ERROR_I2C_DEVICE_ERROR",
    'return "i2c_device_error";',
    "OPERATION_ERROR_I2C_REFRESH_FAILED",
    'return "i2c_refresh_failed";',
    "OPERATION_ERROR_CALIBRATION_INVALID_RESULT",
    'return "calibration_invalid_result";',
):
    if token not in operation_store:
        errors.append(f"operation_store.h missing A-02 error contract: {token}")

for token in (
    "enum PumpCalibrationResult",
    "PUMP_CALIBRATION_OK",
    "PUMP_CALIBRATION_INVALID_STATE",
    "PUMP_CALIBRATION_INVALID_RESULT",
    "PUMP_CALIBRATION_PROFILE_PERSIST_FAILED",
    "PumpCalibrationResult pump_calibrate(int stpspeed);",
):
    if token not in api:
        errors.append(f"samovar_api.h missing calibration result contract: {token}")

for struct_name, cap in (
    ("PendingI2CStepperCmd", 64),
    ("PendingI2CPumpCmd", 24),
    ("PendingI2CCalCmd", 12),
    ("PendingLocalCalCmd", 8),
):
    match = re.search(rf"struct\s+{struct_name}\s*\{{(?P<body>.*?)\}};", samovar, re.S)
    if not match:
        errors.append(f"Samovar.ino missing {struct_name}")
        continue
    if "OperationId operationId;" not in match.group("body"):
        errors.append(f"{struct_name} missing operationId")
    if f"sizeof({struct_name}) <= {cap}" not in samovar:
        errors.append(f"{struct_name} missing <= {cap} byte budget")

for prototype in (
    "static OperationError execute_pending_i2c_stepper(\n"
    "    const PendingI2CStepperCmd& command);",
    "static OperationError execute_pending_i2c_pump(\n"
    "    const PendingI2CPumpCmd& command);",
    "static OperationError execute_pending_i2c_calibration(\n"
    "    const PendingI2CCalCmd& command);",
    "static OperationError execute_pending_local_calibration(\n"
    "    const PendingLocalCalCmd& command);",
):
    if prototype not in samovar:
        errors.append(f"Samovar.ino missing Arduino-safe prototype: {prototype}")

result_match = re.search(
    r"struct\s+PendingOperationResult\s*\{(?P<body>.*?)\};", samovar, re.S)
if not result_match:
    errors.append("Samovar.ino missing PendingOperationResult")
else:
    fields = " ".join(result_match.group("body").split())
    expected = (
        "OperationId id; OperationState state; OperationError error; bool pending;"
    )
    if fields != expected:
        errors.append(f"PendingOperationResult field drift: {fields}")
if "sizeof(PendingOperationResult) <= 8" not in samovar:
    errors.append("PendingOperationResult missing <= 8 byte budget")

queue_specs = (
    ("queue_pending_i2cstepper", "OPERATION_KIND_I2C_STEPPER", "pending_i2cstepper_buf", "pending_i2cstepper_flag"),
    ("queue_pending_i2cpump", "OPERATION_KIND_I2C_PUMP", "pending_i2cpump_buf", "pending_i2cpump_flag"),
    ("queue_pending_i2ccal", "OPERATION_KIND_CALIBRATION", "pending_i2ccal_buf", "pending_i2ccal_flag"),
    ("queue_pending_local_cal", "OPERATION_KIND_CALIBRATION", "pending_local_cal_buf", "pending_local_cal_flag"),
)
for name, kind, slot, flag in queue_specs:
    queue = body(web, f"static OperationError {name}(")
    require_ordered_tokens(
        f"{name} atomic reserve/publication",
        queue,
        [
            "pending_command_lock(pdMS_TO_TICKS(50))",
            "mode_switch_in_progress()",
            "operation_store_reserve_locked(",
            kind,
            "command.operationId = reservedId;",
            f"{slot} = command;",
            "__sync_synchronize();",
            f"{flag} = true;",
            "operationId = reservedId;",
            "pending_command_unlock(true);",
        ],
        errors,
    )
    if queue.count("operation_store_reserve_locked(") != 1:
        errors.append(f"{name} must reserve exactly once")
    publication_at = queue.find("command.operationId = reservedId;")
    if publication_at >= 0 and any(
        token in queue[publication_at:queue.find(f"{flag} = true;", publication_at)]
        for token in ("return ", "pending_command_unlock")
    ):
        errors.append(f"{name} can fail between reserve and DTO publication")

process = body(samovar, "static void process_pending_i2c_operations()")
cancel = body(samovar, "static bool cancel_queued_i2c_operations_locked(")
discard = body(web, "static bool discard_pending_mode_control_commands(")
loop = body(samovar, "void loop()")
stepper_execute = definition_body(
    samovar, "static OperationError execute_pending_i2c_stepper(")
pump_execute = definition_body(
    samovar, "static OperationError execute_pending_i2c_pump(")
i2c_cal_execute = definition_body(
    samovar, "static OperationError execute_pending_i2c_calibration(")
local_cal_execute = definition_body(
    samovar, "static OperationError execute_pending_local_calibration(")
confirm_candidate = body(samovar, "static OperationError confirm_i2c_candidate(")

require_ordered_tokens(
    "A-02 loop owner publishes terminal before a new claim",
    process,
    [
        "if (pending_i2c_operation_result.pending)",
        "pending_command_lock(pdMS_TO_TICKS(50))",
        "operation_store_finish_locked(",
        "clear_pending_i2c_operation_locked(",
        "pending_i2c_operation_result = {};",
        "return;",
        "mode_switch_in_progress()",
        "operation_store_mark_running_locked(",
        "pending_command_unlock(true);",
        "publish_pending_i2c_result(",
    ],
    errors,
)
if process.count("operation_store_mark_running_locked(") != 1:
    errors.append("process_pending_i2c_operations must have one shared RUNNING transition")
if process.count("operation_store_finish_locked(") != 1:
    errors.append("process_pending_i2c_operations must have one terminal publication callsite")
if any(token in process for token in ("save_profile_nvs(", "i2c_stepper_send_command(", "i2c_stepper_start(", "i2c_stepper_stop(")):
    errors.append("process_pending_i2c_operations mixes lifecycle with hardware/NVS execution")

require_ordered_tokens(
    "queued-only mode cancellation",
    cancel,
    [
        "operation_store_copy_locked(",
        "record.state == OPERATION_STATE_RUNNING",
        "record.state != OPERATION_STATE_QUEUED",
        "operation_store_finish_locked(",
        "OPERATION_STATE_FAILED",
        "OPERATION_ERROR_CANCELLED",
        "clear_pending_i2c_operation_locked(",
    ],
    errors,
)
for token in ("operation_store_mark_running_locked(", "i2c_stepper_", "save_profile_nvs("):
    if token in cancel:
        errors.append(f"cancel_queued_i2c_operations_locked owns forbidden action: {token}")
if "cancel_queued_i2c_operations_locked(" not in discard:
    errors.append("mode-switch discard does not delegate A-02 queued cancellation")

require_ordered_tokens(
    "loop A-02 owner order",
    loop,
    [
        "process_profile_operation();",
        "process_pending_i2c_operations();",
        "if (mode_switch_in_progress())",
    ],
    errors,
)
if loop.count("process_pending_i2c_operations();") != 1:
    errors.append("loop must call process_pending_i2c_operations exactly once")

for name, executor in (
    ("stepper", stepper_execute),
    ("pump", pump_execute),
    ("i2c calibration", i2c_cal_execute),
):
    if "pending_command_lock(" in executor:
        errors.append(f"{name} executor performs hardware/NVS under pending lock")
    require_ordered_tokens(
        f"{name} config transaction",
        executor,
        ["i2c_stepper_config_begin(", "I2CStepperDevice candidate", "i2c_stepper_config_end("],
        errors,
    )

for token in ("save_profile_nvs(", "I2CPumpCalibrating =", "SamSetup ="):
    if token in stepper_execute:
        errors.append(f"generic I2C stepper path owns calibration profile side effect: {token}")
if i2c_cal_execute.count("save_profile_nvs(") != 1:
    errors.append("/calibrate I2C owner must persist exactly once")
# Подтверждённая железом калибровка фиксируется в RAM ДО записи в NVS: отменить
# уже совершённое насосом действие отказом записи нельзя, а дозу ESP считает по
# SamSetup.StepperStepMlI2C. Порядок обратный staging-схеме и потому закреплён.
require_ordered_tokens(
    "/calibrate I2C finish commit order",
    i2c_cal_execute,
    [
        "i2c_stepper_send_command(",
        "confirm_i2c_candidate(candidate)",
        "SamSetup.StepperStepMlI2C = candidate.stepsPerMl;",
        "i2cStepperPump = candidate;",
        "I2CPumpCalibrating = false;",
        "save_profile_nvs(SamSetup)",
    ],
    errors,
)
require_ordered_tokens(
    "forced refresh confirmation",
    confirm_candidate,
    ["i2c_stepper_refresh(candidate, true)", "i2c_command_result(true, candidate)"],
    errors,
)
for token in (
    "PUMP_CALIBRATION_INVALID_STATE",
    "PUMP_CALIBRATION_INVALID_RESULT",
    "PUMP_CALIBRATION_PROFILE_PERSIST_FAILED",
):
    if token not in local_cal_execute:
        errors.append(f"local calibration operation missing result mapping: {token}")

pump_calibrate = body(logic, "PumpCalibrationResult pump_calibrate(int stpspeed)")
for token in (
    "return PUMP_CALIBRATION_INVALID_STATE;",
    "return PUMP_CALIBRATION_INVALID_RESULT;",
    "return PUMP_CALIBRATION_PROFILE_PERSIST_FAILED;",
    "return PUMP_CALIBRATION_OK;",
):
    if token not in pump_calibrate:
        errors.append(f"pump_calibrate missing explicit result: {token}")

for route in ("/i2cstepper", "/i2cpump", "/calibrate"):
    matches = re.findall(rf'server\.on\("{re.escape(route)}"\s*,\s*(HTTP_[A-Z_]+)', web)
    if matches != ["HTTP_GET"]:
        errors.append(f"route/method drift for {route}: {matches}")
for forbidden in ('server.on("/operation"', "xTaskCreate", "xQueueCreate", "xSemaphoreCreate"):
    a02_scope = "\n".join(
        [process, cancel, stepper_execute, pump_execute, i2c_cal_execute, local_cal_execute]
    )
    if forbidden in a02_scope:
        errors.append(f"A-02 introduced forbidden route/task/queue/mutex token: {forbidden}")

for page_name, page in (("i2cstepper", i2c_page), ("calibrate", calibrate_page)):
    for token in ("SamovarApp.readOperationAcceptance", "SamovarApp.waitForOperation"):
        if token not in page:
            errors.append(f"{page_name} UI missing A-12 waiter token: {token}")
    if "/operation" in page:
        errors.append(f"{page_name} UI uses forbidden operation endpoint")

try:
    compile_and_run_harness(
        "executor",
        build_executor_harness(),
        executor_fake_headers(),
        copy_i2c_header=True,
    )
    compile_and_run_harness("lifecycle", build_lifecycle_harness())
except ValueError as exc:
    errors.append(f"A-02 harness extraction failed: {exc}")

if errors:
    print("A-02 I2C operation results smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("A-02 I2C operation results smoke passed")
