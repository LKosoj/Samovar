#ifndef __SAMOVAR_I2CSTEPPER_H_
#define __SAMOVAR_I2CSTEPPER_H_

#include <Arduino.h>
#include <Wire.h>
#include "Samovar.h"

void stopService(void);
void startService(void);
float get_liquid_volume_by_step(float StepCount);
float get_liquid_rate_by_step(int StepperSpeed);
float get_speed_from_rate(float volume_per_hour);

#define I2CSTEPPER_PROTO_VERSION 2
#define I2CSTEPPER_MAGIC 0x53
#define I2CSTEPPER_MIXER_ADDR 1
#define I2CSTEPPER_PUMP_ADDR 2

#define I2CSTEPPER_CAP_MIXER   0x01
#define I2CSTEPPER_CAP_PUMP    0x02
#define I2CSTEPPER_CAP_FILLING 0x04
#define I2CSTEPPER_CAP_RELAY   0x08
#define I2CSTEPPER_CAP_SENSOR  0x10

#define I2CSTEPPER_STATUS_RUNNING     0x01
#define I2CSTEPPER_STATUS_PAUSED      0x02
#define I2CSTEPPER_STATUS_SENSOR      0x04
#define I2CSTEPPER_STATUS_CALIBRATION 0x08
#define I2CSTEPPER_STATUS_ERROR       0x80

#define I2CSTEPPER_FLAG_REVERSE_AFTER_PAUSE 0x01
#define I2CSTEPPER_FLAG_SMOOTH_START        0x02
#define I2CSTEPPER_FLAG_DIRECTION           0x04

#define I2CSTEPPER_SENSOR_ACTIVE_HIGH 0x01
#define I2CSTEPPER_SENSOR_STOP        0x02
#define I2CSTEPPER_SENSOR_PUMP_PAUSE  0x04

enum I2CStepperMode : uint8_t {
  I2CSTEP_MODE_MIXER = 1,
  I2CSTEP_MODE_PUMP = 2,
  I2CSTEP_MODE_FILLING = 3,
};

enum I2CStepperRegister : uint8_t {
  I2CSTEP_REG_MAGIC = 0,
  I2CSTEP_REG_VERSION = 1,
  I2CSTEP_REG_CAPS = 2,
  I2CSTEP_REG_ROLE = 3,
  I2CSTEP_REG_MODE = 4,
  I2CSTEP_REG_COMMAND = 5,
  I2CSTEP_REG_COMMAND_SEQ = 6,
  I2CSTEP_REG_ACK_SEQ = 7,
  I2CSTEP_REG_STATUS = 8,
  I2CSTEP_REG_ERROR = 9,
  I2CSTEP_REG_RELAY_MASK = 10,
  I2CSTEP_REG_SENSOR_FLAGS = 11,
  I2CSTEP_REG_OPTION_FLAGS = 12,
  I2CSTEP_REG_MIXER_RPM_H = 13,
  I2CSTEP_REG_MIXER_RPM_L = 14,
  I2CSTEP_REG_MIXER_RUN_H = 15,
  I2CSTEP_REG_MIXER_RUN_L = 16,
  I2CSTEP_REG_MIXER_PAUSE_H = 17,
  I2CSTEP_REG_MIXER_PAUSE_L = 18,
  I2CSTEP_REG_PUMP_MLH_H = 19,
  I2CSTEP_REG_PUMP_MLH_L = 20,
  I2CSTEP_REG_PUMP_PAUSE_H = 21,
  I2CSTEP_REG_PUMP_PAUSE_L = 22,
  I2CSTEP_REG_FILL_ML_H = 23,
  I2CSTEP_REG_FILL_ML_L = 24,
  I2CSTEP_REG_FILL_MLH_H = 25,
  I2CSTEP_REG_FILL_MLH_L = 26,
  I2CSTEP_REG_STEPS_PER_ML_H = 27,
  I2CSTEP_REG_STEPS_PER_ML_L = 28,
  I2CSTEP_REG_REMAINING_3 = 29,
  I2CSTEP_REG_REMAINING_2 = 30,
  I2CSTEP_REG_REMAINING_1 = 31,
  I2CSTEP_REG_REMAINING_0 = 32,
  I2CSTEP_REG_CURRENT_SPEED_H = 33,
  I2CSTEP_REG_CURRENT_SPEED_L = 34,
};

