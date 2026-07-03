#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def forbid_tokens(name: str, body: str, tokens: list[str]) -> None:
    for token in tokens:
        if token in body:
            errors.append(f"{name} contains forbidden token: {token}")


nbk_text = read_text("nbk.h")
alarm_text = read_text("alarm.h")
api_text = read_text("samovar_api.h")

if nbk_text:
    try:
        body = extract_function_body(nbk_text, "bool check_nbk_critical_alarms")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    for token in [
        "request_emergency_stop(\"Кончилась брага! Останов.\")",
        "request_emergency_stop(\"Недостаточное охлаждение! Останов.\")",
    ]:
        if token not in body:
            errors.append(f"NBK critical alarm missing emergency request: {token}")

    forbid_tokens(
        "check_nbk_critical_alarms",
        body,
        [
            "delay(",
            "SetSpeed(",
            "run_nbk_program(",
            "nbk_finish(",
            "set_power(",
            "set_current_power(",
            "nbk_M =",
            "nbk_P =",
        ],
    )

    try:
        body = extract_function_body(nbk_text, "void nbk_finish_common")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    for token in [
        "SetSpeed(0);",
        "stats.avgSpeed",
        "ProgramNum = 0;",
        "startval = 0;",
        "SamovarStatusInt = 0;",
        "stats.startTime = 0;",
        "stats.totalVolume = 0;",
    ]:
        if token not in body:
            errors.append(f"NBK finish common missing: {token}")
    forbid_tokens("nbk_finish_common", body, ["delay(", "set_power(", "run_nbk_program("])

    try:
        body = extract_function_body(nbk_text, "void nbk_emergency_finish")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "NBK emergency finish uses common cleanup and closes log",
        body,
        ["nbk_finish_common(true);", "nbk_close_data_log();"],
        errors,
    )
    forbid_tokens("nbk_emergency_finish", body, ["delay(", "set_power(", "run_nbk_program(", "nbk_finish("])

    try:
        body = extract_function_body(nbk_text, "void nbk_finish()")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "NBK normal finish keeps power-off wrapper",
        body,
        ["nbk_finish_common(false);", "delay(1000);", "set_power(false);", "reset_sensor_counter();", "nbk_close_data_log();"],
        errors,
    )

if alarm_text:
    try:
        body = extract_function_body(alarm_text, "void perform_emergency_stop")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "perform_emergency_stop calls NBK cleanup before generic hardware stop",
        body,
        [
            "if (Samovar_Mode == SAMOVAR_NBK_MODE) nbk_emergency_finish();",
            "if (PowerOn)",
            "set_power(false);",
            "set_stepper_target(0, 0, 0);",
        ],
        errors,
    )

if api_text and "void nbk_emergency_finish();" not in api_text:
    errors.append("samovar_api.h missing nbk_emergency_finish declaration")

if errors:
    print("NBK critical alarm smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("NBK critical alarm smoke check passed")
