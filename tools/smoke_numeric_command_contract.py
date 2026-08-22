#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"missing {name}")
        return ""
    return strip_cpp_comments(path.read_text(encoding="utf-8", errors="ignore"))


web = read("WebServer.ino")
samovar = read("Samovar.ino")

try:
    action_body = extract_function_body(web, "static bool get_web_command_action")
    command_body = extract_function_body(web, "void web_command")
    loop_body = extract_function_body(samovar, "void loop()")
    # P8: вода/скорость насоса/pnbk вынесены из loop() в отдельные tick_* функции
    # (Samovar.ino). Тела подставляются в loop_body_with_pending в ТОМ ЖЕ порядке,
    # в котором loop() их реально вызывает (ищем позицию каждого call-сайта), чтобы
    # перестановка вызовов в loop() по-прежнему ломала проверку порядка токенов ниже.
    pending_tick_functions = [
        ("tick_apply_pending_water_temp", "static void tick_apply_pending_water_temp()"),
        ("tick_apply_pending_pump_speed", "static void tick_apply_pending_pump_speed()"),
        ("tick_apply_pending_pnbk", "static void tick_apply_pending_pnbk()"),
    ]
    call_positions = []
    for call_name, signature in pending_tick_functions:
        call_index = loop_body.find(call_name + "();")
        if call_index < 0:
            raise ValueError(f"loop() does not call {call_name}()")
        call_positions.append((call_index, signature))
    call_positions.sort(key=lambda item: item[0])
    loop_body_with_pending = loop_body
    for _, signature in call_positions:
        loop_body_with_pending += extract_function_body(samovar, signature)
except ValueError as exc:
    errors.append(str(exc))
    action_body = command_body = loop_body = ""
    loop_body_with_pending = ""

require_ordered_tokens(
    "exactly one POST action",
    action_body,
    [
        "request->params() != 1",
        "request->getParam(0)",
        "!param->isPost()",
        "param->isFile()",
        "name.toLowerCase()",
        "!web_command_name_allowed(name)",
    ],
    errors,
)
require_ordered_tokens(
    "parse before throttle and side effect",
    command_body,
    [
        "get_web_command_action(request, action, actionParam)",
        "parse_exact_bool(actionParam->value().c_str(), boolValue)",
        "parse_control_water_pwm(actionParam->value().c_str(), waterPwm)",
        "parse_control_rate_steps(",
        "parse_control_nbk(",
        "parse_control_power(actionParam->value().c_str(), maxValue, voltage)",
        "if (!parseResult.ok())",
        'send_web_command_response(request, 400, "BAD_REQUEST")',
        "String commandKey = action;",
        "commandKey == last_command_key",
        "if (action == \"start\")",
    ],
    errors,
)
for token in [
    "queue_pending_value(pending_mixer_flag, pending_mixer_on, boolValue)",
    "queue_pending_nbk(nbkCommand)",
    "queue_pending_value(pending_water_temp_flag, pending_water_temp_value, waterPwm)",
    "queue_pending_value(pending_pump_speed_flag, pending_pump_speed_steps, pumpSpeedSteps)",
    "queue_pending_value(pending_voltage_flag, pending_voltage_value, voltage)",
]:
    if token not in command_body:
        errors.append(f"typed command queue missing: {token}")

for token in [".toInt()", ".toFloat()", "parseLongSafe", "parseFloatSafe"]:
    if token in command_body:
        errors.append(f"web_command contains unsafe conversion: {token}")
for token in ["set_current_power(", "set_mixer(", "set_water_temp(", "set_pump_speed(", "set_stepper_target("]:
    if token in command_body:
        errors.append(f"web_command performs direct side effect: {token}")

require_ordered_tokens(
    "typed pending command consumption",
    loop_body_with_pending,
    [
        "take_pending_value(pending_water_temp_flag, pending_water_temp_value, waterTemp)",
        "set_water_temp(waterTemp);",
        "take_pending_value(pending_pump_speed_flag, pending_pump_speed_steps, pumpSpeedSteps)",
        "set_pump_speed(pumpSpeedSteps, true);",
        "pnbk = pending_pnbk_value;",
        "pnbk.kind == CONTROL_NBK_INCREMENT",
        "pnbk.kind == CONTROL_NBK_DECREMENT",
        "pnbk.kind == CONTROL_NBK_ABSOLUTE",
        "set_stepper_target(pnbk.stepSpeed",
        "pnbk.kind == CONTROL_NBK_STOP",
    ],
    errors,
)
for token in ["pending_pump_speed_rate", "float pnbk", "i2c_get_speed_from_rate(pnbk"]:
    if token in samovar:
        errors.append(f"Samovar.ino retains raw pending command state: {token}")

if errors:
    print("Numeric command contract smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Numeric command contract smoke passed")
