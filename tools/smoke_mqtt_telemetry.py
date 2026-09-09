#!/usr/bin/env python3
"""Проверяет минимальную MQTT-телеметрию и её расписание."""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8")


mqtt_header = read_text("SamovarMqtt.h")
samovar = read_text("Samovar.ino")
blynk = read_text("Blynk.ino")
samovar_h = read_text("Samovar.h")
override_example = read_text("user_config_override.example.h")

if mqtt_header:
    feature_guard = mqtt_header.find("#ifdef USE_MQTT")
    include = mqtt_header.find("#include <mqtt_client.h>")
    if feature_guard < 0 or include < feature_guard:
        errors.append("esp-mqtt include must be inside #ifdef USE_MQTT")
    for token in [
        "esp_mqtt_client_handle_t mqttClient",
        "MQTT_TRANSPORT_OVER_TCP",
        "reconnect_timeout_ms = 10000",
        "esp_mqtt_client_get_outbox_size(mqttClient)",
    ]:
        if token not in mqtt_header:
            errors.append(f"SamovarMqtt.h missing MQTT contract token: {token}")
    compact_header = re.sub(r"\s+", " ", mqtt_header)
    enqueue_call = (
        "esp_mqtt_client_enqueue( mqttClient, MQTT_TOPIC, line.c_str(), "
        "line.length(), 1, true, false)"
    )
    if enqueue_call not in compact_header:
        errors.append("SamovarMqtt.h missing QoS 1 retained enqueue call")
    if "mqtt://" in mqtt_header or "mqtts://" in mqtt_header:
        errors.append("MQTT transport must use host/port settings without a hidden URI")
    if "static char" in mqtt_header and "payload" in mqtt_header:
        errors.append("MQTT module must not own a mutable payload queue")

if samovar_h:
    for macro in ("MQTT_SERVER", "MQTT_PORT", "MQTT_USER", "MQTT_PASSWORD", "MQTT_TOPIC"):
        if f"#ifndef {macro}" not in samovar_h:
            errors.append(f"Samovar.h must fail explicitly when {macro} is missing")

if override_example:
    for token in [
        "//#define USE_MQTT",
        '#define MQTT_SERVER ""',
        "#define MQTT_PORT 1883",
        '#define MQTT_USER ""',
        '#define MQTT_PASSWORD ""',
        '#define MQTT_TOPIC "samovar/state"',
    ]:
        if token not in override_example:
            errors.append(f"user_config_override.example.h missing: {token}")

if blynk:
    for token in [
        "volatile uint32_t blynkLastLargePublishAt = 0;",
        "blynkLastLargePublishAt = millis();",
    ]:
        if token not in blynk:
            errors.append(f"Blynk.ino missing MQTT spacing token: {token}")

