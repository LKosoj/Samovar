#ifndef IMPURITY_DETECTOR_H
#define IMPURITY_DETECTOR_H

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include <math.h>

// Грейс-период после старта строки/ручного продолжения (мс)
static unsigned long detector_grace_until = 0;
// Окно блокировки детектора после ручного продолжения (мс)
static unsigned long detector_manual_override_until = 0;
// Стабилизация пара перед стартом детектора
static uint32_t detector_steam_stable_since = 0;
enum DetectorSteamStabilityReason : uint8_t {
  DETECTOR_STEAM_FILLING = 0,
  DETECTOR_STEAM_RANGE_HIGH,
  DETECTOR_STEAM_VARIANCE_HIGH,
  DETECTOR_STEAM_HOLDING,
  DETECTOR_STEAM_READY,
};
static DetectorSteamStabilityReason detector_steam_stability_reason = DETECTOR_STEAM_FILLING;
static float detector_steam_stability_span = 0.0f;
static float detector_steam_stability_variance = 0.0f;
// Минимальное число точек истории для критического тренда
static const uint8_t DETECTOR_MIN_HISTORY_CRITICAL = 10;

// Шаг квантования DS18B20 в 12-битном режиме (sensorinit.h: setResolution(addr, 12)).
// Датчик физически не может выдать изменение мельче этого значения, поэтому все пороги,
// связанные с шумом температуры, считаются от него, а не от абстрактных долей градуса.
static const float DETECTOR_SENSOR_QUANT_C = 0.0625f;

// Интервал между точками истории. Показания DS обновляются раз в секунду
// (triggerSysTicker), в одну точку усредняются все чтения за интервал: усреднение
// четырёх чтений снижает шум наклона примерно вчетверо, а окно 30 * 4 с = 2 минуты
// делает порог 0.04 °C/мин измеримым (за 58-секундное окно он был мельче кванта датчика).
static const uint32_t DETECTOR_SAMPLE_INTERVAL_MS = 4000UL;

// Порог стабильности пара и окно стабилизации. Раньше здесь стояли 0.1 °C размаха и
// дисперсия 0.000625 (СКО 0.4 кванта) — ниже собственного шума квантования: температура,
// «дышащая» между двумя соседними квантами, давала дисперсию 0.000977 и гейт не проходил
// НИКОГДА, из-за чего детектор на первой строке тела молча не включался.
static const float DETECTOR_STEAM_STABLE_SPAN = DETECTOR_SENSOR_QUANT_C * 3.0f;
static const float DETECTOR_STEAM_STABLE_VARIANCE =
    DETECTOR_SENSOR_QUANT_C * DETECTOR_SENSOR_QUANT_C;
static const uint32_t DETECTOR_STEAM_STABLE_MS = 600000UL; // 10 минут

// Порог предупреждения. Раньше базовое значение задавалось вручную через плотность
// насадки: 0.03 + (100 - PackDens) * 0.0005, то есть весь диапазон настройки двигал порог
// на ±25%, тогда как автоматические поправки в get_adaptive_threshold дают разброс в разы.
// Теперь база измеряется: детектор набирает собственный фоновый шум тренда на спокойном
// участке строки и ставит порог по нему. DEFAULT используется, пока фон не набран.
static const float DETECTOR_DEFAULT_WARNING_TREND = 0.04f;
static const float DETECTOR_MIN_WARNING_TREND = 0.02f;
static const float DETECTOR_MAX_WARNING_TREND = 0.15f;
// Сколько замеров фона набрать (60 * 4 с = 4 минуты) и сколько сигм заложить в порог
static const uint16_t DETECTOR_BG_SAMPLES = 60;
static const float DETECTOR_BG_SIGMA_K = 4.0f;

// Сколько замеров подряд тренд должен держаться выше критического порога, чтобы отбор
// был остановлен. Критическая ветка — единственная, которая ничем не фильтровалась:
// одиночный щелчок кванта датчика посреди окна даёт наклон 0.094 °C/мин и этого хватало
// для паузы отбора при плотности насадки от 85%.
static const uint8_t DETECTOR_CRITICAL_CONFIRM = 2;

static const float HEAT_LOSS_MIN_DELTA_T = 15.0f;

// [M-29] Предыдущее состояние источника датчика (для детекции смены)
// -1 = не инициализировано, 0 = пар, 1 = царга
static int8_t detector_last_pipe_sensor = -1;

// Накопитель усреднения между точками истории: сумма показаний и их количество.
// detector_last_ds_counter отсекает повторные чтения одного и того же значения —
// process_impurity_detector() вызывается из loop() сотни раз в секунду, а датчик
// обновляется раз в секунду.
static double detector_avg_sum = 0.0;
static uint16_t detector_avg_count = 0;
static uint32_t detector_last_ds_counter = 0;

// Замер фонового шума тренда на спокойном участке строки: сумма, сумма квадратов,
// счётчик. detector_bg_threshold = 0 означает «фон ещё не набран, порог берём дефолтный».
static double detector_bg_sum = 0.0;
static double detector_bg_sumsq = 0.0;
static uint16_t detector_bg_count = 0;
static float detector_bg_threshold = 0.0f;

// [П3-1] Базовая скорость отбора текущей строки программы для детектора примесей.
// Обновляется при старте строки (run_program) и внешних/пользовательских вызовах
// set_pump_speed(updateBase=true). Корректировки самого детектора базу НЕ трогают
// (updateBase=false), чтобы не портить program[N].Speed при резюме после паузы.
volatile float CurrentBaseSpeedRate = 0.0f;

