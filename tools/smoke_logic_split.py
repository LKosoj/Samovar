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


def count_defs(text: str, name: str, return_type: str) -> int:
    return len(re.findall(
        rf"^\s*(?:inline\s+)?{re.escape(return_type)}\s+{re.escape(name)}\s*\(",
        text,
        re.MULTILINE,
    ))


def count_moved_defs(text: str, name: str) -> int:
    return len(re.findall(
        rf"^\s*(?:inline\s+)?(?:bool|void|float|unsigned int|ActuatorCommandResult)\s+{re.escape(name)}\s*\(",
        text,
        re.MULTILINE,
    ))


logic = strip_cpp_comments(read_text("logic.h"))
headers = {
    "alarm.h": strip_cpp_comments(read_text("alarm.h")),
    "valve_buzzer.h": strip_cpp_comments(read_text("valve_buzzer.h")),
    "power_regulator.h": strip_cpp_comments(read_text("power_regulator.h")),
    "selftest.h": strip_cpp_comments(read_text("selftest.h")),
}
headers["power_regulator_kvic.h"] = strip_cpp_comments(read_text("power_regulator_kvic.h"))
headers["power_regulator_rmvk.h"] = strip_cpp_comments(read_text("power_regulator_rmvk.h"))
headers["power_regulator_sem.h"]  = strip_cpp_comments(read_text("power_regulator_sem.h"))

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
    "alarm.h": {
        "samovar_process_active": ("bool", 1),
        "sensor_configured": ("bool", 1),
        "sensor_reading_valid": ("bool", 1),
        "sensor_valid": ("bool", 1),
        "optional_sensor_failed": ("bool", 1),
        "rectification_ds_sensors_assigned": ("bool", 1),
        "notify_rectification_sensors_unassigned": ("void", 1),
        "sensor_temp_at_least": ("bool", 1),
        "request_emergency_stop": ("void", 1),
        "perform_emergency_stop": ("void", 1),
        "process_sensor_failed": ("bool", 1),
        "set_alarm": ("void", 1),
        "check_alarm": ("void", 1),
    },
    "valve_buzzer.h": {
        "open_valve": ("ActuatorCommandResult", 1),
        "process_buzzer": ("void", 1),
        "set_buzzer": ("void", 1),
    },
    "power_regulator.h": {
        "set_power": ("ActuatorCommandResult", 1),
        "check_power_error": ("void", 1),
        "get_current_power": ("void", 1),
        "set_current_power": ("ActuatorCommandResult", 1),
        "set_power_mode": ("void", 1),
    },
    "power_regulator_kvic.h": {"triggerPowerStatus": ("void", 1)},
    "power_regulator_rmvk.h": {"triggerPowerStatus": ("void", 1)},
    "power_regulator_sem.h": {"triggerPowerStatus": ("void", 1), "clear_serial_in_buff": ("void", 1)},
    "selftest.h": {
        "start_self_test": ("void", 1),
        "stop_self_test": ("void", 1),
    },
}

for file_name, functions in moved_functions.items():
    text = headers.get(file_name, "")
    for name, (return_type, expected) in functions.items():
        actual = count_defs(text, name, return_type)
        if actual != expected:
            errors.append(
                f"{file_name} expected {expected} {return_type} definition(s) "
                f"of {name}, found {actual}"
            )
        if count_moved_defs(logic, name) != 0:
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