enum I2CStepperCommand : uint8_t {
  I2CSTEP_CMD_NONE = 0,
  I2CSTEP_CMD_APPLY = 1,
  I2CSTEP_CMD_START = 2,
  I2CSTEP_CMD_STOP = 3,
  I2CSTEP_CMD_SAVE = 4,
  I2CSTEP_CMD_CALIBRATE_START = 5,
  I2CSTEP_CMD_CALIBRATE_FINISH = 6,
  I2CSTEP_CMD_RELAY = 7,
};

struct I2CStepperDevice {
  bool present;
  uint8_t address;
  uint8_t role;
  uint8_t mode;
  uint8_t caps;
  uint8_t status;
  uint8_t error;
  uint8_t relayMask;
  uint8_t sensorFlags;
  uint8_t optionFlags;
  uint8_t commandSeq;
  uint8_t ackSeq;
  uint16_t mixerRpm;
  uint16_t mixerRunSec;
  uint16_t mixerPauseSec;
  uint16_t pumpMlHour;
  uint16_t pumpPauseSec;
  uint16_t fillingMl;
  uint16_t fillingMlHour;
  uint16_t stepsPerMl;
  uint32_t remaining;
  uint16_t currentSpeed;
};

I2CStepperDevice i2cStepperMixer = {false, I2CSTEPPER_MIXER_ADDR};
I2CStepperDevice i2cStepperPump = {false, I2CSTEPPER_PUMP_ADDR};

inline bool i2c_stepper_refresh(I2CStepperDevice& dev);

inline uint8_t check_I2C_device(uint8_t address) {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(1000 / portTICK_RATE_MS)) == pdTRUE) {
    Wire.beginTransmission(address);
    int r = Wire.endTransmission();
    xSemaphoreGive(xI2CSemaphore);
    return (r == 0) ? address : 0;
  }
  return 255;
}

inline bool i2c_stepper_read_byte(uint8_t address, uint8_t reg, uint8_t& value) {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(1000 / portTICK_RATE_MS)) != pdTRUE) return false;
  value = I2C2.readByte(address, reg);
  xSemaphoreGive(xI2CSemaphore);
  return true;
}

inline bool i2c_stepper_write_byte(uint8_t address, uint8_t reg, uint8_t value) {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(1000 / portTICK_RATE_MS)) != pdTRUE) return false;
  uint8_t rc = I2C2.writeByte(address, reg, value);
  xSemaphoreGive(xI2CSemaphore);
  return rc == 0;
}

inline bool i2c_stepper_read_u16(uint8_t address, uint8_t reg, uint16_t& value) {
  uint8_t hi = 0;
  uint8_t lo = 0;
  if (!i2c_stepper_read_byte(address, reg, hi)) return false;
  if (!i2c_stepper_read_byte(address, reg + 1, lo)) return false;
  value = ((uint16_t)hi << 8) | lo;
  return true;
}

inline bool i2c_stepper_write_u16(uint8_t address, uint8_t reg, uint16_t value) {
  return i2c_stepper_write_byte(address, reg, value >> 8) &&
         i2c_stepper_write_byte(address, reg + 1, value & 0xFF);
}

inline bool i2c_stepper_read_u32(uint8_t address, uint8_t reg, uint32_t& value) {
  uint8_t b0 = 0;
  uint8_t b1 = 0;
  uint8_t b2 = 0;
  uint8_t b3 = 0;
  if (!i2c_stepper_read_byte(address, reg, b0)) return false;
  if (!i2c_stepper_read_byte(address, reg + 1, b1)) return false;
  if (!i2c_stepper_read_byte(address, reg + 2, b2)) return false;
  if (!i2c_stepper_read_byte(address, reg + 3, b3)) return false;
  value = ((uint32_t)b0 << 24) | ((uint32_t)b1 << 16) | ((uint32_t)b2 << 8) | b3;
  return true;
}

inline bool i2c_stepper_mixer_present() {
  return i2c_stepper_refresh(i2cStepperMixer);
}

inline bool i2c_stepper_pump_present() {
  return i2c_stepper_refresh(i2cStepperPump);
}

