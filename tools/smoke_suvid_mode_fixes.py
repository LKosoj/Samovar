#!/usr/bin/env python3
"""Пины трёх фиксов режима Сувид (22.07.2026).

1. get_lua_mode_name знает режим SUVID (lua.h) и дефолт LUA_SUVID объявлен (Samovar.h).
2. tick_status_fsm даёт Сувиду собственный статус ДО ветки «Разгон колонны»
   и не присваивает SamovarStatusInt (Сувид живёт со статусом 0).
3. Общий хелпер перегрева mode_request_overheat_emergency_if_needed вызывается
   из beer_check_cooling_limits и check_alarm_suvid (пины distiller/BK — в
   smoke_dist_bk_small_fixes.py, тело хелпера — там же).
"""
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


samovar_text = read_text("Samovar.h")
if samovar_text and "#ifndef LUA_SUVID" not in samovar_text:
    errors.append("Samovar.h missing LUA_SUVID default define")

lua_text = strip_cpp_comments(read_text("lua.h"))
if lua_text:
    try:
        body = extract_function_body(lua_text, "String get_lua_mode_name")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "get_lua_mode_name resolves SUVID script before rect fallback",
        body,
        [
            "Samovar_CR_Mode == SAMOVAR_SUVID_MODE",
            "fl = \"/suvid\" + String(LUA_SUVID) + \".lua\";",
            "fl = \"suvid\";",
            "fl = \"/rectificat\" + String(LUA_RECT) + \".lua\";",
        ],
        errors,
    )

logic_text = strip_cpp_comments(read_text("logic.h"))
if logic_text:
    try:
        body = extract_function_body(logic_text, "String tick_status_fsm")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "suvid status branch precedes rect accel branch",
        body,
        [
            "else if (PowerOn && Samovar_Mode == SAMOVAR_SUVID_MODE) {",
            "suvid_target_temp()",
            "\" (Нагрев)\"",
            "\" (Термостатирование)\"",
            "F(\"Разгон колонны\")",
        ],
        errors,
    )

    if body:
        try:
            suvid_branch, _ = extract_braced_block_after(
                body, "else if (PowerOn && Samovar_Mode == SAMOVAR_SUVID_MODE) {"
            )
        except ValueError as exc:
            errors.append(str(exc))
            suvid_branch = ""
        if "SamovarStatusInt =" in suvid_branch:
            errors.append("suvid status branch must not assign SamovarStatusInt (suvid runs with status 0)")

beer_text = strip_cpp_comments(read_text("beer.h"))
if beer_text:
    try:
        body = extract_function_body(beer_text, "inline void beer_check_cooling_limits")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "beer cooling limits gate by stage then delegate to common overheat helper",
        body,
        [
            "if (current_program_type() != 'C') return;",
            "mode_request_overheat_emergency_if_needed();",
        ],
        errors,
    )

suvid_text = strip_cpp_comments(read_text("suvid.h"))
if suvid_text:
    try:
        body = extract_function_body(suvid_text, "inline float suvid_target_temp")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if body and "SamSetup.SuvidTemp > 0 ? SamSetup.SuvidTemp : 60.0f" not in body:
        errors.append("suvid_target_temp lost the 0-sentinel default of 60")

    try:
        body = extract_function_body(suvid_text, "inline void check_alarm_suvid")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "suvid alarm delegates overheat to common helper before thermostat",
        body,
        [
            "mode_request_overheat_emergency_if_needed();",
            "mode_request_water_flow_emergency_if_needed();",
            "const float setpoint = suvid_target_temp();",
        ],
        errors,
    )
    require_ordered_tokens(
        "suvid thermostat resets its state cold and mirrors heater_state",
        body,
        [
            "if (!PowerOn) {",
            "suvidHeaterOn = false;",
            "heater_state = false;",
            "return;",
            "heater_state = suvidHeaterOn;",
            "setHeaterPosition(suvidHeaterOn);",
        ],
        errors,
    )

if errors:
    print("suvid mode fixes smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("suvid mode fixes smoke passed")
