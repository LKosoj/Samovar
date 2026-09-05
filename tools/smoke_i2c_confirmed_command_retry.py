#!/usr/bin/env python3
"""Проверяет повтор I2C-команды с одним sequence до подтверждения.

Харнесс исполняет реальное тело i2c_stepper_send_confirmed_command() из
I2CStepper.h. Конфигурационные регистры не моделируются как часть команды:
каждая попытка обязана повторять только COMMAND и COMMAND_SEQ, причём sequence
остаётся одинаковым во всех десяти попытках.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
I2C = ROOT / "I2CStepper.h"
SIGNATURE = (
    "inline bool i2c_stepper_send_confirmed_command("
    "I2CStepperDevice& dev, uint8_t command)"
)

try:
    helper_body = extract_function_body(
        I2C.read_text(encoding="utf-8", errors="ignore"), SIGNATURE
    )
except ValueError as exc:
    print(f"FAIL: confirmed command helper is missing: {exc}", file=sys.stderr)
    sys.exit(1)

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <vector>

using TickType_t = int;
#define portTICK_PERIOD_MS 1

enum : uint8_t {
  I2CSTEP_REG_MODE = 2,
  I2CSTEP_REG_COMMAND = 16,
  I2CSTEP_REG_COMMAND_SEQ = 17,
  I2CSTEP_REG_ACK_SEQ = 18,
  I2CSTEP_REG_ERROR = 20,
};

struct I2CStepperDevice {
  bool present = true;
  uint8_t address = 2;
  uint8_t commandSeq = 0;
  uint8_t ackSeq = 0;
  uint8_t error = 0;
};

struct WriteCall {
  uint8_t reg;
  uint8_t value;
};

static std::vector<WriteCall> writes;
static int commandSends = 0;
static int refreshCalls = 0;
static int feedLoopWDTCalls = 0;
static int ackOnSend = 0;
static uint8_t reportedError = 0;

inline bool i2c_stepper_write_byte(uint8_t, uint8_t reg, uint8_t value) {
  writes.push_back({reg, value});
  if (reg == I2CSTEP_REG_COMMAND) commandSends++;
  return true;
}

inline bool i2c_stepper_refresh(I2CStepperDevice& dev, bool) {
  refreshCalls++;
  if (ackOnSend > 0 && commandSends >= ackOnSend) {
    dev.ackSeq = writes.back().value;
  }
  return true;
}

inline bool i2c_stepper_read_byte(uint8_t, uint8_t reg, uint8_t& value) {
  if (reg == I2CSTEP_REG_ACK_SEQ) {
    value = ackOnSend > 0 && commandSends >= ackOnSend
        ? writes.back().value
        : 0;
    return true;
  }
  if (reg == I2CSTEP_REG_ERROR) {
    value = reportedError;
    return true;
  }
  return false;
}

void vTaskDelay(TickType_t) {}
void feedLoopWDT() { feedLoopWDTCalls++; }

inline bool i2c_stepper_send_confirmed_command(
    I2CStepperDevice& dev, uint8_t command) {
@HELPER_BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(int confirmedOnSend) {
  writes.clear();
  commandSends = 0;
  refreshCalls = 0;
  feedLoopWDTCalls = 0;
  ackOnSend = confirmedOnSend;
  reportedError = 0;
}

static void check_command_pairs(
    uint8_t command, uint8_t sequence, int expectedSends) {
  check(static_cast<int>(writes.size()) == expectedSends * 2,
        "each send must contain exactly COMMAND and COMMAND_SEQ writes");
  for (int attempt = 0; attempt < expectedSends; attempt++) {
    const WriteCall& commandWrite = writes[attempt * 2];
    const WriteCall& sequenceWrite = writes[attempt * 2 + 1];
    check(commandWrite.reg == I2CSTEP_REG_COMMAND && commandWrite.value == command,
          "every retry must resend the same command");
    check(sequenceWrite.reg == I2CSTEP_REG_COMMAND_SEQ && sequenceWrite.value == sequence,
          "every retry must resend the same sequence");
  }
}

int main() {
  {
    reset_fixture(1);
    I2CStepperDevice dev;
    dev.commandSeq = 7;
    bool ok = i2c_stepper_send_confirmed_command(dev, 41);
    check(ok, "ack on the first send must succeed");
    check(commandSends == 1,
          "first-send ack must stop without duplicate commands");
    check(refreshCalls == 0,
          "confirmed path must not emit legacy refresh fallback messages");
    check(feedLoopWDTCalls == 0,
          "first-send ack must not feed between nonexistent retries");
    check_command_pairs(41, 8, 1);
  }

  {
    reset_fixture(4);
    I2CStepperDevice dev;
    dev.commandSeq = 20;
    bool ok = i2c_stepper_send_confirmed_command(dev, 73);
    check(ok, "ack on a later send must succeed");
    check(commandSends == 4,
          "helper must stop on the exact send that is acknowledged");
    check(refreshCalls == 0,
          "late ack must not use the legacy fallback-reporting refresh path");
    check(feedLoopWDTCalls == 3,
          "watchdog must be fed between four command attempts");
    check_command_pairs(73, 21, 4);
  }

  {
    reset_fixture(0);
    I2CStepperDevice dev;
    dev.commandSeq = 90;
    bool ok = i2c_stepper_send_confirmed_command(dev, 99);
    check(!ok, "ten sends without ack must fail");
    check(commandSends == 10,
          "missing ack must produce exactly ten total command sends");
    check(refreshCalls == 0,
          "missing ack must not claim a local fallback through refresh");
    check(feedLoopWDTCalls == 9,
          "watchdog must be fed between all ten command attempts");
    check_command_pairs(99, 91, 10);
  }

  {
    reset_fixture(2);
    I2CStepperDevice dev;
    dev.commandSeq = 255;
    bool ok = i2c_stepper_send_confirmed_command(dev, 17);
    check(ok, "wrapped sequence must still be acknowledged");
    check_command_pairs(17, 1, 2);
  }

  {
    reset_fixture(1);
    I2CStepperDevice dev;
    reportedError = 4;
    bool ok = i2c_stepper_send_confirmed_command(dev, 18);
    check(!ok, "ack with a device error must not confirm the command");
    check(commandSends == 10,
          "device error must keep retrying the same command ten times");
  }

  {
    reset_fixture(0);
    writes.push_back({I2CSTEP_REG_MODE, 6});
    I2CStepperDevice dev;
    dev.present = false;
    bool ok = i2c_stepper_send_confirmed_command(dev, 33);
    check(!ok, "stale absent cache without ack must fail after retries");
    check(commandSends == 10,
          "stale absent cache must not suppress ten physical command attempts");
    check(writes.front().reg == I2CSTEP_REG_MODE,
          "configuration write must remain separate from command attempts");
  }

  if (failures != 0) return 1;
  std::cout << "i2c confirmed command retry checks passed\n";
  return 0;
}
'''


def run() -> int:
    compiler = shutil.which("g++")
    if compiler is None:
        print("FAIL: g++ is required for confirmed command smoke", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-i2c-confirmed-command-") as tmp:
        tmp_path = Path(tmp)

        def compile_and_run(body: str, name: str) -> subprocess.CompletedProcess[str]:
            source_path = tmp_path / f"{name}.cpp"
            binary_path = tmp_path / name
            source_path.write_text(
                HARNESS.replace("@HELPER_BODY@", body), encoding="utf-8"
            )
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(source_path),
                    "-o",
                    str(binary_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if compile_result.returncode != 0:
                return compile_result
            return subprocess.run(
                [str(binary_path)], capture_output=True, text=True, check=False
            )

        result = compile_and_run(helper_body, "confirmed_command")
        if result.returncode != 0:
            print("FAIL: confirmed command harness failed", file=sys.stderr)
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1

        mutation_anchor = "attempt < 10"
        if helper_body.count(mutation_anchor) != 1:
            print("FAIL: retry-limit mutation anchor is missing", file=sys.stderr)
            return 1
        mutated_body = helper_body.replace(mutation_anchor, "attempt < 9", 1)
        mutated_result = compile_and_run(mutated_body, "confirmed_command_mutated")
        if mutated_result.returncode == 0:
            print(
                "FAIL: retry-limit mutation survived: nine sends passed as ten",
                file=sys.stderr,
            )
            return 1
        if "missing ack must produce exactly ten total command sends" not in (
            mutated_result.stdout + mutated_result.stderr
        ):
            print(
                "FAIL: retry-limit mutation failed for an unrelated reason",
                file=sys.stderr,
            )
            print(mutated_result.stdout + mutated_result.stderr, file=sys.stderr)
            return 1

        watchdog_anchor = "if (attempt + 1 < 10) feedLoopWDT();"
        if helper_body.count(watchdog_anchor) != 1:
            print("FAIL: watchdog mutation anchor is missing", file=sys.stderr)
            return 1
        watchdog_mutated_body = helper_body.replace(
            watchdog_anchor, "if (false) feedLoopWDT();", 1
        )
        watchdog_mutated_result = compile_and_run(
            watchdog_mutated_body, "confirmed_command_watchdog_mutated"
        )
        if watchdog_mutated_result.returncode == 0:
            print(
                "FAIL: watchdog mutation survived: retry loop did not require feeding",
                file=sys.stderr,
            )
            return 1
        if "watchdog must be fed between four command attempts" not in (
            watchdog_mutated_result.stdout + watchdog_mutated_result.stderr
        ):
            print(
                "FAIL: watchdog mutation failed for an unrelated reason",
                file=sys.stderr,
            )
            print(
                watchdog_mutated_result.stdout + watchdog_mutated_result.stderr,
                file=sys.stderr,
            )
            return 1

        print(result.stdout, end="")
        return 0


sys.exit(run())
