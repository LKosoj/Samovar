#include <ESP8266WiFi.h>
#include <Arduino.h>


void handleCalculateCurve(AsyncWebServerRequest *request);
void handleSaveNTCToEEPROM(AsyncWebServerRequest *request);
void handleExportNTCText(AsyncWebServerRequest *request);
void handleImportNTCText(AsyncWebServerRequest *request);
void handleGetTemps(AsyncWebServerRequest *request);

void setupWebServer() {
#ifdef ENABLE_WEB_SERVER
    // Главная страница
    server.on("/", HTTP_GET, [](AsyncWebServerRequest *request) {
        String h = FPSTR(MAIN_PAGE);
        request->send(200, "text/html", h);
    });

    // API для данных
    server.on("/get_data", HTTP_GET, [](AsyncWebServerRequest *request) {
        request->send(200, "application/json", getSensorDataJSON());
    });

    // Настройки Wi-Fi
    server.on("/setup_wifi", HTTP_GET, [](AsyncWebServerRequest *request) {
        String h = FPSTR(WIFI_PAGE);
        h.replace("%s%", savedSSID);
        h.replace("%p%", savedPass);
        request->send(200, "text/html", h);
    });

    // Сохранение настроек Wi-Fi
    server.on("/save_wifi", HTTP_POST, [](AsyncWebServerRequest *request) {
        if (request->hasParam("ssid", true)) savedSSID = request->getParam("ssid", true)->value();
        if (request->hasParam("pass", true)) savedPass = request->getParam("pass", true)->value();
        WiFiSetup(savedSSID, savedPass);
        request->redirect("/");
    });

    // Настройки MQTT
server.on("/setup_mqtt", HTTP_GET, [](AsyncWebServerRequest *request) {
    String h = FPSTR(MQTT_PAGE);
    h.replace("%s%", mqtt_server);
    h.replace("%o%", String(mqtt_port));
    h.replace("%u%", mqtt_user);
    h.replace("%p%", mqtt_password);
    h.replace("%st%", mqttDebugLog.lastStatus);
    h.replace("%lg%", mqttDebugLog.connectionLog);
    h.replace("%er%", mqttDebugLog.lastError);
    h.replace("%a%", String(mqtt_attempts));  // Добавить эту строку
    request->send(200, "text/html", h);
});

    // Сохранение настроек MQTT
// В обработчике "/save_mqtt":
server.on("/save_mqtt", HTTP_POST, [](AsyncWebServerRequest *request) {
    if (request->hasParam("server", true)) mqtt_server = request->getParam("server", true)->value();
    if (request->hasParam("port", true)) mqtt_port = request->getParam("port", true)->value().toInt();
    if (request->hasParam("user", true)) mqtt_user = request->getParam("user", true)->value();
    if (request->hasParam("pass", true)) mqtt_password = request->getParam("pass", true)->value();
    if (request->hasParam("attempts", true)) mqtt_attempts = request->getParam("attempts", true)->value().toInt();
    
    EEPROM.begin(EEPROM_SIZE);
    EEPROM.write(MQTT_SAVED_FLAG_ADDR, MQTT_SAVED_FLAG_VALUE);
    writeEEPROM(MQTT_SERVER_ADDR, mqtt_server, 32);
    EEPROM.put(MQTT_PORT_ADDR, mqtt_port);
    writeEEPROM(MQTT_USER_ADDR, mqtt_user, 9);
    writeEEPROM(MQTT_PASSWORD_ADDR, mqtt_password, 9);
    EEPROM.put(MQTT_ATTEMPTS_ADDR, mqtt_attempts);  // Добавить эту строку
    EEPROM.commit();
    EEPROM.end();
    
    mqttClient.setServer(mqtt_server.c_str(), mqtt_port);
    mqttConnect();
    request->redirect("/setup_mqtt");
});

    // Настройки термисторов
    server.on("/setup_ntc", HTTP_GET, [](AsyncWebServerRequest *request) {
        if(m_adc_text == "") {
            m_adc_text = "";
            for(int i = 0; i < 151; i++) {
                if(i > 0) m_adc_text += ", ";
                m_adc_text += String(m_adc[i]);
            }
        }

        String h = FPSTR(NTC_PAGE);
        h.replace("%r25%", String(setup_R25,2));
        h.replace("%r100%", String(setup_R100,3));
        h.replace("%t25%", String(setup_T25,1));
        h.replace("%t100%", String(setup_T100,1));
        h.replace("%b25%", String(setup_B25,1));
        h.replace("%u33%", String(setup_U33,2));
        h.replace("%uref%", String(setup_Uref,3));
        h.replace("%r62%", String(setup_R62,3));
        h.replace("%r10%", String(setup_R10,3));
        h.replace("%adc%", m_adc_text);
        request->send(200, "text/html", h);
    });

    // Получение текущей характеристики термистора
    server.on("/getCurrentCurve", HTTP_GET, [](AsyncWebServerRequest *request) {
        String curve = "";
        for(int i = 0; i < 151; i++) {
            if(i > 0) curve += ", ";
            curve += String(m_adc[i]);
        }
        request->send(200, "text/plain", curve);
    });

// Обработчик установки датчика алкоголя
server.on("/setAlcSensor", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasParam("num")) {
        setup_alc_sensor = request->getParam("num")->value().toInt();
        if (setup_alc_sensor < 1 || setup_alc_sensor > 3) {
            setup_alc_sensor = 1;
        }
    }
    request->send(200, "text/plain", "OK");
});

