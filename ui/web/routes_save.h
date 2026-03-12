#ifndef __SAMOVAR_UI_WEB_ROUTES_SAVE_H__
#define __SAMOVAR_UI_WEB_ROUTES_SAVE_H__

#include <Arduino.h>
#include <ESPAsyncWebServer.h>

#include "Samovar.h"
#include "state/globals.h"
#include "ui/web/routes_setup_wifi.h"
#include "ui/web/routes_setup_process.h"
#include "modes/beer/beer_program_codec.h"
#include "modes/beer/beer_runtime.h"
#include "modes/dist/dist_program_codec.h"
#include "modes/nbk/nbk_program_codec.h"
#include "modes/bk/bk_water_control.h"
#include "sensorinit.h"
#include "column_math.h"

// Forward declarations для функций, не доступных через заголовки
String getValue(String& data, char separator, int index);
void set_program(String WProgram);
void set_beer_program(String WProgram);
void get_task_stack_usage();
extern bool is_reboot;

// Обработчик сохранения настроек (объединяет WiFi и процессные настройки)
inline void handleSave(AsyncWebServerRequest *request) {
  if (!request) {
    return;
  }

  // WiFi настройки
  if (request->hasArg("videourl")) {
    copyStringSafe(SamSetup.videourl, request->arg("videourl"));
  }
  if (request->hasArg("blynkauth")) {
    copyStringSafe(SamSetup.blynkauth, request->arg("blynkauth"));
  }
  if (request->hasArg("tgtoken")) {
    copyStringSafe(SamSetup.tg_token, request->arg("tgtoken"));
  }
  if (request->hasArg("tgchatid")) {
    copyStringSafe(SamSetup.tg_chat_id, request->arg("tgchatid"));
  }

  // Температурные задержки
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

  // Температурные дельты
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

  // Уставки температур
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

  // PID параметры
  if (request->hasArg("Kp")) {
    SamSetup.Kp = request->arg("Kp").toFloat();
  }
  if (request->hasArg("Ki")) {
    SamSetup.Ki = request->arg("Ki").toFloat();
  }
  if (request->hasArg("Kd")) {
    SamSetup.Kd = request->arg("Kd").toFloat();
  }

  // Напряжения
  if (request->hasArg("StbVoltage")) {
    SamSetup.StbVoltage = request->arg("StbVoltage").toFloat();
  }
  if (request->hasArg("BVolt")) {
    SamSetup.BVolt = request->arg("BVolt").toFloat();
  }

  // Дистилляция параметры
  if (request->hasArg("DistTimeF")) {
    SamSetup.DistTimeF = request->arg("DistTimeF").toInt();
  }
  if (request->hasArg("MaxPressureValue")) {
    SamSetup.MaxPressureValue = request->arg("MaxPressureValue").toFloat();
  }

  // Шаговый двигатель
  if (request->hasArg("StepperStepMl")) {
    SamSetup.StepperStepMl = request->arg("StepperStepMl").toInt();
  }
  if (request->hasArg("StepperStepMlI2C")) {
    SamSetup.StepperStepMlI2C = request->arg("StepperStepMlI2C").toInt();
  }
  if (request->hasArg("stepperstepml")) {
    SamSetup.StepperStepMl = request->arg("stepperstepml").toInt() / 100;
  }

  // Программа
  if (request->hasArg("WProgram")) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) set_beer_program(request->arg("WProgram"));
    else
      set_program(request->arg("WProgram"));
  }

  // Флаги
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

  // НБК параметры
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

  // Вызываем обработчики WiFi настроек
  handleSaveWifiSettings(request);

  // Цвета
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

  // Вызываем обработчик процессных настроек
  handleSaveProcessSettings(request);

  // Реле
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

  // Адреса датчиков
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

  // Параметры колонны
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
  save_profile_nvs();
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

#endif
