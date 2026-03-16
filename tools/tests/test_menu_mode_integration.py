#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
MENU_ACTIONS_HEADER = ROOT / "ui" / "menu" / "actions.h"
MENU_INPUT_HEADER = ROOT / "ui" / "menu" / "input.h"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_function(text: str, signature: str) -> str:
    pattern = re.compile(rf"(?:inline\s+)?{re.escape(signature)}\s*\{{", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Function signature not found: {signature}")

    brace_start = text.find("{", match.start())
    if brace_start == -1:
        raise AssertionError(f"Function body start not found: {signature}")

    depth = 0
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]

    raise AssertionError(f"Function body end not found: {signature}")


def assert_contains(text: str, fragment: str, label: str) -> None:
    require(fragment in text, f"{label}: missing fragment `{fragment}`")


def assert_ordered(text: str, fragments: list[str], label: str) -> None:
    position = 0
    for fragment in fragments:
        index = text.find(fragment, position)
        require(index != -1, f"{label}: missing or out-of-order fragment `{fragment}`")
        position = index + len(fragment)


def run_command(command: list[str], label: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    require(
        result.returncode == 0,
        result.stderr or result.stdout or f"{label} failed",
    )
    output = (result.stdout + result.stderr).strip()
    if output:
        for line in output.splitlines():
            print(f"    {line}")
    return output


def check_static_contracts() -> None:
    print("=" * 72)
    print("Menu mode integration")
    print("=" * 72)

    actions_text = read_text(MENU_ACTIONS_HEADER)
    input_text = read_text(MENU_INPUT_HEADER)

    menu_get_power = extract_function(actions_text, "void menu_get_power()")
    setup_go_back = extract_function(actions_text, "void setup_go_back()")
    menu_calibrate = extract_function(actions_text, "void menu_calibrate()")
    menu_samovar_start = extract_function(actions_text, "void menu_samovar_start()")

    print("\n[1] Verifying menu state semantics with named values...")
    for fragment in [
        "Samovar_Mode == SAMOVAR_BEER_MODE",
        "sam_command_sync = SAMOVAR_BEER;",
        "Samovar_Mode == SAMOVAR_DISTILLATION_MODE",
        "sam_command_sync = SAMOVAR_DISTILLATION;",
        "Samovar_Mode == SAMOVAR_BK_MODE",
        "sam_command_sync = SAMOVAR_BK;",
        "Samovar_Mode == SAMOVAR_NBK_MODE",
        "sam_command_sync = SAMOVAR_NBK;",
        "sam_command_sync = SAMOVAR_POWER;",
    ]:
        assert_contains(menu_get_power, fragment, "menu_get_power")
    assert_ordered(
        setup_go_back,
        [
            "reset_focus();",
            "set_menu_screen(2);",
            "save_profile_nvs();",
            "read_config();",
        ],
        "setup_go_back",
    )
    for fragment in [
        "startval_is_active_non_calibration(startval)",
        "startval == SAMOVAR_STARTVAL_CALIBRATION",
        "startval = SAMOVAR_STARTVAL_CALIBRATION;",
    ]:
        assert_contains(menu_calibrate, fragment, "menu_calibrate")
    for fragment in [
        "startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE",
        "startval = SAMOVAR_STARTVAL_RECT_STOPPED;",
        "startval == SAMOVAR_STARTVAL_RECT_IDLE",
        "startval = SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING;",
        "startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING",
    ]:
        assert_contains(menu_samovar_start, fragment, "menu_samovar_start")
    for fragment in [
        "if (startval == SAMOVAR_STARTVAL_CALIBRATION) {",
        "startval = SAMOVAR_STARTVAL_RECT_IDLE;",
    ]:
        assert_contains(input_text, fragment, "menu input")
    print("    ✓ menu actions/input use named mode/startval/status semantics in transition points")


def run_existing_menu_tests() -> None:
    print("\n[2] Running focused menu integration tests...")
    output = run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_ui_menu_actions_behavior",
            "tests.test_ui_menu_input_behavior",
            "tests.test_ui_menu_integration_behavior",
        ],
        "menu unittest suite",
    )
    for expected in [
        "Ran 3 tests",
        "OK",
    ]:
        require(expected in output, f"menu unittest suite: missing `{expected}`")
    print("    ✓ menu behavior harness suite passed")


def main() -> None:
    check_static_contracts()
    run_existing_menu_tests()
    print("\n" + "=" * 72)
    print("Menu mode integration: PASS")
    print("=" * 72)


if __name__ == "__main__":
    main()
