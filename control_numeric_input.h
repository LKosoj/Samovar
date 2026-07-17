#pragma once

#include <stdint.h>

#include "numeric_parse.h"

static const float CONTROL_VLESS_MIN = 0.001f;
static const float CONTROL_VLESS_MAX = 10000.0f;
// Доверенный диапазон сопротивления ТЭНа. 2..65 Ом - это 26450..813 Вт при 230 В.
// Нижняя граница - не реальный потолок мощности, а заслон от абсурдно малых значений;
// верхняя (65 Ом → 813 Вт) - самый слабый ТЭН, который стоит поддерживать.
// Заводское значение обязано совпадать с NVS_Manager.ino: вне диапазона (старая
// запись в NVS) считаем именно по нему.
static const float CONTROL_HEATER_R_MIN = 2.0f;
static const float CONTROL_HEATER_R_MAX = 65.0f;
static const float CONTROL_HEATER_R_DEFAULT = 15.2f;
static const uint16_t CONTROL_WATER_PWM_MAX = 1023;
// Привязка к STEPPER_MAX_SPEED (Samovar_pin.h) — в прошивке пин-хедер подключён
// раньше этого файла. В standalone-сборке smoke-теста макроса нет: фолбэк-литерал.
#ifdef STEPPER_MAX_SPEED
static_assert(STEPPER_MAX_SPEED == 8000, "CONTROL_STEPPER_SPEED_MAX must track STEPPER_MAX_SPEED");
static const uint16_t CONTROL_STEPPER_SPEED_MAX = STEPPER_MAX_SPEED;
#else
static const uint16_t CONTROL_STEPPER_SPEED_MAX = 8000;
#endif

enum ControlNbkKind : uint8_t {
  CONTROL_NBK_STOP = 0,
  CONTROL_NBK_ABSOLUTE,
  CONTROL_NBK_DECREMENT,
  CONTROL_NBK_INCREMENT,
};

struct ControlNbkCommand {
  ControlNbkKind kind;
  uint16_t stepSpeed;
};

struct ControlI2CPumpInput {
  uint16_t speedSteps;
  uint32_t targetSteps;
  float targetMl;
  uint16_t fillingMl;
  uint16_t fillingMlHour;
  uint16_t stepsPerMl;
};

// Единственное место, где решается, можно ли верить сохранённому сопротивлению.
// Делить на результат безопасно всегда: он не бывает ни нулём, ни NaN. Раньше это
// решение принималось в четырёх местах по-разному (4000 Вт в power_regulator.h,
// 18 Ом в nbk.h, 10 Ом в Samovar.ino), из-за чего одно и то же значение давало
// разную мощность в разных режимах.
inline float trusted_heater_resistance(float heaterResistance) {
  return isfinite(heaterResistance) && heaterResistance >= CONTROL_HEATER_R_MIN &&
                 heaterResistance <= CONTROL_HEATER_R_MAX
             ? heaterResistance
             : CONTROL_HEATER_R_DEFAULT;
}

