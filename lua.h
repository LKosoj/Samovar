#ifndef __SAMOVAR_LUA_H_
#define __SAMOVAR_LUA_H_

#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#include <LuaWrapper.h>
LuaWrapper lua;

inline bool lua_state_lock(TickType_t timeout = pdMS_TO_TICKS(50)) {
  return xLuaSemaphore && xSemaphoreTake(xLuaSemaphore, timeout) == pdTRUE;
}

inline void lua_state_unlock(bool locked) {
  if (locked) xSemaphoreGive(xLuaSemaphore);
}

inline String lua_exec_locked(String& script, bool collect_garbage = false) {
  String result = lua.Lua_dostring(&script);
  if (collect_garbage) {
    lua_gc(lua.GetState(), LUA_GCCOLLECT, 0);
  }
  return result;
}

inline String lua_exec(String& script, bool collect_garbage = false, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = lua_state_lock(timeout);
  if (!locked) return "Lua busy";
  String result = lua_exec_locked(script, collect_garbage);
  lua_state_unlock(true);
  return result;
}

inline bool lua_chunk_ref_valid(int ref) {
  return ref != LUA_NOREF && ref != LUA_REFNIL;
}

inline void lua_unref_chunk_locked(int& ref) {
  if (lua_chunk_ref_valid(ref)) {
    luaL_unref(lua.GetState(), LUA_REGISTRYINDEX, ref);
  }
  ref = LUA_NOREF;
}

inline String lua_error_string(lua_State* L) {
  const char* error = lua_tostring(L, -1);
  return error ? String(error) : String("unknown Lua error");
}

inline String lua_compile_chunk_locked(const String& script, const char* chunk_name, int& ref) {
  lua_unref_chunk_locked(ref);
  if (script.length() == 0) return "";
  lua_State* L = lua.GetState();
  int base = lua_gettop(L);
  if (luaL_loadbuffer(L, script.c_str(), script.length(), chunk_name) != LUA_OK) {
    String error = lua_error_string(L);
    lua_settop(L, base);
    return "# lua compile error:\n" + error;
  }
  ref = luaL_ref(L, LUA_REGISTRYINDEX);
  lua_settop(L, base);
  return "";
}

inline String lua_exec_chunk_locked(int ref, bool collect_garbage = false) {
  if (!lua_chunk_ref_valid(ref)) return "";
  lua_State* L = lua.GetState();
  int base = lua_gettop(L);
  String result;
  lua_rawgeti(L, LUA_REGISTRYINDEX, ref);
  if (lua_pcall(L, 0, LUA_MULTRET, 0) != LUA_OK) {
    result = "# lua error:\n" + lua_error_string(L);
  }
  lua_settop(L, base);
  if (collect_garbage) {
    lua_gc(L, LUA_GCCOLLECT, 0);
  }
  return result;
}

inline void lua_set_number_global_locked(const char* name, lua_Number value) {
  lua_pushnumber(lua.GetState(), value);
  lua_setglobal(lua.GetState(), name);
}

inline void lua_install_constants_locked() {
  lua_set_number_global_locked("INPUT", INPUT);
  lua_set_number_global_locked("OUTPUT", OUTPUT);
  lua_set_number_global_locked("LOW", LOW);
  lua_set_number_global_locked("HIGH", HIGH);
}

#include <SimpleMap.h>

#include <asyncHTTPrequest.h>
#include "I2CStepper.h"

#include <TimeLib.h>

#define EXPANDER_UPDATE_TIMEOUT 500


unsigned long lua_timer[10];  //10 таймеров для lua
String lua_type_script;
String script1, script2;
int script1_ref = LUA_NOREF;
int script2_ref = LUA_NOREF;
extern String lua_script_list_cache;

SimpleMap<String, String> *luaObj = new SimpleMap<String, String>([](String &a, String &b) -> int {
  if (a == b) return 0;      // a and b are equal
  else if (a > b) return 1;  // a is bigger than b
  else return -1;            // a is smaller than b
});

TaskHandle_t DoLuaScriptTask = NULL;
volatile bool lua_finished;
volatile bool lua_start_requested = false;

enum LuaJobType : uint8_t {
  LUA_JOB_NONE = 0,
  LUA_JOB_SCRIPT,
  LUA_JOB_INLINE
};

String lua_job_script;
volatile LuaJobType lua_job_type = LUA_JOB_NONE;

inline bool queue_lua_job(LuaJobType type, const String& script) {
  if (script.length() == 0) return true;
  bool locked = runtime_state_lock(pdMS_TO_TICKS(500));
  if (!locked) return false;
  bool queued = false;
  if (lua_job_type == LUA_JOB_NONE) {
    lua_job_script = script;
    lua_job_type = type;
    queued = true;
  }
  runtime_state_unlock(true);
  return queued;
}

inline bool queue_lua_script_job(const String& script) {
  return queue_lua_job(LUA_JOB_SCRIPT, script);
}

inline bool queue_lua_inline_job(const String& script) {
  return queue_lua_job(LUA_JOB_INLINE, script);
}

inline bool take_lua_job(String& script, LuaJobType& type) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  bool hasJob = false;
  if (lua_job_type != LUA_JOB_NONE) {
    script = lua_job_script;
    type = lua_job_type;
    lua_job_script = "";
    lua_job_type = LUA_JOB_NONE;
    hasJob = true;
  }
  runtime_state_unlock(true);
  return hasJob;
}

inline bool request_lua_periodic_start() {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  bool accepted = false;
  if (lua_finished && !lua_start_requested) {
    lua_start_requested = true;
    accepted = true;
  }
  runtime_state_unlock(true);
  return accepted;
}

