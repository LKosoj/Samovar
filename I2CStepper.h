#ifndef __SAMOVAR_I2CSTEPPER_H_
#define __SAMOVAR_I2CSTEPPER_H_

#include <Arduino.h>
#include <Wire.h>
#include <I2CStepperV3.h>

#include "Samovar.h"
#include "samovar_api.h"
#include "debug_i2cstepper_emu.h"

#define I2CSTEPPER_DEVICE_COUNT 10U
#define I2C_LOCK_WAIT_MS 1000
#define I2C_CACHE_LOCK_WAIT_MS 10
#define I2CSTEPPER_HEARTBEAT_MS 250UL
#define I2CSTEPPER_SCAN_MS 100UL
// Бит optionFlags «обратное направление» (I2CSTEPPER_FLAG_DIRECTION в прошивке Nano).
#define I2CSTEPPER_OPTION_DIRECTION 0x04U

struct I2CStepperDevice {
  bool present;
  bool everPresent;
  uint8_t address;
  uint8_t capabilities;
  I2CStepperV3Config config;
  I2CStepperV3Motion motion;
  I2CStepperV3StatusSnapshot status;
  uint32_t lastStopEventSeq;
  uint32_t lastHeartbeatMs;
  uint32_t configGeneration;  // поколение настроек Nano, с которым прочитана копия config
};

inline I2CStepperDevice make_i2c_stepper_device(uint8_t address) {
  I2CStepperDevice device = {};
  device.address = address;
  device.config.address = address;
  device.status.address = address;
  return device;
}

I2CStepperDevice i2cSteppers[I2CSTEPPER_DEVICE_COUNT] = {
  make_i2c_stepper_device(1), make_i2c_stepper_device(2),
  make_i2c_stepper_device(3), make_i2c_stepper_device(4),
  make_i2c_stepper_device(5), make_i2c_stepper_device(6),
  make_i2c_stepper_device(7), make_i2c_stepper_device(8),
  make_i2c_stepper_device(9), make_i2c_stepper_device(10),
};

volatile uint32_t i2c_config_in_flight = 0;
uint8_t i2cStepperScanAddress = I2CSTEPPER_V3_ADDRESS_MIN;
uint32_t i2cStepperLastScanMs = 0;
volatile bool i2cStepperScanActive = true;
uint8_t i2cStepperSessionMixerAddress = 0;
uint8_t i2cStepperSessionPumpAddress = 0;
// Номер последнего отправленного кадра команды по каждому адресу. Хранится отдельно от
// device.status: статус мог не прочитаться после записи, а копии-кандидаты отбрасываются.
uint32_t i2cStepperLastSentSeq[I2CSTEPPER_DEVICE_COUNT] = {};
// Оператор сам остановил или запустил мешалку процесса (энкодер Nano, вкладка I2CStepper).
// Пока флаг стоит, расписание режима её не трогает; снимается сменой строки программы,
// концом процесса или кнопкой «Вернуть управление программе».
volatile bool i2cStepperMixerManualHold = false;
// Поправка скорости оператором на время процесса: подменяет скорость, которую задаёт программа
// (мешалка - об/мин, насос - л/ч; 0 = поправки нет). Иначе программа возвращает свою скорость.
uint16_t i2cStepperMixerRpmOverride = 0;
float i2cStepperPumpRateOverride = 0.0f;
// Направление с вкладки I2CStepper вместо программного: 0 - как в программе, 1 - прямое, 2 - обратное.
uint8_t i2cStepperMixerDirOverride = 0;
uint8_t i2cStepperPumpDirOverride = 0;

inline I2CStepperDevice* i2c_stepper_device(uint8_t address) {
  if (!i2cstepper_v3_address_valid(address)) return nullptr;
  return &i2cSteppers[address - I2CSTEPPER_V3_ADDRESS_MIN];
}

// Общая проверка шины нужна LCD и не относится к адресам или кадрам I2CStepper v3.
inline uint8_t check_I2C_device(uint8_t address,
                                TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  if (xSemaphoreTake(xI2CSemaphore,
                     TickType_t(lockWaitMs / portTICK_PERIOD_MS)) != pdTRUE) return 0;
  Wire.beginTransmission(address);
  const uint8_t result = Wire.endTransmission();
  xSemaphoreGive(xI2CSemaphore);
  return result == 0 ? address : 0;
}

inline uint32_t i2c_stepper_config_bit(uint8_t address) {
  return uint32_t(1U) << (address - I2CSTEPPER_V3_ADDRESS_MIN);
}

