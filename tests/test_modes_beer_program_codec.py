from pathlib import Path
import unittest


BEER_PROGRAM_CODEC_HEADER = Path("modes/beer/beer_program_codec.h")
LEGACY_BEER_HEADER = Path("beer.h")
DIRECT_INCLUDE_USERS = (
    Path("sensorinit.h"),
    Path("FS.ino"),
    Path("Blynk.ino"),
    Path("WebServer.ino"),
    Path("modes/beer/beer_runtime.h"),
)


class BeerProgramCodecStructureTest(unittest.TestCase):
    def test_beer_program_codec_header_exists(self) -> None:
        self.assertTrue(BEER_PROGRAM_CODEC_HEADER.exists(), "modes/beer/beer_program_codec.h must exist")

    def test_beer_program_codec_header_contains_codec_functions(self) -> None:
        text = BEER_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")
        self.assertIn("String get_beer_program()", text)
        self.assertIn("void set_beer_program(String WProgram)", text)

    def test_direct_users_include_beer_program_codec_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/beer/beer_program_codec.h"', text)

    def test_legacy_beer_header_deleted(self) -> None:
        self.assertFalse(LEGACY_BEER_HEADER.exists())


if __name__ == "__main__":
    unittest.main()
