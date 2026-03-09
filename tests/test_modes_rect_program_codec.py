from pathlib import Path
import unittest


RECT_PROGRAM_CODEC_HEADER = Path("modes/rect/rect_program_codec.h")
RECT_PROGRAM_CODEC_USERS = [
    Path("Menu.ino"),
    Path("FS.ino"),
    Path("sensorinit.h"),
    Path("Blynk.ino"),
    Path("WebServer.ino"),
]


class RectProgramCodecStructureTest(unittest.TestCase):
    def test_rect_program_codec_header_exists_and_defines_functions(self) -> None:
        self.assertTrue(
            RECT_PROGRAM_CODEC_HEADER.exists(),
            "modes/rect/rect_program_codec.h must exist",
        )
        text = RECT_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")
        self.assertIn("inline void set_program(String WProgram)", text)
        self.assertIn("inline String get_program(uint8_t s)", text)

    def test_logic_header_deleted(self) -> None:
        self.assertFalse(Path("logic.h").exists())

    def test_rect_program_codec_users_include_header_directly(self) -> None:
        for path in RECT_PROGRAM_CODEC_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/rect/rect_program_codec.h"', text)


if __name__ == "__main__":
    unittest.main()
