#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, text: str, token: str) -> None:
    if token not in text:
        errors.append(f"{name} missing token: {token}")


def require_order(name: str, text: str, tokens: list[str]) -> None:
    offset = 0
    for token in tokens:
        index = text.find(token, offset)
        if index < 0:
            errors.append(f"{name} missing ordered token: {token}")
            return
        offset = index + len(token)


beer = read_text("data/beer.lua")
rectificat = read_text("data/rectificat.lua")

if beer:
    require_order(
        "beer.lua status is built before publishing",
        beer,
        [
            'ValveStatus = getNumVariable("valve_status") + 0',
            'status = string.format("ACPT = %.2f; TankT = %.2f; WaterTemp = %.2f; Клапан %.0f"',
            "setLuaStatus(status)",
        ],
    )
    if re.search(r"setLuaStatus\s*\(\s*status\s*\).*?status\s*=", beer, flags=re.S):
        errors.append("beer.lua publishes status before assigning it")

if rectificat:
    if "getNumVariable(WFflowRate)" in rectificat:
        errors.append("rectificat.lua still reads WFflowRate as nil/global variable")
    require_token("rectificat.lua flow rate read", rectificat, 'getNumVariable("WFflowRate") + 0')
    require_order(
        "rectificat.lua check4volume integrates flow readings",
        rectificat,
        [
            "local function check4volume()",
            'local current_rate = getNumVariable("WFflowRate") + 0',
            "local elapsed_min = (now - last_reading_time) / 60000.0",
            "local avg_rate = (last_reading_flow + current_rate) / 2.0",
            "total_volume = total_volume + avg_rate * elapsed_min * flow_factor",
            'setObject("last_reading_time", last_reading_time)',
            'setObject("last_reading_flow", last_reading_flow)',
            'setObject("total_volume", total_volume)',
            'setLuaStatus(string.format("Заполнение куба: %.2f / %.2f л", total_volume, target_volume))',
            "return total_volume >= target_volume",
        ],
    )
    require_order(
        "rectificat.lua validates flow configuration before run",
        rectificat,
        [
            "local function verifyVolumeTargets",
            'type(target_volume) ~= "number"',
            "target_volume <= 0",
            'type(flow_factor) ~= "number"',
            "flow_factor <= 0",
            "use_flow_sensor = false",
            "verifyVolumeTargets()",
            "if not use_level_sensor and not use_flow_sensor then",
        ],
    )

if errors:
    print("Lua scripts smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Lua scripts smoke passed")
