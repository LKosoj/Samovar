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
  impurityDetector.tempStdDev = 0.0f;
  impurityDetector.consecutiveRises = 0;
  impurityDetector.lastTemp = 0.0f;
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
  impurityDetector.tempStdDev = 0.0f;
  impurityDetector.consecutiveRises = 0;
  impurityDetector.lastTemp = 0.0f;
}

/**
 * Расчет дисперсии температуры за период (фильтрация выбросов)
 * Используется дисперсия
 * Значение дисперсии пропорционально stdDev^2
 */
float calculate_temperature_variance() {
  uint8_t n = impurityDetector.historySize;
  if (n < 5) return 0.0f; // Нужно минимум 5 точек для расчета

  // Вычисляем среднее значение
  float mean = 0.0f;
  for (uint8_t i = 0; i < n; i++) {
    uint8_t idx = (impurityDetector.historyIndex - n + i + 30) % 30;
    mean += impurityDetector.tempHistory[idx];
  }
  mean /= n;

  // Вычисляем дисперсию
  float variance = 0.0f;
  for (uint8_t i = 0; i < n; i++) {
    uint8_t idx = (impurityDetector.historyIndex - n + i + 30) % 30;
    float diff = impurityDetector.tempHistory[idx] - mean;
    variance += diff * diff;
  }
  variance /= n;

  // Возвращаем дисперсию
  // Для сравнения используем порог в квадрате: если stdDev > 0.1, то variance > 0.01
  return variance;
}

/**
 * Проверка на последовательные повышения температуры (фильтрация выбросов)
 * Возвращает количество последовательных повышений (>= 0.02°C)
 */
uint8_t check_consecutive_rises(float currentTemp) {
  if (impurityDetector.lastTemp > 0.0f && currentTemp > impurityDetector.lastTemp + 0.02f) {
    // Температура повысилась на более чем 0.02°C
    impurityDetector.consecutiveRises++;
  } else {
    // Температура не повысилась или повысилась недостаточно
    impurityDetector.consecutiveRises = 0;
  }
  impurityDetector.lastTemp = currentTemp;
  return impurityDetector.consecutiveRises;
}

/**
 * Добавление температуры в историю
 */
