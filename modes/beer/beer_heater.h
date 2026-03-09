#ifndef __SAMOVAR_BEER_HEATER_H_
#define __SAMOVAR_BEER_HEATER_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/messages.h"
#include "app/config_apply.h"
#include "io/power_control.h"

void save_profile();
inline void set_heater_state(float setpoint, float temp);
inline void set_heater(double dutyCycle);
inline void setHeaterPosition(bool state);
inline void StartAutoTune();
inline void FinishAutoTune();

inline void set_heater_state(float setpoint, float temp) {
#ifdef SAMOVAR_USE_POWER
  if (setpoint - temp > ACCELERATION_HEATER_DELTA && !tuning) {
    if (!acceleration_heater) {
      acceleration_heater = true;
      digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
    }
  } else if (acceleration_heater) {
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    acceleration_heater = false;
  }
#endif

  if (setpoint - temp > HEAT_DELTA && !tuning) {
    heater_state = true;
#ifdef SAMOVAR_USE_POWER
    vTaskDelay(5 / portTICK_PERIOD_MS);
    set_current_power(SamSetup.BVolt);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  } else {
    heaterPID.SetMode(AUTOMATIC);
    Setpoint = setpoint;
    Input = temp;

    if (tuning) {
      if (aTune.Runtime()) {
        FinishAutoTune();
      }
    } else {
      heaterPID.Compute();
    }
    set_heater(Output / 100);
  }
}

inline void set_heater(double dutyCycle) {
  static uint32_t oldTime = 0;
  static uint32_t periodTime = 0;

  uint32_t newTime = millis();
  uint32_t offTime = periodInSeconds * 1000 * (dutyCycle);

  if (newTime < oldTime) {
    periodTime += (UINT32_MAX - oldTime + newTime);
  } else {
    periodTime += (newTime - oldTime);
  }
  oldTime = newTime;

  if (periodTime < offTime) {
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else if (periodTime >= periodInSeconds * 1000) {
    periodTime = 0;
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else {
    setHeaterPosition(false);
  }
}

inline void setHeaterPosition(bool state) {
  heater_state = state;

  if (state) {
#ifdef SAMOVAR_USE_POWER
    set_current_power(SamSetup.StbVoltage);
    check_power_error();
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    vTaskDelay(50 / portTICK_PERIOD_MS);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    if (current_power_mode != POWER_SLEEP_MODE) {
      set_power_mode(POWER_SLEEP_MODE);
    }
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }
}

inline void StartAutoTune() {
  ATuneModeRemember = heaterPID.GetMode();

  Output = 50;

  aTune.SetControlType(1);
  aTune.SetNoiseBand(aTuneNoise);
  aTune.SetOutputStep(aTuneStep);
  aTune.SetLookbackSec((int)aTuneLookBack);
  tuning = true;
}

inline void FinishAutoTune() {
  aTune.Cancel();
  tuning = false;

  SamSetup.Kp = aTune.GetKp();
  SamSetup.Ki = aTune.GetKi();
  SamSetup.Kd = aTune.GetKd();

  WriteConsoleLog("Kp = " + (String)SamSetup.Kp);
  WriteConsoleLog("Ki = " + (String)SamSetup.Ki);
  WriteConsoleLog("Kd = " + (String)SamSetup.Kd);

  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  heaterPID.SetMode(ATuneModeRemember);

  save_profile();
  read_config();

  set_heater_state(0, 50);
}

#endif
