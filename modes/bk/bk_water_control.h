#ifndef __SAMOVAR_BK_WATER_CONTROL_H_
#define __SAMOVAR_BK_WATER_CONTROL_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

void SendMsg(const String& m, MESSAGE_TYPE msg_type);

inline void set_water_temp(float duty) {
#ifdef USE_WATER_PUMP
  bk_pwm = duty;
  if (pump_started) {
    pump_pwm.write(bk_pwm);
    water_pump_speed = bk_pwm;
  }
#else
  SendMsg(("Управление насосом не поддерживается вашим оборудованием"), NOTIFY_MSG);
#endif
}

#endif
