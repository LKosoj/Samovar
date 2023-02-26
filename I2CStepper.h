#ifndef __SAMOVAR_I2CSTEPPER_H_
#define __SAMOVAR_I2CSTEPPER_H_

#include <Arduino.h>
//#include <Wire.h>
#include "Samovar.h"

//byte           I2CStepper_arr[2 + 1 + 4 + 1 = 8]

//spd - скорость в шагах в секунду, direction - прямое или обратное направление, target - количество шагов
void set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target) {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (30 / portTICK_RATE_MS)) == pdTRUE) {
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
  }
}

uint32_t get_stepper_status(void) {
  uint32_t rest = 0;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (30 / portTICK_RATE_MS)) == pdTRUE) {
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
