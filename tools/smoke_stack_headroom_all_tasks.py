#!/usr/bin/env python3
"""Поведенческая проверка П24: tick_check_stack_headroom() следит не только за loop().

Раньше uxTaskGetStackHighWaterMark(NULL) проверял только "текущую задачу" (loop()).
PowerStatusTask (самый маленький из рабочих стеков, и именно он на путях отказа
регулятора строит длинные String), SysTicker, GetClockTicker и
EmergencyButtonTask не проверялись вовсе. Теперь функция дополнительно обходит
таблицу stackWatchTable, храня УКАЗАТЕЛЬ на хэндл (задача может быть ещё не создана -
такую запись нужно молча пропустить, как GetBMPTask, который нигде не создаётся).

Тест берёт РЕАЛЬНЫЕ struct StackWatchEntry / stackWatchTable[] / тело
tick_check_stack_headroom() (текстовым срезом + extract_function_body - без
переписывания логики) и подставляет их в host-харнесс с подменённым
uxTaskGetStackHighWaterMark(handle), который возвращает разное значение остатка стека
для разных хэндлов, чтобы наблюдать реальное поведение по каждой задаче.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER

using TaskHandle_t = void*;

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  size_t length() const { return value_.size(); }
  const char* c_str() const { return value_.c_str(); }

  String& operator+=(const String& other) {
    value_ += other.value_;
    return *this;
  }

  friend String operator+(String left, const String& right) {
    left += right;
    return left;
  }

 private:
  std::string value_;
};

enum MESSAGE_TYPE : uint8_t { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };

// Реальные хэндлы задач (Samovar.h / Samovar.ino), с фиктивными адресами - чтобы
// мок uxTaskGetStackHighWaterMark мог различать их между собой.
TaskHandle_t SysTickerTask1 = reinterpret_cast<TaskHandle_t>(0x1001);
TaskHandle_t GetClockTask1 = reinterpret_cast<TaskHandle_t>(0x1002);
// GetBMPTask нигде не создаётся в прошивке - хэндл всегда остаётся NULL.
TaskHandle_t GetBMPTask = nullptr;
#ifdef SAMOVAR_USE_POWER
TaskHandle_t PowerStatusTask = reinterpret_cast<TaskHandle_t>(0x1003);
#endif

@TABLE_DECL@

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

// --- Подменяемый остаток стека по хэндлу. По умолчанию - заведомо безопасное
// значение (100000), чтобы неучтённые/нулевые хэндлы никогда не вызывали ложных
// срабатываний сами по себе; totalQueryCalls считает КАЖДЫЙ вызов (включая
// NULL - для текущей задачи), что позволяет доказать, что nullptr-хэндлы из
// таблицы (GetBMPTask) реально пропускаются, а не тихо проходят проверку с
// безопасным значением по умолчанию.
static uint32_t sysTickerHeadroom = 100000;
static uint32_t getClockHeadroom = 100000;
#ifdef SAMOVAR_USE_POWER
static uint32_t powerStatusHeadroom = 100000;
#endif
static int totalQueryCalls = 0;

static uint32_t uxTaskGetStackHighWaterMark(TaskHandle_t handle) {
  totalQueryCalls++;
  if (handle == SysTickerTask1) return sysTickerHeadroom;
  if (handle == GetClockTask1) return getClockHeadroom;
#ifdef SAMOVAR_USE_POWER
  if (handle == PowerStatusTask) return powerStatusHeadroom;
#endif
  return 100000;
}

static void tick_check_stack_headroom() {
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  sysTickerHeadroom = 100000;
  getClockHeadroom = 100000;
#ifdef SAMOVAR_USE_POWER
  powerStatusHeadroom = 100000;
#endif
  emergencyStopCalls = 0;
  lastReason.clear();
  sendMsgAlarmCalls = 0;
  vTaskDelayCalls = 0;
  espRestartCalls = 0;
  totalQueryCalls = 0;
}

// Все задачи в норме -> тишина. Заодно доказывает, что GetBMPTask (хэндл всегда
// NULL - задача нигде не создаётся) реально ПРОПУЩЕН, а не опрошен со
// значением по умолчанию: ровно 4 запроса (NULL текущей задачи + SysTicker +
// GetClockTicker + PowerStatusTask), не 5.
static void test_all_healthy_is_silent() {
  reset_fixture();
  tick_check_stack_headroom();
  check(emergencyStopCalls == 0, "здоровые задачи ошибочно вызвали request_emergency_stop");
  check(espRestartCalls == 0, "здоровые задачи ошибочно вызвали ESP.restart");
  check(totalQueryCalls == 4,
        "REGRESS: число опросов uxTaskGetStackHighWaterMark изменилось - "
        "похоже, nullptr-хэндл (GetBMPTask) больше не пропускается");
}

// Мало место только у SysTicker -> отсечка сработала один раз, причина называет
// именно эту задачу.
static void test_low_systicker_names_systicker() {
  reset_fixture();
  sysTickerHeadroom = 500;
  tick_check_stack_headroom();
  check(emergencyStopCalls == 1, "низкий стек SysTicker не вызвал request_emergency_stop ровно один раз");
  check(lastReason.find("SysTicker") != std::string::npos,
        "причина отсечки не называет SysTicker");
  check(lastReason.find("PowerStatusTask") == std::string::npos,
        "причина отсечки SysTicker ошибочно упоминает PowerStatusTask");
  check(sendMsgAlarmCalls == 1, "SendMsg(..., ALARM_MSG) не вызван при низком стеке SysTicker");
  check(vTaskDelayCalls == 1, "vTaskDelay не вызван при низком стеке SysTicker");
  check(espRestartCalls == 1, "ESP.restart не вызван при низком стеке SysTicker");
}

// Мало место только у PowerStatusTask (самый маленький рабочий стек,
// строит длинные String на путях отказа регулятора) -> отсечка называет именно её.
static void test_low_power_status_names_power_status() {
  reset_fixture();
#ifdef SAMOVAR_USE_POWER
  powerStatusHeadroom = 500;
  tick_check_stack_headroom();
  check(emergencyStopCalls == 1,
        "низкий стек PowerStatusTask не вызвал request_emergency_stop ровно один раз");
  check(lastReason.find("PowerStatusTask") != std::string::npos,
        "причина отсечки не называет PowerStatusTask");
  check(lastReason.find("SysTicker") == std::string::npos,
        "причина отсечки PowerStatusTask ошибочно упоминает SysTicker");
#endif
}

int main() {
  test_all_healthy_is_silent();
  test_low_systicker_names_systicker();
  test_low_power_status_names_power_status();

  if (failures != 0) return 1;
  std::cout << "tick_check_stack_headroom multi-task coverage checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8", errors="ignore")
    table_start = source.index("struct StackWatchEntry {")
    body_signature = "static void tick_check_stack_headroom()"
    table_end = source.index(body_signature)
    table_decl = source[table_start:table_end].rstrip() + "\n"
    body = extract_function_body(source, body_signature)
    return HARNESS_TEMPLATE.replace("@TABLE_DECL@", table_decl).replace("@BODY@", body)


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-stack-headroom-all-tasks-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "stack_headroom_all_tasks_test.cpp"
        binary = temp / "stack_headroom_all_tasks_test"
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
