from pathlib import Path
import unittest


POWER_CONTROL_HEADER = Path("io/power_control.h")
LOGIC_HEADER = Path("logic.h")
POWER_CONTROL_USERS = [
    Path("Samovar.ino"),
    Path("WebServer.ino"),
    Path("Menu.ino"),
    Path("beer.h"),
    Path("distiller.h"),
    Path("BK.h"),
    Path("nbk.h"),
    Path("lua.h"),
    Path("Blynk.ino"),
    Path("sensorinit.h"),
]


class PowerControlStructureTest(unittest.TestCase):
    def test_power_control_header_exists_and_defines_functions(self) -> None:
        self.assertTrue(POWER_CONTROL_HEADER.exists(), "io/power_control.h must exist")
        text = POWER_CONTROL_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void set_power(bool On)", text)
        self.assertIn("inline void triggerPowerStatus(void* parameter)", text)
        self.assertIn("inline void check_power_error()", text)
        self.assertIn("inline void get_current_power()", text)
        self.assertIn("inline void set_current_power(float Volt)", text)
        self.assertIn("inline void set_power_mode(String Mode)", text)

    def test_logic_header_includes_power_control_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "io/power_control.h"', text)

    def test_power_control_definitions_removed_from_logic_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("void set_power(bool On) {", text)
        self.assertNotIn("void triggerPowerStatus(void *parameter) {", text)
        self.assertNotIn("void check_power_error() {", text)
        self.assertNotIn("void get_current_power() {", text)
        self.assertNotIn("void set_current_power(float Volt) {", text)
        self.assertNotIn("void set_power_mode(String Mode) {", text)
        self.assertNotIn("void clear_serial_in_buff() {", text)

    def test_power_control_users_include_header_directly(self) -> None:
        for path in POWER_CONTROL_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "io/power_control.h"', text)


if __name__ == "__main__":
    unittest.main()
