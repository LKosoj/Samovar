from pathlib import Path
import unittest


BK_ALARM_HEADER = Path("modes/bk/bk_alarm.h")
BK_HEADER = Path("BK.h")
DIRECT_INCLUDE_USERS = (
    Path("app/runtime_tasks.h"),
)


class BkAlarmExtractionTest(unittest.TestCase):
    def test_bk_alarm_header_exists(self) -> None:
        self.assertTrue(BK_ALARM_HEADER.exists(), "modes/bk/bk_alarm.h must exist")

    def test_bk_alarm_header_contains_extracted_alarm(self) -> None:
        text = BK_ALARM_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void check_alarm_bk()", text)

    def test_direct_users_include_bk_alarm_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/bk/bk_alarm.h"', text)

    def test_bk_header_no_longer_contains_alarm(self) -> None:
        text = BK_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("void check_alarm_bk() {", text)


if __name__ == "__main__":
    unittest.main()
