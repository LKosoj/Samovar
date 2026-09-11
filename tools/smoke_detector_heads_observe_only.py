#!/usr/bin/env python3
"""Поведенческая проверка "детектор на головах и хвостах только наблюдает" (impurity_detector.h).

Рост Т пара на строке голов ('H') - штатный процесс (лёгкие фракции выводятся,
пар очищается, Т идёт к спиртовой полке), а не проскок примесей. Детектор больше
не управляет по нему скоростью: на 'H' он ведёт историю и тренд (телеметрия и лог
перегона остаются живыми), но выходит до порогов и коррекций.

Часть (а): вытаскивает РЕАЛЬНЫЙ фрагмент "if (currentType == 'H' || currentType == 'T') { ... }" из
process_impurity_detector() (условие + тело, без переписанной в тесте копии) и
проверяет поведением: на 'H'/'T' статус обнуляется, correctionFactor возвращается к
1.0 и выполняется ранний return; на 'B'/'C' фрагмент ничего не делает.

Часть (б): статически фиксирует место вставки (после сбора истории, до грейс-периода),
отсутствие управляющих вызовов внутри ветки, удаление осиротевшего кода
(множитель 0.9 для голов в get_adaptive_threshold, спецграйс 60 с в
detector_on_program_start) и подпись "Головы: наблюдение" в веб-интерфейсе.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]

OBSERVE_BRANCH_TOKEN = "if (currentType == 'H' || currentType == 'T') {"
TAILS_GUARD_TOKEN = "if (program_type_at(ProgramNum) == 'T') return false;"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

typedef char ProgramType;

struct ImpurityDetector {
  uint8_t detectorStatus = 0;
  uint8_t criticalConfirm = 0;
  float correctionFactor = 1.0f;
  uint8_t historySize = 0;
  float currentTrend = 0.0f;
};

static ImpurityDetector impurityDetector;
static bool reachedTail = false;

enum DetectorIdleReason : uint8_t {
  DETECTOR_IDLE_ACTIVE = 0,
  DETECTOR_IDLE_HEADS = 2,
  DETECTOR_IDLE_TAILS = 8
};
static DetectorIdleReason detector_idle_reason = DETECTOR_IDLE_ACTIVE;

// ---- Реальный код под тестом (фрагмент impurity_detector.h) ----
static void detector_observe_tick(ProgramType currentType) {
@OBSERVE_BRANCH@
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

static void reset_fixture(uint8_t status, float factor, uint8_t historySize, float trend) {
  impurityDetector.detectorStatus = status;
  impurityDetector.correctionFactor = factor;
  impurityDetector.historySize = historySize;
  impurityDetector.currentTrend = trend;
  reachedTail = false;
}

// Сценарий 1: строка голов - наблюдение вместо управления.
static void test_heads_row_observes_only() {
  reset_fixture(2, 0.7f, 5, 0.021f);  // как если бы состояние осталось с предыдущей строки

  detector_observe_tick('H');

  check(impurityDetector.detectorStatus == 0, "головы: статус детектора должен быть сброшен в 0");
  check(impurityDetector.correctionFactor == 1.0f,
        "головы: correctionFactor должен вернуться к 1.0 - скорость задаёт только строка программы");
  check(impurityDetector.historySize == 5 && impurityDetector.currentTrend == 0.021f,
        "головы: накопленная история и тренд остаются для телеметрии");
  check(!reachedTail, "головы: должен быть ранний return, пороги и коррекции недостижимы");
}

// Сценарий 2: хвосты - наблюдение вместо управления.
static void test_tails_row_observes_only() {
  reset_fixture(1, 0.7f, 9, 0.073f);

  detector_observe_tick('T');

  check(impurityDetector.detectorStatus == 0, "хвосты: статус детектора должен быть сброшен в 0");
  check(impurityDetector.correctionFactor == 1.0f,
        "хвосты: correctionFactor должен вернуться к 1.0 без команды приводу");
  check(impurityDetector.historySize == 9 && impurityDetector.currentTrend == 0.073f,
        "хвосты: история и второй тренд остаются для телеметрии");
  check(!reachedTail, "хвосты: должен быть ранний return, пороги, паузы и коррекции недостижимы");
  check(detector_idle_reason == DETECTOR_IDLE_TAILS, "хвосты: должна быть отдельная причина простоя");

  reset_fixture(2, 0.8f, 14, 0.118f);

  detector_observe_tick('T');

  check(impurityDetector.historySize == 14 && impurityDetector.currentTrend == 0.118f,
        "хвосты: второй набор истории и тренда остаётся для телеметрии");
  check(!reachedTail, "хвосты: второй тренд тоже не должен дойти до порогов");
}

// Сценарий 3: тело - ветка наблюдения не вмешивается.
static void test_body_row_falls_through() {
  reset_fixture(1, 0.8f, 7, 0.041f);

  detector_observe_tick('B');

  check(impurityDetector.detectorStatus == 1, "тело: ветка наблюдения не должна трогать статус");
  check(impurityDetector.correctionFactor == 0.8f, "тело: ветка наблюдения не должна трогать correctionFactor");
  check(reachedTail, "тело: управление должно дойти до порогов детектора");
}

// Сценарий 4: предзахлеб - управляющая ветка остаётся достижимой.
static void test_prechoke_row_falls_through() {
  reset_fixture(1, 0.9f, 8, 0.052f);

  detector_observe_tick('C');

  check(impurityDetector.detectorStatus == 1, "предзахлеб: ветка наблюдения не должна трогать статус");
  check(impurityDetector.correctionFactor == 0.9f, "предзахлеб: ветка наблюдения не должна трогать correctionFactor");
  check(reachedTail, "предзахлеб: управление должно дойти до порогов детектора");
}

int main() {
  test_heads_row_observes_only();
  test_tails_row_observes_only();
  test_body_row_falls_through();
  test_prechoke_row_falls_through();

  if (failures != 0) return 1;
  std::cout << "detector heads observe-only behaviour checks passed\n";
  return 0;
}
'''


def extract_observe_branch(detector_source: str) -> str:
    """Реальный фрагмент общей ветки наблюдения: условие вместе с телом."""
    occurrences = detector_source.count(OBSERVE_BRANCH_TOKEN)
    if occurrences != 1:
        raise ValueError(f"ожидалась одна ветка наблюдения, найдено {occurrences}: {OBSERVE_BRANCH_TOKEN}")
    start = detector_source.find(OBSERVE_BRANCH_TOKEN)
    _, end = extract_braced_block_after(detector_source, OBSERVE_BRANCH_TOKEN)
    return detector_source[start:end]


def build_harness(detector_source: str) -> str:
    return HARNESS_TEMPLATE.replace("@OBSERVE_BRANCH@", extract_observe_branch(detector_source))


def compile_harness(harness: str) -> subprocess.CompletedProcess[str]:
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
            return compile_result
        return subprocess.run([str(binary)], capture_output=True, text=True, check=False)


def compile_and_run(harness: str) -> int:
    result = compile_harness(harness)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def require_tails_observe_mutant_fails(detector_source: str) -> None:
    observe_branch = extract_observe_branch(detector_source)
    mutant_branch = observe_branch.replace(
        "if (currentType == 'H' || currentType == 'T') {",
        "if (currentType == 'H') {",
        1,
    )
    result = compile_harness(HARNESS_TEMPLATE.replace("@OBSERVE_BRANCH@", mutant_branch))
    output = result.stdout + result.stderr
    if result.returncode == 0 or "хвосты: должен быть ранний return" not in output:
        raise AssertionError("мутант без наблюдения на хвостах пережил runtime-проверку")


def check_detector_source(detector_source: str) -> list[str]:
    errors: list[str] = []

    try:
        process_body = extract_function_body(detector_source, "void process_impurity_detector()")
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    # Место вставки: история и тренд успевают обновиться, пороги остаются недостижимы
    require_ordered_tokens(
        "process_impurity_detector: ветка наблюдения стоит после сбора истории и до грейс-периода",
        process_body,
        [
            "detector_sample_tick(detectorTemp, now);",
            OBSERVE_BRANCH_TOKEN,
            "detector_grace_until > 0",
        ],
        errors,
    )

    try:
        observe_branch = extract_observe_branch(detector_source)
    except ValueError as exc:
        errors.append(str(exc))
        observe_branch = ""

    for forbidden in ("set_pump_speed", "pause_withdrawal", "set_program_wait_type"):
        if forbidden in observe_branch:
            errors.append(f"ветка наблюдения не должна управлять процессом, найден вызов: {forbidden}")

    if "DETECTOR_IDLE_TAILS" not in observe_branch:
        errors.append("ветка наблюдения: для хвостов нужна отдельная причина простоя DETECTOR_IDLE_TAILS")

    try:
        correction_body = extract_function_body(
            detector_source,
            "inline bool apply_detector_speed_correction(float baseSpeedRate)",
        )
        if TAILS_GUARD_TOKEN not in correction_body:
            errors.append("apply_detector_speed_correction: на хвостах обязателен ранний выход без команды приводу")
    except ValueError as exc:
        errors.append(str(exc))

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
    checks = {
        "data_raw/app.js": (
            "подпись наблюдения на головах задаётся в detectorIdleText",
            ["function detectorIdleText(", "prgType === 'H'", "Головы: наблюдение"],
        ),
        "data_raw/index.htm": (
            "подпись причины простоя (в том числе голов) стоит перед разбором статуса детектора",
            ["SamovarApp.detectorIdleText(", "myObj.DetectorStatus == 0"],
        ),
    }
    for relative, (title, tokens) in checks.items():
        path = ROOT / relative
        if not path.exists():
            errors.append(f"{relative}: файл не найден")
            continue
        require_ordered_tokens(f"{relative}: {title}", path.read_text(encoding="utf-8"), tokens, errors)
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
    result = compile_and_run(harness)
    if result != 0:
        return result
    try:
        require_tails_observe_mutant_fails(detector_source)
    except (AssertionError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
