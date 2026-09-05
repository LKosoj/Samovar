#ifndef __SAMOVAR_I2CSTEPPER_H_
#define __SAMOVAR_I2CSTEPPER_H_

#include <Arduino.h>
#include <Wire.h>
#include "Samovar.h"
#include "samovar_api.h"

#define I2CSTEPPER_PROTO_VERSION 2
#define I2CSTEPPER_MAGIC 0x53
#define I2CSTEPPER_MIXER_ADDR 1
#define I2CSTEPPER_PUMP_ADDR 2
#define I2CSTEPPER_FAIL_STREAK_ALERT 5
#define I2CSTEPPER_DETECT_ATTEMPTS 3

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
  uint8_t refreshFailStreak;
};

inline I2CStepperDevice make_i2c_stepper_device(uint8_t address) {
  I2CStepperDevice dev = {};
  dev.address = address;
  return dev;
}

I2CStepperDevice i2cStepperMixer = make_i2c_stepper_device(I2CSTEPPER_MIXER_ADDR);
I2CStepperDevice i2cStepperPump = make_i2c_stepper_device(I2CSTEPPER_PUMP_ADDR);

#define I2CSTEP_CONFIG_MIXER 0x01
#define I2CSTEP_CONFIG_PUMP  0x02
volatile uint8_t i2c_config_in_flight = 0;

inline uint8_t i2c_stepper_config_bit(const I2CStepperDevice& dev) {
  if (dev.address == I2CSTEPPER_MIXER_ADDR) return I2CSTEP_CONFIG_MIXER;
  if (dev.address == I2CSTEPPER_PUMP_ADDR) return I2CSTEP_CONFIG_PUMP;
  return 0;
}

inline bool i2c_stepper_config_begin(const I2CStepperDevice& dev) {
  uint8_t bit = i2c_stepper_config_bit(dev);
  if (bit == 0) return false;
  uint8_t current = 0;
  do {
    current = i2c_config_in_flight;
    if ((current & bit) != 0) return false;
  } while (!__sync_bool_compare_and_swap(&i2c_config_in_flight, current, current | bit));
  return true;
}

inline void i2c_stepper_config_end(const I2CStepperDevice& dev) {
  uint8_t bit = i2c_stepper_config_bit(dev);
  if (bit == 0) return;
  uint8_t current = 0;
  do {
    current = i2c_config_in_flight;
  } while (!__sync_bool_compare_and_swap(&i2c_config_in_flight, current, current & ~bit));
}

inline bool i2c_stepper_config_busy(const I2CStepperDevice& dev) {
  uint8_t bit = i2c_stepper_config_bit(dev);
  return bit != 0 && (i2c_config_in_flight & bit) != 0;
}

// Таймаут (мс) ожидания мьютекса I2C. I2C_LOCK_WAIT_MS - значение по умолчанию для
// чтения (используется и путём записи конфигурации пользователем, который не меняем).
// I2C_CACHE_LOCK_WAIT_MS - укороченный таймаут для фонового обновления кэша из
// SysTicker (см. refresh_i2c_stepper_cache в Samovar.ino), чтобы занятая шина не
// подвешивала задачу-надзиратель на секунду.
#define I2C_LOCK_WAIT_MS 1000
#define I2C_CACHE_LOCK_WAIT_MS 100

inline bool i2c_stepper_refresh(I2CStepperDevice& dev, bool force = false, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS);