// Обработчик термокоррекции
server.on("/setAlcThermo", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasParam("value")) {
        setup_alc_k_temp = request->getParam("value")->value().toFloat();
    }
    request->send(200, "text/plain", "OK");
});

// Обработчик калибровки
server.on("/calibrateAlc", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasParam("target")) {
        float target = request->getParam("target")->value().toFloat();
        if (target > 0 && target <= 100 && pressure[setup_alc_sensor] > 0.2) {
            setup_alc_target = target;
            setup_alc_k = Alc_to_G((uint16_t)(setup_alc_target * 100)) / pressure[setup_alc_sensor];
            request->send(200, "text/plain", String(setup_alc_k, 1));
        } else {
            request->send(400, "text/plain", "Invalid target or pressure too low");
        }
    } else {
        request->send(400, "text/plain", "Missing target parameter");
    }
});

    // Получение данных алкоголя
    server.on("/getAlcData", HTTP_GET, [](AsyncWebServerRequest *request) {
        float alc = 0.0;
        float alcTemp = 0.0;
        float currentPressure = 0.0;
        float currentTemp = Temp[6];
        
        if (pressure[setup_alc_sensor] > 0.2) {
            alc = (float)G_to_alc((uint16_t)(setup_alc_k * pressure[setup_alc_sensor])) / 10;
            alcTemp = alc + (20 - currentTemp) * setup_alc_k_temp;
            currentPressure = pressure[setup_alc_sensor];
        }
        
        String json = "{";
        json += "\"alc\":" + String(alc, 2) + ",";
        json += "\"alcTemp\":" + String(alcTemp, 2) + ",";
        json += "\"pressure\":" + String(currentPressure, 2) + ",";
        json += "\"temp\":" + String(currentTemp, 1);
        json += "}";
        request->send(200, "application/json", json);
    });

