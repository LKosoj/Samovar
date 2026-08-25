#!/usr/bin/env python3
"""T25.2: i2c_stepper_write_u16() обязана писать 16-битный регистр ОДНОЙ raw-
транзакцией Wire (beginTransmission/write x3/endTransmission), а не двумя
отдельными I2C2.writeByte() - иначе приёмник может прочитать наполовину
записанное значение между двумя транзакциями.

Компилирует РЕАЛЬНОЕ тело i2c_stepper_write_u16(), извлечённое из
I2CStepper.h. FakeI2C2.writeByte() сам делает одну законченную транзакцию
через тот же общий мок Wire (как это в реальности делает низкоуровневая
iarduino_I2C_connect), поэтому мутация "вернуть два I2C2.writeByte()" честно
проявляется как двойной вызов endTransmission, а не как расхождение мока.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

i2c_text = (ROOT / "I2CStepper.h").read_text(encoding="utf-8", errors="ignore")

try:
    write_u16_body = extract_function_body(i2c_text, "inline bool i2c_stepper_write_u16(uint8_t address, uint8_t reg, uint16_t value)")
except ValueError as exc:
    errors.append(str(exc))
    write_u16_body = ""

if errors:
    print("i2c_stepper_write_u16 atomic smoke failed to extract source:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <vector>

using TickType_t = int;
using SemaphoreHandle_t = int;
#define pdTRUE 1
#define portTICK_RATE_MS 1

SemaphoreHandle_t xI2CSemaphore = 1;
int xSemaphoreTake(SemaphoreHandle_t, TickType_t) { return pdTRUE; }
void xSemaphoreGive(SemaphoreHandle_t) {}

struct FakeWireState {
  int beginCount = 0;
  int endCount = 0;
  std::vector<uint8_t> writes;
};
static FakeWireState wireState;

class FakeWire {
 public:
  void beginTransmission(uint8_t) { wireState.beginCount++; }
  size_t write(uint8_t value) { wireState.writes.push_back(value); return 1; }
  int endTransmission(bool stop = true) { (void)stop; wireState.endCount++; return 0; }
};
static FakeWire Wire;

// Имитирует реальную iarduino_I2C_connect: один writeByte() - одна
// законченная I2C-транзакция (begin+write x2+end) через ту же шину, что и
// прямой Wire-путь выше - иначе мутация "два writeByte" была бы неотличима
// от одной raw-транзакции по числу вызовов endTransmission.
class FakeI2C2 {
 public:
  uint8_t writeByte(uint8_t address, uint8_t reg, uint8_t value) {
    Wire.beginTransmission(address);
    Wire.write(reg);
    Wire.write(value);
    return static_cast<uint8_t>(Wire.endTransmission());
  }
};
static FakeI2C2 I2C2 __attribute__((unused));

inline bool i2c_stepper_write_u16(uint8_t address, uint8_t reg, uint16_t value) {
@WRITE_U16_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  wireState = FakeWireState{};
  bool ok = i2c_stepper_write_u16(2, 13, 0x1234);
  check(ok, "write_u16 must report success when the bus acks");

  check(wireState.beginCount == 1,
        "write_u16 must open exactly one I2C transaction (found a different count - old code opened two)");
  check(wireState.endCount == 1,
        "write_u16 must close exactly one I2C transaction - endTransmission must not be called twice");

  if (wireState.writes.size() >= 3) {
    check(wireState.writes[0] == 13, "first byte on the wire must be the register address");
    check(wireState.writes[1] == 0x12, "second byte on the wire must be the high byte, written before the low byte");
    check(wireState.writes[2] == 0x34, "third byte on the wire must be the low byte");
  } else {
    check(false, "write_u16 must write reg+hi+lo (3 bytes) inside the single transaction");
  }

  if (failures != 0) return 1;
  std::cout << "i2c_stepper_write_u16 atomic checks passed\n";
  return 0;
}
'''


def build_source() -> str:
    return HARNESS.replace("@WRITE_U16_BODY@", write_u16_body)


def run() -> None:
    compiler = shutil.which("g++")
    if compiler is None:
        errors.append("g++ is required for the i2c_stepper_write_u16 atomic harness")
        return
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-write-u16-") as tmp:
        tmp_path = Path(tmp)
        source_path = tmp_path / "write_u16_atomic.cpp"
        binary_path = tmp_path / "write_u16_atomic"
        source_path.write_text(build_source(), encoding="utf-8")
        compile_result = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append("write_u16 atomic harness compile failed:\n" + compile_result.stdout + compile_result.stderr)
            return
        run_result = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
        if run_result.returncode != 0:
            errors.append("write_u16 atomic harness runtime checks failed:\n" + run_result.stdout + run_result.stderr)


run()

if errors:
    print("i2c_stepper_write_u16 atomic smoke failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("i2c_stepper_write_u16 atomic smoke passed")
