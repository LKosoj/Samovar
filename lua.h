#ifndef __SAMOVAR_LUA_H_
#define __SAMOVAR_LUA_H_

#include "Samovar.h"
#include "samovar_api.h"
#include "numeric_parse.h"
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
volatile bool lua_job_active = false;

inline bool lua_state_mutation_allowed() {
  return !mode_switch_in_progress();
}

inline int lua_reject_state_mutation(lua_State* lua_state) {
  return luaL_error(lua_state, "mode switch blocks state changes");
}

inline bool queue_lua_job(LuaJobType type, const String& script) {
  if (script.length() == 0) return true;
  if (mode_switch_in_progress()) return false;
  bool locked = runtime_state_lock(pdMS_TO_TICKS(500));
  if (!locked) return false;
  bool queued = false;
  if (!mode_switch_in_progress() && lua_job_type == LUA_JOB_NONE) {
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
  if (!mode_switch_in_progress() && lua_job_type != LUA_JOB_NONE) {
    script = lua_job_script;
    type = lua_job_type;
    lua_job_script = "";
    lua_job_type = LUA_JOB_NONE;
    lua_job_active = true;
    hasJob = true;
  }
  runtime_state_unlock(true);
  return hasJob;
}

inline void finish_lua_job() {
  bool locked = runtime_state_lock(portMAX_DELAY);
  if (locked) {
    lua_job_active = false;
    runtime_state_unlock(true);
  }
}

inline bool request_lua_periodic_start() {
  if (mode_switch_in_progress()) return false;
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  bool accepted = false;
  if (!mode_switch_in_progress() && lua_finished && !lua_start_requested) {
    lua_start_requested = true;
    accepted = true;
  }
  runtime_state_unlock(true);
  return accepted;
}

inline bool request_lua_mode_stop() {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  SetScriptOff = true;
  loop_lua_fl = false;
  lua_start_requested = false;
  lua_job_script = "";
  lua_job_type = LUA_JOB_NONE;
  runtime_state_unlock(true);
  return true;
}

inline bool lua_mode_owner_idle() {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  const bool idle = lua_finished && !lua_start_requested &&
                    lua_job_type == LUA_JOB_NONE && !lua_job_active &&
                    !loop_lua_fl;
  runtime_state_unlock(true);
  if (!idle) return false;
  const bool vmIdle = lua_state_lock(0);
  lua_state_unlock(vmIdle);
  return vmIdle;
}

inline bool consume_lua_periodic_start_request(bool& accepted) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  accepted = false;
  if (mode_switch_in_progress()) {
    lua_start_requested = false;
  } else if (lua_start_requested && lua_finished) {
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

enum LuaNumVariableDomain : uint8_t {
  LUA_NUM_INTEGRAL = 0,
  LUA_NUM_FRACTIONAL,
};

struct LuaNumVariableDescriptor {
  const char* name;
  float (*getter)();
  bool (*setter)(int32_t integerValue, float fractionalValue);
  uint8_t access;
  LuaNumVariableDomain domain;
  int32_t minValue;
  int32_t maxValue;
};

static float lua_num_get_WFpulseCount() { return water_pulse_count_get(); }
static bool lua_num_set_WFpulseCount(int32_t value, float) {
  water_pulse_count_set(static_cast<uint16_t>(value));
  return true;
}
static float lua_num_get_pump_started() { return pump_started; }
static bool lua_num_set_pump_started(int32_t value, float) {
  pump_started = value;
  return true;
}
static float lua_num_get_valve_status() { return valve_status; }
static bool lua_num_set_valve_status(int32_t value, float) {
  valve_status = value;
  return true;
}
static float lua_num_get_SamSetup_Mode() { return SamSetup.Mode; }
static bool lua_num_set_SamSetup_Mode(int32_t value, float) {
  return set_lua_mode_value(LUA_MODE_TARGET_SETUP, value);
}
static float lua_num_get_Samovar_Mode() { return Samovar_Mode; }
static bool lua_num_set_Samovar_Mode(int32_t value, float) {
  return set_lua_mode_value(LUA_MODE_TARGET_ACTIVE, value);
}
static float lua_num_get_Samovar_CR_Mode() { return Samovar_CR_Mode; }
static bool lua_num_set_Samovar_CR_Mode(int32_t value, float) {
  return set_lua_mode_value(LUA_MODE_TARGET_CONTROL, value);
}
static float lua_num_get_acceleration_temp() { return acceleration_temp; }
static bool lua_num_set_acceleration_temp(int32_t value, float) {
  acceleration_temp = static_cast<uint16_t>(value);
  return true;
}
#ifdef USE_WATER_PUMP
static float lua_num_get_wp_count() { return wp_count; }
static bool lua_num_set_wp_count(int32_t value, float) {
  wp_count = static_cast<int8_t>(value);
  return true;
}
static bool lua_num_set_pmpKp(int32_t, float value) {
  pump_regulator.Kp = value;
  return true;
}
static bool lua_num_set_pmpKi(int32_t, float value) {
  pump_regulator.Ki = value;
  return true;
}
static bool lua_num_set_pmpKd(int32_t, float value) {
  pump_regulator.Kd = value;
  return true;
}
#endif
static float lua_num_get_SteamTemp() { return SteamSensor.avgTemp; }
static bool lua_num_set_SteamTemp(int32_t, float value) {
  SteamSensor.avgTemp = value;
  return true;
}
static float lua_num_get_boil_temp() { return boil_temp; }
static bool lua_num_set_boil_temp(int32_t, float value) {
  boil_temp = value;
  return true;
}
static float lua_num_get_PipeTemp() { return PipeSensor.avgTemp; }
static bool lua_num_set_PipeTemp(int32_t, float value) {
  PipeSensor.avgTemp = value;
  return true;
}
static float lua_num_get_WaterTemp() { return WaterSensor.avgTemp; }
static bool lua_num_set_WaterTemp(int32_t, float value) {
  WaterSensor.avgTemp = value;
  return true;
}
static float lua_num_get_TankTemp() { return TankSensor.avgTemp; }
static bool lua_num_set_TankTemp(int32_t, float value) {
  TankSensor.avgTemp = value;
  return true;
}
static float lua_num_get_ACPTemp() { return ACPSensor.avgTemp; }
static bool lua_num_set_ACPTemp(int32_t, float value) {
  ACPSensor.avgTemp = value;
  return true;
}
static float lua_num_get_loop_lua_fl() { return loop_lua_fl; }
static bool lua_num_set_loop_lua_fl(int32_t value, float) {
  loop_lua_fl = value;
  return true;
}
static float lua_num_get_SetScriptOff() { return SetScriptOff; }
static bool lua_num_set_SetScriptOff(int32_t value, float) {
  SetScriptOff = value != 0;
  return true;
}
static float lua_num_get_show_lua_script() { return show_lua_script; }
static bool lua_num_set_show_lua_script(int32_t value, float) {
  show_lua_script = value;
  return true;
}
static float lua_num_get_test_num_val() { return test_num_val; }
static bool lua_num_set_test_num_val(int32_t, float value) {
  test_num_val = value;
  return true;
}
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
  {"WFpulseCount", lua_num_get_WFpulseCount, lua_num_set_WFpulseCount,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, UINT16_MAX},
  {"pump_started", lua_num_get_pump_started, lua_num_set_pump_started,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, 1},
  {"valve_status", lua_num_get_valve_status, lua_num_set_valve_status,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, 1},
  {"SamSetup_Mode", lua_num_get_SamSetup_Mode, lua_num_set_SamSetup_Mode,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, SAMOVAR_LUA_MODE},
  {"Samovar_Mode", lua_num_get_Samovar_Mode, lua_num_set_Samovar_Mode,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, SAMOVAR_LUA_MODE},
  {"Samovar_CR_Mode", lua_num_get_Samovar_CR_Mode, lua_num_set_Samovar_CR_Mode,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, SAMOVAR_LUA_MODE},
  {"acceleration_temp", lua_num_get_acceleration_temp, lua_num_set_acceleration_temp,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, UINT16_MAX},
#ifdef USE_WATER_PUMP
  {"wp_count", lua_num_get_wp_count, lua_num_set_wp_count,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, INT8_MIN, INT8_MAX},
  {"pmpKp", nullptr, lua_num_set_pmpKp,
   LUA_VAR_WO, LUA_NUM_FRACTIONAL, 0, 0},
  {"pmpKi", nullptr, lua_num_set_pmpKi,
   LUA_VAR_WO, LUA_NUM_FRACTIONAL, 0, 0},
  {"pmpKd", nullptr, lua_num_set_pmpKd,
   LUA_VAR_WO, LUA_NUM_FRACTIONAL, 0, 0},
#endif
  {"SteamTemp", lua_num_get_SteamTemp, lua_num_set_SteamTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"boil_temp", lua_num_get_boil_temp, lua_num_set_boil_temp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"PipeTemp", lua_num_get_PipeTemp, lua_num_set_PipeTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"WaterTemp", lua_num_get_WaterTemp, lua_num_set_WaterTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"TankTemp", lua_num_get_TankTemp, lua_num_set_TankTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"ACPTemp", lua_num_get_ACPTemp, lua_num_set_ACPTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"loop_lua_fl", lua_num_get_loop_lua_fl, lua_num_set_loop_lua_fl,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, 1},
  {"SetScriptOff", lua_num_get_SetScriptOff, lua_num_set_SetScriptOff,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, 1},
  {"show_lua_script", lua_num_get_show_lua_script, lua_num_set_show_lua_script,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, 1},
  {"test_num_val", lua_num_get_test_num_val, lua_num_set_test_num_val,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"WFtotalMilliLitres", lua_num_get_WFtotalMilliLitres, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"WFflowRate", lua_num_get_WFflowRate, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_volume", lua_num_get_program_volume, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_speed", lua_num_get_program_speed, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_temp", lua_num_get_program_temp, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_power", lua_num_get_program_power, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_time", lua_num_get_program_time, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_capacity_num", lua_num_get_program_capacity_num, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"capacity_num", lua_num_get_capacity_num, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"target_power_volt", lua_num_get_target_power_volt, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"PowerOn", lua_num_get_PowerOn, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"alcohol", lua_num_get_alcohol, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"alcohol_s", lua_num_get_alcohol_s, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"water_pump_speed", lua_num_get_water_pump_speed, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"pressure_value", lua_num_get_pressure_value, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"PauseOn", lua_num_get_PauseOn, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_Wait", lua_num_get_program_Wait, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"YY", lua_num_get_YY, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"MM", lua_num_get_MM, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"DD", lua_num_get_DD, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"HH", lua_num_get_HH, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"MI", lua_num_get_MI, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"SS", lua_num_get_SS, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
};

static const LuaNumVariableDescriptor* find_lua_num_variable(const char* name) {
  if (!name) return nullptr;
  for (size_t i = 0; i < sizeof(lua_num_variables) / sizeof(lua_num_variables[0]); i++) {
    if (strcmp(name, lua_num_variables[i].name) == 0) return &lua_num_variables[i];
  }
  return nullptr;
}

static int lua_numeric_error(
    lua_State* lua_state,
    const char* name,
    NumericParseError error) {
  return luaL_error(
      lua_state, "Invalid %s: %s", name, numeric_parse_error_code(error));
}

// [PKG-F] Две политики для числовых аргументов. Для ВЕЛИЧИН (магнитуд: ШИМ,
// скорость, время, напряжение/мощность) обновлённый luaL_checkinteger кидает
// "number has no integer representation" на нецелых float (напр.
// set_stepper_by_time(0,0,1.5) валил бы скрипт), тогда как старый код молча
// усекал. lua_check_truncated_arg принимает любое число и усекает к нулю
// (как (int)double), с клемпом против UB при |x|>LONG_MAX / NaN. Для
// ИНДЕКСОВ/СЕЛЕКТОРОВ (номер пина, канал, реле, направление и т.п.)
// действует обратная политика — см. lua_check_index_arg ниже: дробное
// значение это ошибка скрипта и должно быть показано, а не спрятано
// усечением.
static long lua_check_truncated_arg(lua_State* lua_state, int index) {
  // Точные целые (Lua-integer или float с целым значением) берём напрямую через
  // lua_tointegerx — без прогона через lua_Number. Иначе при LUA_32BITS (lua_Number =
  // float) целые >2^24 округляются (напр. 2147483647 -> 2147483648) и ломают диапазон.
  int isInteger = 0;
  const lua_Integer asInteger = lua_tointegerx(lua_state, index, &isInteger);
  if (isInteger) return static_cast<long>(asInteger);
  // Дробное число: принимаем и усекаем к нулю (поведение HEAD), с клемпом против UB
  // при |x|>LONG_MAX / NaN.
  const lua_Number rawValue = luaL_checknumber(lua_state, index);
  const double truncated = trunc(static_cast<double>(rawValue));
  if (!isfinite(truncated)) return 0;
  if (truncated <= static_cast<double>(LONG_MIN)) return LONG_MIN;
  if (truncated >= static_cast<double>(LONG_MAX)) return LONG_MAX;
  return static_cast<long>(truncated);
}

// [PKG-F] Проверяем диапазон float В DOUBLE до сужения: сужение double, чья
// величина превышает FLT_MAX, — формально UB (parse_finite_float проверяет
// величину в double по той же причине).
static NumericParseResult lua_narrow_to_float(lua_Number rawValue, float& out) {
  const double value = static_cast<double>(rawValue);
  if (!isfinite(value)) return numeric_parse_result(NUMERIC_PARSE_NOT_FINITE);
  const double magnitude = value < 0.0 ? -value : value;
  if (magnitude > static_cast<double>(FLT_MAX)) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = static_cast<float>(value);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

static int32_t lua_check_int32_arg(
    lua_State* lua_state,
    int index,
    int32_t minValue,
    int32_t maxValue,
    const char* name) {
  const long rawValue = lua_check_truncated_arg(lua_state, index);
  int32_t value = 0;
  const NumericParseResult result = checked_narrow_int32(
      static_cast<int64_t>(rawValue), minValue, maxValue, value);
  if (!result.ok()) lua_numeric_error(lua_state, name, result.error);
  return value;
}

// [PKG-F] Строгая проверка для индексов/селекторов: аргумент обязан быть
// точным целым (lua_tointegerx уже успешен и для Lua-float с целым
// значением). Дробный вход — ошибка скрипта (NUMERIC_PARSE_INVALID_FORMAT),
// а не молчаливое усечение, как в lua_check_int32_arg.
static int32_t lua_check_index_arg(
    lua_State* lua_state,
    int index,
    int32_t minValue,
    int32_t maxValue,
    const char* name) {
  int isInteger = 0;
  const lua_Integer asInteger = lua_tointegerx(lua_state, index, &isInteger);
  if (!isInteger) {
    luaL_checknumber(lua_state, index);  // not a number at all: standard Lua error
    lua_numeric_error(lua_state, name, NUMERIC_PARSE_INVALID_FORMAT);
  }
  int32_t value = 0;
  const NumericParseResult result = checked_narrow_int32(
      static_cast<int64_t>(asInteger), minValue, maxValue, value);
  if (!result.ok()) lua_numeric_error(lua_state, name, result.error);
  return value;
}

static float lua_check_finite_arg(
    lua_State* lua_state,
    int index,
    const char* name) {
  float value = 0.0f;
  const NumericParseResult result =
      lua_narrow_to_float(luaL_checknumber(lua_state, index), value);
  if (!result.ok()) lua_numeric_error(lua_state, name, result.error);
  return value;
}

struct LuaStrVariableDescriptor {
  const char* name;
  bool (*getter)(String& value);
  bool (*setter)(const String& value);
  uint8_t access;
  const char* busy_error;
};

static bool lua_str_get_Msg(String& value) { return copy_web_message_raw(value); }
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
  // [PKG-F] Msg: чтение (getter) продвигает приватный Lua-курсор по кольцу событий
  // (copy_web_message_raw отдаёт следующее непрочитанное сообщение или ""); запись
  // идёт спец-веткой `if (Var == "Msg")` в set_str_variable через append_web_message,
  // поэтому setter намеренно nullptr при доступе RW.
  {"Msg", lua_str_get_Msg, nullptr, LUA_VAR_RW, "Msg busy"},
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

inline bool lua_pin_is_heater_channel(int pin) {
  return pin == RELE_CHANNEL1 || pin == RELE_CHANNEL4;
}

static int lua_wrapper_pinMode(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  int b = lua_check_truncated_arg(lua_state, 2);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (a == RELE_CHANNEL1 || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == LUA_PIN) {
    if (lua_pin_is_heater_channel(a) && heater_safety_latched()) {
      // Защёлка взведена: pinMode(INPUT) отдал бы пин подтяжке платы в обход
      // защёлки, поэтому молча игнорируем; luaL_error оборвал бы весь чанк.
    } else {
      pinMode(a, b);
    }
  }
  return 0;
}

static int lua_wrapper_digitalWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  int b = lua_check_truncated_arg(lua_state, 2);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (a == RELE_CHANNEL1 || a == WATER_PUMP_PIN || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == LUA_PIN
#ifdef ALARM_BTN_PIN
      || a == ALARM_BTN_PIN
#endif
#ifdef BTN_PIN
      || a == BTN_PIN
#endif
     ) {
    // ВНИМАНИЕ: для RELE_CHANNEL2/3 здесь НАМЕРЕННО сырая запись на пин, без инверсии
    // по SamSetup.releN, в отличие от остального C++-тракта (ВКЛ = releN, ВЫКЛ = !releN).
    // Это не упущение: функция повторяет семантику одноимённого примитива Arduino, и все
    // существующие пользовательские скрипты написаны под сырой проход — они уже учитывают
    // полярность своей платы сами. Добавление инверсии молча перевернуло бы миксер и
    // клапан у всех на конфигурации по умолчанию (releN=false), поэтому поведение
    // зафиксировано тестом. Полярность-зависимое управление реле — это отдельная новая
    // функция, а не смена смысла digitalWrite.
    if (lua_pin_is_heater_channel(a) && heater_safety_latched()) {
      // Защёлка аварийного отключения нагрева взведена. C++-тракт уже погасил эти
      // каналы и сам их не подаст, пока защёлка не снята. Lua пишет сырым значением
      // мимо releN-инверсии, поэтому по b нельзя отличить "включить" от "выключить";
      // запись игнорируется молча — luaL_error убил бы весь чанк (общий lua_pcall).
    } else if (a != WATER_PUMP_PIN) digitalWrite(a, b);
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
  int a = lua_check_truncated_arg(lua_state, 1);
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
  const int32_t pin = lua_check_index_arg(lua_state, 1, 0, 15, "pin");
  const int32_t mode = lua_check_index_arg(
      lua_state, 2, INT32_MIN, INT32_MAX, "mode");
  if (mode != INPUT && mode != OUTPUT && mode != INPUT_PULLUP) {
    return lua_numeric_error(lua_state, "mode", NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C expander write timeout");
  }
  expander.pinMode(static_cast<uint8_t>(pin), static_cast<uint8_t>(mode));
  xSemaphoreGive(xI2CSemaphore);
  return 0;
}

static int lua_wrapper_exp_digitalWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t pin = lua_check_index_arg(lua_state, 1, 0, 15, "pin");
  const int32_t value = lua_check_index_arg(
      lua_state, 2, INT32_MIN, INT32_MAX, "value");
  if (value != LOW && value != HIGH) {
    return lua_numeric_error(lua_state, "value", NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C expander write timeout");
  }
  const bool writeOk = expander.digitalWrite(
      static_cast<uint8_t>(pin), static_cast<uint8_t>(value));
  xSemaphoreGive(xI2CSemaphore);
  if (!writeOk) return luaL_error(lua_state, "I2C expander write failed");
  return 0;
}

static int lua_wrapper_exp_digitalRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t pin = lua_check_index_arg(lua_state, 1, 0, 15, "pin");
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C expander read timeout");
  }
  const uint8_t value = expander.digitalRead(static_cast<uint8_t>(pin));
  xSemaphoreGive(xI2CSemaphore);
  lua_pushnumber(lua_state, static_cast<lua_Number>(value));
  return 1;
}
#endif

#ifdef USE_ANALOG_EXPANDER
static int lua_wrapper_exp_analogWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t value = lua_check_int32_arg(
      lua_state, 1, 0, UINT8_MAX, "value");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C analog expander write timeout");
  }
  analog_expander.analogWrite(static_cast<uint8_t>(value));
  xSemaphoreGive(xI2CSemaphore);
  return 0;
}

