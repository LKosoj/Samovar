#!/usr/bin/env python3
"""Регресс-проверка T10 code review: пока поднят барьер смены режима
(mode_switch_barrier_active), приводами распоряжается ТОЛЬКО процедура
переключения (stop_local_mode_actuators(), mode_switch.h).

Контекст: mode_dispatch_alarm() (mode_registry.h) сознательно НЕ проверяет
барьер - аварийный надзор обязан идти всегда, даже во время смены режима
(до 30 секунд). Но per-mode alarm-функции (check_alarm_bk, check_alarm,
check_alarm_distiller, check_alarm_nbk) не только НАДЗИРАЮТ, но и УПРАВЛЯЮТ
клапаном охлаждения (valve_buzzer.h::open_valve) и насосом охлаждения
(pumppwm.h::set_pump_pwm) через mode_should_open_cooling(). Они живут в
задаче SysTicker, а смена режима (stop_local_mode_actuators) - в loop():
без гейта оба кода борются за RELE_CHANNEL3/насос наперегонки, а
mode_actuators_idle() (требует !valve_status и, под USE_WATER_PUMP,
!pump_started && water_pump_speed == 0) не сходится - переключение режима
срывается в принудительное завершение по 30-секундному дедлайну.

Фикс: гейт добавлен ТОЛЬКО на включение (открытие клапана / скорость насоса
> 0) - закрытие/выключение должно проходить всегда, иначе стремление системы
к безопасному состоянию (закрыто/выключено) само оказалось бы заблокировано.

Тест вытаскивает РЕАЛЬНЫЕ тела open_valve() (valve_buzzer.h) и set_pump_pwm()
(pumppwm.h) через extract_function_body и компилирует их g++-харнессами -
без переписывания логики. Проверяется поведение (возврат, valve_status/
water_pump_speed, факт записи в GPIO/ШИМ), а не текст.

Мутации (тест обязан падать на ASSERT, не на ошибке компиляции):
  - гейт убран целиком -> включение во время барьера проходит;
  - гейт расширен на закрытие/выключение -> закрытие/выключение во время
    барьера блокируется (нарушает "движение к остановке проходит всегда").
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

OPEN_VALVE_SIGNATURE = "ActuatorCommandResult open_valve(bool Val, bool msg = true)"
SET_PUMP_PWM_SIGNATURE = "ActuatorCommandResult set_pump_pwm(float duty)"

OPEN_VALVE_GATE_LINE = "if (mode_switch_barrier_active) return ACTUATOR_COMMAND_FAILED;\n    "
SET_PUMP_PWM_GATE_LINE = "if (duty > 0 && mode_switch_barrier_active) return ACTUATOR_COMMAND_FAILED;\n\n  "

OPEN_VALVE_HARNESS = r'''
#include <iostream>

#define RELE_CHANNEL3 3

struct SetupEEPROM { bool rele3; };
static SetupEEPROM SamSetup;

static bool valve_status = false;
static bool mode_switch_barrier_active = false;

enum { WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

static int sendMsgCalls = 0;
void SendMsg(const char*, int) { sendMsgCalls++; }

static int digitalWriteCalls = 0;
static int lastDigitalWriteValue = -1;
void digitalWrite(int, int value) {
  digitalWriteCalls++;
  lastDigitalWriteValue = value;
}

ActuatorCommandResult open_valve(bool Val, bool msg = true) {
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
  SamSetup.rele3 = true;
  valve_status = false;
  mode_switch_barrier_active = false;
  sendMsgCalls = 0;
  digitalWriteCalls = 0;
  lastDigitalWriteValue = -1;
}

int main() {
  // Барьер снят: открытие/закрытие работают как обычно (регресс на штатный путь).
  reset_fixture();
  check(open_valve(true, false) == ACTUATOR_COMMAND_APPLIED,
        "барьер снят: открытие должно подтверждаться как APPLIED");
  check(valve_status == true, "барьер снят: клапан должен открыться");
  check(digitalWriteCalls == 1, "барьер снят: открытие должно писать GPIO");

  reset_fixture();
  valve_status = true;
  check(open_valve(false, false) == ACTUATOR_COMMAND_APPLIED,
        "барьер снят: закрытие должно подтверждаться как APPLIED");
  check(valve_status == false, "барьер снят: клапан должен закрыться");

  // Барьер поднят: ОТКРЫТИЕ обязано блокироваться и не трогать состояние/GPIO/сообщения.
  reset_fixture();
  mode_switch_barrier_active = true;
  check(open_valve(true, false) == ACTUATOR_COMMAND_FAILED,
        "барьер поднят: открытие обязано вернуть ACTUATOR_COMMAND_FAILED");
  check(valve_status == false,
        "барьер поднят: открытие не должно менять valve_status");
  check(digitalWriteCalls == 0,
        "барьер поднят: открытие не должно писать GPIO");
  check(sendMsgCalls == 0,
        "барьер поднят: заблокированное открытие не должно слать сообщение пользователю");

  // Барьер поднят: ЗАКРЫТИЕ обязано проходить всегда - иначе stop_local_mode_actuators()
  // (mode_switch.h) не смог бы привести приводы к безопасному состоянию.
  reset_fixture();
  mode_switch_barrier_active = true;
  valve_status = true;
  check(open_valve(false, false) == ACTUATOR_COMMAND_APPLIED,
        "барьер поднят: закрытие обязано пройти (ACTUATOR_COMMAND_APPLIED)");
  check(valve_status == false, "барьер поднят: закрытие обязано снять valve_status");
  check(digitalWriteCalls == 1, "барьер поднят: закрытие обязано записать GPIO");

  if (failures != 0) return 1;
  std::cout << "open_valve mode-switch-barrier gate checks passed\n";
  return 0;
}
'''

SET_PUMP_PWM_HARNESS = r'''
#include <iostream>
#include <cstdint>

enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

#define PWM_LOW_VALUE 10
#define PWM_START_VALUE 40

#ifndef constrain
#define constrain(amt, low, high) ((amt) < (low) ? (low) : ((amt) > (high) ? (high) : (amt)))
#endif

static bool pump_started = false;
static int bk_pwm = 0;
static int8_t wp_count = 0;
static uint16_t water_pump_speed = 0;
static bool mode_switch_barrier_active = false;

struct FakePwm {
  int lastWrite = -1;
  void write(int value) { lastWrite = value; }
};
static FakePwm pump_pwm;

static ActuatorCommandResult set_pump_pwm(float duty) {
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
  pump_started = false;
  bk_pwm = 0;
  wp_count = 0;
  water_pump_speed = 0;
  pump_pwm.lastWrite = -1;
  mode_switch_barrier_active = false;
}

int main() {
  // Барьер снят: включение/выключение работают как обычно (регресс на штатный путь).
  reset_fixture();
  check(set_pump_pwm(700) == ACTUATOR_COMMAND_APPLIED,
        "барьер снят: включение должно подтверждаться как APPLIED");
  check(pump_started == true, "барьер снят: насос должен запуститься");

  reset_fixture();
  pump_started = true;
  water_pump_speed = 700;
  check(set_pump_pwm(0) == ACTUATOR_COMMAND_APPLIED,
        "барьер снят: выключение должно подтверждаться как APPLIED");
  check(water_pump_speed == 0, "барьер снят: скорость насоса должна обнулиться");

  // Барьер поднят: ВКЛЮЧЕНИЕ (duty > 0) обязано блокироваться и не трогать состояние/ШИМ.
  reset_fixture();
  mode_switch_barrier_active = true;
  check(set_pump_pwm(700) == ACTUATOR_COMMAND_FAILED,
        "барьер поднят: включение обязано вернуть ACTUATOR_COMMAND_FAILED");
  check(pump_started == false,
        "барьер поднят: заблокированное включение не должно менять pump_started");
  check(water_pump_speed == 0,
        "барьер поднят: заблокированное включение не должно менять water_pump_speed");
  check(pump_pwm.lastWrite == -1,
        "барьер поднят: заблокированное включение не должно писать в ШИМ");

  // Барьер поднят: ВЫКЛЮЧЕНИЕ (duty == 0) обязано проходить всегда - иначе
  // stop_local_mode_actuators() (mode_switch.h) не смог бы остановить насос, а
  // mode_actuators_idle() (!pump_started && water_pump_speed == 0) не сошлась бы.
  reset_fixture();
  mode_switch_barrier_active = true;
  pump_started = true;
  water_pump_speed = 700;
  check(set_pump_pwm(0) == ACTUATOR_COMMAND_APPLIED,
        "барьер поднят: выключение обязано пройти (ACTUATOR_COMMAND_APPLIED)");
  check(pump_started == false, "барьер поднят: выключение обязано сбросить pump_started");
  check(water_pump_speed == 0, "барьер поднят: выключение обязано обнулить water_pump_speed");
  check(pump_pwm.lastWrite == 0, "барьер поднят: выключение обязано записать 0 в ШИМ");

  if (failures != 0) return 1;
  std::cout << "set_pump_pwm mode-switch-barrier gate checks passed\n";
  return 0;
}
'''


def compile_and_run(harness: str, prefix: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
        source = Path(temp_dir) / "harness.cpp"
        binary = Path(temp_dir) / "harness"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            return compiled.returncode, compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def run_variant(label: str, variant: str, harness_template: str, body: str, prefix: str, *, expect_pass: bool) -> int:
    code, output = compile_and_run(harness_template.replace("@BODY@", body), prefix)
    if expect_pass:
        sys.stdout.write(output)
        if code:
            print(f"FAIL: {label} {variant} harness failed unexpectedly", file=sys.stderr)
            return 1
        return 0
    if code == 0:
        print(f"FAIL: {label} mutation '{variant}' пережила тест (харнесс прошёл, а обязан был упасть)", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print(f"{label}: мутация '{variant}' отклонена как ожидалось")
    return 0


def check_open_valve() -> int:
    source = (ROOT / "valve_buzzer.h").read_text(encoding="utf-8")
    try:
        body = extract_function_body(source, OPEN_VALVE_SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if OPEN_VALVE_GATE_LINE not in body:
        print("FAIL: open_valve - не нашли ожидаемую строку гейта в исходнике", file=sys.stderr)
        return 1

    rc = run_variant("open_valve", "baseline", OPEN_VALVE_HARNESS, body,
                      "samovar-mode-switch-gate-valve-", expect_pass=True)
    if rc:
        return rc

    # Мутация 1: гейт убран целиком - открытие во время барьера обязано было бы
    # блокироваться, но перестаёт. Тест обязан упасть на ASSERT.
    mutant_no_gate = body.replace(OPEN_VALVE_GATE_LINE, "", 1)
    rc = run_variant("open_valve", "гейт убран", OPEN_VALVE_HARNESS, mutant_no_gate,
                      "samovar-mode-switch-gate-valve-nogate-", expect_pass=False)
    if rc:
        return rc

    # Мутация 2: гейт распространён на ЗАКРЫТИЕ - убираем его из ветки if (Val) и
    # ставим БЕЗУСЛОВНО перед всей веткой открытия/закрытия, так что барьер блокирует
    # и путь к безопасному состоянию. Нарушает "закрытие проходит всегда" - обязан
    # упасть на ASSERT (а не просто провалить компиляцию).
    body_without_gate = body.replace(OPEN_VALVE_GATE_LINE, "", 1)
    mutant_broad_gate = "\n  if (mode_switch_barrier_active) return ACTUATOR_COMMAND_FAILED;" + body_without_gate
    rc = run_variant("open_valve", "гейт распространён на закрытие", OPEN_VALVE_HARNESS, mutant_broad_gate,
                      "samovar-mode-switch-gate-valve-broadgate-", expect_pass=False)
    if rc:
        return rc
    return 0


def check_set_pump_pwm() -> int:
    source = (ROOT / "pumppwm.h").read_text(encoding="utf-8", errors="ignore")
    try:
        body = extract_function_body(source, SET_PUMP_PWM_SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if SET_PUMP_PWM_GATE_LINE not in body:
        print("FAIL: set_pump_pwm - не нашли ожидаемую строку гейта в исходнике", file=sys.stderr)
        return 1

    rc = run_variant("set_pump_pwm", "baseline", SET_PUMP_PWM_HARNESS, body,
                      "samovar-mode-switch-gate-pump-", expect_pass=True)
    if rc:
        return rc

    # Мутация 1: гейт убран целиком - включение во время барьера обязано было бы
    # блокироваться, но перестаёт. Тест обязан упасть на ASSERT.
    mutant_no_gate = body.replace(SET_PUMP_PWM_GATE_LINE, "", 1)
    rc = run_variant("set_pump_pwm", "гейт убран", SET_PUMP_PWM_HARNESS, mutant_no_gate,
                      "samovar-mode-switch-gate-pump-nogate-", expect_pass=False)
    if rc:
        return rc

    # Мутация 2: гейт распространён на ВЫКЛЮЧЕНИЕ - убираем условие "duty > 0 && ",
    # так что барьер блокирует и duty == 0. Нарушает "выключение проходит всегда" -
    # обязан упасть на ASSERT.
    broadened_condition = "if (mode_switch_barrier_active) return ACTUATOR_COMMAND_FAILED;\n\n  "
    if broadened_condition == SET_PUMP_PWM_GATE_LINE:
        print("FAIL: set_pump_pwm - мутация 'гейт на выключение' не изменяет строку", file=sys.stderr)
        return 1
    mutant_broad_gate = body.replace(SET_PUMP_PWM_GATE_LINE, broadened_condition, 1)
    rc = run_variant("set_pump_pwm", "гейт распространён на выключение", SET_PUMP_PWM_HARNESS, mutant_broad_gate,
                      "samovar-mode-switch-gate-pump-broadgate-", expect_pass=False)
    if rc:
        return rc
    return 0


def main() -> int:
    rc = check_open_valve()
    if rc:
        return rc

    rc = check_set_pump_pwm()
    if rc:
        return rc

    print("Mode-switch actuator gate (T10 review) checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
