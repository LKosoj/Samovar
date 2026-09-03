#!/usr/bin/env python3
"""Поведенческая проверка [T14 п.1/п.8]: нижняя граница мощности НБК.

nbk.h переводит вольты/мощность в ватты через toPower() и передаёт результат
nbk_schedule_actuator_command() -> set_current_power() (через fromPower()) -
тот же set_current_power(), что бесшумно схлопывает мощность в SLEEP ниже
POWER_WORK_MODE_THRESHOLD. Три точки снижения без floor'а:
  - handle_nbk_stage_manual(): candidateM = toPower(target_power_volt) / 2
    при захлёбе в "Ручной настройке";
  - handle_nbk_stage_work(): nbk_Mo / 2 (повторный захлёб в паузе Работы) и
    nbk_Mo -= nbk_dM/10 с полом "0" (обычное снижение в паузе);
  - handle_overflow(): nbk_Mo / 2 в ветке finish=false/pause_ms>0 - ПЕРВЫЙ
    захлёб во время обычной Работы (до входа в паузу). Тот же паттерн, что и
    в handle_nbk_stage_work(), но кламп в этом месте изначально забыли -
    nbk_Mo может прийти сюда ровно с порога (после предыдущей паузы, см.
    handle_nbk_stage_work() строка ~915) и следующий захлёб уводил бы половину
    порога в SLEEP.

Тест вытаскивает РЕАЛЬНЫЙ toPower() и все три фрагмента через
extract_function_body/extract_braced_block_after (без переписывания логики),
собирает ДВАЖДЫ (без и с -DSAMOVAR_USE_SEM_AVR), используя РЕАЛЬНЫЙ toPower()
(не тождественную заглушку) - так floor проверяется в правильном ваттном
домене для обоих типов регулятора.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

THRESHOLD_CONST = "static constexpr float POWER_WORK_MODE_THRESHOLD"
IFDEF_MARKER = "#ifdef SAMOVAR_USE_SEM_AVR"
TO_POWER_SIGNATURE = "float toPower(float value)"
MANUAL_SIGNATURE = "void handle_nbk_stage_manual() {"
PAUSE_ANCHOR = "if (nbk_work_in_pause) {"
OVERFLOW_SIGNATURE = "void handle_overflow(const String& msg, bool finish, uint32_t pause_ms, bool graceful) {"

COMMON_PRELUDE = r'''
#include <cstdint>
#include <iostream>
#include <string>

float max(float left, float right) { return left > right ? left : right; }

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String(float value, int) : value_(std::to_string(value)) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  String& operator+=(const char* text) { value_ += (text ? text : ""); return *this; }
  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  void reserve(size_t) {}
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum NbkActuatorDeadlineTarget { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };
#define portTICK_PERIOD_MS 1
#define NBK_MULT_PAUSE_OVERFLOW 2
// Не static: не в каждом харнессе, вклеенном ниже, вызывается vTaskDelay() -
// со static неиспользованный экземпляр падал бы на -Wunused-function.
void vTaskDelay(int) {}

struct NbkSessionConfig { float heaterResistance; };
// Не static: под SAMOVAR_USE_SEM_AVR toPower() эту переменную не читает -
// со static неиспользованный экземпляр падал бы на -Wunused-variable.
NbkSessionConfig nbkSessionConfig = {20.0f};

// [T1-2026-09-03] обучение потолка давления (не предмет этого теста, но
// теперь вызывается из handle_overflow/handle_nbk_stage_manual/паузы) - не
// static: не в каждом харнессе вызывается, со static падал бы на
// -Wunused-function.
void nbk_learn_pressure_ceiling() {}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
'''


def read_source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def extract_threshold_block(power_source: str) -> str:
    first = power_source.find(THRESHOLD_CONST)
    if first < 0:
        raise ValueError(f"constant not found: {THRESHOLD_CONST}")
    start = power_source.rfind(IFDEF_MARKER, 0, first)
    if start < 0:
        raise ValueError(f"enclosing {IFDEF_MARKER} not found before threshold constant")
    endif_idx = power_source.find("#endif", first)
    if endif_idx < 0:
        raise ValueError("closing #endif for threshold constant not found")
    endif_idx += len("#endif")
    block = power_source[start:endif_idx]
    return block + "\ninline float power_work_mode_threshold() { return POWER_WORK_MODE_THRESHOLD; }\n"


def build_to_power(nbk_source: str) -> str:
    body = extract_function_body(nbk_source, TO_POWER_SIGNATURE)
    return TO_POWER_SIGNATURE + " {" + body + "}"


def build_manual_harness(threshold_block: str, to_power_func: str, nbk_source: str) -> str:
    body = extract_function_body(nbk_source, MANUAL_SIGNATURE)
    func = "void handle_nbk_stage_manual() {" + body + "}"
    return COMMON_PRELUDE + "\n" + threshold_block + "\n" + to_power_func + r'''

static bool overflowFlag = false;
bool overflow() { return overflowFlag; }
const char* nbk_overflow_source() { return "ДЗ"; }
bool manual_overflow = false;
float target_power_volt = 0.0f;
uint16_t nbk_opt_iter = 0;
uint16_t nbk_column_inertia = 180;
// [Ремонт-2026-09-02 П4/П6] новые зависимости "Ручной настройки".
static float feedRateStub = 9.0f;
float nbk_actual_feed_rate() { return feedRateStub; }
uint32_t nbk_manual_overflow_until = 0;
static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t safety_deadline_after(uint32_t now, uint32_t ms) { return now + ms; }
bool safety_deadline_expired(uint32_t now, uint32_t deadline) { return now >= deadline; }

static int scheduleCalls = 0;
static float lastCandidateM = -1.0f;
static float lastCandidateP = -1.0f;
void nbk_enter_safe_wait(const String&) {}
void SendMsg(const String&, MESSAGE_TYPE) {}
bool nbk_schedule_actuator_command(float candidateM, float candidateP, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  lastCandidateM = candidateM;
  lastCandidateP = candidateP;
  return true;
}

''' + func + r'''

int main() {
  const float floorWatts = toPower(power_work_mode_threshold());

  // Далеко выше порога - floor не должен ничего менять.
  overflowFlag = true; manual_overflow = false; scheduleCalls = 0; lastCandidateM = -1.0f;
  target_power_volt = power_work_mode_threshold() * 10.0f;
  feedRateStub = 9.0f;
  handle_nbk_stage_manual();
  check(scheduleCalls == 1, "захлёб в Ручной настройке обязан отправить составную команду");
  check(lastCandidateM == toPower(target_power_volt) / 2.0f,
        "вдали от порога candidateM должен равняться toPower(target_power_volt)/2 без клэмпа");
  check(lastCandidateP == feedRateStub / 3.0f,
        "candidateP обязан браться из nbk_actual_feed_rate()/3, а не из фиксированной подачи");

  // Рядом с порогом - половина уйдёт ниже порога без клэмпа.
  overflowFlag = true; manual_overflow = false; scheduleCalls = 0; lastCandidateM = -1.0f;
  target_power_volt = power_work_mode_threshold() * 1.2f;
  handle_nbk_stage_manual();
  check(lastCandidateM >= floorWatts,
        "РЕГРЕСС: candidateM в Ручной настройке обязан клэмпиться к toPower(power_work_mode_threshold())");

  if (failures != 0) return 1;
  std::cout << "handle_nbk_stage_manual candidateM floor checks passed\n";
  return 0;
}
'''


def build_pause_harness(threshold_block: str, to_power_func: str, nbk_source: str) -> str:
    block, _ = extract_braced_block_after(nbk_source, PAUSE_ANCHOR)
    return COMMON_PRELUDE + "\n" + threshold_block + "\n" + to_power_func + r'''

bool nbk_work_in_pause = false;
uint8_t nbk_work_pause_stage = 0;
bool nbk_overflow_happened = false;
bool nbk_pause_overflow_repeat_latched = false;
uint32_t nbk_work_next_time = 0;
uint16_t nbk_column_inertia = 180;
uint16_t nbk_opt_iter = 0;
float nbk_Mo = 0.0f;
float nbk_Po = 5.0f;
float nbk_Po_ceiling = 0.0f; // [П10] заполняется в extract'нутом блоке
float nbk_P = 5.0f;
float nbk_dM = 10.0f;
float nbk_dP = 1.0f;

static bool test_overflow = false;
bool overflow() { return test_overflow; }
const char* nbk_overflow_source() { return "ДЗ"; }
float fromPower(float value) { return value; }

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t safety_deadline_after(uint32_t now, uint32_t ms) { return now + ms; }
bool safety_deadline_expired(uint32_t, uint32_t) { return true; }

static int scheduleCalls = 0;
static float lastM = -1.0f;
bool nbk_schedule_actuator_command(float m, float, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  lastM = m;
  return true;
}
void nbk_enter_safe_wait(const String&) {}
void SendMsg(const String&, MESSAGE_TYPE) {}

static void run_pause_tick() {
  if (nbk_work_in_pause) {
''' + block + r'''
  }
}

int main() {
  const float floorWatts = toPower(power_work_mode_threshold());

  // [T1] повторный захлёб в паузе: nbk_Mo/2 рядом с порогом обязан клэмпиться.
  nbk_work_in_pause = true;
  nbk_work_pause_stage = 0;
  nbk_pause_overflow_repeat_latched = false;
  test_overflow = true;
  nbk_Mo = floorWatts * 1.2f;
  scheduleCalls = 0; lastM = -1.0f;
  run_pause_tick();
  check(scheduleCalls == 1, "повторный захлёб в паузе обязан отправить составную команду");
  check(lastM >= floorWatts,
        "РЕГРЕСС: повторный захлёб в паузе обязан клэмпить nbk_Mo/2 к toPower(power_work_mode_threshold())");

  // Обычное снижение (deadline истёк, не повторный захлёб): nbk_Mo -= dM/10,
  // многократно повторённое, не должно провалиться ниже пола.
  nbk_work_in_pause = true;
  nbk_work_pause_stage = 1;
  nbk_pause_overflow_repeat_latched = false;
  test_overflow = false;
  nbk_overflow_happened = true;
  nbk_Mo = floorWatts + 0.5f;
  nbk_dM = 100.0f;  // заведомо большой шаг, чтобы без клэмпа Mo ушёл в отрицательные
  scheduleCalls = 0; lastM = -1.0f;
  run_pause_tick();
  check(nbk_Mo >= floorWatts,
        "РЕГРЕСС: снижение nbk_Mo в паузе обязано клэмпиться к toPower(power_work_mode_threshold()), а не к 0");

  if (failures != 0) return 1;
  std::cout << "handle_nbk_stage_work pause-overflow Mo floor checks passed\n";
  return 0;
}
'''


def build_overflow_harness(threshold_block: str, to_power_func: str, nbk_source: str) -> str:
    body = extract_function_body(nbk_source, OVERFLOW_SIGNATURE)
    func = OVERFLOW_SIGNATURE + body + "}"
    return COMMON_PRELUDE + "\n" + threshold_block + "\n" + to_power_func + r'''

enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
ActuatorCommandResult SetSpeed(float) { return ACTUATOR_COMMAND_APPLIED; }

enum SamovarCommands { SAMOVAR_NONE, SAMOVAR_POWER };
bool queue_samovar_command(SamovarCommands) { return true; }
void request_emergency_stop(const String&) {}

bool nbk_work_in_pause = false;
uint8_t nbk_work_pause_stage = 0;
bool nbk_overflow_happened = false;
bool nbk_pause_overflow_repeat_latched = true;
uint16_t nbk_opt_iter = 0;
float nbk_Mo = 0.0f;
// [Ремонт-2026-09-02 П4] реальная подача насоса вместо фиксированного nbk_P.
static float feedRateStub = 9.0f;
float nbk_actual_feed_rate() { return feedRateStub; }

const char* nbk_overflow_source() { return "ДЗ"; }
void SendMsg(const String&, MESSAGE_TYPE) {}
void nbk_enter_safe_wait(const String&) {}

static int scheduleCalls = 0;
static float lastM = -1.0f;
bool nbk_schedule_actuator_command(float m, float, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  lastM = m;
  return true;
}

''' + func + r'''

int main() {
  const float floorWatts = toPower(power_work_mode_threshold());

  // [T14 ЗАМЕЧАНИЕ 1] Первый захлёб в обычной Работе (finish=false, pause_ms>0):
  // nbk_Mo/2 рядом с порогом обязан клэмпиться так же, как соседние места в
  // handle_nbk_stage_work() - до фикса клампа в handle_overflow() не было.
  nbk_work_in_pause = false;
  nbk_work_pause_stage = 0;
  nbk_overflow_happened = false;
  nbk_pause_overflow_repeat_latched = true;
  nbk_Mo = floorWatts * 1.2f;
  scheduleCalls = 0; lastM = -1.0f;
  handle_overflow("Временное снижение подачи и нагрева.", false, 1000, true);
  check(scheduleCalls == 1, "первый захлёб в Работе обязан отправить составную команду снижения");
  check(lastM >= floorWatts,
        "РЕГРЕСС [T14 замечание 1]: handle_overflow обязан клэмпить nbk_Mo/2 к toPower(power_work_mode_threshold())");
  check(nbk_work_in_pause, "handle_overflow обязан перевести в паузу W (nbk_work_in_pause)");
  check(nbk_work_pause_stage == 1, "handle_overflow обязан выставить nbk_work_pause_stage = 1");
  check(!nbk_pause_overflow_repeat_latched,
        "handle_overflow обязан сбросить nbk_pause_overflow_repeat_latched для новой паузы W");

  if (failures != 0) return 1;
  std::cout << "handle_overflow (первый захлёб в Работе) Mo floor checks passed\n";
  return 0;
}
'''


def compile_and_run(harness: str, label: str, extra_define: str | None) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-power-floor-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "nbk_power_floor_test.cpp"
        binary = temp / "nbk_power_floor_test"
        source.write_text(harness, encoding="utf-8")
        cmd = ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror"]
        if extra_define:
            cmd.append(extra_define)
        cmd += [str(source), "-o", str(binary)]
        compile_result = subprocess.run(cmd, capture_output=True, text=True, check=False)
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


def run_both(build_fn, name: str) -> int:
    rc = compile_and_run(build_fn(), f"{name} KVIC/RMVK", None)
    if rc != 0:
        return rc
    return compile_and_run(build_fn(), f"{name} SEM_AVR", "-DSAMOVAR_USE_SEM_AVR")


def main() -> int:
    power_source = read_source("power_regulator.h")
    nbk_source = read_source("nbk.h")

    try:
        threshold_block = extract_threshold_block(power_source)
        to_power_func = build_to_power(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        rc = run_both(lambda: build_manual_harness(threshold_block, to_power_func, nbk_source), "handle_nbk_stage_manual")
        if rc != 0:
            return rc
        rc = run_both(lambda: build_pause_harness(threshold_block, to_power_func, nbk_source), "захлёб-пауза Работы")
        if rc != 0:
            return rc
        rc = run_both(lambda: build_overflow_harness(threshold_block, to_power_func, nbk_source), "handle_overflow первый захлёб")
        if rc != 0:
            return rc
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    # --- Проверка содержательности: убираем оба клэмпа из РЕАЛЬНОГО nbk.h -
    # мутация обязана провалить сборочные харнессы на assert-е, не на
    # предупреждении компилятора.
    mutated = nbk_source.replace(
        "max(toPower(target_power_volt) / 2, toPower(power_work_mode_threshold()))",
        "toPower(target_power_volt) / 2",
        1,
    )
    if mutated == nbk_source:
        print("FAIL: mutation anchor missing (handle_nbk_stage_manual)", file=sys.stderr)
        return 1
    mutation_rc = compile_and_run(
        build_manual_harness(threshold_block, to_power_func, mutated), "mutation handle_nbk_stage_manual", None
    )
    if mutation_rc == 0:
        print("FAIL: mutation (removed manual-stage floor) survived", file=sys.stderr)
        return 1

    mutated2 = nbk_source.replace(
        "if (nbk_Mo < toPower(power_work_mode_threshold())) nbk_Mo = toPower(power_work_mode_threshold());",
        "if (nbk_Mo < 0) nbk_Mo = 0;",
        1,
    )
    if mutated2 == nbk_source:
        print("FAIL: mutation anchor missing (pause Mo floor)", file=sys.stderr)
        return 1
    mutation_rc2 = compile_and_run(
        build_pause_harness(threshold_block, to_power_func, mutated2), "mutation pause Mo floor", None
    )
    if mutation_rc2 == 0:
        print("FAIL: mutation (reverted pause Mo floor to 0) survived", file=sys.stderr)
        return 1

    # --- [T14 замечание 1] Убираем кламп из handle_overflow() (первый захлёб
    # в обычной Работе) - мутация обязана провалить харнесс на assert-е
    # "handle_overflow обязан клэмпить nbk_Mo/2", не на предупреждении компилятора.
    # Якорь включает следующий параметр (candidateP), т.к. идентичный
    # "max(nbk_Mo / 2, toPower(power_work_mode_threshold())),"  есть и в
    # handle_nbk_stage_work() (повторный захлёб в паузе, второй параметр
    # nbk_P) - без этого replace(..., 1) молча заменил бы не то место.
    mutated3 = nbk_source.replace(
        "max(nbk_Mo / 2, toPower(power_work_mode_threshold())),\n            candidateP,",
        "nbk_Mo / 2,\n            candidateP,",
        1,
    )
    if mutated3 == nbk_source:
        print("FAIL: mutation anchor missing (handle_overflow floor)", file=sys.stderr)
        return 1
    mutation_rc3 = compile_and_run(
        build_overflow_harness(threshold_block, to_power_func, mutated3), "mutation handle_overflow floor", None
    )
    if mutation_rc3 == 0:
        print("FAIL: mutation (removed handle_overflow floor) survived", file=sys.stderr)
        return 1

    print("nbk power floor mutation checks: all three mutations killed as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
