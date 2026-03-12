from pathlib import Path
import unittest


NBK_PROGRAM_CODEC_HEADER = Path("modes/nbk/nbk_program_codec.h")
DIRECT_INCLUDE_USERS = (
    Path("Blynk.ino"),
    Path("ui/web/routes_save.h"),
    Path("modes/nbk/nbk_runtime.h"),
    Path("app/default_programs.h"),
)


class NbkProgramCodecExtractionTest(unittest.TestCase):
    def test_nbk_program_codec_header_exists(self) -> None:
        self.assertTrue(NBK_PROGRAM_CODEC_HEADER.exists(), "modes/nbk/nbk_program_codec.h must exist")

    def test_nbk_program_codec_header_contains_extracted_codec(self) -> None:
        text = NBK_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void set_nbk_program(String WProgram)",
            "inline String get_nbk_program()",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_nbk_program_codec_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/nbk/nbk_program_codec.h"', text)

    def test_legacy_nbk_header_removed(self) -> None:
        self.assertFalse(Path("nbk.h").exists())


if __name__ == "__main__":
    unittest.main()
