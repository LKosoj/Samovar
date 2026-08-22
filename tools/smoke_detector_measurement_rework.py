#!/usr/bin/env python3
"""Проверка переработки измерительной части детектора примесей (impurity_detector.h).

Разбор показал: детектор не измерял тренд, а щёлкал. Показания DS18B20 квантованы
шагом 0.0625 °C, окно регрессии было 58 секунд, и на нём истинный рост до ~0.09 °C/мин
давал РОВНО ноль, а первый же щелчок кванта - сразу 0.094 °C/мин. Все рабочие пороги
(0.034...0.125) лежали внутри этой слепой зоны.

Проверяется:
(а) calculate_temperature_trend считает наклон по ФАКТИЧЕСКИМ меткам времени замеров,
    а не по предположению "точки идут ровно через 2 секунды";
(б) detector_update_background набирает фон и выставляет порог по нему (замена ручной
    плотности насадки), с клампами снизу и сверху;
(в) критическая пауза требует подтверждения: одиночный выброс её не вызывает;
(г) статические контракты: формула по PackDens убрана, нерабочий фильтр
    consecutiveRises удалён, порог считается в одном месте.

Все тела функций вытаскиваются из настоящего исходника, а не переписываются в тесте.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

CONFIRM_BLOCK_TOKEN = "if (trendUpdated) {"

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>

typedef char ProgramType;

struct ImpurityDetector {
  float tempHistory[30];
  uint32_t sampleTime[30];
  uint8_t historyIndex;
  uint8_t historySize;
  uint8_t criticalConfirm;
  float currentTrend;
};

static ImpurityDetector impurityDetector = {};

static const uint16_t DETECTOR_BG_SAMPLES = 60;
static const float DETECTOR_BG_SIGMA_K = 4.0f;
static const float DETECTOR_DEFAULT_WARNING_TREND = 0.04f;
static const float DETECTOR_MIN_WARNING_TREND = 0.02f;
static const float DETECTOR_MAX_WARNING_TREND = 0.15f;
static const uint8_t DETECTOR_CRITICAL_CONFIRM = 2;

static double detector_bg_sum = 0.0;
static double detector_bg_sumsq = 0.0;
static uint16_t detector_bg_count = 0;
static float detector_bg_threshold = 0.0f;

// ---- Реальный код под тестом ----
@TREND_FUNCTION@
@BACKGROUND_FUNCTION@
@BASE_THRESHOLD_FUNCTION@

// Блок подтверждения критики из process_impurity_detector (extract_braced_block_after)
static bool hasCriticalHistory = true;
static float criticalThreshold = 0.1f;
static void confirm_tick(bool trendUpdated) {
  if (trendUpdated) {
@CONFIRM_BLOCK@
  }
}

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

// Заполняет буфер: температура растёт с заданной скоростью, точки идут с заданными
// интервалами (мс). Возвращает ничего - результат в impurityDetector.
static void fill(const uint32_t* steps, uint8_t count, uint32_t startTime,
                 float startTemp, float degPerMinute) {
  impurityDetector.historySize = 0;
  impurityDetector.historyIndex = 0;
  uint32_t t = startTime;
  for (uint8_t i = 0; i < count; i++) {
    if (i > 0) t += steps[i - 1];
    const float elapsedMin = static_cast<float>(t - startTime) / 60000.0f;
    impurityDetector.tempHistory[impurityDetector.historyIndex] =
        startTemp + degPerMinute * elapsedMin;
    impurityDetector.sampleTime[impurityDetector.historyIndex] = t;
    impurityDetector.historyIndex = (impurityDetector.historyIndex + 1) % 30;
    if (impurityDetector.historySize < 30) impurityDetector.historySize++;
  }
}

// (а1) Равномерный шаг 4 с: наклон должен совпасть с заложенным ростом.
static void test_uniform_step() {
  uint32_t steps[29];
  for (uint8_t i = 0; i < 29; i++) steps[i] = 4000;
  fill(steps, 30, 100000, 78.0f, 0.05f);
  const float trend = calculate_temperature_trend();
  check(std::fabs(trend - 0.05f) < 0.001f,
        "равномерный шаг: наклон должен совпасть с заложенным ростом 0.05 C/мин");
}

// (а2) Неравномерный шаг: часть точек пришла с задержкой. По фактическим меткам
// времени наклон тот же; по предположению "каждые 2 секунды" он был бы искажён.
static void test_irregular_step() {
  uint32_t steps[29];
  for (uint8_t i = 0; i < 29; i++) steps[i] = (i < 15) ? 4000 : 12000;
  fill(steps, 30, 100000, 78.0f, 0.05f);
  const float trend = calculate_temperature_trend();
  check(std::fabs(trend - 0.05f) < 0.001f,
        "неравномерный шаг: наклон должен остаться верным (0.05 C/мин)");
}

// (а3) Переполнение millis каждые ~49.7 суток не должно ломать наклон:
// разность беззнаковых остаётся корректной.
static void test_millis_wraparound() {
  uint32_t steps[29];
  for (uint8_t i = 0; i < 29; i++) steps[i] = 4000;
  fill(steps, 30, UINT32_MAX - 40000U, 78.0f, 0.05f);
  const float trend = calculate_temperature_trend();
  check(std::fabs(trend - 0.05f) < 0.001f,
        "wraparound millis: наклон должен остаться верным");
}

// (а4) Окно ещё не заполнено (10 точек из 30): наклон уже должен считаться,
// иначе первые две минуты строки детектор слеп.
static void test_partial_window() {
  uint32_t steps[29];
  for (uint8_t i = 0; i < 29; i++) steps[i] = 4000;
  fill(steps, 10, 100000, 78.0f, 0.05f);
  const float trend = calculate_temperature_trend();
  check(std::fabs(trend - 0.05f) < 0.001f,
        "частично заполненное окно: наклон должен считаться по записанным точкам");
}

// (а4) Слишком короткая история: наклон не считается.
static void test_short_history() {
  uint32_t steps[29];
  for (uint8_t i = 0; i < 29; i++) steps[i] = 4000;
  fill(steps, 4, 100000, 78.0f, 0.05f);
  check(calculate_temperature_trend() == 0.0f,
        "меньше 5 точек: наклон должен быть нулевым");
}

static void reset_background() {
  detector_bg_sum = 0.0;
  detector_bg_sumsq = 0.0;
  detector_bg_count = 0;
  detector_bg_threshold = 0.0f;
  impurityDetector.historySize = 30;
}

// (б1) Пока фон не набран - порог дефолтный; после набора считается по фону.
static void test_background_calibration() {
  reset_background();
  check(std::fabs(detector_base_warning_threshold() - DETECTOR_DEFAULT_WARNING_TREND) < 1e-6f,
        "фон не набран: порог должен быть дефолтным");

  // Фон: тренд гуляет ±0.01 вокруг нуля. Сигма = 0.01, порог = 4 сигмы = 0.04.
  for (uint16_t i = 0; i < DETECTOR_BG_SAMPLES; i++) {
    impurityDetector.currentTrend = (i % 2 == 0) ? 0.01f : -0.01f;
    detector_update_background();
  }
  check(detector_bg_count == DETECTOR_BG_SAMPLES, "фон должен набраться ровно за DETECTOR_BG_SAMPLES замеров");
  check(std::fabs(detector_base_warning_threshold() - 0.04f) < 0.002f,
        "порог должен быть 4 сигмы измеренного разброса (0.04)");

  // Добор сверх лимита не должен менять уже зафиксированный порог
  const float fixed = detector_base_warning_threshold();
  for (uint16_t i = 0; i < 10; i++) {
    impurityDetector.currentTrend = 5.0f;
    detector_update_background();
  }
  check(detector_base_warning_threshold() == fixed,
        "после набора фон должен быть зафиксирован до конца строки");
}

// (б2) Очень тихий фон не должен опустить порог ниже минимума.
static void test_background_clamped_low() {
  reset_background();
  for (uint16_t i = 0; i < DETECTOR_BG_SAMPLES; i++) {
    impurityDetector.currentTrend = 0.0f;
    detector_update_background();
  }
  check(std::fabs(detector_base_warning_threshold() - DETECTOR_MIN_WARNING_TREND) < 1e-6f,
        "нулевой фон должен упереться в минимальный порог, а не отключить детектор чувствительностью");
}

// (б3) Очень шумный фон не должен задрать порог до бесконечности.
static void test_background_clamped_high() {
  reset_background();
  for (uint16_t i = 0; i < DETECTOR_BG_SAMPLES; i++) {
    impurityDetector.currentTrend = (i % 2 == 0) ? 0.5f : -0.5f;
    detector_update_background();
  }
  check(std::fabs(detector_base_warning_threshold() - DETECTOR_MAX_WARNING_TREND) < 1e-6f,
        "шумный фон должен упереться в максимальный порог");
}

// (б4) Падающая температура не должна занижать порог отрицательным средним.
// Фон гуляет между -0.03 и -0.05: среднее -0.04, разброс (сигма) 0.01.
// Порог должен получиться 4 сигмы = 0.04, а не 4 сигмы минус средний спад = 0.0.
static void test_background_negative_mean_does_not_lower_threshold() {
  reset_background();
  for (uint16_t i = 0; i < DETECTOR_BG_SAMPLES; i++) {
    impurityDetector.currentTrend = (i % 2 == 0) ? -0.03f : -0.05f;
    detector_update_background();
  }
  check(std::fabs(detector_base_warning_threshold() - 0.04f) < 0.002f,
        "отрицательный фон не должен вычитаться из порога: ожидались 4 сигмы разброса (0.04)");
}

// (б7) Идеально ровный фон. Дисперсия здесь математически ноль, но накопление
// сумм в double даёт крошечный минус (-3e-19), и sqrt от него - это NaN.
// Порог NaN не проходит ни одно сравнение и молча выключил бы детектор.
static void test_background_constant_trend_is_not_nan() {
  reset_background();
  for (uint16_t i = 0; i < DETECTOR_BG_SAMPLES; i++) {
    impurityDetector.currentTrend = 0.015f;
    detector_update_background();
  }
  const float threshold = detector_base_warning_threshold();
  check(!std::isnan(threshold), "ровный фон не должен давать NaN в пороге");
  check(std::fabs(threshold - DETECTOR_MIN_WARNING_TREND) < 1e-6f,
        "ровный фон 0.015 должен упереться в минимальный порог");
}

// (б6) Штатный медленный дрейф вверх (тело всегда ползёт) должен войти в порог,
// иначе детектор сработает на нормальном ходе перегона. Фон между +0.02 и +0.04:
// среднее 0.03 плюс 4 сигмы разброса (0.04) = 0.07.
static void test_background_includes_positive_drift() {
  reset_background();
  for (uint16_t i = 0; i < DETECTOR_BG_SAMPLES; i++) {
    impurityDetector.currentTrend = (i % 2 == 0) ? 0.02f : 0.04f;
    detector_update_background();
  }
  check(std::fabs(detector_base_warning_threshold() - 0.07f) < 0.002f,
        "штатный дрейф вверх должен подниматься в порог (ожидалось 0.07)");
}

// (б5) Неполное окно истории фон не набирает: наклон на 5 точках слишком шумный.
static void test_background_needs_full_window() {
  reset_background();
  impurityDetector.historySize = 29;
  for (uint16_t i = 0; i < DETECTOR_BG_SAMPLES; i++) {
    impurityDetector.currentTrend = 0.01f;
    detector_update_background();
  }
  check(detector_bg_count == 0, "неполное окно не должно попадать в замер фона");
}

// (в1) Одиночный выброс выше критического порога паузу не вызывает.
static void test_single_spike_does_not_confirm() {
  impurityDetector.criticalConfirm = 0;
  impurityDetector.currentTrend = 0.5f;   // выше criticalThreshold
  confirm_tick(true);
  check(impurityDetector.criticalConfirm < DETECTOR_CRITICAL_CONFIRM,
        "одиночный выброс не должен набрать подтверждение");
  impurityDetector.currentTrend = 0.01f;  // вернулось в норму
  confirm_tick(true);
  check(impurityDetector.criticalConfirm == 0,
        "возврат тренда в норму должен обнулить подтверждения");
}

// (в2) Устойчивое превышение подтверждается и даёт право на паузу.
static void test_sustained_excess_confirms() {
  impurityDetector.criticalConfirm = 0;
  impurityDetector.currentTrend = 0.5f;
  for (uint8_t i = 0; i < DETECTOR_CRITICAL_CONFIRM; i++) confirm_tick(true);
  check(impurityDetector.criticalConfirm >= DETECTOR_CRITICAL_CONFIRM,
        "устойчивое превышение должно подтвердиться");
}

// (в3) Подтверждения считаются по НОВЫМ точкам. Иначе за секунду набрались бы сотни:
// process_impurity_detector вызывается из loop() десятки раз в секунду.
static void test_confirm_counts_only_new_samples() {
  impurityDetector.criticalConfirm = 0;
  impurityDetector.currentTrend = 0.5f;
  for (int i = 0; i < 100; i++) confirm_tick(false);
  check(impurityDetector.criticalConfirm == 0,
        "без новой точки подтверждение накапливаться не должно");
}

// (в4) Короткая история критику не подтверждает.
static void test_confirm_requires_history() {
  impurityDetector.criticalConfirm = 0;
  impurityDetector.currentTrend = 0.5f;
  hasCriticalHistory = false;
  for (int i = 0; i < 10; i++) confirm_tick(true);
  hasCriticalHistory = true;
  check(impurityDetector.criticalConfirm == 0,
        "без минимальной истории подтверждение накапливаться не должно");
}

int main() {
  test_uniform_step();
  test_irregular_step();
  test_millis_wraparound();
  test_partial_window();
  test_short_history();
  test_background_calibration();
  test_background_clamped_low();
  test_background_clamped_high();
  test_background_negative_mean_does_not_lower_threshold();
  test_background_needs_full_window();
  test_background_includes_positive_drift();
  test_background_constant_trend_is_not_nan();
  test_single_spike_does_not_confirm();
  test_sustained_excess_confirms();
  test_confirm_counts_only_new_samples();
  test_confirm_requires_history();

  if (failures != 0) return 1;
  std::cout << "detector measurement rework behaviour checks passed\n";
  return 0;
}
'''


def _const_int(code: str, name: str):
    """Достаёт целочисленное значение константы из исходника."""
    match = re.search(rf"\b{name}\s*=\s*(\d+)", code)
    return int(match.group(1)) if match else None


def static_contracts(detector_source: str) -> list[str]:
    """Статические контракты переработки: что должно исчезнуть и что не должно раздвоиться."""
    errors: list[str] = []
    code = strip_cpp_comments(detector_source)

    # Плотность насадки детектору больше не нужна: её диапазон 60-100% двигал порог
    # на ±25%, а автоматические поправки дают разброс в разы.
    if "SamSetup.PackDens" in code:
        errors.append("детектор не должен читать SamSetup.PackDens: базовый порог измеряется")

    # Нерабочий фильтр выбросов: требовал 0.6-1.9 °C/мин при порогах 0.04-0.1,
    # то есть всегда был равен нулю и просто поднимал порог на 30%.
    for gone in ("consecutiveRises", "check_consecutive_rises", "isValidTrend"):
        if gone in code:
            errors.append(f"нерабочий фильтр выбросов должен быть удалён, найдено: {gone}")

    # Дисперсия считается одним способом - по инкрементальным суммам кольца.
    if "calculate_temperature_variance" in code:
        errors.append("дублирующий подсчёт дисперсии calculate_temperature_variance должен быть удалён")

    # Порог считается в одном месте: иначе правка формулы разводит реакцию и возврат.
    try:
        recovery = extract_function_body(code, "inline float detector_current_recovery_threshold()")
    except ValueError as exc:
        errors.append(str(exc))
        recovery = ""
    if "detector_warning_threshold()" not in recovery:
        errors.append("detector_current_recovery_threshold должен брать порог из detector_warning_threshold")
    if "get_adaptive_threshold" in recovery:
        errors.append("detector_current_recovery_threshold не должен пересчитывать формулу порога сам")

    try:
        process = extract_function_body(code, "void process_impurity_detector()")
    except ValueError as exc:
        errors.append(str(exc))
        process = ""
    if "detector_warning_threshold()" not in process:
        errors.append("process_impurity_detector должен брать порог из detector_warning_threshold")
    if "get_adaptive_threshold(" in process:
        errors.append("process_impurity_detector не должен звать get_adaptive_threshold напрямую")

    # get_adaptive_threshold вызывается ровно из одного места
    calls = code.count("get_adaptive_threshold(")
    if calls != 2:  # объявление функции + единственный вызов
        errors.append(f"get_adaptive_threshold должен вызываться из одного места, найдено вхождений: {calls}")


    # Время калибровки фона: слишком короткое поймает переходный процесс после смены
    # строки, слишком длинное оставит детектор на дефолтном пороге полстроки.
    bg_samples = _const_int(code, "DETECTOR_BG_SAMPLES")
    interval_ms = _const_int(code, "DETECTOR_SAMPLE_INTERVAL_MS")
    if bg_samples is None or interval_ms is None:
        errors.append("не найдены константы DETECTOR_BG_SAMPLES / DETECTOR_SAMPLE_INTERVAL_MS")
    else:
        calibration_min = bg_samples * interval_ms / 60000.0
        if not 2.0 <= calibration_min <= 10.0:
            errors.append(
                f"калибровка фона занимает {calibration_min:.1f} мин, ожидалось 2-10 мин"
            )

    # Подтверждение критической паузы: минимум две новые точки подряд, иначе одиночный
    # щелчок кванта датчика остановит отбор; больше пяти - реакция позже 20 секунд.
    confirm = _const_int(code, "DETECTOR_CRITICAL_CONFIRM")
    if confirm is None:
        errors.append("не найдена константа DETECTOR_CRITICAL_CONFIRM")
    elif not 2 <= confirm <= 5:
        errors.append(f"DETECTOR_CRITICAL_CONFIRM = {confirm}, ожидалось 2..5")

    return errors


def build_harness() -> str:
    detector_source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")

    trend_signature = "float calculate_temperature_trend()"
    trend = trend_signature + " {" + extract_function_body(detector_source, trend_signature) + "}"

    bg_signature = "void detector_update_background()"
    background = bg_signature + " {" + extract_function_body(detector_source, bg_signature) + "}"

    base_signature = "inline float detector_base_warning_threshold()"
    base = (
        "static float detector_base_warning_threshold() {"
        + extract_function_body(detector_source, base_signature)
        + "}"
    )

    confirm_block, _ = extract_braced_block_after(detector_source, CONFIRM_BLOCK_TOKEN)

    return (
        HARNESS_TEMPLATE.replace("@TREND_FUNCTION@", trend)
        .replace("@BACKGROUND_FUNCTION@", background)
        .replace("@BASE_THRESHOLD_FUNCTION@", base)
        .replace("@CONFIRM_BLOCK@", confirm_block)
    )


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-detector-measurement-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "detector_measurement_test.cpp"
        binary = temp / "detector_measurement_test"
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
    detector_source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")
    errors = static_contracts(detector_source)
    if errors:
        print("detector measurement rework smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    result = compile_and_run(harness)
    if result == 0:
        print("detector measurement rework static checks passed")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
