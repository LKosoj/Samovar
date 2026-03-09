from pathlib import Path
import unittest


BEER_RUNTIME_HEADER = Path("modes/beer/beer_runtime.h")
BEER_CODEC_HEADER = Path("modes/beer/beer_program_codec.h")
LEGACY_BEER_HEADER = Path("beer.h")
DIRECT_INCLUDE_USERS = (
    Path("Samovar.ino"),
    Path("app/runtime_tasks.h"),
    Path("app/loop_dispatch.h"),
    Path("app/orchestration.h"),
    Path("WebServer.ino"),
    Path("lua.h"),
)


class BeerRuntimeExtractionTest(unittest.TestCase):
    def test_beer_runtime_header_exists(self) -> None:
        self.assertTrue(BEER_RUNTIME_HEADER.exists(), "modes/beer/beer_runtime.h must exist")

    def test_beer_runtime_header_contains_extracted_runtime(self) -> None:
        text = BEER_RUNTIME_HEADER.read_text(encoding="utf-8")
        for signature in [
            "struct BoilingDetector {",
            "extern BoilingDetector boilingDetector;",
            "inline void beer_proc()",
            "inline void run_beer_program(uint8_t num)",
            "inline void beer_finish()",
            "inline void check_alarm_beer()",
            "inline void check_mixer_state()",
            "inline void set_mixer_state(bool state, bool dir)",
            "inline void set_heater_state(float setpoint, float temp)",
            "inline void set_heater(double dutyCycle)",
            "inline void setHeaterPosition(bool state)",
            "inline void StartAutoTune()",
            "inline void FinishAutoTune()",
            "inline void set_mixer(bool On)",
            "inline void HopStepperStep()",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_beer_runtime_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/beer/beer_runtime.h"', text)

    def test_beer_codec_header_no_longer_contains_runtime(self) -> None:
        text = BEER_CODEC_HEADER.read_text(encoding="utf-8")
        for signature in [
            "struct BoilingDetector {",
            "void beer_proc() {",
            "void run_beer_program(uint8_t num) {",
            "void beer_finish() {",
            "void check_alarm_beer() {",
            "void check_mixer_state() {",
            "void set_mixer_state(bool state, bool dir) {",
            "void set_heater_state(float setpoint, float temp) {",
            "void set_heater(double dutyCycle) {",
            "void setHeaterPosition(bool state) {",
            "void StartAutoTune() {",
            "void FinishAutoTune() {",
            "void set_mixer(bool On) {",
            "void HopStepperStep() {",
        ]:
            with self.subTest(signature=signature):
                self.assertNotIn(signature, text)

    def test_legacy_beer_header_deleted(self) -> None:
        self.assertFalse(LEGACY_BEER_HEADER.exists())


if __name__ == "__main__":
    unittest.main()
