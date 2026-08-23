#!/usr/bin/env python3
"""Арифметическая проверка двух модулей без единого теста (пункт 66 WP19):

  - column_math.h::calculate_column_etalon() - расчёт "эталона" колонны
    (мощность захлёба/головы/тело/хвосты, число тарелок) для program.htm;
  - time_utils.h::format_uptime() - форматирование аптайма в ЧЧ:ММ:СС.

Оба извлекаются РЕАЛЬНЫМ кодом (extract_function_body/extract_braced_block_after)
и компилируются g++-харнессом - проверяется настоящая арифметика, а не
переписанная копия. Эталонные числа посчитаны независимо на Python по тому же
алгоритму (см. docstring внутри check_column_etalon).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

COLUMN_HARNESS_TEMPLATE = r'''
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
static void check_near(float actual, float expected, float tol, const char* what) {
  if (std::fabs(actual - expected) > tol) {
    std::cerr << "FAIL: " << what << " expected " << expected << " got " << actual << "\n";
    failures++;
  }
}
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    failures++;
  }
}

int main() {
  // Некорректная настройка (нулевой диаметр) обязана вернуть нулевую
  // структуру, а не мусорные/бесконечные значения.
  SamSetup.ColDiam = 0.0f;
  SamSetup.ColHeight = 1.0f;
  SamSetup.PackDens = 60;
  ColumnResults invalid = calculate_column_etalon(2);
  check(invalid.floodPowerW == 0.0f, "нулевой диаметр должен давать нулевую структуру (floodPowerW)");
  check(invalid.theoreticalPlates == 0.0f, "нулевой диаметр должен давать нулевую структуру (theoreticalPlates)");

  // Рабочий случай: 2" диаметр, 0.3 м насадки, плотность 60%, сахар (2).
  // Эталон посчитан независимо на Python тем же алгоритмом (без клампов).
  SamSetup.ColDiam = 2.0f;
  SamSetup.ColHeight = 0.3f;
  SamSetup.PackDens = 60;
  ColumnResults sugar = calculate_column_etalon(2);
  check_near(sugar.theoreticalPlates, 10.0f, 0.01f, "theoreticalPlates для 0.3 м/60% должно быть 10");
  check_near(sugar.floodPowerW, 2339.10f, 1.0f, "floodPowerW для эталонного случая");
  check_near(sugar.bodyFlowMaxMlH, 647.75f, 1.0f, "bodyFlowMaxMlH для эталонного случая (без клампа)");
  check_near(sugar.bodyFlowMinMlH, 416.87f, 1.0f, "bodyFlowMinMlH для эталонного случая (без клампа)");
  check(sugar.bodyFlowMaxMlH > sugar.bodyFlowMinMlH,
        "верхняя граница потока тела должна быть больше нижней (иначе диапазон отбора вывернут наизнанку)");
  check_near(sugar.tailsFlowMlH, 272.06f, 1.0f, "tailsFlowMlH для эталонного случая");

  // ВАЖНО: при плотности 60% множитель (packingDensity - 0.6) обнуляется,
  // и densityImpact/pDensityAdj-коэффициент можно испортить незаметно для
  // сценария выше. Проверяем реальный дефолт пользователей
  // (profile_setup_fields.h: PackDens = 80) и точку с другой стороны от 60%
  // (40%), чтобы (packingDensity - 0.6) была ненулевой в обе стороны.
  // Эталоны посчитаны независимо на Python тем же алгоритмом (без клампов):
  //   packingDensity = 0.8; hetpFactor = 1 - (0.8-0.6)*(0.3/0.4) = 0.85;
  //   theoreticalPlates = 30*10/(30*0.85) = 11.7647...
  //   pDensityAdj = 1.2 - (0.8-0.6)*0.5 = 1.1; floodPowerW = crossSectionMm2*1.15*1.1*pHeightAdj = 2144.18
  SamSetup.ColDiam = 2.0f;
  SamSetup.ColHeight = 0.3f;
  SamSetup.PackDens = 80;
  ColumnResults sugar80 = calculate_column_etalon(2);
  check_near(sugar80.theoreticalPlates, 11.76f, 0.01f, "theoreticalPlates для 0.3 м/80% (реальный дефолт) должно быть 11.76");
  check_near(sugar80.floodPowerW, 2144.18f, 1.0f, "floodPowerW для 80% (реальный дефолт)");
  check_near(sugar80.bodyFlowMaxMlH, 689.20f, 1.0f, "bodyFlowMaxMlH для 80% (реальный дефолт, без клампа)");
  check_near(sugar80.bodyFlowMinMlH, 445.67f, 1.0f, "bodyFlowMinMlH для 80% (реальный дефолт, без клампа)");
  check_near(sugar80.tailsFlowMlH, 289.46f, 1.0f, "tailsFlowMlH для 80% (реальный дефолт)");

  SamSetup.PackDens = 40;
  ColumnResults sugar40 = calculate_column_etalon(2);
  check_near(sugar40.theoreticalPlates, 8.70f, 0.01f, "theoreticalPlates для 0.3 м/40% должно быть 8.70");
  check_near(sugar40.floodPowerW, 2534.03f, 1.0f, "floodPowerW для 40% (другая сторона от 60%)");
  check_near(sugar40.bodyFlowMaxMlH, 616.39f, 1.0f, "bodyFlowMaxMlH для 40% (без клампа)");
  check_near(sugar40.bodyFlowMinMlH, 395.26f, 1.0f, "bodyFlowMinMlH для 40% (без клампа)");
  check_near(sugar40.tailsFlowMlH, 258.88f, 1.0f, "tailsFlowMlH для 40% (другая сторона от 60%)");

  // Сырьё меняет рабочий коэффициент: у фруктов (0) он ниже, чем у сахара (2) -
  // рабочая мощность должна быть меньше при прочих равных настройках колонны.
  ColumnResults fruit = calculate_column_etalon(0);
  check(fruit.workingPowerW < sugar.workingPowerW,
        "рабочая мощность для фруктов (pWorkFactor=0.48) должна быть меньше, чем для сахара (0.75)");

  if (failures != 0) return 1;
  std::cout << "column_math.h calculate_column_etalon() arithmetic checks passed\n";
  return 0;
}
'''

TIME_HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

class String : public std::string {
 public:
  String() = default;
  String(const char* s) : std::string(s) {}
  String(unsigned long v) : std::string(std::to_string(v)) {}
};

@FORMAT_UPTIME_BODY@

static int failures = 0;
static void check(const char* actual, const char* expected, const char* what) {
  if (std::string(actual) != std::string(expected)) {
    std::cerr << "FAIL: " << what << " expected '" << expected << "' got '" << actual << "'\n";
    failures++;
  }
}

int main() {
  check(format_uptime(0).c_str(), "00:00:00", "0 секунд");
  check(format_uptime(59).c_str(), "00:00:59", "59 секунд (только секунды)");
  check(format_uptime(3661).c_str(), "01:01:01", "1ч 1м 1с - все поля ненулевые");
  check(format_uptime(32703).c_str(), "09:05:03", "9ч 5м 3с - ведущие нули часов/минут/секунд");
  // Часы >= 10: ведущий ноль часов быть НЕ должен (в отличие от минут/секунд).
  check(format_uptime(90000).c_str(), "25:00:00", "25 часов - без ведущего нуля у часов");

  if (failures != 0) return 1;
  std::cout << "time_utils.h format_uptime() arithmetic checks passed\n";
  return 0;
}
'''


def build_column_harness() -> str:
    source = (ROOT / "column_math.h").read_text(encoding="utf-8")
    struct_body, _ = extract_braced_block_after(source, "struct ColumnResults {")
    fn_body = extract_function_body(source, "ColumnResults calculate_column_etalon(uint8_t rawMaterial)")
    harness = COLUMN_HARNESS_TEMPLATE.replace(
        "@COLUMN_RESULTS_STRUCT@", "struct ColumnResults {" + struct_body + "};"
    )
    harness = harness.replace(
        "@CALCULATE_COLUMN_ETALON_BODY@",
        "static ColumnResults calculate_column_etalon(uint8_t rawMaterial) {" + fn_body + "}",
    )
    return harness


def build_time_harness() -> str:
    source = (ROOT / "time_utils.h").read_text(encoding="utf-8")
    fn_body = extract_function_body(source, "inline String format_uptime(unsigned long seconds)")
    return TIME_HARNESS_TEMPLATE.replace(
        "@FORMAT_UPTIME_BODY@",
        "static String format_uptime(unsigned long seconds) {" + fn_body + "}",
    )


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-column-time-math-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / f"{label}.cpp"
        binary = temp / label
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            sys.stderr.write(f"{label} compile failed:\n")
            sys.stderr.write(compiled.stdout)
            sys.stderr.write(compiled.stderr)
            return compiled.returncode
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(ran.stdout)
        sys.stderr.write(ran.stderr)
        return ran.returncode


def main() -> int:
    try:
        column_harness = build_column_harness()
        time_harness = build_time_harness()
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    rc1 = compile_and_run(column_harness, "column_math_test")
    rc2 = compile_and_run(time_harness, "time_utils_test")
    return 1 if (rc1 or rc2) else 0


if __name__ == "__main__":
    sys.exit(main())
