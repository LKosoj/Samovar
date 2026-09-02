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

  // concat() атомарен, как у настоящего Arduino String: JsonStringPrint зовёт его
  // напрямую, чтобы честно вернуть неуспех при нехватке памяти. В этом мок-хосте
  // память не кончается, поэтому обе перегрузки всегда успешны.
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

// [БК п.9] Границы 5-го поля БК (program_parse_bk_row, program_io.h) обычно
// объявлены в Samovar_ini.h - здесь минимальные значения только для
// компиляции; сами границы (30/100) проверяет smoke_bk_program_rows.py против
// РЕАЛЬНОГО Samovar_ini.h, этот файл их не пинит.
#define BK_STEAM_SETPOINT_MIN 30
#define BK_STEAM_SETPOINT_MAX 100

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
      {"M;-inf;0;0^0^0^0;0\n", beer_program_parse_spec},
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
      ";M;45;0;0^0^0^0;0\n",
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
      std::string("M;") + std::string(256, ';') + "45;0;0^0^0^0;0\n";
  const std::string device_overflow =
      std::string("M;45;0;0") + std::string(256, '^') + "^0^0^0;0\n";
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
      "M;45;0;0^0^0^0;0\nP;60;10;1^20^3^4;1\n",
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

void test_dist_row_type_bounds() {
  struct Case {
    const char* text;
    bool expectOk;
  };
  const Case cases[] = {
      {"T;150;0;0\n", true},
      {"T;0.01;0;0\n", true},
      {"T;0;0;0\n", false},
      {"A;0;0;0\n", true},
      {"A;99.99;0;0\n", true},
      {"A;100;0;0\n", false},
      {"P;50;0;0\n", true},
      {"P;100;0;0\n", false},
      {"S;0.999;0;0\n", true},
      {"S;1;0;0\n", false},
      {"S;0.0001;0;0\n", true},
      {"S;0;0;0\n", false},
      {"R;0.5;0;0\n", true},
      {"R;0.999;0;0\n", true},
      {"R;1;0;0\n", false},
      {"R;1.5;0;0\n", false},
  };
  for (const Case& test : cases) {
    ProgramDraft draft{};
    ProgramParseResult result = program_parse_lines(String(test.text), dist_program_parse_spec(), draft);
    std::string message = std::string("dist row type-dependent bound mismatch for: ") + test.text;
    check(result.ok() == test.expectOk, message.c_str());
  }
}

void test_beer_row_semantics() {
  struct Case {
    ProgramType type;
    float temp;
    float time;
    long devType;
    long speed;
    long onTime;
    long offTime;
    long sensor;
    bool expectOk;
  };
  const Case cases[] = {
      {'M', 45, 0, 0, 0, 0, 0, 0, true},
      {'M', 45, 1, 0, 0, 0, 0, 0, false},
      {'M', 0, 0, 0, 0, 0, 0, 0, false},
      {'C', 20, 0, 0, 0, 0, 0, 0, true},
      {'C', 20, 1, 0, 0, 0, 0, 0, false},
      {'F', 18, 0, 0, 0, 0, 0, 0, true},
      {'F', 18, 1, 0, 0, 0, 0, 0, false},
      {'P', 65, 1, 0, 0, 0, 0, 0, true},
      {'P', 65, 0, 0, 0, 0, 0, 0, false},
      {'P', 65, 1, 0, -1, 2, 3, 0, false},
      {'P', 65, 1, 1, -1, 2, 0, 0, true},
      {'B', 0, 1, 0, 0, 0, 0, 0, true},
      {'B', 1, 1, 0, 0, 0, 0, 0, false},
      {'W', 0, 0, 1, 20, 3, 4, 0, true},
      {'W', 0, 1, 1, 20, 3, 4, 0, false},
      {'W', 0, 0, 1, 20, 3, 4, 4, true},
      {'A', 70, 0, 0, 0, 0, 0, 1, true},
      {'A', 70, 0, 1, 20, 3, 4, 1, false},
      {'A', 0, 0, 0, 0, 0, 0, 1, false},
      {'L', 0, 0, 0, 0, 0, 0, 0, false},
  };
  for (const Case& test : cases) {
    const char* error = nullptr;
    const bool ok = program_validate_beer_row_semantics(
        test.type, test.temp, test.time, test.devType, test.speed,
        test.onTime, test.offTime, test.sensor, error);
    std::string message = std::string("beer semantic matrix mismatch for type ") + test.type;
    check(ok == test.expectOk, message.c_str());
    if (!ok) check(error != nullptr, "rejected beer semantic row lacks an error message");
  }
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
       "M;45;0;0^0^0^0;0\nP;45;1;0^0^0^0;0\nP;60;1;0^0^0^0;0\nW;0;0;0^0^0^0;0\nB;0;1;0^0^0^0;0\nC;30;0;0^0^0^0;0\n", 6},
      {SAMOVAR_BK_MODE, PROGRAM_FORMAT_BK,
       "T;93;1;0;0\n", 1},
      {SAMOVAR_NBK_MODE, PROGRAM_FORMAT_NBK,
       "H;1;0\nS;10;2000\nO;0;0\nW;0;0\n", 4},
      {SAMOVAR_SUVID_MODE, PROGRAM_FORMAT_BEER,
       "M;45;0;0^0^0^0;0\nP;45;1;0^0^0^0;0\nP;60;1;0^0^0^0;0\nW;0;0;0^0^0^0;0\nB;0;1;0^0^0^0;0\nC;30;0;0^0^0^0;0\n", 6},
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