static int lua_wrapper_exp_analogRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t channel = lua_check_index_arg(
      lua_state, 1, 0, 3, "channel");
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C analog expander read timeout");
  }
  const uint8_t value = analog_expander.analogRead(
      static_cast<uint8_t>(channel));
  xSemaphoreGive(xI2CSemaphore);
  lua_pushnumber(lua_state, static_cast<lua_Number>(value));
  return 1;
}
#endif

static int lua_wrapper_delay(lua_State *lua_state) {
  int a = lua_check_truncated_arg(lua_state, 1);
  vTaskDelay(a / portTICK_PERIOD_MS);
  return 0;
}

static int lua_wrapper_millis(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)millis());
  return 1;
}

static int lua_wrapper_set_pause_withdrawal(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  pause_withdrawal(a);
  return 0;
}

static int lua_wrapper_set_power(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
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
  int a = lua_check_truncated_arg(lua_state, 1);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  set_mixer(a);
  return 0;
}

static int lua_wrapper_open_valve(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  bool a = lua_check_truncated_arg(lua_state, 1);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  open_valve(a, false);
  return 0;
}

#ifdef SAMOVAR_USE_POWER
static int lua_wrapper_set_current_power(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  float a = lua_check_finite_arg(lua_state, 1, "power");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
#ifdef SAMOVAR_USE_SEM_AVR
  a = roundf(a);  // регулятор SEM/AVR: уставка в ваттах
#else
  a = roundf(a * 10.0f) / 10.0f;  // регулятор по напряжению: один знак после запятой
#endif
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
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  set_body_temp();
  return 0;
}

