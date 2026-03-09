#ifndef __SAMOVAR_UI_WEB_SERVER_INIT_H__
#define __SAMOVAR_UI_WEB_SERVER_INIT_H__

void WebServerInit(void) {

  FS_init();  // Включаем работу с файловой системой

//  HeaderFreeMiddleware spiffsHeaderFree;
//  spiffsHeaderFree.keep("If-Modified-Since");
//  spiffsHeaderFree.keep("Host");
//  // Add any other headers you need to keep
//
//  // Then either add it globally
//  server.addMiddleware(&spiffsHeaderFree);


  server.on("/", HTTP_GET | HTTP_POST, [](AsyncWebServerRequest* request) {
    // Если нет подключения к WiFi сети - показываем страницу настройки WiFi
    // Это сработает когда Самовар в режиме AP (точка доступа)
    if (WiFi.status() != WL_CONNECTED) {
      // Отправляем wifi.htm из памяти (gzip архив)
      handleWifiHtmFromMemory(request);
    } else {
      // Иначе - обычный интерфейс Самовара (перенаправление на index.htm)
      request->redirect("/index.htm");
    }
  });

  server.on("/style.css", HTTP_GET, [](AsyncWebServerRequest *request) {
    handleFileWithGzip(request, "/style.css", "text/css", "max-age=5000");
  });
  //server.serveStatic("/style.css", SPIFFS, "/style.css").setCacheControl("max-age=5000");
  server.on("/minus.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/minus.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=604800");
    request->send(response);
  });
  server.on("/plus.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/plus.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=614800");
    request->send(response);
  });
  server.on("/favicon.ico", HTTP_GET, [](AsyncWebServerRequest *request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/favicon.ico", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=624800");
    request->send(response);
  });

  server.on("/Red_light.gif", HTTP_GET, [](AsyncWebServerRequest *request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/Red_light.gif", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=634800");
    request->send(response);
  });
  server.on("/Green.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/Green.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=644800");
    request->send(response);
  });

  //  server.serveStatic("/style.css", SPIFFS, "/style.css");
  //  server.serveStatic("/Red_light.gif", SPIFFS, "/Red_light.gif");
  //  server.serveStatic("/Green.png", SPIFFS, "/Green.png");
  //  server.serveStatic("/minus.png", SPIFFS, "/minus.png");
  //  server.serveStatic("/plus.png", SPIFFS, "/plus.png");
  //  server.serveStatic("/favicon.ico", SPIFFS, "/favicon.ico");

  server.serveStatic("/alarm.mp3", SPIFFS, "/alarm.mp3");
  server.serveStatic("/resetreason.css", SPIFFS, "/resetreason.css").setCacheControl("max-age=1");
  server.serveStatic("/data_old.csv", SPIFFS, "/data_old.csv").setCacheControl("max-age=1");
  server.serveStatic("/prg.csv", SPIFFS, "/prg.csv").setCacheControl("max-age=1");
  server.serveStatic("/state.csv", SPIFFS, "/state.csv").setCacheControl("max-age=1");
  server.serveStatic("/program.htm", SPIFFS, "/program.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.serveStatic("/chart.htm", SPIFFS, "/chart.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.serveStatic("/calibrate.htm", SPIFFS, "/calibrate.htm").setTemplateProcessor(calibrateKeyProcessor).setCacheControl("max-age=800");
  server.serveStatic("/manual.htm", SPIFFS, "/manual.htm").setCacheControl("max-age=800");
  server.serveStatic("/pong.htm", SPIFFS, "/alarm.mp3");
  server.serveStatic("/program_fruit.txt", SPIFFS, "/program_fruit.txt").setCacheControl("max-age=1");
  server.serveStatic("/program_grain.txt", SPIFFS, "/program_grain.txt").setCacheControl("max-age=1");
  server.serveStatic("/program_shugar.txt", SPIFFS, "/program_shugar.txt").setCacheControl("max-age=1");
  server.serveStatic("/brewxml.htm", SPIFFS, "/brewxml.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.serveStatic("/test.txt", SPIFFS, "/test.txt").setTemplateProcessor(indexKeyProcessor);
  server.serveStatic("/setup.htm", SPIFFS, "/setup.htm").setTemplateProcessor(setupKeyProcessor).setCacheControl("max-age=1");
  // Обработчик для /wifi.htm - отдаем из памяти (gzip архив)
  server.on("/wifi.htm", HTTP_GET, [](AsyncWebServerRequest* request) {
    handleWifiHtmFromMemory(request);
  });

  server.on("/wifi", HTTP_GET, [](AsyncWebServerRequest* request) {
    request->redirect("/wifi.htm");
  });

  server.on("/wifi/save", HTTP_POST, [](AsyncWebServerRequest* request) {
    if (!request) return;
    if (!request->hasArg("ssid")) {
      request->send(400, "text/plain", "Missing ssid");
      return;
    }

    String ssid = request->arg("ssid");
    String pass = request->hasArg("pass") ? request->arg("pass") : "";
    ssid.trim();

    if (ssid.length() == 0) {
      request->send(400, "text/plain", "Empty ssid");
      return;
    }

    save_wifi_credentials(ssid.c_str(), pass.c_str());
    request->send(200, "text/plain", "OK. Rebooting...");
    delay(200);
    ESP.restart();
  });

  server.on("/wifi/clear", HTTP_POST, [](AsyncWebServerRequest* request) {
    clear_wifi_credentials();
    request->send(200, "text/plain", "OK. Rebooting...");
    delay(200);
    ESP.restart();
  });
  //server.serveStatic("/edit", SPIFFS, "/edit.htm");
  // SPIFFSEditor уже обрабатывает /edit с поддержкой gzip в FS.ino

  //#ifdef USE_LUA
  //  server.serveStatic("/btn_button1.lua", SPIFFS, "/btn_button1.lua");
  //  server.serveStatic("/btn_button2.lua", SPIFFS, "/btn_button2.lua");
  //  server.serveStatic("/btn_button3.lua", SPIFFS, "/btn_button3.lua");
  //  server.serveStatic("/btn_button4.lua", SPIFFS, "/btn_button4.lua");
  //  server.serveStatic("/btn_button5.lua", SPIFFS, "/btn_button5.lua");
  //#endif

  change_samovar_mode();

  load_profile();



  server.on("/rrlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(SPIFFS, "/resetreason.css", String());
  });
  server.on("/data.csv", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (fileToAppend && fileToAppend.available())
      fileToAppend.flush();
    request->send(SPIFFS, "/data.csv", String());
  });
  server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_ajax_json(request);
  });
  server.on("/command", HTTP_GET, [](AsyncWebServerRequest *request) {
    web_command(request);
  });
  server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request) {
    web_program(request);
  });
  server.on("/ajax_col_params", HTTP_GET, [](AsyncWebServerRequest *request) {
    uint8_t mat = 2; // По умолчанию сахар
    if (request->hasParam("mat")) mat = request->getParam("mat")->value().toInt();

    ColumnResults res = calculate_column_etalon(mat);

    String json = "{";
    json += "\"floodPowerW\":" + String(res.floodPowerW, 0) + ",";
    json += "\"workingPowerW\":" + String(res.workingPowerW, 0) + ",";
    json += "\"maxFlowMlH\":" + String(res.maxFlowMlH, 0) + ",";
    json += "\"theoreticalPlates\":" + String(res.theoreticalPlates, 1) + ",";
    json += "\"headsFlowMlH\":" + String(res.headsFlowMlH, 0) + ",";
    json += "\"bodyFlowMinMlH\":" + String(res.bodyFlowMinMlH, 0) + ",";
    json += "\"bodyFlowMaxMlH\":" + String(res.bodyFlowMaxMlH, 0) + ",";
    json += "\"bodyEndFlowMlH\":" + String(res.bodyEndFlowMlH, 0) + ",";
    json += "\"tailsFlowMlH\":" + String(res.tailsFlowMlH, 0) + ",";
    json += "\"headsPowerW\":" + String(res.headsPowerW, 0) + ",";
    json += "\"bodyEndPowerW\":" + String(res.bodyEndPowerW, 0) + ",";
    json += "\"tailsPowerW\":" + String(res.tailsPowerW, 0);
    json += "}";
    request->send(200, "application/json", json);
  });
  server.on("/calibrate", HTTP_GET, [](AsyncWebServerRequest *request) {
    calibrate_command(request);
  });
  server.on("/i2cpump", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (use_I2C_dev != 2) {
      request->send(400, "text/plain", "I2C pump not available");
      return;
    }
    if (request->hasArg("stop")) {
      set_stepper_target(0, 0, 0);
      I2CPumpTargetSteps = 0;
      I2CPumpTargetMl = 0;
      I2CPumpCmdSpeed = 0;
      request->send(200, "text/plain", "OK");
      return;
    }
    float speedRate = request->hasArg("speed") ? request->arg("speed").toFloat() : 0.0f;
    float volumeMl = request->hasArg("volume") ? request->arg("volume").toFloat() : 0.0f;
    if (speedRate <= 0 || volumeMl <= 0) {
      request->send(400, "text/plain", "Invalid params");
      return;
    }
    uint16_t stepsPerMl = SamSetup.StepperStepMlI2C > 0 ? SamSetup.StepperStepMlI2C : I2C_STEPPER_STEP_ML_DEFAULT;
    uint32_t targetSteps = (uint32_t)(volumeMl * stepsPerMl);
    uint16_t speedSteps = (uint16_t)i2c_get_speed_from_rate(speedRate);
    I2CPumpCmdSpeed = speedSteps;
    I2CPumpTargetSteps = targetSteps;
    I2CPumpTargetMl = volumeMl;
    set_stepper_target(speedSteps, 0, targetSteps);
    request->send(200, "text/plain", "OK");
  });
  server.on("/getlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    get_data_log(request, "data.csv");
  });
  server.on("/getoldlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    get_data_log(request, "data_old.csv");
  });
