#ifndef __SAMOVAR_MQTT_H_
#define __SAMOVAR_MQTT_H_

#include <AsyncMqttClient.h>
#include "Samovar.h"
#include "samovar_api.h"

#define PAYLOADSIZE 800
#define MQTT_TOPIC_SIZE 128

AsyncMqttClient mqttClient;
SemaphoreHandle_t xMqttSemaphore = NULL;
StaticSemaphore_t xMqttSemaphoreBuffer;

char mqttstr[100] = "SMV/";

static const char mqttUser[] = "samovar";
static const char mqttPassword[] = "samovar-tool.ru";

void onMqttConnect(bool sessionPresent);
void onMqttDisconnect(AsyncMqttClientDisconnectReason reason);
void onMqttPublish(uint16_t packetId);
void connectToMqtt();
void disconnectFromMqtt();
bool mqttConnected();

inline void mqtt_local_error(const __FlashStringHelper* message) {
  Serial.println(message);
}

inline bool init_mqtt_lock() {
  xMqttSemaphore = xSemaphoreCreateMutexStatic(&xMqttSemaphoreBuffer);
  return xMqttSemaphore != NULL;
}

inline bool mqtt_lock(TickType_t timeout = pdMS_TO_TICKS(500)) {
  return xMqttSemaphore && xSemaphoreTake(xMqttSemaphore, timeout) == pdTRUE;
}

inline void mqtt_unlock(bool locked) {
  if (locked) xSemaphoreGive(xMqttSemaphore);
}

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
  snprintf(mqttstr, sizeof(mqttstr), "SMV/%s/", SamSetup.blynkauth);

  if (strlen(SamSetup.blynkauth) < 30) send_mqtt = false; else send_mqtt = true;

  connectToMqtt();
}

void connectToMqtt() {
  bool locked = mqtt_lock(pdMS_TO_TICKS(500));
  if (!locked) {
    mqtt_local_error(F("MQTT mutex busy: connect skipped"));
    return;
  }
  if (!mqttClient.connected()) {
    mqttClient.connect();
  }
  mqtt_unlock(true);
}

void disconnectFromMqtt() {
  bool locked = mqtt_lock(pdMS_TO_TICKS(500));
  if (!locked) {
    mqtt_local_error(F("MQTT mutex busy: disconnect skipped"));
    return;
  }
  if (mqttClient.connected()) {
    mqttClient.disconnect();
  }
  mqtt_unlock(true);
}

bool mqttConnected() {
  bool locked = mqtt_lock(pdMS_TO_TICKS(100));
  if (!locked) return false;
  bool connected = mqttClient.connected();
  mqtt_unlock(true);
  return connected;
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
  char topic[MQTT_TOPIC_SIZE];
  int topicLength = snprintf(topic, sizeof(topic), "%s%s/%d", mqttstr, chart, version);
  if (topicLength < 0 || topicLength >= (int)sizeof(topic)) {
    mqtt_local_error(F("MQTT topic too long, message not sent"));
    return;
  }
  if (Str.length() >= PAYLOADSIZE) {
    mqtt_local_error(F("MQTT payload too long, message not sent"));
    return;
  }
  char payload[PAYLOADSIZE];
  const size_t payloadLength = Str.length();
  memcpy(payload, Str.c_str(), payloadLength);
  payload[payloadLength] = '\0';

  bool locked = mqtt_lock(pdMS_TO_TICKS(500));
  if (!locked) {
    mqtt_local_error(F("MQTT mutex busy: publish skipped"));
    return;
  }
  uint16_t packetIdPub1 = mqttClient.publish(topic, 2, true, payload, payloadLength);
  if (packetIdPub1 == 0) {
    if (!mqttClient.connected()){
      mqttClient.connect();
    }
    packetIdPub1 = mqttClient.publish(topic, 2, true, payload, payloadLength);
  }
  mqtt_unlock(true);
}

#endif
