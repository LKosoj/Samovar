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

struct AdaptiveHeaterState {
  float filteredRate;
  float reactionDelaySeconds;
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
};

struct AdaptiveHeaterResult {
  float duty;
  bool boost;
};

inline void adaptive_heater_reset(AdaptiveHeaterState& state) {
  state = {};
  state.reactionDelaySeconds = 15.0f;
  state.powerForOneDegreePerMinute = 1.0f;
  state.boostAllowed = true;
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

  state.predictedTemp = temp +
      state.filteredRate * state.reactionDelaySeconds / 60.0f;
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

struct AdaptivePumpState {
  float filteredRate;
  float reactionDelaySeconds;
  float dutyForOneDegreePerMinute;
  float predictedTemp;
  float integral;
  float lastOutput;
  float lastTemp;
  uint32_t lastSampleMs;
  uint32_t lastCommandMs;
  uint32_t learningBlockedUntilMs;
  bool initialized;
  bool lastCommandLearnable;
};

inline void adaptive_pump_reset(AdaptivePumpState& state, float minimumDuty) {
  state = {};
  state.reactionDelaySeconds = 8.0f;
  state.dutyForOneDegreePerMinute = 0.35f;
  state.integral = minimumDuty;
}

inline float adaptive_pump_step(
    AdaptivePumpState& state, float setpoint, float controlTemp,
    float measuredTemp, float minimumDuty, uint32_t nowMs,
    bool learningAllowed) {
  minimumDuty = adaptive_pid_clamp(minimumDuty, 0.0f, 1.0f);
  if (!state.initialized) {
    adaptive_pump_reset(state, minimumDuty);
    state.initialized = true;
    state.lastTemp = measuredTemp;
    state.predictedTemp = controlTemp;
    state.lastSampleMs = nowMs;
    state.lastCommandMs = nowMs;
  }

  if (!learningAllowed) {
    state.learningBlockedUntilMs = nowMs +
        static_cast<uint32_t>(state.reactionDelaySeconds * 1000.0f);
  }

  uint32_t elapsedMs = nowMs - state.lastSampleMs;
  if (elapsedMs > 5000U) {
    state.filteredRate = 0.0f;
    state.lastTemp = measuredTemp;
    state.lastSampleMs = nowMs;
    elapsedMs = 0;
  }
  const bool sampleReady = elapsedMs >= 250U;
  if (sampleReady) {
    const float dtSeconds = elapsedMs / 1000.0f;
    const float rawRate = adaptive_pid_clamp(
        (measuredTemp - state.lastTemp) * 60.0f / dtSeconds, -20.0f, 20.0f);
    const float alpha = adaptive_pid_filter_alpha(dtSeconds, 12.0f);
    state.filteredRate += alpha * (rawRate - state.filteredRate);

    if (learningAllowed && state.lastCommandLearnable &&
        adaptive_pid_deadline_reached(nowMs, state.learningBlockedUntilMs) &&
        state.lastOutput >= minimumDuty + 0.05f &&
        state.filteredRate < -0.03f) {
      const float observed = adaptive_pid_clamp(
          state.lastOutput / -state.filteredRate, 0.05f, 5.0f);
      const float learnAlpha = adaptive_pid_filter_alpha(dtSeconds, 180.0f);
      state.dutyForOneDegreePerMinute +=
          learnAlpha * (observed - state.dutyForOneDegreePerMinute);
    }

    state.lastTemp = measuredTemp;
    state.lastSampleMs = nowMs;
  }

  state.predictedTemp = controlTemp +
      state.filteredRate * state.reactionDelaySeconds / 60.0f;
  const float error = state.predictedTemp - setpoint;
  const float desiredCoolingRate = adaptive_pid_clamp(error * 0.25f, 0.0f, 3.0f);
  const float feedForward = adaptive_pid_clamp(
      desiredCoolingRate * state.dutyForOneDegreePerMinute, 0.0f, 0.6f);
  const float proportional = 0.05f * error;
  float output = adaptive_pid_clamp(
      state.integral + feedForward + proportional, minimumDuty, 1.0f);

  if (sampleReady) {
    const float dtMinutes = elapsedMs / 60000.0f;
    const float integralChange = 0.02f * error * dtMinutes;
    if ((output > minimumDuty && output < 1.0f) ||
        (output <= minimumDuty && integralChange > 0.0f) ||
        (output >= 1.0f && integralChange < 0.0f)) {
      state.integral = adaptive_pid_clamp(
          state.integral + integralChange, minimumDuty, 1.0f);
      output = adaptive_pid_clamp(
          state.integral + feedForward + proportional, minimumDuty, 1.0f);
    }
  }

  state.lastOutput = output;
  state.lastCommandMs = nowMs;
  return output;
}

inline void adaptive_pump_note_command(
    AdaptivePumpState& state, uint32_t nowMs, bool learnable) {
  state.lastCommandLearnable = learnable;
  if (!learnable) {
    state.learningBlockedUntilMs = nowMs +
        static_cast<uint32_t>(state.reactionDelaySeconds * 1000.0f);
  }
}
