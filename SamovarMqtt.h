#ifndef SAMOVAR_MQTT_H
#define SAMOVAR_MQTT_H

#include <AsyncMqttClient.h>
#define PAYLOADSIZE 2000

AsyncMqttClient mqttClient;
char mqttstr[100] = "SMV/\0";
char mqttstr1[100];
char payload[PAYLOADSIZE];

static const char mqttUser[] = "samovar";
static const char mqttPassword[] = "samovar-tool.ru";

void onMqttConnect(bool sessionPresent);
void onMqttDisconnect(AsyncMqttClientDisconnectReason reason);
void onMqttPublish(uint16_t packetId);
void connectToMqtt();

void initMqtt(){
  char buf[10];
  itoa(chipId, buf, 10);
  mqttClient.onConnect(onMqttConnect);
  mqttClient.onDisconnect(onMqttDisconnect);
  mqttClient.onPublish(onMqttPublish);
  mqttClient.setClientId(buf);
  //mqttClient.setClientId("1234");
  mqttClient.setMaxTopicLength(PAYLOADSIZE);
  mqttClient.setCredentials(mqttUser,mqttPassword);
  mqttClient.setServer("ora1.samovar-tool.ru", 1883);
  strcat(mqttstr,SamSetup.blynkauth);
  strcat(mqttstr,"/");

//  mqttClient.onSubscribe(onMqttSubscribe);
//  mqttClient.onUnsubscribe(onMqttUnsubscribe);
//  mqttClient.onMessage(onMqttMessage);
  
  connectToMqtt();
}

void connectToMqtt() {
//  Serial.println("Connecting to MQTT...");
//  byte i;
//  i = 0;
  mqttClient.connect();
//  while (!mqttClient.connected()){
//    delay(50);
//    i++;
//    if (i > 25) break;
//  }
}

void onMqttConnect(bool sessionPresent) {
//  Serial.print("mqttClient.connected = ");
//  Serial.println(mqttClient.connected());
}

void onMqttDisconnect(AsyncMqttClientDisconnectReason reason) {
  Serial.printf("Disconnected from MQTT: %u\n", static_cast<std::underlying_type<AsyncMqttClientDisconnectReason>::type>(reason));
}

void onMqttPublish(uint16_t packetId) {
//  Serial.println("Publish acknowledged.");
//  Serial.print("  packetId: ");
//  Serial.println(packetId);
}

void MqttSendMsg(String Str, const char *chart ){
  if (strlen(SamSetup.blynkauth) <30 ) return;
//  Serial.println("mqttClient.StartSession");
//  uint16_t packetIdPub1 = mqttClient.publish(MqttStr + "/st", 2, true, "test 1");
  strcpy(mqttstr1, mqttstr);
  strcat(mqttstr1,chart);
  strcat(mqttstr1,"/1");
  Str.toCharArray(payload, PAYLOADSIZE);
  uint16_t packetIdPub1 = mqttClient.publish(mqttstr1, 2, true, payload);
}


#endif