#ifndef __SAMOVAR_BEER_AUTOTUNE_H_
#define __SAMOVAR_BEER_AUTOTUNE_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/messages.h"
#include "app/config_apply.h"
#include "modes/beer/beer_heater.h"

void save_profile();
inline void StartAutoTune();
inline void FinishAutoTune();

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
