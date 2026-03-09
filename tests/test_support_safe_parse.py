from pathlib import Path
import unittest


SAFE_PARSE_HEADER = Path("support/safe_parse.h")
SAMOVAR_HEADER = Path("Samovar.h")


class SafeParseStructureTest(unittest.TestCase):
    def test_safe_parse_header_exists_and_defines_helpers(self) -> None:
        self.assertTrue(SAFE_PARSE_HEADER.exists(), "support/safe_parse.h must exist")
        text = SAFE_PARSE_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void copyStringSafe", text)
        self.assertIn("inline bool parseLongSafe", text)
        self.assertIn("inline bool parseFloatSafe", text)

    def test_samovar_header_includes_safe_parse_header(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "support/safe_parse.h"', text)

    def test_safe_parse_definitions_removed_from_samovar_header(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("inline void copyStringSafe", text)
        self.assertNotIn("inline bool parseLongSafe", text)
        self.assertNotIn("inline bool parseFloatSafe", text)


if __name__ == "__main__":
    unittest.main()