inline bool i2c_stepper_config_begin(const I2CStepperDevice& device) {
  const uint32_t bit = i2c_stepper_config_bit(device.address);
  uint32_t current = 0;
  do {
    current = i2c_config_in_flight;
    if ((current & bit) != 0) return false;
  } while (!__sync_bool_compare_and_swap(&i2c_config_in_flight, current, current | bit));
  return true;
}

inline void i2c_stepper_config_end(const I2CStepperDevice& device) {
  const uint32_t bit = i2c_stepper_config_bit(device.address);
  uint32_t current = 0;
  do {
    current = i2c_config_in_flight;
  } while (!__sync_bool_compare_and_swap(&i2c_config_in_flight, current, current & ~bit));
}

inline bool i2c_stepper_config_busy(const I2CStepperDevice& device) {
  return (i2c_config_in_flight & i2c_stepper_config_bit(device.address)) != 0;
}

inline uint32_t i2c_stepper_command_bit(uint8_t address) {
  return i2c_stepper_config_bit(address) << I2CSTEPPER_DEVICE_COUNT;
}

inline bool i2c_stepper_command_begin(const I2CStepperDevice& device) {
  const uint32_t bit = i2c_stepper_command_bit(device.address);
  uint32_t current = 0;
  do {
    current = i2c_config_in_flight;
    if ((current & bit) != 0) return false;
  } while (!__sync_bool_compare_and_swap(&i2c_config_in_flight, current, current | bit));
  return true;
}

inline void i2c_stepper_command_end(const I2CStepperDevice& device) {
  const uint32_t bit = i2c_stepper_command_bit(device.address);
  uint32_t current = 0;
  do {
    current = i2c_config_in_flight;
  } while (!__sync_bool_compare_and_swap(&i2c_config_in_flight, current, current & ~bit));
}

inline bool i2c_stepper_read_block(uint8_t address, uint8_t reg, uint8_t* data,
                                   uint8_t len, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS,
                                   bool* lockBusy = nullptr) {
  if (lockBusy) *lockBusy = false;
  if (address == 0 || address > 0x7F || !data ||
      !i2cstepper_v3_read_size_valid(len)) return false;
  if (xSemaphoreTake(xI2CSemaphore,
                     TickType_t(lockWaitMs / portTICK_PERIOD_MS)) != pdTRUE) {
    if (lockBusy) *lockBusy = true;
    return false;
  }
#ifdef __SAMOVAR_DEBUG
  bool emulated = false;
  if (debug_i2c_emu_read(address, reg, data, len, millis(), emulated)) {
    xSemaphoreGive(xI2CSemaphore);
    return emulated;
  }
#endif
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    xSemaphoreGive(xI2CSemaphore);
    return false;
  }
  const uint8_t received = Wire.requestFrom(address, len);
  if (received != len) {
    xSemaphoreGive(xI2CSemaphore);
    return false;
  }
  for (uint8_t index = 0; index < len; index++) data[index] = Wire.read();
  xSemaphoreGive(xI2CSemaphore);
  return true;
}

inline bool i2c_stepper_write_block(uint8_t address, uint8_t reg,
                                    const uint8_t* payload, uint8_t payloadSize,
                                    TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  if (address == 0 || address > 0x7F || !payload ||
      !i2cstepper_v3_write_payload_size_valid(payloadSize)) return false;
  if (xSemaphoreTake(xI2CSemaphore,
                     TickType_t(lockWaitMs / portTICK_PERIOD_MS)) != pdTRUE) return false;
#ifdef __SAMOVAR_DEBUG
  bool emulated = false;
  if (debug_i2c_emu_write(address, reg, payload, payloadSize, millis(), emulated)) {
    xSemaphoreGive(xI2CSemaphore);
    return emulated;
  }
#endif
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(payload, payloadSize);
  const bool ok = Wire.endTransmission() == 0;
  xSemaphoreGive(xI2CSemaphore);
  return ok;
}

// Эти primitive-функции обслуживают ADS1115 в cheese.h; к протоколу v3 они не относятся.
inline bool i2c_stepper_read_u16(uint8_t address, uint8_t reg, uint16_t& value,
                                 TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  uint8_t bytes[2] = {};
  if (!i2c_stepper_read_block(address, reg, bytes, sizeof(bytes), lockWaitMs)) return false;
  value = i2cstepper_v3_read_u16_be(bytes);
  return true;
}

inline bool i2c_stepper_write_u16(uint8_t address, uint8_t reg, uint16_t value) {
  uint8_t bytes[2] = {};
  i2cstepper_v3_write_u16_be(bytes, value);
  return i2c_stepper_write_block(address, reg, bytes, sizeof(bytes));
}

