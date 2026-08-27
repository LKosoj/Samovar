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


beer = read_text("data_raw/beer.lua")
rectificat = read_text("data_raw/rectificat.lua")
dist_autofill = read_text("Lua_script/dist_autofill.lua")
pump_speed_script = read_text("Lua_script/beer (Управление скоростью насоса воды).lua")

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


for script_name, script in [
    ("rectificat.lua", rectificat),
    ("dist_autofill.lua", dist_autofill),
]:
    if not script:
        continue
    require_token(
        f"{script_name} reads physical pump state",
        script,
        'getNumVariable("pump_started") + 0',
    )
    require_order(
        f"{script_name} starts pump through confirmed actuator API",
        script,
        [
            "local function startPump()",
            "setPumpPwm(1023)",
            "ACTUATOR_COMMAND_APPLIED",
            "return false",
            "return true",
        ],
    )
    require_order(
        f"{script_name} stops pump through confirmed actuator API",
        script,
        [
            "local function stopPump()",
            "setPumpPwm(0)",
            "ACTUATOR_COMMAND_APPLIED",
            "return false",
            "return true",
        ],
    )
    require_order(
        f"{script_name} does not publish filling success after failed pump stop",
        script,
        [
            "local function stopFilling",
            "if not stopPump() then return false end",
            'setLuaStatus("Куб заполнен")',
            'setObject("tank_filled", "true")',
            "return true",
        ],
    )
    require_order(
        f"{script_name} does not continue after failed pump start",
        script,
        [
            'setLuaStatus("Заполнение куба")',
            "if not startPump() then return false end",
        ],
    )
    if script_name == "rectificat.lua":
        require_order(
            "rectificat.lua republishes filling status if pump already runs",
            script,
            [
                "if use_level_sensor and check4level() then",
                "stopFilling()",
                "if use_flow_sensor then",
                'setLuaStatus("Заполнение куба")',
            ],
        )
        require_order(
            "rectificat.lua stops pump on SetScriptOff inside the cycle script",
            script,
            [
                'getNumVariable("SetScriptOff") + 0 == 1',
                "stopPump()",
                'setLuaStatus("Скрипт остановлен")',
                "fillTank()",
            ],
        )
    for forbidden in [
        'getObject("pump_started")',
        'setObject("pump_started"',
        "pinMode(4",
        "digitalWrite(4",
    ]:
        if forbidden in script:
            errors.append(f"{script_name} retains forbidden pump bypass: {forbidden}")


def preserves_pump_failure_status_contract(script: str) -> bool:
    return all(
        token in script
        for token in [
            "if not stopPump() then return false end",
            'setLuaStatus("Куб заполнен")',
            'setObject("tank_filled", "true")',
        ]
    ) and script.find("if not stopPump() then return false end") < script.find(
        'setLuaStatus("Куб заполнен")'
    )


for script_name, script in [
    ("rectificat.lua", rectificat),
    ("dist_autofill.lua", dist_autofill),
]:
    mutant = script.replace("if not stopPump() then return false end", "if false then return false end", 1)
    if preserves_pump_failure_status_contract(mutant):
        errors.append(f"{script_name} pump-stop status mutation survived")
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


if pump_speed_script:
    require_order(
        "pump speed script confirms start before clearing request",
        pump_speed_script,
        [
            "if pump_start == 1 and pump_started == 0 then",
            "local result = setPumpPwm(1023)",
            "if result ~= ACTUATOR_COMMAND_APPLIED then",
            'setLuaStatus("Ошибка включения насоса; запрос сохранён для повтора")',
            "else",
            'setObject("pump_start", 0)',
            'sendMsg("Насос включен", 2)',
        ],
    )
    require_order(
        "pump speed script confirms speed change before clearing request",
        pump_speed_script,
        [
            "local function applyPumpSpeed",
            "local result = setPumpPwm(target_speed)",
            "if result ~= ACTUATOR_COMMAND_APPLIED then",
            'setLuaStatus("Ошибка изменения скорости насоса; запрос сохранён для повтора")',
            "return false",
            'setObject(request_name, 0)',
            'setLuaStatus(" Скорость насоса "..target_speed.."/1023")',
            "return true",
        ],
    )


def preserves_pump_start_confirmation(script: str) -> bool:
    required = [
        "local result = setPumpPwm(1023)",
        "if result ~= ACTUATOR_COMMAND_APPLIED then",
        'setObject("pump_start", 0)',
    ]
    return all(token in script for token in required) and (
        script.find(required[0]) < script.find(required[1]) < script.find(required[2])
    )


def preserves_pump_speed_confirmation(script: str) -> bool:
    required = [
        "local result = setPumpPwm(target_speed)",
        "if result ~= ACTUATOR_COMMAND_APPLIED then",
        'setObject(request_name, 0)',
        'setLuaStatus(" Скорость насоса "..target_speed.."/1023")',
    ]
    return all(token in script for token in required) and (
        script.find(required[0]) < script.find(required[1]) < script.find(required[2]) < script.find(required[3])
    )


for label, contract, old, new in [
    (
        "pump start confirmation",
        preserves_pump_start_confirmation,
        "local result = setPumpPwm(1023)\n  if result ~= ACTUATOR_COMMAND_APPLIED then",
        "local result = setPumpPwm(1023)\n  if result == ACTUATOR_COMMAND_APPLIED then",
    ),
    (
        "pump speed confirmation",
        preserves_pump_speed_confirmation,
        "local result = setPumpPwm(target_speed)",
        "setObject(request_name, 0)\n  local result = setPumpPwm(target_speed)",
    ),
]:
    mutant = pump_speed_script.replace(old, new, 1)
    if contract(mutant):
        errors.append(f"{label} mutation survived")

if errors:
    print("Lua scripts smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Lua scripts smoke passed")
