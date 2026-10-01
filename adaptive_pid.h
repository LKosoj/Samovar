#pragma once

#include <math.h>
#include <stdint.h>

inline float adaptive_pid_clamp(float value, float low, float high) {
  if (value < low) return low;
  if (value > high) return high;
  return value;
}

inline float adaptive_pid_filter_alpha(float dtSeconds, float timeConstantSeconds) {
  return dtSeconds / (timeConstantSeconds + dtSeconds);
}

inline bool adaptive_pid_deadline_reached(uint32_t nowMs, uint32_t deadlineMs) {
  return static_cast<int32_t>(nowMs - deadlineMs) >= 0;
}

// Горизонт предсказания: на сколько секунд вперёд регулятор продлевает текущую скорость
// роста, прежде чем сравнить температуру с уставкой. Он равен времени выбега котла: после
// резкого снятия мощности температура растёт ещё на (скорость в момент снятия) * выбег.
// Выбег измеряется заново на каждом таком снятии, поэтому смена котла или мешалки
// переучивается за одну-две паузы.
static const float ADAPTIVE_HEATER_HORIZON_DEFAULT_S = 60.0f;
static const float ADAPTIVE_HEATER_HORIZON_MIN_S = 15.0f;
static const float ADAPTIVE_HEATER_HORIZON_MAX_S = 900.0f;

enum AdaptiveHeaterCoastPhase : uint8_t {
  ADAPTIVE_COAST_IDLE = 0,
  ADAPTIVE_COAST_ARMED,     // Была полная мощность
  ADAPTIVE_COAST_DROPPING,  // Мощность прошла половину вниз, ждём почти нуля
  ADAPTIVE_COAST_RUNNING,   // Мощность снята, ждём вершину
};

// Замер выбега. Переживает смену строки: у сыра нагрев и выдержка - разные строки,
// и вершина приходит уже на строке выдержки.
struct AdaptiveHeaterCoast {
  float startTemp;
  float startRate;  // °C/мин в середине сброса мощности
  float peak;
  // Опорные точки скорости: датчик меряет ступеньками по 0.0625 °C, и мгновенная
  // скорость на них скачет вдвое. Скорость для замера берётся за 1-2 минуты.
  float refTemp[2];
  uint32_t refMs[2];
  uint32_t startMs;
  uint32_t peakMs;
  uint32_t lastMs;
  uint8_t phase;
};

struct AdaptiveHeaterState {
  float filteredRate;
  float reactionDelaySeconds;
  float predictionHorizonSeconds;
  float powerForOneDegreePerMinute;
  float predictedTemp;
  float integral;
  float lastOutput;
  float lastTemp;
  uint32_t lastSampleMs;
  uint32_t lastCommandMs;
  uint32_t learningBlockedUntilMs;
  bool initialized;
  bool boostAllowed;
  bool boostActive;
  bool lastCommandApplied;
  bool horizonLearned;  // Горизонт изменён по замеру выбега - его надо сохранить
  AdaptiveHeaterCoast coast;
};

struct AdaptiveHeaterResult {
  float duty;
  bool boost;
};

// horizonSeconds - выученный горизонт (0 или мусор - ещё не выучен).
inline void adaptive_heater_reset(AdaptiveHeaterState& state, float horizonSeconds) {
  const AdaptiveHeaterCoast coast = state.coast;
  state = {};
  state.coast = coast;
  state.reactionDelaySeconds = 15.0f;
  state.predictionHorizonSeconds =
      horizonSeconds >= ADAPTIVE_HEATER_HORIZON_MIN_S
          ? adaptive_pid_clamp(horizonSeconds, ADAPTIVE_HEATER_HORIZON_MIN_S,
                               ADAPTIVE_HEATER_HORIZON_MAX_S)
          : ADAPTIVE_HEATER_HORIZON_DEFAULT_S;
  state.powerForOneDegreePerMinute = 1.0f;
  state.boostAllowed = true;
}

