from pathlib import Path
import unittest


CONFIG_TYPES = Path("state/config_types.h")
SAMOVAR_HEADER = Path("Samovar.h")


class ConfigTypesStructureTest(unittest.TestCase):
    def test_config_types_header_exists_and_defines_setup(self) -> None:
        self.assertTrue(CONFIG_TYPES.exists(), "state/config_types.h must exist")
        text = CONFIG_TYPES.read_text(encoding="utf-8")
        self.assertIn("struct SetupEEPROM", text)
        self.assertIn("uint16_t StepperStepMlI2C;", text)

    def test_samovar_header_includes_config_types(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "state/config_types.h"', text)

    def test_setup_definition_removed_from_samovar_header(self) -> None:
        text = SAMOVAR_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("struct SetupEEPROM {", text)


if __name__ == "__main__":
    unittest.main()
