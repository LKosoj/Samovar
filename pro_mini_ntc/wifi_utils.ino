void writeEEPROM(int addr, String data, byte limit) { // Функция для сохранения данных в EEPROM
  for (int i = 0; i < data.length() && i < limit; i++) {
    EEPROM.write(addr + i, data[i]);
  }
  EEPROM.write(addr + data.length(), 0); // Записываем нулевой байт в конце 
}

String readEEPROM(int addr, byte limit) { // Функция для чтения данных из EEPROM с пределом длины
  String data;
  char ch;
  int length = 0; // Счетчик прочитанных символов
  // Читаем символы до тех пор, пока не встретим нулевой символ или не достигнем предела длины
  while ((ch = EEPROM.read(addr++)) && length < limit) {
    data += ch;
    length++;
  }
  return data;
}

// Старт точки доступа
void startHotspot() {
  #ifdef ENABLE_WIFI  
  hotspotMode = true;
  WiFi.softAP("Measurer", "12345678");
  //Serial.println("Точка доступа запущена. IP: " + WiFi.softAPIP().toString());
  #endif // WIFI
}

 void ConnectWIFI(String SSID, String Pass){
  #ifdef ENABLE_WIFI  
   WiFi.setSleep(false);
   WiFi.setHostname("Measurer");
   WiFi.setAutoReconnect(true);
   WiFi.begin(SSID, Pass);
   //Serial.print("Подключение к WiFi "); 
   //Serial.println(SSID); //Serial.println(savedPass);
    /*uint32_t startTime = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startTime < 10000) {
      //Serial.print(".");
      delay(100);
    } */
    //Serial.println();
  #endif // WIFI
  }

void WiFiSetup(String savedSSID, String savedPass){
  #ifdef ENABLE_WIFI  
 hotspotMode = false;
 EEPROM.begin(EEPROM_SIZE);
 writeEEPROM(SSID_ADDR, savedSSID, 31);
 writeEEPROM(PASS_ADDR, savedPass, 31);
 EEPROM.write(WIFI_SAVED_FLAG_ADDR,WIFI_SAVED_FLAG_VALUE);
 EEPROM.commit();
 EEPROM.end();
 if (WiFi.status() != WL_CONNECTED) ConnectWIFI(savedSSID, savedPass);
 #endif // WIFI
}
void hotspotSetup(){
  #ifdef ENABLE_WIFI  
 //Serial.println("Starting hotspot...");  // Отладочный вывод
 hotspotMode = true;
 EEPROM.begin(EEPROM_SIZE);
 writeEEPROM(SSID_ADDR, "", 31);
 writeEEPROM(PASS_ADDR, "", 31);
 EEPROM.write(WIFI_SAVED_FLAG_ADDR,WIFI_SAVED_FLAG_VALUE);
 EEPROM.commit();
 EEPROM.end(); 
 startHotspot();
 #endif // WIFI
}

// Инициализация Wifi
void initWiFi() {
  #ifdef ENABLE_WIFI  
   EEPROM.begin(EEPROM_SIZE);
   if(EEPROM.read(WIFI_SAVED_FLAG_ADDR)==WIFI_SAVED_FLAG_VALUE) {
   savedSSID = readEEPROM(SSID_ADDR, 32);
   savedPass = readEEPROM(PASS_ADDR, 32);
  }
   EEPROM.end();
   if (savedSSID.length() == 0) 
   {savedSSID = defaultSSID; savedPass = defaultPass;}
   if (savedSSID.length() != 0) ConnectWIFI(savedSSID, savedPass);
   /*
    if (WiFi.status() != WL_CONNECTED) {
      //Serial.println("Failed to connect to WiFi. Starting hotspot...");
      startHotspot();
    } else {
      Serial.println();
      Serial.print("Connected to WiFi. IP: ");
      Serial.println(WiFi.localIP());
      Serial.print("Signal Strength (RSSI): ");
      Serial.print(WiFi.RSSI()); Serial.println(" dBm");
      localIP = WiFi.localIP().toString();
      }*/
#endif // WIFI    
}
/*
void loopWIFI(){
  #ifdef ENABLE_WIFI  
  #if defined WIFI_RECONNECT
  if (WiFi.status() != WL_CONNECTED) {
      WiFi.disconnect();
      WiFi.reconnect();
    //WiFi.begin(savedSSID, savedPass);
    RSSI = 0; 
  } else {
    RSSI = WiFi.RSSI(); 
  }
  #endif
  #endif
} */
