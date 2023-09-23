#include <asyncHTTPrequest.h>
#include <ESPping.h>

void web_command(AsyncWebServerRequest *request);
void handleSave(AsyncWebServerRequest *request);
void get_data_log(AsyncWebServerRequest *request);
void get_old_data_log(AsyncWebServerRequest *request);
String calibrateKeyProcessor(const String &var);
String indexKeyProcessor(const String &var);
void web_program(AsyncWebServerRequest *request);
void calibrate_command(AsyncWebServerRequest *request);
String setupKeyProcessor(const String &var);
String get_DSAddressList(String Address);
void set_pump_speed(float pumpspeed, bool continue_process);
void start_self_test(void);
void stop_self_test(void);
String get_web_file(String fn, get_web_type type);
void get_web_interface();

#ifdef USE_LUA
void start_lua_script();
void load_lua_script();
String get_lua_script_list();
void run_lua_script(String fn);
#endif

void change_samovar_mode() {
  if (Samovar_Mode == SAMOVAR_BEER_MODE) {
    server.on("/", HTTP_GET, [](AsyncWebServerRequest * request) {
      request->send(SPIFFS, "/beer.htm", String(), false, indexKeyProcessor);
    });
    server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest * request) {
      request->send(SPIFFS, "/beer.htm", String(), false, indexKeyProcessor);
    });
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    server.on("/", HTTP_GET, [](AsyncWebServerRequest * request) {
      request->send(SPIFFS, "/distiller.htm", String(), false, indexKeyProcessor);
    });
    server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest * request) {
      request->send(SPIFFS, "/distiller.htm", String(), false, indexKeyProcessor);
    });
  } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
    server.on("/", HTTP_GET, [](AsyncWebServerRequest * request) {
      request->send(SPIFFS, "/bk.htm", String(), false, indexKeyProcessor);
    });
    server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest * request) {
      request->send(SPIFFS, "/bk.htm", String(), false, indexKeyProcessor);
    });
  } else {
    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
    server.on("/", HTTP_GET, [](AsyncWebServerRequest * request) {
      request->send(SPIFFS, "/index.htm", String(), false, indexKeyProcessor);
    });
    server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest * request) {
      request->send(SPIFFS, "/index.htm", String(), false, indexKeyProcessor);
    });
  }
  Samovar_CR_Mode = Samovar_Mode;
}

