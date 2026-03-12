#ifndef __SAMOVAR_NBK_FINISH_H_
#define __SAMOVAR_NBK_FINISH_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/messages.h"
#include "io/sensor_scan.h"
#include "io/power_control.h"
#include "modes/nbk/nbk_flow_control.h"

inline void nbk_finish() {
  SendMsg("Работа НБК завершена", NOTIFY_MSG);
  SetSpeed(0);
  uint32_t totalTime = (millis() - stats.startTime) / 1000;
  if (totalTime > 0) {
    stats.avgSpeed = (stats.totalVolume * 3600.0) / (float)totalTime;
  } else {
    stats.avgSpeed = 0;
  }

  String summary = "";
  summary += "Пропущено браги " + String(stats.totalVolume, 2) + " л ";
  summary += "со средней скоростью " + String(stats.avgSpeed, 2) + " л/ч ";
  summary += "за: " + String(totalTime / 3600.0, 2) + " ч.";
  SendMsg(summary, NOTIFY_MSG);
  delay(1000);
  set_power(false);
  reset_sensor_counter();
  if (fileToAppend) {
    fileToAppend.close();
  }
}

#endif
