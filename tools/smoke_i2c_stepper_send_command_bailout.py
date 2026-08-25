#!/usr/bin/env python3
"""[Ревью 24.08, ошибка 1 + предупреждение 4] i2c_stepper_send_command() раньше
всегда делал все 20 попыток подтверждения команды, даже когда i2c_stepper_refresh()
уже сообщил, что устройство пропало (dev.present=false) - на зависшей/оборванной
шине, где каждая попытка стоит до I2C_LOCK_WAIT_MS=1000 мс, это было до ~20 секунд
СИНХРОННО внутри loop(), который сам под сторожем (esp_task_wdt) на
LOOP_WDT_TIMEOUT_S=10 секунд. Затем выяснилось, что выход по ПЕРВОЙ же неудаче
refresh() перегибал в другую сторону: одиночная помеха на шине (или LcdLockGuard,
на долю секунды занявший xI2CSemaphore перерисовкой LCD) - не то же самое, что
пропажа устройства, а цикл сдавался немедленно. Сейчас выход - по
I2CSTEPPER_FAIL_STREAK_ALERT (5) неудачам ПОДРЯД.

Компилирует РЕАЛЬНЫЕ тела функций (i2c_stepper_send_command/refresh/read_block/
read_byte/read_u16/read_u32/write_byte/check_I2C_device/note_refresh_failure),
извлечённые из I2CStepper.h, реальные safety_deadline_after()/safety_deadline_expired()
из safety_transition.h (send_command переиспользует их вместо ручной арифметики),
вместе с реальным списком полей struct I2CStepperDevice и реальным списком
регистров/команд - так все мутации, которые снимают защиту (ранний выход по
streak, порог streak, общий дедлайн по millis()), обязаны уронить тест, а не
остаться незамеченными.

Сценарий А: устройство не отвечает на пробу адреса вообще ("молчащая" шина) -
цикл обязан остановиться ровно после I2CSTEPPER_FAIL_STREAK_ALERT неудачных
попыток ПОДРЯД, а не после первой же и не после всех 20.

Сценарий Б: устройство отвечает (present остаётся true), но ackSeq никогда не
совпадёт (например, испорченная прошивка платы стоит бракованная) - здесь streak
неудач не растёт (refresh() каждый раз возвращает true), и только общий дедлайн
по millis() может остановить цикл раньше границы в 20 попыток. Каждая попытка в
этом сценарии искусственно "стоит" 400 мс подряд, имитируя занятую/полуживую
шину - это модель ИМЕННО семафорной задержки внутри check_I2C_device()/
i2c_stepper_read_block(), а не аппаратного зависания самой шины Wire (последнее -
отдельный, не устранённый этой правкой риск, см. отчёт).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

i2c_text = (ROOT / "I2CStepper.h").read_text(encoding="utf-8", errors="ignore")
safety_text = (ROOT / "safety_transition.h").read_text(encoding="utf-8", errors="ignore")


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
command_enum_body = block("enum I2CStepperCommand : uint8_t {")
device_struct_body = block("struct I2CStepperDevice {")
check_device_body = fn("inline uint8_t check_I2C_device(uint8_t address, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
read_block_body = fn("inline bool i2c_stepper_read_block(uint8_t address, uint8_t reg, uint8_t* data, uint8_t len, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
read_byte_body = fn("inline bool i2c_stepper_read_byte(uint8_t address, uint8_t reg, uint8_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
read_u16_body = fn("inline bool i2c_stepper_read_u16(uint8_t address, uint8_t reg, uint16_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
read_u32_body = fn("inline bool i2c_stepper_read_u32(uint8_t address, uint8_t reg, uint32_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS)")
write_byte_body = fn("inline bool i2c_stepper_write_byte(uint8_t address, uint8_t reg, uint8_t value)")
note_failure_body = fn("inline void i2c_stepper_note_refresh_failure(I2CStepperDevice& dev)")
refresh_body = fn("inline bool i2c_stepper_refresh(I2CStepperDevice& dev, bool force, TickType_t lockWaitMs)")
send_command_body = fn("inline bool i2c_stepper_send_command(I2CStepperDevice& dev, uint8_t command)")


def safety_fn(signature: str) -> str:
    try:
        return extract_function_body(safety_text, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


# [Ревью 24.08, замечание 5] send_command() теперь считает дедлайн через эти два
# хелпера из safety_transition.h вместо ручной арифметики millis() - извлекаем
# РЕАЛЬНЫЕ тела, чтобы харнесс не разошёлся с прошивкой.
deadline_expired_body = safety_fn("inline bool safety_deadline_expired(uint32_t now, uint32_t deadline)")
deadline_after_body = safety_fn("inline uint32_t safety_deadline_after(uint32_t now, uint32_t delayMs)")

if errors:
    print("i2c_stepper send_command bailout smoke failed to extract sources:")
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
#define portTICK_PERIOD_MS 1

#define I2CSTEPPER_MAGIC 0x53
#define I2CSTEPPER_PROTO_VERSION 2
#define I2CSTEPPER_FAIL_STREAK_ALERT 5
#define I2C_LOCK_WAIT_MS 1000
#define I2C_CACHE_LOCK_WAIT_MS 100

enum I2CStepperRegister : uint8_t {
@REGISTER_ENUM@
};

enum I2CStepperCommand : uint8_t {
@COMMAND_ENUM@
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
SemaphoreHandle_t xMsgSemaphore = 1;
int xSemaphoreTake(SemaphoreHandle_t, TickType_t) { return pdTRUE; }
void xSemaphoreGive(SemaphoreHandle_t) {}

static int sendMsgCalls = 0;
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

// --- Фиктивный таймер: millis()/vTaskDelay() двигают один и тот же счётчик, как
//     на реальной прошивке. checkDeviceCalls считает попытки подтверждения (ровно
//     одна на итерацию retry-цикла в send_command, т.к. check_I2C_device() -
//     первая операция внутри i2c_stepper_refresh()). perCallAdvanceMs имитирует
//     "дорогую" попытку (занятый семафор) - настраивается на сценарий.
static uint32_t fakeMillis = 0;
static int checkDeviceCalls = 0;
static uint32_t perCallAdvanceMs = 0;
uint32_t millis() { return fakeMillis; }
void vTaskDelay(TickType_t ticks) { fakeMillis += static_cast<uint32_t>(ticks); }

// --- Подставная шина: probeNack моделирует отказ на самой пробе адреса (bare
//     beginTransmission/endTransmission без write() - именно так устроен реальный
//     check_I2C_device()). failReg моделирует отказ конкретного регистра.
//     useTransientFail/transientFailCalls моделируют ВРЕМЕННУЮ помеху (сценарий В):
//     первые transientFailCalls обращений к check_I2C_device() проваливаются, затем
//     шина "отпускает" сама - probeNack вычисляется динамически по checkDeviceCalls
//     вместо статичного значения, которое использует сценарий А.
struct FakeWireState {
  uint8_t regs[64] = {};
  uint8_t lastReg = 0;
  bool regWritten = false;
  uint8_t failReg = 0xFF;
  uint8_t readCursor = 0;
  bool probeNack = false;
  bool useTransientFail = false;
  int transientFailCalls = 0;
};
static FakeWireState wireState;

class FakeWire {
 public:
  void beginTransmission(uint8_t) { wireState.regWritten = false; }
  size_t write(uint8_t reg) { wireState.lastReg = reg; wireState.regWritten = true; return 1; }
  int endTransmission(bool stop = true) {
    (void)stop;
    if (!wireState.regWritten) return wireState.probeNack ? 1 : 0;
    if (wireState.lastReg == wireState.failReg) return 1;
    return 0;
  }
  uint8_t requestFrom(uint8_t, uint8_t len) {
    wireState.readCursor = wireState.lastReg;
    return len;
  }
  int read() { return wireState.regs[wireState.readCursor++]; }
};
static FakeWire Wire;

class FakeI2C2 {
 public:
  uint8_t writeByte(uint8_t, uint8_t, uint8_t) { return 0; }
};
static FakeI2C2 I2C2 __attribute__((unused));

inline bool i2c_stepper_config_busy(const I2CStepperDevice&) { return false; }

// checkDeviceCalls/fakeMillis двигаются ЗДЕСЬ, в обвязке харнесса - тело функции
// ниже дословно взято из I2CStepper.h и не тронуто (ссылается на lockWaitMs -
// параметр добавлен [Ревью 24.08, ошибка 3], сигнатура здесь обязана совпадать).
// useTransientFail пересчитывает probeNack по числу уже сделанных попыток - для
// сценария В (временная помеха, которая сама проходит).
inline uint8_t check_I2C_device(uint8_t address, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
  checkDeviceCalls++;
  fakeMillis += perCallAdvanceMs;
  if (wireState.useTransientFail) {
    wireState.probeNack = checkDeviceCalls <= wireState.transientFailCalls;
  }
@CHECK_DEVICE_BODY@
}

inline bool i2c_stepper_read_block(uint8_t address, uint8_t reg, uint8_t* data, uint8_t len, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
@READ_BLOCK_BODY@
}

inline bool i2c_stepper_read_byte(uint8_t address, uint8_t reg, uint8_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
@READ_BYTE_BODY@
}

inline bool i2c_stepper_read_u16(uint8_t address, uint8_t reg, uint16_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
@READ_U16_BODY@
}

inline bool i2c_stepper_read_u32(uint8_t address, uint8_t reg, uint32_t& value, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
@READ_U32_BODY@
}

inline bool i2c_stepper_write_byte(uint8_t address, uint8_t reg, uint8_t value) {
@WRITE_BYTE_BODY@
}

inline void i2c_stepper_note_refresh_failure(I2CStepperDevice& dev) {
@NOTE_FAILURE_BODY@
}

inline bool i2c_stepper_refresh(I2CStepperDevice& dev, bool force, TickType_t lockWaitMs = I2C_LOCK_WAIT_MS) {
@REFRESH_BODY@
}

inline bool safety_deadline_expired(uint32_t now, uint32_t deadline) {
@DEADLINE_EXPIRED_BODY@
}

inline uint32_t safety_deadline_after(uint32_t now, uint32_t delayMs) {
@DEADLINE_AFTER_BODY@
}

inline bool i2c_stepper_send_command(I2CStepperDevice& dev, uint8_t command) {
@SEND_COMMAND_BODY@
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

  // --- Сценарий А: шина "молчит" - устройство не отвечает даже на пробу адреса.
  //     Раньше (до меры 1) цикл всё равно делал все 20 попыток. Затем (до меры 4)
  //     ранний выход останавливал цикл уже после ПЕРВОЙ неудачи - одиночная помеха
  //     на шине принималась за пропажу устройства. Сейчас выход - строго после
  //     I2CSTEPPER_FAIL_STREAK_ALERT неудач ПОДРЯД, не раньше и не позже.
  {
    wireState = FakeWireState{};
    wireState.probeNack = true;
    checkDeviceCalls = 0;
    perCallAdvanceMs = 0;
    fakeMillis = 0;

    I2CStepperDevice dev{};
    dev.address = ADDR;
    dev.present = true;
    dev.commandSeq = 0;

    bool ok = i2c_stepper_send_command(dev, I2CSTEP_CMD_START);
    check(!ok, "send_command must report failure when the device stops answering");
    check(!dev.present, "device must end up marked absent after a silent bus");
    check(checkDeviceCalls == I2CSTEPPER_FAIL_STREAK_ALERT,
          "bailout must stop the retry loop after exactly I2CSTEPPER_FAIL_STREAK_ALERT "
          "consecutive failed refreshes (was: 1 attempt before [warning 4], 20 before [error 1])");
  }

  // --- Сценарий Б: устройство отвечает (present остаётся true), но ackSeq
  //     никогда не совпадёт. Здесь ранний выход не сработает - только общий
  //     дедлайн по millis() может остановить цикл раньше границы в 20 попыток.
  //     Каждая попытка искусственно "стоит" 400 мс - имитация занятого семафора.
  {
    wireState = FakeWireState{};
    wireState.probeNack = false;
    wireState.failReg = 0xFF;
    wireState.regs[I2CSTEP_REG_MAGIC] = I2CSTEPPER_MAGIC;
    wireState.regs[I2CSTEP_REG_VERSION] = I2CSTEPPER_PROTO_VERSION;
    wireState.regs[I2CSTEP_REG_ACK_SEQ] = 0;  // seq стартует с 1 - никогда не совпадёт
    checkDeviceCalls = 0;
    perCallAdvanceMs = 400;
    fakeMillis = 0;

    I2CStepperDevice dev{};
    dev.address = ADDR;
    dev.present = true;
    dev.commandSeq = 0;

    bool ok = i2c_stepper_send_command(dev, I2CSTEP_CMD_START);
    check(!ok, "send_command must report failure when ackSeq never matches");
    check(dev.present, "a device that keeps answering must stay marked present");
    check(checkDeviceCalls < 20,
          "overall millis() deadline must stop the loop well before the 20-attempt cap when every attempt is slow (was: unbounded by time)");
    check(checkDeviceCalls >= 5,
          "deadline must not fire so early that a normally-slow device never gets a fair chance to ack");
  }

  // --- Сценарий В [Ревью 24.08, предупреждение 4]: временная помеха - устройство не
  //     отвечает на пробу адреса I2CSTEPPER_FAIL_STREAK_ALERT-1 раз подряд (меньше
  //     порога), затем шина "отпускает" и всё успешно подтверждается. До меры 4 это
  //     ложно провалилось бы (выход по первой же неудаче), хотя устройство было на
  //     связи и просто ответило на 1 попытку позже.
  {
    wireState = FakeWireState{};
    wireState.useTransientFail = true;
    wireState.transientFailCalls = I2CSTEPPER_FAIL_STREAK_ALERT - 1;
    wireState.failReg = 0xFF;
    wireState.regs[I2CSTEP_REG_MAGIC] = I2CSTEPPER_MAGIC;
    wireState.regs[I2CSTEP_REG_VERSION] = I2CSTEPPER_PROTO_VERSION;
    wireState.regs[I2CSTEP_REG_ACK_SEQ] = 1;  // seq стартует с 1 - совпадёт сразу же
    checkDeviceCalls = 0;
    perCallAdvanceMs = 0;
    fakeMillis = 0;

    I2CStepperDevice dev{};
    dev.address = ADDR;
    dev.present = true;
    dev.commandSeq = 0;

    bool ok = i2c_stepper_send_command(dev, I2CSTEP_CMD_START);
    check(ok, "send_command must still succeed when failures stop short of the streak "
              "threshold and the device then acks (single/few-glitch tolerance)");
    check(dev.present, "device that eventually answers must end up marked present");
    check(checkDeviceCalls == I2CSTEPPER_FAIL_STREAK_ALERT,
          "loop must spend exactly (threshold-1) failed attempts plus the first "
          "successful one, not bail out earlier");
  }

  if (failures != 0) return 1;
  std::cout << "i2c_stepper send_command bailout checks passed\n";
  return 0;
}
'''


def build_source() -> str:
    src = HARNESS
    src = src.replace("@REGISTER_ENUM@", register_enum_body)
    src = src.replace("@COMMAND_ENUM@", command_enum_body)
    src = src.replace("@DEVICE_STRUCT@", device_struct_body)
    src = src.replace("@CHECK_DEVICE_BODY@", check_device_body)
    src = src.replace("@READ_BLOCK_BODY@", read_block_body)
    src = src.replace("@READ_BYTE_BODY@", read_byte_body)
    src = src.replace("@READ_U16_BODY@", read_u16_body)
    src = src.replace("@READ_U32_BODY@", read_u32_body)
    src = src.replace("@WRITE_BYTE_BODY@", write_byte_body)
    src = src.replace("@NOTE_FAILURE_BODY@", note_failure_body)
    src = src.replace("@REFRESH_BODY@", refresh_body)
    src = src.replace("@DEADLINE_EXPIRED_BODY@", deadline_expired_body)
    src = src.replace("@DEADLINE_AFTER_BODY@", deadline_after_body)
    src = src.replace("@SEND_COMMAND_BODY@", send_command_body)
    return src


def run() -> None:
    compiler = shutil.which("g++")
    if compiler is None:
        errors.append("g++ is required for the i2c_stepper send_command bailout harness")
        return
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-send-command-bailout-") as tmp:
        tmp_path = Path(tmp)
        source_path = tmp_path / "send_command_bailout.cpp"
        binary_path = tmp_path / "send_command_bailout"
        source_path.write_text(build_source(), encoding="utf-8")
        compile_result = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append("send_command bailout harness compile failed:\n" + compile_result.stdout + compile_result.stderr)
            return
        run_result = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
        if run_result.returncode != 0:
            errors.append("send_command bailout harness runtime checks failed:\n" + run_result.stdout + run_result.stderr)


run()

if errors:
    print("i2c_stepper send_command bailout smoke failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("i2c_stepper send_command bailout smoke passed")
