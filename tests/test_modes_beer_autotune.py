from pathlib import Path
import unittest


BEER_AUTOTUNE_HEADER = Path("modes/beer/beer_autotune.h")
BEER_HEATER_HEADER = Path("modes/beer/beer_heater.h")
DIRECT_INCLUDE_USERS = (
    Path("modes/beer/beer_runtime.h"),
)


class BeerAutotuneExtractionTest(unittest.TestCase):
    def test_beer_autotune_header_exists(self) -> None:
        self.assertTrue(BEER_AUTOTUNE_HEADER.exists(), "modes/beer/beer_autotune.h must exist")

    def test_beer_autotune_header_contains_autotune_functions(self) -> None:
        text = BEER_AUTOTUNE_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void StartAutoTune()",
            "inline void FinishAutoTune()",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_beer_autotune_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/beer/beer_autotune.h"', text)

    def test_beer_heater_header_no_longer_contains_autotune_logic(self) -> None:
        text = BEER_HEATER_HEADER.read_text(encoding="utf-8")
        for signature in [
            "void StartAutoTune() {",
            "void FinishAutoTune() {",
        ]:
            with self.subTest(signature=signature):
                self.assertNotIn(signature, text)


if __name__ == "__main__":
    unittest.main()
