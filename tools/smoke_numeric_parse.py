#!/usr/bin/env python3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <iostream>

#include "numeric_parse.h"

namespace {

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

void test_finite_float() {
  float value = -77.0f;
  NumericParseResult result = parse_finite_float("  -1.25\t", value);
  check(result.ok() && value == -1.25f, "finite float with surrounding whitespace failed");

  struct Case {
    const char* text;
    NumericParseError error;
  };
  const Case invalid[] = {
      {"", NUMERIC_PARSE_EMPTY},
      {" \t\r\n", NUMERIC_PARSE_EMPTY},
      {"value", NUMERIC_PARSE_INVALID_FORMAT},
      {"1tail", NUMERIC_PARSE_TRAILING_CHARACTERS},
      {"1 2", NUMERIC_PARSE_TRAILING_CHARACTERS},
      {"0x1p2", NUMERIC_PARSE_TRAILING_CHARACTERS},
      {"1e", NUMERIC_PARSE_INVALID_FORMAT},
      {"nan", NUMERIC_PARSE_NOT_FINITE},
      {"NaN", NUMERIC_PARSE_NOT_FINITE},
      {"inf", NUMERIC_PARSE_NOT_FINITE},
      {"+inf", NUMERIC_PARSE_NOT_FINITE},
      {"-inf", NUMERIC_PARSE_NOT_FINITE},
      {"1e999", NUMERIC_PARSE_OUT_OF_RANGE},
      {"1e-9999", NUMERIC_PARSE_OUT_OF_RANGE},
  };
  for (const Case& test : invalid) {
    value = 123.25f;
    result = parse_finite_float(test.text, value);
    check(!result.ok(), "invalid finite float was accepted");
    check(result.error == test.error, "finite float error kind mismatch");
    check(value == 123.25f, "finite float changed output on error");
  }

  value = -77.0f;
  result = parse_finite_float("1.1754944e-38", value);
  check(result.ok() && value > 0.0f, "minimum normal float was rejected");
  const char* float_range_errors[] = {"1e-40", "-1e-40", "1e-50", "3.5e38", "-3.5e38"};
  for (const char* text : float_range_errors) {
    value = 123.25f;
    result = parse_finite_float(text, value);
    check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && value == 123.25f,
          "float narrowing range error changed output or error kind");
  }
  value = 0.0f;
  check(parse_finite_float("3.4028234e38", value).ok() && isfinite(value),
        "finite float near maximum was rejected");
}

void test_finite_double() {
  double value = -77.0;
  check(parse_finite_double("7999.9999", value).ok() && value > 7999.9998 && value < 8000.0,
        "finite double lost decimal boundary");
  check(parse_finite_double("1e-40", value).ok() && value > 0.0,
        "double source parser incorrectly applies float subnormal limits");
  const char* invalid[] = {"", "nan", "inf", "1e9999", "1x"};
  for (const char* text : invalid) {
    value = 123.25;
    check(!parse_finite_double(text, value).ok() && value == 123.25,
          "invalid finite double changed output");
  }
}

void test_bounded_float() {
  float value = 0.0f;
  check(parse_bounded_float("-10", -10.0f, 10.0f, value).ok() && value == -10.0f,
        "bounded float minimum failed");
  check(parse_bounded_float("10", -10.0f, 10.0f, value).ok() && value == 10.0f,
        "bounded float maximum failed");

  value = 3.5f;
  NumericParseResult result = parse_bounded_float("-11", -10.0f, 10.0f, value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && value == 3.5f,
        "bounded float accepted min - 1 or changed output");
  result = parse_bounded_float("11", -10.0f, 10.0f, value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && value == 3.5f,
        "bounded float accepted max + 1 or changed output");
  result = parse_bounded_float("0", 10.0f, -10.0f, value);
  check(result.error == NUMERIC_PARSE_INVALID_BOUNDS && value == 3.5f,
        "invalid float bounds changed output");
}

