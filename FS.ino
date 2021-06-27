const char *http_username = "admin";
const char *http_password = "admin";

String get_sys_info();

void onWsEvent(AsyncWebSocket *server, AsyncWebSocketClient *client, AwsEventType type, void *arg, uint8_t *data, size_t len) {
  if (type == WS_EVT_CONNECT) {
    Serial.printf("ws[%s][%u] connect\n", server->url(), client->id());
    client->printf("Hello Client %u :)", client->id());
    client->ping();
  } else if (type == WS_EVT_DISCONNECT) {
    Serial.printf("ws[%s][%u] disconnect\n", server->url(), client->id());
  } else if (type == WS_EVT_ERROR) {
    Serial.printf("ws[%s][%u] error(%u): %s\n", server->url(), client->id(), *((uint16_t *)arg), (char *)data);
  } else if (type == WS_EVT_PONG) {
    Serial.printf("ws[%s][%u] pong[%u]: %s\n", server->url(), client->id(), len, (len) ? (char *)data : "");
  } else if (type == WS_EVT_DATA) {
    AwsFrameInfo *info = (AwsFrameInfo *)arg;
    String msg = "";
    if (info->final && info->index == 0 && info->len == len) {
      //the whole message is in a single frame and we got all of it's data
      Serial.printf("ws[%s][%u] %s-message[%llu]: ", server->url(), client->id(), (info->opcode == WS_TEXT) ? "text" : "binary", info->len);

      if (info->opcode == WS_TEXT) {
        for (size_t i = 0; i < info->len; i++) {
          msg += (char)data[i];
        }
      } else {
        char buff[3];
        for (size_t i = 0; i < info->len; i++) {
          sprintf(buff, "%02x ", (uint8_t)data[i]);
          msg += buff;
        }
      }
      Serial.printf("%s\n", msg.c_str());

      if (info->opcode == WS_TEXT)
        client->text("I got your text message");
      else
        client->binary("I got your binary message");
    } else {
      //message is comprised of multiple frames or the frame is split into multiple packets
      if (info->index == 0) {
        if (info->num == 0)
          Serial.printf("ws[%s][%u] %s-message start\n", server->url(), client->id(), (info->message_opcode == WS_TEXT) ? "text" : "binary");
        Serial.printf("ws[%s][%u] frame[%u] start[%llu]\n", server->url(), client->id(), info->num, info->len);
      }

      Serial.printf("ws[%s][%u] frame[%u] %s[%llu - %llu]: ", server->url(), client->id(), info->num, (info->message_opcode == WS_TEXT) ? "text" : "binary", info->index, info->index + len);

      if (info->opcode == WS_TEXT) {
        for (size_t i = 0; i < len; i++) {
          msg += (char)data[i];
        }
      } else {
        char buff[3];
        for (size_t i = 0; i < len; i++) {
          sprintf(buff, "%02x ", (uint8_t)data[i]);
          msg += buff;
        }
      }
      Serial.printf("%s\n", msg.c_str());

      if ((info->index + len) == info->len) {
        Serial.printf("ws[%s][%u] frame[%u] end[%llu]\n", server->url(), client->id(), info->num, info->len);
        if (info->final) {
          Serial.printf("ws[%s][%u] %s-message end\n", server->url(), client->id(), (info->message_opcode == WS_TEXT) ? "text" : "binary");
          if (info->message_opcode == WS_TEXT)
            client->text("I got your text message");
          else
            client->binary("I got your binary message");
        }
      }
    }
  }
}


//format bytes
String formatBytes(size_t bytes) {
  if (bytes < 1024) {
    return String(bytes) + "B";
  } else if (bytes < (1024 * 1024)) {
    return String(bytes / 1024.0) + "KB";
  } else if (bytes < (1024 * 1024 * 1024)) {
    return String(bytes / 1024.0 / 1024.0) + "MB";
  } else {
    return String(bytes / 1024.0 / 1024.0 / 1024.0) + "GB";
  }
}


