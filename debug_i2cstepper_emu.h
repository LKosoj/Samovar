#pragma once

// Отладка без железа: вместо плат I2CStepper на шине отвечает эмулятор - мешалка на адресе 1
// и насос на адресе 2. Подменяется только обмен блоками регистров, поэтому остальной код
// (сканирование, команды с номерами, пульс, вкладка I2CStepper) работает как с настоящей Nano.
// Мотор «крутится» по времени: пройденные шаги = скорость * прошедшие секунды.

#ifdef __SAMOVAR_DEBUG

#include <stdint.h>
#include <I2CStepperV3.h>

#define DEBUG_I2C_EMU_COUNT 2U
#define DEBUG_I2C_EMU_MIXER_STEPS 400UL  // шагов на оборот, как STEPPER_STEPS в прошивке Nano

struct DebugI2CNano {
  I2CStepperV3Config active;
  I2CStepperV3Config staging;
  I2CStepperV3Motion motion;
  I2CStepperV3StatusSnapshot status;
  uint32_t lastSeq;
  bool busy;          // привод занят: мотор крутится или идёт пауза цикла мешалки
  bool paused;
  bool calibration;
  uint32_t speed;     // шагов в секунду
  uint32_t target;    // шагов до остановки, 0 - без остановки
  uint32_t phaseMs;   // начало текущей фазы (вращение или пауза)
};

DebugI2CNano debugI2CNanos[DEBUG_I2C_EMU_COUNT] = {};

inline DebugI2CNano* debug_i2c_nano(uint8_t address) {
  if (address < 1 || address > DEBUG_I2C_EMU_COUNT) return nullptr;
  DebugI2CNano& nano = debugI2CNanos[address - 1];
  if (nano.active.address == 0) {  // первое обращение: настройки Nano по умолчанию
    nano.active.address = address;
    nano.active.mode = i2cstepper_v3_address_is_mixer(address) ? I2CSTEPPER_V3_MODE_MIXER
                                                                : I2CSTEPPER_V3_MODE_PUMP;
    nano.active.optionFlags = 0x02;  // плавный пуск
    nano.active.sensorFlags = 0x02;  // датчик останавливает привод
    nano.active.mixerRpm = 20;
    nano.active.pumpMlHour = 100;
    nano.active.fillingMl = 100;
    nano.active.fillingMlHour = 100;
    nano.active.stepsPerMl = 16000;
    nano.staging = nano.active;
    nano.status.address = address;
    nano.status.generation = 1;
  }
  return &nano;
}

inline uint32_t debug_i2c_rate_steps(uint32_t value, uint32_t factor, uint32_t divisor) {
  return uint32_t((uint64_t(value) * factor + divisor / 2U) / divisor);
}

inline uint32_t debug_i2c_config_speed(const I2CStepperV3Config& config) {
  if (config.mode == I2CSTEPPER_V3_MODE_MIXER) {
    return debug_i2c_rate_steps(config.mixerRpm, DEBUG_I2C_EMU_MIXER_STEPS, 60U);
  }
  return debug_i2c_rate_steps(config.mode == I2CSTEPPER_V3_MODE_PUMP ? config.pumpMlHour
                                                                     : config.fillingMlHour,
                              config.stepsPerMl, 3600U);
}

inline uint64_t debug_i2c_config_target(const I2CStepperV3Config& config) {
  if (config.mode == I2CSTEPPER_V3_MODE_MIXER) {
    return uint64_t(debug_i2c_config_speed(config)) * config.mixerRunSec;
  }
  return config.mode == I2CSTEPPER_V3_MODE_FILLING ? uint64_t(config.fillingMl) * config.stepsPerMl
                                                   : 0;
}

