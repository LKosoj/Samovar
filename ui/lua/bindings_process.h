#ifndef __SAMOVAR_UI_LUA_BINDINGS_PROCESS_H_
#define __SAMOVAR_UI_LUA_BINDINGS_PROCESS_H_

static int lua_wrapper_set_pause_withdrawal(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  pause_withdrawal(a);
  return 0;
}

static int lua_wrapper_set_power(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  wait_command_sync();
  int a = luaL_checkinteger(lua_state, 1);

  if (a && !PowerOn) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
      sam_command_sync = SAMOVAR_BEER;
    } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
      sam_command_sync = SAMOVAR_BK;
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
      sam_command_sync = SAMOVAR_NBK;
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
      sam_command_sync = SAMOVAR_DISTILLATION;
    } else
      sam_command_sync = SAMOVAR_POWER;
  } else if (!a && PowerOn)
    sam_command_sync = SAMOVAR_POWER;

  return 0;
}

static int lua_wrapper_set_alarm(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  set_alarm();
  return 0;
}

static int lua_wrapper_set_body_temp(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  set_body_temp();
  return 0;
}

static int lua_wrapper_set_next_program(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  wait_command_sync();
  if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
    sam_command_sync = SAMOVAR_START;
  } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
    sam_command_sync = SAMOVAR_BEER_NEXT;
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    sam_command_sync = SAMOVAR_DIST_NEXT;
  }
  return 0;
}

static int lua_wrapper_get_state(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  lua_pushnumber(lua_state, (lua_Number)SamovarStatusInt);
  return 1;
}

static int lua_wrapper_send_msg(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String st;
  const char *s;
  size_t l;
  int a = luaL_checkinteger(lua_state, 2);
  lua_getglobal(lua_state, "tostring");
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s = lua_tolstring(lua_state, -1, &l);
  st = s;
  lua_pop(lua_state, 1);
  if (a == -1) {
    WriteConsoleLog(st);
  } else {
    SendMsg(st, (MESSAGE_TYPE)a);
  }
  return 0;
}

#endif
