#include <LuaWrapper.h>

LuaWrapper lua;

static int lua_wrapper_pinMode(lua_State *lua_state) {
  int a = luaL_checkinteger(lua_state, 1);
  int b = luaL_checkinteger(lua_state, 2);
  pinMode(a, b);
  return 0;
}

static int lua_wrapper_digitalWrite(lua_State *lua_state) {
  int a = luaL_checkinteger(lua_state, 1);
  int b = luaL_checkinteger(lua_state, 2);
  digitalWrite(a, b);
  return 0;
}
  
static int lua_wrapper_delay(lua_State *lua_state) {
  int a = luaL_checkinteger(lua_state, 1);
  delay(a);
  return 0;
}

static int lua_wrapper_millis(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number) millis());
  return 1;
}

void setup() {
  lua.Lua_register("pinMode", (const lua_CFunction) &lua_wrapper_pinMode);
  lua.Lua_register("digitalWrite", (const lua_CFunction) &lua_wrapper_digitalWrite);
  lua.Lua_register("delay", (const lua_CFunction) &lua_wrapper_delay);
  lua.Lua_register("millis", (const lua_CFunction) &lua_wrapper_millis);
  Serial.begin(115200);
}

void loop() {
  String script = "";
  char c = 0;
  Serial.println();
  Serial.println("# Enter the lua script and press Control-D when finished:");
  while(1) {
    if(Serial.available() > 0) {
      c = Serial.read();
      if(c == 4) {
        break;
      }
      Serial.write(c);
      script += c;
      if(c == '\r') {
        Serial.write('\n');
        script += '\n';
      }
    }   
  }
  if(script.length() > 0) {
    Serial.println();
    Serial.println("# Executing script:");
    Serial.println(lua.Lua_dostring(&script));
  }
}
