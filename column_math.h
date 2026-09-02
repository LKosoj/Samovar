#ifndef COLUMN_MATH_H
#define COLUMN_MATH_H

#include <Arduino.h>
#include "Samovar.h"

struct ColumnResults {
  float floodPowerW;
  float workingPowerW;
  float headsPowerW;
  float bodyEndPowerW;
  float tailsPowerW;
  float headsFlowMlH;
  float bodyFlowMaxMlH;
  float bodyFlowMinMlH;
  float bodyEndFlowMlH;
  float tailsFlowMlH;
  float maxFlowMlH; // Паспортный максимум (ФЧ=4 при захлебе)
  float theoreticalPlates;
  // [В8] Рекомендация уже упёрлась в потолок сечения колонны - дальнейшие изменения
  // параметров формы её не сдвинут, пока не изменится диаметр/высота/насадка.
  bool headsSpeedClamped;
  bool bodySpeedClamped;
};

/**
 * Расчет параметров колонны на основе "эталона" из program.htm
 * @param rawMaterial: 0=Фрукты, 1=Зерно, 2=Сахар
 * @param diamInches: внутренний диаметр царги (1.5 / 2 / 3)
 */
inline ColumnResults calculate_column_etalon(uint8_t rawMaterial, float diamInches) {
  ColumnResults res = {};
  
  // 1. Геометрия: диаметр с калькулятора, высота и насадка из профиля
  float diamMm = diamInches * 25.4f;
  float heightCm = SamSetup.ColHeight * 100.0f;
  float packingDensity = (float)SamSetup.PackDens / 100.0f;
  if (isnan(diamMm) || isnan(heightCm) || isnan(packingDensity) ||
      diamMm <= 0 || heightCm <= 0 || packingDensity <= 0) {
    return res;
  }
  
  // Площадь сечения (мм2)
  float radiusMm = diamMm / 2.0f;
  float crossSectionMm2 = PI * radiusMm * radiusMm;
  
  // 2. HETP и тарелки
  float hetpBase = 30.0f; 
  float densityImpact = 0.3f;
  float hetpFactor = 1.0f - (packingDensity - 0.6f) * (densityImpact / 0.4f); 
  float hetp = hetpBase * hetpFactor;
  res.theoreticalPlates = (hetp > 0) ? ((heightCm * 10.0f) / hetp) : 1.0f;
  if (res.theoreticalPlates < 1.0f) res.theoreticalPlates = 1.0f;
  
  // 3. Расчет мощности захлеба
  // [Ф5] Коэффициент 0.58 (раньше 1.15) подогнан под практику: 2" СПН 3.5 при 1.5 м
  // захлёбывается на 1.3-1.9 кВт, 3" - на 3.6-4.5 кВт; эталон шаблонов program_*.txt
  // (173+3 В на ТЭНе 3480 Вт) - около 2 кВт. С 1.15 модель давала 3.8 и 8.5 кВт.
  float pDensityAdj = 1.2f - (packingDensity - 0.6f) * 0.5f;
  float pHeightAdj = pow(heightCm / 50.0f, 0.35f);
  res.floodPowerW = crossSectionMm2 * 0.58f * pDensityAdj * pHeightAdj;

  // 4. Паспортный максимум (для совместимости с логами)
  // Это потенциал железа при ФЧ=4 на мощности захлеба
  res.maxFlowMlH = (res.floodPowerW * EVAPORATION_FACTOR) / (4.0f + 1.0f);
  
  // 5. Рабочие коэффициенты по типу сырья
  float pWorkFactor = 0.75f; // Сахар (default)
  float frMultiplier = 1.2f;
  
  if (rawMaterial == 0) { // Фрукты
    pWorkFactor = 0.48f;
    frMultiplier = 0.85f;
  } else if (rawMaterial == 1) { // Зерно
    pWorkFactor = 0.62f;
    frMultiplier = 1.0f;
  }
  
  res.workingPowerW = res.floodPowerW * pWorkFactor;
  res.headsPowerW = res.floodPowerW * (pWorkFactor * 0.9f);
  res.bodyEndPowerW = res.workingPowerW * 1.05f;
  res.tailsPowerW = res.workingPowerW * 1.10f;
  
  // 6. Потоки пара и жидкости (ФЧ)
  float workingVaporFlowMlH = res.workingPowerW * EVAPORATION_FACTOR;
  float platesRatio = 20.0f / res.theoreticalPlates;
  
  // Головы (ФЧ ~ 250)
  float headsFR = 250.0f * platesRatio;
  res.headsFlowMlH = workingVaporFlowMlH / (1.0f + headsFR);
  
  // Ограничение скорости голов по сечению (0.08 л/ч на мм2)
  float maxHeadsSpeed = crossSectionMm2 * 0.08f;
  if (res.headsFlowMlH > maxHeadsSpeed) {
    res.headsFlowMlH = maxHeadsSpeed;
    res.headsSpeedClamped = true;
  }
  
  // Тело (ФЧ 5-8)
  // [Ф6] Без множителя по тарелкам: для колонны 1.5 м он опускал ФЧ тела до 1.5-2,
  // расчётная скорость всегда упиралась в предел сечения ниже, а сырьё на неё не влияло.
  float bodyFR_Min = 5.0f * frMultiplier;
  float bodyFR_Max = 8.0f * frMultiplier;
  
  res.bodyFlowMaxMlH = workingVaporFlowMlH / (1.0f + bodyFR_Min);
  res.bodyFlowMinMlH = workingVaporFlowMlH / (1.0f + bodyFR_Max);
  
  // Физический предел безопасности (0.65 л/ч на мм2)
  float maxSafeSpeed = crossSectionMm2 * 0.65f;
  if (res.bodyFlowMaxMlH > maxSafeSpeed) {
    res.bodyFlowMaxMlH = maxSafeSpeed;
    res.bodySpeedClamped = true;
  }
  if (res.bodyFlowMinMlH > maxSafeSpeed) {
    res.bodyFlowMinMlH = maxSafeSpeed;
    res.bodySpeedClamped = true;
  }
  
  // Конец тела (60% от макс)
  res.bodyEndFlowMlH = res.bodyFlowMaxMlH * 0.6f;
  
  // Хвосты (70% от конца тела)
  res.tailsFlowMlH = res.bodyEndFlowMlH * 0.7f;
  
  return res;
}

inline ColumnResults calculate_column_etalon(uint8_t rawMaterial) {
  return calculate_column_etalon(rawMaterial, SamSetup.ColDiam);
}

#endif
