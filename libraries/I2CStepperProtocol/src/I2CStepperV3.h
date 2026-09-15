#ifndef __I2CSTEPPER_V3_H
#define __I2CSTEPPER_V3_H

#include <stdint.h>

#define I2CSTEPPER_V3_MAGIC 0x53U
#define I2CSTEPPER_V3_VERSION 3U

#define I2CSTEPPER_V3_ADDRESS_MIN 1U
#define I2CSTEPPER_V3_ADDRESS_MAX 10U
#define I2CSTEPPER_V3_TARGET_STEPS_MAX 2147483647UL
#define I2CSTEPPER_V3_MAX_SPEED_STEPS_PER_SEC 18000UL

#define I2CSTEPPER_V2_EEPROM_MARKER 0x53U
#define I2CSTEPPER_V2_EEPROM_VERSION 2U
#define I2CSTEPPER_V2_ROLE_MIXER 1U
#define I2CSTEPPER_V2_ROLE_PUMP 2U

// На Arduino Nano буфер Wire — 32 байта, включая адрес первого регистра.
#define I2CSTEPPER_V3_WIRE_BUFFER_SIZE 32U
#define I2CSTEPPER_V3_WRITE_PAYLOAD_MAX 31U

enum I2CStepperV3Register : uint8_t {
  I2CSTEPPER_V3_REG_IDENTITY = 0x00,
  I2CSTEPPER_V3_REG_STATUS = 0x10,
  I2CSTEPPER_V3_REG_CONFIG_A = 0x30,
  I2CSTEPPER_V3_REG_CONFIG_B = 0x50,
  I2CSTEPPER_V3_REG_MOTION = 0x70,
  I2CSTEPPER_V3_REG_COMMAND = 0x80,
};

enum I2CStepperV3Mode : uint8_t {
  I2CSTEPPER_V3_MODE_MIXER = 1,
  I2CSTEPPER_V3_MODE_PUMP = 2,
  I2CSTEPPER_V3_MODE_FILLING = 3,
};

enum I2CStepperV3Command : uint8_t {
  I2CSTEPPER_V3_CMD_NONE = 0,
  I2CSTEPPER_V3_CMD_APPLY = 1,
  I2CSTEPPER_V3_CMD_SAVE = 2,
  I2CSTEPPER_V3_CMD_START_FINITE = 3,
  I2CSTEPPER_V3_CMD_START_CONTINUOUS = 4,
  I2CSTEPPER_V3_CMD_STOP = 5,
  I2CSTEPPER_V3_CMD_RELAY = 6,
  I2CSTEPPER_V3_CMD_CALIBRATE_START = 7,
  I2CSTEPPER_V3_CMD_CALIBRATE_FINISH = 8,
  I2CSTEPPER_V3_CMD_HEARTBEAT = 9,
  I2CSTEPPER_V3_CMD_START_CONFIGURED = 10,
};

enum I2CStepperV3Error : uint8_t {
  I2CSTEPPER_V3_ERR_NONE = 0,
  I2CSTEPPER_V3_ERR_BAD_ADDRESS = 1,
  I2CSTEPPER_V3_ERR_UNSUPPORTED_MODE = 2,
  I2CSTEPPER_V3_ERR_BAD_CONFIG = 3,
  I2CSTEPPER_V3_ERR_BAD_COMMAND = 4,
  I2CSTEPPER_V3_ERR_HEARTBEAT_TIMEOUT = 5,
  I2CSTEPPER_V3_ERR_EEPROM_INVALID = 6,
  I2CSTEPPER_V3_ERR_EEPROM_WRITE = 7,
  I2CSTEPPER_V3_ERR_BAD_SEQUENCE = 8,
  I2CSTEPPER_V3_ERR_REBOOT_REQUIRED = 9,
};

enum I2CStepperV3CommandResult : uint8_t {
  I2CSTEPPER_V3_RESULT_NONE = 0,
  I2CSTEPPER_V3_RESULT_PENDING = 1,
  I2CSTEPPER_V3_RESULT_SUCCESS = 2,
  I2CSTEPPER_V3_RESULT_FAILED = 3,
};

