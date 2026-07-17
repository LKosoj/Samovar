#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

SKIP_DIRS = {
    ".git",
    ".pio",
    ".ai-docs",
    "ai_docs_site",
    "libraries",
    "pro_mini_ntc",
}


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


samovar_mqtt = read_text("SamovarMqtt.h")
samovar_ino = read_text("Samovar.ino")

if samovar_mqtt:
    for token in [
        "SemaphoreHandle_t xMqttSemaphore = NULL;",
        "StaticSemaphore_t xMqttSemaphoreBuffer;",
        "inline bool init_mqtt_lock()",
        "inline bool mqtt_lock(",
        "inline void mqtt_unlock(",
        "void disconnectFromMqtt()",
        "bool mqttConnected()",
    ]:
        if token not in samovar_mqtt:
            errors.append(f"SamovarMqtt.h missing MQTT ownership token: {token}")

    try:
        body = extract_function_body(samovar_mqtt, "void MqttSendMsg")
        if "static " in body:
            errors.append("MqttSendMsg must not use static mutable buffers")
        if "SendMsg(" in body:
            errors.append("MqttSendMsg must not call SendMsg")
        for token in [
            "char topic[MQTT_TOPIC_SIZE];",
            "char payload[PAYLOADSIZE];",
            "memcpy(payload, Str.c_str(), payloadLength);",
            "payload[payloadLength] = '\\0';",
        ]:
            if token not in body:
                errors.append(f"MqttSendMsg missing local-buffer token: {token}")
        require_ordered_tokens(
            "MqttSendMsg locks around publish/retry",
            body,
            [
                "bool locked = mqtt_lock",
                "mqttClient.publish(topic, 2, true, payload, payloadLength);",
                "mqttClient.connected()",
                "mqttClient.connect();",
                "mqttClient.publish(topic, 2, true, payload, payloadLength);",
                "mqtt_unlock(true);",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

    for signature in ["void connectToMqtt() {", "void disconnectFromMqtt() {", "bool mqttConnected() {"]:
        try:
            body = extract_function_body(samovar_mqtt, signature)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if "mqtt_lock" not in body or "mqtt_unlock(true)" not in body:
            errors.append(f"{signature} must lock and unlock mqttClient access")

if samovar_ino:
    try:
        setup_body = extract_function_body(samovar_ino, "void setup()")
        require_ordered_tokens(
            "setup initializes MQTT mutex before initMqtt",
            setup_body,
            [
                "#ifdef USE_MQTT",
                "const bool mqttLockReady = init_mqtt_lock();",
                "if (!mqttLockReady) {",
                'report_degraded_boot("mqtt", "mutex init failed");',
                "if (mqttLockReady && !wifiAP) {",
                "initMqtt();",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    # Owner decision: a failed MQTT mutex init degrades and continues (fail-open) instead
    # of halting boot forever; initMqtt() must stay gated behind the lock actually existing.
    try:
        mqtt_gate_body = extract_function_body(samovar_ino, "if (!mqttLockReady) {")
        if "while (true)" in mqtt_gate_body or "while(true)" in mqtt_gate_body:
            errors.append("MQTT mutex init failure must not halt boot forever")
    except ValueError as exc:
        errors.append(str(exc))
    if "mqttClient.connected()" in samovar_ino or "mqttClient.disconnect()" in samovar_ino:
        errors.append("Samovar.ino must use MQTT wrappers instead of direct mqttClient lifecycle calls")

for path in ROOT.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in rel.parts):
        continue
    if path.name == "SamovarMqtt.h":
        continue
    if rel.as_posix() == "tools/smoke_mqtt_buffers.py":
        continue
    if path.suffix not in {".ino", ".h", ".cpp", ".hpp", ".py"}:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "mqttClient." in text:
        errors.append(f"{rel} accesses mqttClient directly outside SamovarMqtt.h")

if errors:
    print("MQTT buffer/lifecycle smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("MQTT buffer/lifecycle smoke check passed")
