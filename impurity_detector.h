#ifndef IMPURITY_DETECTOR_H
#define IMPURITY_DETECTOR_H

#include <Arduino.h>
#include "Samovar.h"

/**
 * Инициализация детектора
 */
void init_impurity_detector() {
  memset(impurityDetector.tempHistory, 0, sizeof(impurityDetector.tempHistory));
  impurityDetector.historyIndex = 0;
  impurityDetector.historySize = 0;
  impurityDetector.lastSampleTime = 0;
  impurityDetector.currentTrend = 0;
  impurityDetector.detectorStatus = 0;
  impurityDetector.correctionFactor = 1.0f;
  impurityDetector.lastCorrectionTime = 0;
}

/**
 * Полный сброс состояния (вызывается при смене программы или ручной установке Т тела)
 */
void reset_impurity_detector() {
  impurityDetector.historySize = 0;
  impurityDetector.historyIndex = 0;
  impurityDetector.currentTrend = 0;
  impurityDetector.detectorStatus = 0;
  impurityDetector.correctionFactor = 1.0f;
  impurityDetector.lastCorrectionTime = millis();
}

/**
 * Добавление температуры в историю
 */
void update_detector_history(float columnTemp) {
  impurityDetector.tempHistory[impurityDetector.historyIndex] = columnTemp;
  impurityDetector.historyIndex = (impurityDetector.historyIndex + 1) % 30;
  if (impurityDetector.historySize < 30) impurityDetector.historySize++;
}

/**
 * Расчет температурного тренда (°C/мин) методом линейной регрессии
 */
float calculate_temperature_trend() {
  uint8_t n = impurityDetector.historySize;
  if (n < 5) return 0.0f; // Нужно минимум 5 точек (10 сек) для расчета тренда

  float sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (uint8_t i = 0; i < n; i++) {
    // Индекс в кольцевом буфере: от самого старого к самому новому
    uint8_t idx = (impurityDetector.historyIndex - n + i + 30) % 30;
    float x = i * 2.0f; // Опрос каждые 2 секунды
    float y = impurityDetector.tempHistory[idx];
    
    sumX += x;
    sumY += y;
    sumXY += x * y;
    sumX2 += x * x;
  }

  float denominator = (n * sumX2 - sumX * sumX);
  if (denominator == 0) return 0.0f;

  float slope = (n * sumXY - sumX * sumY) / denominator;
  return slope * 60.0f; // Изменение в минуту
}

/**
 * Основная логика работы детектора
 */
