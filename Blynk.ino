#include "Samovar.h"
#include "control_numeric_input.h"
#include "samovar_api.h"
#include "program_io.h"
#ifdef SAMOVAR_USE_BLYNK
#include <BlynkSimpleEsp32.h>

static inline void report_blynk_numeric_error(
    uint8_t virtualPin,
    NumericParseResult result) {
  String message = "Blynk V";
  message += virtualPin;
  message += ": ";
  message += numeric_parse_error_code(result.error);
  SendMsg(message, WARNING_MSG);
}

#ifdef USE_LUA
WidgetTerminal terminal(V22);

BLYNK_WRITE(V22) {
  if (mode_switch_in_progress()) return;
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
  Blynk.virtualWrite(V24, serialize_program_for_mode(Samovar_Mode));
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
  if (mode_switch_in_progress()) return;
  float maxPower = 0.0f;
#ifdef SAMOVAR_USE_SEM_AVR
  const bool semBuild = true;
#else
  const bool semBuild = false;
#endif
  NumericParseResult result = control_power_input_max(
      semBuild, SamSetup.HeaterResistant, maxPower);
  float value = 0.0f;
  if (result.ok()) result = parse_control_power(param.asStr(), maxPower, value);
  if (!result.ok()) {
    report_blynk_numeric_error(16, result);
    return;
  }
  set_current_power(value);
}
#endif

BLYNK_WRITE(V17) {
  if (mode_switch_in_progress()) return;
  uint16_t stepSpeed = 0;
  // [PKG-F] Ноль снова останавливает насос, как на HEAD: param.asFloat()==0 шёл через
  // set_pump_speed(get_speed_from_rate(0)) до внедрения строгого парсера, который
  // отвергает rate<=0. Нулевой вход обрабатываем ДО строгого парсера.
  float rate = 0.0f;
  NumericParseResult result = parse_finite_float(param.asStr(), rate);
  if (result.ok() && rate == 0.0f) {
    stepSpeed = (uint16_t)get_speed_from_rate(0);
  } else {
    result = parse_control_rate_steps(
        param.asStr(), SamSetup.StepperStepMl, stepSpeed);
  }
  if (!result.ok()) {
    report_blynk_numeric_error(17, result);
    return;
  }
  set_pump_speed(stepSpeed, true);
}

BLYNK_WRITE(V18) {
  if (mode_switch_in_progress()) return;
  set_body_temp();
}

BLYNK_WRITE(V12) {
  if (mode_switch_in_progress()) return;
  bool state = false;
  NumericParseResult result = parse_exact_bool(param.asStr(), state);
  if (!result.ok()) {
    report_blynk_numeric_error(12, result);
    return;
  }
  if (!PowerOn) return;
  if (state) {
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
  if (mode_switch_in_progress()) return;
  // [P7 п.4][P2 п.6][Ревью] PauseOn (ректификация) ИЛИ beerManualPause (пиво) - см.
  // Menu.ino menu_pause(). Пауза/возобновление - через общие хелперы enter_manual_pause()/
  // resume_from_pause() (logic.h), симметрично остальным точкам входа.
  if (PauseOn || beerManualPause) resume_from_pause();
  else enter_manual_pause();
}

BLYNK_WRITE(V3) {
  if (mode_switch_in_progress()) return;
  bool value = false;
  NumericParseResult result = parse_exact_bool(param.asStr(), value);
  if (!result.ok()) {
    report_blynk_numeric_error(3, result);
    return;
  }
  if (value && PowerOn) {
    menu_samovar_start();
  } else {
    if (!queue_samovar_reset_command()) SendMsg("Очередь команд занята: reset из Blynk не поставлен", WARNING_MSG);
  }
}
BLYNK_WRITE(V4) {
  if (mode_switch_in_progress()) return;
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