// Обработчик сохранения настроек
server.on("/saveAlcToEEPROM", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasParam("k")) {
        setup_alc_k = request->getParam("k")->value().toFloat();
    }
    
    EEPROM.begin(EEPROM_SIZE);
    EEPROM.put(N_dPressAlc_EAdr, setup_alc_sensor);
    EEPROM.put(k_Alc_T_EAdr, setup_alc_k_temp);
    EEPROM.put(k_Alc_EAdr, setup_alc_k);
    EEPROM.commit();
    EEPROM.end();
    request->send(200, "text/plain", "Настройки сохранены в EEPROM");
});

    // Настройки зуммера
    server.on("/setup_spk", HTTP_GET, [](AsyncWebServerRequest *request) {
        String h = FPSTR(SPK_PAGE);
        h.replace("%s0", spk_on == -1 ? " selected" : "");
        h.replace("%s1", spk_on == 0 ? " selected" : "");
        h.replace("%s2", spk_on == 1 ? " selected" : "");
        h.replace("%s3", spk_on == 2 ? " selected" : "");
        h.replace("%s4", spk_on == 3 ? " selected" : "");
        h.replace("%s5", spk_on == 4 ? " selected" : "");
        h.replace("%tt", String(T_target, 1));
        h.replace("%cc", String(spk_max_count));
        request->send(200, "text/html", h);
    });

    // Сохранение настроек зуммера
    server.on("/save_spk", HTTP_POST, [](AsyncWebServerRequest *request) {
        bool needSave = false;
        
        if (request->hasParam("t_target", true)) {
            T_target = request->getParam("t_target", true)->value().toFloat();
            needSave = true;
        }
        if (request->hasParam("spk_count", true)) {
            spk_max_count = request->getParam("spk_count", true)->value().toInt();
            needSave = true;
        }
        if (request->hasParam("sensor", true)) {
            spk_on = request->getParam("sensor", true)->value().toInt();
            needSave = true;
            if (spk_on > -1) spk_count = spk_max_count + spk_max_count;
        }
        
        if (needSave) {
            EEPROM.begin(EEPROM_SIZE);
            if (request->hasParam("t_target", true)) EEPROM.put(T_target_EAdr, T_target);
            if (request->hasParam("spk_count", true)) EEPROM.put(spk_max_count_EAdr, spk_max_count);
            if (request->hasParam("sensor", true)) EEPROM.put(spk_on_EAdr, spk_on);
            EEPROM.commit();
            EEPROM.end();
        }
        
        request->redirect("/setup_spk");
    });

// Настройка датчиков давления
server.on("/pressure_setup", HTTP_GET, [](AsyncWebServerRequest *r){
    String h = FPSTR(PRESSURE_PAGE);
    h.replace("%KDD%", String(XGZP6897D_k));
    for(int i=1;i<=3;i++){
        h.replace("%S"+String(i)+"%",(Pressure_enable[i]==1)?" checked":"");
        h.replace("%D"+String(i)+"%",(Pressure_enable[i]==1)?"":" style=display:none");
        h.replace("%DS"+String(i)+"%",(Pressure_enable[0]==i)?" selected":"");
    }
    h.replace("%DS0%",(Pressure_enable[0]==0)?" selected":"");
    h.replace("%KT1%",String(KTemp_1,2));
    h.replace("%BT1%",String(BaseTemp_1,1));
    h.replace("%PQ%",String(PressureQ,6));
    h.replace("%HXM%",String(HX710B_Mult,2));
    h.replace("%KT3%",String(KTemp_3,2));
    h.replace("%BT3%",String(BaseTemp_3,1));
    h.replace("%O1%",String(dPress_1,2));
    h.replace("%O2%",String(PressureBaseADS,0));
    h.replace("%O3%",String(dPress_3,2));
    r->send(200,"text/html",h);
});

