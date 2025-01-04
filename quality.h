#ifndef QUALITY_H
#define QUALITY_H

#include "Samovar.h"

// Структура для хранения параметров качества
struct QualityParams {
    float stabilityScore;     // Оценка стабильности процесса (0-100)
    float alcoholScore;       // Оценка качества спирта (0-100)
    float tempScore;         // Оценка температурного режима (0-100)
    float overallScore;      // Общая оценка качества (0-100)
    String recommendation;    // Рекомендации по улучшению
};

// Константы для оценки качества
#define IDEAL_STEAM_TEMP 78.3        // Идеальная температура пара для этанола
#define TEMP_TOLERANCE 0.5           // Допустимое отклонение температуры
#define STABILITY_WINDOW_SIZE 60     // Размер окна для оценки стабильности (в секундах)
#define MIN_QUALITY_SCORE 0
#define MAX_QUALITY_SCORE 100

// Буфер для анализа стабильности
float steamTempHistory[STABILITY_WINDOW_SIZE];
uint8_t historyIndex = 0;

// Оценка стабильности температуры пара
float calculateStabilityScore() {
    float maxDiff = 0;
    float avgTemp = 0;
    
    // Вычисляем среднюю температуру
    for (int i = 0; i < STABILITY_WINDOW_SIZE; i++) {
        avgTemp += steamTempHistory[i];
    }
    avgTemp /= STABILITY_WINDOW_SIZE;
    
    // Находим максимальное отклонение
    for (int i = 0; i < STABILITY_WINDOW_SIZE; i++) {
        float diff = abs(steamTempHistory[i] - avgTemp);
        if (diff > maxDiff) maxDiff = diff;
    }
    
    // Оценка стабильности (100 - максимально стабильно)
    float score = 100 - (maxDiff * 20);
    return constrain(score, MIN_QUALITY_SCORE, MAX_QUALITY_SCORE);
}

// Оценка температурного режима
float calculateTempScore() {
    float steamDiff = abs(SteamSensor.avgTemp - IDEAL_STEAM_TEMP);
    float score = 100 - (steamDiff * 10);
    return constrain(score, MIN_QUALITY_SCORE, MAX_QUALITY_SCORE);
}

// Оценка качества спирта на основе температуры пара
float calculateAlcoholScore() {
    float steamTemp = SteamSensor.avgTemp;
    float score = 100;
    
    // Штраф за отклонение от идеальной температуры этанола
    if (steamTemp < 78.0 || steamTemp > 78.6) {
        score -= abs(steamTemp - IDEAL_STEAM_TEMP) * 15;
    }
    
    // Штраф за высокую температуру (признак появления сивушных масел)
    if (steamTemp > 79.0) {
        score -= (steamTemp - 79.0) * 20;
    }
    
    return constrain(score, MIN_QUALITY_SCORE, MAX_QUALITY_SCORE);
}

// Получение текущей оценки качества
QualityParams getQualityAssessment() {
    QualityParams quality;
    
    // Обновляем историю температур
    steamTempHistory[historyIndex] = SteamSensor.avgTemp;
    historyIndex = (historyIndex + 1) % STABILITY_WINDOW_SIZE;
    
    // Рассчитываем оценки
    quality.stabilityScore = calculateStabilityScore();
    quality.alcoholScore = calculateAlcoholScore();
    quality.tempScore = calculateTempScore();
    
    // Общая оценка (взвешенная сумма)
    quality.overallScore = (
        quality.stabilityScore * 0.4 +
        quality.alcoholScore * 0.4 +
        quality.tempScore * 0.2
    );
    
    // Формируем рекомендации
    if (quality.stabilityScore < 70) {
        quality.recommendation = "Нестабильный режим работы. Проверьте охлаждение и мощность.";
    } else if (quality.alcoholScore < 70) {
        quality.recommendation = "Возможно наличие примесей. Рекомендуется уменьшить отбор.";
    } else if (quality.tempScore < 70) {
        quality.recommendation = "Температурный режим не оптимален. Отрегулируйте мощность нагрева.";
    } else {
        quality.recommendation = "Процесс идет нормально. Продолжайте в том же режиме.";
    }
    
    return quality;
}

#endif // QUALITY_H