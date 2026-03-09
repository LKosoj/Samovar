from pathlib import Path
import unittest


RECT_RUNTIME_HEADER = Path("modes/rect/rect_runtime.h")
LOGIC_HEADER = Path("logic.h")
DIRECT_INCLUDE_USERS = (
    Path("Samovar.ino"),
    Path("Menu.ino"),
    Path("Blynk.ino"),
    Path("lua.h"),
    Path("impurity_detector.h"),
)
LEGACY_DECLARATION_ONLY_USERS = (
    Path("WebServer.ino"),
    Path("distiller.h"),
)


class RectRuntimeExtractionTest(unittest.TestCase):
    def test_rect_runtime_header_exists(self) -> None:
        self.assertTrue(RECT_RUNTIME_HEADER.exists(), "modes/rect/rect_runtime.h must exist")

    def test_rect_runtime_contains_extracted_functions(self) -> None:
        text = RECT_RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void withdrawal(void)", text)
        self.assertIn("inline void pause_withdrawal(bool Pause)", text)
        self.assertIn("inline void run_program(uint8_t num)", text)
        self.assertIn("inline void set_body_temp()", text)
        self.assertIn("inline void check_alarm()", text)
        self.assertIn("inline bool column_wetting()", text)

    def test_logic_header_includes_rect_runtime_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "modes/rect/rect_runtime.h"', text)

    def test_rect_runtime_definitions_removed_from_logic_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("void withdrawal(void) {", text)
        self.assertNotIn("void pause_withdrawal(bool Pause) {", text)
        self.assertNotIn("void run_program(uint8_t num) {", text)
        self.assertNotIn("void set_body_temp() {", text)
        self.assertNotIn("void check_alarm() {", text)
        self.assertNotIn("bool column_wetting() {", text)

    def test_direct_users_include_rect_runtime_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/rect/rect_runtime.h"', text)

    def test_legacy_declarations_removed_from_non_users(self) -> None:
        for path in LEGACY_DECLARATION_ONLY_USERS:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("void set_body_temp();", text)


if __name__ == "__main__":
    unittest.main()