void test_integral_parsers() {
  long long_value = 0;
  check(parse_bounded_long(" -10 ", -10, 10, long_value).ok() && long_value == -10,
        "bounded long minimum failed");
  check(parse_bounded_long("10", -10, 10, long_value).ok() && long_value == 10,
        "bounded long maximum failed");

  long_value = 44;
  NumericParseResult result = parse_bounded_long("-11", -10, 10, long_value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && long_value == 44,
        "bounded long accepted min - 1 or changed output");
  result = parse_bounded_long("11", -10, 10, long_value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && long_value == 44,
        "bounded long accepted max + 1 or changed output");
  const char* invalid_long[] = {"", " ", "1.0", "1x", "1 2", "999999999999999999999999999"};
  for (const char* text : invalid_long) {
    long_value = 44;
    result = parse_bounded_long(text, -100, 100, long_value);
    check(!result.ok() && long_value == 44, "invalid long changed output");
  }

  int32_t int_value = 0;
  check(parse_exact_int32("-2147483648", int_value).ok() && int_value == INT32_MIN,
        "exact int32 minimum failed");
  check(parse_exact_int32("2147483647", int_value).ok() && int_value == INT32_MAX,
        "exact int32 maximum failed");
  int_value = 91;
  result = parse_exact_int32("2147483648", int_value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && int_value == 91,
        "exact int32 overflow changed output");
  result = parse_exact_int32("-2147483649", int_value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && int_value == 91,
        "exact int32 underflow changed output");

  uint16_t u16_value = 9;
  check(parse_bounded_uint16("0", 0, UINT16_MAX, u16_value).ok() && u16_value == 0,
        "uint16 minimum failed");
  check(parse_bounded_uint16("65535", 0, UINT16_MAX, u16_value).ok() && u16_value == 65535,
        "uint16 maximum failed");
  u16_value = 9;
  result = parse_bounded_uint16("-1", 0, UINT16_MAX, u16_value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && u16_value == 9,
        "uint16 accepted min - 1 or changed output");
  result = parse_bounded_uint16("65536", 0, UINT16_MAX, u16_value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && u16_value == 9,
        "uint16 accepted max + 1 or changed output");

  check(parse_bounded_uint16("100", 100, 200, u16_value).ok() && u16_value == 100,
        "bounded uint16 minimum failed");
  check(parse_bounded_uint16("200", 100, 200, u16_value).ok() && u16_value == 200,
        "bounded uint16 maximum failed");
  u16_value = 9;
  result = parse_bounded_uint16("99", 100, 200, u16_value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && u16_value == 9,
        "bounded uint16 accepted min - 1 or changed output");
  result = parse_bounded_uint16("201", 100, 200, u16_value);
  check(result.error == NUMERIC_PARSE_OUT_OF_RANGE && u16_value == 9,
        "bounded uint16 accepted max + 1 or changed output");
}

void test_exact_bool_and_enum() {
  bool bool_value = false;
  check(parse_exact_bool(" 1 ", bool_value).ok() && bool_value,
        "exact bool 1 failed");
  check(parse_exact_bool("0", bool_value).ok() && !bool_value,
        "exact bool 0 failed");
  const char* invalid_bool[] = {"", "2", "-1", "+1", "01", "1.0", "true", "1x"};
  for (const char* text : invalid_bool) {
    bool_value = true;
    NumericParseResult result = parse_exact_bool(text, bool_value);
    check(!result.ok() && bool_value, "invalid bool changed output");
  }

  const int32_t allowed[] = {-2, 0, 5};
  int32_t enum_value = 77;
  check(parse_exact_enum("-2", allowed, 3, enum_value).ok() && enum_value == -2,
        "exact enum minimum member failed");
  check(parse_exact_enum("5", allowed, 3, enum_value).ok() && enum_value == 5,
        "exact enum maximum member failed");
  enum_value = 77;
  NumericParseResult result = parse_exact_enum("1", allowed, 3, enum_value);
  check(result.error == NUMERIC_PARSE_NOT_ALLOWED && enum_value == 77,
        "exact enum accepted a hole or changed output");
  result = parse_exact_enum("5x", allowed, 3, enum_value);
  check(result.error == NUMERIC_PARSE_TRAILING_CHARACTERS && enum_value == 77,
        "invalid enum syntax changed output");
  result = parse_exact_enum("0", nullptr, 0, enum_value);
  check(result.error == NUMERIC_PARSE_INVALID_ARGUMENT && enum_value == 77,
        "invalid enum domain changed output");
}

