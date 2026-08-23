#!/usr/bin/env python3
"""Поведенческая проверка П4: наблюдатель живучести задачи SysTicker.

mode_dispatch_alarm() (проверки перегрева/воды/датчиков/давления) вызывается
единственный раз во всей прошивке - внутри задачи SysTicker. Если эта задача
зависнет (например, на xSemaphoreTake(xI2CSemaphore, 1000) при полуживой шине
I2C или внутри DS_getvalue()), проверки молча перестанут выполняться при
включённом нагреве, а loop() и веб на другом ядре продолжат отвечать - снаружи
всё выглядит живым. esp_task_wdt не годится (см. комментарий в Samovar.ino), поэтому
используется счётчик пульса sysTickerHeartbeat + наблюдатель tick_check_systicker_liveness().

Тест берёт РЕАЛЬНОЕ тело tick_check_systicker_liveness() (через extract_function_body -
без переписывания логики) и подставляет его в минимальный host-харнесс, подменяя
millis()/sysTickerHeartbeat/request_emergency_stop()/SendMsg()/vTaskDelay()/ESP.restart().
Единый непрерывный таймлайн вызовов (как это реально происходит из loop()):
пульс растёт -> пульс замирает, но порог не достигнут -> порог превышен.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  size_t length() const { return value_.size(); }
  const char* c_str() const { return value_.c_str(); }

 private:
  std::string value_;
};

enum MESSAGE_TYPE : uint8_t { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };

static unsigned long mockMillis = 0;
static unsigned long millis() { return mockMillis; }

// Пульс задачи SysTicker - в реальном коде инкрементируется первой строкой
// внешнего while(true) в triggerSysTicker().
static volatile uint32_t sysTickerHeartbeat = 0;

static int emergencyStopCalls = 0;
static std::string lastReason;
static void request_emergency_stop(const String& reason) {
  emergencyStopCalls++;
  lastReason = reason.c_str();
}

static int sendMsgAlarmCalls = 0;
static void SendMsg(const String& text, uint8_t level) {
  (void)text;
  if (level == ALARM_MSG) sendMsgAlarmCalls++;
}

static int vTaskDelayCalls = 0;
static void vTaskDelay(unsigned long ms) {
  (void)ms;
  vTaskDelayCalls++;
}

static int espRestartCalls = 0;
struct ESPClassStub {
  void restart() { espRestartCalls++; }
};
static ESPClassStub ESP;

static void tick_check_systicker_liveness() {
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- Первый вызов: пульс=0, время=0. Просто фиксирует стартовую точку отсчёта. ---
  tick_check_systicker_liveness();
  check(emergencyStopCalls == 0, "ложное срабатывание на самом первом вызове (t=0)");

  // --- (1) Пульс растёт вместе со временем -> отсечка не вызывается ни разу. ---
  for (int i = 0; i < 5; i++) {
    sysTickerHeartbeat++;
    mockMillis += 1000;
    tick_check_systicker_liveness();
  }
  check(emergencyStopCalls == 0, "растущий пульс ошибочно вызвал request_emergency_stop");
  // Последнее изменение пульса зафиксировано на mockMillis == 5000.

  // --- (3) Пульс замер, но порог (10с) с момента последнего изменения не достигнут. ---
  mockMillis += 9000;  // итого 9000мс с последнего изменения пульса (< 10000)
  tick_check_systicker_liveness();
  check(emergencyStopCalls == 0,
        "отсечка сработала до истечения порога живучести SysTicker (9с < 10с)");
  check(vTaskDelayCalls == 0, "vTaskDelay вызван до истечения порога");
  check(espRestartCalls == 0, "ESP.restart вызван до истечения порога");

  // --- (2) Пульс всё ещё замер, порог превышен -> ровно одно срабатывание. ---
  mockMillis += 1002;  // итого 10002мс с последнего изменения пульса (> 10000)
  tick_check_systicker_liveness();
  check(emergencyStopCalls == 1,
        "request_emergency_stop вызван не ровно один раз при превышении порога живучести");
  check(lastReason == "Аварийное отключение: задача надзора SysTicker зависла",
        "неверная причина аварийной отсечки при зависании SysTicker");
  check(sendMsgAlarmCalls == 1, "SendMsg(..., ALARM_MSG) не вызван при зависании SysTicker");
  check(vTaskDelayCalls == 1, "vTaskDelay не вызван при зависании SysTicker");
  check(espRestartCalls == 1, "ESP.restart не вызван при зависании SysTicker");

  if (failures != 0) return 1;
  std::cout << "SysTicker liveness watchdog behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = strip_cpp_comments((ROOT / "Samovar.ino").read_text(encoding="utf-8", errors="ignore"))
    body = extract_function_body(source, "static void tick_check_systicker_liveness() {")
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-systicker-liveness-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "systicker_liveness_test.cpp"
        binary = temp / "systicker_liveness_test"
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
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
