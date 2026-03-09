#ifndef __SAMOVAR_UI_WEB_ROUTES_PROGRAM_H__
#define __SAMOVAR_UI_WEB_ROUTES_PROGRAM_H__

inline void web_program(AsyncWebServerRequest *request) {
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

#endif
