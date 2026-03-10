#ifndef __SAMOVAR_UI_WEB_ROUTES_COMMAND_H__
#define __SAMOVAR_UI_WEB_ROUTES_COMMAND_H__

#include <Arduino.h>
#include <ESPAsyncWebServer.h>

#include "Samovar.h"
#include "state/globals.h"
#include "modes/bk/bk_water_control.h"
#include "io/actuators.h"

// Forward declaration для set_water_temp (inline функция)
void set_water_temp(float duty);
#include "io/power_control.h"
#include "modes/nbk/nbk_math.h"
#include "modes/nbk/nbk_state.h"

#ifdef USE_LUA
void run_lua_script(String fn);
void run_lua_string(String lstr);
#endif
void menu_reset_wifi();
void scan_ds_adress();
void set_mixer(bool On);
uint16_t get_stepper_speed(void);
uint32_t get_stepper_status(void);
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
float i2c_get_speed_from_rate(float volume_per_hour);
float get_speed_from_rate(float rate);
void set_pump_speed(float pumpspeed, bool continue_process);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void stop_self_test();
#ifdef SAMOVAR_USE_POWER
void set_current_power(float Volt);
#endif

inline void web_command(AsyncWebServerRequest *request) {
  // Защита от повторных команд
  static uint32_t last_command_time = 0;
  if (millis() - last_command_time < 1500) {
    request->send(200, "text/plain", "OK");
    return;
  }
  last_command_time = millis();
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
  if (request->hasArg("start") && PowerOn) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      sam_command_sync = SAMOVAR_BEER_NEXT;
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      sam_command_sync = SAMOVAR_DIST_NEXT;
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      sam_command_sync = SAMOVAR_NBK_NEXT;
    } else {
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
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      if (!PowerOn) sam_command_sync = SAMOVAR_NBK;
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
  } else if (request->hasArg("rescands")) {
    scan_ds_adress();
  } else if (request->hasArg("stopst")) {
    stop_self_test();
  } else if (request->hasArg("mixer")) {
    if (request->arg("mixer").toInt() == 1) {
      set_mixer(true);
    } else {
      set_mixer(false);
    }
  } else if (request->hasArg("pnbk") && PowerOn) {
    if (request->arg("pnbk").toInt() == 9000) { // повышаем скорость насоса на один шаг
      set_stepper_target(get_stepper_speed() + i2c_get_speed_from_rate(float(SamSetup.NbkDP) + 0.0001), 0, 2147483640);
      // Serial.println("pnbk inc");
      // Serial.println(get_stepper_speed());
      // Serial.println(i2c_get_speed_from_rate(float(SamSetup.NbkDP)));
      // Serial.println(get_stepper_speed());
      // Serial.println(i2c_get_liquid_rate_by_step(get_stepper_speed()));
    } else if (request->arg("pnbk").toInt() == 8000) { // понижаем скорость насоса на один шаг
      if (get_stepper_speed() - i2c_get_speed_from_rate(0.0499) < 0) {
        set_stepper_target(0, 0, 0);
      } else {
        set_stepper_target(get_stepper_speed() - i2c_get_speed_from_rate(float(SamSetup.NbkDP) - 0.0001), 0, 2147483640);
      }
    } else if (request->arg("pnbk").toFloat() >= 0 && request->arg("pnbk").toInt() < 8000) { // устанавливаем заказанную скорость насоса
      set_stepper_target(i2c_get_speed_from_rate(float(request->arg("pnbk").toFloat()) + 0.0001), 0, 2147483640);
    }
  } else if (request->hasArg("nbkopt") && PowerOn) { // устанавливаем текущие М и Р как оптимальные Мо и Ро
    nbk_Mo = nbk_M;
    nbk_Po = nbk_P;
#ifdef SAMOVAR_USE_POWER
    SendMsg("Установлены оптимальные значения: " + String(fromPower(nbk_Mo), 0) + String(PWR_SIGN) + ",  " + String(nbk_Po, 1) + " л/ч", WARNING_MSG);
#endif
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
  } else if (request->hasArg("startnbk")) {
    if (request->arg("startnbk").toInt() == 1) {
      sam_command_sync = SAMOVAR_NBK;
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
  } else if (request->hasArg("luastr")) {
    String lstr = request->arg("luastr");
    lstr.replace("^", " ");
    run_lua_string(lstr);
  }
#endif
  request->send(200, "text/plain", "OK");
}

#endif
