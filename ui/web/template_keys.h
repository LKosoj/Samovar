#ifndef __SAMOVAR_UI_WEB_TEMPLATE_KEYS_H__
#define __SAMOVAR_UI_WEB_TEMPLATE_KEYS_H__

#include "storage/nvs_wifi.h"

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
    else if (Samovar_Mode == SAMOVAR_NBK_MODE) return get_nbk_program();
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
  else if (var == "pwr_unit_v_only")
    return (String(PWR_TYPE) == "V") ? "block" : "none";
#ifdef USE_LUA
  if (var == "btn_list")
    return get_lua_script_list();
#endif
  else if (var == "showvideo") {
    if (strlen(SamSetup.videourl) > 0) return "inline";
    else
      return "none";
  } else if (var == "ColDiam")
    return String(SamSetup.ColDiam, 1);
  else if (var == "ColHeight")
    return String(SamSetup.ColHeight, 2);
  else if (var == "PackDens")
    return String(SamSetup.PackDens);
  else if (var == "I2CPumpTab")
    return (use_I2C_dev == 2) ? "inline-block" : "none";
  else if (var == "HeaterMaxPower") {
    float R = SamSetup.HeaterResistant;
    if (R <= 0) return "3500";
    float power = (220 * 220) / R;
    return String((int)power);
  }
  return "";
}

String setupKeyProcessor(const String &var) {
  static String s;
  s = "";
  if (var == "DeltaSteamTemp") {
    s = format_float(SamSetup.DeltaSteamTemp, 2);
    return s;
  } else if (var == "DeltaPipeTemp") {
    s = format_float(SamSetup.DeltaPipeTemp, 2);
    return s;
  } else if (var == "DeltaWaterTemp") {
    s = format_float(SamSetup.DeltaWaterTemp, 2);
    return s;
  } else if (var == "DeltaTankTemp") {
    s = format_float(SamSetup.DeltaTankTemp, 2);
    return s;
  } else if (var == "DeltaACPTemp") {
    s = format_float(SamSetup.DeltaACPTemp, 2);
    return s;
  } else if (var == "SetSteamTemp") {
    s = format_float(SamSetup.SetSteamTemp, 2);
    return s;
  } else if (var == "SetPipeTemp") {
    if (isnan(SamSetup.SetPipeTemp)) {
      SamSetup.SetPipeTemp = 0;
    }
    s = format_float(SamSetup.SetPipeTemp, 2);
    return s;
  } else if (var == "SetWaterTemp") {
    if (isnan(SamSetup.SetWaterTemp)) {
      SamSetup.SetWaterTemp = 0;
    }
    s = format_float(SamSetup.SetWaterTemp, 2);
    return s;
  } else if (var == "SetTankTemp") {
    if (isnan(SamSetup.SetTankTemp)) {
      SamSetup.SetTankTemp = 0;
    }
    s = format_float(SamSetup.SetTankTemp, 2);
    return s;
  } else if (var == "SetACPTemp") {
    if (isnan(SamSetup.SetACPTemp)) {
      SamSetup.SetACPTemp = 0;
    }
    s = format_float(SamSetup.SetACPTemp, 2);
    return s;
  } else if (var == "StepperStepMl") {
    s = SamSetup.StepperStepMl;
    return s;
  } else if (var == "StepperStepMlI2C") {
    s = SamSetup.StepperStepMlI2C;
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
  } else if (var == "tgtoken") {
    s = SamSetup.tg_token;
    return s;
  } else if (var == "tgchatid") {
    s = SamSetup.tg_chat_id;
    return s;
  } else if (var == "BVolt") {
    s = SamSetup.BVolt;
    return s;
  } else if (var == "DistTimeF") {
    s = SamSetup.DistTimeF;
    return s;
  } else if (var == "MaxPressureValue") {
    s = SamSetup.MaxPressureValue;
    return s;
  } else if (var == "NbkIn") {
    s = SamSetup.NbkIn;
    return s;
  } else if (var == "NbkDelta") {
    s = SamSetup.NbkDelta;
    return s;
  } else if (var == "NbkDM") {
    s = SamSetup.NbkDM;
    return s;
  } else if (var == "NbkDP") {
    s = SamSetup.NbkDP;
    return s;
  } else if (var == "NbkSteamT") {
    s = SamSetup.NbkSteamT;
    return s;
  } else if (var == "NbkOwPress") {
    s = SamSetup.NbkOwPress;
    return s;
  } else if (var == "Checked") {
    if (SamSetup.UsePreccureCorrect) return "checked='true'";
    else
      return "";
  } else if (var == "FLChecked") {
    if (SamSetup.UseHLS) return "checked='true'";
    else
      return "";
#ifdef IGNORE_HEAD_LEVEL_SENSOR_SETTING
  } else if (var == "IgnFL") {
    return F("style="
             "display: none"
             "");
#endif
  } else if (var == "UASChecked") {
    if (SamSetup.useautospeed) return "checked='true'";
    else
      return "";
  } else if (var == "UASHeadsChecked") {
    if (SamSetup.useDetectorOnHeads) return "checked='true'";
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
  } else if (var == "CUBBuzz") {
    if (SamSetup.UseBBuzzer) return "checked='true'";
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
    s = format_float(SamSetup.DistTemp, 2);
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
  else if (var == "NBK" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_NBK_MODE)
    return "selected";
  else if (var == "SUVID" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_SUVID_MODE)
    return "selected";
  else if (var == "LUA_MODE" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_LUA_MODE)
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
  else if (var == "ColDiam")
    return String(SamSetup.ColDiam, 1);
  else if (var == "ColDiam_1.5") {
    if (abs(SamSetup.ColDiam - 1.5f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColDiam_2.0") {
    if (abs(SamSetup.ColDiam - 2.0f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColDiam_3.0") {
    if (abs(SamSetup.ColDiam - 3.0f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight")
    return String(SamSetup.ColHeight, 2);
  else if (var == "ColHeight_0.50") {
    if (abs(SamSetup.ColHeight - 0.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_0.75") {
    if (abs(SamSetup.ColHeight - 0.75f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.00") {
    if (abs(SamSetup.ColHeight - 1.00f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.25") {
    if (abs(SamSetup.ColHeight - 1.25f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.50") {
    if (abs(SamSetup.ColHeight - 1.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.75") {
    if (abs(SamSetup.ColHeight - 1.75f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.00") {
    if (abs(SamSetup.ColHeight - 2.00f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.25") {
    if (abs(SamSetup.ColHeight - 2.25f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.50") {
    if (abs(SamSetup.ColHeight - 2.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "PackDens")
    return String(SamSetup.PackDens);
  else if (var == "I2CPumpTab")
    return (use_I2C_dev == 2) ? "inline-block" : "none";
  return "";
}

String wifiKeyProcessor(const String &var) {
  if (var == "wifi_ssid") {
    String ssid = get_wifi_ssid();
    if (ssid.length() == 0) return String("-");
    return ssid;
  }
  return "";
}

String calibrateKeyProcessor(const String &var) {
  if (var == "StepperStep") return (String)STEPPER_MAX_SPEED;
  else if (var == "StepperStepMl")
    return (String)(SamSetup.StepperStepMl * 100);
  else if (var == "StepperStepMlI2C")
    return (String)(SamSetup.StepperStepMlI2C * 100);
  else if (var == "I2CPumpTab")
    return (use_I2C_dev == 2) ? "inline-block" : "none";

  return String();
}

#endif
