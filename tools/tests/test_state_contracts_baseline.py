#!/usr/bin/env python3

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import state_inventory  # noqa: E402


EXPECTED_STATUS_VALUES = [0, 10, 15, 20, 30, 40, 50, 51, 52, 1000, 2000, 3000, 4000]
EXPECTED_START_VALUES = [0, 1, 2, 3, 100, 1000, 2000, 2001, 2002, 3000, 4000, 4001]
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


def main() -> None:
    print("=" * 72)
    print("State contracts baseline test")
    print("=" * 72)

    inventory = state_inventory.build_inventory()

    print("\n[1] Verifying SamovarStatusInt exact numeric baseline...")
    actual_status_values = list(inventory["status_values"])
    require_equal("SamovarStatusInt", actual_status_values, EXPECTED_STATUS_VALUES)
    print(f"    ✓ SamovarStatusInt={actual_status_values}")

    print("\n[2] Verifying startval exact numeric baseline...")
    actual_start_values = list(inventory["start_values"])
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