// Регулятор сбрасывает мощность с полной до нуля не мгновенно, а за минуты. Для ровного
// сброса это то же, что мгновенное снятие в его середине, поэтому выбег отсчитывается от
// момента, когда мощность прошла половину. Замер засчитывается, только если до этого была
// полная мощность, а после мощность за 5 минут упала почти до нуля. Вершина пройдена,
// когда температура ушла на 0.2 °C ниже максимума или максимум не рос 5 минут. За один
// замер горизонт меняется не больше чем втрое - открытая крышка его не собьёт.
inline void adaptive_heater_track_coast(
    AdaptiveHeaterState& state, float temp, uint32_t nowMs) {
  AdaptiveHeaterCoast& coast = state.coast;
  // Нагрев не вызывался дольше 5 с (остановка, строка без нагрева) - замер прерван.
  if (nowMs - coast.lastMs > 5000U) {
    coast.phase = ADAPTIVE_COAST_IDLE;
    coast.refTemp[0] = coast.refTemp[1] = temp;
    coast.refMs[0] = coast.refMs[1] = nowMs;
  }
  coast.lastMs = nowMs;
  if (nowMs - coast.refMs[1] >= 60000U) {
    coast.refTemp[0] = coast.refTemp[1];
    coast.refMs[0] = coast.refMs[1];
    coast.refTemp[1] = temp;
    coast.refMs[1] = nowMs;
  }
  const float output = state.lastOutput;
  if (!state.lastCommandApplied) {
    coast.phase = ADAPTIVE_COAST_IDLE;
    return;
  }
  if (output >= 0.9f && coast.phase != ADAPTIVE_COAST_RUNNING) {
    coast.phase = ADAPTIVE_COAST_ARMED;
    return;
  }
  switch (coast.phase) {
    case ADAPTIVE_COAST_IDLE:
      return;
    case ADAPTIVE_COAST_ARMED:
      if (output < 0.5f) {
        const uint32_t spanMs = nowMs - coast.refMs[0];
        const float rate = spanMs >= 60000U
            ? (temp - coast.refTemp[0]) * 60000.0f / spanMs : 0.0f;
        if (rate < 0.1f) {
          coast.phase = ADAPTIVE_COAST_IDLE;
          return;
        }
        coast.phase = ADAPTIVE_COAST_DROPPING;
        coast.startTemp = temp;
        coast.startRate = rate;
        coast.startMs = nowMs;
      }
      return;
    case ADAPTIVE_COAST_DROPPING:
      if (output >= 0.5f) {
        coast.phase = ADAPTIVE_COAST_ARMED;
      } else if (nowMs - coast.startMs > 5UL * 60000UL) {
        coast.phase = ADAPTIVE_COAST_IDLE;
      } else if (output <= 0.05f) {
        coast.phase = ADAPTIVE_COAST_RUNNING;
        coast.peak = temp;
        coast.peakMs = nowMs;
      }
      return;
  }

  if (temp > coast.peak) {
    coast.peak = temp;
    coast.peakMs = nowMs;
  }
  const bool peakPassed =
      temp <= coast.peak - 0.2f || nowMs - coast.peakMs >= 5UL * 60000UL;
  if (!peakPassed && output <= 0.3f) return;
  coast.phase = ADAPTIVE_COAST_IDLE;

  const float current = state.predictionHorizonSeconds;
  // Запас 1.2: при горизонте ровно в выбег регулятор ещё подливает мощность на подходе.
  float measured = adaptive_pid_clamp(
      1.2f * 60.0f * (coast.peak - coast.startTemp) / coast.startRate,
      ADAPTIVE_HEATER_HORIZON_MIN_S, ADAPTIVE_HEATER_HORIZON_MAX_S);
  if (!peakPassed) {
    // Мощность вернули ещё на росте: регулятор ждал выбега дольше настоящего. Измеренная
    // часть выбега - нижняя оценка, годится только на укорочение, и не больше чем на 20 %.
    // Возврат быстрее минуты - дрожание регулятора на ступеньках датчика, а не выбег.
    if (nowMs - coast.startMs < 60000U || measured > current) return;
    if (measured < 0.8f * current) measured = 0.8f * current;
  }
  const float horizon = adaptive_pid_clamp(measured, current / 3.0f, current * 3.0f);
  if (fabsf(horizon - current) < 0.05f * current) return;
  state.predictionHorizonSeconds = horizon;
  state.horizonLearned = true;
}

