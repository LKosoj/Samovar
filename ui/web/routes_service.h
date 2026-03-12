#ifndef __SAMOVAR_UI_WEB_ROUTES_SERVICE_H__
#define __SAMOVAR_UI_WEB_ROUTES_SERVICE_H__

inline void calibrate_command(AsyncWebServerRequest *request) {
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
        save_profile_nvs();
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

inline void get_data_log(AsyncWebServerRequest *request, String fn) {
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

#endif
