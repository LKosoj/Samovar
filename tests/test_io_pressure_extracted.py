from pathlib import Path
import unittest


IO_PRESSURE_HEADER = Path("io/pressure.h")
SENSORINIT_FILE = Path("sensorinit.h")
SAMOVAR_INO_FILE = Path("Samovar.ino")


class IoPressureExtractionTests(unittest.TestCase):
    def test_io_pressure_module_exists_and_owns_pressure_runtime(self) -> None:
        self.assertTrue(IO_PRESSURE_HEADER.exists(), "io/pressure.h must exist")

        header_text = IO_PRESSURE_HEADER.read_text(encoding="utf-8")
        for snippet in [
            "inline void BME_getvalue(bool fl)",
            "inline void pressure_sensor_init()",
            "bme_pressure = bme.pressure / 100 * 0.75;",
            "bme_pressure = event.pressure * 0.75;",
            "bme_pressure = bme.readPressure() / 100 * 0.75;",
            "inline void pressure_sensor_get()",
            "pressure_value = pressure_value / 133.32;",
            "pressure_value = (old_pressure_value + pressure_value) / 2;",
            "pressure_value = (analogRead(LUA_PIN) - 36.7) / 12;",
            "if (!pressure_sensor.begin())",
            "bmefound = false;",
            "use_pressure_sensor = false;",
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, header_text)

    def test_sensorinit_legacy_file_is_removed(self) -> None:
        self.assertFalse(SENSORINIT_FILE.exists(), "sensorinit.h must be removed")

    def test_samovar_no_longer_owns_pressure_sensor_object(self) -> None:
        samovar_text = SAMOVAR_INO_FILE.read_text(encoding="utf-8")
        self.assertNotIn("XGZP6897D pressure_sensor(", samovar_text)
        self.assertNotIn("#include <Adafruit_BME680.h>", samovar_text)
        self.assertNotIn("#include <Adafruit_BMP085_U.h>", samovar_text)
        self.assertNotIn("#include <Adafruit_BMP280.h>", samovar_text)
        self.assertNotIn("#include <Adafruit_BME280.h>", samovar_text)


if __name__ == "__main__":
    unittest.main()
