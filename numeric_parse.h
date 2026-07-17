#pragma once

#include <errno.h>
#include <float.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum NumericParseError : uint8_t {
  NUMERIC_PARSE_OK = 0,
  NUMERIC_PARSE_EMPTY,
  NUMERIC_PARSE_INVALID_FORMAT,
  NUMERIC_PARSE_TRAILING_CHARACTERS,
  NUMERIC_PARSE_OUT_OF_RANGE,
  NUMERIC_PARSE_NOT_FINITE,
  NUMERIC_PARSE_INVALID_BOUNDS,
  NUMERIC_PARSE_NOT_ALLOWED,
  NUMERIC_PARSE_INVALID_ARGUMENT,
};

struct NumericParseResult {
  NumericParseError error;

  bool ok() const {
    return error == NUMERIC_PARSE_OK;
  }
};

inline NumericParseResult numeric_parse_result(NumericParseError error) {
  return {error};
}

// Numeric fields allow ASCII whitespace around a token, never inside it.
inline bool numeric_ascii_space(char value) {
  return value == ' ' || value == '\t' || value == '\r' ||
         value == '\n' || value == '\f' || value == '\v';
}

inline char numeric_ascii_lower(char value) {
  if (value >= 'A' && value <= 'Z') return value + ('a' - 'A');
  return value;
}