#ifdef USE_LUA
  server.on("/lua", HTTP_GET, [](AsyncWebServerRequest *request) {
    start_lua_script();
    request->send(200, "text/html", "OK");
  });
#endif

  server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request) {
    //Serial.println("SAVE");
    handleSave(request);
  });

  server.onFileUpload([](AsyncWebServerRequest *request, const String &filename, size_t index, uint8_t *data, size_t len, bool final) {
    if (!index)
      Serial.printf("UploadStart: %s\n", filename.c_str());
    if (len) {
      Serial.write(data, len);
    }
    if (final)
      Serial.printf("UploadEnd: %s (%u)\n", filename.c_str(), index + len);
  });
  server.onRequestBody([](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!index)
      Serial.printf("BodyStart: %u\n", total);
    if (len) {
      Serial.write(data, len);
    }
    if (index + len == total)
      Serial.printf("BodyEnd: %u\n", total);
  });

  DefaultHeaders::Instance().addHeader("Access-Control-Allow-Origin", "*");  // CORS
  headerFilter.filter("If-Modified-Since");
  //  DefaultHeaders::Instance().addHeader("Cache-Control", "no-cache");
  //  DefaultHeaders::Instance().addHeader("Pragma", "no-cache");
  //  DefaultHeaders::Instance().addHeader("Expires", "Thu, 01 Jan 1970 00:00:00 UTC");
  //  DefaultHeaders::Instance().addHeader("Last-Modified", "Mon, 03 Jan 2050 00:00:00 UTC");

  // Автоматическая раздача всех файлов из SPIFFS
  server.serveStatic("/", SPIFFS, "/");

  server.begin();
#ifdef __SAMOVAR_DEBUG
  Serial.println("HTTP server started");
#endif

#ifndef NOT_USE_INTERFACE_UPDATE
  get_web_interface();
#endif
}

#endif
