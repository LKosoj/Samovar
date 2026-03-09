from pathlib import Path
import re
import subprocess
import unittest


BASELINE_BK_COMMIT = "43e22996"
CURRENT_BK_FILES = {
    "runtime": Path("modes/bk/bk_runtime.h"),
    "alarm": Path("modes/bk/bk_alarm.h"),
    "finish": Path("modes/bk/bk_finish.h"),
    "water_control": Path("modes/bk/bk_water_control.h"),
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


def _normalize_cpp_body(body: str) -> str:
    body = re.sub(r"//.*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"\s+", "", body)
    return body


class BkBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_texts = {
            name: path.read_text(encoding="utf-8")
            for name, path in CURRENT_BK_FILES.items()
        }
        cls.baseline_text = _read_git_file(BASELINE_BK_COMMIT, "BK.h")

    def test_current_bk_modules_exist(self) -> None:
        self.assertFalse(Path("BK.h").exists())
        for path in CURRENT_BK_FILES.values():
            self.assertTrue(path.exists(), f"{path} must exist")

    def test_bk_runtime_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void bk_proc()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void bk_proc()",
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_bk_alarm_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["alarm"],
                "void check_alarm_bk()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void check_alarm_bk()",
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_bk_finish_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["finish"],
                "void bk_finish()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void bk_finish()",
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_bk_water_control_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["water_control"],
                "void set_water_temp(float duty)",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void set_water_temp(float duty)",
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_bk_runtime_keeps_heat_and_finish_transitions(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void bk_proc()",
            )
        )

        self.assertIn("if(!PowerOn){", normalized)
        self.assertIn("set_power(true);", normalized)
        self.assertIn("set_power_mode(POWER_SPEED_MODE);", normalized)
        self.assertIn("create_data();", normalized)
        self.assertIn("SteamSensor.Start_Pressure=bme_pressure;", normalized)
        self.assertIn(
            'SendMsg(("Включеннагревбражнойколонны"),NOTIFY_MSG);',
            normalized,
        )
        self.assertIn(
            "if(TankSensor.avgTemp>=SamSetup.DistTemp){bk_finish();}",
            normalized,
        )

    def test_bk_alarm_keeps_expected_emergency_state_transitions(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["alarm"],
                "void check_alarm_bk()",
            )
        )

        self.assertIn(
            "if(PowerOn&&!valve_status&&TankSensor.avgTemp>=OPEN_VALVE_TANK_TEMP){open_valve(true,true);",
            normalized,
        )
        self.assertIn(
            "if(current_power_mode==POWER_SPEED_MODE&&(check_boiling()||SteamSensor.avgTemp>CHANGE_POWER_MODE_STEAM_TEMP||PipeSensor.avgTemp>CHANGE_POWER_MODE_STEAM_TEMP)){",
            normalized,
        )
        self.assertIn(
            "if((WaterSensor.avgTemp>=MAX_WATER_TEMP)&&PowerOn){set_buzzer(true);set_power(false);",
            normalized,
        )
        self.assertIn(
            "if(WFAlarmCount>WF_ALARM_COUNT&&PowerOn){set_buzzer(true);sam_command_sync=SAMOVAR_POWER;",
            normalized,
        )
        self.assertIn(
            "alarm_t_min=millis()+30000;",
            normalized,
        )
        self.assertIn(
            "set_current_power(target_power_volt-5);",
            normalized,
        )

    def test_bk_finish_keeps_expected_shutdown_transition(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["finish"],
                "void bk_finish()",
            )
        )

        self.assertIn(
            'stop_process("Работабражнойколоннызавершена");',
            normalized,
        )

    def test_bk_water_control_keeps_expected_pump_and_notify_paths(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["water_control"],
                "void set_water_temp(float duty)",
            )
        )

        self.assertIn("bk_pwm=duty;", normalized)
        self.assertIn("if(pump_started){pump_pwm.write(bk_pwm);water_pump_speed=bk_pwm;}", normalized)
        self.assertIn(
            'SendMsg(("Управлениенасосомнеподдерживаетсявашимоборудованием"),NOTIFY_MSG);',
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