// Сохранение настроек давления
server.on("/savePressureSettings", HTTP_POST, [](AsyncWebServerRequest *request) {
    EEPROM.begin(EEPROM_SIZE);
    
    if (request->hasParam("defaultSensor", true)) {
        Pressure_enable[0] = request->getParam("defaultSensor", true)->value().toInt();
        EEPROM.put(DEFAULT_PRESSURE_ADDR, Pressure_enable[0]);
    }
    
    for (int i = 1; i <= 3; i++) {
        String argName = "sensor" + String(i);
        if (request->hasParam(argName, true)) {
            bool enabled = request->getParam(argName, true)->value() == "1";
            Pressure_enable[i] = enabled ? 1 : 0;
            
            if (i == 2) {
                EEPROM.put(PRESSURE_MPX_ENABLE_ADDR, Pressure_enable[2]);
            }
            if (i == 3) {
                EEPROM.put(PRESSURE_HX710B_ENABLE_ADDR, Pressure_enable[3]);
            } 
        }
    }
    if (request->hasParam("kdd", true)) {
        XGZP6897D_k = request->getParam("kdd", true)->value().toInt();
        EEPROM.put(XGZP6897D_K_ADDR, XGZP6897D_k);
    }
    if (request->hasParam("b1", true)) {
        BaseTemp_1 = request->getParam("b1", true)->value().toFloat();
        EEPROM.put(BaseTemp_1_EAdr, BaseTemp_1);
    }
    if (request->hasParam("p", true)) {
        PressureQ = request->getParam("p", true)->value().toFloat();
        EEPROM.put(PressureQ_EAdr, PressureQ);
    }
    if (request->hasParam("h", true)) {
        HX710B_Mult = request->getParam("h", true)->value().toFloat();
        EEPROM.put(HX710B_Mult_EAdr, HX710B_Mult);
    }
    if (request->hasParam("k3", true)) {
        KTemp_3 = request->getParam("k3", true)->value().toFloat();
        EEPROM.put(KTemp_3_EAdr, KTemp_3);
    }
    if (request->hasParam("b3", true)) {
        BaseTemp_3 = request->getParam("b3", true)->value().toFloat();
        EEPROM.put(BaseTemp_3_EAdr, BaseTemp_3);
    }
    
    for (int i = 1; i <= 3; i++) {
        String offsetName = "o" + String(i);
        if (request->hasParam(offsetName, true)) {
            float offset = request->getParam(offsetName, true)->value().toFloat();
            switch(i) {
                case 1: 
                    dPress_1 = offset;
                    EEPROM.put(dPress_1_EAdr, offset);
                    break;
                case 2:
                    PressureBaseADS = offset;
                    EEPROM.put(PressureBaseADS_EAdr, offset);
                    break;
                case 3:
                    dPress_3 = offset;
                    EEPROM.put(dPress_3_EAdr, offset);
                    break;
            }
        }
    }
    
    EEPROM.commit();
    EEPROM.end();
    request->send(200, "text/plain", "Settings saved");
});

    // Применение настроек давления без сохранения
    server.on("/applyPressureSettings", HTTP_POST, [](AsyncWebServerRequest *request) {
    if (request->hasParam("defaultSensor", true)) {
        Pressure_enable[0] = request->getParam("defaultSensor", true)->value().toInt();
    }
    for (int i = 1; i <= 3; i++) {
        String argName = "sensor" + String(i);
        if (request->hasParam(argName, true)) {
            bool enabled = request->getParam(argName, true)->value() == "1";
            Pressure_enable[i] = enabled ? 1 : 0;
        }
    }
    if (request->hasParam("kdd", true)) {XGZP6897D_k = request->getParam("kdd", true)->value().toInt();}
    if (request->hasParam("b1", true)) { BaseTemp_1 = request->getParam("b1", true)->value().toFloat(); }
    if (request->hasParam("p", true)) { PressureQ = request->getParam("p", true)->value().toFloat(); }
    if (request->hasParam("h", true)) { HX710B_Mult = request->getParam("h", true)->value().toFloat(); }
    if (request->hasParam("k3", true)) {KTemp_3 = request->getParam("k3", true)->value().toFloat(); }
    if (request->hasParam("b3", true)) { BaseTemp_3 = request->getParam("b3", true)->value().toFloat(); }
    for (int i = 1; i <= 3; i++) {
        String offsetName = "o" + String(i);
        if (request->hasParam(offsetName, true)) {
            float offset = request->getParam(offsetName, true)->value().toFloat();
            switch(i) {
                case 1: 
                    dPress_1 = offset;
                    break;
                case 2:
                    PressureBaseADS = offset;
                    break;
                case 3:
                    dPress_3 = offset;
                    break;
            }
        }
    }
        request->redirect("/pressure_setup");
    });

    // Получение значений давления
    server.on("/getPressureValues", HTTP_GET, [](AsyncWebServerRequest *request) {
        String json = "{";
        json += "\"sensor1\":" + String(pressure[1], 2) + ",";
        json += "\"temp1\":" + String(temperature[1], 1) + ",";
        json += "\"sensor2\":" + String(pressure[2], 2) + ",";
        json += "\"temp2\":" + String(Temp[6], 1) + ",";
        json += "\"sensor3\":" + String(pressure[3], 2) + ",";
        json += "\"temp3\":" + String(Temp[6], 1);
        json += "}";
        request->send(200, "application/json", json);
    });

