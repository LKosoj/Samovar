#!/usr/bin/env python3
"""Поведенческая проверка локального и серверного формата строк журнала."""

from pathlib import Path
import re
import subprocess
import tempfile

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
FS_SOURCE = (ROOT / "FS.ino").read_text(encoding="utf-8")
errors: list[str] = []


def extract(signature: str) -> str:
    try:
        return extract_function_body(FS_SOURCE, signature, strip_comments=False)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


FORMAT_BODY = extract(
    "static String format_log_base_fields(const float sensorTemp[], float pressure, uint8_t programNum, bool fileLog)"
)
BUILD_BODY = extract("static String build_current_log_base_line()")
header_match = re.search(
    r"String str = (.*?);\s*size_t headerWritten", extract("bool create_data()"), re.S
)
HEADER_EXPRESSION = header_match.group(1).strip() if header_match else ""

if "fileLog ? 2 : 3" not in FORMAT_BODY:
    errors.append("format precision logic was not extracted")
if "build_current_log_base_line" not in FS_SOURCE or "bme_pressure" not in BUILD_BODY:
    errors.append("build_current_log_base_line was not extracted")
if HEADER_EXPRESSION != '"Date,Steam,Pipe,Water,Tank"':
    errors.append("create_data header expression was not extracted")

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}
  String& operator=(const char* value) { value_ = value ? value : ""; return *this; }
  String operator+(const char* value) const { return String(value_ + (value ? value : "")); }
  String operator+(const String& value) const { return String(value_ + value.value_); }
  String& operator+=(const char* value) { value_ += value ? value : ""; return *this; }
  String& operator+=(const String& value) { value_ += value.value_; return *this; }
  String& operator+=(int value) { value_ += std::to_string(value); return *this; }
  size_t length() const { return value_.length(); }
  int indexOf(char value) const { const auto p = value_.find(value); return p == std::string::npos ? -1 : static_cast<int>(p); }
  bool endsWith(const char* suffix) const { std::string s(suffix); return value_.size() >= s.size() && value_.compare(value_.size() - s.size(), s.size(), s) == 0; }
  void remove(size_t start) { value_.erase(start); }
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};
static String operator+(const char* left, const String& right) { return String(std::string(left) + right.value()); }

static String format_float(float value, int digits) {
  char output[32];
  std::snprintf(output, sizeof(output), "%.*f", digits, value);
  return String(output);
}
static String Crt = "2026-10-03T04:44:12";
static constexpr uint8_t DS_LOGGED_SENSOR_COUNT = 4;
static float bme_pressure = 0.0f;
static uint8_t ProgramNum = 0;
struct Sensor { float avgTemp = 0.0f; } SteamSensor, PipeSensor, WaterSensor, TankSensor;

@FORMAT@
@BUILD@