inline bool debug_i2c_config_valid(const I2CStepperV3Config& config) {
  if (!i2cstepper_v3_mode_supported(config.address, config.mode) ||
      config.stepsPerMl == 0 || (config.relayMask & 0xF0U) != 0) return false;
  const uint32_t speed = debug_i2c_config_speed(config);
  const uint64_t target = debug_i2c_config_target(config);
  const bool targetRequired = config.mode == I2CSTEPPER_V3_MODE_FILLING ||
      (config.mode == I2CSTEPPER_V3_MODE_MIXER && config.mixerRunSec > 0);
  return speed >= 1 && speed <= I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC &&
         target <= I2CSTEPPER_V3_TARGET_STEPS_MAX && (!targetRequired || target >= 1);
}

inline uint32_t debug_i2c_steps_done(const DebugI2CNano& nano, uint32_t now) {
  return uint32_t(uint64_t(nano.speed) * uint32_t(now - nano.phaseMs) / 1000U);
}

inline void debug_i2c_start(DebugI2CNano& nano, uint32_t speed, uint32_t target, uint32_t now) {
  nano.busy = true;
  nano.paused = false;
  nano.speed = speed;
  nano.target = target;
  nano.phaseMs = now;
  nano.status.stopReason = I2CSTEPPER_V3_STOP_NONE;
}

inline void debug_i2c_start_configured(DebugI2CNano& nano, uint32_t now) {
  debug_i2c_start(nano, debug_i2c_config_speed(nano.active),
                  uint32_t(debug_i2c_config_target(nano.active)), now);
}

// Продвигает «мотор» до текущего момента: конец дозы, пауза цикла мешалки и новый цикл.
inline void debug_i2c_advance(DebugI2CNano& nano, uint32_t now) {
  if (!nano.busy) return;
  if (nano.paused) {
    if (uint32_t(now - nano.phaseMs) >= nano.active.mixerPauseSec * 1000UL) {
      debug_i2c_start_configured(nano, now);
    }
    return;
  }
  if (nano.target == 0 || debug_i2c_steps_done(nano, now) < nano.target) return;
  if (nano.active.mode == I2CSTEPPER_V3_MODE_MIXER && nano.active.mixerRunSec > 0 &&
      nano.active.mixerPauseSec > 0) {
    nano.paused = true;
    nano.phaseMs = now;
  } else {
    nano.busy = false;
    nano.status.stopReason = I2CSTEPPER_V3_STOP_COMPLETE;
  }
}

inline void debug_i2c_result(DebugI2CNano& nano, uint32_t sequence, uint8_t error) {
  nano.status.commandSeq = sequence;
  nano.status.ackSeq = sequence;
  nano.status.commandResult = error == I2CSTEPPER_V3_ERR_NONE ? I2CSTEPPER_V3_RESULT_SUCCESS
                                                              : I2CSTEPPER_V3_RESULT_FAILED;
  nano.status.error = error;
}