inline bool consume_lua_periodic_start_request(bool& accepted) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  accepted = false;
  if (lua_start_requested && lua_finished) {
    lua_start_requested = false;
    lua_finished = false;
    accepted = true;
  }
  runtime_state_unlock(true);
  return true;
}

inline bool lua_periodic_active(bool& active) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  active = !lua_finished;
  runtime_state_unlock(true);
  return true;
}

inline void finish_lua_periodic_run() {
  bool locked = runtime_state_lock(portMAX_DELAY);
  if (locked) {
    lua_finished = true;
    runtime_state_unlock(true);
  }
}

static bool lua_copy_current_program(WProgram& currentProgram) {
  if (ProgramNum >= PROGRAM_MAX) return false;
  currentProgram = program[ProgramNum];
  return !program_type_empty(currentProgram.WType);
}

static String lua_to_string_arg(lua_State *lua_state, int index) {
  String value;
  lua_getglobal(lua_state, "tostring");
  lua_pushvalue(lua_state, index);
  lua_call(lua_state, 1, 1);
  size_t len;
  const char *text = lua_tolstring(lua_state, -1, &len);
  if (text) value = text;
  lua_pop(lua_state, 1);
  return value;
}

enum LuaVariableAccess : uint8_t {
  LUA_VAR_READ = 0x01,
  LUA_VAR_WRITE = 0x02
};

static const uint8_t LUA_VAR_RO = LUA_VAR_READ;
static const uint8_t LUA_VAR_WO = LUA_VAR_WRITE;
static const uint8_t LUA_VAR_RW = LUA_VAR_READ | LUA_VAR_WRITE;

struct LuaNumVariableDescriptor {
  const char* name;
  float (*getter)();
  void (*setter)(float value);
  uint8_t access;
};

static float lua_num_get_WFpulseCount() { return water_pulse_count_get(); }
static void lua_num_set_WFpulseCount(float value) { water_pulse_count_set((uint16_t)value); }
static float lua_num_get_pump_started() { return pump_started; }
static void lua_num_set_pump_started(float value) { pump_started = (int)value; }
static float lua_num_get_valve_status() { return valve_status; }
static void lua_num_set_valve_status(float value) { valve_status = (int)value; }
static float lua_num_get_SamSetup_Mode() { return SamSetup.Mode; }
static void lua_num_set_SamSetup_Mode(float value) { SamSetup.Mode = (int)value; }
static float lua_num_get_Samovar_Mode() { return Samovar_Mode; }
static void lua_num_set_Samovar_Mode(float value) {
  SAMOVAR_MODE newMode = (SAMOVAR_MODE)value;
  if (Samovar_Mode != newMode) {
    Samovar_Mode = newMode;
    change_samovar_mode();
  }
}
static float lua_num_get_Samovar_CR_Mode() { return Samovar_CR_Mode; }
static void lua_num_set_Samovar_CR_Mode(float value) { Samovar_CR_Mode = (SAMOVAR_MODE)value; }
static float lua_num_get_acceleration_temp() { return acceleration_temp; }
static void lua_num_set_acceleration_temp(float value) { acceleration_temp = (uint16_t)value; }
#ifdef USE_WATER_PUMP
static float lua_num_get_wp_count() { return wp_count; }
static void lua_num_set_wp_count(float value) { wp_count = (byte)value; }
static void lua_num_set_pmpKp(float value) { pump_regulator.Kp = (byte)value; }
static void lua_num_set_pmpKi(float value) { pump_regulator.Ki = (byte)value; }
static void lua_num_set_pmpKd(float value) { pump_regulator.Kd = (byte)value; }
#endif
static float lua_num_get_SteamTemp() { return SteamSensor.avgTemp; }
static void lua_num_set_SteamTemp(float value) { SteamSensor.avgTemp = value; }
static float lua_num_get_boil_temp() { return boil_temp; }
static void lua_num_set_boil_temp(float value) { boil_temp = value; }
static float lua_num_get_PipeTemp() { return PipeSensor.avgTemp; }
static void lua_num_set_PipeTemp(float value) { PipeSensor.avgTemp = value; }
static float lua_num_get_WaterTemp() { return WaterSensor.avgTemp; }
static void lua_num_set_WaterTemp(float value) { WaterSensor.avgTemp = value; }
static float lua_num_get_TankTemp() { return TankSensor.avgTemp; }
static void lua_num_set_TankTemp(float value) { TankSensor.avgTemp = value; }
static float lua_num_get_ACPTemp() { return ACPSensor.avgTemp; }
static void lua_num_set_ACPTemp(float value) { ACPSensor.avgTemp = value; }
static float lua_num_get_loop_lua_fl() { return loop_lua_fl; }
static void lua_num_set_loop_lua_fl(float value) { loop_lua_fl = (int)value; }
static float lua_num_get_SetScriptOff() { return SetScriptOff; }
static void lua_num_set_SetScriptOff(float value) { SetScriptOff = (bool)value; }
static float lua_num_get_show_lua_script() { return show_lua_script; }
static void lua_num_set_show_lua_script(float value) { show_lua_script = (int)value; }
static float lua_num_get_test_num_val() { return test_num_val; }
static void lua_num_set_test_num_val(float value) { test_num_val = value; }
static float lua_num_get_WFtotalMilliLitres() { return WFtotalMilliLitres; }
static float lua_num_get_WFflowRate() { return WFflowRate; }
static float lua_num_get_program_volume() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Volume : 0;
}
static float lua_num_get_program_speed() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Speed : 0;
}
static float lua_num_get_program_temp() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Temp : 0;
}
static float lua_num_get_program_power() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Power : 0;
}
static float lua_num_get_program_time() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Time : 0;
}
static float lua_num_get_program_capacity_num() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.capacity_num : 0;
}
static float lua_num_get_capacity_num() { return capacity_num; }
static float lua_num_get_target_power_volt() { return target_power_volt; }
static float lua_num_get_PowerOn() { return PowerOn; }
static float lua_num_get_alcohol() { return get_alcohol(TankSensor.avgTemp); }
static float lua_num_get_alcohol_s() { return alcohol_s; }
static float lua_num_get_water_pump_speed() { return water_pump_speed; }
static float lua_num_get_pressure_value() { return pressure_value; }
static float lua_num_get_PauseOn() { return PauseOn; }
static float lua_num_get_program_Wait() { return program_Wait; }
static float lua_num_get_YY() { return year(time(NULL)); }
static float lua_num_get_MM() { return month(time(NULL)); }
static float lua_num_get_DD() { return day(time(NULL)); }
static float lua_num_get_HH() { return hour(time(NULL)) + SamSetup.TimeZone; }
static float lua_num_get_MI() { return minute(time(NULL)); }
static float lua_num_get_SS() { return second(time(NULL)); }

