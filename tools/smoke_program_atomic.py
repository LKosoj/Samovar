#!/usr/bin/env python3
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
#include <array>
#include <cstdint>
#include <cstring>
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

void seed_program() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) {
    program[i] = {};
    program[i].WType = 'X';
    program[i].Volume = static_cast<uint16_t>(1000 + i);
    program[i].Speed = 10.0f + i;
    program[i].capacity_num = i;
    program[i].Temp = 20.0f + i;
    program[i].Power = 30.0f + i;
    program[i].TempSensor = i % 5;
    program[i].Time = 40.0f + i;
  }
  ProgramLen = 3;
}

std::array<unsigned char, sizeof(program)> program_bytes() {
  std::array<unsigned char, sizeof(program)> bytes{};
  std::memcpy(bytes.data(), program, sizeof(program));
  return bytes;
}

void check_unchanged(
    const std::array<unsigned char, sizeof(program)>& before,
    uint8_t before_len,
    const char* message) {
  check(std::memcmp(before.data(), program, sizeof(program)) == 0, message);
  check(ProgramLen == before_len, "ProgramLen changed after rejected input");
}

void check_round_trip(
    const char* text,
    const ProgramParseSpec& spec,
    ProgramRowSerializer serializer,
    uint8_t expected_len,
    const char* expected_types) {
  ProgramParseResult applied = program_parse_lines(String(text), spec);
  check(applied.ok(), "valid program was rejected");
  check(ProgramLen == expected_len, "valid program length mismatch");

  String serialized = program_serialize_rows(0, PROGRAM_END, serializer);
  ProgramDraft reparsed{};
  ProgramParseResult result = program_parse_lines(serialized, spec, reparsed);
  check(result.ok(), "serialized program could not be reparsed");
  check(reparsed.len == expected_len, "round-trip length mismatch");
  for (uint8_t i = 0; i < expected_len; i++) {
    check(reparsed.rows[i].WType == expected_types[i], "round-trip type mismatch");
  }
}

void test_rejected_input_is_atomic() {
  seed_program();
  const auto before = program_bytes();
  const uint8_t before_len = ProgramLen;

  ProgramDraft draft{};
  ProgramParseResult parsed = program_parse_lines(
      String("H;450;0.1;1;0;45\nZ;450;1;1;0;45\n"),
      rect_program_parse_spec(),
      draft);
  check(!parsed.ok(), "bad row type was accepted");
  check(parsed.error == PROGRAM_PARSE_INVALID_ROW, "bad row error kind mismatch");
  check(parsed.lineNumber == 2, "bad row line number mismatch");
  check_unchanged(before, before_len, "parse-only failure changed active rows");

  ProgramParseResult applied = program_parse_lines(
      String("H;450;0.1;1;0;45\nZ;450;1;1;0;45\n"),
      rect_program_parse_spec());
  check(!applied.ok(), "atomic apply accepted a bad row");
  check_unchanged(before, before_len, "atomic apply failure changed active rows");
}

void test_empty_requires_explicit_clear() {
  seed_program();
  const auto before = program_bytes();
  const uint8_t before_len = ProgramLen;

  ProgramParseResult empty = program_parse_lines(String(""), rect_program_parse_spec());
  check(!empty.ok(), "empty text implicitly cleared the program");
  check(empty.error == PROGRAM_PARSE_EMPTY_INPUT, "empty input error kind mismatch");
  check(empty.lineNumber == 0, "empty input must be an input-level error");
  check_unchanged(before, before_len, "empty input changed active rows");

  ProgramParseResult blank = program_parse_lines(String("\r\n \t\r\n"), rect_program_parse_spec());
  check(!blank.ok(), "blank-only text implicitly cleared the program");
  check(blank.error == PROGRAM_PARSE_EMPTY_INPUT, "blank-only error kind mismatch");
  check_unchanged(before, before_len, "blank-only input changed active rows");

  std::array<uint16_t, PROGRAM_MAX> volumes{};
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) volumes[i] = program[i].Volume;
  program_clear();
  check(ProgramLen == 0, "explicit clear did not reset ProgramLen");
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) {
    check(program_type_empty(program[i].WType), "explicit clear left a live row");
    check(program[i].Volume == volumes[i], "explicit clear erased non-sentinel row data");
  }
}

