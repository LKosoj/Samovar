#ifndef __SAMOVAR_UI_LUA_BINDINGS_VARIABLES_H_
#define __SAMOVAR_UI_LUA_BINDINGS_VARIABLES_H_

#include <TimeLib.h>

inline void wait_command_sync() {
  while (sam_command_sync != SAMOVAR_NONE) {
    vTaskDelay(100 / portTICK_PERIOD_MS);
  }
}

static int lua_wrapper_delay(lua_State *lua_state) {
  int a = luaL_checkinteger(lua_state, 1);
  vTaskDelay(a / portTICK_PERIOD_MS);
  return 0;
}

static int lua_wrapper_millis(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  lua_pushnumber(lua_state, (lua_Number)millis());
  return 1;
}

static int lua_wrapper_set_num_variable(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var;
  const char *s;
  size_t l;
  float a = luaL_checknumber(lua_state, 2);
  lua_getglobal(lua_state, "tostring");
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s = lua_tolstring(lua_state, -1, &l);
  Var = s;
  lua_pop(lua_state, 1);

  if (Var == "WFpulseCount") {
    WFpulseCount = (byte)a;
  } else if (Var == "pump_started") {
    pump_started = (int)a;
  } else if (Var == "valve_status") {
    valve_status = (int)a;
  } else if (Var == "SamSetup_Mode") {
    SamSetup.Mode = (int)a;
  } else if (Var == "Samovar_Mode") {
    Samovar_Mode = (SAMOVAR_MODE)a;
  } else if (Var == "Samovar_CR_Mode") {
    Samovar_CR_Mode = (SAMOVAR_MODE)a;
  } else if (Var == "acceleration_temp") {
    acceleration_temp = (uint16_t)a;
#ifdef USE_WATER_PUMP
  } else if (Var == "wp_count") {
    wp_count = (byte)a;
  } else if (Var == "pmpKp") {
    pump_regulator.Kp = (byte)a;
  } else if (Var == "pmpKi") {
    pump_regulator.Ki = (byte)a;
  } else if (Var == "pmpKd") {
    pump_regulator.Kd = (byte)a;
#endif
  } else if (Var == "SteamTemp") {
    SteamSensor.avgTemp = a;
  } else if (Var == "boil_temp") {
    boil_temp = a;
  } else if (Var == "PipeTemp") {
    PipeSensor.avgTemp = a;
  } else if (Var == "WaterTemp") {
    WaterSensor.avgTemp = a;
  } else if (Var == "TankTemp") {
    TankSensor.avgTemp = a;
  } else if (Var == "ACPTemp") {
    ACPSensor.avgTemp = a;
  } else if (Var == "loop_lua_fl") {
    loop_lua_fl = (int)a;
  } else if (Var == "SetScriptOff") {
    SetScriptOff = (bool)a;
  } else if (Var == "show_lua_script") {
    show_lua_script = (int)a;
  } else if (Var == "test_num_val") {
    test_num_val = a;
  } else if (Var.length() > 0) {
    WriteConsoleLog("UNDEF NUMERIC LUA VAR " + Var + " = " + a);
  }
  return 0;
}

static int lua_wrapper_get_num_variable(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var;
  const char *s;
  size_t l;
  lua_getglobal(lua_state, "tostring");
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s = lua_tolstring(lua_state, -1, &l);
  Var = s;
  lua_pop(lua_state, 1);
  float a = 0;
  if (Var == "WFpulseCount") {
    a = WFpulseCount;
  } else if (Var == "pump_started") {
    a = pump_started;
  } else if (Var == "valve_status") {
    a = valve_status;
  } else if (Var == "SamSetup_Mode") {
    a = SamSetup.Mode;
  } else if (Var == "Samovar_Mode") {
    a = Samovar_Mode;
  } else if (Var == "Samovar_CR_Mode") {
    a = Samovar_CR_Mode;
  } else if (Var == "boil_temp") {
    a = boil_temp;
  } else if (Var == "acceleration_temp") {
    a = acceleration_temp;
#ifdef USE_WATER_PUMP
  } else if (Var == "wp_count") {
    a = wp_count;
#endif
  } else if (Var == "WFtotalMilliLitres") {
    a = WFtotalMilliLitres;
  } else if (Var == "WFflowRate") {
    a = WFflowRate;
  } else if (Var == "SteamTemp") {
    a = SteamSensor.avgTemp;
  } else if (Var == "PipeTemp") {
    a = PipeSensor.avgTemp;
  } else if (Var == "WaterTemp") {
    a = WaterSensor.avgTemp;
  } else if (Var == "TankTemp") {
    a = TankSensor.avgTemp;
  } else if (Var == "ACPTemp") {
    a = ACPSensor.avgTemp;
  } else if (Var == "loop_lua_fl") {
    a = loop_lua_fl;
  } else if (Var == "show_lua_script") {
    a = show_lua_script;
  } else if (Var == "SetScriptOff") {
    a = SetScriptOff;
  } else if (Var == "program_volume") {
    a = program[ProgramNum].Volume;
  } else if (Var == "program_speed") {
    a = program[ProgramNum].Speed;
  } else if (Var == "program_temp") {
    a = program[ProgramNum].Temp;
  } else if (Var == "program_power") {
    a = program[ProgramNum].Power;
  } else if (Var == "program_time") {
    a = program[ProgramNum].Time;
  } else if (Var == "program_capacity_num") {
    a = program[ProgramNum].capacity_num;
  } else if (Var == "capacity_num") {
    a = capacity_num;
  } else if (Var == "target_power_volt") {
    a = target_power_volt;
  } else if (Var == "PowerOn") {
    a = PowerOn;
  } else if (Var == "alcohol") {
    a = get_alcohol(TankSensor.avgTemp);
  } else if (Var == "alcohol_s") {
    a = alcohol_s;
  } else if (Var == "water_pump_speed") {
    a = water_pump_speed;
  } else if (Var == "pressure_value") {
    a = pressure_value;
  } else if (Var == "PauseOn") {
    a = PauseOn;
  } else if (Var == "program_Wait") {
    a = program_Wait;
  } else if (Var == "YY") {
    a = year(time(NULL));
  } else if (Var == "MM") {
    a = month(time(NULL));
  } else if (Var == "DD") {
    a = day(time(NULL));
  } else if (Var == "HH") {
    a = hour(time(NULL)) + SamSetup.TimeZone;
  } else if (Var == "MI") {
    a = minute(time(NULL));
  } else if (Var == "SS") {
    a = second(time(NULL));
  } else if (Var == "test_num_val") {
    a = test_num_val;
  } else if (Var.length() > 0) {
    WriteConsoleLog("GET UNDEF NUMERIC LUA VAR " + Var);
  }
  lua_pushnumber(lua_state, (lua_Number)a);
  return 1;
}

