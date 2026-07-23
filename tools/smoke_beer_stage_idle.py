#!/usr/bin/env python3
"""Поведенческая проверка П2 п.5+6: накопитель простоя строки P/B.

beer_update_stage_idle() не должен засчитывать в выдержку строки время
ручной паузы (обе строки 'P' и 'B'), а также время вне полосы гистерезиса
на 'P' (но НЕ на 'B' - кипячение реагирует только на ручную паузу, не на
температурные скачки). Тест вытаскивает РЕАЛЬНОЕ тело
beer_update_stage_idle() из beer.h через extract_function_body и проверяет
итоговые значения beerStageIdleAccumMs/beerStageIdleSinceMs после серии
вызовов, а не факт наличия строк в исходнике.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

BEER_UPDATE_STAGE_IDLE_SIGNATURE = "inline void beer_update_stage_idle(ProgramType currentType, float temp, float tempDelta, unsigned long nowMs)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

using ProgramType = char;
constexpr uint8_t PROGRAM_MAX = 8;

struct WProgram {
  float Temp = 0;
};

static WProgram program[PROGRAM_MAX];
static uint8_t ProgramNum = 0;
static unsigned long begintime = 0;
static bool beerManualPause = false;
static unsigned long beerStageIdleAccumMs = 0;
static unsigned long beerStageIdleSinceMs = 0;

@BEER_UPDATE_STAGE_IDLE_BODY@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  ProgramNum = 0;
  begintime = 0;
  beerManualPause = false;
  beerStageIdleAccumMs = 0;
  beerStageIdleSinceMs = 0;
}

// [P2 п.6] Ручная пауза на строке 'P' - простой должен копиться, пока пауза
// активна, и зафиксироваться в накопитель ровно в момент снятия паузы.
static void test_manual_pause_accumulates_idle_on_pause_row() {
  reset_fixture();
  program[0].Temp = 65;
  begintime = 1;
  beerManualPause = true;

  beer_update_stage_idle('P', 65, 0.3f, 1000);
  check(beerStageIdleSinceMs == 1000, "РЕГРЕСС: начало ручной паузы не зафиксировало момент начала простоя");
  check(beerStageIdleAccumMs == 0, "накопитель не должен расти, пока простой ещё не завершён");

  beer_update_stage_idle('P', 65, 0.3f, 4500);
  check(beerStageIdleSinceMs == 1000, "простой продолжается - момент начала не должен сдвигаться");
  check(beerStageIdleAccumMs == 0, "накопитель не должен расти во время непрерывного простоя");

  beerManualPause = false;
  beer_update_stage_idle('P', 65, 0.3f, 6000);
  check(beerStageIdleSinceMs == 0, "РЕГРЕСС: снятие паузы должно было сбросить момент начала простоя");
  check(beerStageIdleAccumMs == 5000,
        "РЕГРЕСС: снятие ручной паузы должно было зачесть в накопитель весь интервал простоя (5000мс)");
}

// [P2 п.6] Ручная пауза во время кипячения ('B') тоже должна копить простой -
// не только строка 'P'.
static void test_manual_pause_accumulates_idle_on_boil_row() {
  reset_fixture();
  begintime = 1;
  beerManualPause = true;

  beer_update_stage_idle('B', 99, 0.3f, 2000);
  check(beerStageIdleSinceMs == 2000, "РЕГРЕСС: ручная пауза на кипячении не зафиксировала начало простоя");

  beerManualPause = false;
  beer_update_stage_idle('B', 99, 0.3f, 2700);
  check(beerStageIdleAccumMs == 700, "РЕГРЕСС: ручная пауза на кипячении не зачлась в накопитель после снятия");
}

// [P2 п.5] Выход температуры за полосу гистерезиса на 'P' должен копить
// простой ТОЛЬКО когда строка уже стартовала (begintime > 0) - иначе ещё не
// дошедшая до цели строка перед стартом ложно считалась бы простоем.
static void test_P_out_of_band_idle_requires_started_row() {
  reset_fixture();
  program[0].Temp = 65;
  begintime = 0;  // строка ещё не стартовала

  beer_update_stage_idle('P', 40, 0.3f, 1000);  // сильно ниже цели
  check(beerStageIdleSinceMs == 0,
        "РЕГРЕСС: температура вне полосы до старта строки (begintime==0) не должна считаться простоем");

  begintime = 1;
  beer_update_stage_idle('P', 40, 0.3f, 2000);
  check(beerStageIdleSinceMs == 2000, "РЕГРЕСС: температура вне полосы гистерезиса на 'P' после старта строки не считается простоем");

  beer_update_stage_idle('P', 65, 0.3f, 5000);  // вернулись в полосу
  check(beerStageIdleSinceMs == 0, "РЕГРЕСС: возврат в полосу гистерезиса не сбросил простой");
  check(beerStageIdleAccumMs == 3000, "РЕГРЕСС: возврат в полосу гистерезиса не зачёл накопленный простой (3000мс)");
}

// [P2 п.5] На 'B' (кипячение) выход температуры за пределы program[].Temp+-tempDelta
// НЕ считается простоем - кипячение реагирует только на ручную паузу.
static void test_B_type_ignores_temperature_band() {
  reset_fixture();
  program[0].Temp = 100;
  begintime = 1;

  beer_update_stage_idle('B', 10, 0.3f, 1000);  // далеко вне "полосы", но это не 'P'
  check(beerStageIdleSinceMs == 0,
        "РЕГРЕСС: температурная полоса не должна считаться простоем на строке 'B' (только ручная пауза)");
  check(beerStageIdleAccumMs == 0, "накопитель не должен расти на 'B' без ручной паузы");
}

// Контроль: типы, отличные от 'P'/'B' (например, 'M'), не участвуют в
// накопителе простоя вовсе, даже если ручная пауза активна.
static void test_other_types_never_accumulate_idle() {
  reset_fixture();
  beerManualPause = true;

  beer_update_stage_idle('M', 30, 0.3f, 1000);
  check(beerStageIdleSinceMs == 0, "РЕГРЕСС: строка 'M' не должна участвовать в накопителе простоя");
  check(beerStageIdleAccumMs == 0, "РЕГРЕСС: строка 'M' не должна зачитывать простой в накопитель");
}

int main() {
  test_manual_pause_accumulates_idle_on_pause_row();
  test_manual_pause_accumulates_idle_on_boil_row();
  test_P_out_of_band_idle_requires_started_row();
  test_B_type_ignores_temperature_band();
  test_other_types_never_accumulate_idle();
  if (failures != 0) return 1;
  std::cout << "beer.h stage idle accumulator behaviour checks passed\n";
  return 0;
}
'''


def build_harness(beer_header_path: Path) -> str:
    beer_source = beer_header_path.read_text(encoding="utf-8")
    body = extract_function_body(beer_source, BEER_UPDATE_STAGE_IDLE_SIGNATURE)
    fn = (
        "void beer_update_stage_idle(ProgramType currentType, float temp, float tempDelta, unsigned long nowMs) {"
        + body
        + "}"
    )
    return HARNESS_TEMPLATE.replace("@BEER_UPDATE_STAGE_IDLE_BODY@", fn)


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-stage-idle-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_stage_idle_test.cpp"
        binary = temp / "beer_stage_idle_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        harness = build_harness(ROOT / "beer.h")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return compile_and_run(harness, "beer.h")


if __name__ == "__main__":
    raise SystemExit(main())
