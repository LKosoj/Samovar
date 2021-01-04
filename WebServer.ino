void  web_command(AsyncWebServerRequest *request);
void  handleSave(AsyncWebServerRequest *request);
void get_data_log(AsyncWebServerRequest *request);

void WebServerInit(void){

  FS_init();                                        // Включаем работу с файловой системой

  server.serveStatic("/favicon.ico", SPIFFS, "/favicon.ico");
  server.serveStatic("/chart.htm", SPIFFS, "/chart.htm");
  server.serveStatic("/data.csv", SPIFFS, "/data.csv");
  server.serveStatic("/calibrate.htm", SPIFFS, "/calibrate.htm").setTemplateProcessor(calibrateKeyProcessor);
  server.serveStatic("/manual.htm", SPIFFS, "/manual.htm");

  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(SPIFFS, "/index.htm", String(), false);
  });
  server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(SPIFFS, "/index.htm", String(), false);
  });

  server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest *request) {
    //TempStr = temp;
    getjson();
    request->send(200, "text/html", jsonstr);
#ifdef __SAMOVAR_DEBUG
    //Serial.println("  web jsonstr = " + jsonstr);
#endif
  });
  server.on("/command", HTTP_GET, [](AsyncWebServerRequest *request){
    web_command(request);
  });
  server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request){
    web_program(request);
  });
  server.on("/calibrate", HTTP_GET, [](AsyncWebServerRequest *request){
    calibrate_command(request);
  });
  server.on("/getlog", HTTP_GET, [](AsyncWebServerRequest *request){
    get_data_log(request);
  });

  server.serveStatic("/setup.htm", SPIFFS, "/setup.htm").setTemplateProcessor(setupKeyProcessor);
  
  server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request){
     //Serial.println("SAVE");
        handleSave(request);
  });

  server.onFileUpload([](AsyncWebServerRequest *request, const String& filename, size_t index, uint8_t *data, size_t len, bool final){
    if(!index)
      Serial.printf("UploadStart: %s\n", filename.c_str());
    Serial.printf("%s", (const char*)data);
    if(final)
      Serial.printf("UploadEnd: %s (%u)\n", filename.c_str(), index+len);
  });
  server.onRequestBody([](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total){
    if(!index)
      Serial.printf("BodyStart: %u\n", total);
    Serial.printf("%s", (const char*)data);
    if(index + len == total)
      Serial.printf("BodyEnd: %u\n", total);
  });

  
  server.begin();
#ifdef __SAMOVAR_DEBUG
  Serial.println("HTTP server started");
#endif
}

String setupKeyProcessor(const String& var)
{
  if (var == "DeltaSteamTemp") return (String)SamSetup.DeltaSteamTemp;
  else if (var == "DeltaPipeTemp") return (String)SamSetup.DeltaPipeTemp;
  else if (var == "DeltaWaterTemp") return (String)SamSetup.DeltaWaterTemp;
  else if (var == "DeltaTankTemp") return (String)SamSetup.DeltaTankTemp;
  else if (var == "SetSteamTemp") return (String)SamSetup.SetSteamTemp;
  else if (var == "SetPipeTemp") return (String)SamSetup.SetPipeTemp;
  else if (var == "SetWaterTemp") return (String)SamSetup.SetWaterTemp;
  else if (var == "SetTankTemp") return (String)SamSetup.SetTankTemp;
  else if (var == "StepperStepMl") return (String)SamSetup.StepperStepMl;
  else if (var == "WProgram") return get_program(CAPACITY_NUM * 2);
  
  return String();
}

String calibrateKeyProcessor(const String& var)
{
  static char outstr[15];
  if (var == "StepperStep") return (String)STEPPER_MAX_SPEED;
  else if (var == "StepperStepMl") return (String)(SamSetup.StepperStepMl * 100);
  
  return String();
}

