from pathlib import Path
import unittest


RUNTIME_TYPES = Path("state/runtime_types.h")
SAMOVAR_HEADER = Path("Samovar.h")


class RuntimeTypesStructureTest(unittest.TestCase):
    def test_runtime_types_header_exists_and_defines_runtime_types(self) -> None:
        self.assertTrue(RUNTIME_TYPES.exists(), "state/runtime_types.h must exist")
        text = RUNTIME_TYPES.read_text(encoding="utf-8")
        self.assertIn("enum SamovarCommands", text)
        self.assertIn("enum SAMOVAR_MODE", text)
        self.assertIn("enum MESSAGE_TYPE", text)
        self.assertIn("enum get_web_type", text)
        self.assertIn("struct ImpurityDetector", text)
        self.assertIn("struct DSSensor", text)
        self.assertIn("struct WProgram", text)

    def test_samovar_header_includes_runtime_types(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "state/runtime_types.h"', text)

    def test_runtime_type_definitions_removed_from_samovar_header(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("enum SamovarCommands {", text)
        self.assertNotIn("enum SAMOVAR_MODE {", text)
        self.assertNotIn("enum MESSAGE_TYPE {", text)
        self.assertNotIn("enum get_web_type {", text)
        self.assertNotIn("struct ImpurityDetector {", text)
        self.assertNotIn("struct DSSensor {", text)
        self.assertNotIn("struct WProgram {", text)


if __name__ == "__main__":
    unittest.main()
