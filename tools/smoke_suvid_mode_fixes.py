#!/usr/bin/env python3
"""Пины трёх фиксов режима Сувид (22.07.2026).

1. get_lua_mode_name знает режим SUVID (lua.h) и дефолт LUA_SUVID объявлен (Samovar.h).
2. tick_status_fsm даёт Сувиду собственный статус ДО ветки «Разгон колонны»
   и не присваивает SamovarStatusInt (Сувид живёт со статусом 0).
3. Общий хелпер перегрева mode_request_overheat_emergency_if_needed вызывается
   из beer_check_cooling_limits и check_alarm_suvid (пины distiller/BK — в
   smoke_dist_bk_small_fixes.py, тело хелпера — там же).

Плюс П6 (22.07.2026): вода/ТСА в Сувиде опциональны (optional_sensor_failed),
куб обязателен (sensor_valid), общий mode_check_powered_cooling_sensors (жёсткая
проверка воды) в теле check_alarm_suvid больше не вызывается; и кламп уставки
SuvidTemp в WebServer.ino снижен со 150 до 100°.
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
            "if (current_program_type() != 'C' && current_program_type() != 'F') return;",
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
            "suvidHold = {false, false, 0};",
            "return;",
            "heater_state = suvidHeaterOn;",
            "setHeaterPosition(suvidHeaterOn);",
        ],
        errors,
    )

    require_ordered_tokens(
        "suvid sensor guard: water/ACP optional, tank mandatory",
        body,
        [
            "optional_sensor_failed(WaterSensor)",
            "process_sensor_failed(\"Сувид\", \"воды\")",
            "optional_sensor_failed(ACPSensor)",
            "process_sensor_failed(\"Сувид\", \"ТСА\")",
            "sensor_valid(TankSensor)",
            "process_sensor_failed(\"Сувид\", \"куба\")",
        ],
        errors,
    )
    if "mode_check_powered_cooling_sensors" in body:
        errors.append(
            "check_alarm_suvid must not call mode_check_powered_cooling_sensors "
            "(that helper treats water as mandatory; Сувид needs it optional)"
        )

webserver_text = strip_cpp_comments(read_text("WebServer.ino"))
if webserver_text:
    try:
        handle_save_body = extract_function_body(webserver_text, "void handleSave")
    except ValueError as exc:
        errors.append(str(exc))
        handle_save_body = ""
    if handle_save_body:
        suvid_clamp_marker = 'apply_save_float_arg(request, "SuvidTemp"'
        idx = handle_save_body.find(suvid_clamp_marker)
        if idx < 0:
            errors.append("handleSave lost the SuvidTemp save clamp call")
        else:
            line_end = handle_save_body.find(";", idx)
            suvid_clamp_line = handle_save_body[idx:line_end if line_end >= 0 else idx + 120]
            if "0.0f" not in suvid_clamp_line:
                errors.append("SuvidTemp clamp lost its 0.0f lower bound")
            if "100.0f" not in suvid_clamp_line:
                errors.append("SuvidTemp clamp must cap at 100.0f (setpoint can't exceed 100°)")
            if "150.0f" in suvid_clamp_line:
                errors.append("SuvidTemp clamp still allows the old 150.0f upper bound")

if errors:
    print("suvid mode fixes smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("suvid mode fixes smoke passed")