void test_power_first_row_scope() {
  // [Б7.2] Правило "первая строка задаёт АБСОЛЮТНУЮ мощность" (program[0].Power)
  // из prepare_program_for_mode() распространяется ТОЛЬКО на ректификацию -
  // check_alarm() (alarm.h) безусловно применяет её к регулятору только там.
  // У Lua мощность задаёт скрипт - его это правило не должно ловить молча.
  // [БК п.9] У БК теперь СВОЁ формат (PROGRAM_FORMAT_BK) и своё правило первой
  // НЕНУЛЕВОЙ мощности - то же самое, что у дистилляции (см. bk_* кейсы ниже,
  // по образцу dist_*).
  ProgramDraft draft{};

  ProgramParseResult rect_zero = prepare_program_for_mode(
      SAMOVAR_RECTIFICATION_MODE, String("H;450;0.1;1;0;0\n"), draft);
  check(!rect_zero.ok(), "rectification first row with Power=0 was accepted");
  check(rect_zero.error == PROGRAM_PARSE_INVALID_ROW,
        "rectification Power=0 error kind mismatch");

  ProgramParseResult rect_low = prepare_program_for_mode(
      SAMOVAR_RECTIFICATION_MODE, String("H;450;0.1;1;0;30\n"), draft);
  check(!rect_low.ok(), "rectification first row with Power=30 (below threshold) was accepted");

  // [Пункт 3] Power РОВНО равна порогу - сравнение строгое (>), граница не абсолютная
  // уставка. Порог берём из уже включённого program_types.h (PROGRAM_POWER_ABS_THRESHOLD),
  // не хардкодим число - кейс остаётся верным для обеих веток (400 SEM_AVR / 40 остальные).
  String thresholdRow = String("H;450;0.1;1;0;") + String(PROGRAM_POWER_ABS_THRESHOLD) + String("\n");
  ProgramParseResult rect_threshold = prepare_program_for_mode(
      SAMOVAR_RECTIFICATION_MODE, thresholdRow, draft);
  check(!rect_threshold.ok(), "rectification first row with Power==threshold (strict >) was accepted");

  ProgramParseResult lua_zero = prepare_program_for_mode(
      SAMOVAR_LUA_MODE, String("H;450;0.1;1;0;0\n"), draft);
  check(lua_zero.ok(), "Lua first row with Power=0 must stay valid - Lua power is set by the script");

  // [БК п.9] БК: то же правило, что и у дистилляции (первая НЕНУЛЕВАЯ Power
  // должна быть абсолютной), но формат строки БК - 5 полей (Тип;Порог;Ёмкость;
  // Мощность;Тпара), не 6, как у ректификации.
  ProgramParseResult bk_correction_first = prepare_program_for_mode(
      SAMOVAR_BK_MODE, String("A;80;1;-20;0\n"), draft);
  check(!bk_correction_first.ok(),
        "BK first nonzero-power row as a correction (-20) was accepted");
  check(bk_correction_first.lineNumber == 1, "BK correction-first line number mismatch");

  ProgramParseResult bk_zero_then_abs = prepare_program_for_mode(
      SAMOVAR_BK_MODE, String("A;80;1;0;0\nS;0.5;2;60;0\n"), draft);
  check(bk_zero_then_abs.ok(),
        "BK zero-power row followed by an absolute row must be accepted");

  ProgramParseResult bk_zero_then_correction = prepare_program_for_mode(
      SAMOVAR_BK_MODE, String("A;80;1;0;0\nS;0.5;2;20;0\n"), draft);
  check(!bk_zero_then_correction.ok(),
        "BK zero-power row followed by a correction as first nonzero must be rejected");
  check(bk_zero_then_correction.lineNumber == 2, "BK zero-then-correction line number mismatch");

  ProgramParseResult bk_all_zero = prepare_program_for_mode(
      SAMOVAR_BK_MODE, String("A;80;1;0;0\nS;0.5;2;0;0\n"), draft);
  check(bk_all_zero.ok(), "BK program with all-zero Power must stay valid (matches built-in default)");

  // [П1] Дистилляция: правило иное - не program[0], а ПЕРВАЯ строка с Power != 0.
  // run_dist_program() применяет Power только на переходе строки (distiller.h), поэтому
  // строки с Power==0 разрешено пропускать сколько угодно - опасен только первый
  // ненулевой Power, если он оказывается поправкой, а не абсолютной уставкой.
  ProgramParseResult dist_correction_first = prepare_program_for_mode(
      SAMOVAR_DISTILLATION_MODE, String("A;80;1;-20\n"), draft);
  check(!dist_correction_first.ok(),
        "dist first nonzero-power row as a correction (-20) was accepted");
  check(dist_correction_first.lineNumber == 1, "dist correction-first line number mismatch");

  ProgramParseResult dist_zero_then_abs = prepare_program_for_mode(
      SAMOVAR_DISTILLATION_MODE, String("A;80;1;0\nS;0.5;2;60\n"), draft);
  check(dist_zero_then_abs.ok(),
        "dist zero-power row followed by an absolute row must be accepted");

  ProgramParseResult dist_zero_then_correction = prepare_program_for_mode(
      SAMOVAR_DISTILLATION_MODE, String("A;80;1;0\nS;0.5;2;20\n"), draft);
  check(!dist_zero_then_correction.ok(),
        "dist zero-power row followed by a correction as first nonzero must be rejected");
  check(dist_zero_then_correction.lineNumber == 2, "dist zero-then-correction line number mismatch");

  ProgramParseResult dist_all_zero = prepare_program_for_mode(
      SAMOVAR_DISTILLATION_MODE, String("A;80;1;0\nS;0.5;2;0\n"), draft);
  check(dist_all_zero.ok(), "dist program with all-zero Power must stay valid (matches built-in default)");

  // [П1 доп.] program_parse_lines() пропускает пустые строки, наращивая
  // lineNumber БЕЗ увеличения индекса непустой строки - номер в сообщении
  // обязан быть ФИЗИЧЕСКИМ номером строки текста, а не индексом draft.rows[i].
  ProgramParseResult dist_blank_first_line = prepare_program_for_mode(
      SAMOVAR_DISTILLATION_MODE, String("\nA;80;1;-20\n"), draft);
  check(!dist_blank_first_line.ok(),
        "dist correction row after a blank line must still be rejected");
  check(dist_blank_first_line.lineNumber == 2,
        "dist blank-first-line physical line number mismatch");

  ProgramParseResult dist_no_blank_lines = prepare_program_for_mode(
      SAMOVAR_DISTILLATION_MODE, String("A;80;1;0\nS;0.5;2;-20\n"), draft);
  check(!dist_no_blank_lines.ok(),
        "dist correction row (no blank lines) must be rejected");
  check(dist_no_blank_lines.lineNumber == 2,
        "dist no-blank-lines physical line number mismatch");
}

}  // namespace

