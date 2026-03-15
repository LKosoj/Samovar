#ifndef __SAMOVAR_BEER_SUPPORT_H_
#define __SAMOVAR_BEER_SUPPORT_H_

#include <Arduino.h>

#include "src/core/state/status_codes.h"
#include "state/globals.h"

inline float getBeerCurrentTemp() {
  if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return 0.0;

  switch (program[ProgramNum].TempSensor) {
    case 0:
      return TankSensor.avgTemp;
    case 1:
      return WaterSensor.avgTemp;
    case 2:
      return PipeSensor.avgTemp;
    case 3:
      return SteamSensor.avgTemp;
    case 4:
      return ACPSensor.avgTemp;
    default:
      return TankSensor.avgTemp;
  }
}

#endif
