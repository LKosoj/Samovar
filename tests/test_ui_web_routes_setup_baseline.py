from pathlib import Path
import re
import subprocess
import unittest


BASELINE_SETUP_SAVE_COMMIT = "64506d0d"
ROUTES_SAVE_PATH = Path("ui/web/routes_save.h")
SETUP_WIFI_PATH = Path("ui/web/routes_setup_wifi.h")
SETUP_PROCESS_PATH = Path("ui/web/routes_setup_process.h")


def _read_git_file(commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        text=True,
    )


def _extract_function_body(text: str, signature: str) -> str:
    pattern = re.compile(rf"(?:static\s+)?(?:inline\s+)?{re.escape(signature)}\s*\{{", re.MULTILINE)
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
                return text[brace_start + 1:index]

    raise AssertionError(f"Function body end not found: {signature}")


def _extract_between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start == -1:
        raise AssertionError(f"Start marker not found: {start_marker}")
    end = text.find(end_marker, start)
    if end == -1:
        raise AssertionError(f"End marker not found: {end_marker}")
    return text[start:end]


def _normalize_cpp(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"\s+", "", text)
    return text


def _marker_positions(text: str, markers: list[str]) -> list[int]:
    positions = []
    for marker in markers:
        index = text.find(marker)
        if index == -1:
            raise AssertionError(f"Marker not found: {marker}")
        positions.append(index)
    return positions


def _assert_markers_are_ordered(test_case: unittest.TestCase, text: str, markers: list[str]) -> None:
    last_index = -1
    for marker in markers:
        index = text.find(marker, last_index + 1)
        if index == -1:
            test_case.fail(f"Marker not found in order: {marker}")
        last_index = index


class SetupSaveBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_routes_save = ROUTES_SAVE_PATH.read_text(encoding="utf-8")
        cls.current_wifi = SETUP_WIFI_PATH.read_text(encoding="utf-8")
        cls.current_process = SETUP_PROCESS_PATH.read_text(encoding="utf-8")
        cls.baseline_webserver = _read_git_file(
            BASELINE_SETUP_SAVE_COMMIT,
            "WebServer.ino",
        )

    def test_wifi_helper_matches_pre_split_baseline_block(self) -> None:
        baseline_block = _extract_between(
            self.baseline_webserver,
            'if (request->hasArg("videourl")) {',
            'if (request->hasArg("SteamColor")) {',
        )
        current_body = _extract_function_body(
            self.current_wifi,
            "void handleSaveWifiSettings(AsyncWebServerRequest *request)",
        )
        self.assertEqual(_normalize_cpp(current_body), _normalize_cpp(baseline_block))

    def test_handle_save_keeps_wifi_updates_before_process_switch(self) -> None:
        current_wifi_call = self.current_routes_save.find("handleSaveWifiSettings(request);")
        current_process_call = self.current_routes_save.find("handleSaveProcessSettings(request);")
        current_rele1 = self.current_routes_save.find('if (request->hasArg("rele1")) {')

        self.assertNotEqual(current_wifi_call, -1)
        self.assertNotEqual(current_process_call, -1)
        self.assertNotEqual(current_rele1, -1)
        self.assertLess(current_wifi_call, current_process_call)
        self.assertLess(current_process_call, current_rele1)

        baseline_wifi = self.baseline_webserver.find('if (request->hasArg("videourl")) {')
        baseline_mode = self.baseline_webserver.find('if (request->hasArg("mode")) {')
        baseline_rele1 = self.baseline_webserver.find('if (request->hasArg("rele1")) {')

        self.assertNotEqual(baseline_wifi, -1)
        self.assertNotEqual(baseline_mode, -1)
        self.assertNotEqual(baseline_rele1, -1)
        self.assertLess(baseline_wifi, baseline_mode)
        self.assertLess(baseline_mode, baseline_rele1)

    def test_process_helper_keeps_side_effect_order_identical_to_baseline(self) -> None:
        baseline_block = _extract_between(
            self.baseline_webserver,
            'if (request->hasArg("mode")) {',
            'if (request->hasArg("rele1")) {',
        )
        current_body = _extract_function_body(
            self.current_process,
            "void handleSaveProcessSettings(AsyncWebServerRequest *request)",
        )
        baseline_markers = [
            "distiller_finish();",
            "beer_finish();",
            "bk_finish();",
            "nbk_finish();",
            "set_power(false);",
            "SetScriptOff = true;",
            "loop_lua_fl = false;",
            "delay(100);",
            "samovar_reset();",
            'SamSetup.Mode = request->arg("mode").toInt();',
            "Samovar_Mode =",
            "Samovar_CR_Mode =",
            "load_default_program_for_mode();",
            "save_profile();",
            "load_profile();",
            "lua_type_script = get_lua_mode_name();",
            "load_lua_script();",
            "change_samovar_mode();",
        ]
        current_markers = [
            "distiller_finish();",
            "beer_finish();",
            "bk_finish();",
            "nbk_finish();",
            "set_power(false);",
            "SetScriptOff = true;",
            "loop_lua_fl = false;",
            "delay(100);",
            "samovar_reset();",
            "SamSetup.Mode = nextMode;",
            "Samovar_Mode =",
            "Samovar_CR_Mode =",
            "load_default_program_for_mode();",
            "save_profile();",
            "load_profile();",
            "lua_type_script = get_lua_mode_name();",
            "load_lua_script();",
            "change_samovar_mode();",
        ]

        _assert_markers_are_ordered(self, baseline_block, baseline_markers)
        _assert_markers_are_ordered(self, current_body, current_markers)

    def test_process_helper_keeps_persist_before_reload_sequence(self) -> None:
        current_body = _extract_function_body(
            self.current_process,
            "void handleSaveProcessSettings(AsyncWebServerRequest *request)",
        )
        _assert_markers_are_ordered(
            self,
            current_body,
            [
                "load_default_program_for_mode();",
                "save_profile();",
                "load_profile();",
                "lua_type_script = get_lua_mode_name();",
                "load_lua_script();",
                "change_samovar_mode();",
            ],
        )

    def test_legacy_webserver_file_removed(self) -> None:
        self.assertFalse(Path("WebServer.ino").exists())


if __name__ == "__main__":
    unittest.main()
