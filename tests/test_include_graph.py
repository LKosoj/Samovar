from pathlib import Path
import unittest


GLOBALS_DIRECT_INCLUDE_FILES = [
    "I2CStepper.h",
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
    "ui/menu/actions.h",
    "ui/menu/input.h",
    "ui/menu/screens.h",
    "SamovarMqtt.h",
]

SAFE_PARSE_DIRECT_INCLUDE_FILES = [
    "modes/beer/beer_program_codec.h",
    "modes/nbk/nbk_program_codec.h",
    "Samovar.ino",
    "ui/menu/actions.h",
    "ui/menu/screens.h",
    "SamovarMqtt.h",
]

SENSORS_DIRECT_INCLUDE_FILES = [
    "app/runtime_tasks.h",
    "ui/web/routes_command.h",
    "ui/web/routes_save.h",
    "ui/web/template_keys.h",
]

PRESSURE_DIRECT_INCLUDE_FILES = [
    "app/runtime_tasks.h",
]

SENSOR_SCAN_DIRECT_INCLUDE_FILES = [
    "app/orchestration.h",
    "app/process_common.h",
    "ui/menu/actions.h",
    "modes/nbk/nbk_finish.h",
]

FORMAT_UTILS_DIRECT_INCLUDE_FILES = [
    "app/status_text.h",
    "storage/session_logs.h",
    "io/actuators.h",
    "app/runtime_tasks.h",
    "ui/web/template_keys.h",
    "ui/web/ajax_snapshot.h",
    "modes/rect/rect_runtime.h",
]

DEFAULT_PROGRAMS_DIRECT_INCLUDE_FILES = [
    "io/sensor_scan.h",
    "ui/web/routes_setup_process.h",
]

TASK_STACK_USAGE_DIRECT_INCLUDE_FILES = [
    "app/orchestration.h",
    "ui/web/routes_save.h",
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

    def test_sensor_consumers_include_sensors_header_directly(self) -> None:
        for relative_path in SENSORS_DIRECT_INCLUDE_FILES:
            with self.subTest(path=relative_path):
                text = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn('#include "io/sensors.h"', text)

    def test_pressure_consumers_include_pressure_header_directly(self) -> None:
        for relative_path in PRESSURE_DIRECT_INCLUDE_FILES:
            with self.subTest(path=relative_path):
                text = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn('#include "io/pressure.h"', text)

    def test_sensor_scan_consumers_include_sensor_scan_header_directly(self) -> None:
        for relative_path in SENSOR_SCAN_DIRECT_INCLUDE_FILES:
            with self.subTest(path=relative_path):
                text = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn('#include "io/sensor_scan.h"', text)

    def test_format_utils_consumers_include_format_utils_header_directly(self) -> None:
        for relative_path in FORMAT_UTILS_DIRECT_INCLUDE_FILES:
            with self.subTest(path=relative_path):
                text = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn('#include "support/format_utils.h"', text)

    def test_default_program_consumers_include_default_programs_header_directly(self) -> None:
        for relative_path in DEFAULT_PROGRAMS_DIRECT_INCLUDE_FILES:
            with self.subTest(path=relative_path):
                text = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn('#include "app/default_programs.h"', text)

    def test_task_stack_usage_consumers_include_task_stack_usage_header_directly(self) -> None:
        for relative_path in TASK_STACK_USAGE_DIRECT_INCLUDE_FILES:
            with self.subTest(path=relative_path):
                text = Path(relative_path).read_text(encoding="utf-8")
                self.assertIn('#include "support/task_stack_usage.h"', text)


if __name__ == "__main__":
    unittest.main()
