#!/usr/bin/env python3
"""Поведенческая проверка power_regulator.h::set_power_mode(): «сон» во время включения.

set_power(true) шлёт регулятору разгон не сразу, а через
SAMOVAR_USE_POWER_START_TIME. Первая строка программы ('C'/'W' пива; 'W', 'S',
перемешивание, дозирование сыра) гасит нагрев через setHeaterPosition(false) ->
set_power_mode(POWER_SLEEP_MODE) один раз, в первую секунду - раньше разгона.
Прямая заявка в этот момент перебивалась отложенным разгоном, и куб грелся на
полной мощности при шаге «Охлаждение». Теперь «сон» паркуется в
powerTransition.pendingPowerValue (тем же путём, что и set_current_power()), и
tick_power_transition() применяет его после разгона.

Тест вытаскивает РЕАЛЬНЫЕ тела set_power_mode() и regulator_mode_from_string()
из power_regulator.h через extract_function_body и подставляет их в host-харнесс
с замоканными внешними зависимостями - логика функций не переписывается.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

MODE_SIGNATURE = "inline void set_power_mode(String Mode) {"
PARSE_SIGNATURE = (
    "inline bool regulator_mode_from_string(const String& modeText, SafetyRegulatorMode& mode) {"
)

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

typedef std::string String;
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum SafetyRegulatorMode {
  SAFETY_REGULATOR_MODE_WORK,
  SAFETY_REGULATOR_MODE_SPEED,
  SAFETY_REGULATOR_MODE_SLEEP,
};

#define POWER_WORK_MODE "0"
#define POWER_SPEED_MODE "1"
#define POWER_SLEEP_MODE "2"

#define portENTER_CRITICAL(x) ((void)(x))
#define portEXIT_CRITICAL(x) ((void)(x))
static int emergencyStopMux = 0;

struct PowerTransitionState {
  float pendingPowerValue;
  bool pendingPowerValueSet;
  uint64_t pendingPowerGeneration;
  uint64_t pendingPowerRegulatorGeneration;
};
static PowerTransitionState powerTransition = {-1.0f, false, 0, 77};

struct SafetyRegulatorRequestState { uint64_t lastGeneration; };
static SafetyRegulatorRequestState regulatorRequestState = {10};
uint64_t safety_regulator_next_generation(SafetyRegulatorRequestState& state) {
  return ++state.lastGeneration;
}

// --- Управляемые тестом заглушки ---
static bool test_startPending = false;
bool power_transition_start_pending_locked() { return test_startPending; }

struct DirectRequest { SafetyRegulatorMode mode; bool hasVoltage; float voltage; bool verify; };
static std::vector<DirectRequest> directRequests;
uint64_t request_regulator_state_locked(SafetyRegulatorMode mode, bool hasVoltage, float voltage, bool verify) {
  directRequests.push_back({mode, hasVoltage, voltage, verify});
  return 1;
}
static int workerNotifications = 0;
void notify_power_worker() { workerNotifications++; }
static int sentMessages = 0;
void SendMsg(const String&, int) { sentMessages++; }

bool PowerOn = false;
float target_power_volt = 0;

@PARSE@

@MODE@

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  powerTransition = {-1.0f, false, 0, 77};
  regulatorRequestState = {10};
  test_startPending = false;
  directRequests.clear();
  workerNotifications = 0;
  sentMessages = 0;
  PowerOn = true;
  target_power_volt = 180.0f;
}

int main() {
  // --- Главный кейс: «сон» в окне включения обязан быть отложен, а не послан
  // прямой заявкой (её перебил бы отложенный разгон). ---
  reset_fixture();
  test_startPending = true;
  set_power_mode(POWER_SLEEP_MODE);
  check(directRequests.empty(), "РЕГРЕСС: «сон» во время включения ушёл прямой заявкой - разгон его перебьёт");
  check(powerTransition.pendingPowerValueSet, "«сон» во время включения обязан быть запаркован");
  check(powerTransition.pendingPowerValue == 0.0f, "запаркованная уставка обязана быть нулевой (ниже порога WORK = сон)");
  check(powerTransition.pendingPowerGeneration == 11, "парковка обязана взять новое поколение заявки");
  check(powerTransition.pendingPowerRegulatorGeneration == 0, "парковка обязана сбросить поколение прошлой отложенной заявки");
  check(target_power_volt == 0.0f, "целевая мощность обязана обнулиться");
  check(sentMessages == 0, "парковка не должна слать сообщений");

  // --- Контраст: включение завершено - «сон» идёт обычной прямой заявкой. ---
  reset_fixture();
  set_power_mode(POWER_SLEEP_MODE);
  check(directRequests.size() == 1, "вне окна включения «сон» обязан идти прямой заявкой");
  check(!directRequests.empty() && directRequests[0].mode == SAFETY_REGULATOR_MODE_SLEEP, "прямая заявка обязана быть сном");
  check(!powerTransition.pendingPowerValueSet, "вне окна включения парковать нечего");
  check(workerNotifications == 1, "прямая заявка обязана разбудить задачу регулятора");

  // --- Парковка касается только сна: разгон в окне включения идёт как раньше. ---
  reset_fixture();
  test_startPending = true;
  set_power_mode(POWER_SPEED_MODE);
  check(directRequests.size() == 1, "разгон в окне включения обязан идти прямой заявкой");
  check(!powerTransition.pendingPowerValueSet, "разгон не должен парковаться");

  // --- Нагрев выключен: парковать нечего, решает барьер в прямой заявке. ---
  reset_fixture();
  test_startPending = true;
  PowerOn = false;
  set_power_mode(POWER_SLEEP_MODE);
  check(directRequests.size() == 1, "при PowerOn=false «сон» обязан идти прямой заявкой");
  check(!powerTransition.pendingPowerValueSet, "при PowerOn=false парковки быть не должно");

  if (failures != 0) return 1;
  std::cout << "set_power_mode sleep-during-start parking checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "power_regulator.h").read_text(encoding="utf-8")
    parse_body = extract_function_body(source, PARSE_SIGNATURE)
    mode_body = extract_function_body(source, MODE_SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@PARSE@",
        "bool regulator_mode_from_string(const String& modeText, SafetyRegulatorMode& mode) "
        f"{{{parse_body}}}",
    ).replace("@MODE@", f"void set_power_mode(String Mode) {{{mode_body}}}")


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-power-mode-sleep-start-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "test.cpp"
        binary = temp / "test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