enum I2CStepperV3SequenceState : uint8_t {
  I2CSTEPPER_V3_SEQUENCE_NEW = 0,
  I2CSTEPPER_V3_SEQUENCE_DUPLICATE = 1,
  I2CSTEPPER_V3_SEQUENCE_STALE = 2,
  I2CSTEPPER_V3_SEQUENCE_INVALID = 3,
};

enum I2CStepperV3StopReason : uint8_t {
  I2CSTEPPER_V3_STOP_NONE = 0,
  I2CSTEPPER_V3_STOP_COMPLETE = 1,
  I2CSTEPPER_V3_STOP_REMOTE = 2,
  I2CSTEPPER_V3_STOP_LOCAL = 3,
  I2CSTEPPER_V3_STOP_SENSOR = 4,
  I2CSTEPPER_V3_STOP_HEARTBEAT = 5,
};

enum I2CStepperV3Status : uint8_t {
  I2CSTEPPER_V3_STATUS_RUNNING = 0x01,
  I2CSTEPPER_V3_STATUS_PAUSED = 0x02,
  I2CSTEPPER_V3_STATUS_SENSOR = 0x04,
  I2CSTEPPER_V3_STATUS_CALIBRATION = 0x08,
  I2CSTEPPER_V3_STATUS_ERROR = 0x80,
};

enum I2CStepperV3Capability : uint8_t {
  I2CSTEPPER_V3_CAP_MIXER = 0x01,
  I2CSTEPPER_V3_CAP_PUMP = 0x02,
  I2CSTEPPER_V3_CAP_FILLING = 0x04,
  I2CSTEPPER_V3_CAP_RELAY = 0x08,
  I2CSTEPPER_V3_CAP_SENSOR = 0x10,
};

enum I2CStepperV3FrameSize : uint8_t {
  I2CSTEPPER_V3_IDENTITY_SIZE = 8,
  I2CSTEPPER_V3_STATUS_SIZE = 32,
  I2CSTEPPER_V3_CONFIG_A_SIZE = 20,
  I2CSTEPPER_V3_CONFIG_B_SIZE = 17,
  I2CSTEPPER_V3_MOTION_SIZE = 10,
  I2CSTEPPER_V3_COMMAND_SIZE = 6,
};

enum I2CStepperV3IdentityOffset : uint8_t {
  I2CSTEPPER_V3_IDENTITY_MAGIC_OFFSET = 0,
  I2CSTEPPER_V3_IDENTITY_VERSION_OFFSET = 1,
  I2CSTEPPER_V3_IDENTITY_ADDRESS_OFFSET = 2,
  I2CSTEPPER_V3_IDENTITY_CAPABILITIES_OFFSET = 3,
};

enum I2CStepperV3StatusOffset : uint8_t {
  I2CSTEPPER_V3_STATUS_MAGIC_OFFSET = 0,
  I2CSTEPPER_V3_STATUS_VERSION_OFFSET = 1,
  I2CSTEPPER_V3_STATUS_ADDRESS_OFFSET = 2,
  I2CSTEPPER_V3_STATUS_MODE_OFFSET = 3,
  I2CSTEPPER_V3_STATUS_FLAGS_OFFSET = 4,
  I2CSTEPPER_V3_STATUS_RESULT_OFFSET = 5,
  I2CSTEPPER_V3_STATUS_ERROR_OFFSET = 6,
  I2CSTEPPER_V3_STATUS_STOP_REASON_OFFSET = 7,
  I2CSTEPPER_V3_STATUS_GENERATION_OFFSET = 8,
  I2CSTEPPER_V3_STATUS_COMMAND_SEQ_OFFSET = 12,
  I2CSTEPPER_V3_STATUS_ACK_SEQ_OFFSET = 16,
  I2CSTEPPER_V3_STATUS_STOP_EVENT_SEQ_OFFSET = 20,
  I2CSTEPPER_V3_STATUS_CURRENT_SPEED_OFFSET = 24,
  I2CSTEPPER_V3_STATUS_REMAINING_STEPS_OFFSET = 28,
};

