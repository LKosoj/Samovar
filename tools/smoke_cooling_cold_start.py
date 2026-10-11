#!/usr/bin/env python3
"""Первое измерение DS18B20 должно завершиться до проверки охлаждения.

Исполняет настоящие scan_ds_adress(), DS_getvalue() и условие открытия воды.
Заглушка моделирует регистр 85°C до завершения измерения, а не готовый ответ.
"""
import re

from smoke_ds_getvalue_power_on_artifact import build_harness, compile_and_run, ROOT
from smoke_helpers import extract_function_body


def function(source, signature):
    return signature + " {\n" + extract_function_body(source, signature) + "\n}\n"


def main():
    harness = build_harness(ROOT / "sensorinit.h").split("int main() {")[0]
    start = harness.index("struct SensorsStub {")
    end = harness.index("static SensorsStub sensors;", start)
    harness = harness[:start] + r'''
struct SensorsStub {
  float readings[DS_SENSOR_COUNT] = {};
  float measured[DS_SENSOR_COUNT] = {};
  bool waitForConversion = false;
  bool pending = false;
  unsigned completed = 0;
  void begin() {}
  bool getAddress(uint8_t* addr, uint8_t index) {
    if (index >= DS_SENSOR_COUNT) return false;
    addr[0] = index;
    return true;
  }
  void setResolution(const uint8_t*, uint8_t) {}
  void setWaitForConversion(bool wait) { waitForConversion = wait; }
  float getTempC(const uint8_t* addr) { return readings[addr[0]]; }
  void complete() {
    if (!pending) return;
    for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) readings[i] = measured[i];
    pending = false;
    completed++;
  }
  void requestTemperatures() {
    pending = true;
    if (waitForConversion) complete();
  }
};
''' + harness[end:]
    harness += r'''
static const uint8_t SAMOVAR_DS_ADDRESS_MAX = DS_SENSOR_COUNT;
static DeviceAddress DSAddr[DS_SENSOR_COUNT];
static uint8_t DScnt;
#define portENTER_CRITICAL(mux) ((void)0)
#define portEXIT_CRITICAL(mux) ((void)0)
static void set_invalid_ds_address(uint8_t* addr) {
  for (uint8_t i = 0; i < 8; i++) addr[i] = 0xFF;
}
static void CopyDSAddress(const uint8_t* from, uint8_t* to) {
  for (uint8_t i = 0; i < 8; i++) to[i] = from[i];
}
static bool valve_status = false;
'''
    ini = (ROOT / "Samovar_ini.h").read_text()
    for name in ("MAX_ACP_TEMP", "OPEN_VALVE_TANK_TEMP"):
        harness += re.search(r"^#define " + name + r"\s+\d+", ini, re.M)[0] + "\n"
    alarm = (ROOT / "alarm.h").read_text()
    harness += function(alarm, "inline bool sensor_configured(const DSSensor& sensor)")
    harness += function(alarm, "inline bool sensor_temp_at_least(const DSSensor& sensor, float temp)")
    harness += function((ROOT / "sensorinit.h").read_text(), "void scan_ds_adress()")
    harness += function(
        (ROOT / "mode_common.h").read_text(),
        "inline bool mode_should_open_cooling(bool requirePower, bool includeAcp, bool includeTank)",
    )
    # Берём параметры общего условия из настоящих обработчиков режимов.
    checks = ""
    for filename in ("alarm.h", "distiller.h", "BK.h", "nbk.h"):
        source = (ROOT / filename).read_text()
        call = re.search(r"mode_should_open_cooling\([^)]*\)", source)[0]
        checks += f'  check(!{call}, "{filename}: cold boot must not open water without heat");\n'
    harness += r'''
int main() {
  for (float ambient : {18.0f, 31.0f}) {
    reset_sensors();
    sensors.completed = 0;
    // И холодное включение, и повторное сканирование после async-опроса.
    sensors.waitForConversion = false;
    for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
      sensors.readings[i] = 85.0f;
      sensors.measured[i] = ambient + i;
    }
    scan_ds_adress();
    check(sensors.completed == 1, "scan must finish the first conversion before returning");
    check(!sensors.waitForConversion, "regular polling must remain asynchronous");
    DS_getvalue();
    for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) {
      check(std::fabs(sensorList[i]->avgTemp - (ambient + i)) < 1e-4,
            "first reading must be measured temperature, not power-on 85C");
    }
''' + checks + r'''
    check(sensors.completed == 1, "regular polling must not wait for conversion");
    sensors.measured[0] = ambient + 6;
    sensors.complete();
    DS_getvalue();
    check(std::fabs(SteamSensor.avgTemp - (ambient + 6)) < 1e-4,
          "next polling must accept the next completed measurement");
  }
  // Реальные 85°C нельзя отбрасывать: горячая ТСА требует воды без нагрева.
  reset_sensors();
  for (uint8_t i = 0; i < DS_SENSOR_COUNT; i++) sensors.measured[i] = 85.0f;
  scan_ds_adress();
  DS_getvalue();
  check(ACPSensor.avgTemp == 85.0f, "real 85C at startup must remain readable");
  check(mode_should_open_cooling(false, true, true),
        "hot ACP must still open water with heater off");
  if (failures) return 1;
  std::cout << "PASS: cold-start conversion and cooling across column modes\n";
}
'''
    return compile_and_run(harness, "cold-start cooling")


if __name__ == "__main__":
    raise SystemExit(main())
