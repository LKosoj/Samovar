#!/usr/bin/env python3
"""Хелперы, у которых действия обязаны идти парой.

Волна дедупликации свернула повторяющиеся куски в общие хелперы. У выигрыша есть
обратная сторона: раньше пропажа строки ломала одно место, теперь - все точки вызова
разом. Опаснее всего пары «взял замок - отдал замок» и «выставил флаг - обновил его
метку времени»: компилятор молчит (это не неиспользуемая переменная, а логика),
а последствие - зависший навсегда замок или замерший счётчик связи.

Тест не повторяет логику хелперов, а вынимает их тела из исходников и требует, чтобы
обязательные строки стояли в нужном порядке. Добавляя очередной такой хелпер, допишите
сюда кортеж - отдельный тест заводить не нужно.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

# (файл, сигнатура для поиска тела, зачем это важно, обязательные токены по порядку)
HELPERS = [
    (
        "runtime_helpers.h",
        "inline bool assign_locked_runtime_field(",
        "не отдав runtime_state_lock, вешает ajax-снимок состояния и Lua-мост",
        [
            "runtime_state_lock(timeout)",
            "if (!locked) return false;",
            "destination = value;",
            "runtime_state_unlock(true);",
            "return true;",
        ],
    ),
    (
        "Menu.ino",
        "struct LcdLockGuard",
        "деструктор - единственное место, где отдаётся I2C-замок всех восьми функций меню",
        [
            "acquired(xSemaphoreTake(xI2CSemaphore, timeout) == pdTRUE)",
            "~LcdLockGuard() { if (acquired) xSemaphoreGive(xI2CSemaphore); }",
            "explicit operator bool() const { return acquired; }",
        ],
    ),
    (
        "I2CStepper.h",
        "inline bool set_i2c_rele_state(",
        "кэш выбранного устройства меняется только после записи и подтверждённого RELAY",
        [
            "I2CStepperDevice* device = select_relay_capable_device();",
            "if (!device) return false;",
            "if (!i2c_stepper_config_begin(*device)) return false;",
            "I2CStepperDevice candidate = *device;",
            "if (!i2c_stepper_read_config(candidate))",
            "i2c_stepper_write_config(candidate)",
            "i2c_stepper_send_command(candidate, I2CSTEPPER_V3_CMD_RELAY)",
            "if (succeeded) *device = candidate;",
            "i2c_stepper_config_end(*device);",
            "return succeeded;",
        ],
    ),
    (
        "I2CStepper.h",
        "inline uint8_t get_i2c_rele_state(",
        "чтение реле использует тот же выбранный v3 device",
        [
            "I2CStepperDevice* device = select_relay_capable_device();",
            "return !device || relay < 1 || relay > 4 ? 0xFF :",
            "device->config.relayMask",
        ],
    ),
    (
        "mod_rmv.ino",
        "static void rmvk_mark_online()",
        "без метки времени признак «регулятор на связи» больше не обновляется",
        [
            "reg_online = true;",
            "last_reg_online = millis();",
        ],
    ),
]


def relay_action_errors(body: str) -> list[str]:
    errors: list[str] = []
    require_ordered_tokens(
        "I2CStepper.h set_i2c_rele_state v3 action",
        body,
        [
            "I2CStepperDevice* device = select_relay_capable_device();",
            "if (!device) return false;",
            "if (!i2c_stepper_config_begin(*device)) return false;",
            "I2CStepperDevice candidate = *device;",
            "if (!i2c_stepper_read_config(candidate))",
            "i2c_stepper_write_config(candidate)",
            "i2c_stepper_send_command(candidate, I2CSTEPPER_V3_CMD_RELAY)",
            "if (succeeded) *device = candidate;",
            "i2c_stepper_config_end(*device);",
            "return succeeded;",
        ],
        errors,
    )
    if "i2c_stepper_apply(" in body:
        errors.append("I2CStepper.h set_i2c_rele_state must not send APPLY")
    if body.count("i2c_stepper_read_config(candidate)") != 1:
        errors.append("I2CStepper.h set_i2c_rele_state must read fresh mask once before RELAY")
    return errors


RELAY_HARNESS = r'''
#include <cstdint>
#include <iostream>

constexpr uint8_t I2CSTEPPER_V3_CMD_APPLY = 1;
constexpr uint8_t I2CSTEPPER_V3_CMD_RELAY = 7;

struct I2CStepperV3Config { uint8_t relayMask; };
struct I2CStepperDevice {
  bool present;
  uint8_t address;
  I2CStepperV3Config config;
};

static I2CStepperDevice device = {true, 2, {0}};
static I2CStepperDevice* selectedDevice = &device;
static bool configLocked = false;
static bool writeSucceeds = true;
static bool relaySucceeds = true;
static bool readSucceeds = true;
static uint8_t stagedRelayMask = 0;
static uint8_t physicalRelayMask = 0;
static uint8_t lastCommand = 0;
static int writeCalls = 0;
static int commandCalls = 0;
static int readCalls = 0;

I2CStepperDevice* select_relay_capable_device() {
  return selectedDevice && selectedDevice->present ? selectedDevice : nullptr;
}
bool i2c_stepper_config_begin(const I2CStepperDevice&) {
  if (configLocked) return false;
  configLocked = true;
  return true;
}
void i2c_stepper_config_end(const I2CStepperDevice&) { configLocked = false; }
bool i2c_stepper_write_config(I2CStepperDevice& candidate) {
  writeCalls++;
  stagedRelayMask = candidate.config.relayMask;
  return writeSucceeds;
}
bool i2c_stepper_send_command(I2CStepperDevice&, uint8_t command) {
  commandCalls++;
  lastCommand = command;
  if (!relaySucceeds) return false;
  physicalRelayMask = stagedRelayMask;
  return true;
}
bool i2c_stepper_read_config(I2CStepperDevice& candidate) {
  readCalls++;
  if (!readSucceeds) return false;
  candidate.config.relayMask = physicalRelayMask;
  return true;
}
bool i2c_stepper_apply(I2CStepperDevice& candidate) {
  return i2c_stepper_write_config(candidate) &&
      i2c_stepper_send_command(candidate, I2CSTEPPER_V3_CMD_APPLY);
}

inline bool set_i2c_rele_state(uint8_t relay, bool state) {
@RELAY_BODY@
}

static int failures = 0;
void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
void reset(uint8_t cachedMask, uint8_t physicalMask) {
  device = {true, 2, {cachedMask}};
  selectedDevice = &device;
  configLocked = false;
  writeSucceeds = true;
  relaySucceeds = true;
  readSucceeds = true;
  stagedRelayMask = physicalMask;
  physicalRelayMask = physicalMask;
  lastCommand = 0;
  writeCalls = commandCalls = readCalls = 0;
}

int main() {
  reset(0x00, 0x02);
  check(set_i2c_rele_state(1, true), "successful relay update must succeed");
  check(device.config.relayMask == 0x03 && physicalRelayMask == 0x03,
        "fresh Nano relay mask must win over stale ESP cache");
  check(writeCalls == 1 && commandCalls == 1 && readCalls == 1 &&
            lastCommand == I2CSTEPPER_V3_CMD_RELAY,
        "successful relay update sends one RELAY command after one fresh read");
  check(!configLocked, "successful relay update releases config guard");

  reset(0x00, 0x02);
  writeSucceeds = false;
  check(!set_i2c_rele_state(1, true), "config write failure must fail relay update");
  check(device.config.relayMask == 0x00 && physicalRelayMask == 0x02,
        "config write failure leaves cache and physical relay unchanged");
  check(writeCalls == 1 && commandCalls == 0 && readCalls == 1 && !configLocked,
        "config write failure stops before RELAY and releases guard");

  reset(0x00, 0x02);
  relaySucceeds = false;
  check(!set_i2c_rele_state(1, true), "RELAY failure must fail relay update");
  check(device.config.relayMask == 0x00 && physicalRelayMask == 0x02,
        "RELAY failure after staging leaves active physical value and cache unchanged");
  check(writeCalls == 1 && commandCalls == 1 && readCalls == 1 && !configLocked,
        "RELAY failure does not read back or retain guard");

  reset(0x00, 0x02);
  readSucceeds = false;
  check(!set_i2c_rele_state(1, true), "fresh-mask read failure must fail relay update");
  check(physicalRelayMask == 0x02 && device.config.relayMask == 0x00,
        "fresh-mask read failure must leave cache and physical relay unchanged");
  check(writeCalls == 0 && commandCalls == 0 && readCalls == 1 && !configLocked,
        "fresh-mask read failure must release guard before staging");

  reset(0x00, 0x03);
  check(set_i2c_rele_state(1, false), "relay off must succeed from fresh mask");
  check(physicalRelayMask == 0x02 && device.config.relayMask == 0x02,
        "relay off must change only the requested fresh bit");
  return failures == 0 ? 0 : 1;
}
'''


def run_relay_harness(body: str) -> subprocess.CompletedProcess[str]:
    compiler = shutil.which("g++")
    if compiler is None:
        raise RuntimeError("g++ is required for relay helper smoke")
    with tempfile.TemporaryDirectory(prefix="samovar-relay-helper-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "relay_helper_test.cpp"
        binary = temp / "relay_helper_test"
        source.write_text(RELAY_HARNESS.replace("@RELAY_BODY@", body), encoding="utf-8")
        compiled = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source),
             "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            return compiled
        return subprocess.run([str(binary)], capture_output=True, text=True, check=False)


def main() -> int:
    for file_name, signature, why, tokens in HELPERS:
        path = ROOT / file_name
        if not path.exists():
            errors.append(f"{file_name} not found")
            continue
        # strip_cpp_comments до поиска тела: закомментированная строка кода всё ещё
        # содержит текст токена как подстроку, поэтому без вырезания комментариев тест
        # пропустил бы «// xSemaphoreGive(...)» - замок навсегда занят, а тест зелёный.
        source = strip_cpp_comments(path.read_text(encoding="utf-8", errors="ignore"))
        try:
            body = extract_function_body(source, signature)
        except ValueError as exc:
            errors.append(f"{file_name}: {exc} ({why})")
            continue
        require_ordered_tokens(f"{file_name} {signature.strip()} [{why}]", body, tokens, errors)

    source = strip_cpp_comments((ROOT / "I2CStepper.h").read_text(encoding="utf-8", errors="ignore"))
    try:
        relay_body = extract_function_body(source, "inline bool set_i2c_rele_state(")
    except ValueError as exc:
        errors.append(f"I2CStepper.h: {exc}")
        relay_body = ""
    if relay_body:
        mutated = relay_body.replace("I2CSTEPPER_V3_CMD_RELAY", "I2CSTEPPER_V3_CMD_STOP", 1)
        if mutated == relay_body:
            errors.append("set_i2c_rele_state: relay-command mutation anchor missing")
        elif not relay_action_errors(mutated):
            errors.append("set_i2c_rele_state: relay-command mutation survived")
        try:
            result = run_relay_harness(relay_body)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            if result.returncode != 0:
                errors.append("set_i2c_rele_state source-derived harness failed:\n" +
                              result.stdout + result.stderr)
            apply_mutation = relay_body.replace(
                "i2c_stepper_write_config(candidate)",
                "i2c_stepper_apply(candidate)",
                1,
            )
            if apply_mutation == relay_body:
                errors.append("set_i2c_rele_state: APPLY mutation anchor missing")
            else:
                mutated_result = run_relay_harness(apply_mutation)
                if mutated_result.returncode == 0:
                    errors.append("set_i2c_rele_state: APPLY mutation survived")
                elif "successful relay update sends one RELAY command" not in (
                        mutated_result.stdout + mutated_result.stderr):
                    errors.append("set_i2c_rele_state: APPLY mutation failed for an unrelated reason:\n" +
                                  mutated_result.stdout + mutated_result.stderr)
            readback_mutation = relay_body.replace(
                "i2c_stepper_send_command(candidate, I2CSTEPPER_V3_CMD_RELAY);",
                "i2c_stepper_send_command(candidate, I2CSTEPPER_V3_CMD_RELAY) &&\n"
                "      i2c_stepper_read_config(candidate);",
                1,
            )
            if readback_mutation == relay_body:
                errors.append("set_i2c_rele_state: readback mutation anchor missing")
            else:
                mutated_result = run_relay_harness(readback_mutation)
                if mutated_result.returncode == 0:
                    errors.append("set_i2c_rele_state: readback mutation survived")
                elif "after one fresh read" not in (
                        mutated_result.stdout + mutated_result.stderr):
                    errors.append("set_i2c_rele_state: readback mutation failed for an unrelated reason:\n" +
                                  mutated_result.stdout + mutated_result.stderr)
            fresh_read = "if (!i2c_stepper_read_config(candidate)) {\n"
            fresh_read += "    i2c_stepper_config_end(*device);\n"
            fresh_read += "    return false;\n"
            fresh_read += "  }\n"
            fresh_read_mutation = relay_body.replace(fresh_read, "", 1)
            if fresh_read_mutation == relay_body:
                errors.append("set_i2c_rele_state: fresh-read mutation anchor missing")
            else:
                mutated_result = run_relay_harness(fresh_read_mutation)
                if mutated_result.returncode == 0:
                    errors.append("set_i2c_rele_state: fresh-read mutation survived")
                elif "fresh Nano relay mask" not in (
                        mutated_result.stdout + mutated_result.stderr):
                    errors.append("set_i2c_rele_state: fresh-read mutation failed for an unrelated reason:\n" +
                                  mutated_result.stdout + mutated_result.stderr)

    if errors:
        print("helper paired actions smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("helper paired actions smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
