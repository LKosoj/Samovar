void readMQTTSettings() { // Чтение параметров MQTT
 #ifdef ENABLE_MQTT  
  EEPROM.begin(EEPROM_SIZE);
  if (EEPROM.read(MQTT_SAVED_FLAG_ADDR) == MQTT_SAVED_FLAG_VALUE) {
  mqtt_server = readEEPROM(MQTT_SERVER_ADDR, 32);
  EEPROM.get(MQTT_PORT_ADDR,mqtt_port);
  mqtt_user = readEEPROM(MQTT_USER_ADDR, 9);
  mqtt_password = readEEPROM(MQTT_PASSWORD_ADDR, 9); 
  EEPROM.get(MQTT_ATTEMPTS_ADDR, mqtt_attempts);
 // Проверка на валидность значения
 if(mqtt_attempts > 10) mqtt_attempts = 3;  // Значение по умолчанию
  //mqtt_reconnection = EEPROM.read(MQTT_RECONNECTION_ADDR);
  //EEPROM.get(MQTT_TIME_PUBLICATION_ADDR,mqtt_time_publication);
  EEPROM.end();
 /*
  Serial.println();
  Serial.println("mqtt_server:           " + mqtt_server);
  Serial.println("mqtt_port:             " + String(mqtt_port));
  Serial.println("mqtt_user:             " + mqtt_user);
  Serial.println("mqtt_password:         " + mqtt_password);
  Serial.println("mqtt_topic_temp:      " + mqtt_topic_temp);
  Serial.println("mqtt_topic_press:      " + mqtt_topic_press);
  Serial.println("mqtt_topic_alc:       " + mqtt_topic_alc);
  Serial.println("mqtt_attempts:         " + String(mqtt_attempts));
  Serial.println("mqtt_time_publication: " + String(mqtt_time_publication));
  Serial.println("mqtt_reconnection:     " + String(mqtt_reconnection));
  Serial.println();*/
  
    
  }
 #endif 
}
// Функция для обработки входящих MQTT сообщений
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  #ifdef ENABLE_MQTT
  String message;
  for (int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  // Управление только при активном подключении
  if (mqttClient.connected()) {
    if (String(topic) == mqtt_topic_temp) {
        //setPower(message.toInt());      // Установка мощности
        //mqttClient.publish(mqtt_topic_status.c_str(), ("Power set to: " + String(powerSetpoint)).c_str());
      }
    } else if (String(topic) == mqtt_topic_press) {
      // Включение/выключение режима разгона
      if (message == "1") {
       // boost(ON);
       // mqttClient.publish(mqtt_topic_status.c_str(), "Boost mode enabled");
      } else if (message == "0") {
       // boost(OFF);
       // mqttClient.publish(mqtt_topic_status.c_str(), "Boost mode disabled");
      }
   } else if (String(topic) == mqtt_topic_alc) {
    // Включение/выключение нагрева
    if (message == "1") {
      //heat(ON);
      //mqttClient.publish(mqtt_topic_status.c_str(), "Heat enabled");
    } else if (message == "0") {
      //heat(OFF);
      //mqttClient.publish(mqtt_topic_status.c_str(), "Heat disabled");
    }
  }
#endif 
}

// Функция для подключения к MQTT-брокеру с n попытками
void mqttConnect() {
  #ifdef ENABLE_MQTT
      mqttDebugLog.connectionAttempts++;
    mqttDebugLog.lastAttemptTime = millis();
  int attempts = 0;
  while (!mqttClient.connected() && attempts < mqtt_attempts ) { // Попытки 
   mqttDebugLog.connectionLog = "Попытка подключения к " + mqtt_server + ":" + String(mqtt_port);
    //Serial.print("Attempting MQTT connection...");
    if (mqttClient.connect("ESP12E_Measurer", mqtt_user.c_str(), mqtt_password.c_str())) {
      mqttDebugLog.connectionLog += "\nУспешное подключение!";
      mqttDebugLog.lastError = "";
      //Serial.println("connected");
      //mqttClient.subscribe(mqtt_topic_temp.c_str());
      //mqttClient.subscribe(mqtt_topic_press.c_str());
      //mqttClient.subscribe(mqtt_topic_alc.c_str());
      String initMsg = "Устройство запущено. IP: " + WiFi.localIP().toString();
            mqttClient.publish(mqtt_topic_status.c_str(), initMsg.c_str());
            mqttDebugLog.lastStatus = initMsg;
        } else {
            mqttDebugLog.lastError = "Ошибка подключения. Код: " + String(mqttClient.state());
      //Serial.print("failed, rc=");
      //Serial.print(mqttClient.state());
      //Serial.println(" try again in 1 seconds");
      delay(500);
      attempts++;
    }
  }
  if (attempts >= mqtt_attempts) {
    mqttDebugLog.lastError = "Не удалось подключиться после " + String(mqtt_attempts) + " попыток";
    //Serial.println("Failed to connect to MQTT broker after " + String(mqtt_attempts) + " attempts.");
  }
  #endif 
}

