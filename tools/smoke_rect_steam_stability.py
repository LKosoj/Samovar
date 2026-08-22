#!/usr/bin/env python3
"""Поведенческая проверка скользящей стабильности пара."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

def telemetry_contract_ok(samovar_source: str, index_source: str) -> bool:
    firmware_tokens = (
        "snapshot.detectorRecoveryThreshold =",
        "detector_current_recovery_threshold();",
        "snapshot.detectorRecoveryReady = detector_trend_settled();",
        '"DetectorRecoveryThreshold"',
        '"DetectorRecoveryReady"',
    )
    ui_tokens = (
        "myObj.DetectorRecoveryThreshold.toFixed(4)",
        "myObj.DetectorRecoveryReady ? 'условие выполнено' : 'ожидание'",
        "восстановление тренда",
    )
    return all(token in samovar_source for token in firmware_tokens) and all(
        token in index_source for token in ui_tokens
    )

def stability_gate_ok(detector_source: str) -> bool:
    """Гейт 10-минутной стабилизации первой строки тела работает по ВЫБРАННОМУ датчику.

    Раньше он стоял под условием !usePipeSensor: при уходе контроля на царгу
    (Т куба >= 92.5) защита первой строки тела после голов молча отключалась.
    is_steam_stable() считает диапазон и дисперсию по истории детектора, а история
    ведётся по detectorTemp, поэтому проверка применима к обоим датчикам и параметра
    не принимает — передать "не тот" датчик больше нельзя по сигнатуре.
    """
    try:
        body = extract_function_body(detector_source, "void process_impurity_detector()")
    except ValueError:
        return False
    gate = "if (is_first_body_program_after_heads(currentProgram, currentType)) {"
    if gate not in body:
        return False
    if "usePipeSensor && is_first_body_program_after_heads" in body:
        return False
    return "if (!is_steam_stable()) {" in body


def stability_thresholds_ok(detector_source: str) -> bool:
    """Пороги стабилизации выражены через квант датчика, а не абстрактными долями градуса.

    Прежние 0.1 °C размаха и дисперсия 0.000625 (СКО 0.4 кванта) лежали НИЖЕ шума
    квантования DS18B20: температура, дышащая между двумя соседними квантами, давала
    дисперсию 0.000977, гейт не проходил никогда, и детектор на первой строке тела
    молча не включался.
    """
    span = "static const float DETECTOR_STEAM_STABLE_SPAN = DETECTOR_SENSOR_QUANT_C * 3.0f;"
    variance = (
        "static const float DETECTOR_STEAM_STABLE_VARIANCE =\n"
        "    DETECTOR_SENSOR_QUANT_C * DETECTOR_SENSOR_QUANT_C;"
    )
    quant = "static const float DETECTOR_SENSOR_QUANT_C = 0.0625f;"
    return all(token in detector_source for token in (span, variance, quant))


HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>

struct Detector {
  float tempHistory[30];
  uint32_t sampleTime[30];
  uint8_t historyIndex;
  uint8_t historySize;
  double historySum;
  double historySumSquares;
  float historyMin;
  float historyMax;
  float tempVariance;
};

static Detector impurityDetector = {};
static uint32_t detector_steam_stable_since = 0;
enum DetectorSteamStabilityReason : uint8_t {
  DETECTOR_STEAM_FILLING = 0,
  DETECTOR_STEAM_RANGE_HIGH,
  DETECTOR_STEAM_VARIANCE_HIGH,
  DETECTOR_STEAM_HOLDING,
  DETECTOR_STEAM_READY,
};
static DetectorSteamStabilityReason detector_steam_stability_reason =
    DETECTOR_STEAM_FILLING;
static float detector_steam_stability_span = 0.0f;
static float detector_steam_stability_variance = 0.0f;
static const float DETECTOR_SENSOR_QUANT_C = 0.0625f;
static const float DETECTOR_STEAM_STABLE_SPAN = DETECTOR_SENSOR_QUANT_C * 3.0f;
static const float DETECTOR_STEAM_STABLE_VARIANCE =
    DETECTOR_SENSOR_QUANT_C * DETECTOR_SENSOR_QUANT_C;
static const uint32_t DETECTOR_STEAM_STABLE_MS = 600000UL;
static uint32_t fakeNow = 1000;
static uint32_t millis() { return fakeNow; }

@VARIANCE_FUNCTION@
@UPDATE_FUNCTION@
@FUNCTION@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void load(const float* values, uint8_t count) {
  impurityDetector.historySize = count;
  impurityDetector.historyIndex = count % 30;
  impurityDetector.historySum = 0.0f;
  impurityDetector.historySumSquares = 0.0f;
  impurityDetector.historyMin = count > 0 ? values[0] : 0.0f;
  impurityDetector.historyMax = impurityDetector.historyMin;
  for (uint8_t i = 0; i < count; i++) {
    impurityDetector.tempHistory[i] = values[i];
    impurityDetector.historySum += values[i];
    impurityDetector.historySumSquares += values[i] * values[i];
    if (values[i] < impurityDetector.historyMin) impurityDetector.historyMin = values[i];
    if (values[i] > impurityDetector.historyMax) impurityDetector.historyMax = values[i];
  }
}

int main() {
  for (uint8_t i = 0; i < 30; i++) update_detector_history(77.0f + i * 0.01f, i * 4000U);
  check(impurityDetector.historySize == 30, "кольцо должно заполниться 30 точками");
  check(std::fabs(impurityDetector.historyMin - 77.0f) < 0.0001f,
        "кольцо должно хранить минимум");
  check(std::fabs(impurityDetector.historyMax - 77.29f) < 0.0001f,
        "кольцо должно хранить максимум");
  check(std::fabs(impurityDetector.historySum - 2314.35f) < 0.01f,
        "кольцо должно поддерживать сумму");
  check(std::fabs(impurityDetector.historySumSquares - 178540.7555f) < 0.1f,
        "кольцо должно поддерживать сумму квадратов");
  update_detector_history(78.0f, 30U * 4000U);
  check(std::fabs(impurityDetector.historyMin - 77.01f) < 0.0001f,
        "перезапись старейшего минимума должна обновить минимум");
  check(std::fabs(impurityDetector.historyMax - 78.0f) < 0.0001f,
        "перезапись должна обновить максимум");
  check(std::fabs(impurityDetector.historySum - 2315.35f) < 0.01f,
        "перезапись должна вычесть старое значение из суммы");
  check(std::fabs(impurityDetector.historySumSquares - 178695.7555f) < 0.1f,
        "перезапись должна вычесть старый квадрат");

  float stable[30];
  for (uint8_t i = 0; i < 30; i++) stable[i] = 78.00f + (i % 3) * 0.01f;
  load(stable, 29);
  check(!is_steam_stable(), "29 точек недостаточно для полного окна");
  check(detector_steam_stability_reason == DETECTOR_STEAM_FILLING,
        "29 точек должны сообщать FILLING");
  load(stable, 30);
  check(!is_steam_stable(), "первое стабильное окно только запускает выдержку");
  check(detector_steam_stability_reason == DETECTOR_STEAM_HOLDING,
        "стабильное окно должно сообщать причину HOLDING");
  fakeNow += DETECTOR_STEAM_STABLE_MS - 1;
  check(!is_steam_stable(), "599.999 секунд недостаточно");
  fakeNow += 1;
  check(is_steam_stable(), "600 секунд стабильного окна должны дать READY");

  float rangeHigh[30];
  for (uint8_t i = 0; i < 30; i++) rangeHigh[i] = 78.00f + (i % 3) * 0.01f;
  rangeHigh[17] = 78.25f; // размах 0.25 > 3 квантов (0.1875)
  load(rangeHigh, 30);
  check(!is_steam_stable(), "широкий диапазон должен сбрасывать стабильность");
  check(detector_steam_stability_reason == DETECTOR_STEAM_RANGE_HIGH,
        "телеметрия должна объяснять превышенный диапазон");
  check(detector_steam_stable_since == 0, "выброс должен сбросить непрерывную выдержку");

  float varianceHigh[30];
  for (uint8_t i = 0; i < 30; i++) varianceHigh[i] = i < 15 ? 78.00f : 78.15f;
  load(varianceHigh, 30);
  check(!is_steam_stable(), "шумное окно должно отклоняться по дисперсии");
  check(detector_steam_stability_reason == DETECTOR_STEAM_VARIANCE_HIGH,
        "телеметрия должна объяснять высокую дисперсию");

  float varianceEdge[30];
  // разброс ровно в один квант вокруг среднего: дисперсия 0.000977 - именно тот случай,
  // на котором старый порог 0.000625 отклонял стабильный пар навсегда
  for (uint8_t i = 0; i < 30; i++) varianceEdge[i] = i < 15 ? 78.00f : 78.0625f;
  load(varianceEdge, 30);
  detector_steam_stable_since = 0;
  check(!is_steam_stable(), "дыхание в один квант только запускает выдержку");
  check(detector_steam_stability_reason == DETECTOR_STEAM_HOLDING,
        "дыхание в один квант не должно отклоняться как шум");

  // На четырёх точках дисперсия - не оценка шума, а случайность: адаптивный порог
  // не должен на неё реагировать, пока окно не набрало минимум пять замеров.
  float tiny[5] = {78.0f, 78.5f, 79.0f, 78.2f, 78.9f};
  load(tiny, 4);
  check(detector_history_variance() == 0.0f,
        "меньше 5 точек: дисперсия должна быть нулевой");
  // На неполном окне дисперсия считается по фактическому числу точек. Делить на 30
  // нельзя: дисперсия завысится в разы и адаптивный порог задерётся на старте строки.
  load(tiny, 5);
  check(std::fabs(detector_history_variance() - 0.1496f) < 0.0005f,
        "на пяти точках дисперсия должна считаться по этим пяти точкам (0.1496)");

  // Инкрементальные суммы копят ошибку округления, и разность может уйти в минус.
  // Отрицательная дисперсия ушла бы и в телеметрию, и в адаптивный порог, снизив его
  // ниже базового - ровно там, где детектор должен становиться осторожнее.
  float flat[30];
  for (uint8_t i = 0; i < 30; i++) flat[i] = 78.0f;
  load(flat, 30);
  impurityDetector.historySumSquares -= 1e-9;  // имитация накопленной ошибки
  check(detector_history_variance() >= 0.0f,
        "дисперсия не должна становиться отрицательной из-за ошибки округления");

  impurityDetector.historySize = 4;
  check(!is_steam_stable(), "неполное окно не должно считаться стабильным");
  check(detector_steam_stability_reason == DETECTOR_STEAM_FILLING,
        "неполное окно должно сообщать FILLING");

  load(stable, 30);
  fakeNow = UINT32_MAX - 300000U;
  check(!is_steam_stable(), "выдержка до переполнения должна стартовать");
  fakeNow += DETECTOR_STEAM_STABLE_MS - 1U;
  check(!is_steam_stable(), "переполнение millis не должно сокращать выдержку");
  fakeNow += 1U;
  check(is_steam_stable(), "выдержка должна завершиться после wraparound");

  if (failures != 0) return 1;
  std::cout << "rectification steam stability window passed\n";
  return 0;
}
'''


def main() -> int:
    source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")
    samovar_source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    index_source = (ROOT / "data_raw" / "index.htm").read_text(encoding="utf-8")
    if not telemetry_contract_ok(samovar_source, index_source):
        print("FAIL: неполный telemetry-контракт восстановления детектора", file=sys.stderr)
        return 1
    telemetry_mutants = (
        (
            samovar_source.replace(
                "detector_current_recovery_threshold();", "0.0f;", 1
            ),
            index_source,
        ),
        (
            samovar_source.replace('"DetectorRecoveryReady"', '"DetectorReady"', 1),
            index_source,
        ),
        (
            samovar_source,
            index_source.replace(
                "myObj.DetectorRecoveryReady ? 'условие выполнено' : 'ожидание'",
                "'неизвестно'",
                1,
            ),
        ),
    )
    if any(telemetry_contract_ok(*mutant) for mutant in telemetry_mutants):
        print("FAIL: мутация recovery-телеметрии пережила контракт", file=sys.stderr)
        return 1
    if not stability_gate_ok(source):
        print(
            "FAIL: гейт стабилизации первой строки тела должен работать по выбранному датчику",
            file=sys.stderr,
        )
        return 1
    gate_mutants = (
        source.replace(
            "if (is_first_body_program_after_heads(currentProgram, currentType)) {",
            "if (!usePipeSensor && is_first_body_program_after_heads(currentProgram, currentType)) {",
            1,
        ),
        source.replace("if (!is_steam_stable()) {", "if (false) {", 1),
    )
    if any(stability_gate_ok(mutant) for mutant in gate_mutants):
        print("FAIL: мутация гейта стабилизации пережила контракт", file=sys.stderr)
        return 1
    if not stability_thresholds_ok(source):
        print(
            "FAIL: пороги стабилизации должны считаться от кванта датчика",
            file=sys.stderr,
        )
        return 1
    threshold_mutants = (
        source.replace(
            "static const float DETECTOR_STEAM_STABLE_SPAN = DETECTOR_SENSOR_QUANT_C * 3.0f;",
            "static const float DETECTOR_STEAM_STABLE_SPAN = 0.1f;",
            1,
        ),
        source.replace(
            "static const float DETECTOR_STEAM_STABLE_VARIANCE =\n"
            "    DETECTOR_SENSOR_QUANT_C * DETECTOR_SENSOR_QUANT_C;",
            "static const float DETECTOR_STEAM_STABLE_VARIANCE = 0.000625f;",
            1,
        ),
    )
    if any(stability_thresholds_ok(mutant) for mutant in threshold_mutants):
        print("FAIL: мутация порогов стабилизации пережила контракт", file=sys.stderr)
        return 1
    body = extract_function_body(source, "bool is_steam_stable()")
    function = "bool is_steam_stable() {" + body + "}"
    update_body = extract_function_body(
        source, "void update_detector_history(float columnTemp, uint32_t sampleMillis)"
    )
    update_function = (
        "void update_detector_history(float columnTemp, uint32_t sampleMillis) {"
        + update_body
        + "}"
    )
    variance_body = extract_function_body(source, "float detector_history_variance()")
    variance_function = "float detector_history_variance() {" + variance_body + "}"
    harness = (
        HARNESS.replace("@VARIANCE_FUNCTION@", variance_function)
        .replace("@UPDATE_FUNCTION@", update_function)
        .replace("@FUNCTION@", function)
    )
    with tempfile.TemporaryDirectory(prefix="samovar-steam-stability-") as temp_dir:
        temp = Path(temp_dir)
        def compile_and_run(name: str, text: str) -> subprocess.CompletedProcess[str]:
            source_path = temp / f"{name}.cpp"
            binary_path = temp / name
            source_path.write_text(text, encoding="utf-8")
            result = subprocess.run(
                [
                    "g++",
                    "-std=c++11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(source_path),
                    "-o",
                    str(binary_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return result
            return subprocess.run(
                [str(binary_path)], capture_output=True, text=True, check=False
            )

        result = compile_and_run("steam_stability", harness)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode != 0:
            return result.returncode

        mutant = harness.replace(
            "detector_steam_stable_since = 0;\n"
            "    detector_steam_stability_reason = DETECTOR_STEAM_RANGE_HIGH;",
            "detector_steam_stability_reason = DETECTOR_STEAM_RANGE_HIGH;",
            1,
        )
        if mutant == harness:
            print("FAIL: не удалось построить мутацию сброса стабильности", file=sys.stderr)
            return 1
        if compile_and_run("steam_stability_mutant", mutant).returncode == 0:
            print("FAIL: мутация сброса стабильности пережила тест", file=sys.stderr)
            return 1
        count_mutant = harness.replace("if (count < 30)", "if (count < 29)", 1)
        if count_mutant == harness:
            print("FAIL: не удалось построить мутацию полного окна", file=sys.stderr)
            return 1
        if compile_and_run("steam_stability_count_mutant", count_mutant).returncode == 0:
            print("FAIL: мутация порога заполнения пережила тест", file=sys.stderr)
            return 1
        aggregate_mutant = harness.replace(
            "impurityDetector.historySumSquares += columnTemp * columnTemp;", "", 1
        )
        if aggregate_mutant == harness:
            print("FAIL: не удалось построить мутацию агрегатов кольца", file=sys.stderr)
            return 1
        if compile_and_run("steam_stability_aggregate_mutant", aggregate_mutant).returncode == 0:
            print("FAIL: мутация агрегатов кольца пережила тест", file=sys.stderr)
            return 1
        wrap_mutant = harness.replace(
            "if (now - detector_steam_stable_since < DETECTOR_STEAM_STABLE_MS)",
            "if (now >= detector_steam_stable_since && "
            "now - detector_steam_stable_since < DETECTOR_STEAM_STABLE_MS)",
            1,
        )
        if wrap_mutant == harness:
            print("FAIL: не удалось построить мутацию wraparound выдержки", file=sys.stderr)
            return 1
        if compile_and_run("steam_stability_wrap_mutant", wrap_mutant).returncode == 0:
            print("FAIL: мутация wraparound выдержки пережила тест", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