void process_impurity_detector() {
  // Детектор работает только при включенной авто-коррекции и в режиме отбора (SamovarStatusInt == 10)
  if (!SamSetup.useautospeed || SamovarStatusInt != 10) {
    impurityDetector.detectorStatus = 0;
    impurityDetector.correctionFactor = 1.0f;
    return;
  }

  unsigned long now = millis();
  
  // Сбор данных каждые 2 секунды
  if (now - impurityDetector.lastSampleTime >= 2000) {
    update_detector_history(PipeSensor.avgTemp);
    impurityDetector.currentTrend = calculate_temperature_trend();
    impurityDetector.lastSampleTime = now;
  }

  // Адаптивные пороги на основе плотности насадки (PackDens)
  // Для плотной насадки (100%) порог ниже, для разреженной (60%) выше.
  // Базовый порог предупреждения: 0.02 °C/мин
  float warningThreshold = 0.02f + (100 - SamSetup.PackDens) * 0.0005f;
  float criticalThreshold = warningThreshold * 2.5f;

  // Реакция на тренд
  if (impurityDetector.currentTrend > criticalThreshold) {
    // КРИТИЧЕСКИЙ ПРОСКОК: Ставим на ПАУЗУ
    if (!program_Wait) {
      impurityDetector.detectorStatus = 2; // Breakthrough
      program_Wait = true;
      program_Wait_Type = "(Детектор)";
      pause_withdrawal(true);
      t_min = now + PipeSensor.Delay * 1000;
      set_buzzer(true);
      SendMsg("Детектор: Критический тренд! Пауза отбора.", ALARM_MSG);
    }
  } else if (impurityDetector.currentTrend > warningThreshold) {
    // ПРЕДУПРЕЖДЕНИЕ: Постепенно снижаем скорость
    impurityDetector.detectorStatus = 1; // Correction
    if (now - impurityDetector.lastCorrectionTime > 15000) { // Корректируем не чаще раза в 15 сек
      impurityDetector.correctionFactor *= 0.95f; // Снижаем скорость на 5%
      if (impurityDetector.correctionFactor < 0.7f) impurityDetector.correctionFactor = 0.7f;
      impurityDetector.lastCorrectionTime = now;
      
      // Применяем новую скорость
      float baseSpeedRate = program[ProgramNum].Speed;
      if (baseSpeedRate > 0) {
        float baseStepSpeed = get_speed_from_rate(baseSpeedRate);
        set_pump_speed(baseStepSpeed * impurityDetector.correctionFactor, true);
      }
      
      SendMsg("Детектор: Снижение скорости (тренд " + String(impurityDetector.currentTrend, 3) + ")", NOTIFY_MSG);
    }
  } else if (impurityDetector.currentTrend < (warningThreshold / 2.0f)) {
    // СТАБИЛЬНО: Плавное восстановление скорости
    impurityDetector.detectorStatus = 0; // Stable
    if (impurityDetector.correctionFactor < 1.0f) {
      if (now - impurityDetector.lastCorrectionTime > 30000) { // Восстанавливаем медленно, раз в 30 сек
        impurityDetector.correctionFactor += 0.02f;
        if (impurityDetector.correctionFactor > 1.0f) impurityDetector.correctionFactor = 1.0f;
        impurityDetector.lastCorrectionTime = now;
        
        // Применяем новую скорость
        float baseSpeedRate = program[ProgramNum].Speed;
        if (baseSpeedRate > 0) {
          float baseStepSpeed = get_speed_from_rate(baseSpeedRate);
          set_pump_speed(baseStepSpeed * impurityDetector.correctionFactor, true);
        }
      }
    }
  }
}

/**
 * Автоматический расчет теплопотерь при нагреве до 70°C (п. 5)
 */
void update_heat_loss_calculation() {
  if (heatLossCalculated || BoilerVolume <= 0 || !PowerOn) return;

  // Инициализация замера при достижении 40°C
  if (heatStartMillis == 0 && TankSensor.avgTemp >= 40.0) {
    heatStartMillis = millis();
    heatStartTemp = TankSensor.avgTemp;
  }

  // Финальный расчет при достижении 70°C
  if (heatStartMillis > 0 && TankSensor.avgTemp >= 70.0) {
    float timeSec = (millis() - heatStartMillis) / 1000.0;
    if (timeSec > 60) { // Минимум 1 минута замера для точности
      float deltaT = TankSensor.avgTemp - heatStartTemp;
      
      // Энергия на нагрев: Q = m * c * deltaT (c воды = 4187 Дж/(кг*К))
      // Принимаем плотность сырца за 1 кг/л
      float energyUsed = BoilerVolume * 4187.0f * deltaT;
      float powerEffective = energyUsed / timeSec;
      
      // Теплопотери = Поданная мощность - Эффективная мощность
#ifdef SAMOVAR_USE_POWER
      CurrentHeatLoss = (float)current_power_p - powerEffective;
#else
      CurrentHeatLoss = 0; // Если нет датчика мощности, не можем вычислить потери автоматически
#endif
      
      if (CurrentHeatLoss < 0) CurrentHeatLoss = 0;
      if (CurrentHeatLoss > 1500) CurrentHeatLoss = 1500; // Ограничение здравого смысла
      
      heatLossCalculated = true;
      if (CurrentHeatLoss > 0) {
        SendMsg("Расчет теплопотерь завершен: " + String(CurrentHeatLoss, 0) + " Вт", NOTIFY_MSG);
      } else {
        SendMsg("Теплопотери не определены (проверьте мощность)", WARNING_MSG);
      }
    }
  }
}

#endif

