from pathlib import Path
import unittest


BEER_HEATER_HEADER = Path("modes/beer/beer_heater.h")
BEER_RUNTIME_HEADER = Path("modes/beer/beer_runtime.h")
DIRECT_INCLUDE_USERS = (
    Path("modes/beer/beer_runtime.h"),
)


class BeerHeaterStructureTest(unittest.TestCase):
    def test_beer_heater_header_exists(self) -> None:
        self.assertTrue(BEER_HEATER_HEADER.exists(), "modes/beer/beer_heater.h must exist")

    def test_beer_heater_header_contains_heater_functions(self) -> None:
        text = BEER_HEATER_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void set_heater_state(float setpoint, float temp)",
            "inline void set_heater(double dutyCycle)",
            "inline void setHeaterPosition(bool state)",
            "inline void StartAutoTune()",
            "inline void FinishAutoTune()",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_beer_heater_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/beer/beer_heater.h"', text)

    def test_beer_runtime_header_no_longer_contains_heater_logic(self) -> None:
        text = BEER_RUNTIME_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void set_heater_state(float setpoint, float temp)",
            "inline void set_heater(double dutyCycle)",
            "inline void setHeaterPosition(bool state)",
            "inline void StartAutoTune()",
            "inline void FinishAutoTune()",
        ]:
            with self.subTest(signature=signature):
                self.assertNotIn(signature, text)


if __name__ == "__main__":
    unittest.main()
