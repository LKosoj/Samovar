#!/usr/bin/env python3
"""Поведенческая проверка клампа таймаута в runtime_helpers.h::append_runtime_event.

Раньше клэмп определял "своих" по xPortGetCoreID() == 0 — комментарий утверждал,
что на core0 сидят и SysTicker, и async_tcp. Это неверно: async_tcp запинен на
CONFIG_ASYNC_TCP_RUNNING_CORE=1 (platformio.ini), а на core0 жёстко запинены
только SysTickerTask1 и (при SAMOVAR_USE_POWER) PowerStatusTask (Samovar.ino).
Кламп переведён на сравнение хэндла текущей задачи с этими двумя хэндлами.

Тест берёт РЕАЛЬНОЕ тело append_runtime_event (через extract_function_body —
без переписывания логики) и подставляет его в минимальный host-харнесс,
подменяя только downstream-зависимости (runtime_state_lock и т.п.). Наблюдаем
поведение: какой timeout реально доезжает до runtime_state_lock() в
зависимости от того, чей xTaskGetCurrentTaskHandle() сейчас активен.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

using TickType_t = uint32_t;
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))

using TaskHandle_t = void*;

static TaskHandle_t currentTaskHandle = nullptr;
static TaskHandle_t xTaskGetCurrentTaskHandle() { return currentTaskHandle; }

@POWER_DEFINE@

TaskHandle_t SysTickerTask1 = reinterpret_cast<TaskHandle_t>(0x1001);
#ifdef SAMOVAR_USE_POWER
TaskHandle_t PowerStatusTask = reinterpret_cast<TaskHandle_t>(0x1002);
#endif
// Ни один из реальных клэмп-кандидатов: имитирует loopTask (core1) или
// гипотетический прямой вызов из async_tcp (тоже core1, CONFIG_ASYNC_TCP_RUNNING_CORE=1).
static TaskHandle_t OtherTask = reinterpret_cast<TaskHandle_t>(0x2001);

class String {
 public:
  String() = default;
  String(const char* value) : value_(value) {}
  size_t length() const { return value_.size(); }
  const char* c_str() const { return value_.c_str(); }

 private:
  std::string value_;
};

static const uint16_t RUNTIME_EVENT_MAX_TEXT_BYTES = 10000;

enum RuntimeEventKind : uint8_t { RUNTIME_EVENT_MESSAGE = 1, RUNTIME_EVENT_CONSOLE = 2 };
enum MESSAGE_TYPE : uint8_t { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };

enum RuntimeEventAppendResult : uint8_t {
  RUNTIME_EVENT_APPEND_OK = 0,
  RUNTIME_EVENT_APPEND_EMPTY,
  RUNTIME_EVENT_TEXT_TOO_LONG,
  RUNTIME_EVENT_APPEND_INVALID_ARGUMENT,
  RUNTIME_EVENT_APPEND_CORRUPT,
};

struct RuntimeEventRing {};
static RuntimeEventRing runtimeEventRing{};

static void runtime_event_init(RuntimeEventRing&) {}

static RuntimeEventAppendResult appendLockedResult = RUNTIME_EVENT_APPEND_OK;
static RuntimeEventAppendResult runtime_event_append_locked(
    RuntimeEventRing&, RuntimeEventKind, uint8_t, const char*, size_t) {
  return appendLockedResult;
}

static uint32_t millis() { return 0; }

// --- Наблюдаемая точка: какой timeout реально доезжает до лока ---
static TickType_t lastLockTimeout = 0;
static int lockCalls = 0;
static bool lockShouldSucceed = true;

static bool runtime_state_lock(TickType_t timeout) {
  lockCalls++;
  lastLockTimeout = timeout;
  return lockShouldSucceed;
}
static void runtime_state_unlock(bool) {}

enum RuntimeEventPublishResult : uint8_t {
  RUNTIME_EVENT_PUBLISH_OK = 0,
  RUNTIME_EVENT_PUBLISH_EMPTY,
  RUNTIME_EVENT_PUBLISH_LOCK_BUSY,
  RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG,
  RUNTIME_EVENT_PUBLISH_CORRUPT,
};

inline RuntimeEventPublishResult append_runtime_event(
    RuntimeEventKind kind, const String& text, uint8_t level,
    TickType_t timeout = pdMS_TO_TICKS(500)) {
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(TaskHandle_t task) {
  currentTaskHandle = task;
  lastLockTimeout = 0;
  lockCalls = 0;
  lockShouldSucceed = true;
  appendLockedResult = RUNTIME_EVENT_APPEND_OK;
}

static void test_systicker_clamped_to_50ms() {
  reset_fixture(SysTickerTask1);
  RuntimeEventPublishResult result = append_runtime_event(
      RUNTIME_EVENT_MESSAGE, String("payload"), 1, pdMS_TO_TICKS(500));
  check(lockCalls == 1, "SysTicker call did not reach runtime_state_lock ровно один раз");
  check(lastLockTimeout == pdMS_TO_TICKS(50),
        "SysTicker (core0, короткий цикл) не клэмпнут до 50мс");
  check(result == RUNTIME_EVENT_PUBLISH_OK, "успешная запись не долетела до OK");
}

#ifdef SAMOVAR_USE_POWER
static void test_power_status_clamped_to_50ms() {
  reset_fixture(PowerStatusTask);
  append_runtime_event(RUNTIME_EVENT_MESSAGE, String("payload"), 1, pdMS_TO_TICKS(500));
  check(lastLockTimeout == pdMS_TO_TICKS(50),
        "PowerStatusTask (core0, UART-цикл) не клэмпнут до 50мс");
}
#endif

static void test_other_task_keeps_full_timeout() {
  reset_fixture(OtherTask);
  append_runtime_event(RUNTIME_EVENT_MESSAGE, String("payload"), 1, pdMS_TO_TICKS(500));
  check(lastLockTimeout == pdMS_TO_TICKS(500),
        "задача, не входящая в список коротких таймаутов (loopTask/async_tcp), "
        "неожиданно урезана до 50мс");
}

static void test_short_requested_timeout_is_not_extended() {
  // Явный короткий таймаут вызывающего не должен раздуваться клэмпом.
  reset_fixture(SysTickerTask1);
  append_runtime_event(RUNTIME_EVENT_MESSAGE, String("payload"), 1, pdMS_TO_TICKS(10));
  check(lastLockTimeout == pdMS_TO_TICKS(10),
        "клэмп увеличил заведомо короткий таймаут вызывающего");
}

static void test_clamp_is_keyed_by_task_not_by_default_state() {
  // currentTaskHandle == nullptr (задача ещё не создана / хэндл не инициализирован)
  // не должен случайно совпасть ни с одним из хэндлов и получить клэмп.
  reset_fixture(nullptr);
  append_runtime_event(RUNTIME_EVENT_MESSAGE, String("payload"), 1, pdMS_TO_TICKS(500));
  check(lastLockTimeout == pdMS_TO_TICKS(500),
        "нулевой хэндл текущей задачи ошибочно приравнен к SysTicker/PowerStatusTask");
}

int main() {
  test_systicker_clamped_to_50ms();
#ifdef SAMOVAR_USE_POWER
  test_power_status_clamped_to_50ms();
#endif
  test_other_task_keeps_full_timeout();
  test_short_requested_timeout_is_not_extended();
  test_clamp_is_keyed_by_task_not_by_default_state();
  if (failures != 0) return 1;
  std::cout << "append_runtime_event task-handle clamp behaviour checks passed\n";
  return 0;
}
'''


def build_harness(define_power: bool) -> str:
    source = (ROOT / "runtime_helpers.h").read_text(encoding="utf-8")
    body = extract_function_body(source, "inline RuntimeEventPublishResult append_runtime_event(")
    power_define = "#define SAMOVAR_USE_POWER" if define_power else "// SAMOVAR_USE_POWER not defined for this build"
    return (
        HARNESS_TEMPLATE
        .replace("@BODY@", body)
        .replace("@POWER_DEFINE@", power_define)
    )


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix=f"samovar-runtime-event-clamp-{label}-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "runtime_event_task_clamp_test.cpp"
        binary = temp / "runtime_event_task_clamp_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        # Основная конфигурация: SAMOVAR_USE_POWER определён (значение по умолчанию
        # в Samovar_ini.h) — проверяем поведенческий кламп для обеих короткоживущих задач.
        harness_with_power = build_harness(define_power=True)
        # Сборка без регулятора напряжения: PowerStatusTask не существует — проверяем,
        # что #ifdef SAMOVAR_USE_POWER в самой функции не ломает компиляцию и клэмп
        # по-прежнему работает для SysTicker.
        harness_without_power = build_harness(define_power=False)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    exit_code = compile_and_run(harness_with_power, "with-power")
    if exit_code != 0:
        return exit_code
    return compile_and_run(harness_without_power, "without-power")


if __name__ == "__main__":
    raise SystemExit(main())
