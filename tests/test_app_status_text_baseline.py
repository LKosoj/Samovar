from pathlib import Path
import re
import subprocess
import unittest


BASELINE_LOGIC_COMMIT = "43e22996"
STATUS_TEXT_HEADER = Path("app/status_text.h")
STATUS_CODES_HEADER = Path("src/core/state/status_codes.h")
MODE_CODES_HEADER = Path("src/core/state/mode_codes.h")


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


def _expand_status_constants(text: str) -> str:
    constants_text = STATUS_CODES_HEADER.read_text(encoding="utf-8")
    matches = re.findall(
        r"static constexpr int16_t (SAMOVAR_STATUS_[A-Z0-9_]+) = (-?\d+);",
        constants_text,
    )
    for name, value in sorted(matches, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(name, value)
    return text


def _expand_status_helpers(text: str) -> str:
    text = text.replace(
        "samovar_status_allows_rectification_withdrawal(SamovarStatusInt)",
        "SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN || "
        "SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT || "
        "SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_PAUSE"
    )
    return text.replace(
        "samovar_status_has_rectification_program_progress(SamovarStatusInt)",
        "SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN || "
        "SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT",
    )


def _expand_startval_constants(text: str) -> str:
    constants_text = MODE_CODES_HEADER.read_text(encoding="utf-8")
    matches = re.findall(
        r"static constexpr int16_t (SAMOVAR_STARTVAL_[A-Z0-9_]+) = (-?\d+);",
        constants_text,
    )
    for name, value in sorted(matches, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(name, value)
    return text


class StatusTextBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_text = STATUS_TEXT_HEADER.read_text(encoding="utf-8")
        cls.baseline_text = _read_git_file(BASELINE_LOGIC_COMMIT, "logic.h")

    def test_status_text_header_exists(self) -> None:
        self.assertTrue(STATUS_TEXT_HEADER.exists(), "app/status_text.h must exist")

    def test_status_text_matches_pre_extraction_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _expand_startval_constants(
                _expand_status_constants(
                    _expand_status_helpers(
                        _extract_function_body(self.current_text, "String get_Samovar_Status()")
                    )
                )
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(self.baseline_text, "String get_Samovar_Status()")
        )
        self.assertEqual(current_body, baseline_body)

    def test_status_text_keeps_updating_runtime_status_code(self) -> None:
        body = _extract_function_body(self.current_text, "String get_Samovar_Status()")
        self.assertIn("SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_RUN;", body)
        self.assertIn("SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WAIT;", body)
        self.assertIn("SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_COMPLETE;", body)
        self.assertIn("SamovarStatusInt = SAMOVAR_STATUS_CALIBRATION;", body)
        self.assertIn("SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_PAUSE;", body)
        self.assertIn("SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WARMUP;", body)


if __name__ == "__main__":
    unittest.main()
