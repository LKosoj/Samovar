from pathlib import Path
import unittest


STATUS_TEXT_HEADER = Path("app/status_text.h")
STATUS_TEXT_USERS = [
    Path("Samovar.ino"),
    Path("Blynk.ino"),
]


class StatusTextStructureTest(unittest.TestCase):
    def test_status_text_header_exists_and_defines_function(self) -> None:
        self.assertTrue(STATUS_TEXT_HEADER.exists(), "app/status_text.h must exist")
        text = STATUS_TEXT_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline String get_Samovar_Status()", text)

    def test_logic_header_deleted(self) -> None:
        self.assertFalse(Path("logic.h").exists())

    def test_status_text_users_include_header_directly(self) -> None:
        for path in STATUS_TEXT_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "app/status_text.h"', text)


if __name__ == "__main__":
    unittest.main()