inline bool i2c_stepper_read_identity(I2CStepperDevice& device,
                                      TickType_t lockWaitMs = I2C_LOCK_WAIT_MS,
                                      bool* lockBusy = nullptr) {
  if (lockBusy) *lockBusy = false;
  uint8_t bytes[I2CSTEPPER_V3_IDENTITY_SIZE] = {};
  I2CStepperV3Identity identity{};
  if (!i2c_stepper_read_block(device.address, I2CSTEPPER_V3_REG_IDENTITY,
                              bytes, sizeof(bytes), lockWaitMs, lockBusy) ||
      !i2cstepper_v3_decode_identity(bytes, &identity) ||
      identity.address != device.address) return false;
  device.capabilities = identity.capabilities;
  return true;
}

inline bool i2c_stepper_read_config(I2CStepperDevice& device,
                                    TickType_t lockWaitMs = I2C_LOCK_WAIT_MS,
                                    bool* lockBusy = nullptr) {
  if (lockBusy) *lockBusy = false;
  for (uint8_t attempt = 0; attempt < 2; attempt++) {
    uint8_t statusBeforeBytes[I2CSTEPPER_V3_STATUS_SIZE] = {};
    uint8_t configA[I2CSTEPPER_V3_CONFIG_A_SIZE] = {};
    uint8_t configB[I2CSTEPPER_V3_CONFIG_B_SIZE] = {};
    uint8_t statusAfterBytes[I2CSTEPPER_V3_STATUS_SIZE] = {};
    I2CStepperV3StatusSnapshot statusBefore{};
    I2CStepperV3StatusSnapshot statusAfter{};
    I2CStepperV3Config config{};
    if (!i2c_stepper_read_block(device.address, I2CSTEPPER_V3_REG_STATUS,
                                statusBeforeBytes, sizeof(statusBeforeBytes), lockWaitMs, lockBusy) ||
        !i2cstepper_v3_decode_status(statusBeforeBytes, &statusBefore) ||
        statusBefore.address != device.address ||
        statusBefore.mode < I2CSTEPPER_V3_MODE_MIXER ||
        statusBefore.mode > I2CSTEPPER_V3_MODE_FILLING ||
        !i2c_stepper_read_block(device.address, I2CSTEPPER_V3_REG_CONFIG_A,
                                configA, sizeof(configA), lockWaitMs, lockBusy) ||
        !i2c_stepper_read_block(device.address, I2CSTEPPER_V3_REG_CONFIG_B,
                                configB, sizeof(configB), lockWaitMs, lockBusy) ||
        !i2c_stepper_read_block(device.address, I2CSTEPPER_V3_REG_STATUS,
                                statusAfterBytes, sizeof(statusAfterBytes), lockWaitMs, lockBusy) ||
        !i2cstepper_v3_decode_status(statusAfterBytes, &statusAfter) ||
        statusAfter.address != device.address) return false;
    if (statusAfter.generation != statusBefore.generation) continue;
    i2cstepper_v3_decode_config_a(configA, &config);
    i2cstepper_v3_decode_config_b(configB, &config);
    if (!i2cstepper_v3_address_valid(config.address) ||
        !i2cstepper_v3_mode_supported(config.address, config.mode)) return false;
    device.config = config;
    device.status = statusAfter;
    device.configGeneration = statusAfter.generation;
    return true;
  }
  return false;
}

inline void i2c_stepper_note_refresh_failure(I2CStepperDevice& device) {
  const bool selected = device.address == i2cStepperSessionMixerAddress ||
                        device.address == i2cStepperSessionPumpAddress;
  if (device.present && selected) {
    SendMsg(String(F("Потеря связи с I2C степпером, адрес ")) + device.address,
            ALARM_MSG);
  }
  device.present = false;
}

// Адрес мешалки сессии вне процесса равен 0, поэтому флаг ставится только во время процесса.
inline void i2c_stepper_note_manual_control(uint8_t address) {
  if (address == i2cStepperSessionMixerAddress) i2cStepperMixerManualHold = true;
}