void test_bounds_and_line_numbers() {
  seed_program();
  const auto before = program_bytes();
  const uint8_t before_len = ProgramLen;

  ProgramParseResult extra = program_parse_lines(
      String("H;0;0\nS;1;10\nO;2;20\nW;3;30\nH;4;40\n"),
      nbk_program_parse_spec());
  check(!extra.ok(), "NBK extra row was accepted");
  check(extra.error == PROGRAM_PARSE_TOO_MANY_ROWS, "extra-row error kind mismatch");
  check(extra.lineNumber == 5, "extra-row line number mismatch");
  check_unchanged(before, before_len, "extra row changed active program");

  ProgramParseResult short_program = program_parse_lines(
      String("H;0;0\nS;1;10\nO;2;20\n"),
      nbk_program_parse_spec());
  check(!short_program.ok(), "incomplete NBK program was accepted");
  check(short_program.error == PROGRAM_PARSE_WRONG_ROW_COUNT, "row-count error kind mismatch");
  check(short_program.lineNumber == 4, "missing-row line number mismatch");
  check_unchanged(before, before_len, "incomplete program changed active program");

  std::string oversized(MAX_PROGRAM_INPUT_LEN + 1, 'X');
  ProgramParseResult too_long = program_parse_lines(String(oversized), rect_program_parse_spec());
  check(!too_long.ok(), "oversized program was accepted");
  check(too_long.error == PROGRAM_PARSE_INPUT_TOO_LONG, "oversize error kind mismatch");
  check(too_long.lineNumber == 0, "oversize must be an input-level error");
  check_unchanged(before, before_len, "oversized input changed active program");
}

void test_non_finite_values_are_atomic() {
  struct Case {
    const char* text;
    const ProgramParseSpec& (*spec)();
  };
  const Case invalid[] = {
      {"H;450;nan;1;0;45\n", rect_program_parse_spec},
      {"A;80;1;inf\n", dist_program_parse_spec},
      {"M;-inf;0;0^-1^2^2;0\n", beer_program_parse_spec},
      {"H;1e999;0\nS;1;10\nO;2;20\nW;3;30\n", nbk_program_parse_spec},
  };
  for (const Case& test : invalid) {
    seed_program();
    const auto before = program_bytes();
    const uint8_t before_len = ProgramLen;
    ProgramParseResult result = program_parse_lines(String(test.text), test.spec());
    check(!result.ok(), "non-finite program value was accepted");
    check(result.error == PROGRAM_PARSE_INVALID_ROW, "non-finite row error kind mismatch");
    check_unchanged(before, before_len, "non-finite value changed active program");
  }
}

void test_delimiter_structure_is_atomic() {
  const char* malformed[] = {
      "H;;450;0.1;1;0;45\n",
      "A;80;1;0;\n",
      ";M;45;0;0^-1^2^2;0\n",
      "H;;1;0\nS;1;10\nO;2;20\nW;3;30\n",
  };
  const ProgramParseSpec* specs[] = {
      &rect_program_parse_spec(),
      &dist_program_parse_spec(),
      &beer_program_parse_spec(),
      &nbk_program_parse_spec(),
  };

  for (size_t i = 0; i < sizeof(malformed) / sizeof(malformed[0]); i++) {
    seed_program();
    const auto before = program_bytes();
    const uint8_t before_len = ProgramLen;
    ProgramParseResult result = program_parse_lines(String(malformed[i]), *specs[i]);
    check(!result.ok(), "malformed delimiter structure was accepted");
    check(result.error == PROGRAM_PARSE_INVALID_ROW,
          "malformed delimiter error kind mismatch");
    check_unchanged(before, before_len, "malformed delimiters changed active program");
  }

  const std::string semicolon_overflow =
      std::string("M;") + std::string(256, ';') + "45;0;0^-1^2^2;0\n";
  const std::string device_overflow =
      std::string("M;45;0;0") + std::string(256, '^') + "^-1^2^2;0\n";
  for (const std::string& text : {semicolon_overflow, device_overflow}) {
    seed_program();
    const auto before = program_bytes();
    const uint8_t before_len = ProgramLen;
    ProgramParseResult result = program_parse_lines(String(text), beer_program_parse_spec());
    check(!result.ok(), "256-delimiter overflow was accepted");
    check(result.error == PROGRAM_PARSE_INVALID_ROW,
          "256-delimiter overflow error kind mismatch");
    check_unchanged(before, before_len, "256-delimiter overflow changed active program");
  }
}

