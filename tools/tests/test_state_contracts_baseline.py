#!/usr/bin/env python3

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import state_inventory  # noqa: E402


STATUS_CODES_HEADER = ROOT / "src" / "core" / "state" / "status_codes.h"
MODE_CODES_HEADER = ROOT / "src" / "core" / "state" / "mode_codes.h"
EXPECTED_STATUS_CODES = {
    "SAMOVAR_STATUS_OFF": 0,
    "SAMOVAR_STATUS_RECTIFICATION_RUN": 10,
    "SAMOVAR_STATUS_RECTIFICATION_WAIT": 15,
    "SAMOVAR_STATUS_RECTIFICATION_COMPLETE": 20,
    "SAMOVAR_STATUS_CALIBRATION": 30,
    "SAMOVAR_STATUS_RECTIFICATION_PAUSE": 40,
    "SAMOVAR_STATUS_RECTIFICATION_WARMUP": 50,
    "SAMOVAR_STATUS_RECTIFICATION_STABILIZING": 51,
    "SAMOVAR_STATUS_RECTIFICATION_STABILIZED": 52,
    "SAMOVAR_STATUS_DISTILLATION": 1000,
    "SAMOVAR_STATUS_BEER": 2000,
    "SAMOVAR_STATUS_BK": 3000,
    "SAMOVAR_STATUS_NBK": 4000,
}
EXPECTED_START_VALUES = {
    "SAMOVAR_STARTVAL_RECT_IDLE": 0,
    "SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING": 1,
    "SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE": 2,
    "SAMOVAR_STARTVAL_RECT_STOPPED": 3,
    "SAMOVAR_STARTVAL_CALIBRATION": 100,
    "SAMOVAR_STARTVAL_DISTILLATION_ENTRY": 1000,
    "SAMOVAR_STARTVAL_BEER_ENTRY": 2000,
    "SAMOVAR_STARTVAL_BEER_MALT_HEATING": 2001,
    "SAMOVAR_STARTVAL_BEER_MALT_WAIT": 2002,
    "SAMOVAR_STARTVAL_BK_ENTRY": 3000,
    "SAMOVAR_STARTVAL_NBK_ENTRY": 4000,
    "SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING": 4001,
}
EXPECTED_COMMAND_ENUM = {
    "SAMOVAR_NONE": 0,
    "SAMOVAR_START": 1,
    "SAMOVAR_POWER": 2,
    "SAMOVAR_RESET": 3,
    "CALIBRATE_START": 4,
    "CALIBRATE_STOP": 5,
    "SAMOVAR_PAUSE": 6,
    "SAMOVAR_CONTINUE": 7,
    "SAMOVAR_SETBODYTEMP": 8,
    "SAMOVAR_DISTILLATION": 9,
    "SAMOVAR_BEER": 10,
    "SAMOVAR_BEER_NEXT": 11,
    "SAMOVAR_BK": 12,
    "SAMOVAR_NBK": 13,
    "SAMOVAR_SELF_TEST": 14,
    "SAMOVAR_DIST_NEXT": 15,
    "SAMOVAR_NBK_NEXT": 16,
}
EXPECTED_MODE_ENUM = {
    "SAMOVAR_RECTIFICATION_MODE": 0,
    "SAMOVAR_DISTILLATION_MODE": 1,
    "SAMOVAR_BEER_MODE": 2,
    "SAMOVAR_BK_MODE": 3,
    "SAMOVAR_NBK_MODE": 4,
    "SAMOVAR_SUVID_MODE": 5,
    "SAMOVAR_LUA_MODE": 6,
}


def require_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def parse_status_codes() -> dict[str, int]:
    text = STATUS_CODES_HEADER.read_text(encoding="utf-8")
    pattern = re.compile(r"static constexpr int16_t (SAMOVAR_STATUS_[A-Z0-9_]+) = (-?\d+);")
    values = {name: int(raw_value) for name, raw_value in pattern.findall(text)}
    if not values:
        raise AssertionError(f"No status codes found in {STATUS_CODES_HEADER}")
    return values


def parse_startval_codes() -> dict[str, int]:
    text = MODE_CODES_HEADER.read_text(encoding="utf-8")
    pattern = re.compile(r"static constexpr int16_t (SAMOVAR_STARTVAL_[A-Z0-9_]+) = (-?\d+);")
    values = {name: int(raw_value) for name, raw_value in pattern.findall(text)}
    if not values:
        raise AssertionError(f"No startval codes found in {MODE_CODES_HEADER}")
    return values


def main() -> None:
    print("=" * 72)
    print("State contracts baseline test")
    print("=" * 72)

    print("\n[1] Verifying SamovarStatusInt exact numeric baseline...")
    actual_status_codes = parse_status_codes()
    require_equal("SamovarStatusInt", actual_status_codes, EXPECTED_STATUS_CODES)
    print(f"    ✓ SamovarStatusInt={actual_status_codes}")

    print("\n[2] Verifying startval exact numeric baseline...")
    actual_start_values = parse_startval_codes()
    require_equal("startval", actual_start_values, EXPECTED_START_VALUES)
    print(f"    ✓ startval={actual_start_values}")

    print("\n[3] Verifying sam_command_sync exact numeric baseline...")
    actual_command_enum = state_inventory.parse_enum("SamovarCommands")
    require_equal("sam_command_sync", actual_command_enum, EXPECTED_COMMAND_ENUM)
    print(f"    ✓ sam_command_sync={actual_command_enum}")

    print("\n[4] Verifying Samovar_Mode exact numeric baseline...")
    actual_mode_enum = state_inventory.parse_enum("SAMOVAR_MODE")
    require_equal("Samovar_Mode", actual_mode_enum, EXPECTED_MODE_ENUM)
    print(f"    ✓ Samovar_Mode={actual_mode_enum}")

    print("\n" + "=" * 72)
    print("State contracts baseline: PASS")
    print("=" * 72)


if __name__ == "__main__":
    main()
