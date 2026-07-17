#pragma once

#include <stdint.h>
#include <string.h>

#include "control_numeric_input.h"

struct PowerRegulatorTelemetry {
  float currentValue;
  float targetValue;
  char mode;
  bool hasTarget;
  bool hasMode;
};

inline NumericParseResult parse_kvic_power_response(
    const char* text,
    PowerRegulatorTelemetry& out) {
  if (!text || text[0] == '\0') return numeric_parse_result(NUMERIC_PARSE_EMPTY);
  if (strlen(text) != 8 || text[0] != 'T') {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_FORMAT);
  }

  // Ток (первые 3 hex, легаси-границы 31..2549) — сигнатура реального пакета KVIC.
  // Его невалидность = это не пакет регулятора, бракуем целиком.
  const char currentText[4] = {text[1], text[2], text[3], '\0'};
  uint16_t currentRaw = 0;
  NumericParseResult result = parse_fixed_hex_uint16(
      currentText, 3, 31, 2549, currentRaw);
  if (!result.ok()) return result;

  // Пакет реальный. target (0..2550) и mode ('0'..'3') — best-effort: применяем
  // валидные поля, подозрительное отбрасываем, но пакет НЕ бракуем (иначе через
  // 15с ложно reg_online=false из-за единичного искажённого поля).
  PowerRegulatorTelemetry parsed = {};
  parsed.currentValue = currentRaw / 10.0f;

  const char targetText[4] = {text[4], text[5], text[6], '\0'};
  uint16_t targetRaw = 0;
  if (parse_fixed_hex_uint16(targetText, 3, 0, 2550, targetRaw).ok()) {
    parsed.targetValue = targetRaw / 10.0f;
    parsed.hasTarget = true;
  }
  if (text[7] >= '0' && text[7] <= '3') {
    parsed.mode = text[7];
    parsed.hasMode = true;
  }

  out = parsed;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_sem_power_mode_response(const char* text, char& out) {
  if (!text || text[0] == '\0') return numeric_parse_result(NUMERIC_PARSE_EMPTY);
  if (text[1] != '\0') {
    return numeric_parse_result(NUMERIC_PARSE_TRAILING_CHARACTERS);
  }
  if (text[0] < '0' || text[0] > '2') {
    return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  out = text[0];
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

// telemetry=true — граница ИЗМЕРЕНИЯ (эквивалент 250 В: 62500/R), используется при
// парсинге ответов регулятора (+VO?/+VS?). telemetry=false — граница УСТАВКИ (230 В).
inline NumericParseResult parse_sem_power_value_response(
    const char* text,
    float heaterResistance,
    uint16_t& out,
    bool telemetry = false) {
  if (!text || text[0] == '\0') return numeric_parse_result(NUMERIC_PARSE_EMPTY);
  for (const char* current = text; *current != '\0'; current++) {
    if (*current < '0' || *current > '9') {
      return numeric_parse_result(
          current == text ? NUMERIC_PARSE_INVALID_FORMAT
                          : NUMERIC_PARSE_TRAILING_CHARACTERS);
    }
  }

  float maxPower = 0.0f;
  NumericParseResult result =
      control_power_input_max(true, heaterResistance, maxPower, telemetry);
  if (!result.ok()) return result;
  if (maxPower > UINT16_MAX) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_BOUNDS);
  }
  const uint16_t maxValue = static_cast<uint16_t>(maxPower);
  return parse_bounded_uint16(text, 0, maxValue, out);
}