void test_blank_lines_and_all_formats_round_trip() {
  ProgramDraft draft{};
  ProgramParseResult blank_lines = program_parse_lines(
      String("\r\n \t\r\nH;450;0.10;1;0;45\r\n\r\n"),
      rect_program_parse_spec(),
      draft);
  check(blank_lines.ok(), "CRLF and blank rows were rejected");
  check(draft.len == 1 && draft.rows[0].WType == 'H', "blank rows affected row indexing");

  check_round_trip(
      "H;450;0.10;1;0;45\nB;900;1.00;2;78.2;46\n",
      rect_program_parse_spec(),
      program_append_rect_row,
      2,
      "HB");
  check_round_trip(
      "A;80.00;1;0\nS;0.50;2;10\n",
      dist_program_parse_spec(),
      program_append_dist_row,
      2,
      "AS");
  check_round_trip(
      "M;45;0;0^-1^2^2;0\nP;60;10;1^20^3^4;1\n",
      beer_program_parse_spec(),
      program_append_beer_row,
      2,
      "MP");
  check_round_trip(
      "H;0;0\nS;1;10\nO;2;20\nW;3;30\n",
      nbk_program_parse_spec(),
      program_append_nbk_row,
      NBK_PROGRAM_MAX,
      "HSOW");
}

void test_mode_mapping_and_defaults() {
  struct ModeCase {
    SAMOVAR_MODE mode;
    ProgramFormat format;
    const char* text;
    uint8_t expected_len;
  };
  const ModeCase modes[] = {
      {SAMOVAR_RECTIFICATION_MODE, PROGRAM_FORMAT_RECT,
       "H;450;0.1;1;0;45\nB;450;1;1;0;45\nH;450;0.1;1;0;45\n", 3},
      {SAMOVAR_DISTILLATION_MODE, PROGRAM_FORMAT_DIST,
       "A;80.00;1;0\nS;0.50;2;0\nS;0.30;3;0\n", 3},
      {SAMOVAR_BEER_MODE, PROGRAM_FORMAT_BEER,
       "M;45;0;0^-1^2^2;0\nP;45;1;0^-1^2^3;0\nP;60;1;0^-1^2^3;0\nW;0;0;0^-1^2^3;0\nB;0;1;0^-1^2^3;0\nC;30;0;0^-1^2^3;0\n", 6},
      {SAMOVAR_BK_MODE, PROGRAM_FORMAT_RECT,
       "H;450;0.1;1;0;45\nB;450;1;1;0;45\nH;450;0.1;1;0;45\n", 3},
      {SAMOVAR_NBK_MODE, PROGRAM_FORMAT_NBK,
       "H;1;0\nS;10;2000\nO;0;0\nW;0;0\n", 4},
      {SAMOVAR_SUVID_MODE, PROGRAM_FORMAT_BEER,
       "M;45;0;0^-1^2^2;0\nP;45;1;0^-1^2^3;0\nP;60;1;0^-1^2^3;0\nW;0;0;0^-1^2^3;0\nB;0;1;0^-1^2^3;0\nC;30;0;0^-1^2^3;0\n", 6},
      {SAMOVAR_LUA_MODE, PROGRAM_FORMAT_RECT,
       "H;450;0.1;1;0;45\nB;450;1;1;0;45\nH;450;0.1;1;0;45\n", 3},
  };

  for (const ModeCase& test : modes) {
    check(program_format_for_mode(test.mode) == test.format, "mode-to-format mapping mismatch");
    ProgramDraft draft{};
    ProgramParseResult result = prepare_program_for_mode(test.mode, String(test.text), draft);
    check(result.ok(), "built-in default was rejected");
    check(draft.len == test.expected_len, "built-in default length mismatch");
  }

  seed_program();
  const auto before = program_bytes();
  const uint8_t before_len = ProgramLen;
  ProgramDraft invalid_draft{};
  ProgramParseResult unsupported = prepare_program_for_mode(
      static_cast<SAMOVAR_MODE>(99),
      String("H;450;0.1;1;0;45\n"),
      invalid_draft);
  check(!unsupported.ok(), "unsupported mode was accepted");
  check(unsupported.error == PROGRAM_PARSE_UNSUPPORTED_MODE,
        "unsupported mode error kind mismatch");
  check_unchanged(before, before_len, "unsupported mode changed active program");

  check(sizeof(ProgramDraft) == 564, "ProgramDraft size changed");
}

}  // namespace

int main() {
  test_rejected_input_is_atomic();
  test_empty_requires_explicit_clear();
  test_bounds_and_line_numbers();
  test_non_finite_values_are_atomic();
  test_delimiter_structure_is_atomic();
  test_blank_lines_and_all_formats_round_trip();
  test_mode_mapping_and_defaults();

  if (failures != 0) return 1;
  std::cout << "Program atomic parse/commit behavioral checks passed (draft "
            << sizeof(ProgramDraft) << " bytes)\n";
  return 0;
}
'''


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-program-atomic-") as temp_dir:
        temp = Path(temp_dir)
        (temp / "Arduino.h").write_text(ARDUINO_STUB, encoding="utf-8")
        harness = temp / "program_atomic_test.cpp"
        harness.write_text(HARNESS, encoding="utf-8")
        binary = temp / "program_atomic_test"

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
