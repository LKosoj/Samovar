#ifndef __SAMOVAR_I2CSTEPPER_H_
#define __SAMOVAR_I2CSTEPPER_H_

// Настройки для шагового двигателя
#define STEPPER_I2C_MS 2
#define STEPPER_I2C_STEPS 200 * STEPPER_I2C_MS //количество шагов, 200 x MS
#define STEPPER_I2C_MAX_SPEED 1200


#include <Arduino.h>
//#include <Wire.h>
#include "Samovar.h"

bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);


byte check_I2C_device(byte address) {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    Wire.beginTransmission(address);
    int r = Wire.endTransmission();
    xSemaphoreGive(xI2CSemaphore);
    if (r == 0) {
      return address;
    } else {
      return 0;
    }
  } else return 255;
}

//                              spd direction target transaction
//byte           I2CStepper_arr[2 + 1 +       5 +    1           = 9]

//spd - скорость в оборотах в минуту, direction - прямое или обратное направление, time - время включения двигателя в секундах
bool set_stepper_by_time(uint16_t spd, uint8_t direction, uint16_t time) {
  if (!use_I2C_dev) return false;
  return set_stepper_target(spd * STEPPER_I2C_STEPS / 60, direction, time * spd * STEPPER_I2C_STEPS / 60);
}


//spd - скорость в шагах в секунду, direction - прямое или обратное направление, target - количество шагов
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target) {
  if (!use_I2C_dev) return false;
  bool result = false;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    I2C2.writeByte(0x01, 8, 1);
    I2C2.writeByte(0x01, 0, spd >> 8);
    I2C2.writeByte(0x01, 1, spd);
    I2C2.writeByte(0x01, 2, direction);
    I2C2.writeByte(0x01, 3, target >> 24);
    I2C2.writeByte(0x01, 4, target >> 16);
    I2C2.writeByte(0x01, 5, target >> 8);
    I2C2.writeByte(0x01, 6, target);
    I2C2.writeByte(0x01, 8, 0);
    xSemaphoreGive(xI2CSemaphore);
    result = true;
  }
  return result;
}

uint32_t get_stepper_status(void) {
  uint32_t rest = 0xFFFFFFFF;
  if (!use_I2C_dev) return rest;
  
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    //Читаем количество оставшихся шагов
    rest  = (uint32_t)I2C2.readByte(0x01, 3) << 24;       // Считываем старший байт значения шагов, сдвигаем полученный байт на 32 бит влево, т.к. он старший
    rest += (uint32_t)I2C2.readByte(0x01, 4) << 16;
    rest += (uint32_t)I2C2.readByte(0x01, 5) << 8;
    rest += (uint32_t)I2C2.readByte(0x01, 6);           // Считываем младший байт значения шагов, добавляя его значение к ранее полученному старшему байту
    xSemaphoreGive(xI2CSemaphore);
  }
  return rest;
}

bool set_mixer_pump_target(uint8_t on) {
  if (!use_I2C_dev) return false;
  bool result = false;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    byte b = I2C2.readByte(0x01, 7);
    bitWrite(b, 0, on);
    I2C2.writeByte(0x01, 7, b);
    xSemaphoreGive(xI2CSemaphore);
    result = true;
  }
  return result;
}

byte get_mixer_pump_status(void) {
  byte state = 0xFF;
  if (!use_I2C_dev) return state;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    state = BitIsSet(I2C2.readByte(0x01, 7), 0);
    xSemaphoreGive(xI2CSemaphore);
  }
  return state;
}

byte get_i2c_rele_state(uint8_t r) {
  byte state = 0xFF;
  if (!use_I2C_dev) return state;
  byte s;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    s = I2C2.readByte(0x01, 7);
    state = BitIsSet(s, r - 1);
    xSemaphoreGive(xI2CSemaphore);
  }
  return state;
}

bool set_i2c_rele_state(uint8_t r, bool s) {
  if (!use_I2C_dev) return false;
  bool result = false;
  byte b;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    b = I2C2.readByte(0x01, 7);
    bitWrite(b, (r - 1), s);
    I2C2.writeByte(0x01, 7, b);
    xSemaphoreGive(xI2CSemaphore);
    result = true;
  }
  return result;
}


#endif //__SAMOVAR_I2CSTEPPER_H_
