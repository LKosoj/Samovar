#!/usr/bin/env python3
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
LUA = strip_cpp_comments((ROOT / "lua.h").read_text(encoding="utf-8"))
SAMOVAR = strip_cpp_comments((ROOT / "Samovar.ino").read_text(encoding="utf-8"))
API = strip_cpp_comments((ROOT / "samovar_api.h").read_text(encoding="utf-8"))
WEB = strip_cpp_comments((ROOT / "WebServer.ino").read_text(encoding="utf-8"))
ERRORS: list[str] = []


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        ERRORS.append(str(exc))
        return ""


for token in [
    "enum LuaModeTarget",
    "bool set_lua_mode_value(LuaModeTarget target, int32_t value);",
]:
    if token not in API:
        ERRORS.append(f"samovar_api.h missing A-07 mode-owner contract: {token}")

enum_start = API.find("enum LuaModeTarget")
enum_end = API.find("};", enum_start)
declaration_start = API.find(
    "bool set_lua_mode_value(LuaModeTarget target, int32_t value);"
)
api_lua_guard = API.rfind("#ifdef USE_LUA", 0, declaration_start)
api_lua_guard_end = API.find("#endif", declaration_start)
api_lua_region = API[api_lua_guard : api_lua_guard_end + len("#endif")]
api_lua_directives = re.findall(
    r"(?m)^\s*(#(?:if|ifdef|ifndef|elif|else|endif)\b[^\n]*)", api_lua_region
)
if not (
    API.count("enum LuaModeTarget") == 1
    and enum_start >= 0
    and enum_start < enum_end < api_lua_guard < declaration_start < api_lua_guard_end
    and API[api_lua_guard:declaration_start].strip().endswith("#ifdef USE_LUA")
    and api_lua_directives == ["#ifdef USE_LUA", "#endif"]
    and API.count("bool set_lua_mode_value(LuaModeTarget target, int32_t value);") == 1
):
    ERRORS.append(
        "LuaModeTarget must be unconditionally visible before the single Lua-only owner declaration"
    )

definition_start = SAMOVAR.find(
    "bool set_lua_mode_value(LuaModeTarget target, int32_t value)"
)
definition_guard = SAMOVAR.rfind("#ifdef USE_LUA", 0, definition_start)
definition_guard_end = SAMOVAR.find("#endif", definition_start)
lua_include_start = SAMOVAR.find('#include "lua.h"')
lua_include_guard = SAMOVAR.rfind("#ifdef USE_LUA", 0, lua_include_start)
lua_include_guard_end = SAMOVAR.find("#endif", lua_include_start)
if not (
    SAMOVAR.count("bool set_lua_mode_value(LuaModeTarget target, int32_t value)") == 1
    and definition_guard < definition_start < definition_guard_end
    and SAMOVAR[definition_guard:definition_start].strip().endswith("#ifdef USE_LUA")
    and SAMOVAR.count('#include "lua.h"') == 1
    and lua_include_guard < lua_include_start < lua_include_guard_end
    and SAMOVAR[lua_include_guard:lua_include_start].strip().endswith("#ifdef USE_LUA")
):
    ERRORS.append(
        "Lua mode owner definition and lua.h registration surface must remain Lua-only"
    )

owner = body(SAMOVAR, "bool set_lua_mode_value")
for token in [
    "pending_command_lock(pdMS_TO_TICKS(50))",
    "profile_operation_phase_load() != PROFILE_OPERATION_EMPTY",
    "mode_switch_in_progress()",
    "pending_command_unlock(true)",
]:
    if owner and token not in owner:
        ERRORS.append(f"Lua mode owner missing token: {token}")

set_num = body(LUA, "static int lua_wrapper_set_num_variable")
for token in [
    "luaL_checkinteger(lua_state, 2)",
    "luaL_checknumber(lua_state, 2)",
    "checked_narrow_int32",
    "lua_numeric_error",
]:
    if token not in set_num:
        ERRORS.append(f"setNumVariable missing checked typed path: {token}")
for forbidden in ["String Var", "float a = luaL_checknumber"]:
    if forbidden in set_num:
        ERRORS.append(f"setNumVariable retains unsafe path: {forbidden}")

numeric_error = body(LUA, "static int lua_numeric_error")
if "numeric_parse_error_code(error)" not in numeric_error:
    ERRORS.append("Lua numeric errors do not use stable production error codes")

for signature, required, forbidden in [
    ("static int lua_wrapper_exp_pinMode", ["I2C expander write timeout"], []),
    ("static int lua_wrapper_exp_digitalWrite", ["I2C expander write timeout", "if (!writeOk)"], []),
    ("static int lua_wrapper_exp_analogWrite", ["I2C analog expander write timeout"], []),
    ("static int lua_wrapper_set_stepper_by_time", ["lua_check_int32_arg", "lua_check_index_arg"], ["uint16_t a = luaL_checkinteger"]),
    ("static int lua_wrapper_set_stepper_target", ["lua_check_int32_arg", "lua_check_index_arg"], ["uint32_t c = luaL_checkinteger"]),
    ("static int lua_wrapper_i2cpump_start", ["checked_truncating_product_u32", "i2c_get_speed_from_rate"], ["(uint32_t)(volumeMl * stepsPerMl)"]),
    ("static int lua_wrapper_i2cpump_stop", ["const bool stopped = set_stepper_target", "stopped"], ["lua_pushnumber(lua_state, 1)"]),
    ("static int lua_wrapper_set_mixer_pump_target", ["lua_check_index_arg"], ["uint8_t a = luaL_checkinteger", "lua_check_int32_arg"]),
    ("static int lua_wrapper_set_i2c_rele_state", ["lua_check_index_arg"], ["uint8_t a = luaL_checkinteger", "lua_check_int32_arg"]),
    ("static int lua_wrapper_get_i2c_rele_state", ["lua_check_index_arg"], ["uint8_t a = luaL_checkinteger", "lua_check_int32_arg"]),
]:
    callback = body(LUA, signature)
    for token in required:
        if callback and token not in callback:
            ERRORS.append(f"{signature} missing token: {token}")
    for token in forbidden:
        if token in callback:
            ERRORS.append(f"{signature} retains unsafe token: {token}")

for direct in [
    "SamSetup.Mode = (int)value",
    "Samovar_Mode = newMode",
    "change_samovar_mode();",
    "Samovar_CR_Mode = (SAMOVAR_MODE)value",
]:
    if direct in LUA:
        ERRORS.append(f"lua.h retains direct mode mutation: {direct}")

a07_surface = set_num + owner
for signature, _, _ in [
    ("static int lua_wrapper_exp_pinMode", [], []),
    ("static int lua_wrapper_exp_digitalWrite", [], []),
    ("static int lua_wrapper_exp_digitalRead", [], []),
    ("static int lua_wrapper_exp_analogWrite", [], []),
    ("static int lua_wrapper_exp_analogRead", [], []),
    ("static int lua_wrapper_set_stepper_by_time", [], []),
    ("static int lua_wrapper_set_stepper_target", [], []),
    ("static int lua_wrapper_i2cpump_start", [], []),
    ("static int lua_wrapper_i2cpump_stop", [], []),
    ("static int lua_wrapper_set_mixer_pump_target", [], []),
    ("static int lua_wrapper_set_i2c_rele_state", [], []),
    ("static int lua_wrapper_get_i2c_rele_state", [], []),
]:
    a07_surface += body(LUA, signature)
for forbidden in ["xTaskCreate", "OperationStore", "AsyncWebServer", "server.on("]:
    if forbidden in a07_surface:
        ERRORS.append(f"A-07 introduced out-of-scope lifecycle/route token: {forbidden}")

registrations = re.findall(r'lua\.Lua_register\("([^"]+)"', LUA)
expected_registrations = [
    "pinMode", "digitalWrite", "digitalRead", "analogRead", "exp_pinMode",
    "exp_digitalWrite", "exp_digitalRead", "exp_analogWrite",
    "exp_analogRead", "delay", "millis", "sendMsg", "setPower",
    "setBodyTemp", "setAlarm", "setNumVariable", "setStrVariable",
    "setObject", "setLuaStatus", "setPumpPwm", "setCurrentPower",
    "setMixer", "setNextProgram", "setPauseWithdrawal", "setTimer",
    "setCapacity", "openValve", "getNumVariable", "getStrVariable",
    "getState", "getObject", "getTimer", "http_request",
    "check_I2C_device", "set_stepper_by_time", "set_stepper_target",
    "get_stepper_status", "i2cpump_start", "i2cpump_stop",
    "i2cpump_get_speed", "i2cpump_get_target_ml",
    "i2cpump_get_remaining_ml", "i2cpump_get_running",
    "set_mixer_pump_target", "get_mixer_pump_status",
    "get_i2c_rele_state", "set_i2c_rele_state",
]
if registrations != expected_registrations:
    ERRORS.append("Lua registration names/order/cardinality changed")
