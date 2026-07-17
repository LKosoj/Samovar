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


def production_section(source: str) -> str:
    snapshot = extract_struct(source, "AjaxTelemetrySnapshot")
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
    return f"""
{snapshot}

static inline void jsonAddKey(Print &out, bool &first, const char *key) {{
{json_key}
}}

static void jsonPrintEscaped(Print &out, const String &value) {{
{json_escape}
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

enum SAMOVAR_MODE : uint8_t {
  SAMOVAR_RECTIFICATION_MODE,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE,
};

using ProgramType = char;

struct SetupFixture {
  bool useautospeed;
  bool UseBBuzzer;
  uint16_t StepperStepMl;
};

struct SensorFixture {
  float avgTemp;
  float BodyTemp;
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
};

volatile float bme_temp = 1.25f;
volatile float bme_pressure = 760.0f;
volatile float start_pressure = 755.5f;
SetupFixture SamSetup{true, true, 800};
SensorFixture SteamSensor{78.125f, 77.0f};
SensorFixture PipeSensor{77.25f, 76.0f};
SensorFixture WaterSensor{20.5f, 0.0f};
SensorFixture TankSensor{89.75f, 0.0f};
SensorFixture ACPSensor{30.0f, 0.0f};
DetectorFixture impurityDetector{0.125f, 2};
volatile float ActualVolumePerHour = 1.234f;
volatile bool PowerOn = true;
volatile bool PauseOn = false;
volatile uint8_t WthdrwlProgress = 55;
volatile int16_t startval = 1;
volatile uint8_t ProgramNum = 2;
bool mixer_status = true;
volatile I2CCacheFixture i2c_stepper_cache{true, true, 400, 2.5f, 7, 1};
volatile float I2CPumpTargetMl = 12.5f;
uint32_t total_byte = 100000;
uint32_t used_byte = 1234;
volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
volatile int16_t SamovarStatusInt = 10;
volatile float current_power_volt = 221.26f;
volatile float target_power_volt = 220.0f;
volatile uint16_t current_power_p = 1500;
uint16_t water_pump_speed = 321;
volatile float WFflowRate = 1.25f;
volatile uint32_t WFtotalMilliLitres = 456;
float pressure_value = 3.5f;
TimePredictorFixture timePredictor{99.9f, 12.9f};
bool bootDegraded = false;
String bootDegradedReason = "";

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

RuntimeAjaxSnapshotResult copy_ajax_runtime_snapshot(
    String& crt, String& status, String& luaStatus, String& currentPowerMode,
    uint32_t, String& eventText, RuntimeEventDescriptor& event, bool& hasEvent,
    uint32_t& latestSequence) {
  copyCalls++;
  if (copyResult != RUNTIME_AJAX_SNAPSHOT_OK) return copyResult;
  crt = "clock\"x";
  status = "run\nok";
  luaStatus = "lua\\ok";
  currentPowerMode = "auto";
  eventText = "evt";
  event = sourceEvent;
  hasEvent = sourceHasEvent;
  latestSequence = fakeLatestSequence;
  return RUNTIME_AJAX_SNAPSHOT_OK;
}

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
}

int main() {
  AjaxTelemetrySnapshot first{};
  if (captureAjaxTelemetrySnapshot(6, first) != RUNTIME_AJAX_SNAPSHOT_OK) return 10;
  if (copyCalls != 1 || !first.hasRuntimeEvent || first.runtimeEvent.sequence != 7) return 11;
  const std::string before = serialize(first);

  mutateSources();
  const std::string after = serialize(first);
  if (before != after) return 12;

  AjaxTelemetrySnapshot second{};
  if (captureAjaxTelemetrySnapshot(7, second) != RUNTIME_AJAX_SNAPSHOT_OK) return 13;
  if (copyCalls != 2 || serialize(second) == before) return 14;

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
      !contains(distillationJson, "\"TimeRemaining\":12") ||
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
      noEvent.hasRuntimeEvent) return 19;
  sourceHasEvent = true;
  sourceEvent.kind = RUNTIME_EVENT_CONSOLE;
  AjaxTelemetrySnapshot consoleEvent{};
  if (captureAjaxTelemetrySnapshot(0, consoleEvent) != RUNTIME_AJAX_SNAPSHOT_OK ||
      consoleEvent.runtimeEvent.kind != RUNTIME_EVENT_CONSOLE) return 20;

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

  std::cout << before << '\n';
  return 0;
}
'''


EXPECTED_DEFAULT = (
    '{"bme_temp":1.250,"bme_pressure":760.000,"start_pressure":755.500,'
    '"crnt_tm":"clock\\"x","stm":"01:02:03","SteamTemp":78.125,'
    '"PipeTemp":77.250,"WaterTemp":20.500,"TankTemp":89.750,'
    '"ACPTemp":30.000,"DetectorTrend":0.125,"DetectorStatus":2,'
    '"useautospeed":1,"version":"6.27",'
    '"boot_degraded":0,"boot_degraded_reason":"","VolumeAll":42,'
    '"ActualVolumePerHour":1.234,"PowerOn":1,"PauseOn":0,'
    '"WthdrwlProgress":55,"TargetStepps":1000,"CurrrentStepps":250,'
    '"WthdrwlStatus":1,"ProgramNum":3,"ProgramIndex":2,'
    '"CurrrentSpeed":13.00,"UseBBuzzer":1,"StepperStepMl":800,'
    '"BodyTemp_Steam":77.000,"BodyTemp_Pipe":76.000,"mixer":1,'
    '"ISspd":2.500,"i2c_stepper_present":1,"i2c_mixer_present":1,'
    '"i2c_pump_present":1,"i2c_pump_speed":400,"i2c_pump_target_ml":12.5,'
    '"i2c_pump_remaining_ml":7.0,"i2c_pump_running":1,"heap":123456,'
    '"rssi":-45,"fr_bt":98766,"PrgType":"B","current_power_volt":0,'
    '"target_power_volt":0,"current_power_mode":"0","current_power_p":0,'
    '"alc":44.88,"stm_alc":19.53,"Status":"run\\nok",'
    '"Lstatus":"lua\\\\ok","heaterAlarmLatched":0,"latestMessageSequence":42'
)


EXPECTED_FEATURES = EXPECTED_DEFAULT.replace(
    '"current_power_volt":0,"target_power_volt":0,"current_power_mode":"0",'
    '"current_power_p":0,"alc":',
    '"current_power_volt":221.3,"target_power_volt":220.0,'
    '"current_power_mode":"auto","current_power_p":1500,"wp_spd":321,'
    '"WFflowRate":1.25,"WFtotalMl":456,"prvl":3.50,"alc":',
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
    try:
        snapshot = extract_struct(samovar, "AjaxTelemetrySnapshot")
        capture = extract_function_body(
            samovar, "static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot("
        )
        writer = extract_function_body(
            samovar, "static void writeAjaxTelemetryFields("
        )
        send_ajax = extract_function_body(
            samovar, "void send_ajax_json(AsyncWebServerRequest *request)"
        )
        section = production_section(samovar)
    except ValueError as error:
        print(f"A-05 state owners smoke failed: {error}")
        return 1

    if not re.search(
        r"static_assert\s*\(\s*sizeof\(AjaxTelemetrySnapshot\)\s*<=\s*512",
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

    writer_clean = strip_cpp_literals(strip_cpp_comments(writer))
    forbidden_writer_tokens = (
        "bme_temp", "bme_pressure", "start_pressure", "SteamSensor",
        "PipeSensor", "WaterSensor", "TankSensor", "ACPSensor", "SamSetup",
        "impurityDetector", "ActualVolumePerHour", "PowerOn", "PauseOn",
        "WthdrwlProgress", "ProgramNum", "startval", "mixer_status",
        "i2c_stepper_cache", "I2CPumpTargetMl", "ESP.", "WiFi.",
        "total_byte", "used_byte", "Samovar_Mode", "SamovarStatusInt",
        "current_power_volt", "target_power_volt", "current_power_mode",
        "current_power_p", "water_pump_speed", "WFflowRate",
        "WFtotalMilliLitres", "pressure_value", "timePredictor",
        "millis(", "get_liquid_volume(", "stepper_safe_get_",
        "current_program_type(", "get_alcohol(", "get_steam_alcohol(",
        "copy_ajax_runtime_snapshot(", "heater_safety_latched(",
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
        "String programType", "String eventText", "RuntimeEventDescriptor runtimeEvent",
        "float currentSpeed", "bool hasRuntimeEvent",
        "bool heaterAlarmLatched", "uint32_t latestMessageSequence",
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
            "4909e61379972ead1bb07a686bfa97e2cb8db1d2a05c67303553a3139df6ef8e",
        "static bool runtimeEventWriteSection(":
            "b1e5894de3c9241b43570cff75bb2afd91a12c11d8fcf6cf435fd933763f5616",
    }
    for signature, expected in hashes.items():
        actual = hashlib.sha256(
            extract_function_body(samovar, signature).encode("utf-8")
        ).hexdigest()
        if actual != expected:
            errors.append(f"pre-existing query/event helper changed: {signature}")
    operation_prefix = send_ajax[:send_ajax.find("  const uint32_t messageCursor = query.value;")]
    if hashlib.sha256(operation_prefix.encode("utf-8")).hexdigest() != (
        "137ca05f30bc28569b0aa63c511343a4dcd7c9e8948d9420f02d82cd1ca40351"
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