void WebServerInit(void) {

  FS_init();  // Включаем работу с файловой системой

  server.on("/style.css", HTTP_GET, [](AsyncWebServerRequest * request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/style.css");
    response->addHeader("Cache-Control", "max-age=5000");
    request->send(response);
  });
  server.on("/minus.png", HTTP_GET, [](AsyncWebServerRequest * request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/minus.png");
    response->addHeader("Cache-Control", "max-age=604800");
    request->send(response);
  });
  server.on("/plus.png", HTTP_GET, [](AsyncWebServerRequest * request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/plus.png");
    response->addHeader("Cache-Control", "max-age=614800");
    request->send(response);
  });
  server.on("/favicon.ico", HTTP_GET, [](AsyncWebServerRequest * request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/favicon.ico");
    response->addHeader("Cache-Control", "max-age=624800");
    request->send(response);
  });

  server.on("/Red_light.gif", HTTP_GET, [](AsyncWebServerRequest * request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/Red_light.gif");
    response->addHeader("Cache-Control", "max-age=634800");
    request->send(response);
  });
  server.on("/Green.png", HTTP_GET, [](AsyncWebServerRequest * request) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/Green.png");
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
  server.serveStatic("/resetreason.css", SPIFFS, "/resetreason.css");
  server.serveStatic("/data_old.csv", SPIFFS, "/data_old.csv");
  server.serveStatic("/prg.csv", SPIFFS, "/prg.csv");
  server.serveStatic("/state.csv", SPIFFS, "/state.csv");
  server.serveStatic("/program.htm", SPIFFS, "/program.htm").setTemplateProcessor(indexKeyProcessor);
  server.serveStatic("/chart.htm", SPIFFS, "/chart.htm").setTemplateProcessor(indexKeyProcessor);
  server.serveStatic("/calibrate.htm", SPIFFS, "/calibrate.htm").setTemplateProcessor(calibrateKeyProcessor);
  server.serveStatic("/manual.htm", SPIFFS, "/manual.htm");
  server.serveStatic("/pong.htm", SPIFFS, "/alarm.mp3");
  server.serveStatic("/program_fruit.txt", SPIFFS, "/program_fruit.txt");
  server.serveStatic("/program_grain.txt", SPIFFS, "/program_grain.txt");
  server.serveStatic("/program_shugar.txt", SPIFFS, "/program_shugar.txt");
  server.serveStatic("/brewxml.htm", SPIFFS, "/brewxml.htm").setTemplateProcessor(indexKeyProcessor);
  server.serveStatic("/test.txt", SPIFFS, "/test.txt").setTemplateProcessor(indexKeyProcessor);
  server.serveStatic("/setup.htm", SPIFFS, "/setup.htm").setTemplateProcessor(setupKeyProcessor);

#ifdef USE_LUA
  server.serveStatic("/btn_button1.lua", SPIFFS, "/btn_button1.lua");
  server.serveStatic("/btn_button2.lua", SPIFFS, "/btn_button2.lua");
  server.serveStatic("/btn_button3.lua", SPIFFS, "/btn_button3.lua");
  server.serveStatic("/btn_button4.lua", SPIFFS, "/btn_button4.lua");
  server.serveStatic("/btn_button5.lua", SPIFFS, "/btn_button5.lua");
#endif

  change_samovar_mode();

  load_profile();

  server.on("/rrlog", HTTP_GET, [](AsyncWebServerRequest * request) {
    request->send(SPIFFS, "/resetreason.css", String());
  });
  server.on("/data.csv", HTTP_GET, [](AsyncWebServerRequest * request) {
    if (fileToAppend)
      fileToAppend.flush();
    request->send(SPIFFS, "/data.csv", String());
  });
  server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest * request) {
    //TempStr = temp;
    getjson();
    request->send(200, "text/html", jsonstr);
  });
  server.on("/command", HTTP_GET, [](AsyncWebServerRequest * request) {
    web_command(request);
  });
  server.on("/program", HTTP_POST, [](AsyncWebServerRequest * request) {
    web_program(request);
  });
  server.on("/calibrate", HTTP_GET, [](AsyncWebServerRequest * request) {
    calibrate_command(request);
  });
  server.on("/getlog", HTTP_GET, [](AsyncWebServerRequest * request) {
    get_data_log(request);
  });
  server.on("/getoldlog", HTTP_GET, [](AsyncWebServerRequest * request) {
    get_old_data_log(request);
  });
#ifdef USE_LUA
  server.on("/lua", HTTP_GET, [](AsyncWebServerRequest * request) {
    start_lua_script();
    request->send(200, "text/html", "OK");
  });
