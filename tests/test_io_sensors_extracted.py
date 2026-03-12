from pathlib import Path
import unittest


IO_SENSORS_HEADER = Path("io/sensors.h")
SENSORINIT_FILE = Path("sensorinit.h")


class IoSensorsExtractionTests(unittest.TestCase):
    def test_io_sensors_module_exists_and_owns_ds18b20_runtime(self) -> None:
        self.assertTrue(IO_SENSORS_HEADER.exists(), "io/sensors.h must exist")

        header_text = IO_SENSORS_HEADER.read_text(encoding="utf-8")
        for snippet in [
            "inline void DS_getvalue(void)",
            "sensors.getTempC(SteamSensor.Sensor)",
            "sensors.getTempC(PipeSensor.Sensor)",
            "sensors.requestTemperatures();",
            "SteamSensor.avgTemp = ss + SamSetup.DeltaSteamTemp;",
            "PipeSensor.avgTemp = ps + SamSetup.DeltaPipeTemp;",
            "inline void scan_ds_adress()",
            "inline String getDSAddress(DeviceAddress deviceAddress)",
            "inline String get_DSAddressList(String Address)",
            "inline void CopyDSAddress(const uint8_t* DevSAddress, uint8_t* DevTAddress)",
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, header_text)

    def test_sensorinit_legacy_file_is_removed(self) -> None:
        self.assertFalse(SENSORINIT_FILE.exists(), "sensorinit.h must be removed")


if __name__ == "__main__":
    unittest.main()