// [П3-2] Счетчик стоп-пауз текущей строки программы (по датчику пара/царги или от
// детектора), кумулятивный за время строки (не только подряд идущие). Сбрасывается
// при смене строки и при срабатывании лимита (авто-снижение скорости).
volatile uint8_t RowStopPauseCount = 0;

// [Ф3] Отложенный захват Т тела. При старте строки B/C с ненулевой мощностью
// (run_program) старая Т тела обнуляется: колонна ещё не отреагировала на новую
// мощность, и захват через 0.5 с дал бы опору от прежнего режима. Новая Т тела берётся
// в withdrawal(), когда пар устоялся (is_steam_stable()) или истёк этот срок
// (DETECTOR_STEAM_STABLE_MS от старта строки - когда детектор выключен, история не
// ведётся и стабильность не наступает никогда). 0 = захват не ожидается.
static uint32_t body_temp_capture_deadline = 0;

// [Ф4] Т тела первого захвата в текущей строке - опора для предела автоподъёма
// BODY_TEMP_AUTOSET_MAX_RISE. Обнуляется при старте строки и ручной установке Т тела.
static float body_temp_row_base = 0.0f;

// [Ф4] Разрешён ли ещё автоподъём Т тела в этой строке: пар не ушёл выше опоры
// больше, чем на BODY_TEMP_AUTOSET_MAX_RISE. Без опоры (0) - не разрешён.
inline bool body_temp_autoset_allowed() {
  return body_temp_row_base > 0.0f &&
         SteamSensor.avgTemp <= body_temp_row_base + BODY_TEMP_AUTOSET_MAX_RISE;
}

// Сброс накопителя усреднения и замера фона. Оба привязаны к истории: если история
// очищена, усреднять и калиброваться надо заново.
inline void detector_reset_sampling() {
  detector_avg_sum = 0.0;
  detector_avg_count = 0;
  detector_bg_sum = 0.0;
  detector_bg_sumsq = 0.0;
  detector_bg_count = 0;
  detector_bg_threshold = 0.0f;
}

// Сброс истории температур и накопителей детектора: применяется при инициализации,
// полном сбросе и смене датчика-источника (пар/царга). Очищает буферы истории и
// времени выборки, обнуляет статистику окна и lastSampleTime — для немедленного
// начала сбора данных.
inline void detector_reset_history() {
  memset(impurityDetector.tempHistory, 0, sizeof(impurityDetector.tempHistory));
  memset(impurityDetector.sampleTime, 0, sizeof(impurityDetector.sampleTime));
  impurityDetector.historyIndex = 0;
  impurityDetector.historySize = 0;
  impurityDetector.historySum = 0.0f;
  impurityDetector.historySumSquares = 0.0f;
  impurityDetector.historyMin = 0.0f;
  impurityDetector.historyMax = 0.0f;
  impurityDetector.lastSampleTime = 0;
  impurityDetector.currentTrend = 0;
  impurityDetector.criticalConfirm = 0;
  impurityDetector.tempVariance = 0.0f;
  detector_reset_sampling();
}

// Полный сброс состояния детектора поверх detector_reset_history(): дополнительно
// обнуляет статус, коэффициент коррекции, время последней коррекции (задаёт
// вызывающий — 0 при инициализации, millis() при полном сбросе) и состояние
// стабилизации пара / выбора датчика.
inline void detector_reset_full(unsigned long lastCorrectionTimeValue) {
  detector_reset_history();
  impurityDetector.detectorStatus = 0;
  impurityDetector.correctionFactor = 1.0f;
  impurityDetector.lastCorrectionTime = lastCorrectionTimeValue;
  detector_steam_stable_since = 0;
  detector_steam_stability_reason = DETECTOR_STEAM_FILLING;
  detector_steam_stability_span = 0.0f;
  detector_steam_stability_variance = 0.0f;
  detector_last_pipe_sensor = -1; // [M-29] сброс выбора датчика
}

/**
 * Инициализация детектора
 */
void init_impurity_detector() {
  detector_reset_full(0);
}

void reset_heat_loss_calculation() {
  CurrentHeatLoss = 0;
  heatStartMillis = 0;
  heatStartTemp = 0;
  heatLossCalculated = false;
}

/**
 * Полный сброс состояния (вызывается при смене программы или ручной установке Т тела)
 */
void reset_impurity_detector() {
  detector_reset_full(millis());
}

// Вызывается при старте новой строки программы
void detector_on_program_start() {
  detector_grace_until = millis() + 30000UL; // общий грейс-период
  detector_manual_override_until = 0;
  detector_steam_stable_since = 0;
  detector_steam_stability_reason = DETECTOR_STEAM_FILLING;
  detector_steam_stability_span = 0.0f;
  detector_steam_stability_variance = 0.0f;
}

// Вызывается при ручном продолжении отбора
void detector_on_manual_resume() {
  reset_impurity_detector();
  detector_manual_override_until = millis() + 60000UL;
  detector_grace_until = detector_manual_override_until;
}

// Вызывается при авто-продолжении после детекторной паузы
void detector_on_auto_resume() {
  reset_impurity_detector();
  detector_grace_until = millis() + 30000UL;
  detector_manual_override_until = 0;
}

/**
 * Дисперсия температуры в окне истории.
 * Считается по инкрементальным суммам, которые ведёт update_detector_history():
 * отдельный цикл по буферу для той же величины больше не нужен.
 */
