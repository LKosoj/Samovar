#!/usr/bin/env python3
"""[БК п.9] Формат программы БК (PROGRAM_FORMAT_BK, program_io.h).

Тест компилирует и исполняет РЕАЛЬНЫЕ program_io.h/program_types.h/
string_utils.h/Samovar_ini.h проекта (g++, не текстовый grep) - тот же
подход, что и у tools/smoke_program_atomic.py. В отличие от него, харнесс
подключает настоящий Samovar_ini.h, чтобы границы 5-го поля БК
(BK_STEAM_SETPOINT_MIN/MAX = 30/100) бралось из реального источника, а не
дублировалось числом здесь - иначе тест не поймал бы реальный сдвиг
константы.

Формат строки БК - Тип;Порог;Ёмкость;Мощность;Тпара (program_io.h::
bk_program_parse_spec) - первые четыре поля идентичны DIST (program_parse_
threshold_fields), пятое (Тпара, уставка воды дефлегматора) - 0 (вручную)
либо строго BK_STEAM_SETPOINT_MIN..MAX включительно.
"""
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ARDUINO_STUB = r'''
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>

#define F(text) (text)

// [T29] program_io.h (program_commit/program_clear/program_serialize_rows) защищает
// program[]/ProgramLen спинлоком configMux - минимальная заглушка, семантика
// критической секции здесь не проверяется (см. tools/smoke_lock_order.py).
using portMUX_TYPE = int;
static portMUX_TYPE configMux = 0;
#define portENTER_CRITICAL(mux) do { (void)(mux); } while (0)
#define portEXIT_CRITICAL(mux) do { (void)(mux); } while (0)

class Print {
 public:
  virtual ~Print() {}
  virtual size_t write(uint8_t value) = 0;
  virtual size_t write(const uint8_t* buffer, size_t size) = 0;
};

// string_utils.h (2026-08) зовёт Serial.println(F(...)) при нехватке памяти в
// JsonStringPrint - минимальная заглушка, вывод в этих тестах не проверяется.
class String;
struct FakeSerial {
  void println(const char*) {}
};
static FakeSerial Serial;

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(char value) : value_(1, value) {}
  String(unsigned char value) : value_(std::to_string(value)) {}
  String(unsigned short value) : value_(std::to_string(value)) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  String(unsigned long value) : value_(std::to_string(value)) {}
  String(signed char value) : value_(std::to_string(value)) {}
  String(short value) : value_(std::to_string(value)) {}
  String(int value) : value_(std::to_string(value)) {}
  String(long value) : value_(std::to_string(value)) {}
  String(float value) : value_(format_float(value)) {}
  String(double value) : value_(format_float(value)) {}

  size_t length() const { return value_.length(); }
  const char* c_str() const { return value_.c_str(); }
  char charAt(size_t index) const { return value_.at(index); }
  void reserve(size_t size) { value_.reserve(size); }

  bool concat(char c) { value_ += c; return true; }
  bool concat(const char* s, size_t len) { value_.append(s, len); return true; }

  String& operator+=(const String& other) {
    value_ += other.value_;
    return *this;
  }

  friend String operator+(String left, const String& right) {
    left += right;
    return left;
  }

 private:
  static std::string format_float(double value) {
    char buffer[48] = {0};
    std::snprintf(buffer, sizeof(buffer), "%.2f", value);
    return buffer;
  }

  std::string value_;
};
'''

