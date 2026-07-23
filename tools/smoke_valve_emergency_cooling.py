#!/usr/bin/env python3
"""Регресс-проверка: авария по перегреву не должна глушить охлаждение.

Инвариант проекта: heater_safety_latched() - гейт ИМЕННО нагревательных
каналов (RELE_CHANNEL1/RELE_CHANNEL4, см. tools/smoke_lua_relay_polarity.py).
Клапан подачи воды охлаждения (RELE_CHANNEL3, valve_buzzer.h::open_valve) и
насос охлаждения (pumppwm.h::set_pump_pwm) - НЕ нагревательные каналы. Раньше
оба несли собственный безусловный гейт по heater_safety_latched(), из-за чего
после аварии по перегреву - когда охлаждение нужнее всего - клапан и насос
молча глушились.

Тест вытаскивает РЕАЛЬНОЕ тело open_valve() из valve_buzzer.h через
extract_function_body - без переписывания логики - и подставляет его в
минимальный host-харнесс, замокав heater_safety_latched/digitalWrite/SendMsg.
Проверяется поведение (valve_status и аргумент digitalWrite), а не текст.

Плюс регресс на pumppwm.h::set_pump_pwm - тело функции не должно снова
обрасти гейтом по heater_safety_latched().
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

OPEN_VALVE_SIGNATURE = "void open_valve(bool Val, bool msg = true)"

HARNESS_TEMPLATE = r'''
#include <iostream>

#define RELE_CHANNEL3 3

static bool g_heaterLatched = false;
bool heater_safety_latched() { return g_heaterLatched; }

struct SetupEEPROM { bool rele3; };
static SetupEEPROM SamSetup;

static bool valve_status = false;

enum { WARNING_MSG = 1, NOTIFY_MSG = 2 };
static int sendMsgCalls = 0;
void SendMsg(const char*, int) { sendMsgCalls++; }

// Заглушка НЕ static: единственный вызов на каждую ветку лежит во вклеенном
// теле open_valve ниже, и со static мутация, вернувшая гейт по
// heater_safety_latched(), роняла бы компилятор по unused-function вместо
// содержательного assert-а на digitalWriteCalls/lastDigitalWriteValue.
static int digitalWriteCalls = 0;
static int lastDigitalWritePin = -1;
static int lastDigitalWriteValue = -1;
void digitalWrite(int pin, int value) {
  digitalWriteCalls++;
  lastDigitalWritePin = pin;
  lastDigitalWriteValue = value;
}

void open_valve(bool Val, bool msg = true) {
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(bool rele3, bool latched) {
  SamSetup.rele3 = rele3;
  g_heaterLatched = latched;
  valve_status = false;
  sendMsgCalls = 0;
  digitalWriteCalls = 0;
  lastDigitalWritePin = -1;
  lastDigitalWriteValue = -1;
}

int main() {
  const bool bools[2] = {true, false};

  // open_valve(true): клапан обязан открываться НЕЗАВИСИМО от защёлки -
  // регресс-кейс против "if (Val && !heater_safety_latched())".
  for (bool rele3 : bools) {
    for (bool latched : bools) {
      reset_fixture(rele3, latched);
      open_valve(true, false);
      check(valve_status == true, "open_valve(true) должен открыть клапан независимо от защёлки");
      check(digitalWriteCalls == 1, "open_valve(true) должен вызвать digitalWrite ровно один раз");
      check(lastDigitalWritePin == RELE_CHANNEL3, "open_valve(true) должен писать в RELE_CHANNEL3");
      check(lastDigitalWriteValue == (rele3 ? 1 : 0),
            "open_valve(true) должен писать SamSetup.rele3 как есть (полярность реле)");
    }
  }

  // open_valve(false): клапан закрывается вне зависимости от защёлки -
  // латч не подменяет обычную логику закрытия.
  for (bool rele3 : bools) {
    for (bool latched : bools) {
      reset_fixture(rele3, latched);
      open_valve(false, false);
      check(valve_status == false, "open_valve(false) должен закрыть клапан независимо от защёлки");
      check(digitalWriteCalls == 1, "open_valve(false) должен вызвать digitalWrite ровно один раз");
      check(lastDigitalWriteValue == (rele3 ? 0 : 1),
            "open_valve(false) должен писать !SamSetup.rele3");
    }
  }

  if (failures != 0) return 1;
  std::cout << "open_valve emergency-cooling behaviour checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    body = extract_function_body(source, OPEN_VALVE_SIGNATURE)
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def compile_and_run_open_valve() -> int:
    source = (ROOT / "valve_buzzer.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-valve-emergency-cooling-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "valve_emergency_cooling_test.cpp"
        binary = temp / "valve_emergency_cooling_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(cpp_source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def check_pump_pwm_no_latch_gate() -> int:
    source = (ROOT / "pumppwm.h").read_text(encoding="utf-8", errors="ignore")
    try:
        body = extract_function_body(source, "void set_pump_pwm(float duty)")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    stripped = strip_cpp_comments(body)
    if "heater_safety_latched" in stripped:
        print(
            "FAIL: pumppwm.h::set_pump_pwm regressed - "
            "heater_safety_latched() must not gate the cooling pump",
            file=sys.stderr,
        )
        return 1
    print("pumppwm.h set_pump_pwm has no heater_safety_latched gate")
    return 0


def main() -> int:
    rc = compile_and_run_open_valve()
    if rc != 0:
        return rc
    return check_pump_pwm_no_latch_gate()


if __name__ == "__main__":
    raise SystemExit(main())
