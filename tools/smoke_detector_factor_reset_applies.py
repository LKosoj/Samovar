#!/usr/bin/env python3
"""Поведенческая проверка [T05]: выключение детектора/автоскорости обязано СНЯТЬ
накопленную коррекцию со скорости насоса, а не только обнулить correctionFactor
в памяти (impurity_detector.h).

До правки обе ветки сброса в process_impurity_detector() ставили
impurityDetector.correctionFactor = 1.0f и делали return ДО вызова
apply_detector_speed_correction() - насос продолжал крутиться с последней
применённой пониженной скоростью (например 0.7 от базовой), пока оператор не
менял её вручную.

Часть (а): вытаскивает РЕАЛЬНЫЕ фрагменты веток
"!SamSetup.useautospeed || !SamSetup.useDetector" (~558) и
"SamovarStatusInt != SAMOVAR_STATUS_RECT_WITHDRAWAL" (~585) вместе с реальным
телом apply_detector_speed_correction() и проверяет поведением: после сброса
скорость, переданная насосу, соответствует полной CurrentBaseSpeedRate (без
старого correctionFactor), причём пропорционально для разных базовых скоростей.

Часть (б): статически подтверждает, что обе ветки зовут
apply_detector_speed_correction() до return.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]

APPLY_CORRECTION_SIGNATURE = "inline bool apply_detector_speed_correction(float baseSpeedRate) {"
AUTOSPEED_OFF_TOKEN = "if (!SamSetup.useautospeed || !SamSetup.useDetector) {"
STATUS_RESET_TOKEN = "if (SamovarStatusInt != SAMOVAR_STATUS_RECT_WITHDRAWAL) {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

struct SamSetupType {
  bool useautospeed = true;
  bool useDetector = true;
};
static SamSetupType SamSetup;

struct ImpurityDetector {
  uint8_t detectorStatus = 0;
  float correctionFactor = 1.0f;
};
static ImpurityDetector impurityDetector;

static volatile float CurrentBaseSpeedRate = 0.0f;

static const int SAMOVAR_STATUS_RECT_WITHDRAWAL = 10;
static int SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;

// ---- Моки внешних зависимостей ----
static float lastPumpSpeedArg = -1.0f;
static int setPumpSpeedCallCount = 0;

static void set_pump_speed(float stepSpeed, bool, bool) {
  lastPumpSpeedArg = stepSpeed;
  setPumpSpeedCallCount++;
}

// Тождественный мок: реальный get_speed_from_rate (logic.h) домножает на
// SamSetup.StepperStepMl - для проверки пропорциональности коррекции достаточно
// тождественного преобразования rate -> шаги/с.
static float get_speed_from_rate(float volume_per_hour) {
  return volume_per_hour;
}

// ---- Реальный код под тестом (фрагменты impurity_detector.h) ----
static bool apply_detector_speed_correction(float baseSpeedRate) {
@APPLY_BODY@
}

static bool reachedTailAutospeedOff = false;
static void autospeed_off_tick() {
@AUTOSPEED_OFF_BRANCH@
  reachedTailAutospeedOff = true;
}

static bool reachedTailStatusReset = false;
static void status_reset_tick() {
@STATUS_RESET_BRANCH@
  reachedTailStatusReset = true;
}

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(float correctionFactor, float baseSpeedRate) {
  impurityDetector.detectorStatus = 2;
  impurityDetector.correctionFactor = correctionFactor;
  CurrentBaseSpeedRate = baseSpeedRate;
  lastPumpSpeedArg = -1.0f;
  setPumpSpeedCallCount = 0;
  reachedTailAutospeedOff = false;
  reachedTailStatusReset = false;
}

// Сценарий 1: детектор выключен (useDetector=false) при накопленной коррекции 0.7 -
// снятая коррекция должна немедленно применяться к насосу, а не оставаться висеть в памяти.
static void test_autospeed_off_resets_pump_speed() {
  reset_fixture(0.7f, 60.0f);
  SamSetup.useautospeed = true;
  SamSetup.useDetector = false;

  autospeed_off_tick();

  check(impurityDetector.correctionFactor == 1.0f, "выключение детектора: correctionFactor должен сброситься в 1.0");
  check(setPumpSpeedCallCount == 1, "выключение детектора: set_pump_speed должен быть вызван ровно один раз");
  check(lastPumpSpeedArg == 60.0f,
        "скорость не восстановлена: насосу должна быть передана полная CurrentBaseSpeedRate (60.0), а не заниженная 0.7*60");
  check(!reachedTailAutospeedOff, "выключение детектора: должен быть ранний return");
}

// Сценарий 2: другая базовая скорость (вдвое больше) - результат обязан быть
// пропорционален CurrentBaseSpeedRate, а не хардкоженным значением из сценария 1.
static void test_autospeed_off_resets_pump_speed_proportionally() {
  reset_fixture(0.5f, 120.0f);
  SamSetup.useautospeed = false;
  SamSetup.useDetector = true;

  autospeed_off_tick();

  check(impurityDetector.correctionFactor == 1.0f, "выключение автоскорости: correctionFactor должен сброситься в 1.0");
  check(setPumpSpeedCallCount == 1, "выключение автоскорости: set_pump_speed должен быть вызван ровно один раз");
  check(lastPumpSpeedArg == 120.0f,
        "скорость не восстановлена: насосу должна быть передана полная CurrentBaseSpeedRate (120.0)");
}

// Сценарий 3: ветка сброса по статусу (не RECT_WITHDRAWAL) - вызов безвреден
// (моковый set_pump_speed всё равно примет значение), но по правилам единообразия
// обязан присутствовать до return, как и в ветке 1.
static void test_status_reset_calls_apply_correction() {
  reset_fixture(0.6f, 80.0f);
  SamovarStatusInt = 99;  // любой статус, кроме RECT_WITHDRAWAL

  status_reset_tick();

  check(impurityDetector.correctionFactor == 1.0f, "сброс по статусу: correctionFactor должен сброситься в 1.0");
  check(setPumpSpeedCallCount == 1, "сброс по статусу: apply_detector_speed_correction должен быть вызван до return");
  check(!reachedTailStatusReset, "сброс по статусу: должен быть ранний return");
}

// Сценарий 4: сброс - событие, а не состояние. process_impurity_detector() зовётся
// из loop() (~200 раз в секунду); пока коррекции нет, переставлять насосу ту же
// скорость незачем - это перезапись периода таймера степпера на каждом обороте.
static void test_reset_applies_once_not_every_tick() {
  reset_fixture(0.7f, 60.0f);
  SamSetup.useautospeed = true;
  SamSetup.useDetector = false;

  autospeed_off_tick();
  check(setPumpSpeedCallCount == 1, "первый тик после выключения детектора обязан снять коррекцию");

  for (int i = 0; i < 50; i++) autospeed_off_tick();
  check(setPumpSpeedCallCount == 1,
        "РЕГРЕСС: снятая коррекция переприменяется на каждом обороте loop() - скорость насоса переставляется впустую");

  // Та же проверка для ветки сброса по статусу, причём с самого начала без коррекции:
  // ни одного обращения к насосу быть не должно.
  reset_fixture(1.0f, 80.0f);
  SamovarStatusInt = 99;
  for (int i = 0; i < 50; i++) status_reset_tick();
  check(setPumpSpeedCallCount == 0,
        "РЕГРЕСС: сброс по статусу без накопленной коррекции не должен трогать насос вообще");
  SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
}

int main() {
  test_autospeed_off_resets_pump_speed();
  test_autospeed_off_resets_pump_speed_proportionally();
  test_status_reset_calls_apply_correction();
  test_reset_applies_once_not_every_tick();

  if (failures != 0) return 1;
  std::cout << "detector correctionFactor reset applies to pump speed checks passed\n";
  return 0;
}
'''


def extract_branch(detector_source: str, token: str) -> str:
    """Реальный фрагмент ветки: условие вместе с телом (как есть в исходнике)."""
    occurrences = detector_source.count(token)
    if occurrences != 1:
        raise ValueError(f"ожидалась одна ветка, найдено {occurrences}: {token}")
    start = detector_source.find(token)
    _, end = extract_braced_block_after(detector_source, token)
    return detector_source[start:end]


def build_harness(detector_source: str) -> str:
    apply_body = extract_function_body(detector_source, APPLY_CORRECTION_SIGNATURE)
    autospeed_off_branch = extract_branch(detector_source, AUTOSPEED_OFF_TOKEN)
    status_reset_branch = extract_branch(detector_source, STATUS_RESET_TOKEN)
    harness = HARNESS_TEMPLATE.replace("@APPLY_BODY@", apply_body)
    harness = harness.replace("@AUTOSPEED_OFF_BRANCH@", autospeed_off_branch)
    harness = harness.replace("@STATUS_RESET_BRANCH@", status_reset_branch)
    return harness


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-detector-factor-reset-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "detector_factor_reset_applies_test.cpp"
        binary = temp / "detector_factor_reset_applies_test"
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

    # Обе ветки сброса обязаны звать apply_detector_speed_correction() до return,
    # иначе накопленная коррекция навсегда останется в скорости насоса.
    require_ordered_tokens(
        "process_impurity_detector: ветка выключения детектора/автоскорости применяет сброс к скорости насоса",
        process_body,
        [
            AUTOSPEED_OFF_TOKEN,
            "correctionFactor = 1.0f;",
            "apply_detector_speed_correction(CurrentBaseSpeedRate);",
            "return;",
        ],
        errors,
    )
    require_ordered_tokens(
        "process_impurity_detector: ветка сброса по статусу применяет сброс к скорости насоса",
        process_body,
        [
            STATUS_RESET_TOKEN,
            "correctionFactor = 1.0f;",
            "apply_detector_speed_correction(CurrentBaseSpeedRate);",
            "return;",
        ],
        errors,
    )

    return errors


def main() -> int:
    detector_source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")

    static_errors = check_detector_source(detector_source)
    if static_errors:
        print("detector correctionFactor reset applies smoke failed:")
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
