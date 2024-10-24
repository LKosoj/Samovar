#ifndef __SAMOVAR_I2CSTEPPER_H_
#define __SAMOVAR_I2CSTEPPER_H_

// Настройки для шагового двигателя
#define STEPPER_I2C_MS 2
#define STEPPER_I2C_STEPS 200 * STEPPER_I2C_MS //количество шагов, 200 x MS
//#define STEPPER_I2C_MAX_SPEED 1200

#ifndef I2CStepperStepMl
#define I2CStepperStepMl 16000                //количество шагов на мл для I2CStepper
#endif

#include <Arduino.h>
//#include <Wire.h>
#include "Samovar.h"

void stopService(void);
void startService(void);

bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
uint16_t get_stepper_speed(void);
float get_liguid_volume_by_step(int StepCount);
float get_liguid_rate_by_step(int StepperSpeed);
float get_speed_from_rate(float volume_per_hour);

uint8_t check_I2C_device(uint8_t address) {
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
//uint8_t           I2CStepper_arr[2 + 1 +       5 +    1           = 9]

//spd - скорость в оборотах в минуту, direction - прямое или обратное направление, time - время включения двигателя в секундах
bool set_stepper_by_time(uint16_t spd, uint8_t direction, uint16_t time) {
  if (!use_I2C_dev) {
    return false;
  } else {
    return set_stepper_target(spd * STEPPER_I2C_STEPS / 60, direction, time * spd * STEPPER_I2C_STEPS / 60);
  }
}

//Получаем объем отбора
float i2c_get_liguid_volume_by_step(int StepCount) {
  float retval;
  if (!use_I2C_dev) {
    retval = get_liguid_volume_by_step(StepCount);
  } else {
    if (I2CStepperStepMl > 0) retval = (float)StepCount / I2CStepperStepMl;
    else
      retval = 0;
  }
  return retval;
}

//Получаем скорость отбора
float i2c_get_liguid_rate_by_step(int StepperSpeed) {
  if (!use_I2C_dev) {
    return get_liguid_rate_by_step(StepperSpeed);
  } else {
    return round(i2c_get_liguid_volume_by_step(StepperSpeed) * 3.6 * 1000) / 1000.00;
  }
}

float i2c_get_speed_from_rate(float volume_per_hour) {
  float v;
  //ActualVolumePerHour = volume_per_hour;
  ////////
  ////////
  ////////
  if (!use_I2C_dev) {
    v = get_speed_from_rate(volume_per_hour);
  } else {
    v = round(I2CStepperStepMl * volume_per_hour * 1000 / 3.6) / 1000.00;
    if (v < 1) v = 1;
  }
  return v;
}

float i2c_get_liquid_volume() {
  if (!use_I2C_dev) {
    return get_liguid_volume_by_step(get_stepper_speed());
  } else {
    return i2c_get_liguid_volume_by_step(get_stepper_speed());
  }
}

//spd - скорость в шагах в секунду, direction - прямое или обратное направление, target - количество шагов
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target) {
  bool result = false;
  I2CStepperSpeed = spd;
  if (!use_I2C_dev) {
    stopService();
    if (spd > 0) {
      CurrrentStepperSpeed = spd;
      stepper.setTarget(2147483646);
      stepper.setMaxSpeed(spd);
      //stepper.setSpeed(spd);
      startService();
    }
    return true;
  } else {
    if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
      I2C2.writeByte(use_I2C_dev, 8, 1);
      I2C2.writeByte(use_I2C_dev, 0, spd >> 8);
      I2C2.writeByte(use_I2C_dev, 1, spd);
      I2C2.writeByte(use_I2C_dev, 2, direction);
      I2C2.writeByte(use_I2C_dev, 3, target >> 24);
      I2C2.writeByte(use_I2C_dev, 4, target >> 16);
      I2C2.writeByte(use_I2C_dev, 5, target >> 8);
      I2C2.writeByte(use_I2C_dev, 6, target);
      I2C2.writeByte(use_I2C_dev, 8, 0);
      xSemaphoreGive(xI2CSemaphore);
      result = true;
    }
  }
  return result;
}

uint16_t get_stepper_speed(void) {
  uint16_t rest = 0xFFFF;
  if (!use_I2C_dev) {
    return CurrrentStepperSpeed;
  } else {
    if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
      //Читаем скорость
      rest = (uint32_t)I2C2.readByte(use_I2C_dev, 0) << 8;
      rest += (uint32_t)I2C2.readByte(use_I2C_dev, 1);           // Считываем младший байт значения скорости, добавляя его значение к ранее полученному старшему байту
      xSemaphoreGive(xI2CSemaphore);
    }
    I2CStepperSpeed = rest;
    return rest;
  }
  return rest;
}

uint32_t get_stepper_status(void) {
  uint32_t rest = 0xFFFFFFFF;
  if (!use_I2C_dev) {
    return stepper.getTarget();
  } else {

    if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
      //Читаем количество оставшихся шагов
      rest  = (uint32_t)I2C2.readByte(use_I2C_dev, 3) << 24;       // Считываем старший байт значения шагов, сдвигаем полученный байт на 32 бит влево, т.к. он старший
      rest += (uint32_t)I2C2.readByte(use_I2C_dev, 4) << 16;
      rest += (uint32_t)I2C2.readByte(use_I2C_dev, 5) << 8;
      rest += (uint32_t)I2C2.readByte(use_I2C_dev, 6);           // Считываем младший байт значения шагов, добавляя его значение к ранее полученному старшему байту
      xSemaphoreGive(xI2CSemaphore);
    }
    return rest;
  }
  return rest;
}

bool set_mixer_pump_target(uint8_t on) {
  if (!use_I2C_dev) return false;
  bool result = false;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    uint8_t b = I2C2.readByte(use_I2C_dev, 7);
    bitWrite(b, 0, on);
    I2C2.writeByte(use_I2C_dev, 7, b);
    xSemaphoreGive(xI2CSemaphore);
    result = true;
  }
  return result;
}

uint8_t get_mixer_pump_status(void) {
  uint8_t state = 0xFF;
  if (!use_I2C_dev) return state;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    state = BitIsSet(I2C2.readByte(use_I2C_dev, 7), 0);
    xSemaphoreGive(xI2CSemaphore);
  }
  return state;
}

uint8_t get_i2c_rele_state(uint8_t r) {
  uint8_t state = 0xFF;
  if (!use_I2C_dev) return state;
  uint8_t s;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    s = I2C2.readByte(use_I2C_dev, 7);
    xSemaphoreGive(xI2CSemaphore);
    state = BitIsSet(s, (r - 1));
  }
  return state;
}

bool set_i2c_rele_state(uint8_t r, bool s) {
  if (!use_I2C_dev) return false;
  bool result = false;
  uint8_t b;
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (1000 / portTICK_RATE_MS)) == pdTRUE) {
    b = I2C2.readByte(use_I2C_dev, 7);
    bitWrite(b, (r - 1), s);
    I2C2.writeByte(use_I2C_dev, 7, b);
    xSemaphoreGive(xI2CSemaphore);
    result = true;
  }
  return result;
}


#endif //__SAMOVAR_I2CSTEPPER_H_
