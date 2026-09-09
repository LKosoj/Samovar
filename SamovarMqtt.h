#ifndef __SAMOVAR_MQTT_H_
#define __SAMOVAR_MQTT_H_

#ifdef USE_MQTT

#include <mqtt_client.h>

static esp_mqtt_client_handle_t mqttClient = nullptr;
static volatile bool mqttClientConnected = false;

#ifdef SAMOVAR_USE_BLYNK
extern volatile uint32_t blynkLastLargePublishAt;
#endif

static esp_err_t mqtt_event_handler(esp_mqtt_event_handle_t event) {
  if (event->event_id == MQTT_EVENT_CONNECTED) {
    mqttClientConnected = true;
    Serial.printf("MQTT connected at_ms=%lu\n", static_cast<unsigned long>(millis()));
  } else if (event->event_id == MQTT_EVENT_DISCONNECTED) {
    mqttClientConnected = false;
    Serial.printf("MQTT disconnected at_ms=%lu\n", static_cast<unsigned long>(millis()));
  }
  return ESP_OK;
}

inline bool init_mqtt() {
  esp_mqtt_client_config_t config = {};
  config.event_handle = mqtt_event_handler;
  config.host = MQTT_SERVER;
  config.port = MQTT_PORT;
  config.username = MQTT_USER[0] ? MQTT_USER : nullptr;
  config.password = MQTT_PASSWORD[0] ? MQTT_PASSWORD : nullptr;
  config.transport = MQTT_TRANSPORT_OVER_TCP;
  config.reconnect_timeout_ms = 10000;

  mqttClient = esp_mqtt_client_init(&config);
  if (!mqttClient) {
    Serial.println(F("MQTT init failed"));
    return false;
  }
  if (esp_mqtt_client_start(mqttClient) != ESP_OK) {
    Serial.println(F("MQTT start failed"));
    esp_mqtt_client_destroy(mqttClient);
    mqttClient = nullptr;
    return false;
  }
  return true;
}

inline bool mqtt_publish_log_line(const String& line) {
  if (!mqttClient || !mqttClientConnected) return false;
  // Не накапливаем несколько устаревших QoS 1 сообщений: пока предыдущее не
  // подтверждено брокером, очередной снимок пропускается.
  if (esp_mqtt_client_get_outbox_size(mqttClient) != 0) return false;
  return esp_mqtt_client_enqueue(
      mqttClient, MQTT_TOPIC, line.c_str(), line.length(), 1, true, false) >= 0;
}

#endif  // USE_MQTT

#endif  // __SAMOVAR_MQTT_H_