#endif

  server.on("/save", HTTP_POST, [](AsyncWebServerRequest * request) {
    //Serial.println("SAVE");
    handleSave(request);
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

  DefaultHeaders::Instance().addHeader("Access-Control-Allow-Origin", "*");  // CORS
  server.begin();
#ifdef __SAMOVAR_DEBUG
  Serial.println("HTTP server started");
#endif

  get_web_interface();
}

String indexKeyProcessor(const String &var) {
  if (var == "SteamColor") return (String)SamSetup.SteamColor;
  else if (var == "v")
    return SAMOVAR_VERSION;
  else if (var == "PipeColor")
    return (String)SamSetup.PipeColor;
  else if (var == "WaterColor")
    return (String)SamSetup.WaterColor;
  else if (var == "TankColor")
    return (String)SamSetup.TankColor;
  else if (var == "ACPColor")
    return (String)SamSetup.ACPColor;
  else if (var == "SteamHide") {
    if (SteamSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "PipeHide") {
    if (PipeSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "WaterHide") {
    if (WaterSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "TankHide") {
    if (TankSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "PressureHide") {
    if (bme_pressure > 0) return "false";
    else return "true";
  } else if (var == "ProgNumHide") {
    if (ProgramNum > 0) return "false";
    else return "true";
  } else if (var == "WProgram") {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
    else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) return get_dist_program();
    else
      return get_program(CAPACITY_NUM * 2);
  } else if (var == "Descr") {
    return SessionDescription;
  } else if (var == "videourl")
    return (String)SamSetup.videourl;
  else if (var == "PWM_LV")
    return (String)(PWM_LOW_VALUE * 10);
  else if (var == "PWM_V")
    return (String)bk_pwm;
  else if (var == "pwr_unit")
    return PWR_TYPE;
#ifdef USE_LUA
  if (var == "btn_list")
    return get_lua_script_list();
#endif
  else if (var == "showvideo") {
    if ((String)SamSetup.videourl != "") return "inline";
    else
      return "none";
  };
  return "";
}

String setupKeyProcessor(const String &var) {
  static String s;
  s = "";
  if (var == "DeltaSteamTemp") {
    s = format_float(SamSetup.DeltaSteamTemp, 3);
    return s;
  } else if (var == "DeltaPipeTemp") {
    s = format_float(SamSetup.DeltaPipeTemp, 3);
    return s;
  } else if (var == "DeltaWaterTemp") {
    s = format_float(SamSetup.DeltaWaterTemp, 3);
    return s;
  } else if (var == "DeltaTankTemp") {
    s = format_float(SamSetup.DeltaTankTemp, 3);
    return s;
  } else if (var == "DeltaACPTemp") {
    s = format_float(SamSetup.DeltaACPTemp, 3);
    return s;
  } else if (var == "SetSteamTemp") {
    s = format_float(SamSetup.SetSteamTemp, 3);
    return s;
  } else if (var == "SetPipeTemp") {
    if (isnan(SamSetup.SetPipeTemp)) {
      SamSetup.SetPipeTemp = 0;
    }
    s = format_float(SamSetup.SetPipeTemp, 3);
    return s;
  } else if (var == "SetWaterTemp") {
    if (isnan(SamSetup.SetWaterTemp)) {
      SamSetup.SetWaterTemp = 0;
    }
    s = format_float(SamSetup.SetWaterTemp, 3);
    return s;
  } else if (var == "SetTankTemp") {
    if (isnan(SamSetup.SetTankTemp)) {
      SamSetup.SetTankTemp = 0;
    }
    s = format_float(SamSetup.SetTankTemp, 3);
    return s;
  } else if (var == "SetACPTemp") {
    if (isnan(SamSetup.SetACPTemp)) {
      SamSetup.SetACPTemp = 0;
    }
    s = format_float(SamSetup.SetACPTemp, 3);
    return s;
  } else if (var == "StepperStepMl") {
    s = SamSetup.StepperStepMl;
    return s;
  } else if (var == "WProgram") {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
    else
      return get_program(CAPACITY_NUM * 2);
  } else if (var == "Kp") {
    s = format_float(SamSetup.Kp, 3);
    return s;
  } else if (var == "Ki") {
    s = format_float(SamSetup.Ki, 3);
    return s;
  } else if (var == "Kd") {
    s = format_float(SamSetup.Kd, 3);
    return s;
  } else if (var == "StbVoltage") {
    s = SamSetup.StbVoltage;
    return s;
  } else if (var == "SteamDelay") {
    s = SamSetup.SteamDelay;
    return s;
  } else if (var == "PipeDelay") {
    s = SamSetup.PipeDelay;
    return s;
  } else if (var == "WaterDelay") {
    s = SamSetup.WaterDelay;
    return s;
  } else if (var == "TankDelay") {
    s = SamSetup.TankDelay;
    return s;
  } else if (var == "ACPDelay") {
    s = SamSetup.ACPDelay;
    return s;
  } else if (var == "TimeZone") {
    s = SamSetup.TimeZone;
    return s;
  } else if (var == "LogPeriod") {
    s = SamSetup.LogPeriod;
    return s;
  } else if (var == "HeaterR") {
    s = format_float(SamSetup.HeaterResistant, 3);
    return s;
  } else if (var == "videourl") {
    s = SamSetup.videourl;
    return s;
  } else if (var == "blynkauth") {
    s = SamSetup.blynkauth;
    return s;
  } else if (var == "BVolt") {
    s = SamSetup.BVolt;
    return s;
  } else if (var == "Checked") {
    if (SamSetup.UsePreccureCorrect) return "checked='true'";
    else
      return "";
  } else if (var == "UAPChecked") {
    if (SamSetup.useautopowerdown) return "checked='true'";
    else
      return "";
  } else if (var == "UASChecked") {
    if (SamSetup.useautospeed) return "checked='true'";
    else
      return "";
  } else if (var == "CPBuzz") {
    if (SamSetup.ChangeProgramBuzzer) return "checked='true'";
    else
      return "";
  } else if (var == "CUBuzz") {
    if (SamSetup.UseBuzzer) return "checked='true'";
    else
      return "";
  } else if (var == "UseWS") {
    if (SamSetup.UseWS) return "checked='true'";
    else
      return "";
  } else if (var == "UseST") {
    if (SamSetup.UseST) return "checked='true'";
    else
      return "";
  } else if (var == "ChckPwr") {
    if (SamSetup.CheckPower) return "checked='true'";
    else
      return "";
  } else if (var == "autospeed") {
    s = SamSetup.autospeed;
    return s;
  } else if (var == "DistTemp") {
    s = format_float(SamSetup.DistTemp, 3);
    return s;
  } else if (var == "SteamColor") {
    s = SamSetup.SteamColor;
    return s;
  } else if (var == "PipeColor") {
    s = SamSetup.PipeColor;
    return s;
  } else if (var == "WaterColor") {
    s = SamSetup.WaterColor;
    return s;
  } else if (var == "TankColor") {
    s = SamSetup.TankColor;
    return s;
  } else if (var == "ACPColor") {
    s = SamSetup.ACPColor;
    return s;
  } else if (var == "RECT" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_RECTIFICATION_MODE)
    return "selected";
  else if (var == "DIST" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_DISTILLATION_MODE)
    return "selected";
  else if (var == "BEER" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_BEER_MODE)
    return "selected";
  else if (var == "BK" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_BK_MODE)
    return "selected";
  else if (var == "SUVID" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_SUVID_MODE)
    return "selected";
  else if (var == "RAL" && !SamSetup.rele1)
    return "selected";
  else if (var == "RAH" && SamSetup.rele1)
    return "selected";
  else if (var == "RBL" && !SamSetup.rele2)
    return "selected";
  else if (var == "RBH" && SamSetup.rele2)
    return "selected";
  else if (var == "RCL" && !SamSetup.rele3)
    return "selected";
  else if (var == "RCH" && SamSetup.rele3)
    return "selected";
  else if (var == "RDL" && !SamSetup.rele4)
    return "selected";
  else if (var == "RDH" && SamSetup.rele4)
    return "selected";
  else if (var == "SteamAddr")
    return get_DSAddressList(getDSAddress(SteamSensor.Sensor));
  else if (var == "PipeAddr")
    return get_DSAddressList(getDSAddress(PipeSensor.Sensor));
  else if (var == "WaterAddr")
    return get_DSAddressList(getDSAddress(WaterSensor.Sensor));
  else if (var == "TankAddr")
    return get_DSAddressList(getDSAddress(TankSensor.Sensor));
  else if (var == "ACPAddr")
    return get_DSAddressList(getDSAddress(ACPSensor.Sensor));
  return "";
}

String calibrateKeyProcessor(const String &var) {
  if (var == "StepperStep") return (String)STEPPER_MAX_SPEED;
  else if (var == "StepperStepMl")
    return (String)(SamSetup.StepperStepMl * 100);

  return String();
}

void handleSave(AsyncWebServerRequest *request) {
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

  if (request->hasArg("SteamDelay")) {
    SamSetup.SteamDelay = request->arg("SteamDelay").toInt();
  }
  if (request->hasArg("PipeDelay")) {
    SamSetup.PipeDelay = request->arg("PipeDelay").toInt();
  }
  if (request->hasArg("WaterDelay")) {
    SamSetup.WaterDelay = request->arg("WaterDelay").toInt();
  }
  if (request->hasArg("TankDelay")) {
    SamSetup.TankDelay = request->arg("TankDelay").toInt();
  }
  if (request->hasArg("ACPDelay")) {
    SamSetup.ACPDelay = request->arg("ACPDelay").toInt();
  }

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
  if (request->hasArg("DeltaACPTemp")) {
    SamSetup.DeltaACPTemp = request->arg("DeltaACPTemp").toFloat();
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
  if (request->hasArg("SetACPTemp")) {
    SamSetup.SetACPTemp = request->arg("SetACPTemp").toFloat();
  }
  if (request->hasArg("Kp")) {
    SamSetup.Kp = request->arg("Kp").toFloat();
  }
  if (request->hasArg("Ki")) {
    SamSetup.Ki = request->arg("Ki").toFloat();
  }
  if (request->hasArg("Kd")) {
    SamSetup.Kd = request->arg("Kd").toFloat();
  }
  if (request->hasArg("StbVoltage")) {
    SamSetup.StbVoltage = request->arg("StbVoltage").toFloat();
  }
  if (request->hasArg("BVolt")) {
    SamSetup.BVolt = request->arg("BVolt").toFloat();
  }
  if (request->hasArg("StepperStepMl")) {
    SamSetup.StepperStepMl = request->arg("StepperStepMl").toInt();
  }
  if (request->hasArg("stepperstepml")) {
    SamSetup.StepperStepMl = request->arg("stepperstepml").toInt() / 100;
  }
  if (request->hasArg("WProgram")) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) set_beer_program(request->arg("WProgram"));
    else
      set_program(request->arg("WProgram"));
  }

  SamSetup.UsePreccureCorrect = false;
  if (request->hasArg("usepressure")) {
    SamSetup.UsePreccureCorrect = true;
  }

  SamSetup.useautopowerdown = false;
  if (request->hasArg("useautopowerdown")) {
    SamSetup.useautopowerdown = true;
  }

  SamSetup.useautospeed = false;
  if (request->hasArg("useautospeed")) {
    SamSetup.useautospeed = true;
  }

  SamSetup.ChangeProgramBuzzer = false;
  if (request->hasArg("ChangeProgramBuzzer")) {
    SamSetup.ChangeProgramBuzzer = true;
  }

  SamSetup.UseBuzzer = false;
  if (request->hasArg("UseBuzzer")) {
    SamSetup.UseBuzzer = true;
  }

  SamSetup.UseWS = false;
  if (request->hasArg("UseWS")) {
    SamSetup.UseWS = true;
  }

  SamSetup.UseST = false;
  if (request->hasArg("UseST")) {
    SamSetup.UseST = true;
  }

  SamSetup.CheckPower = false;
  if (request->hasArg("CheckPower")) {
    SamSetup.CheckPower = true;
  }

  if (request->hasArg("autospeed")) {
    SamSetup.autospeed = request->arg("autospeed").toInt();
  }
  if (request->hasArg("DistTemp")) {
    SamSetup.DistTemp = request->arg("DistTemp").toFloat();
  }
  if (request->hasArg("TimeZone")) {
    SamSetup.TimeZone = request->arg("TimeZone").toInt();
  }
  if (request->hasArg("LogPeriod")) {
    SamSetup.LogPeriod = request->arg("LogPeriod").toInt();
  }
  if (request->hasArg("HeaterR")) {
    SamSetup.HeaterResistant = request->arg("HeaterR").toFloat();
  }
  if (request->hasArg("videourl")) {
    request->arg("videourl").toCharArray(SamSetup.videourl, request->arg("videourl").length() + 1);
  }
  if (request->hasArg("blynkauth")) {
    request->arg("blynkauth").toCharArray(SamSetup.blynkauth, 33);
  }
  if (request->hasArg("SteamColor")) {
    request->arg("SteamColor").toCharArray(SamSetup.SteamColor, request->arg("SteamColor").length() + 1);
  }
  if (request->hasArg("PipeColor")) {
    request->arg("PipeColor").toCharArray(SamSetup.PipeColor, request->arg("PipeColor").length() + 1);
  }
  if (request->hasArg("WaterColor")) {
    request->arg("WaterColor").toCharArray(SamSetup.WaterColor, request->arg("WaterColor").length() + 1);
  }
  if (request->hasArg("TankColor")) {
    request->arg("TankColor").toCharArray(SamSetup.TankColor, request->arg("TankColor").length() + 1);
  }
  if (request->hasArg("ACPColor")) {
    request->arg("ACPColor").toCharArray(SamSetup.ACPColor, request->arg("ACPColor").length() + 1);
  }
  if (request->hasArg("mode")) {
    if (SamSetup.Mode != request->arg("mode").toInt()) {
      is_reboot = true;
      SamSetup.Mode = request->arg("mode").toInt();
    }
  }
  if (request->hasArg("rele1")) {
    SamSetup.rele1 = request->arg("rele1").toInt();
  }
  if (request->hasArg("rele2")) {
    SamSetup.rele2 = request->arg("rele2").toInt();
  }
  if (request->hasArg("rele3")) {
    SamSetup.rele3 = request->arg("rele3").toInt();
  }
  if (request->hasArg("rele4")) {
    SamSetup.rele4 = request->arg("rele4").toInt();
  }
  if (request->hasArg("SteamAddr")) {
    if (request->arg("SteamAddr").toInt() >= 0) CopyDSAddress(DSAddr[request->arg("SteamAddr").toInt()], SamSetup.SteamAdress);
    else {
      SamSetup.SteamAdress[0] = 255;
      SteamSensor.Sensor[0] = 255;
      SteamSensor.avgTemp = 0;
    }
  }
  if (request->hasArg("PipeAddr")) {
    if (request->arg("PipeAddr").toInt() >= 0) CopyDSAddress(DSAddr[request->arg("PipeAddr").toInt()], SamSetup.PipeAdress);
    else {
      SamSetup.PipeAdress[0] = 255;
      PipeSensor.Sensor[0] = 255;
      PipeSensor.avgTemp = 0;
    }
  }
  if (request->hasArg("WaterAddr")) {
    if (request->arg("WaterAddr").toInt() >= 0) CopyDSAddress(DSAddr[request->arg("WaterAddr").toInt()], SamSetup.WaterAdress);
    else {
      SamSetup.WaterAdress[0] = 255;
      WaterSensor.Sensor[0] = 255;
      WaterSensor.avgTemp = 0;
    }
  }
  if (request->hasArg("TankAddr")) {
    if (request->arg("TankAddr").toInt() >= 0) CopyDSAddress(DSAddr[request->arg("TankAddr").toInt()], SamSetup.TankAdress);
    else {
      SamSetup.TankAdress[0] = 255;
      TankSensor.Sensor[0] = 255;
      TankSensor.avgTemp = 0;
    }
  }
  if (request->hasArg("ACPAddr")) {
    if (request->arg("ACPAddr").toInt() >= 0) CopyDSAddress(DSAddr[request->arg("ACPAddr").toInt()], SamSetup.ACPAdress);
    else {
      SamSetup.ACPAdress[0] = 255;
      ACPSensor.Sensor[0] = 255;
      ACPSensor.avgTemp = 0;
    }
  }

  // Сохраняем изменения в память.
  save_profile();
  read_config();

  AsyncWebServerResponse *response = request->beginResponse(301);
  response->addHeader("Location", "/");
  response->addHeader("Cache-Control", "no-cache");
  request->send(response);
  if (is_reboot) {
    ESP.restart();
  }
}

void web_command(AsyncWebServerRequest *request) {
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
  if (request->params() == 1) {
    if (request->hasArg("start") && PowerOn) {
      if (Samovar_Mode == SAMOVAR_BEER_MODE) {
        sam_command_sync = SAMOVAR_BEER_NEXT;
      }
      else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
        sam_command_sync = SAMOVAR_DIST_NEXT;
      }
      else {
        sam_command_sync = SAMOVAR_START;
      }
    } else if (request->hasArg("power")) {
      if (Samovar_Mode == SAMOVAR_BEER_MODE) {
        if (!PowerOn) sam_command_sync = SAMOVAR_BEER;
        else
          sam_command_sync = SAMOVAR_POWER;
      } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
        if (!PowerOn) sam_command_sync = SAMOVAR_DISTILLATION;
        else
          sam_command_sync = SAMOVAR_POWER;
      } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
        if (!PowerOn) sam_command_sync = SAMOVAR_BK;
        else
          sam_command_sync = SAMOVAR_POWER;
      } else
        sam_command_sync = SAMOVAR_POWER;
    } else if (request->hasArg("setbodytemp")) {
      sam_command_sync = SAMOVAR_SETBODYTEMP;
    } else if (request->hasArg("reset")) {
      sam_command_sync = SAMOVAR_RESET;
    } else if (request->hasArg("reboot")) {
      ESP.restart();
    } else if (request->hasArg("resetwifi")) {
      menu_reset_wifi();
    } else if (request->hasArg("startst")) {
      sam_command_sync = SAMOVAR_SELF_TEST;
    } else if (request->hasArg("stopst")) {
      stop_self_test();
    } else if (request->hasArg("mixer")) {
      if (request->arg("mixer").toInt() == 1) {
        set_mixer(true);
      } else {
        set_mixer(false);
      }
    } else if (request->hasArg("distiller")) {
      if (request->arg("distiller").toInt() == 1) {
        sam_command_sync = SAMOVAR_DISTILLATION;
      } else {
        sam_command_sync = SAMOVAR_POWER;
      }
    } else if (request->hasArg("startbk")) {
      if (request->arg("startbk").toInt() == 1) {
        sam_command_sync = SAMOVAR_BK;
      } else {
        sam_command_sync = SAMOVAR_POWER;
      }
    } else if (request->hasArg("watert")) {
      set_water_temp(request->arg("watert").toFloat());
    } else if (request->hasArg("pumpspeed")) {
      set_pump_speed(get_speed_from_rate(request->arg("pumpspeed").toFloat()), true);
    } else if (request->hasArg("pause")) {
      if (PauseOn) {
        sam_command_sync = SAMOVAR_CONTINUE;
      } else {
        sam_command_sync = SAMOVAR_PAUSE;
      }
    }
#ifdef SAMOVAR_USE_POWER
    else if (request->hasArg("voltage")) {
      set_current_power(request->arg("voltage").toFloat());
    }
#endif
#ifdef USE_LUA
    else if (request->hasArg("lua")) {
      run_lua_script(request->arg("lua"));
    }
#endif
  }
  request->send(200, "text/plain", "OK");
}
void web_program(AsyncWebServerRequest *request) {
  if (request->hasArg("WProgram")) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      set_beer_program(request->arg("WProgram"));
      request->send(200, "text/plain", get_beer_program());
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      set_dist_program(request->arg("WProgram"));
      request->send(200, "text/plain", get_dist_program());
    } else {
      set_program(request->arg("WProgram"));
      request->send(200, "text/plain", get_program(CAPACITY_NUM * 2));
    }
  }
  if (request->hasArg("Descr")) {
    SessionDescription = request->arg("Descr");
    SessionDescription.replace("%", "&#37;");
  }
}

