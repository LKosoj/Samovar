#!/usr/bin/env python3
"""T25.1: i2c_stepper_read_byte() обязана делегировать на i2c_stepper_read_block()
(который на отказе НЕ трогает выходной буфер), а i2c_stepper_refresh() - копить
refreshFailStreak и сообщать РОВНО ОДИН раз при достижении порога
I2CSTEPPER_FAIL_STREAK_ALERT.

Компилирует РЕАЛЬНЫЕ тела функций (i2c_stepper_read_block/read_byte/read_u16/
read_u32/check_I2C_device/i2c_stepper_note_refresh_failure/i2c_stepper_refresh),
извлечённые из I2CStepper.h, вместе с реальным списком полей struct
I2CStepperDevice и реальным списком регистров enum I2CStepperRegister - так
мутация тела read_byte (возврат старого `I2C2.readByte(...); return true;`)
обязана уронить тест, а не остаться незамеченной.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

i2c_text = (ROOT / "I2CStepper.h").read_text(encoding="utf-8", errors="ignore")


def define_line(name: str) -> str:
    m = re.search(rf"#define {re.escape(name)} .*", i2c_text)
    if not m:
        errors.append(f"missing #define: {name}")
        return f"#define {name} 0"
    return m.group()


def block(token: str) -> str:
    try:
        body, _ = extract_braced_block_after(i2c_text, token)
        return body
    except ValueError as exc:
        errors.append(str(exc))
        return ""


def fn(signature: str) -> str:
    try:
        return extract_function_body(i2c_text, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


register_enum_body = block("enum I2CStepperRegister : uint8_t {")
device_struct_body = block("struct I2CStepperDevice {")
read_block_body = fn("inline bool i2c_stepper_read_block(uint8_t address, uint8_t reg, uint8_t* data, uint8_t len, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
read_byte_body = fn("inline bool i2c_stepper_read_byte(uint8_t address, uint8_t reg, uint8_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
read_u16_body = fn("inline bool i2c_stepper_read_u16(uint8_t address, uint8_t reg, uint16_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
read_u32_body = fn("inline bool i2c_stepper_read_u32(uint8_t address, uint8_t reg, uint32_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
check_device_body = fn("inline uint8_t check_I2C_device(uint8_t address, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
note_failure_body = fn("inline void i2c_stepper_note_refresh_failure(I2CStepperDevice& dev)")
refresh_body = fn("inline bool i2c_stepper_refresh(I2CStepperDevice& dev, bool force, TickType_t lockWaitMs)")

if errors:
    print("i2c_stepper refresh fail-streak smoke failed to extract sources:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>

using TickType_t = int;
using SemaphoreHandle_t = int;
#define pdTRUE 1
#define portTICK_RATE_MS 1

@MAGIC_DEFINE@
@PROTO_DEFINE@
@ALERT_DEFINE@

enum I2CStepperRegister : uint8_t {
@REGISTER_ENUM@
};

struct I2CStepperDevice {
@DEVICE_STRUCT@
};

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(uint8_t value) : value_(std::to_string(value)) {}
  String& operator+=(const String& value) { value_ += value.value_; return *this; }
 private:
  std::string value_;
};
inline String operator+(String lhs, const String& rhs) { lhs += rhs; return lhs; }

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };

SemaphoreHandle_t xI2CSemaphore = 1;
SemaphoreHandle_t xMsgSemaphore = 1;  // detect_i2c_steppers() идёт после его создания в setup()
int xSemaphoreTake(SemaphoreHandle_t, TickType_t) { return pdTRUE; }
void xSemaphoreGive(SemaphoreHandle_t) {}

static int sendMsgCalls = 0;
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

// --- Подставная шина: различает пробу адреса (check_I2C_device, регистр не
//     пишется) и транзакцию чтения регистра (write(reg) перед endTransmission).
struct FakeWireState {
  uint8_t regs[64] = {};
  uint8_t lastReg = 0;
  bool regWritten = false;
  uint8_t failReg = 0xFF;
  uint8_t readCursor = 0;
};
static FakeWireState wireState;

class FakeWire {
 public:
  void beginTransmission(uint8_t) { wireState.regWritten = false; }
  size_t write(uint8_t reg) { wireState.lastReg = reg; wireState.regWritten = true; return 1; }
  int endTransmission(bool stop = true) {
    (void)stop;
    if (wireState.regWritten && wireState.lastReg == wireState.failReg) return 1;
    return 0;
  }
  uint8_t requestFrom(uint8_t, uint8_t len) {
    wireState.readCursor = wireState.lastReg;
    return len;
  }
  int read() { return wireState.regs[wireState.readCursor++]; }
};
static FakeWire Wire;

// I2C2 нужен только чтобы мутация (возврат старого тела read_byte) слинковалась -
// имитирует "тихо отдаёт 0 на сбое" из тикета.
class FakeI2C2 {
 public:
  uint8_t readByte(uint8_t, uint8_t) { return 0; }
};
// Используется только мутацией (старое тело read_byte зовёт I2C2.readByte
// напрямую) - текущий код на неё не ссылается, поэтому подавляем -Wunused.
static FakeI2C2 I2C2 __attribute__((unused));

inline bool i2c_stepper_config_busy(const I2CStepperDevice&) { return false; }

inline uint8_t check_I2C_device(uint8_t address, TickType_t lockWaitMs = 1000) {
@CHECK_DEVICE_BODY@
}

inline bool i2c_stepper_read_block(uint8_t address, uint8_t reg, uint8_t* data, uint8_t len, TickType_t lockWaitMs = 1000) {
@READ_BLOCK_BODY@
}

inline bool i2c_stepper_read_byte(uint8_t address, uint8_t reg, uint8_t& value, TickType_t lockWaitMs = 1000) {
@READ_BYTE_BODY@
}

inline bool i2c_stepper_read_u16(uint8_t address, uint8_t reg, uint16_t& value, TickType_t lockWaitMs = 1000) {
@READ_U16_BODY@
}

inline bool i2c_stepper_read_u32(uint8_t address, uint8_t reg, uint32_t& value, TickType_t lockWaitMs = 1000) {
@READ_U32_BODY@
}

inline void i2c_stepper_note_refresh_failure(I2CStepperDevice& dev) {
@NOTE_FAILURE_BODY@
}

inline bool i2c_stepper_refresh(I2CStepperDevice& dev, bool force, TickType_t lockWaitMs) {
@REFRESH_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  const uint8_t ADDR = 2;
  I2CStepperDevice dev{};
  dev.address = ADDR;

  wireState = FakeWireState{};
  wireState.regs[I2CSTEP_REG_MAGIC] = 0x53;
  wireState.regs[I2CSTEP_REG_VERSION] = 2;
  wireState.regs[I2CSTEP_REG_STATUS] = 0x11;
  wireState.failReg = 0xFF;  // ничего не падает

  // (а) успешное обновление.
  bool ok = i2c_stepper_refresh(dev, true, 1000);
  check(ok, "clean refresh must report success");
  check(dev.present, "clean refresh must set present=true");
  check(dev.refreshFailStreak == 0, "clean refresh must keep refreshFailStreak at 0");
  check(dev.status == 0x11, "clean refresh must read real status from the bus");
  check(sendMsgCalls == 0, "no failure message on a clean refresh");

  // (б) 5 подряд отказов: ломаем чтение MIXER_RPM (u16, всегда идёт через Wire
  //     независимо от мутации read_byte) - present должен упасть, а status
  //     остаться от последнего успеха.
  wireState.failReg = I2CSTEP_REG_MIXER_RPM_H;
  for (int i = 1; i <= 5; i++) {
    bool iterOk = i2c_stepper_refresh(dev, true, 1000);
    check(!iterOk, "refresh with a broken register must report failure");
    check(!dev.present, "refresh with a broken register must clear present");
    check(dev.refreshFailStreak == static_cast<uint8_t>(i),
          "refreshFailStreak must increment exactly once per failed refresh");
  }

  check(dev.refreshFailStreak == 5, "refreshFailStreak must reach the alert threshold");
  check(dev.status == 0x11,
        "status must stay at the last good cached value, not be corrupted by a failed refresh");
  check(sendMsgCalls == 1,
        "the fail-streak message must fire exactly once (streak==threshold), not once per failed refresh");

  // Ещё один отказ не должен слать сообщение повторно (не спамим).
  bool sixthOk = i2c_stepper_refresh(dev, true, 1000);
  check(!sixthOk, "sixth consecutive failure must still report failure");
  check(dev.refreshFailStreak == 6, "refreshFailStreak keeps counting past the alert threshold");
  check(sendMsgCalls == 1, "message must not repeat on further failures past the threshold");

  if (failures != 0) return 1;
  std::cout << "i2c_stepper refresh fail-streak checks passed\n";
  return 0;
}
'''


def build_source() -> str:
    src = HARNESS
    src = src.replace("@MAGIC_DEFINE@", define_line("I2CSTEPPER_MAGIC"))
    src = src.replace("@PROTO_DEFINE@", define_line("I2CSTEPPER_PROTO_VERSION"))
    src = src.replace("@ALERT_DEFINE@", define_line("I2CSTEPPER_FAIL_STREAK_ALERT"))
    src = src.replace("@REGISTER_ENUM@", register_enum_body)
    src = src.replace("@DEVICE_STRUCT@", device_struct_body)
    src = src.replace("@CHECK_DEVICE_BODY@", check_device_body)
    src = src.replace("@READ_BLOCK_BODY@", read_block_body)
    src = src.replace("@READ_BYTE_BODY@", read_byte_body)
    src = src.replace("@READ_U16_BODY@", read_u16_body)
    src = src.replace("@READ_U32_BODY@", read_u32_body)
    src = src.replace("@NOTE_FAILURE_BODY@", note_failure_body)
    src = src.replace("@REFRESH_BODY@", refresh_body)
    return src


def run() -> None:
    compiler = shutil.which("g++")
    if compiler is None:
        errors.append("g++ is required for the i2c_stepper refresh fail-streak harness")
        return
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-refresh-fail-streak-") as tmp:
        tmp_path = Path(tmp)
        source_path = tmp_path / "refresh_fail_streak.cpp"
        binary_path = tmp_path / "refresh_fail_streak"
        source_path.write_text(build_source(), encoding="utf-8")
        compile_result = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append("refresh fail-streak harness compile failed:\n" + compile_result.stdout + compile_result.stderr)
            return
        run_result = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
        if run_result.returncode != 0:
            errors.append("refresh fail-streak harness runtime checks failed:\n" + run_result.stdout + run_result.stderr)


run()

if errors:
    print("i2c_stepper refresh fail-streak smoke failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("i2c_stepper refresh fail-streak smoke passed")
