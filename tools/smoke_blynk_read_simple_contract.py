#!/usr/bin/env python3
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


def extract_call_args(source: str, open_paren_index: int) -> tuple[str, int]:
    # Вытаскивает текст аргументов вызова макроса между круглыми скобками
    # (source[open_paren_index] это сама открывающая скобка), учитывая
    # вложенные скобки вида "(String)" и строковые литералы вида "Тек:".
    depth = 0
    in_string = False
    in_char = False
    escaped = False
    for index in range(open_paren_index, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if in_char:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_char = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "'":
            in_char = True
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_paren_index + 1:index], index + 1
    raise ValueError("macro call arguments are not closed")


def split_top_level_args(args_text: str) -> list[str]:
    # Делит аргументы макровызова по запятым ВЕРХНЕГО уровня, не заходя
    # внутрь вложенных скобок и строковых литералов.
    parts: list[str] = []
    depth = 0
    in_string = False
    in_char = False
    escaped = False
    current: list[str] = []
    for char in args_text:
        if in_string:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if in_char:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_char = False
            continue
        if char == '"':
            in_string = True
            current.append(char)
            continue
        if char == "'":
            in_char = True
            current.append(char)
            continue
        if char in "([{":
            depth += 1
            current.append(char)
            continue
        if char in ")]}":
            depth -= 1
            current.append(char)
            continue
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts]


blynk = strip_cpp_comments(read_text("Blynk.ino"))

MACRO_SIGNATURE = "BLYNK_READ_SIMPLE(pin, expr)"
MACRO_DEFINE = f"#define {MACRO_SIGNATURE}"

# (а) тело макроса, вытащенное из исходника, содержит guard в правильном порядке.
macro_body = ""
if blynk:
    define_count = blynk.count(MACRO_DEFINE)
    if define_count != 1:
        errors.append(
            f"expected exactly one '{MACRO_DEFINE}', found {define_count}")
    try:
        macro_body = extract_function_body(blynk, MACRO_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))

require_ordered_tokens(
    "BLYNK_READ_SIMPLE macro body",
    macro_body,
    [
        "static bool inReadHandler = false;",
        "if (inReadHandler) return;",
        "inReadHandler = true;",
        "Blynk.virtualWrite(pin, expr);",
        "inReadHandler = false;",
    ],
    errors,
)

# (б) ровно 14 вызовов макроса, набор пинов и конкретные выражения совпадают
# с ожидаемым (не больше и не меньше).
expected_calls = {
    "V1": "PipeSensor.avgTemp",
    "V25": "ACPSensor.avgTemp",
    "V2": "WthdrwlProgress",
    "V5": "bme_pressure",
    "V6": "WaterSensor.avgTemp",
    "V7": "TankSensor.avgTemp",
    "V8": "get_liquid_volume()",
    "V9": "ActualVolumePerHour",
    "V15": "ipst",
    "V19": "SAMOVAR_VERSION",
    "V20": "Samovar_Mode",
    "V23": "pressure_value",
    "V21": '"Тек:" + (String)current_power_volt + " Цель:" + (String)target_power_volt',
    "V16": "target_power_volt",
}

invocation_pins: list[str] = []
if blynk:
    try:
        _, search_from = extract_braced_block_after(blynk, MACRO_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        search_from = len(blynk)

    call_token = "BLYNK_READ_SIMPLE("
    while True:
        call_index = blynk.find(call_token, search_from)
        if call_index < 0:
            break
        open_paren = call_index + len(call_token) - 1
        try:
            args_text, after = extract_call_args(blynk, open_paren)
        except ValueError as exc:
            errors.append(f"BLYNK_READ_SIMPLE call at offset {call_index}: {exc}")
            break
        parts = split_top_level_args(args_text)
        if len(parts) != 2:
            errors.append(
                f"BLYNK_READ_SIMPLE call at offset {call_index} does not have exactly "
                f"2 arguments: {args_text!r}")
        else:
            pin, expr = parts
            invocation_pins.append(pin)
            if pin not in expected_calls:
                errors.append(f"BLYNK_READ_SIMPLE call uses unexpected pin: {pin}")
            elif expr != expected_calls[pin]:
                errors.append(
                    f"BLYNK_READ_SIMPLE({pin}, ...) expression mismatch: "
                    f"expected {expected_calls[pin]!r}, got {expr!r}")
        search_from = after

if len(invocation_pins) != 14:
    errors.append(
        f"expected exactly 14 BLYNK_READ_SIMPLE invocations, found {len(invocation_pins)}")
if len(set(invocation_pins)) != len(invocation_pins):
    errors.append("BLYNK_READ_SIMPLE invocations contain duplicate pins")
missing_pins = set(expected_calls) - set(invocation_pins)
if missing_pins:
    errors.append(f"BLYNK_READ_SIMPLE invocations missing pins: {sorted(missing_pins)}")
extra_pins = set(invocation_pins) - set(expected_calls)
if extra_pins:
    errors.append(f"BLYNK_READ_SIMPLE invocations have unexpected pins: {sorted(extra_pins)}")

# (в) V0/V10/V11/V14/V24 сохранили буквальную форму "BLYNK_READ(<pin>) {" и не
# попали под макрос - их нельзя сворачивать (см. комментарий у макроса).
for pin in ("V0", "V10", "V11", "V14", "V24"):
    literal_signature = f"BLYNK_READ({pin}) {{"
    if blynk and literal_signature not in blynk:
        errors.append(f"{pin} handler lost its literal signature: {literal_signature}")
    if blynk and f"BLYNK_READ_SIMPLE({pin}," in blynk:
        errors.append(f"{pin} handler must not be wrapped by BLYNK_READ_SIMPLE")

if errors:
    print("BLYNK_READ_SIMPLE contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("BLYNK_READ_SIMPLE contract smoke check passed")