inline bool i2c_stepper_refresh(I2CStepperDevice& device, bool force = false,
                                TickType_t lockWaitMs = I2C_LOCK_WAIT_MS,
                                bool noteFailure = true, bool* lockBusy = nullptr) {
  if (lockBusy) *lockBusy = false;
  if (!force && i2c_stepper_config_busy(device)) return device.present;
  uint8_t bytes[I2CSTEPPER_V3_STATUS_SIZE] = {};
  I2CStepperV3StatusSnapshot status{};
  if (!i2c_stepper_read_block(device.address, I2CSTEPPER_V3_REG_STATUS,
                              bytes, sizeof(bytes), lockWaitMs, lockBusy) ||
      !i2cstepper_v3_decode_status(bytes, &status) ||
      status.address != device.address ||
      status.mode < I2CSTEPPER_V3_MODE_MIXER ||
      status.mode > I2CSTEPPER_V3_MODE_FILLING) {
    if (noteFailure) i2c_stepper_note_refresh_failure(device);
    return false;
  }
  const bool localStop = status.stopReason == I2CSTEPPER_V3_STOP_LOCAL &&
                         status.stopEventSeq != 0 &&
                         status.stopEventSeq != device.lastStopEventSeq;
  device.status = status;
  device.present = true;
  device.everPresent = true;
  if (localStop) {
    device.lastStopEventSeq = status.stopEventSeq;
    SendMsg(String(F("Локальный останов I2C степпера, адрес ")) + device.address,
            ALARM_MSG);
    i2c_stepper_note_manual_control(device.address);
  }
  return true;
}

inline bool i2c_stepper_probe(I2CStepperDevice& device, bool* lockBusyOut = nullptr) {
  bool lockBusy = false;
  if (lockBusyOut) *lockBusyOut = false;
  if (!i2c_stepper_read_identity(device, I2C_CACHE_LOCK_WAIT_MS, &lockBusy)) {
    if (!lockBusy) i2c_stepper_note_refresh_failure(device);
    if (lockBusyOut) *lockBusyOut = lockBusy;
    return false;
  }
  if (!i2c_stepper_read_config(device, I2C_CACHE_LOCK_WAIT_MS, &lockBusy) ||
      !i2c_stepper_refresh(device, true, I2C_CACHE_LOCK_WAIT_MS, false, &lockBusy)) {
    if (!lockBusy) i2c_stepper_note_refresh_failure(device);
    if (lockBusyOut) *lockBusyOut = lockBusy;
    return false;
  }
  return true;
}

inline void i2c_stepper_scan_begin() {
  i2cStepperScanAddress = I2CSTEPPER_V3_ADDRESS_MIN;
  i2cStepperLastScanMs = 0;
  i2cStepperScanActive = true;
}

inline void i2c_stepper_scan_step() {
  if (!i2cStepperScanActive) return;
  I2CStepperDevice* device = i2c_stepper_device(i2cStepperScanAddress);
  bool lockBusy = false;
  if (device) i2c_stepper_probe(*device, &lockBusy);
  // Шина была занята (обычно экраном): адрес не проверен, повторяем его на следующем шаге.
  if (lockBusy) return;
  if (i2cStepperScanAddress == I2CSTEPPER_V3_ADDRESS_MAX) {
    i2cStepperScanActive = false;
  } else {
    i2cStepperScanAddress++;
  }
}

inline uint8_t i2c_stepper_present_count() {
  uint8_t count = 0;
  for (uint8_t index = 0; index < I2CSTEPPER_DEVICE_COUNT; index++) {
    if (i2cSteppers[index].present) count++;
  }
  return count;
}

inline I2CStepperDevice* i2c_stepper_lowest_present(bool mixer) {
  for (uint8_t address = I2CSTEPPER_V3_ADDRESS_MIN;
       address <= I2CSTEPPER_V3_ADDRESS_MAX; address++) {
    if (i2cstepper_v3_address_is_mixer(address) != mixer) continue;
    I2CStepperDevice* device = i2c_stepper_device(address);
    if (device && device->present) return device;
  }
  return nullptr;
}

inline void i2c_stepper_session_begin() {
  I2CStepperDevice* mixer = i2c_stepper_lowest_present(true);
  I2CStepperDevice* pump = i2c_stepper_lowest_present(false);
  i2cStepperSessionMixerAddress = mixer ? mixer->address : 0;
  i2cStepperSessionPumpAddress = pump ? pump->address : 0;
  i2cStepperMixerManualHold = false;
  i2cStepperMixerRpmOverride = 0;
  i2cStepperPumpRateOverride = 0.0f;
  i2cStepperMixerDirOverride = 0;
  i2cStepperPumpDirOverride = 0;
}

inline void i2c_stepper_session_end() {
  i2cStepperSessionMixerAddress = 0;
  i2cStepperSessionPumpAddress = 0;
  i2cStepperMixerManualHold = false;
  i2cStepperMixerRpmOverride = 0;
  i2cStepperPumpRateOverride = 0.0f;
  i2cStepperMixerDirOverride = 0;
  i2cStepperPumpDirOverride = 0;
}

inline bool i2c_stepper_session_active() {
  return startval != SAMOVAR_STARTVAL_IDLE || PowerOn;
}