void test_unsigned_hex_and_arithmetic() {
  uint8_t u8 = 19;
  check(parse_bounded_uint8("0", 0, UINT8_MAX, u8).ok() && u8 == 0,
        "uint8 minimum failed");
  check(parse_bounded_uint8("255", 0, UINT8_MAX, u8).ok() && u8 == 255,
        "uint8 maximum failed");
  u8 = 19;
  check(!parse_bounded_uint8("256", 0, UINT8_MAX, u8).ok() && u8 == 19,
        "uint8 overflow changed output");

  uint32_t u32 = 17;
  check(parse_bounded_uint32("0", 0, UINT32_MAX, u32).ok() && u32 == 0,
        "uint32 minimum failed");
  check(parse_bounded_uint32("4294967295", 0, UINT32_MAX, u32).ok() && u32 == UINT32_MAX,
        "uint32 maximum failed");
  const char* invalid_u32[] = {"-1", "4294967296", "999999999999999999999", "1.0", "1x"};
  for (const char* text : invalid_u32) {
    u32 = 17;
    check(!parse_bounded_uint32(text, 0, UINT32_MAX, u32).ok() && u32 == 17,
          "invalid uint32 changed output");
  }
  u32 = 17;
  check(parse_bounded_uint32("-x", 0, UINT32_MAX, u32).error ==
            NUMERIC_PARSE_INVALID_FORMAT && u32 == 17,
        "malformed negative uint32 error kind mismatch");
  check(parse_bounded_uint32("-1x", 0, UINT32_MAX, u32).error ==
            NUMERIC_PARSE_TRAILING_CHARACTERS && u32 == 17,
        "negative uint32 trailing error kind mismatch");

  uint16_t hex = 71;
  check(parse_fixed_hex_uint16("01f", 3, 0, 0xFFF, hex).ok() && hex == 0x01f,
        "lowercase fixed hex failed");
  check(parse_fixed_hex_uint16("FFF", 3, 0, 0xFFF, hex).ok() && hex == 0xFFF,
        "uppercase fixed hex failed");
  const char* invalid_hex[] = {"FF", "FFFF", "F_G", " 01", "01 "};
  for (const char* text : invalid_hex) {
    hex = 71;
    check(!parse_fixed_hex_uint16(text, 3, 0, 0xFFF, hex).ok() && hex == 71,
          "invalid fixed hex changed output");
  }
  hex = 71;
  check(parse_fixed_hex_uint16("001", 3, 10, 1, hex).error == NUMERIC_PARSE_INVALID_BOUNDS &&
            hex == 71,
        "invalid fixed hex bounds changed output or error kind");
  check(parse_fixed_hex_uint16(nullptr, 3, 0, 0xFFF, hex).error ==
            NUMERIC_PARSE_INVALID_ARGUMENT && hex == 71,
        "invalid fixed hex argument changed output or error kind");

  uint32_t product = 33;
  check(checked_mul_u32(65535, 65535, product).ok() && product == 4294836225U,
        "checked uint32 product failed");
  product = 33;
  check(!checked_mul_u32(UINT32_MAX, 2, product).ok() && product == 33,
        "overflowing uint32 product changed output");

  uint16_t steps = 29;
  check(checked_rate_to_step_speed(3.6f, 1000, steps).ok() && steps == 1000,
        "rate to steps conversion failed");
  const double lastAcceptedRate = std::nextafter(65535.5, 0.0) * 3.6;
  steps = 29;
  check(checked_rate_to_step_speed(lastAcceptedRate, 1, steps).ok() && steps == 65535,
        "last round-to-nearest value was rejected");
  steps = 29;
  check(!checked_rate_to_step_speed(65535.5 * 3.6, 1, steps).ok() && steps == 29,
        "rate rounding to 65536 was accepted");
  steps = 29;
  check(!checked_rate_to_step_speed(3.6f, 0, steps).ok() && steps == 29,
        "zero calibration changed rate output");
  check(!checked_rate_to_step_speed(1000.0f, UINT16_MAX, steps).ok() && steps == 29,
        "overflowing rate changed output");

  uint16_t mlh = 41;
  check(checked_step_speed_to_mlh(1000, 1000, mlh).ok() && mlh == 3600,
        "steps to ml/h conversion failed");
  mlh = 41;
  check(!checked_step_speed_to_mlh(UINT16_MAX, 1, mlh).ok() && mlh == 41,
        "overflowing ml/h changed output");

  check(validate_bounded_finite_float(1.0f, 0.0f, 1.0f).ok(),
        "typed finite upper bound failed");
  check(validate_bounded_finite_float(INFINITY, 0.0f, 1.0f).error == NUMERIC_PARSE_NOT_FINITE,
        "typed infinity was accepted");
  check(strcmp(numeric_parse_error_code(NUMERIC_PARSE_OUT_OF_RANGE), "range") == 0,
        "stable numeric error code mismatch");
}

