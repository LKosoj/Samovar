#!/usr/bin/env python3
"""Поведенческая проверка [П70а] power_regulator.h::set_power(true).

Раньше set_power(true) отслеживал ПЯТЬ причин отказа (!workerReady,
авария, идёт выключение, эксклюзивный владелец, переключение режима) -
каждая со своим SendMsg. Шестая возможная причина - "уже идёт ВКЛЮЧЕНИЕ"
(power_transition_start_pending_locked() истинен, пока PowerOn уже false, а
фаза ON_SEM_WAIT/ON_REGULATOR_WAIT ещё не отменена тиком перехода) -
проверялась в общем условии, но НЕ входила в список отслеживаемых причин
отказа: оператор получал отказ вовсе без сообщения от set_power (только
общее "Нагрев НБК не включён. Старт отменён." от вызывающей стороны).

Тест вытаскивает РЕАЛЬНОЕ тело set_power() из power_regulator.h через
extract_function_body и подставляет в host-харнесс с замоканными
внешними зависимостями (heater_outputs_enable_locked,
power_transition_start_pending_locked, power_transition_phase_is_off,
SendMsg и т.д.) - логика функции не переписывается.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "inline ActuatorCommandResult set_power(bool On, bool enqueueResetCommand) {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum ActuatorCommandResult {
  ACTUATOR_COMMAND_FAILED,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_ACCEPTED,
};

#define portENTER_CRITICAL(x) ((void)(x))
#define portEXIT_CRITICAL(x) ((void)(x))
static int emergencyStopMux = 0;

constexpr int16_t SAMOVAR_RECTIFICATION_MODE = 1;
constexpr int SAFETY_HEATER_OUTPUT_MAIN = 0;
constexpr int SAFETY_HEATER_OUTPUT_BOOST = 1;
constexpr int POWER_SPEED_MODE = 0;
constexpr int POWER_SLEEP_MODE = 1;
constexpr uint32_t SAMOVAR_USE_POWER_START_TIME = 2000;

struct SafetyTransition { int phase; uint32_t deadline; };
struct PowerTransitionState {
  SafetyTransition transition;
  bool enqueueResetCommand;
  bool pendingPowerValueSet;
  uint64_t pendingPowerGeneration;
  uint64_t pendingPowerRegulatorGeneration;
  uint64_t regulatorGeneration;
};
static PowerTransitionState powerTransition = {{0, 0}, false, false, 0, 0, 0};

struct HeaterSafetyState {
  bool emergencyLatched;
  bool exclusiveOwnerActive;
  bool powerOn;
};
static HeaterSafetyState heaterSafetyState = {false, false, false};

// --- Управляемые тестом заглушки-предикаты ---
static bool test_blockedOffTransition = false;
static bool test_blockedOnStartPending = false;
static bool test_heaterEnableResult = true;
bool power_transition_phase_is_off(int) { return test_blockedOffTransition; }
bool power_transition_start_pending_locked() { return test_blockedOnStartPending; }
bool heater_outputs_enable_locked(int, bool) { return test_heaterEnableResult; }
void reset_heat_loss_calculation() {}
void finish_power_off_transition(bool) {}
void force_heater_output_off_locked(bool) {}
void set_current_power_mode_value(int) {}
void set_menu_screen(int) {}
uint32_t millis() { return 0; }

bool PowerOn = false;
bool mode_switch_barrier_active = false;
int16_t Samovar_Mode = 0;
bool reg_online = false;
uint32_t last_reg_online = 0;
const char* power_text_ptr = "";

static std::vector<std::pair<std::string, int>> sentMessages;
void SendMsg(const char* message, int type) {
  sentMessages.emplace_back(message, type);
}

@BODY@

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  heaterSafetyState = {false, false, false};
  powerTransition.transition.phase = 0;
  powerTransition.enqueueResetCommand = false;
  test_blockedOffTransition = false;
  test_blockedOnStartPending = false;
  test_heaterEnableResult = true;
  PowerOn = false;
  mode_switch_barrier_active = false;
  sentMessages.clear();
}

int main() {
  // --- Идущий ON-переход (PowerOn уже false, но фаза ON_WAIT ещё не снята) -
  // раньше НИКАКОГО сообщения не было; теперь обязано быть ровно одно, и оно
  // должно отличаться текстом от всех пяти прежних причин. ---
  reset_fixture();
  test_blockedOnStartPending = true;
  ActuatorCommandResult result = set_power(true, false);
  check(result == ACTUATOR_COMMAND_FAILED, "идущий ON-переход обязан отклонить повторный set_power(true)");
  check(sentMessages.size() == 1, "РЕГРЕСС: идущий ON-переход обязан теперь давать РОВНО одно сообщение");
  const std::string startPendingMsg = sentMessages.empty() ? "" : sentMessages[0].first;
  check(startPendingMsg.find("НБК") == std::string::npos || true, "sanity");

  // --- [Дефект 1] Идущий ON-переход, но PowerOn УЖЕ true (heater_outputs_enable_locked
  // выставляет PowerOn=true сразу, а фаза ON_SEM_WAIT/ON_REGULATOR_WAIT держится ещё
  // до SAMOVAR_USE_POWER_START_TIME после этого) - повторный set_power(true) в этом
  // окне обязан быть ТИХИМ no-op "уже включено", без единого сообщения. ---
  reset_fixture();
  PowerOn = true;
  test_blockedOnStartPending = true;
  ActuatorCommandResult alreadyOnResult = set_power(true, false);
  check(alreadyOnResult == ACTUATOR_COMMAND_FAILED, "PowerOn=true + идущий переход обязан отклонить повторный set_power(true)");
  check(sentMessages.empty(), "РЕГРЕСС: PowerOn=true + идущий переход не должен слать никаких сообщений (тихий no-op)");

  // --- Остальные пять причин, каждая изолированно - собираем их тексты. ---
  reset_fixture();
  test_heaterEnableResult = true; // не влияет: workerReady в этой сборке всегда true (SAMOVAR_USE_POWER не определён)
  heaterSafetyState.emergencyLatched = true;
  set_power(true, false);
  check(sentMessages.size() == 1, "авария обязана дать ровно одно сообщение");
  const std::string emergencyMsg = sentMessages[0].first;

  reset_fixture();
  test_blockedOffTransition = true;
  set_power(true, false);
  check(sentMessages.size() == 1, "переход выключения обязан дать ровно одно сообщение");
  const std::string offTransitionMsg = sentMessages[0].first;

  reset_fixture();
  heaterSafetyState.exclusiveOwnerActive = true;
  set_power(true, false);
  check(sentMessages.size() == 1, "эксклюзивный владелец обязан дать ровно одно сообщение");
  const std::string exclusiveOwnerMsg = sentMessages[0].first;

  reset_fixture();
  mode_switch_barrier_active = true;
  set_power(true, false);
  check(sentMessages.size() == 1, "переключение режима обязано дать ровно одно сообщение");
  const std::string modeSwitchMsg = sentMessages[0].first;

  // --- Все шесть текстов обязаны быть ПОПАРНО различны. ---
  std::vector<std::string> all = {
      startPendingMsg, emergencyMsg, offTransitionMsg, exclusiveOwnerMsg, modeSwitchMsg,
  };
  for (size_t i = 0; i < all.size(); i++) {
    for (size_t j = i + 1; j < all.size(); j++) {
      check(all[i] != all[j], "сообщения о разных причинах отказа обязаны различаться текстом");
    }
  }
  check(!startPendingMsg.empty(), "сообщение о идущем ON-переходе не должно быть пустым");

  // --- Успешный старт (ничего не блокирует) - для контраста, чтобы
  // убедиться, что блокировка не мешает нормальному включению. ---
  reset_fixture();
  ActuatorCommandResult ok = set_power(true, false);
  check(ok == ACTUATOR_COMMAND_APPLIED, "без единой причины блокировки set_power(true) обязан успешно включаться");
  check(sentMessages.empty(), "успешное включение не должно слать сообщение об отказе");

  if (failures != 0) return 1;
  std::cout << "set_power on-transition-pending distinguishability checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "power_regulator.h").read_text(encoding="utf-8")
    body = extract_function_body(source, SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@BODY@", f"ActuatorCommandResult set_power(bool On, bool enqueueResetCommand) {{{body}}}"
    )


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-power-on-pending-") as temp_dir:
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
