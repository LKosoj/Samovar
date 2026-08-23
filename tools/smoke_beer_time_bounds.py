#!/usr/bin/env python3
"""[П33] Поле «время» строки программы пива обязано проверяться на диапазон -
так же, как соседнее поле «температура» - а не приниматься произвольным (вплоть
до ~3.4e38, предела float) значением.

До правки program_parse_beer_row() гонял токен времени через parse_finite_float()
(только "конечное число", без верхней границы), тогда как токен температуры уже
проверялся через parse_bounded_float(..., PROGRAM_TEMP_MIN, PROGRAM_TEMP_MAX, ...).
Значение вроде 1e38 благополучно проходило разбор и попадало в row.Time, дальше
портя экран (String(row.Time)) и расчёты (деление в beer_stage_elapsed_ms()/Time).

Тест компилирует РЕАЛЬНЫЙ program_parse_beer_row() (и его реальные помощники
program_parse_beer_device/program_validate_beer_row_semantics/program_count_char)
вместе с настоящим numeric_parse.h (через -I) и проверяет поведение на реальных
строках программы.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstring>
#include <climits>
#include <iostream>
#include <string>

#include "numeric_parse.h"

using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';

struct WProgram {
  ProgramType WType;
  float Temp;
  float Time;
  uint8_t capacity_num;
  float Speed;
  uint16_t Volume;
  uint16_t Power;
  uint8_t TempSensor;
};

struct ProgramParseSpec { const char* allowedTypes; };

static bool parse_program_type(const char* text, const char* allowedTypes, ProgramType& type) {
  if (!text || text[0] == '\0' || text[1] != '\0') return false;
  for (const char* p = allowedTypes; *p; p++) {
    if (*p == text[0]) { type = text[0]; return true; }
  }
  return false;
}

@CONST_TIME@

@PROGRAM_COUNT_CHAR@

@PROGRAM_PARSE_BEER_DEVICE@

@PROGRAM_VALIDATE_BEER_ROW_SEMANTICS@

@PROGRAM_PARSE_BEER_ROW@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static bool parse_row(const char* line, WProgram& row) {
  char buffer[256];
  std::strncpy(buffer, line, sizeof(buffer) - 1);
  buffer[sizeof(buffer) - 1] = '\0';
  ProgramParseSpec spec{"MPBCFWLA"};
  const char* errorMessage = nullptr;
  row = WProgram{};
  return program_parse_beer_row(buffer, std::strlen(buffer), (uint8_t)0, row, spec, errorMessage);
}

int main() {
  WProgram row{};

  // Разумное значение выдержки (мин) - должно пройти и сохраниться как есть.
  check(parse_row("P;65;90;0^0^0^0;0", row), "нормальная выдержка 90 мин должна пройти");
  check(row.Time == 90.0f, "row.Time должен получить именно введённое значение");

  // [П33] Ключевой случай бага: время ~1e38 (физически бессмысленно) обязано
  // отвергаться разбором, точно как отвергается такое же по масштабу Temp.
  check(!parse_row("P;65;1e38;0^0^0^0;0", row), "время 1e38 обязано отвергаться разбором (как и Temp)");

  // Верхняя граница включительно - PROGRAM_TIME_MAX ровно на потолке должна проходить.
  check(parse_row("P;65;1440;0^0^0^0;0", row), "время ровно на верхней границе (1440 мин) должно проходить");
  check(row.Time == 1440.0f, "row.Time должен сохранить граничное значение без искажений");

  // Чуть выше границы - обязано отвергаться.
  check(!parse_row("P;65;1440.01;0^0^0^0;0", row), "время чуть выше верхней границы обязано отвергаться");

  // Отрицательное время по-прежнему недопустимо (как и раньше).
  check(!parse_row("P;65;-5;0^0^0^0;0", row), "отрицательное время обязано отвергаться");

  if (failures != 0) return 1;
  std::cout << "beer program Time bounds checks passed\n";
  return 0;
}
'''


def build_harness(program_io: str) -> str:
    const_start = program_io.find("constexpr float PROGRAM_TEMP_MIN")
    const_end = program_io.find("constexpr float PROGRAM_TIME_MAX")
    const_end = program_io.find(";", const_end) + 1
    if const_start < 0 or const_end <= 0:
        raise ValueError("PROGRAM_TEMP_MIN..PROGRAM_TIME_MAX constants not found")
    const_block = program_io[const_start:const_end]

    count_char = extract_function_body(program_io, "inline size_t program_count_char")
    device = extract_function_body(program_io, "inline bool program_parse_beer_device")
    semantics = extract_function_body(program_io, "inline bool program_validate_beer_row_semantics")
    row_parser = extract_function_body(program_io, "inline bool program_parse_beer_row")

    harness = HARNESS_TEMPLATE
    harness = harness.replace("@CONST_TIME@", const_block)
    harness = harness.replace(
        "@PROGRAM_COUNT_CHAR@",
        "static size_t program_count_char(const char* text, char needle) {" + count_char + "}",
    )
    harness = harness.replace(
        "@PROGRAM_PARSE_BEER_DEVICE@",
        "static bool program_parse_beer_device(char* token, long& devType, long& speed, long& onTime, long& offTime) {"
        + device + "}",
    )
    harness = harness.replace(
        "@PROGRAM_VALIDATE_BEER_ROW_SEMANTICS@",
        "static bool program_validate_beer_row_semantics("
        "ProgramType type, float temp, float timeMin, long devType, long speed, "
        "long onTime, long offTime, long sensor, const char*& errorMessage) {"
        + semantics + "}",
    )
    harness = harness.replace(
        "@PROGRAM_PARSE_BEER_ROW@",
        "static bool program_parse_beer_row(char* line, size_t lineLen, uint8_t, WProgram& row, "
        "const ProgramParseSpec& spec, const char*& errorMessage) {"
        + row_parser + "}",
    )
    return harness


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-time-bounds-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_time_bounds_test.cpp"
        binary = temp / "beer_time_bounds_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(binary)],
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
    program_io = (ROOT / "program_io.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(program_io)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
