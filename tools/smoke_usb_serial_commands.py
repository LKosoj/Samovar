#!/usr/bin/env python3
"""Проверяет потоковый отчёт compile-time конфигурации через USB.

Харнесс компилирует настоящее тело USB-приёмника из Samovar.ino и настоящий
firmware_config_report.h. Две матрицы флагов доказывают, что отчёт отражает
результат сборки, а не один захардкоженный JSON. Мутации накладываются только
на временные копии исходников и обязаны ломать содержательные проверки.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import samovar_configurator as configurator

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
INO_SOURCE = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
HEADER_SOURCE = (ROOT / "firmware_config_report.h").read_text(encoding="utf-8")
STRING_UTILS_SOURCE = (ROOT / "string_utils.h").read_text(encoding="utf-8")
USB_SIGNATURE = "inline void tick_usb_serial_command()"
ESCAPE_SIGNATURE = "inline bool json_write_escaped(Print& out, const char* text, size_t length)"
EXPECTED_SETTING_KEYS = {
    "board", "regulator", "atmospheric_sensor", "column_pressure_sensor", "servoDelta",
    "wifi_ssid", "wifi_password",
    *(spec.macro for spec in configurator.VALUE_SPECS),
    *(spec.macro for spec in configurator.BOOL_SPECS),
    *(spec.macro for spec in configurator.OPTIONAL_SPECS),
    *(spec.macro for spec in configurator.CHOICE_VALUE_SPECS),
}


def escaped_body() -> str:
    return extract_function_body(STRING_UTILS_SOURCE, ESCAPE_SIGNATURE)


def json_string_print_source() -> str:
    start = STRING_UTILS_SOURCE.index("class JsonStringPrint : public Print {")
    end = STRING_UTILS_SOURCE.index("/** JSON-строка", start)
    return STRING_UTILS_SOURCE[start:end].strip()


def matrix_defines(name: str) -> str:
    common = r'''
#define F(value) value
#define SAMOVAR_VERSION F("7.00")
#define DEVKIT 1
#define LILYGO 2
#define ESP32S3 3
#define LOW 0x0
#define HIGH 0x1
#define SAMOVAR_HOST "samovar"
#define ALARM_WATER_TEMP 70
#define MAX_WATER_TEMP 75
#define MAX_STEAM_TEMP 98.8
#define MAX_ACP_TEMP 75
#define CHANGE_POWER_MODE_STEAM_TEMP 39
#define OPEN_VALVE_TANK_TEMP 77
#define DELTA_T_CLOSE_VALVE 20
#define PWM_LOW_VALUE 10
#define PWM_START_VALUE 40
#define HEAT_DELTA 1
#define ACCELERATION_HEATER_DELTA 4
#define BOILING_TEMP 98.9
#define DEFAULT_DIST_TEMP 99.9
#define WF_CALIBRATION 98
#define WATER_FLOW_MIN_PULSES 7
#define NBK_MULT_PAUSE_OVERFLOW 2
#define NBK_PUMP_LIMIT 30
#define NBK_WORK_PRESSURE_RATIO 0.5f
#define NBK_PRESSURE_MARGIN 5
#define NBK_END_STEAM_RISE 5.0f
#define SAMOVAR_USE_POWER_START_TIME 2000
#define LCD_RESET_PERIOD_MS 240000UL
#define PAUSE_RESUME_HYSTERESIS_DELTA 0.07f
#define PROGRAM_ROW_STOP_PAUSE_LIMIT 3
#define PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT 10
#define PROGRAM_DONE_AUTO_POWEROFF_MIN 30
#define BODY_TEMP_AUTOSET_MAX_RISE 0.3f
#define BK_STEAM_SETPOINT_MIN 30
#define BK_STEAM_SETPOINT_MAX 100
#define BK_WATER_ADJUST_PERIOD_MS 60000
#define BK_WATER_DEADBAND 0.2f
#define BK_WATER_PWM_STEP 30
int8_t servoDelta[11] = {0, -2, -3, -4, -3, -2, 0, 0, 0, 0, -2};
'''
    if name == "default":
        return common + r'''
#define BOARD DEVKIT
#define BLYNK_SAMOVAR_TOOL "samovar-tool.ru"
#define SAMOVAR_USE_BLYNK
#define SAMOVAR_USE_POWER
#define USE_WATERSENSOR
#define USE_WATER_PUMP
#define USE_HEAD_LEVEL_SENSOR
#define IGNORE_HEAD_LEVEL_SENSOR_SETTING
#define USE_BTN
#define USE_BODY_TEMP_AUTOSET
#define USE_BME680
'''
    if name == "sem_s3":
        return common + r'''
#define BOARD ESP32S3
#define SAMOVAR_USE_SEM_AVR
#define SAMOVAR_USE_RMVK
#define USE_LUA
#define USE_ALARM_BTN
#define USE_UPDATE_OTA
#define USE_STEPPER_ACCELERATION
#define STEPPER_REVERSE
#define COLUMN_WETTING
#define USE_WATER_VALVE LOW
#define USE_EXPANDER 0x20
#define USE_ANALOG_EXPANDER 0x48
#define USE_ADS1115 0x49
#define I2CStepperStepMl 16000
#define WETTING_POWER 220
#define USE_PRESSURE_1WIRE {0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x55}
#define USE_BMP280_ALT
#define SAMOVAR_WIFI_SSID "Lab\\\"<SSID>"
#define SAMOVAR_WIFI_PASSWORD "pass\\word"
'''
    raise ValueError(name)


def harness(usb_body: str, header_source: str, matrix: str) -> str:
    header = header_source.replace("#pragma once", "").replace("#include <Arduino.h>", "").replace(
        '#include "string_utils.h"', ""
    )
    return r'''
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <limits>
#include <string>

class Print {
 public:
  virtual ~Print() {}
  virtual size_t write(uint8_t value) = 0;
  virtual size_t write(const uint8_t* data, size_t size) {
    size_t written = 0;
    while (written < size && write(data[written]) == 1) written++;
    return written;
  }
  size_t print(long value) {
    const std::string text = std::to_string(value);
    return write(reinterpret_cast<const uint8_t*>(text.data()), text.size());
  }
  size_t print(double value, int digits) {
    char text[64];
    const int size = std::snprintf(text, sizeof(text), "%.*f", digits, value);
    return size > 0 ? write(reinterpret_cast<const uint8_t*>(text), static_cast<size_t>(size)) : 0;
  }
  size_t print(const char* value) {
    return write(reinterpret_cast<const uint8_t*>(value), std::strlen(value));
  }
};

class String {
 public:
  static size_t capacityLimit;

  bool concat(char value) {
    return append(&value, 1);
  }
  bool concat(const char* value, size_t size) {
    return append(value, size);
  }
  const char* c_str() const { return value_.c_str(); }
  size_t length() const { return value_.size(); }

 private:
  bool append(const char* value, size_t size) {
    if (size > capacityLimit - value_.size()) return false;
    value_.append(value, size);
    return true;
  }
  std::string value_;
};

size_t String::capacityLimit = std::numeric_limits<size_t>::max();

inline bool json_write_escaped(Print& out, const char* text, size_t length) {
@ESCAPED_BODY@
}

@JSON_STRING_PRINT@

@MATRIX@

struct FakeSerial : Print {
  std::string input;
  std::string output;
  size_t position = 0;
  size_t bufferWrites = 0;
  bool injectConcurrentLog = false;
  int available() const { return position < input.size(); }
  int read() { return static_cast<unsigned char>(input[position++]); }
  size_t write(uint8_t value) override { output += static_cast<char>(value); return 1; }
  size_t write(const uint8_t* data, size_t size) override {
    bufferWrites++;
    if (injectConcurrentLog) {
      output += "CONCURRENT LOG\n";
      injectConcurrentLog = false;
    }
    output.append(reinterpret_cast<const char*>(data), size);
    return size;
  }
  size_t print(const char* value) { return Print::print(value); }
  size_t println(const char* value) { const size_t written = print(value); output += "\n"; return written + 1; }
  size_t println() { output += "\n"; return 1; }
  void feed(const char* value) { input += value; }
} Serial;

char ipst[16] = "stale-ip";
char ipstSnapshot[16] = "192.168.1.37";

void ipst_copy(char (&copy)[sizeof(ipst)]) {
  std::memcpy(copy, ipstSnapshot, sizeof(ipst));
}

@HEADER@

inline void tick_usb_serial_command() {
@USB_BODY@
}

static bool expect(const std::string& actual, const std::string& expected, const char* label) {
  if (actual == expected) return true;
  std::cerr << label << ": expected [" << expected << "] got [" << actual << "]\n";
  return false;
}

int main() {
  Serial.feed("SAMOVAR:IP?");
  tick_usb_serial_command();
  if (!expect(Serial.output, "", "fragment must wait for newline")) return 1;
  Serial.feed("\n");
  tick_usb_serial_command();
  if (!expect(Serial.output, "SAMOVAR:IP=192.168.1.37\n", "IP response")) return 2;

  Serial.output.clear();
  Serial.bufferWrites = 0;
  Serial.injectConcurrentLog = true;
  Serial.feed("SAMOVAR:CONFIG?");
  tick_usb_serial_command();
  if (!expect(Serial.output, "", "config fragment must wait for newline")) return 3;

  Serial.feed("\n");
  tick_usb_serial_command();
  if (Serial.bufferWrites != 1) return 4;
  const size_t jsonStart = Serial.output.find('{');
  const size_t logStart = Serial.output.find("CONCURRENT LOG\n");
  if (jsonStart == std::string::npos || logStart == std::string::npos || logStart > jsonStart) return 5;
  if (Serial.output.back() != '\n' || Serial.output.find('\n', jsonStart) != Serial.output.size() - 1) return 6;
  const std::string config = Serial.output.substr(jsonStart);

  Serial.output.clear();
  Serial.feed("SAMOVAR:CONFIG!\n");
  tick_usb_serial_command();
  if (!expect(Serial.output, "", "unknown command")) return 7;

  Serial.feed("SAMOVAR:CONFIG?xxxxxxxxx\n");
  tick_usb_serial_command();
  if (!expect(Serial.output, "", "overflow command")) return 8;

  Serial.feed("SAMOVAR:CONFIG?\n");
  tick_usb_serial_command();
  if (!expect(Serial.output, config, "overflow recovery")) return 9;

  Serial.output.clear();
  Serial.bufferWrites = 0;
  String::capacityLimit = 32;
  Serial.feed("SAMOVAR:CONFIG?\n");
  tick_usb_serial_command();
  if (!Serial.output.empty() || Serial.bufferWrites != 0) return 10;
  String::capacityLimit = std::numeric_limits<size_t>::max();

  std::cout << config;
  return 0;
}
'''.replace("@ESCAPED_BODY@", escaped_body()).replace(
        "@JSON_STRING_PRINT@", json_string_print_source()
    ).replace("@MATRIX@", matrix_defines(matrix)).replace(
        "@HEADER@", header
    ).replace("@USB_BODY@", usb_body)


def compile_and_run(usb_body: str, header_source: str, matrix: str, name: str) -> subprocess.CompletedProcess[str]:
    compiler = shutil.which("g++")
    if not compiler:
        raise RuntimeError("g++ not found")
    with tempfile.TemporaryDirectory(prefix="samovar-usb-config-") as directory:
        source = Path(directory) / (name + ".cpp")
        binary = Path(directory) / name
        source.write_text(harness(usb_body, header_source, matrix), encoding="utf-8")
        built = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True,
        )
        if built.returncode:
            return built
        return subprocess.run([str(binary)], capture_output=True, text=True)


def parse_config(result: subprocess.CompletedProcess[str], matrix: str) -> dict:
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    line = result.stdout.rstrip("\n")
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{matrix}: ответ не JSON: {line!r}: {error}") from error
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{matrix}: корень JSON должен быть объектом")
    return parsed


def check_matrix(matrix: str, parsed: dict) -> list[str]:
    settings = parsed.get("settings")
    if parsed.get("type") != "samovar_firmware_config":
        return [f"{matrix}: неверный маркер type"]
    if parsed.get("schema") != 1:
        return [f"{matrix}: schema должен быть 1"]
    if parsed.get("firmwareVersion") != "7.00":
        return [f"{matrix}: неверная версия прошивки"]
    if not isinstance(settings, dict):
        return [f"{matrix}: settings отсутствует или не объект"]

    errors = []
    if set(settings) != EXPECTED_SETTING_KEYS:
        errors.append(
            f"{matrix}: settings не совпадает с текущими полями desktop configurator: "
            f"missing={sorted(EXPECTED_SETTING_KEYS - set(settings))}, "
            f"extra={sorted(set(settings) - EXPECTED_SETTING_KEYS)}"
        )
    for spec in configurator.BOOL_SPECS:
        if not isinstance(settings.get(spec.macro), bool):
            errors.append(f"{matrix}: {spec.macro} должен быть boolean")
    for spec in (*configurator.OPTIONAL_SPECS, *configurator.CHOICE_VALUE_SPECS):
        if settings.get(spec.macro) is not None and not isinstance(settings.get(spec.macro), str):
            errors.append(f"{matrix}: {spec.macro} должен быть string или null")
    if settings.get("SAMOVAR_HOST") != "samovar":
        errors.append(f"{matrix}: не экспортирован SAMOVAR_HOST")
    if settings.get("MAX_STEAM_TEMP") != 98.8:
        errors.append(f"{matrix}: не экспортирован MAX_STEAM_TEMP")
    if settings.get("DEFAULT_DIST_TEMP") != 99.9:
        errors.append(f"{matrix}: не экспортирован DEFAULT_DIST_TEMP")
    if settings.get("servoDelta") != [0, -2, -3, -4, -3, -2, 0, 0, 0, 0, -2]:
        errors.append(f"{matrix}: не экспортирован servoDelta")
    if matrix == "default":
        expected = {
            "board": "DEVKIT", "regulator": "kvic", "atmospheric_sensor": "bme680",
            "column_pressure_sensor": "none", "SAMOVAR_USE_BLYNK": True,
            "USE_WATER_PUMP": True, "USE_LUA": False, "USE_EXPANDER": None,
            "USE_PRESSURE_XGZ": None, "wifi_ssid": None, "wifi_password": None,
        }
    else:
        expected = {
            "board": "ESP32S3", "regulator": "sem_avr", "atmospheric_sensor": "bmp280_alt",
            "column_pressure_sensor": "onewire", "SAMOVAR_USE_BLYNK": False,
            "USE_WATER_PUMP": False, "USE_LUA": True, "USE_EXPANDER": "0x20",
            "USE_ADS1115": "0x49",
            "USE_WATER_VALVE": "LOW", "USE_PRESSURE_XGZ": None,
            "USE_PRESSURE_1WIRE": "{0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x55}",
            "wifi_ssid": 'Lab\\"<SSID>', "wifi_password": "pass\\word",
        }
    for key, value in expected.items():
        if settings.get(key) != value:
            errors.append(f"{matrix}: {key} expected {value!r}, got {settings.get(key)!r}")
    return errors


def check_ui_config(matrix: str, response: dict) -> list[str]:
    try:
        config = configurator.parse_device_config(json.dumps(response, ensure_ascii=False))
    except configurator.ConfigError as error:
        return [f"{matrix}: configurator rejected firmware JSON: {error}"]

    settings = response["settings"]
    ui = config.settings
    expected_choices = {
        "default": {
            "board": "ESP32 DevKit",
            "regulator": "KVIC",
            "atmospheric_sensor": "BME680",
            "column_pressure_sensor": "Не использовать",
        },
        "sem_s3": {
            "board": "ESP32-S3",
            "regulator": "SEM_AVR",
            "atmospheric_sensor": "BMP280, альтернативный адрес",
            "column_pressure_sensor": "1-Wire",
        },
    }[matrix]
    errors = []
    for key, value in expected_choices.items():
        if ui.get(key) != value:
            errors.append(f"{matrix}: UI {key} expected {value!r}, got {ui.get(key)!r}")
    for spec in configurator.VALUE_SPECS:
        value = settings[spec.macro]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if ui.get(spec.macro) != str(value):
                errors.append(
                    f"{matrix}: UI {spec.macro} expected string {str(value)!r}, got {ui.get(spec.macro)!r}"
                )
    servo = ", ".join(str(value) for value in settings["servoDelta"])
    if ui.get("servoDelta") != servo:
        errors.append(f"{matrix}: UI servoDelta expected {servo!r}, got {ui.get('servoDelta')!r}")
    for spec in configurator.OPTIONAL_SPECS:
        value = settings[spec.macro]
        enabled = value is not None
        if ui.get(spec.macro + ".enabled") is not enabled:
            errors.append(
                f"{matrix}: UI {spec.macro}.enabled expected {enabled!r}, "
                f"got {ui.get(spec.macro + '.enabled')!r}"
            )
        if enabled and ui.get(spec.macro) != value:
            errors.append(f"{matrix}: UI {spec.macro} expected {value!r}, got {ui.get(spec.macro)!r}")
    for key in ("wifi_ssid", "wifi_password"):
        expected = settings[key] if settings[key] is not None else ""
        if ui.get(key) != expected:
            errors.append(f"{matrix}: UI {key} expected {expected!r}, got {ui.get(key)!r}")
    return errors


def main() -> int:
    usb_body = extract_function_body(INO_SOURCE, USB_SIGNATURE)
    errors = []
    for matrix in ("default", "sem_s3"):
        try:
            parsed = parse_config(compile_and_run(usb_body, HEADER_SOURCE, matrix, matrix), matrix)
        except RuntimeError as error:
            errors.append(f"{matrix}: USB/config harness failed: {error}")
            continue
        errors.extend(check_matrix(matrix, parsed))
        errors.extend(check_ui_config(matrix, parsed))

    loop_body = extract_function_body(INO_SOURCE, "void loop()")
    if loop_body.count("tick_usb_serial_command();") != 1:
        errors.append("loop() must call tick_usb_serial_command() exactly once")

    mutations = (
        ("usb command recognition", "usb", 'strcmp(command, "SAMOVAR:CONFIG?") == 0', "false"),
        ("newline framing", "usb", "incoming == '\\n'", "incoming == '\\r'"),
        ("IP snapshot", "usb", "ipst_copy(ip);", "std::memcpy(ip, ipst, sizeof(ip));"),
        (
            "single serial buffer write", "usb",
            "Serial.write(\n                reinterpret_cast<const uint8_t*>(configJson.c_str()), configJson.length());",
            "Serial.write(\n                reinterpret_cast<const uint8_t*>(configJson.c_str()), 1);\n"
            "            Serial.write(\n                reinterpret_cast<const uint8_t*>(configJson.c_str() + 1), configJson.length() - 1);",
        ),
        ("report type", "header", '"samovar_firmware_config"', '"broken_config"'),
        ("schema", "header", '"schema", 1', '"schema", 2'),
        ("password key", "header", '"wifi_password", SAMOVAR_WIFI_PASSWORD', '"broken_password", SAMOVAR_WIFI_PASSWORD'),
        ("water valve token", "header", '"USE_WATER_VALVE", "LOW"', '"USE_WATER_VALVE", "BROKEN"'),
    )
    for label, target, old, new in mutations:
        source = usb_body if target == "usb" else HEADER_SOURCE
        if source.count(old) != 1:
            errors.append(f"mutation target missing: {label}")
            continue
        mutated_usb = usb_body.replace(old, new) if target == "usb" else usb_body
        mutated_header = HEADER_SOURCE.replace(old, new) if target == "header" else HEADER_SOURCE
        result = compile_and_run(mutated_usb, mutated_header, "sem_s3", "mutant")
        if label == "IP snapshot":
            if result.returncode == 0 or "IP response" not in result.stderr:
                errors.append("mutation was not rejected by the IP response assertion")
            continue
        try:
            parsed = parse_config(result, "mutant")
            rejected = bool(check_matrix("sem_s3", parsed) or check_ui_config("sem_s3", parsed))
        except RuntimeError:
            rejected = True
        if not rejected:
            errors.append(f"mutation was not rejected: {label}")

    if errors:
        print("USB firmware configuration smoke check failed:")
        for error in errors:
            print(" - " + error)
        return 1
    print("USB firmware configuration smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
