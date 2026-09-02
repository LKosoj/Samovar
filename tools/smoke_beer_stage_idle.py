#!/usr/bin/env python3
"""Поведенческая проверка П2 п.5+6 и П1: накопитель простоя строки P/B/C и
формула прошедшего активного времени строки.

beer_update_stage_idle() не должен засчитывать в выдержку строки время
ручной паузы (строки 'P', 'B' и 'C'), а также время вне полосы гистерезиса
на 'P' (но НЕ на 'B'/'C' - они реагируют только на ручную паузу, не на
температурные скачки). Тест вытаскивает РЕАЛЬНОЕ тело
beer_update_stage_idle() из beer.h через extract_function_body и проверяет
итоговые значения beerStageIdleAccumMs/beerStageIdleSinceMs после серии
вызовов, а не факт наличия строк в исходнике.

[П1, БЛОКЕР] beer_stage_elapsed_ms() раньше была двумя копипастами формулы
вида (float)(millis() - begintime - beerStageIdleAccumMs): все три величины
unsigned long, приведение к float шло ПОСЛЕ вычитания. Если накопленный
простой (beerStageIdleAccumMs) больше прошедшего с begintime времени,
разность заворачивается в ~4.29e9 мс, и проверка "выдержка строки истекла"
становится мгновенно истинной - шаг затирания/кипячения проскакивает за
0 секунд. Тест проверяет РЕАЛЬНОЕ тело beer_stage_elapsed_ms() именно на
этом сценарии (begintime=1000, beerStageIdleAccumMs=50000, nowMs=2000).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

BEER_UPDATE_STAGE_IDLE_SIGNATURE = "inline void beer_update_stage_idle(ProgramType currentType, float temp, float tempDelta, unsigned long nowMs)"
BEER_STAGE_ELAPSED_MS_SIGNATURE = "inline float beer_stage_elapsed_ms(unsigned long nowMs)"

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

@BEER_STAGE_ELAPSED_MS_BODY@

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

// [П13] Ручная пауза во время остывания ('C') тоже должна копить простой -
// нужна для таймаута остывания (beer_stage_elapsed_ms).
static void test_manual_pause_accumulates_idle_on_cooling_row() {
  reset_fixture();
  begintime = 1;
  beerManualPause = true;

  beer_update_stage_idle('C', 50, 0.3f, 3000);
  check(beerStageIdleSinceMs == 3000, "РЕГРЕСС: ручная пауза на охлаждении не зафиксировала начало простоя");

  beerManualPause = false;
  beer_update_stage_idle('C', 50, 0.3f, 3400);
  check(beerStageIdleAccumMs == 400, "РЕГРЕСС: ручная пауза на охлаждении не зачлась в накопитель после снятия");
}

// [П1] Ручная пауза до старта строки (begintime==0) не должна начинать
// копить простой - иначе накопитель может обогнать прошедшее время ещё до
// того, как строка вообще стартовала (см. beer_stage_elapsed_ms).
static void test_manual_pause_before_row_start_does_not_accumulate() {
  reset_fixture();
  program[0].Temp = 65;
  begintime = 0;
  beerManualPause = true;

  beer_update_stage_idle('P', 30, 0.3f, 1000);
  check(beerStageIdleSinceMs == 0,
        "РЕГРЕСС: ручная пауза при begintime==0 не должна считаться простоем (строка ещё не стартовала)");
  check(beerStageIdleAccumMs == 0,
        "РЕГРЕСС: ручная пауза при begintime==0 не должна копить накопитель простоя");

  beer_update_stage_idle('B', 30, 0.3f, 2000);
  check(beerStageIdleSinceMs == 0,
        "РЕГРЕСС: ручная пауза на 'B' при begintime==0 не должна считаться простоем");
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

// [Пиво 02.09 A4] Перегрев выше полосы гистерезиса на 'P' простоем не считается -
// таймер выдержки не должен останавливаться, пока температура не ниже цели.
static void test_P_overheat_above_band_does_not_accumulate_idle() {
  reset_fixture();
  program[0].Temp = 65;
  begintime = 1;

  beer_update_stage_idle('P', 70, 0.3f, 1000);  // сильно выше цели
  check(beerStageIdleSinceMs == 0,
        "РЕГРЕСС: перегрев выше полосы гистерезиса на 'P' ошибочно считается простоем");
  check(beerStageIdleAccumMs == 0, "накопитель не должен расти на перегреве строки 'P'");
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

// Контроль: типы, отличные от 'P'/'B'/'C' (например, 'M'), не участвуют в
// накопителе простоя вовсе, даже если ручная пауза активна.
static void test_other_types_never_accumulate_idle() {
  reset_fixture();
  beerManualPause = true;
  begintime = 1;

  beer_update_stage_idle('M', 30, 0.3f, 1000);
  check(beerStageIdleSinceMs == 0, "РЕГРЕСС: строка 'M' не должна участвовать в накопителе простоя");
  check(beerStageIdleAccumMs == 0, "РЕГРЕСС: строка 'M' не должна зачитывать простой в накопитель");
}

// [П1, БЛОКЕР] Ключевой регресс-сценарий: накопленный простой БОЛЬШЕ
// прошедшего с begintime времени. До фикса
// (float)(millis() - begintime - beerStageIdleAccumMs) заворачивал
// беззнаковое вычитание в ~4.29e9 мс - любой порог по времени "проходил"
// мгновенно. После фикса результат должен быть ровно 0 (зажат снизу).
static void test_elapsed_clamped_when_idle_exceeds_elapsed_wall_time() {
  reset_fixture();
  begintime = 1000;
  beerStageIdleAccumMs = 50000;  // больше, чем прошло реального времени ниже

  float elapsed = beer_stage_elapsed_ms(2000);
  check(elapsed == 0.0f,
        "РЕГРЕСС: переполнение при beerStageIdleAccumMs > прошедшего времени должно давать 0, а не ~4.29e9 мс");
}

// Контроль: в обычном случае (простой меньше прошедшего времени) формула
// считает как обычная арифметика.
static void test_elapsed_normal_case() {
  reset_fixture();
  begintime = 1000;
  beerStageIdleAccumMs = 500;

  float elapsed = beer_stage_elapsed_ms(10000);
  check(elapsed == 8500.0f, "РЕГРЕСС: обычный расчёт прошедшего активного времени сломан");
}

int main() {
  test_manual_pause_accumulates_idle_on_pause_row();
  test_manual_pause_accumulates_idle_on_boil_row();
  test_manual_pause_accumulates_idle_on_cooling_row();
  test_manual_pause_before_row_start_does_not_accumulate();
  test_P_out_of_band_idle_requires_started_row();
  test_P_overheat_above_band_does_not_accumulate_idle();
  test_B_type_ignores_temperature_band();
  test_other_types_never_accumulate_idle();
  test_elapsed_clamped_when_idle_exceeds_elapsed_wall_time();
  test_elapsed_normal_case();
  if (failures != 0) return 1;
  std::cout << "beer.h stage idle accumulator behaviour checks passed\n";
  return 0;
}
'''


def build_harness(beer_header_path: Path) -> str:
    beer_source = beer_header_path.read_text(encoding="utf-8")
    idle_body = extract_function_body(beer_source, BEER_UPDATE_STAGE_IDLE_SIGNATURE)
    idle_fn = (
        "void beer_update_stage_idle(ProgramType currentType, float temp, float tempDelta, unsigned long nowMs) {"
        + idle_body
        + "}"
    )
    elapsed_body = extract_function_body(beer_source, BEER_STAGE_ELAPSED_MS_SIGNATURE)
    elapsed_fn = "float beer_stage_elapsed_ms(unsigned long nowMs) {" + elapsed_body + "}"
    harness = HARNESS_TEMPLATE.replace("@BEER_UPDATE_STAGE_IDLE_BODY@", idle_fn)
    return harness.replace("@BEER_STAGE_ELAPSED_MS_BODY@", elapsed_fn)


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
