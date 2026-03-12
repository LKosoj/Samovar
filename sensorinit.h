#ifndef __SAMOVAR_S_I_H_
#define __SAMOVAR_S_I_H_
#include <Arduino.h>
#include "Samovar.h"
#include "modes/beer/beer_program_codec.h"
#include "modes/dist/dist_program_codec.h"
#include "modes/nbk/nbk_program_codec.h"
#include "modes/rect/rect_program_codec.h"
#include "app/status_text.h"
#include "state/globals.h"
#include "io/pressure.h"
#include "io/sensor_scan.h"
#include "io/sensors.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "pumppwm.h"

#ifdef USE_LUA
#include "lua.h"
#endif
// Функция загрузки программы по умолчанию для текущего режима
void load_default_program_for_mode() {
  if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
    set_beer_program("M;45;0;0^-1^2^2;0\nP;45;1;0^-1^2^3;0\nP;60;1;0^-1^2^3;0\nW;0;0;0^-1^2^3;0\nB;0;1;0^-1^2^3;0\nC;30;0;0^-1^2^3;0\n");
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    set_dist_program("A;80.00;1;0\nS;0.50;2;0\nS;0.30;3;0\n");
  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
    set_nbk_program(NBK_DEFAULT_PROGRAM);
  } else {
    set_program("H;450;0.1;1;0;45\nB;450;1;1;0;45\nH;450;0.1;1;0;45\n");
  }
}

void clok();
void clok1();
void stopService(void);
void startService(void);
void setupOpenLog(void);
void createFile(char* fileName);
void init_pump_pwm(uint8_t pin, int freq);
void set_pump_pwm(float duty);

#endif

#ifndef GET_TASK_STACK_USAGE_DEFINED
#define GET_TASK_STACK_USAGE_DEFINED

// Функция для вывода статистики использования стека задачами FreeRTOS
// Помогает оптимизировать размеры стеков и выявлять проблемы переполнения
void get_task_stack_usage() {

  // Выводим статистику использования стека задачами
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

#endif // GET_TASK_STACK_USAGE_DEFINED
