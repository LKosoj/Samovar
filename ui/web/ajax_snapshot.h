#ifndef __SAMOVAR_AJAX_SNAPSHOT_H_
#define __SAMOVAR_AJAX_SNAPSHOT_H_

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <NTPClient.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/status_text.h"
#include "modes/dist/dist_time_predictor.h"
#include "modes/dist/dist_runtime.h"
#include "support/format_utils.h"
#include "support/process_math.h"
uint16_t get_stepper_speed(void);
uint32_t get_stepper_status(void);
float i2c_get_liquid_rate_by_step(int StepperSpeed);
float i2c_get_liquid_volume_by_step(int StepCount);

extern NTPClient NTP;

static inline void jsonAddKey(Print &out, bool &first, const char *key) {
  if (!first) out.print(',');
  first = false;
  out.print('\"');
  out.print(key);
  out.print("\":");
}

static inline void jsonPrintEscaped(Print &out, const String &value) {
  for (size_t i = 0; i < value.length(); i++) {
    char c = value[i];
    if (c == '\"' || c == '\\') {
      out.print('\\');
      out.print(c);
    } else if (c == '\n') {
      out.print("\\n");
    } else if (c == '\r') {
      out.print("\\r");
    } else if (c == '\t') {
      out.print("\\t");
    } else {
      out.print(c);
    }
  }
}

void send_ajax_json(AsyncWebServerRequest *request) {
  AsyncResponseStream *response = request->beginResponseStream("application/json");
  response->addHeader("Cache-Control", "no-cache");

  Print &out = *response;
  bool first = true;
  out.print('{');

  jsonAddKey(out, first, "bme_temp");
  out.print(format_float(bme_temp, 3));
  jsonAddKey(out, first, "bme_pressure");
  out.print(format_float(bme_pressure, 3));
  jsonAddKey(out, first, "start_pressure");
  out.print(format_float(start_pressure, 3));
  jsonAddKey(out, first, "crnt_tm");
  out.print('\"');
  jsonPrintEscaped(out, Crt);
  out.print('\"');
  jsonAddKey(out, first, "stm");
  out.print('\"');
  jsonPrintEscaped(out, NTP.getFormattedTime((unsigned long)(millis() / 1000)));
  out.print('\"');
  jsonAddKey(out, first, "SteamTemp");
  out.print(format_float(SteamSensor.avgTemp, 3));
  jsonAddKey(out, first, "PipeTemp");
  out.print(format_float(PipeSensor.avgTemp, 3));
  jsonAddKey(out, first, "WaterTemp");
  out.print(format_float(WaterSensor.avgTemp, 3));
  jsonAddKey(out, first, "TankTemp");
  out.print(format_float(TankSensor.avgTemp, 3));
  jsonAddKey(out, first, "ACPTemp");
  out.print(format_float(ACPSensor.avgTemp, 3));
  jsonAddKey(out, first, "DetectorTrend");
  out.print(format_float(impurityDetector.currentTrend, 3));
  jsonAddKey(out, first, "DetectorStatus");
  out.print(impurityDetector.detectorStatus);
  jsonAddKey(out, first, "useautospeed");
  out.print(SamSetup.useautospeed);
  jsonAddKey(out, first, "version");
  out.print('\"');
  out.print(SAMOVAR_VERSION);
  out.print('\"');
  jsonAddKey(out, first, "VolumeAll");
  out.print(get_liquid_volume());
  jsonAddKey(out, first, "ActualVolumePerHour");
  out.print(format_float(ActualVolumePerHour, 3));
  jsonAddKey(out, first, "PowerOn");
  out.print(PowerOn);
  jsonAddKey(out, first, "PauseOn");
  out.print(PauseOn);
  jsonAddKey(out, first, "WthdrwlProgress");
  out.print(WthdrwlProgress);
  jsonAddKey(out, first, "TargetStepps");
  out.print(stepper.getTarget());
  jsonAddKey(out, first, "CurrrentStepps");
  out.print(stepper.getCurrent());
  jsonAddKey(out, first, "WthdrwlStatus");
  out.print(startval);
  jsonAddKey(out, first, "CurrrentSpeed");
  out.print(round(stepper.getSpeed() * (uint8_t)stepper.getState()));
  jsonAddKey(out, first, "UseBBuzzer");
  out.print(SamSetup.UseBBuzzer);
  jsonAddKey(out, first, "StepperStepMl");
  out.print(SamSetup.StepperStepMl);
  jsonAddKey(out, first, "BodyTemp_Steam");
  out.print(format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3));
  jsonAddKey(out, first, "BodyTemp_Pipe");
  out.print(format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3));
  jsonAddKey(out, first, "mixer");
  out.print(mixer_status);
  jsonAddKey(out, first, "ISspd");
  out.print(format_float(i2c_get_liquid_rate_by_step(get_stepper_speed()), 3));
  jsonAddKey(out, first, "i2c_pump_present");
  out.print((use_I2C_dev == 2) ? 1 : 0);

  if (use_I2C_dev == 2) {
    uint32_t i2cRemaining = get_stepper_status();
    float i2cRemainingMl = i2c_get_liquid_volume_by_step(i2cRemaining);
    jsonAddKey(out, first, "i2c_pump_speed");
    out.print(get_stepper_speed());
    jsonAddKey(out, first, "i2c_pump_target_ml");
    out.print(format_float(I2CPumpTargetMl, 1));
    jsonAddKey(out, first, "i2c_pump_remaining_ml");
    out.print(format_float(i2cRemainingMl, 1));
    jsonAddKey(out, first, "i2c_pump_running");
    out.print((get_stepper_speed() > 0 && i2cRemaining > 0) ? 1 : 0);
  } else {
    jsonAddKey(out, first, "i2c_pump_speed");
    out.print(0);
    jsonAddKey(out, first, "i2c_pump_target_ml");
    out.print(0);
    jsonAddKey(out, first, "i2c_pump_remaining_ml");
    out.print(0);
    jsonAddKey(out, first, "i2c_pump_running");
    out.print(0);
  }

  jsonAddKey(out, first, "heap");
  out.print(ESP.getFreeHeap());
  jsonAddKey(out, first, "rssi");
  out.print(WiFi.RSSI());
  jsonAddKey(out, first, "fr_bt");
  out.print(total_byte - used_byte);

  String pt = "";
  if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) &&
      (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
       SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
       (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn))) {
    pt = program[ProgramNum].WType;
  }
  jsonAddKey(out, first, "PrgType");
  out.print('\"');
  jsonPrintEscaped(out, pt);
  out.print('\"');

  if (Msg.length() > 0) {
    jsonAddKey(out, first, "Msg");
    out.print('\"');
    jsonPrintEscaped(out, Msg);
    out.print('\"');
    jsonAddKey(out, first, "msglvl");
    out.print(msg_level);
    Msg = "";
    msg_level = NONE_MSG;
  }
  if (LogMsg.length() > 0) {
    jsonAddKey(out, first, "LogMsg");
    out.print('\"');
    jsonPrintEscaped(out, LogMsg);
    out.print('\"');
    LogMsg = "";
  }

