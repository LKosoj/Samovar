#!/usr/bin/env python3
"""Поведенческая проверка [В8]: флаги headsSpeedClamped/bodySpeedClamped в
column_math.h::calculate_column_etalon() - "рекомендация упёрлась в предел
сечения колонны, дальше её не сдвинуть без смены геометрии/насадки".

Сейчас ни один тест не читает эти два поля - удаление любого из двух
`res.xxxSpeedClamped = true;` (или подмена одного флага другим copy-paste'ом,
т.к. блоки heads/body структурно почти одинаковы) пройдёт незамеченным.

Извлекается РЕАЛЬНЫЙ код (struct + функция) через extract_braced_block_after/
extract_function_body - проверяется настоящая арифметика, а не переписанная
копия. Эталонные значения (клэмп срабатывает/не срабатывает) посчитаны
независимо по той же формуле, что и в прошивке, и записаны числами в
комментариях у каждой проверки в HARNESS_TEMPLATE ниже (например,
"headsFlowMlH~16.8 << предел~162.1" у случая A) - не скопированы из вывода
текущей прошивки.

Три параметрических случая (диаметр везде 2", т.к. клэмп зависит только от
высоты/плотности/сырья - обе стороны неравенства масштабируются сечением
одинаково):
  - A: высота 0.3 м, плотность 60%, сахар      -> оба флага false (запас с большим отрывом)
  - B: высота 2.5 м, плотность 40%, сахар      -> headsSpeedClamped false, bodySpeedClamped true
  - C: высота 4.0 м, плотность 60%, зерно      -> оба флага true
[Ф5][Ф6] 02.09.2026: коэффициент захлёба 1.15 -> 0.58 и ФЧ тела без множителя по
тарелкам - предел сечения теперь достигается только на очень высоких колоннах,
высоты сценариев B/C подняты (это и была цель правки: рекомендация тела больше
не упирается в предел на обычной колонне).
Случаи A/C дают "оба случая на каждый флаг"; случай B вдобавок разводит два
флага по разным значениям - ловит подмену одного флага другим.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

STRUCT_TOKEN = "struct ColumnResults {"
FN_SIGNATURE = "inline ColumnResults calculate_column_etalon(uint8_t rawMaterial, float diamInches)"
HEADS_CLAMP_LINE = "res.headsSpeedClamped = true;"
BODY_CLAMP_LINE_1 = "res.bodySpeedClamped = true;"

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>

static const float PI = 3.14159265358979323846f;
using std::isnan;
using std::pow;

static float EVAPORATION_FACTOR = 4.8f;

struct SetupEEPROM {
  float ColDiam;
  float ColHeight;
  uint8_t PackDens;
};
static SetupEEPROM SamSetup;

@COLUMN_RESULTS_STRUCT@

@CALCULATE_COLUMN_ETALON_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    failures++;
  }
}

int main() {
  // A: короткая колонна, сахар - оба флага НЕ подняты (запас с большим отрывом,
  // независимо посчитано: headsFlowMlH~16.8 << предел~162.1;
  // bodyFlowMaxMlH~647.8 << предел~1317.4).
  SamSetup.ColDiam = 2.0f;
  SamSetup.ColHeight = 0.3f;
  SamSetup.PackDens = 60;
  ColumnResults a = calculate_column_etalon(2, SamSetup.ColDiam);
  check(!a.headsSpeedClamped, "A: headsSpeedClamped не должен подниматься с большим запасом от предела");
  check(!a.bodySpeedClamped, "A: bodySpeedClamped не должен подниматься с большим запасом от предела");

  // B: высокая рыхлая колонна, сахар - headsSpeedClamped НЕ поднят (headsFlowMlH~138.0 < предел~162.1),
  // а bodySpeedClamped ПОДНЯТ (bodyFlowMaxMlH~1380.5 > предел~1317.4). Разводит
  // два флага по разным значениям - ловит подмену одного флага другим.
  SamSetup.ColDiam = 2.0f;
  SamSetup.ColHeight = 2.5f;
  SamSetup.PackDens = 40;
  ColumnResults b = calculate_column_etalon(2, SamSetup.ColDiam);
  check(!b.headsSpeedClamped, "B: headsSpeedClamped не должен подниматься - голова ещё далеко от предела сечения");
  check(b.bodySpeedClamped, "B: bodySpeedClamped обязан подняться - тело упёрлось в предел сечения (0.65 л/ч/мм2)");

  // C: очень высокая колонна, зерно - оба флага ПОДНЯТЫ (headsFlowMlH~225.8 > предел~162.1;
  // bodyFlowMaxMlH~1448.7 > предел~1317.4).
  SamSetup.ColDiam = 2.0f;
  SamSetup.ColHeight = 4.0f;
  SamSetup.PackDens = 60;
  ColumnResults c = calculate_column_etalon(1, SamSetup.ColDiam);
  check(c.headsSpeedClamped, "C: headsSpeedClamped обязан подняться - голова упёрлась в предел сечения (0.08 л/ч/мм2)");
  check(c.bodySpeedClamped, "C: bodySpeedClamped обязан подняться - тело тоже упёрлось в предел сечения");

  if (failures != 0) return 1;
  std::cout << "column_math.h speed clamp flag checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    struct_body, _ = extract_braced_block_after(source, STRUCT_TOKEN)
    fn_body = extract_function_body(source, FN_SIGNATURE)
    harness = HARNESS_TEMPLATE.replace(
        "@COLUMN_RESULTS_STRUCT@", "struct ColumnResults {" + struct_body + "};"
    )
    harness = harness.replace(
        "@CALCULATE_COLUMN_ETALON_BODY@",
        "static ColumnResults calculate_column_etalon(uint8_t rawMaterial, float diamInches) {" + fn_body + "}",
    )
    return harness


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-column-speed-clamp-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "column_speed_clamp_test.cpp"
        binary = temp / "column_speed_clamp_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compiled.stdout)
            sys.stderr.write(compiled.stderr)
            return compiled.returncode
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(f"[{label}] ")
        sys.stdout.write(ran.stdout)
        sys.stderr.write(ran.stderr)
        return ran.returncode


def main() -> int:
    source = (ROOT / "column_math.h").read_text(encoding="utf-8")

    if HEADS_CLAMP_LINE not in source:
        print(f"FAIL: anchor not found: {HEADS_CLAMP_LINE}", file=sys.stderr)
        return 1
    if source.count(BODY_CLAMP_LINE_1) < 2:
        print(f"FAIL: expected 2 occurrences of {BODY_CLAMP_LINE_1!r}, found {source.count(BODY_CLAMP_LINE_1)}", file=sys.stderr)
        return 1

    rc = compile_and_run(build_harness(source), "column speed clamp flags")
    if rc != 0:
        return rc

    # --- Мутация: убираем headsSpeedClamped=true - случай C обязан покраснеть.
    mutated_heads = source.replace(HEADS_CLAMP_LINE, "", 1)
    if mutated_heads == source:
        print("FAIL: mutation anchor missing (headsSpeedClamped)", file=sys.stderr)
        return 1
    rc_heads = compile_and_run(build_harness(mutated_heads), "mutation: headsSpeedClamped removed")
    if rc_heads == 0:
        print("FAIL: mutation (removed headsSpeedClamped) survived", file=sys.stderr)
        return 1

    # --- Мутация: убираем ОБА res.bodySpeedClamped = true; - случаи B/C обязаны покраснеть.
    mutated_body = source.replace(BODY_CLAMP_LINE_1, "")
    if mutated_body == source:
        print("FAIL: mutation anchor missing (bodySpeedClamped)", file=sys.stderr)
        return 1
    rc_body = compile_and_run(build_harness(mutated_body), "mutation: bodySpeedClamped removed")
    if rc_body == 0:
        print("FAIL: mutation (removed bodySpeedClamped) survived", file=sys.stderr)
        return 1

    print("column speed clamp flag mutation checks: FAIL as expected without flags (mutations killed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
