from pathlib import Path
import unittest


DIST_PROGRAM_CODEC_HEADER = Path("modes/dist/dist_program_codec.h")
DIRECT_INCLUDE_USERS = (
    Path("modes/dist/dist_runtime.h"),
    Path("Blynk.ino"),
    Path("FS.ino"),
    Path("WebServer.ino"),
    Path("sensorinit.h"),
)


class DistProgramCodecExtractionTest(unittest.TestCase):
    def test_dist_program_codec_header_exists(self) -> None:
        self.assertTrue(DIST_PROGRAM_CODEC_HEADER.exists(), "modes/dist/dist_program_codec.h must exist")

    def test_dist_program_codec_header_contains_extracted_codec(self) -> None:
        text = DIST_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void set_dist_program(String WProgram)",
            "inline String get_dist_program()",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_dist_program_codec_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/dist/dist_program_codec.h"', text)

    def test_distiller_header_deleted(self) -> None:
        self.assertFalse(Path("distiller.h").exists())


if __name__ == "__main__":
    unittest.main()