enum I2CStepperV3ConfigAOffset : uint8_t {
  I2CSTEPPER_V3_CONFIG_A_MODE_OFFSET = 0,
  I2CSTEPPER_V3_CONFIG_A_OPTION_FLAGS_OFFSET = 1,
  I2CSTEPPER_V3_CONFIG_A_SENSOR_FLAGS_OFFSET = 2,
  I2CSTEPPER_V3_CONFIG_A_RELAY_MASK_OFFSET = 3,
  I2CSTEPPER_V3_CONFIG_A_MIXER_RPM_OFFSET = 4,
  I2CSTEPPER_V3_CONFIG_A_MIXER_RUN_OFFSET = 8,
  I2CSTEPPER_V3_CONFIG_A_MIXER_PAUSE_OFFSET = 12,
  I2CSTEPPER_V3_CONFIG_A_PUMP_MLH_OFFSET = 16,
};

enum I2CStepperV3ConfigBOffset : uint8_t {
  I2CSTEPPER_V3_CONFIG_B_ADDRESS_OFFSET = 0,
  I2CSTEPPER_V3_CONFIG_B_PUMP_PAUSE_OFFSET = 1,
  I2CSTEPPER_V3_CONFIG_B_FILLING_ML_OFFSET = 5,
  I2CSTEPPER_V3_CONFIG_B_FILLING_MLH_OFFSET = 9,
  I2CSTEPPER_V3_CONFIG_B_STEPS_PER_ML_OFFSET = 13,
};

enum I2CStepperV3MotionOffset : uint8_t {
  I2CSTEPPER_V3_MOTION_MODE_OFFSET = 0,
  I2CSTEPPER_V3_MOTION_DIRECTION_OFFSET = 1,
  I2CSTEPPER_V3_MOTION_SPEED_OFFSET = 2,
  I2CSTEPPER_V3_MOTION_TARGET_OFFSET = 6,
};

enum I2CStepperV3CommandOffset : uint8_t {
  I2CSTEPPER_V3_COMMAND_ADDRESS_OFFSET = 0,
  I2CSTEPPER_V3_COMMAND_CODE_OFFSET = 1,
  I2CSTEPPER_V3_COMMAND_SEQ_OFFSET = 2,
};

struct __attribute__((packed)) I2CStepperV2Config {
  uint8_t marker;
  uint8_t version;
  uint8_t role;
  uint8_t mode;
  uint16_t mixerRpm;
  uint16_t mixerRunSec;
  uint16_t mixerPauseSec;
  uint16_t pumpMlHour;
  uint16_t pumpPauseSec;
  uint16_t fillingMl;
  uint16_t fillingMlHour;
  uint16_t stepperStepMl;
  uint8_t optionFlags;
  uint8_t sensorFlags;
  uint8_t relayMask;
};

static_assert(sizeof(I2CStepperV2Config) == 23, "I2CStepper v2 EEPROM layout changed");

// Semantic objects only. Never serialize them with memcpy: AVR, ESP and host
// may choose different layout and alignment. Use the explicit codec below.
struct I2CStepperV3Identity {
  uint8_t address;
  uint8_t capabilities;
};

struct I2CStepperV3Config {
  uint8_t address;
  uint8_t mode;
  uint8_t optionFlags;
  uint8_t sensorFlags;
  uint8_t relayMask;
  uint32_t mixerRpm;
  uint32_t mixerRunSec;
  uint32_t mixerPauseSec;
  uint32_t pumpMlHour;
  uint32_t pumpPauseSec;
  uint32_t fillingMl;
  uint32_t fillingMlHour;
  uint32_t stepsPerMl;
};

struct I2CStepperV3Motion {
  uint8_t mode;
  uint8_t direction;
  uint32_t speedStepsPerSec;
  uint32_t targetSteps;
};

struct I2CStepperV3CommandFrame {
  uint8_t address;
  uint8_t command;
  uint32_t commandSeq;
};

struct I2CStepperV3StatusSnapshot {
  uint8_t address;
  uint8_t mode;
  uint8_t status;
  uint8_t commandResult;
  uint8_t error;
  uint8_t stopReason;
  uint32_t generation;
  uint32_t commandSeq;
  uint32_t ackSeq;
  uint32_t stopEventSeq;
  uint32_t currentSpeedStepsPerSec;
  uint32_t remainingSteps;
};

