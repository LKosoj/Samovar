from pathlib import Path
import unittest


NBK_MATH_HEADER = Path("modes/nbk/nbk_math.h")
NBK_RUNTIME_HEADER = Path("modes/nbk/nbk_runtime.h")
WEBSERVER_FILE = Path("WebServer.ino")


class NbkMathExtractionTest(unittest.TestCase):
    def test_nbk_math_header_exists(self) -> None:
        self.assertTrue(NBK_MATH_HEADER.exists(), "modes/nbk/nbk_math.h must exist")

    def test_nbk_math_header_contains_extracted_math(self) -> None:
        text = NBK_MATH_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline float toPower(float value)",
            "inline float SQRT(float num)",
            "inline float fromPower(float value)",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_nbk_math_header(self) -> None:
        for path in (NBK_RUNTIME_HEADER, WEBSERVER_FILE):
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/nbk/nbk_math.h"', text)

    def test_legacy_nbk_header_removed(self) -> None:
        self.assertFalse(Path("nbk.h").exists())

    def test_webserver_no_longer_uses_manual_frompower_declaration(self) -> None:
        text = WEBSERVER_FILE.read_text(encoding="utf-8")
        self.assertNotIn("float fromPower(float value);", text)


if __name__ == "__main__":
    unittest.main()