static const LuaNumVariableDescriptor lua_num_variables[] = {
  {"WFpulseCount", lua_num_get_WFpulseCount, lua_num_set_WFpulseCount, LUA_VAR_RW},
  {"pump_started", lua_num_get_pump_started, lua_num_set_pump_started, LUA_VAR_RW},
  {"valve_status", lua_num_get_valve_status, lua_num_set_valve_status, LUA_VAR_RW},
  {"SamSetup_Mode", lua_num_get_SamSetup_Mode, lua_num_set_SamSetup_Mode, LUA_VAR_RW},
  {"Samovar_Mode", lua_num_get_Samovar_Mode, lua_num_set_Samovar_Mode, LUA_VAR_RW},
  {"Samovar_CR_Mode", lua_num_get_Samovar_CR_Mode, lua_num_set_Samovar_CR_Mode, LUA_VAR_RW},
  {"acceleration_temp", lua_num_get_acceleration_temp, lua_num_set_acceleration_temp, LUA_VAR_RW},
#ifdef USE_WATER_PUMP
  {"wp_count", lua_num_get_wp_count, lua_num_set_wp_count, LUA_VAR_RW},
  {"pmpKp", nullptr, lua_num_set_pmpKp, LUA_VAR_WO},
  {"pmpKi", nullptr, lua_num_set_pmpKi, LUA_VAR_WO},
  {"pmpKd", nullptr, lua_num_set_pmpKd, LUA_VAR_WO},
#endif
  {"SteamTemp", lua_num_get_SteamTemp, lua_num_set_SteamTemp, LUA_VAR_RW},
  {"boil_temp", lua_num_get_boil_temp, lua_num_set_boil_temp, LUA_VAR_RW},
  {"PipeTemp", lua_num_get_PipeTemp, lua_num_set_PipeTemp, LUA_VAR_RW},
  {"WaterTemp", lua_num_get_WaterTemp, lua_num_set_WaterTemp, LUA_VAR_RW},
  {"TankTemp", lua_num_get_TankTemp, lua_num_set_TankTemp, LUA_VAR_RW},
  {"ACPTemp", lua_num_get_ACPTemp, lua_num_set_ACPTemp, LUA_VAR_RW},
  {"loop_lua_fl", lua_num_get_loop_lua_fl, lua_num_set_loop_lua_fl, LUA_VAR_RW},
  {"SetScriptOff", lua_num_get_SetScriptOff, lua_num_set_SetScriptOff, LUA_VAR_RW},
  {"show_lua_script", lua_num_get_show_lua_script, lua_num_set_show_lua_script, LUA_VAR_RW},
  {"test_num_val", lua_num_get_test_num_val, lua_num_set_test_num_val, LUA_VAR_RW},
  {"WFtotalMilliLitres", lua_num_get_WFtotalMilliLitres, nullptr, LUA_VAR_RO},
  {"WFflowRate", lua_num_get_WFflowRate, nullptr, LUA_VAR_RO},
  {"program_volume", lua_num_get_program_volume, nullptr, LUA_VAR_RO},
  {"program_speed", lua_num_get_program_speed, nullptr, LUA_VAR_RO},
  {"program_temp", lua_num_get_program_temp, nullptr, LUA_VAR_RO},
  {"program_power", lua_num_get_program_power, nullptr, LUA_VAR_RO},
  {"program_time", lua_num_get_program_time, nullptr, LUA_VAR_RO},
  {"program_capacity_num", lua_num_get_program_capacity_num, nullptr, LUA_VAR_RO},
  {"capacity_num", lua_num_get_capacity_num, nullptr, LUA_VAR_RO},
  {"target_power_volt", lua_num_get_target_power_volt, nullptr, LUA_VAR_RO},
  {"PowerOn", lua_num_get_PowerOn, nullptr, LUA_VAR_RO},
  {"alcohol", lua_num_get_alcohol, nullptr, LUA_VAR_RO},
  {"alcohol_s", lua_num_get_alcohol_s, nullptr, LUA_VAR_RO},
  {"water_pump_speed", lua_num_get_water_pump_speed, nullptr, LUA_VAR_RO},
  {"pressure_value", lua_num_get_pressure_value, nullptr, LUA_VAR_RO},
  {"PauseOn", lua_num_get_PauseOn, nullptr, LUA_VAR_RO},
  {"program_Wait", lua_num_get_program_Wait, nullptr, LUA_VAR_RO},
  {"YY", lua_num_get_YY, nullptr, LUA_VAR_RO},
  {"MM", lua_num_get_MM, nullptr, LUA_VAR_RO},
  {"DD", lua_num_get_DD, nullptr, LUA_VAR_RO},
  {"HH", lua_num_get_HH, nullptr, LUA_VAR_RO},
  {"MI", lua_num_get_MI, nullptr, LUA_VAR_RO},
  {"SS", lua_num_get_SS, nullptr, LUA_VAR_RO},
};

