void initOTA() {
   #ifdef ENABLE_OTA   // Запуск ОТА
   ArduinoOTA.setHostname("ESP12E");
   ArduinoOTA.setPassword("admin");
    ArduinoOTA.onStart([]() { Serial.println("Запуск OTA");});
    ArduinoOTA.onEnd([]() { Serial.println("\nПрошивка передана."); });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("Передано: %u%%\r", (progress / (total / 100)));  });
    ArduinoOTA.onError([](ota_error_t error) {Serial.printf("Ошибка[%u]: ", error);
        if (error == OTA_AUTH_ERROR) Serial.println("Неудачная авторизация");
        else if (error == OTA_BEGIN_ERROR) Serial.println("Сбой запуска ОТА");
        else if (error == OTA_CONNECT_ERROR) Serial.println("Сбой подключения ОТА");
        else if (error == OTA_RECEIVE_ERROR) Serial.println("Сбой передачи ОТА");
        else if (error == OTA_END_ERROR) Serial.println("Сбой окончания ОТА"); });

    ArduinoOTA.begin();
    Serial.println("Сервер OTA запущен.");
   #endif \\ENABLE_OTA 
}