void test_checked_lua_narrowing() {
  int32_t narrowed = 77;
  check(checked_narrow_int32(INT32_MIN, INT32_MIN, INT32_MAX, narrowed).ok() &&
            narrowed == INT32_MIN,
        "checked int32 minimum failed");
  check(checked_narrow_int32(INT32_MAX, INT32_MIN, INT32_MAX, narrowed).ok() &&
            narrowed == INT32_MAX,
        "checked int32 maximum failed");
  narrowed = 77;
  check(checked_narrow_int32(static_cast<int64_t>(INT32_MIN) - 1,
                             INT32_MIN, INT32_MAX, narrowed).error ==
            NUMERIC_PARSE_OUT_OF_RANGE && narrowed == 77,
        "checked int32 underflow changed output");
  check(checked_narrow_int32(static_cast<int64_t>(INT32_MAX) + 1,
                             INT32_MIN, INT32_MAX, narrowed).error ==
            NUMERIC_PARSE_OUT_OF_RANGE && narrowed == 77,
        "checked int32 overflow changed output");
  check(checked_narrow_int32(0, 1, -1, narrowed).error ==
            NUMERIC_PARSE_INVALID_BOUNDS && narrowed == 77,
        "checked int32 invalid bounds changed output");

  uint32_t product = 91;
  check(checked_truncating_product_u32(1.0, 1.0, product).ok() && product == 1,
        "checked truncating product minimum failed");
  check(checked_truncating_product_u32(1.75, 2.0, product).ok() && product == 3,
        "checked truncating product lost truncation semantics");
  product = 91;
  check(checked_truncating_product_u32(0.5, 1.0, product).error ==
            NUMERIC_PARSE_OUT_OF_RANGE && product == 91,
        "sub-unit product changed output");
  check(checked_truncating_product_u32(0.0, 1.0, product).error ==
            NUMERIC_PARSE_OUT_OF_RANGE && product == 91,
        "zero product changed output");
  check(checked_truncating_product_u32(
            static_cast<double>(UINT32_MAX), 1.0, product).ok() &&
            product == UINT32_MAX,
        "checked truncating product uint32 maximum failed");
  product = 91;
  check(checked_truncating_product_u32(
            std::nextafter(static_cast<double>(UINT32_MAX), INFINITY),
            1.0, product).error == NUMERIC_PARSE_OUT_OF_RANGE && product == 91,
        "checked truncating product overflow changed output");
  check(checked_truncating_product_u32(NAN, 1.0, product).error ==
            NUMERIC_PARSE_NOT_FINITE && product == 91,
        "NaN product changed output");
  check(checked_truncating_product_u32(INFINITY, 1.0, product).error ==
            NUMERIC_PARSE_NOT_FINITE && product == 91,
        "positive infinity product changed output");
  check(checked_truncating_product_u32(-INFINITY, 1.0, product).error ==
            NUMERIC_PARSE_NOT_FINITE && product == 91,
        "negative infinity product changed output");
}

}  // namespace

int main() {
  test_finite_float();
  test_finite_double();
  test_bounded_float();
  test_integral_parsers();
  test_exact_bool_and_enum();
  test_unsigned_hex_and_arithmetic();
  test_checked_lua_narrowing();
  if (failures != 0) return 1;
  std::cout << "Numeric parse behavioral checks passed\n";
  return 0;
}
'''


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-numeric-parse-") as temp_dir:
        temp = Path(temp_dir)
        harness = temp / "numeric_parse_test.cpp"
        harness.write_text(HARNESS, encoding="utf-8")
        binary = temp / "numeric_parse_test"
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
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