inline void i2c_stepper_session_end_if_idle() {
  if (!i2c_stepper_session_active()) {
    i2c_stepper_session_end();
  }
}

inline I2CStepperDevice* i2c_stepper_selected_mixer() {
  return i2c_stepper_session_active()
      ? i2c_stepper_device(i2cStepperSessionMixerAddress)
      : i2c_stepper_lowest_present(true);
}

inline I2CStepperDevice* i2c_stepper_selected_pump() {
  return i2c_stepper_session_active()
      ? i2c_stepper_device(i2cStepperSessionPumpAddress)
      : i2c_stepper_lowest_present(false);
}

inline bool i2c_stepper_write_config(I2CStepperDevice& device) {
  uint8_t configA[I2CSTEPPER_V3_CONFIG_A_SIZE] = {};
  uint8_t configB[I2CSTEPPER_V3_CONFIG_B_SIZE] = {};
  i2cstepper_v3_encode_config_a(configA, &device.config);
  i2cstepper_v3_encode_config_b(configB, &device.config);
  return i2c_stepper_write_block(device.address, I2CSTEPPER_V3_REG_CONFIG_A,
                                 configA, sizeof(configA)) &&
         i2c_stepper_write_block(device.address, I2CSTEPPER_V3_REG_CONFIG_B,
                                 configB, sizeof(configB));
}

inline bool i2c_stepper_write_motion(I2CStepperDevice& device) {
  uint8_t motion[I2CSTEPPER_V3_MOTION_SIZE] = {};
  i2cstepper_v3_encode_motion(motion, &device.motion);
  return i2c_stepper_write_block(device.address, I2CSTEPPER_V3_REG_MOTION,
                                 motion, sizeof(motion));
}

// Новый номер обязан быть позже и подтверждённого Nano, и уже отправленного нами: иначе
// команда совпадёт с предыдущим кадром (например heartbeat, чей статус не прочитался),
// Nano отбросит её как дубликат, а чужой SUCCESS будет принят за её результат.
inline uint32_t i2c_stepper_next_command_seq(const I2CStepperDevice& device) {
  uint32_t& sent = i2cStepperLastSentSeq[device.address - I2CSTEPPER_V3_ADDRESS_MIN];
  const uint32_t base = i2cstepper_v3_sequence_after(sent, device.status.commandSeq)
      ? sent : device.status.commandSeq;
  sent = i2cstepper_v3_sequence_next(base);
  return sent;
}

inline bool i2c_stepper_send_command(I2CStepperDevice& device, uint8_t command) {
  if (!i2c_stepper_command_begin(device)) return false;
  I2CStepperV3CommandFrame frame{};
  frame.address = device.address;
  frame.command = command;
  frame.commandSeq = i2c_stepper_next_command_seq(device);
  uint8_t bytes[I2CSTEPPER_V3_COMMAND_SIZE] = {};
  i2cstepper_v3_encode_command(bytes, &frame);
  const uint32_t deadline = millis() + 3000UL;
  bool succeeded = false;
  do {
    // При неясном результате write или задержанном ACK повторяем тот же кадр:
    // Nano вернёт кэшированный результат duplicate-command, не запуская действие снова.
    i2c_stepper_write_block(device.address, I2CSTEPPER_V3_REG_COMMAND,
                            bytes, sizeof(bytes));
    vTaskDelay(10 / portTICK_PERIOD_MS);
    // PENDING: Nano приняла команду и ещё выполняет её (запись EEPROM) - ждём итог.
    if (i2c_stepper_refresh(device, true) && device.status.ackSeq == frame.commandSeq &&
        device.status.commandResult != I2CSTEPPER_V3_RESULT_PENDING) {
      succeeded = device.status.commandResult == I2CSTEPPER_V3_RESULT_SUCCESS &&
                  device.status.error == I2CSTEPPER_V3_ERR_NONE;
      break;
    }
  } while ((int32_t)(millis() - deadline) < 0);
  i2c_stepper_command_end(device);
  return succeeded;
}

