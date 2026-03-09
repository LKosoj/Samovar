from pathlib import Path
import re
import subprocess
import unittest


BASELINE_NBK_COMMIT = "43e22996"
CURRENT_NBK_FILES = {
    "runtime": Path("modes/nbk/nbk_runtime.h"),
    "math": Path("modes/nbk/nbk_math.h"),
    "alarm": Path("modes/nbk/nbk_alarm.h"),
}


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


class NbkBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_texts = {
            name: path.read_text(encoding="utf-8")
            for name, path in CURRENT_NBK_FILES.items()
        }
        cls.baseline_text = _read_git_file(BASELINE_NBK_COMMIT, "nbk.h")

    def test_current_nbk_modules_exist(self) -> None:
        for path in CURRENT_NBK_FILES.values():
            self.assertTrue(path.exists(), f"{path} must exist")
        self.assertTrue(Path("nbk.h").exists())

    def test_nbk_math_matches_pre_split_baseline(self) -> None:
        signatures = [
            "float toPower(float value)",
            "float SQRT(float num)",
            "float fromPower(float value)",
        ]

        for signature in signatures:
            current_body = _normalize_cpp_body(
                _extract_function_body(self.current_texts["math"], signature)
            )
            baseline_body = _normalize_cpp_body(
                _extract_function_body(self.baseline_text, signature)
            )
            self.assertEqual(current_body, baseline_body, signature)

    def test_nbk_alarm_keeps_pre_split_control_flow(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["alarm"],
                "void check_alarm_nbk()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void check_alarm_nbk()",
            )
        )

        expected_fragments = [
            "if(!PowerOn&&!is_self_test&&valve_status&&WaterSensor.avgTemp<=TARGET_WATER_TEMP-20){open_valve(false,true);",
            "if(!PowerOn){return;}",
            "if(alarm_t_min>0&&alarm_t_min<=millis())alarm_t_min=0;",
            "if(PowerOn&&!valve_status&&TankSensor.avgTemp>=OPEN_VALVE_TANK_TEMP){open_valve(true,true);}",
            "if(valve_status){",
            "if(ACPSensor.avgTemp>SamSetup.SetACPTemp&&ACPSensor.avgTemp>WaterSensor.avgTemp)",
            "set_pump_speed_pid(SamSetup.SetWaterTemp+3);",
            "set_pump_speed_pid(WaterSensor.avgTemp);",
            "if(WFAlarmCount>WF_ALARM_COUNT&&PowerOn){set_buzzer(true);sam_command_sync=SAMOVAR_POWER;SendMsg((\"Аварийноеотключение!Прекращенаподачаводы.\"),ALARM_MSG);}",
            "if((WaterSensor.avgTemp>=ALARM_WATER_TEMP-5)&&PowerOn&&alarm_t_min==0){set_buzzer(true);SendMsg((\"Критическаятемператураводы!\"),WARNING_MSG);alarm_t_min=millis()+60000;}",
            "vTaskDelay(10/portTICK_PERIOD_MS);",
        ]

        for fragment in expected_fragments:
            self.assertIn(fragment, current_body)
            self.assertIn(fragment, baseline_body)

    def test_nbk_critical_alarm_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "bool check_nbk_critical_alarms()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "bool check_nbk_critical_alarms()",
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_nbk_math_keeps_expected_conversion_formulas(self) -> None:
        normalized_power = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["math"],
                "float toPower(float value)",
            )
        )
        normalized_sqrt = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["math"],
                "float SQRT(float num)",
            )
        )
        normalized_from_power = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["math"],
                "float fromPower(float value)",
            )
        )

        self.assertIn("floatR=SamSetup.HeaterResistant>1?SamSetup.HeaterResistant:18;", normalized_power)
        self.assertIn("returnvalue*value/R;", normalized_power)
        self.assertIn("guess=(guess+num/guess)/2;", normalized_sqrt)
        self.assertIn("while(abs(guess-prev_guess)>0.001);", normalized_sqrt)
        self.assertIn("staticfloatprev_W=0.0f;", normalized_from_power)
        self.assertIn("staticfloatprev_V=0.0f;", normalized_from_power)
        self.assertIn("prev_V=SQRT(value*R);", normalized_from_power)

    def test_nbk_alarm_keeps_expected_water_and_buzzer_paths(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["alarm"],
                "void check_alarm_nbk()",
            )
        )

        self.assertIn(
            "if(!PowerOn&&!is_self_test&&valve_status&&WaterSensor.avgTemp<=TARGET_WATER_TEMP-20){open_valve(false,true);",
            normalized,
        )
        self.assertIn(
            "if(PowerOn&&!valve_status&&TankSensor.avgTemp>=OPEN_VALVE_TANK_TEMP){open_valve(true,true);}",
            normalized,
        )
        self.assertIn(
            "if(WFAlarmCount>WF_ALARM_COUNT&&PowerOn){set_buzzer(true);sam_command_sync=SAMOVAR_POWER;SendMsg((\"Аварийноеотключение!Прекращенаподачаводы.\"),ALARM_MSG);}",
            normalized,
        )
        self.assertIn(
            "if((WaterSensor.avgTemp>=ALARM_WATER_TEMP-5)&&PowerOn&&alarm_t_min==0){set_buzzer(true);SendMsg((\"Критическаятемператураводы!\"),WARNING_MSG);alarm_t_min=millis()+60000;}",
            normalized,
        )

    def test_nbk_critical_alarm_keeps_expected_finish_paths(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "bool check_nbk_critical_alarms()",
            )
        )

        self.assertIn("if(program[ProgramNum].WType!=\"S\"){if(SteamSensor.avgTemp>98.0){", normalized)
        self.assertIn("SendMsg(\"Кончиласьбрага!Останов.\",ALARM_MSG);", normalized)
        self.assertIn("nbk_M=0;", normalized)
        self.assertIn("nbk_P=0;", normalized)
        self.assertIn("SetSpeed(0);", normalized)
        self.assertIn("run_nbk_program(CAPACITY_NUM*2);", normalized)
        self.assertIn("if(ACPSensor.avgTemp>60.0||WaterSensor.avgTemp>MAX_WATER_TEMP){", normalized)
        self.assertIn("if(millis()-overheat_start_time>60000){", normalized)
        self.assertIn("set_power(false);", normalized)
        self.assertIn("SendMsg(\"Недостаточноеохлаждение!Останов.\",ALARM_MSG);", normalized)


if __name__ == "__main__":
    unittest.main()
