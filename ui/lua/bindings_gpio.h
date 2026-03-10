#ifndef __SAMOVAR_UI_LUA_BINDINGS_GPIO_H_
#define __SAMOVAR_UI_LUA_BINDINGS_GPIO_H_

static int lua_wrapper_pinMode(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  int b = luaL_checkinteger(lua_state, 2);
  if (a == RELE_CHANNEL1 || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == LUA_PIN) pinMode(a, b);
  return 0;
}

static int lua_wrapper_digitalWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  int b = luaL_checkinteger(lua_state, 2);
  if (a == RELE_CHANNEL1 || a == WATER_PUMP_PIN || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == LUA_PIN
#ifdef ALARM_BTN_PIN
      || a == ALARM_BTN_PIN
#endif
#ifdef BTN_PIN
      || a == BTN_PIN
#endif
     ) {
    if (a != WATER_PUMP_PIN) digitalWrite(a, b);
    else {
#ifdef USE_WATER_PUMP
      if (b == LOW) {
        water_pump_speed = 0;
        pump_pwm.write(0);
      } else {
        water_pump_speed = 1023;
        pump_pwm.write(1023);
      }
#else
      digitalWrite(a, b);
#endif
    }
  }
  return 0;
}

static int lua_wrapper_digitalRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  if (a == RELE_CHANNEL1 || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == WATER_PUMP_PIN) lua_pushnumber(lua_state, (lua_Number)digitalRead(a));
  return 1;
}

static int lua_wrapper_analogRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  lua_pushnumber(lua_state, (lua_Number)analogRead(LUA_PIN));
  return 1;
}

#ifdef USE_EXPANDER
static int lua_wrapper_exp_pinMode(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  int b = luaL_checkinteger(lua_state, 2);
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    expander.pinMode(a, b);
    xSemaphoreGive(xI2CSemaphore);
  }
  return 0;
}

static int lua_wrapper_exp_digitalWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  int b = luaL_checkinteger(lua_state, 2);
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    expander.digitalWrite(a, b);
    xSemaphoreGive(xI2CSemaphore);
  }
  return 0;
}

static int lua_wrapper_exp_digitalRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    lua_pushnumber(lua_state, (lua_Number)expander.digitalRead(a));
    xSemaphoreGive(xI2CSemaphore);
  }
  return 1;
}
#endif

#ifdef USE_ANALOG_EXPANDER
static int lua_wrapper_exp_analogWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    analog_expander.analogWrite(a);
    xSemaphoreGive(xI2CSemaphore);
  }
  return 0;
}

static int lua_wrapper_exp_analogRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    lua_pushnumber(lua_state, (lua_Number)analog_expander.analogRead(a));
    xSemaphoreGive(xI2CSemaphore);
  }
  return 1;
}
#endif

#endif