static int lua_wrapper_set_next_program(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
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
  int a = lua_check_truncated_arg(lua_state, 2);
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
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const char* variableName = luaL_checkstring(lua_state, 1);
  const LuaNumVariableDescriptor* descriptor =
      find_lua_num_variable(variableName);
  if (descriptor && (descriptor->access & LUA_VAR_WRITE) && descriptor->setter) {
    int32_t integerValue = 0;
    float fractionalValue = 0.0f;
    NumericParseResult result = numeric_parse_result(NUMERIC_PARSE_OK);
    if (descriptor->domain == LUA_NUM_INTEGRAL) {
      const lua_Integer rawValue = luaL_checkinteger(lua_state, 2);
      result = checked_narrow_int32(
          static_cast<int64_t>(rawValue), descriptor->minValue,
          descriptor->maxValue, integerValue);
    } else {
      // [PKG-F] Проверяем диапазон float в double ДО сужения (иначе UB при |x|>FLT_MAX).
      result = lua_narrow_to_float(luaL_checknumber(lua_state, 2), fractionalValue);
    }
    if (!result.ok()) {
      return lua_numeric_error(lua_state, variableName, result.error);
    }
    if (!descriptor->setter(integerValue, fractionalValue)) {
      return luaL_error(lua_state, "%s busy", variableName);
    }
  } else {
    const lua_Number value = luaL_checknumber(lua_state, 2);
    if (variableName[0] != '\0') {
      WriteConsoleLog(
          "UNDEF NUMERIC LUA VAR " + String(variableName) + " = " +
          String(static_cast<float>(value)));
    }
  }
  return 0;
}

