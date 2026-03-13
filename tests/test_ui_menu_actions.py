from pathlib import Path
import unittest


MENU_ACTIONS_HEADER = Path("ui/menu/actions.h")
MENU_INPUT_HEADER = Path("ui/menu/input.h")
MENU_SOURCE = Path("Menu.ino")

EXPECTED_ACTION_HELPERS = [
    "inline void menu_setup() {",
    "inline void setup_go_back() {",
    "inline void menu_pump_speed_up() {",
    "inline void menu_pump_speed_down() {",
    "inline void set_delta_steam_temp_up() {",
    "inline void set_delta_steam_temp_down() {",
    "inline void set_delta_pipe_temp_up() {",
    "inline void set_delta_pipe_temp_down() {",
    "inline void set_delta_water_temp_up() {",
    "inline void set_delta_water_temp_down() {",
    "inline void set_delta_tank_temp_up() {",
    "inline void set_delta_tank_temp_down() {",
    "inline void set_delta_set_steam_temp_up() {",
    "inline void set_delta_set_steam_temp_down() {",
    "inline void set_delta_set_pipe_temp_up() {",
    "inline void set_delta_set_pipe_temp_down() {",
    "inline void set_delta_set_water_temp_up() {",
    "inline void set_delta_set_water_temp_down() {",
    "inline void set_delta_set_tank_temp_up() {",
    "inline void set_delta_set_tank_temp_down() {",
    "inline void stepper_step_ml_up() {",
    "inline void stepper_step_ml_down() {",
    "inline void menu_program() {",
    "inline void menu_program_back() {",
    "inline void menu_reset_wifi() {",
    "inline void menu_get_power() {",
    "inline void menu_pause() {",
    "inline void menu_calibrate() {",
    "inline void menu_calibrate_down() {",
    "inline void menu_samovar_start() {",
    "inline void samovar_reset() {",
]

EXPECTED_ACTION_BASELINE = [
    "set_pump_speed(get_speed_from_rate(ActualVolumePerHour + 0.01 * multiplier), true);",
    "set_pump_speed(get_speed_from_rate(ActualVolumePerHour - 0.01 * multiplier), true);",
    "save_profile_nvs();",
    "read_config();",
    "pause_withdrawal(!PauseOn);",
    "pump_calibrate(stpspeed);",
    "run_program(0);",
    "run_program(CAPACITY_NUM * 2);",
    "copyStringSafe(startval_text_val, Str);",
    "clear_wifi_credentials();",
    "ESP.restart();",
    "power_text_ptr = (char *)menu_text_power_on;",
    "sam_command_sync = SAMOVAR_NONE;",
]

MOVED_MENU_ACTION_SNIPPETS = [
    "void menu_setup() {",
    "void setup_go_back() {",
    "void menu_pump_speed_up() {",
    "void menu_pump_speed_down() {",
    "void set_delta_steam_temp_up() {",
    "void set_delta_set_tank_temp_down() {",
    "void stepper_step_ml_down() {",
    "void menu_program() {",
    "void menu_program_back() {",
    "void menu_reset_wifi() {",
    "void menu_get_power() {",
    "void menu_pause() {",
    "void menu_calibrate() {",
    "void menu_calibrate_down() {",
    "void menu_samovar_start() {",
    "void samovar_reset() {",
]

LEGACY_INPUT_DECLARATIONS = [
    "void samovar_reset();",
    "void menu_samovar_start();",
    "void menu_pump_speed_up();",
    "void menu_pump_speed_down();",
    "void menu_setup();",
    "void menu_calibrate();",
    "void menu_reset_wifi();",
    "void setup_go_back();",
    "void menu_get_power();",
    "void menu_pause();",
]


class MenuActionsStructureTest(unittest.TestCase):
    def test_menu_actions_header_exists_with_baseline_logic(self) -> None:
        self.assertTrue(MENU_ACTIONS_HEADER.exists(), "ui/menu/actions.h must exist")
        text = MENU_ACTIONS_HEADER.read_text(encoding="utf-8")

        self.assertIn("#include <Arduino.h>", text)
        self.assertIn('#include "ui/menu/strings.h"', text)

        for snippet in EXPECTED_ACTION_HELPERS + EXPECTED_ACTION_BASELINE:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text)

    def test_menu_input_depends_on_actions_module_without_duplicate_prototypes(self) -> None:
        input_text = MENU_INPUT_HEADER.read_text(encoding="utf-8")

        self.assertIn('#include "ui/menu/actions.h"', input_text)
        for snippet in LEGACY_INPUT_DECLARATIONS:
            with self.subTest(snippet=snippet):
                self.assertNotIn(snippet, input_text)

    def test_menu_source_includes_actions_module_and_no_longer_keeps_inline_logic(self) -> None:
        source_text = MENU_SOURCE.read_text(encoding="utf-8")

        self.assertIn('#include "ui/menu/actions.h"', source_text)
        for snippet in MOVED_MENU_ACTION_SNIPPETS:
            with self.subTest(snippet=snippet):
                self.assertNotIn(snippet, source_text)


if __name__ == "__main__":
    unittest.main()