// Обнуление датчика давления
server.on("/zeroPressureSensor", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasParam("sensor")) {
        int sensorNum = request->getParam("sensor")->value().toInt();
        if (sensorNum >= 1 && sensorNum <= 3) {
            EEPROM.begin(EEPROM_SIZE);
            float offset = 0.0;
            
            switch(sensorNum) {
                case 1: // XGZP6897D
                    dPress_1 = pressure[1] + dPress_1 + dPt_1;
                    BaseTemp_1 = temperature[1];
                    offset = dPress_1;
                    EEPROM.put(dPress_1_EAdr, dPress_1);
                    EEPROM.put(BaseTemp_1_EAdr, BaseTemp_1);
                    break;
                    
                case 2: // MPX5010DP
                    PressureBaseADS = (float)readADS(7, 16);// Для MPX5010DP смещение учитывается через PressureBaseADS
                    BaseTemp_2 = Temp[6];
                    offset = PressureBaseADS; 
                    EEPROM.put(PressureBaseADS_EAdr, PressureBaseADS);
                    EEPROM.put(BaseTemp_2_EAdr, BaseTemp_2);
                    break;
                    
                case 3: // HX710B
                    dPress_3 = pressure[3] + dPress_3 + dPt_3;
                    BaseTemp_3 = Temp[6];
                    offset = dPress_3;
                    EEPROM.put(dPress_3_EAdr, dPress_3);
                    EEPROM.put(BaseTemp_3_EAdr, BaseTemp_3);
                    break;
            }
            
            EEPROM.commit();
            EEPROM.end();
            
            // Возвращаем JSON с новым значением смещения
            String json = "{\"offset\":" + String(offset, 2) + "}";
            request->send(200, "application/json", json);
        } else {
            request->send(400, "text/plain", "Invalid sensor number");
        }
    } else {
        request->send(400, "text/plain", "Missing sensor parameter");
    }
});

    // Настройки электронного попугая