inline uint8_t debug_i2c_execute(DebugI2CNano& nano, uint8_t command, uint32_t now) {
  switch (command) {
    case I2CSTEPPER_V3_CMD_HEARTBEAT:
      return I2CSTEPPER_V3_ERR_NONE;
    case I2CSTEPPER_V3_CMD_APPLY:
    case I2CSTEPPER_V3_CMD_SAVE:
      // Смена адреса у эмулятора не поддержана: плат всегда две, на адресах 1 и 2.
      if (nano.staging.address != nano.active.address) return I2CSTEPPER_V3_ERR_BAD_ADDRESS;
      if (!i2cstepper_v3_mode_supported(nano.staging.address, nano.staging.mode)) {
        return I2CSTEPPER_V3_ERR_UNSUPPORTED_MODE;
      }
      if (!debug_i2c_config_valid(nano.staging)) return I2CSTEPPER_V3_ERR_BAD_CONFIG;
      nano.active = nano.staging;
      nano.status.generation++;
      return I2CSTEPPER_V3_ERR_NONE;
    case I2CSTEPPER_V3_CMD_START_CONFIGURED:
      if (!debug_i2c_config_valid(nano.active)) return I2CSTEPPER_V3_ERR_BAD_CONFIG;
      debug_i2c_start_configured(nano, now);
      return I2CSTEPPER_V3_ERR_NONE;
    case I2CSTEPPER_V3_CMD_START_FINITE:
    case I2CSTEPPER_V3_CMD_START_CONTINUOUS: {
      const bool finite = command == I2CSTEPPER_V3_CMD_START_FINITE;
      if (!i2cstepper_v3_start_mode_supported(nano.active.mode, nano.motion.mode, command)) {
        return I2CSTEPPER_V3_ERR_UNSUPPORTED_MODE;
      }
      if (nano.motion.direction > 1 || nano.motion.speedStepsPerSec < 1 ||
          nano.motion.speedStepsPerSec > I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC ||
          (finite && (nano.motion.targetSteps < 1 ||
                      nano.motion.targetSteps > I2CSTEPPER_V3_TARGET_STEPS_MAX))) {
        return I2CSTEPPER_V3_ERR_BAD_CONFIG;
      }
      debug_i2c_start(nano, nano.motion.speedStepsPerSec, finite ? nano.motion.targetSteps : 0, now);
      return I2CSTEPPER_V3_ERR_NONE;
    }
    case I2CSTEPPER_V3_CMD_STOP:
      nano.busy = false;
      nano.paused = false;
      nano.calibration = false;
      nano.status.stopReason = I2CSTEPPER_V3_STOP_REMOTE;
      return I2CSTEPPER_V3_ERR_NONE;
    case I2CSTEPPER_V3_CMD_RELAY:
      if ((nano.staging.relayMask & 0xF0U) != 0) return I2CSTEPPER_V3_ERR_BAD_CONFIG;
      nano.active.relayMask = nano.staging.relayMask;
      nano.status.generation++;
      return I2CSTEPPER_V3_ERR_NONE;
    case I2CSTEPPER_V3_CMD_CALIBRATE_START: {
      if (i2cstepper_v3_address_is_mixer(nano.active.address)) return I2CSTEPPER_V3_ERR_UNSUPPORTED_MODE;
      const uint32_t speed = debug_i2c_rate_steps(nano.active.pumpMlHour, nano.active.stepsPerMl, 3600U);
      if (nano.busy || nano.calibration || speed < 1 ||
          speed > I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC) return I2CSTEPPER_V3_ERR_BAD_CONFIG;
      debug_i2c_start(nano, speed, 0, now);
      nano.calibration = true;
      return I2CSTEPPER_V3_ERR_NONE;
    }
    case I2CSTEPPER_V3_CMD_CALIBRATE_FINISH: {
      if (!nano.calibration) return I2CSTEPPER_V3_ERR_BAD_CONFIG;
      const uint32_t measured = debug_i2c_steps_done(nano, now) / 100UL;
      nano.busy = false;
      nano.calibration = false;
      if (measured == 0) return I2CSTEPPER_V3_ERR_EEPROM_WRITE;
      nano.active.stepsPerMl = measured;
      nano.staging = nano.active;
      nano.status.generation++;
      return I2CSTEPPER_V3_ERR_NONE;
    }
    default:
      return I2CSTEPPER_V3_ERR_BAD_COMMAND;
  }
}

