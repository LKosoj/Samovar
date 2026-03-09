import unittest
from pathlib import Path


CONFIG_APPLY_HEADER = Path("app/config_apply.h")
SAMOVAR_INO = Path("Samovar.ino")


class ConfigApplyHeaderTest(unittest.TestCase):
    def test_config_apply_header_exists(self) -> None:
        self.assertTrue(CONFIG_APPLY_HEADER.exists())

    def test_config_apply_header_contains_read_config(self) -> None:
        text = CONFIG_APPLY_HEADER.read_text(encoding="utf-8")
        self.assertIn("void read_config() {", text)

    def test_samovar_includes_config_apply_header(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertIn('#include "app/config_apply.h"', text)

    def test_samovar_no_longer_defines_read_config(self) -> None:
        text = SAMOVAR_INO.read_text(encoding="utf-8")
        self.assertNotIn("void read_config() {", text)


if __name__ == "__main__":
    unittest.main()
