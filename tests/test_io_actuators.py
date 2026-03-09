from pathlib import Path
import unittest


ACTUATORS_HEADER = Path("io/actuators.h")
LOGIC_HEADER = Path("logic.h")
ACTUATORS_USERS = [
    Path("logic.h"),
    Path("app/process_common.h"),
    Path("app/alarm_control.h"),
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
    Path("impurity_detector.h"),
]


class ActuatorsStructureTest(unittest.TestCase):
    def test_actuators_header_exists_and_defines_functions(self) -> None:
        self.assertTrue(ACTUATORS_HEADER.exists(), "io/actuators.h must exist")
        text = ACTUATORS_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void pump_calibrate(int stpspeed)", text)
        self.assertIn(
            "inline void set_pump_speed(float pumpspeed, bool continue_process)",
            text,
        )
        self.assertIn("inline void set_capacity(uint8_t cap)", text)
        self.assertIn("inline void next_capacity(void)", text)
        self.assertIn("inline void open_valve(bool Val, bool msg = true)", text)
        self.assertIn("inline void set_boiling()", text)
        self.assertIn("inline bool check_boiling()", text)

    def test_logic_header_includes_actuators_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "io/actuators.h"', text)

    def test_actuators_definitions_removed_from_logic_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("void pump_calibrate(int stpspeed) {", text)
        self.assertNotIn(
            "void set_pump_speed(float pumpspeed, bool continue_process) {",
            text,
        )
        self.assertNotIn("void set_capacity(uint8_t cap) {", text)
        self.assertNotIn("void next_capacity(void) {", text)
        self.assertNotIn("void open_valve(bool Val, bool msg = true) {", text)
        self.assertNotIn("void set_boiling() {", text)
        self.assertNotIn("bool check_boiling() {", text)

    def test_actuators_users_include_header_directly(self) -> None:
        for path in ACTUATORS_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "io/actuators.h"', text)


if __name__ == "__main__":
    unittest.main()
