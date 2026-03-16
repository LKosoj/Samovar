#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
ROUTES_SETUP_HEADER = ROOT / "ui" / "web" / "routes_setup.h"
PAGE_ASSETS_HEADER = ROOT / "ui" / "web" / "page_assets.h"
MODE_SWITCH_HARNESS = ROOT / "tools" / "tests" / "test_mode_switching_behavior.py"


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
    print("Web mode integration")
    print("=" * 72)

    routes_setup = read_text(ROUTES_SETUP_HEADER)
    page_assets = read_text(PAGE_ASSETS_HEADER)

    handle_save_process = extract_function(
        routes_setup,
        "void handleSaveProcessSettings(AsyncWebServerRequest *request)",
    )
    handle_save = extract_function(routes_setup, "void handleSave(AsyncWebServerRequest *request)")
    change_mode = extract_function(page_assets, "void change_samovar_mode()")

    print("\n[1] Verifying web setup/save state contract...")
    assert_ordered(
        handle_save_process,
        [
            'if (!request->hasArg("mode")) {',
            "int nextMode = request->arg(\"mode\").toInt();",
            "if (SamSetup.Mode == nextMode) {",
            "samovar_reset();",
            "SamSetup.Mode = nextMode;",
            "Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;",
            "Samovar_CR_Mode = Samovar_Mode;",
            "load_default_program_for_mode();",
            "save_profile_nvs();",
            "load_profile_nvs();",
            "change_samovar_mode();",
        ],
        "handleSaveProcessSettings",
    )
    assert_ordered(
        handle_save,
        [
            "handleSaveWifiSettings(request);",
            "handleSaveProcessSettings(request);",
            "save_profile_nvs();",
            "read_config();",
        ],
        "handleSave",
    )
    for fragment in [
        "distiller_finish();",
        "beer_finish();",
        "bk_finish();",
        "nbk_finish();",
        "set_power(false);",
    ]:
        assert_contains(handle_save_process, fragment, "handleSaveProcessSettings")
    for fragment in [
        "const char* activePage = mode_active_page(Samovar_Mode);",
        "Samovar_Mode = mode_runtime_owner(Samovar_Mode);",
        'server.serveStatic("/index.htm", SPIFFS, activePage)',
    ]:
        assert_contains(change_mode, fragment, "change_samovar_mode")
    print("    ✓ handleSave/handleSaveProcessSettings keep explicit save-switch-rebind order")


def run_existing_web_tests() -> None:
    print("\n[2] Running focused web route baseline tests...")
    run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_ui_web_routes_setup_save",
            "tests.test_ui_web_routes_setup_baseline",
            "tests.test_change_samovar_mode_behavior",
        ],
        "web unittest suite",
    )
    print("    ✓ web route/unit harness suite passed")

    print("\n[3] Running web mode-switch integration harness...")
    output = run_command(
        [sys.executable, str(MODE_SWITCH_HARNESS)],
        "web mode switching harness",
    )
    for expected in [
        "rect_to_dist|ok|",
        "rect_to_beer|ok|",
        "rect_to_bk|ok|",
        "rect_to_nbk|ok|",
        "rect_to_suvid|ok|",
        "rect_to_lua|ok|",
        "mode_switching_behavior|ok",
        "Mode switching behavior: PASS",
    ]:
        require(expected in output, f"web mode switching harness: missing `{expected}`")
    print("    ✓ setup/save mode switching is confirmed for all target mode families")


def main() -> None:
    check_static_contracts()
    run_existing_web_tests()
    print("\n" + "=" * 72)
    print("Web mode integration: PASS")
    print("=" * 72)


if __name__ == "__main__":
    main()
