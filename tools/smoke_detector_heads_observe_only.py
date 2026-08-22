#!/usr/bin/env python3
"""Поведенческая проверка "детектор на головах только наблюдает" (impurity_detector.h).

Рост Т пара на строке голов ('H') - штатный процесс (лёгкие фракции выводятся,
пар очищается, Т идёт к спиртовой полке), а не проскок примесей. Детектор больше
не управляет по нему скоростью: на 'H' он ведёт историю и тренд (телеметрия и лог
перегона остаются живыми), но выходит до порогов и коррекций.

Часть (а): вытаскивает РЕАЛЬНЫЙ фрагмент "if (currentType == 'H') { ... }" из
process_impurity_detector() (условие + тело, без переписанной в тесте копии) и
проверяет поведением: на 'H' статус обнуляется, correctionFactor возвращается к
1.0 и выполняется ранний return; на 'B'/'T' фрагмент ничего не делает.

Часть (б): статически фиксирует место вставки (после сбора истории, до грейс-периода),
отсутствие управляющих вызовов внутри ветки, удаление осиротевшего кода
(множитель 0.9 для голов в get_adaptive_threshold, спецграйс 60 с в
detector_on_program_start) и подпись "только наблюдение" в веб-интерфейсе.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]

HEADS_BRANCH_TOKEN = "if (currentType == 'H') {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

typedef char ProgramType;

struct ImpurityDetector {
  uint8_t detectorStatus = 0;
  uint8_t criticalConfirm = 0;
  float correctionFactor = 1.0f;
};

static ImpurityDetector impurityDetector;
static bool reachedTail = false;

// ---- Реальный код под тестом (фрагмент impurity_detector.h) ----
static void detector_heads_tick(ProgramType currentType) {
@HEADS_BRANCH@
  // Хвост функции: сюда управление доходит, только если ветка голов не сработала
  reachedTail = true;
}

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(uint8_t status, float factor) {
  impurityDetector.detectorStatus = status;
  impurityDetector.correctionFactor = factor;
  reachedTail = false;
}

// Сценарий 1: строка голов - наблюдение вместо управления.
static void test_heads_row_observes_only() {
  reset_fixture(2, 0.7f);  // как если бы состояние осталось с предыдущей строки

  detector_heads_tick('H');

  check(impurityDetector.detectorStatus == 0, "головы: статус детектора должен быть сброшен в 0");
  check(impurityDetector.correctionFactor == 1.0f,
        "головы: correctionFactor должен вернуться к 1.0 - скорость задаёт только строка программы");
  check(!reachedTail, "головы: должен быть ранний return, пороги и коррекции недостижимы");
}

// Сценарий 2: тело - ветка голов не вмешивается.
static void test_body_row_falls_through() {
  reset_fixture(1, 0.8f);

  detector_heads_tick('B');

  check(impurityDetector.detectorStatus == 1, "тело: ветка голов не должна трогать статус");
  check(impurityDetector.correctionFactor == 0.8f, "тело: ветка голов не должна трогать correctionFactor");
  check(reachedTail, "тело: управление должно дойти до порогов детектора");
}

// Сценарий 3: хвосты - детектор по-прежнему работает в полном объёме.
static void test_tails_row_falls_through() {
  reset_fixture(1, 0.9f);

  detector_heads_tick('T');

  check(impurityDetector.detectorStatus == 1, "хвосты: ветка голов не должна трогать статус");
  check(impurityDetector.correctionFactor == 0.9f, "хвосты: ветка голов не должна трогать correctionFactor");
  check(reachedTail, "хвосты: управление должно дойти до порогов детектора");
}

int main() {
  test_heads_row_observes_only();
  test_body_row_falls_through();
  test_tails_row_falls_through();

  if (failures != 0) return 1;
  std::cout << "detector heads observe-only behaviour checks passed\n";
  return 0;
}
'''


def extract_heads_branch(detector_source: str) -> str:
    """Реальный фрагмент ветки голов: условие вместе с телом."""
    occurrences = detector_source.count(HEADS_BRANCH_TOKEN)
    if occurrences != 1:
        raise ValueError(f"ожидалась одна ветка голов, найдено {occurrences}: {HEADS_BRANCH_TOKEN}")
    start = detector_source.find(HEADS_BRANCH_TOKEN)
    _, end = extract_braced_block_after(detector_source, HEADS_BRANCH_TOKEN)
    return detector_source[start:end]


def build_harness(detector_source: str) -> str:
    return HARNESS_TEMPLATE.replace("@HEADS_BRANCH@", extract_heads_branch(detector_source))


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-detector-heads-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "detector_heads_observe_only_test.cpp"
        binary = temp / "detector_heads_observe_only_test"
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


def check_detector_source(detector_source: str) -> list[str]:
    errors: list[str] = []

    try:
        process_body = extract_function_body(detector_source, "void process_impurity_detector()")
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    # Место вставки: история и тренд успевают обновиться, пороги остаются недостижимы
    require_ordered_tokens(
        "process_impurity_detector: ветка голов стоит после сбора истории и до грейс-периода",
        process_body,
        [
            "detector_sample_tick(detectorTemp, now);",
            HEADS_BRANCH_TOKEN,
            "detector_grace_until > 0",
        ],
        errors,
    )

    try:
        heads_branch = extract_heads_branch(detector_source)
    except ValueError as exc:
        errors.append(str(exc))
        heads_branch = ""

    for forbidden in ("set_pump_speed", "pause_withdrawal", "set_program_wait_type"):
        if forbidden in heads_branch:
            errors.append(f"ветка голов не должна управлять процессом, найден вызов: {forbidden}")

    # Осиротевший код удалён: на головах порог больше не считается вовсе
    try:
        threshold_body = extract_function_body(
            detector_source,
            "float get_adaptive_threshold(float baseThreshold",
        )
        if "processPhase == 'H'" in threshold_body:
            errors.append(
                "get_adaptive_threshold: множитель для голов недостижим - строки 'H' до порогов не доходят"
            )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        grace_body = extract_function_body(detector_source, "void detector_on_program_start()")
        if "60000UL" in grace_body:
            errors.append(
                "detector_on_program_start: спецграйс для голов недостижим - на 'H' детектор не реагирует"
            )
    except ValueError as exc:
        errors.append(str(exc))

    return errors


def check_web_interface() -> list[str]:
    errors: list[str] = []
    for relative in ("data_raw/index.htm", "data/index.htm"):
        path = ROOT / relative
        if not path.exists():
            errors.append(f"{relative}: файл не найден")
            continue
        require_ordered_tokens(
            f"{relative}: подпись наблюдения на головах стоит перед разбором статуса детектора",
            path.read_text(encoding="utf-8"),
            [
                "myObj.PrgType === 'H'",
                "только наблюдение",
                "myObj.DetectorStatus == 0",
            ],
            errors,
        )
    return errors


def main() -> int:
    detector_source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")

    static_errors = check_detector_source(detector_source) + check_web_interface()
    if static_errors:
        print("detector heads observe-only smoke failed:")
        for error in static_errors:
            print(f" - {error}")
        return 1

    try:
        harness = build_harness(detector_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
