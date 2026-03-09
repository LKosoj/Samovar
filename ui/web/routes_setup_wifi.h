#ifndef __SAMOVAR_UI_WEB_ROUTES_SETUP_WIFI_H__
#define __SAMOVAR_UI_WEB_ROUTES_SETUP_WIFI_H__

inline void handleSaveWifiSettings(AsyncWebServerRequest *request) {
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
}

#endif