static int lua_wrapper_set_str_variable(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var, Val;
  lua_getglobal(lua_state, "tostring");

  const char *s1;
  size_t l1;
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s1 = lua_tolstring(lua_state, -1, &l1);
  Var = s1;
  lua_pop(lua_state, 1);

  const char *s2;
  size_t l2;
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 2);
  lua_call(lua_state, 1, 1);
  s2 = lua_tolstring(lua_state, -1, &l2);
  Val = s2;
  lua_pop(lua_state, 1);

  if (Var == "Msg") {
    Msg = Val;
  } else if (Var == "SamovarStatus") {
    SamovarStatus = Val;
  } else if (Var == "test_str_val") {
    test_str_val = Val;
  } else if (Var == "program_type") {
    WriteConsoleLog(F("WARNING! program_type is read only property"));
  } else if (Var.length() > 0) {
    WriteConsoleLog("UNDEF STRING LUA VAR " + Var + " = " + Val);
  }
  return 0;
}

static int lua_wrapper_get_str_variable(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var;
  const char *s;
  size_t l;
  lua_getglobal(lua_state, "tostring");
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s = lua_tolstring(lua_state, -1, &l);
  Var = s;
  lua_pop(lua_state, 1);
  String c;
  if (Var == "Msg") {
    c = Msg;
  } else if (Var == "SamovarStatus") {
    c = SamovarStatus;
  } else if (Var == "test_str_val") {
    c = test_str_val;
  } else if (Var == "program_type") {
    c = program[ProgramNum].WType;
  } else if (Var.length() > 0) {
    WriteConsoleLog("UNDEF GET STRING LUA VAR " + Var);
    return 0;
  }
  lua_pushstring(lua_state, c.c_str());
  return 1;
}

static int lua_wrapper_set_object(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var, Val;
  lua_getglobal(lua_state, "tostring");

  const char *s1;
  size_t l1;
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s1 = lua_tolstring(lua_state, -1, &l1);
  Var = s1;
  lua_pop(lua_state, 1);

  const char *s2;
  size_t l2;
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 2);
  lua_call(lua_state, 1, 1);
  s2 = lua_tolstring(lua_state, -1, &l2);
  Val = s2;
  lua_pop(lua_state, 1);

  luaObj->put(Var, Val);
  return 0;
}

static int lua_wrapper_get_object(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var, Type;
  const char *s;
  int n = lua_gettop(lua_state);
  size_t l;
  lua_getglobal(lua_state, "tostring");
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s = lua_tolstring(lua_state, -1, &l);
  Var = s;
  lua_pop(lua_state, 1);

  String v = luaObj->get(Var);
  if (n == 2) {
    const char *s2;
    size_t l2;
    lua_pushvalue(lua_state, -1);
    lua_pushvalue(lua_state, 2);
    lua_call(lua_state, 1, 1);
    s2 = lua_tolstring(lua_state, -1, &l2);
    Type = s2;
    lua_pop(lua_state, 1);
    if (Type == "NUMERIC" && v.length() == 0) {
      v = "0";
    }
  }

  lua_pushstring(lua_state, v.c_str());
  return 1;
}

static int lua_wrapper_set_lua_status(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var;
  lua_getglobal(lua_state, "tostring");

  const char *s1;
  size_t l1;
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s1 = lua_tolstring(lua_state, -1, &l1);
  Var = s1;
  lua_pop(lua_state, 1);
  Lua_status = Var;
  return 0;
}

static int lua_wrapper_set_timer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checknumber(lua_state, 1);
  a--;
  if (a <= 0 || a > 9) return 0;
  uint16_t b = luaL_checknumber(lua_state, 2);
  lua_timer[a] = millis() + b * 1000;
  return 0;
}

static int lua_wrapper_get_timer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checknumber(lua_state, 1);
  uint16_t b;
  a--;
  if (a <= 0 || a > 9) {
    b = 0;
  } else if (lua_timer[a] == 0) {
    b = 0;
  } else {
    long l = lua_timer[a] - millis();
    if (l <= 0) {
      b = 0;
      lua_timer[a] = 0;
    } else {
      b = l / 1000;
    }
  }
  lua_pushnumber(lua_state, (lua_Number)b);
  return 1;
}

#endif