static const LuaNumVariableDescriptor* find_lua_num_variable(const String& name) {
  for (size_t i = 0; i < sizeof(lua_num_variables) / sizeof(lua_num_variables[0]); i++) {
    if (name == lua_num_variables[i].name) return &lua_num_variables[i];
  }
  return nullptr;
}

struct LuaStrVariableDescriptor {
  const char* name;
  bool (*getter)(String& value);
  bool (*setter)(const String& value);
  uint8_t access;
  const char* busy_error;
};

static bool lua_str_get_Msg(String& value) { return copy_web_message_raw(value); }
static bool lua_str_set_Msg(const String& value) { return set_web_message_raw(value); }
static bool lua_str_get_SamovarStatus(String& value) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  value = SamovarStatus;
  runtime_state_unlock(true);
  return true;
}
static bool lua_str_set_SamovarStatus(const String& value) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  SamovarStatus = value;
  runtime_state_unlock(true);
  return true;
}
static bool lua_str_get_test_str_val(String& value) {
  value = test_str_val;
  return true;
}
static bool lua_str_set_test_str_val(const String& value) {
  test_str_val = value;
  return true;
}
static bool lua_str_get_program_type(String& value) {
  WProgram currentProgram;
  value = lua_copy_current_program(currentProgram) ? program_type_to_string(currentProgram.WType) : String();
  return true;
}

static const LuaStrVariableDescriptor lua_str_variables[] = {
  {"Msg", lua_str_get_Msg, lua_str_set_Msg, LUA_VAR_RW, "Msg busy"},
  {"SamovarStatus", lua_str_get_SamovarStatus, lua_str_set_SamovarStatus, LUA_VAR_RW, "SamovarStatus busy"},
  {"test_str_val", lua_str_get_test_str_val, lua_str_set_test_str_val, LUA_VAR_RW, nullptr},
  {"program_type", lua_str_get_program_type, nullptr, LUA_VAR_RO, nullptr},
};

static const LuaStrVariableDescriptor* find_lua_str_variable(const String& name) {
  for (size_t i = 0; i < sizeof(lua_str_variables) / sizeof(lua_str_variables[0]); i++) {
    if (name == lua_str_variables[i].name) return &lua_str_variables[i];
  }
  return nullptr;
}

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
  lua_pushnumber(lua_state, (lua_Number)digitalRead(a));
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
  } else {
    return luaL_error(lua_state, "I2C expander read timeout");
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
  } else {
    return luaL_error(lua_state, "I2C analog expander read timeout");
  }
  return 1;
}
#endif

static int lua_wrapper_delay(lua_State *lua_state) {
  int a = luaL_checkinteger(lua_state, 1);
  vTaskDelay(a / portTICK_PERIOD_MS);
  return 0;
}

static int lua_wrapper_millis(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)millis());
  return 1;
}

static int lua_wrapper_set_pause_withdrawal(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  pause_withdrawal(a);
  return 0;
}

static int lua_wrapper_set_power(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  SamovarCommands command = SAMOVAR_NONE;

  if (a && !PowerOn) {
    if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
      command = SAMOVAR_BEER;
    } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
      command = SAMOVAR_BK;
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
      command = SAMOVAR_NBK;
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
      command = SAMOVAR_DISTILLATION;
    } else
      command = SAMOVAR_POWER;
  } else if (!a && PowerOn)
    command = SAMOVAR_POWER;

  if (command != SAMOVAR_NONE) {
    if (!queue_samovar_command(command, pdMS_TO_TICKS(100))) {
      return luaL_error(lua_state, "Samovar command queue busy");
    }
  }

  return 0;
}

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
  SamovarCommands command = SAMOVAR_NONE;
  if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
    command = SAMOVAR_START;
  } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
    command = SAMOVAR_BEER_NEXT;
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    command = SAMOVAR_DIST_NEXT;
  }
  if (command != SAMOVAR_NONE) {
    if (!queue_samovar_command(command, pdMS_TO_TICKS(100))) {
      return luaL_error(lua_state, "Samovar command queue busy");
    }
  }
  return 0;
}

static int lua_wrapper_get_state(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)SamovarStatusInt);
  return 1;
}

static int lua_wrapper_send_msg(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 2);
  String st = lua_to_string_arg(lua_state, 1);
  if (a == -1) {
    WriteConsoleLog(st);
  } else {
    SendMsg(st, (MESSAGE_TYPE)a);
  }
  return 0;
}

static int lua_wrapper_set_num_variable(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  float a = luaL_checknumber(lua_state, 2);
  String Var = lua_to_string_arg(lua_state, 1);
  const LuaNumVariableDescriptor* descriptor = find_lua_num_variable(Var);
  if (descriptor && (descriptor->access & LUA_VAR_WRITE) && descriptor->setter) {
    descriptor->setter(a);
  } else if (Var.length() > 0) {
    WriteConsoleLog("UNDEF NUMERIC LUA VAR " + Var + " = " + String(a));
  }
  return 0;
}

