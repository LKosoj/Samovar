#!/usr/bin/env python3
"""Поведенческая проверка нижнего клампа в power_regulator.h::set_current_power.

Тест берёт РЕАЛЬНОЕ тело функции set_current_power из power_regulator.h (через
extract_function_body — без переписывания логики) и подставляет его в
минимальный host-харнесс, замокав только downstream-зависимости
(request_regulator_state_locked, notify_power_worker,
power_transition_start_pending_locked). Так проверяется поведение: какое
значение реально доезжает до регулятора, а не наличие конкретной строки в
исходнике.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

using TickType_t = int;
using portMUX_TYPE = int;
#define portENTER_CRITICAL(mux) do { (void)(mux); } while (0)
#define portEXIT_CRITICAL(mux) do { (void)(mux); } while (0)

#include "safety_transition.h"

portMUX_TYPE emergencyStopMux = 0;
volatile bool PowerOn = true;
volatile bool mode_switch_barrier_active = false;
volatile float target_power_volt = 0.0f;

static SafetyHeaterBarrierState heaterSafetyState = {false, false, false, 0};
static SafetyRegulatorRequestState regulatorRequestState = {};

struct PowerTransitionState {
  SafetyTransition transition;
  bool enqueueResetCommand;
  bool pendingPowerValueSet;
  float pendingPowerValue;
  uint64_t pendingPowerGeneration;
  uint64_t pendingPowerRegulatorGeneration;
  uint64_t regulatorGeneration;
};
static PowerTransitionState powerTransition = {
  {SAFETY_TRANSITION_IDLE, 0}, false, false, 0, 0, 0, 0,
};

inline bool power_transition_start_pending_locked() {
  return powerTransition.transition.phase == POWER_TRANSITION_ON_SEM_WAIT ||
         powerTransition.transition.phase == POWER_TRANSITION_ON_REGULATOR_WAIT;
}

// Не-SEM_AVR (KVIC/RMVK) сборка: порог 40В, верхний предел уставки 230В.
static constexpr float POWER_WORK_MODE_THRESHOLD = 40.0f;

static int requestCalls = 0;
static SafetyRegulatorMode lastMode = SAFETY_REGULATOR_MODE_WORK;
static bool lastHasVoltage = true;
static float lastVoltage = -999.0f;
static bool lastForce = true;

uint64_t request_regulator_state_locked(
    SafetyRegulatorMode mode, bool hasVoltage, float voltage, bool force) {
  requestCalls++;
  lastMode = mode;
  lastHasVoltage = hasVoltage;
  lastVoltage = voltage;
  lastForce = force;
  return 1;
}

static int notifyCalls = 0;
// Заглушки НЕ static: единственный вызов каждой лежит во вклеенном теле
// set_current_power ниже, и со static мутация, убравшая вызов, роняла бы
// компилятор по unused-function вместо содержательного assert-а. Держится
// это на проверках requestCalls/notifyCalls: без них снятие static меняет
// ложный улов на молчаливую слепую зону, что хуже.
void notify_power_worker() { notifyCalls++; }
ActuatorCommandResult current_power_command_status(uint64_t generation) {
@STATUS_BODY@
}

inline ActuatorCommandResult set_current_power(
    float Volt,
    uint64_t* generation = nullptr) {
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
  PowerOn = true;
  mode_switch_barrier_active = false;
  heaterSafetyState = {false, false, false, 0};
  target_power_volt = 123.0f;  // не ноль — чтобы увидеть, что реально обнулили
  powerTransition = {{SAFETY_TRANSITION_IDLE, 0}, false, false, 0, 0, 0, 0};
  requestCalls = 0;
  lastMode = SAFETY_REGULATOR_MODE_WORK;  // sentinel, не должен остаться
  lastHasVoltage = true;                  // sentinel, не должен остаться
  lastVoltage = -999.0f;                  // sentinel: отрицательное значение
  lastForce = true;                       // sentinel
  notifyCalls = 0;
}

static void test_negative_clamped_to_zero_sleep() {
  reset_fixture();
  set_current_power(-50.0f);
  check(requestCalls == 1, "отрицательная уставка не дошла до регулятора ровно один раз");
  check(lastMode == SAFETY_REGULATOR_MODE_SLEEP, "отрицательная уставка не перевела регулятор в SLEEP");
  check(!lastHasVoltage, "отрицательная уставка выставила hasVoltage вместо SLEEP");
  check(lastVoltage == 0.0f, "отрицательная уставка дошла до регулятора не нулём");
  check(!(lastVoltage < 0.0f), "отрицательное значение утекло в команду регулятора");
  check(target_power_volt == 0.0f, "отрицательная уставка не обнулила target_power_volt");
  check(notifyCalls == 1, "регулятор не разбужен после запроса");
}

static void test_nan_clamped_to_zero_sleep() {
  reset_fixture();
  set_current_power(std::nanf(""));
  check(requestCalls == 1, "NaN-уставка не дошла до регулятора ровно один раз");
  check(lastMode == SAFETY_REGULATOR_MODE_SLEEP, "NaN-уставка не перевела регулятор в SLEEP");
  check(!lastHasVoltage, "NaN-уставка выставила hasVoltage вместо SLEEP");
  check(lastVoltage == 0.0f, "NaN-уставка дошла до регулятора не нулём");
  check(!std::isnan(lastVoltage), "NaN утёк в команду регулятора");
  check(target_power_volt == 0.0f, "NaN-уставка не обнулила target_power_volt");
}

static void test_zero_boundary_sleep() {
  reset_fixture();
  set_current_power(0.0f);
  check(requestCalls == 1, "нулевая уставка не дошла до регулятора");
  check(lastMode == SAFETY_REGULATOR_MODE_SLEEP, "нулевая уставка не резолвится в SLEEP");
  check(lastVoltage == 0.0f, "нулевая уставка была искажена по пути к регулятору");
  check(target_power_volt == 0.0f, "нулевая уставка не обнулила target_power_volt");
}

static void test_upper_clamp_still_applies() {
  reset_fixture();
  set_current_power(500.0f);  // выше потолка 230В (не-SEM_AVR ветка)
  check(requestCalls == 1, "уставка выше потолка не дошла до регулятора");
  check(lastMode == SAFETY_REGULATOR_MODE_WORK, "уставка выше потолка не резолвится в WORK");
  check(lastHasVoltage, "уставка выше потолка потеряла hasVoltage в WORK-режиме");
  check(lastVoltage == 230.0f, "регресс верхнего клампа: значение выше 230В дошло до регулятора некламплено");
  check(target_power_volt == 123.0f, "WORK-режим не должен трогать target_power_volt здесь");
}

// Гард аварийной отсечки: КАЖДОЕ из трёх условий обязано в одиночку запретить
// подачу. Проверяются они по отдельности, а не одним "всё сразу": при одном
// комбинированном кейсе выпадение любого терма из условия осталось бы
// незамеченным - ровно та дыра, что чинилась в R11 для барьера смены режима.
struct HeaterBlockCase {
  const char* name;
  bool powerOn;
  bool emergencyLatched;
  bool barrierActive;
};

static void test_each_guard_condition_blocks_power_alone() {
  const HeaterBlockCase cases[] = {
      {"PowerOn=false", false, false, false},
      {"аварийная защёлка взведена", true, true, false},
      {"барьер смены режима поднят", true, false, true},
  };
  for (const HeaterBlockCase& c : cases) {
    reset_fixture();
    PowerOn = c.powerOn;
    heaterSafetyState.emergencyLatched = c.emergencyLatched;
    mode_switch_barrier_active = c.barrierActive;
    set_current_power(200.0f);  // заведомо рабочая уставка, выше порога 40В
    const std::string p = std::string("нагрев не заблокирован (") + c.name + "): ";
    check(requestCalls == 0, (p + "уставка ушла в регулятор").c_str());
    check(notifyCalls == 0, (p + "разбужен воркер регулятора").c_str());
    // target_power_volt обязан остаться нетронутым: гард стоит ДО любой записи,
    // и заявка на мощность не должна оседать в состоянии на будущее.
    check(target_power_volt == 123.0f, (p + "уставка осела в target_power_volt").c_str());
  }
}

// Переход питания в процессе: уставка обязана осесть в pendingPowerValue и
// НЕ уйти в регулятор сразу - иначе мощность подаётся мимо машины переходов,
// пока та ещё поднимает питание.
static void test_pending_transition_defers_setpoint() {
  reset_fixture();
  powerTransition.transition.phase = POWER_TRANSITION_ON_REGULATOR_WAIT;
  uint64_t generation = 0;
  check(set_current_power(200.0f, &generation) == ACTUATOR_COMMAND_PENDING,
        "отложенная уставка должна вернуть PENDING");
  check(requestCalls == 0, "во время перехода питания уставка ушла в регулятор напрямую");
  check(notifyCalls == 0, "во время перехода питания разбужен воркер регулятора");
  check(powerTransition.pendingPowerValueSet &&
            powerTransition.pendingPowerValue == 200.0f,
        "уставка не отложена в pendingPowerValue на время перехода питания");
  check(target_power_volt == 200.0f,
        "target_power_volt не принял отложенную уставку");
  check(generation != 0 && generation == powerTransition.pendingPowerGeneration,
        "PENDING обязан вернуть зарезервированное поколение команды");
  check(current_power_command_status(generation) == ACTUATOR_COMMAND_PENDING,
        "статус зарезервированного поколения до старта регулятора обязан быть PENDING");
  powerTransition.pendingPowerValueSet = false;
  powerTransition.pendingPowerRegulatorGeneration = 2;
  regulatorRequestState.desiredGeneration = 2;
  regulatorRequestState.pending = true;
  check(current_power_command_status(generation) == ACTUATOR_COMMAND_PENDING,
        "статус должен оставаться PENDING после передачи поколения регулятору");
  regulatorRequestState.pending = false;
  regulatorRequestState.completedGeneration = 2;
  check(current_power_command_status(generation) == ACTUATOR_COMMAND_APPLIED,
        "статус должен наблюдать APPLIED фактической команды регулятора");
}

int main() {
  test_negative_clamped_to_zero_sleep();
  test_nan_clamped_to_zero_sleep();
  test_zero_boundary_sleep();
  test_upper_clamp_still_applies();
  test_each_guard_condition_blocks_power_alone();
  test_pending_transition_defers_setpoint();
  if (failures != 0) return 1;
  std::cout << "set_current_power negative/NaN clamp behaviour checks passed\n";
  return 0;
}
'''


def build_harness(body: str | None = None, status_body: str | None = None) -> str:
    if body is None:
        source = (ROOT / "power_regulator.h").read_text(encoding="utf-8")
        body = extract_function_body(
            source,
            "inline ActuatorCommandResult set_current_power(float Volt, uint64_t* generation)",
        )
    if status_body is None:
        status_body = extract_function_body(
            (ROOT / "power_regulator.h").read_text(encoding="utf-8"),
            "inline ActuatorCommandResult current_power_command_status(uint64_t generation)",
        )
    return HARNESS_TEMPLATE.replace("@BODY@", body).replace("@STATUS_BODY@", status_body)


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-power-clamp-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "power_regulator_negative_clamp_test.cpp"
        binary = temp / "power_regulator_negative_clamp_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(ROOT),
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            if emit:
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness, True) != 0:
        return 1
    body = extract_function_body(
        (ROOT / "power_regulator.h").read_text(encoding="utf-8"),
        "inline ActuatorCommandResult set_current_power(float Volt, uint64_t* generation)",
    )
    mutation = body.replace(
        "powerTransition.pendingPowerGeneration =\n        safety_regulator_next_generation(regulatorRequestState);",
        "powerTransition.pendingPowerGeneration = 0;",
        1,
    )
    if mutation == body:
        print("FAIL: PENDING generation mutation anchor missing", file=sys.stderr)
        return 1
    if compile_and_run(build_harness(mutation), False) == 0:
        print("FAIL: PENDING generation mutation survived", file=sys.stderr)
        return 1
    status_body = extract_function_body(
        (ROOT / "power_regulator.h").read_text(encoding="utf-8"),
        "inline ActuatorCommandResult current_power_command_status(uint64_t generation)",
    )
    status_mutation = status_body.replace(
        "if (generation == powerTransition.pendingPowerGeneration)",
        "if (false)",
        1,
    )
    if status_mutation == status_body:
        print("FAIL: PENDING status mutation anchor missing", file=sys.stderr)
        return 1
    if compile_and_run(build_harness(body, status_mutation), False) == 0:
        print("FAIL: PENDING status mutation survived", file=sys.stderr)
        return 1
    print("set_current_power negative/NaN clamp and PENDING generation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