// Инициализация FFS
void FS_init(void) {
  SPIFFS.begin();
  {
    File dir = SPIFFS.open("/");
    while (dir.openNextFile()) {
      String fileName = dir.name();
      //size_t fileSize = dir.size();
    }
  }

  ws.onEvent(onWsEvent);
  server.addHandler(&ws);

  events.onConnect([](AsyncEventSourceClient * client) {
    client->send("hello!", NULL, millis(), 1000);
  });
  server.addHandler(&events);

  server.addHandler(new SPIFFSEditor(SPIFFS, http_username, http_password));

  server.on("/heap", HTTP_GET, [](AsyncWebServerRequest * request) {
    request->send(200, "text/plain", get_sys_info());
  });

  //server.serveStatic("/", SPIFFS, "/").setDefaultFile("index.htm");

  server.onNotFound([](AsyncWebServerRequest * request) {
    Serial.printf("NOT_FOUND: ");
    if (request->method() == HTTP_GET)
      Serial.printf("GET");
    else if (request->method() == HTTP_POST)
      Serial.printf("POST");
    else if (request->method() == HTTP_DELETE)
      Serial.printf("DELETE");
    else if (request->method() == HTTP_PUT)
      Serial.printf("PUT");
    else if (request->method() == HTTP_PATCH)
      Serial.printf("PATCH");
    else if (request->method() == HTTP_HEAD)
      Serial.printf("HEAD");
    else if (request->method() == HTTP_OPTIONS)
      Serial.printf("OPTIONS");
    else
      Serial.printf("UNKNOWN");
    Serial.printf(" http://%s%s\n", request->host().c_str(), request->url().c_str());

    if (request->contentLength()) {
      Serial.printf("_CONTENT_TYPE: %s\n", request->contentType().c_str());
      Serial.printf("_CONTENT_LENGTH: %u\n", request->contentLength());
    }

    int headers = request->headers();
    int i;
    for (i = 0; i < headers; i++) {
      AsyncWebHeader *h = request->getHeader(i);
      Serial.printf("_HEADER[%s]: %s\n", h->name().c_str(), h->value().c_str());
    }

    int params = request->params();
    for (i = 0; i < params; i++) {
      AsyncWebParameter *p = request->getParam(i);
      if (p->isFile()) {
        Serial.printf("_FILE[%s]: %s, size: %u\n", p->name().c_str(), p->value().c_str(), p->size());
      } else if (p->isPost()) {
        Serial.printf("_POST[%s]: %s\n", p->name().c_str(), p->value().c_str());
      } else {
        Serial.printf("_GET[%s]: %s\n", p->name().c_str(), p->value().c_str());
      }
    }

    request->send(404);
  });
  server.onFileUpload([](AsyncWebServerRequest * request, const String & filename, size_t index, uint8_t *data, size_t len, bool final) {
    if (!index)
      Serial.printf("UploadStart: %s\n", filename.c_str());
    Serial.printf("%s", (const char *)data);
    if (final)
      Serial.printf("UploadEnd: %s (%u)\n", filename.c_str(), index + len);
  });
  server.onRequestBody([](AsyncWebServerRequest * request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!index)
      Serial.printf("BodyStart: %u\n", total);
    Serial.printf("%s", (const char *)data);
    if (index + len == total)
      Serial.printf("BodyEnd: %u\n", total);
  });
}

bool exists(String path) {
  static bool yes;
  File file = SPIFFS.open(path, "r");
  if (!file.isDirectory()) {
    yes = true;
  } else {
    yes = false;
  }
  file.close();
  return yes;
}

void create_data() {
  //Удаляем старый файл с архивным логом
  if (SPIFFS.exists("/data_old.csv")) {
    SPIFFS.remove("/data_old.csv");
  }
  //Переименовываем файл с логом в архивный (на всякий случай)
  if (SPIFFS.exists("/data.csv")) {
    SPIFFS.rename("/data.csv", "/data_old.csv");
  }
  File fileToWrite = SPIFFS.open("/data.csv", FILE_WRITE);
  String str = "Date,Steam,Pipe,Water,Tank,Pressure";
#ifdef WRITE_PROGNUM_IN_LOG
  str += ",ProgNum";
#endif
  fileToWrite.println(str);
  fileToWrite.close();
  fileToAppend = SPIFFS.open("/data.csv", FILE_APPEND);
  SteamSensor.PrevTemp = 0;
  PipeSensor.PrevTemp = 0;
  WaterSensor.PrevTemp = 0;
  TankSensor.PrevTemp = 0;
  bme_prev_pressure = 0;
}

