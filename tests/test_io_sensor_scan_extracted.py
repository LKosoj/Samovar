from pathlib import Path
import unittest


IO_SENSOR_SCAN_HEADER = Path("io/sensor_scan.h")
SENSORINIT_FILE = Path("sensorinit.h")


class IoSensorScanExtractionTests(unittest.TestCase):
    def test_io_sensor_scan_module_exists_and_owns_sensor_reset_runtime(self) -> None:
        self.assertTrue(IO_SENSOR_SCAN_HEADER.exists(), "io/sensor_scan.h must exist")

        header_text = IO_SENSOR_SCAN_HEADER.read_text(encoding="utf-8")
        for snippet in [
            "inline void sensor_init(void)",
            "pressure_sensor_init();",
            'writeString("DS1820 init...     ", 3);',
            "scan_ds_adress();",
            "load_default_program_for_mode();",
            "heaterPID.SetSampleTime(1000);",
            "inline void reset_sensor_counter(void)",
            "stopService();",
            "set_capacity(0);",
            "pressure_value = 0.0;",
            "old_pressure_value = 0.0;",
            "if (bme_pressure < 100) BME_getvalue(false);",
            "set_power(false);",
            'Lua_status = "";',
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, header_text)

    def test_sensorinit_includes_io_sensor_scan_and_has_no_local_duplicates(self) -> None:
        sensorinit_text = SENSORINIT_FILE.read_text(encoding="utf-8")

        self.assertIn('#include "io/sensor_scan.h"', sensorinit_text)
        for snippet in [
            "void sensor_init(void) {",
            "void reset_sensor_counter(void) {",
        ]:
            with self.subTest(snippet=snippet):
                self.assertNotIn(snippet, sensorinit_text)


if __name__ == "__main__":
    unittest.main()
