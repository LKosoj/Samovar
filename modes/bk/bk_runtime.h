#ifndef __SAMOVAR_BK_RUNTIME_H_
#define __SAMOVAR_BK_RUNTIME_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "io/power_control.h"

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

void create_data();
void bk_finish();
void SendMsg(const String& m, MESSAGE_TYPE msg_type);

inline void bk_proc() {
  if (!PowerOn) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + ",BK," + SessionDescription, "st");
#endif
    set_power(true);
#ifdef SAMOVAR_USE_POWER
    delay(1000);
    set_power_mode(POWER_SPEED_MODE);
#else
    current_power_mode = POWER_SPEED_MODE;
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
    create_data();
    SteamSensor.Start_Pressure = bme_pressure;
    SendMsg(("Включен нагрев бражной колонны"), NOTIFY_MSG);
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    bk_finish();
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

#endif
