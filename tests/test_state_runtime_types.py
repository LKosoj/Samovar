from pathlib import Path
import unittest


RUNTIME_TYPES = Path("state/runtime_types.h")
STATUS_CODES = Path("src/core/state/status_codes.h")
MODE_CODES = Path("src/core/state/mode_codes.h")
SAMOVAR_HEADER = Path("Samovar.h")


class RuntimeTypesStructureTest(unittest.TestCase):
    def test_runtime_types_header_exists_and_includes_status_and_mode_codes(self) -> None:
        self.assertTrue(RUNTIME_TYPES.exists(), "state/runtime_types.h must exist")
        text = RUNTIME_TYPES.read_text(encoding="utf-8")
        self.assertIn('#include "src/core/state/status_codes.h"', text)
        self.assertIn('#include "src/core/state/mode_codes.h"', text)
        self.assertIn("enum MESSAGE_TYPE", text)
        self.assertIn("enum get_web_type", text)
        self.assertIn("struct ImpurityDetector", text)
        self.assertIn("struct DSSensor", text)
        self.assertIn("struct WProgram", text)

    def test_status_codes_header_exists_and_defines_status_and_commands(self) -> None:
        self.assertTrue(STATUS_CODES.exists(), "src/core/state/status_codes.h must exist")
        text = STATUS_CODES.read_text(encoding="utf-8")
        self.assertIn("enum SamovarCommands", text)
        self.assertIn("SAMOVAR_STATUS_RECTIFICATION_RUN = 10", text)
        self.assertIn("SAMOVAR_STATUS_RECTIFICATION_STABILIZED = 52", text)
        self.assertIn("SAMOVAR_STATUS_NBK = 4000", text)

    def test_mode_codes_header_exists_and_defines_modes_and_startvals(self) -> None:
        self.assertTrue(MODE_CODES.exists(), "src/core/state/mode_codes.h must exist")
        text = MODE_CODES.read_text(encoding="utf-8")
        self.assertIn("enum SAMOVAR_MODE", text)
        self.assertIn("SAMOVAR_RECTIFICATION_MODE = 0", text)
        self.assertIn("SAMOVAR_LUA_MODE = 6", text)
        self.assertIn("SAMOVAR_STARTVAL_RECT_IDLE = 0", text)
        self.assertIn("SAMOVAR_STARTVAL_BEER_MALT_WAIT = 2002", text)
        self.assertIn("SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING = 4001", text)

    def test_samovar_header_includes_runtime_types_status_and_mode_codes(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "src/core/state/mode_codes.h"', text)
        self.assertIn('#include "src/core/state/status_codes.h"', text)
        self.assertIn('#include "state/runtime_types.h"', text)

    def test_runtime_type_definitions_removed_from_samovar_header(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("enum SamovarCommands {", text)
        self.assertNotIn("enum MESSAGE_TYPE {", text)
        self.assertNotIn("enum get_web_type {", text)
        self.assertNotIn("struct ImpurityDetector {", text)
        self.assertNotIn("struct DSSensor {", text)
        self.assertNotIn("struct WProgram {", text)


if __name__ == "__main__":
    unittest.main()