// Heartbeat is deliberately one attempt: unlike a work command it must not
// hold the loop for its three-second retry window when one Nano disappeared.
inline bool i2c_stepper_send_heartbeat(I2CStepperDevice& device) {
  if (!i2c_stepper_command_begin(device)) return false;
  I2CStepperV3CommandFrame frame{};
  frame.address = device.address;
  frame.command = I2CSTEPPER_V3_CMD_HEARTBEAT;
  frame.commandSeq = i2c_stepper_next_command_seq(device);
  uint8_t bytes[I2CSTEPPER_V3_COMMAND_SIZE] = {};
  i2cstepper_v3_encode_command(bytes, &frame);
  const bool written = i2c_stepper_write_block(device.address,
                                                I2CSTEPPER_V3_REG_COMMAND,
                                                bytes, sizeof(bytes), 0);
  // Background heartbeat must yield immediately to an active I2C transaction.
  // A zero-wait miss is not a device failure and must not make it unavailable.
  const bool acknowledged = written && i2c_stepper_refresh(device, true, 0, false) &&
      device.status.ackSeq == frame.commandSeq &&
      device.status.commandResult == I2CSTEPPER_V3_RESULT_SUCCESS &&
      device.status.error == I2CSTEPPER_V3_ERR_NONE;
  i2c_stepper_command_end(device);
  return acknowledged;
}

inline bool i2c_stepper_apply(I2CStepperDevice& device) {
  if (!i2c_stepper_write_config(device) ||
      !i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_APPLY)) return false;
  // Поколение выросло ровно на наш APPLY: копия config совпадает с Nano, перечитывать незачем.
  if (device.status.generation == device.configGeneration + 1) device.configGeneration++;
  return true;
}

inline bool i2c_stepper_save(I2CStepperDevice& device) {
  return i2c_stepper_write_config(device) &&
         i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_SAVE);
}

inline bool i2c_stepper_start_finite(I2CStepperDevice& device) {
  return i2cstepper_v3_start_mode_supported(device.config.mode, device.motion.mode,
                                             I2CSTEPPER_V3_CMD_START_FINITE) &&
         i2c_stepper_apply(device) &&
         i2c_stepper_write_motion(device) &&
         i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_START_FINITE);
}

inline bool i2c_stepper_start_continuous(I2CStepperDevice& device) {
  return i2cstepper_v3_start_mode_supported(device.config.mode, device.motion.mode,
                                             I2CSTEPPER_V3_CMD_START_CONTINUOUS) &&
         i2c_stepper_apply(device) &&
         i2c_stepper_write_motion(device) &&
         i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_START_CONTINUOUS);
}

inline bool i2c_stepper_stop(I2CStepperDevice& device) {
  return i2c_stepper_send_command(device, I2CSTEPPER_V3_CMD_STOP);
}

// Настройки сохранили с меню Nano (поколение в статусе ушло вперёд): обновляем копию, иначе
// следующий запуск вернёт в Nano устаревшие значения и посчитает дозу по старой калибровке.
inline void i2c_stepper_sync_config(I2CStepperDevice& device) {
  if (device.status.generation == device.configGeneration ||
      !i2c_stepper_config_begin(device)) return;
  i2c_stepper_read_config(device, I2C_CACHE_LOCK_WAIT_MS);
  i2c_stepper_config_end(device);
}

inline void i2c_stepper_tick() {
  const uint32_t now = millis();
  if (i2cStepperScanActive && now - i2cStepperLastScanMs >= I2CSTEPPER_SCAN_MS) {
    i2cStepperLastScanMs = now;
    i2c_stepper_scan_step();
  }
  for (uint8_t index = 0; index < I2CSTEPPER_DEVICE_COUNT; index++) {
    I2CStepperDevice& device = i2cSteppers[index];
    if (!device.present || now - device.lastHeartbeatMs < I2CSTEPPER_HEARTBEAT_MS) continue;
    if (i2c_stepper_send_heartbeat(device)) device.lastHeartbeatMs = now;
    i2c_stepper_sync_config(device);
  }
}

inline bool i2c_stepper_mixer_present() {
  I2CStepperDevice* device = i2c_stepper_selected_mixer();
  return device && device->present;
}

inline bool i2c_stepper_pump_present() {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  return device && device->present;
}

inline float i2c_get_liquid_volume_by_step(uint32_t steps) {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  return device && device->present && device->config.stepsPerMl > 0
      ? static_cast<float>(steps) / device->config.stepsPerMl : 0.0f;
}

inline float i2c_get_liquid_rate_by_step(uint32_t stepsPerSecond) {
  return round(i2c_get_liquid_volume_by_step(stepsPerSecond) * 3.6f * 1000.0f) / 1000.0f;
}

