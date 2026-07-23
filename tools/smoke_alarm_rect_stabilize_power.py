#!/usr/bin/env python3
"""Регресс-проверка перехода RECT_ACCEL -> RECT_STABILIZING в alarm.h.

Раньше этот переход применял program[0].Power к регулятору напрямую через
голый set_current_power(program[0].Power) - без логики "абсолют/дельта/0",
которая используется в run_program()/run_dist_program(). Из-за этого при
Power == 0 или малой дельте уставка проваливалась ниже
POWER_WORK_MODE_THRESHOLD, регулятор уходил в SLEEP, и нагрев молча гас под
статусом "стабилизация". Фикс - переход вызывает тот же unified-хелпер
apply_program_power_row(), что и run_program()/run_dist_program().

Тест вытаскивает РЕАЛЬНЫЙ блок кода (тело "if (column_wetting_result) { ... }"
внутри перехода) из alarm.h через extract_braced_block_after - без
переписывания логики - и подставляет его в минимальный host-харнесс, замокав
apply_program_power_row(). Проверяется факт и аргумент вызова - для двух
значений program[0].Power (0 и 55) хелпер должен быть вызван РОВНО один раз с
точным значением. Откат к сырому set_current_power(program[0].Power) не
компилируется (такого символа в харнессе нет), поэтому мутация "вернули
set_current_power" ловится уже на этапе сборки.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

ANCHOR = "if (column_wetting_result) {"

HARNESS_TEMPLATE = r'''
#include <iostream>

enum { NOTIFY_MSG = 2 };

int SamovarStatusInt = 0;
enum { SAMOVAR_STATUS_RECT_STABILIZING = 42 };
float acceleration_temp = -1.0f;

struct ProgramRow { float Power; };
static ProgramRow program[1];

static int sendMsgCalls = 0;
void SendMsg(const char*, int) { sendMsgCalls++; }

static int buzzerCalls = 0;
static bool lastBuzzer = false;
void set_buzzer(bool value) { buzzerCalls++; lastBuzzer = value; }

// Заглушка НЕ static: единственный вызов лежит во вклеенном теле блока ниже,
// и со static мутация, убравшая вызов (откат к раскрытой abs/дельта-логике
// или к сырому set_current_power), роняла бы компилятор по unused-function
// вместо содержательного assert-а. Держится это на проверках powerRowCalls/
// lastPowerRowArg: без них снятие static меняет ложный улов на молчаливую
// слепую зону, что хуже.
static int powerRowCalls = 0;
static float lastPowerRowArg = -999.0f;
void apply_program_power_row(float power) { powerRowCalls++; lastPowerRowArg = power; }

static void rect_stabilize_transition() {
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(float power) {
  SamovarStatusInt = 0;
  acceleration_temp = -1.0f;
  sendMsgCalls = 0;
  buzzerCalls = 0;
  lastBuzzer = false;
  powerRowCalls = 0;
  lastPowerRowArg = -999.0f;
  program[0].Power = power;
}

int main() {
  reset_fixture(0.0f);
  rect_stabilize_transition();
  check(powerRowCalls == 1, "переход в стабилизацию при Power==0 должен вызвать apply_program_power_row ровно один раз");
  check(lastPowerRowArg == 0.0f, "переход в стабилизацию должен передать program[0].Power как есть (0)");
  check(SamovarStatusInt == SAMOVAR_STATUS_RECT_STABILIZING, "переход не выставил статус RECT_STABILIZING");

  reset_fixture(55.0f);
  rect_stabilize_transition();
  check(powerRowCalls == 1, "переход в стабилизацию при Power==55 должен вызвать apply_program_power_row ровно один раз");
  check(lastPowerRowArg == 55.0f, "переход в стабилизацию должен передать program[0].Power как есть (55)");

  if (failures != 0) return 1;
  std::cout << "alarm.h RECT_ACCEL->RECT_STABILIZING power application checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    code = strip_cpp_comments(source)
    body, _ = extract_braced_block_after(code, ANCHOR)
    body = body.replace("\r\n", "\n")
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def main() -> int:
    source = (ROOT / "alarm.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-alarm-rect-stabilize-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "alarm_rect_stabilize_power_test.cpp"
        binary = temp / "alarm_rect_stabilize_power_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-DSAMOVAR_USE_POWER",
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


if __name__ == "__main__":
    raise SystemExit(main())