if len(registrations) != len(set(registrations)):
    ERRORS.append("Lua registration names contain duplicates")

descriptor_table_start = LUA.find(
    "static const LuaNumVariableDescriptor lua_num_variables[]"
)
descriptor_table_end = LUA.find(
    "static const LuaNumVariableDescriptor* find_lua_num_variable",
    descriptor_table_start,
)
descriptor_names = re.findall(
    r'\{\s*"([^"]+)"', LUA[descriptor_table_start:descriptor_table_end]
)
expected_descriptor_names = [
    "WFpulseCount", "pump_started", "valve_status", "SamSetup_Mode",
    "Samovar_Mode", "Samovar_CR_Mode", "acceleration_temp", "wp_count",
    "pmpKp", "pmpKi", "pmpKd", "SteamTemp", "boil_temp", "PipeTemp",
    "WaterTemp", "TankTemp", "ACPTemp", "loop_lua_fl", "SetScriptOff",
    "show_lua_script", "test_num_val", "WFtotalMilliLitres", "WFflowRate",
    "program_volume", "program_speed", "program_temp", "program_power",
    "program_time", "program_capacity_num", "capacity_num",
    "target_power_volt", "PowerOn", "alcohol", "alcohol_s",
    "water_pump_speed", "pressure_value", "PauseOn", "program_Wait", "YY",
    "MM", "DD", "HH", "MI", "SS",
]
if descriptor_names != expected_descriptor_names or len(descriptor_names) != 44:
    ERRORS.append("Lua numeric descriptor names/order/cardinality changed")


def definition(source: str, signature: str) -> str:
    return f"{signature} {{\n{extract_function_body(source, signature)}\n}}\n"