HARNESS = r'''
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>

#include "Arduino.h"

#define __SAMOVAR_H_
#define CAPACITY_NUM 10

// [Б7.2] Без этого define ветвь проверки первой строки в
// prepare_program_for_mode() (program_io.h) вырезается препроцессором.
#define SAMOVAR_USE_POWER

#include "program_types.h"
#include "Samovar_ini.h"  // [БК п.9] реальные BK_STEAM_SETPOINT_MIN/MAX

struct WProgram {
  ProgramType WType;
  uint16_t Volume;
  float Speed;
  uint8_t capacity_num;
  float Temp;
  float Power;
  uint8_t TempSensor;
  float Time;
};

WProgram program[PROGRAM_MAX];
volatile uint8_t ProgramLen = 0;

enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE,
};

#include "string_utils.h"
#include "program_io.h"

namespace {

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

void test_valid_row() {
  ProgramDraft draft{};
  ProgramParseResult result = program_parse_lines(String("T;93;1;0;40\n"), bk_program_parse_spec(), draft);
  check(result.ok(), "valid BK row was rejected");
  check(draft.len == 1, "valid BK row was rejected");
  check(draft.rows[0].WType == 'T', "valid BK row was rejected");
  check(draft.rows[0].Speed == 93.0f, "valid BK row was rejected");
  check(draft.rows[0].capacity_num == 1, "valid BK row was rejected");
  check(draft.rows[0].Power == 0.0f, "valid BK row was rejected");
  check(draft.rows[0].Temp == 40.0f, "valid BK row was rejected");
}

void test_temp_zero_is_manual() {
  ProgramDraft draft{};
  ProgramParseResult result = program_parse_lines(String("T;93;1;0;0\n"), bk_program_parse_spec(), draft);
  check(result.ok(), "BK row with Temp=0 (manual water) was rejected");
  check(draft.rows[0].Temp == 0.0f, "BK row with Temp=0 (manual water) was rejected");
}

void test_bounds_inclusive() {
  for (const char* text : {"T;93;1;0;30\n", "T;93;1;0;100\n"}) {
    ProgramDraft draft{};
    ProgramParseResult result = program_parse_lines(String(text), bk_program_parse_spec(), draft);
    check(result.ok(), "BK row with Temp==30/100 (inclusive bound) was rejected");
  }
}

void test_below_lower_bound_rejected() {
  ProgramDraft draft{};
  ProgramParseResult result = program_parse_lines(String("T;93;1;0;29.9\n"), bk_program_parse_spec(), draft);
  check(!result.ok(), "BK row with Temp=29.9 (below lower bound) was accepted");
  check(result.errorMessage != nullptr &&
            std::string(result.errorMessage) == "Ошибка программы: Т пара: 0 или 30..100",
        "BK row error message mismatch for out-of-range Temp");
}

void test_above_upper_bound_rejected() {
  ProgramDraft draft{};
  ProgramParseResult result = program_parse_lines(String("T;93;1;0;100.1\n"), bk_program_parse_spec(), draft);
  check(!result.ok(), "BK row with Temp=100.1 (above upper bound) was accepted");
  check(result.errorMessage != nullptr &&
            std::string(result.errorMessage) == "Ошибка программы: Т пара: 0 или 30..100",
        "BK row error message mismatch for out-of-range Temp");
}

void test_extra_token_rejected() {
  ProgramDraft draft{};
  ProgramParseResult result = program_parse_lines(String("T;93;1;0;40;9\n"), bk_program_parse_spec(), draft);
  check(!result.ok(), "BK spec accepted a 6-field row (extra token)");
  check(result.error == PROGRAM_PARSE_INVALID_ROW, "BK spec accepted a 6-field row (extra token)");
}

void test_four_fields_rejected_for_bk() {
  ProgramDraft draft{};
  ProgramParseResult result = program_parse_lines(String("T;93;1;0\n"), bk_program_parse_spec(), draft);
  check(!result.ok(), "BK spec accepted a 4-field DIST-style row");
}

void test_dist_still_rejects_five_fields() {
  ProgramDraft draft{};
  ProgramParseResult result = program_parse_lines(String("T;93;1;0;40\n"), dist_program_parse_spec(), draft);
  check(!result.ok(), "DIST spec accepted a 5-field BK-style row");
}

void test_type_dependent_narrowing_reused() {
  ProgramDraft bad{};
  ProgramParseResult badResult = program_parse_lines(String("S;1;0;0;0\n"), bk_program_parse_spec(), bad);
  check(!badResult.ok(), "BK type-dependent narrowing (S/R) not enforced");

  ProgramDraft good{};
  ProgramParseResult goodResult = program_parse_lines(String("S;0.5;0;0;0\n"), bk_program_parse_spec(), good);
  check(goodResult.ok(), "BK type-dependent narrowing (S/R) not enforced");
}

void test_round_trip() {
  ProgramParseResult applied = program_parse_lines(
      String("T;93;1;0;40\nA;80;2;0;70\n"), bk_program_parse_spec());
  check(applied.ok(), "BK program round-trip mismatch");
  check(ProgramLen == 2, "BK program round-trip mismatch");

  String serialized = program_serialize_rows(0, PROGRAM_END, program_append_bk_row);
  ProgramDraft reparsed{};
  ProgramParseResult result = program_parse_lines(serialized, bk_program_parse_spec(), reparsed);
  check(result.ok(), "BK program round-trip mismatch");
  check(reparsed.len == 2, "BK program round-trip mismatch");
  check(reparsed.rows[0].WType == 'T' && reparsed.rows[1].WType == 'A', "BK program round-trip mismatch");
  check(reparsed.rows[0].Temp == 40.0f && reparsed.rows[1].Temp == 70.0f, "BK program round-trip mismatch");
  check(reparsed.rows[0].Speed == 93.0f && reparsed.rows[1].Speed == 80.0f, "BK program round-trip mismatch");
  check(reparsed.rows[0].capacity_num == 1 && reparsed.rows[1].capacity_num == 2, "BK program round-trip mismatch");
}

void test_sensorinit_default_parses() {
  // Буквально литерал из sensorinit.h::prepare_default_program_for_mode
  // (case SAMOVAR_BK_MODE) - синхронизацию текста держит
  // tools/smoke_default_program_power_threshold.py, здесь проверяется, что
  // ЭТОТ текст реально разбирается через prepare_program_for_mode().
  ProgramDraft draft{};
  ProgramParseResult result = prepare_program_for_mode(SAMOVAR_BK_MODE, String("T;93;1;0;0\n"), draft);
  check(result.ok(), "sensorinit.h BK default program was rejected");
  check(draft.len == 1, "sensorinit.h BK default program was rejected");
}

void test_mode_mapping() {
  check(program_format_for_mode(SAMOVAR_BK_MODE) == PROGRAM_FORMAT_BK,
        "BK/LUA mode-to-format mapping mismatch");
  check(program_format_for_mode(SAMOVAR_LUA_MODE) == PROGRAM_FORMAT_RECT,
        "BK/LUA mode-to-format mapping mismatch");
}

}  // namespace

int main() {
  test_valid_row();
  test_temp_zero_is_manual();
  test_bounds_inclusive();
  test_below_lower_bound_rejected();
  test_above_upper_bound_rejected();
  test_extra_token_rejected();
  test_four_fields_rejected_for_bk();
  test_dist_still_rejects_five_fields();
  test_type_dependent_narrowing_reused();
  test_round_trip();
  test_sensorinit_default_parses();
  test_mode_mapping();

  if (failures != 0) return 1;
  std::cout << "BK program row parse/serialize checks passed\n";
  return 0;
}
'''


