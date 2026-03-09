#ifndef __SAMOVAR_NBK_MATH_H_
#define __SAMOVAR_NBK_MATH_H_

#include "Samovar.h"
#include "state/globals.h"

inline float toPower(float value) { // конвертер в мощность ( V | W ) => W
 #ifdef SAMOVAR_USE_SEM_AVR
  return value; // если нечто иное возвращаем неизменным
 #else
  float R = SamSetup.HeaterResistant > 1 ? SamSetup.HeaterResistant : 18;
  return value * value / R; //если от kvic или RVMK пересчитываем в P
 #endif
}

#ifndef SAMOVAR_USE_SEM_AVR
inline float SQRT(float num) { // компилируем только по необходимости
  if (num < 0) {
    return -1.0f;
  }
  if (num == 0) {
    return 0.0f;
  }
  float guess = num;
  float prev_guess;
  do {
    prev_guess = guess;
    guess = (guess + num / guess) / 2;
    delay(3);
  } while (abs(guess - prev_guess) > 0.001);
  return guess;
}
#endif

inline float fromPower(float value) { // конвертер из мощности: W => ( V | W )
 #ifdef SAMOVAR_USE_SEM_AVR
  return value;
 #else
  static float prev_W = 0.0f;
  static float prev_V = 0.0f;
  if (value != prev_W) {
    prev_W = value;
    float R = SamSetup.HeaterResistant > 1 && SamSetup.HeaterResistant < 200 ? SamSetup.HeaterResistant : 18;
    prev_V = SQRT(value * R);
  }
  return prev_V;
 #endif
}

#endif
