#!/usr/bin/env python3
"""[П16] Поведенческая проверка выдержки TIME_C для строки "предзахлёб" (тип 'C').

logic.h::run_program() при старте строки типа 'C' записывает alarm_c_low_min, а
alarm.h::check_alarm() трактует это поле как АБСОЛЮТНУЮ метку millis() срока
наступления (см. beer.h:31: "alarm_c_min/alarm_c_low_min - АБСОЛЮТНЫЕ метки
millis(), не относительное"). До правки run_program() писал туда МОМЕНТ СТАРТА
(millis()), а не срок (millis() + TIME_C*60000) - условие в check_alarm()
срабатывало почти сразу после старта строки, и защитная выдержка TIME_C минут
перед подъёмом напряжения фактически не работала (напряжение поднималось на
грани захлёба).

Тест вытаскивает РЕАЛЬНУЮ строку записи из run_program() (logic.h) и РЕАЛЬНЫЙ
ветвящийся блок чтения из check_alarm() (alarm.h) и связывает их в одном
харнессе с управляемым fake millis() - проверяется поведение обеих сторон
вместе, а не переписанная копия.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

# Уникальный якорь перед нужным (вторым) "if (currentType == 'C') {" в check_alarm() -
# первый такой if встречается раньше, в ветке alarm_c_min; этот комментарий
# предшествует именно интересующему нас блоку (alarm_c_low_min).
READ_BLOCK_ANCHOR = "Если программа предзахлеб и давно не было срабатывания датчика - повышаем напряжение"

WRITE_STMT_PREFIX = "if (program[num].WType == 'C' && alarm_c_low_min == 0) alarm_c_low_min ="

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

constexpr int TIME_C = 4;                 // Samovar.h: #define TIME_C 4
constexpr float PWR_FACTOR = 1.0f;

struct WProgram { char WType = 0; };

static WProgram program[2];
static unsigned long alarm_c_low_min = 0;
static unsigned long alarm_c_min = 0;
static float target_power_volt = 200.0f;

static unsigned long fake_now = 0;
static unsigned long millis() { return fake_now; }

static int setCurrentPowerCalls = 0;
static void set_current_power(float) { setCurrentPowerCalls++; }

// ---- Реальный код под тестом (записывающая сторона, logic.h::run_program) ----
static void write_side_apply(uint8_t num) {
  @WRITE_STMT@
}

// ---- Реальный код под тестом (читающая сторона, alarm.h::check_alarm, ветка 'C') ----
static void read_side_check(char currentType) {
  if (currentType == 'C') {
@READ_BLOCK@
  }
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // Строка программы №1 - предзахлёб.
  program[0].WType = 'C';
  alarm_c_low_min = 0;
  alarm_c_min = 0;
  setCurrentPowerCalls = 0;
  fake_now = 1000000UL;

  unsigned long startTime = fake_now;
  write_side_apply(0);

  check(alarm_c_low_min > startTime, "alarm_c_low_min должен стать СРОКОМ в будущем, а не текущим моментом");
  check(alarm_c_low_min == startTime + 1000UL * 60UL * (unsigned long)TIME_C,
        "alarm_c_low_min должен быть millis() + TIME_C минут (формат читающей ветки check_alarm())");

  // Сразу же (через "секунду", как в тикете) проверяем читающую сторону - подъём
  // напряжения НЕ должен сработать раньше срока.
  fake_now = startTime + 1000UL;  // +1 секунда
  read_side_check('C');
  check(setCurrentPowerCalls == 0, "напряжение не должно подниматься раньше выдержки TIME_C минут");
  check(alarm_c_low_min == startTime + 1000UL * 60UL * (unsigned long)TIME_C,
        "срок не должен был сброситься/сдвинуться преждевременно");

  // Спустя TIME_C минут (и мгновение) - подъём напряжения обязан сработать.
  fake_now = startTime + 1000UL * 60UL * (unsigned long)TIME_C + 1UL;
  read_side_check('C');
  check(setCurrentPowerCalls == 1, "после выдержки TIME_C минут напряжение обязано подняться");

  if (failures != 0) return 1;
  std::cout << "predflood (WType 'C') TIME_C delay behaviour checks passed\n";
  return 0;
}
'''


def extract_write_statement(logic_text: str) -> str:
    stripped = strip_cpp_comments(logic_text)
    start = stripped.find(WRITE_STMT_PREFIX)
    if start < 0:
        raise ValueError(f"write statement not found: {WRITE_STMT_PREFIX}")
    end = stripped.find(";", start)
    if end < 0:
        raise ValueError("write statement not terminated")
    return stripped[start:end + 1]


def build_harness() -> str:
    logic_text = (ROOT / "logic.h").read_text(encoding="utf-8")
    alarm_text = (ROOT / "alarm.h").read_text(encoding="utf-8")

    write_stmt = extract_write_statement(logic_text)

    anchor_pos = alarm_text.find(READ_BLOCK_ANCHOR)
    if anchor_pos < 0:
        raise ValueError(f"read block anchor not found: {READ_BLOCK_ANCHOR}")
    read_block, _ = extract_braced_block_after(alarm_text, "if (currentType == 'C') {", anchor_pos)

    harness = HARNESS_TEMPLATE
    harness = harness.replace("@WRITE_STMT@", write_stmt)
    harness = harness.replace("@READ_BLOCK@", read_block)
    return harness


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-predflood-delay-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "predflood_delay_test.cpp"
        binary = temp / "predflood_delay_test"
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


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    sys.exit(main())
