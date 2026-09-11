#!/usr/bin/env python3

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def extract_struct(source: str, name: str) -> str:
    token = f"struct {name} {{"
    start = source.find(token)
    if start < 0:
        raise ValueError(f"struct not found: {name}")
    brace = source.find("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                semicolon = source.find(";", index)
                return source[start:semicolon + 1]
    raise ValueError(f"struct is not closed: {name}")


def extract_region(source: str, start_token: str, end_token: str) -> str:
    start = source.find(start_token)
    end = source.find(end_token, start)
    if start < 0 or end < start:
        raise ValueError(f"region not found: {start_token} .. {end_token}")
    return source[start:end]


def production_section(source: str, string_utils_source: str) -> str:
    json_write_escaped = extract_function_body(
        string_utils_source,
        "inline bool json_write_escaped(Print& out, const char* text, size_t length)",
    )
    snapshot = extract_struct(source, "AjaxTelemetrySnapshot")
    ui_types = extract_region(source, "enum UiStagePhase", "static UiStateDescriptor s_uiStateCache")
    ui_wait_reason = extract_region(read("runtime_pair_events.h"), "enum UiWaitReason", "struct RuntimePairState")
    ui_add_control = extract_function_body(
        source, "static void ui_add_control(UiStateDescriptor& value, uint8_t kind,"
    )
    ui_add_heater = extract_function_body(
        source, "static void ui_add_heater_control(UiStateDescriptor& value)"
    )
    ui_sensor_source = extract_function_body(
        source, "static uint8_t ui_end_source_from_program_sensor(uint8_t sensorId)"
    )
    ui_active_row = extract_function_body(source, "static bool ui_has_active_program_row()")
    ui_builder = extract_function_body(source, "static UiStateDescriptor build_ui_state_from_loop()")
    capture = extract_function_body(
        source,
        "static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot(",
    )
    writer = extract_function_body(
        source,
        "static void writeAjaxTelemetryFields(",
    )
    json_key = extract_function_body(
        source,
        "static inline void jsonAddKey(Print &out, bool &first, const char *key)",
    )
    json_escape = extract_function_body(
        source,
        "static void jsonPrintEscaped(Print &out, const String &value)",
    )
    json_field_float = extract_function_body(
        source,
        "static inline void jsonFieldFloat(Print &out, bool &first, const char *key, float value, int decimals)",
    )
    json_field_string = extract_function_body(
        source,
        "static inline void jsonFieldString(Print &out, bool &first, const char *key, const String &value)",
    )
    json_field_bool = extract_function_body(
        source,
        "static inline void jsonFieldBool(Print &out, bool &first, const char *key, bool value)",
    )
    json_field_raw = extract_function_body(
        read("json_field_raw.h"),
        "static inline void jsonFieldRaw(Print &out, bool &first, const char *key, T value)",
    )
    ui_end = extract_function_body(
        source, "static void writeUiEndFields(Print& out, bool& first, const UiEndDescriptor& value)"
    )
    ui_writer = extract_function_body(
        source, "static void writeUiStateJson(Print& out, bool& first, const UiStateDescriptor& value,"
    )
    return f"""
{ui_wait_reason}
{re.search(r'static UiControlSource uiWithdrawalControlSource = [^;]+;', source).group(0)}
{ui_types}
static UiStateDescriptor s_uiStateCache{{}};
static void ui_add_control(UiStateDescriptor& value, uint8_t kind,
                           bool hasRequested, float requested,
                           bool hasApplied, float applied, uint8_t unit,
                           uint8_t source) {{
{ui_add_control}
}}
static void ui_add_heater_control(UiStateDescriptor& value) {{
{ui_add_heater}
}}
static uint8_t ui_end_source_from_program_sensor(uint8_t sensorId) {{
{ui_sensor_source}
}}
static bool ui_has_active_program_row() {{
{ui_active_row}
}}
static UiStateDescriptor build_ui_state_from_loop() {{
{ui_builder}
}}
{snapshot}

static inline void jsonAddKey(Print &out, bool &first, const char *key) {{
{json_key}
}}

inline bool json_write_escaped(Print& out, const char* text, size_t length) {{
{json_write_escaped}
}}

static void jsonPrintEscaped(Print &out, const String &value) {{
{json_escape}
}}

static inline void jsonFieldFloat(Print &out, bool &first, const char *key, float value, int decimals) {{
{json_field_float}
}}

static inline void jsonFieldString(Print &out, bool &first, const char *key, const String &value) {{
{json_field_string}
}}

static inline void jsonFieldBool(Print &out, bool &first, const char *key, bool value) {{
{json_field_bool}
}}

template <typename T>
static inline void jsonFieldRaw(Print &out, bool &first, const char *key, T value) {{
{json_field_raw}
}}

static void writeUiEndFields(Print& out, bool& first, const UiEndDescriptor& value) {{
{ui_end}
}}

static void writeUiStateJson(Print& out, bool& first, const UiStateDescriptor& value,
                             const String& luaStatus) {{
{ui_writer}
}}

static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot(
    uint32_t messageCursor, AjaxTelemetrySnapshot& snapshot) {{
{capture}
}}

static void writeAjaxTelemetryFields(
    Print& out, const AjaxTelemetrySnapshot& snapshot) {{
{writer}
}}
"""


def strip_cpp_literals(source: str) -> str:
    result: list[str] = []
    index = 0
    quote = ""
    escaped = False
    while index < len(source):
        char = source[index]
        if quote:
            result.append("\n" if char == "\n" else " ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in ("\"", "'"):
            quote = char
            result.append(" ")
        else:
            result.append(char)
        index += 1
    return "".join(result)


HARNESS_PREFIX = r'''
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <type_traits>

using std::isfinite;

#define SAMOVAR_VERSION "6.27"
#define I2CSTEPPER_STATUS_RUNNING 1

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(char value) : value_(1, value) {}
  String(int value) : value_(std::to_string(value)) {}
  String(unsigned long value) : value_(std::to_string(value)) {}
  size_t length() const { return value_.size(); }
  char operator[](size_t index) const { return value_[index]; }
  const char* c_str() const { return value_.c_str(); }
  const std::string& str() const { return value_; }
  String& operator=(const char* value) {
    value_ = value ? value : "";
    return *this;
  }
 private:
  std::string value_;
};

class Print {
 public:
  void print(char value) { bytes.push_back(value); }
  void print(const char* value) { bytes += value; }
  void print(const String& value) { bytes += value.str(); }
  size_t write(const uint8_t* buffer, size_t size) {
    bytes.append(reinterpret_cast<const char*>(buffer), size);
    return size;
  }
  template <typename T>
  typename std::enable_if<std::is_integral<T>::value, void>::type print(T value) {
    std::ostringstream out;
    if (std::is_same<T, bool>::value) out << (value ? 1 : 0);
    else if (std::is_signed<T>::value) out << static_cast<long long>(value);
    else out << static_cast<unsigned long long>(value);
    bytes += out.str();
  }
  void print(float value) { printFloating(value); }
  void print(double value) { printFloating(value); }
  std::string bytes;
 private:
  void printFloating(double value) {
    std::ostringstream out;
    out << std::fixed << std::setprecision(2) << value;
    bytes += out.str();
  }
};

enum RuntimeAjaxSnapshotResult : uint8_t {
  RUNTIME_AJAX_SNAPSHOT_OK = 0,
  RUNTIME_AJAX_SNAPSHOT_LOCK_BUSY,
  RUNTIME_AJAX_SNAPSHOT_NO_MEMORY,
  RUNTIME_AJAX_SNAPSHOT_CORRUPT,
};

enum RuntimeEventKind : uint8_t {
  RUNTIME_EVENT_MESSAGE = 1,
  RUNTIME_EVENT_CONSOLE = 2,
};

struct RuntimeEventDescriptor {
  uint32_t sequence;
  uint16_t offset;
  uint16_t length;
  uint8_t kind;
  uint8_t level;
};

static const uint8_t RUNTIME_EVENT_DESCRIPTOR_CAPACITY = 32;

enum SAMOVAR_MODE : uint8_t {
  SAMOVAR_RECTIFICATION_MODE,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE,
  SAMOVAR_CHEESE_MODE,
};

constexpr uint8_t PROGRAM_END = 0xFF;
enum ProgramWaitType : uint8_t {
  PROGRAM_WAIT_NONE = 0,
  PROGRAM_WAIT_STEAM,
  PROGRAM_WAIT_PIPE,
  PROGRAM_WAIT_DETECTOR,
};

using ProgramType = char;

struct SetupFixture {
  bool useautospeed;
  bool UseBBuzzer;
  uint16_t StepperStepMl;
  uint8_t BeerBrewOrder;
  bool useDetector;
  float DistTemp;
  uint8_t DistTimeF;
  uint16_t SuvidHoldMinutes;
};

struct SensorFixture {
  float avgTemp;
  float BodyTemp;
};
using DSSensor = SensorFixture;

struct WProgram {
  ProgramType WType;
  uint16_t Volume;
  float Speed;
  uint8_t capacity_num;
  float Temp;
  float Power;
  uint8_t TempSensor;
  float Time;
  float Param;
  uint16_t LuaTextOffset;
};

struct DetectorFixture {
  float currentTrend;
  uint8_t detectorStatus;
};

struct I2CCacheFixture {
  bool mixer_present;
  bool pump_present;
  uint16_t pump_current_speed;
  float pump_current_rate;
  uint32_t pump_remaining;
  uint8_t pump_status;
};

struct TimePredictorFixture {
  float predictedTotalTime;
  float remainingTime;
  float rowPredictedTotalTime;
  float processRemainingTime;
  bool rowPredictionAvailable;
  bool processPredictionAvailable;
};

volatile float bme_temp = 1.25f;
volatile float bme_pressure = 760.0f;
volatile float start_pressure = 755.5f;
SetupFixture SamSetup{true, true, 800, 0, true, 96.0f, 5, 15};
SensorFixture SteamSensor{78.125f, 77.0f};
SensorFixture PipeSensor{77.25f, 76.0f};
SensorFixture WaterSensor{20.5f, 0.0f};
SensorFixture TankSensor{89.75f, 0.0f};
SensorFixture ACPSensor{30.0f, 0.0f};
WProgram program[8] = {};
DetectorFixture impurityDetector{0.125f, 2};
volatile float ActualVolumePerHour = 1.234f;
volatile bool PowerOn = true;
volatile bool PauseOn = false;
volatile bool program_Pause = false;
volatile bool program_Wait = false;
volatile ProgramWaitType program_Wait_Type = PROGRAM_WAIT_NONE;
bool copy_program_wait_type(ProgramWaitType& waitType) {{
  waitType = program_Wait_Type;
  return true;
}}
bool beerManualPause = false;  // [Пиво 02.09 C2]
bool rectManualPauseActive = false;
bool heater_state = true;
volatile uint8_t WthdrwlProgress = 55;
volatile int16_t startval = 1;
volatile uint8_t ProgramNum = 2;
uint8_t ProgramLen = 3;
bool bk_work_power_pending = false;
float bk_pwm = 456.0f;
uint8_t beerSkipConfirmProgramNum = 0xFF;
unsigned long begintime = 0;
bool mixer_status = true;
struct SuvidHoldFixture { bool active; bool inBand; };
SuvidHoldFixture suvidHold{false, false};
bool suvidHeaterOn = false;
int32_t suvid_hold_remaining_sec() { return suvidHold.active ? 420 : -1; }
// [9b] Всегда читаются captureAjaxTelemetrySnapshot() безусловно (без #ifdef
// USE_WATER_PUMP) - см. BK.h/Samovar.ino. Ненулевые значения фиксируют, что
// снимок реально читает эти глобалы, а не просто печатает дефолт структуры.
volatile bool bk_water_auto = true;
volatile float bk_steam_setpoint = 78.4f;
volatile I2CCacheFixture i2c_stepper_cache{true, true, 400, 2.5f, 7, 1};
volatile float I2CPumpTargetMl = 12.5f;
uint32_t total_byte = 100000;
uint32_t used_byte = 1234;
volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
constexpr int16_t SAMOVAR_STATUS_RECT_WITHDRAWAL = 10;
constexpr int16_t SAMOVAR_STATUS_RECT_AUTOPAUSE = 15;
constexpr int16_t SAMOVAR_STATUS_BEER = 2000;
constexpr int16_t SAMOVAR_STATUS_CHEESE = 5000;
constexpr int16_t SAMOVAR_STARTVAL_BEER_WAIT_MALT = 2002;
volatile int16_t SamovarStatusInt = 10;
volatile float current_power_volt = 221.26f;
volatile float target_power_volt = 220.0f;
volatile uint16_t current_power_p = 1500;
uint16_t water_pump_speed = 321;
bool valve_status = true;
bool program_type_one_of(ProgramType type, const char* types) {
  return std::string(types).find(type) != std::string::npos;
}
float fromPower(float value) { return value; }
struct NbkActuatorCommandFixture {
  bool active;
  bool closeTransitionPair;
  bool closeSafeWaitPair;
};
NbkActuatorCommandFixture nbkActuatorCommand{};
bool nbk_transition_active() { return false; }
bool nbk_safe_waiting = false;
float nbk_M = 0;
float nbk_P = 0;
uint8_t nbkUiPowerSource = 0;
uint8_t nbkUiFeedSource = 0;
bool nbkUiPowerApplied = false;
bool nbkUiFeedApplied = false;
enum CheeseStageKind : uint8_t {
  CHEESE_STAGE_INVALID, CHEESE_STAGE_HEAT, CHEESE_STAGE_HOLD,
  CHEESE_STAGE_COOL, CHEESE_STAGE_MIX, CHEESE_STAGE_DOSE,
  CHEESE_STAGE_PH, CHEESE_STAGE_WAIT, CHEESE_STAGE_DRAIN, CHEESE_STAGE_LUA,
};
struct CheeseRuntimeFixture {
  uint32_t holdAccumulatedMs;
  bool mixerRunning;
  bool doserStarted;
  bool doserCompleted;
  bool temperatureConfirmActive;
  bool phReachedActive;
};
CheeseRuntimeFixture cheeseRuntime{};
CheeseStageKind cheese_stage_kind(ProgramType type) {
  switch (type) {
    case 'H': return CHEESE_STAGE_HEAT; case 'P': return CHEESE_STAGE_HOLD;
    case 'C': return CHEESE_STAGE_COOL; case 'M': return CHEESE_STAGE_MIX;
    case 'D': return CHEESE_STAGE_DOSE; case 'N': return CHEESE_STAGE_PH;
    case 'W': return CHEESE_STAGE_WAIT; case 'S': return CHEESE_STAGE_DRAIN;
    case 'L': return CHEESE_STAGE_LUA; default: return CHEESE_STAGE_INVALID;
  }
}
bool cheese_in_temperature_band(float actual, float target) {
  return std::fabs(actual - target) <= 0.3f;
}
volatile float WFflowRate = 1.25f;
volatile uint32_t WFtotalMilliLitres = 456;
float pressure_value = 3.5f;
TimePredictorFixture timePredictor{99.9f, 12.9f, 44.9f, 22.9f, true, true};
bool bootDegraded = false;
String bootDegradedReason = "";

enum BoilingEvidence : uint8_t {
  BOILING_EVIDENCE_NONE = 0,
  BOILING_EVIDENCE_STEAM,
  BOILING_EVIDENCE_PIPE,
  BOILING_EVIDENCE_TANK_AND_WATER,
};
BoilingEvidence boiling_evidence = BOILING_EVIDENCE_TANK_AND_WATER;
uint8_t distRowPredictionReason = 4;
uint8_t distProcessPredictionReason = 4;

static uint32_t fakeMillis = 3723000;
static uint32_t fakeHeap = 123456;
static int32_t fakeRssi = -45;
static int volumeValue = 42;
static int32_t targetSteps = 1000;
static int32_t currentSteps = 250;
static float stepperSpeed = 12.5f;
static bool stepperState = true;
static ProgramType programType = 'B';
static RuntimeAjaxSnapshotResult copyResult = RUNTIME_AJAX_SNAPSHOT_OK;
static bool sourceHasEvent = true;
static RuntimeEventDescriptor sourceEvent{7, 0, 3, RUNTIME_EVENT_MESSAGE, 2};
static int copyCalls = 0;
static int sourceGetterCalls = 0;
static uint32_t fakeLatestSequence = 42;
static bool fakeHeaterAlarmLatched = false;
static int fakeCheesePhRaw = 2048;
static float fakeCheesePh = 5.25f;
static bool fakeCheesePhValid = true;
static bool fakeCheesePhRawValid = true;
static uint32_t fakeCheeseWorkSeconds = 75;
static uint32_t fakeCheeseTimeoutRemainingSeconds = 1725;
uint32_t currentSessionId = 1001;
char latched_emergency_stop_reason[192] = "";

struct ESPFixture {
  uint32_t getFreeHeap() {
    sourceGetterCalls++;
    return fakeHeap;
  }
} ESP;

struct WiFiFixture {
  int32_t RSSI() {
    sourceGetterCalls++;
    return fakeRssi;
  }
} WiFi;

uint32_t millis() {
  sourceGetterCalls++;
  return fakeMillis;
}

bool sensor_configured(const SensorFixture&) { return true; }
bool sensor_valid(const SensorFixture&) { return true; }
bool beer_control_sensor(uint8_t sensorId, const SensorFixture*& sensor, const char*& name) {
  static const char* names[] = {"tank", "water", "pipe", "steam", "acp"};
  static const SensorFixture* sensors[] = {&TankSensor, &WaterSensor, &PipeSensor, &SteamSensor, &ACPSensor};
  if (sensorId >= 5) return false;
  sensor = sensors[sensorId];
  name = names[sensorId];
  return true;
}
#define BEER_TEMP_HYSTERESIS 0.3f
// Состояние детектора примесей (impurity_detector.h): снимок читает его через
// функции-доступы, а не через статики файла детектора.
uint8_t detector_idle_reason_code() { return 5; }
float detector_steam_wait_span() { return 0.125f; }
uint16_t detector_steam_wait_left_sec() { return 321; }

int cheese_ph_raw() {
  sourceGetterCalls++;
  return fakeCheesePhRaw;
}

float cheese_ph_value() {
  sourceGetterCalls++;
  return fakeCheesePh;
}

bool cheese_ph_valid() {
  sourceGetterCalls++;
  return fakeCheesePhValid;
}

bool cheese_ph_raw_valid() {
  sourceGetterCalls++;
  return fakeCheesePhRawValid;
}

uint32_t cheese_work_seconds() {
  sourceGetterCalls++;
  return fakeCheeseWorkSeconds;
}

uint32_t cheese_timeout_remaining_seconds() {
  sourceGetterCalls++;
  return fakeCheeseTimeoutRemainingSeconds;
}

String format_uptime(unsigned long seconds) {
  std::ostringstream out;
  out << std::setfill('0') << std::setw(2) << seconds / 3600UL << ':'
      << std::setw(2) << (seconds % 3600UL) / 60UL << ':'
      << std::setw(2) << seconds % 60UL;
  return out.str();
}

String format_float(float value, int digits) {
  if (!std::isfinite(value)) return "---";
  if (value > 99999.0f) value = 99999.0f;
  if (value < -99999.0f) value = -99999.0f;
  std::ostringstream out;
  out << std::fixed << std::setprecision(digits) << value;
  return out.str();
}

int get_liquid_volume() {
  sourceGetterCalls++;
  return volumeValue;
}

int32_t stepper_safe_get_target() {
  sourceGetterCalls++;
  return targetSteps;
}

int32_t stepper_safe_get_current() {
  sourceGetterCalls++;
  return currentSteps;
}

float stepper_safe_get_speed() {
  sourceGetterCalls++;
  return stepperSpeed;
}

bool stepper_safe_get_state() {
  sourceGetterCalls++;
  return stepperState;
}

ProgramType current_program_type() {
  sourceGetterCalls++;
  return programType;
}

bool program_type_empty(ProgramType type) { return type == '\0'; }
String program_type_to_string(ProgramType type) { return String(type); }

float get_alcohol(float temperature) {
  sourceGetterCalls++;
  return temperature / 2.0f;
}

float get_steam_alcohol(float temperature) {
  sourceGetterCalls++;
  return temperature / 4.0f;
}

template <typename UiState>
RuntimeAjaxSnapshotResult copy_ajax_runtime_snapshot(
    String& crt, String& status, String& luaStatus, String& currentPowerMode,
    uint32_t, String& eventText, RuntimeEventDescriptor* events, uint8_t& eventCount,
    uint32_t& latestSequence, const UiState& uiStateSource, UiState& uiStateDestination) {
  copyCalls++;
  if (copyResult != RUNTIME_AJAX_SNAPSHOT_OK) return copyResult;
  uiStateDestination = uiStateSource;
  crt = "clock\"x";
  status = "run\nok";
  luaStatus = "lua\\ok";
  currentPowerMode = "auto";
  eventCount = sourceHasEvent ? 1 : 0;
  if (sourceHasEvent && events) {
    eventText = "evt";
    events[0] = sourceEvent;
    events[0].offset = 0;
    events[0].length = 3;
  } else {
    eventText = "";
  }
  latestSequence = fakeLatestSequence;
  return RUNTIME_AJAX_SNAPSHOT_OK;
}

bool rectSecondPumpRunning = true;
bool rect_second_i2c_pump_enabled() { return true; }
bool heater_safety_latched() {
  sourceGetterCalls++;
  return fakeHeaterAlarmLatched;
}
'''


HARNESS_SUFFIX = r'''
static std::string serialize(const AjaxTelemetrySnapshot& snapshot) {
  Print out;
  writeAjaxTelemetryFields(out, snapshot);
  return out.bytes;
}

static bool contains(const std::string& value, const char* token) {
  return value.find(token) != std::string::npos;
}

static void mutateSources() {
  bme_temp = 9.0f;
  SteamSensor.avgTemp = 10.0f;
  SamSetup.useautospeed = false;
  volumeValue = 99;
  PowerOn = false;
  ProgramNum = 7;
  targetSteps = 9000;
  currentSteps = 8000;
  stepperSpeed = 3.0f;
  i2c_stepper_cache.pump_present = false;
  fakeHeap = 1;
  fakeRssi = -1;
  used_byte = 99999;
  Samovar_Mode = SAMOVAR_SUVID_MODE;
  SamovarStatusInt = 0;
  programType = '\0';
  sourceEvent = RuntimeEventDescriptor{8, 0, 3, RUNTIME_EVENT_CONSOLE, 100};
  fakeLatestSequence = 999;
  fakeHeaterAlarmLatched = true;
  fakeCheesePhRaw = 1000;
  fakeCheesePh = 7.0f;
  fakeCheesePhValid = false;
  fakeCheesePhRawValid = false;
  fakeCheeseWorkSeconds = 0;
  fakeCheeseTimeoutRemainingSeconds = 0;
  currentSessionId = 2002;
}

int main() {
  PowerOn = true;
  ProgramNum = 2;
  programType = 'B';
  program_Wait = true;
  program_Wait_Type = PROGRAM_WAIT_STEAM;
  s_uiStateCache = build_ui_state_from_loop();
  AjaxTelemetrySnapshot first{};
  if (captureAjaxTelemetrySnapshot(6, first) != RUNTIME_AJAX_SNAPSHOT_OK) return 10;
  if (copyCalls != 1 || first.eventCount != 1 || first.runtimeEvents[0].sequence != 7 ||
      first.ui.mode != SAMOVAR_RECTIFICATION_MODE || first.ui.row != 3 ||
      first.ui.waitCount != 1 || first.ui.waits[0].reason != UI_WAIT_RECT_STEAM) return 11;
  const std::string before = serialize(first);

  mutateSources();
  const std::string after = serialize(first);
  if (before != after) return 12;

  Samovar_Mode = SAMOVAR_SUVID_MODE;
  PowerOn = true;
  SamSetup.SuvidHoldMinutes = 15;
  suvidHold = {true, false};
  s_uiStateCache = build_ui_state_from_loop();

  AjaxTelemetrySnapshot second{};
  if (captureAjaxTelemetrySnapshot(7, second) != RUNTIME_AJAX_SNAPSHOT_OK) return 13;
  if (copyCalls != 2 || serialize(second) == before ||
      second.ui.mode != SAMOVAR_SUVID_MODE || second.ui.phase != UI_PHASE_HOLD ||
      !second.ui.end.present || second.ui.end.remainingSeconds != 420 ||
      second.ui.waitCount != 1 || second.ui.waits[0].reason != UI_WAIT_SUVID_HOLD_OUTSIDE_BAND ||
      !contains(serialize(second), "\"sessionId\":2002")) return 14;

  Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
  PowerOn = true;
  SamovarStatusInt = 10;
  programType = 'D';
  i2c_stepper_cache.pump_present = false;
  AjaxTelemetrySnapshot distillation{};
  if (captureAjaxTelemetrySnapshot(0, distillation) != RUNTIME_AJAX_SNAPSHOT_OK) return 15;
  const std::string distillationJson = serialize(distillation);
  if (!contains(distillationJson, "\"alc\":") ||
      !contains(distillationJson, "\"stm_alc\":") ||
      !contains(distillationJson, "\"RowPredictionAvailable\":1") ||
      !contains(distillationJson, "\"ProcessPredictionAvailable\":1") ||
      !contains(distillationJson, "\"RowPredictionReason\":4") ||
      !contains(distillationJson, "\"ProcessPredictionReason\":4") ||
      !contains(distillationJson, "\"TimeRemaining\":12") ||
      !contains(distillationJson, "\"RowTotalTime\":44") ||
      !contains(distillationJson, "\"ProcessTimeRemaining\":22") ||
      !contains(distillationJson, "\"TotalTime\":99") ||
      !contains(distillationJson, "\"i2c_pump_speed\":0,\"i2c_pump_target_ml\":0,\"i2c_pump_remaining_ml\":0,\"i2c_pump_running\":0")) return 16;
  const SAMOVAR_MODE alcoholModes[] = {
      SAMOVAR_RECTIFICATION_MODE, SAMOVAR_BK_MODE, SAMOVAR_NBK_MODE};
  for (SAMOVAR_MODE mode : alcoholModes) {
    Samovar_Mode = mode;
    AjaxTelemetrySnapshot value{};
    if (captureAjaxTelemetrySnapshot(0, value) != RUNTIME_AJAX_SNAPSHOT_OK ||
        !contains(serialize(value), "\"alc\":")) return 17;
  }
  Samovar_Mode = SAMOVAR_BEER_MODE;
  AjaxTelemetrySnapshot beer{};
  if (captureAjaxTelemetrySnapshot(0, beer) != RUNTIME_AJAX_SNAPSHOT_OK ||
      contains(serialize(beer), "\"alc\":")) return 18;

  sourceHasEvent = false;
  AjaxTelemetrySnapshot noEvent{};
  if (captureAjaxTelemetrySnapshot(0, noEvent) != RUNTIME_AJAX_SNAPSHOT_OK ||
      noEvent.eventCount != 0) return 19;
  sourceHasEvent = true;
  sourceEvent.kind = RUNTIME_EVENT_CONSOLE;
  AjaxTelemetrySnapshot consoleEvent{};
  if (captureAjaxTelemetrySnapshot(0, consoleEvent) != RUNTIME_AJAX_SNAPSHOT_OK ||
      consoleEvent.eventCount != 1 ||
      consoleEvent.runtimeEvents[0].kind != RUNTIME_EVENT_CONSOLE) return 20;

  const int gettersBeforeFailure = sourceGetterCalls;
  copyResult = RUNTIME_AJAX_SNAPSHOT_LOCK_BUSY;
  AjaxTelemetrySnapshot failed{};
  if (captureAjaxTelemetrySnapshot(0, failed) != RUNTIME_AJAX_SNAPSHOT_LOCK_BUSY ||
      sourceGetterCalls != gettersBeforeFailure) return 21;
  copyResult = RUNTIME_AJAX_SNAPSHOT_NO_MEMORY;
  if (captureAjaxTelemetrySnapshot(0, failed) != RUNTIME_AJAX_SNAPSHOT_NO_MEMORY ||
      sourceGetterCalls != gettersBeforeFailure) return 22;
  copyResult = RUNTIME_AJAX_SNAPSHOT_CORRUPT;
  if (captureAjaxTelemetrySnapshot(0, failed) != RUNTIME_AJAX_SNAPSHOT_CORRUPT ||
      sourceGetterCalls != gettersBeforeFailure) return 23;

  // Реальное извлечённое тело build_ui_state_from_loop(): два подтверждённых
  // значения НБК должны попасть в разные applied-controls, а не в requested.
  Samovar_Mode = SAMOVAR_NBK_MODE;
  PowerOn = true;
  ProgramNum = 1; ProgramLen = 3; programType = 'H';
  nbkUiPowerApplied = true; nbkUiFeedApplied = true;
  nbkUiPowerSource = UI_CONTROL_SOURCE_PROGRAM;
  nbkUiFeedSource = UI_CONTROL_SOURCE_PROGRAM;
  nbk_M = 120.0f; nbk_P = 1.25f;
  UiStateDescriptor nbkFirst = build_ui_state_from_loop();
  nbk_M = 240.0f; nbk_P = 2.50f;
  UiStateDescriptor nbkSecond = build_ui_state_from_loop();
  if (nbkFirst.phase != UI_PHASE_HEATING || !nbkFirst.end.present ||
      nbkFirst.controlCount != 2 || !nbkFirst.controls[0].hasApplied ||
      nbkFirst.controls[0].applied != 120.0f ||
      nbkSecond.controls[0].applied != 240.0f ||
      nbkFirst.controls[1].applied != 1.25f ||
      nbkSecond.controls[1].applied != 2.50f ||
      nbkFirst.controls[0].source != UI_CONTROL_SOURCE_PROGRAM) return 24;
  nbkUiPowerApplied = false; nbkUiFeedApplied = false;
  if (build_ui_state_from_loop().controlCount != 0) return 25;

  // Выдержка сыра использует накопленное время, а не duration строки: проверяем
  // две разные остаточные величины и реальное ожидание замороженных часов.
  Samovar_Mode = SAMOVAR_CHEESE_MODE;
  ProgramNum = 1; ProgramLen = 3; programType = 'P';
  program[1].WType = 'P'; program[1].Time = 10.0f; program[1].Temp = 65.0f;
  TankSensor.avgTemp = 60.0f;
  cheeseRuntime = CheeseRuntimeFixture{120000U, false, false, false, false, false};
  UiStateDescriptor cheeseFirst = build_ui_state_from_loop();
  cheeseRuntime.holdAccumulatedMs = 420000U;
  UiStateDescriptor cheeseSecond = build_ui_state_from_loop();
  if (cheeseFirst.phase != UI_PHASE_HOLD || !cheeseFirst.end.present ||
      !cheeseFirst.end.hasRemainingSeconds || cheeseFirst.end.remainingSeconds != 480 ||
      cheeseSecond.end.remainingSeconds != 180 || cheeseFirst.waitCount != 1 ||
      cheeseFirst.waits[0].reason != UI_WAIT_CHEESE_HOLD_CLOCK_FREEZE) return 26;

  std::cout << before << '\n';
  return 0;
}
'''


EXPECTED_DEFAULT = (
    '{"bme_temp":1.250,"bme_pressure":760.000,"start_pressure":755.500,'
    '"crnt_tm":"clock\\"x","stm":"01:02:03","SteamTemp":78.125,'
    '"PipeTemp":77.250,"WaterTemp":20.500,"TankTemp":89.750,'
    '"ACPTemp":30.000,"CheesePhRaw":2048,"CheesePhRawValid":1,"CheesePh":5.250,"CheesePhValid":1,'
    '"CheeseWorkSeconds":75,"CheeseTimeoutRemainingSeconds":1725,'
    '"DetectorTrend":0.125,"DetectorStatus":2,'
    '"DetectorIdle":5,"DetectorWaitSpan":0.125,"DetectorWaitLeft":321,'
    '"BoilingDetected":1,"BoilingEvidence":3,"BoilingPrecisionSensorConfigured":1,'
    '"useautospeed":1,"useDetector":1,"version":"6.27",'
    '"sessionId":1001,'
    '"boot_degraded":0,"boot_degraded_reason":"","VolumeAll":42,'
    '"ActualVolumePerHour":1.234,"PowerOn":1,"PauseOn":0,"BeerManualPause":0,'
    '"BeerBrewOrder":"allinone",'
    '"WthdrwlProgress":55,"TargetStepps":1000,"CurrrentStepps":250,'
    '"WthdrwlStatus":1,"SamovarStatusInt":10,"ProgramNum":3,"ProgramIndex":2,'
    '"CurrrentSpeed":13.00,"UseBBuzzer":1,"StepperStepMl":800,'
    '"BodyTemp_Steam":77.000,"BodyTemp_Pipe":76.000,"mixer":1,'
    '"bk_water_auto":1,"bk_steam_setpoint":78.4,'
    '"ISspd":2.500,"i2c_stepper_present":1,"i2c_mixer_present":1,'
    '"i2c_pump_present":1,"i2c_pump_speed":400,"i2c_pump_target_ml":12.5,'
    '"i2c_pump_remaining_ml":7.0,"i2c_pump_running":1,'
    '"i2c_second_pump":1,"i2c_second_pump_running":1,"heap":123456,'
    '"rssi":-45,"fr_bt":98766,"PrgType":"B","current_power_volt":0,'
    '"target_power_volt":0,"current_power_mode":"0","current_power_p":0,'
    '"valve":1,"alc":44.88,"stm_alc":19.53,'
    '"ui":{"m":0,"r":3,"p":8,"w":[{"q":3,"co":1}],"c":[{"k":2,"r":0.000,"a":1.234,"u":3,"s":0},{"k":1,"r":1.000,"a":1.000,"u":8,"s":0}]},"Status":"run\\nok",'
    '"Lstatus":"lua\\\\ok","heaterAlarmLatched":0,"heaterAlarmReason":"","latestMessageSequence":42'
)


EXPECTED_FEATURES = EXPECTED_DEFAULT.replace(
    '"current_power_volt":0,"target_power_volt":0,"current_power_mode":"0",'
    '"current_power_p":0,"valve":1,"alc":',
    '"current_power_volt":221.3,"target_power_volt":220.0,'
    '"current_power_mode":"auto","current_power_p":1500,"valve":1,"wp_spd":321,'
    '"WFflowRate":1.25,"WFtotalMl":456,"prvl":3.50,"alc":',
).replace(
    '"c":[{"k":2,"r":0.000,"a":1.234,"u":3,"s":0},{"k":1,"r":1.000,"a":1.000,"u":8,"s":0}]',
    '"c":[{"k":2,"r":0.000,"a":1.234,"u":3,"s":0},{"k":1,"r":220.000,"a":221.260,"u":9,"s":0}]',
)


def compile_matrix(section: str, name: str, defines: list[str]) -> str:
    source = HARNESS_PREFIX + section + HARNESS_SUFFIX
    with tempfile.TemporaryDirectory(prefix=f"samovar-a05-{name}-") as tmp:
        source_path = Path(tmp) / "test.cpp"
        binary_path = Path(tmp) / "test"
        source_path.write_text(source, encoding="utf-8")
        command = [
            "g++",
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            *defines,
            str(source_path),
            "-o",
            str(binary_path),
        ]
        subprocess.run(command, check=True, cwd=ROOT)
        result = subprocess.run(
            [str(binary_path)], check=True, cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return result.stdout.rstrip("\n")


def main() -> int:
    errors: list[str] = []
    samovar = read("Samovar.ino")
    string_utils = read("string_utils.h")
    try:
        snapshot = extract_struct(samovar, "AjaxTelemetrySnapshot")
        capture = extract_function_body(
            samovar, "static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot("
        )
        writer = extract_function_body(
            samovar, "static void writeAjaxTelemetryFields("
        )
        ui_builder = extract_function_body(
            samovar, "static UiStateDescriptor build_ui_state_from_loop()"
        )
        ui_publisher = extract_function_body(
            samovar, "static void publish_ui_state_from_loop()"
        )
        loop_body = extract_function_body(samovar, "void loop()")
        send_ajax = extract_function_body(
            samovar, "void send_ajax_json(AsyncWebServerRequest *request)"
        )
        section = production_section(samovar, string_utils)
    except ValueError as error:
        print(f"A-05 state owners smoke failed: {error}")
        return 1

    if not re.search(
        r"static_assert\s*\(\s*sizeof\(AjaxTelemetrySnapshot\)\s*<=\s*960",
        samovar,
    ):
        errors.append("AjaxTelemetrySnapshot stack budget assertion is missing")
    forward_declarations = re.findall(
        r"\bstruct\s+AjaxTelemetrySnapshot\s*;", samovar
    )
    definitions = re.findall(
        r"\bstruct\s+AjaxTelemetrySnapshot\s*\{", samovar
    )
    if len(forward_declarations) != 1 or len(definitions) != 1:
        errors.append(
            "AjaxTelemetrySnapshot must have one early declaration and one definition"
        )
    forward_index = samovar.find("struct AjaxTelemetrySnapshot;")
    arduino_prototype_boundary = samovar.find("#include <Arduino.h>")
    definition_index = samovar.find("struct AjaxTelemetrySnapshot {")
    if not (
        0 <= forward_index < arduino_prototype_boundary < definition_index
    ):
        errors.append(
            "AjaxTelemetrySnapshot declaration must precede Arduino prototype insertion"
        )
    if samovar.count("captureAjaxTelemetrySnapshot(") != 2:
        errors.append("captureAjaxTelemetrySnapshot must have one definition and one call")
    if samovar.count("writeAjaxTelemetryFields(") != 2:
        errors.append("writeAjaxTelemetryFields must have one definition and one call")
    if capture.count("copy_ajax_runtime_snapshot(") != 1:
        errors.append("capture must call copy_ajax_runtime_snapshot exactly once")
    if "build_ui_state_from_loop(" in capture or "snapshot.ui." in capture:
        errors.append("HTTP capture must copy, not build or amend, ui state")
    if "const UiStateDescriptor value = build_ui_state_from_loop();" not in ui_publisher or \
       "s_uiStateCache = value;" not in ui_publisher:
        errors.append("loop must build and publish the complete ui cache")
    if not re.search(
        r"runtime_state_lock\(0\).*s_uiStateCache\s*=\s*value;.*runtime_state_unlock\(true\);",
        ui_publisher,
        re.DOTALL,
    ):
        errors.append("ui cache publication must use the existing runtime lock")
    if not re.search(
        r"mode_dispatch_loop\(\);\s*cheese_ph_tick\(\);\s*suvid_tick\(\);\s*"
        r"session_checkpoint_tick\(\);\s*publish_ui_state_from_loop\(\);",
        loop_body,
    ):
        errors.append("ui cache must be published after mode ticks")
    if "copy_program_wait_type(waitType)" not in ui_builder:
        errors.append("ui builder must copy the shared program wait type through its helper")

    writer_clean = strip_cpp_literals(strip_cpp_comments(writer))
    forbidden_writer_tokens = (
        "bme_temp", "bme_pressure", "start_pressure", "SteamSensor",
        "PipeSensor", "WaterSensor", "TankSensor", "ACPSensor", "SamSetup",
        "impurityDetector", "ActualVolumePerHour", "PowerOn", "PauseOn",
        "beerManualPause",
        "WthdrwlProgress", "ProgramNum", "startval", "mixer_status",
        "i2c_stepper_cache", "I2CPumpTargetMl", "ESP.", "WiFi.",
        "total_byte", "used_byte", "Samovar_Mode", "SamovarStatusInt",
        "current_power_volt", "target_power_volt", "current_power_mode",
        "current_power_p", "water_pump_speed", "valve_status", "WFflowRate",
        "WFtotalMilliLitres", "pressure_value", "timePredictor",
        "millis(", "get_liquid_volume(", "stepper_safe_get_",
        "current_program_type(", "get_alcohol(", "get_steam_alcohol(",
        "copy_ajax_runtime_snapshot(", "heater_safety_latched(",
        # [9b] bk_water_auto/bk_steam_setpoint - те же безусловные глобалы БК,
        # что и mixer_status/PowerOn выше - тоже обязаны идти через снимок.
        "bk_water_auto", "bk_steam_setpoint",
    )
    for token in forbidden_writer_tokens:
        if token in writer_clean:
            errors.append(f"serializer reads mutable source after capture: {token}")

    response_index = send_ajax.find('beginResponseStream("application/json")')
    capture_index = send_ajax.find("captureAjaxTelemetrySnapshot(")
    writer_index = send_ajax.find("writeAjaxTelemetryFields(")
    if not (0 <= capture_index < response_index < writer_index):
        errors.append("capture/response/const serializer ordering changed")
    response_tail = strip_cpp_literals(strip_cpp_comments(send_ajax[response_index:]))
    for token in forbidden_writer_tokens:
        if token in response_tail:
            errors.append(f"send_ajax_json reads mutable source after response creation: {token}")

    required_snapshot_members = (
        "String crt", "String status", "String luaStatus", "String currentPowerMode",
        "String programType", "String eventText",
        "RuntimeEventDescriptor runtimeEvents",
        "float currentSpeed", "uint8_t eventCount",
        "bool heaterAlarmLatched", "String heaterAlarmReason", "uint32_t latestMessageSequence",
        "UiStateDescriptor ui",
        "uint32_t cheeseWorkSeconds", "uint32_t cheeseTimeoutRemainingSeconds",
    )
    for token in required_snapshot_members:
        if token not in snapshot:
            errors.append(f"snapshot member missing: {token}")

    hashes = {
        "static RuntimeAjaxQuery classifyRuntimeAjaxQuery(AsyncWebServerRequest* request)":
            "530cf3702917d3d6b3c03f3065f0e4a0420e5780578a91eadc1f82965accd6ae",
        "static bool sendRuntimeAjaxQueryError(":
            "d0276e7c4ab3fe8b8bee4b80c4a34e998bbb50b2178e40923f5a06eda2adf68e",
        "static bool sendRuntimeEventResponse(":
            "1721d7a14e3fa8c79967cc05c6d397c27fde8b52105f73c4bce25ab8af4f4806",
        "static bool runtimeEventWriteSection(":
            "787fcfdbed4331d45f1c919d881de9565fc0987eb80c15849aa4fe2b6b12695a",
    }
    for signature, expected in hashes.items():
        actual = hashlib.sha256(
            extract_function_body(samovar, signature).encode("utf-8")
        ).hexdigest()
        if actual != expected:
            errors.append(f"pre-existing query/event helper changed: {signature}")
    operation_prefix = send_ajax[:send_ajax.find("  const uint32_t messageCursor = query.value;")]
    if hashlib.sha256(operation_prefix.encode("utf-8")).hexdigest() != (
        "36a1e2ced5eaa7a8ca2542442ee1a53c06e6cec7b163200811c7bde95b9163fd"
    ):
        errors.append("operation/query branch is not byte-identical to A-05 baseline")

    if errors:
        print("A-05 state owners smoke failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    matrices = (
        ("default", [], EXPECTED_DEFAULT),
        (
            "features",
            [
                "-DSAMOVAR_USE_POWER",
                "-DUSE_WATER_PUMP",
                "-DUSE_WATERSENSOR",
                "-DUSE_PRESSURE_XGZ",
            ],
            EXPECTED_FEATURES,
        ),
    )
    for name, defines, expected in matrices:
        try:
            actual = compile_matrix(section, name, defines)
        except subprocess.CalledProcessError as error:
            print(f"A-05 {name} C++11 harness failed: {error}")
            return 1
        if actual != expected:
            print(f"A-05 {name} golden mismatch")
            print(f"expected: {expected}")
            print(f"actual:   {actual}")
            return 1

    print("A-05 immutable telemetry snapshot smoke passed (2 compile matrices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
