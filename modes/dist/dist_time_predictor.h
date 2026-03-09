#ifndef __SAMOVAR_DIST_TIME_PREDICTOR_H_
#define __SAMOVAR_DIST_TIME_PREDICTOR_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "support/process_math.h"

struct TimePredictor {
  unsigned long startTime;
  float initialAlcohol;
  float initialTemp;
  float lastTemp;
  float tempChangeRate;
  unsigned long lastUpdateTime;
  float predictedTotalTime;
  float remainingTime;
};

extern TimePredictor timePredictor;

static constexpr float MIN_TEMP_RATE = 0.01f;
static constexpr float MIN_ALC_RATE = 0.001f;
static constexpr unsigned long PREDICTOR_UPDATE_MS = 30000;

inline void resetTimePredictor() {
  timePredictor.startTime = millis();
  timePredictor.initialAlcohol = get_alcohol(TankSensor.avgTemp);
  timePredictor.initialTemp = TankSensor.avgTemp;
  timePredictor.lastTemp = TankSensor.avgTemp;
  timePredictor.lastUpdateTime = millis();
  timePredictor.tempChangeRate = 0;
  timePredictor.predictedTotalTime = 0;
  timePredictor.remainingTime = 0;
}

inline void updateTimePredictor() {
  unsigned long currentTime = millis();
  float currentTemp = TankSensor.avgTemp;
  float currentAlcohol = get_alcohol(currentTemp);

  unsigned long dtMs = currentTime - timePredictor.lastUpdateTime;
  if (dtMs < PREDICTOR_UPDATE_MS) return;

  float dtMin = dtMs / 60000.0f;
  timePredictor.tempChangeRate = (currentTemp - timePredictor.lastTemp) / dtMin;
  timePredictor.lastTemp = currentTemp;
  timePredictor.lastUpdateTime = currentTime;

  float alcoholDelta = timePredictor.initialAlcohol - currentAlcohol;
  float alcoholChangeRate = (dtMin > 0) ? (alcoholDelta / ((currentTime - timePredictor.startTime) / 60000.0f)) : 0;

  if (ProgramNum >= ProgramLen || program[ProgramNum].WType.length() == 0) {
    timePredictor.remainingTime = 0;
    float elapsedMinutes = (currentTime - timePredictor.startTime) / 60000.0f;
    timePredictor.predictedTotalTime = elapsedMinutes;
    return;
  }

  float remaining = 0;
  String wtype = program[ProgramNum].WType;

  if (wtype == "T") {
    float targetTemp = program[ProgramNum].Speed;
    float dT = targetTemp - currentTemp;
    if (dT <= 0) {
      remaining = 0;
    } else if (timePredictor.tempChangeRate > MIN_TEMP_RATE) {
      remaining = dT / timePredictor.tempChangeRate;
    }
  } else if (wtype == "A" || wtype == "S") {
    float targetAlcohol = program[ProgramNum].Speed;
    if (wtype == "S") {
      targetAlcohol *= get_alcohol(TankSensor.StartProgTemp);
    }
    float dA = currentAlcohol - targetAlcohol;
    if (dA <= 0) {
      remaining = 0;
    } else if (alcoholChangeRate > MIN_ALC_RATE) {
      remaining = dA / alcoholChangeRate;
    }
  } else if (wtype == "P" || wtype == "R") {
    float currentSteamAlcohol = get_steam_alcohol(currentTemp);
    float target = program[ProgramNum].Speed;
    if (wtype == "R") {
      target *= get_steam_alcohol(TankSensor.StartProgTemp);
    }
    float dS = currentSteamAlcohol - target;
    if (dS <= 0) {
      remaining = 0;
    } else if (alcoholChangeRate > MIN_ALC_RATE) {
      remaining = dS / alcoholChangeRate;
    }
  } else {
    remaining = 0;
  }

  timePredictor.remainingTime = max(0.0f, remaining);
  float elapsedMinutes = (currentTime - timePredictor.startTime) / 60000.0f;
  timePredictor.predictedTotalTime = elapsedMinutes + timePredictor.remainingTime;
}

inline float get_dist_remaining_time() {
  return timePredictor.remainingTime;
}

inline float get_dist_predicted_total_time() {
  return timePredictor.predictedTotalTime;
}

#endif