def run_behavioral_harness() -> tuple[int, str, str]:
    descriptor_start = LUA.find("enum LuaVariableAccess")
    descriptor_end = LUA.find("struct LuaStrVariableDescriptor")
    if descriptor_start < 0 or descriptor_end <= descriptor_start:
        return 1, "", "failed to extract Lua numeric descriptor region\n"

    state_helpers = "\n".join(
        definition(LUA, signature)
        for signature in [
            "inline bool lua_state_mutation_allowed()",
            "inline int lua_reject_state_mutation(lua_State* lua_state)",
        ]
    )
    string_helper = definition(
        LUA, "static String lua_to_string_arg(lua_State *lua_state, int index)"
    )
    callback_signatures = [
        "static int lua_wrapper_set_num_variable(lua_State *lua_state)",
        "static int lua_wrapper_set_str_variable(lua_State *lua_state)",
        "static int lua_wrapper_set_object(lua_State *lua_state)",
        "static int lua_wrapper_set_lua_status(lua_State *lua_state)",
        "static int lua_wrapper_exp_pinMode(lua_State *lua_state)",
        "static int lua_wrapper_exp_digitalWrite(lua_State *lua_state)",
        "static int lua_wrapper_exp_digitalRead(lua_State *lua_state)",
        "static int lua_wrapper_exp_analogWrite(lua_State *lua_state)",
        "static int lua_wrapper_exp_analogRead(lua_State *lua_state)",
        "static int lua_wrapper_set_stepper_by_time(lua_State *lua_state)",
        "static int lua_wrapper_set_stepper_target(lua_State *lua_state)",
        "static int lua_wrapper_i2cpump_start(lua_State *lua_state)",
        "static int lua_wrapper_i2cpump_stop(lua_State *lua_state)",
        "static int lua_wrapper_set_mixer_pump_target(lua_State *lua_state)",
        "static int lua_wrapper_set_i2c_rele_state(lua_State *lua_state)",
        "static int lua_wrapper_get_i2c_rele_state(lua_State *lua_state)",
        "static int lua_wrapper_set_current_power(lua_State *lua_state)",
    ]
    callbacks = "\n".join(definition(LUA, signature) for signature in callback_signatures)
    mode_validator = (
        "bool is_valid_samovar_mode(long mode) {\n"
        f"{extract_function_body(WEB, 'bool is_valid_samovar_mode(long mode) {')}\n"
        "}\n"
    )
    owner_definition = (
        f"{mode_validator}\n"
        "bool set_lua_mode_value(LuaModeTarget target, int32_t value) {\n"
        f"{owner}\n"
        "}\n"
    )

    harness = r'''
#include <cfloat>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <iostream>
#include <limits>
#include <string>

extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}

#include "numeric_parse.h"

#define USE_WATER_PUMP 1
#define INPUT 1
#define OUTPUT 3
#define INPUT_PULLUP 5
#define LOW 0
#define HIGH 1
#define pdTRUE 1
#define portTICK_RATE_MS 1
#define portTICK_PERIOD_MS 1
#define EXPANDER_UPDATE_TIMEOUT 500
#define I2C_STEPPER_STEP_ML_DEFAULT 16000
#define pdMS_TO_TICKS(value) (value)

using TickType_t = uint32_t;

enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE = 0,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE,
};

enum LuaModeTarget : uint8_t {
  LUA_MODE_TARGET_SETUP = 0,
  LUA_MODE_TARGET_ACTIVE,
  LUA_MODE_TARGET_CONTROL,
};

enum ProfileOperationPhase : uint8_t {
  PROFILE_OPERATION_EMPTY = 0,
  PROFILE_OPERATION_QUEUED,
  PROFILE_OPERATION_RUNNING,
  PROFILE_OPERATION_MODE_SWITCH,
  PROFILE_OPERATION_TERMINAL_PENDING,
  PROFILE_OPERATION_FAILED_CLOSED,
};

struct SetupFake {
  int32_t Mode;
  uint16_t StepperStepMlI2C;
  uint16_t StepperStepMl;
  int TimeZone;
};

struct SensorFake { float avgTemp; };
struct PumpRegulatorFake { float Kp; float Ki; float Kd; };
struct WProgram {
  float Volume;
  float Speed;
  float Temp;
  float Power;
  float Time;
  float capacity_num;
};

int liveStringCount = 0;

class String : public std::string {
 public:
  using std::string::operator=;

  String() { liveStringCount++; }
  String(const char* value) : std::string(value ? value : "") {
    liveStringCount++;
  }
  String(const std::string& value) : std::string(value) {
    liveStringCount++;
  }
  String(const String& value) : std::string(value) { liveStringCount++; }
  explicit String(float value) : std::string(std::to_string(value)) {
    liveStringCount++;
  }
  ~String() { liveStringCount--; }
};

String operator+(const char* left, const String& right) {
  return String(std::string(left ? left : "") + right);
}
String operator+(const String& left, const char* right) {
  return String(static_cast<const std::string&>(left) + (right ? right : ""));
}
String operator+(const String& left, const String& right) {
  return String(
      static_cast<const std::string&>(left) +
      static_cast<const std::string&>(right));
}
void WriteConsoleLog(const String&) {}

SetupFake SamSetup{};
SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
SAMOVAR_MODE Samovar_CR_Mode = SAMOVAR_RECTIFICATION_MODE;
SensorFake SteamSensor{}, PipeSensor{}, WaterSensor{}, TankSensor{}, ACPSensor{};
PumpRegulatorFake pump_regulator{};
WProgram fakeProgram{};
bool fakeProgramAvailable = false;
uint16_t waterPulseCount = 0;
int pump_started = 0;
int valve_status = 0;
uint16_t acceleration_temp = 0;
int8_t wp_count = 0;
float boil_temp = 0.0f;
int loop_lua_fl = 0;
bool SetScriptOff = false;
int show_lua_script = 0;
float test_num_val = 0.0f;
float WFtotalMilliLitres = 0.0f;
float WFflowRate = 0.0f;
float capacity_num = 0.0f;
float target_power_volt = 0.0f;
bool PowerOn = false;
float alcohol_s = 0.0f;
float water_pump_speed = 0.0f;
float pressure_value = 0.0f;
bool PauseOn = false;
float program_Wait = 0.0f;

void water_pulse_count_set(uint16_t value) { waterPulseCount = value; }
uint16_t water_pulse_count_get() { return waterPulseCount; }
float get_alcohol(float value) { return value; }
int year(std::time_t) { return 2026; }
int month(std::time_t) { return 7; }
int day(std::time_t) { return 13; }
int hour(std::time_t) { return 12; }
int minute(std::time_t) { return 34; }
int second(std::time_t) { return 56; }
static bool lua_copy_current_program(WProgram& currentProgram) {
  currentProgram = fakeProgram;
  return fakeProgramAvailable;
}

bool pendingLockAvailable = true;
int pendingLockCalls = 0;
int pendingUnlockCount = 0;
bool modeSwitchActive = false;
bool bypassOuterModeSwitchCheck = false;
int modeSwitchCheckCalls = 0;
ProfileOperationPhase profilePhase = PROFILE_OPERATION_EMPTY;
int changeModeCalls = 0;

bool pending_command_lock(TickType_t) {
  pendingLockCalls++;
  return pendingLockAvailable;
}
void pending_command_unlock(bool locked) { if (locked) pendingUnlockCount++; }
ProfileOperationPhase profile_operation_phase_load() { return profilePhase; }
bool mode_switch_in_progress() {
  modeSwitchCheckCalls++;
  if (bypassOuterModeSwitchCheck && modeSwitchCheckCalls == 1) return false;
  return modeSwitchActive;
}
void change_samovar_mode() {
  changeModeCalls++;
  Samovar_CR_Mode = Samovar_Mode;
}

__OWNER__

__STATE_HELPERS__

__STRING_HELPER__

__DESCRIPTORS__

enum RuntimeEventPublishResult : uint8_t {
  RUNTIME_EVENT_PUBLISH_OK = 0,
  RUNTIME_EVENT_PUBLISH_EMPTY,
  RUNTIME_EVENT_PUBLISH_LOCK_BUSY,
  RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG,
  RUNTIME_EVENT_PUBLISH_CORRUPT,
};

static const int NOTIFY_MSG = 1;
RuntimeEventPublishResult runtimeEventResult = RUNTIME_EVENT_PUBLISH_OK;
int runtimeEventCalls = 0;
std::string lastRuntimeEventText;

RuntimeEventPublishResult append_web_message(const String& value, int) {
  runtimeEventCalls++;
  if (runtimeEventResult == RUNTIME_EVENT_PUBLISH_OK ||
      runtimeEventResult == RUNTIME_EVENT_PUBLISH_EMPTY) {
    lastRuntimeEventText = value;
  }
  return runtimeEventResult;
}

struct LuaStrVariableDescriptor {
  const char* name;
  bool (*getter)(String& value);
  bool (*setter)(const String& value);
  uint8_t access;
  const char* busy_error;
};

bool stringSetterResult = true;
int stringSetterCalls = 0;
std::string lastStringValue;

bool fake_string_setter(const String& value) {
  stringSetterCalls++;
  if (stringSetterResult) lastStringValue = value;
  return stringSetterResult;
}

static const LuaStrVariableDescriptor lua_str_variables[] = {
  {"SamovarStatus", nullptr, fake_string_setter, LUA_VAR_WRITE,
   "SamovarStatus busy"},
  {"test_str_val", nullptr, fake_string_setter, LUA_VAR_WRITE, nullptr},
};

static const LuaStrVariableDescriptor* find_lua_str_variable(
    const String& name) {
  for (const LuaStrVariableDescriptor& descriptor : lua_str_variables) {
    if (name == descriptor.name) return &descriptor;
  }
  return nullptr;
}

struct LuaObjectFake {
  int putCalls = 0;
  std::string lastKey;
  std::string lastValue;

  void put(const String& key, const String& value) {
    putCalls++;
    lastKey = key;
    lastValue = value;
  }
} luaObject;

LuaObjectFake* luaObj = &luaObject;

bool luaStatusSetResult = true;
int luaStatusSetCalls = 0;
std::string lastLuaStatus;

bool set_lua_status_value(const String& value) {
  luaStatusSetCalls++;
  if (luaStatusSetResult) lastLuaStatus = value;
  return luaStatusSetResult;
}

void vTaskDelay(TickType_t) {}

bool semaphoreAvailable = true;
int semaphoreTakeCount = 0;
int semaphoreGiveCount = 0;
int xI2CSemaphore = 1;
int xSemaphoreTake(int, TickType_t) {
  semaphoreTakeCount++;
  return semaphoreAvailable ? pdTRUE : 0;
}
void xSemaphoreGive(int) { semaphoreGiveCount++; }

struct ExpanderFake {
  int pinModeCalls = 0;
  int digitalWriteCalls = 0;
  int digitalReadCalls = 0;
  bool writeResult = true;
  uint8_t readResult = 0;
  void pinMode(uint8_t, uint8_t) { pinModeCalls++; }
  bool digitalWrite(uint8_t, uint8_t) {
    digitalWriteCalls++;
    return writeResult;
  }
  uint8_t digitalRead(uint8_t) {
    digitalReadCalls++;
    return readResult;
  }
} expander;

struct AnalogExpanderFake {
  int writeCalls = 0;
  int readCalls = 0;
  uint8_t readResult = 0;
  void analogWrite(uint8_t) { writeCalls++; }
  uint8_t analogRead(uint8_t) {
    readCalls++;
    return readResult;
  }
} analog_expander;

bool stepperByTimeResult = true;
bool stepperTargetResult = true;
bool mixerTargetResult = true;
bool relaySetResult = true;
uint8_t relayReadResult = 0;
float speedFromRateResult = 1.0f;
int stepperByTimeCalls = 0;
int stepperTargetCalls = 0;
int mixerTargetCalls = 0;
int relaySetCalls = 0;
int relayReadCalls = 0;
int speedFromRateCalls = 0;
uint16_t lastSpeed = 0;
uint8_t lastDirection = 0;
uint16_t lastTime = 0;
uint32_t lastTarget = 0;
float lastRate = 0.0f;
int use_I2C_dev = 2;
uint16_t I2CPumpCmdSpeed = 0;
uint32_t I2CPumpTargetSteps = 0;
float I2CPumpTargetMl = 0.0f;

bool set_stepper_by_time(uint16_t speed, uint8_t direction, uint16_t seconds) {
  stepperByTimeCalls++;
  lastSpeed = speed;
  lastDirection = direction;
  lastTime = seconds;
  return stepperByTimeResult;
}
bool set_stepper_target(uint16_t speed, uint8_t direction, uint32_t target) {
  stepperTargetCalls++;
  lastSpeed = speed;
  lastDirection = direction;
  lastTarget = target;
  return stepperTargetResult;
}
float i2c_get_speed_from_rate(float rate) {
  speedFromRateCalls++;
  lastRate = rate;
  return speedFromRateResult;
}
bool set_mixer_pump_target(uint8_t target) {
  mixerTargetCalls++;
  lastTarget = target;
  return mixerTargetResult;
}
bool set_i2c_rele_state(uint8_t relay, bool state) {
  relaySetCalls++;
  lastTarget = relay;
  lastDirection = state;
  return relaySetResult;
}
uint8_t get_i2c_rele_state(uint8_t relay) {
  relayReadCalls++;
  lastTarget = relay;
  return relayReadResult;
}

int powerCalls = 0;
float lastPowerArg = 0.0f;
void set_current_power(float volt) {
  powerCalls++;
  lastPowerArg = volt;
}

__CALLBACKS__

struct AllocationHeader { size_t size; };
size_t allocatedBytes = 0;

void* tracked_alloc(void*, void* pointer, size_t, size_t newSize) {
  if (newSize == 0) {
    if (pointer) {
      AllocationHeader* header = static_cast<AllocationHeader*>(pointer) - 1;
      allocatedBytes -= header->size;
      std::free(header);
    }
    return nullptr;
  }
  if (!pointer) {
    AllocationHeader* header = static_cast<AllocationHeader*>(
        std::malloc(sizeof(AllocationHeader) + newSize));
    if (!header) return nullptr;
    header->size = newSize;
    allocatedBytes += newSize;
    return header + 1;
  }
  AllocationHeader* oldHeader = static_cast<AllocationHeader*>(pointer) - 1;
  const size_t oldSize = oldHeader->size;
  AllocationHeader* newHeader = static_cast<AllocationHeader*>(
      std::realloc(oldHeader, sizeof(AllocationHeader) + newSize));
  if (!newHeader) return nullptr;
  newHeader->size = newSize;
  allocatedBytes = allocatedBytes - oldSize + newSize;
  return newHeader + 1;
}

int failures = 0;
std::string lastError;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

void check_last_error_contains(const std::string& expected, const char* message) {
  check(lastError.find(expected) != std::string::npos, message);
}

bool run_chunk(lua_State* state, const std::string& code, bool expectSuccess,
               int expectedResults = 0, lua_Number* result = nullptr) {
  const int base = lua_gettop(state);
  int status = luaL_loadstring(state, code.c_str());
  if (status == LUA_OK) status = lua_pcall(state, 0, LUA_MULTRET, 0);
  const bool success = status == LUA_OK;
  if (!success) {
    const char* error = lua_tostring(state, -1);
    lastError = error ? error : "unknown";
  } else {
    lastError.clear();
  }
  check(success == expectSuccess, code.c_str());
  if (success && expectSuccess) {
    check(lua_gettop(state) - base == expectedResults, "success return cardinality");
    if (result && expectedResults == 1) *result = lua_tonumber(state, -1);
  }
  lua_settop(state, base);
  return success == expectSuccess;
}

void set_number_global(lua_State* state, const char* name, lua_Number value) {
  lua_pushnumber(state, value);
  lua_setglobal(state, name);
}

void register_callbacks(lua_State* state) {
  lua_register(state, "setNumVariable", lua_wrapper_set_num_variable);
  lua_register(state, "setStrVariable", lua_wrapper_set_str_variable);
  lua_register(state, "setObject", lua_wrapper_set_object);
  lua_register(state, "setLuaStatus", lua_wrapper_set_lua_status);
  lua_register(state, "exp_pinMode", lua_wrapper_exp_pinMode);
  lua_register(state, "exp_digitalWrite", lua_wrapper_exp_digitalWrite);
  lua_register(state, "exp_digitalRead", lua_wrapper_exp_digitalRead);
  lua_register(state, "exp_analogWrite", lua_wrapper_exp_analogWrite);
  lua_register(state, "exp_analogRead", lua_wrapper_exp_analogRead);
  lua_register(state, "set_stepper_by_time", lua_wrapper_set_stepper_by_time);
  lua_register(state, "set_stepper_target", lua_wrapper_set_stepper_target);
  lua_register(state, "i2cpump_start", lua_wrapper_i2cpump_start);
  lua_register(state, "i2cpump_stop", lua_wrapper_i2cpump_stop);
  lua_register(state, "set_mixer_pump_target", lua_wrapper_set_mixer_pump_target);
  lua_register(state, "set_i2c_rele_state", lua_wrapper_set_i2c_rele_state);
  lua_register(state, "get_i2c_rele_state", lua_wrapper_get_i2c_rele_state);
  lua_register(state, "setCurrentPower", lua_wrapper_set_current_power);
  set_number_global(state, "INPUT", INPUT);
  set_number_global(state, "OUTPUT", OUTPUT);
  set_number_global(state, "INPUT_PULLUP", INPUT_PULLUP);
  set_number_global(state, "LOW", LOW);
  set_number_global(state, "HIGH", HIGH);
}

float descriptor_target_value(const char* name) {
  if (std::strcmp(name, "WFpulseCount") == 0) return waterPulseCount;
  if (std::strcmp(name, "pump_started") == 0) return pump_started;
  if (std::strcmp(name, "valve_status") == 0) return valve_status;
  if (std::strcmp(name, "SamSetup_Mode") == 0) return SamSetup.Mode;
  if (std::strcmp(name, "Samovar_Mode") == 0) return Samovar_Mode;
  if (std::strcmp(name, "Samovar_CR_Mode") == 0) return Samovar_CR_Mode;
  if (std::strcmp(name, "acceleration_temp") == 0) return acceleration_temp;
  if (std::strcmp(name, "wp_count") == 0) return wp_count;
  if (std::strcmp(name, "pmpKp") == 0) return pump_regulator.Kp;
  if (std::strcmp(name, "pmpKi") == 0) return pump_regulator.Ki;
  if (std::strcmp(name, "pmpKd") == 0) return pump_regulator.Kd;
  if (std::strcmp(name, "SteamTemp") == 0) return SteamSensor.avgTemp;
  if (std::strcmp(name, "boil_temp") == 0) return boil_temp;
  if (std::strcmp(name, "PipeTemp") == 0) return PipeSensor.avgTemp;
  if (std::strcmp(name, "WaterTemp") == 0) return WaterSensor.avgTemp;
  if (std::strcmp(name, "TankTemp") == 0) return TankSensor.avgTemp;
  if (std::strcmp(name, "ACPTemp") == 0) return ACPSensor.avgTemp;
  if (std::strcmp(name, "loop_lua_fl") == 0) return loop_lua_fl;
  if (std::strcmp(name, "SetScriptOff") == 0) return SetScriptOff;
  if (std::strcmp(name, "show_lua_script") == 0) return show_lua_script;
  if (std::strcmp(name, "test_num_val") == 0) return test_num_val;
  check(false, "unknown writable descriptor target");
  return 0.0f;
}

void test_descriptors(lua_State* state) {
  struct IntegralDomain { const char* name; int32_t minimum; int32_t maximum; };
  const IntegralDomain domains[] = {
      {"WFpulseCount", 0, UINT16_MAX}, {"pump_started", 0, 1},
      {"valve_status", 0, 1}, {"SamSetup_Mode", 0, SAMOVAR_LUA_MODE},
      {"Samovar_Mode", 0, SAMOVAR_LUA_MODE},
      {"Samovar_CR_Mode", 0, SAMOVAR_LUA_MODE},
      {"acceleration_temp", 0, UINT16_MAX}, {"wp_count", INT8_MIN, INT8_MAX},
      {"loop_lua_fl", 0, 1}, {"SetScriptOff", 0, 1},
      {"show_lua_script", 0, 1},
  };
  pendingLockAvailable = true;
  profilePhase = PROFILE_OPERATION_EMPTY;
  modeSwitchActive = false;
  for (const IntegralDomain& domain : domains) {
    run_chunk(state, "setNumVariable(\"" + std::string(domain.name) + "\"," +
                         std::to_string(domain.minimum) + ")", true);
    check(descriptor_target_value(domain.name) == domain.minimum,
          "integral descriptor minimum did not reach exact target");
    run_chunk(state, "setNumVariable(\"" + std::string(domain.name) + "\"," +
                         std::to_string(domain.maximum) + ")", true);
    check(descriptor_target_value(domain.name) == domain.maximum,
          "integral descriptor maximum did not reach exact target");
    if (domain.minimum > INT32_MIN) {
      run_chunk(state, "setNumVariable(\"" + std::string(domain.name) + "\"," +
                           std::to_string(static_cast<int64_t>(domain.minimum) - 1) + ")", false);
      check_last_error_contains("Invalid " + std::string(domain.name) + ": range",
                                "integral minimum error class/text");
    }
    if (domain.maximum < INT32_MAX) {
      run_chunk(state, "setNumVariable(\"" + std::string(domain.name) + "\"," +
                           std::to_string(static_cast<int64_t>(domain.maximum) + 1) + ")", false);
      check_last_error_contains("Invalid " + std::string(domain.name) + ": range",
                                "integral maximum error class/text");
    }
    run_chunk(state, "setNumVariable(\"" + std::string(domain.name) + "\",1.5)", false);
    check_last_error_contains("number has no integer representation",
                              "fractional integer error class/text");
    set_number_global(state, "bad", NAN);
    run_chunk(state, "setNumVariable(\"" + std::string(domain.name) + "\",bad)", false);
    check_last_error_contains("number has no integer representation",
                              "integral NaN error class/text");
    set_number_global(state, "bad", INFINITY);
    run_chunk(state, "setNumVariable(\"" + std::string(domain.name) + "\",bad)", false);
    check_last_error_contains("number has no integer representation",
                              "integral positive infinity error class/text");
    set_number_global(state, "bad", -INFINITY);
    run_chunk(state, "setNumVariable(\"" + std::string(domain.name) + "\",bad)", false);
    check_last_error_contains("number has no integer representation",
                              "integral negative infinity error class/text");
  }
  run_chunk(state, "setNumVariable(\"WFpulseCount\",16777217)", false);
  check_last_error_contains("Invalid WFpulseCount: range",
                            "wide exact integer range error text");
  run_chunk(state, "setNumVariable(\"WFpulseCount\",2147483647)", false);
  check_last_error_contains("Invalid WFpulseCount: range",
                            "INT32_MAX range error text");

  const char* fractional[] = {
      "pmpKp", "pmpKi", "pmpKd", "SteamTemp", "boil_temp", "PipeTemp",
      "WaterTemp", "TankTemp", "ACPTemp", "test_num_val",
  };
  for (const char* name : fractional) {
    set_number_global(state, "value", -FLT_MAX);
    run_chunk(state, "setNumVariable(\"" + std::string(name) + "\",value)", true);
    check(descriptor_target_value(name) == -FLT_MAX,
          "fractional descriptor minimum did not reach exact target");
    set_number_global(state, "value", FLT_MAX);
    run_chunk(state, "setNumVariable(\"" + std::string(name) + "\",value)", true);
    check(descriptor_target_value(name) == FLT_MAX,
          "fractional descriptor maximum did not reach exact target");
    set_number_global(state, "value", NAN);
    run_chunk(state, "setNumVariable(\"" + std::string(name) + "\",value)", false);
    check_last_error_contains("Invalid " + std::string(name) + ": finite",
                              "fractional NaN error class/text");
    set_number_global(state, "value", INFINITY);
    run_chunk(state, "setNumVariable(\"" + std::string(name) + "\",value)", false);
    check_last_error_contains("Invalid " + std::string(name) + ": finite",
                              "fractional positive infinity error class/text");
    set_number_global(state, "value", -INFINITY);
    run_chunk(state, "setNumVariable(\"" + std::string(name) + "\",value)", false);
    check_last_error_contains("Invalid " + std::string(name) + ": finite",
                              "fractional negative infinity error class/text");
  }
  run_chunk(state, "setNumVariable(\"pmpKp\",6.5); setNumVariable(\"pmpKi\",0.3); setNumVariable(\"pmpKd\",30.25)", true);
  check(pump_regulator.Kp == 6.5f && pump_regulator.Ki > 0.29f &&
            pump_regulator.Ki < 0.31f && pump_regulator.Kd == 30.25f,
        "PID coefficients lost fractional values");

  pump_started = 0;
  valve_status = 0;
  run_chunk(state, "setNumVariable(\"pump_started\",2); setNumVariable(\"valve_status\",1)", false);
  check(pump_started == 0 && valve_status == 0,
        "invalid descriptor chunk continued after Lua error");
}

void test_modes(lua_State* state) {
  SamSetup.Mode = 1;
  Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
  Samovar_CR_Mode = SAMOVAR_BK_MODE;
  changeModeCalls = 0;
  pendingLockCalls = pendingUnlockCount = modeSwitchCheckCalls = 0;
  run_chunk(state, "setNumVariable(\"SamSetup_Mode\",4)", true);
  check(SamSetup.Mode == 4 && Samovar_Mode == SAMOVAR_DISTILLATION_MODE &&
            Samovar_CR_Mode == SAMOVAR_BK_MODE && changeModeCalls == 0,
        "SamSetup_Mode changed active/control mode");
  check(pendingLockCalls == 1 && pendingUnlockCount == 1,
        "SamSetup_Mode owner lock/unlock accounting");

  Samovar_CR_Mode = SAMOVAR_NBK_MODE;
  pendingLockCalls = pendingUnlockCount = modeSwitchCheckCalls = 0;
  run_chunk(state, "setNumVariable(\"Samovar_Mode\",1)", true);
  check(Samovar_CR_Mode == SAMOVAR_NBK_MODE && changeModeCalls == 0,
        "same active mode normalized control mode");
  check(pendingLockCalls == 1 && pendingUnlockCount == 1,
        "same active mode owner lock/unlock accounting");
  pendingLockCalls = pendingUnlockCount = modeSwitchCheckCalls = 0;
  run_chunk(state, "setNumVariable(\"Samovar_Mode\",2)", true);
  check(Samovar_Mode == SAMOVAR_BEER_MODE && Samovar_CR_Mode == SAMOVAR_BEER_MODE &&
            changeModeCalls == 1 && SamSetup.Mode == 4,
        "active mode semantics changed");
  check(pendingLockCalls == 1 && pendingUnlockCount == 1,
        "active mode owner lock/unlock accounting");
  pendingLockCalls = pendingUnlockCount = modeSwitchCheckCalls = 0;
  run_chunk(state, "setNumVariable(\"Samovar_CR_Mode\",3)", true);
  check(Samovar_CR_Mode == SAMOVAR_BK_MODE && Samovar_Mode == SAMOVAR_BEER_MODE &&
            SamSetup.Mode == 4 && changeModeCalls == 1,
        "control mode semantics changed");
  check(pendingLockCalls == 1 && pendingUnlockCount == 1,
        "control mode owner lock/unlock accounting");

  const char* modeNames[] = {"SamSetup_Mode", "Samovar_Mode", "Samovar_CR_Mode"};
  for (const char* name : modeNames) {
    SamSetup.Mode = 1;
    Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
    Samovar_CR_Mode = SAMOVAR_BK_MODE;
    pendingLockAvailable = false;
    pendingLockCalls = pendingUnlockCount = modeSwitchCheckCalls = 0;
    run_chunk(state, "setNumVariable(\"" + std::string(name) + "\",2)", false);
    check_last_error_contains(std::string(name) + " busy",
                              "mode owner lock-busy error text/class");
    check(SamSetup.Mode == 1 && Samovar_Mode == SAMOVAR_DISTILLATION_MODE &&
              Samovar_CR_Mode == SAMOVAR_BK_MODE,
          "mode lock busy changed state");
    check(pendingLockCalls == 1 && pendingUnlockCount == 0,
          "mode lock-busy accounting");

    pendingLockAvailable = true;
    modeSwitchActive = true;
    bypassOuterModeSwitchCheck = true;
    pendingLockCalls = pendingUnlockCount = modeSwitchCheckCalls = 0;
    run_chunk(state, "setNumVariable(\"" + std::string(name) + "\",2)", false);
    check_last_error_contains(std::string(name) + " busy",
                              "owner mode-switch barrier error text/class");
    check(SamSetup.Mode == 1 && Samovar_Mode == SAMOVAR_DISTILLATION_MODE &&
              Samovar_CR_Mode == SAMOVAR_BK_MODE,
          "active mode switch changed state");
    check(pendingLockCalls == 1 && pendingUnlockCount == 1 &&
              modeSwitchCheckCalls >= 2,
          "owner mode-switch barrier did not execute under lock");
    bypassOuterModeSwitchCheck = false;
    modeSwitchActive = false;

    for (int phase = PROFILE_OPERATION_QUEUED;
         phase <= PROFILE_OPERATION_FAILED_CLOSED; phase++) {
      profilePhase = static_cast<ProfileOperationPhase>(phase);
      pendingLockCalls = pendingUnlockCount = modeSwitchCheckCalls = 0;
      run_chunk(state, "setNumVariable(\"" + std::string(name) + "\",2)", false);
      check_last_error_contains(std::string(name) + " busy",
                                "owner profile barrier error text/class");
      check(SamSetup.Mode == 1 && Samovar_Mode == SAMOVAR_DISTILLATION_MODE &&
                Samovar_CR_Mode == SAMOVAR_BK_MODE,
            "non-empty profile phase changed mode state");
      check(pendingLockCalls == 1 && pendingUnlockCount == 1,
            "owner profile barrier lock/unlock accounting");
    }
    profilePhase = PROFILE_OPERATION_EMPTY;
  }
}

void test_expanders(lua_State* state) {
  semaphoreAvailable = true;
  semaphoreTakeCount = semaphoreGiveCount = 0;
  run_chunk(state, "exp_pinMode(0,INPUT)", true, 0);
  run_chunk(state, "exp_pinMode(15,INPUT_PULLUP)", true, 0);
  check(expander.pinModeCalls == 2 && semaphoreGiveCount == 2,
        "expander pinMode INPUT/INPUT_PULLUP contract");
  const int beforeTake = semaphoreTakeCount;
  run_chunk(state, "exp_pinMode(16,INPUT)", false);
  check_last_error_contains("Invalid pin: range", "expander pin overflow error");
  run_chunk(state, "exp_pinMode(-1,INPUT)", false);
  check_last_error_contains("Invalid pin: range", "expander pin negative error");
  run_chunk(state, "exp_pinMode(1.5,INPUT)", false);
  check_last_error_contains("Invalid pin: format", "expander fractional-pin error");
  run_chunk(state, "exp_pinMode(1,1.5)", false);
  check_last_error_contains("Invalid mode: format", "expander fractional-mode error");
  run_chunk(state, "exp_pinMode(1,2)", false);
  check_last_error_contains("Invalid mode: allowed", "expander invalid mode error");
  check(semaphoreTakeCount == beforeTake && expander.pinModeCalls == 2,
        "invalid expander pin/mode touched semaphore or hardware");

  semaphoreAvailable = false;
  const int beforeGive = semaphoreGiveCount;
  run_chunk(state, "exp_pinMode(1,OUTPUT)", false);
  check_last_error_contains("I2C expander write timeout",
                            "pinMode timeout error text/class");
  check(semaphoreGiveCount == beforeGive, "timeout gave untaken semaphore");

  const int beforeDigitalWrites = expander.digitalWriteCalls;
  run_chunk(state, "exp_digitalWrite(1,HIGH)", false);
  check_last_error_contains("I2C expander write timeout",
                            "digitalWrite timeout error text/class");
  check(expander.digitalWriteCalls == beforeDigitalWrites &&
            semaphoreGiveCount == beforeGive,
        "digital write timeout touched hardware or gave semaphore");
  run_chunk(state, "exp_digitalRead(1)", false);
  check_last_error_contains("I2C expander read timeout",
                            "digitalRead timeout error text/class");
  check(expander.digitalReadCalls == 0 && semaphoreGiveCount == beforeGive,
        "digital read timeout touched hardware or gave semaphore");
  run_chunk(state, "exp_analogWrite(1)", false);
  check_last_error_contains("I2C analog expander write timeout",
                            "analogWrite timeout error text/class");
  run_chunk(state, "exp_analogRead(1)", false);
  check_last_error_contains("I2C analog expander read timeout",
                            "analogRead timeout error text/class");
  check(analog_expander.writeCalls == 0 && analog_expander.readCalls == 0 &&
            semaphoreGiveCount == beforeGive,
        "analog timeout touched hardware or gave semaphore");

  semaphoreAvailable = true;
  expander.writeResult = false;
  run_chunk(state, "exp_digitalWrite(1,HIGH)", false);
  check_last_error_contains("I2C expander write failed",
                            "digitalWrite vendor-false error text/class");
  check(semaphoreGiveCount == beforeGive + 1 && expander.digitalWriteCalls == 1,
        "digitalWrite failure did not unlock exactly once");
  expander.writeResult = true;
  run_chunk(state, "exp_digitalWrite(1,LOW)", true, 0);
  const int digitalWriteCalls = expander.digitalWriteCalls;
  run_chunk(state, "exp_digitalWrite(1,0.5)", false);
  check_last_error_contains("Invalid value: format",
                            "digitalWrite fractional-value error");
  run_chunk(state, "exp_digitalWrite(1.5,LOW)", false);
  check_last_error_contains("Invalid pin: format",
                            "digitalWrite fractional-pin error");
  run_chunk(state, "exp_digitalWrite(-1,LOW)", false);
  run_chunk(state, "exp_digitalWrite(16,LOW)", false);
  run_chunk(state, "exp_digitalWrite(1,2)", false);
  check(expander.digitalWriteCalls == digitalWriteCalls,
        "invalid digitalWrite bounds touched hardware");
  expander.readResult = 1;
  lua_Number result = 0;
  run_chunk(state, "return exp_digitalRead(15)", true, 1, &result);
  check(result == 1, "digitalRead result contract");
  const int digitalReadCalls = expander.digitalReadCalls;
  run_chunk(state, "exp_digitalRead(1.5)", false);
  check_last_error_contains("Invalid pin: format",
                            "digitalRead fractional-pin error");
  run_chunk(state, "exp_digitalRead(-1)", false);
  run_chunk(state, "exp_digitalRead(16)", false);
  check(expander.digitalReadCalls == digitalReadCalls,
        "invalid digitalRead bounds touched hardware");

  run_chunk(state, "exp_analogWrite(0)", true, 0);
  run_chunk(state, "exp_analogWrite(255)", true, 0);
  run_chunk(state, "exp_analogWrite(1.5)", true, 0);
  check(analog_expander.writeCalls == 3, "analog write min/max/fractional contract");
  const int analogWriteCalls = analog_expander.writeCalls;
  run_chunk(state, "exp_analogWrite(-1)", false);
  run_chunk(state, "exp_analogWrite(256)", false);
  check(analog_expander.writeCalls == analogWriteCalls,
        "invalid analogWrite bounds touched hardware");
  analog_expander.readResult = 77;
  run_chunk(state, "return exp_analogRead(0)", true, 1, &result);
  run_chunk(state, "return exp_analogRead(3)", true, 1, &result);
  check(result == 77, "analog read result contract");
  const int analogReadCalls = analog_expander.readCalls;
  run_chunk(state, "exp_analogRead(0.5)", false);
  check_last_error_contains("Invalid channel: format",
                            "analog read fractional-channel error");
  run_chunk(state, "exp_analogRead(-1)", false);
  run_chunk(state, "exp_analogRead(4)", false);
  check(analog_expander.readCalls == analogReadCalls,
        "invalid analogRead bounds touched hardware");
}

void test_i2c_wrappers(lua_State* state) {
  lua_Number result = 0;
  stepperByTimeCalls = 0;
  stepperByTimeResult = false;
  run_chunk(state, "return set_stepper_by_time(65535,1,65535)", true, 1, &result);
  check(result == 0 && stepperByTimeCalls == 1 && lastSpeed == UINT16_MAX &&
            lastDirection == 1 && lastTime == UINT16_MAX,
        "stepper-by-time bool/bounds contract");
  stepperByTimeResult = true;
  run_chunk(state, "return set_stepper_by_time(0,0,0)", true, 1, &result);
  check(result == 1 && stepperByTimeCalls == 2 && lastSpeed == 0 &&
            lastDirection == 0 && lastTime == 0,
        "stepper-by-time min/true contract");
  run_chunk(state, "return set_stepper_by_time(0.5,0,0)", true, 1, &result);
  run_chunk(state, "return set_stepper_by_time(0,0,0.5)", true, 1, &result);
  check(result == 1 && stepperByTimeCalls == 4 && lastSpeed == 0 &&
            lastDirection == 0 && lastTime == 0,
        "stepper-by-time fractional speed/time truncation contract");
  run_chunk(state, "set_stepper_by_time(0,0.5,0)", false);
  check_last_error_contains("Invalid direction: format",
                            "stepper-by-time fractional-direction error");
  check(stepperByTimeCalls == 4,
        "stepper-by-time fractional direction touched hardware");
  run_chunk(state, "set_stepper_by_time(-1,0,0)", false);
  run_chunk(state, "set_stepper_by_time(65536,0,0)", false);
  run_chunk(state, "set_stepper_by_time(0,-1,0)", false);
  run_chunk(state, "set_stepper_by_time(0,2,0)", false);
  run_chunk(state, "set_stepper_by_time(0,0,-1)", false);
  run_chunk(state, "set_stepper_by_time(0,0,65536)", false);
  check(stepperByTimeCalls == 4, "invalid stepper-by-time touched hardware");

  stepperTargetCalls = 0;
  stepperTargetResult = true;
  run_chunk(state, "return set_stepper_target(0,0,2147483647)", true, 1, &result);
  check(result == 1 && lastTarget == 2147483647U,
        "stepper target INT32_MAX contract");
  stepperTargetResult = false;
  run_chunk(state, "return set_stepper_target(65535,1,0)", true, 1, &result);
  check(result == 0 && stepperTargetCalls == 2 && lastSpeed == UINT16_MAX &&
            lastDirection == 1 && lastTarget == 0,
        "stepper target underlying-false/min contract");
  run_chunk(state, "return set_stepper_target(0.5,0,0)", true, 1, &result);
  run_chunk(state, "return set_stepper_target(0,0,0.5)", true, 1, &result);
  check(result == 0 && stepperTargetCalls == 4 && lastSpeed == 0 &&
            lastDirection == 0 && lastTarget == 0,
        "stepper target fractional speed/target truncation contract");
  run_chunk(state, "set_stepper_target(0,0.5,0)", false);
  check_last_error_contains("Invalid direction: format",
                            "stepper target fractional-direction error");
  check(stepperTargetCalls == 4,
        "stepper target fractional direction touched hardware");
  run_chunk(state, "set_stepper_target(-1,0,0)", false);
  run_chunk(state, "set_stepper_target(65536,0,0)", false);
  run_chunk(state, "set_stepper_target(0,-1,0)", false);
  run_chunk(state, "set_stepper_target(0,2,0)", false);
  run_chunk(state, "set_stepper_target(0,0,-1)", false);
  run_chunk(state, "set_stepper_target(0,0,2147483648)", false);
  check(stepperTargetCalls == 4, "invalid stepper target touched hardware");

  mixerTargetCalls = 0;
  mixerTargetResult = false;
  run_chunk(state, "return set_mixer_pump_target(1)", true, 1, &result);
  check(result == 0 && mixerTargetCalls == 1, "mixer bool contract");
  mixerTargetResult = true;
  run_chunk(state, "return set_mixer_pump_target(0)", true, 1, &result);
  check(result == 1 && mixerTargetCalls == 2, "mixer true/min contract");
  run_chunk(state, "set_mixer_pump_target(0.5)", false);
  check_last_error_contains("Invalid target: format",
                            "mixer fractional-target error");
  run_chunk(state, "set_mixer_pump_target(-1)", false);
  run_chunk(state, "set_mixer_pump_target(2)", false);
  check(mixerTargetCalls == 2, "invalid mixer target touched hardware");

  relaySetCalls = relayReadCalls = 0;
  relaySetResult = false;
  run_chunk(state, "return set_i2c_rele_state(4,1)", true, 1, &result);
  check(result == 0 && relaySetCalls == 1, "relay bool contract");
  relaySetResult = true;
  run_chunk(state, "return set_i2c_rele_state(1,0)", true, 1, &result);
  check(result == 1 && relaySetCalls == 2, "relay true/min contract");
  run_chunk(state, "set_i2c_rele_state(1.5,1)", false);
  check_last_error_contains("Invalid relay: format",
                            "relay set fractional-relay error");
  run_chunk(state, "set_i2c_rele_state(1,0.5)", false);
  check_last_error_contains("Invalid state: format",
                            "relay set fractional-state error");
  check(relaySetCalls == 2, "invalid relay fractional args touched hardware");
  run_chunk(state, "set_i2c_rele_state(-1,1)", false);
  run_chunk(state, "set_i2c_rele_state(0,1)", false);
  run_chunk(state, "set_i2c_rele_state(5,1)", false);
  run_chunk(state, "set_i2c_rele_state(1,-1)", false);
  run_chunk(state, "set_i2c_rele_state(1,2)", false);
  check(relaySetCalls == 2, "invalid relay bounds touched hardware");
  relayReadResult = 1;
  run_chunk(state, "return get_i2c_rele_state(1)", true, 1, &result);
  run_chunk(state, "return get_i2c_rele_state(4)", true, 1, &result);
  check(result == 1 && relayReadCalls == 2, "relay read min/max contract");
  run_chunk(state, "get_i2c_rele_state(1.5)", false);
  check_last_error_contains("Invalid relay: format",
                            "relay read fractional-relay error");
  check(relayReadCalls == 2, "invalid relay read fractional arg touched hardware");
  run_chunk(state, "get_i2c_rele_state(-1)", false);
  run_chunk(state, "get_i2c_rele_state(0)", false);
  run_chunk(state, "get_i2c_rele_state(5)", false);
  check(relayReadCalls == 2, "invalid relay read bounds touched hardware");
}

void test_pump(lua_State* state) {
  lua_Number result = 0;
  use_I2C_dev = 2;
  SamSetup.StepperStepMlI2C = 100;
  SamSetup.StepperStepMl = 25;
  speedFromRateResult = 42.0f;
  stepperTargetResult = true;
  speedFromRateCalls = stepperTargetCalls = 0;
  run_chunk(state, "return i2cpump_start(3.5,1.25)", true, 1, &result);
  check(result == 1 && lastRate == 3.5f && I2CPumpTargetSteps == 125 &&
            I2CPumpTargetMl == 1.25f && I2CPumpCmdSpeed == 42 &&
            lastTarget == 125,
        "fractional pump volume/rate tracking contract");

  SamSetup.StepperStepMlI2C = 0;
  run_chunk(state, "return i2cpump_start(1,1)", true, 1, &result);
  check(lastTarget == I2C_STEPPER_STEP_ML_DEFAULT,
        "persisted/default I2C calibration contract");

  SamSetup.StepperStepMlI2C = 1;
  const float nearUint32 = std::nextafter(4294967296.0f, 0.0f);
  set_number_global(state, "nearUint32", nearUint32);
  speedFromRateResult = 1.0f;
  run_chunk(state, "return i2cpump_start(1,nearUint32)", true, 1, &result);
  check(result == 1 && lastTarget == static_cast<uint32_t>(nearUint32) &&
            lastTarget == 4294967040U,
        "near-UINT32 pump product edge was rejected or narrowed incorrectly");

  speedFromRateResult = 65535.0f;
  run_chunk(state, "return i2cpump_start(1,1)", true, 1, &result);
  check(I2CPumpCmdSpeed == UINT16_MAX, "pump speed 65535 rejected");
  speedFromRateResult = 65536.0f;
  const int targetCalls = stepperTargetCalls;
  run_chunk(state, "return i2cpump_start(1,1)", true, 1, &result);
  check(result == 0, "pump speed overflow now soft no-throw contract");
  check(stepperTargetCalls == targetCalls, "pump speed 65536 touched target");

  speedFromRateResult = 1.0f;
  const int rateCalls = speedFromRateCalls;
  run_chunk(state, "return i2cpump_start(1,0.5)", true, 1, &result);
  check(result == 0, "sub-unit pump product now soft no-throw contract");
  check(speedFromRateCalls == rateCalls, "sub-unit product touched speed boundary");

  const int overflowTargets = stepperTargetCalls;
  run_chunk(state, "return i2cpump_start(1,4294967296)", true, 1, &result);
  check(result == 0, "pump product overflow now soft no-throw contract");
  run_chunk(state, "return i2cpump_start(0,1)", true, 1, &result);
  check(result == 0, "zero pump rate now soft no-throw contract");
  run_chunk(state, "return i2cpump_start(-1,1)", true, 1, &result);
  check(result == 0, "negative pump rate now soft no-throw contract");
  run_chunk(state, "return i2cpump_start(1,0)", true, 1, &result);
  check(result == 0, "zero pump volume now soft no-throw contract");
  run_chunk(state, "return i2cpump_start(1,-1)", true, 1, &result);
  check(result == 0, "negative pump volume now soft no-throw contract");
  check(stepperTargetCalls == overflowTargets, "invalid pump rate/volume touched hardware");

  const int finiteTargets = stepperTargetCalls;
  set_number_global(state, "bad", INFINITY);
  run_chunk(state, "return i2cpump_start(bad,1)", true, 1, &result);
  check(result == 0, "positive-infinite pump rate now soft no-throw contract");
  set_number_global(state, "bad", -INFINITY);
  run_chunk(state, "return i2cpump_start(bad,1)", true, 1, &result);
  check(result == 0, "negative-infinite pump rate now soft no-throw contract");
  set_number_global(state, "bad", NAN);
  run_chunk(state, "return i2cpump_start(bad,1)", true, 1, &result);
  check(result == 0, "NaN pump rate now soft no-throw contract");
  set_number_global(state, "bad", INFINITY);
  run_chunk(state, "return i2cpump_start(1,bad)", true, 1, &result);
  check(result == 0, "infinite pump volume now soft no-throw contract");
  check(stepperTargetCalls == finiteTargets, "NaN/Inf pump rate/volume touched hardware");

  use_I2C_dev = 1;
  const int noDeviceTargets = stepperTargetCalls;
  const int noDeviceRates = speedFromRateCalls;
  run_chunk(state, "return i2cpump_start(1,1)", true, 1, &result);
  check(result == 0 && stepperTargetCalls == noDeviceTargets &&
            speedFromRateCalls == noDeviceRates,
        "non-I2C pump did not preserve zero/no-call contract");
  use_I2C_dev = 2;

  modeSwitchActive = true;
  bypassOuterModeSwitchCheck = false;
  use_I2C_dev = 1;
  const int guardSkipTargets = stepperTargetCalls;
  run_chunk(state, "return i2cpump_start(1,1)", true, 1, &result);
  check(result == 0 && stepperTargetCalls == guardSkipTargets,
        "hardware-absent pump start stays soft even mid mode-switch (hw check runs first)");
  use_I2C_dev = 2;
  run_chunk(state, "i2cpump_start(1,1)", false);
  check_last_error_contains("mode switch blocks state changes",
                            "hardware-present pump start still honors the mode-switch mutation guard");
  check(stepperTargetCalls == guardSkipTargets, "blocked pump start touched hardware");
  modeSwitchActive = false;

  modeSwitchActive = true;
  use_I2C_dev = 1;
  const int stopGuardSkipTargets = stepperTargetCalls;
  run_chunk(state, "return i2cpump_stop()", true, 1, &result);
  check(result == 0 && stepperTargetCalls == stopGuardSkipTargets,
        "hardware-absent pump stop stays soft even mid mode-switch (hw check runs first)");
  use_I2C_dev = 2;
  run_chunk(state, "i2cpump_stop()", false);
  check_last_error_contains("mode switch blocks state changes",
                            "hardware-present pump stop still honors the mode-switch mutation guard");
  check(stepperTargetCalls == stopGuardSkipTargets, "blocked pump stop touched hardware");
  modeSwitchActive = false;

  SamSetup.StepperStepMlI2C = 100;
  speedFromRateResult = static_cast<float>(SamSetup.StepperStepMl);
  run_chunk(state, "return i2cpump_start(2,1)", true, 1, &result);
  check(I2CPumpCmdSpeed == SamSetup.StepperStepMl,
        "physical refresh local-calibration boundary result changed");

  stepperTargetResult = false;
  run_chunk(state, "return i2cpump_start(2,1)", true, 1, &result);
  check(result == 0, "pump underlying false announced success");
  I2CPumpTargetSteps = 7;
  I2CPumpTargetMl = 8.0f;
  I2CPumpCmdSpeed = 9;
  run_chunk(state, "return i2cpump_stop()", true, 1, &result);
  check(result == 0 && I2CPumpTargetSteps == 0 && I2CPumpTargetMl == 0.0f &&
            I2CPumpCmdSpeed == 0,
        "pump stop false/tracking contract");
  stepperTargetResult = true;
  run_chunk(state, "return i2cpump_stop()", true, 1, &result);
  check(result == 1, "pump stop true contract");
}

void test_power(lua_State* state) {
  modeSwitchActive = false;
  profilePhase = PROFILE_OPERATION_EMPTY;
  powerCalls = 0;
  run_chunk(state, "setCurrentPower(150.34)", true, 0);
  check(powerCalls == 1 && std::fabs(lastPowerArg - 150.3f) < 0.001f,
        "setCurrentPower rounds volts to one decimal (down)");
  run_chunk(state, "setCurrentPower(150.36)", true, 0);
  check(powerCalls == 2 && std::fabs(lastPowerArg - 150.4f) < 0.001f,
        "setCurrentPower rounds volts to one decimal (up)");
  run_chunk(state, "setCurrentPower(-5.26)", true, 0);
  check(powerCalls == 3 && std::fabs(lastPowerArg - (-5.3f)) < 0.001f,
        "setCurrentPower rounds negative volts to one decimal");
  set_number_global(state, "bad", NAN);
  run_chunk(state, "setCurrentPower(bad)", false);
  check_last_error_contains("Invalid power: finite", "NaN power rejected");
  check(powerCalls == 3, "NaN power reached set_current_power");
  set_number_global(state, "bad", INFINITY);
  run_chunk(state, "setCurrentPower(bad)", false);
  check_last_error_contains("Invalid power: finite",
                            "positive-infinite power rejected");
  check(powerCalls == 3, "positive-infinite power reached set_current_power");
  set_number_global(state, "bad", -INFINITY);
  run_chunk(state, "setCurrentPower(bad)", false);
  check_last_error_contains("Invalid power: finite",
                            "negative-infinite power rejected");
  check(powerCalls == 3, "negative-infinite power reached set_current_power");
}

void check_strings_destroyed(const char* message) {
  check(liveStringCount == 0, message);
}

void test_string_callbacks(lua_State* state) {
  modeSwitchActive = true;
  bypassOuterModeSwitchCheck = false;
  runtimeEventCalls = stringSetterCalls = luaObject.putCalls = luaStatusSetCalls = 0;

  run_chunk(state, "setStrVariable('Msg','blocked')", false);
  check_last_error_contains("mode switch blocks state changes",
                            "blocked string setter error text");
  check(runtimeEventCalls == 0 && stringSetterCalls == 0,
        "blocked string setter reached mutation boundary");
  check_strings_destroyed("blocked string setter retained Arduino String");

  run_chunk(state, "setObject('key','blocked')", false);
  check_last_error_contains("mode switch blocks state changes",
                            "blocked object setter error text");
  check(luaObject.putCalls == 0, "blocked object setter changed object state");
  check_strings_destroyed("blocked object setter retained Arduino String");

  run_chunk(state, "setLuaStatus('blocked')", false);
  check_last_error_contains("mode switch blocks state changes",
                            "blocked Lua_status setter error text");
  check(luaStatusSetCalls == 0,
        "blocked Lua_status setter reached mutation boundary");
  check_strings_destroyed("blocked Lua_status setter retained Arduino String");
  modeSwitchActive = false;

  runtimeEventResult = RUNTIME_EVENT_PUBLISH_LOCK_BUSY;
  run_chunk(state, "setStrVariable('Msg','message')", false);
  check_last_error_contains("Msg busy", "Msg lock-busy error text");
  check_strings_destroyed("Msg lock-busy retained Arduino String");

  runtimeEventResult = RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG;
  run_chunk(state, "setStrVariable('Msg','message')", false);
  check_last_error_contains("Msg too long", "Msg oversize error text");
  check_strings_destroyed("Msg oversize retained Arduino String");

  runtimeEventResult = RUNTIME_EVENT_PUBLISH_CORRUPT;
  run_chunk(state, "setStrVariable('Msg','message')", false);
  check_last_error_contains("Msg event store corrupt", "Msg corrupt error text");
  check_strings_destroyed("Msg corrupt retained Arduino String");

  runtimeEventResult = RUNTIME_EVENT_PUBLISH_OK;
  run_chunk(state, "setStrVariable('Msg','published')", true, 0);
  check(lastRuntimeEventText == "published", "Msg success lost published value");
  check_strings_destroyed("Msg success retained Arduino String");

  runtimeEventResult = RUNTIME_EVENT_PUBLISH_EMPTY;
  run_chunk(state, "setStrVariable('Msg','')", true, 0);
  check(lastRuntimeEventText.empty(), "Msg empty success changed value");
  check_strings_destroyed("Msg empty success retained Arduino String");

  stringSetterResult = false;
  run_chunk(state, "setStrVariable('SamovarStatus','blocked')", false);
  check_last_error_contains("SamovarStatus busy", "descriptor busy error text");
  check(lastStringValue.empty(), "busy descriptor changed string state");
  check_strings_destroyed("descriptor busy retained Arduino String");

  run_chunk(state, "setStrVariable('test_str_val','blocked')", false);
  check_last_error_contains("Lua string variable busy",
                            "descriptor fallback busy error text");
  check_strings_destroyed("descriptor fallback busy retained Arduino String");

  stringSetterResult = true;
  run_chunk(state, "setStrVariable('SamovarStatus','ready')", true, 0);
  check(lastStringValue == "ready", "descriptor success lost value");
  check_strings_destroyed("descriptor success retained Arduino String");

  run_chunk(state, "setObject('key','value')", true, 0);
  check(luaObject.putCalls == 1 && luaObject.lastKey == "key" &&
            luaObject.lastValue == "value",
        "object success lost key/value side effect");
  check_strings_destroyed("object success retained Arduino String");

  luaStatusSetResult = false;
  run_chunk(state, "setLuaStatus('blocked')", false);
  check_last_error_contains("Lua_status busy", "Lua_status busy error text");
  check(lastLuaStatus.empty(), "busy Lua_status changed state");
  check_strings_destroyed("Lua_status busy retained Arduino String");

  luaStatusSetResult = true;
  run_chunk(state, "setLuaStatus('ready')", true, 0);
  check(lastLuaStatus == "ready", "Lua_status success lost value");
  check_strings_destroyed("Lua_status success retained Arduino String");
}

void test_longjmp_allocations(lua_State* state) {
  modeSwitchActive = false;
  runtimeEventResult = RUNTIME_EVENT_PUBLISH_LOCK_BUSY;
  luaStatusSetResult = false;
  for (int i = 0; i < 10; i++) {
    run_chunk(state, "setNumVariable(\"pump_started\",2)", false);
    run_chunk(state, "setStrVariable('Msg','message')", false);
    run_chunk(state, "setLuaStatus('blocked')", false);
    check_strings_destroyed("String callback warmup retained Arduino String");
  }
  lua_gc(state, LUA_GCCOLLECT, 0);
  const size_t baseline = allocatedBytes;
  for (int i = 0; i < 100; i++) {
    run_chunk(state, "setNumVariable(\"pump_started\",2)", false);
    run_chunk(state, "setStrVariable('Msg','message')", false);
    run_chunk(state, "setLuaStatus('blocked')", false);
    check_strings_destroyed("repeated Lua error retained Arduino String");
  }
  lua_gc(state, LUA_GCCOLLECT, 0);
  check(allocatedBytes == baseline, "repeated Lua errors leaked tracked allocations");
  runtimeEventResult = RUNTIME_EVENT_PUBLISH_OK;
  luaStatusSetResult = true;
}

int main() {
  check(sizeof(lua_Number) == 4, "vendored lua_Number is not 32-bit");
  check(sizeof(lua_Integer) == 4, "vendored lua_Integer is not 32-bit");
  lua_State* state = lua_newstate(tracked_alloc, nullptr);
  check(state != nullptr, "lua_newstate failed");
  if (!state) return 1;
  luaL_openlibs(state);
  register_callbacks(state);
  test_descriptors(state);
  test_modes(state);
  test_expanders(state);
  test_i2c_wrappers(state);
  test_pump(state);
  test_power(state);
  test_string_callbacks(state);
  test_longjmp_allocations(state);
  lua_close(state);
  check(allocatedBytes == 0, "lua_close leaked tracked allocations");
  if (failures != 0) return 1;
  std::cout << "Lua A-07 production callback behavior passed\n";
  return 0;
}
'''
    harness = harness.replace("__OWNER__", owner_definition)
    harness = harness.replace("__STATE_HELPERS__", state_helpers)
    harness = harness.replace("__STRING_HELPER__", string_helper)
    harness = harness.replace(
        "__DESCRIPTORS__", LUA[descriptor_start:descriptor_end]
    )
    harness = harness.replace("__CALLBACKS__", callbacks)

    lua_dir = ROOT / "libraries/ESP-Arduino-Lua/src/lua"
    sources = sorted(
        path for path in lua_dir.glob("*.c") if path.name not in {"lua.c", "luac.c"}
    )
    with tempfile.TemporaryDirectory(prefix="samovar-lua-a07-") as temp_dir:
        temp = Path(temp_dir)
        harness_path = temp / "lua_a07_test.cpp"
        harness_path.write_text(harness, encoding="utf-8")
        objects: list[Path] = []
        for source in sources:
            object_path = temp / f"{source.stem}.o"
            result = subprocess.run(
                [
                    "gcc", "-std=c11", "-O0", "-I", str(lua_dir),
                    "-c", str(source), "-o", str(object_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return result.returncode, result.stdout, result.stderr
            objects.append(object_path)

        binary = temp / "lua_a07_test"
        result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(lua_dir), "-I", str(ROOT), str(harness_path),
                *[str(path) for path in objects], "-lm", "-ldl", "-o", str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode, result.stdout, result.stderr
        result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        return result.returncode, result.stdout, result.stderr

if ERRORS:
    print("Lua A-07 smoke failed:")
    for error in ERRORS:
        print(f" - {error}")
    sys.exit(1)

returncode, stdout, stderr = run_behavioral_harness()
sys.stdout.write(stdout)
sys.stderr.write(stderr)
if returncode != 0:
    raise SystemExit(returncode)

print("Lua A-07 checked argument/error contracts passed")