static int lua_wrapper_get_num_variable(lua_State *lua_state) {
  float a = 0;
  String Var = lua_to_string_arg(lua_state, 1);
  const LuaNumVariableDescriptor* descriptor = find_lua_num_variable(Var);
  if (descriptor && (descriptor->access & LUA_VAR_READ) && descriptor->getter) {
    a = descriptor->getter();
  } else if (Var.length() > 0) {
    WriteConsoleLog("GET UNDEF NUMERIC LUA VAR " + Var);
  }
  lua_pushnumber(lua_state, (lua_Number)a);
  return 1;
}

static int lua_wrapper_set_str_variable(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var = lua_to_string_arg(lua_state, 1);
  String Val = lua_to_string_arg(lua_state, 2);
  const LuaStrVariableDescriptor* descriptor = find_lua_str_variable(Var);
  if (descriptor && (descriptor->access & LUA_VAR_WRITE) && descriptor->setter) {
    if (!descriptor->setter(Val)) return luaL_error(lua_state, descriptor->busy_error ? descriptor->busy_error : "Lua string variable busy");
  } else if (descriptor) {
    WriteConsoleLog("WARNING! " + Var + " is read only property");
  } else if (Var.length() > 0) {
    WriteConsoleLog("UNDEF STRING LUA VAR " + Var + " = " + Val);
  }
  return 0;
}

static int lua_wrapper_set_object(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var = lua_to_string_arg(lua_state, 1);
  String Val = lua_to_string_arg(lua_state, 2);
  luaObj->put(Var, Val);
  return 0;
}

static int lua_wrapper_get_object(lua_State *lua_state) {
  String Var, Type;
  int n = lua_gettop(lua_state); /* number of arguments */
  Var = lua_to_string_arg(lua_state, 1);

  String v = luaObj->get(Var);
  if (n == 2) {
    Type = lua_to_string_arg(lua_state, 2);
    if (Type == "NUMERIC" && v.length() == 0) {
      v = "0";
    }
  }

  lua_pushstring(lua_state, v.c_str());
  return 1;
}

static int lua_wrapper_set_lua_status(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  String Var = lua_to_string_arg(lua_state, 1);
  if (!set_lua_status_value(Var)) return luaL_error(lua_state, "Lua_status busy");
  return 0;
}

static int lua_wrapper_set_capacity(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  if (a < 0 || a > CAPACITY_NUM) return luaL_error(lua_state, "capacity out of range");
  set_capacity((uint8_t)a);
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

static int lua_wrapper_set_timer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checknumber(lua_state, 1);
  if (a < 1 || a > 10) return 0;
  a--;
  uint16_t b = luaL_checknumber(lua_state, 2);
  lua_timer[a] = millis() + b * 1000;
  return 0;
}

static int lua_wrapper_get_timer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checknumber(lua_state, 1);
  uint16_t b;
  if (a < 1 || a > 10) b = 0;
  else {
    a--;
    if (lua_timer[a] == 0) b = 0;
    else {
      long l;
      l = lua_timer[a] - millis();
      if (l <= 0) {
        b = 0;
        lua_timer[a] = 0;
      } else b = l / 1000;
    }
  }
  lua_pushnumber(lua_state, (lua_Number)b);
  return 1;
}

static int lua_wrapper_get_str_variable(lua_State *lua_state) {
  String c;
  String Var = lua_to_string_arg(lua_state, 1);
  const LuaStrVariableDescriptor* descriptor = find_lua_str_variable(Var);
  if (descriptor && (descriptor->access & LUA_VAR_READ) && descriptor->getter) {
    if (!descriptor->getter(c)) return luaL_error(lua_state, descriptor->busy_error ? descriptor->busy_error : "Lua string variable busy");
  } else if (Var.length() > 0) {
    WriteConsoleLog("UNDEF GET STRING LUA VAR " + Var);
    return 0;
  }
  lua_pushstring(lua_state, c.c_str());
  return 1;
}