// Скорость мешалки задаётся в об/мин (так её передают Пиво, Сыр и Lua). Число шагов на
// оборот знает только Nano, поэтому шлём ей настройки мешалки и START_CONFIGURED, а не
// готовые шаги/с. Паузу обнуляем: циклом «работа/пауза» управляет Самовар.
inline bool set_stepper_by_time(uint32_t rpm, uint8_t direction, uint32_t seconds) {
  I2CStepperDevice* device = i2c_stepper_selected_mixer();
  if (!device || !device->present) return false;
  if (rpm == 0) return i2c_stepper_stop(*device);
  if (i2cStepperMixerRpmOverride) rpm = i2cStepperMixerRpmOverride;
  if (i2cStepperMixerDirOverride) direction = i2cStepperMixerDirOverride - 1;
  device->config.mode = I2CSTEPPER_V3_MODE_MIXER;
  device->config.mixerRpm = rpm;
  device->config.mixerRunSec = seconds;
  device->config.mixerPauseSec = 0;
  if (direction) device->config.optionFlags |= I2CSTEPPER_OPTION_DIRECTION;
  else device->config.optionFlags &= uint8_t(~I2CSTEPPER_OPTION_DIRECTION);
  return i2c_stepper_apply(*device) &&
         i2c_stepper_send_command(*device, I2CSTEPPER_V3_CMD_START_CONFIGURED);
}

inline float i2c_get_speed_from_rate(float litersPerHour) {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  if (!device || !device->present || device->config.stepsPerMl == 0 || litersPerHour <= 0.0f) return 0.0f;
  return roundf(litersPerHour * 1000.0f * device->config.stepsPerMl / 3600.0f);
}

inline float i2c_stepper_steps_from_rate(float litersPerHour) {
  return i2c_get_speed_from_rate(litersPerHour);
}

inline bool set_stepper_target(uint32_t speedStepsPerSecond, uint8_t direction,
                               uint32_t targetSteps, bool requireI2c) {
  (void)requireI2c;
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  if (!device || !device->present) return false;
  if (speedStepsPerSecond == 0 || targetSteps == 0) return i2c_stepper_stop(*device);
  if (targetSteps > I2CSTEPPER_V3_TARGET_STEPS_MAX ||
      speedStepsPerSecond > I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC) return false;
  device->config.mode = I2CSTEPPER_V3_MODE_FILLING;
  device->motion.mode = I2CSTEPPER_V3_MODE_FILLING;
  device->motion.direction = direction;
  device->motion.speedStepsPerSec = speedStepsPerSecond;
  device->motion.targetSteps = targetSteps;
  return i2c_stepper_start_finite(*device);
}

inline bool start_second_i2c_pump_steps(float rateLitersPerHour, uint32_t targetSteps) {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  if (!device || !device->present || rateLitersPerHour <= 0.0f) return false;
  if (i2cStepperPumpRateOverride > 0.0f) rateLitersPerHour = i2cStepperPumpRateOverride;
  const float speed = i2c_get_speed_from_rate(rateLitersPerHour);
  if (speed <= 0.0f || speed > I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC) return false;
  if (targetSteps == 0) return false;
  device->config.mode = I2CSTEPPER_V3_MODE_FILLING;
  device->motion.mode = device->config.mode;
  device->motion.direction = i2cStepperPumpDirOverride ? i2cStepperPumpDirOverride - 1 : 0;
  device->motion.speedStepsPerSec = uint32_t(speed);
  if (targetSteps > I2CSTEPPER_V3_TARGET_STEPS_MAX) return false;
  device->motion.targetSteps = targetSteps;
  return i2c_stepper_start_finite(*device);
}

inline bool start_second_i2c_pump(float rateLitersPerHour, uint16_t volumeMl) {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  if (!device || !device->present || rateLitersPerHour <= 0.0f) return false;
  if (i2cStepperPumpRateOverride > 0.0f) rateLitersPerHour = i2cStepperPumpRateOverride;
  if (volumeMl == 0) {
    const float speed = i2c_get_speed_from_rate(rateLitersPerHour);
    if (speed <= 0.0f || speed > I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC) return false;
    device->config.mode = I2CSTEPPER_V3_MODE_PUMP;
    device->motion.mode = I2CSTEPPER_V3_MODE_PUMP;
    device->motion.direction = i2cStepperPumpDirOverride ? i2cStepperPumpDirOverride - 1 : 0;
    device->motion.speedStepsPerSec = uint32_t(speed);
    device->motion.targetSteps = 0;
    return i2c_stepper_start_continuous(*device);
  }
  if (device->config.stepsPerMl == 0) return false;
  const uint64_t targetSteps = uint64_t(volumeMl) * device->config.stepsPerMl;
  return targetSteps <= I2CSTEPPER_V3_TARGET_STEPS_MAX &&
      start_second_i2c_pump_steps(rateLitersPerHour, uint32_t(targetSteps));
}