float detector_history_variance() {
  const uint8_t n = impurityDetector.historySize;
  if (n < 5) return 0.0f; // Нужно минимум 5 точек для расчета

  const double mean = impurityDetector.historySum / n;
  double variance = impurityDetector.historySumSquares / n - mean * mean;
  if (variance < 0.0) variance = 0.0; // защита от накопленной ошибки округления
  return static_cast<float>(variance);
}

/**
 * Проверка стабилизации температуры пара по скользящему диапазону и дисперсии.
 */
bool is_steam_stable() {
  const uint32_t now = millis();
  const uint8_t count = impurityDetector.historySize;
  if (count < 30) {
    detector_steam_stable_since = 0;
    detector_steam_stability_reason = DETECTOR_STEAM_FILLING;
    detector_steam_stability_span = 0.0f;
    detector_steam_stability_variance = 0.0f;
    return false;
  }

  const float variance = detector_history_variance();
  detector_steam_stability_span =
      impurityDetector.historyMax - impurityDetector.historyMin;
  detector_steam_stability_variance = variance;

  if (detector_steam_stability_span > DETECTOR_STEAM_STABLE_SPAN) {
    detector_steam_stable_since = 0;
    detector_steam_stability_reason = DETECTOR_STEAM_RANGE_HIGH;
    return false;
  }
  if (variance > static_cast<double>(DETECTOR_STEAM_STABLE_VARIANCE)) {
    detector_steam_stable_since = 0;
    detector_steam_stability_reason = DETECTOR_STEAM_VARIANCE_HIGH;
    return false;
  }
  if (detector_steam_stable_since == 0) detector_steam_stable_since = now;
  if (now - detector_steam_stable_since < DETECTOR_STEAM_STABLE_MS) {
    detector_steam_stability_reason = DETECTOR_STEAM_HOLDING;
    return false;
  }
  detector_steam_stability_reason = DETECTOR_STEAM_READY;
  return true;
}

/**
 * Добавление температуры в историю
 * @param columnTemp - усреднённое показание за интервал между замерами
 * @param sampleMillis - момент замера, по нему считается наклон в calculate_temperature_trend
 */
void update_detector_history(float columnTemp, uint32_t sampleMillis) {
  if (impurityDetector.historySize == 30) {
    const float replaced =
        impurityDetector.tempHistory[impurityDetector.historyIndex];
    impurityDetector.historySum -= replaced;
    impurityDetector.historySumSquares -= replaced * replaced;
  }
  impurityDetector.tempHistory[impurityDetector.historyIndex] = columnTemp;
  impurityDetector.sampleTime[impurityDetector.historyIndex] = sampleMillis;
  impurityDetector.historyIndex = (impurityDetector.historyIndex + 1) % 30;
  if (impurityDetector.historySize < 30) impurityDetector.historySize++;
  impurityDetector.historySum += columnTemp;
  impurityDetector.historySumSquares += columnTemp * columnTemp;

  const uint8_t oldest =
      (impurityDetector.historyIndex - impurityDetector.historySize + 30) % 30;
  impurityDetector.historyMin = impurityDetector.tempHistory[oldest];
  impurityDetector.historyMax = impurityDetector.tempHistory[oldest];
  for (uint8_t i = 1; i < impurityDetector.historySize; i++) {
    const uint8_t index = (oldest + i) % 30;
    const float value = impurityDetector.tempHistory[index];
    if (value < impurityDetector.historyMin) impurityDetector.historyMin = value;
    if (value > impurityDetector.historyMax) impurityDetector.historyMax = value;
  }

  // Дисперсия считается из тех же инкрементальных сумм за O(1), поэтому обновляется
  // каждый замер (раньше был отдельный цикл по буферу и счётчик "раз в 5 обновлений").
  impurityDetector.tempVariance = detector_history_variance();
}

/**
 * Расчет температурного тренда (°C/мин) методом линейной регрессии
 */
