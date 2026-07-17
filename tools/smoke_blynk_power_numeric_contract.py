#!/usr/bin/env python3
import json
import sys
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
    strip_cpp_comments,
)


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def function_body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


blynk = strip_cpp_comments(read_text("Blynk.ino"))
power = strip_cpp_comments(read_text("power_regulator.h"))
api = strip_cpp_comments(read_text("samovar_api.h"))

for forbidden in (".asInt()", ".asFloat()"):
    if forbidden in blynk:
        errors.append(f"Blynk.ino contains forbidden numeric conversion: {forbidden}")

handler_contracts = {
    "BLYNK_WRITE(V16)": [
        "control_power_input_max(",
        "parse_control_power(param.asStr(), maxPower, value)",
        "if (!result.ok())",
        "report_blynk_numeric_error(16, result);",
        "set_current_power(value);",
    ],
    "BLYNK_WRITE(V17)": [
        "parse_control_rate_steps(",
        "param.asStr()",
        "if (!result.ok())",
        "report_blynk_numeric_error(17, result);",
        "set_pump_speed(stepSpeed, true);",
    ],
    "BLYNK_WRITE(V12)": [
        "parse_exact_bool(param.asStr(), state)",
        "if (!result.ok())",
        "report_blynk_numeric_error(12, result);",
        "if (!PowerOn) return;",
        "if (state)",
        "queue_samovar_command(command)",
    ],
    "BLYNK_WRITE(V3)": [
        "parse_exact_bool(param.asStr(), value)",
        "if (!result.ok())",
        "report_blynk_numeric_error(3, result);",
        "if (value && PowerOn)",
        "menu_samovar_start();",
        "queue_samovar_reset_command()",
    ],
}

for signature, ordered in handler_contracts.items():
    body = function_body(blynk, signature)
    require_ordered_tokens(signature, body, ordered, errors)
    try:
        invalid_body, invalid_end = extract_braced_block_after(body, "if (!result.ok())")
    except ValueError as exc:
        errors.append(f"{signature}: {exc}")
        continue
    report_token = next(token for token in ordered if "report_blynk_numeric_error" in token)
    if report_token not in invalid_body:
        errors.append(f"{signature} invalid branch does not report the parse error")
    if "return;" not in invalid_body:
        errors.append(f"{signature} invalid branch does not return before side effects")
    side_effects = {
        "BLYNK_WRITE(V16)": ("set_current_power(",),
        "BLYNK_WRITE(V17)": ("set_pump_speed(",),
        "BLYNK_WRITE(V12)": ("queue_samovar_command(",),
        "BLYNK_WRITE(V3)": ("menu_samovar_start(", "queue_samovar_reset_command("),
    }[signature]
    for side_effect in side_effects:
        if side_effect in invalid_body:
            errors.append(f"{signature} invalid branch contains side effect: {side_effect}")
        side_effect_index = body.find(side_effect)
        if side_effect_index >= 0 and side_effect_index < invalid_end:
            errors.append(f"{signature} side effect occurs before invalid branch returns: {side_effect}")

if '#include "power_regulator_numeric_input.h"' not in power:
    errors.append("power_regulator.h does not include the protocol parser")
for forbidden in ("hexToDec(", ".toInt()"):
    if forbidden in power:
        errors.append(f"power_regulator.h contains forbidden parser: {forbidden}")
if "hexToDec(" in api:
    errors.append("samovar_api.h still declares hexToDec")

trigger_signature = "void triggerPowerStatus(void *parameter)"
first_trigger = power.find(trigger_signature)
second_trigger = power.find(trigger_signature, first_trigger + len(trigger_signature))
if first_trigger < 0 or second_trigger < 0:
    errors.append("power_regulator.h must keep both triggerPowerStatus feature branches")
    kvic_body = ""
    sem_body = ""
else:
    kvic_body = function_body(power[first_trigger:], trigger_signature)
    sem_body = function_body(power[second_trigger:], trigger_signature)

require_ordered_tokens(
    "KVIC response transaction",
    kvic_body,
    [
        "PowerRegulatorTelemetry parsed = {};",
        "parse_kvic_power_response(data.c_str(), parsed)",
        "if (result.ok())",
        "commit_kvic_power_response(parsed);",
    ],
    errors,
)
for token in ("current_power_volt =", "target_power_volt =", "last_reg_online ="):
    if token in kvic_body:
        errors.append(f"KVIC parser mutates telemetry outside commit helper: {token}")

for tokens in (
    [
        'sem_avr_print_samovar_command("+SS?\\r")',
        "parse_sem_power_mode_response(resp.c_str(), mode)",
        "if (result.ok()) commit_sem_power_mode_response(mode);",
    ],
    [
        'sem_avr_print_samovar_command("+VO?\\r")',
        "parse_sem_power_value_response(",
        "if (result.ok()) commit_sem_current_power_response(value);",
    ],
    [
        'sem_avr_print_samovar_command("+VS?\\r")',
        "parse_sem_power_value_response(",
        "if (result.ok()) commit_sem_target_power_response(value);",
    ],
):
    require_ordered_tokens("SEM response transaction", sem_body, tokens, errors)

for token in (
    "inline void commit_kvic_power_response",
    "inline void commit_sem_power_mode_response",
    "inline void commit_sem_current_power_response",
    "inline void commit_sem_target_power_response",
    "POWER_RESPONSE_ERROR_INTERVAL_MS",
):
    if token not in power:
        errors.append(f"power_regulator.h missing response contract token: {token}")

manifest_text = read_text("tools/static_analysis_sources.json")
try:
    manifest = json.loads(manifest_text)
except json.JSONDecodeError as exc:
    errors.append(f"static analysis manifest is invalid JSON: {exc}")
else:
    if "power_regulator_numeric_input.h" not in manifest.get("inventory", []):
        errors.append("static analysis manifest misses power_regulator_numeric_input.h")

if errors:
    print("Blynk/power numeric contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Blynk/power numeric contract smoke check passed")
