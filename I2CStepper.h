#ifndef __SAMOVAR_I2CSTEPPER_H_
#define __SAMOVAR_I2CSTEPPER_H_

#include <Arduino.h>
//#include <Wire.h>
#include "Samovar.h"

bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);

//byte           I2CStepper_arr[2 + 1 +       4 +    1           = 8]
//                              spd direction target transaction


//spd - скорость в оборотах в минуту, direction - прямое или обратное направление, time - время включения двигателя
bool set_stepper_by_time(uint16_t spd, uint8_t direction, uint16_t time){
  return set_stepper_target(spd * 200 / 60, direction, time * spd * 200 / 60);
}


//spd - скорость в шагах в секунду, direction - прямое или обратное направление, target - количество шагов
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target) {
  bool result = false;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    I2C2.writeByte(0x01, 7, 1);
    I2C2.writeByte(0x01, 0, spd >> 8);
    I2C2.writeByte(0x01, 1, spd);
    I2C2.writeByte(0x01, 2, direction);
    I2C2.writeByte(0x01, 3, target >> 32);
    I2C2.writeByte(0x01, 4, target >> 16);
    I2C2.writeByte(0x01, 5, target >> 8);
    I2C2.writeByte(0x01, 6, target);
    I2C2.writeByte(0x01, 7, 0);
    xSemaphoreGive(xI2CSemaphore);
    result = true;
  }
  return result;
}

uint32_t get_stepper_status(void) {
  uint32_t rest = 0xFFFFFFFF;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    //Читаем количество оставшихся шагов
    rest  = I2C2.readByte(0x01, 3) << 32;       // Считываем старший байт значения шагов, сдвигаем полученный байт на 32 бит влево, т.к. он старший
    rest += I2C2.readByte(0x01, 4) << 16;
    rest += I2C2.readByte(0x01, 5) << 8;
    rest += I2C2.readByte(0x01, 6);           // Считываем младший байт значения шагов, добавляя его значение к ранее полученному старшему байту
    xSemaphoreGive(xI2CSemaphore);
  }
  return rest;
}

#endif //__SAMOVAR_I2CSTEPPER_H_