float calculate_temperature_trend() {
  uint8_t n = impurityDetector.historySize;
  if (n < 5) return 0.0f; // Нужно минимум 5 точек для расчета тренда

  const uint8_t oldest = (impurityDetector.historyIndex - n + 30) % 30;
  const uint32_t baseTime = impurityDetector.sampleTime[oldest];

  float sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (uint8_t i = 0; i < n; i++) {
    // Индекс в кольцевом буфере: от самого старого к самому новому
    uint8_t idx = (oldest + i) % 30;
    // Секунды от начала окна по ФАКТИЧЕСКОМУ времени замера. Раньше здесь стояло
    // x = i * 2.0f — предположение "точки идут ровно через 2 секунды". Реальный шаг
    // плавает (загруженный веб-сервер, запись на файловую систему), и наклон искажался.
    // Разность беззнаковых корректна и при переполнении millis().
    float x = static_cast<float>(impurityDetector.sampleTime[idx] - baseTime) / 1000.0f;
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
 * Один такт сбора данных: накопить показание датчика и, если интервал истёк,
 * положить в историю усреднённое значение и пересчитать тренд.
 * @return true, если добавлена новая точка (тренд пересчитан)
 *
 * Усреднение здесь — ключевая часть: показания DS18B20 квантованы шагом 0.0625 °C,
 * и на коротком окне тренд получался ступенчатым (либо ровно 0, либо сразу ~0.09 °C/мин).
 * Среднее нескольких чтений даёт дробное значение между квантами.
 */
bool detector_sample_tick(float detectorTemp, uint32_t now) {
  // Одно и то же показание датчика не должно попадать в среднее несколько раз:
  // детектор вызывается из loop() сотни раз в секунду, датчик обновляется раз в секунду.
  const uint32_t dsCounter = DSUpdateCounter;
  if (dsCounter != detector_last_ds_counter) {
    detector_last_ds_counter = dsCounter;
    detector_avg_sum += detectorTemp;
    detector_avg_count++;
  }

  if (now - impurityDetector.lastSampleTime < DETECTOR_SAMPLE_INTERVAL_MS) return false;

  // Если новых чтений датчика не было (сбои опроса), берём текущее значение как есть.
  const float sample = (detector_avg_count > 0)
                           ? static_cast<float>(detector_avg_sum / detector_avg_count)
                           : detectorTemp;
  detector_avg_sum = 0.0;
  detector_avg_count = 0;

  update_detector_history(sample, now);
  impurityDetector.currentTrend = calculate_temperature_trend();
  impurityDetector.lastSampleTime = now;
  return true;
}

/**
 * Замер фонового шума тренда. Пока детектор спокоен, копим среднее и разброс
 * собственных показаний тренда, а по набору статистики выставляем порог
 * предупреждения = средний фон + DETECTOR_BG_SIGMA_K сигм. Это заменяет ручной
 * ввод плотности насадки: разброс учитывает и шум датчика, и то, как дышит колонна.
 */
void detector_update_background() {
  if (detector_bg_count >= DETECTOR_BG_SAMPLES) return; // фон уже набран
  if (impurityDetector.historySize < 30) return;        // окно ещё не заполнено

  const double trend = impurityDetector.currentTrend;
  detector_bg_sum += trend;
  detector_bg_sumsq += trend * trend;
  detector_bg_count++;
  if (detector_bg_count < DETECTOR_BG_SAMPLES) return;

  const double mean = detector_bg_sum / detector_bg_count;
  double variance = detector_bg_sumsq / detector_bg_count - mean * mean;
  if (variance < 0.0) variance = 0.0;
  // Падающая температура не должна занижать порог, поэтому средний фон снизу режем нулём.
  const double base = (mean > 0.0 ? mean : 0.0) + DETECTOR_BG_SIGMA_K * sqrt(variance);

  float threshold = static_cast<float>(base);
  if (threshold < DETECTOR_MIN_WARNING_TREND) threshold = DETECTOR_MIN_WARNING_TREND;
  if (threshold > DETECTOR_MAX_WARNING_TREND) threshold = DETECTOR_MAX_WARNING_TREND;
  detector_bg_threshold = threshold;
}

/**
 * Получить адаптивный порог с учетом дисперсии, скорости отбора и фазы процесса
 * @param variance - дисперсия температуры
 *                   Порог сравнения: variance > 0.01 соответствует stdDev > 0.1°C
 */
float get_adaptive_threshold(float baseThreshold, float variance, float volumePerHour, ProgramType processPhase) {
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
  // Тело: стандартный порог
  // Хвосты: менее чувствительный (больше примесей ожидается)
  // Головы ('H') сюда не попадают - на них детектор только наблюдает
  // (см. process_impurity_detector)
  if (processPhase == 'T') {
    adaptiveThreshold *= 1.2f; // Хвосты - менее чувствительный (больше примесей ожидается)
  }
  // "B" (тело) и "C" (предзахлеб) - без изменений

  return adaptiveThreshold;
}

/**
 * Проверка, является ли текущая программа первой программой отбора тела (B/C) после голов (H)
 * Учитывает возможность наличия программ паузы (P) между H и B/C
 * @return true если текущая программа - первая B/C после H, false иначе
 */
bool is_first_body_program_after_heads(uint8_t currentProgram, ProgramType currentType) {
  // Текущая программа должна быть B или C
  if (currentProgram >= PROGRAM_MAX || (currentType != 'B' && currentType != 'C')) {
    return false;
  }

  // Тело первой строкой программы: голов перед ним нет по определению. Ниже цикл дал бы
  // тот же ответ (i стартует с -1 и сразу проваливает условие), но намерение читалось бы
  // только вместе с типом счётчика. Проверка явная, чтобы это не приходилось выводить.
  if (currentProgram == 0) {
    return false;
  }

  // Проверяем предыдущие программы, пропуская P
  for (int i = currentProgram - 1; i >= 0; i--) {
    ProgramType previousType = program_type_at(static_cast<uint8_t>(i));
    if (program_type_empty(previousType)) {
      break; // Конец списка программ
    }

    // Пропускаем программы паузы
    if (previousType == 'P') {
      continue;
    }

    // Если нашли программу отбора голов - это первая программа тела
    if (previousType == 'H') {
      return true;
    }

    // Если нашли другую программу (не H и не P), то это не первая программа тела
    // Например, если между предыдущей B/C и текущей был другой тип
    return false;
  }

  // Если не нашли H в предыдущих программах - это не первая программа тела после голов
  return false;
}

/**
 * [П3-2] Политика реакции на повторяющиеся стоп-паузы одной строки программы:
 * если подряд накопилось PROGRAM_ROW_STOP_PAUSE_LIMIT пауз (по датчику пара/царги
 * или от детектора) без смены строки - снижаем базовую скорость строки на фиксированный
 * процент, чтобы колонна не продолжала раз за разом упираться в тот же предел.
 */
inline void apply_row_stop_pause_policy() {
  if (RowStopPauseCount < PROGRAM_ROW_STOP_PAUSE_LIMIT) return;
  RowStopPauseCount = 0;
  if (CurrentBaseSpeedRate <= 0) return;
  float reducedRate = CurrentBaseSpeedRate * (1.0f - PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT / 100.0f);
  float reducedStepSpeed = get_speed_from_rate(reducedRate);
  set_pump_speed(reducedStepSpeed, false, true);  // continue_process=false: насос остаётся стоять, меняем только базу на будущее резюме
  SendMsg("Строка №" + String(ProgramNum + 1) + ": " + String(PROGRAM_ROW_STOP_PAUSE_LIMIT) +
          " стоп-паузы подряд. Базовая скорость снижена до " + String(reducedRate, 2) + " л/ч.", ALARM_MSG);
}

/**
 * Базовый порог предупреждения (°C/мин) до адаптивных поправок.
 * Пока фон не набран — фиксированный дефолт, дальше — измеренный шум тренда.
 */
inline float detector_base_warning_threshold() {
  return (detector_bg_threshold > 0.0f) ? detector_bg_threshold
                                        : DETECTOR_DEFAULT_WARNING_TREND;
}

/**
 * Полный порог предупреждения с адаптивными поправками.
 * Единственное место, где он считается: и рабочая логика в process_impurity_detector,
 * и порог восстановления для withdrawal() зовут именно эту функцию. Раньше формула
 * была продублирована, и правка в одном месте разводила пороги реакции и возврата.
 */
inline float detector_warning_threshold() {
  const ProgramType currentType = program_type_at(ProgramNum);
  const float currentVolumePerHour = (CurrentBaseSpeedRate > 0) ? CurrentBaseSpeedRate : 0.24f;
  const ProgramType processPhase = !program_type_empty(currentType) ? currentType : 'B';
  return get_adaptive_threshold(detector_base_warning_threshold(),
                                impurityDetector.tempVariance,
                                currentVolumePerHour, processPhase);
}

/**
 * [П3-4] Порог восстановления тренда.
 * Используется withdrawal() для проверки "тренд устоялся" перед резюме
 * после паузы, поставленной детектором.
 */
inline float detector_current_recovery_threshold() {
  const float warningThreshold = detector_warning_threshold();
  return warningThreshold - warningThreshold * 0.15f;
}

inline bool detector_trend_settled() {
  return impurityDetector.currentTrend < detector_current_recovery_threshold();
}

/**
 * @brief [П3-7] Шаг коррекции (доля 0.01-0.20) на основе SamSetup.autospeed
 * (0-99%, "Процент изменения скорости"). 0/не задано -> дефолт 5%. Клампим
 * до 20%, чтобы одна коррекция не могла резко обрушить скорость (веб-форма
 * допускает до 99%, а это поле раньше было полностью мёртвым/непроверенным).
 */
inline float get_detector_correction_step() {
  uint8_t pct = SamSetup.autospeed;
  if (pct < 1) pct = 5;
  if (pct > 20) pct = 20;
  return pct / 100.0f;
}

// Пересчёт и применение скорости насоса под текущий correctionFactor детектора.
// Общий код для веток коррекции и восстановления скорости в process_impurity_detector().
// [fix П32] Возвращает, ПРИМЕНИЛАСЬ ли скорость фактически. set_pump_speed() (logic.h)
// молча отвергает значение ниже 1 шага/с и ничего не сообщает о факте отказа - здесь
// тот же порог проверяется заранее, чтобы вызывающий код не считал коррекцию успешной,
// когда насос её не принял.
inline bool apply_detector_speed_correction(float baseSpeedRate) {
  if (baseSpeedRate <= 0) return false;
  float baseStepSpeed = get_speed_from_rate(baseSpeedRate);
  float targetStepSpeed = baseStepSpeed * impurityDetector.correctionFactor;
  if (targetStepSpeed < 1.0f) return false;  // тот же порог отказа, что и в set_pump_speed()
  set_pump_speed(targetStepSpeed, true, false);
  return true;
}

/**
 * Основная логика работы детектора
 */
void process_impurity_detector() {
  // [L-20/M-30] Если авто-коррекция или сам детектор выключены — сбрасываем всё и выходим.
  // useDetector действует на все типы строк (H/B/C/T), а не только на головы.
  if (!SamSetup.useautospeed || !SamSetup.useDetector) {
    impurityDetector.detectorStatus = 0;
    // [T05] Применяем сброшенный correctionFactor к скорости насоса, иначе накопленная
    // ранее коррекция навсегда останется в скорости после выключения детектора/автоскорости.
    // Только по факту сброса: process_impurity_detector() зовётся из loop() (~200 раз в
    // секунду), а когда коррекции уже нет, переставлять насосу ту же скорость незачем -
    // это перезапись периода таймера степпера на каждом обороте без единого изменения.
    if (impurityDetector.correctionFactor != 1.0f) {
      impurityDetector.correctionFactor = 1.0f;
      apply_detector_speed_correction(CurrentBaseSpeedRate);
    }
    return;
  }

  // Паузы в ходе активного цикла (статус 15 = program_Wait, статус 40 = PauseOn):
  // сохраняем correctionFactor, только снимаем статус детектора
  if (SamovarStatusInt == SAMOVAR_STATUS_RECT_AUTOPAUSE || SamovarStatusInt == SAMOVAR_STATUS_PAUSED) {
    impurityDetector.detectorStatus = 0;
    // correctionFactor НЕ трогаем — накопленная коррекция сохраняется на время паузы
    // [П3-4] Во время паузы, поставленной САМИМ детектором, тренд продолжаем обновлять —
    // иначе withdrawal() никогда не увидит "тренд устоялся" (значение замороженное
    // на критическом уровне момента входа в паузу). Паузы по пару/царге и ручная —
    // тренд по-прежнему замораживаем (данные при остановленном насосе нерепрезентативны).
    ProgramWaitType pauseWaitType = PROGRAM_WAIT_NONE;
    bool isDetectorOwnPause = program_Wait && copy_program_wait_type(pauseWaitType) && pauseWaitType == PROGRAM_WAIT_DETECTOR;
    if (isDetectorOwnPause) {
      bool usePipeSensor = (detector_last_pipe_sensor == 1);
      float detectorTemp = usePipeSensor ? PipeSensor.avgTemp : SteamSensor.avgTemp;
      detector_sample_tick(detectorTemp, millis());
      return;
    }
    return;
  }

  // Любой другой статус, кроме активного отбора (10) — сброс
  if (SamovarStatusInt != SAMOVAR_STATUS_RECT_WITHDRAWAL) {
    impurityDetector.detectorStatus = 0;
    // [T05] см. пояснение выше: применяем сброс correctionFactor к скорости насоса -
    // один раз, по факту сброса, а не на каждом обороте loop().
    if (impurityDetector.correctionFactor != 1.0f) {
      impurityDetector.correctionFactor = 1.0f;
      apply_detector_speed_correction(CurrentBaseSpeedRate);
    }
    return;
  }

  // Детектор работает только в режиме ректификации
  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) {
    impurityDetector.detectorStatus = 0;
    return;
  }

  const uint8_t currentProgram = ProgramNum;
  const ProgramType currentType = program_type_at(currentProgram);

  // Детектор не работает во время программы типа "P" (Пауза)
  // Во время паузы отбор должен быть полностью остановлен и не возобновляться детектором
  if (currentType == 'P') {
    impurityDetector.detectorStatus = 0;
    // Не меняем correctionFactor, чтобы сохранить состояние на момент паузы
    return;
  }

  ProgramWaitType currentWaitType = PROGRAM_WAIT_NONE;
  if (program_Wait && !copy_program_wait_type(currentWaitType)) {
    SendMsg("Детектор: тип автоматической паузы занят. Проверка пропущена.", WARNING_MSG);
    impurityDetector.detectorStatus = 0;
    return;
  }

  // Детектор не работает во время паузы по царге или пару (автоматическая пауза из-за превышения температуры)
  // При такой паузе детектор был сброшен при её установке, и должен оставаться неактивным
  if (program_Wait && (currentWaitType == PROGRAM_WAIT_PIPE || currentWaitType == PROGRAM_WAIT_STEAM)) {
    impurityDetector.detectorStatus = 0;
    return;
  }

  unsigned long now = millis();
  if (detector_manual_override_until > 0 && (int32_t)(now - detector_manual_override_until) < 0) {
    impurityDetector.detectorStatus = 0;
    return;
  }

  // [M-29] Выбор датчика температуры с гистерезисом ±0.5°C вокруг 92°:
  // - при Т куба < 91.5°C: контроль по пару
  // - при Т куба >= 92.5°C: контроль по царге
  // - в зоне [91.5, 92.5): сохраняем предыдущий источник (гистерезис, без дребезга)
  //
  // [fix] При невалидной Т куба (≤ 0: ошибка DS18B20 = -127, неинициализировано = 0)
  // НЕ переключаем источник и НЕ сбрасываем историю — сохраняем текущий выбор датчика
  // до восстановления валидной температуры.
  bool usePipeSensor;
  bool sensorChanged = false;
  if (TankSensor.avgTemp <= 0.0f) {
    // Невалидная Т куба: блок выбора/смены датчика пропускается целиком.
    // detector_last_pipe_sensor не изменяется; sensorChanged остаётся false.
    if (detector_last_pipe_sensor < 0) {
      // Датчик ещё не инициализирован — безопасный дефолт: пар
      usePipeSensor = false;
    } else {
      usePipeSensor = (detector_last_pipe_sensor == 1);
    }
  } else if (detector_last_pipe_sensor < 0) {
    // Первая инициализация при валидной Т куба: выбираем без гистерезиса
    usePipeSensor = (TankSensor.avgTemp >= 92.0f);
    // sensorChanged = false: история пуста, очищать нечего
    detector_last_pipe_sensor = usePipeSensor ? 1 : 0;
  } else if (TankSensor.avgTemp >= 92.5f) {
    usePipeSensor = true;
    sensorChanged = (detector_last_pipe_sensor != 1);
    detector_last_pipe_sensor = 1;
  } else if (TankSensor.avgTemp < 91.5f) {
    usePipeSensor = false;
    sensorChanged = (detector_last_pipe_sensor != 0);
    detector_last_pipe_sensor = 0;
  } else {
    // Зона гистерезиса — сохраняем предыдущий источник
    usePipeSensor = (detector_last_pipe_sensor == 1);
  }

  // При фактической смене источника датчика — очищаем историю тренда,
  // чтобы линейная регрессия не считалась по смешанным данным двух датчиков
  if (sensorChanged) {
    // [fix M-29] detector_reset_history() тот же сброс истории/накопителей, что при
    // инициализации и полном сбросе, включая lastSampleTime = 0 — немедленный старт
    // сбора с нового датчика. detectorStatus/correctionFactor/lastCorrectionTime и
    // detector_steam_*/detector_last_pipe_sensor намеренно НЕ трогаются: это состояние
    // строки программы и выбора датчика, а не истории.
    detector_reset_history();
    // Короткий грейс-период: дать буферу заполниться свежими данными (30 сек)
    unsigned long detector_new_grace_until = now + 30000UL;
    if (detector_grace_until == 0 || (int32_t)(detector_grace_until - detector_new_grace_until) < 0) {
      detector_grace_until = detector_new_grace_until;
    }
  }

  float detectorTemp = usePipeSensor ? PipeSensor.avgTemp : SteamSensor.avgTemp;

  // Сбор данных: показания усредняются, точка ложится в историю раз в интервал
  const bool trendUpdated = detector_sample_tick(detectorTemp, now);

  // Головы: детектор только наблюдает. Рост Т пара на головах - штатный процесс
  // (лёгкие фракции выводятся, пар очищается, Т идёт к спиртовой полке), а не
  // проскок примесей, поэтому управлять по нему скоростью нельзя.
  // История и тренд выше уже обновлены - телеметрия и лог перегона остаются живыми.
  // correctionFactor держим равным 1.0: скорость на головах задаёт только строка
  // программы (run_program), детектор её не трогает.
  if (currentType == 'H') {
    impurityDetector.detectorStatus = 0;
    impurityDetector.correctionFactor = 1.0f;
    impurityDetector.criticalConfirm = 0;
    return;
  }

  // Грейс-период после старта строки/продолжения: не реагируем.
  // Подтверждения критики обнуляем: пока детектор молчит, накопленные замеры
  // относятся к прошлому состоянию колонны и не должны сработать сразу после грейса.
  if (detector_grace_until > 0 && (int32_t)(now - detector_grace_until) < 0) {
    impurityDetector.detectorStatus = 0;
    impurityDetector.criticalConfirm = 0;
    return;
  }

  // Для первой программы тела/предзахлеба после голов: ждать стабилизацию 10 минут.
  // Проверка идёт по ТОМУ ЖЕ датчику, что выбран выше (пар или царга): is_steam_stable()
  // считает диапазон и дисперсию по истории детектора, а история ведётся по detectorTemp.
  // Раньше здесь стояло условие !usePipeSensor, и при уходе контроля на царгу
  // (Т куба >= 92.5) защита первой строки тела молча отключалась.
  if (is_first_body_program_after_heads(currentProgram, currentType)) {
    if (!is_steam_stable()) {
      impurityDetector.detectorStatus = 0;
      return;
    }
  }

  // Замер фона: пока детектор спокоен и никто не вмешивался в скорость, копим
  // статистику собственного шума тренда. Из неё берётся базовый порог — вместо
  // ручной плотности насадки. Считаем только по новым точкам, иначе за секунду
  // набралось бы столько "замеров", сколько раз вызвался loop().
  if (trendUpdated && impurityDetector.detectorStatus == 0 &&
      impurityDetector.correctionFactor >= 1.0f && !program_Wait && !PauseOn) {
    detector_update_background();
  }

  // Порог предупреждения с адаптивными поправками (дисперсия, скорость отбора, фаза)
  float warningThreshold = detector_warning_threshold();

  float criticalThreshold = warningThreshold * 2.5f;

  // Гистерезис для предотвращения частых переключений (15% от адаптивного порога)
  float hysteresis = warningThreshold * 0.15f;
  float correctionThreshold = warningThreshold + hysteresis;  // Порог для снижения скорости
  float recoveryThreshold = warningThreshold - hysteresis;    // Порог для восстановления скорости

  // Подтверждение критического тренда. Считаем ТОЛЬКО по новым точкам: одиночный
  // выброс (щелчок кванта датчика, скачок атмосферного давления) даёт наклон около
  // 0.09 °C/мин и раньше этого хватало, чтобы мгновенно остановить отбор.
  bool hasCriticalHistory = (impurityDetector.historySize >= DETECTOR_MIN_HISTORY_CRITICAL);
  if (trendUpdated) {
    if (hasCriticalHistory && impurityDetector.currentTrend > criticalThreshold) {
      if (impurityDetector.criticalConfirm < 255) impurityDetector.criticalConfirm++;
    } else {
      impurityDetector.criticalConfirm = 0;
    }
  }

  // Реакция на тренд
  // Пауза детектора не меняется ни одной из веток ниже раньше своего чтения
  // (program_Wait выставляется только внутри критической ветки, уже после
  // использования isDetectorPause), а сами ветки взаимоисключающие - поэтому
  // значение можно посчитать один раз до цепочки if/else if.
  bool isDetectorPause = (program_Wait && currentWaitType == PROGRAM_WAIT_DETECTOR);
  if (impurityDetector.criticalConfirm >= DETECTOR_CRITICAL_CONFIRM) {
    // КРИТИЧЕСКИЙ ПРОСКОК: Ставим на ПАУЗУ (всегда реагируем на критический)
    // Но только если нет ручной паузы пользователя
    if (!program_Wait && !PauseOn) {
      if (!set_program_wait_type(PROGRAM_WAIT_DETECTOR, pdMS_TO_TICKS(500))) {
        SendMsg("Детектор: не удалось установить тип паузы.", WARNING_MSG);
        impurityDetector.detectorStatus = 0;
        return;
      }
      impurityDetector.detectorStatus = 2; // Breakthrough
      program_Wait = true;
      pause_withdrawal(true);
      uint16_t delaySec = usePipeSensor ? PipeSensor.Delay : SteamSensor.Delay;
      t_min = now + delaySec * 1000;
      set_buzzer(true);
      SendMsg("Детектор: Критический тренд! Пауза отбора. (тренд: " +
              String(impurityDetector.currentTrend, 3) + ", variance: " +
              String(impurityDetector.tempVariance, 4) + ")", ALARM_MSG);
      RowStopPauseCount++;
      apply_row_stop_pause_policy();
    } else if (isDetectorPause && impurityDetector.detectorStatus != 2) {
      // Пауза уже установлена детектором, но статус почему-то не 2 - восстанавливаем
      impurityDetector.detectorStatus = 2; // Breakthrough
    }
  } else if (impurityDetector.currentTrend > correctionThreshold) {
    // ПРЕДУПРЕЖДЕНИЕ: Постепенно снижаем скорость
    // Но только если нет ручной паузы пользователя
    // И не устанавливаем статус "коррекция", если пауза уже установлена детектором
    if (!PauseOn && !isDetectorPause) {
      impurityDetector.detectorStatus = 1; // Correction

      // Для первой программы отбора тела после голов: вместо снижения скорости
      // устанавливаем новую температуру тела
      bool isFirstBodyProgram = is_first_body_program_after_heads(currentProgram, currentType);

      // [Ф4] Подъём Т тела ограничен BODY_TEMP_AUTOSET_MAX_RISE от первого захвата в
      // строке - выше него предупреждение детектора обрабатывается как в обычной строке.
      if (isFirstBodyProgram && body_temp_autoset_allowed()) {
        // Это первая программа тела - устанавливаем новую Т тела вместо снижения скорости
        set_body_temp();
        SendMsg("Детектор: Установка новой Т тела (первая программа тела, тренд " +
                String(impurityDetector.currentTrend, 3) + ", variance: " +
                String(impurityDetector.tempVariance, 4) + ")", WARNING_MSG);
        // Не снижаем скорость сразу, дадим детектору время адаптироваться к новой Т тела
        impurityDetector.lastCorrectionTime = now;
        return; // Выходим, чтобы не применять снижение скорости в этом цикле
      }

      // Обычная логика снижения скорости (для не первой программы тела)
      // Адаптивный интервал коррекции: при быстром росте температуры корректируем чаще
      // Базовый интервал: 25 сек
      // При приближении к критическому порогу (60% от criticalThreshold): 10 сек
      // При очень быстром росте (>80% от criticalThreshold): 5 сек
      unsigned long correctionInterval = 25000; // Базовый интервал 25 сек
      float trendRatio = impurityDetector.currentTrend / criticalThreshold;
      if (trendRatio > 0.8f) {
        correctionInterval = 5000;  // Очень быстрый рост - каждые 5 сек
      } else if (trendRatio > 0.6f) {
        correctionInterval = 10000; // Быстрый рост - каждые 10 сек
      }

      if (now - impurityDetector.lastCorrectionTime > correctionInterval) {
        float correctionStep = get_detector_correction_step();
        const float previousFactor = impurityDetector.correctionFactor;
        impurityDetector.correctionFactor *= (1.0f - correctionStep);
        if (impurityDetector.correctionFactor < 0.7f) impurityDetector.correctionFactor = 0.7f;
        impurityDetector.lastCorrectionTime = now;
        // Коэффициент упёрся в нижний предел 0.7 - скорость больше не меняется. Без этой
        // проверки сообщение уходило каждые 5-25 сек до конца строки (спам на хвостах).
        const bool factorChanged = impurityDetector.correctionFactor != previousFactor;

        // Применяем новую скорость и сообщаем оператору правду о результате:
        // насос мог отвергнуть слишком малое значение (уже на минимуме) - тогда
        // это не "снижение скорости", а исчерпание защиты.
        if (factorChanged) {
          bool speedApplied = apply_detector_speed_correction(CurrentBaseSpeedRate);
          if (speedApplied) {
            SendMsg("Детектор: Снижение скорости (тренд " + String(impurityDetector.currentTrend, 3) +
                    ", порог: " + String(warningThreshold, 3) + ", variance: " +
                    String(impurityDetector.tempVariance, 4) + ")", NOTIFY_MSG);
          } else {
            SendMsg("Детектор: скорость уже на минимуме, дальнейшее снижение невозможно (тренд " +
                    String(impurityDetector.currentTrend, 3) + ", variance: " +
                    String(impurityDetector.tempVariance, 4) + ")", WARNING_MSG);
          }
        }
      }
    }
  } else if (impurityDetector.currentTrend < recoveryThreshold) {
    // СТАБИЛЬНО: Плавное восстановление скорости (используется гистерезис)
    // НЕ сбрасываем detectorStatus в 0, если пауза была установлена детектором
    // Статус должен оставаться 2 (критический проскок), пока пауза активна
    if (!isDetectorPause) {
      impurityDetector.detectorStatus = 0; // Stable - только если пауза НЕ от детектора
    }
    // Восстанавливаем скорость только если нет паузы (ни ручной, ни автоматической от детектора)
    // Если пользователь поставил на паузу вручную, или есть автоматическая пауза - не возобновляем
    if (impurityDetector.correctionFactor < 1.0f && !PauseOn && !program_Wait) {
      if (now - impurityDetector.lastCorrectionTime > 30000) { // Восстанавливаем медленно, раз в 30 сек
        impurityDetector.correctionFactor += get_detector_correction_step() * 0.4f;  // сохраняем текущее соотношение 2%/5%=0.4 — восстановление медленнее реакции
        if (impurityDetector.correctionFactor > 1.0f) impurityDetector.correctionFactor = 1.0f;
        impurityDetector.lastCorrectionTime = now;

        // Применяем новую скорость
        apply_detector_speed_correction(CurrentBaseSpeedRate);
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
      if (deltaT < HEAT_LOSS_MIN_DELTA_T) return;

      // Энергия на нагрев: Q = m * c * deltaT (c воды = 4187 Дж/(кг*К))
      // Принимаем плотность сырца за 1 кг/л
#ifdef SAMOVAR_USE_POWER
      float energyUsed = BoilerVolume * 4187.0f * deltaT;
      float powerEffective = energyUsed / timeSec;

      // Теплопотери = Поданная мощность - Эффективная мощность
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
