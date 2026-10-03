#!/usr/bin/env python3
"""Проверяет, что ожидания BME680 и BME280 имеют ограничение времени.

Исполняет извлечённые тела настоящих функций библиотек с небольшими моделями
датчиков. Мутации убирают только условия таймаутов и должны быть пойманы самим
тестом, а не ограничением времени запуска компилятора.
"""
import re
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
BME68X_DEFS = (ROOT / "libraries/Adafruit_BME680_Library/bme68x_defs.h").as_posix()

HARNESS = r'''
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>

#include "@BME68X_DEFS@"

enum { BME280_REGISTER_CHIPID = 0xD0, BME280_REGISTER_SOFTRESET = 0xE0,
       BME280_REGISTER_STATUS = 0xF3 };

struct Bme68xState {
  uint64_t nowUs = 0;
  int readyAfterReads = 0;
  int reads = 0;
  int setCalls = 0;
  uint8_t finalMode = 255;
  int error = BME68X_OK;
};

static void fail_budget(const char* sensor) {
  std::cerr << "FAIL: sensor wait exceeded test budget (" << sensor << ")\n";
  std::exit(2);
}

static int8_t fake_get_regs(uint8_t reg, uint8_t* data, uint32_t len,
                            struct bme68x_dev* dev) {
  auto* state = static_cast<Bme68xState*>(dev->intf_ptr);
  if (state->nowUs > 6000000) fail_budget("BME680");
  if (state->error != BME68X_OK) return static_cast<int8_t>(state->error);
  if (reg != BME68X_REG_CTRL_MEAS || len != 1) return BME68X_E_INVALID_LENGTH;
  ++state->reads;
  *data = state->reads > state->readyAfterReads ? BME68X_SLEEP_MODE
                                                  : BME68X_FORCED_MODE;
  return BME68X_OK;
}

static int8_t fake_set_regs(const uint8_t* reg, const uint8_t* data,
                            uint32_t len, struct bme68x_dev* dev) {
  auto* state = static_cast<Bme68xState*>(dev->intf_ptr);
  if (reg == nullptr || data == nullptr || len != 1) return BME68X_E_NULL_PTR;
  ++state->setCalls;
  state->finalMode = *data & BME68X_MODE_MSK;
  return BME68X_OK;
}

static void fake_delay(uint32_t period, void* ptr) {
  auto* state = static_cast<Bme68xState*>(ptr);
  state->nowUs += period;
}

int8_t bme68x_get_regs(uint8_t reg, uint8_t* data, uint32_t len,
                       struct bme68x_dev* dev) {
  return fake_get_regs(reg, data, len, dev);
}
int8_t bme68x_set_regs(const uint8_t* reg, const uint8_t* data, uint32_t len,
                       struct bme68x_dev* dev) {
  return fake_set_regs(reg, data, len, dev);
}
int8_t bme68x_set_op_mode(const uint8_t op_mode, struct bme68x_dev *dev);

int8_t run_bme680(int readyAfterReads, int error) {
  Bme68xState state;
  state.readyAfterReads = readyAfterReads;
  state.error = error;
  bme68x_dev dev{};
  dev.intf_ptr = &state;
  dev.read = nullptr;
  dev.write = nullptr;
  dev.delay_us = fake_delay;
  const int8_t result = bme68x_set_op_mode(BME68X_FORCED_MODE, &dev);
  if (readyAfterReads > 1000) {
    if (result != BME68X_E_COM_FAIL || state.nowUs < 5000000 ||
        state.nowUs > 5010000) {
      std::cerr << "BME680 stuck path did not stop at 5 seconds\n";
      return 5;
    }
    return result;
  }
  if (error != BME68X_OK) {
    if (result != error || state.reads != 0 || state.setCalls != 0)
      std::cerr << "BME680 error path was not preserved\n";
    return result;
  }
  if (result != BME68X_OK || state.reads != readyAfterReads + 1 ||
      state.setCalls != readyAfterReads + 1 ||
      state.finalMode != BME68X_FORCED_MODE) {
    std::cerr << "BME680 normal path has wrong reads or final mode\n";
    return 3;
  }
  return result;
}

int8_t bme68x_set_op_mode(const uint8_t op_mode, struct bme68x_dev *dev) {
@BME680_BODY@
}

static uint32_t fakeNowMs;
static void fakeFailBudget() {
  std::cerr << "FAIL: sensor wait exceeded test budget (BME280)\n";
  std::exit(2);
}

class Adafruit_BME280 {
 public:
  bool init();
  uint8_t read8(uint8_t reg);
  void write8(uint8_t reg, uint8_t value);
  bool isReadingCalibration();
  void readCoefficients();
  void setSampling();

  int readyAfterReads = 0;
  int calibrationReads = 0;
  int coefficientCalls = 0;
  int samplingCalls = 0;
  int writes = 0;
  int32_t _sensorID = 0;
};

static uint32_t millis() { return fakeNowMs; }
static void delay(uint32_t duration) {
  fakeNowMs += duration;
  if (fakeNowMs > 2000) fakeFailBudget();
}

uint8_t Adafruit_BME280::read8(uint8_t reg) {
  if (reg == BME280_REGISTER_CHIPID) return 0x60;
  if (reg == BME280_REGISTER_STATUS) {
    ++calibrationReads;
    return calibrationReads <= readyAfterReads ? 1 : 0;
  }
  return 0;
}
void Adafruit_BME280::write8(uint8_t, uint8_t) { ++writes; }
bool Adafruit_BME280::isReadingCalibration() {
  return (read8(BME280_REGISTER_STATUS) & (1 << 0)) != 0;
}
void Adafruit_BME280::readCoefficients() { ++coefficientCalls; }
void Adafruit_BME280::setSampling() { ++samplingCalls; }

bool Adafruit_BME280::init() {
@BME280_BODY@
}

static int run_bme280(int readyAfter) {
  fakeNowMs = 0;
  Adafruit_BME280 sensor;
  sensor.readyAfterReads = readyAfter;
  const bool result = sensor.init();
  if (readyAfter > 1000) {
    if (result || fakeNowMs < 1000 || fakeNowMs > 1020) {
      std::cerr << "BME280 stuck path did not stop at 1 second\n";
      return 6;
    }
    return 0;
  }
  if (!result || sensor.calibrationReads != readyAfter + 1 ||
      sensor.coefficientCalls != 1 || sensor.samplingCalls != 1) {
    std::cerr << "BME280 normal path has wrong reads or initialization calls\n";
    return 4;
  }
  return 0;
}

int main() {
  if (run_bme680(2, BME68X_OK) != BME68X_OK) return 1;
  if (run_bme680(7, BME68X_OK) != BME68X_OK) return 1;
  if (run_bme680(1000001, BME68X_OK) != BME68X_E_COM_FAIL) return 1;
  if (run_bme680(0, BME68X_E_COM_FAIL) != BME68X_E_COM_FAIL) return 1;
  if (run_bme280(2) != 0 || run_bme280(7) != 0) return 1;
  if (run_bme280(1000001) != 0) return 1;
  return 0;
}
'''


