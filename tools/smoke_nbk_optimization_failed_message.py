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
// [Ремонт-2026-09-02 П1] та же константа, что Samovar_ini.h/nbk.h.
#define NBK_MULT_PAUSE_OVERFLOW 2
template <typename T> T max(T a, T b) { return a > b ? a : b; } // Arduino-подобный шаблон
class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
  String(float value, int) : value_(std::to_string(value)) {}
  void reserve(size_t) {}
  String& operator+=(const char* text) { value_ += (text ? text : ""); return *this; }
  String& operator+=(const String& other) { value_ += other.value_; return *this; }
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
// [Ремонт-2026-09-02 П1] новые зависимости автовхода optimumEntry.
static float nbk_Mo = 0;
static float nbk_Po = 0;
static float feedRateStub = 0;
// [T1] причина автовхода по давлению (текст сообщения здесь не собирается - нет SAMOVAR_USE_POWER).
static bool nbk_opt_entry_by_pressure = false;
static bool scheduledKeepsOptimum = false;
static uint32_t scheduledDelay = 0;
static NbkActuatorDeadlineTarget scheduledDeadlineTarget = NBK_ACTUATOR_WORK_DEADLINE;
float nbk_actual_feed_rate() { return feedRateStub; }
float power_work_mode_threshold() { return 10.0f; }

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
    NbkActuatorDeadlineTarget deadlineTarget,
    uint32_t delayMs,
    uint16_t,
    bool commit,
    uint8_t programNum,
    bool commitKeepsOptimum = false) {
  scheduleCalls++;
  scheduledM = power;
  scheduledP = speed;
  scheduledCommit = commit;
  scheduledProgram = programNum;
  scheduledKeepsOptimum = commitKeepsOptimum;
  scheduledDelay = delayMs;
  scheduledDeadlineTarget = deadlineTarget;
  return true;
}
void SendMsg(const String&, MESSAGE_TYPE) {}

static void run_w(uint8_t num, bool workConfirmed, bool optimumEntry = false) {
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
  nbk_Mo = 0;
  nbk_Po = 0;
  feedRateStub = 0;
  scheduledKeepsOptimum = false;
  scheduledDelay = 0;
  scheduledDeadlineTarget = NBK_ACTUATOR_WORK_DEADLINE;
}
int main() {
  reset_fixture();
  run_w(1, false);
  check(safeWaitCalls == 1 && scheduleCalls == 0,
        "автоматический O->W обязан перейти в safe-wait без команды приводам");

  // [Ремонт-2026-09-02 П1] optimumEntry: автовход в Работу с найденным оптимумом.
  reset_fixture();
  nbk_Mo = 1000;
  nbk_Po = 6;
  feedRateStub = 9;
  run_w(1, false, true);
  check(safeWaitCalls == 0 && scheduleCalls == 1,
        "optimumEntry с Мо/По>0 должен принять одну команду без safe-wait");
  check(scheduledM == 500 && scheduledP == 3 && scheduledCommit &&
            scheduledProgram == 1 && scheduledKeepsOptimum,
        "optimumEntry обязан считать М=max(Мо/2, порог), П=реальная подача/3, commitKeepsOptimum=true");
  check(scheduledDeadlineTarget == NBK_ACTUATOR_WORK_DEADLINE &&
            scheduledDelay == uint32_t(NBK_MULT_PAUSE_OVERFLOW) * nbk_column_inertia * 1000,
        "optimumEntry обязан планировать WORK_DEADLINE с паузой MULT*Ин");

  // Другое Мо доказывает, что М реально берёт max(), а не всегда Мо/2.
  reset_fixture();
  nbk_Mo = 20;
  nbk_Po = 6;
  feedRateStub = 9;
  run_w(1, false, true);
  check(scheduleCalls == 1 && scheduledM == 20,
        "optimumEntry обязан поднять М до порога, если Мо/2 ниже него");

  reset_fixture();
  run_w(1, false, true);
  check(safeWaitCalls == 1 && scheduleCalls == 0,
        "optimumEntry без сохранённого оптимума (Мо=0) обязан уйти в safe-wait без команды");

  // [Ремонт-2026-09-02 П5.3] явный W с нулями в строке берёт сохранённые nbk_Mo/nbk_Po
  // напрямую, без повторного toPower().
  reset_fixture();
  program[1] = {'W', 0, 0};
  nbk_Mo = 800;
  nbk_Po = 4;
  run_w(1, true);
  check(safeWaitCalls == 0 && scheduleCalls == 1,
        "явный W с нулями в строке, но сохранённым Мо/По, обязан принять команду");
  check(scheduledM == 800 && scheduledP == 4 && !scheduledKeepsOptimum,
        "явный W с нулями обязан взять именно nbk_Mo/nbk_Po без повторного toPower()");

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
            "if ((program[num].Power <= 0 || program[num].Speed <= 0) &&\n"
            "        !(nbk_Mo > 0 && nbk_Po > 0)) {",
            "if (false) {",
            1,
        ),
        source.replace(
            "            true,\n            num))",
            "            false,\n            num))",
            1,
        ),
        # [Ремонт-2026-09-02 П1] снимаем проверку сохранённого оптимума перед
        # автовходом optimumEntry — без неё Мо=0 не должен уходить в safe-wait.
        source.replace(
            "if (nbk_safe_waiting || !PowerOn || !(nbk_Mo > 0) || !(nbk_Po > 0)) {",
            "if (nbk_safe_waiting || !PowerOn) {",
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
