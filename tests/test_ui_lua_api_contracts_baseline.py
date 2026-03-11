import re
import subprocess
import unittest
from pathlib import Path


BASELINE_COMMIT = "63b2c303"
CONTRACTS_DOC = Path("docs/refactoring/contracts.md")
RUNTIME_HEADER = Path("ui/lua/runtime.h")
PROCESS_HEADER = Path("ui/lua/bindings_process.h")
IO_HEADER = Path("ui/lua/bindings_io.h")
HTTP_HEADER = Path("ui/lua/bindings_http.h")
SERVER_INIT_HEADER = Path("ui/web/server_init.h")
ROUTES_COMMAND_HEADER = Path("ui/web/routes_command.h")
ROUTES_SETUP_PROCESS_HEADER = Path("ui/web/routes_setup_process.h")


def git_show(pathspec: str) -> str:
    result = subprocess.run(
        ["git", "show", pathspec],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def normalize_cpp(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"\s+", "", text)
    return text


def extract_function_body(text: str, signature: str) -> str:
    pattern = re.compile(re.escape(signature) + r"\s*\{", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"Function definition not found: {signature}")

    brace_start = match.end() - 1
    depth = 0
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : index + 1]

    raise AssertionError(f"Unbalanced braces for: {signature}")


def extract_runtime_registrations(text: str) -> list[tuple[str, str]]:
    return re.findall(
        r'lua\.Lua_register\("([^"]+)",\s*\(const lua_CFunction\)&([A-Za-z0-9_]+)\);',
        text,
    )


def extract_documented_lua_names(text: str) -> list[str]:
    match = re.search(
        r"Зарегистрированные Lua names:\n\n((?:- `[^`]+`\n)+)",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise AssertionError("Lua API names section not found in contracts doc")
    return re.findall(r"- `([^`]+)`", match.group(1))


class LuaApiContractsBaselineTest(unittest.TestCase):
    def test_runtime_registration_pairs_match_pre_delete_baseline(self) -> None:
        baseline_text = git_show(f"{BASELINE_COMMIT}:ui/lua/runtime.h")
        current_text = RUNTIME_HEADER.read_text(encoding="utf-8")

        self.assertEqual(
            extract_runtime_registrations(current_text),
            extract_runtime_registrations(baseline_text),
        )

    def test_phase0_documented_lua_api_names_are_registered(self) -> None:
        documented_names = set(
            extract_documented_lua_names(CONTRACTS_DOC.read_text(encoding="utf-8"))
        )
        registered_names = {
            name for name, _ in extract_runtime_registrations(RUNTIME_HEADER.read_text(encoding="utf-8"))
        }

        self.assertEqual(registered_names, documented_names)

    def test_http_request_wrapper_matches_baseline(self) -> None:
        baseline_text = git_show(f"{BASELINE_COMMIT}:ui/lua/bindings_http.h")
        current_text = HTTP_HEADER.read_text(encoding="utf-8")

        baseline_body = extract_function_body(
            baseline_text,
            "static int lua_wrapper_http_request(lua_State *lua_state)",
        )
        current_body = extract_function_body(
            current_text,
            "static int lua_wrapper_http_request(lua_State *lua_state)",
        )

        self.assertEqual(normalize_cpp(current_body), normalize_cpp(baseline_body))

    def test_set_power_wrapper_matches_baseline(self) -> None:
        baseline_text = git_show(f"{BASELINE_COMMIT}:ui/lua/bindings_process.h")
        current_text = PROCESS_HEADER.read_text(encoding="utf-8")

        baseline_body = extract_function_body(
            baseline_text,
            "static int lua_wrapper_set_power(lua_State *lua_state)",
        )
        current_body = extract_function_body(
            current_text,
            "static int lua_wrapper_set_power(lua_State *lua_state)",
        )

        self.assertEqual(normalize_cpp(current_body), normalize_cpp(baseline_body))

    def test_open_valve_wrapper_matches_baseline(self) -> None:
        baseline_text = git_show(f"{BASELINE_COMMIT}:ui/lua/bindings_io.h")
        current_text = IO_HEADER.read_text(encoding="utf-8")

        baseline_body = extract_function_body(
            baseline_text,
            "static int lua_wrapper_open_valve(lua_State *lua_state)",
        )
        current_body = extract_function_body(
            current_text,
            "static int lua_wrapper_open_valve(lua_State *lua_state)",
        )

        self.assertEqual(normalize_cpp(current_body), normalize_cpp(baseline_body))

    def test_valve_api_name_is_open_valve_in_runtime_and_contracts(self) -> None:
        documented_names = set(
            extract_documented_lua_names(CONTRACTS_DOC.read_text(encoding="utf-8"))
        )
        registered_names = {
            name for name, _ in extract_runtime_registrations(RUNTIME_HEADER.read_text(encoding="utf-8"))
        }

        self.assertIn("openValve", documented_names)
        self.assertIn("openValve", registered_names)
        self.assertNotIn("set_valve", documented_names)
        self.assertNotIn("set_valve", registered_names)

    def test_mode_and_button_script_entry_points_remain_wired(self) -> None:
        runtime_text = RUNTIME_HEADER.read_text(encoding="utf-8")
        routes_command_text = ROUTES_COMMAND_HEADER.read_text(encoding="utf-8")
        server_init_text = SERVER_INIT_HEADER.read_text(encoding="utf-8")
        routes_setup_process_text = ROUTES_SETUP_PROCESS_HEADER.read_text(encoding="utf-8")

        for marker in [
            'SPIFFS.open("/init.lua")',
            "get_global_variables();",
            "lua_type_script = get_lua_mode_name();",
            "load_lua_script();",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, runtime_text)

        for marker in [
            'run_lua_script(request->arg("lua"));',
            "run_lua_string(lstr);",
            'server.on("/lua", HTTP_GET',
            "start_lua_script();",
            "lua_type_script = get_lua_mode_name();",
            "load_lua_script();",
        ]:
            with self.subTest(marker=marker):
                self.assertTrue(
                    marker in routes_command_text
                    or marker in server_init_text
                    or marker in routes_setup_process_text
                )


if __name__ == "__main__":
    unittest.main()