void  handleSave(AsyncWebServerRequest *request){
/*
  int params = request->params();
  for(int i=0;i<params;i++){
    AsyncWebParameter* p = request->getParam(i);
    Serial.print(p->name().c_str());
    Serial.print("=");
    Serial.println(p->value().c_str());
  }
//return;
*/
  if (request->hasArg("DeltaSteamTemp")) {
    SamSetup.DeltaSteamTemp = request->arg("DeltaSteamTemp").toFloat();
  }
  if (request->hasArg("DeltaPipeTemp")) {
    SamSetup.DeltaPipeTemp = request->arg("DeltaPipeTemp").toFloat();
  }
  if (request->hasArg("DeltaWaterTemp")) {
    SamSetup.DeltaWaterTemp = request->arg("DeltaWaterTemp").toFloat();
  }
  if (request->hasArg("DeltaTankTemp")) {
    SamSetup.DeltaTankTemp = request->arg("DeltaTankTemp").toFloat();
  }
  if (request->hasArg("SetSteamTemp")) {
    SamSetup.SetSteamTemp = request->arg("SetSteamTemp").toFloat();
  }
  if (request->hasArg("SetPipeTemp")) {
    SamSetup.SetPipeTemp = request->arg("SetPipeTemp").toFloat();
  }
  if (request->hasArg("SetWaterTemp")) {
    SamSetup.SetWaterTemp = request->arg("SetWaterTemp").toFloat();
  }
  if (request->hasArg("SetTankTemp")) {
    SamSetup.SetTankTemp = request->arg("SetTankTemp").toFloat();
  }
  if (request->hasArg("StepperStepMl")) {
    SamSetup.StepperStepMl = request->arg("StepperStepMl").toInt();
  }
  if (request->hasArg("stepperstepml")) {
    SamSetup.StepperStepMl = request->arg("stepperstepml").toInt()/100;
  }
  if (request->hasArg("WProgram")) {
    set_program(request->arg("WProgram"));
  }
  
  // Сохраняем изменения в память.
  EEPROM.put(0, SamSetup);
  EEPROM.commit();
  read_config();

  AsyncWebServerResponse *response = request->beginResponse(301);
  response->addHeader("Location", "/");
  response->addHeader("Cache-Control", "no-cache");
  request->send(response);
}

void  web_command(AsyncWebServerRequest *request){

int params = request->params();
/*  
  for(int i=0;i<params;i++){
    AsyncWebParameter* p = request->getParam(i);
    Serial.print(p->name().c_str());
    Serial.print("=");
    Serial.println(p->value().c_str());
  }
//return;
*/
  if (request->params() == 1) {
   if (request->hasArg("start") && PowerOn) {
    sam_command_sync = SAMOVAR_START;
   }
   if (request->hasArg("power")) {
    sam_command_sync = SAMOVAR_POWER;
   }
   if (request->hasArg("reset")) {
    sam_command_sync = SAMOVAR_RESET;
   }
   if (request->hasArg("voltage")) {
     set_current_power(request->arg("voltage").toFloat());
   }
   if (request->hasArg("pause")) {
    if (PauseOn) {
      sam_command_sync = SAMOVAR_CONTINUE;
    } else {
      sam_command_sync = SAMOVAR_PAUSE;
    }
   }
  }
    request->send(200,"text/plain","OK");
}
void  web_program(AsyncWebServerRequest *request){

int params = request->params();
    if (request->hasArg("WProgram")) {
      set_program(request->arg("WProgram"));
      request->send(200,"text/plain",get_program(CAPACITY_NUM * 2));
    }
}

void  calibrate_command(AsyncWebServerRequest *request){
  if (request->params() >= 1) {
   if (request->hasArg("stpstep")) {
    CurrrentStepperSpeed = request->arg("stpstep").toInt();
   }
   if (request->hasArg("start") && startval == 0) {
    sam_command_sync = CALIBRATE_START;
   }
   if (request->hasArg("finish") && startval == 100) {
    sam_command_sync = CALIBRATE_STOP;
   }
  }
  vTaskDelay(10);
  if (sam_command_sync != SAMOVAR_NONE){
    int s = round((float)stepper.getCurrent() / 100) * 100;
    request->send(200, "text/plain", (String)s);
  } else request->send(200, "text/plain", "OK");
}

void get_data_log(AsyncWebServerRequest *request){
  AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/data.csv", String(), true);
  response->addHeader("Content-Type", "application/octet-stream");
  response->addHeader("Content-Description", "File Transfer");
  //response->addHeader("Content-Disposition", "attachment; filename='data.csv'");
  response->addHeader("Pragma", "public");
  response->addHeader("Cache-Control", "no-cache");
  request->send(response);
}