def compile_and_run(temp: Path, program_io_text: str, label: str) -> int:
    (temp / "program_io.h").write_text(program_io_text, encoding="utf-8")
    binary = temp / f"bk_program_rows_{label}"
    compile_result = subprocess.run(
        [
            "g++",
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(temp),
            "-I",
            str(ROOT),
            str(temp / "bk_program_rows_test.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if compile_result.returncode != 0:
        sys.stderr.write(f"FAIL: {label} did not compile\n")
        sys.stderr.write(compile_result.stdout)
        sys.stderr.write(compile_result.stderr)
        return -1

    run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
    # Вывод мутантов не пробрасываем: их FAIL ожидаем, в зелёном логе он только
    # сбивает с толку (как в smoke_program_atomic.py).
    if label == "base":
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
    return run_result.returncode


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-bk-program-rows-") as temp_dir:
        temp = Path(temp_dir)
        (temp / "Arduino.h").write_text(ARDUINO_STUB, encoding="utf-8")
        (temp / "bk_program_rows_test.cpp").write_text(HARNESS, encoding="utf-8")

        base_program_io = (ROOT / "program_io.h").read_text(encoding="utf-8")
        rc = compile_and_run(temp, base_program_io, "base")
        if rc != 0:
            return 1 if rc < 0 else rc

        # Мутация A: убрать нижнюю границу BK_STEAM_SETPOINT_MIN - сценарий
        # "29.9 отбит" должен перестать проходить (мутант вернёт 0, если не так).
        lower_bound_needle = "(temp == 0.0f || temp >= BK_STEAM_SETPOINT_MIN)"
        assert lower_bound_needle in base_program_io
        mutated_lower = base_program_io.replace(
            lower_bound_needle, "(temp == 0.0f || true)", 1
        )
        rc = compile_and_run(temp, mutated_lower, "mutation_lower")
        if rc < 0:
            return 1
        if rc == 0:
            sys.stderr.write("FAIL: lower-bound mutation was not caught\n")
            return 1
        print("Lower-bound mutation was rejected as expected")

        # Мутация B: убрать верхнюю границу BK_STEAM_SETPOINT_MAX - сценарий
        # "100.1 отбит" должен перестать проходить.
        upper_bound_needle = "parse_bounded_float(tokTemp, 0.0f, BK_STEAM_SETPOINT_MAX, temp)"
        assert upper_bound_needle in base_program_io
        mutated_upper = base_program_io.replace(
            upper_bound_needle, "parse_bounded_float(tokTemp, 0.0f, 1e6f, temp)", 1
        )
        rc = compile_and_run(temp, mutated_upper, "mutation_upper")
        if rc < 0:
            return 1
        if rc == 0:
            sys.stderr.write("FAIL: upper-bound mutation was not caught\n")
            return 1
        print("Upper-bound mutation was rejected as expected")

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