void update_detector_history(float columnTemp) {
  // Проверяем последовательные повышения для фильтрации выбросов
  check_consecutive_rises(columnTemp);
  
  impurityDetector.tempHistory[impurityDetector.historyIndex] = columnTemp;
  impurityDetector.historyIndex = (impurityDetector.historyIndex + 1) % 30;
  if (impurityDetector.historySize < 30) impurityDetector.historySize++;
  
  // Пересчитываем дисперсию (реже, чем каждое обновление - для оптимизации)
  // Вычисляем раз в 10 секунд (каждые 5 обновлений при обновлении раз в 2 сек)
  static uint8_t varianceUpdateCounter = 0;
  if (impurityDetector.historySize >= 5) {
    varianceUpdateCounter++;
    if (varianceUpdateCounter >= 5) { // Каждые 10 секунд
      impurityDetector.tempStdDev = calculate_temperature_variance(); // Храним variance, не stdDev
      varianceUpdateCounter = 0;
    }
  }
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
 * Получить адаптивный порог с учетом дисперсии, скорости отбора и фазы процесса
 * @param variance - дисперсия температуры
 *                   Порог сравнения: variance > 0.01 соответствует stdDev > 0.1°C
 */
float get_adaptive_threshold(float baseThreshold, float variance, float volumePerHour, String processPhase) {
  float adaptiveThreshold = baseThreshold;
  
  // 1. Корректировка на основе дисперсии (стандартного отклонения)
  // Если дисперсия высокая, увеличиваем порог пропорционально
  // variance > 0.01 соответствует stdDev > 0.1°C (0.1^2 = 0.01)
  // variance > 0.36 соответствует stdDev > 0.6°C (0.6^2 = 0.36)
  if (variance > 0.01f) {
    // Линейная аппроксимация: при variance = 0.01 -> фактор 1.0, при variance = 0.36 -> фактор 2.0
    float varianceFactor = 1.0f + (variance - 0.01f) * (1.0f / 0.35f); // (2.0-1.0)/(0.36-0.01)
    if (varianceFactor > 2.0f) varianceFactor = 2.0f; // Максимум удвоение
    adaptiveThreshold *= varianceFactor;
  }
  
  // 2. Корректировка на основе скорости отбора
  // При высокой скорости отбора (> 0.5 л/ч) порог должен быть выше
  // При низкой скорости (< 0.1 л/ч) порог может быть ниже
  if (volumePerHour > 0.1f) {
    if (volumePerHour > 0.5f) {
      // Высокая скорость - увеличиваем порог на 30%
      adaptiveThreshold *= 1.3f;
    } else if (volumePerHour < 0.2f) {
      // Низкая скорость - уменьшаем порог на 15%
      adaptiveThreshold *= 0.85f;
    }
  }
  
  // 3. Корректировка на основе фазы процесса
  // Головы: более чувствительный (порог * 0.9)
  // Тело: стандартный порог
  // Хвосты: менее чувствительный (порог * 1.2)
  if (processPhase == "H") {
    adaptiveThreshold *= 0.9f; // Головы - более чувствительный
  } else if (processPhase == "T") {
    adaptiveThreshold *= 1.2f; // Хвосты - менее чувствительный (больше примесей ожидается)
  }
  // "B" (тело) и "C" (предзахлеб) - без изменений
  
  return adaptiveThreshold;
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

  // Детектор не работает во время программы типа "P" (Пауза)
  // Во время паузы отбор должен быть полностью остановлен и не возобновляться детектором
  if (ProgramNum < 30 && program[ProgramNum].WType == "P") {
    impurityDetector.detectorStatus = 0;
    // Не меняем correctionFactor, чтобы сохранить состояние на момент паузы
    return;
  }

  // Детектор не работает во время ручной паузы пользователя (PauseOn)
  // Пользователь может поставить на паузу по любой причине, и детектор не должен вмешиваться
  if (PauseOn) {
    impurityDetector.detectorStatus = 0;
    // Не меняем correctionFactor, чтобы сохранить состояние на момент паузы
    return;
  }

  unsigned long now = millis();
  
  // Сбор данных каждые 2 секунды
  if (now - impurityDetector.lastSampleTime >= 2000) {
    update_detector_history(PipeSensor.avgTemp);
    impurityDetector.currentTrend = calculate_temperature_trend();
    impurityDetector.lastSampleTime = now;
  }

  // Базовый порог на основе плотности насадки (PackDens)
  // Для плотной насадки (100%) порог ниже, для разреженной (60%) выше.
  float baseWarningThreshold = 0.03f + (100 - SamSetup.PackDens) * 0.0005f;
  
  // Получаем текущие параметры процесса
  float currentVolumePerHour = (ProgramNum < 30 && program[ProgramNum].Speed > 0) 
                                ? program[ProgramNum].Speed 
                                : 0.24f; // Дефолтное значение
  String processPhase = (ProgramNum < 30 && program[ProgramNum].WType.length() > 0) 
                         ? program[ProgramNum].WType 
                         : "B"; // По умолчанию тело
  
  // Адаптивный порог с учетом дисперсии, скорости отбора и фазы процесса
  float warningThreshold = get_adaptive_threshold(
    baseWarningThreshold, 
    impurityDetector.tempStdDev, 
    currentVolumePerHour, 
    processPhase
  );
  
  float criticalThreshold = warningThreshold * 2.5f;
  
  // Гистерезис для предотвращения частых переключений (15% от адаптивного порога)
  float hysteresis = warningThreshold * 0.15f;
  float correctionThreshold = warningThreshold + hysteresis;  // Порог для снижения скорости
  float recoveryThreshold = warningThreshold - hysteresis;    // Порог для восстановления скорости
  
  // Фильтрация выбросов: учитываем только устойчивые тренды
  // Игнорируем единичные всплески, если нет 3+ последовательных повышений
  bool isValidTrend = true;
  if (impurityDetector.consecutiveRises < 3 && impurityDetector.currentTrend > correctionThreshold) {
    // Тренд есть, но нет устойчивой последовательности повышений
    // Снижаем чувствительность на 30% для таких случаев
    correctionThreshold *= 1.3f;
    if (impurityDetector.currentTrend < correctionThreshold) {
      isValidTrend = false; // Игнорируем этот тренд как выброс
    }
  }

  // Реакция на тренд (только если тренд валидный или критический)
  if (impurityDetector.currentTrend > criticalThreshold) {
    // КРИТИЧЕСКИЙ ПРОСКОК: Ставим на ПАУЗУ (всегда реагируем на критический)
    // Но только если нет ручной паузы пользователя
    if (!program_Wait && !PauseOn) {
      impurityDetector.detectorStatus = 2; // Breakthrough
      program_Wait = true;
      program_Wait_Type = "(Детектор)";
      pause_withdrawal(true);
      t_min = now + PipeSensor.Delay * 1000;
      set_buzzer(true);
      SendMsg("Детектор: Критический тренд! Пауза отбора. (тренд: " + 
              String(impurityDetector.currentTrend, 3) + ", variance: " + 
              String(impurityDetector.tempStdDev, 4) + ")", ALARM_MSG);
    }
  } else if (isValidTrend && impurityDetector.currentTrend > correctionThreshold) {
    // ПРЕДУПРЕЖДЕНИЕ: Постепенно снижаем скорость
    // Но только если нет ручной паузы пользователя
    if (!PauseOn) {
      impurityDetector.detectorStatus = 1; // Correction
      if (now - impurityDetector.lastCorrectionTime > 25000) { // Корректируем не чаще раза в 25 сек (увеличено с 15)
        impurityDetector.correctionFactor *= 0.95f; // Снижаем скорость на 5%
        if (impurityDetector.correctionFactor < 0.7f) impurityDetector.correctionFactor = 0.7f;
        impurityDetector.lastCorrectionTime = now;
        
        // Применяем новую скорость
        float baseSpeedRate = program[ProgramNum].Speed;
        if (baseSpeedRate > 0) {
          float baseStepSpeed = get_speed_from_rate(baseSpeedRate);
          set_pump_speed(baseStepSpeed * impurityDetector.correctionFactor, true);
        }
        
        SendMsg("Детектор: Снижение скорости (тренд " + String(impurityDetector.currentTrend, 3) + 
                ", порог: " + String(warningThreshold, 3) + ", variance: " + 
                String(impurityDetector.tempStdDev, 4) + ")", NOTIFY_MSG);
      }
    }
  } else if (impurityDetector.currentTrend < recoveryThreshold) {
    // СТАБИЛЬНО: Плавное восстановление скорости (используется гистерезис вместо порога/2)
    impurityDetector.detectorStatus = 0; // Stable
    // Восстанавливаем скорость только если нет паузы (ни ручной, ни автоматической от детектора)
    // Если пользователь поставил на паузу вручную, или есть автоматическая пауза - не возобновляем
    if (impurityDetector.correctionFactor < 1.0f && !PauseOn && !program_Wait) {
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
  // Зона между recoveryThreshold и correctionThreshold - зона нечувствительности (гистерезис)
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