// [Ревью 24.08, ошибка 3] lockWaitMs со значением по умолчанию I2C_LOCK_WAIT_MS -
// ЧТОБЫ i2c_stepper_refresh() мог передать сюда укороченный I2C_CACHE_LOCK_WAIT_MS
// (100 мс), как он уже делает во ВСЕ остальные i2c_stepper_read_*() ниже по функции.
// Раньше здесь был захардкожен 1000 мс, и фоновый опрос кэша из SysTicker
// (refresh_i2c_stepper_cache в Samovar.ino, рассчитанный именно на 100 мс, чтобы не
// подвесить задачу-надзиратель) на первой же строке check_I2C_device() всё равно мог
// простоять до секунды. Остальные вызывающие (LCD-проба в setup(), Lua-обёртка) не
// передают lockWaitMs и получают прежнее поведение по умолчанию.
inline uint8_t check_I2C_device(uint8_t address, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(lockWaitMs / portTICK_RATE_MS)) == pdTRUE) {
    Wire.beginTransmission(address);
    int r = Wire.endTransmission();
    xSemaphoreGive(xI2CSemaphore);
    return (r == 0) ? address : 0;
  }
  return 255;
}

inline bool i2c_stepper_read_block(uint8_t address, uint8_t reg, uint8_t* data, uint8_t len, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  if (len == 0 || data == nullptr) return false;
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(lockWaitMs / portTICK_RATE_MS)) != pdTRUE) return false;
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    xSemaphoreGive(xI2CSemaphore);
    return false;
  }
  uint8_t bytesRead = Wire.requestFrom(address, len);
  if (bytesRead != len) {
    xSemaphoreGive(xI2CSemaphore);
    return false;
  }
  for (uint8_t i = 0; i < len; i++) {
    data[i] = Wire.read();
  }
  xSemaphoreGive(xI2CSemaphore);
  return true;
}

// Делегирует на i2c_stepper_read_block(), которая (в отличие от старого прямого
// I2C2.readByte()) проверяет endTransmission()/число принятых байт и НЕ трогает
// value при отказе - буфер/кэш остаётся на последнем успешном значении.
inline bool i2c_stepper_read_byte(uint8_t address, uint8_t reg, uint8_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  return i2c_stepper_read_block(address, reg, &value, 1, lockWaitMs);
}

inline bool i2c_stepper_write_byte(uint8_t address, uint8_t reg, uint8_t value) {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(1000 / portTICK_RATE_MS)) != pdTRUE) return false;
  uint8_t rc = I2C2.writeByte(address, reg, value);
  xSemaphoreGive(xI2CSemaphore);
  return rc == 0;
}

inline bool i2c_stepper_read_u16(uint8_t address, uint8_t reg, uint16_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  uint8_t data[2] = {};
  if (!i2c_stepper_read_block(address, reg, data, sizeof(data), lockWaitMs)) return false;
  value = ((uint16_t)data[0] << 8) | data[1];
  return true;
}

// Одна raw-транзакция Wire (reg, hi, lo одним пакетом) вместо двух отдельных
// I2C2.writeByte() - иначе приёмник может прочитать наполовину записанное значение
// между двумя транзакциями. Тайм-аут семафора (1000 мс) не менялся, как и у
// остальных функций записи (i2c_stepper_write_byte).
inline bool i2c_stepper_write_u16(uint8_t address, uint8_t reg, uint16_t value) {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(1000 / portTICK_RATE_MS)) != pdTRUE) return false;
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write((uint8_t)(value >> 8));
  Wire.write((uint8_t)(value & 0xFF));
  bool ok = Wire.endTransmission() == 0;
  xSemaphoreGive(xI2CSemaphore);
  return ok;
}

inline bool i2c_stepper_read_u32(uint8_t address, uint8_t reg, uint32_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  uint8_t data[4] = {};
  if (!i2c_stepper_read_block(address, reg, data, sizeof(data), lockWaitMs)) return false;
  value = ((uint32_t)data[0] << 24) | ((uint32_t)data[1] << 16) | ((uint32_t)data[2] << 8) | data[3];
  return true;
}

