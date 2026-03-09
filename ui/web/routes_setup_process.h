#ifndef __SAMOVAR_UI_WEB_ROUTES_SETUP_PROCESS_H__
#define __SAMOVAR_UI_WEB_ROUTES_SETUP_PROCESS_H__

inline void handleSaveProcessSettings(AsyncWebServerRequest *request) {
  if (!request->hasArg("mode")) {
    return;
  }

  int nextMode = request->arg("mode").toInt();
  if (SamSetup.Mode == nextMode) {
    return;
  }

  if (PowerOn) {
    if (SamovarStatusInt == 1000) {
      distiller_finish();
    } else if (SamovarStatusInt == 2000) {
      beer_finish();
    } else if (SamovarStatusInt == 3000) {
      bk_finish();
    } else if (SamovarStatusInt == 4000) {
      nbk_finish();
    } else {
      set_power(false);
    }
  }

#ifdef USE_LUA
  if (loop_lua_fl) {
    SetScriptOff = true;
    loop_lua_fl = false;
    delay(100);
  }
#endif

  samovar_reset();

  SamSetup.Mode = nextMode;
  Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;
  Samovar_CR_Mode = Samovar_Mode;

  load_default_program_for_mode();
  save_profile();
  load_profile();

#ifdef USE_LUA
  lua_type_script = get_lua_mode_name();
  load_lua_script();
#endif

  change_samovar_mode();
}

#endif