// semBuild — сборка с регулятором мощности SEM_AVR (уставка/телеметрия в ваттах,
// граница = напряжение² / R). telemetry=false — граница УСТАВКИ (ввод желаемой
// мощности), эквивалент 230 В: 52900 = 230². telemetry=true — граница ИЗМЕРЕНИЯ
// (парсинг ответов регулятора), эквивалент 250 В: 62500 = 250².
inline NumericParseResult control_power_input_max(
    bool semBuild,
    float heaterResistance,
    float& out,
    bool telemetry = false) {
  float value = telemetry ? 250.0f : 230.0f;
  if (semBuild) {
    const float powerCeil = telemetry ? 62500.0f : 52900.0f;
    value = powerCeil / trusted_heater_resistance(heaterResistance);
  }
  if (!isfinite(value) || value <= 0.0f) {
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  out = value;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_control_power(
    const char* text,
    float maxValue,
    float& out) {
  return parse_bounded_float(text, 0.0f, maxValue, out);
}

inline NumericParseResult parse_control_water_pwm(const char* text, uint16_t& out) {
  return parse_bounded_uint16(text, 0, CONTROL_WATER_PWM_MAX, out);
}

inline NumericParseResult parse_control_rate_steps(
    const char* text,
    uint16_t stepsPerMl,
    uint16_t& out) {
  float rate = 0.0f;
  NumericParseResult result = parse_finite_float(text, rate);
  if (!result.ok()) return result;
  if (rate <= 0.0f) return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  return checked_rate_to_step_speed(rate, stepsPerMl, out);
}

inline NumericParseResult parse_control_nbk(
    const char* text,
    uint16_t stepsPerMl,
    ControlNbkCommand& out) {
  ControlNbkCommand parsed = {};
  uint16_t tag = 0;
  // Sentinel-протокол НБК: 0 = стоп, 8000 = декремент, 9000 = инкремент;
  // прочие значения 0<v<8000 трактуются как абсолютная скорость (л/ч).
  NumericParseResult result = parse_bounded_uint16(text, 0, 9000, tag);
  if (result.ok() && (tag == 0 || tag == 8000 || tag == 9000)) {
    parsed.kind = tag == 0 ? CONTROL_NBK_STOP
        : tag == 8000 ? CONTROL_NBK_DECREMENT
                      : CONTROL_NBK_INCREMENT;
  } else {
    double value = 0.0;
    result = parse_finite_double(text, value);
    if (!result.ok()) return result;
    if (!(value > 0.0 && value < 8000.0)) {
      return numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
    }
    parsed.kind = CONTROL_NBK_ABSOLUTE;
    result = checked_rate_to_step_speed(value, stepsPerMl, parsed.stepSpeed);
    if (!result.ok()) return result;
  }
  out = parsed;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_control_i2c_pump(
    const char* speedText,
    const char* volumeText,
    uint16_t stepsPerMl,
    ControlI2CPumpInput& out,
    const char*& errorField) {
  // Контракт: вызывающая сторона (WebServer) обязана передавать УЖЕ разрешённую
  // калибровку — i2c_stepper_steps_per_ml() (фолбэк на I2C_STEPPER_STEP_ML_DEFAULT
  // при SamSetup.StepperStepMlI2C==0), поэтому 0 здесь — только защитная ветка.
  if (stepsPerMl == 0) {
    errorField = "calibration";
    return numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }

  ControlI2CPumpInput parsed = {};
  parsed.stepsPerMl = stepsPerMl;
  NumericParseResult result = parse_control_rate_steps(speedText, stepsPerMl, parsed.speedSteps);
  if (!result.ok()) {
    errorField = "speed";
    return result;
  }
  result = checked_step_speed_to_mlh(parsed.speedSteps, stepsPerMl, parsed.fillingMlHour);
  if (!result.ok()) {
    errorField = "speed";
    return result;
  }

  // /i2cpump принимает дробные мл (как HEAD toFloat): объём — float.
  float volumeMl = 0.0f;
  result = parse_finite_float(volumeText, volumeMl);
  if (!result.ok()) {
    errorField = "volume";
    return result;
  }
  if (volumeMl <= 0.0f || volumeMl > static_cast<float>(UINT16_MAX)) {
    errorField = "volume";
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  result = checked_truncating_product_u32(volumeMl, stepsPerMl, parsed.targetSteps);
  if (!result.ok()) {
    errorField = "volume";
    return result;
  }
  parsed.fillingMl = static_cast<uint16_t>(volumeMl);
  parsed.targetMl = volumeMl;
  out = parsed;
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

inline NumericParseResult parse_control_vless(const char* text, float& out) {
  return parse_bounded_float(text, CONTROL_VLESS_MIN, CONTROL_VLESS_MAX, out);
}

inline NumericParseResult parse_control_calibration_speed(const char* text, uint16_t& out) {
  return parse_bounded_uint16(text, 1, CONTROL_STEPPER_SPEED_MAX, out);
}