inline bool i2c_stepper_refresh(I2CStepperDevice& dev) {
  uint8_t magic = 0;
  uint8_t version = 0;
  if (check_I2C_device(dev.address) != dev.address) {
    dev.present = false;
    return false;
  }
  if (!i2c_stepper_read_byte(dev.address, I2CSTEP_REG_MAGIC, magic) || magic != I2CSTEPPER_MAGIC) {
    dev.present = false;
    return false;
  }
  if (!i2c_stepper_read_byte(dev.address, I2CSTEP_REG_VERSION, version) || version != I2CSTEPPER_PROTO_VERSION) {
    dev.present = false;
    return false;
  }

  bool ok = i2c_stepper_read_byte(dev.address, I2CSTEP_REG_CAPS, dev.caps) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_ROLE, dev.role) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_MODE, dev.mode) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_STATUS, dev.status) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_ERROR, dev.error) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_RELAY_MASK, dev.relayMask) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_SENSOR_FLAGS, dev.sensorFlags) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_OPTION_FLAGS, dev.optionFlags) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_COMMAND_SEQ, dev.commandSeq) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_ACK_SEQ, dev.ackSeq) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_MIXER_RPM_H, dev.mixerRpm) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_MIXER_RUN_H, dev.mixerRunSec) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_MIXER_PAUSE_H, dev.mixerPauseSec) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_PUMP_MLH_H, dev.pumpMlHour) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_PUMP_PAUSE_H, dev.pumpPauseSec) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_FILL_ML_H, dev.fillingMl) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_FILL_MLH_H, dev.fillingMlHour) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_STEPS_PER_ML_H, dev.stepsPerMl) &&
            i2c_stepper_read_u32(dev.address, I2CSTEP_REG_REMAINING_3, dev.remaining) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_CURRENT_SPEED_H, dev.currentSpeed);
  if (!ok) {
    dev.present = false;
    return false;
  }
  dev.present = true;
  return true;
}

inline void detect_i2c_steppers() {
  i2c_stepper_refresh(i2cStepperMixer);
  i2c_stepper_refresh(i2cStepperPump);
  use_I2C_dev = 0;
  if (i2cStepperMixer.present) use_I2C_dev = I2CSTEPPER_MIXER_ADDR;
  if (i2cStepperPump.present) use_I2C_dev = I2CSTEPPER_PUMP_ADDR;
}

inline bool i2c_stepper_write_config(I2CStepperDevice& dev) {
  if (!dev.present) return false;
  return i2c_stepper_write_byte(dev.address, I2CSTEP_REG_MODE, dev.mode) &&
         i2c_stepper_write_byte(dev.address, I2CSTEP_REG_RELAY_MASK, dev.relayMask) &&
         i2c_stepper_write_byte(dev.address, I2CSTEP_REG_SENSOR_FLAGS, dev.sensorFlags) &&
         i2c_stepper_write_byte(dev.address, I2CSTEP_REG_OPTION_FLAGS, dev.optionFlags) &&
         i2c_stepper_write_u16(dev.address, I2CSTEP_REG_MIXER_RPM_H, dev.mixerRpm) &&
         i2c_stepper_write_u16(dev.address, I2CSTEP_REG_MIXER_RUN_H, dev.mixerRunSec) &&
         i2c_stepper_write_u16(dev.address, I2CSTEP_REG_MIXER_PAUSE_H, dev.mixerPauseSec) &&
         i2c_stepper_write_u16(dev.address, I2CSTEP_REG_PUMP_MLH_H, dev.pumpMlHour) &&
         i2c_stepper_write_u16(dev.address, I2CSTEP_REG_PUMP_PAUSE_H, dev.pumpPauseSec) &&
         i2c_stepper_write_u16(dev.address, I2CSTEP_REG_FILL_ML_H, dev.fillingMl) &&
         i2c_stepper_write_u16(dev.address, I2CSTEP_REG_FILL_MLH_H, dev.fillingMlHour) &&
         i2c_stepper_write_u16(dev.address, I2CSTEP_REG_STEPS_PER_ML_H, dev.stepsPerMl);
}

inline bool i2c_stepper_send_command(I2CStepperDevice& dev, uint8_t command) {
  if (!dev.present) return false;
  uint8_t seq = dev.commandSeq + 1;
  if (seq == 0) seq = 1;
  if (!i2c_stepper_write_byte(dev.address, I2CSTEP_REG_COMMAND, command)) return false;
  if (!i2c_stepper_write_byte(dev.address, I2CSTEP_REG_COMMAND_SEQ, seq)) return false;
  for (uint8_t i = 0; i < 20; i++) {
    vTaskDelay(10 / portTICK_PERIOD_MS);
    i2c_stepper_refresh(dev);
    if (dev.ackSeq == seq) break;
  }
  return dev.present && dev.ackSeq == seq && dev.error == 0;
}

