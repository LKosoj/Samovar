from pathlib import Path
import unittest


BEER_SUPPORT_HEADER = Path("modes/beer/beer_support.h")
LOGIC_HEADER = Path("logic.h")
STATUS_TEXT_HEADER = Path("app/status_text.h")


class BeerSupportStructureTest(unittest.TestCase):
    def test_beer_support_header_exists_and_defines_function(self) -> None:
        self.assertTrue(BEER_SUPPORT_HEADER.exists(), "modes/beer/beer_support.h must exist")
        text = BEER_SUPPORT_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline float getBeerCurrentTemp()", text)

    def test_function_removed_from_logic_header(self) -> None:
        text = LOGIC_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("float getBeerCurrentTemp() {", text)

    def test_status_text_includes_beer_support_directly(self) -> None:
        text = STATUS_TEXT_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "modes/beer/beer_support.h"', text)


if __name__ == "__main__":
    unittest.main()