static int lua_wrapper_get_num_variable(lua_State *lua_state) {
  float a = 0;
  String Var = lua_to_string_arg(lua_state, 1);
  const LuaNumVariableDescriptor* descriptor = find_lua_num_variable(Var.c_str());
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
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const char* errorMessage = nullptr;
  {
    String Var = lua_to_string_arg(lua_state, 1);
    String Val = lua_to_string_arg(lua_state, 2);
    if (Var == "Msg") {
      const RuntimeEventPublishResult result = append_web_message(Val, NOTIFY_MSG);
      if (result == RUNTIME_EVENT_PUBLISH_OK || result == RUNTIME_EVENT_PUBLISH_EMPTY) return 0;
      if (result == RUNTIME_EVENT_PUBLISH_LOCK_BUSY) errorMessage = "Msg busy";
      else if (result == RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG) errorMessage = "Msg too long";
      else errorMessage = "Msg event store corrupt";
    } else {
      const LuaStrVariableDescriptor* descriptor = find_lua_str_variable(Var);
      if (descriptor && (descriptor->access & LUA_VAR_WRITE) && descriptor->setter) {
        if (!descriptor->setter(Val)) errorMessage = descriptor->busy_error ? descriptor->busy_error : "Lua string variable busy";
      } else if (descriptor) {
        WriteConsoleLog("WARNING! " + Var + " is read only property");
      } else if (Var.length() > 0) {
        WriteConsoleLog("UNDEF STRING LUA VAR " + Var + " = " + Val);
      }
    }
  }
  if (errorMessage) return luaL_error(lua_state, "%s", errorMessage);
  return 0;
}