// Счётчик подряд идущих неудачных обновлений устройства (см. refreshFailStreak).
// Сообщаем один раз при достижении порога I2CSTEPPER_FAIL_STREAK_ALERT - приём уже
// применён в проекте (noDZ_message_sent, pressure_alarm_sent), чтобы не заспамить
// пользователя повторным сообщением на каждый последующий неудачный опрос.
// SendMsg() здесь безопасен: единственный вызов из setup() - detect_i2c_steppers()
// внутри setup_finalize_boot_display(), а он идёт ПОСЛЕ создания xMsgSemaphore;
// остальные пути (loop, SysTicker, веб) заведомо позже.
inline void i2c_stepper_note_refresh_failure(I2CStepperDevice& dev) {
  if (dev.refreshFailStreak < 255) dev.refreshFailStreak++;
  if (dev.refreshFailStreak != I2CSTEPPER_FAIL_STREAK_ALERT) return;
  SendMsg(String("Степпер на адресе ") + dev.address + " не отвечает, переход на локальный запасной путь", ALARM_MSG);
}

inline bool i2c_stepper_mixer_present() {
  return i2c_stepper_refresh(i2cStepperMixer);
}

inline bool i2c_stepper_pump_present() {
  return i2c_stepper_refresh(i2cStepperPump);
}

inline bool i2c_stepper_refresh(I2CStepperDevice& dev, bool force, TickType_t lockWaitMs) {
  if (!force && i2c_stepper_config_busy(dev)) return dev.present;
  uint8_t magic = 0;
  uint8_t version = 0;
  if (check_I2C_device(dev.address, lockWaitMs) != dev.address) {
    dev.present = false;
    i2c_stepper_note_refresh_failure(dev);
    return false;
  }
  if (!i2c_stepper_read_byte(dev.address, I2CSTEP_REG_MAGIC, magic, lockWaitMs) || magic != I2CSTEPPER_MAGIC) {
    dev.present = false;
    i2c_stepper_note_refresh_failure(dev);
    return false;
  }
  if (!i2c_stepper_read_byte(dev.address, I2CSTEP_REG_VERSION, version, lockWaitMs) || version != I2CSTEPPER_PROTO_VERSION) {
    dev.present = false;
    i2c_stepper_note_refresh_failure(dev);
    return false;
  }

  bool ok = i2c_stepper_read_byte(dev.address, I2CSTEP_REG_CAPS, dev.caps, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_ROLE, dev.role, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_MODE, dev.mode, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_STATUS, dev.status, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_ERROR, dev.error, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_RELAY_MASK, dev.relayMask, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_SENSOR_FLAGS, dev.sensorFlags, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_OPTION_FLAGS, dev.optionFlags, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_COMMAND_SEQ, dev.commandSeq, lockWaitMs) &&
            i2c_stepper_read_byte(dev.address, I2CSTEP_REG_ACK_SEQ, dev.ackSeq, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_MIXER_RPM_H, dev.mixerRpm, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_MIXER_RUN_H, dev.mixerRunSec, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_MIXER_PAUSE_H, dev.mixerPauseSec, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_PUMP_MLH_H, dev.pumpMlHour, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_PUMP_PAUSE_H, dev.pumpPauseSec, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_FILL_ML_H, dev.fillingMl, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_FILL_MLH_H, dev.fillingMlHour, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_STEPS_PER_ML_H, dev.stepsPerMl, lockWaitMs) &&
            i2c_stepper_read_u32(dev.address, I2CSTEP_REG_REMAINING_3, dev.remaining, lockWaitMs) &&
            i2c_stepper_read_u16(dev.address, I2CSTEP_REG_CURRENT_SPEED_H, dev.currentSpeed, lockWaitMs);
  if (!ok) {
    dev.present = false;
    i2c_stepper_note_refresh_failure(dev);
    return false;
  }
  dev.present = true;
  dev.refreshFailStreak = 0;
  return true;
}

