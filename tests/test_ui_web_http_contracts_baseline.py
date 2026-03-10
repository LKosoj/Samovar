from pathlib import Path
import re
import subprocess
import unittest


BASELINE_WEB_COMMIT = "a0197e27"
SERVER_INIT_PATH = Path("ui/web/server_init.h")
AJAX_SNAPSHOT_PATH = Path("ui/web/ajax_snapshot.h")
CONTRACTS_DOC_PATH = Path("docs/refactoring/contracts.md")


def _read_git_file(commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        text=True,
    )


def _normalize_http_methods(methods: str) -> str:
    parts = [part.strip() for part in methods.split("|")]
    normalized_parts = []
    for part in parts:
        if part.startswith("HTTP_"):
            normalized_parts.append(part)
        else:
            normalized_parts.append(f"HTTP_{part}")
    return "|".join(normalized_parts)


def _extract_section(text: str, title: str, next_title: str) -> str:
    start = text.find(title)
    if start == -1:
        raise AssertionError(f"Section not found: {title}")

    end = text.find(next_title, start)
    if end == -1:
        raise AssertionError(f"Section end not found: {next_title}")

    return text[start:end]


def _strip_cpp_comments(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


def _extract_server_on_routes(text: str) -> set[tuple[str, str]]:
    text = _strip_cpp_comments(text)
    pattern = re.compile(
        r'server\.on\("([^"]+)"\s*,\s*(HTTP_[A-Z_]+(?:\s*\|\s*HTTP_[A-Z_]+)*)',
        re.MULTILINE,
    )
    return {
        (path, re.sub(r"\s+", "", methods))
        for path, methods in pattern.findall(text)
    }


def _extract_serve_static_paths(text: str) -> set[str]:
    text = _strip_cpp_comments(text)
    return set(re.findall(r'server\.serveStatic\("([^"]+)"', text))


def _extract_http_contracts(text: str) -> set[tuple[str, str]]:
    section = _extract_section(
        text,
        "## HTTP endpoints",
        "## /ajax JSON keys",
    )
    contracts = set()
    for token in re.findall(r"- `([^`]+)`", section):
        if "/" not in token:
            continue
        if " " not in token:
            continue
        methods, path = token.split(" ", 1)
        contracts.add((path.strip(), _normalize_http_methods(methods.strip())))
    return contracts


def _extract_ajax_contract_keys(text: str) -> set[str]:
    section = _extract_section(
        text,
        "## /ajax JSON keys",
        "## Lua API names",
    )
    return set(re.findall(r"- `([^`]+)`", section))


def _extract_function_body(text: str, signature: str) -> str:
    pattern = re.compile(
        rf"(?:static\s+)?(?:inline\s+)?{re.escape(signature)}\s*\{{",
        re.MULTILINE,
    )
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


def _extract_ajax_keys(text: str) -> list[str]:
    body = _extract_function_body(
        text,
        "void send_ajax_json(AsyncWebServerRequest *request)",
    )
    return re.findall(r'jsonAddKey\s*\(\s*out\s*,\s*first\s*,\s*"([^"]+)"\s*\)', body)


class WebHttpContractsBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server_init_text = SERVER_INIT_PATH.read_text(encoding="utf-8")
        cls.ajax_snapshot_text = AJAX_SNAPSHOT_PATH.read_text(encoding="utf-8")
        cls.contracts_doc_text = CONTRACTS_DOC_PATH.read_text(encoding="utf-8")
        cls.baseline_webserver_text = _read_git_file(
            BASELINE_WEB_COMMIT,
            "WebServer.ino",
        )

    def test_phase0_documented_http_endpoints_are_registered(self) -> None:
        documented_endpoints = _extract_http_contracts(self.contracts_doc_text)
        current_routes = _extract_server_on_routes(self.server_init_text)
        self.assertTrue(documented_endpoints.issubset(current_routes))

    def test_server_on_routes_match_pre_removal_baseline(self) -> None:
        current_routes = _extract_server_on_routes(self.server_init_text)
        baseline_routes = _extract_server_on_routes(self.baseline_webserver_text)
        self.assertEqual(current_routes, baseline_routes)

    def test_serve_static_paths_match_pre_removal_baseline(self) -> None:
        current_paths = _extract_serve_static_paths(self.server_init_text)
        baseline_paths = _extract_serve_static_paths(self.baseline_webserver_text)
        self.assertEqual(current_paths, baseline_paths)

    def test_key_http_handlers_still_use_expected_contract_targets(self) -> None:
        expected_snippets = [
            'server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest *request) {',
            "send_ajax_json(request);",
            'server.on("/command", HTTP_GET, [](AsyncWebServerRequest *request) {',
            "web_command(request);",
            'server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request) {',
            "web_program(request);",
            'server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request) {',
            "handleSave(request);",
            'server.on("/calibrate", HTTP_GET, [](AsyncWebServerRequest *request) {',
            "calibrate_command(request);",
            'server.on("/getlog", HTTP_GET, [](AsyncWebServerRequest *request) {',
            'get_data_log(request, "data.csv");',
            'server.on("/getoldlog", HTTP_GET, [](AsyncWebServerRequest *request) {',
            'get_data_log(request, "data_old.csv");',
        ]
        for snippet in expected_snippets:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, self.server_init_text)

    def test_ajax_keys_cover_phase0_contract_doc(self) -> None:
        current_ajax_keys = set(_extract_ajax_keys(self.ajax_snapshot_text))
        documented_ajax_keys = _extract_ajax_contract_keys(self.contracts_doc_text)
        self.assertTrue(documented_ajax_keys.issubset(current_ajax_keys))


if __name__ == "__main__":
    unittest.main()