static inline bool i2cstepper_v3_address_valid(uint8_t address) {
  return address >= I2CSTEPPER_V3_ADDRESS_MIN && address <= I2CSTEPPER_V3_ADDRESS_MAX;
}

static inline bool i2cstepper_v3_address_is_mixer(uint8_t address) {
  return (address & 1U) != 0;
}

static inline bool i2cstepper_v3_mode_supported(uint8_t address, uint8_t mode) {
  if (!i2cstepper_v3_address_valid(address)) return false;
  if (i2cstepper_v3_address_is_mixer(address)) {
    return mode == I2CSTEPPER_V3_MODE_MIXER;
  }
  return mode == I2CSTEPPER_V3_MODE_PUMP || mode == I2CSTEPPER_V3_MODE_FILLING;
}

static inline bool i2cstepper_v3_mode_after_address_change(uint8_t oldAddress,
                                                            uint8_t newAddress,
                                                            uint8_t oldMode,
                                                            uint8_t* newMode) {
  if (!newMode || !i2cstepper_v3_address_valid(oldAddress) ||
      !i2cstepper_v3_address_valid(newAddress) ||
      !i2cstepper_v3_mode_supported(oldAddress, oldMode)) {
    return false;
  }
  if (i2cstepper_v3_address_is_mixer(oldAddress) == i2cstepper_v3_address_is_mixer(newAddress)) {
    *newMode = oldMode;
    return true;
  }
  *newMode = i2cstepper_v3_address_is_mixer(newAddress) ? I2CSTEPPER_V3_MODE_MIXER : I2CSTEPPER_V3_MODE_PUMP;
  return true;
}

static inline bool i2cstepper_v3_read_size_valid(uint8_t readSize) {
  return readSize > 0 && readSize <= I2CSTEPPER_V3_WIRE_BUFFER_SIZE;
}

static inline bool i2cstepper_v3_write_payload_size_valid(uint8_t payloadSize) {
  return payloadSize <= I2CSTEPPER_V3_WRITE_PAYLOAD_MAX;
}

static inline bool i2cstepper_v3_sequence_after(uint32_t sequence, uint32_t previous) {
  return sequence != 0 && previous != 0 &&
         (uint32_t)(sequence - previous) < 0x80000000UL && sequence != previous;
}

static inline uint32_t i2cstepper_v3_sequence_next(uint32_t sequence) {
  return sequence == 0xFFFFFFFFUL ? 1UL : sequence + 1UL;
}

static inline I2CStepperV3SequenceState i2cstepper_v3_sequence_state(uint32_t previous,
                                                                        uint32_t sequence) {
  if (sequence == 0) return I2CSTEPPER_V3_SEQUENCE_INVALID;
  if (previous == 0 || i2cstepper_v3_sequence_after(sequence, previous)) {
    return I2CSTEPPER_V3_SEQUENCE_NEW;
  }
  if (sequence == previous) return I2CSTEPPER_V3_SEQUENCE_DUPLICATE;
  return I2CSTEPPER_V3_SEQUENCE_STALE;
}

static inline bool i2cstepper_v3_start_mode_supported(uint8_t activeMode,
                                                        uint8_t motionMode,
                                                        uint8_t command) {
  if (activeMode != motionMode) return false;
  if (command == I2CSTEPPER_V3_CMD_START_FINITE) {
    return activeMode == I2CSTEPPER_V3_MODE_MIXER || activeMode == I2CSTEPPER_V3_MODE_FILLING;
  }
  if (command == I2CSTEPPER_V3_CMD_START_CONTINUOUS) {
    return activeMode == I2CSTEPPER_V3_MODE_MIXER || activeMode == I2CSTEPPER_V3_MODE_PUMP;
  }
  return false;
}

static inline uint16_t i2cstepper_v3_read_u16_be(const uint8_t* data) {
  return ((uint16_t)data[0] << 8) | data[1];
}

static inline void i2cstepper_v3_write_u16_be(uint8_t* data, uint16_t value) {
  data[0] = (uint8_t)(value >> 8);
  data[1] = (uint8_t)value;
}

static inline uint16_t i2cstepper_v3_read_u16_le(const uint8_t* data) {
  return (uint16_t)data[0] | ((uint16_t)data[1] << 8);
}

