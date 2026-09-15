#!/usr/bin/env python3
"""Контракт Blynk V36/V37 I2CStepper v3.

Харнессы компилируют тела новых функций, извлечённые из Blynk.ino и Samovar.ino.
Поэтому проверки смотрят на прошивочный код, а не на его копию в Python. Отдельно
запускаются мутации округления V36, разрешения `save` и Blynk executor.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
BLYNK = ROOT / "Blynk.ino"
SAMOVAR = ROOT / "Samovar.ino"
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"
ERRORS: list[str] = []


def extracted(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        ERRORS.append(str(exc))
        return ""


def compile_and_run(
    name: str, source: str, include_dir: Path | None = None, needs_arduino: bool = False
) -> tuple[int, str]:
    compiler = shutil.which("g++")
    if compiler is None:
        return 1, "g++ is required"
    with tempfile.TemporaryDirectory(prefix=f"samovar-{name}-") as directory:
        directory_path = Path(directory)
        cpp = directory_path / "harness.cpp"
        binary = directory_path / "harness"
        cpp.write_text(source, encoding="utf-8")
        if needs_arduino:
            (directory_path / "Arduino.h").write_text('''#pragma once
#include <cstdint>
#include <cstddef>
#include <string>
class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const char* value, size_t size) : value_(value, size) {}
  String(uint8_t value) : value_(std::to_string(value)) {}
  const char* c_str() const { return value_.c_str(); }
  void toLowerCase() { for (char& value : value_) if (value >= 'A' && value <= 'Z') value += 'a' - 'A'; }
  bool operator==(const char* value) const { return value_ == (value ? value : ""); }
 private:
  std::string value_;
};
''', encoding="utf-8")
        command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)]
        if needs_arduino:
            command[1:1] = ["-I", str(directory_path)]
        if include_dir:
            command[1:1] = ["-I", str(include_dir)]
        built = subprocess.run(command, text=True, capture_output=True, check=False)
        if built.returncode:
            return built.returncode, built.stderr
        ran = subprocess.run([str(binary)], text=True, capture_output=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def v36_harness(remaining: str, writer: str, push: str) -> str:
    return f'''#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#define V36 36
#define I2CSTEPPER_DEVICE_COUNT 10U
#define I2CSTEPPER_V3_MODE_MIXER 1U

class String {{
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {{}}
  void reserve(size_t size) {{ value_.reserve(size); }}
  String& operator+=(char value) {{ value_ += value; return *this; }}
  const std::string& value() const {{ return value_; }}
 private:
  std::string value_;
}};

class Print {{
 public:
  virtual ~Print() = default;
  virtual size_t write(uint8_t value) = 0;
  void print(const char* value) {{ while (*value) write(uint8_t(*value++)); }}
  void print(char value) {{ write(uint8_t(value)); }}
  void print(int value) {{ print(uint32_t(value)); }}
  void print(uint8_t value) {{ print(uint32_t(value)); }}
  void print(uint32_t value) {{ print(std::to_string(value).c_str()); }}
}};

class JsonStringPrint : public Print {{
 public:
  explicit JsonStringPrint(String& value) : value_(value) {{}}
  size_t write(uint8_t value) override {{ value_ += char(value); return 1; }}
 private:
  String& value_;
}};

struct Config {{ uint32_t stepsPerMl; uint8_t relayMask; }};
struct Motion {{ uint32_t speedStepsPerSec; }};
struct Status {{ uint32_t remainingSteps; uint8_t status; uint8_t error; uint8_t mode; uint32_t currentSpeedStepsPerSec; }};
struct I2CStepperDevice {{ bool present; bool everPresent; uint8_t address; uint8_t capabilities; Config config; Motion motion; Status status; }};
I2CStepperDevice i2cSteppers[I2CSTEPPER_DEVICE_COUNT] = {{}};
struct BlynkProbe {{
  std::string payload;
  void virtualWrite(int pin, const String& value) {{ if (pin == V36) payload = value.value(); }}
}} Blynk;

static uint32_t blynk_i2c_v36_remaining(const I2CStepperDevice& device) {{
{remaining}
}}
static void blynk_i2c_v36_write_device(Print& out, const I2CStepperDevice& device) {{
{writer}
}}
static void blynk_push_v36() {{
{push}
}}

int failures = 0;
void check(bool value, const char* message) {{ if (!value) {{ std::cerr << "FAIL: " << message << '\\n'; failures++; }} }}
void reset() {{ std::memset(i2cSteppers, 0, sizeof(i2cSteppers)); Blynk.payload.clear(); }}
void set_device(uint8_t index, bool present, uint8_t mode, uint32_t remaining, uint32_t divisor) {{
  I2CStepperDevice& device = i2cSteppers[index];
  device.everPresent = true; device.present = present; device.address = index + 1;
  device.capabilities = 25; device.status.status = present ? 1 : 0; device.status.error = present ? 0 : 7;
  device.status.mode = mode; device.status.currentSpeedStepsPerSec = 120; device.status.remainingSteps = remaining;
  device.motion.speedStepsPerSec = mode == I2CSTEPPER_V3_MODE_MIXER ? divisor : 0;
  device.config.stepsPerMl = mode == I2CSTEPPER_V3_MODE_MIXER ? 0 : divisor; device.config.relayMask = index;
}}
int main() {{
  reset(); blynk_push_v36();
  check(Blynk.payload == "{{\\\"v\\\":3,\\\"d\\\":[]}}", "zero devices must use compact empty array");

  reset(); set_device(0, true, 1, 121, 120); blynk_push_v36();
  check(Blynk.payload == "{{\\\"v\\\":3,\\\"d\\\":[{{\\\"a\\\":1,\\\"p\\\":1,\\\"c\\\":25,\\\"s\\\":1,\\\"e\\\":0,\\\"m\\\":1,\\\"q\\\":120,\\\"r\\\":2,\\\"l\\\":0}}]}}",
        "one mixer must round seconds up and use only compact keys");

  set_device(1, false, 3, 201, 100); blynk_push_v36();
  check(Blynk.payload == "{{\\\"v\\\":3,\\\"d\\\":[{{\\\"a\\\":1,\\\"p\\\":1,\\\"c\\\":25,\\\"s\\\":1,\\\"e\\\":0,\\\"m\\\":1,\\\"q\\\":120,\\\"r\\\":2,\\\"l\\\":0}},{{\\\"a\\\":2,\\\"p\\\":0,\\\"c\\\":25,\\\"s\\\":0,\\\"e\\\":7,\\\"m\\\":3,\\\"q\\\":120,\\\"r\\\":3,\\\"l\\\":1}}]}}",
        "lost ever-present device must remain p=0 in address order");

  reset(); set_device(0, true, 2, 13, 0); blynk_push_v36();
  check(Blynk.payload.find("\\\"r\\\":0") != std::string::npos,
        "zero conversion divisor must publish zero remaining amount");

  reset();
  for (uint8_t index = 0; index < I2CSTEPPER_DEVICE_COUNT; index++) set_device(index, true, index % 2 ? 2 : 1, 0xffffffffU, 1);
  blynk_push_v36();
  check(Blynk.payload.size() < 1024, "ten worst-case cached devices must fit Blynk payload limit");
  check(Blynk.payload.find("\\\"a\\\":10") != std::string::npos, "all ten addresses must be serialized");
  return failures == 0 ? 0 : 1;
}}
'''


def parser_harness(well_formed: str, known_name: str, parser: str) -> str:
    return f'''#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#define I2CSTEPPER_V3_ADDRESS_MIN 1U
#define I2CSTEPPER_V3_ADDRESS_MAX 10U
#include "i2c_stepper_params.h"
#include "numeric_parse.h"

enum : uint8_t {{ BLYNK_I2C_V37_START = 0, BLYNK_I2C_V37_STOP, BLYNK_I2C_V37_RELAY }};

static bool blynk_i2c_v37_query_well_formed(const char* query) {{
{well_formed}
}}
static bool blynk_i2c_v37_known_name(const String& name) {{
{known_name}
}}
static bool blynk_i2c_v37_parse(const char* query, uint8_t& requestedAddress, uint8_t& command, uint8_t& relay, bool& relayState, String& address, const char*& reason) {{
{parser}
}}

int failures = 0;
void check(bool value, const char* message) {{ if (!value) {{ std::cerr << "FAIL: " << message << '\\n'; failures++; }} }}
void accept(const char* query, uint8_t addressValue, uint8_t expectedCommand, uint8_t expectedRelay, bool expectedState) {{
  uint8_t requestedAddress = 0; uint8_t command = 0; uint8_t relay = 0; bool relayState = false; String address; const char* reason = nullptr;
  check(blynk_i2c_v37_parse(query, requestedAddress, command, relay, relayState, address, reason), query);
  check(requestedAddress == addressValue && command == expectedCommand && relay == expectedRelay && relayState == expectedState, "accepted request fields");
}}
void reject(const char* query, const char* expectedAddress, const char* expectedReason) {{
  uint8_t requestedAddress = 0; uint8_t command = 0; uint8_t relay = 0; bool relayState = false; String address; const char* reason = nullptr;
  check(!blynk_i2c_v37_parse(query, requestedAddress, command, relay, relayState, address, reason), query);
  check(address == expectedAddress && std::strcmp(reason, expectedReason) == 0, "rejection address and reason");
}}
int main() {{
  accept("v=3&address=1&cmd=start", 1, BLYNK_I2C_V37_START, 0, false);
  accept("v=3&address=2&cmd=relay&relay=4&state=1", 2, BLYNK_I2C_V37_RELAY, 4, true);
  accept("v=3&address=10&cmd=STOP", 10, BLYNK_I2C_V37_STOP, 0, false);
  reject("v=3&address=0&cmd=start", "?", "address");
  reject("v=3&address=1&cmd=start&mode=1", "1", "argument request");
  reject("v=3&address=1&cmd=save", "1", "cmd");
  reject("v=3&address=1&cmd=relay&relay=5&state=1", "1", "relay");
  reject("v=3&address=1&cmd=relay&relay=1&state=2", "1", "state");
  reject("v=3&address=1&cmd=start&cmd=stop", "1", "argument request");
  reject("v=3&address=1&cmd=start&x=1", "1", "argument request");
  reject("v=3&address=1&&cmd=start", "1", "argument request");
  return failures == 0 ? 0 : 1;
}}
'''


def executor_harness(executor: str, command_result: str, reporter: str) -> str:
    return f'''#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#include <I2CStepperV3.h>

enum OperationError : uint8_t {{
  OPERATION_ERROR_NONE = 0,
  OPERATION_ERROR_INTERNAL,
  OPERATION_ERROR_I2C_CONFIG_BUSY,
  OPERATION_ERROR_I2C_COMMAND_FAILED,
  OPERATION_ERROR_I2C_DEVICE_ERROR,
  OPERATION_ERROR_I2C_REFRESH_FAILED,
}};

class String {{
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {{}}
  String(uint8_t value) : value_(std::to_string(value)) {{}}
  String& operator+=(const char* value) {{ value_ += value ? value : ""; return *this; }}
  String& operator+=(const String& value) {{ value_ += value.value_; return *this; }}
  String& operator+=(uint8_t value) {{ value_ += std::to_string(value); return *this; }}
  const std::string& value() const {{ return value_; }}
 private:
  std::string value_;
}};

static const int WARNING_MSG = 1;
static std::string lastMessage;
static void SendMsg(const String& message, int) {{ lastMessage = message.value(); }}
static void WriteConsoleLog(const String&) {{}}
static const char* operation_error_code(OperationError error) {{
  switch (error) {{
    case OPERATION_ERROR_I2C_CONFIG_BUSY: return "i2c_config_busy";
    case OPERATION_ERROR_I2C_COMMAND_FAILED: return "i2c_command_failed";
    case OPERATION_ERROR_I2C_DEVICE_ERROR: return "i2c_device_error";
    case OPERATION_ERROR_I2C_REFRESH_FAILED: return "i2c_refresh_failed";
    default: return "internal";
  }}
}}

struct I2CStepperDevice {{
  bool present;
  uint8_t address;
  I2CStepperV3Config config;
  I2CStepperV3Motion motion;
  I2CStepperV3StatusSnapshot status;
}};
struct PendingI2CStepperCmd {{
  uint8_t address;
  uint8_t relay;
  bool relayState;
  I2CStepperV3Config config;
  I2CStepperV3Motion motion;
  char cmd[16];
}};

static I2CStepperDevice devices[10] = {{}};
static I2CStepperDevice* i2c_stepper_device(uint8_t address) {{
  return address >= 1 && address <= 10 ? &devices[address - 1] : nullptr;
}}
static bool configLock = false;
static bool i2c_stepper_config_begin(const I2CStepperDevice&) {{
  if (configLock) return false;
  configLock = true;
  return true;
}}
static void i2c_stepper_config_end(const I2CStepperDevice&) {{ configLock = false; }}

static uint8_t freshRelayMask = 0;
static bool readConfigSucceeds = true;
static bool writeConfigSucceeds = true;
static bool sendSucceeds = true;
static uint8_t sendError = I2CSTEPPER_V3_ERR_NONE;
static int readConfigCalls = 0;
static int writeConfigCalls = 0;
static int confirmCalls = 0;
static int saveCalls = 0;
static int finiteStartCalls = 0;
static int scanBeginCalls = 0;
static uint8_t writtenRelayMask = 0;
static std::vector<uint8_t> sentCommands;

static void i2c_stepper_scan_begin() {{ scanBeginCalls++; }}

static bool i2c_stepper_read_config(I2CStepperDevice& device) {{
  readConfigCalls++;
  if (!readConfigSucceeds) return false;
  device.config.relayMask = freshRelayMask;
  return true;
}}
static bool i2c_stepper_write_config(I2CStepperDevice& device) {{
  writeConfigCalls++;
  writtenRelayMask = device.config.relayMask;
  return writeConfigSucceeds;
}}
static bool i2c_stepper_send_command(I2CStepperDevice& device, uint8_t command) {{
  sentCommands.push_back(command);
  device.status.error = sendError;
  return sendSucceeds;
}}
static bool i2c_stepper_apply(I2CStepperDevice&) {{ return true; }}
static bool i2c_stepper_save(I2CStepperDevice&) {{ saveCalls++; return true; }}
static bool i2c_stepper_start_finite(I2CStepperDevice&) {{ finiteStartCalls++; return true; }}
static bool i2c_stepper_stop(I2CStepperDevice& device) {{
  return i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_STOP);
}}
static OperationError confirm_i2c_candidate(I2CStepperDevice&) {{
  confirmCalls++;
  return OPERATION_ERROR_NONE;
}}

static OperationError i2c_command_result(bool commandSucceeded, const I2CStepperDevice& candidate) {{
{command_result}
}}
static void report_blynk_i2c_v37_execution_failure(
    const char* command, uint8_t address, OperationError error,
    const I2CStepperDevice* device) {{
{reporter}
}}
static OperationError execute_pending_i2c_stepper(const PendingI2CStepperCmd& command) {{
{executor}
}}

static int failures = 0;
static void check(bool value, const char* message) {{
  if (!value) {{ std::cerr << "FAIL: " << message << '\\n'; failures++; }}
}}
static I2CStepperV3Config cachedConfig = {{}};
static I2CStepperV3Motion cachedMotion = {{}};
static bool cached_fields_unchanged() {{
  return std::memcmp(&devices[1].config, &cachedConfig, sizeof(cachedConfig)) == 0 &&
      std::memcmp(&devices[1].motion, &cachedMotion, sizeof(cachedMotion)) == 0;
}}
static bool relay_keeps_unrelated_fields(uint8_t relayMask) {{
  I2CStepperV3Config expected = cachedConfig;
  expected.relayMask = relayMask;
  return std::memcmp(&devices[1].config, &expected, sizeof(expected)) == 0 &&
      std::memcmp(&devices[1].motion, &cachedMotion, sizeof(cachedMotion)) == 0;
}}
static void reset() {{
  std::memset(devices, 0, sizeof(devices));
  devices[1].address = 2;
  devices[1].present = true;
  devices[1].config.address = 2;
  devices[1].config.mode = I2CSTEPPER_V3_MODE_PUMP;
  devices[1].config.relayMask = 0x09;
  devices[1].config.stepsPerMl = 17;
  devices[1].config.pumpMlHour = 19;
  devices[1].motion.mode = I2CSTEPPER_V3_MODE_PUMP;
  devices[1].motion.direction = 1;
  devices[1].motion.speedStepsPerSec = 123;
  devices[1].motion.targetSteps = 456;
  cachedConfig = devices[1].config;
  cachedMotion = devices[1].motion;
  devices[1].status.error = I2CSTEPPER_V3_ERR_NONE;
  configLock = false; freshRelayMask = 0; readConfigSucceeds = true;
  writeConfigSucceeds = true;
  sendSucceeds = true; sendError = I2CSTEPPER_V3_ERR_NONE;
  readConfigCalls = writeConfigCalls = confirmCalls = saveCalls = finiteStartCalls = 0;
  scanBeginCalls = 0;
  writtenRelayMask = 0; sentCommands.clear(); lastMessage.clear();
}}
static PendingI2CStepperCmd command(const char* text) {{
  PendingI2CStepperCmd value = {{}};
  value.address = 2;
  std::strncpy(value.cmd, text, sizeof(value.cmd) - 1);
  return value;
}}
int main() {{
  reset();
  PendingI2CStepperCmd scan = command("scan");
  devices[1].present = false;
  check(execute_pending_i2c_stepper(scan) == OPERATION_ERROR_NONE,
        "manual scan must start without a present device");
  check(scanBeginCalls == 1 && sentCommands.empty() && readConfigCalls == 0,
        "manual scan must only restart address discovery");

  reset();
  PendingI2CStepperCmd start = command("blynk_start");
  check(execute_pending_i2c_stepper(start) == OPERATION_ERROR_NONE, "configured start must succeed");
  check(sentCommands.size() == 1 && sentCommands[0] == I2CSTEPPER_V3_CMD_START_CONFIGURED,
        "Blynk start must send only START_CONFIGURED");
  check(readConfigCalls == 0 && writeConfigCalls == 0 && confirmCalls == 0 &&
        saveCalls == 0 && finiteStartCalls == 0,
        "configured start must not read/write/apply/save cached motion");
  check(cached_fields_unchanged(),
        "START_CONFIGURED must preserve cached config and motion");

  reset();
  PendingI2CStepperCmd stop = command("blynk_stop");
  check(execute_pending_i2c_stepper(stop) == OPERATION_ERROR_NONE, "direct stop must succeed");
  check(sentCommands.size() == 1 && sentCommands[0] == I2CSTEPPER_V3_CMD_STOP &&
        readConfigCalls == 0 && writeConfigCalls == 0 && confirmCalls == 0,
        "Blynk stop must send only STOP");
  check(cached_fields_unchanged(), "Blynk STOP must preserve cached config and motion");

  for (const char* runtimeCommand : {{"stop", "calfinish"}}) {{
    reset();
    PendingI2CStepperCmd runtime = command(runtimeCommand);
    check(execute_pending_i2c_stepper(runtime) == OPERATION_ERROR_NONE,
          "runtime command must succeed");
    check(cached_fields_unchanged(),
          "STOP and CALIBRATE_FINISH must preserve cached config and motion");
  }}

  for (const char* draftCommand : {{"apply", "save", "start", "calstart"}}) {{
    reset();
    PendingI2CStepperCmd draft = command(draftCommand);
    draft.config = cachedConfig;
    draft.motion = cachedMotion;
    draft.config.relayMask = 0x06;
    draft.motion.speedStepsPerSec = 321;
    draft.motion.targetSteps = 654;
    check(execute_pending_i2c_stepper(draft) == OPERATION_ERROR_NONE,
          "draft command must succeed");
    check(std::memcmp(&devices[1].config, &draft.config, sizeof(draft.config)) == 0 &&
              std::memcmp(&devices[1].motion, &draft.motion, sizeof(draft.motion)) == 0,
          "draft command must apply exact config and motion DTO");
  }}

  reset();
  PendingI2CStepperCmd relay = command("blynk_relay");
  relay.relay = 1;
  relay.relayState = true;
  devices[1].config.relayMask = 0;
  freshRelayMask = 0x02;
  check(execute_pending_i2c_stepper(relay) == OPERATION_ERROR_NONE, "runtime relay must succeed");
  check(readConfigCalls == 1 && writeConfigCalls == 1 && writtenRelayMask == 0x03 &&
            devices[1].config.relayMask == 0x03,
        "queued Blynk relay must update one fresh Nano bit, not stale ESP mask");
  check(relay_keeps_unrelated_fields(0x03),
        "Blynk relay must preserve cached motion and non-relay config");
  check(sentCommands.size() == 1 && sentCommands[0] == I2CSTEPPER_V3_CMD_RELAY &&
            confirmCalls == 0 && saveCalls == 0,
        "runtime relay must commit RELAY ACK without SAVE or a second readback");

  reset();
  PendingI2CStepperCmd webRelay = command("relay");
  webRelay.relay = 1;
  webRelay.relayState = true;
  devices[1].config.relayMask = 0;
  freshRelayMask = 0x02;
  check(execute_pending_i2c_stepper(webRelay) == OPERATION_ERROR_NONE,
        "web relay must succeed after RELAY ACK");
  check(writeConfigCalls == 1 && sentCommands.size() == 1 &&
            sentCommands[0] == I2CSTEPPER_V3_CMD_RELAY &&
            readConfigCalls == 1 && confirmCalls == 0 &&
            devices[1].config.relayMask == 0x03,
        "queued web relay must commit fresh ACKed mask without post-readback");
  check(relay_keeps_unrelated_fields(0x03),
        "web relay must preserve cached motion and non-relay config");

  reset();
  webRelay = command("relay");
  webRelay.relay = 1;
  webRelay.relayState = true;
  freshRelayMask = 0x02;
  writeConfigSucceeds = false;
  check(execute_pending_i2c_stepper(webRelay) == OPERATION_ERROR_I2C_COMMAND_FAILED,
        "web relay staging failure must fail");
  check(readConfigCalls == 1 && writeConfigCalls == 1 && sentCommands.empty() &&
            devices[1].config.relayMask == cachedConfig.relayMask && confirmCalls == 0,
        "web relay staging failure must not command or commit cache");

  reset();
  webRelay = command("relay");
  webRelay.relay = 1;
  webRelay.relayState = true;
  freshRelayMask = 0x02;
  sendSucceeds = false;
  check(execute_pending_i2c_stepper(webRelay) == OPERATION_ERROR_I2C_COMMAND_FAILED,
        "web relay ACK failure must fail");
  check(readConfigCalls == 1 && writeConfigCalls == 1 && sentCommands.size() == 1 &&
            sentCommands[0] == I2CSTEPPER_V3_CMD_RELAY &&
            devices[1].config.relayMask == cachedConfig.relayMask && confirmCalls == 0,
        "web relay ACK failure must leave cache unchanged");

  reset();
  relay = command("blynk_relay");
  relay.relay = 1;
  relay.relayState = false;
  freshRelayMask = 0x03;
  check(execute_pending_i2c_stepper(relay) == OPERATION_ERROR_NONE,
        "Blynk relay off must succeed");
  check(writtenRelayMask == 0x02 && devices[1].config.relayMask == 0x02,
        "Blynk relay off must clear only requested fresh bit");

  reset();
  webRelay = command("relay");
  webRelay.relay = 1;
  webRelay.relayState = false;
  freshRelayMask = 0x03;
  check(execute_pending_i2c_stepper(webRelay) == OPERATION_ERROR_NONE,
        "web relay off must succeed");
  check(writtenRelayMask == 0x02 && devices[1].config.relayMask == 0x02,
        "web relay off must clear only requested fresh bit");

  reset();
  webRelay = command("relay");
  webRelay.relay = 1;
  webRelay.relayState = true;
  readConfigSucceeds = false;
  check(execute_pending_i2c_stepper(webRelay) == OPERATION_ERROR_I2C_REFRESH_FAILED,
        "web relay fresh-mask read failure must fail");
  check(readConfigCalls == 1 && writeConfigCalls == 0 && sentCommands.empty() &&
            devices[1].config.relayMask == cachedConfig.relayMask,
        "web relay fresh-mask read failure must not stage or commit cache");

  reset();
  relay = command("blynk_relay");
  relay.relay = 1;
  relay.relayState = true;
  freshRelayMask = 0x02;
  writeConfigSucceeds = false;
  check(execute_pending_i2c_stepper(relay) == OPERATION_ERROR_I2C_COMMAND_FAILED,
        "Blynk relay staging failure must fail");
  check(readConfigCalls == 1 && writeConfigCalls == 1 && sentCommands.empty() &&
            devices[1].config.relayMask == cachedConfig.relayMask,
        "Blynk relay staging failure must leave cache unchanged");

  reset();
  relay = command("blynk_relay");
  relay.relay = 1;
  relay.relayState = true;
  freshRelayMask = 0x02;
  sendSucceeds = false;
  check(execute_pending_i2c_stepper(relay) == OPERATION_ERROR_I2C_COMMAND_FAILED,
        "Blynk relay ACK failure must fail");
  check(readConfigCalls == 1 && writeConfigCalls == 1 && sentCommands.size() == 1 &&
            devices[1].config.relayMask == cachedConfig.relayMask,
        "Blynk relay ACK failure must leave cache unchanged");

  reset();
  readConfigSucceeds = false;
  devices[1].status.error = I2CSTEPPER_V3_ERR_REBOOT_REQUIRED;
  check(execute_pending_i2c_stepper(relay) == OPERATION_ERROR_I2C_REFRESH_FAILED,
        "relay readback failure must fail");
  check(lastMessage == "Blynk V37 a=2: i2c_refresh_failed",
        "relay readback failure must not reuse a stale Nano error");

  reset();
  devices[1].present = false;
  check(execute_pending_i2c_stepper(start) == OPERATION_ERROR_I2C_REFRESH_FAILED,
        "absent Blynk address must fail");
  check(lastMessage == "Blynk V37 a=2: i2c_refresh_failed",
        "absent Blynk address must report V26 with address");

  reset();
  sendSucceeds = false;
  sendError = I2CSTEPPER_V3_ERR_REBOOT_REQUIRED;
  check(execute_pending_i2c_stepper(start) == OPERATION_ERROR_I2C_DEVICE_ERROR,
        "Nano reboot-required start must fail");
  check(lastMessage == "Blynk V37 a=2: REBOOT_REQUIRED",
        "Nano reboot-required failure must report exact V26 address and reason");
  return failures == 0 ? 0 : 1;
}}
'''


def check_static_contract(source: str, samovar: str) -> None:
    writer = extracted(source, "static void blynk_i2c_v36_write_device(")
    expected = ['\\"a\\"', '\\"p\\"', '\\"c\\"', '\\"s\\"', '\\"e\\"', '\\"m\\"', '\\"q\\"', '\\"r\\"', '\\"l\\"']
    position = 0
    for key in expected:
        position = writer.find(key, position)
        if position < 0:
            ERRORS.append(f"V36 writer missing key {key}")
            break
        position += len(key)
    if "mixer" in writer or "pump" in writer or "cal" in writer:
        ERRORS.append("V36 writer contains legacy fields")

    try:
        callback, _ = extract_braced_block_after(source, "BLYNK_WRITE(V37)")
    except ValueError as exc:
        ERRORS.append(str(exc))
        callback = ""
    for token in ("blynk_i2c_v37_parse", "queue_blynk_i2c_v37"):
        if token not in callback:
            ERRORS.append(f"V37 callback missing {token}")
    for forbidden in ("Wire.", "i2c_stepper_read_", "i2c_stepper_write_", "i2c_stepper_send_"):
        if forbidden in callback:
            ERRORS.append(f"V37 callback must not use I2C: {forbidden}")

    queue = extracted(source, "static OperationError queue_blynk_i2c_v37(")
    for token in ("pending.address = requestedAddress", '"blynk_start"', '"blynk_stop"',
                  '"blynk_relay"', "pending.relay = relay", "pending.relayState = relayState",
                  "queue_pending_i2cstepper"):
        if token not in queue:
            ERRORS.append(f"V37 queue bridge missing {token}")
    for forbidden in ("pending.config =", "pending.motion ="):
        if forbidden in queue:
            ERRORS.append(f"V37 queue bridge retains stale cache: {forbidden}")
    if "I2CSTEPPER_V3_CMD_START_CONFIGURED" not in samovar:
        ERRORS.append("executor missing START_CONFIGURED")
    if '"REBOOT_REQUIRED"' not in samovar:
        ERRORS.append("executor missing REBOOT_REQUIRED V26 reason")


def main() -> int:
    source = BLYNK.read_text(encoding="utf-8") if BLYNK.exists() else ""
    samovar = SAMOVAR.read_text(encoding="utf-8") if SAMOVAR.exists() else ""
    if not source:
        ERRORS.append("Blynk.ino not found")
    if not samovar:
        ERRORS.append("Samovar.ino not found")
    if ERRORS:
        print("\n".join(ERRORS), file=sys.stderr)
        return 1

    remaining = extracted(source, "static uint32_t blynk_i2c_v36_remaining(")
    writer = extracted(source, "static void blynk_i2c_v36_write_device(")
    push = extracted(source, "static void blynk_push_v36(")
    well_formed = extracted(source, "static bool blynk_i2c_v37_query_well_formed(")
    known_name = extracted(source, "static bool blynk_i2c_v37_known_name(")
    parser = extracted(source, "static bool blynk_i2c_v37_parse(")
    executor = extracted(
        samovar,
        "static OperationError execute_pending_i2c_stepper(\n"
        "    const PendingI2CStepperCmd& command) {")
    command_result = extracted(samovar, "static OperationError i2c_command_result(")
    reporter = extracted(samovar, "static void report_blynk_i2c_v37_execution_failure(")
    check_static_contract(source, samovar)
    if ERRORS:
        print("\n".join(ERRORS), file=sys.stderr)
        return 1

    for name, harness, include_dir, needs_arduino in (
        ("blynk-v36", v36_harness(remaining, writer, push), None, False),
        ("blynk-v37", parser_harness(well_formed, known_name, parser), ROOT, True),
        ("blynk-v37-executor", executor_harness(executor, command_result, reporter), PROTOCOL, False),
    ):
        code, output = compile_and_run(name, harness, include_dir, needs_arduino)
        if code:
            ERRORS.append(f"{name} harness failed:\n{output}")

    rounded_down = remaining.replace("(remaining % divisor != 0 ? 1 : 0)", "0", 1)
    code, _ = compile_and_run("blynk-v36-mutation", v36_harness(rounded_down, writer, push))
    if code == 0:
        ERRORS.append("V36 rounding mutation passed")
    accepts_save = parser.replace(
        'if (commandText == "start")',
        'if (commandText == "start" || commandText == "save")', 1)
    code, _ = compile_and_run(
        "blynk-v37-mutation", parser_harness(well_formed, known_name, accepts_save), ROOT, True)
    if code == 0:
        ERRORS.append("V37 save mutation passed")
    configured_start_mutation = executor.replace(
        "I2CSTEPPER_V3_CMD_START_CONFIGURED", "I2CSTEPPER_V3_CMD_STOP", 1)
    code, _ = compile_and_run(
        "blynk-v37-configured-start-mutation",
        executor_harness(configured_start_mutation, command_result, reporter), PROTOCOL)
    if configured_start_mutation == executor or code == 0:
        ERRORS.append("V37 configured-start mutation passed")
    relay_read_mutation = executor.replace(
        "if (!i2c_stepper_read_config(candidate))", "if (false)", 1)
    code, _ = compile_and_run(
        "blynk-v37-relay-read-mutation",
        executor_harness(relay_read_mutation, command_result, reporter), PROTOCOL)
    if relay_read_mutation == executor or code == 0:
        ERRORS.append("V37 relay current-config mutation passed")
    relay_readback_mutation = executor.replace(
        "      skipReadback = true;\n      commandSucceeded = i2c_stepper_write_config(candidate)",
        "      commandSucceeded = i2c_stepper_write_config(candidate)",
        1)
    code, _ = compile_and_run(
        "blynk-v37-relay-readback-mutation",
        executor_harness(relay_readback_mutation, command_result, reporter), PROTOCOL)
    if relay_readback_mutation == executor or code == 0:
        ERRORS.append("V37 relay readback mutation passed")
    dto_clobber_mutation = executor.replace(
        "if (commandCarriesConfig) {", "if (true) {", 1)
    code, _ = compile_and_run(
        "blynk-v37-dto-clobber-mutation",
        executor_harness(dto_clobber_mutation, command_result, reporter), PROTOCOL)
    if dto_clobber_mutation == executor or code == 0:
        ERRORS.append("V37 DTO clobber mutation passed")

    if ERRORS:
        print("\n".join(ERRORS), file=sys.stderr)
        return 1
    print("smoke_blynk_i2c_v3: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