// Новая скорость и направление с вкладки I2CStepper (direction: 0 - как в программе, 1 - прямое,
// 2 - обратное). Если привод сейчас крутится - перезапускаем его (время и остаток шагов
// прежние); стоит - применится при пуске.
inline bool i2c_stepper_override_mixer_rpm(uint16_t rpm, uint8_t direction) {
  I2CStepperDevice* device = i2c_stepper_selected_mixer();
  if (!device || !device->present || rpm == 0) return false;
  // Допустимые обороты знает только Nano (шаги на оборот): проверяем через APPLY, и лишь
  // потом запоминаем скорость - иначе недопустимое число сорвало бы все пуски по расписанию.
  const I2CStepperV3Config previous = device->config;
  device->config.mixerRpm = rpm;
  if (direction == 2) device->config.optionFlags |= I2CSTEPPER_OPTION_DIRECTION;
  else if (direction == 1) device->config.optionFlags &= uint8_t(~I2CSTEPPER_OPTION_DIRECTION);
  if (!i2c_stepper_apply(*device)) {
    device->config = previous;
    return false;
  }
  i2cStepperMixerRpmOverride = rpm;
  i2cStepperMixerDirOverride = direction;
  if (i2cStepperMixerManualHold ||
      (device->status.status & I2CSTEPPER_V3_STATUS_RUNNING) == 0) return true;
  return i2c_stepper_send_command(*device, I2CSTEPPER_V3_CMD_START_CONFIGURED);
}

inline bool i2c_stepper_override_pump_rate(float rateLitersPerHour, uint8_t direction) {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  if (!device || !device->present) return false;
  const float speed = i2c_get_speed_from_rate(rateLitersPerHour);
  if (speed < 1.0f || speed > I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC) return false;
  i2cStepperPumpRateOverride = rateLitersPerHour;
  i2cStepperPumpDirOverride = direction;
  if ((device->status.status & I2CSTEPPER_V3_STATUS_RUNNING) == 0) return true;
  if (device->motion.targetSteps == 0) return start_second_i2c_pump(rateLitersPerHour, 0);
  if (!i2c_stepper_refresh(*device, true)) return false;
  return device->status.remainingSteps == 0 ||
         start_second_i2c_pump_steps(rateLitersPerHour, device->status.remainingSteps);
}

inline bool stop_second_i2c_pump() {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  return device && device->present && i2c_stepper_stop(*device);
}

inline uint32_t get_stepper_speed() {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  return device && device->present ? device->status.currentSpeedStepsPerSec : 0;
}

inline uint32_t get_stepper_status() {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  return device && device->present ? device->status.remainingSteps : 0;
}

inline bool stop_i2c_pump_confirmed() {
  I2CStepperDevice* device = i2c_stepper_selected_pump();
  return device && device->present && i2c_stepper_stop(*device);
}

inline I2CStepperDevice* select_relay_capable_device() {
  I2CStepperDevice* mixer = i2c_stepper_selected_mixer();
  if (mixer && mixer->present &&
      (mixer->capabilities & I2CSTEPPER_V3_CAP_RELAY)) return mixer;
  I2CStepperDevice* pump = i2c_stepper_selected_pump();
  return pump && pump->present &&
      (pump->capabilities & I2CSTEPPER_V3_CAP_RELAY) ? pump : nullptr;
}

inline bool set_i2c_rele_state(uint8_t relay, bool state) {
  if (relay < 1 || relay > 4) return false;
  I2CStepperDevice* device = select_relay_capable_device();
  if (!device) return false;
  if (!i2c_stepper_config_begin(*device)) return false;
  I2CStepperDevice candidate = *device;
  if (!i2c_stepper_read_config(candidate)) {
    i2c_stepper_config_end(*device);
    return false;
  }
  if (state) candidate.config.relayMask |= uint8_t(1U << (relay - 1));
  else candidate.config.relayMask &= uint8_t(~(1U << (relay - 1)));
  const bool succeeded = i2c_stepper_write_config(candidate) &&
      i2c_stepper_send_command(candidate, I2CSTEPPER_V3_CMD_RELAY);
  if (succeeded) *device = candidate;
  i2c_stepper_config_end(*device);
  return succeeded;
}

inline uint8_t get_i2c_rele_state(uint8_t relay) {
  I2CStepperDevice* device = select_relay_capable_device();
  return !device || relay < 1 || relay > 4 ? 0xFF :
      uint8_t((device->config.relayMask >> (relay - 1)) & 1U);
}

inline bool set_mixer_pump_target(uint8_t on) { return set_i2c_rele_state(1, on != 0); }
inline uint8_t get_mixer_pump_status() { return get_i2c_rele_state(1); }

#endif  // __SAMOVAR_I2CSTEPPER_H_