#ifdef SAMOVAR_USE_POWER
  jsonAddKey(out, first, "current_power_volt");
  out.print(format_float(current_power_volt, 1));
  jsonAddKey(out, first, "target_power_volt");
  out.print(format_float(target_power_volt, 1));
  jsonAddKey(out, first, "current_power_mode");
  out.print('\"');
  jsonPrintEscaped(out, current_power_mode);
  out.print('\"');
  jsonAddKey(out, first, "current_power_p");
  out.print(current_power_p);
#else
  jsonAddKey(out, first, "current_power_volt");
  out.print(0);
  jsonAddKey(out, first, "target_power_volt");
  out.print(0);
  jsonAddKey(out, first, "current_power_mode");
  out.print('\"');
  out.print(0);
  out.print('\"');
  jsonAddKey(out, first, "current_power_p");
  out.print(0);
#endif

#ifdef USE_WATER_PUMP
  jsonAddKey(out, first, "wp_spd");
  out.print(water_pump_speed);
#endif

#ifdef USE_WATERSENSOR
  jsonAddKey(out, first, "WFflowRate");
  out.print(format_float(WFflowRate, 2));
  jsonAddKey(out, first, "WFtotalMl");
  out.print(WFtotalMilliLitres);
#endif

#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined(USE_PRESSURE_MPX)
  jsonAddKey(out, first, "prvl");
  out.print(format_float(pressure_value, 2));
#endif

  if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BK_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
    jsonAddKey(out, first, "alc");
    out.print(format_float(get_alcohol(TankSensor.avgTemp), 2));
    jsonAddKey(out, first, "stm_alc");
    out.print(format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2));
  }

  if (PowerOn && Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    jsonAddKey(out, first, "TimeRemaining");
    out.print(String(int(get_dist_remaining_time())));
    jsonAddKey(out, first, "TotalTime");
    out.print(String(int(get_dist_predicted_total_time())));
  }

  jsonAddKey(out, first, "Status");
  out.print('\"');
  jsonPrintEscaped(out, get_Samovar_Status());
  out.print('\"');
  jsonAddKey(out, first, "Lstatus");
  out.print('\"');
  jsonPrintEscaped(out, Lua_status);
  out.print('\"');
  out.print('}');

  request->send(response);
}

#endif