static int lua_wrapper_http_request(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int n = lua_gettop(lua_state); /* number of arguments */
  String Var = lua_to_string_arg(lua_state, 1);

  asyncHTTPrequest request;
  String payload;
  //int httpResponseCode;

  const uint32_t timeoutMs = 4000; // общий таймаут на connect/done
  request.setDebug(false);
  request.setTimeout(3);  //Таймаут три секунды (внутренний по отсутствию активности)
  vTaskDelay(10 / portTICK_PERIOD_MS);
  if (n != 1 && n != 4) {
    lua_pushstring(lua_state, "error");
    return 1;
  }

  if (n == 1) { // GET(url)
    if (!request.open("GET", Var.c_str())) {  //URL
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

    RequestType = lua_to_string_arg(lua_state, 2);
    ContentType = lua_to_string_arg(lua_state, 3);
    Body = lua_to_string_arg(lua_state, 4);

    if (!request.open(RequestType.c_str(), Var.c_str())) {  //URL
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
  // Free resources

  lua_pushstring(lua_state, payload.c_str());

  return 1;
}

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

void lua_init() {
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

  // 1. Уменьшим размер стека для lua скриптов
  lua_State* L = lua.GetState();
  lua_gc(L, LUA_GCSETPAUSE, 120); // Увеличим паузу между сборками мусора
  lua_gc(L, LUA_GCSETSTEPMUL, 200); // Увеличим агрессивность сборки
  lua_install_constants_locked();
  
  //Запускаем инициализирующий lua-скрипт
  File f = SPIFFS.open("/init.lua");
  if (f) {
    //нашли файл со скриптом, выполняем
    String script;
    script = get_global_variables();
    script += f.readString();
    f.close();
    if (show_lua_script) {
      WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
      WriteConsoleLog(script);
      WriteConsoleLog(F("--END LUA SCRIPT--"));
    }
    String sr = lua_exec(script);
    if (sr.length() > 0) WriteConsoleLog("INI ERR " + sr);
  }
  lua_type_script = get_lua_mode_name();
  lua_finished = true;

  load_lua_script();

  //Запускаем таск для запуска скрипта
  xTaskCreatePinnedToCore(
    do_lua_script,    /* Function to implement the task */
    "do_lua_script",  /* Name of the task */
    5900,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &DoLuaScriptTask, /* Task handle. */
    1);               /* Core where the task should run */
}

String get_lua_script_list() {
  String s, fn;
  uint8_t i = 1;
  File root = SPIFFS.open("/");
  File file = root.openNextFile();
  while (file) {
    if (!file.isDirectory()) {
      fn = file.name();
      if (fn.substring(0, 4) == "btn_" && getValue(fn, '_', 1) == get_lua_mode_name(false)) {
        String str;
        s = s + fn;
        if (fn[0] != '/') fn = "/" + fn;
        File f = SPIFFS.open(fn);
        str = f.readStringUntil('^');
        str = getValue(str, '|', 1);
        if (str.length() == 0) str = "LUA" + (String)i;
        i++;
        s = s + "|" + str + ",";
      }
    }
    file = root.openNextFile();
  }
  s = s.substring(0, s.length() - 1);
  return s;
}

String get_lua_script(String fn) {
  String s = "";
  File f;
  if (fn[0] != '/') fn = "/" + fn;
  f = SPIFFS.open(fn);
  if (f) {
    //нашли файл со скриптом, загружаем
    s = f.readString();
    s.trim();
    f.close();
  }
  return s;
}

bool run_lua_script(String fn) {
  String s = get_lua_script(fn);
  if (s.length() > 0) s = get_global_variables() + s;
  if (!queue_lua_script_job(s)) {
    WriteConsoleLog(F("Lua busy"));
    return false;
  }
  return true;
}

String run_lua_string(String lstr) {
  String sr = "";
  if (lstr.length() > 0) {
#ifdef USE_MQTT
    String MsgPl = lstr;
    MsgPl.replace(",", ";");
    MqttSendMsg(MsgPl + "," + NOTIFY_MSG, "msg");
#endif
    if (!queue_lua_inline_job(lstr)) {
      sr = "Lua busy";
      WriteConsoleLog(sr);
    } else {
      WriteConsoleLog(F("Lua queued"));
    }
  }
  return sr;
}

void load_lua_script() {
  String s1 = get_lua_script("script.lua");
  String s2 = get_lua_script(lua_type_script);
  String btnList = get_lua_script_list();
  String modeChunkName = "@" + lua_type_script;

  bool lua_locked = lua_state_lock(portMAX_DELAY);
  if (!lua_locked) {
    WriteConsoleLog(F("Lua reload busy"));
    return;
  }
  String script1Error = lua_compile_chunk_locked(s1, "@script.lua", script1_ref);
  String script2Error = lua_compile_chunk_locked(s2, modeChunkName.c_str(), script2_ref);
  bool locked = runtime_state_lock(portMAX_DELAY);
  if (locked) {
    script1 = s1;
    script2 = s2;
    lua_script_list_cache = btnList;
    runtime_state_unlock(true);
  }
  lua_state_unlock(lua_locked);
  if (script1Error.length() > 0) WriteConsoleLog("ERR in script.lua: " + script1Error);
  if (script2Error.length() > 0) WriteConsoleLog("ERR in " + lua_type_script + ": " + script2Error);
}

//Запускаем таск для запуска скрипта
void do_lua_script(void *parameter) {
  String sr;
  sr.reserve(128);
  unsigned long last_periodic_lua_start = 0;
  //String glv;
  while (1) {
    // Приостанавливаем выполнение Lua скриптов во время OTA обновления
    if (ota_running) {
      vTaskDelay(500 / portTICK_PERIOD_MS);  // Увеличиваем задержку во время OTA
      continue;
    }

    // One-shot Lua jobs from web/Blynk/buttons are executed only by this task.
    {
      String local_job_script;
      LuaJobType local_job_type = LUA_JOB_NONE;
      if (take_lua_job(local_job_script, local_job_type)) {
        bool lua_locked = false;
        lua_locked = lua_state_lock(portMAX_DELAY);
        if (!lua_locked) {
          WriteConsoleLog(F("Lua mutex unavailable"));
          vTaskDelay(50 / portTICK_PERIOD_MS);
          continue;
        }
        if (show_lua_script && local_job_script.length() > 0) {
          WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
          WriteConsoleLog(local_job_script);
          WriteConsoleLog(F("--END LUA SCRIPT--"));
        }
        sr = lua_exec_locked(local_job_script);
        sr.trim();
        if (sr.length() > 0) {
          WriteConsoleLog((local_job_type == LUA_JOB_INLINE) ? "ERR in lua: " + sr : "ERR in BTN_SCRIPT " + sr);
        } else {
          WriteConsoleLog((local_job_type == LUA_JOB_INLINE) ? F("Lua run complete") : F("BTN_SCRIPT complete"));
        }
        lua_state_unlock(lua_locked);
      }
    }

    if (SetScriptOff && loop_lua_fl) {
      loop_lua_fl = false;
    }
    if (loop_lua_fl && !SetScriptOff) {
      unsigned long now = millis();
      if (last_periodic_lua_start == 0 || now - last_periodic_lua_start >= 1000) {
        if (request_lua_periodic_start()) last_periodic_lua_start = now;
      }
    }
    bool has_lua_start_request = false;
    if (!consume_lua_periodic_start_request(has_lua_start_request)) {
      vTaskDelay(5 / portTICK_PERIOD_MS);
      continue;
    }
    bool lua_active = false;
    if (!lua_periodic_active(lua_active)) {
      vTaskDelay(5 / portTICK_PERIOD_MS);
      continue;
    }
    if (lua_active) {
      // [W-4/W3] Копируем script1/script2 под runtime lock, но после захвата Lua VM:
      // если runtime lock занят, оставляем lua_finished=false и повторяем позже.
      bool lua_locked = lua_state_lock(portMAX_DELAY);
      if (!lua_locked) {
        WriteConsoleLog(F("Lua mutex unavailable"));
        vTaskDelay(50 / portTICK_PERIOD_MS);
        continue;
      }
      if (ota_running) {
        lua_state_unlock(lua_locked);
        vTaskDelay(500 / portTICK_PERIOD_MS);
        continue;
      }
      String local_s1, local_s2;
      int local_script1_ref = script1_ref;
      int local_script2_ref = script2_ref;
      {
        bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
        if (locked) {
          local_s1 = script1;
          local_s2 = script2;
          runtime_state_unlock(true);
        } else {
          lua_state_unlock(lua_locked);
          vTaskDelay(5 / portTICK_PERIOD_MS);
          continue;
        }
      }

      if (local_s1.length() > 0 && lua_chunk_ref_valid(local_script1_ref)) {
        if (show_lua_script) {
          WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
          WriteConsoleLog(local_s1);
          WriteConsoleLog(F("--END LUA SCRIPT--"));
        }
        sr = lua_exec_chunk_locked(local_script1_ref);
        sr.trim();
        if (sr.length() > 0) WriteConsoleLog("ERR in script.lua: " + sr);
      }
      vTaskDelay(5 / portTICK_PERIOD_MS);

      if (local_s2.length() > 0 && lua_chunk_ref_valid(local_script2_ref)) {
        if (show_lua_script) {
          WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
          WriteConsoleLog(local_s2);
          WriteConsoleLog(F("--END LUA SCRIPT--"));
        }
        sr = lua_exec_chunk_locked(local_script2_ref, true);
        sr.trim();
        if (sr.length() > 0) WriteConsoleLog("ERR in " + lua_type_script + ": " + sr);
      } else {
        lua_gc(lua.GetState(), LUA_GCCOLLECT, 0);
      }
      finish_lua_periodic_run();
      lua_state_unlock(lua_locked);
    } else {
      vTaskDelay(50 / portTICK_PERIOD_MS);
    }
    if (!loop_lua_fl && SetScriptOff) {
      SetScriptOff = 0;
    }
    vTaskDelay(5 / portTICK_PERIOD_MS);
  }
}

bool start_lua_script() {
  if (!request_lua_periodic_start()) {
    WriteConsoleLog(F("Lua busy"));
    return false;
  }
  return true;
}

String get_global_variables() {
  String Variables;
  //  Variables = "bme_temp = " + String(bme_temp) + "\r\n";
  //  Variables += "start_pressure = " + String(start_pressure) + "\r\n";
  Variables += "bme_pressure = " + String(bme_pressure) + "\r\n";
  //  Variables += "bme_prev_pressure = " + String(bme_prev_pressure) + "\r\n";
  //  Variables += "bme_humidity = " + String(bme_humidity) + "\r\n";
  //  Variables += "SamovarStatus = \"" + SamovarStatus + "\"\r\n";
  Variables += "capacity_num = " + String(capacity_num) + "\r\n";
  Variables += "SamovarStatusInt = " + String(SamovarStatusInt) + "\r\n";
  //  Variables += "prev_ProgramNum = " + String(prev_ProgramNum) + "\r\n";
  Variables += "ProgramNum = " + String(ProgramNum) + "\r\n";
  Variables += "ProgramLen = " + String(ProgramLen) + "\r\n";
  //  Variables += "startval = " + String(startval) + "\r\n";
  //  Variables += "currentstepcnt = " + String(currentstepcnt) + "\r\n";
  //  Variables += "prev_time_ms = " + String(prev_time_ms) + "\r\n";
  Variables += "ActualVolumePerHour = " + String(ActualVolumePerHour) + "\r\n";
  //  Variables += "CurrrentStepperSpeed = " + String(CurrrentStepperSpeed) + "\r\n";
  //  Variables += "CurrrentStepps = " + String(CurrrentStepps) + "\r\n";
  //  Variables += "TargetStepps = " + String(TargetStepps) + "\r\n";
  Variables += "WthdrwlProgress = " + String(WthdrwlProgress) + "\r\n";
  Variables += "PowerOn = " + String(PowerOn) + "\r\n";
  Variables += "PauseOn = " + String(PauseOn) + "\r\n";
  Variables += "StepperMoving = " + String(StepperMoving) + "\r\n";
  Variables += "program_Pause = " + String(program_Pause) + "\r\n";
  Variables += "program_Wait = " + String(program_Wait) + "\r\n";
  String programWaitTypeText;
  if (!copy_program_wait_type_text(programWaitTypeText)) {
    WriteConsoleLog(F("WARNING! program_Wait_Type busy"));
    Variables += "error('program_Wait_Type busy')\r\n";
  } else {
    Variables += "program_Wait_Type = \"" + programWaitTypeText + "\"\r\n";
  }
  //  Variables += "begintime = " + String(begintime) + "\r\n";
  //  Variables += "t_min = " + String(t_min) + "\r\n";
  //  Variables += "alarm_t_min = " + String(alarm_t_min) + "\r\n";
  //  Variables += "alarm_h_min = " + String(alarm_h_min) + "\r\n";
  //  Variables += "WFpulseCount = " + String(WFpulseCount) + "\r\n";
#ifdef USE_WATERSENSOR
  Variables += "WFflowMilliLitres = " + String(WFflowMilliLitres) + "\r\n";
  Variables += "WFtotalMilliLitres = " + String(WFtotalMilliLitres) + "\r\n";
  Variables += "WFflowRate = " + String(WFflowRate) + "\r\n";
#endif
  //  Variables += "WFAlarmCount = " + String(WFAlarmCount) + "\r\n";
  //  Variables += "acceleration_temp = " + String(acceleration_temp) + "\r\n";
  Variables += "WthdrwTimeAll = " + String(WthdrwTimeAll) + "\r\n";
  Variables += "WthdrwTime = " + String(WthdrwTime) + "\r\n";
  Variables += "WthdrwTimeAllS = \"" + WthdrwTimeAllS + "\"\r\n";
  Variables += "WthdrwTimeS = \"" + WthdrwTimeS + "\"\r\n";
  Variables += "pump_started = " + String(pump_started) + "\r\n";
  Variables += "heater_state = " + String(heater_state) + "\r\n";
  //  Variables += "ofl = \"" + ofl + "\"\r\n";
  Variables += "mixer_status = " + String(mixer_status) + "\r\n";
  //  Variables += "bk_pwm = " + String(bk_pwm) + "\r\n";
  //  Variables += "chipId = " + String(chipId) + "\r\n";
  Variables += "alarm_event = " + String(alarm_event) + "\r\n";
  Variables += "acceleration_heater = " + String(acceleration_heater) + "\r\n";
  Variables += "valve_status = " + String(valve_status) + "\r\n";
  WProgram currentProgram;
  bool hasCurrentProgram = lua_copy_current_program(currentProgram);
  Variables += "program_type = \"" + String(hasCurrentProgram ? program_type_to_string(currentProgram.WType) : String()) + "\"\r\n";
  Variables += "program_volume = " + String(hasCurrentProgram ? currentProgram.Volume : 0) + "\r\n";
  Variables += "program_speed = " + String(hasCurrentProgram ? currentProgram.Speed : 0) + "\r\n";
  Variables += "program_temp = " + String(hasCurrentProgram ? currentProgram.Temp : 0) + "\r\n";
  Variables += "program_power = " + String(hasCurrentProgram ? currentProgram.Power : 0) + "\r\n";
  Variables += "program_time = " + String(hasCurrentProgram ? currentProgram.Time : 0) + "\r\n";
  Variables += "program_capacity_num = " + String(hasCurrentProgram ? currentProgram.capacity_num : 0) + "\r\n";

  //  Variables += "loop_lua_fl = " + String(loop_lua_fl) + "\r\n";
  //  Variables += "show_lua_script = " + String(show_lua_script) + "\r\n";
  Variables += "SamSetup_Mode = " + String(SamSetup.Mode) + "\r\n";
  Variables += "test_num_val = " + String(test_num_val) + "\r\n";
  Variables += "test_str_val = \"" + test_str_val + "\"\r\n";

  Variables += "SteamTemp = " + String(SteamSensor.avgTemp) + "\r\n";
  Variables += "PipeTemp = " + String(PipeSensor.avgTemp) + "\r\n";
  Variables += "WaterTemp = " + String(WaterSensor.avgTemp) + "\r\n";
  Variables += "TankTemp = " + String(TankSensor.avgTemp) + "\r\n";
  Variables += "ACPTemp = " + String(ACPSensor.avgTemp) + "\r\n";

  String currentPowerMode;
  if (!copy_current_power_mode_value(currentPowerMode)) {
    WriteConsoleLog(F("WARNING! current_power_mode busy"));
    Variables += "error('current_power_mode busy')\r\n";
  } else {
    Variables += "current_power_mode = \"" + currentPowerMode + "\"\r\n";
  }
  Variables += "target_power_volt = " + String(target_power_volt) + "\r\n";

#ifdef USE_WATER_PUMP
  Variables += "wp_count = " + String(wp_count) + "\r\n";
#endif

  return Variables;
}

String get_lua_mode_name(bool filename) {
  String fl;
  if (Samovar_CR_Mode == SAMOVAR_BEER_MODE) {
    if (filename) {
      fl = "/beer" + String(LUA_BEER) + ".lua";
    } else {
      fl = "beer";
    }
  } else if (Samovar_CR_Mode == SAMOVAR_DISTILLATION_MODE) {
    if (filename) {
      fl = "/dist" + String(LUA_DIST) + ".lua";
    } else {
      fl = "dist";
    }
  } else if (Samovar_CR_Mode == SAMOVAR_BK_MODE) {
    if (filename) {
      fl = "/bk" + String(LUA_BK) + ".lua";
    } else {
      fl = "bk";
    }
  } else if (Samovar_CR_Mode == SAMOVAR_NBK_MODE) {
    if (filename) {
      fl = "/nbk" + String(LUA_NBK) + ".lua";
    } else {
      fl = "nbk";
    }
  } else {
    if (filename) {
      fl = "/rectificat" + String(LUA_RECT) + ".lua";
    } else {
      fl = "rect";
    }
  }
  return fl;
}
#endif
