#include <asyncHTTPrequest.h>
//#include <ESPping.h>
#include <WiFi.h>

#include "Samovar.h"
#include "modes/beer/beer_program_codec.h"
#include "modes/beer/beer_mixer.h"
#include "modes/beer/beer_runtime.h"
#include "modes/bk/bk_finish.h"
#include "modes/bk/bk_water_control.h"
#include "modes/nbk/nbk_finish.h"
#include "modes/nbk/nbk_math.h"
#include "modes/nbk/nbk_program_codec.h"
#include "modes/nbk/nbk_state.h"
#include "modes/dist/dist_program_codec.h"
#include "modes/dist/dist_runtime.h"
#include "modes/rect/rect_program_codec.h"
#include "state/globals.h"
#include "app/process_common.h"
#include "ui/web/ajax_snapshot.h"
#include "ui/web/page_assets.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "support/safe_parse.h"
#include "support/process_math.h"
#include "FS.h"
#include "sensorinit.h"
#include "column_math.h"

float i2c_get_speed_from_rate(float volume_per_hour);
String getValue(String& data, char separator, int index);
void menu_reset_wifi();
uint16_t get_stepper_speed(void);
uint32_t get_stepper_status(void);
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
float get_speed_from_rate(float rate);
float get_alcohol(float t);
void FS_init(void);
void save_profile();
void read_config();
void load_profile();
void change_samovar_mode();
void WebServerInit(void);
String indexKeyProcessor(const String &var);
String setupKeyProcessor(const String &var);
String wifiKeyProcessor(const String &var);
String get_DSAddressList(String Address);
String get_web_file(String fn, get_web_type type);
void get_web_interface();
String http_sync_request_get(String url);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void web_command(AsyncWebServerRequest *request);
void handleSave(AsyncWebServerRequest *request);
void handleSaveProcessSettings(AsyncWebServerRequest *request);
void handleSaveWifiSettings(AsyncWebServerRequest *request);
void get_data_log(AsyncWebServerRequest *request, String fn);
String calibrateKeyProcessor(const String &var);
String indexKeyProcessor(const String &var);
void web_program(AsyncWebServerRequest *request);
void calibrate_command(AsyncWebServerRequest *request);
String setupKeyProcessor(const String &var);
String get_DSAddressList(String Address);
String get_web_file(String fn, get_web_type type);
void get_web_interface();
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void samovar_reset();

#ifdef USE_LUA
void start_lua_script();
void load_lua_script();
String get_lua_script_list();
void run_lua_script(String fn);
String run_lua_string(String lstr);
#endif

// filter out specific headers from the incoming request
AsyncHeaderFilterMiddleware headerFilter;

AsyncStaticWebHandler* indexHandler = nullptr;

