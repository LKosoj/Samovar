#!/usr/bin/env python3
import re
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


def require_token(name: str, text: str, token: str) -> None:
    if token not in text:
        errors.append(f"{name} missing token: {token}")


samovar = strip_cpp_comments(read_text("Samovar.ino"))
helpers = strip_cpp_comments(read_text("runtime_helpers.h"))
beer = strip_cpp_comments(read_text("beer.h"))

if samovar:
    require_token("Samovar.ino", samovar, "portMUX_TYPE waterPulseMux = portMUX_INITIALIZER_UNLOCKED;")
    try:
        body = extract_function_body(samovar, "void IRAM_ATTR WFpulseCounter")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if body:
        require_ordered_tokens(
            "WFpulseCounter protects shared counter in ISR context",
            body,
            [
                "portENTER_CRITICAL_ISR(&waterPulseMux);",
                "WFpulseCount++;",
                "portEXIT_CRITICAL_ISR(&waterPulseMux);",
            ],
            errors,
        )

    try:
        body = extract_function_body(samovar, "void triggerSysTicker")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if body:
        require_token("triggerSysTicker", body, "uint16_t waterPulses = water_pulse_count_take();")
        if re.search(r"\bWFpulseCount\s*=", body) or "WFpulseCount++" in body:
            errors.append("triggerSysTicker writes WFpulseCount directly")

    try:
        body = extract_function_body(samovar, "void recvMsg")
    except ValueError:
        body = ""
    if body:
        require_ordered_tokens(
            "WebSerial WFpulseCount access uses helpers",
            body,
            [
                'if (Var == "WFpulseCount")',
                "water_pulse_count_set((uint16_t)Val.toInt());",
                "WebSerial.println(water_pulse_count_get());",
            ],
            errors,
        )

if helpers:
    for signature, tokens in [
        (
            "inline void water_pulse_count_set",
            ["portENTER_CRITICAL(&waterPulseMux);", "WFpulseCount = value;", "portEXIT_CRITICAL(&waterPulseMux);"],
        ),
        (
            "inline uint16_t water_pulse_count_get",
            ["portENTER_CRITICAL(&waterPulseMux);", "uint16_t value = WFpulseCount;", "portEXIT_CRITICAL(&waterPulseMux);"],
        ),
        (
            "inline uint16_t water_pulse_count_take",
            ["portENTER_CRITICAL(&waterPulseMux);", "uint16_t value = WFpulseCount;", "WFpulseCount = 0;", "portEXIT_CRITICAL(&waterPulseMux);"],
        ),
    ]:
        try:
            body = extract_function_body(helpers, signature)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        require_ordered_tokens(signature, body, tokens, errors)

if beer:
    try:
        body = extract_function_body(beer, "void check_alarm_beer")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if body:
        require_token(
            "beer mash/boil finish uses fractional minutes",
            body,
            "(float)(millis() - begintime) / 60000.0f >= program[ProgramNum].Time",
        )
        if "/ 1000 / 60 >= program[ProgramNum].Time" in body:
            errors.append("beer pause finish condition still uses integer-minute division")

if errors:
    print("beer small fixes smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("beer small fixes smoke passed")
