#ifndef __SAMOVAR_UI_LUA_BINDINGS_IO_H_
#define __SAMOVAR_UI_LUA_BINDINGS_IO_H_

static int lua_wrapper_set_mixer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  set_mixer(a);
  return 0;
}

static int lua_wrapper_open_valve(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  bool a = luaL_checkinteger(lua_state, 1);
  open_valve(a, false);
  return 0;
}

#ifdef SAMOVAR_USE_POWER
static int lua_wrapper_set_current_power(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  float a = luaL_checknumber(lua_state, 1);
  set_current_power(a);
  return 0;
}
#endif

static int lua_wrapper_set_capacity(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checknumber(lua_state, 1);
  set_capacity(a);
  return 0;
}

#ifdef USE_WATER_PUMP
static int lua_wrapper_set_pump_pwm(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checknumber(lua_state, 1);
  pump_pwm.write(a);
  water_pump_speed = a;
  return 0;
}
#endif

static int lua_wrapper_set_stepper_by_time(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint16_t a = luaL_checkinteger(lua_state, 1);
  uint8_t b = luaL_checkinteger(lua_state, 2);
  uint16_t c = luaL_checkinteger(lua_state, 3);
  lua_pushnumber(lua_state, (lua_Number)set_stepper_by_time(a, b, c));
  return 1;
}

static int lua_wrapper_set_stepper_target(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint16_t a = luaL_checkinteger(lua_state, 1);
  uint8_t b = luaL_checkinteger(lua_state, 2);
  uint32_t c = luaL_checkinteger(lua_state, 3);
  lua_pushnumber(lua_state, (lua_Number)set_stepper_target(a, b, c));
  return 1;
}

static int lua_wrapper_get_stepper_status(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)get_stepper_status());
  return 1;
}

static int lua_wrapper_i2cpump_start(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  float speedRate = luaL_checknumber(lua_state, 1);
  float volumeMl = luaL_checknumber(lua_state, 2);
  if (use_I2C_dev != 2 || speedRate <= 0 || volumeMl <= 0) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  uint16_t stepsPerMl = SamSetup.StepperStepMlI2C > 0 ? SamSetup.StepperStepMlI2C : I2C_STEPPER_STEP_ML_DEFAULT;
  uint32_t targetSteps = (uint32_t)(volumeMl * stepsPerMl);
  uint16_t speedSteps = (uint16_t)i2c_get_speed_from_rate(speedRate);
  I2CPumpCmdSpeed = speedSteps;
  I2CPumpTargetSteps = targetSteps;
  I2CPumpTargetMl = volumeMl;
  lua_pushnumber(lua_state, (lua_Number)set_stepper_target(speedSteps, 0, targetSteps));
  return 1;
}

static int lua_wrapper_i2cpump_stop(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  set_stepper_target(0, 0, 0);
  I2CPumpTargetSteps = 0;
  I2CPumpTargetMl = 0;
  I2CPumpCmdSpeed = 0;
  lua_pushnumber(lua_state, 1);
  return 1;
}

static int lua_wrapper_i2cpump_get_speed(lua_State *lua_state) {
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  lua_pushnumber(lua_state, (lua_Number)get_stepper_speed());
  return 1;
}

static int lua_wrapper_i2cpump_get_target_ml(lua_State *lua_state) {
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  lua_pushnumber(lua_state, (lua_Number)I2CPumpTargetMl);
  return 1;
}

static int lua_wrapper_i2cpump_get_remaining_ml(lua_State *lua_state) {
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  uint32_t remaining = get_stepper_status();
  float remainingMl = i2c_get_liquid_volume_by_step(remaining);
  lua_pushnumber(lua_state, (lua_Number)remainingMl);
  return 1;
}

static int lua_wrapper_i2cpump_get_running(lua_State *lua_state) {
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  uint32_t remaining = get_stepper_status();
  lua_pushnumber(lua_state, (lua_Number)((get_stepper_speed() > 0 && remaining > 0) ? 1 : 0));
  return 1;
}

static int lua_wrapper_set_mixer_pump_target(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checkinteger(lua_state, 1);
  lua_pushnumber(lua_state, (lua_Number)set_mixer_pump_target(a));
  return 1;
}

static int lua_wrapper_get_mixer_pump_status(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)get_mixer_pump_status());
  return 1;
}

static int lua_wrapper_check_I2C_device(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checkinteger(lua_state, 1);
  lua_pushnumber(lua_state, (lua_Number)check_I2C_device(a));
  return 1;
}

static int lua_wrapper_set_i2c_rele_state(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checkinteger(lua_state, 1);
  uint8_t b = luaL_checkinteger(lua_state, 2);
  lua_pushnumber(lua_state, (lua_Number)set_i2c_rele_state(a, b));
  return 1;
}

static int lua_wrapper_get_i2c_rele_state(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checkinteger(lua_state, 1);
  lua_pushnumber(lua_state, (lua_Number)get_i2c_rele_state(a));
  return 1;
}

#endif
