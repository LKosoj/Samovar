#pragma once
#include "Samovar.h"
#ifdef USE_WATER_PUMP
#include <Arduino.h>
//#define PID_OPTIMIZED_I
#include <GyverPID.h>

#ifndef PUMP_PWM_FREQ
#define PUMP_PWM_FREQ 15
#else
#pragma message ("CUSTOM PUMP_PWM_FREQ")
#endif

static ESP32PWM pump_pwm;
static GyverPID pump_regulator(6.5, 0.3, 30, 1023);

void init_pump_pwm(uint8_t pin, int freq) {
  pump_pwm.attachPin(pin, freq, 10);
  pump_regulator.setDirection(REVERSE);                // направление регулирования (NORMAL/REVERSE). ПО УМОЛЧАНИЮ СТОИТ NORMAL
  pump_regulator.setLimits(PWM_LOW_VALUE * 10, 1023);  // пределы (ставим для 8 битного ШИМ). ПО УМОЛЧАНИЮ СТОЯТ 0 И 255
  //pump_regulator.setMode(ON_RATE);
  pump_regulator.setpoint = SamSetup.SetWaterTemp;     // сообщаем регулятору температуру, которую он должен поддерживать
  pump_started = false;
}

void set_pump_pwm(float duty) {
  if (alarm_event) {
    water_pump_speed = 0;
    pump_pwm.write(0);
    pump_started = false;
    return;
  }

  duty = constrain(duty, 0, 1023);

  if (!pump_started && duty > 0) {
    wp_count = 0;
    pump_pwm.write(PWM_START_VALUE * 10);
    water_pump_speed = PWM_START_VALUE * 10;
    pump_started = true;
    pump_pwm.write(duty);
    if (bk_pwm != PWM_LOW_VALUE * 40) {
      delay(1000);
      pump_pwm.write(bk_pwm);
      water_pump_speed = bk_pwm;
    }
    return;
  }
  if (duty > 0 && wp_count < 10 && pump_started) {
    if (bk_pwm != PWM_LOW_VALUE * 40) {
      pump_pwm.write(bk_pwm);
      water_pump_speed = bk_pwm;
    } else {
      pump_pwm.write(PWM_START_VALUE * 10);
      water_pump_speed = PWM_START_VALUE * 10;
    }
    wp_count++;
    return;
  }
  if (duty == 0) pump_started = false;
  pump_pwm.write(duty);
  water_pump_speed = duty;
  //MsgLog = duty;
}

void set_pump_speed_pid(float temp) {
  pump_regulator.input = temp;
  set_pump_pwm(pump_regulator.getResultNow());
}
#endif