def main():
    bme680 = extract_function_body(
        (ROOT / "libraries/Adafruit_BME680_Library/bme68x.c").read_text(),
        "int8_t bme68x_set_op_mode(const uint8_t op_mode, struct bme68x_dev *dev)",
    )
    bme280 = extract_function_body(
        (ROOT / "libraries/Adafruit_BME280_Library/Adafruit_BME280.cpp").read_text(),
        "bool Adafruit_BME280::init()",
    )
    harness = (HARNESS.replace("@BME68X_DEFS@", BME68X_DEFS)
               .replace("@BME680_BODY@", bme680)
               .replace("@BME280_BODY@", bme280))
    bme680_timeout = "if ((rslt == BME68X_OK) && (sleep_wait_us >= UINT32_C(5000000)))"
    bme280_timeout = "if (millis() - calibrationStart >= 1000) return false;"
    mutations = [
        ("BME680 timeout", harness.replace(bme680_timeout, "if (false)"),
         "FAIL: sensor wait exceeded test budget (BME680)"),
        ("BME280 timeout", harness.replace(bme280_timeout,
                                            "if (millis() - calibrationStart >= 0xFFFFFFFFu) return false;"),
         "FAIL: sensor wait exceeded test budget (BME280)"),
    ]
    with tempfile.TemporaryDirectory(prefix="samovar-bme-waits-") as tmp:
        source = Path(tmp) / "test.cpp"
        binary = Path(tmp) / "test"
        source.write_text(harness)
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        str(source), "-o", str(binary)], check=True,
                       capture_output=True, text=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        for name, code, expected in mutations:
            source.write_text(code)
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True,
                           capture_output=True, text=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            assert result.returncode != 0 and expected in result.stderr, (
                f"{name}: mutation survived or failed for an unrelated reason: {result.stderr}"
            )
    print("PASS: BME680/BME280 normal, stuck, error paths and timeout mutations")


if __name__ == "__main__":
    main()
