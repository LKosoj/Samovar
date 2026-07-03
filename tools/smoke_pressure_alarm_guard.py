#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


samovar_text = read_text("Samovar.ino")

if samovar_text:
    try:
        ticker_body = extract_function_body(samovar_text, "void triggerSysTicker(void *parameter)")
    except ValueError as exc:
        errors.append(str(exc))
        ticker_body = ""

    if ticker_body:
        for token in [
            "bool pressure_alarm_sent = false;",
            "SamSetup.MaxPressureValue > 0 && pressure_value >= SamSetup.MaxPressureValue",
            "if (!pressure_alarm_sent)",
            "request_emergency_stop(\"Превышено предельное давление!\")",
            "pressure_alarm_sent = true;",
            "float pressure_hysteresis = SamSetup.MaxPressureValue * 0.05f;",
            "if (pressure_hysteresis < 5.0f) pressure_hysteresis = 5.0f;",
            "pressure_value < SamSetup.MaxPressureValue - pressure_hysteresis",
            "pressure_alarm_sent = false;",
        ]:
            if token not in ticker_body:
                errors.append(f"pressure guard contract missing: {token}")

        require_ordered_tokens(
            "pressure alarm guard and hysteresis order",
            ticker_body,
            [
                "bool pressure_alarm_sent = false;",
                "SamSetup.MaxPressureValue > 0 && pressure_value >= SamSetup.MaxPressureValue",
                "if (!pressure_alarm_sent)",
                "request_emergency_stop(\"Превышено предельное давление!\")",
                "pressure_alarm_sent = true;",
                "} else if (pressure_alarm_sent) {",
                "float pressure_hysteresis = SamSetup.MaxPressureValue * 0.05f;",
                "if (pressure_hysteresis < 5.0f) pressure_hysteresis = 5.0f;",
                "pressure_value < SamSetup.MaxPressureValue - pressure_hysteresis",
                "pressure_alarm_sent = false;",
            ],
            errors,
        )

        pressure_request = "request_emergency_stop(\"Превышено предельное давление!\")"
        if ticker_body.count(pressure_request) != 1:
            errors.append("pressure emergency request must appear exactly once in triggerSysTicker")
        if "!pressure_alarm_sent || !alarm_event" in ticker_body:
            errors.append("pressure guard still depends on global alarm_event")
        try:
            pressure_body, pressure_end = extract_braced_block_after(
                ticker_body,
                "if (SamSetup.MaxPressureValue > 0 && pressure_value >= SamSetup.MaxPressureValue)",
            )
            guard_body, _ = extract_braced_block_after(pressure_body, "if (!pressure_alarm_sent)")
            reset_body, _ = extract_braced_block_after(ticker_body, "else if (pressure_alarm_sent)", pressure_end)
            for token in [
                "request_emergency_stop(\"Превышено предельное давление!\")",
                "pressure_alarm_sent = true;",
            ]:
                if token not in guard_body:
                    errors.append(f"pressure one-shot guard branch missing: {token}")
            for token in ["set_alarm(", "SendMsg(", "!alarm_event", "pressure_alarm_sent = false;"]:
                if token in guard_body:
                    errors.append(f"pressure one-shot guard branch contains forbidden token: {token}")
            for token in [
                "float pressure_hysteresis = SamSetup.MaxPressureValue * 0.05f;",
                "if (pressure_hysteresis < 5.0f) pressure_hysteresis = 5.0f;",
                "pressure_value < SamSetup.MaxPressureValue - pressure_hysteresis",
                "pressure_alarm_sent = false;",
            ]:
                if token not in reset_body:
                    errors.append(f"pressure hysteresis reset branch missing: {token}")
            for token in ["request_emergency_stop(", "set_alarm(", "SendMsg("]:
                if token in reset_body:
                    errors.append(f"pressure hysteresis reset branch contains forbidden token: {token}")
        except ValueError as exc:
            errors.append(str(exc))

if errors:
    print("Pressure alarm guard smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("Pressure alarm guard smoke check passed")