// true - адрес обслужил эмулятор (result = исход обмена), false - идти на настоящую шину.
inline bool debug_i2c_emu_write(uint8_t address, uint8_t reg, const uint8_t* payload,
                                uint8_t size, uint32_t now, bool& result) {
  DebugI2CNano* nano = debug_i2c_nano(address);
  if (!nano) return false;
  result = true;
  debug_i2c_advance(*nano, now);
  if (reg == I2CSTEPPER_V3_REG_CONFIG_A && size == I2CSTEPPER_V3_CONFIG_A_SIZE) {
    i2cstepper_v3_decode_config_a(payload, &nano->staging);
  } else if (reg == I2CSTEPPER_V3_REG_CONFIG_B && size == I2CSTEPPER_V3_CONFIG_B_SIZE) {
    i2cstepper_v3_decode_config_b(payload, &nano->staging);
  } else if (reg == I2CSTEPPER_V3_REG_MOTION && size == I2CSTEPPER_V3_MOTION_SIZE) {
    i2cstepper_v3_decode_motion(payload, &nano->motion);
  } else if (reg == I2CSTEPPER_V3_REG_COMMAND && size == I2CSTEPPER_V3_COMMAND_SIZE) {
    I2CStepperV3CommandFrame frame{};
    i2cstepper_v3_decode_command(payload, &frame);
    const I2CStepperV3SequenceState state =
        i2cstepper_v3_sequence_state(nano->lastSeq, frame.commandSeq);
    if (state == I2CSTEPPER_V3_SEQUENCE_DUPLICATE) return true;  // итог уже лежит в статусе
    if (state != I2CSTEPPER_V3_SEQUENCE_NEW) {
      debug_i2c_result(*nano, frame.commandSeq, I2CSTEPPER_V3_ERR_BAD_SEQUENCE);
      return true;
    }
    nano->lastSeq = frame.commandSeq;
    debug_i2c_result(*nano, frame.commandSeq,
                     frame.address == address ? debug_i2c_execute(*nano, frame.command, now)
                                              : uint8_t(I2CSTEPPER_V3_ERR_BAD_ADDRESS));
  } else {
    result = false;
  }
  return true;
}

inline bool debug_i2c_emu_read(uint8_t address, uint8_t reg, uint8_t* data, uint8_t len,
                               uint32_t now, bool& result) {
  DebugI2CNano* nano = debug_i2c_nano(address);
  if (!nano) return false;
  result = true;
  debug_i2c_advance(*nano, now);
  const bool turning = nano->busy && !nano->paused;
  if (reg == I2CSTEPPER_V3_REG_IDENTITY && len == I2CSTEPPER_V3_IDENTITY_SIZE) {
    I2CStepperV3Identity identity{};
    identity.address = address;
    identity.capabilities = i2cstepper_v3_address_is_mixer(address)
        ? (I2CSTEPPER_V3_CAP_MIXER | I2CSTEPPER_V3_CAP_RELAY | I2CSTEPPER_V3_CAP_SENSOR)
        : (I2CSTEPPER_V3_CAP_PUMP | I2CSTEPPER_V3_CAP_FILLING | I2CSTEPPER_V3_CAP_RELAY |
           I2CSTEPPER_V3_CAP_SENSOR);
    i2cstepper_v3_encode_identity(data, &identity);
  } else if (reg == I2CSTEPPER_V3_REG_STATUS && len == I2CSTEPPER_V3_STATUS_SIZE) {
    I2CStepperV3StatusSnapshot& status = nano->status;
    status.mode = nano->active.mode;
    status.status = turning ? I2CSTEPPER_V3_STATUS_RUNNING : 0;
    if (nano->paused) status.status |= I2CSTEPPER_V3_STATUS_PAUSED;
    if (nano->calibration) status.status |= I2CSTEPPER_V3_STATUS_CALIBRATION;
    if (status.error != I2CSTEPPER_V3_ERR_NONE) status.status |= I2CSTEPPER_V3_STATUS_ERROR;
    status.currentSpeedStepsPerSec = turning ? nano->speed : 0;
    status.remainingSteps = turning && nano->target
        ? nano->target - debug_i2c_steps_done(*nano, now) : 0;
    i2cstepper_v3_encode_status(data, &status);
  } else if (reg == I2CSTEPPER_V3_REG_CONFIG_A && len == I2CSTEPPER_V3_CONFIG_A_SIZE) {
    i2cstepper_v3_encode_config_a(data, &nano->active);
  } else if (reg == I2CSTEPPER_V3_REG_CONFIG_B && len == I2CSTEPPER_V3_CONFIG_B_SIZE) {
    i2cstepper_v3_encode_config_b(data, &nano->active);
  } else if (reg == I2CSTEPPER_V3_REG_MOTION && len == I2CSTEPPER_V3_MOTION_SIZE) {
    i2cstepper_v3_encode_motion(data, &nano->motion);
  } else {
    result = false;
  }
  return true;
}

#endif  // __SAMOVAR_DEBUG
