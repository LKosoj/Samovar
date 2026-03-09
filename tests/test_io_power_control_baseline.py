from pathlib import Path
import re
import subprocess
import unittest


BASELINE_LOGIC_COMMIT = "2f96daf1"
POWER_CONTROL_HEADER = Path("io/power_control.h")


def _read_git_file(commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        text=True,
    )


def _extract_trigger_power_status_bodies(text: str) -> list[str]:
    pattern = re.compile(
        r"(?:inline\s+)?void\s+(?:IRAM_ATTR\s+)?triggerPowerStatus\s*\([^)]*\)\s*\{",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        raise AssertionError("Function signature not found: triggerPowerStatus")

    bodies: list[str] = []
    for match in matches:
        brace_start = text.find("{", match.start())
        if brace_start == -1:
            raise AssertionError("Function body start not found: triggerPowerStatus")

        depth = 0
        for index in range(brace_start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    bodies.append(text[brace_start + 1:index])
                    break
        else:
            raise AssertionError("Function body end not found: triggerPowerStatus")

    return bodies


def _normalize_cpp_body(body: str) -> str:
    body = re.sub(r"//.*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"\s+", "", body)
    return body


class PowerControlBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_text = POWER_CONTROL_HEADER.read_text(encoding="utf-8")
        cls.baseline_text = _read_git_file(BASELINE_LOGIC_COMMIT, "logic.h")

    def test_power_control_header_exists(self) -> None:
        self.assertTrue(POWER_CONTROL_HEADER.exists(), "io/power_control.h must exist")

    def test_trigger_power_status_variants_match_pre_extraction_baseline(self) -> None:
        current_bodies = _extract_trigger_power_status_bodies(self.current_text)
        baseline_bodies = _extract_trigger_power_status_bodies(self.baseline_text)

        self.assertEqual(len(current_bodies), 2)
        self.assertEqual(len(baseline_bodies), 2)
        self.assertEqual(
            [_normalize_cpp_body(body) for body in current_bodies],
            [_normalize_cpp_body(body) for body in baseline_bodies],
        )

    def test_rmvk_trigger_power_status_updates_expected_runtime_state(self) -> None:
        current_bodies = _extract_trigger_power_status_bodies(self.current_text)

        non_rmvk_body = current_bodies[0]
        self.assertIn("current_power_volt =", non_rmvk_body)
        self.assertIn("target_power_volt =", non_rmvk_body)
        self.assertIn("current_power_mode =", non_rmvk_body)
        self.assertIn("reg_online = true;", non_rmvk_body)
        self.assertIn("last_reg_online = millis();", non_rmvk_body)

        rmvk_body = current_bodies[1]
        self.assertIn("current_power_mode =", rmvk_body)
        self.assertIn("current_power_volt =", rmvk_body)
        self.assertIn("target_power_volt =", rmvk_body)
        self.assertIn("reg_online = true;", rmvk_body)
        self.assertIn("last_reg_online = millis();", rmvk_body)


if __name__ == "__main__":
    unittest.main()
