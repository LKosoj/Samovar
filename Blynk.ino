#include "Samovar.h"
#include "samovar_api.h"
#ifdef SAMOVAR_USE_BLYNK
#include <BlynkSimpleEsp32.h>

#ifdef USE_LUA
WidgetTerminal terminal(V22);

BLYNK_WRITE(V22) {
  String lstr = param.asStr();  // assigning incoming value from pin V22 to a variable
  terminal.println(lstr);
  lstr = run_lua_string(lstr);
  if (lstr.length() > 0) {
    terminal.println("ERR in lua: " + lstr);
  }
  else {
    terminal.println(F("Lua queued"));
  }
  terminal.flush();
}
#endif

BLYNK_READ(V0) {
  static bool inReadHandler = false;
  if (inReadHandler) return; // Предотвращаем рекурсию
  inReadHandler = true;
  
  vTaskDelay(2 / portTICK_PERIOD_MS);
  Blynk.virtualWrite(V0, SteamSensor.avgTemp);
  vTaskDelay(2 / portTICK_PERIOD_MS);
  Blynk.virtualWrite(V4, PowerOn);
  int i;
  int k;
  if (startval > 0 && startval < 5)
    i = 1;
  else
    i = 0;
  Blynk.virtualWrite(V3, i);
  vTaskDelay(2 / portTICK_PERIOD_MS);
  if (PauseOn)
    k = 1;
  else
    k = 0;
  Blynk.virtualWrite(V13, k);
  
  inReadHandler = false;
}

BLYNK_READ(V1) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V1, PipeSensor.avgTemp);
  inReadHandler = false;
}

BLYNK_READ(V25) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V25, ACPSensor.avgTemp);
  inReadHandler = false;
}

BLYNK_READ(V2) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V2, WthdrwlProgress);
  inReadHandler = false;
}

BLYNK_READ(V5) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V5, bme_pressure);
  inReadHandler = false;
}

BLYNK_READ(V6) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V6, WaterSensor.avgTemp);
  inReadHandler = false;
}

BLYNK_READ(V7) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V7, TankSensor.avgTemp);
  inReadHandler = false;
}

BLYNK_READ(V8) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V8, get_liquid_volume());
  inReadHandler = false;
}

BLYNK_READ(V9) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V9, ActualVolumePerHour);
  inReadHandler = false;
}

BLYNK_READ(V10) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  // [C-1] Читаем строки времени под замком.
  {
    String timesCopy;
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      timesCopy = WthdrwTimeS + "; " + WthdrwTimeAllS;
      runtime_state_unlock(true);
    }
    Blynk.virtualWrite(V10, timesCopy);
  }
  inReadHandler = false;
}

BLYNK_READ(V11) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  // [C-1] Читаем строку StrCrt под замком.
  {
    String strCrtCopy;
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      strCrtCopy = StrCrt;
      runtime_state_unlock(true);
    }
    Blynk.virtualWrite(V11, strCrtCopy);
  }
  inReadHandler = false;
}

BLYNK_READ(V14) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  // [C-2] Читаем кэш SamovarStatus под замком; FSM продвигает его раз в секунду
  // из секундного гейта triggerSysTicker (core 0) через get_Samovar_Status().
  {
    String statusCopy;
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      statusCopy = SamovarStatus;
      runtime_state_unlock(true);
    }
    Blynk.virtualWrite(V14, statusCopy);
  }
  inReadHandler = false;
}

BLYNK_READ(V15) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V15, ipst);
  inReadHandler = false;
}

BLYNK_READ(V19) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V19, SAMOVAR_VERSION);
  inReadHandler = false;
}

BLYNK_READ(V20) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V20, Samovar_Mode);
  inReadHandler = false;
}

BLYNK_READ(V24) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
    Blynk.virtualWrite(V24, get_beer_program());
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    Blynk.virtualWrite(V24, get_dist_program());
  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
    Blynk.virtualWrite(V24, get_nbk_program());
  } else {
    Blynk.virtualWrite(V24, get_program(PROGRAM_END));
  }
  inReadHandler = false;
}

#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX) || defined(USE_PRESSURE_1WIRE)
BLYNK_READ(V23) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V23, pressure_value);
  inReadHandler = false;
}
#endif

#ifdef SAMOVAR_USE_POWER
BLYNK_READ(V21) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V21, "Тек:" + (String)current_power_volt + " Цель:" + (String)target_power_volt);
  inReadHandler = false;
}
#endif

#ifdef SAMOVAR_USE_POWER
BLYNK_READ(V16) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V16, target_power_volt);
  inReadHandler = false;
}

BLYNK_WRITE(V16) {
  float Value16 = param.asFloat();  // assigning incoming value from pin V16 to a variable
  set_current_power(Value16);
}
#endif

BLYNK_WRITE(V17) {
  float Value17 = param.asFloat();  // assigning incoming value from pin V17 to a variable
  set_pump_speed(get_speed_from_rate(Value17), true);
}

BLYNK_WRITE(V18) {
  set_body_temp();
}

BLYNK_WRITE(V12) {
  if (!PowerOn) return;
  int State = param.asInt();
  if (State == 1) {
    SamovarCommands command = SAMOVAR_START;
    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      command = SAMOVAR_BEER_NEXT;
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      command = SAMOVAR_DIST_NEXT;
    }
    if (!queue_samovar_command(command)) {
      SendMsg("Очередь команд занята: команда Blynk V12 не поставлена", WARNING_MSG);
    }
  }
}

BLYNK_WRITE(V13) {
  pause_withdrawal(!PauseOn);
  t_min = 0;
  program_Wait = false;
}

BLYNK_WRITE(V3) {
  int Value3 = param.asInt();  // assigning incoming value from pin V3 to a variable
  if (Value3 == 1 && PowerOn) {
    menu_samovar_start();
  } else {
    if (!queue_samovar_reset_command()) SendMsg("Очередь команд занята: reset из Blynk не поставлен", WARNING_MSG);
  }
}
BLYNK_WRITE(V4) {
  //int Value4 = param.asInt();  // assigning incoming value from pin V4 to a variable
  SamovarCommands command = SAMOVAR_POWER;
  if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
    command = SAMOVAR_BEER;
  } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
    command = SAMOVAR_BK;
  } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
    command = SAMOVAR_NBK;
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
    command = SAMOVAR_DISTILLATION;
  }
  if (!queue_samovar_command(command)) {
    SendMsg("Очередь команд занята: команда Blynk V4 не поставлена", WARNING_MSG);
  }
  //set_power(Value4);
}

#endif
