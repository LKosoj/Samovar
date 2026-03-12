#ifndef __SAMOVAR_SUPPORT_TASK_STACK_USAGE_H_
#define __SAMOVAR_SUPPORT_TASK_STACK_USAGE_H_

#include <Arduino.h>

#include "state/globals.h"

inline void get_task_stack_usage() {
  Serial.println(F("=== Task Stack Usage ==="));
  Serial.printf("SysTicker:        %u words free (of 3200)\n", uxTaskGetStackHighWaterMark(SysTickerTask1));
  Serial.printf("GetClock:         %u words free (of 3400)\n", uxTaskGetStackHighWaterMark(GetClockTask1));
#ifdef USE_LUA
  if (DoLuaScriptTask) {
    Serial.printf("LuaScript:        %u words free (of 5900)\n", uxTaskGetStackHighWaterMark(DoLuaScriptTask));
  }
#endif
#ifdef SAMOVAR_USE_POWER
  Serial.printf("PowerStatus:      %u words free (of 1800)\n", uxTaskGetStackHighWaterMark(PowerStatusTask));
#endif
  Serial.println(F("========================"));
}

#endif
