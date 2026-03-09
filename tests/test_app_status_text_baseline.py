from pathlib import Path
import re
import subprocess
import unittest


BASELINE_LOGIC_COMMIT = "43e22996"
STATUS_TEXT_HEADER = Path("app/status_text.h")


def _read_git_file(commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        text=True,
    )


def _extract_function_body(text: str, signature: str) -> str:
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
                return text[brace_start + 1:index]

    raise AssertionError(f"Function body end not found: {signature}")


def _normalize_cpp_body(body: str) -> str:
    body = re.sub(r"//.*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"\s+", "", body)
    return body


class StatusTextBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_text = STATUS_TEXT_HEADER.read_text(encoding="utf-8")
        cls.baseline_text = _read_git_file(BASELINE_LOGIC_COMMIT, "logic.h")

    def test_status_text_header_exists(self) -> None:
        self.assertTrue(STATUS_TEXT_HEADER.exists(), "app/status_text.h must exist")

    def test_status_text_matches_pre_extraction_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(self.current_text, "String get_Samovar_Status()")
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(self.baseline_text, "String get_Samovar_Status()")
        )
        self.assertEqual(current_body, baseline_body)

    def test_status_text_keeps_updating_runtime_status_code(self) -> None:
        body = _extract_function_body(self.current_text, "String get_Samovar_Status()")
        self.assertIn("SamovarStatusInt = 10;", body)
        self.assertIn("SamovarStatusInt = 15;", body)
        self.assertIn("SamovarStatusInt = 20;", body)
        self.assertIn("SamovarStatusInt = 30;", body)
        self.assertIn("SamovarStatusInt = 40;", body)
        self.assertIn("SamovarStatusInt = 50;", body)


if __name__ == "__main__":
    unittest.main()