// Одна проба зафиксировала бы use_I2C_dev на всю сессию: разовая помеха на шине при
// старте (на той же линии поднимаются LCD и датчики) навсегда увела бы насос на
// локальный запасной путь, и подтверждение останова по шине не сработало бы ни разу.
inline bool i2c_stepper_detect_with_retry(I2CStepperDevice& dev) {
  for (uint8_t attempt = 0; attempt < I2CSTEPPER_DETECT_ATTEMPTS; attempt++) {
    if (i2c_stepper_refresh(dev, true)) return true;
    vTaskDelay(20 / portTICK_PERIOD_MS);
  }
  return false;
}

inline void detect_i2c_steppers() {
  i2c_stepper_detect_with_retry(i2cStepperMixer);
  i2c_stepper_detect_with_retry(i2cStepperPump);
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

// [Ревью 24.08, ошибка 1] Раньше цикл ждал ВСЕ 20 попыток даже после того, как
// i2c_stepper_refresh() уже сообщил "устройства больше нет" (dev.present=false) -
// лишние попытки ничего не решают, ответа не будет. Каждая попытка при потерянном
// семафоре (кто-то другой держит xI2CSemaphore) стоит до I2C_LOCK_WAIT_MS=1000 мс
// внутри check_I2C_device(), так что 20 таких попыток - это до ~20 секунд СИНХРОННО
// внутри loop(), а loop() сам под сторожем на LOOP_WDT_TIMEOUT_S=10 секунд (см.
// Samovar.ino) - зависшая I2C-плата вызывала бы ложную перезагрузку прямо во время
// перегонки. Короткий I2C_CACHE_LOCK_WAIT_MS (100 мс, как в фоновом опросе SysTicker)
// здесь НЕ применяем сознательно: main_menu1.update() (Menu.ino, LcdLockGuard) штатно
// держит xI2CSemaphore на всю перерисовку LCD 20x4 через PCF8574 в 4-битном режиме -
// LiquidCrystal_I2C.cpp::send() тратит 6 I2C-транзакций на КАЖДЫЙ байт экрана, это
// обычно больше 100 мс. Короткий таймаут семафора здесь превратил бы устойчивую к
// этой обычной задержке команду в ложный отказ подтверждения - для start/stop насоса
// это прямой риск (см. комментарий у stop_i2c_pump_confirmed() ниже по файлу). Поэтому
// вместо укорачивания таймаута - выход по НЕСКОЛЬКИМ ПОДРЯД неудачам refresh() (см.
// [Ревью 24.08, предупреждение 4] ниже) и общий потолок по времени как страховка от
// редкого случая, когда каждая из ~19 попыток чтения ВНУТРИ одного refresh() по
// отдельности упирается в полный таймаут семафора.
//
// [Ревью 24.08, предупреждение 4] Выход по ПЕРВОЙ же неудаче refresh() принимал
// одиночную помеху на шине (или тот же LcdLockGuard, на долю секунды занявший
// xI2CSemaphore перерисовкой экрана - см. абзац выше) за пропажу устройства: одного
// такого сбоя достаточно, чтобы confirm-цикл сдался, хотя борт всё ещё на связи и
// ответил бы на следующей попытке 10 мс спустя. Порог берём готовый -
// I2CSTEPPER_FAIL_STREAK_ALERT (5) - тот же критерий "случайность или отказ", которым
// в проекте уже меряют пропажу устройства в фоновом опросе (см.
// i2c_stepper_note_refresh_failure() выше). Счётчик локальный для ЭТОГО вызова, а не
// dev.refreshFailStreak: последний живёт дольше одной команды (копится фоновым
// опросом SysTicker ДО того, как эта функция вообще начала работать, через ту же
// candidate - копию устройства в execute_pending_i2c_*() в Samovar.ino), и его
// текущее значение перед вызовом непредсказуемо - список попыток именно ЭТОЙ
// команды обязан начинаться с нуля. Общий дедлайн по millis() (страховка от "20
// попыток по секунде") не меняется.
//
// [Ревью 24.08, замечание 5] Дедлайн - через safety_deadline_after()/
// safety_deadline_expired() (safety_transition.h), а не через ручную арифметику:
// I2CStepper.h подключает samovar_api.h выше по файлу, а тот подключает
// safety_transition.h раньше, чем здесь встречается первое использование - хелперы
// уже видны в точке этого include.
inline bool i2c_stepper_send_command(I2CStepperDevice& dev, uint8_t command) {
  if (!dev.present) return false;
  uint8_t seq = dev.commandSeq + 1;
  if (seq == 0) seq = 1;
  if (!i2c_stepper_write_byte(dev.address, I2CSTEP_REG_COMMAND, command)) return false;
  if (!i2c_stepper_write_byte(dev.address, I2CSTEP_REG_COMMAND_SEQ, seq)) return false;
  uint32_t deadline = safety_deadline_after(millis(), 3000);
  uint8_t failStreak = 0;
  for (uint8_t i = 0; i < 20; i++) {
    vTaskDelay(10 / portTICK_PERIOD_MS);
    if (i2c_stepper_refresh(dev, true)) {
      failStreak = 0;
    } else if (++failStreak >= I2CSTEPPER_FAIL_STREAK_ALERT) {
      break;
    }
    if (dev.ackSeq == seq) break;
    if (safety_deadline_expired(millis(), deadline)) break;
  }
  return dev.present && dev.ackSeq == seq && dev.error == 0;
}

inline bool i2c_stepper_send_confirmed_command(I2CStepperDevice& dev, uint8_t command) {
  if (!dev.present) return false;
  uint8_t seq = dev.commandSeq + 1;
  if (seq == 0) seq = 1;
  for (uint8_t attempt = 0; attempt < 10; attempt++) {
    bool sent = i2c_stepper_write_byte(dev.address, I2CSTEP_REG_COMMAND, command) &&
                i2c_stepper_write_byte(dev.address, I2CSTEP_REG_COMMAND_SEQ, seq);
    vTaskDelay(10 / portTICK_PERIOD_MS);
    if (sent && i2c_stepper_refresh(dev, true) &&
        dev.ackSeq == seq && dev.error == 0) return true;
  }
  return false;
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

inline bool start_second_i2c_pump(float rateLitersPerHour, uint16_t volumeMl) {
  if (use_I2C_dev != I2CSTEPPER_PUMP_ADDR || rateLitersPerHour <= 0) return false;
  if (!i2c_stepper_refresh(i2cStepperPump, true) ||
      !i2c_stepper_config_begin(i2cStepperPump)) return false;

  const uint32_t rateMlHour = (uint32_t)round(rateLitersPerHour * 1000.0f);
  i2cStepperPump.stepsPerMl = i2c_stepper_steps_per_ml();
  i2cStepperPump.optionFlags &= ~I2CSTEPPER_FLAG_DIRECTION;
  if (volumeMl > 0) {
    i2cStepperPump.mode = I2CSTEP_MODE_FILLING;
    i2cStepperPump.fillingMl = volumeMl;
    i2cStepperPump.fillingMlHour =
        rateMlHour > 65535UL ? 65535 : (uint16_t)rateMlHour;
  } else {
    i2cStepperPump.mode = I2CSTEP_MODE_PUMP;
    i2cStepperPump.pumpMlHour =
        rateMlHour > 65535UL ? 65535 : (uint16_t)rateMlHour;
  }
  const bool ok = i2c_stepper_write_config(i2cStepperPump) &&
                  i2c_stepper_send_confirmed_command(i2cStepperPump, I2CSTEP_CMD_START);
  i2c_stepper_config_end(i2cStepperPump);
  return ok;
}

inline bool stop_second_i2c_pump() {
  if (use_I2C_dev != I2CSTEPPER_PUMP_ADDR) return false;
  if (!i2c_stepper_refresh(i2cStepperPump, true) ||
      !i2c_stepper_config_begin(i2cStepperPump)) return false;
  const bool ok = i2c_stepper_send_confirmed_command(i2cStepperPump, I2CSTEP_CMD_STOP);
  i2c_stepper_config_end(i2cStepperPump);
  return ok;
}

inline uint16_t i2c_stepper_mlh_from_step_speed(uint16_t spd) {
  uint16_t stepsPerMl = i2c_stepper_steps_per_ml();
  if (spd == 0 || stepsPerMl == 0) return 0;
  uint32_t mlh = ((uint32_t)spd * 3600UL + stepsPerMl / 2) / stepsPerMl;
  if (mlh == 0) return 1;
  return mlh > 65535UL ? 65535 : (uint16_t)mlh;
}

// [W-4] Чистый пересчёт скорости (шаги/с) из л/ч по SamSetup — БЕЗ I2C.
//        Вынесено из i2c_get_speed_from_rate(), чтобы async-обработчики
//        (/i2cpump) могли считать скорость без блокирующего i2c_stepper_refresh.
inline float i2c_stepper_steps_from_rate(float volume_per_hour) {
  uint16_t stepsPerMl = i2c_stepper_steps_per_ml();
  float v = round(stepsPerMl * volume_per_hour * 1000 / 3.6) / 1000.0;
  if (v < 1) return 1;
  if (v > 65535) return 65535;
  return v;
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
  if (!i2c_stepper_config_begin(i2cStepperMixer)) return false;
  i2cStepperMixer.mode = I2CSTEP_MODE_MIXER;
  i2cStepperMixer.mixerRpm = spd;
  i2cStepperMixer.mixerRunSec = time;
  if (direction) i2cStepperMixer.optionFlags |= I2CSTEPPER_FLAG_DIRECTION;
  else i2cStepperMixer.optionFlags &= ~I2CSTEPPER_FLAG_DIRECTION;
  bool ok = spd == 0 ? i2c_stepper_stop(i2cStepperMixer) : i2c_stepper_start(i2cStepperMixer);
  i2c_stepper_config_end(i2cStepperMixer);
  return ok;
}

inline bool set_stepper_target(
    uint16_t spd,
    uint8_t direction,
    uint32_t target,
    bool requireI2c) {
  if (!i2c_stepper_refresh(i2cStepperPump)) {
    if (requireI2c) return false;
    I2CStepperSpeed = spd;
    CurrrentStepperSpeed = spd;
    stopService();
    if (spd > 0) {
      // direction!=0 в I2C-ветке этой же функции устанавливает I2CSTEPPER_FLAG_DIRECTION -
      // здесь тот же смысл параметра переносим на физическую полярность DIR. reverse()
      // ВЫСТАВЛЯЕТ флаг, а не переключает, поэтому под STEPPER_REVERSE инвертируем, чтобы
      // не затереть компенсацию проводки, заданную в sensorinit.h.
#ifdef STEPPER_REVERSE
      stepper_safe_reverse(direction == 0);
#else
      stepper_safe_reverse(direction != 0);
#endif
      stepper_safe_set_motion(spd, 0, target);
      startService();
    } else {
      stepper_safe_stop_reset();
    }
    return true;
  }

  I2CPumpCmdSpeed = spd;
  I2CPumpTargetSteps = target;
  if (!i2c_stepper_config_begin(i2cStepperPump)) return false;
  if (spd == 0 || target == 0) {
    I2CPumpTargetMl = 0;
    bool ok = i2c_stepper_stop(i2cStepperPump);
    if (ok) I2CStepperSpeed = spd;
    i2c_stepper_config_end(i2cStepperPump);
    return ok;
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
  bool ok = i2c_stepper_start(i2cStepperPump);
  if (ok) I2CStepperSpeed = spd;
  i2c_stepper_config_end(i2cStepperPump);
  return ok;
}

// [T13] Подтверждённая остановка дозирующего насоса по I2C для аварийного тракта.
// Признак "насос на этом аппарате есть" берём из use_I2C_dev (выставляется один раз
// при старте в detect_i2c_steppers() и больше не меняется), а НЕ из i2cStepperPump.present -
// это секундный кэш опроса шины, и разовый сбой чтения регистра (дребезг реле, просадка
// питания в момент самой аварии) сбрасывает его в false. Тогда requireI2c стал бы false,
// set_stepper_target() ушёл бы в локальный запасной путь (степпер по выводам платы,
// к насосу отношения не имеющий) и вернул бы true - латч не взвёлся бы, повтора не было
// бы, а физический насос продолжал бы качать. Если насос обнаружен - останов обязан
// пройти через шину и вернуть реальное подтверждение (requireI2c=true); если насоса на
// аппарате нет вовсе - действует обычный локальный останов степпера (requireI2c=false).
inline bool stop_i2c_pump_confirmed() {
  return set_stepper_target(0, 0, 0, use_I2C_dev == I2CSTEPPER_PUMP_ADDR);
}

inline uint16_t get_stepper_speed(void) {
  if (i2c_stepper_refresh(i2cStepperPump)) return i2cStepperPump.currentSpeed;
  return CurrrentStepperSpeed;
}

inline uint32_t get_stepper_status(void) {
  if (i2c_stepper_refresh(i2cStepperPump)) return (uint32_t)i2cStepperPump.remaining * i2c_stepper_steps_per_ml();
  return stepper_safe_get_target();
}

// Приоритет: если у mixer есть CAP_RELAY и он на связи — используем его,
// иначе — pump с CAP_RELAY. Единая точка бизнес-правила выбора реле-устройства.
inline I2CStepperDevice* select_relay_capable_device() {
  if (i2c_stepper_refresh(i2cStepperMixer) && (i2cStepperMixer.caps & I2CSTEPPER_CAP_RELAY)) return &i2cStepperMixer;
  if (i2c_stepper_refresh(i2cStepperPump) && (i2cStepperPump.caps & I2CSTEPPER_CAP_RELAY)) return &i2cStepperPump;
  return nullptr;
}

inline bool set_mixer_pump_target(uint8_t on) {
  I2CStepperDevice* dev = select_relay_capable_device();
  if (!dev) return false;
  if (!i2c_stepper_config_begin(*dev)) return false;
  if (on) dev->relayMask |= 0x01;
  else dev->relayMask &= ~0x01;
  bool ok = i2c_stepper_write_config(*dev) && i2c_stepper_send_command(*dev, I2CSTEP_CMD_RELAY);
  i2c_stepper_config_end(*dev);
  return ok;
}

inline uint8_t get_mixer_pump_status(void) {
  I2CStepperDevice* dev = select_relay_capable_device();
  if (!dev) return 0xFF;
  return bitRead(dev->relayMask, 0);
}

inline uint8_t get_i2c_rele_state(uint8_t r) {
  if (r < 1 || r > 4) return 0xFF;
  I2CStepperDevice* dev = select_relay_capable_device();
  if (!dev) return 0xFF;
  return bitRead(dev->relayMask, r - 1);
}

inline bool set_i2c_rele_state(uint8_t r, bool s) {
  if (r < 1 || r > 4) return false;
  I2CStepperDevice* dev = select_relay_capable_device();
  if (!dev) return false;
  if (!i2c_stepper_config_begin(*dev)) return false;
  if (s) dev->relayMask |= (1 << (r - 1));
  else dev->relayMask &= ~(1 << (r - 1));
  bool ok = i2c_stepper_write_config(*dev) && i2c_stepper_send_command(*dev, I2CSTEP_CMD_RELAY);
  i2c_stepper_config_end(*dev);
  return ok;
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
  return i2c_stepper_steps_from_rate(volume_per_hour);
}

#endif  //__SAMOVAR_I2CSTEPPER_H_
