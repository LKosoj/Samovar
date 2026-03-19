#ifndef __SAMOVAR_UI_WEB_ROUTES_PROGRAM_H__
#define __SAMOVAR_UI_WEB_ROUTES_PROGRAM_H__

#include "app/default_programs.h"

inline void web_program(AsyncWebServerRequest *request) {
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
  if (request->hasArg("WProgram")) {
    set_program_for_mode(Samovar_Mode, request->arg("WProgram"));
  }
  request->send(200, "text/plain", get_program_for_mode(Samovar_Mode));
}

#endif
