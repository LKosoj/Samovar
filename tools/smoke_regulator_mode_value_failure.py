#!/usr/bin/env python3
"""Поведенческая проверка [T14 п.29]: занятый лок set_current_power_mode_value()
не должен обрывать сессию пользователя.

История вопроса: раньше apply_regulator_mode_blocking() (KVIC/RMVK/SEM) при
провале set_current_power_mode_value() (занятый на 500 мс runtime_state_lock())
возвращала false, хотя аппаратная команда уже успешно ушла регулятору. false
эскалировался цепочкой process_pending_power_request() ->
safety_regulator_failure_action() -> fail_close_regulator_locked() - разовая
занятость лока другой задачей сбрасывала активную сессию дистилляции/БК/НБК
в IDLE без реальной аварии.

Решение владельца (п.29): set_current_power_mode_value() возвращает признак
успеха, ВЫЗЫВАЮЩИЙ ПОВТОРЯЕТ. Провал записи больше не считается отказом
регулятора - вместо этого взводится отложенная заявка на повтор
(arm_pending_power_mode_retry() в runtime_helpers.h), которую дочинивает
process_pending_power_request() (power_regulator.h) на следующем проходе.

Часть 1: реальное тело set_current_power_mode_value() (runtime_helpers.h) -
поведение самой функции не менялось: занятый лок -> false, current_power_mode
не тронут; свободный лок -> true, current_power_mode записан.

Часть 2: реальное тело apply_regulator_mode_blocking() (все три backend'а) -
провал set_current_power_mode_value() обязан (а) вернуть true (не отказ
регулятора), (б) выполнить обычный SLEEP-сброс - железо команду уже приняло,
(в) взвести заявку на повтор с ПРАВИЛЬНЫМ значением режима.

Часть 3: реальное тело добавленного в process_pending_power_request() блока
повтора - заявка не взведена -> ничего не делает; заявка взведена и повтор
удался -> кэш дописан, заявка снята; заявка взведена и повтор снова не удался ->
заявка остаётся взведённой (не теряется) для следующего прохода.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SET_VALUE_SIGNATURE = "inline bool set_current_power_mode_value(const String& mode) {"
APPLY_SIGNATURE = "inline bool apply_regulator_mode_blocking(SafetyRegulatorMode mode, uint64_t powerGeneration) {"
RETRY_ANCHOR = "if (pending_power_mode_retry_armed()) {"

SET_VALUE_HARNESS = r'''
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  bool operator==(const String& other) const { return value_ == other.value_; }
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};

typedef int TickType_t;
#define pdMS_TO_TICKS(x) (x)

static bool test_lockResult = true;
static int lockCalls = 0;
bool runtime_state_lock(TickType_t) { lockCalls++; return test_lockResult; }
static int unlockCalls = 0;
void runtime_state_unlock(bool) { unlockCalls++; }

static String current_power_mode;

@BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- Занятый лок: false, режим НЕ записан, unlock не вызывается (мы его
  // не брали). ---
  test_lockResult = false;
  current_power_mode = String("SLEEP");
  lockCalls = 0; unlockCalls = 0;
  bool result = set_current_power_mode_value(String("SPEED"));
  check(!result, "РЕГРЕСС [T14 п.29]: занятый лок обязан вернуть false");
  check(current_power_mode == String("SLEEP"),
        "занятый лок не должен менять current_power_mode");
  check(unlockCalls == 0, "занятый лок не должен вызывать unlock (лок не был взят)");

  // --- Свободный лок: true, режим записан, unlock вызван. ---
  test_lockResult = true;
  current_power_mode = String("SLEEP");
  lockCalls = 0; unlockCalls = 0;
  result = set_current_power_mode_value(String("SPEED"));
  check(result, "свободный лок обязан вернуть true");
  check(current_power_mode == String("SPEED"), "свободный лок обязан записать новый режим");
  check(unlockCalls == 1, "свободный лок обязан вызвать unlock ровно один раз");

  if (failures != 0) return 1;
  std::cout << "set_current_power_mode_value success-flag checks passed\n";
  return 0;
}
'''

APPLY_HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  size_t length() const { return value_.size(); }
  const char* c_str() const { return value_.c_str(); }
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

enum SafetyRegulatorMode { SAFETY_REGULATOR_MODE_SLEEP, SAFETY_REGULATOR_MODE_SPEED };
typedef int TickType_t;
#define pdMS_TO_TICKS(x) (x)
#define portTICK_PERIOD_MS 1
#define UART_NUM_2 2
static void vTaskDelay(int) {}

static String test_modeText = "SPEED";
String regulator_mode_text(SafetyRegulatorMode) { return test_modeText; }

static bool test_uartResult = true;
static int uartCalls = 0;
bool heater_uart_enqueue(int, const char*, size_t, uint64_t, bool) {
  uartCalls++;
  return test_uartResult;
}

@EXTRA_STUBS@

static bool test_setValueResult = true;
static int setValueCalls = 0;
static String lastModeArg;
bool set_current_power_mode_value(const String& mode) {
  setValueCalls++;
  lastModeArg = mode;
  return test_setValueResult;
}

static int armCalls = 0;
static SafetyRegulatorMode lastArmedMode = SAFETY_REGULATOR_MODE_SLEEP;
void arm_pending_power_mode_retry(SafetyRegulatorMode mode) {
  armCalls++;
  lastArmedMode = mode;
}

float target_power_volt = -1.0f;
float current_power_volt = -1.0f;
float current_power_p = -1.0f;

@BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset(float sentinel) {
  test_modeText = "SPEED";
  test_uartResult = true;
  uartCalls = 0;
  test_setValueResult = true;
  setValueCalls = 0;
  armCalls = 0;
  target_power_volt = sentinel;
  current_power_volt = sentinel;
  current_power_p = sentinel;
}

int main() {
  // --- set_current_power_mode_value() провалилась (занятый лок): команда
  // регулятору уже успешно ушла (uart) - это НЕ отказ регулятора. apply_regulator_mode_blocking()
  // обязана вернуть true как при успехе, выполнить обычный SLEEP-сброс и
  // взвести заявку на отложенный повтор записи кэша с правильным режимом. ---
  reset(-1.0f);
  test_setValueResult = false;
  bool result = apply_regulator_mode_blocking(SAFETY_REGULATOR_MODE_SLEEP, 42);
  check(setValueCalls == 1, "set_current_power_mode_value обязана быть вызвана ровно один раз");
  check(result,
        "РЕГРЕСС [T14 п.29]: занятый лок кэша - не отказ регулятора, apply_regulator_mode_blocking обязана вернуть true");
  check(target_power_volt == 0.0f,
        "РЕГРЕСС: SLEEP-сброс обязан выполняться даже при занятом локе кэша - железо команду уже приняло");
  check(armCalls == 1,
        "РЕГРЕСС [T14 п.29]: провал записи кэша обязан взвести отложенный повтор, а не потерять значение молча");
  check(lastArmedMode == SAFETY_REGULATOR_MODE_SLEEP,
        "заявка на повтор обязана нести именно тот режим, что был применён к железу");

  // --- Успех: обычное поведение, SLEEP-сброс выполняется, true, повтор НЕ взводится. ---
  reset(-1.0f);
  test_setValueResult = true;
  result = apply_regulator_mode_blocking(SAFETY_REGULATOR_MODE_SLEEP, 42);
  check(result, "успешная запись режима обязана вернуть true");
  check(target_power_volt == 0.0f, "успешный SLEEP обязан обнулить target_power_volt");
  check(armCalls == 0, "успешная запись кэша не должна взводить отложенный повтор");

  if (failures != 0) return 1;
  std::cout << "apply_regulator_mode_blocking mode-value retry checks passed\n";
  return 0;
}
'''

RETRY_HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  bool operator==(const String& other) const { return value_ == other.value_; }
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};

enum SafetyRegulatorMode : uint8_t {
  SAFETY_REGULATOR_MODE_SLEEP = 0,
  SAFETY_REGULATOR_MODE_SPEED,
  SAFETY_REGULATOR_MODE_WORK,
};

static bool test_armed = false;
bool pending_power_mode_retry_armed() { return test_armed; }

static SafetyRegulatorMode test_pendingValue = SAFETY_REGULATOR_MODE_SLEEP;
SafetyRegulatorMode pending_power_mode_retry_value() { return test_pendingValue; }

static int clearCalls = 0;
void clear_pending_power_mode_retry() { clearCalls++; test_armed = false; }

static String test_modeText = "WORK";
static int modeTextCalls = 0;
static SafetyRegulatorMode lastModeTextArg = SAFETY_REGULATOR_MODE_SLEEP;
String regulator_mode_text(SafetyRegulatorMode mode) {
  modeTextCalls++;
  lastModeTextArg = mode;
  return test_modeText;
}

static bool test_setValueResult = true;
static int setValueCalls = 0;
static String lastSetValueArg;
bool set_current_power_mode_value(const String& mode) {
  setValueCalls++;
  lastSetValueArg = mode;
  return test_setValueResult;
}

void retry_worker_tick() {
  if (pending_power_mode_retry_armed()) {
@BLOCK@
  }
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset() {
  clearCalls = 0;
  modeTextCalls = 0;
  setValueCalls = 0;
  test_setValueResult = true;
  lastSetValueArg = String();
}

int main() {
  // --- Заявки нет: воркер не трогает set_current_power_mode_value. ---
  reset();
  test_armed = false;
  retry_worker_tick();
  check(setValueCalls == 0, "без заявки повтор не должен вызывать set_current_power_mode_value");
  check(clearCalls == 0, "без заявки нечего снимать");

  // --- Заявка взведена, повтор удался: кэш дописан, заявка снята. ---
  reset();
  test_armed = true;
  test_pendingValue = SAFETY_REGULATOR_MODE_WORK;
  test_setValueResult = true;
  retry_worker_tick();
  check(setValueCalls == 1, "взведённая заявка обязана вызвать set_current_power_mode_value ровно один раз");
  check(lastModeTextArg == SAFETY_REGULATOR_MODE_WORK,
        "повтор обязан конвертировать именно взведённое значение режима");
  check(clearCalls == 1,
        "РЕГРЕСС [T14 п.29]: удачный повтор обязан снять заявку (clear_pending_power_mode_retry)");
  check(!test_armed, "после удачного повтора заявка не должна остаться взведённой");

  // --- Заявка взведена, повтор снова не удался: значение не теряется -
  // заявка обязана остаться взведённой для следующего прохода воркера. ---
  reset();
  test_armed = true;
  test_pendingValue = SAFETY_REGULATOR_MODE_SLEEP;
  test_setValueResult = false;
  retry_worker_tick();
  check(setValueCalls == 1, "неудачный повтор всё равно обязан попытаться записать кэш");
  check(clearCalls == 0,
        "РЕГРЕСС [T14 п.29]: неудачный повтор не должен снимать заявку - значение потеряется молча");
  check(test_armed, "заявка обязана остаться взведённой после повторного провала");

  if (failures != 0) return 1;
  std::cout << "process_pending_power_request retry-block checks passed\n";
  return 0;
}
'''


def build_set_value_harness(runtime_source: str) -> str:
    body = extract_function_body(runtime_source, SET_VALUE_SIGNATURE)
    func = "bool set_current_power_mode_value(const String& mode) {" + body + "}"
    return SET_VALUE_HARNESS.replace("@BODY@", func)


EXTRA_STUBS = {
    "power_regulator_kvic.h": "",
    "power_regulator_rmvk.h": r'''
enum { RMVK_ERROR = -1, RMVK_OK = 0 };
#define RMVK_READ_DELAY 200
#define MAX_VOLTAGE (230)
#define POWER_DEBUG_LOG(...) do {} while (0)
int RMVK_set_on(int, uint64_t) { return RMVK_OK; }
int RMVK_set_out_voltge(float, uint64_t) { return RMVK_OK; }
''',
    "power_regulator_sem.h": r'''
#define RMVK_READ_DELAY 200
#define RMVK_DEFAULT_READ_TIMEOUT 300
#define portTICK_RATE_MS 1
#define POWER_DEBUG_LOG(...) do {} while (0)
static const bool pdTRUE = true;
static int xSemaphoreAVR = 1;
bool xSemaphoreTake(int, TickType_t) { return true; }
void xSemaphoreGive(int) {}
static bool test_semQueued = true;
bool sem_avr_write_samovar_command(const char*, uint64_t, bool) { return test_semQueued; }
''',
}


def build_apply_harness(source: str, filename: str) -> str:
    body = extract_function_body(source, APPLY_SIGNATURE)
    func = "bool apply_regulator_mode_blocking(SafetyRegulatorMode mode, uint64_t powerGeneration) {" + body + "}"
    harness = APPLY_HARNESS.replace("@EXTRA_STUBS@", EXTRA_STUBS.get(filename, ""))
    return harness.replace("@BODY@", func)


def build_retry_harness(power_source: str) -> str:
    block, _ = extract_braced_block_after(power_source, RETRY_ANCHOR)
    return RETRY_HARNESS.replace("@BLOCK@", block)


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-regulator-mode-value-failure-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "test.cpp"
        binary = temp / "test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(f"[{label}] ")
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    runtime_source = (ROOT / "runtime_helpers.h").read_text(encoding="utf-8")
    power_source = (ROOT / "power_regulator.h").read_text(encoding="utf-8")
    try:
        set_value_harness = build_set_value_harness(runtime_source)
        retry_harness = build_retry_harness(power_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc = compile_and_run(set_value_harness, "set_current_power_mode_value")
    if rc != 0:
        return rc

    rc = compile_and_run(retry_harness, "process_pending_power_request retry block")
    if rc != 0:
        return rc

    backends = {
        "power_regulator_kvic.h": "KVIC",
        "power_regulator_rmvk.h": "RMVK",
        "power_regulator_sem.h": "SEM",
    }
    for filename, label in backends.items():
        source = (ROOT / filename).read_text(encoding="utf-8")
        try:
            harness = build_apply_harness(source, filename)
        except ValueError as error:
            print(f"FAIL: {filename}: {error}", file=sys.stderr)
            return 1
        rc = compile_and_run(harness, f"apply_regulator_mode_blocking {label}")
        if rc != 0:
            return rc

    # --- Проверка содержательности (1): убираем взведение заявки на повтор в
    # KVIC-backend - мутация обязана провалить харнесс на assert-е "провал
    # записи кэша обязан взвести отложенный повтор", не на предупреждении
    # компилятора.
    kvic_source = (ROOT / "power_regulator_kvic.h").read_text(encoding="utf-8")
    mutated_kvic = kvic_source.replace(
        "if (!set_current_power_mode_value(Mode)) arm_pending_power_mode_retry(mode);",
        "set_current_power_mode_value(Mode);",
        1,
    )
    if mutated_kvic == kvic_source:
        print("FAIL: mutation anchor missing (power_regulator_kvic.h retry arming)", file=sys.stderr)
        return 1
    mutation_rc = compile_and_run(
        build_apply_harness(mutated_kvic, "power_regulator_kvic.h"), "mutation KVIC (dropped retry arming)"
    )
    if mutation_rc == 0:
        print("FAIL: mutation (dropped arm_pending_power_mode_retry) survived", file=sys.stderr)
        return 1

    # --- Проверка содержательности (2): выключаем сам повтор в
    # process_pending_power_request() - мутация обязана провалить харнесс на
    # assert-е "взведённая заявка обязана вызвать set_current_power_mode_value",
    # не на предупреждении компилятора.
    mutated_power = power_source.replace(
        "  if (pending_power_mode_retry_armed()) {\n"
        "    if (set_current_power_mode_value(regulator_mode_text(pending_power_mode_retry_value()))) {\n"
        "      clear_pending_power_mode_retry();\n"
        "    }\n"
        "  }\n",
        "  if (pending_power_mode_retry_armed()) {\n"
        "  }\n",
        1,
    )
    if mutated_power == power_source:
        print("FAIL: mutation anchor missing (power_regulator.h retry worker)", file=sys.stderr)
        return 1
    mutation_rc2 = compile_and_run(build_retry_harness(mutated_power), "mutation retry worker (no-op)")
    if mutation_rc2 == 0:
        print("FAIL: mutation (retry worker no longer retries) survived", file=sys.stderr)
        return 1

    print("regulator mode-value retry mutation checks: both mutations killed as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