void calibrate_command(AsyncWebServerRequest *request) {
  bool cl = false;
  if (request->params() >= 1) {
    if (request->hasArg("stpstep")) {
      CurrrentStepperSpeed = request->arg("stpstep").toInt();
    }
    if (request->hasArg("start") && startval == 0) {
      sam_command_sync = CALIBRATE_START;
    }
    if (request->hasArg("finish") && startval == 100) {
      sam_command_sync = CALIBRATE_STOP;
      cl = true;
    }
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
  if (cl) {
    int s = round((float)stepper.getCurrent() / 100) * 100;
    request->send(200, "text/plain", (String)s);
  } else
    request->send(200, "text/plain", "OK");
}

void get_data_log(AsyncWebServerRequest *request) {
  if (fileToAppend)
    fileToAppend.flush();
  AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/data.csv", String(), true);
  if (SPIFFS.exists("/data.csv")) {
    response = request->beginResponse(SPIFFS, "/data.csv", String(), true);
  } else {
    response = request->beginResponse(400, "text/plain", "");
  }
  response->addHeader("Content-Type", "application/octet-stream");
  response->addHeader("Content-Description", "File Transfer");
  response->addHeader("Content-Disposition", "attachment; filename=\"data.csv\"");
  response->addHeader("Pragma", "public");
  response->addHeader("Cache-Control", "no-cache");
  request->send(response);
}

void get_old_data_log(AsyncWebServerRequest *request) {
  AsyncWebServerResponse *response;
  if (SPIFFS.exists("/data_old.csv")) {
    response = request->beginResponse(SPIFFS, "/data_old.csv", String(), true);
  } else {
    response = request->beginResponse(400, "text/plain", "");
  }
  response->addHeader("Content-Type", "application/octet-stream");
  response->addHeader("Content-Description", "File Transfer");
  response->addHeader("Content-Disposition", "attachment; filename=\"data_old.csv\"");
  response->addHeader("Pragma", "public");
  response->addHeader("Cache-Control", "no-cache");
  request->send(response);
}

void get_web_interface() {

  bool ret = Ping.ping("web.samovar-tool.ru", 2);
  if (!ret) {
    Serial.println(F("Нет покдлючения к интернету. Не удалось проверить обновление интерфейса. Если это первичная установка - необходимо загрузить интерфейс в Самовар в соответствии с инструкцией"));
    return;
  }

  String version;
  String local_version;
  String s = "";

  version = get_web_file("version.txt", GET_CONTENT);
  if (version == "<ERR>") return;

  Serial.print(F("WEB interface version = "));
  Serial.println(version);

  File fn = SPIFFS.open("/version.txt", FILE_READ);
  if (fn) {
    local_version = fn.readStringUntil('\n');
    fn.close();
  }
  Serial.print(F("Local interface version = "));
  Serial.println(local_version);
  if (version != local_version) {
    s += get_web_file("index.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("Green.png", SAVE_FILE_OVERRIDE);
    s += get_web_file("Red_light.gif", SAVE_FILE_OVERRIDE);
    s += get_web_file("alarm.mp3", SAVE_FILE_OVERRIDE);
    s += get_web_file("favicon.ico", SAVE_FILE_OVERRIDE);
    s += get_web_file("minus.png", SAVE_FILE_OVERRIDE);
    s += get_web_file("plus.png", SAVE_FILE_OVERRIDE);

    s += get_web_file("style.css", SAVE_FILE_OVERRIDE);

    s += get_web_file("beer.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("bk.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("brewxml.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("calibrate.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("chart.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("distiller.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("edit.htm", SAVE_FILE_OVERRIDE);
    
    s += get_web_file("program.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("setup.htm", SAVE_FILE_OVERRIDE);

    s += get_web_file("beer.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("bk.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("dist.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("init.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("rectificat.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("script.lua", SAVE_FILE_IF_NOT_EXIST);

    s += get_web_file("program_fruit.txt", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("program_grain.txt", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("program_shugar.txt", SAVE_FILE_IF_NOT_EXIST);

    if (s == "") {
      s = get_web_file("version.txt", SAVE_FILE_OVERRIDE);
    }
  }
}

String get_web_file(String fn, get_web_type type) {
  if (type == SAVE_FILE_IF_NOT_EXIST && SPIFFS.exists("/" + fn)) {
    Serial.println("File " + fn + " already exist.");
    return "";
  }
  asyncHTTPrequest request;
  String command = "GET";
  String url = "http://web.samovar-tool.ru/" + String(SAMOVAR_VERSION) + "/" + fn;
  Serial.print("url = ");
  Serial.println(url);
  request.setDebug(false);
  request.setTimeout(4);                      //Таймаут три секунды
  request.open(command.c_str(), url.c_str());  //URL
  while (request.readyState() < 1) {
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  request.send();
  vTaskDelay(150 / portTICK_PERIOD_MS);
  while (request.readyState() != 4) {
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  if (request.responseHTTPcode() >= 0) {
    if (request.responseHTTPcode() != 200) {
      Serial.print("responseHTTPcode = ");
      Serial.println(request.responseHTTPcode());
      Serial.println("Content " + fn + " download error");
      return "<ERR>";
    }
    if (type == GET_CONTENT) {
      String s = String("") + request.responseText() + "";
      return s;
    } else {
      File wf = SPIFFS.open("/" + fn, FILE_WRITE);
      wf.print(request.responseText());
      wf.close();
      //Serial.print("responseText = ");
      //Serial.println(s);
    }
    Serial.println("Done");
  } else {
    Serial.println("error");
    Serial.println(request.responseHTTPcode());
    return "<ERR>";
  }
  return "";
}
