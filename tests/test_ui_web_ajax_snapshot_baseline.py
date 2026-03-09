from pathlib import Path
import re
import subprocess
import unittest


BASELINE_AJAX_COMMIT = "b5a8bedf"
AJAX_SNAPSHOT_HEADER = Path("ui/web/ajax_snapshot.h")


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


def _normalize_cpp_body(body: str) -> str:
    body = re.sub(r"//.*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"\s+", "", body)
    return body


def _extract_json_keys(body: str) -> list[str]:
    return re.findall(r'jsonAddKey\s*\(\s*out\s*,\s*first\s*,\s*"([^"]+)"\s*\)', body)


def _extract_escaped_values(body: str) -> list[str]:
    matches = re.findall(r"jsonPrintEscaped\s*\(\s*out\s*,\s*([^)]+)\)", body)
    return [re.sub(r"\s+", "", match) for match in matches]


class AjaxSnapshotBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_text = AJAX_SNAPSHOT_HEADER.read_text(encoding="utf-8")
        cls.baseline_text = _read_git_file(BASELINE_AJAX_COMMIT, "Samovar.ino")

    def test_ajax_snapshot_header_exists(self) -> None:
        self.assertTrue(AJAX_SNAPSHOT_HEADER.exists())

    def test_json_add_key_matches_pre_extraction_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_text,
                'void jsonAddKey(Print &out, bool &first, const char *key)',
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                'void jsonAddKey(Print &out, bool &first, const char *key)',
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_json_print_escaped_matches_pre_extraction_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_text,
                'void jsonPrintEscaped(Print &out, const String &value)',
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                'void jsonPrintEscaped(Print &out, const String &value)',
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_send_ajax_json_keeps_json_key_order_identical_to_baseline(self) -> None:
        current_body = _extract_function_body(
            self.current_text,
            "void send_ajax_json(AsyncWebServerRequest *request)",
        )
        baseline_body = _extract_function_body(
            self.baseline_text,
            "void send_ajax_json(AsyncWebServerRequest *request)",
        )
        self.assertEqual(_extract_json_keys(current_body), _extract_json_keys(baseline_body))

    def test_send_ajax_json_keeps_escaped_fields_identical_to_baseline(self) -> None:
        current_body = _extract_function_body(
            self.current_text,
            "void send_ajax_json(AsyncWebServerRequest *request)",
        )
        baseline_body = _extract_function_body(
            self.baseline_text,
            "void send_ajax_json(AsyncWebServerRequest *request)",
        )
        self.assertEqual(_extract_escaped_values(current_body), _extract_escaped_values(baseline_body))

    def test_send_ajax_json_clears_msg_and_resets_level(self) -> None:
        body = _normalize_cpp_body(
            _extract_function_body(
                self.current_text,
                "void send_ajax_json(AsyncWebServerRequest *request)",
            )
        )
        self.assertIn("if(Msg.length()>0){", body)
        self.assertIn("Msg=\"\";", body)
        self.assertIn("msg_level=NONE_MSG;", body)

    def test_send_ajax_json_clears_logmsg(self) -> None:
        body = _normalize_cpp_body(
            _extract_function_body(
                self.current_text,
                "void send_ajax_json(AsyncWebServerRequest *request)",
            )
        )
        self.assertIn("if(LogMsg.length()>0){", body)
        self.assertIn("LogMsg=\"\";", body)


if __name__ == "__main__":
    unittest.main()