// Инициализация MQTT
void setupMQTT() {
  #ifdef ENABLE_MQTT
  readMQTTSettings(); // Чтение параметров MQTT из EEPROM
  delay(100); // Даем время на стабилизацию
  mqttClient.setServer(mqtt_server.c_str(), mqtt_port);
  mqttClient.setCallback(mqttCallback);
  startTime = millis(); // Засекаем время старта
  mqttConnect();
  #endif 
}
// Функция для публикации данных
void publishMQTTData() {
    #ifdef ENABLE_MQTT
    if (!mqttClient.connected()) {
        mqttDebugLog.lastError = "Нет подключения к MQTT брокеру";
        return;
    }

    // Публикация температур
    for (int i = 1; i <= 7; i++) {
        String topic = mqtt_topic_temp + "/t" + String(i);
        if (ntcEn[i]) {
            mqttClient.publish(topic.c_str(), String(Temp[i], 2).c_str());
        } else {
            mqttClient.publish(topic.c_str(), "null");
        }
    }

    // Публикация давлений
    for (int i = 1; i <= 3; i++) {
        String topic = mqtt_topic_press + "/p" + String(i);
        if (Pressure_enable[i]) {
            mqttClient.publish(topic.c_str(), String(pressure[i], 2).c_str());
        } else {
            mqttClient.publish(topic.c_str(), "null");
        }
    }
    
    // Давление для самовара из Temp[0]
    String samovarTopic = mqtt_topic_press + "/for_Samovar";
    if (Pressure_enable[0]) {
        mqttClient.publish(samovarTopic.c_str(), String(Temp[0], 2).c_str());
    } else {
        mqttClient.publish(samovarTopic.c_str(), "null");
    }

    // Публикация статуса (RSSI и uptime)
    if (millis() - lastStatusUpdate >= 60000) { // Каждую минуту
        String statusMsg = "IP: " + WiFi.localIP().toString() + 
                         ", RSSI: " + String(WiFi.RSSI()) + " dBm" +
                         ", Uptime: " + String((millis() - startTime) / 1000) + " sec";
        mqttClient.publish(mqtt_topic_status.c_str(), statusMsg.c_str());
        lastStatusUpdate = millis();
    }
        // При успешной публикации обновляем статус
    mqttDebugLog.lastStatus = "Данные отправлены: " + String(millis());
  #endif 
}
// Обновление MQTT в основном цикле
void loopMQTT() {
  #ifdef ENABLE_MQTT
    static unsigned long timeout = millis(); //раз в минуту проверяем соединение с mqtt сервером если включена настройка
  if (millis() - timeout >= 60000) { 
  if (mqtt_reconnection && !mqttClient.connected()) {
      if (mqttClient.connect("ESP12E_Measurer", mqtt_user.c_str(), mqtt_password.c_str())) {
      mqttClient.subscribe(mqtt_topic_temp.c_str());
      mqttClient.subscribe(mqtt_topic_press.c_str());
      mqttClient.subscribe(mqtt_topic_alc.c_str());
    }
  }//*/
    timeout = millis();                    //перезапуск секундного таймера
  }    
  mqttClient.loop();
  // Публикация текущего статуса только при активном подключении
  static unsigned long lastMQTTPublish = 0;
if (millis() - lastMQTTPublish >= mqtt_time_publication) {
  if (mqttClient.connected()) {
    publishMQTTData(); 
    }
  lastMQTTPublish = millis();
}
  #endif 
}