static inline uint32_t i2cstepper_v3_read_u32_be(const uint8_t* data) {
  return ((uint32_t)data[0] << 24) |
         ((uint32_t)data[1] << 16) |
         ((uint32_t)data[2] << 8) |
         (uint32_t)data[3];
}

static inline void i2cstepper_v3_write_u32_be(uint8_t* data, uint32_t value) {
  data[0] = (uint8_t)(value >> 24);
  data[1] = (uint8_t)(value >> 16);
  data[2] = (uint8_t)(value >> 8);
  data[3] = (uint8_t)value;
}

static inline void i2cstepper_v3_encode_identity(uint8_t* data,
                                                   const I2CStepperV3Identity* identity) {
  data[I2CSTEPPER_V3_IDENTITY_MAGIC_OFFSET] = I2CSTEPPER_V3_MAGIC;
  data[I2CSTEPPER_V3_IDENTITY_VERSION_OFFSET] = I2CSTEPPER_V3_VERSION;
  data[I2CSTEPPER_V3_IDENTITY_ADDRESS_OFFSET] = identity->address;
  data[I2CSTEPPER_V3_IDENTITY_CAPABILITIES_OFFSET] = identity->capabilities;
  data[4] = 0;
  data[5] = 0;
  data[6] = 0;
  data[7] = 0;
}

static inline bool i2cstepper_v3_decode_identity(const uint8_t* data,
                                                  I2CStepperV3Identity* identity) {
  if (data[I2CSTEPPER_V3_IDENTITY_MAGIC_OFFSET] != I2CSTEPPER_V3_MAGIC ||
      data[I2CSTEPPER_V3_IDENTITY_VERSION_OFFSET] != I2CSTEPPER_V3_VERSION) {
    return false;
  }
  identity->address = data[I2CSTEPPER_V3_IDENTITY_ADDRESS_OFFSET];
  identity->capabilities = data[I2CSTEPPER_V3_IDENTITY_CAPABILITIES_OFFSET];
  return true;
}

static inline void i2cstepper_v3_encode_status(uint8_t* data,
                                                 const I2CStepperV3StatusSnapshot* status) {
  data[I2CSTEPPER_V3_STATUS_MAGIC_OFFSET] = I2CSTEPPER_V3_MAGIC;
  data[I2CSTEPPER_V3_STATUS_VERSION_OFFSET] = I2CSTEPPER_V3_VERSION;
  data[I2CSTEPPER_V3_STATUS_ADDRESS_OFFSET] = status->address;
  data[I2CSTEPPER_V3_STATUS_MODE_OFFSET] = status->mode;
  data[I2CSTEPPER_V3_STATUS_FLAGS_OFFSET] = status->status;
  data[I2CSTEPPER_V3_STATUS_RESULT_OFFSET] = status->commandResult;
  data[I2CSTEPPER_V3_STATUS_ERROR_OFFSET] = status->error;
  data[I2CSTEPPER_V3_STATUS_STOP_REASON_OFFSET] = status->stopReason;
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_STATUS_GENERATION_OFFSET], status->generation);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_STATUS_COMMAND_SEQ_OFFSET], status->commandSeq);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_STATUS_ACK_SEQ_OFFSET], status->ackSeq);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_STATUS_STOP_EVENT_SEQ_OFFSET], status->stopEventSeq);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_STATUS_CURRENT_SPEED_OFFSET], status->currentSpeedStepsPerSec);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_STATUS_REMAINING_STEPS_OFFSET], status->remainingSteps);
}

