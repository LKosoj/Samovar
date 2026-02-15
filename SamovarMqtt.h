#ifndef __SAMOVAR_MQTT_H_
#define __SAMOVAR_MQTT_H_

#include <AsyncMqttClient.h>
#include "Samovar.h"

#define PAYLOADSIZE 800

AsyncMqttClient mqttClient;

char mqttstr[100] = "SMV/\0";
char mqttstr1[100];

static const char mqttUser[] = "samovar";
static const char mqttPassword[] = "samovar-tool.ru";

void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void onMqttConnect(bool sessionPresent);
void onMqttDisconnect(AsyncMqttClientDisconnectReason reason);
void onMqttPublish(uint16_t packetId);
void connectToMqtt();

void initMqtt() {
  char buf[10];
  itoa(chipId, buf, 10);
  mqttClient.onConnect(onMqttConnect);
  mqttClient.onDisconnect(onMqttDisconnect);
  mqttClient.onPublish(onMqttPublish);
  mqttClient.setClientId(buf);
  mqttClient.setMaxTopicLength(PAYLOADSIZE);
  mqttClient.setCredentials(mqttUser, mqttPassword);
  mqttClient.setServer("ora1.samovar-tool.ru", 1883);
  strcat(mqttstr, SamSetup.blynkauth);
  strcat(mqttstr, "/");

  if (strlen(SamSetup.blynkauth) < 30) send_mqtt = false; else send_mqtt = true;

  connectToMqtt();
}

void connectToMqtt() {
  mqttClient.connect();
}

void onMqttConnect(bool sessionPresent) {
#ifdef __SAMOVAR_DEBUG
  String s = "mqttClient.connected";
  SendMsg(s, NOTIFY_MSG);
  WriteConsoleLog(s);
#endif
}

void onMqttDisconnect(AsyncMqttClientDisconnectReason reason) {
#ifdef __SAMOVAR_DEBUG
  String s = "Disconnected from MQTT: " + String(static_cast<std::underlying_type<AsyncMqttClientDisconnectReason>::type>(reason));
  SendMsg(s, ALARM_MSG);
  WriteConsoleLog(s);
#endif
}

void onMqttPublish(uint16_t packetId) {
}

void MqttSendMsg(const String &Str, const char *chart, int version) {
  if (!send_mqtt) return;
  strcpy(mqttstr1, mqttstr);
  strcat(mqttstr1, chart);
  static char payload[PAYLOADSIZE];

  char vstr[5];
  itoa(version, vstr, 10);
  strcat(mqttstr1, "/");
  strcat(mqttstr1, vstr);
  
  copyStringSafe(payload, Str);
  uint16_t packetIdPub1 = mqttClient.publish(mqttstr1, 2, true, payload);
  if (packetIdPub1 == 0) {
    if (!mqttClient.connected()){
      mqttClient.connect();
    }
    packetIdPub1 = mqttClient.publish(mqttstr1, 2, true, payload);
  }
}

#endif