server.on("/setup_alc", HTTP_GET, [](AsyncWebServerRequest *request) {
    String html = FPSTR(ALC_PAGE);
    html.replace("%ALCSENSOR%", String(setup_alc_sensor));
    html.replace("%THERMOENABLED%", setup_alc_k_temp > 0 ? "true" : "false");
    html.replace("%ALCTARGET%", String(setup_alc_target));
    html.replace("%ALCK%", String(setup_alc_k, 1));
    request->send(200, "text/html", html);
});

    // Обработчики для работы с характеристикой термистора
    server.on("/calculateCurve", HTTP_POST, [](AsyncWebServerRequest *request) {
        handleCalculateCurve(request);
    });

    server.on("/saveNTCToEEPROM", HTTP_POST, [](AsyncWebServerRequest *request) {
        handleSaveNTCToEEPROM(request);
    });

    server.on("/exportNTCText", HTTP_GET, [](AsyncWebServerRequest *request) {
        handleExportNTCText(request);
    });

    server.on("/importNTCText", HTTP_POST, [](AsyncWebServerRequest *request) {
        handleImportNTCText(request);
    });

    server.on("/getTemps", HTTP_GET, [](AsyncWebServerRequest *request) {
        handleGetTemps(request);
    });

    server.on("/applyNTCText", HTTP_POST, [](AsyncWebServerRequest *request) {
        if (request->hasParam("plain", true)) {
            String text = request->getParam("plain", true)->value();
            text.replace("\n", "");
            text.replace("\r", "");
            
            int index = 0;
            int startPos = 0;
            int endPos = text.indexOf(',');
            
            while (endPos != -1 && index < 151) {
                String numStr = text.substring(startPos, endPos);
                numStr.trim();
                m_adc[index++] = numStr.toInt();
                startPos = endPos + 1;
                endPos = text.indexOf(',', startPos);
            }
            
            if (index < 151 && startPos < text.length()) {
                String numStr = text.substring(startPos);
                numStr.trim();
                m_adc[index] = numStr.toInt();
            }
            
            m_adc_text = text;
            request->send(200, "text/plain", "Характеристика применена в память");
        } else {
            request->send(400, "text/plain", "Ошибка: отсутствуют данные");
        }
    });

    // Перезагрузка устройства
    server.on("/restart", HTTP_POST, [](AsyncWebServerRequest *request) {
        request->send(200, "text/plain", "Перезагрузка устройства...");
        ESP.reset();
    });
    // Страница эмулятора
    server.on("/debug", HTTP_GET, [](AsyncWebServerRequest *request) {
        String h = FPSTR(DEBUG_PAGE);
        h.replace("%debug_checked%", debug_mode ? "checked" : "");
        h.replace("%temp0%", String(Temp_debug[0], 1)); // Давление в Temp[0]
        h.replace("%temp1%", String(Temp_debug[1], 1));
        h.replace("%temp2%", String(Temp_debug[2], 1));
        h.replace("%temp3%", String(Temp_debug[3], 1));
        h.replace("%temp4%", String(Temp_debug[4], 1));
        h.replace("%temp5%", String(Temp_debug[5], 1));
        request->send(200, "text/html", h);
    });

    // Обработчик сохранения настроек эмулятора
    server.on("/save_debug", HTTP_POST, [](AsyncWebServerRequest *request) {
        if (request->hasParam("debug_mode", true)) {
            debug_mode = request->getParam("debug_mode", true)->value() == "on";
        } else debug_mode = false;
        
        if (request->hasParam("temp0", true)) Temp_debug[0] = request->getParam("temp0", true)->value().toFloat();
        if (request->hasParam("temp1", true)) Temp_debug[1] = request->getParam("temp1", true)->value().toFloat();
        if (request->hasParam("temp2", true)) Temp_debug[2] = request->getParam("temp2", true)->value().toFloat();
        if (request->hasParam("temp3", true)) Temp_debug[3] = request->getParam("temp3", true)->value().toFloat();
        if (request->hasParam("temp4", true)) Temp_debug[4] = request->getParam("temp4", true)->value().toFloat();
        if (request->hasParam("temp5", true)) Temp_debug[5] = request->getParam("temp5", true)->value().toFloat();        
        request->redirect("/debug");
    });
    // Запуск сервера
    server.begin();
#endif
}

// Функция получения имени датчика
const char* getSensorName(int8_t num) {
    switch(num) {
        case -1: return "откл";
        case 0: return "давл";
        case 1: return "пар";
        case 2: return "царга";
        case 3: return "куб";
        case 4: return "вода";
        default: return "---";
    }
}

// Функция получения данных датчиков в формате JSON
String getSensorDataJSON() {
    DynamicJsonDocument doc(512);
    JsonArray temps = doc.createNestedArray("temps");
    
    for (int i = 0; i < 8; i++) {
        if (ntcEn[i]) temps.add(Temp[i]);
        else temps.add(static_cast<float>(NAN));
    }
    
    doc["p0"] = Pressure_enable[0] ? Temp[0] : static_cast<float>(NAN);
    doc["p1"] = Pressure_enable[1] ? pressure[1] : static_cast<float>(NAN);
    doc["p2"] = Pressure_enable[2] ? pressure[2] : static_cast<float>(NAN);
    doc["p3"] = Pressure_enable[3] ? pressure[3] : static_cast<float>(NAN);
    doc["alc"] = N_dPressureAlc ? Alc_T : static_cast<float>(NAN);
    doc["spk_on"] = spk_on != -1;
    doc["t_target"] = T_target;
    doc["rssi"] = WiFi.RSSI();
    doc["spk_sensor"] = getSensorName(spk_on);
    String json;
    serializeJson(doc, json);
    return json;
}