int main() {
  test_rejected_input_is_atomic();
  test_empty_requires_explicit_clear();
  test_bounds_and_line_numbers();
  test_non_finite_values_are_atomic();
  test_delimiter_structure_is_atomic();
  test_blank_lines_and_all_formats_round_trip();
  test_dist_row_type_bounds();
  test_beer_row_semantics();
  test_mode_mapping_and_defaults();
  test_power_first_row_scope();

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
        if run_result.returncode != 0:
            return run_result.returncode

        # Mutation proof: a nonzero mixer schedule without a selected device
        # must not become accepted. Compile the altered production header in a
        # temporary include directory; the repository source itself is never
        # written.
        mutated_program_io = (ROOT / "program_io.h").read_text(encoding="utf-8")
        mutated_program_io = mutated_program_io.replace(
            "const bool validDeviceSchedule = validDeviceMask && onTime > 0;",
            "const bool validDeviceSchedule = devType == 0 || (validDeviceMask && onTime > 0);", 1,
        )
        (temp / "program_io.h").write_text(mutated_program_io, encoding="utf-8")
        mutation_binary = temp / "program_atomic_mutation_test"
        mutation_compile = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(temp), "-I", str(ROOT), str(harness), "-o", str(mutation_binary),
            ],
            capture_output=True, text=True, check=False,
        )
        if mutation_compile.returncode != 0:
            sys.stderr.write("FAIL: semantic mutation did not compile\n")
            sys.stderr.write(mutation_compile.stderr)
            return 1
        mutation_run = subprocess.run(
            [str(mutation_binary)], capture_output=True, text=True, check=False
        )
        if mutation_run.returncode == 0:
            sys.stderr.write("FAIL: beer semantic test did not catch the mutation\n")
            return 1
        print("Beer semantic mutation was rejected as expected")

        # [П1] Mutation proof: neutralize the "skip zero-power rows" guard so the
        # first-nonzero-power check would fire on program[0] unconditionally instead
        # of scanning for the first nonzero row - a correction-only program with a
        # leading zero row must stop being rejected once this line is disabled.
        mutated_p1 = (ROOT / "program_io.h").read_text(encoding="utf-8")
        mutated_p1 = mutated_p1.replace(
            "if (draft.rows[i].Power == 0.0f) continue;",
            "if (true) continue;", 1,
        )
        (temp / "program_io.h").write_text(mutated_p1, encoding="utf-8")
        p1_mutation_binary = temp / "program_atomic_p1_mutation_test"
        p1_mutation_compile = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(temp), "-I", str(ROOT), str(harness), "-o", str(p1_mutation_binary),
            ],
            capture_output=True, text=True, check=False,
        )
        if p1_mutation_compile.returncode != 0:
            sys.stderr.write("FAIL: dist first-power-row mutation did not compile\n")
            sys.stderr.write(p1_mutation_compile.stderr)
            return 1
        p1_mutation_run = subprocess.run(
            [str(p1_mutation_binary)], capture_output=True, text=True, check=False
        )
        if p1_mutation_run.returncode == 0:
            sys.stderr.write("FAIL: dist first-power-row test did not catch the mutation\n")
            return 1
        print("Dist first-power-row mutation was rejected as expected")

        # [П1 доп.] Mutation proof: revert program_physical_line_for_row() to the
        # original bug it replaces (rowIndex + 1, ignoring blank lines) - the
        # blank-line test above must then see line 1 instead of line 2 and fail.
        mutated_line_helper = (ROOT / "program_io.h").read_text(encoding="utf-8")
        mutated_line_helper = mutated_line_helper.replace(
            "inline uint16_t program_physical_line_for_row(const String& text, uint8_t rowIndex) {\n"
            "  const char* cursor = text.c_str();",
            "inline uint16_t program_physical_line_for_row(const String& text, uint8_t rowIndex) {\n"
            "  return rowIndex + 1;\n"
            "  const char* cursor = text.c_str();",
            1,
        )
        if mutated_line_helper == (ROOT / "program_io.h").read_text(encoding="utf-8"):
            sys.stderr.write("FAIL: line-number helper mutation target not found\n")
            return 1
        (temp / "program_io.h").write_text(mutated_line_helper, encoding="utf-8")
        line_mutation_binary = temp / "program_atomic_line_mutation_test"
        line_mutation_compile = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(temp), "-I", str(ROOT), str(harness), "-o", str(line_mutation_binary),
            ],
            capture_output=True, text=True, check=False,
        )
        if line_mutation_compile.returncode != 0:
            sys.stderr.write("FAIL: line-number helper mutation did not compile\n")
            sys.stderr.write(line_mutation_compile.stderr)
            return 1
        line_mutation_run = subprocess.run(
            [str(line_mutation_binary)], capture_output=True, text=True, check=False
        )
        if line_mutation_run.returncode == 0:
            sys.stderr.write("FAIL: physical-line test did not catch the mutation\n")
            return 1
        print("Physical-line-number mutation was rejected as expected")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
