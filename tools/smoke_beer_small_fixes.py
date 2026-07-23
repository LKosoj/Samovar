#!/usr/bin/env python3
import re
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
                'static const char prefix[] = "WFpulseCount=";',
                "parse_bounded_uint16(valueText, 0, UINT16_MAX, value)",
                "if (!result.ok())",
                "water_pulse_count_set(value);",
                "WebSerial.println(water_pulse_count_get());",
            ],
            errors,
        )
        for forbidden in ["String d", ".toInt()", "getValue("]:
            if forbidden in body:
                errors.append(f"WebSerial recvMsg contains unsafe parser token: {forbidden}")

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
        body = extract_function_body(beer, "void beer_stage_tick")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if body:
        require_token(
            "beer mash/boil finish uses fractional minutes and subtracts idle time",
            body,
            "(float)(millis() - begintime - beerStageIdleAccumMs) / 60000.0f >= program[ProgramNum].Time",
        )
        if "/ 1000 / 60 >= program[ProgramNum].Time" in body:
            errors.append("beer pause finish condition still uses integer-minute division")

        require_token(
            "beer M/P/F hysteresis uses own constant, not the sensor's SetTemp",
            body,
            "tempDelta = BEER_TEMP_HYSTERESIS;",
        )
        if "tempDelta = controlSensor->SetTemp;" in body:
            errors.append("beer hysteresis still borrows controlSensor->SetTemp")

        try:
            autotune_block, _ = extract_braced_block_after(body, "if (currentType == 'A') {")
        except ValueError as exc:
            errors.append(str(exc))
            autotune_block = ""
        if autotune_block:
            require_token(
                "beer autotune retries instead of emergency-stopping the whole process",
                autotune_block,
                "queue_samovar_command(SAMOVAR_BEER_NEXT)",
            )
            if "request_emergency_stop" in autotune_block:
                errors.append("beer autotune completion still escalates to request_emergency_stop")

        try:
            boil_block, _ = extract_braced_block_after(body, "if (currentType == 'B') {")
        except ValueError as exc:
            errors.append(str(exc))
            boil_block = ""
        if boil_block:
            require_ordered_tokens(
                "hop reminder fires only when the next row continues boiling",
                boil_block,
                ["program_type_at(ProgramNum + 1) == 'B'", "HopStepperStep();"],
                errors,
            )

            require_token(
                "beer boiling relay-only path scales heater duty by SamSetup.BVolt",
                boil_block,
                "set_heater(constrain(SamSetup.BVolt, 0.0f, 100.0f) / 100.0);",
            )
            if "heater_enable_outputs(SAFETY_HEATER_OUTPUT_MAIN)" in boil_block:
                errors.append(
                    "beer boiling relay-only path still enables heater at fixed 100% instead of BVolt duty cycle"
                )

if errors:
    print("beer small fixes smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("beer small fixes smoke passed")