static void check(bool condition, const std::string& message) {
  if (!condition) std::cerr << "FAIL: " << message << '\n', std::exit(1);
}
static std::vector<std::string> fields(const String& value) {
  std::vector<std::string> result; std::string current;
  for (char ch : value.value()) { if (ch == ',') { result.push_back(current); current.clear(); } else current += ch; }
  result.push_back(current); return result;
}
static void setSensors() {
  SteamSensor.avgTemp = 78.126f; PipeSensor.avgTemp = 77.938f;
  WaterSensor.avgTemp = 10.999f; TankSensor.avgTemp = -2.50f;
  bme_pressure = 1013.25f; ProgramNum = 6;
}
static void test_local_format() {
  const float values[] = {78.126f, 77.938f, 10.999f, -2.50f};
  auto result = fields(format_log_base_fields(values, 1013.25f, 6, true));
  check(result.size() == 5, "local log must contain header date and four temperatures");
  if (result.size() == 5) {
    check(result[1] == "78.13", "local first temperature must use two decimals and round");
    check(result[2] == "77.94", "local second temperature must use two decimals and round");
    check(result[3] == "11", "local whole temperature must lose trailing zero and point");
    check(result[4] == "-2.5", "local negative half temperature must lose one trailing zero");
  }
  const float secondValues[] = {0.0f, 123.406f, 20.5f, -0.126f};
  auto second = fields(format_log_base_fields(secondValues, 750.12f, 2, true));
  check(second.size() == 5 && second[1] == "0" && second[2] == "123.41" &&
        second[3] == "20.5" && second[4] == "-0.13",
        "second local sample must preserve zero, sign, and rounded fractions");
}
static void test_server_format() {
  setSensors();
  auto result = fields(build_current_log_base_line());
#ifdef WRITE_PROGNUM_IN_LOG
  check(result.size() == 7, "server log with program number must contain seven fields");
#else
  check(result.size() == 6, "server log without program number must contain six fields");
#endif
  if (result.size() >= 6) {
    check(result[1] == "78.126" && result[2] == "77.938" && result[3] == "10.999" && result[4] == "-2.500",
          "server log must use three decimals for all temperatures");
    check(result[5] == "1013.25", "server log must use the current pressure");
#ifdef WRITE_PROGNUM_IN_LOG
    check(result[6] == "7", "server log program number must be one based");
#endif
  }
  SteamSensor.avgTemp = 1.5f; PipeSensor.avgTemp = 2.625f;
  WaterSensor.avgTemp = 3.125f; TankSensor.avgTemp = 4.75f;
  bme_pressure = 750.12f; ProgramNum = 2;
  auto second = fields(build_current_log_base_line());
  check(second[1] == "1.500" && second[2] == "2.625" && second[3] == "3.125" &&
        second[4] == "4.750" && second[5] == "750.12",
        "second server sample must retain fixed precision and current pressure");
#ifdef WRITE_PROGNUM_IN_LOG
  check(second[6] == "3", "second server sample must retain current program number");
#endif
}
static void test_file_header() {
  String header = @HEADER@;
  check(header.value() == "Date,Steam,Pipe,Water,Tank", "file header must contain Date and four named sensors");
  check(fields(header).size() == 5, "file header must contain exactly five columns");
}
int main() { test_local_format(); test_server_format(); test_file_header(); return 0; }
'''


def make_harness(format_body: str = FORMAT_BODY, macro: bool = True) -> str:
    source = HARNESS.replace("@FORMAT@", f"static String format_log_base_fields(const float sensorTemp[], float pressure, uint8_t programNum, bool fileLog) {{{format_body}}}")
    source = source.replace("@BUILD@", f"static String build_current_log_base_line() {{{BUILD_BODY}}}")
    source = source.replace("@HEADER@", HEADER_EXPRESSION)
    if macro:
        source = "#define WRITE_PROGNUM_IN_LOG\n" + source
    return source


def run(name: str, source: str, success: bool) -> None:
    with tempfile.TemporaryDirectory(prefix=f"samovar-local-log-{name}-") as directory:
        root = Path(directory)
        cpp = root / "probe.cpp"
        cpp.write_text(source, encoding="utf-8")
        result = subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(root / "probe")], capture_output=True, text=True)
        if result.returncode:
            errors.append(f"{name} compile failed:\n{result.stderr}")
            return
        result = subprocess.run([str(root / "probe")], capture_output=True, text=True)
        if success and result.returncode:
            errors.append(f"{name} behavior failed:\n{result.stdout}{result.stderr}")
        if not success:
            expected = {
                "mutation-local-pressure": "local log must contain header date and four temperatures",
                "mutation-local-program": "local log must contain header date and four temperatures",
                "mutation-local-precision": "local first temperature must use two decimals and round",
                "mutation-local-trim": "local whole temperature must lose trailing zero and point",
            }[name]
            if result.returncode == 0 or "FAIL: " + expected not in result.stdout + result.stderr:
                errors.append(f"mutation {name} missed its assertion: {result.stdout}{result.stderr}")


if not errors:
    run("server-with-program", make_harness(macro=True), True)
    run("server-without-program", make_harness(macro=False), True)
    run("local", make_harness(macro=True), True)
    run("mutation-local-pressure", make_harness(FORMAT_BODY.replace("if (!fileLog) {\n    str += \",\";\n    str += format_float(pressure, 2);", "{\n    str += \",\";\n    str += format_float(pressure, 2);", 1), macro=True), False)
    run("mutation-local-program", make_harness(FORMAT_BODY.replace("#ifdef WRITE_PROGNUM_IN_LOG\n  if (!fileLog)", "#ifdef WRITE_PROGNUM_IN_LOG\n  if (true)", 1), macro=True), False)
    run("mutation-local-precision", make_harness(FORMAT_BODY.replace("fileLog ? 2 : 3", "3", 1), macro=True), False)
    run("mutation-local-trim", make_harness(FORMAT_BODY.replace("while (temperature.endsWith(\"0\"))", "while (false && temperature.endsWith(\"0\"))", 1), macro=True), False)

if errors:
    print("Local log format smoke failed:")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("Local log format smoke passed")
