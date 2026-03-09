from pathlib import Path
import re
import subprocess
import unittest


BASELINE_BEER_COMMIT = "43e22996"
CURRENT_BEER_FILES = {
    "runtime": Path("modes/beer/beer_runtime.h"),
    "heater": Path("modes/beer/beer_heater.h"),
    "mixer": Path("modes/beer/beer_mixer.h"),
    "autotune": Path("modes/beer/beer_autotune.h"),
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


class BeerBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_texts = {
            name: path.read_text(encoding="utf-8")
            for name, path in CURRENT_BEER_FILES.items()
        }
        cls.baseline_text = _read_git_file(BASELINE_BEER_COMMIT, "beer.h")

    def test_current_beer_modules_exist(self) -> None:
        for path in CURRENT_BEER_FILES.values():
            self.assertTrue(path.exists(), f"{path} must exist")
        self.assertFalse(Path("beer.h").exists())

    def test_beer_heater_matches_pre_split_baseline(self) -> None:
        signatures = [
            "void set_heater(double dutyCycle)",
            "void setHeaterPosition(bool state)",
        ]

        for signature in signatures:
            current_body = _normalize_cpp_body(
                _extract_function_body(self.current_texts["heater"], signature)
            )
            baseline_body = _normalize_cpp_body(
                _extract_function_body(self.baseline_text, signature)
            )
            self.assertEqual(current_body, baseline_body, signature)

    def test_beer_heater_state_keeps_pre_split_logic(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["heater"],
                "void set_heater_state(float setpoint, float temp)",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void set_heater_state(float setpoint, float temp)",
            )
        )

        self.assertIn(
            "if(setpoint-temp>ACCELERATION_HEATER_DELTA&&!tuning){if(!acceleration_heater){acceleration_heater=true;digitalWrite(RELE_CHANNEL4,SamSetup.rele4);}}",
            current_body,
        )
        self.assertIn(
            "digitalWrite(RELE_CHANNEL4,!SamSetup.rele4);acceleration_heater=false;",
            current_body,
        )
        self.assertIn("if(setpoint-temp>HEAT_DELTA&&!tuning){heater_state=true;", current_body)
        self.assertIn("vTaskDelay(5/portTICK_PERIOD_MS);set_current_power(SamSetup.BVolt);", current_body)
        self.assertIn("heaterPID.SetMode(AUTOMATIC);Setpoint=setpoint;Input=temp;", current_body)
        self.assertIn("if(aTune.Runtime()){FinishAutoTune();}", current_body)
        self.assertIn("heaterPID.Compute();", current_body)
        self.assertIn("set_heater(Output/100);", current_body)
        self.assertIn(
            "digitalWrite(RELE_CHANNEL4,!SamSetup.rele4);acceleration_heater=false;",
            baseline_body,
        )

    def test_beer_mixer_matches_pre_split_baseline(self) -> None:
        signatures = [
            "void set_mixer(bool On)",
            "void HopStepperStep()",
        ]

        for signature in signatures:
            current_body = _normalize_cpp_body(
                _extract_function_body(self.current_texts["mixer"], signature)
            )
            baseline_body = _normalize_cpp_body(
                _extract_function_body(self.baseline_text, signature)
            )
            self.assertEqual(current_body, baseline_body, signature)

    def test_beer_mixer_state_actions_keep_pre_split_logic(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["mixer"],
                "void set_mixer_state(bool state, bool dir)",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void set_mixer_state(bool state, bool dir)",
            )
        )

        self.assertIn("mixer_status=state;", current_body)
        self.assertIn(
            "if(BitIsSet(program[ProgramNum].capacity_num,0)){digitalWrite(RELE_CHANNEL2,SamSetup.rele2);",
            current_body,
        )
        self.assertIn("if(use_I2C_dev==1){inttm=abs(program[ProgramNum].Volume);", current_body)
        self.assertIn("if(tm==0)tm=10;", current_body)
        self.assertIn("set_stepper_by_time(20,dir,tm);", current_body)
        self.assertIn(
            "if(BitIsSet(program[ProgramNum].capacity_num,1)){",
            current_body,
        )
        self.assertIn("pump_pwm.write(1023);", current_body)
        self.assertIn("set_mixer_pump_target(1);", current_body)
        self.assertIn("digitalWrite(RELE_CHANNEL2,!SamSetup.rele2);", current_body)
        self.assertIn("pump_pwm.write(0);", current_body)
        self.assertIn("set_stepper_by_time(0,0,0);", current_body)
        self.assertIn("set_mixer_pump_target(0);", current_body)
        self.assertIn(
            "if(BitIsSet(program[ProgramNum].capacity_num,0)){digitalWrite(RELE_CHANNEL2,SamSetup.rele2);",
            baseline_body,
        )

    def test_beer_mixer_state_machine_keeps_pre_split_logic(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["mixer"],
                "void check_mixer_state()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void check_mixer_state()",
            )
        )

        self.assertIn(
            "if(alarm_c_min>0&&alarm_c_min<=millis()){alarm_c_min=0;alarm_c_low_min=0;set_mixer_state(false,false);}",
            current_body,
        )
        self.assertIn(
            "if((alarm_c_low_min>0)&&(alarm_c_low_min<=millis())){alarm_c_low_min=0;if(alarm_c_min>0)",
            current_body,
        )
        self.assertIn(
            "if(alarm_c_low_min==0&&alarm_c_min==0){alarm_c_low_min=millis()+program[ProgramNum].Volume*1000;",
            current_body,
        )
        self.assertIn(
            "if(program[ProgramNum].Power>0)alarm_c_min=alarm_c_low_min+program[ProgramNum].Power*1000;",
            current_body,
        )
        self.assertIn("currentstepcnt++;booldir=false;", current_body)
        self.assertIn("if(currentstepcnt%2==0&&program[ProgramNum].Speed<0)dir=true;", current_body)
        self.assertIn("set_mixer_state(true,dir);", current_body)
        self.assertIn(
            "else{if(mixer_status){set_mixer_state(false,false);}}",
            current_body,
        )
        self.assertIn(
            "if(alarm_c_min>0&&alarm_c_min<=millis()){alarm_c_min=0;alarm_c_low_min=0;set_mixer_state(false,false);}",
            baseline_body,
        )

    def test_beer_autotune_matches_pre_split_baseline(self) -> None:
        signatures = [
            "void StartAutoTune()",
            "void FinishAutoTune()",
        ]

        for signature in signatures:
            current_body = _normalize_cpp_body(
                _extract_function_body(self.current_texts["autotune"], signature)
            )
            baseline_body = _normalize_cpp_body(
                _extract_function_body(self.baseline_text, signature)
            )
            self.assertEqual(current_body, baseline_body, signature)

    def test_run_beer_program_keeps_autotune_entrypoint(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void run_beer_program(uint8_t num)",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void run_beer_program(uint8_t num)",
            )
        )
        self.assertEqual(current_body, baseline_body)
        self.assertIn('if(program[ProgramNum].WType=="A"){StartAutoTune();}', current_body)

    def test_beer_proc_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void beer_proc()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void beer_proc()",
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_beer_finish_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void beer_finish()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void beer_finish()",
            )
        )
        self.assertEqual(current_body, baseline_body)

    def test_check_alarm_beer_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void check_alarm_beer()",
            )
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(
                self.baseline_text,
                "void check_alarm_beer()",
            )
        )

        expected_fragments = [
            'if(program[ProgramNum].WType!="C"&&program[ProgramNum].WType!="F"&&valve_status&&PowerOn&&program[ProgramNum].WType!="L"){open_valve(false,false);}',
            'if(program[ProgramNum].WType=="L"){return;}',
            'if(program[ProgramNum].WType=="W"){if(begintime==0){begintime=millis();setHeaterPosition(false);open_valve(false,false);}check_mixer_state();return;}',
            'if(program[ProgramNum].WType=="A"){if(tuning){set_heater_state(program[ProgramNum].Temp,temp);}else{beer_finish();}}',
            'if(program[ProgramNum].WType=="M"||program[ProgramNum].WType=="P"){set_heater_state(program[ProgramNum].Temp,temp);}',
            'if(program[ProgramNum].WType=="F"){if(temp<program[ProgramNum].Temp-tempDelta){if(valve_status){open_valve(false,false);}set_heater_state(program[ProgramNum].Temp,temp);}',
            'elseif(temp>program[ProgramNum].Temp+tempDelta)',
            'if(program[ProgramNum].WType=="M"&&temp>=program[ProgramNum].Temp-tempDelta){',
            'if(program[ProgramNum].WType=="P"&&temp>=program[ProgramNum].Temp-tempDelta){',
            'if(program[ProgramNum].WType=="C"){if(begintime==0){begintime=millis();setHeaterPosition(false);open_valve(true,false);',
            'if(program[ProgramNum].WType=="B"){',
            'if(begintime>0&&(program[ProgramNum].WType=="B"||program[ProgramNum].WType=="P")&&((millis()-begintime)/1000/60>=program[ProgramNum].Time)){run_beer_program(ProgramNum+1);}',
            'check_mixer_state();',
            'vTaskDelay(10/portTICK_PERIOD_MS);',
        ]

        for fragment in expected_fragments:
            self.assertIn(fragment, current_body)
            self.assertIn(fragment, baseline_body)

    def test_autotune_initialization_keeps_expected_state_changes(self) -> None:
        body = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["autotune"],
                "void StartAutoTune()",
            )
        )

        self.assertIn("ATuneModeRemember=heaterPID.GetMode();", body)
        self.assertIn("Output=50;", body)
        self.assertIn("aTune.SetControlType(1);", body)
        self.assertIn("aTune.SetNoiseBand(aTuneNoise);", body)
        self.assertIn("aTune.SetOutputStep(aTuneStep);", body)
        self.assertIn("aTune.SetLookbackSec((int)aTuneLookBack);", body)
        self.assertIn("tuning=true;", body)

    def test_beer_proc_keeps_mode_start_transition(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void beer_proc()",
            )
        )

        self.assertIn("if(SamovarStatusInt!=2000)return;", normalized)
        self.assertIn("if(startval==2000&&!PowerOn){", normalized)
        self.assertIn("resetBoilingDetector();", normalized)
        self.assertIn("create_data();", normalized)
        self.assertIn("PowerOn=true;", normalized)
        self.assertIn("set_power(true);", normalized)
        self.assertIn("run_beer_program(0);", normalized)

    def test_beer_finish_keeps_mode_shutdown_transition(self) -> None:
        normalized = _normalize_cpp_body(
            _extract_function_body(
                self.current_texts["runtime"],
                "void beer_finish()",
            )
        )

        self.assertIn("resetBoilingDetector();", normalized)
        self.assertIn("set_mixer_state(false,false);", normalized)
        self.assertIn("setHeaterPosition(false);", normalized)
        self.assertIn("PowerOn=false;", normalized)
        self.assertIn("heater_state=false;", normalized)
        self.assertIn("startval=0;", normalized)
        self.assertIn(
            'stop_process("Программазатираниязавершена");',
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