inline bool i2c_stepper_apply(I2CStepperDevice& dev) {
  return i2c_stepper_write_config(dev) && i2c_stepper_send_command(dev, I2CSTEP_CMD_APPLY);
}

inline bool i2c_stepper_save(I2CStepperDevice& dev) {
  return i2c_stepper_write_config(dev) && i2c_stepper_send_command(dev, I2CSTEP_CMD_SAVE);
}

inline bool i2c_stepper_start(I2CStepperDevice& dev) {
  return i2c_stepper_write_config(dev) && i2c_stepper_send_command(dev, I2CSTEP_CMD_START);
}

inline bool i2c_stepper_stop(I2CStepperDevice& dev) {
  return i2c_stepper_send_command(dev, I2CSTEP_CMD_STOP);
}

inline uint16_t i2c_stepper_steps_per_ml() {
  return SamSetup.StepperStepMlI2C > 0 ? SamSetup.StepperStepMlI2C : I2C_STEPPER_STEP_ML_DEFAULT;
}

inline uint16_t i2c_stepper_mlh_from_step_speed(uint16_t spd) {
  uint16_t stepsPerMl = i2c_stepper_steps_per_ml();
  if (spd == 0 || stepsPerMl == 0) return 0;
  uint32_t mlh = ((uint32_t)spd * 3600UL + stepsPerMl / 2) / stepsPerMl;
  if (mlh == 0) return 1;
  return mlh > 65535UL ? 65535 : (uint16_t)mlh;
}

inline uint16_t i2c_stepper_ml_from_steps(uint32_t steps) {
  uint16_t stepsPerMl = i2c_stepper_steps_per_ml();
  if (steps == 0 || stepsPerMl == 0) return 0;
  uint32_t ml = (steps + stepsPerMl / 2) / stepsPerMl;
  if (ml == 0) return 1;
  return ml > 65535UL ? 65535 : (uint16_t)ml;
}

inline bool set_stepper_by_time(uint16_t spd, uint8_t direction, uint16_t time) {
  if (!i2c_stepper_refresh(i2cStepperMixer)) return false;
  i2cStepperMixer.mode = I2CSTEP_MODE_MIXER;
  i2cStepperMixer.mixerRpm = spd;
  i2cStepperMixer.mixerRunSec = time;
  if (direction) i2cStepperMixer.optionFlags |= I2CSTEPPER_FLAG_DIRECTION;
  else i2cStepperMixer.optionFlags &= ~I2CSTEPPER_FLAG_DIRECTION;
  return spd == 0 ? i2c_stepper_stop(i2cStepperMixer) : i2c_stepper_start(i2cStepperMixer);
}

inline bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target) {
  I2CStepperSpeed = spd;
  if (!i2c_stepper_refresh(i2cStepperPump)) {
    CurrrentStepperSpeed = spd;
    stopService();
    if (spd > 0) {
      stepper_safe_set_motion(spd, 0, target);
      startService();
    } else {
      stepper_safe_stop_reset();
    }
    return true;
  }

  I2CPumpCmdSpeed = spd;
  I2CPumpTargetSteps = target;
  if (spd == 0 || target == 0) {
    I2CPumpTargetMl = 0;
    return i2c_stepper_stop(i2cStepperPump);
  }

  uint16_t mlh = i2c_stepper_mlh_from_step_speed(spd);
  i2cStepperPump.stepsPerMl = i2c_stepper_steps_per_ml();
  if (direction) i2cStepperPump.optionFlags |= I2CSTEPPER_FLAG_DIRECTION;
  else i2cStepperPump.optionFlags &= ~I2CSTEPPER_FLAG_DIRECTION;

  if (target >= 2147480000UL) {
    I2CPumpTargetMl = 0;
    i2cStepperPump.mode = I2CSTEP_MODE_PUMP;
    i2cStepperPump.pumpMlHour = mlh;
  } else {
    uint16_t ml = i2c_stepper_ml_from_steps(target);
    I2CPumpTargetMl = ml;
    i2cStepperPump.mode = I2CSTEP_MODE_FILLING;
    i2cStepperPump.fillingMl = ml;
    i2cStepperPump.fillingMlHour = mlh;
  }
  return i2c_stepper_start(i2cStepperPump);
}

