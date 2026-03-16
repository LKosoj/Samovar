from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


MENU_ACTIONS_HEADER = Path("ui/menu/actions.h")
MODE_CODES_HEADER = Path("src/core/state/mode_codes.h")


def _extract_function(text: str, signature: str) -> str:
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
                return text[match.start():index + 1]

    raise AssertionError(f"Function body end not found: {signature}")


class MenuActionsBehaviorTest(unittest.TestCase):
    def test_debug_harness_executes_extracted_menu_actions(self) -> None:
        compiler = shutil.which("g++") or shutil.which("c++")
        self.assertIsNotNone(compiler, "C++ compiler is required for menu actions harness test")

        header_text = MENU_ACTIONS_HEADER.read_text(encoding="utf-8")
        mode_codes_text = MODE_CODES_HEADER.read_text(encoding="utf-8")
        extracted_helpers = "\n\n".join(
            _extract_function(mode_codes_text, signature)
            for signature in [
                "bool startval_is_active_non_calibration(int16_t value)",
            ]
        )
        extracted_functions = "\n\n".join(
            _extract_function(header_text, signature)
            for signature in [
                "void menu_setup()",
                "void setup_go_back()",
                "void menu_pump_speed_up()",
                "void menu_pump_speed_down()",
                "void set_delta_steam_temp_up()",
                "void set_delta_steam_temp_down()",
                "void stepper_step_ml_down()",
                "void menu_program()",
                "void menu_program_back()",
                "void samovar_reset()",
                "void menu_get_power()",
                "void menu_pause()",
                "void menu_calibrate()",
                "void menu_calibrate_down()",
                "void menu_samovar_start()",
                "void menu_reset_wifi()",
            ]
        )

        harness = textwrap.dedent(
            f"""
            #include <cstdint>
            #include <cstdio>
            #include <cstring>
            #include <iomanip>
            #include <iostream>
            #include <string>

            using uint8_t = std::uint8_t;

            class String {{
             public:
              String() = default;
              String(const char* text) : value_(text == nullptr ? "" : text) {{}}
              String(int number) : value_(std::to_string(number)) {{}}
              String(const std::string& text) : value_(text) {{}}
              String(const String&) = default;
              String& operator=(const String&) = default;

              String& operator=(const char* text) {{
                value_ = text == nullptr ? "" : text;
                return *this;
              }}

              const char* c_str() const {{
                return value_.c_str();
              }}

              friend String operator+(const String& left, const String& right) {{
                return String(left.value_ + right.value_);
              }}

             private:
              std::string value_;
            }};

            static constexpr int STEPPER_MAX_SPEED = 120;
            static constexpr int CAPACITY_NUM = 3;

            enum {{
              SAMOVAR_RECTIFICATION_MODE = 0,
              SAMOVAR_BEER_MODE = 1,
              SAMOVAR_DISTILLATION_MODE = 2,
              SAMOVAR_BK_MODE = 3,
              SAMOVAR_NBK_MODE = 4,
            }};

            enum {{
              SAMOVAR_NONE = 0,
              SAMOVAR_POWER = 1,
              SAMOVAR_BEER = 2,
              SAMOVAR_DISTILLATION = 3,
              SAMOVAR_BK = 4,
              SAMOVAR_NBK = 5,
            }};

            static constexpr int SAMOVAR_STARTVAL_RECT_IDLE = 0;
            static constexpr int SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING = 1;
            static constexpr int SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE = 2;
            static constexpr int SAMOVAR_STARTVAL_RECT_STOPPED = 3;
            static constexpr int SAMOVAR_STARTVAL_CALIBRATION = 100;

            static const char menu_text_continue[] = "Continue";
            static const char menu_text_pause[] = "Pause";
            static const char menu_text_stop[] = "Stop";
            static const char menu_text_start[] = "Start";
            static const char menu_text_program_number_first[] = "Prg No 1";
            static const char menu_text_program_number_prefix[] = "Prg No ";
            static const char menu_text_program_finish[] = "Prg finish";
            static const char menu_text_stopped[] = "Stoped";
            static const char menu_text_stopped_padded[] = "Stoped             ";
            static const char menu_text_power_on[] = "ON";

            struct SamSetupStruct {{
              float DeltaSteamTemp = 10.0f;
              float DeltaPipeTemp = 20.0f;
              float DeltaWaterTemp = 30.0f;
              float DeltaTankTemp = 40.0f;
              float SetSteamTemp = 50.0f;
              float SetPipeTemp = 60.0f;
              float SetWaterTemp = 70.0f;
              float SetTankTemp = 80.0f;
              int StepperStepMl = 0;
              String TimeZone;
            }};

            struct MockStepper {{
              int speed = 100;

              int getSpeed() const {{
                return speed;
              }}
            }};

            struct MockEsp {{
              int restart_calls = 0;

              void restart() {{
                restart_calls++;
              }}
            }};

            SamSetupStruct SamSetup;
            MockStepper stepper;
            MockEsp ESP;

            char startval_text_val[20];
            char* power_text_ptr = nullptr;
            char* pause_text_ptr = nullptr;
            char* calibrate_text_ptr = nullptr;

            int Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
            int sam_command_sync = SAMOVAR_NONE;
            int t_min = 7;
            int ProgramNum = 0;
            int ProgramLen = 4;
            int startval = SAMOVAR_STARTVAL_RECT_IDLE;
            float multiplier = 1.0f;
            float ActualVolumePerHour = 1.23f;
            bool PowerOn = false;
            bool PauseOn = false;
            bool StepperMoving = false;
            bool program_Wait = true;

            int reset_focus_calls = 0;
            int menu_update_calls = 0;
            int last_menu_screen = -1;
            int save_profile_calls = 0;
            int read_config_calls = 0;
            int pause_withdrawal_calls = 0;
            bool last_pause_withdrawal_arg = false;
            int detector_resume_calls = 0;
            int pump_calibrate_calls = 0;
            int last_pump_calibrate_speed = -1;
            float last_speed_rate_input = -1.0f;
            float last_set_pump_speed = -1.0f;
            bool last_set_pump_force = false;
            int set_pump_speed_calls = 0;
            int run_program_calls = 0;
            int last_run_program = -1;
            int create_data_calls = 0;
            int reset_sensor_counter_calls = 0;
            int clear_wifi_credentials_calls = 0;

            template <std::size_t N>
            void copyStringSafe(char (&dst)[N], const String& src) {{
              std::snprintf(dst, N, "%s", src.c_str());
            }}

            void reset_focus() {{
              reset_focus_calls++;
            }}

            void set_menu_screen(uint8_t param) {{
              last_menu_screen = param;
            }}

            void menu_update() {{
              menu_update_calls++;
            }}

            void save_profile_nvs() {{
              save_profile_calls++;
            }}

            void read_config() {{
              read_config_calls++;
            }}

            void pause_withdrawal(bool pause) {{
              pause_withdrawal_calls++;
              last_pause_withdrawal_arg = pause;
              PauseOn = pause;
            }}

            void detector_on_manual_resume() {{
              detector_resume_calls++;
            }}

            void pump_calibrate(int speed) {{
              pump_calibrate_calls++;
              last_pump_calibrate_speed = speed;
              stepper.speed = speed;
            }}

            float get_speed_from_rate(float volume_per_hour) {{
              last_speed_rate_input = volume_per_hour;
              return volume_per_hour * 10.0f;
            }}

            void set_pump_speed(float speed, bool force) {{
              set_pump_speed_calls++;
              last_set_pump_speed = speed;
              last_set_pump_force = force;
            }}

            void run_program(uint8_t num) {{
              run_program_calls++;
              last_run_program = num;
            }}

            void create_data() {{
              create_data_calls++;
            }}

            void reset_sensor_counter() {{
              reset_sensor_counter_calls++;
            }}

            void clear_wifi_credentials() {{
              clear_wifi_credentials_calls++;
            }}

            {extracted_helpers}

            {extracted_functions}

            static void reset_state() {{
              SamSetup = SamSetupStruct();
              stepper = MockStepper();
              ESP = MockEsp();

              std::snprintf(startval_text_val, sizeof(startval_text_val), "%s", "Boot");
              power_text_ptr = (char*)menu_text_stopped;
              pause_text_ptr = (char*)menu_text_pause;
              calibrate_text_ptr = (char*)menu_text_stop;

              Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
              sam_command_sync = SAMOVAR_NONE;
              t_min = 7;
              ProgramNum = 0;
              ProgramLen = 4;
              startval = SAMOVAR_STARTVAL_RECT_IDLE;
              multiplier = 1.0f;
              ActualVolumePerHour = 1.23f;
              PowerOn = false;
              PauseOn = false;
              StepperMoving = false;
              program_Wait = true;

              reset_focus_calls = 0;
              menu_update_calls = 0;
              last_menu_screen = -1;
              save_profile_calls = 0;
              read_config_calls = 0;
              pause_withdrawal_calls = 0;
              last_pause_withdrawal_arg = false;
              detector_resume_calls = 0;
              pump_calibrate_calls = 0;
              last_pump_calibrate_speed = -1;
              last_speed_rate_input = -1.0f;
              last_set_pump_speed = -1.0f;
              last_set_pump_force = false;
              set_pump_speed_calls = 0;
              run_program_calls = 0;
              last_run_program = -1;
              create_data_calls = 0;
              reset_sensor_counter_calls = 0;
              clear_wifi_credentials_calls = 0;
            }}

            int main() {{
              std::cout << std::fixed << std::setprecision(2);

              reset_state();
              menu_setup();
              std::cout << "setup|" << reset_focus_calls << "|" << last_menu_screen << "\\n";

              reset_state();
              setup_go_back();
              std::cout << "back|" << reset_focus_calls << "|" << last_menu_screen << "|"
                        << save_profile_calls << "|" << read_config_calls << "\\n";

              reset_state();
              multiplier = 2.0f;
              menu_pump_speed_up();
              const float pump_up_rate = last_speed_rate_input;
              const float pump_up_speed = last_set_pump_speed;
              menu_pump_speed_down();
              std::cout << "pump|" << pump_up_rate << "|" << pump_up_speed << "|"
                        << last_speed_rate_input << "|" << last_set_pump_speed << "|"
                        << last_set_pump_force << "\\n";

              reset_state();
              multiplier = 2.0f;
              set_delta_steam_temp_up();
              set_delta_steam_temp_down();
              stepper_step_ml_down();
              std::cout << "adjust|" << SamSetup.DeltaSteamTemp << "|" << SamSetup.StepperStepMl << "\\n";

              reset_state();
              menu_program();
              menu_program_back();
              std::cout << "program_nav|" << reset_focus_calls << "|" << last_menu_screen << "\\n";

              reset_state();
              Samovar_Mode = SAMOVAR_BEER_MODE;
              menu_get_power();
              std::cout << "power_beer_off|" << reset_focus_calls << "|" << last_menu_screen << "|"
                        << sam_command_sync << "|" << reset_sensor_counter_calls << "\\n";

              reset_state();
              PowerOn = true;
              menu_get_power();
              std::cout << "power_rect_on|" << reset_focus_calls << "|" << last_menu_screen << "|"
                        << sam_command_sync << "|" << reset_sensor_counter_calls << "|"
                        << power_text_ptr << "\\n";

              reset_state();
              menu_pause();
              std::cout << "pause_start|" << PauseOn << "|" << pause_text_ptr << "|"
                        << detector_resume_calls << "\\n";

              reset_state();
              PauseOn = true;
              menu_pause();
              std::cout << "pause_resume|" << PauseOn << "|" << pause_text_ptr << "|"
                        << t_min << "|" << program_Wait << "|" << detector_resume_calls << "\\n";

              reset_state();
              menu_calibrate();
              std::cout << "calibrate|" << startval << "|" << calibrate_text_ptr << "|"
                        << last_pump_calibrate_speed << "|" << pump_calibrate_calls << "\\n";

              reset_state();
              startval = SAMOVAR_STARTVAL_CALIBRATION;
              menu_calibrate_down();
              std::cout << "calibrate_down|" << stepper.speed << "|" << last_pump_calibrate_speed << "|"
                        << pump_calibrate_calls << "\\n";

              reset_state();
              PowerOn = true;
              menu_samovar_start();
              std::cout << "start_first|" << startval << "|" << ProgramNum << "|"
                        << last_run_program << "|" << create_data_calls << "|"
                        << startval_text_val << "|" << reset_focus_calls << "|"
                        << menu_update_calls << "\\n";

              reset_state();
              menu_reset_wifi();
              std::cout << "wifi|" << clear_wifi_credentials_calls << "|" << ESP.restart_calls << "\\n";

              reset_state();
              sam_command_sync = SAMOVAR_BEER;
              samovar_reset();
              std::cout << "reset|" << reset_focus_calls << "|" << last_menu_screen << "|"
                        << sam_command_sync << "|" << reset_sensor_counter_calls << "|"
                        << power_text_ptr << "\\n";
              return 0;
            }}
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_path = tmpdir_path / "menu_actions_harness.cpp"
            binary_path = tmpdir_path / "menu_actions_harness"
            source_path.write_text(harness, encoding="utf-8")

            subprocess.run(
                [compiler, "-std=c++17", str(source_path), "-o", str(binary_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            completed = subprocess.run(
                [str(binary_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            completed.stdout.strip().splitlines(),
            [
                "setup|1|1",
                "back|1|2|1|1",
                "pump|1.25|12.50|1.21|12.10|1",
                "adjust|10.00|0",
                "program_nav|2|1",
                "power_beer_off|1|2|2|0",
                "power_rect_on|2|3|0|1|ON",
                "pause_start|1|Continue|0",
                "pause_resume|0|Pause|0|0|1",
                "calibrate|100|Start|120|1",
                "calibrate_down|90|90|1",
                "start_first|1|0|0|1|Prg No 1|1|1",
                "wifi|1|1",
                "reset|1|3|0|1|ON",
            ],
        )


if __name__ == "__main__":
    unittest.main()
