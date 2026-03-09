from pathlib import Path
import unittest


NBK_ALARM_HEADER = Path("modes/nbk/nbk_alarm.h")
NBK_HEADER = Path("nbk.h")
DIRECT_INCLUDE_USERS = (
    Path("app/runtime_tasks.h"),
)


class NbkAlarmExtractionTest(unittest.TestCase):
    def test_nbk_alarm_header_exists(self) -> None:
        self.assertTrue(NBK_ALARM_HEADER.exists(), "modes/nbk/nbk_alarm.h must exist")

    def test_nbk_alarm_header_contains_extracted_alarm(self) -> None:
        text = NBK_ALARM_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void check_alarm_nbk()", text)

    def test_direct_users_include_nbk_alarm_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/nbk/nbk_alarm.h"', text)

    def test_legacy_nbk_header_no_longer_contains_alarm_definition(self) -> None:
        text = NBK_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("void check_alarm_nbk() {", text)


if __name__ == "__main__":
    unittest.main()
