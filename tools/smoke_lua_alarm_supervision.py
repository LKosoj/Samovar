#!/usr/bin/env python3
"""[P8] Static checks for Lua alarm supervision (check_alarm_lua).

Pins:
- lua.h::check_alarm_lua treats water/ACP/tank sensors as OPTIONAL (Lua scripts
  decide which sensors they need) and calls the three mode_common.h helpers.
- mode_registry.h's LUA row wires the alarm slot to SAMOVAR_LUA_ALARM_FN, not nullptr.
- samovar_api.h defines SAMOVAR_LUA_ALARM_FN in both the USE_LUA and non-USE_LUA branches.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, body: str, token: str) -> None:
    if token not in body:
        errors.append(f"{name} missing token: {token}")


def forbid_token(name: str, body: str, token: str) -> None:
    if token in body:
        errors.append(f"{name} contains forbidden token: {token}")


lua = strip_cpp_comments(read_text("lua.h"))
mode_registry = strip_cpp_comments(read_text("mode_registry.h"))
api = strip_cpp_comments(read_text("samovar_api.h"))

# --- lua.h::check_alarm_lua body checks -------------------------------------------------
if lua:
    try:
        check_alarm_lua = extract_function_body(lua, "inline void check_alarm_lua()")
    except ValueError as exc:
        errors.append(str(exc))
        check_alarm_lua = ""

    if check_alarm_lua:
        require_ordered_tokens(
            "check_alarm_lua",
            check_alarm_lua,
            [
                "mode_clear_alarm_pause_if_expired();",
                "if (PowerOn)",
                'optional_sensor_failed(WaterSensor) && process_sensor_failed("Lua", "воды")',
                'optional_sensor_failed(ACPSensor) && process_sensor_failed("Lua", "ТСА")',
                'optional_sensor_failed(TankSensor) && process_sensor_failed("Lua", "куба")',
                "mode_request_overheat_emergency_if_needed();",
                "mode_request_water_flow_emergency_if_needed();",
            ],
            errors,
        )
        # ALL three sensors must be optional - Lua scripts decide which sensors they need.
        # A hard sensor_valid(...) requirement on any of them would stall the mode whenever
        # a script that doesn't use that sensor runs on hardware without it wired up.
        forbid_token("check_alarm_lua", check_alarm_lua, "sensor_valid(WaterSensor)")
        forbid_token("check_alarm_lua", check_alarm_lua, "sensor_valid(ACPSensor)")
        forbid_token("check_alarm_lua", check_alarm_lua, "sensor_valid(TankSensor)")
        require_token(
            "check_alarm_lua",
            check_alarm_lua,
            "#ifdef SAMOVAR_USE_POWER",
        )
        require_token("check_alarm_lua", check_alarm_lua, "check_power_error();")

# --- mode_registry.h LUA row --------------------------------------------------------------
if mode_registry:
    lua_row_token = '{SAMOVAR_LUA_MODE,'
    row_start = mode_registry.find(lua_row_token)
    if row_start < 0:
        errors.append("mode_registry.h: SAMOVAR_LUA_MODE row not found")
    else:
        row_end = mode_registry.find("},", row_start)
        row = mode_registry[row_start:row_end + 1]
        require_token("mode_registry.h LUA row", row, "SAMOVAR_LUA_ALARM_FN")
        fields = [f.strip() for f in row.strip("{}").rstrip(",").split(",")]
        if len(fields) != 10:
            errors.append(
                f"mode_registry.h LUA row: expected 10 fields, found {len(fields)}: {row}"
            )
        else:
            # Field 8 (index 7, 0-based) is `alarm`.
            if fields[7] != "SAMOVAR_LUA_ALARM_FN":
                errors.append(
                    f"mode_registry.h LUA row: alarm field must be SAMOVAR_LUA_ALARM_FN, got {fields[7]}"
                )
            # finish/status (fields 9-10) must be left untouched (nullptr).
            if fields[8] != "nullptr" or fields[9] != "nullptr":
                errors.append(
                    "mode_registry.h LUA row: finish/status fields must remain nullptr "
                    f"(got finish={fields[8]!r}, status={fields[9]!r})"
                )

# --- samovar_api.h macro definitions -------------------------------------------------------
if api:
    require_token("samovar_api.h", api, "#define SAMOVAR_LUA_ALARM_FN check_alarm_lua")
    require_token("samovar_api.h", api, "#define SAMOVAR_LUA_ALARM_FN nullptr")
    require_token("samovar_api.h", api, "inline void check_alarm_lua();")
    require_token("samovar_api.h", api, "inline void mode_clear_alarm_pause_if_expired();")
    require_token(
        "samovar_api.h", api, "inline void mode_request_overheat_emergency_if_needed();"
    )
    # mode_request_water_flow_emergency_if_needed already has an unconditional forward
    # declaration elsewhere in this file - it must NOT be duplicated inside the USE_LUA block.
    if api.count("inline void mode_request_water_flow_emergency_if_needed();") != 1:
        errors.append(
            "samovar_api.h: mode_request_water_flow_emergency_if_needed forward declaration "
            "must appear exactly once (must not be duplicated for USE_LUA)"
        )
    # Both #define branches for the macro must exist under proper guards.
    define_lua = api.find("#define SAMOVAR_LUA_ALARM_FN check_alarm_lua")
    define_else = api.find("#define SAMOVAR_LUA_ALARM_FN nullptr")
    guard_ifdef = api.rfind("#ifdef USE_LUA", 0, define_lua) if define_lua >= 0 else -1
    guard_else = api.find("#else", define_lua) if define_lua >= 0 else -1
    if not (
        define_lua >= 0
        and define_else >= 0
        and guard_ifdef >= 0
        and guard_ifdef < define_lua < guard_else < define_else
    ):
        errors.append(
            "samovar_api.h: SAMOVAR_LUA_ALARM_FN must be defined in both the #ifdef USE_LUA "
            "branch (check_alarm_lua) and the #else branch (nullptr)"
        )

if errors:
    for err in errors:
        print(f"FAIL: {err}")
    sys.exit(1)

print("Lua alarm supervision smoke check passed")
sys.exit(0)
