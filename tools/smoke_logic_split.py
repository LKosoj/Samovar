#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_ordered(name: str, text: str, tokens: list[str]) -> None:
    pos = -1
    for token in tokens:
        next_pos = text.find(token, pos + 1)
        if next_pos == -1:
            errors.append(f"{name} missing ordered token: {token}")
            return
        pos = next_pos


def count_defs(text: str, name: str) -> int:
    return len(re.findall(rf"^\s*(?:inline\s+)?(?:bool|void|float|unsigned int)\s+{re.escape(name)}\s*\(", text, re.MULTILINE))


logic = strip_cpp_comments(read_text("logic.h"))
headers = {
    "alarm.h": strip_cpp_comments(read_text("alarm.h")),
    "valve_buzzer.h": strip_cpp_comments(read_text("valve_buzzer.h")),
    "power_regulator.h": strip_cpp_comments(read_text("power_regulator.h")),
    "selftest.h": strip_cpp_comments(read_text("selftest.h")),
}

require_ordered(
    "logic.h split include order",
    logic,
    [
        '#include "impurity_detector.h"',
        '#include "alarm.h"',
        '#include "valve_buzzer.h"',
        '#include "power_regulator.h"',
        '#include "selftest.h"',
    ],
)

moved_functions = {
    "alarm.h": [
        "samovar_process_active",
        "sensor_configured",
        "sensor_reading_valid",
        "sensor_valid",
        "optional_sensor_failed",
        "sensor_temp_at_least",
        "request_emergency_stop",
        "perform_emergency_stop",
        "process_sensor_failed",
        "set_alarm",
        "check_alarm",
    ],
    "valve_buzzer.h": ["open_valve", "process_buzzer", "set_buzzer"],
    "power_regulator.h": [
        "set_power",
        "clear_serial_in_buff",
        "triggerPowerStatus",
        "check_power_error",
        "get_current_power",
        "set_current_power",
        "set_power_mode",
        "hexToDec",
    ],
    "selftest.h": ["start_self_test", "stop_self_test"],
}

for file_name, functions in moved_functions.items():
    text = headers.get(file_name, "")
    for name in functions:
        expected = 2 if name == "triggerPowerStatus" else 1
        actual = count_defs(text, name)
        if actual != expected:
            errors.append(f"{file_name} expected {expected} definition(s) of {name}, found {actual}")
        if count_defs(logic, name) != 0:
            errors.append(f"logic.h still defines moved function: {name}")

for file_name, text in headers.items():
    if "#pragma once" not in text:
        errors.append(f"{file_name} missing #pragma once")

if errors:
    print("logic.h split smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("logic.h split smoke check passed")
