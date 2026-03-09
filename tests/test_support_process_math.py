from pathlib import Path
import unittest


PROCESS_MATH_HEADER = Path("support/process_math.h")
PROCESS_MATH_USERS = [
    Path("I2CStepper.h"),
    Path("SPIFFSEditor.h"),
    Path("FS.ino"),
    Path("nbk.h"),
    Path("impurity_detector.h"),
    Path("lua.h"),
    Path("Blynk.ino"),
    Path("distiller.h"),
    Path("beer.h"),
    Path("Samovar.ino"),
    Path("Menu.ino"),
    Path("WebServer.ino"),
]


class ProcessMathStructureTest(unittest.TestCase):
    def test_process_math_header_exists_and_defines_math_helpers(self) -> None:
        self.assertTrue(PROCESS_MATH_HEADER.exists(), "support/process_math.h must exist")
        text = PROCESS_MATH_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline uint8_t getDelimCount", text)
        self.assertIn("inline String getValue", text)
        self.assertIn("inline float get_liquid_volume_by_step", text)
        self.assertIn("inline float get_temp_by_pressure", text)
        self.assertIn("inline float get_steam_alcohol", text)
        self.assertIn("inline float get_alcohol", text)
        self.assertIn("inline unsigned int hexToDec", text)

    def test_logic_header_deleted(self) -> None:
        self.assertFalse(Path("logic.h").exists())

    def test_process_math_users_include_header_directly(self) -> None:
        for path in PROCESS_MATH_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "support/process_math.h"', text)


if __name__ == "__main__":
    unittest.main()
