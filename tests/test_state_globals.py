from pathlib import Path
import unittest


GLOBALS_HEADER = Path("state/globals.h")
SAMOVAR_HEADER = Path("Samovar.h")


class GlobalsStructureTest(unittest.TestCase):
    def test_globals_header_exists_and_uses_extern(self) -> None:
        self.assertTrue(GLOBALS_HEADER.exists(), "state/globals.h must exist")
        text = GLOBALS_HEADER.read_text(encoding="utf-8")
        self.assertIn("extern SetupEEPROM SamSetup;", text)
        self.assertIn("extern volatile SamovarCommands sam_command_sync;", text)
        self.assertIn("extern AsyncWebServer server;", text)
        self.assertIn("extern char ipst[16];", text)

    def test_samovar_header_includes_globals_header(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "state/globals.h"', text)

    def test_global_definitions_removed_from_samovar_header(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("SetupEEPROM SamSetup;", text)
        self.assertNotIn("volatile SamovarCommands sam_command_sync;", text)
        self.assertNotIn("AsyncWebServer server(80);", text)
        self.assertNotIn('char ipst[16] = "000.000.000.000";', text)


if __name__ == "__main__":
    unittest.main()
