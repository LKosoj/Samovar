#include <Arduino.h>

#ifdef USE_WATER_PUMP
//#define PID_OPTIMIZED_I
#include <GyverPID.h>

#define PUMP_PWM_FREQ 15

ESP32PWM pump_pwm;
GyverPID pump_regulator(10, 1.4, 1.4, 1000);

void init_pump_pwm(byte pin, int freq) {
  pump_pwm.attachPin(pin, freq, 10);
  pump_regulator.setDirection(REVERSE);          // направление регулирования (NORMAL/REVERSE). ПО УМОЛЧАНИЮ СТОИТ NORMAL
  pump_regulator.setLimits(PWM_LOW_VALUE * 10, 1023);           // пределы (ставим для 8 битного ШИМ). ПО УМОЛЧАНИЮ СТОЯТ 0 И 255
  pump_regulator.setpoint = TARGET_WATER_TEMP;   // сообщаем регулятору температуру, которую он должен поддерживать
  pump_started = false;
}

void set_pump_pwm(float duty) {
  if (!pump_started && duty > 0) {
    wp_count = 0;
    pump_pwm.write(500);
    pump_started = true;
    return;
  }
  if (duty > 0 && wp_count < 10) {
    pump_pwm.write(500);
    wp_count++;
    return;
  }
  if (duty == 0) pump_started = false;
  pump_pwm.write(duty);
  //MsgLog = duty;
}

void set_pump_speed_pid(float temp) {
  pump_regulator.input = temp;
  set_pump_pwm(pump_regulator.getResultNow());
}
#endif