inline AdaptiveHeaterResult adaptive_heater_step(
    AdaptiveHeaterState& state, float setpoint, float boostTarget, float temp,
    float boostCutoff, uint32_t nowMs) {
  if (!state.initialized) {
    state.initialized = true;
    state.lastTemp = temp;
    state.predictedTemp = temp;
    state.lastSampleMs = nowMs;
    state.lastCommandMs = nowMs;
  }

  if (!state.lastCommandApplied || state.boostActive) {
    state.learningBlockedUntilMs = nowMs +
        static_cast<uint32_t>(state.reactionDelaySeconds * 1000.0f);
  }

  uint32_t elapsedMs = nowMs - state.lastSampleMs;
  if (elapsedMs > 5000U) {
    state.filteredRate = 0.0f;
    state.lastTemp = temp;
    state.lastSampleMs = nowMs;
    elapsedMs = 0;
  }
  const bool sampleReady = elapsedMs >= 250U;
  if (sampleReady) {
    const float dtSeconds = elapsedMs / 1000.0f;
    const float rawRate = adaptive_pid_clamp(
        (temp - state.lastTemp) * 60.0f / dtSeconds, -20.0f, 20.0f);
    const float alpha = adaptive_pid_filter_alpha(dtSeconds, 20.0f);
    state.filteredRate += alpha * (rawRate - state.filteredRate);

    if (state.lastCommandApplied && !state.boostActive &&
        adaptive_pid_deadline_reached(nowMs, state.learningBlockedUntilMs) &&
        state.lastOutput >= 0.25f && state.filteredRate > 0.03f) {
      const float observed = adaptive_pid_clamp(
          state.lastOutput / state.filteredRate, 0.05f, 20.0f);
      const float learnAlpha = adaptive_pid_filter_alpha(dtSeconds, 120.0f);
      state.powerForOneDegreePerMinute +=
          learnAlpha * (observed - state.powerForOneDegreePerMinute);
    }

    state.lastTemp = temp;
    state.lastSampleMs = nowMs;
  }

  if (sampleReady) adaptive_heater_track_coast(state, temp, nowMs);

  state.predictedTemp = temp +
      state.filteredRate * state.predictionHorizonSeconds / 60.0f;
  const float actualError = boostTarget - temp;
  boostCutoff = adaptive_pid_clamp(boostCutoff, 0.0f, 100.0f);
  if (actualError <= boostCutoff) state.boostAllowed = false;

  const float error = setpoint - state.predictedTemp;
  const float desiredRate = adaptive_pid_clamp(error * 0.35f, 0.0f, 3.0f);
  const float feedForward = adaptive_pid_clamp(
      desiredRate * state.powerForOneDegreePerMinute, 0.0f, 1.0f);
  const float proportional = 0.10f * error;
  float output = adaptive_pid_clamp(
      feedForward + proportional + state.integral, 0.0f, 1.0f);

  if (sampleReady) {
    const float dtMinutes = elapsedMs / 60000.0f;
    const float integralChange = 0.06f * error * dtMinutes;
    if ((output > 0.0f && output < 1.0f) ||
        (output <= 0.0f && integralChange > 0.0f) ||
        (output >= 1.0f && integralChange < 0.0f)) {
      state.integral = adaptive_pid_clamp(
          state.integral + integralChange, 0.0f, 1.0f);
      output = adaptive_pid_clamp(
          feedForward + proportional + state.integral, 0.0f, 1.0f);
    }
  }

  state.lastOutput = output;
  state.lastCommandMs = nowMs;
  state.boostActive = state.boostAllowed && actualError > boostCutoff;
  return {output, state.boostActive};
}
