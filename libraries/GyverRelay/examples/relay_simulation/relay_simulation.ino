/*
  Симуляция работы реле. Обнули k и увидишь, как регулятор
  перестанет справляться с инерционной системой
*/

#include "GyverRelay.h"
GyverRelay regulator(REVERSE);

void setup() {
  Serial.begin(9600);
  regulator.setpoint = 40;
  regulator.hysteresis = 5;
  regulator.k = 0.6;
}

boolean state = 0;
float value = 0;

void loop() {
  process();
  regulator.input = value;
  state = regulator.getResult();

  Serial.print(value);
  Serial.print(' ');
  Serial.print(regulator.setpoint - regulator.hysteresis / 2);
  Serial.print(' ');
  Serial.print(regulator.setpoint + regulator.hysteresis / 2);
  Serial.print(' ');
  Serial.println(regulator.setpoint);
  delay(100);
}

void process() {
  static float coef = 0;
  coef += state ? 0.3 : -0.6;
  coef = constrain(coef, -3, 2);
  value += coef;
}
