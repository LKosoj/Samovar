#!/usr/bin/env python3
"""Проверяет safe-wait после O и только явный подтверждаемый вход в W."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]
ANCHOR = "if (program[num].WType == 'W') {"

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
enum NbkActuatorDeadlineTarget : uint8_t {
  NBK_ACTUATOR_WORK_DEADLINE = 2,
};
class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
  String(float value, int) : value_(std::to_string(value)) {}
  String operator+(const String& rhs) const { return String(value_ + rhs.value_); }
 private:
  explicit String(const std::string& value) : value_(value) {}
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(lhs) + rhs;
}
struct ProgramRow {
  char WType;
  float Power;
  float Speed;
};
struct SessionProbe { bool valid; };
static ProgramRow program[4] = {};
static SessionProbe nbkSessionConfig = {true};
static bool nbk_safe_waiting = false;
static bool nbk_safe_wait_feed_stopped = false;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
static bool PowerOn = true;
static bool transitionActive = false;
static uint16_t nbk_column_inertia = 180;
static uint16_t nbk_opt_iter = 7;
static int safeWaitCalls = 0;
static int scheduleCalls = 0;
static int powerOnCalls = 0;
static bool scheduledCommit = false;
static uint8_t scheduledProgram = 255;
static float scheduledM = -1;
static float scheduledP = -1;

void nbk_enter_safe_wait(const String&) {
  safeWaitCalls++;
  nbk_safe_waiting = true;
  nbk_safe_wait_result = ACTUATOR_COMMAND_APPLIED;
  PowerOn = false;
}
void tick_nbk_safe_wait() {}
bool power_transition_active() { return transitionActive; }
void set_power(bool on, bool = true) {
  powerOnCalls++;
  PowerOn = on;
}
float toPower(float value) { return value * 2.0f; }
bool nbk_schedule_actuator_command(
    float power,
    float speed,
    NbkActuatorDeadlineTarget,
    uint32_t,
    uint16_t,
    bool commit,
    uint8_t programNum) {
  scheduleCalls++;
  scheduledM = power;
  scheduledP = speed;
  scheduledCommit = commit;
  scheduledProgram = programNum;
  return true;
}
void SendMsg(const String&, MESSAGE_TYPE) {}

static void run_w(uint8_t num, bool workConfirmed) {
@BODY@
}
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static void reset_fixture() {
  program[1] = {'W', 500, 6};
  nbkSessionConfig.valid = true;
  nbk_safe_waiting = false;
  nbk_safe_wait_feed_stopped = false;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  PowerOn = true;
  transitionActive = false;
  safeWaitCalls = 0;
  scheduleCalls = 0;
  powerOnCalls = 0;
  scheduledCommit = false;
  scheduledProgram = 255;
  scheduledM = -1;
  scheduledP = -1;
}
int main() {
  reset_fixture();
  run_w(1, false);
  check(safeWaitCalls == 1 && scheduleCalls == 0,
        "автоматический O->W обязан перейти в safe-wait без команды приводам");

  reset_fixture();
  program[1].Power = 0;
  run_w(1, true);
  check(safeWaitCalls == 1 && scheduleCalls == 0,
        "явный W с нулевой мощностью обязан остаться в safe-wait");

  reset_fixture();
  run_w(1, true);
  check(safeWaitCalls == 0 && scheduleCalls == 1,
        "явный W с ненулевыми параметрами должен принять одну команду");
  check(scheduledM == 1000 && scheduledP == 6 &&
            scheduledCommit && scheduledProgram == 1,
        "W должен передать точные M/P и отложенный commit строки");

  reset_fixture();
  nbk_safe_waiting = true;
  nbk_safe_wait_result = ACTUATOR_COMMAND_PENDING;
  PowerOn = false;
  run_w(1, true);
  check(scheduleCalls == 0 && powerOnCalls == 0,
        "W запрещён до terminal APPLIED безопасного останова");

  reset_fixture();
  nbk_safe_waiting = true;
  nbk_safe_wait_result = ACTUATOR_COMMAND_APPLIED;
  PowerOn = false;
  run_w(1, true);
  check(powerOnCalls == 1 && scheduleCalls == 1,
        "только явная команда может вывести подтверждённый safe-wait в W");
  return failures == 0 ? 0 : 1;
}
'''


def run(source: str, emit: bool) -> int:
    try:
        body, _ = extract_braced_block_after(source, ANCHOR)
    except ValueError as error:
        if emit:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    harness = HARNESS.replace("@BODY@", body.replace("\r\n", "\n"))
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-explicit-work-") as temp_dir:
        temp = Path(temp_dir)
        cpp = temp / "test.cpp"
        binary = temp / "test"
        cpp.write_text(harness, encoding="utf-8")
        build = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if build.returncode:
            if emit:
                sys.stderr.write(build.stderr)
            return build.returncode
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
        return result.returncode


def main() -> int:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    if run(source, True) != 0:
        return 1
    mutations = (
        source.replace(
            "if (!workConfirmed) {",
            "if (false && !workConfirmed) {",
            1,
        ),
        source.replace(
            "if (program[num].Power <= 0 || program[num].Speed <= 0) {",
            "if (false && (program[num].Power <= 0 || program[num].Speed <= 0)) {",
            1,
        ),
        source.replace(
            "            true,\n            num))",
            "            false,\n            num))",
            1,
        ),
    )
    if any(mutation == source for mutation in mutations):
        print("FAIL: explicit-W mutation anchor missing", file=sys.stderr)
        return 1
    for mutation in mutations:
        if run(mutation, False) == 0:
            print("FAIL: explicit-W safety mutation survived", file=sys.stderr)
            return 1
    print("nbk failed optimization and explicit W checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
