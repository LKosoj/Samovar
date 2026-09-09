#!/usr/bin/env python3
"""Поведенческая проверка детектора проскока примесей (impurity_detector.h).

Тест собирает РЕАЛЬНЫЕ тела функций сбора истории, регрессии тренда, замера
фона и адаптивного порога через extract_function_body и гоняет их на
синтетических рядах температуры, квантованных до шага DS18B20 (1/16 °C):

- ровная полка с шумом кванта: тренд около нуля, фон даёт порог у нижней границы;
- равномерный подъём 0.15 °C/мин: регрессия восстанавливает наклон;
- одиночный выброс в окне не поднимает тренд до критического;
- медленный подъём 0.03 °C/мин ВО ВРЕМЯ замера фона не «съедается» порогом:
  замер на подъёме отбрасывается, порог остаётся дефолтным;
- дедупликация чтений датчика по DSUpdateCounter;
- множители адаптивного порога.

Константы читаются из impurity_detector.h, а не дублируются в харнессе, поэтому
их мутация ловится этим тестом. Отдельно проверяется мутация: снятие защиты
«не мерить фон на подъёме» обязано валить проверку «подъём не съеден».
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
DETECTOR = ROOT / "impurity_detector.h"
SAMOVAR_H = ROOT / "Samovar.h"

FUNCTIONS = (
    "inline void detector_bg_restart()",
    "inline void detector_reset_sampling()",
    "inline void detector_reset_history()",
    "float detector_history_variance()",
    "void update_detector_history(float columnTemp, uint32_t sampleMillis)",
    "float calculate_temperature_trend()",
    "bool detector_sample_tick(float detectorTemp, uint32_t now)",
    "void detector_update_background()",
    "float get_adaptive_threshold(float baseThreshold, float variance, float volumePerHour, ProgramType processPhase)",
)


def extract_constants(source: str) -> str:
    consts = re.findall(r"^static const [^;]+;", source, flags=re.MULTILINE | re.DOTALL)
    if len(consts) < 20:
        raise ValueError("too few static const definitions found in impurity_detector.h")
    return "\n".join(consts)


HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstring>
#include <cmath>
#include <iostream>

using ProgramType = char;

@CONSTANTS@

struct ImpurityDetector {@STRUCT@};
ImpurityDetector impurityDetector;
volatile uint32_t DSUpdateCounter = 0;

static double detector_avg_sum = 0.0;
static uint16_t detector_avg_count = 0;
static uint32_t detector_last_ds_counter = 0;
static double detector_bg_sum = 0.0;
static double detector_bg_sumsq = 0.0;
static uint16_t detector_bg_count = 0;
static float detector_bg_threshold = 0.0f;

@FUNCTIONS@

static int failures = 0;
#define CHECK(cond, msg) do { if (!(cond)) { std::cout << "FAIL: " << msg << "\n"; failures++; } } while (0)

static float quantize(float value) {
  return std::round(value / DETECTOR_SENSOR_QUANT_C) * DETECTOR_SENSOR_QUANT_C;
}

static uint32_t lcg = 12345;
static float noise_quant() {
  lcg = lcg * 1664525u + 1013904223u;
  const uint32_t r = (lcg >> 16) % 4;
  return r == 0 ? -DETECTOR_SENSOR_QUANT_C : (r == 3 ? DETECTOR_SENSOR_QUANT_C : 0.0f);
}

// Прогон ряда: slope в °C/мин, points — число точек истории (по 4 чтения датчика
// раз в секунду на точку). Возвращает тренд после последней точки.
static float run_series(float base, float slope, int points, bool noisy, int outlierAt = -1) {
  uint32_t now = 1000;
  detector_reset_history();
  impurityDetector.lastSampleTime = now;
  for (int p = 0; p < points; p++) {
    for (int r = 0; r < 4; r++) {
      now += 1000;
      float t = base + slope * (now / 60000.0f);
      if (noisy) t += noise_quant();
      if (p == outlierAt) t += 0.5f;
      DSUpdateCounter++;
      detector_sample_tick(quantize(t), now);
    }
  }
  return impurityDetector.currentTrend;
}

// Замер фона на ряду с наклоном slope: крутим, пока порог не набран (или лимит точек).
static float run_background(float slope) {
  detector_reset_history();
  uint32_t now = 1000;
  impurityDetector.lastSampleTime = now;
  int points = 0;
  while (detector_bg_threshold == 0.0f && points < 400) {
    for (int r = 0; r < 4; r++) {
      now += 1000;
      DSUpdateCounter++;
      float t = 78.0f + slope * (now / 60000.0f) + noise_quant();
      if (detector_sample_tick(quantize(t), now)) detector_update_background();
    }
    points++;
  }
  return detector_bg_threshold;
}

int main() {
  // 1. Полка с шумом кванта: тренд около нуля
  float flat = run_series(78.0f, 0.0f, 30, true);
  CHECK(std::fabs(flat) < 0.02f, "flat noisy series trend must stay below 0.02 C/min, got " << flat);

  // 2. Подъём 0.15 °C/мин восстанавливается регрессией
  float ramp = run_series(78.0f, 0.15f, 30, true);
  CHECK(ramp > 0.12f && ramp < 0.18f, "ramp 0.15 C/min must be recovered within 20%, got " << ramp);

  // 3. Одиночный выброс +0.5 °C в конце окна не даёт критического тренда
  float outlier = run_series(78.0f, 0.0f, 30, false, 29);
  CHECK(outlier < DETECTOR_DEFAULT_WARNING_TREND * DETECTOR_CRITICAL_MULT,
        "single outlier must not reach critical trend, got " << outlier);

  // 4. Дедупликация: одно и то же чтение датчика попадает в среднее один раз
  detector_reset_history();
  impurityDetector.lastSampleTime = 5000;
  DSUpdateCounter++;
  for (int i = 0; i < 200; i++) detector_sample_tick(78.0f, 5000 + i);
  CHECK(detector_avg_count == 1, "same DS reading must be averaged once, count=" << detector_avg_count);

  // 5. Фон на полке: порог у нижней границы и заведомо ниже дефолта
  float bgFlat = run_background(0.0f);
  CHECK(bgFlat >= DETECTOR_MIN_WARNING_TREND && bgFlat <= DETECTOR_DEFAULT_WARNING_TREND,
        "flat background threshold must be within [min, default], got " << bgFlat);

  // 6. Медленный подъём 0.03 °C/мин во время замера фона: замер отбрасывается,
  //    порог остаётся ненабранным (действует дефолт), подъём не «съедается».
  float bgRamp = run_background(0.03f);
  CHECK(bgRamp == 0.0f, "background must be refused on a 0.03 C/min rise, got threshold " << bgRamp);

  // 7. Адаптивные множители порога
  const float base = 0.04f;
  CHECK(std::fabs(get_adaptive_threshold(base, 0.0f, 0.3f, 'B') - base) < 1e-6f, "body/no variance keeps base");
  CHECK(std::fabs(get_adaptive_threshold(base, 0.0f, 0.3f, 'T') - base * DETECTOR_TAILS_FACTOR) < 1e-6f, "tails factor");
  CHECK(std::fabs(get_adaptive_threshold(base, 0.0f, 0.6f, 'B') - base * DETECTOR_RATE_HIGH_FACTOR) < 1e-6f, "high rate factor");
  CHECK(std::fabs(get_adaptive_threshold(base, 0.0f, 0.15f, 'B') - base * DETECTOR_RATE_LOW_FACTOR) < 1e-6f, "low rate factor");
  CHECK(std::fabs(get_adaptive_threshold(base, DETECTOR_VAR_HIGH, 0.3f, 'B') - base * DETECTOR_VAR_MAX_FACTOR) < 1e-5f, "variance max factor");
  CHECK(std::fabs(get_adaptive_threshold(base, 5.0f, 0.3f, 'B') - base * DETECTOR_VAR_MAX_FACTOR) < 1e-5f, "variance factor is clamped");

  if (failures) return 1;
  std::cout << "impurity detector behaviour checks passed\n";
  return 0;
}
'''


def build_harness(detector_source: str, samovar_source: str) -> str:
    struct_body, _ = extract_braced_block_after(samovar_source, "struct ImpurityDetector {")
    functions = []
    for signature in FUNCTIONS:
        body = extract_function_body(detector_source, signature)
        functions.append(f"{signature} {{{body}}}")
    harness = HARNESS_TEMPLATE.replace("@CONSTANTS@", extract_constants(detector_source))
    harness = harness.replace("@STRUCT@", struct_body)
    harness = harness.replace("@FUNCTIONS@", "\n\n".join(functions))
    return harness


def compile_and_run(harness: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-impurity-detector-") as temp_dir:
        source = Path(temp_dir) / "impurity_detector.cpp"
        binary = Path(temp_dir) / "impurity_detector"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
             str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode:
            return compiled.returncode, compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def main() -> int:
    detector_source = DETECTOR.read_text(encoding="utf-8")
    samovar_source = SAMOVAR_H.read_text(encoding="utf-8")
    harness = build_harness(detector_source, samovar_source)

    code, output = compile_and_run(harness)
    if code:
        print("Impurity detector harness failed:")
        print(output)
        return 1
    print(output.strip())

    # Мутация: снять защиту «не мерить фон на подъёме» — проверка 6 обязана упасть.
    original = "if (mean > static_cast<double>(DETECTOR_BG_MAX_MEAN_TREND))"
    if harness.count(original) != 1:
        print("Mutation anchor not found exactly once in harness")
        return 1
    mutated = harness.replace(original, "if (false)")
    code, output = compile_and_run(mutated)
    if code == 0:
        print("Impurity detector background-on-rise mutation was NOT rejected:")
        print(output)
        return 1
    print("Impurity detector background-on-rise mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