static inline bool i2cstepper_v3_decode_status(const uint8_t* data,
                                                I2CStepperV3StatusSnapshot* status) {
  if (data[I2CSTEPPER_V3_STATUS_MAGIC_OFFSET] != I2CSTEPPER_V3_MAGIC ||
      data[I2CSTEPPER_V3_STATUS_VERSION_OFFSET] != I2CSTEPPER_V3_VERSION) {
    return false;
  }
  status->address = data[I2CSTEPPER_V3_STATUS_ADDRESS_OFFSET];
  status->mode = data[I2CSTEPPER_V3_STATUS_MODE_OFFSET];
  status->status = data[I2CSTEPPER_V3_STATUS_FLAGS_OFFSET];
  status->commandResult = data[I2CSTEPPER_V3_STATUS_RESULT_OFFSET];
  status->error = data[I2CSTEPPER_V3_STATUS_ERROR_OFFSET];
  status->stopReason = data[I2CSTEPPER_V3_STATUS_STOP_REASON_OFFSET];
  status->generation = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_STATUS_GENERATION_OFFSET]);
  status->commandSeq = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_STATUS_COMMAND_SEQ_OFFSET]);
  status->ackSeq = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_STATUS_ACK_SEQ_OFFSET]);
  status->stopEventSeq = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_STATUS_STOP_EVENT_SEQ_OFFSET]);
  status->currentSpeedStepsPerSec = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_STATUS_CURRENT_SPEED_OFFSET]);
  status->remainingSteps = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_STATUS_REMAINING_STEPS_OFFSET]);
  return true;
}

static inline void i2cstepper_v3_encode_config_a(uint8_t* data, const I2CStepperV3Config* config) {
  data[I2CSTEPPER_V3_CONFIG_A_MODE_OFFSET] = config->mode;
  data[I2CSTEPPER_V3_CONFIG_A_OPTION_FLAGS_OFFSET] = config->optionFlags;
  data[I2CSTEPPER_V3_CONFIG_A_SENSOR_FLAGS_OFFSET] = config->sensorFlags;
  data[I2CSTEPPER_V3_CONFIG_A_RELAY_MASK_OFFSET] = config->relayMask;
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_CONFIG_A_MIXER_RPM_OFFSET], config->mixerRpm);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_CONFIG_A_MIXER_RUN_OFFSET], config->mixerRunSec);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_CONFIG_A_MIXER_PAUSE_OFFSET], config->mixerPauseSec);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_CONFIG_A_PUMP_MLH_OFFSET], config->pumpMlHour);
}

static inline void i2cstepper_v3_decode_config_a(const uint8_t* data, I2CStepperV3Config* config) {
  config->mode = data[I2CSTEPPER_V3_CONFIG_A_MODE_OFFSET];
  config->optionFlags = data[I2CSTEPPER_V3_CONFIG_A_OPTION_FLAGS_OFFSET];
  config->sensorFlags = data[I2CSTEPPER_V3_CONFIG_A_SENSOR_FLAGS_OFFSET];
  config->relayMask = data[I2CSTEPPER_V3_CONFIG_A_RELAY_MASK_OFFSET];
  config->mixerRpm = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_CONFIG_A_MIXER_RPM_OFFSET]);
  config->mixerRunSec = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_CONFIG_A_MIXER_RUN_OFFSET]);
  config->mixerPauseSec = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_CONFIG_A_MIXER_PAUSE_OFFSET]);
  config->pumpMlHour = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_CONFIG_A_PUMP_MLH_OFFSET]);
}

static inline void i2cstepper_v3_encode_config_b(uint8_t* data, const I2CStepperV3Config* config) {
  data[I2CSTEPPER_V3_CONFIG_B_ADDRESS_OFFSET] = config->address;
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_CONFIG_B_PUMP_PAUSE_OFFSET], config->pumpPauseSec);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_CONFIG_B_FILLING_ML_OFFSET], config->fillingMl);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_CONFIG_B_FILLING_MLH_OFFSET], config->fillingMlHour);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_CONFIG_B_STEPS_PER_ML_OFFSET], config->stepsPerMl);
}

static inline void i2cstepper_v3_decode_config_b(const uint8_t* data, I2CStepperV3Config* config) {
  config->address = data[I2CSTEPPER_V3_CONFIG_B_ADDRESS_OFFSET];
  config->pumpPauseSec = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_CONFIG_B_PUMP_PAUSE_OFFSET]);
  config->fillingMl = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_CONFIG_B_FILLING_ML_OFFSET]);
  config->fillingMlHour = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_CONFIG_B_FILLING_MLH_OFFSET]);
  config->stepsPerMl = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_CONFIG_B_STEPS_PER_ML_OFFSET]);
}