static int lua_wrapper_set_object(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
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
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  bool statusSet = false;
  {
    String Var = lua_to_string_arg(lua_state, 1);
    statusSet = set_lua_status_value(Var);
  }
  if (!statusSet) return luaL_error(lua_state, "Lua_status busy");
  return 0;
}

static int lua_wrapper_set_capacity(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  if (a < 0 || a > CAPACITY_NUM) return luaL_error(lua_state, "capacity out of range");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  set_capacity((uint8_t)a);
  return 0;
}

#ifdef USE_WATER_PUMP
static int lua_wrapper_set_pump_pwm(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  // [PKG-F] Ограничиваем ШИМ насоса 0..1023 (10-битный pump_pwm, constrain(0,1023)
  // в pumppwm.h; water_pump_speed тоже 0..1023). Float-вход усекается до целого.
  const int32_t duty = lua_check_int32_arg(lua_state, 1, 0, 1023, "pwm");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  pump_pwm.write(duty);
  water_pump_speed = duty;
  return 0;
}
#endif

static int lua_wrapper_set_timer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = luaL_checknumber(lua_state, 1);
  if (a < 1 || a > 10) return 0;
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
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
  const int32_t speed = lua_check_int32_arg(
      lua_state, 1, 0, UINT16_MAX, "speed");
  const int32_t direction = lua_check_index_arg(
      lua_state, 2, 0, 1, "direction");
  const int32_t seconds = lua_check_int32_arg(
      lua_state, 3, 0, UINT16_MAX, "time");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const bool started = set_stepper_by_time(
      static_cast<uint16_t>(speed), static_cast<uint8_t>(direction),
      static_cast<uint16_t>(seconds));
  lua_pushnumber(lua_state, static_cast<lua_Number>(started));
  return 1;
}

