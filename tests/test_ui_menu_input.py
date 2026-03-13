from pathlib import Path
import unittest


MENU_INPUT_HEADER = Path("ui/menu/input.h")
MENU_SOURCE = Path("Menu.ino")

EXPECTED_INPUT_HELPERS = [
    "inline void reset_focus() {",
    "inline void menu_previous_screen() {",
    "inline void menu_next_screen() {",
    "inline void menu_switch_focus() {",
    "inline void menu_reset_lcd() {",
    "inline void change_screen(LiquidScreen* screen) {",
    "inline void menu_update() {",
    "inline void menu_softUpdate() {",
    "inline void set_menu_screen(uint8_t param) {",
    "inline void bind_menu_input_handlers() {",
    "inline void encoder_getvalue() {",
    "inline void setupMenu() {",
]

EXPECTED_INPUT_BASELINE = [
    "lql_start.attach_function(1, menu_samovar_start);",
    "lql_setup_program_reset_wifi.attach_function(2, menu_reset_wifi);",
    "lql_pause.attach_function(2, menu_pause);",
    "if (encoder.isRight()) {",
    "if (!main_menu1.is_callable(1)) {",
    "main_menu1.call_function(1);",
    "} else if (encoder.isLeft()) {",
    "} else if (encoder.isRightH()) {",
    "} else if (encoder.isLeftH()) {",
    "} else if (encoder.isClick()) {",
    "case 1:",
    "setup_temp_screen.hide(false);",
    "change_screen(&setup_temp_screen);",
    "change_screen(&main_screen);",
    "change_screen(&setup_program_settings);",
    "menu_switch_focus();",
    "menu_reset_lcd();",
    "if (updscreen) menu_softUpdate();",
    "lcd.begin(LCD_COLUMNS, LCD_ROWS);",
    "register_menu_screens();",
    "change_screen(&welcome_screen);",
]

MOVED_MENU_INPUT_SNIPPETS = [
    "void reset_focus() {",
    "void menu_previous_screen() {",
    "void menu_next_screen() {",
    "void menu_switch_focus() {",
    "void menu_reset_lcd() {",
    "void change_screen(LiquidScreen* screen) {",
    "void menu_update() {",
    "void menu_softUpdate() {",
    "void set_menu_screen(uint8_t param) {",
    "void encoder_getvalue() {",
    "void setupMenu() {",
    "lql_start.attach_function(1, menu_samovar_start);",
]


class MenuInputStructureTest(unittest.TestCase):
    def test_menu_input_header_exists_with_baseline_logic(self) -> None:
        self.assertTrue(MENU_INPUT_HEADER.exists(), "ui/menu/input.h must exist")
        text = MENU_INPUT_HEADER.read_text(encoding="utf-8")

        self.assertIn("#include <Arduino.h>", text)

        for snippet in EXPECTED_INPUT_HELPERS + EXPECTED_INPUT_BASELINE:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text)

    def test_menu_source_includes_input_module_and_uses_binding_helper(self) -> None:
        source_text = MENU_SOURCE.read_text(encoding="utf-8")
        header_text = MENU_INPUT_HEADER.read_text(encoding="utf-8")

        self.assertIn('#include "ui/menu/input.h"', source_text)
        self.assertIn("bind_menu_input_handlers();", header_text)

    def test_menu_source_no_longer_keeps_inline_input_logic(self) -> None:
        text = MENU_SOURCE.read_text(encoding="utf-8")
        for snippet in MOVED_MENU_INPUT_SNIPPETS:
            with self.subTest(snippet=snippet):
                self.assertNotIn(snippet, text)


if __name__ == "__main__":
    unittest.main()
