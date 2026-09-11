#pragma once

#include <Arduino.h>
#include <string.h>

#include "string_utils.h"

inline bool firmware_config_write_bytes(Print& out, const char* text) {
  const size_t length = strlen(text);
  return out.write(reinterpret_cast<const uint8_t*>(text), length) == length;
}

inline bool firmware_config_write_char(Print& out, char value) {
  return out.write(static_cast<uint8_t>(value)) == 1;
}

inline bool firmware_config_write_string(Print& out, const char* value) {
  return firmware_config_write_char(out, '"') &&
         json_write_escaped(out, value, strlen(value)) &&
         firmware_config_write_char(out, '"');
}

inline bool firmware_config_write_null(Print& out) {
  return firmware_config_write_bytes(out, "null");
}

inline bool firmware_config_write_bool(Print& out, bool value) {
  return firmware_config_write_bytes(out, value ? "true" : "false");
}

inline bool firmware_config_write_long(Print& out, long value) {
  return out.print(value) > 0;
}

inline bool firmware_config_write_float(Print& out, double value) {
  return out.print(value, 6) > 0;
}

inline bool firmware_config_write_key(Print& out, bool& first, const char* key) {
  if (!first && !firmware_config_write_char(out, ',')) return false;
  first = false;
  return firmware_config_write_string(out, key) && firmware_config_write_char(out, ':');
}

inline bool firmware_config_write_string_field(
    Print& out, bool& first, const char* key, const char* value) {
  return firmware_config_write_key(out, first, key) && firmware_config_write_string(out, value);
}

inline bool firmware_config_write_null_field(Print& out, bool& first, const char* key) {
  return firmware_config_write_key(out, first, key) && firmware_config_write_null(out);
}

inline bool firmware_config_write_bool_field(Print& out, bool& first, const char* key, bool value) {
  return firmware_config_write_key(out, first, key) && firmware_config_write_bool(out, value);
}

inline bool firmware_config_write_long_field(Print& out, bool& first, const char* key, long value) {
  return firmware_config_write_key(out, first, key) && firmware_config_write_long(out, value);
}

inline bool firmware_config_write_float_field(Print& out, bool& first, const char* key, double value) {
  return firmware_config_write_key(out, first, key) && firmware_config_write_float(out, value);
}

inline bool firmware_config_write_firmware_version_field(Print& out, bool& first) {
  if (!firmware_config_write_key(out, first, "firmwareVersion") ||
      !firmware_config_write_char(out, '"')) return false;
  if (out.print(SAMOVAR_VERSION) == 0) return false;
  return firmware_config_write_char(out, '"');
}

#define FIRMWARE_CONFIG_STRINGIFY_VALUE(...) #__VA_ARGS__
#define FIRMWARE_CONFIG_STRINGIFY(...) FIRMWARE_CONFIG_STRINGIFY_VALUE(__VA_ARGS__)

