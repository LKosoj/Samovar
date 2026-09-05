#pragma once

// Сглаживание атмосферного давления BMP180/BMP085.
//
// BME680/BMP280 сами дают IIR и нормальный oversampling; BMP180 в STANDARD
// на общей I2C даёт выбросы в единицы мм рт. ст. Это сразу видно в
// correctT = (760 - P) * 0.037 (паузы отбора, спиртуозность).
//
// Период опроса BME_getvalue() в задаче SysTicker ~4 с. EMA α=0.25 даёт
// τ ≈ 14 с: шум ±1.5 мм схлопывается до ~0.4 мм (~0.015 °C), суточный ход
// погоды (1–3 мм/час) проходит. Выброс >4 мм за один такт — не погода,
// а сбой чтения: три таких подряд принимаем как новую опору (переподключение
// датчика / первый мусорный отсчёт), иначе фильтр замёрз бы навсегда.

#ifndef BMP180_PRESSURE_EMA_ALPHA
#define BMP180_PRESSURE_EMA_ALPHA 0.25f
#endif
#ifndef BMP180_PRESSURE_OUTLIER_MMHG
#define BMP180_PRESSURE_OUTLIER_MMHG 4.0f
#endif
#ifndef BMP180_PRESSURE_OUTLIER_ACCEPT
#define BMP180_PRESSURE_OUTLIER_ACCEPT 3
#endif
#ifndef BMP180_PRESSURE_MIN_MMHG
#define BMP180_PRESSURE_MIN_MMHG 400.0f
#endif
#ifndef BMP180_PRESSURE_MAX_MMHG
#define BMP180_PRESSURE_MAX_MMHG 900.0f
#endif

struct Bmp180PressureFilter {
  float value;
  bool seeded;
  uint8_t outlierStreak;
};

inline bool bmp180_pressure_raw_plausible(float rawMmHg) {
  return rawMmHg >= BMP180_PRESSURE_MIN_MMHG && rawMmHg <= BMP180_PRESSURE_MAX_MMHG;
}

inline bool bmp180_pressure_filter_update(Bmp180PressureFilter& filter, float rawMmHg) {
  if (!bmp180_pressure_raw_plausible(rawMmHg)) {
    return false;
  }
  if (!filter.seeded) {
    filter.value = rawMmHg;
    filter.seeded = true;
    filter.outlierStreak = 0;
    return true;
  }
  const float delta = rawMmHg - filter.value;
  const bool outlier =
      delta > BMP180_PRESSURE_OUTLIER_MMHG || delta < -BMP180_PRESSURE_OUTLIER_MMHG;
  if (outlier) {
    filter.outlierStreak = static_cast<uint8_t>(filter.outlierStreak + 1);
    if (filter.outlierStreak < BMP180_PRESSURE_OUTLIER_ACCEPT) {
      return false;
    }
    filter.value = rawMmHg;
    filter.outlierStreak = 0;
    return true;
  }
  filter.outlierStreak = 0;
  filter.value += BMP180_PRESSURE_EMA_ALPHA * delta;
  return true;
}
