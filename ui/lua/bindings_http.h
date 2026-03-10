#ifndef __SAMOVAR_UI_LUA_BINDINGS_HTTP_H_
#define __SAMOVAR_UI_LUA_BINDINGS_HTTP_H_

#include <asyncHTTPrequest.h>

static int lua_wrapper_http_request(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var;
  const char *s;
  size_t l;
  int n = lua_gettop(lua_state); /* number of arguments */

  lua_getglobal(lua_state, "tostring");
  lua_pushvalue(lua_state, -1);
  lua_pushvalue(lua_state, 1);
  lua_call(lua_state, 1, 1);
  s = lua_tolstring(lua_state, -1, &l);
  Var = s;
  lua_pop(lua_state, 1);

  asyncHTTPrequest request;
  String payload;
  const uint32_t timeoutMs = 4000;
  request.setDebug(false);
  request.setTimeout(3);
  vTaskDelay(10 / portTICK_PERIOD_MS);
  if (n != 1 && n != 4) {
    lua_pushstring(lua_state, "error");
    return 1;
  }

  if (n == 1) {
    if (!request.open("GET", Var.c_str())) {
      lua_pushstring(lua_state, "error");
      return 1;
    }
    unsigned long startTime = millis();
    while (request.readyState() < 1) {
      if (millis() - startTime > timeoutMs) {
        request.abort();
        lua_pushstring(lua_state, "error");
        return 1;
      }
      vTaskDelay(25 / portTICK_PERIOD_MS);
    }
    vTaskDelay(150 / portTICK_PERIOD_MS);
    if (!request.send()) {
      request.abort();
      lua_pushstring(lua_state, "error");
      return 1;
    }
  } else {
    String ContentType;
    String Body;
    String RequestType;

    lua_pushvalue(lua_state, -1);
    lua_pushvalue(lua_state, 2);
    lua_call(lua_state, 1, 1);
    s = lua_tolstring(lua_state, -1, &l);
    RequestType = s;
    lua_pop(lua_state, 1);

    lua_pushvalue(lua_state, -1);
    lua_pushvalue(lua_state, 3);
    lua_call(lua_state, 1, 1);
    s = lua_tolstring(lua_state, -1, &l);
    ContentType = s;
    lua_pop(lua_state, 1);

    lua_pushvalue(lua_state, -1);
    lua_pushvalue(lua_state, 4);
    lua_call(lua_state, 1, 1);
    s = lua_tolstring(lua_state, -1, &l);
    Body = s;
    lua_pop(lua_state, 1);

    if (!request.open(RequestType.c_str(), Var.c_str())) {
      lua_pushstring(lua_state, "error");
      return 1;
    }
    unsigned long startTime = millis();
    while (request.readyState() < 1) {
      if (millis() - startTime > timeoutMs) {
        request.abort();
        lua_pushstring(lua_state, "error");
        return 1;
      }
      vTaskDelay(25 / portTICK_PERIOD_MS);
    }
    vTaskDelay(150 / portTICK_PERIOD_MS);
    String ctVal = getValue(ContentType, ':', 1);
    request.setReqHeader("Content-Type", ctVal.c_str());
    if (!request.send(Body)) {
      request.abort();
      lua_pushstring(lua_state, "error");
      return 1;
    }
  }

  vTaskDelay(150 / portTICK_PERIOD_MS);
  unsigned long doneStartTime = millis();
  while (request.readyState() != 4) {
    if (millis() - doneStartTime > timeoutMs) {
      request.abort();
      lua_pushstring(lua_state, "error");
      return 1;
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  if (request.responseHTTPcode() > 0) {
    payload = request.responseText();
  } else {
    payload = "error";
  }

  lua_pushstring(lua_state, payload.c_str());

  return 1;
}

#endif
