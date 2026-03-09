from pathlib import Path
import re
import subprocess
import unittest


BASELINE_DISTILLER_COMMIT = "050a14f9"
CURRENT_DIST_FILES = {
    "runtime": Path("modes/dist/dist_runtime.h"),
    "alarm": Path("modes/dist/dist_alarm.h"),
    "predictor": Path("modes/dist/dist_time_predictor.h"),
}


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


def _extract_function_body_by_boundaries(
    text: str,
    signature: str,
    next_markers: list[str] | None,
) -> str:
    pattern = re.compile(rf"(?:inline\s+)?{re.escape(signature)}\s*\{{", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Function signature not found: {signature}")

    brace_start = text.find("{", match.start())
    if brace_start == -1:
        raise AssertionError(f"Function body start not found: {signature}")

    if next_markers:
        marker_positions = []
        for marker in next_markers:
            pos = text.find(marker, brace_start + 1)
            if pos != -1:
                marker_positions.append(pos)

        if not marker_positions:
            raise AssertionError(f"Next function marker not found: {signature}")

        segment = text[brace_start + 1:min(marker_positions)]
    else:
        segment = text[brace_start + 1:]

    body_end = segment.rfind("}")
    if body_end == -1:
        raise AssertionError(f"Function body end not found: {signature}")

    return segment[:body_end]


def _normalize_cpp_body(body: str) -> str:
    body = re.sub(r"//.*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"\s+", "", body)
    return body


class DistillerBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_texts = {
            name: path.read_text(encoding="utf-8")
            for name, path in CURRENT_DIST_FILES.items()
        }
        cls.baseline_text = _read_git_file(BASELINE_DISTILLER_COMMIT, "distiller.h")

    def test_current_dist_modules_exist(self) -> None:
        for path in CURRENT_DIST_FILES.values():
            self.assertTrue(path.exists(), f"{path} must exist")

    def test_distiller_runtime_matches_pre_split_baseline(self) -> None:
        current_runtime_signatures = {
            "void distiller_proc()": [
                "inline void distiller_finish()",
                "void distiller_finish()",
            ],
            "void distiller_finish()": [
                "inline void run_dist_program(uint8_t num)",
                "void run_dist_program(uint8_t num)",
            ],
            "void run_dist_program(uint8_t num)": None,
        }
        baseline_runtime_signatures = {
            "void distiller_proc()": ["void distiller_finish()"],
            "void distiller_finish()": ["void check_alarm_distiller()"],
            "void run_dist_program(uint8_t num)": ["void set_dist_program(String WProgram)"],
        }

        for signature in current_runtime_signatures:
            current_body = _normalize_cpp_body(
                _extract_function_body_by_boundaries(
                    self.current_texts["runtime"],
                    signature,
                    current_runtime_signatures[signature],
                )
            )
            baseline_body = _normalize_cpp_body(
                _extract_function_body_by_boundaries(
                    self.baseline_text,
                    signature,
                    baseline_runtime_signatures[signature],
                )
            )
            self.assertEqual(current_body, baseline_body, signature)

    def test_distiller_alarm_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["alarm"],
                "void check_alarm_distiller()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void check_alarm_distiller()",
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_distiller_predictor_matches_pre_split_baseline(self) -> None:
        signatures = [
            "void resetTimePredictor()",
            "void updateTimePredictor()",
            "float get_dist_remaining_time()",
            "float get_dist_predicted_total_time()",
        ]

        for signature in signatures:
            current_body = _normalize_cpp_body(
                _extract_function_body(self.current_texts["predictor"], signature)
            )
            baseline_body = _normalize_cpp_body(
                _extract_function_body(self.baseline_text, signature)
            )
            self.assertEqual(current_body, baseline_body, signature)

    def test_overheat_alarm_keeps_buzzer_activation(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["alarm"],
                "void check_alarm_distiller()",
            )
        )

        self.assertIn(
            "if(ACPSensor.avgTemp>=MAX_ACP_TEMP-5){set_buzzer(true);open_valve(true,true);}",
            normalized,
        )
        self.assertIn(
            "elseif(TankSensor.avgTemp>=OPEN_VALVE_TANK_TEMP&&PowerOn){set_buzzer(true);open_valve(true,true);}",
            normalized,
        )
        self.assertIn(
            "if((WaterSensor.avgTemp>=MAX_WATER_TEMP||ACPSensor.avgTemp>=MAX_ACP_TEMP)&&PowerOn){set_buzzer(true);set_power(false);",
            normalized,
        )

    def test_distiller_heat_control_keeps_power_invariant(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void distiller_proc()",
            )
        )

        self.assertIn("if(!PowerOn){", normalized)
        self.assertIn("set_power(true);", normalized)
        self.assertIn("set_power_mode(POWER_SPEED_MODE);", normalized)
        self.assertIn("if(TankSensor.avgTemp>=SamSetup.DistTemp){distiller_finish();}", normalized)

    def test_time_predictor_keeps_expected_calculation_formulas(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["predictor"],
                "void updateTimePredictor()",
            )
        )

        self.assertIn("timePredictor.tempChangeRate=(currentTemp-timePredictor.lastTemp)/dtMin;", normalized)
        self.assertIn(
            "floatalcoholChangeRate=(dtMin>0)?(alcoholDelta/((currentTime-timePredictor.startTime)/60000.0f)):0;",
            normalized,
        )
        self.assertIn(
            "timePredictor.predictedTotalTime=elapsedMinutes+timePredictor.remainingTime;",
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
