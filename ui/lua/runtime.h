#ifndef __SAMOVAR_UI_LUA_RUNTIME_H_
#define __SAMOVAR_UI_LUA_RUNTIME_H_

#include "lua.h"

inline void lua_init() {
  lua.Lua_register("pinMode", (const lua_CFunction)&lua_wrapper_pinMode);
  lua.Lua_register("digitalWrite", (const lua_CFunction)&lua_wrapper_digitalWrite);
  lua.Lua_register("digitalRead", (const lua_CFunction)&lua_wrapper_digitalRead);
  lua.Lua_register("analogRead", (const lua_CFunction)&lua_wrapper_analogRead);
#ifdef USE_EXPANDER
  lua.Lua_register("exp_pinMode", (const lua_CFunction)&lua_wrapper_exp_pinMode);
  lua.Lua_register("exp_digitalWrite", (const lua_CFunction)&lua_wrapper_exp_digitalWrite);
  lua.Lua_register("exp_digitalRead", (const lua_CFunction)&lua_wrapper_exp_digitalRead);
#endif
#ifdef USE_ANALOG_EXPANDER
  lua.Lua_register("exp_analogWrite", (const lua_CFunction)&lua_wrapper_exp_analogWrite);
  lua.Lua_register("exp_analogRead", (const lua_CFunction)&lua_wrapper_exp_analogRead);
#endif
  lua.Lua_register("delay", (const lua_CFunction)&lua_wrapper_delay);
  lua.Lua_register("millis", (const lua_CFunction)&lua_wrapper_millis);
  lua.Lua_register("sendMsg", (const lua_CFunction)&lua_wrapper_send_msg);

  lua.Lua_register("setPower", (const lua_CFunction)&lua_wrapper_set_power);
  lua.Lua_register("setBodyTemp", (const lua_CFunction)&lua_wrapper_set_body_temp);
  lua.Lua_register("setAlarm", (const lua_CFunction)&lua_wrapper_set_alarm);
  lua.Lua_register("setNumVariable", (const lua_CFunction)&lua_wrapper_set_num_variable);
  lua.Lua_register("setStrVariable", (const lua_CFunction)&lua_wrapper_set_str_variable);
  lua.Lua_register("setObject", (const lua_CFunction)&lua_wrapper_set_object);
  lua.Lua_register("setLuaStatus", (const lua_CFunction)&lua_wrapper_set_lua_status);
#ifdef USE_WATER_PUMP
  lua.Lua_register("setPumpPwm", (const lua_CFunction)&lua_wrapper_set_pump_pwm);
#endif
#ifdef SAMOVAR_USE_POWER
  lua.Lua_register("setCurrentPower", (const lua_CFunction)&lua_wrapper_set_current_power);
#endif
  lua.Lua_register("setMixer", (const lua_CFunction)&lua_wrapper_set_mixer);
  lua.Lua_register("setNextProgram", (const lua_CFunction)&lua_wrapper_set_next_program);
  lua.Lua_register("setPauseWithdrawal", (const lua_CFunction)&lua_wrapper_set_pause_withdrawal);
  lua.Lua_register("setTimer", (const lua_CFunction)&lua_wrapper_set_timer);
  lua.Lua_register("setCapacity", (const lua_CFunction)&lua_wrapper_set_capacity);

  lua.Lua_register("openValve", (const lua_CFunction)&lua_wrapper_open_valve);

  lua.Lua_register("getNumVariable", (const lua_CFunction)&lua_wrapper_get_num_variable);
  lua.Lua_register("getStrVariable", (const lua_CFunction)&lua_wrapper_get_str_variable);
  lua.Lua_register("getState", (const lua_CFunction)&lua_wrapper_get_state);
  lua.Lua_register("getObject", (const lua_CFunction)&lua_wrapper_get_object);
  lua.Lua_register("getTimer", (const lua_CFunction)&lua_wrapper_get_timer);
  lua.Lua_register("http_request", (const lua_CFunction)&lua_wrapper_http_request);

  lua.Lua_register("check_I2C_device", (const lua_CFunction)&lua_wrapper_check_I2C_device);
  lua.Lua_register("set_stepper_by_time", (const lua_CFunction)&lua_wrapper_set_stepper_by_time);
  lua.Lua_register("set_stepper_target", (const lua_CFunction)&lua_wrapper_set_stepper_target);
  lua.Lua_register("get_stepper_status", (const lua_CFunction)&lua_wrapper_get_stepper_status);
  lua.Lua_register("i2cpump_start", (const lua_CFunction)&lua_wrapper_i2cpump_start);
  lua.Lua_register("i2cpump_stop", (const lua_CFunction)&lua_wrapper_i2cpump_stop);
  lua.Lua_register("i2cpump_get_speed", (const lua_CFunction)&lua_wrapper_i2cpump_get_speed);
  lua.Lua_register("i2cpump_get_target_ml", (const lua_CFunction)&lua_wrapper_i2cpump_get_target_ml);
  lua.Lua_register("i2cpump_get_remaining_ml", (const lua_CFunction)&lua_wrapper_i2cpump_get_remaining_ml);
  lua.Lua_register("i2cpump_get_running", (const lua_CFunction)&lua_wrapper_i2cpump_get_running);
  lua.Lua_register("set_mixer_pump_target", (const lua_CFunction)&lua_wrapper_set_mixer_pump_target);
  lua.Lua_register("get_mixer_pump_status", (const lua_CFunction)&lua_wrapper_get_mixer_pump_status);

  lua.Lua_register("get_i2c_rele_state", (const lua_CFunction)&lua_wrapper_get_i2c_rele_state);
  lua.Lua_register("set_i2c_rele_state", (const lua_CFunction)&lua_wrapper_set_i2c_rele_state);

  loop_lua_fl = 0;
  SetScriptOff = false;

  lua_State *L = lua.GetState();
  lua_gc(L, LUA_GCSETPAUSE, 120);
  lua_gc(L, LUA_GCSETSTEPMUL, 200);

  File f = SPIFFS.open("/init.lua");
  if (f) {
    String script;
    script = get_global_variables();
    script += f.readString();
    f.close();
    if (show_lua_script) {
      WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
      WriteConsoleLog(script);
      WriteConsoleLog(F("--END LUA SCRIPT--"));
    }
    String sr = lua.Lua_dostring(&script);
    if (sr.length() > 0) WriteConsoleLog("INI ERR " + sr);
  }
  lua_type_script = get_lua_mode_name();
  lua_finished = true;

  load_lua_script();

  xTaskCreatePinnedToCore(
    do_lua_script,
    "do_lua_script",
    5900,
    NULL,
    1,
    &DoLuaScriptTask,
    1);
}

#endif
