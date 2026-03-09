from pathlib import Path
import unittest


DIST_ALARM_HEADER = Path("modes/dist/dist_alarm.h")
DIST_RUNTIME_HEADER = Path("modes/dist/dist_runtime.h")
DIRECT_INCLUDE_USERS = (
    Path("app/runtime_tasks.h"),
)


class DistAlarmExtractionTest(unittest.TestCase):
    def test_dist_alarm_header_exists(self) -> None:
        self.assertTrue(DIST_ALARM_HEADER.exists(), "modes/dist/dist_alarm.h must exist")

    def test_dist_alarm_header_contains_extracted_alarm(self) -> None:
        text = DIST_ALARM_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void check_alarm_distiller()", text)

    def test_direct_users_include_dist_alarm_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/dist/dist_alarm.h"', text)

    def test_dist_runtime_header_no_longer_defines_alarm_function(self) -> None:
        text = DIST_RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("inline void check_alarm_distiller()", text)


if __name__ == "__main__":
    unittest.main()