static inline void i2cstepper_v3_encode_motion(uint8_t* data, const I2CStepperV3Motion* motion) {
  data[I2CSTEPPER_V3_MOTION_MODE_OFFSET] = motion->mode;
  data[I2CSTEPPER_V3_MOTION_DIRECTION_OFFSET] = motion->direction;
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_MOTION_SPEED_OFFSET], motion->speedStepsPerSec);
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_MOTION_TARGET_OFFSET], motion->targetSteps);
}

static inline void i2cstepper_v3_decode_motion(const uint8_t* data, I2CStepperV3Motion* motion) {
  motion->mode = data[I2CSTEPPER_V3_MOTION_MODE_OFFSET];
  motion->direction = data[I2CSTEPPER_V3_MOTION_DIRECTION_OFFSET];
  motion->speedStepsPerSec = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_MOTION_SPEED_OFFSET]);
  motion->targetSteps = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_MOTION_TARGET_OFFSET]);
}

static inline void i2cstepper_v3_encode_command(uint8_t* data, const I2CStepperV3CommandFrame* command) {
  data[I2CSTEPPER_V3_COMMAND_ADDRESS_OFFSET] = command->address;
  data[I2CSTEPPER_V3_COMMAND_CODE_OFFSET] = command->command;
  i2cstepper_v3_write_u32_be(&data[I2CSTEPPER_V3_COMMAND_SEQ_OFFSET], command->commandSeq);
}

static inline void i2cstepper_v3_decode_command(const uint8_t* data, I2CStepperV3CommandFrame* command) {
  command->address = data[I2CSTEPPER_V3_COMMAND_ADDRESS_OFFSET];
  command->command = data[I2CSTEPPER_V3_COMMAND_CODE_OFFSET];
  command->commandSeq = i2cstepper_v3_read_u32_be(&data[I2CSTEPPER_V3_COMMAND_SEQ_OFFSET]);
}

static inline bool i2cstepper_v3_decode_v2_config(const uint8_t* data, I2CStepperV2Config* config) {
  if (!data || !config) return false;
  config->marker = data[0];
  config->version = data[1];
  config->role = data[2];
  config->mode = data[3];
  config->mixerRpm = i2cstepper_v3_read_u16_le(&data[4]);
  config->mixerRunSec = i2cstepper_v3_read_u16_le(&data[6]);
  config->mixerPauseSec = i2cstepper_v3_read_u16_le(&data[8]);
  config->pumpMlHour = i2cstepper_v3_read_u16_le(&data[10]);
  config->pumpPauseSec = i2cstepper_v3_read_u16_le(&data[12]);
  config->fillingMl = i2cstepper_v3_read_u16_le(&data[14]);
  config->fillingMlHour = i2cstepper_v3_read_u16_le(&data[16]);
  config->stepperStepMl = i2cstepper_v3_read_u16_le(&data[18]);
  config->optionFlags = data[20];
  config->sensorFlags = data[21];
  config->relayMask = data[22];
  return true;
}

static inline bool i2cstepper_v3_migrate_v2_config(const I2CStepperV2Config* source,
                                                     I2CStepperV3Config* destination) {
  if (!source || !destination || source->marker != I2CSTEPPER_V2_EEPROM_MARKER ||
      source->version != I2CSTEPPER_V2_EEPROM_VERSION || source->stepperStepMl == 0) {
    return false;
  }

  if (source->role == I2CSTEPPER_V2_ROLE_MIXER) {
    destination->address = 1;
  } else if (source->role == I2CSTEPPER_V2_ROLE_PUMP) {
    destination->address = 2;
  } else {
    return false;
  }

  if (!i2cstepper_v3_mode_supported(destination->address, source->mode)) return false;
  destination->mode = source->mode;
  destination->optionFlags = source->optionFlags;
  destination->sensorFlags = source->sensorFlags;
  destination->relayMask = source->relayMask;
  destination->mixerRpm = source->mixerRpm;
  destination->mixerRunSec = source->mixerRunSec;
  destination->mixerPauseSec = source->mixerPauseSec;
  destination->pumpMlHour = source->pumpMlHour;
  destination->pumpPauseSec = source->pumpPauseSec;
  destination->fillingMl = source->fillingMl;
  destination->fillingMlHour = source->fillingMlHour;
  destination->stepsPerMl = source->stepperStepMl;
  return true;
}

#endif // __I2CSTEPPER_V3_H
