#ifndef __SAMOVAR_BEER_MIXER_H_
#define __SAMOVAR_BEER_MIXER_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "pumppwm.h"
#include "I2CStepper.h"

inline void check_mixer_state();
inline void set_mixer_state(bool state, bool dir);
inline void set_mixer(bool On);
inline void HopStepperStep();

inline void check_mixer_state() {
  if (program[ProgramNum].capacity_num > 0) {
    if (alarm_c_min > 0 && alarm_c_min <= millis()) {
      alarm_c_min = 0;
      alarm_c_low_min = 0;
      set_mixer_state(false, false);
    }

    if ((alarm_c_low_min > 0) && (alarm_c_low_min <= millis())) {
      alarm_c_low_min = 0;
      if (alarm_c_min > 0) {
        set_mixer_state(false, false);
      }
    }

    if (alarm_c_low_min == 0 && alarm_c_min == 0) {
      alarm_c_low_min = millis() + program[ProgramNum].Volume * 1000;
      if (program[ProgramNum].Power > 0) alarm_c_min = alarm_c_low_min + program[ProgramNum].Power * 1000;
      currentstepcnt++;
      bool dir = false;
      if (currentstepcnt % 2 == 0 && program[ProgramNum].Speed < 0) dir = true;
      set_mixer_state(true, dir);
    }
  } else {
    if (mixer_status) {
      set_mixer_state(false, false);
    }
  }
}

inline void set_mixer_state(bool state, bool dir) {
  mixer_status = state;
  if (state) {
    if (BitIsSet(program[ProgramNum].capacity_num, 0)) {
      digitalWrite(RELE_CHANNEL2, SamSetup.rele2);
      if (use_I2C_dev == 1) {
        int tm = abs(program[ProgramNum].Volume);
        if (tm == 0) tm = 10;
        bool b = set_stepper_by_time(20, dir, tm);
        (void)b;
      }
    }
    if (BitIsSet(program[ProgramNum].capacity_num, 1)) {
#ifdef USE_WATER_PUMP
      pump_pwm.write(1023);
#endif
      if (use_I2C_dev == 1 || use_I2C_dev == 2) {
        bool b = set_mixer_pump_target(1);
        (void)b;
      }
    }
  } else {
    digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
#ifdef USE_WATER_PUMP
    pump_pwm.write(0);
#endif
    if (use_I2C_dev == 1) {
      bool b = set_stepper_by_time(0, 0, 0);
      (void)b;
    }
    if (use_I2C_dev == 1 || use_I2C_dev == 2) {
      bool b = set_mixer_pump_target(0);
      (void)b;
    }
  }
}

inline void set_mixer(bool On) {
  set_mixer_state(On, false);
}

inline void HopStepperStep() {
  stopService();
  stepper.brake();
  stepper.disable();
  stepper.setMaxSpeed(200);
  TargetStepps = 360 / 1.8 * 16 / 20;
  stepper.setCurrent(0);
  stepper.setTarget(TargetStepps);
  stepper.enable();
  startService();
}

#endif