void change_samovar_mode() {
  if (indexHandler) {
    server.removeHandler(indexHandler);
    indexHandler = nullptr;
  }

  if (Samovar_Mode == SAMOVAR_BEER_MODE) {
    //server.serveStatic("/", SPIFFS, "/beer.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=800");    
    indexHandler = &server.serveStatic("/index.htm", SPIFFS, "/beer.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("no-cache, no-store, must-revalidate");
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    //server.serveStatic("/", SPIFFS, "/distiller.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=800");
    indexHandler = &server.serveStatic("/index.htm", SPIFFS, "/distiller.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("no-cache, no-store, must-revalidate");
  } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
    //server.serveStatic("/", SPIFFS, "/bk.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=800");
    indexHandler = &server.serveStatic("/index.htm", SPIFFS, "/bk.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("no-cache, no-store, must-revalidate");
  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
    //server.serveStatic("/", SPIFFS, "/nbk.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=800");
    indexHandler = &server.serveStatic("/index.htm", SPIFFS, "/nbk.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("no-cache, no-store, must-revalidate");
  } else {
    //server.serveStatic("/", SPIFFS, "/index.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=800");
    indexHandler = &server.serveStatic("/index.htm", SPIFFS, "/index.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("no-cache, no-store, must-revalidate");
    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  }
  Samovar_CR_Mode = Samovar_Mode;
}


void handleSave(AsyncWebServerRequest *request) {
  if (!request) {
    return;
  }
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
  if (request->hasArg("DistTimeF")) {
    SamSetup.DistTimeF = request->arg("DistTimeF").toInt();
  }
  if (request->hasArg("MaxPressureValue")) {
    SamSetup.MaxPressureValue = request->arg("MaxPressureValue").toFloat();
  }
  if (request->hasArg("StepperStepMl")) {
    SamSetup.StepperStepMl = request->arg("StepperStepMl").toInt();
  }
  if (request->hasArg("StepperStepMlI2C")) {
    SamSetup.StepperStepMlI2C = request->arg("StepperStepMlI2C").toInt();
  }
  if (request->hasArg("stepperstepml")) {
    SamSetup.StepperStepMl = request->arg("stepperstepml").toInt() / 100;
  }
  if (request->hasArg("WProgram")) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) set_beer_program(request->arg("WProgram"));
    else
      set_program(request->arg("WProgram"));
  }

  SamSetup.UseHLS = false;
  if (request->hasArg("useflevel")) {
    SamSetup.UseHLS = true;
  }

  SamSetup.UsePreccureCorrect = false;
  if (request->hasArg("usepressure")) {
    SamSetup.UsePreccureCorrect = true;
  }

  SamSetup.useautospeed = false;
  if (request->hasArg("useautospeed")) {
    SamSetup.useautospeed = true;
  }

  SamSetup.useDetectorOnHeads = false;
  if (request->hasArg("useDetectorOnHeads")) {
    SamSetup.useDetectorOnHeads = true;
  }

  SamSetup.ChangeProgramBuzzer = false;
  if (request->hasArg("ChangeProgramBuzzer")) {
    SamSetup.ChangeProgramBuzzer = true;
  }

  SamSetup.UseBuzzer = false;
  if (request->hasArg("UseBuzzer")) {
    SamSetup.UseBuzzer = true;
  }

  SamSetup.UseBBuzzer = false;
  if (request->hasArg("UseBBuzzer")) {
    SamSetup.UseBBuzzer = true;
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
  if (request->hasArg("NbkIn")) {
    SamSetup.NbkIn = request->arg("NbkIn").toFloat();
  }
  if (request->hasArg("NbkDelta")) {
    SamSetup.NbkDelta = request->arg("NbkDelta").toFloat();
  }
  if (request->hasArg("NbkDM")) {
    SamSetup.NbkDM = request->arg("NbkDM").toFloat();
  }
  if (request->hasArg("NbkDP")) {
    SamSetup.NbkDP = request->arg("NbkDP").toFloat();
  }
  if (request->hasArg("NbkSteamT")) {
    SamSetup.NbkSteamT = request->arg("NbkSteamT").toFloat();
  }
  if (request->hasArg("NbkOwPress")) {
    SamSetup.NbkOwPress = request->arg("NbkOwPress").toFloat();
  }
  handleSaveWifiSettings(request);
  if (request->hasArg("SteamColor")) {
    copyStringSafe(SamSetup.SteamColor, request->arg("SteamColor"));
  }
  if (request->hasArg("PipeColor")) {
    copyStringSafe(SamSetup.PipeColor, request->arg("PipeColor"));
  }
  if (request->hasArg("WaterColor")) {
    copyStringSafe(SamSetup.WaterColor, request->arg("WaterColor"));
  }
  if (request->hasArg("TankColor")) {
    copyStringSafe(SamSetup.TankColor, request->arg("TankColor"));
  }
  if (request->hasArg("ACPColor")) {
    copyStringSafe(SamSetup.ACPColor, request->arg("ACPColor"));
  }
  handleSaveProcessSettings(request);
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
  const int dsAddrMax = (int)(sizeof(DSAddr) / sizeof(DSAddr[0]));
  auto isValidDsIndex = [&](int idx) -> bool {
    return idx >= 0 && idx < DScnt && idx < dsAddrMax;
  };
  if (request->hasArg("SteamAddr")) {
    int idx = request->arg("SteamAddr").toInt();
    if (isValidDsIndex(idx)) CopyDSAddress(DSAddr[idx], SamSetup.SteamAdress);
    else {
      SamSetup.SteamAdress[0] = 255;
      SteamSensor.Sensor[0] = 255;
      SteamSensor.avgTemp = 0;
    }
  }
  if (request->hasArg("PipeAddr")) {
    int idx = request->arg("PipeAddr").toInt();
    if (isValidDsIndex(idx)) CopyDSAddress(DSAddr[idx], SamSetup.PipeAdress);
    else {
      SamSetup.PipeAdress[0] = 255;
      PipeSensor.Sensor[0] = 255;
      PipeSensor.avgTemp = 0;
    }
  }
  if (request->hasArg("WaterAddr")) {
    int idx = request->arg("WaterAddr").toInt();
    if (isValidDsIndex(idx)) CopyDSAddress(DSAddr[idx], SamSetup.WaterAdress);
    else {
      SamSetup.WaterAdress[0] = 255;
      WaterSensor.Sensor[0] = 255;
      WaterSensor.avgTemp = 0;
    }
  }
  if (request->hasArg("TankAddr")) {
    int idx = request->arg("TankAddr").toInt();
    if (isValidDsIndex(idx)) CopyDSAddress(DSAddr[idx], SamSetup.TankAdress);
    else {
      SamSetup.TankAdress[0] = 255;
      TankSensor.Sensor[0] = 255;
      TankSensor.avgTemp = 0;
    }
  }
  if (request->hasArg("ACPAddr")) {
    int idx = request->arg("ACPAddr").toInt();
    if (isValidDsIndex(idx)) CopyDSAddress(DSAddr[idx], SamSetup.ACPAdress);
    else {
      SamSetup.ACPAdress[0] = 255;
      ACPSensor.Sensor[0] = 255;
      ACPSensor.avgTemp = 0;
    }
  }

  if (request->hasArg("ColDiam")) {
    SamSetup.ColDiam = request->arg("ColDiam").toFloat();
  }
  if (request->hasArg("ColHeight")) {
    SamSetup.ColHeight = request->arg("ColHeight").toFloat();
  }
  if (request->hasArg("PackDens")) {
    SamSetup.PackDens = request->arg("PackDens").toInt();
  }

  // Сохраняем изменения в память.
  save_profile();
  read_config();

  get_task_stack_usage();
  AsyncWebServerResponse *response = request->beginResponse(301);
  response->addHeader("Location", "/");
  response->addHeader("Cache-Control", "no-cache");
  request->send(response);
  if (is_reboot) {
    ESP.restart();
  }
}

void web_program(AsyncWebServerRequest *request) {
  if (request->hasArg("WProgram")) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      set_beer_program(request->arg("WProgram"));
      request->send(200, "text/plain", get_beer_program());
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      set_dist_program(request->arg("WProgram"));
      request->send(200, "text/plain", get_dist_program());
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      set_nbk_program(request->arg("WProgram"));
      request->send(200, "text/plain", get_nbk_program());
    } else {
      set_program(request->arg("WProgram"));
      request->send(200, "text/plain", get_program(CAPACITY_NUM * 2));
    }
  }
  if (request->hasArg("vless")) {
    BoilerVolume = request->arg("vless").toFloat();
    if (BoilerVolume <= 0) BoilerVolume = 30.0f; // Защита: если 0, считаем 30л
    heatLossCalculated = false; // Сбрасываем расчет при смене объема
    heatStartMillis = 0;
  }
  if (request->hasArg("Descr")) {
    SessionDescription = request->arg("Descr");
    SessionDescription.replace("%", "&#37;");
  }
}

void calibrate_command(AsyncWebServerRequest *request) {
  bool cl = false;
  bool isI2C = false;
  if (request->hasArg("pump")) {
    String pump = request->arg("pump");
    pump.toLowerCase();
    if (pump == "i2c") isI2C = true;
  }
  if (request->params() >= 1) {
    if (request->hasArg("stpstep")) {
      CurrrentStepperSpeed = request->arg("stpstep").toInt();
    }
    if (!isI2C) {
      if (request->hasArg("start") && startval == 0) {
        sam_command_sync = CALIBRATE_START;
      }
      if (request->hasArg("finish") && startval == 100) {
        sam_command_sync = CALIBRATE_STOP;
        cl = true;
      }
    } else if (use_I2C_dev == 2) {
      if (request->hasArg("start") && !I2CPumpCalibrating) {
        I2CPumpTargetSteps = 2147483640UL;
        I2CPumpTargetMl = 0;
        I2CPumpCmdSpeed = CurrrentStepperSpeed;
        I2CPumpCalibrating = true;
        set_stepper_target(CurrrentStepperSpeed, 0, I2CPumpTargetSteps);
      }
      if (request->hasArg("finish") && I2CPumpCalibrating) {
        set_stepper_target(0, 0, 0);
        uint32_t remaining = get_stepper_status();
        uint32_t done = (I2CPumpTargetSteps > remaining) ? (I2CPumpTargetSteps - remaining) : 0;
        SamSetup.StepperStepMlI2C = (uint16_t)round((float)done / 100.0f);
        I2CPumpCalibrating = false;
        save_profile();
        read_config();
        cl = true;
      }
    }
  }
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (cl) {
    int s = 0;
    if (!isI2C) {
      s = round((float)stepper.getCurrent() / 100) * 100;
    } else {
      s = SamSetup.StepperStepMlI2C * 100;
    }
    request->send(200, "text/plain", (String)s);
  } else
    request->send(200, "text/plain", "OK");
}

void get_data_log(AsyncWebServerRequest *request, String fn) {
  if (fileToAppend && fileToAppend.available())
    fileToAppend.flush();
  AsyncWebServerResponse *response;
  if (SPIFFS.exists("/" + fn)) {
    response = request->beginResponse(SPIFFS, "/" + fn, String(), true);
  } else {
    response = request->beginResponse(400, "text/plain", "");
  }
  response->addHeader(F("Content-Type"), F("application/octet-stream"));
  response->addHeader(F("Content-Description"), F("File Transfer"));
  response->addHeader(F("Content-Disposition"), "attachment; filename=\"" + fn + "\"");
  response->addHeader(F("Pragma"), F("public"));
  response->addHeader(F("Cache-Control"), F("no-cache"));
  request->send(response);
}

void get_web_interface() {
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
    s += get_web_file("wifi.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("index.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("Green.png", SAVE_FILE_OVERRIDE);
    s += get_web_file("Red_light.gif", SAVE_FILE_OVERRIDE);
    s += get_web_file("alarm.mp3", SAVE_FILE_OVERRIDE);
    s += get_web_file("favicon.ico", SAVE_FILE_OVERRIDE);
    s += get_web_file("minus.png", SAVE_FILE_OVERRIDE);
    s += get_web_file("plus.png", SAVE_FILE_OVERRIDE);

    //s += get_web_file("style.css", SAVE_FILE_OVERRIDE);
    s += get_web_file("style.css.gz", SAVE_FILE_OVERRIDE);

    s += get_web_file("beer.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("bk.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("nbk.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("brewxml.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("calibrate.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("chart.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("distiller.htm", SAVE_FILE_OVERRIDE);
    //s += get_web_file("edit.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("edit.htm.gz", SAVE_FILE_OVERRIDE);

    s += get_web_file("program.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("setup.htm", SAVE_FILE_OVERRIDE);

    s += get_web_file("beer.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("bk.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("nbk.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("dist.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("init.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("rectificat.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("script.lua", SAVE_FILE_IF_NOT_EXIST);

    s += get_web_file("btn_rect_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_rect_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_beer_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_beer_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_dist_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_dist_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_bk_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_bk_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_nbk_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_nbk_button2.lua", SAVE_FILE_IF_NOT_EXIST);



    s += get_web_file("program_fruit.txt", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("program_grain.txt", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("program_shugar.txt", SAVE_FILE_IF_NOT_EXIST);

    s += get_web_file("version.txt", SAVE_FILE_OVERRIDE);
  }
}

String get_web_file(String fn, get_web_type type) {
  if (type == SAVE_FILE_IF_NOT_EXIST && SPIFFS.exists("/" + fn)) {
    Serial.println("File " + fn + " already exist.");
    return "";
  }

  String url = "http://web.samovar-tool.ru/" + String(SAMOVAR_VERSION) + "/" + fn + "?" + micros();
  Serial.print("url = ");
  Serial.println(url);

  String s = http_sync_request_get(url);

  if (s == "<ERR>") {
    return s;
  } else {
    if (type == GET_CONTENT) {
      return s;
    } else {
      File wf = SPIFFS.open("/" + fn, FILE_WRITE);
      wf.print(s);
      wf.close();
      //Serial.print("responseText = ");
      //Serial.println(s);
    }
    Serial.println("Done (L=" + String(s.length()) + ")");
  }

  return "";
}

String http_sync_request_get(String url) {
  asyncHTTPrequest request;
  request.setDebug(false);
  const uint32_t timeoutMs = 8000;
  request.setTimeout(8); // Таймаут восемь секунд (внутренний по отсутствию активности)
  if (!request.open("GET", url.c_str())) {
    Serial.println("HTTP GET open() failed");
    return "<ERR>";
  }
  
  unsigned long startTime = millis();
  while (request.readyState() < 1) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: readyState never reached 1");
      request.abort();
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  if (!request.send()) {
    Serial.println("HTTP GET send() failed");
    request.abort();
    return "<ERR>";
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  // Таймаут для ожидания завершения запроса (readyState == 4)
  startTime = millis();
  while (request.readyState() != 4) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: request not completed within 4 seconds");
      request.abort();
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  if (request.responseHTTPcode() >= 0) {
    if (request.responseHTTPcode() != 200) {
      Serial.print(F("responseHTTPcode = "));
      Serial.println(request.responseHTTPcode());
      Serial.println("Content " + url + " download error");
      return "<ERR>";
    }
    return request.responseText();
  } else {
    Serial.print(F("responseHTTPcode = "));
    Serial.println(request.responseHTTPcode());
    Serial.println("Content " + url + " download error (2)");
    return "<ERR>";
  }  
  return "";
}

String http_sync_request_post(String url, String body, String ContentType) {
  asyncHTTPrequest request;
  request.setDebug(false);
  const uint32_t timeoutMs = 8000;
  request.setTimeout(8);  //Таймаут восемь секунд (внутренний по отсутствию активности)

  if (!request.open("POST", url.c_str())) {  //URL
    Serial.println("HTTP POST open() failed");
    return "<ERR>";
  }
  unsigned long startTime = millis();
  while (request.readyState() < 1) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: readyState never reached 1");
      request.abort();
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  request.setReqHeader("Content-Type", getValue(ContentType, ':', 1).c_str());
  if (!request.send(body)) {
    Serial.println("HTTP POST send() failed");
    request.abort();
    return "<ERR>";
  }

  vTaskDelay(150 / portTICK_PERIOD_MS);
  // Таймаут для ожидания завершения запроса (readyState == 4)
  startTime = millis();
  while (request.readyState() != 4) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: request not completed within 4 seconds");
      request.abort();
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  if (request.responseHTTPcode() >= 0) {
    return request.responseText();
  } else {
    return "<ERR>";
  }
}
#include "ui/web/template_keys.h"
#include "ui/web/routes_command.h"
#include "ui/web/routes_setup_wifi.h"
#include "ui/web/routes_setup_process.h"
#include "ui/web/server_init.h"