static int lua_wrapper_set_stepper_target(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t speed = lua_check_int32_arg(
      lua_state, 1, 0, UINT16_MAX, "speed");
  const int32_t direction = lua_check_index_arg(
      lua_state, 2, 0, 1, "direction");
  const int32_t target = lua_check_int32_arg(
      lua_state, 3, 0, INT32_MAX, "target");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const bool started = set_stepper_target(
      static_cast<uint16_t>(speed), static_cast<uint8_t>(direction),
      static_cast<uint32_t>(target));
  lua_pushnumber(lua_state, static_cast<lua_Number>(started));
  return 1;
}

static int lua_wrapper_get_stepper_status(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)get_stepper_status());
  return 1;
}

static int lua_wrapper_i2cpump_start(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  // Плохие ЧИСЛА (NaN/Inf/<=0) - молчаливый возврат 0, без luaL_error: lua_pcall в
  // проекте один (lua.h:77) и оборачивает весь чанк пользователя целиком, поэтому
  // ошибка тут убивала бы весь скрипт из-за одного вызова насоса. Раньше
  // luaL_checknumber пропускал NaN/Inf дальше, NaN<=0 давало false, и мусор уходил
  // в расчёт. На аргументе, который вообще не число, luaL_checknumber по-прежнему
  // валит чанк - так во всех обёртках этого файла, это общая конвенция, а не
  // недосмотр. Проверка железа стоит первой в условии, как раньше.
  const lua_Number rawRate = luaL_checknumber(lua_state, 1);
  const lua_Number rawVolume = luaL_checknumber(lua_state, 2);
  float speedRate = 0.0f;
  float volumeMl = 0.0f;
  const bool rateFinite = lua_narrow_to_float(rawRate, speedRate).ok();
  const bool volumeFinite = lua_narrow_to_float(rawVolume, volumeMl).ok();
  if (use_I2C_dev != 2 || !rateFinite || !volumeFinite || speedRate <= 0.0f || volumeMl <= 0.0f) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  const uint16_t stepsPerMl = SamSetup.StepperStepMlI2C > 0
      ? SamSetup.StepperStepMlI2C
      : I2C_STEPPER_STEP_ML_DEFAULT;
  uint32_t targetSteps = 0;
  const NumericParseResult targetResult = checked_truncating_product_u32(
      static_cast<double>(volumeMl), static_cast<double>(stepsPerMl),
      targetSteps);
  if (!targetResult.ok()) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  const float speedValue = i2c_get_speed_from_rate(speedRate);
  const NumericParseResult speedResult = validate_bounded_finite_float(
      speedValue, 1.0f, static_cast<float>(UINT16_MAX));
  if (!speedResult.ok()) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const uint16_t speedSteps = static_cast<uint16_t>(speedValue);
  I2CPumpCmdSpeed = speedSteps;
  I2CPumpTargetSteps = targetSteps;
  I2CPumpTargetMl = volumeMl;
  const bool started = set_stepper_target(speedSteps, 0, targetSteps);
  lua_pushnumber(lua_state, static_cast<lua_Number>(started));
  return 1;
}

