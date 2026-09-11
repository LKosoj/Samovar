#!/usr/bin/env python3
"""Проверяет реальный V27 для Lua: размер и лимит Lua_status без обрезания."""
import re
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
V27_JSON_MAX = 1017
EXPECTED_LUA_STATUS_ESCAPED_MAX = 361


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def body(source: str, signature: str) -> str:
    return extract_function_body(source, signature)


def region(source: str, start: str, end: str) -> str:
    left = source.find(start)
    right = source.find(end, left)
    if left < 0 or right < left:
        raise ValueError(f"missing source region: {start} .. {end}")
    return source[left:right]


def main() -> int:
    samovar = read("Samovar.ino")
    blynk = read("Blynk.ino")
    string_utils = read("string_utils.h")
    sensorinit = read("sensorinit.h")
    runtime_helpers = read("runtime_helpers.h")
    ui_types = region(samovar, "enum UiStagePhase", "static UiStateDescriptor s_uiStateCache")
    pair_types = region(read("runtime_pair_events.h"), "enum UiWaitReason", "struct RuntimePairState")
    raw = body(read("json_field_raw.h"), "static inline void jsonFieldRaw(Print &out, bool &first, const char *key, T value)")
    blynk_writer = body(blynk, "static void write_blynk_mode_json(Print& out, const AjaxTelemetrySnapshot& s)")
    source = f'''\
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <type_traits>

#define BLYNK_MAX_SENDBYTES 1024
#include <Blynk/BlynkParam.h>
using std::isinf;
using std::isnan;

#define DETECTOR_IDLE_STEAM_WAIT 1
constexpr uint8_t SAMOVAR_LUA_MODE = 6;

class String {{
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {{}}
  String(const std::string& value) : value_(value) {{}}
  String(int value) : value_(std::to_string(value)) {{}}
  size_t length() const {{ return value_.size(); }}
  const char* c_str() const {{ return value_.c_str(); }}
  const std::string& str() const {{ return value_; }}
 private:
  std::string value_;
}};

class Print {{
 public:
  virtual ~Print() = default;
  void print(char value) {{ bytes.push_back(value); }}
  void print(const char* value) {{ bytes += value; }}
  void print(const String& value) {{ bytes += value.str(); }}
  virtual size_t write(uint8_t value) {{ bytes.push_back(static_cast<char>(value)); return 1; }}
  virtual size_t write(const uint8_t* value, size_t size) {{ bytes.append(reinterpret_cast<const char*>(value), size); return size; }}
  template <typename T> typename std::enable_if<std::is_integral<T>::value, void>::type print(T value) {{
    std::ostringstream out; out << static_cast<long long>(value); bytes += out.str();
  }}
  std::string bytes;
}};

char* dtostrf(double value, signed char, unsigned char digits, char* out);

String format_float(float v, int d) {{
{body(sensorinit, "inline String format_float(float v, int d)")}
}}

char* dtostrf(double value, signed char, unsigned char digits, char* out) {{
  std::ostringstream stream; stream << std::fixed << std::setprecision(digits) << value;
  const std::string text = stream.str(); std::copy(text.begin(), text.end(), out); out[text.size()] = '\\0';
  return out;
}}

{pair_types}
{re.search(r'static UiControlSource uiWithdrawalControlSource = [^;]+;', samovar).group(0)}
{ui_types}

static inline void jsonAddKey(Print &out, bool &first, const char *key) {{
{body(samovar, "static inline void jsonAddKey(Print &out, bool &first, const char *key)")}
}}
inline bool json_write_escaped(Print& out, const char* text, size_t length) {{
{body(string_utils, "inline bool json_write_escaped(Print& out, const char* text, size_t length)")}
}}
inline size_t json_escaped_length(const char* text, size_t length) {{
{body(string_utils, "inline size_t json_escaped_length(const char* text, size_t length)")}
}}
constexpr size_t LUA_STATUS_V27_ESCAPED_MAX = {EXPECTED_LUA_STATUS_ESCAPED_MAX};
inline bool lua_status_v27_fits(const String& status) {{
{body(runtime_helpers, "inline bool lua_status_v27_fits(const String& status)")}
}}
static void jsonPrintEscaped(Print &out, const String &value) {{
{body(samovar, "static void jsonPrintEscaped(Print &out, const String &value)")}
}}
static inline void jsonFieldFloat(Print &out, bool &first, const char *key, float value, int decimals) {{
{body(samovar, "static inline void jsonFieldFloat(Print &out, bool &first, const char *key, float value, int decimals)")}
}}
static inline void jsonFieldString(Print &out, bool &first, const char *key, const String &value) {{
{body(samovar, "static inline void jsonFieldString(Print &out, bool &first, const char *key, const String &value)")}
}}
static inline void jsonFieldBool(Print &out, bool &first, const char *key, bool value) {{
{body(samovar, "static inline void jsonFieldBool(Print &out, bool &first, const char *key, bool value)")}
}}
template <typename T> static inline void jsonFieldRaw(Print &out, bool &first, const char *key, T value) {{
{raw}
}}
static void writeUiEndFields(Print& out, bool& first, const UiEndDescriptor& value) {{
{body(samovar, "static void writeUiEndFields(Print& out, bool& first, const UiEndDescriptor& value)")}
}}
static void writeUiStateJson(Print& out, bool& first, const UiStateDescriptor& value, const String& luaStatus) {{
{body(samovar, "static void writeUiStateJson(Print& out, bool& first, const UiStateDescriptor& value,")}
}}

struct AjaxTelemetrySnapshot {{
  int16_t statusInt; uint8_t programIndex; String programType; bool hasAlcohol; float alcohol; float steamAlcohol;
  bool hasTimePrediction; bool rowPredictionAvailable; bool processPredictionAvailable; int timeRemaining;
  int rowPredictedTotalTime; int processRemainingTime; int totalTime; uint8_t detectorStatus; float detectorTrend;
  uint8_t detectorIdle; uint16_t detectorWaitLeftSec; float detectorWaitSpan; bool useDetector; bool useAutoSpeed;
  bool boilingDetected; uint8_t boilingEvidence; bool boilingPrecisionSensorConfigured; bool bkWaterAuto;
  float bkSteamSetpoint; bool valveOpen; uint16_t waterPumpSpeed; float waterFlowRate; uint32_t waterFlowTotalMl;
  float pressure; float i2cStepperSpeed; bool secondPumpEnabled; bool secondPumpRunning; bool beerPaused;
  uint8_t beerBrewOrder; bool mixer; float cheesePh; bool cheesePhValid; UiStateDescriptor ui; String luaStatus;
}};

static void write_blynk_mode_json(Print& out, const AjaxTelemetrySnapshot& s) {{
{blynk_writer}
}}

int main() {{
  AjaxTelemetrySnapshot s{{}};
  s.statusInt = -32768; s.programIndex = 254; s.programType = "L";
  s.detectorStatus = 255; s.detectorTrend = -99999.0f; s.detectorIdle = DETECTOR_IDLE_STEAM_WAIT;
  s.detectorWaitLeftSec = 65535; s.detectorWaitSpan = -99999.0f; s.useDetector = true; s.useAutoSpeed = true;
  s.boilingDetected = true; s.boilingEvidence = 255; s.boilingPrecisionSensorConfigured = true; s.bkWaterAuto = true;
  s.bkSteamSetpoint = -99999.0f; s.valveOpen = true; s.waterPumpSpeed = 65535; s.waterFlowRate = -99999.0f;
  s.waterFlowTotalMl = 4294967295U; s.pressure = -99999.0f; s.i2cStepperSpeed = -99999.0f;
  s.secondPumpEnabled = true; s.secondPumpRunning = true; s.beerPaused = true; s.beerBrewOrder = 255;
  s.mixer = true; s.cheesePh = -99999.0f; s.cheesePhValid = true;
  s.ui.mode = 6; s.ui.phase = UI_PHASE_LUA_KNOWN; s.ui.hasRow = true; s.ui.row = 255;
  s.ui.end = {{true, 9, 9, 5, true, -99999.0f, 11, true, 4294967295U}};
  s.ui.waitCount = 1; s.ui.waits[0] = {{23, 5}}; s.ui.hasNextRow = true; s.ui.nextRow = 255;
  s.ui.controlCount = 4;
  for (uint8_t index = 0; index < s.ui.controlCount; index++)
    s.ui.controls[index] = {{6, true, -99999.0f, true, -99999.0f, 11, 7}};
  Print out; write_blynk_mode_json(out, s); const size_t emptyLength = out.bytes.size();
  const size_t cap = {V27_JSON_MAX} - emptyLength - 8U;  // ,"ls":""
  if (emptyLength >= {V27_JSON_MAX} || cap != {EXPECTED_LUA_STATUS_ESCAPED_MAX}) {{
    std::cerr << "empty=" << emptyLength << " cap=" << cap << "\\n"; return 1;
  }}
  std::string atLimit(50, '<');
  atLimit += std::string(10, '"');
  atLimit += std::string(10, '\\n');
  for (uint8_t index = 0; index < 10; index++) {{
    atLimit.push_back(static_cast<char>(0xD0));
    atLimit.push_back(static_cast<char>(0x96));
  }}
  atLimit.push_back('x');
  const std::string overLimit = atLimit + "x";
  const char escapedSample[] = {{'<', '"', '\\n', static_cast<char>(0xD0), static_cast<char>(0x96)}};
  if (json_escaped_length(atLimit.c_str(), atLimit.size()) != {EXPECTED_LUA_STATUS_ESCAPED_MAX} ||
      json_escaped_length(overLimit.c_str(), overLimit.size()) != {EXPECTED_LUA_STATUS_ESCAPED_MAX} + 1 ||
      json_escaped_length(escapedSample, sizeof(escapedSample)) != 12) {{
    std::cerr << "escaped-length boundary mismatch\\n"; return 1;
  }}
  if (!lua_status_v27_fits(String(atLimit)) || lua_status_v27_fits(String(overLimit))) {{
    std::cerr << "Lua setter boundary mismatch\\n"; return 1;
  }}
  s.luaStatus = String(atLimit);
  Print boundary; write_blynk_mode_json(boundary, s);
  Print escapedStatus; json_write_escaped(escapedStatus, atLimit.c_str(), atLimit.size());
  if (boundary.bytes.size() > {V27_JSON_MAX} ||
      boundary.bytes.find(escapedStatus.bytes) == std::string::npos) {{
    std::cerr << "Lua boundary payload mismatch\\n"; return 1;
  }}
  char blynkParamBuffer[BLYNK_MAX_SENDBYTES] = {{}};
  BlynkParam blynkParam(blynkParamBuffer, 0, sizeof(blynkParamBuffer));
  blynkParam.add("vw"); blynkParam.add("27"); blynkParam.add(boundary.bytes.c_str());
  if (blynkParam.getLength() != boundary.bytes.size() + 7 ||
      std::string(blynkParamBuffer + 6) != boundary.bytes) {{
    std::cerr << "BlynkParam=" << blynkParam.getLength() << "\\n"; return 1;
  }}
  s.hasAlcohol = true; s.alcohol = -99999.0f; s.steamAlcohol = -99999.0f;
  s.hasTimePrediction = true; s.rowPredictionAvailable = true; s.processPredictionAvailable = true;
  s.timeRemaining = -2147483648; s.rowPredictedTotalTime = -2147483648;
  s.processRemainingTime = -2147483648; s.totalTime = -2147483648;
  s.ui = {{}}; s.ui.mode = 0; s.ui.phase = UI_PHASE_ERROR; s.ui.hasRow = true; s.ui.row = 255;
  s.ui.end = {{true, 9, 9, 5, true, -99999.0f, 11, true, 4294967295U}};
  s.ui.globalEndCount = 2;
  s.ui.globalEnds[0] = {{true, 9, 9, 5, true, -99999.0f, 11, true, 4294967295U}};
  s.ui.globalEnds[1] = {{true, 9, 9, 5, true, -99999.0f, 11, true, 4294967295U}};
  s.ui.waitCount = 2; s.ui.waits[0] = {{23, 5}}; s.ui.waits[1] = {{23, 5}};
  s.ui.hasNextRow = true; s.ui.nextRow = 255; s.ui.controlCount = 4;
  for (uint8_t index = 0; index < s.ui.controlCount; index++)
    s.ui.controls[index] = {{6, true, -99999.0f, true, -99999.0f, 11, 7}};
  Print full; write_blynk_mode_json(full, s);
  if (full.bytes.size() > {V27_JSON_MAX}) {{
    std::cerr << "full=" << full.bytes.size() << " exceeds V27 budget\\n"; return 1;
  }}
  std::cout << "lua-empty=" << emptyLength << " lua-escaped-cap=" << cap
            << " full=" << full.bytes.size() << "\\n";
  return 0;
}}
'''
    with tempfile.TemporaryDirectory(prefix="samovar-ui-p01-") as temp:
        cpp = Path(temp) / "test.cpp"
        binary = Path(temp) / "test"
        cpp.write_text(source, encoding="utf-8")
        result = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                                 "-DSAMOVAR_USE_POWER", "-DUSE_WATER_PUMP", "-DUSE_WATERSENSOR", "-DUSE_PRESSURE_XGZ",
                                 "-I", str(ROOT / "libraries/Blynk/src"), str(cpp), "-o", str(binary)], text=True, capture_output=True)
        if result.returncode:
            print(result.stderr, end="")
            return 1
        result = subprocess.run([str(binary)], text=True, capture_output=True)
        if result.returncode:
            print(result.stderr, end="")
            return 1
        print(result.stdout, end="")
        removed_ui = blynk_writer.replace(
            "writeUiStateJson(out, first, s.ui, s.luaStatus);", "(void)s.ui;"
        )
        if removed_ui == blynk_writer:
            print("P01 mutation setup failed: ui serializer call not found")
            return 1
        cpp.write_text(source.replace(blynk_writer, removed_ui), encoding="utf-8")
        mutated = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-pedantic",
                                 "-DSAMOVAR_USE_POWER", "-DUSE_WATER_PUMP", "-DUSE_WATERSENSOR", "-DUSE_PRESSURE_XGZ",
                                 "-I", str(ROOT / "libraries/Blynk/src"), str(cpp), "-o", str(binary)], text=True, capture_output=True)
        if mutated.returncode:
            print(mutated.stderr, end="")
            print("P01 mutation did not compile; semantic coverage is absent")
            return 1
        mutated = subprocess.run([str(binary)], text=True, capture_output=True)
        if mutated.returncode == 0:
            print("P01 mutation survived: removing ui serializer did not fail the budget contract")
            return 1
    print("P01 V27 Lua budget smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
