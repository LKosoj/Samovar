from pathlib import Path
import unittest


BEER_MIXER_HEADER = Path("modes/beer/beer_mixer.h")
BEER_RUNTIME_HEADER = Path("modes/beer/beer_runtime.h")
DIRECT_INCLUDE_USERS = (
    Path("modes/beer/beer_runtime.h"),
    Path("lua.h"),
)


class BeerMixerExtractionTest(unittest.TestCase):
    def test_beer_mixer_header_exists(self) -> None:
        self.assertTrue(BEER_MIXER_HEADER.exists(), "modes/beer/beer_mixer.h must exist")

    def test_beer_mixer_header_contains_extracted_functions(self) -> None:
        text = BEER_MIXER_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void check_mixer_state()",
            "inline void set_mixer_state(bool state, bool dir)",
            "inline void set_mixer(bool On)",
            "inline void HopStepperStep()",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_beer_mixer_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/beer/beer_mixer.h"', text)

    def test_beer_runtime_header_no_longer_contains_mixer_logic(self) -> None:
        text = BEER_RUNTIME_HEADER.read_text(encoding="utf-8")
        for signature in [
            "void check_mixer_state() {",
            "void set_mixer_state(bool state, bool dir) {",
            "void set_mixer(bool On) {",
            "void HopStepperStep() {",
        ]:
            with self.subTest(signature=signature):
                self.assertNotIn(signature, text)


if __name__ == "__main__":
    unittest.main()
