from pathlib import Path
import unittest


GLOBALS_DIRECT_INCLUDE_FILES = [
    "I2CStepper.h",
    "sensorinit.h",
    "NVS_Manager.ino",
    "SPIFFSEditor.h",
    "crash_handler.h",
    "modes/bk/bk_finish.h",
    "modes/bk/bk_water_control.h",
    "modes/bk/bk_alarm.h",
    "column_math.h",
    "impurity_detector.h",
    "quality.h",
    "mod_rmv.ino",
    "ui/web/ajax_snapshot.h",
    "ui/web/routes_command.h",
    "ui/web/routes_save.h",
    "ui/web/routes_setup_process.h",
    "ui/web/server_init.h",
    "Blynk.ino",
    "modes/bk/bk_runtime.h",
    "modes/beer/beer_program_codec.h",
    "modes/beer/beer_autotune.h",
    "modes/beer/beer_heater.h",
    "modes/beer/beer_mixer.h",
    "modes/beer/beer_runtime.h",
    "modes/nbk/nbk_alarm.h",
    "modes/nbk/nbk_finish.h",
    "modes/nbk/nbk_flow_control.h",
    "modes/nbk/nbk_math.h",
    "modes/nbk/nbk_program_codec.h",
    "modes/nbk/nbk_runtime.h",
    "modes/nbk/nbk_state.h",
    "pumppwm.h",
    "Samovar.ino",
    "Menu.ino",
    "SamovarMqtt.h",
]

SAFE_PARSE_DIRECT_INCLUDE_FILES = [
    "NVS_Manager.ino",
    "modes/beer/beer_program_codec.h",
    "modes/nbk/nbk_program_codec.h",
    "Samovar.ino",
    "Menu.ino",
    "SamovarMqtt.h",
]


class IncludeGraphTest(unittest.TestCase):
    def test_globals_consumers_include_globals_header_directly(self) -> None:
        for relative_path in GLOBALS_DIRECT_INCLUDE_FILES:
            with self.subTest(path=relative_path):
                text = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn('#include "state/globals.h"', text)

    def test_safe_parse_consumers_include_safe_parse_header_directly(self) -> None:
        for relative_path in SAFE_PARSE_DIRECT_INCLUDE_FILES:
            with self.subTest(path=relative_path):
                text = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn('#include "support/safe_parse.h"', text)


if __name__ == "__main__":
    unittest.main()
