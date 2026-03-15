from pathlib import Path
import unittest


ALARM_CONTROL_HEADER = Path("app/alarm_control.h")
ALARM_CONTROL_USERS = [
    Path("Samovar.ino"),
    Path("modes/beer/beer_runtime.h"),
    Path("modes/bk/bk_alarm.h"),
    Path("modes/nbk/nbk_alarm.h"),
    Path("impurity_detector.h"),
]


class AlarmControlStructureTest(unittest.TestCase):
    def test_alarm_control_header_exists_and_defines_functions(self) -> None:
        self.assertTrue(ALARM_CONTROL_HEADER.exists(), "app/alarm_control.h must exist")
        text = ALARM_CONTROL_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void set_alarm()", text)
        self.assertIn("inline void process_buzzer()", text)
        self.assertIn("inline void set_buzzer(bool fl)", text)

    def test_logic_header_deleted(self) -> None:
        self.assertFalse(Path("logic.h").exists())

    def test_alarm_control_users_include_header_directly(self) -> None:
        for path in ALARM_CONTROL_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "app/alarm_control.h"', text)


if __name__ == "__main__":
    unittest.main()
