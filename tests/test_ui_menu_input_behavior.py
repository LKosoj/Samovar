from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


MENU_INPUT_HEADER = Path("ui/menu/input.h")


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


class MenuInputBehaviorTest(unittest.TestCase):
    def test_debug_harness_executes_extracted_input_logic(self) -> None:
        compiler = shutil.which("g++") or shutil.which("c++")
        self.assertIsNotNone(compiler, "C++ compiler is required for menu input harness test")

        header_text = MENU_INPUT_HEADER.read_text(encoding="utf-8")
        extracted_functions = "\n\n".join(
            _extract_function(header_text, signature)
            for signature in [
                "void reset_focus()",
                "void menu_previous_screen()",
                "void menu_next_screen()",
                "void menu_switch_focus()",
                "void menu_reset_lcd()",
                "void change_screen(LiquidScreen* screen)",
                "void menu_update()",
                "void menu_softUpdate()",
                "void set_menu_screen(uint8_t param)",
                "void bind_menu_input_handlers()",
                "void encoder_getvalue()",
                "void setupMenu()",
            ]
        )

        harness = textwrap.dedent(
            f"""
            #include <cstdint>
            #include <deque>
            #include <iostream>
            #include <string>
            #include <vector>

            #define LCD_UPDATE_TIMEOUT 200
            #define LCD_COLUMNS 20
            #define LCD_ROWS 4

            using TickType_t = int;

            static constexpr int pdTRUE = 1;
            static constexpr int portTICK_RATE_MS = 1;
            static constexpr int portTICK_PERIOD_MS = 1;
            static constexpr int SAMOVAR_STARTVAL_RECT_IDLE = 0;
            static constexpr int SAMOVAR_STARTVAL_CALIBRATION = 100;

            struct LiquidScreen {{
              std::string name;
              bool hidden = false;

              explicit LiquidScreen(const char* screen_name) : name(screen_name) {{}}

              void hide(bool value) {{
                hidden = value;
              }}
            }};

            struct MockLine {{
              std::string name;
              std::vector<int> attached_slots;

              explicit MockLine(const char* line_name) : name(line_name) {{}}

              void attach_function(int slot, void (*)()) {{
                attached_slots.push_back(slot);
              }}
            }};

            struct MockMenu {{
              std::deque<bool> callable1_results;
              std::deque<bool> callable2_results;
              std::vector<int> called_functions;
              std::vector<std::string> changed_screens;
              int previous_screen_calls = 0;
              int next_screen_calls = 0;
              int switch_focus_calls = 0;
              int update_calls = 0;
              int soft_update_calls = 0;

              bool is_callable(int slot) {{
                auto& queue = slot == 1 ? callable1_results : callable2_results;
                if (queue.empty()) {{
                  return false;
                }}
                bool value = queue.front();
                queue.pop_front();
                return value;
              }}

              void switch_focus() {{
                switch_focus_calls++;
              }}

              void previous_screen() {{
                previous_screen_calls++;
              }}

              void next_screen() {{
                next_screen_calls++;
              }}

              void change_screen(LiquidScreen* screen) {{
                changed_screens.push_back(screen->name);
              }}

              void update() {{
                update_calls++;
              }}

              void softUpdate() {{
                soft_update_calls++;
              }}

              void call_function(int slot) {{
                called_functions.push_back(slot);
              }}
            }};

            struct MockLcd {{
              int begin_calls = 0;
              int init_calls = 0;
              int backlight_calls = 0;
              int clear_calls = 0;

              void begin(int, int) {{
                begin_calls++;
              }}

              void init() {{
                init_calls++;
              }}

              void backlight() {{
                backlight_calls++;
              }}

              void clear() {{
                clear_calls++;
              }}
            }};

            struct MockEncoder {{
              bool right = false;
              bool left = false;
              bool right_hold = false;
              bool left_hold = false;
              bool click = false;

              bool isRight() {{
                bool value = right;
                right = false;
                return value;
              }}

              bool isLeft() {{
                bool value = left;
                left = false;
                return value;
              }}

              bool isRightH() {{
                bool value = right_hold;
                right_hold = false;
                return value;
              }}

              bool isLeftH() {{
                bool value = left_hold;
                left_hold = false;
                return value;
              }}

              bool isClick() {{
                bool value = click;
                click = false;
                return value;
              }}
            }};

            static int xI2CSemaphore = 1;
            static int semaphore_take_calls = 0;
            static int semaphore_give_calls = 0;
            static int delay_ticks = 0;
            static unsigned long fake_millis = 0;
            static int multiplier = 0;
            static int startval = SAMOVAR_STARTVAL_RECT_IDLE;
            static unsigned long CurMin = 0;
            static unsigned long OldMin = 0;
            static int menu_calibrate_calls = 0;
            static int menu_calibrate_down_calls = 0;
            static int setup_menu_screen_decimal_places_calls = 0;
            static int setup_menu_screen_progmem_calls = 0;
            static int register_menu_screens_calls = 0;

            MockMenu main_menu1;
            MockLcd lcd;
            MockEncoder encoder;

            LiquidScreen welcome_screen("welcome_screen");
            LiquidScreen main_screen("main_screen");
            LiquidScreen main_screen1("main_screen1");
            LiquidScreen main_screen2("main_screen2");
            LiquidScreen main_screen4("main_screen4");
            LiquidScreen main_screen5("main_screen5");
            LiquidScreen setup_temp_screen("setup_temp_screen");
            LiquidScreen setup_set_temp_screen("setup_set_temp_screen");
            LiquidScreen setup_stepper_settings("setup_stepper_settings");
            LiquidScreen setup_program_settings("setup_program_settings");
            LiquidScreen setup_program_back("setup_program_back");
            LiquidScreen setup_back_screen("setup_back_screen");

            MockLine lql_start("lql_start");
            MockLine lql_reset("lql_reset");
            MockLine lql_pump_speed("lql_pump_speed");
            MockLine lql_setup("lql_setup");
            MockLine lql_setup_steam_temp("lql_setup_steam_temp");
            MockLine lql_setup_pipe_temp("lql_setup_pipe_temp");
            MockLine lql_setup_water_temp("lql_setup_water_temp");
            MockLine lql_setup_tank_temp("lql_setup_tank_temp");
            MockLine lql_setup_set_steam_temp("lql_setup_set_steam_temp");
            MockLine lql_setup_set_pipe_temp("lql_setup_set_pipe_temp");
            MockLine lql_setup_set_water_temp("lql_setup_set_water_temp");
            MockLine lql_setup_set_tank_temp("lql_setup_set_tank_temp");
            MockLine lql_setup_stepper_stepper_step_ml("lql_setup_stepper_stepper_step_ml");
            MockLine lql_setup_stepper_calibrate("lql_setup_stepper_calibrate");
            MockLine lql_setup_stepper_program("lql_setup_stepper_program");
            MockLine lql_setup_program_back_line("lql_setup_program_back_line");
            MockLine lql_setup_program_reset_wifi("lql_setup_program_reset_wifi");
            MockLine lql_back_line("lql_back_line");
            MockLine lql_get_power("lql_get_power");
            MockLine lql_pause("lql_pause");

            int xSemaphoreTake(int, TickType_t) {{
              semaphore_take_calls++;
              return pdTRUE;
            }}

            void xSemaphoreGive(int) {{
              semaphore_give_calls++;
            }}

            void vTaskDelay(int ticks) {{
              delay_ticks += ticks;
            }}

            unsigned long millis() {{
              return fake_millis;
            }}

            void menu_samovar_start() {{}}
            void samovar_reset() {{}}
            void menu_pump_speed_up() {{}}
            void menu_pump_speed_down() {{}}
            void menu_setup() {{}}
            void set_delta_steam_temp_up() {{}}
            void set_delta_steam_temp_down() {{}}
            void set_delta_pipe_temp_up() {{}}
            void set_delta_pipe_temp_down() {{}}
            void set_delta_water_temp_up() {{}}
            void set_delta_water_temp_down() {{}}
            void set_delta_tank_temp_up() {{}}
            void set_delta_tank_temp_down() {{}}
            void set_delta_set_steam_temp_up() {{}}
            void set_delta_set_steam_temp_down() {{}}
            void set_delta_set_pipe_temp_up() {{}}
            void set_delta_set_pipe_temp_down() {{}}
            void set_delta_set_water_temp_up() {{}}
            void set_delta_set_water_temp_down() {{}}
            void set_delta_set_tank_temp_up() {{}}
            void set_delta_set_tank_temp_down() {{}}
            void stepper_step_ml_up() {{}}
            void stepper_step_ml_down() {{}}
            void menu_program() {{}}
            void menu_program_back() {{}}
            void menu_reset_wifi() {{}}
            void setup_go_back() {{}}
            void menu_get_power() {{}}
            void menu_pause() {{}}

            void menu_calibrate() {{
              menu_calibrate_calls++;
            }}

            void menu_calibrate_down() {{
              menu_calibrate_down_calls++;
            }}

            void setup_menu_screen_decimal_places() {{
              setup_menu_screen_decimal_places_calls++;
            }}

            void setup_menu_screen_progmem() {{
              setup_menu_screen_progmem_calls++;
            }}

            void register_menu_screens() {{
              register_menu_screens_calls++;
            }}

            {extracted_functions}

            static void reset_state() {{
              semaphore_take_calls = 0;
              semaphore_give_calls = 0;
              delay_ticks = 0;
              fake_millis = 0;
              multiplier = 0;
              startval = SAMOVAR_STARTVAL_RECT_IDLE;
              CurMin = 0;
              OldMin = 0;
              menu_calibrate_calls = 0;
              menu_calibrate_down_calls = 0;
              setup_menu_screen_decimal_places_calls = 0;
              setup_menu_screen_progmem_calls = 0;
              register_menu_screens_calls = 0;

              main_menu1 = MockMenu();
              lcd = MockLcd();
              encoder = MockEncoder();

              welcome_screen = LiquidScreen("welcome_screen");
              main_screen = LiquidScreen("main_screen");
              main_screen1 = LiquidScreen("main_screen1");
              main_screen2 = LiquidScreen("main_screen2");
              main_screen4 = LiquidScreen("main_screen4");
              main_screen5 = LiquidScreen("main_screen5");
              setup_temp_screen = LiquidScreen("setup_temp_screen");
              setup_set_temp_screen = LiquidScreen("setup_set_temp_screen");
              setup_stepper_settings = LiquidScreen("setup_stepper_settings");
              setup_program_settings = LiquidScreen("setup_program_settings");
              setup_program_back = LiquidScreen("setup_program_back");
              setup_back_screen = LiquidScreen("setup_back_screen");

              lql_start = MockLine("lql_start");
              lql_reset = MockLine("lql_reset");
              lql_pump_speed = MockLine("lql_pump_speed");
              lql_setup = MockLine("lql_setup");
              lql_setup_steam_temp = MockLine("lql_setup_steam_temp");
              lql_setup_pipe_temp = MockLine("lql_setup_pipe_temp");
              lql_setup_water_temp = MockLine("lql_setup_water_temp");
              lql_setup_tank_temp = MockLine("lql_setup_tank_temp");
              lql_setup_set_steam_temp = MockLine("lql_setup_set_steam_temp");
              lql_setup_set_pipe_temp = MockLine("lql_setup_set_pipe_temp");
              lql_setup_set_water_temp = MockLine("lql_setup_set_water_temp");
              lql_setup_set_tank_temp = MockLine("lql_setup_set_tank_temp");
              lql_setup_stepper_stepper_step_ml = MockLine("lql_setup_stepper_stepper_step_ml");
              lql_setup_stepper_calibrate = MockLine("lql_setup_stepper_calibrate");
              lql_setup_stepper_program = MockLine("lql_setup_stepper_program");
              lql_setup_program_back_line = MockLine("lql_setup_program_back_line");
              lql_setup_program_reset_wifi = MockLine("lql_setup_program_reset_wifi");
              lql_back_line = MockLine("lql_back_line");
              lql_get_power = MockLine("lql_get_power");
              lql_pause = MockLine("lql_pause");
            }}

            static std::string last_changed_screen() {{
              if (main_menu1.changed_screens.empty()) {{
                return "none";
              }}
              return main_menu1.changed_screens.back();
            }}

            int main() {{
              reset_state();
              encoder.right = true;
              main_menu1.callable1_results.push_back(false);
              fake_millis = 1000;
              encoder_getvalue();
              std::cout << "right_nav|" << multiplier << "|" << main_menu1.next_screen_calls << "|"
                        << main_menu1.called_functions.size() << "|" << main_menu1.soft_update_calls << "\\n";

              reset_state();
              encoder.right = true;
              main_menu1.callable1_results.push_back(true);
              fake_millis = 1000;
              encoder_getvalue();
              std::cout << "right_call|" << multiplier << "|"
                        << (main_menu1.called_functions.empty() ? 0 : main_menu1.called_functions.front()) << "|"
                        << main_menu1.next_screen_calls << "|" << delay_ticks << "\\n";

              reset_state();
              encoder.click = true;
              startval = SAMOVAR_STARTVAL_CALIBRATION;
              fake_millis = 1000;
              encoder_getvalue();
              std::cout << "click_calibrate|" << startval << "|" << menu_calibrate_calls << "|"
                        << main_menu1.switch_focus_calls << "\\n";

              reset_state();
              fake_millis = 120000;
              encoder_getvalue();
              std::cout << "refresh_tick|" << lcd.begin_calls << "|" << lcd.init_calls << "|"
                        << main_menu1.soft_update_calls << "|" << OldMin << "\\n";

              reset_state();
              set_menu_screen(1);
              std::cout << "screen_setup|" << last_changed_screen() << "|" << setup_temp_screen.hidden << "|"
                        << main_screen.hidden << "|" << setup_program_settings.hidden << "\\n";

              reset_state();
              setupMenu();
              std::cout << "setup_menu|" << lcd.begin_calls << "|" << lcd.init_calls << "|"
                        << lcd.backlight_calls << "|" << lcd.clear_calls << "|"
                        << setup_menu_screen_decimal_places_calls << "|"
                        << setup_menu_screen_progmem_calls << "|" << register_menu_screens_calls << "|"
                        << lql_start.attached_slots.size() << "|" << lql_pause.attached_slots.size() << "|"
                        << last_changed_screen() << "|" << welcome_screen.hidden << "|"
                        << main_menu1.update_calls << "\\n";
              return 0;
            }}
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_path = tmpdir_path / "menu_input_harness.cpp"
            binary_path = tmpdir_path / "menu_input_harness"
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
                "right_nav|1|1|0|0",
                "right_call|1|1|0|5",
                "click_calibrate|0|1|1",
                "refresh_tick|1|1|1|120",
                "screen_setup|setup_temp_screen|0|1|1",
                "setup_menu|1|1|1|1|1|1|1|2|2|welcome_screen|1|1",
            ],
        )


if __name__ == "__main__":
    unittest.main()