inline uint16_t get_stepper_speed(void) {
  if (i2c_stepper_refresh(i2cStepperPump)) return i2cStepperPump.currentSpeed;
  return CurrrentStepperSpeed;
}

inline uint32_t get_stepper_status(void) {
  if (i2c_stepper_refresh(i2cStepperPump)) return (uint32_t)i2cStepperPump.remaining * i2c_stepper_steps_per_ml();
  return stepper_safe_get_target();
}

inline bool set_mixer_pump_target(uint8_t on) {
  I2CStepperDevice* dev = nullptr;
  if (i2c_stepper_refresh(i2cStepperMixer) && (i2cStepperMixer.caps & I2CSTEPPER_CAP_RELAY)) dev = &i2cStepperMixer;
  else if (i2c_stepper_refresh(i2cStepperPump) && (i2cStepperPump.caps & I2CSTEPPER_CAP_RELAY)) dev = &i2cStepperPump;
  if (!dev) return false;
  if (on) dev->relayMask |= 0x01;
  else dev->relayMask &= ~0x01;
  return i2c_stepper_write_config(*dev) && i2c_stepper_send_command(*dev, I2CSTEP_CMD_RELAY);
}

inline uint8_t get_mixer_pump_status(void) {
  if (i2c_stepper_refresh(i2cStepperMixer) && (i2cStepperMixer.caps & I2CSTEPPER_CAP_RELAY)) return bitRead(i2cStepperMixer.relayMask, 0);
  if (i2c_stepper_refresh(i2cStepperPump) && (i2cStepperPump.caps & I2CSTEPPER_CAP_RELAY)) return bitRead(i2cStepperPump.relayMask, 0);
  return 0xFF;
}

inline uint8_t get_i2c_rele_state(uint8_t r) {
  if (r < 1 || r > 4) return 0xFF;
  if (i2c_stepper_refresh(i2cStepperMixer) && (i2cStepperMixer.caps & I2CSTEPPER_CAP_RELAY)) return bitRead(i2cStepperMixer.relayMask, r - 1);
  if (i2c_stepper_refresh(i2cStepperPump) && (i2cStepperPump.caps & I2CSTEPPER_CAP_RELAY)) return bitRead(i2cStepperPump.relayMask, r - 1);
  return 0xFF;
}

inline bool set_i2c_rele_state(uint8_t r, bool s) {
  if (r < 1 || r > 4) return false;
  I2CStepperDevice* dev = nullptr;
  if (i2c_stepper_refresh(i2cStepperMixer) && (i2cStepperMixer.caps & I2CSTEPPER_CAP_RELAY)) dev = &i2cStepperMixer;
  else if (i2c_stepper_refresh(i2cStepperPump) && (i2cStepperPump.caps & I2CSTEPPER_CAP_RELAY)) dev = &i2cStepperPump;
  if (!dev) return false;
  if (s) dev->relayMask |= (1 << (r - 1));
  else dev->relayMask &= ~(1 << (r - 1));
  return i2c_stepper_write_config(*dev) && i2c_stepper_send_command(*dev, I2CSTEP_CMD_RELAY);
}

inline float i2c_get_liquid_volume_by_step(int stepCount) {
  if (!i2c_stepper_refresh(i2cStepperPump)) return get_liquid_volume_by_step(stepCount);
  uint16_t stepsPerMl = i2c_stepper_steps_per_ml();
  return stepsPerMl > 0 ? static_cast<float>(stepCount) / stepsPerMl : 0;
}

inline float i2c_get_liquid_rate_by_step(int stepperSpeed) {
  return round(i2c_get_liquid_volume_by_step(stepperSpeed) * 3.6 * 1000) / 1000.0;
}

inline float i2c_get_speed_from_rate(float volume_per_hour) {
  if (!i2c_stepper_refresh(i2cStepperPump)) return get_speed_from_rate(volume_per_hour);
  uint16_t stepsPerMl = i2c_stepper_steps_per_ml();
  float v = round(stepsPerMl * volume_per_hour * 1000 / 3.6) / 1000.0;
  if (v < 1) return 1;
  if (v > 65535) return 65535;
  return v;
}

inline float i2c_get_liquid_volume() {
  return i2c_get_liquid_volume_by_step(get_stepper_speed());
}

#endif  //__SAMOVAR_I2CSTEPPER_H_