String IRAM_ATTR append_data() {
  bool w;
  w = false;

  //Если значения лога совпадают с предыдущим - в файл писать не будем
  if (SteamSensor.avgTemp != SSPrevTemp) {
    SSPrevTemp = SteamSensor.avgTemp;
    w = true;
  } else if (PipeSensor.avgTemp != PSPrevTemp) {
    PSPrevTemp = PipeSensor.avgTemp;
    w = true;
  } else if (WaterSensor.avgTemp != WSPrevTemp) {
    WSPrevTemp = WaterSensor.avgTemp;
    w = true;
  } else if (TankSensor.avgTemp != TSPrevTemp) {
    TSPrevTemp = TankSensor.avgTemp;
    w = true;
  } else if (bme_prev_pressure != bme_pressure) {
    bme_prev_pressure = bme_pressure;
    w = true;
  } else if (prev_ProgramNum != ProgramNum) {
    prev_ProgramNum = ProgramNum;
    w = true;
  }

  if (w) {
    String str;
    str = Crt + ",";
    str += format_float(SteamSensor.avgTemp, 3);
    str += ",";
    str += format_float(PipeSensor.avgTemp, 3);
    str += ",";
    str += format_float(WaterSensor.avgTemp, 3);
    str += ",";
    str += format_float(TankSensor.avgTemp, 3);
    str += ",";
    str += format_float(bme_pressure, 2);

#ifdef WRITE_PROGNUM_IN_LOG
    str += ",";
    str += ProgramNum + 1;
#endif
    fileToAppend.println(str);
    return str;
  }
  return "";
}

String get_sys_info() {
  //Получаем системные параметры - размер свободного места, etc
  uint32_t ub = SPIFFS.usedBytes();
  uint32_t tb = SPIFFS.totalBytes();
  String result_st = "totalBytes = " + (String)tb + "; usedBytes = ";
  vTaskDelay(5);
  result_st += (String)ub + "; Free Heap = " + (String)ESP.getFreeHeap();
  if (tb - ub < 400) {
    //Кончилось место, удалим старый файл. Надо было сохранять раньше
    if (SPIFFS.exists("/data_old.csv")) {
      SPIFFS.remove("/data_old.csv");
    }
  }
  //Если используется Blynk - пишем оператору
  if (tb - ub < 200) {
    Msg = "Memory is full!";
#ifdef SAMOVAR_USE_BLYNK
    //Кончилось место, пишем оператору
    Blynk.notify("Alarm! {DEVICE_NAME} Memory is full!");
#endif
  }
  vTaskDelay(5);
  result_st += "; ESP32 t = " + (String)((temprature_sens_read() - 32) / 1.8) + "; BME t = " + (String)bme_temp;
  vTaskDelay(5);
  return result_st;
}

void save_profile() {
  File file = SPIFFS.open(get_prf_name(), FILE_WRITE);
  file.write((byte *)&SamSetup, sizeof(SamSetup));
  file.close();
  EEPROM.put(0, SamSetup);
  EEPROM.commit();
}

void load_profile() {
  String f;
  f = get_prf_name();
  if (SPIFFS.exists(f)) {
    File file = SPIFFS.open(f, FILE_READ);
    file.setTimeout(0);
    file.read((byte *)&SamSetup, sizeof(SamSetup));
    file.close();
  } else
    save_profile();
  EEPROM.put(0, SamSetup);
  EEPROM.commit();
  read_config();
}

String get_prf_name() {
  String fl;
  if (Samovar_CR_Mode == SAMOVAR_BEER_MODE) {
    fl = "beer.prf";
  } else if (Samovar_CR_Mode == SAMOVAR_DISTILLATION_MODE) {
    fl = "dist.prf";
  } else {
    fl = "rectificat.prf";
  }
  return fl;
}
