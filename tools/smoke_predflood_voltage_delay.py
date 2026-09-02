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

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

# Уникальный якорь перед нужным (вторым) "if (currentType == 'C') {" в check_alarm() -
# первый такой if встречается раньше, в ветке alarm_c_min; этот комментарий
# предшествует именно интересующему нас блоку (alarm_c_low_min).
READ_BLOCK_ANCHOR = "Если программа предзахлеб и давно не было срабатывания датчика - повышаем напряжение"

# [Б5] Записывающая сторона теперь целиком ветвится по типу новой строки, а не
# одним условием на alarm_c_low_min - тянем весь if/else блок.
WRITE_IF_TOKEN = "if (program[num].WType == 'C') {"
WRITE_ELSE_TOKEN = "else {"

# [Б5 fix] alarm_h_min гасится ОТДЕЛЬНЫМ безусловным if - вне #ifdef
# SAMOVAR_USE_POWER (она объявлена и используется безусловно во всех сборках),
# перед основным if/else с alarm_c_*/prev_target_power_volt.
ALARM_H_MIN_RESET_TOKEN = "if (program[num].WType != 'C') {"

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
static unsigned long alarm_h_min = 0;
static float target_power_volt = 200.0f;
static float prev_target_power_volt = 0;

static unsigned long fake_now = 0;
static unsigned long millis() { return fake_now; }

static int setCurrentPowerCalls = 0;
static void set_current_power(float) { setCurrentPowerCalls++; }

// ---- Реальный код под тестом (записывающая сторона, logic.h::run_program) ----
static void write_side_apply(uint8_t num) {
  @WRITE_BLOCK@
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

  // [Б5] 'C' сразу за 'C' - уже идущий отсчёт и прочие счётчики НЕ должны обнуляться.
  program[0].WType = 'C';
  alarm_c_low_min = 555000UL;
  alarm_c_min = 777UL;
  prev_target_power_volt = 12.5f;
  alarm_h_min = 42UL;
  write_side_apply(0);
  check(alarm_c_low_min == 555000UL, "'C' за 'C' не должен сдвигать уже идущий отсчёт alarm_c_low_min");
  check(alarm_c_min == 777UL, "'C' за 'C' не должен трогать alarm_c_min");
  check(prev_target_power_volt == 12.5f, "'C' за 'C' не должен трогать prev_target_power_volt");
  check(alarm_h_min == 42UL, "'C' за 'C' не должен трогать alarm_h_min");

  // [Б5] Вход в строку не-'C' - весь тракт "охоты" за предзахлёбом гасится.
  program[0].WType = 'T';
  alarm_c_low_min = 555000UL;
  alarm_c_min = 777UL;
  prev_target_power_volt = 12.5f;
  alarm_h_min = 42UL;
  write_side_apply(0);
  check(alarm_c_min == 0, "вход в строку не-'C' должен обнулить alarm_c_min");
  check(alarm_c_low_min == 0, "вход в строку не-'C' должен обнулить alarm_c_low_min");
  check(prev_target_power_volt == 0, "вход в строку не-'C' должен обнулить prev_target_power_volt");
  check(alarm_h_min == 0, "вход в строку не-'C' должен обнулить alarm_h_min");

  if (failures != 0) return 1;
  std::cout << "predflood (WType 'C') TIME_C delay behaviour checks passed\n";
  return 0;
}
'''


def extract_write_block(logic_text: str) -> str:
    # [Б5 fix] Отдельный безусловный сброс alarm_h_min идёт ПЕРЕД основным if/else
    # (см. logic.h::run_program()) - тянем его тем же способом, реальным кодом.
    reset_body, _ = extract_braced_block_after(logic_text, ALARM_H_MIN_RESET_TOKEN)
    reset_block = ALARM_H_MIN_RESET_TOKEN + "\n" + reset_body + "}"

    if_body, if_end = extract_braced_block_after(logic_text, WRITE_IF_TOKEN)
    else_start = logic_text.find(WRITE_ELSE_TOKEN, if_end)
    if else_start < 0 or logic_text[if_end:else_start].strip() != "":
        raise ValueError("else block not found immediately after predflood write if-block")
    else_body, _ = extract_braced_block_after(logic_text, WRITE_ELSE_TOKEN, else_start)
    return (
        reset_block + "\n"
        "if (program[num].WType == 'C') {\n"
        + if_body
        + "} else {\n"
        + else_body
        + "}"
    )


def build_harness() -> str:
    logic_text = (ROOT / "logic.h").read_text(encoding="utf-8")
    alarm_text = (ROOT / "alarm.h").read_text(encoding="utf-8")

    write_block = extract_write_block(logic_text)

    anchor_pos = alarm_text.find(READ_BLOCK_ANCHOR)
    if anchor_pos < 0:
        raise ValueError(f"read block anchor not found: {READ_BLOCK_ANCHOR}")
    read_block, _ = extract_braced_block_after(alarm_text, "if (currentType == 'C') {", anchor_pos)

    harness = HARNESS_TEMPLATE
    harness = harness.replace("@WRITE_BLOCK@", write_block)
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