payload_body = ""
schedule_body = ""
if samovar:
    try:
        payload_signature = re.search(
            r"static\s+String\s+build_mqtt_log_line\s*\(\s*\)\s*\{", samovar
        )
        if not payload_signature:
            raise ValueError("function not found: static String build_mqtt_log_line()")
        payload_body = extract_function_body(samovar, payload_signature.group(0))
        require_ordered_tokens(
            "MQTT 15-field payload",
            payload_body,
            [
                'line += "1,";',
                "line += Crt;",
                "Samovar_Mode",
                "SamovarStatusInt",
                "ProgramNum + 1",
                "current_program_type()",
                "SteamSensor.avgTemp",
                "PipeSensor.avgTemp",
                "WaterSensor.avgTemp",
                "TankSensor.avgTemp",
                "ACPSensor.avgTemp",
                "bme_pressure",
                "pressure_value",
                "current_power_p",
                "ActualVolumePerHour",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        schedule_signature = re.search(
            r"static\s+bool\s+mqtt_publish_due\s*\(\s*uint32_t\s+now,\s*"
            r"bool\s+idle,\s*uint32_t\s+lastAttemptAt,\s*"
            r"uint32_t\s+lastBlynkAt\s*\)\s*\{",
            samovar,
        )
        if not schedule_signature:
            raise ValueError(
                "function not found: static bool mqtt_publish_due(uint32_t, bool, uint32_t, uint32_t)"
            )
        schedule_body = extract_function_body(samovar, schedule_signature.group(0))
    except ValueError as exc:
        errors.append(str(exc))

if payload_body and schedule_body:
    harness = f"""
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>

class String {{
 public:
  std::string value;
  String() = default;
  String(const char* text) : value(text ? text : "") {{}}
  String(char text) : value(1, text) {{}}
  String(int text) : value(std::to_string(text)) {{}}
  String(unsigned int text) : value(std::to_string(text)) {{}}
  void reserve(size_t) {{}}
  String& operator+=(const String& other) {{ value += other.value; return *this; }}
  String& operator+=(const char* other) {{ value += other; return *this; }}
  String& operator+=(char other) {{ value += other; return *this; }}
  String& operator+=(int other) {{ value += std::to_string(other); return *this; }}
  String& operator+=(unsigned int other) {{ value += std::to_string(other); return *this; }}
}};

String format_float(float value, int decimals) {{
  char buffer[48];
  std::snprintf(buffer, sizeof(buffer), "%.*f", decimals, value);
  return String(buffer);
}}

using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\\0';
constexpr int SAMOVAR_STARTVAL_IDLE = 0;
constexpr uint32_t MQTT_ACTIVE_PERIOD_MS = 4000;
constexpr uint32_t MQTT_IDLE_PERIOD_MS = 5000;
constexpr uint32_t MQTT_BLYNK_GAP_MS = 2000;
struct Sensor {{ float avgTemp; }};
Sensor SteamSensor, PipeSensor, WaterSensor, TankSensor, ACPSensor;
String Crt;
int Samovar_Mode = 0;
int SamovarStatusInt = 0;
unsigned int ProgramNum = 0;
int startval = 0;
float bme_pressure = 0;
float pressure_value = 0;
unsigned int current_power_p = 0;
float ActualVolumePerHour = 0;
ProgramType currentType = PROGRAM_TYPE_NONE;
ProgramType current_program_type() {{ return currentType; }}
void append_program_type(String& text, ProgramType type) {{ if (type) text += type; }}

String build_mqtt_log_line() {{ {payload_body} }}
bool mqtt_publish_due(uint32_t now, bool idle, uint32_t lastAttemptAt, uint32_t lastBlynkAt) {{ {schedule_body} }}

void expect(bool condition, const char* message) {{
  if (!condition) {{ std::cerr << message << "\\n"; std::exit(1); }}
}}

int main() {{
  Crt = String("123"); Samovar_Mode = 2; SamovarStatusInt = 30; ProgramNum = 2; startval = 30;
  currentType = 'B'; SteamSensor.avgTemp = 78.1234f; PipeSensor.avgTemp = 77.2345f;
  WaterSensor.avgTemp = 25.3456f; TankSensor.avgTemp = 91.4567f; ACPSensor.avgTemp = 40.5678f;
  bme_pressure = 752.678f; pressure_value = 12.789f; current_power_p = 1450;
  ActualVolumePerHour = 1.2345f;
  const std::string activeLine = build_mqtt_log_line().value;
  if (activeLine != "1,123,2,30,3,B,78.123,77.234,25.346,91.457,40.568,752.68,12.79,1450,1.235") {{
    std::cerr << "active MQTT payload fields or order changed: " << activeLine << "\\n";
    return 1;
  }}

  Crt = String("456"); Samovar_Mode = 0; SamovarStatusInt = 0; ProgramNum = 7; startval = 0;
  currentType = 'T'; SteamSensor.avgTemp = 1.0f; PipeSensor.avgTemp = 2.0f;
  WaterSensor.avgTemp = 3.0f; TankSensor.avgTemp = 4.0f; ACPSensor.avgTemp = 5.0f;
  bme_pressure = 6.0f; pressure_value = 7.0f; current_power_p = 8;
  ActualVolumePerHour = 9.0f;
  expect(build_mqtt_log_line().value ==
      "1,456,0,0,0,,1.000,2.000,3.000,4.000,5.000,6.00,7.00,8,9.000",
      "idle MQTT payload must use step 0 and an empty step type");

  expect(!mqtt_publish_due(3999, false, 0, 0), "active payload sent before 4 seconds");
  expect(mqtt_publish_due(4000, false, 0, 0), "active payload not sent at 4 seconds");
  expect(!mqtt_publish_due(5000, true, 0, 5000), "idle payload ignored Blynk collision");
  expect(!mqtt_publish_due(6999, true, 0, 5000), "MQTT did not keep the 2 second Blynk gap");
  expect(mqtt_publish_due(7000, true, 0, 5000), "MQTT did not send after the Blynk gap");
  expect(!mqtt_publish_due(10999, false, 7000, 0), "active period measured from wrong point");
  expect(mqtt_publish_due(11000, false, 7000, 0), "active period boundary rejected");
  return 0;
}}
"""
    with tempfile.TemporaryDirectory(prefix="samovar-mqtt-smoke-") as tmp:
        source_path = Path(tmp) / "mqtt_harness.cpp"
        binary_path = Path(tmp) / "mqtt_harness"
        source_path.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append("MQTT source-derived harness did not compile:\n" + compile_result.stderr)
        else:
            run_result = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
            if run_result.returncode != 0:
                errors.append("MQTT source-derived harness failed:\n" + run_result.stderr)
            mutants = (
                (
                    "missing ACPSensor field",
                    harness.replace("line += format_float(ACPSensor.avgTemp, 3);", "", 1),
                ),
                (
                    "missing Blynk gap",
                    harness.replace(
                        "now - lastBlynkAt < MQTT_BLYNK_GAP_MS",
                        "now - lastBlynkAt < MQTT_BLYNK_GAP_MS - 1",
                        1,
                    ),
                ),
            )
            for index, (name, mutant) in enumerate(mutants):
                if mutant == harness:
                    errors.append(f"MQTT mutation was not applied: {name}")
                    continue
                mutant_source = Path(tmp) / f"mqtt_mutant_{index}.cpp"
                mutant_binary = Path(tmp) / f"mqtt_mutant_{index}"
                mutant_source.write_text(mutant, encoding="utf-8")
                mutant_compile = subprocess.run(
                    [
                        "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                        str(mutant_source), "-o", str(mutant_binary),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if mutant_compile.returncode != 0:
                    errors.append(
                        f"MQTT mutation did not reach behavioral assertion: {name}\n"
                        + mutant_compile.stderr
                    )
                    continue
                mutant_run = subprocess.run(
                    [str(mutant_binary)], capture_output=True, text=True, check=False
                )
                if mutant_run.returncode == 0:
                    errors.append(f"MQTT test survived mutation: {name}")

if errors:
    print("MQTT telemetry smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("MQTT telemetry smoke check passed")