inline bool write_firmware_config_json(Print& out) {
  bool first = true;
  if (!firmware_config_write_char(out, '{') ||
      !firmware_config_write_string_field(
          out, first, "type", "samovar_firmware_config") ||
      !firmware_config_write_long_field(out, first, "schema", 1) ||
      !firmware_config_write_firmware_version_field(out, first) ||
      !firmware_config_write_key(out, first, "settings") ||
      !firmware_config_write_char(out, '{')) return false;

  first = true;
#if BOARD == DEVKIT
  if (!firmware_config_write_string_field(out, first, "board", "DEVKIT")) return false;
#elif BOARD == LILYGO
  if (!firmware_config_write_string_field(out, first, "board", "LILYGO")) return false;
#elif BOARD == ESP32S3
  if (!firmware_config_write_string_field(out, first, "board", "ESP32S3")) return false;
#else
#error Unsupported BOARD for firmware configuration report
#endif

  if (!firmware_config_write_string_field(out, first, "SAMOVAR_HOST", SAMOVAR_HOST) ||
      !firmware_config_write_long_field(out, first, "ALARM_WATER_TEMP", ALARM_WATER_TEMP) ||
      !firmware_config_write_long_field(out, first, "MAX_WATER_TEMP", MAX_WATER_TEMP) ||
      !firmware_config_write_float_field(out, first, "MAX_STEAM_TEMP", MAX_STEAM_TEMP) ||
      !firmware_config_write_long_field(out, first, "MAX_ACP_TEMP", MAX_ACP_TEMP) ||
      !firmware_config_write_long_field(out, first, "CHANGE_POWER_MODE_STEAM_TEMP", CHANGE_POWER_MODE_STEAM_TEMP) ||
      !firmware_config_write_long_field(out, first, "OPEN_VALVE_TANK_TEMP", OPEN_VALVE_TANK_TEMP) ||
      !firmware_config_write_long_field(out, first, "DELTA_T_CLOSE_VALVE", DELTA_T_CLOSE_VALVE) ||
      !firmware_config_write_long_field(out, first, "PWM_LOW_VALUE", PWM_LOW_VALUE) ||
      !firmware_config_write_long_field(out, first, "PWM_START_VALUE", PWM_START_VALUE) ||
      !firmware_config_write_long_field(out, first, "HEAT_DELTA", HEAT_DELTA) ||
      !firmware_config_write_long_field(out, first, "ACCELERATION_HEATER_DELTA", ACCELERATION_HEATER_DELTA) ||
      !firmware_config_write_float_field(out, first, "BOILING_TEMP", BOILING_TEMP) ||
      !firmware_config_write_float_field(out, first, "DEFAULT_DIST_TEMP", DEFAULT_DIST_TEMP) ||
      !firmware_config_write_long_field(out, first, "WF_CALIBRATION", WF_CALIBRATION) ||
      !firmware_config_write_long_field(out, first, "WATER_FLOW_MIN_PULSES", WATER_FLOW_MIN_PULSES) ||
      !firmware_config_write_long_field(out, first, "NBK_MULT_PAUSE_OVERFLOW", NBK_MULT_PAUSE_OVERFLOW) ||
      !firmware_config_write_long_field(out, first, "NBK_PUMP_LIMIT", NBK_PUMP_LIMIT) ||
      !firmware_config_write_float_field(out, first, "NBK_WORK_PRESSURE_RATIO", NBK_WORK_PRESSURE_RATIO) ||
      !firmware_config_write_long_field(out, first, "NBK_PRESSURE_MARGIN", NBK_PRESSURE_MARGIN) ||
      !firmware_config_write_float_field(out, first, "NBK_END_STEAM_RISE", NBK_END_STEAM_RISE) ||
      !firmware_config_write_long_field(out, first, "SAMOVAR_USE_POWER_START_TIME", SAMOVAR_USE_POWER_START_TIME) ||
      !firmware_config_write_long_field(out, first, "LCD_RESET_PERIOD_MS", LCD_RESET_PERIOD_MS) ||
      !firmware_config_write_float_field(out, first, "PAUSE_RESUME_HYSTERESIS_DELTA", PAUSE_RESUME_HYSTERESIS_DELTA) ||
      !firmware_config_write_long_field(out, first, "PROGRAM_ROW_STOP_PAUSE_LIMIT", PROGRAM_ROW_STOP_PAUSE_LIMIT) ||
      !firmware_config_write_long_field(out, first, "PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT", PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT) ||
      !firmware_config_write_long_field(out, first, "PROGRAM_DONE_AUTO_POWEROFF_MIN", PROGRAM_DONE_AUTO_POWEROFF_MIN) ||
      !firmware_config_write_float_field(out, first, "BODY_TEMP_AUTOSET_MAX_RISE", BODY_TEMP_AUTOSET_MAX_RISE) ||
      !firmware_config_write_long_field(out, first, "BK_STEAM_SETPOINT_MIN", BK_STEAM_SETPOINT_MIN) ||
      !firmware_config_write_long_field(out, first, "BK_STEAM_SETPOINT_MAX", BK_STEAM_SETPOINT_MAX) ||
      !firmware_config_write_long_field(out, first, "BK_WATER_ADJUST_PERIOD_MS", BK_WATER_ADJUST_PERIOD_MS) ||
      !firmware_config_write_float_field(out, first, "BK_WATER_DEADBAND", BK_WATER_DEADBAND) ||
      !firmware_config_write_long_field(out, first, "BK_WATER_PWM_STEP", BK_WATER_PWM_STEP)) return false;

#ifdef BLYNK_SAMOVAR_TOOL
  if (!firmware_config_write_string_field(out, first, "BLYNK_SAMOVAR_TOOL", BLYNK_SAMOVAR_TOOL)) return false;
#else
  if (!firmware_config_write_null_field(out, first, "BLYNK_SAMOVAR_TOOL")) return false;
#endif

#ifdef SAMOVAR_USE_BLYNK
  if (!firmware_config_write_bool_field(out, first, "SAMOVAR_USE_BLYNK", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "SAMOVAR_USE_BLYNK", false)) return false;
#endif
#ifdef NOT_USE_INTERFACE_UPDATE
  if (!firmware_config_write_bool_field(out, first, "NOT_USE_INTERFACE_UPDATE", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "NOT_USE_INTERFACE_UPDATE", false)) return false;
#endif
#ifdef USE_UPDATE_OTA
  if (!firmware_config_write_bool_field(out, first, "USE_UPDATE_OTA", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_UPDATE_OTA", false)) return false;
#endif
#ifdef KVIC_USE_9600
  if (!firmware_config_write_bool_field(out, first, "KVIC_USE_9600", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "KVIC_USE_9600", false)) return false;
#endif
#ifdef KVIC_DEBUG
  if (!firmware_config_write_bool_field(out, first, "KVIC_DEBUG", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "KVIC_DEBUG", false)) return false;
#endif
#ifdef USE_NBK_DELTA_PRESSURE
  if (!firmware_config_write_bool_field(out, first, "USE_NBK_DELTA_PRESSURE", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_NBK_DELTA_PRESSURE", false)) return false;
#endif
#ifdef USE_NBK_END_BY_STEAM_RISE
  if (!firmware_config_write_bool_field(out, first, "USE_NBK_END_BY_STEAM_RISE", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_NBK_END_BY_STEAM_RISE", false)) return false;
#endif
#ifdef USE_WATERSENSOR
  if (!firmware_config_write_bool_field(out, first, "USE_WATERSENSOR", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_WATERSENSOR", false)) return false;
#endif
#ifdef USE_WATER_PUMP
  if (!firmware_config_write_bool_field(out, first, "USE_WATER_PUMP", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_WATER_PUMP", false)) return false;
#endif
#ifdef USE_HEAD_LEVEL_SENSOR
  if (!firmware_config_write_bool_field(out, first, "USE_HEAD_LEVEL_SENSOR", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_HEAD_LEVEL_SENSOR", false)) return false;
#endif
#ifdef IGNORE_HEAD_LEVEL_SENSOR_SETTING
  if (!firmware_config_write_bool_field(out, first, "IGNORE_HEAD_LEVEL_SENSOR_SETTING", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "IGNORE_HEAD_LEVEL_SENSOR_SETTING", false)) return false;
#endif
#ifdef WHLS_HIGH_PULL
  if (!firmware_config_write_bool_field(out, first, "WHLS_HIGH_PULL", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "WHLS_HIGH_PULL", false)) return false;
#endif
#ifdef USE_ALARM_BTN
  if (!firmware_config_write_bool_field(out, first, "USE_ALARM_BTN", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_ALARM_BTN", false)) return false;
#endif
#ifdef USE_BTN
  if (!firmware_config_write_bool_field(out, first, "USE_BTN", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_BTN", false)) return false;
#endif
#ifdef USE_BODY_TEMP_AUTOSET
  if (!firmware_config_write_bool_field(out, first, "USE_BODY_TEMP_AUTOSET", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_BODY_TEMP_AUTOSET", false)) return false;
#endif
#ifdef USE_LUA
  if (!firmware_config_write_bool_field(out, first, "USE_LUA", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_LUA", false)) return false;
#endif
#ifdef USE_STEPPER_ACCELERATION
  if (!firmware_config_write_bool_field(out, first, "USE_STEPPER_ACCELERATION", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "USE_STEPPER_ACCELERATION", false)) return false;
#endif
#ifdef STEPPER_REVERSE
  if (!firmware_config_write_bool_field(out, first, "STEPPER_REVERSE", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "STEPPER_REVERSE", false)) return false;
#endif
#ifdef COLUMN_WETTING
  if (!firmware_config_write_bool_field(out, first, "COLUMN_WETTING", true)) return false;
#else
  if (!firmware_config_write_bool_field(out, first, "COLUMN_WETTING", false)) return false;
#endif

#ifdef USE_WATER_VALVE
#if USE_WATER_VALVE == LOW
  if (!firmware_config_write_string_field(out, first, "USE_WATER_VALVE", "LOW")) return false;
#elif USE_WATER_VALVE == HIGH
  if (!firmware_config_write_string_field(out, first, "USE_WATER_VALVE", "HIGH")) return false;
#else
#error USE_WATER_VALVE must be LOW or HIGH for firmware configuration report
#endif
#else
  if (!firmware_config_write_null_field(out, first, "USE_WATER_VALVE")) return false;
#endif
#ifdef USE_EXPANDER
  if (!firmware_config_write_string_field(out, first, "USE_EXPANDER", FIRMWARE_CONFIG_STRINGIFY(USE_EXPANDER))) return false;
#else
  if (!firmware_config_write_null_field(out, first, "USE_EXPANDER")) return false;
#endif
#ifdef USE_ANALOG_EXPANDER
  if (!firmware_config_write_string_field(out, first, "USE_ANALOG_EXPANDER", FIRMWARE_CONFIG_STRINGIFY(USE_ANALOG_EXPANDER))) return false;
#else
  if (!firmware_config_write_null_field(out, first, "USE_ANALOG_EXPANDER")) return false;
#endif
#ifdef USE_ADS1115
  if (!firmware_config_write_string_field(out, first, "USE_ADS1115", FIRMWARE_CONFIG_STRINGIFY(USE_ADS1115))) return false;
#else
  if (!firmware_config_write_null_field(out, first, "USE_ADS1115")) return false;
#endif
#ifdef I2CStepperStepMl
  if (!firmware_config_write_string_field(out, first, "I2CStepperStepMl", FIRMWARE_CONFIG_STRINGIFY(I2CStepperStepMl))) return false;
#else
  if (!firmware_config_write_null_field(out, first, "I2CStepperStepMl")) return false;
#endif
#ifdef WETTING_POWER
  if (!firmware_config_write_string_field(out, first, "WETTING_POWER", FIRMWARE_CONFIG_STRINGIFY(WETTING_POWER))) return false;
#else
  if (!firmware_config_write_null_field(out, first, "WETTING_POWER")) return false;
#endif

#ifdef USE_PRESSURE_XGZ
  if (!firmware_config_write_string_field(out, first, "USE_PRESSURE_XGZ", FIRMWARE_CONFIG_STRINGIFY(USE_PRESSURE_XGZ))) return false;
#else
  if (!firmware_config_write_null_field(out, first, "USE_PRESSURE_XGZ")) return false;
#endif
#ifdef USE_PRESSURE_1WIRE
  if (!firmware_config_write_string_field(out, first, "USE_PRESSURE_1WIRE", FIRMWARE_CONFIG_STRINGIFY(USE_PRESSURE_1WIRE))) return false;
#else
  if (!firmware_config_write_null_field(out, first, "USE_PRESSURE_1WIRE")) return false;
#endif

#ifdef SAMOVAR_USE_SEM_AVR
  if (!firmware_config_write_string_field(out, first, "regulator", "sem_avr")) return false;
#elif defined(SAMOVAR_USE_RMVK)
  if (!firmware_config_write_string_field(out, first, "regulator", "rmvk")) return false;
#elif defined(SAMOVAR_USE_POWER)
  if (!firmware_config_write_string_field(out, first, "regulator", "kvic")) return false;
#else
  if (!firmware_config_write_string_field(out, first, "regulator", "none")) return false;
#endif

#ifdef USE_BMP280_ALT
  if (!firmware_config_write_string_field(out, first, "atmospheric_sensor", "bmp280_alt")) return false;
#elif defined(USE_BMP180)
  if (!firmware_config_write_string_field(out, first, "atmospheric_sensor", "bmp180")) return false;
#elif defined(USE_BMP280)
  if (!firmware_config_write_string_field(out, first, "atmospheric_sensor", "bmp280")) return false;
#elif defined(USE_BME280)
  if (!firmware_config_write_string_field(out, first, "atmospheric_sensor", "bme280")) return false;
#elif defined(USE_BME680)
  if (!firmware_config_write_string_field(out, first, "atmospheric_sensor", "bme680")) return false;
#else
  if (!firmware_config_write_string_field(out, first, "atmospheric_sensor", "none")) return false;
#endif

#ifdef USE_PRESSURE_MPX
  if (!firmware_config_write_string_field(out, first, "column_pressure_sensor", "mpx")) return false;
#elif defined(USE_PRESSURE_1WIRE)
  if (!firmware_config_write_string_field(out, first, "column_pressure_sensor", "onewire")) return false;
#elif defined(USE_PRESSURE_XGZ)
  if (!firmware_config_write_string_field(out, first, "column_pressure_sensor", "xgz")) return false;
#else
  if (!firmware_config_write_string_field(out, first, "column_pressure_sensor", "none")) return false;
#endif

  if (!firmware_config_write_key(out, first, "servoDelta") ||
      !firmware_config_write_char(out, '[')) return false;
  for (uint8_t index = 0; index < 11; index++) {
    if (index != 0 && !firmware_config_write_char(out, ',')) return false;
    if (!firmware_config_write_long(out, servoDelta[index])) return false;
  }
  if (!firmware_config_write_char(out, ']')) return false;

#ifdef SAMOVAR_WIFI_SSID
  if (!firmware_config_write_string_field(out, first, "wifi_ssid", SAMOVAR_WIFI_SSID)) return false;
#else
  if (!firmware_config_write_null_field(out, first, "wifi_ssid")) return false;
#endif
#ifdef SAMOVAR_WIFI_PASSWORD
  if (!firmware_config_write_string_field(out, first, "wifi_password", SAMOVAR_WIFI_PASSWORD)) return false;
#else
  if (!firmware_config_write_null_field(out, first, "wifi_password")) return false;
#endif

  return firmware_config_write_bytes(out, "}}");
}

#undef FIRMWARE_CONFIG_STRINGIFY
#undef FIRMWARE_CONFIG_STRINGIFY_VALUE