static int lua_wrapper_i2cpump_stop(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const bool stopped = set_stepper_target(0, 0, 0);
  I2CPumpTargetSteps = 0;
  I2CPumpTargetMl = 0;
  I2CPumpCmdSpeed = 0;
  lua_pushnumber(lua_state, static_cast<lua_Number>(stopped));
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
  const int32_t target = lua_check_index_arg(
      lua_state, 1, 0, 1, "target");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const bool started = set_mixer_pump_target(static_cast<uint8_t>(target));
  lua_pushnumber(lua_state, static_cast<lua_Number>(started));
  return 1;
}

static int lua_wrapper_get_mixer_pump_status(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)get_mixer_pump_status());
  return 1;
}

static int lua_wrapper_check_I2C_device(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = lua_check_truncated_arg(lua_state, 1);
  lua_pushnumber(lua_state, (lua_Number)check_I2C_device(a));
  return 1;
}

static int lua_wrapper_set_i2c_rele_state(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t relay = lua_check_index_arg(
      lua_state, 1, 1, 4, "relay");
  const int32_t state = lua_check_index_arg(
      lua_state, 2, 0, 1, "state");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const bool changed = set_i2c_rele_state(
      static_cast<uint8_t>(relay), state != 0);
  lua_pushnumber(lua_state, static_cast<lua_Number>(changed));
  return 1;
}

static int lua_wrapper_get_i2c_rele_state(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t relay = lua_check_index_arg(
      lua_state, 1, 1, 4, "relay");
  lua_pushnumber(
      lua_state,
      static_cast<lua_Number>(get_i2c_rele_state(static_cast<uint8_t>(relay))));
  return 1;
}

