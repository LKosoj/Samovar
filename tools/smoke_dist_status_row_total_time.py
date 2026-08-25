#!/usr/bin/env python3
"""[T21-3 / Н4] get_distiller_status_text() (logic.h) должна показывать не
только "осталось" по текущей строке дистилляции, но и уже посчитанное "всего"
по строке - оно давно лежит готовым в get_dist_row_predicted_total_time()
(считается в updateTimePredictor(), distiller.h), но раньше в статус не
попадало.

Тест компилирует РЕАЛЬНОЕ тело get_distiller_status_text() (logic.h) через
extract_function_body в изолированном харнессе, замокав
dist_row_prediction_available() -> true, get_dist_remaining_time() -> 12.3,
get_dist_row_predicted_total_time() -> 45.6, и проверяет, что итоговая строка
содержит одновременно "12.3", "45.6" и разделитель " из ~". Откат правки
(возврат к "; Строка, осталось:12.3 мин" без общего времени строки) валит
assert по отсутствию "45.6"/" из ~".
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "String get_distiller_status_text()"

HARNESS_TEMPLATE = r'''
#include <cstdio>
#include <iostream>
#include <string>

struct String {
  std::string s;
  String() {}
  String(const char* value) : s(value) {}
  String(int value) : s(std::to_string(value)) {}
  // snprintf с "%.*f" - как Arduino String(float, decimals) - округляет до
  // заданного числа знаков. std::to_string(float) даёт полную (иногда "грязную",
  // из-за неточного float32) мантиссу и мог бы не содержать ожидаемую подстроку
  // (напр. 45.6f -> "45.599998" без std::to_string, но "45.6" с округлением).
  String(float value, int decimals) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%.*f", decimals, value);
    s = buf;
  }
  String& operator+=(const String& other) { s += other.s; return *this; }
  String operator+(const String& other) const { String r; r.s = s + other.s; return r; }
};
static String operator+(const char* left, const String& right) {
  String r; r.s = std::string(left) + right.s; return r;
}

static int ProgramNum = 0;
static int ProgramLen = 1;
struct SamSetupStruct { float DistTemp = 0.0f; };
static SamSetupStruct SamSetup;
static bool PowerOn = false;

static bool rowPredictionAvailableFixture = false;
static float rowRemainingFixture = 0.0f;
static float rowTotalFixture = 0.0f;
static bool processPredictionAvailableFixture = false;
static float processRemainingFixture = 0.0f;
static float processTotalFixture = 0.0f;

static bool dist_row_prediction_available() { return rowPredictionAvailableFixture; }
static float get_dist_remaining_time() { return rowRemainingFixture; }
// НЕ static: единственный вызов лежит внутри добавленного правкой T21-3 куска
// вклеенного тела ниже. Со static мутация (откат к "; Строка, осталось:...")
// убрала бы единственный вызов, и -Werror=unused-function завалил бы сборку
// раньше, чем дошло бы до содержательного assert-а по "45.6"/" из ~".
float get_dist_row_predicted_total_time() { return rowTotalFixture; }
static bool dist_process_prediction_available() { return processPredictionAvailableFixture; }
static float get_dist_process_remaining_time() { return processRemainingFixture; }
static float get_dist_predicted_total_time() { return processTotalFixture; }

@BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

int main() {
  ProgramNum = 0;
  ProgramLen = 1;
  SamSetup.DistTemp = 0.0f;
  PowerOn = true;
  rowPredictionAvailableFixture = true;
  rowRemainingFixture = 12.3f;
  rowTotalFixture = 45.6f;
  processPredictionAvailableFixture = false;

  String result = get_distiller_status_text();

  check(result.s.find("12.3") != std::string::npos,
        "статус строки должен содержать оставшееся время (12.3)");
  check(result.s.find("45.6") != std::string::npos,
        "статус строки должен содержать посчитанное общее время строки (45.6) из get_dist_row_predicted_total_time()");
  check(result.s.find(" из ~") != std::string::npos,
        "статус строки должен разделять \"осталось\" и \"всего\" через \" из ~\"");

  if (failures != 0) return 1;
  std::cout << "logic.h get_distiller_status_text row total-time checks passed\n";
  return 0;
}
'''


def build_harness(source: str) -> str:
    body = extract_function_body(source, SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@BODY@", "static String get_distiller_status_text() {" + body + "}"
    )


def main() -> int:
    source = (ROOT / "logic.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-dist-status-row-total-") as temp_dir:
        temp = Path(temp_dir)
        cpp_source = temp / "dist_status_row_total_time_test.cpp"
        binary = temp / "dist_status_row_total_time_test"
        cpp_source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp_source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
