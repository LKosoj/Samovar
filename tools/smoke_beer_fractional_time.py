#!/usr/bin/env python3
"""Поведенческая проверка П2 п.12: сериализация Time строки пива дробная.

Раньше program_append_beer_row приводил row.Time к (int) перед сериализацией -
дробная часть выдержки (например, "12.5" минуты) терялась после
сохранения/перезагрузки программы (Time round-trip: 12.5 -> "12" -> 12.0).
Тест компилирует РЕАЛЬНЫЕ program_io.h/program_types.h/string_utils.h проекта
(как smoke_program_atomic.py) и гоняет полный цикл parse -> serialize -> parse,
проверяя фактическое значение Time после раунд-трипа, а не факт наличия строк
в исходнике.
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
#include <cmath>
#include <cstdint>
#include <iostream>

#include "Arduino.h"

#define __SAMOVAR_H_
#define CAPACITY_NUM 10
#include "program_types.h"

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

// [P2 п.12] Дробная выдержка строки 'P' (12.5 мин) не должна усекаться до
// целых минут при сохранении/перезагрузке программы.
void test_fractional_pause_time_survives_round_trip() {
  ProgramDraft draft{};
  ProgramParseResult applied = program_parse_lines(String("P;60;12.5;1^20^3^4;1\n"), beer_program_parse_spec());
  check(applied.ok(), "valid beer program with fractional Time was rejected");
  check(ProgramLen == 1, "unexpected program length after parse");

  String serialized = program_serialize_rows(0, PROGRAM_END, program_append_beer_row);
  check(serialized.c_str()[0] != '\0', "serialized beer program is empty");
  const std::string serializedStr(serialized.c_str());
  check(serializedStr.find("12.50") != std::string::npos,
        "РЕГРЕСС: сериализация не сохранила дробную часть Time (ожидали \"12.50\" в выводе)");

  ProgramParseResult reparsed = program_parse_lines(serialized, beer_program_parse_spec(), draft);
  check(reparsed.ok(), "serialized fractional beer program could not be reparsed");
  check(draft.len == 1, "round-trip length mismatch");
  check(fabsf(draft.rows[0].Time - 12.5f) < 0.01f,
        "РЕГРЕСС: Time потерял дробную часть после раунд-трипа (усечение до int)");
}

// Контроль: целое (нулевое) значение Time на непаузной строке 'M' не должно
// искажаться сериализацией/повторным разбором.
void test_integer_time_stays_undistorted() {
  ProgramDraft draft{};
  ProgramParseResult applied = program_parse_lines(String("M;45;0;0^-1^2^2;0\n"), beer_program_parse_spec());
  check(applied.ok(), "valid beer program with integer Time was rejected");

  String serialized = program_serialize_rows(0, PROGRAM_END, program_append_beer_row);
  ProgramParseResult reparsed = program_parse_lines(serialized, beer_program_parse_spec(), draft);
  check(reparsed.ok(), "serialized integer-Time beer program could not be reparsed");
  check(draft.len == 1, "round-trip length mismatch");
  check(draft.rows[0].WType == 'M', "round-trip type mismatch");
  check(fabsf(draft.rows[0].Time - 0.0f) < 0.01f, "integer Time=0 was distorted by round-trip");
}

}  // namespace

int main() {
  test_fractional_pause_time_survives_round_trip();
  test_integer_time_stays_undistorted();

  if (failures != 0) return 1;
  std::cout << "beer program fractional Time round-trip checks passed\n";
  return 0;
}
'''


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-fractional-time-") as temp_dir:
        temp = Path(temp_dir)
        (temp / "Arduino.h").write_text(ARDUINO_STUB, encoding="utf-8")
        harness = temp / "beer_fractional_time_test.cpp"
        harness.write_text(HARNESS, encoding="utf-8")
        binary = temp / "beer_fractional_time_test"

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
                str(harness),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode

        run_result = subprocess.run(
            [str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
