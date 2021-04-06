#ifdef USE_WATER_PUMP
#include <ESP32Servo.h>
#include <GyverPID.h>

#define PUMP_PWM_FREQ 100

ESP32PWM pump_pwm;
GyverPID regulator(10, 0.05, 0.01, 1000);

void init_pump_pwm(byte pin, int freq) {
  pump_pwm.attachPin(pin, freq, 10);
  regulator.setDirection(REVERSE);          // направление регулирования (NORMAL/REVERSE). ПО УМОЛЧАНИЮ СТОИТ NORMAL
  regulator.setLimits(PWM_LOW_VALUE * 10, 1023);           // пределы (ставим для 8 битного ШИМ). ПО УМОЛЧАНИЮ СТОЯТ 0 И 255
  regulator.setpoint = TARGET_WATER_TEMP;   // сообщаем регулятору температуру, которую он должен поддерживать
  pump_started = false;
}

void set_pump_pwm(float duty) {
  if (!pump_started && duty > 0) {
//    pump_pwm.write(1020);
//    delay(1000);
    pump_started = true;
  }
  if (duty == 0) pump_started = false;
  pump_pwm.write(duty);
  //Msg = duty;
}

void set_pump_speed_pid(float temp) {
  regulator.input = temp;
  set_pump_pwm(regulator.getResultNow());
}
#endif
