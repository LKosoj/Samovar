#!/usr/bin/env python3
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


checks = [
    ("distiller.h", "void check_alarm_distiller", '" Воды"', '" ТСА"'),
    ("BK.h", "void check_alarm_bk", '" воды охлаждения"', '" ТСА"'),
]

for file_name, signature, water_token, acp_token in checks:
    text = strip_cpp_comments(read_text(file_name))
    if not text:
        continue
    try:
        body = extract_function_body(text, signature)
    except ValueError as exc:
        errors.append(str(exc))
        continue

    require_ordered_tokens(
        f"{file_name} reports simultaneous water and ACP overheat",
        body,
        [
            "String s = \"\";",
            "if (WaterSensor.avgTemp >= MAX_WATER_TEMP)",
            f"s = s + {water_token};",
            "if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP))",
            f"s = s + {acp_token};",
            "request_emergency_stop(\"Аварийное отключение! Превышена максимальная температура\" + s);",
        ],
        errors,
    )
    if "else if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP))" in body:
        errors.append(f"{file_name} still hides ACP overheat when water overheat is active")

    require_token(
        f"{file_name} uses common PWR_FACTOR-aware reduction helper",
        body,
        "mode_reduce_power_for_water_alarm_by_volts(",
    )
    if "target_power_volt - 5 * PWR_FACTOR" in body or "target_power_volt - 5" in body:
        errors.append(f"{file_name} contains raw power reduction instead of helper")

if errors:
    print("dist/BK small fixes smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("dist/BK small fixes smoke passed")
