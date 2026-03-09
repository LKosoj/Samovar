#ifndef __SAMOVAR_NBK_FLOW_CONTROL_H_
#define __SAMOVAR_NBK_FLOW_CONTROL_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/messages.h"
#include "modes/nbk/nbk_state.h"

bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
float i2c_get_liquid_rate_by_step(int StepperSpeed);
float i2c_get_speed_from_rate(float volume_per_hour);
uint16_t get_stepper_speed(void);

inline bool overflow() {
  if (PowerOn) {
#ifdef USE_HEAD_LEVEL_SENSOR
    whls.tick();
    if (whls.isHolded()) {
      whls.resetStates();
      SendMsg("Захлёб по ДЗ", WARNING_MSG);
      return true;
    }
#endif
    if (pressure_value >= nbk_overflow_pressure) {
      SendMsg("Захлёб по ДД", WARNING_MSG);
      return true;
    }
    return false;
  }
  return false;
}

inline void SetSpeed(float Speed) {
  uint32_t now = millis();
  if (time_speed == 0) {
    time_speed = now;
  }
  if (program[ProgramNum].WType != "H") {
    stats.totalVolume += i2c_get_liquid_rate_by_step(get_stepper_speed()) * (now - time_speed) / 3600000.0;
  }
  time_speed = now;
  if (Speed == 0) {
    set_stepper_target(0, 0, 0);
  } else {
    set_stepper_target(i2c_get_speed_from_rate(Speed), 0, 2147483640);
  }
}

#endif
