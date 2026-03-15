import re
import subprocess
import unittest
from pathlib import Path


BASELINE_COMMIT = "94f6b3eb"
RUNTIME_HEADER = Path("ui/lua/runtime.h")


def git_show(pathspec: str) -> str:
    result = subprocess.run(
        ["git", "show", pathspec],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def extract_function_body(text: str, signature: str) -> str:
    pattern = re.compile(r"(?:inline\s+)?" + re.escape(signature) + r"\s*\{", re.MULTILINE)
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


def normalize_cpp(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"\s+", "", text)
    return text


class LuaGlobalVariablesBaselineTest(unittest.TestCase):
    def test_get_global_variables_matches_phase0_baseline_body(self) -> None:
        baseline_text = git_show(f"{BASELINE_COMMIT}:lua.h")
        current_text = RUNTIME_HEADER.read_text(encoding="utf-8")

        baseline_body = extract_function_body(baseline_text, "String get_global_variables()")
        current_body = extract_function_body(current_text, "String get_global_variables()")

        self.assertEqual(normalize_cpp(current_body), normalize_cpp(baseline_body))

    def test_get_global_variables_keeps_phase0_markers(self) -> None:
        body = extract_function_body(
            RUNTIME_HEADER.read_text(encoding="utf-8"),
            "String get_global_variables()",
        )

        self.assertIn('return "";', body)
        for marker in [
            'Variables += "capacity_num = "',
            'Variables += "SamovarStatusInt = "',
            'Variables += "ProgramNum = "',
            'Variables += "ProgramLen = "',
            'Variables += "ActualVolumePerHour = "',
            'Variables += "PowerOn = "',
            'Variables += "PauseOn = "',
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, body)


if __name__ == "__main__":
    unittest.main()
