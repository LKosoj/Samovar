from pathlib import Path
import unittest


MENU_SCREENS_HEADER = Path("ui/menu/screens.h")
MENU_SOURCE = Path("Menu.ino")

EXPECTED_SCREEN_DEFINITIONS = [
    "static LiquidLine lql_back_line(0, 10, str_BACK);",
    "static LiquidLine lql_time(0, 10, get_timestr);",
    "static LiquidScreen welcome_screen(welcome_line1, welcome_line2, welcome_line3, welcome_line4);",
    "static LiquidScreen main_screen(lql_steam_temp, lql_pipe_temp, lql_water_temp, lql_time);",
    "static LiquidScreen main_screen1(lql_tank_temp, lql_atm, lql_w_progress, lql_time);",
    "static LiquidScreen main_screen2(lql_start, lql_pump_speed, lql_pause, lql_reset);",
    "static LiquidScreen main_screen4(lql_get_power, lql_setup, lql_ip, lql_time);",
    "static LiquidScreen main_screen5(lql_tank_temp, lql_atm, lql_water_temp, lql_time);",
    "static LiquidScreen setup_temp_screen(lql_setup_steam_temp, lql_setup_pipe_temp, lql_setup_water_temp, lql_setup_tank_temp);",
    "static LiquidScreen setup_set_temp_screen(lql_setup_set_steam_temp, lql_setup_set_pipe_temp, lql_setup_set_water_temp, lql_setup_set_tank_temp);",
    "static LiquidScreen setup_stepper_settings(lql_setup_stepper_stepper_step_ml, lql_setup_stepper_calibrate, lql_setup_stepper_program, lql_time);",
    "static LiquidScreen setup_program_settings(",
    "static LiquidScreen setup_program_back(lql_setup_program_reset_wifi, lql_setup_program_back_line, lql_time);",
    "static LiquidScreen setup_back_screen(lql_back_line, lql_time);",
]

EXPECTED_SCREEN_HELPERS = [
    "inline void setup_menu_screen_decimal_places() {",
    "inline void setup_menu_screen_progmem() {",
    "inline void register_menu_screens() {",
    "lql_steam_temp.set_decimalPlaces(2);",
    "lql_setup_program_back_line.set_asProgmem(1);",
    "main_menu1.add_screen(setup_program_back);",
]

MOVED_MENU_SCREEN_SNIPPETS = [
    "LiquidLine lql_back_line(",
    "LiquidScreen welcome_screen(",
    "LiquidScreen setup_program_settings(",
    "LiquidScreen setup_program_back(",
    "lql_steam_temp.set_decimalPlaces(2);",
    "lql_setup_program_back_line.set_asProgmem(1);",
    "main_menu1.add_screen(welcome_screen);",
]


class MenuScreensStructureTest(unittest.TestCase):
    def test_menu_screens_header_exists_with_baseline_screens(self) -> None:
        self.assertTrue(MENU_SCREENS_HEADER.exists(), "ui/menu/screens.h must exist")
        text = MENU_SCREENS_HEADER.read_text(encoding="utf-8")

        for snippet in EXPECTED_SCREEN_DEFINITIONS + EXPECTED_SCREEN_HELPERS:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text)

    def test_menu_source_includes_screen_module_and_uses_helpers(self) -> None:
        text = MENU_SOURCE.read_text(encoding="utf-8")
        self.assertIn('#include "ui/menu/screens.h"', text)
        self.assertIn("setup_menu_screen_decimal_places();", text)
        self.assertIn("setup_menu_screen_progmem();", text)
        self.assertIn("register_menu_screens();", text)

    def test_menu_source_no_longer_keeps_inline_screen_definitions(self) -> None:
        text = MENU_SOURCE.read_text(encoding="utf-8")
        for snippet in MOVED_MENU_SCREEN_SNIPPETS:
            with self.subTest(snippet=snippet):
                self.assertNotIn(snippet, text)


if __name__ == "__main__":
    unittest.main()
