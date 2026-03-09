from pathlib import Path
import re
import subprocess
import unittest


BASELINE_LOGIC_COMMIT = "68b43293"
PROCESS_MATH_HEADER = Path("support/process_math.h")
FUNCTION_SIGNATURES = [
    "uint8_t getDelimCount(const String& data, char separator)",
    "String getValue(const String& data, char separator, int index)",
    "float get_liquid_volume_by_step(float StepCount)",
    "float get_liquid_rate_by_step(int StepperSpeed)",
    "float get_speed_from_rate(float volume_per_hour)",
    "int get_liquid_volume()",
    "float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure)",
    "float get_steam_alcohol(float t)",
    "float get_alcohol(float t)",
    "unsigned int hexToDec(String hexString)",
]


def _read_baseline_logic() -> str:
    return subprocess.check_output(
        ["git", "show", f"{BASELINE_LOGIC_COMMIT}:logic.h"],
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


class ProcessMathBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_text = PROCESS_MATH_HEADER.read_text(encoding="utf-8")
        cls.baseline_text = _read_baseline_logic()

    def test_process_math_header_exists(self) -> None:
        self.assertTrue(PROCESS_MATH_HEADER.exists(), "support/process_math.h must exist")

    def test_process_math_functions_match_baseline_logic(self) -> None:
        for signature in FUNCTION_SIGNATURES:
            with self.subTest(signature=signature):
                current_body = _normalize_cpp_body(_extract_function_body(self.current_text, signature))
                baseline_body = _normalize_cpp_body(_extract_function_body(self.baseline_text, signature))
                self.assertEqual(current_body, baseline_body)


if __name__ == "__main__":
    unittest.main()