// Обработчик расчета кривой термистора
void handleCalculateCurve(AsyncWebServerRequest *request) {
    if (request->hasParam("R25", true)) setup_R25 = request->getParam("R25", true)->value().toFloat();
    if (request->hasParam("R100", true)) setup_R100 = request->getParam("R100", true)->value().toFloat();
    if (request->hasParam("T25", true)) setup_T25 = request->getParam("T25", true)->value().toFloat();
    if (request->hasParam("T100", true)) setup_T100 = request->getParam("T100", true)->value().toFloat();
    if (request->hasParam("B25", true)) setup_B25 = request->getParam("B25", true)->value().toFloat();
    if (request->hasParam("U33", true)) setup_U33 = request->getParam("U33", true)->value().toFloat();
    if (request->hasParam("Uref", true)) setup_Uref = request->getParam("Uref", true)->value().toFloat();
    if (request->hasParam("R62", true)) setup_R62 = request->getParam("R62", true)->value().toFloat();
    if (request->hasParam("R10", true)) setup_R10 = request->getParam("R10", true)->value().toFloat();

    m_adc_text = "";
    for (int i = -25; i <= 125; i++) {
        float t = i;
        float Rt = setup_R10 * 1000 * exp((1/(t+273.15)-1/(setup_T25+273.15))*setup_B25);
        float Rp = 1/(1/Rt + 1/(setup_R10*1000));
        uint16_t ADS = round(((setup_U33/(setup_R62*1000+Rp))*Rp)/setup_Uref * 32768);
        
        if (i + 25 >= 0 && i + 25 < 151) {
            m_adc[i + 25] = ADS;
        }
        
        if (i > -25) m_adc_text += ", ";
        m_adc_text += String(ADS);
    }
    
    request->send(200, "text/plain", m_adc_text);
}

// Сохранение настроек термистора в EEPROM
void handleSaveNTCToEEPROM(AsyncWebServerRequest *request) {
    EEPROM.begin(EEPROM_SIZE);
    EEPROM.put(m_adc_EAdr, m_adc);
    EEPROM.put(R25_EAdr, setup_R25);
    EEPROM.put(R100_EAdr, setup_R100);
    EEPROM.put(B25_EAdr, setup_B25);
    EEPROM.put(U33_EAdr, setup_U33);
    EEPROM.put(Uref_EAdr, setup_Uref);
    EEPROM.put(R62_EAdr, setup_R62);
    EEPROM.put(R10_EAdr, setup_R10);
    EEPROM.commit();
    EEPROM.end();
    
    request->send(200, "text/plain", "Сохранено в EEPROM успешно");
}

// Экспорт текстовой характеристики термистора
void handleExportNTCText(AsyncWebServerRequest *request) {
    AsyncWebServerResponse *response = request->beginResponse(200, "text/plain", m_adc_text);
    response->addHeader("Content-Disposition", "attachment; filename=ntc_curve.txt");
    request->send(response);
}

// Импорт текстовой характеристики термистора
void handleImportNTCText(AsyncWebServerRequest *request) {
    if (request->hasParam("plain", true)) {
        String text = request->getParam("plain", true)->value();
        text.replace("\n", "");
        text.replace("\r", "");
        
        int index = 0;
        int startPos = 0;
        int endPos = text.indexOf(',');
        
        while (endPos != -1 && index < 151) {
            String numStr = text.substring(startPos, endPos);
            numStr.trim();
            m_adc[index++] = numStr.toInt();
            startPos = endPos + 1;
            endPos = text.indexOf(',', startPos);
        }
        
        if (index < 151 && startPos < text.length()) {
            String numStr = text.substring(startPos);
            numStr.trim();
            m_adc[index] = numStr.toInt();
        }
        
        m_adc_text = text;
        request->send(200, "text/plain", "Данные успешно импортированы");
    } else {
        request->send(400, "text/plain", "Ошибка: отсутствуют данные");
    }
}

// Получение текущих температур
void handleGetTemps(AsyncWebServerRequest *request) {
    String temps = "";
    temps += "Т пара: " + String(Temp[1], 2) + "°C<br>";
    temps += "Т царги: " + String(Temp[2], 2) + "°C<br>"; 
    temps += "Т куба: " + String(Temp[3], 2) + "°C<br>";
    temps += "Т вода: " + String(Temp[4], 2) + "°C<br>";
    temps += "Т тса: " + String(Temp[5], 2) + "°C";
    request->send(200, "text/html", temps);
}