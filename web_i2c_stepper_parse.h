#pragma once

// Шаблон нельзя держать в .ino: Arduino IDE вставляет прототип без
// `template <typename T>`, и компилятор сообщает, что T не объявлен.
template <typename T>
static NumericParseResult parse_i2c_stepper_bounded(
    AsyncWebServerRequest *request,
    const char *name,
    T minValue,
    T maxValue,
    T& target,
    const char*& errorField,
    NumericParseResult (*parser)(const char*, T, T, T&)) {
  const uint8_t count = request_param_count(request, name);
  if (count == 0) return numeric_parse_result(NUMERIC_PARSE_OK);
  if (count != 1) {
    errorField = name;
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  const AsyncWebParameter *param = get_request_param(request, name);
  T parsed = 0;
  NumericParseResult result = param && !param->isFile()
      ? parser(param->value().c_str(), minValue, maxValue, parsed)
      : numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  if (!result.ok()) {
    errorField = name;
    return result;
  }
  target = parsed;
  return result;
}
