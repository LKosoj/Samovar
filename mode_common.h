#pragma once

#include <Arduino.h>
#include "runtime_helpers.h"
#include "samovar_api.h"

inline bool mode_deadline_expired(uint32_t deadline) {
  return (int32_t)(millis() - deadline) >= 0;
}

inline uint32_t mode_deadline_from_now(uint32_t delayMs) {
  return millis() + delayMs;
}

inline void mode_clear_alarm_pause_if_expired() {
  if (alarm_t_min > 0 && mode_deadline_expired(alarm_t_min)) alarm_t_min = 0;
}

inline void mode_set_alarm_pause_ms(uint32_t delayMs) {
  alarm_t_min = mode_deadline_from_now(delayMs);
}

inline bool mode_check_powered_cooling_sensors(const char* modeName) {
  if (!sensor_valid(WaterSensor) && process_sensor_failed(modeName, "воды")) return false;
  if (optional_sensor_failed(ACPSensor) && process_sensor_failed(modeName, "ТСА")) return false;
  return true;
}

inline bool mode_should_open_cooling(bool requirePower, bool includeAcp, bool includeTank) {
  if (valve_status) return false;
  if (requirePower && !PowerOn) return false;
  if (includeAcp && sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP - 5)) return true;
  return includeTank && PowerOn && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP;
}

inline bool mode_should_close_cooling(float closeTemp, bool requireAcpCoolEnough) {
  if (PowerOn || is_self_test || !valve_status || WaterSensor.avgTemp > closeTemp) return false;
  if (!requireAcpCoolEnough) return true;
  return !sensor_configured(ACPSensor) || ACPSensor.avgTemp <= MAX_ACP_TEMP - 10;
}

inline void mode_stop_cooling_pump_if_started() {
#ifdef USE_WATER_PUMP
  if (pump_started) set_pump_pwm(0);
#endif
}

inline void mode_request_water_flow_emergency_if_needed() {
#ifdef USE_WATERSENSOR
  if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
    set_buzzer(true);
    request_emergency_stop("Аварийное отключение! Прекращена подача воды.");
  }
#endif
}

inline bool mode_water_pre_alarm_due() {
  return WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5 && PowerOn && alarm_t_min == 0;
}

inline void mode_update_water_pump_pid(float acpBoostThreshold) {
#ifdef USE_WATER_PUMP
  if (!valve_status) return;
  if (sensor_configured(ACPSensor) && sensor_reading_valid(ACPSensor) && ACPSensor.avgTemp > acpBoostThreshold && ACPSensor.avgTemp > WaterSensor.avgTemp) {
    set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
  } else {
    set_pump_speed_pid(WaterSensor.avgTemp);
  }
#else
  (void)acpBoostThreshold;
#endif
}

inline void mode_reduce_power_for_water_alarm_by_volts(const String& alarmMessage, float reduceVolts) {
#ifdef SAMOVAR_USE_POWER
  if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
    set_buzzer(true);
    SendMsg(alarmMessage, ALARM_MSG);
    set_current_power(reduce_power_by_volts(target_power_volt, reduceVolts));
  }
#else
  (void)alarmMessage;
  (void)reduceVolts;
#endif
}

inline void mode_update_water_valve_by_setpoint() {
#ifdef USE_WATER_VALVE
  if (WaterSensor.avgTemp >= SamSetup.SetWaterTemp + 1) {
    digitalWrite(WATER_PUMP_PIN, USE_WATER_VALVE);
  } else if (WaterSensor.avgTemp <= SamSetup.SetWaterTemp - 1) {
    digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
  }
#endif
}

inline bool mode_start_heating_session(
  int16_t activeStatus,
  const char* createLogError,
  const char* sessionBusyError,
  const String& mqttProgram,
  const char* heatingMessage,
  bool resetHeatLoss
) {
  if (PowerOn || SamovarStatusInt != activeStatus || alarm_event) return false;

  if (resetHeatLoss) reset_heat_loss_calculation();
  if (!create_data()) {
    SendMsg(createLogError, ALARM_MSG);
    SamovarStatusInt = 0;
    startval = 0;
    return false;
  }

  if (alarm_event || SamovarStatusInt != activeStatus) {
    if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
    return false;
  }

#ifdef USE_MQTT
  String sessionDescription;
  if (!copy_mqtt_session_description(sessionDescription, portMAX_DELAY)) {
    SendMsg(sessionBusyError, ALARM_MSG);
    SamovarStatusInt = 0;
    startval = 0;
    if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
    return false;
  }
  if (alarm_event || SamovarStatusInt != activeStatus) {
    if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
    return false;
  }
#else
  (void)mqttProgram;
#endif

  if (alarm_event || SamovarStatusInt != activeStatus) {
    if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
    return false;
  }

  set_power(true);
  if (alarm_event || SamovarStatusInt != activeStatus || !PowerOn) {
    if (PowerOn) set_power(false, false);
    if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
    return false;
  }
#ifdef SAMOVAR_USE_POWER
  delay(1000);
  set_power_mode(POWER_SPEED_MODE);
#else
  set_current_power_mode_value(POWER_SPEED_MODE);
  digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  SteamSensor.Start_Pressure = bme_pressure;
  if (alarm_event || SamovarStatusInt != activeStatus || !PowerOn) {
    if (PowerOn) set_power(false, false);
    if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
    return false;
  }
#ifdef USE_MQTT
  MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + mqttProgram + "," + sessionDescription, "st");
  if (alarm_event || SamovarStatusInt != activeStatus || !PowerOn) {
    if (PowerOn) set_power(false, false);
    if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
    return false;
  }
#endif
  SendMsg(heatingMessage, NOTIFY_MSG);
  return true;
}