inline NumericParseResult numeric_token_bounds(
    const char* text,
    const char*& begin,
    const char*& end) {
  if (!text) return numeric_parse_result(NUMERIC_PARSE_EMPTY);

  begin = text;
  while (*begin && numeric_ascii_space(*begin)) begin++;

  end = text + strlen(text);
  while (end > begin && numeric_ascii_space(end[-1])) end--;
  if (begin == end) return numeric_parse_result(NUMERIC_PARSE_EMPTY);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline bool numeric_token_equals_ignore_case(
    const char* begin,
    const char* end,
    const char* expected) {
  const char* current = begin;
  const char* match = expected;
  while (current < end && *match) {
    if (numeric_ascii_lower(*current) != *match) return false;
    current++;
    match++;
  }
  return current == end && *match == '\0';
}

inline bool numeric_token_is_non_finite(const char* begin, const char* end) {
  if (begin < end && (*begin == '+' || *begin == '-')) begin++;
  return numeric_token_equals_ignore_case(begin, end, "nan") ||
         numeric_token_equals_ignore_case(begin, end, "inf") ||
         numeric_token_equals_ignore_case(begin, end, "infinity");
}

inline NumericParseResult numeric_validate_integer_token(
    const char* begin,
    const char* end) {
  const char* current = begin;
  if (*current == '+' || *current == '-') current++;
  if (current == end || *current < '0' || *current > '9') {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_FORMAT);
  }
  while (current < end && *current >= '0' && *current <= '9') current++;
  if (current != end) {
    return numeric_parse_result(NUMERIC_PARSE_TRAILING_CHARACTERS);
  }
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult numeric_validate_float_token(
    const char* begin,
    const char* end) {
  const char* current = begin;
  if (*current == '+' || *current == '-') current++;

  bool hasDigit = false;
  while (current < end && *current >= '0' && *current <= '9') {
    hasDigit = true;
    current++;
  }
  if (current < end && *current == '.') {
    current++;
    while (current < end && *current >= '0' && *current <= '9') {
      hasDigit = true;
      current++;
    }
  }
  if (!hasDigit) return numeric_parse_result(NUMERIC_PARSE_INVALID_FORMAT);

  if (current < end && (*current == 'e' || *current == 'E')) {
    current++;
    if (current < end && (*current == '+' || *current == '-')) current++;
    const char* exponentDigits = current;
    while (current < end && *current >= '0' && *current <= '9') current++;
    if (current == exponentDigits) {
      return numeric_parse_result(NUMERIC_PARSE_INVALID_FORMAT);
    }
  }
  if (current != end) {
    return numeric_parse_result(NUMERIC_PARSE_TRAILING_CHARACTERS);
  }
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_finite_double(const char* text, double& out) {
  const char* begin = nullptr;
  const char* end = nullptr;
  NumericParseResult result = numeric_token_bounds(text, begin, end);
  if (!result.ok()) return result;
  if (numeric_token_is_non_finite(begin, end)) {
    return numeric_parse_result(NUMERIC_PARSE_NOT_FINITE);
  }
  result = numeric_validate_float_token(begin, end);
  if (!result.ok()) return result;

  errno = 0;
  char* parsedEnd = nullptr;
  double value = strtod(begin, &parsedEnd);
  if (errno == ERANGE) return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  if (errno != 0 || parsedEnd != end) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_FORMAT);
  }
  if (!isfinite(value)) return numeric_parse_result(NUMERIC_PARSE_NOT_FINITE);
  out = value;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_finite_float(const char* text, float& out) {
  double parsed = 0.0;
  NumericParseResult result = parse_finite_double(text, parsed);
  if (!result.ok()) return result;
  const double magnitude = parsed < 0.0 ? -parsed : parsed;
  if (magnitude > FLT_MAX || (magnitude != 0.0 && magnitude < FLT_MIN)) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  const float value = static_cast<float>(parsed);
  if (!isfinite(value)) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = value;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_bounded_float(
    const char* text,
    float minValue,
    float maxValue,
    float& out) {
  if (!isfinite(minValue) || !isfinite(maxValue) || minValue > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }
  float value = 0.0f;
  NumericParseResult result = parse_finite_float(text, value);
  if (!result.ok()) return result;
  if (value < minValue || value > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = value;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_bounded_long(
    const char* text,
    long minValue,
    long maxValue,
    long& out) {
  if (minValue > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }

  const char* begin = nullptr;
  const char* end = nullptr;
  NumericParseResult result = numeric_token_bounds(text, begin, end);
  if (!result.ok()) return result;
  result = numeric_validate_integer_token(begin, end);
  if (!result.ok()) return result;

  errno = 0;
  char* parsedEnd = nullptr;
  long value = strtol(begin, &parsedEnd, 10);
  if (errno == ERANGE) return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  if (errno != 0 || parsedEnd != end) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_FORMAT);
  }
  if (value < minValue || value > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = value;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_exact_int32(const char* text, int32_t& out) {
  long value = 0;
  NumericParseResult result = parse_bounded_long(text, INT32_MIN, INT32_MAX, value);
  if (!result.ok()) return result;
  out = static_cast<int32_t>(value);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_bounded_uint16(
    const char* text,
    uint16_t minValue,
    uint16_t maxValue,
    uint16_t& out) {
  if (minValue > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }
  long value = 0;
  NumericParseResult result = parse_bounded_long(text, minValue, maxValue, value);
  if (!result.ok()) return result;
  out = static_cast<uint16_t>(value);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_bounded_uint8(
    const char* text,
    uint8_t minValue,
    uint8_t maxValue,
    uint8_t& out) {
  if (minValue > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }
  long value = 0;
  NumericParseResult result = parse_bounded_long(text, minValue, maxValue, value);
  if (!result.ok()) return result;
  out = static_cast<uint8_t>(value);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_bounded_uint32(
    const char* text,
    uint32_t minValue,
    uint32_t maxValue,
    uint32_t& out) {
  if (minValue > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }

  const char* begin = nullptr;
  const char* end = nullptr;
  NumericParseResult result = numeric_token_bounds(text, begin, end);
  if (!result.ok()) return result;
  result = numeric_validate_integer_token(begin, end);
  if (!result.ok()) return result;
  if (*begin == '-') return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  if (*begin == '+') begin++;

  uint32_t value = 0;
  for (const char* current = begin; current < end; current++) {
    if (*current < '0' || *current > '9') {
      return numeric_parse_result(NUMERIC_PARSE_TRAILING_CHARACTERS);
    }
    const uint8_t digit = static_cast<uint8_t>(*current - '0');
    if (value > (UINT32_MAX - digit) / 10U) {
      return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
    }
    value = value * 10U + digit;
  }
  if (value < minValue || value > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = value;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_fixed_hex_uint16(
    const char* text,
    uint8_t exactDigits,
    uint16_t minValue,
    uint16_t maxValue,
    uint16_t& out) {
  if (minValue > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }
  if (!text || exactDigits == 0 || exactDigits > 4) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  if (strlen(text) != exactDigits) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_FORMAT);
  }

  uint16_t value = 0;
  for (uint8_t index = 0; index < exactDigits; index++) {
    const char current = text[index];
    uint8_t digit = 0;
    if (current >= '0' && current <= '9') digit = current - '0';
    else if (current >= 'a' && current <= 'f') digit = current - 'a' + 10;
    else if (current >= 'A' && current <= 'F') digit = current - 'A' + 10;
    else return numeric_parse_result(NUMERIC_PARSE_INVALID_FORMAT);
    // exactDigits<=4 (проверено выше) гарантирует value*16+digit<=0xFFFF —
    // переполнение uint16 здесь невозможно.
    value = static_cast<uint16_t>(value * 16U + digit);
  }
  if (value < minValue || value > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = value;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult validate_bounded_finite_float(
    float value,
    float minValue,
    float maxValue) {
  if (!isfinite(minValue) || !isfinite(maxValue) || minValue > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }
  if (!isfinite(value)) return numeric_parse_result(NUMERIC_PARSE_NOT_FINITE);
  if (value < minValue || value > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult checked_mul_u32(uint32_t left, uint32_t right, uint32_t& out) {
  const uint64_t product = static_cast<uint64_t>(left) * right;
  if (product > UINT32_MAX) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = static_cast<uint32_t>(product);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult checked_narrow_int32(
    int64_t value,
    int64_t minValue,
    int64_t maxValue,
    int32_t& out) {
  if (minValue < INT32_MIN || maxValue > INT32_MAX || minValue > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }
  if (value < minValue || value > maxValue) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = static_cast<int32_t>(value);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult checked_truncating_product_u32(
    double left,
    double right,
    uint32_t& out) {
  if (!isfinite(left) || !isfinite(right)) {
    return numeric_parse_result(NUMERIC_PARSE_NOT_FINITE);
  }
  if (left <= 0.0 || right <= 0.0) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  const double product = left * right;
  if (!isfinite(product)) {
    return numeric_parse_result(NUMERIC_PARSE_NOT_FINITE);
  }
  if (product < 1.0 || product > static_cast<double>(UINT32_MAX)) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = static_cast<uint32_t>(product);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult checked_rate_to_step_speed(
    double rateLph,
    uint16_t stepsPerMl,
    uint16_t& outSteps) {
  if (stepsPerMl == 0) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  if (!isfinite(rateLph)) return numeric_parse_result(NUMERIC_PARSE_NOT_FINITE);
  if (rateLph <= 0.0f) return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  const double steps = rateLph * stepsPerMl / 3.6;
  if (!isfinite(steps) || steps < 0.5 || steps >= 65535.5) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  outSteps = static_cast<uint16_t>(steps + 0.5);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult checked_step_speed_to_mlh(
    uint16_t stepSpeed,
    uint16_t stepsPerMl,
    uint16_t& outMlh) {
  if (stepSpeed == 0) return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  if (stepsPerMl == 0) return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  const uint64_t numerator = static_cast<uint64_t>(stepSpeed) * 3600U + stepsPerMl / 2U;
  const uint64_t mlh = numerator / stepsPerMl;
  if (mlh == 0 || mlh > UINT16_MAX) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  outMlh = static_cast<uint16_t>(mlh);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline const char* numeric_parse_error_code(NumericParseError error) {
  switch (error) {
    case NUMERIC_PARSE_OK: return "ok";
    case NUMERIC_PARSE_EMPTY: return "empty";
    case NUMERIC_PARSE_INVALID_FORMAT: return "format";
    case NUMERIC_PARSE_TRAILING_CHARACTERS: return "trailing";
    case NUMERIC_PARSE_OUT_OF_RANGE: return "range";
    case NUMERIC_PARSE_NOT_FINITE: return "finite";
    case NUMERIC_PARSE_INVALID_BOUNDS: return "bounds";
    case NUMERIC_PARSE_NOT_ALLOWED: return "allowed";
    case NUMERIC_PARSE_INVALID_ARGUMENT: return "argument";
  }
  return "argument";
}

inline NumericParseResult parse_exact_bool(const char* text, bool& out) {
  const char* begin = nullptr;
  const char* end = nullptr;
  NumericParseResult result = numeric_token_bounds(text, begin, end);
  if (!result.ok()) return result;
  if (end - begin != 1 || (*begin != '0' && *begin != '1')) {
    if ((*begin == '0' || *begin == '1') && end - begin > 1) {
      return numeric_parse_result(NUMERIC_PARSE_TRAILING_CHARACTERS);
    }
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  out = *begin == '1';
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_exact_enum(
    const char* text,
    const int32_t* allowedValues,
    uint8_t allowedCount,
    int32_t& out) {
  if (!allowedValues || allowedCount == 0) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  int32_t value = 0;
  NumericParseResult result = parse_exact_int32(text, value);
  if (!result.ok()) return result;
  for (uint8_t i = 0; i < allowedCount; i++) {
    if (value == allowedValues[i]) {
      out = value;
      return numeric_parse_result(NUMERIC_PARSE_OK);
    }
  }
  return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
}