void lua_init() {
  lua.Lua_register("pinMode", &lua_wrapper_pinMode);
  lua.Lua_register("digitalWrite", &lua_wrapper_digitalWrite);
  lua.Lua_register("digitalRead", &lua_wrapper_digitalRead);
  lua.Lua_register("analogRead", &lua_wrapper_analogRead);
#ifdef USE_EXPANDER
  lua.Lua_register("exp_pinMode", &lua_wrapper_exp_pinMode);
  lua.Lua_register("exp_digitalWrite", &lua_wrapper_exp_digitalWrite);
  lua.Lua_register("exp_digitalRead", &lua_wrapper_exp_digitalRead);
#endif
#ifdef USE_ANALOG_EXPANDER
  lua.Lua_register("exp_analogWrite", &lua_wrapper_exp_analogWrite);
  lua.Lua_register("exp_analogRead", &lua_wrapper_exp_analogRead);
#endif
  lua.Lua_register("delay", &lua_wrapper_delay);
  lua.Lua_register("millis", &lua_wrapper_millis);
  lua.Lua_register("sendMsg", &lua_wrapper_send_msg);

  lua.Lua_register("setPower", &lua_wrapper_set_power);
  lua.Lua_register("setBodyTemp", &lua_wrapper_set_body_temp);
  lua.Lua_register("setAlarm", &lua_wrapper_set_alarm);
  lua.Lua_register("setNumVariable", &lua_wrapper_set_num_variable);
  lua.Lua_register("setStrVariable", &lua_wrapper_set_str_variable);
  lua.Lua_register("setObject", &lua_wrapper_set_object);
  lua.Lua_register("setLuaStatus", &lua_wrapper_set_lua_status);
#ifdef USE_WATER_PUMP
  lua.Lua_register("setPumpPwm", &lua_wrapper_set_pump_pwm);
#endif
#ifdef SAMOVAR_USE_POWER
  lua.Lua_register("setCurrentPower", &lua_wrapper_set_current_power);
#endif
  lua.Lua_register("setMixer", &lua_wrapper_set_mixer);
  lua.Lua_register("setNextProgram", &lua_wrapper_set_next_program);
  lua.Lua_register("setPauseWithdrawal", &lua_wrapper_set_pause_withdrawal);
  lua.Lua_register("setTimer", &lua_wrapper_set_timer);
  lua.Lua_register("setCapacity", &lua_wrapper_set_capacity);

  lua.Lua_register("openValve", &lua_wrapper_open_valve);

  lua.Lua_register("getNumVariable", &lua_wrapper_get_num_variable);
  lua.Lua_register("getStrVariable", &lua_wrapper_get_str_variable);
  lua.Lua_register("getState", &lua_wrapper_get_state);
  lua.Lua_register("getObject", &lua_wrapper_get_object);
  lua.Lua_register("getTimer", &lua_wrapper_get_timer);
  lua.Lua_register("http_request", &lua_wrapper_http_request);

  lua.Lua_register("check_I2C_device", &lua_wrapper_check_I2C_device);
  lua.Lua_register("set_stepper_by_time", &lua_wrapper_set_stepper_by_time);
  lua.Lua_register("set_stepper_target", &lua_wrapper_set_stepper_target);
  lua.Lua_register("get_stepper_status", &lua_wrapper_get_stepper_status);
  lua.Lua_register("i2cpump_start", &lua_wrapper_i2cpump_start);
  lua.Lua_register("i2cpump_stop", &lua_wrapper_i2cpump_stop);
  lua.Lua_register("i2cpump_get_speed", &lua_wrapper_i2cpump_get_speed);
  lua.Lua_register("i2cpump_get_target_ml", &lua_wrapper_i2cpump_get_target_ml);
  lua.Lua_register("i2cpump_get_remaining_ml", &lua_wrapper_i2cpump_get_remaining_ml);
  lua.Lua_register("i2cpump_get_running", &lua_wrapper_i2cpump_get_running);
  lua.Lua_register("set_mixer_pump_target", &lua_wrapper_set_mixer_pump_target);
  lua.Lua_register("get_mixer_pump_status", &lua_wrapper_get_mixer_pump_status);

  lua.Lua_register("get_i2c_rele_state", &lua_wrapper_get_i2c_rele_state);
  lua.Lua_register("set_i2c_rele_state", &lua_wrapper_set_i2c_rele_state);

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
        // [PKG-F] Свежий one-shot job начинает читать Msg «с текущего момента»:
        // сбрасываем приватный Lua-курсор на новейшее событие (вне runtime_state_lock,
        // одиночный писатель — задача do_lua_script).
        reset_lua_message_cursor();
        bool lua_locked = false;
        lua_locked = lua_state_lock(portMAX_DELAY);
        if (!lua_locked) {
          finish_lua_job();
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
        finish_lua_job();
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
