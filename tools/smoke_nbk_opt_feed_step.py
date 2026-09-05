#!/usr/bin/env python3
"""Поведенческая проверка [T5] (план nbk-2026-09-03-B): шаг подачи в ядре
Оптимизации при неудачной итерации (Тб ещё не достигла Тн). До правки
кандидат подачи домножался на 0.9 (-10%), что на реальных подачах 15-20 л/ч
давало шаг 1.5-2 л/ч - в 3-4 раза больше dП. Теперь кандидат снижается РОВНО
на dП с нижним клампом на dП (не ниже одного шага), симметрично шагу
повышения (candidateP += dП в соседней ветке).

Харнесс вытаскивает РЕАЛЬНОЕ тело "if (nbk_opt_in_progress) {...}" (та же
обёртка core_tick(), что и в smoke_nbk_opt_found.py/smoke_nbk_tn_autocal.py) -
блок T2 (автотарировка Тн) держится через флаг nbk_tn_autocal_done=true
заглушенным (не предмет этого теста), блок T1 (давление) - через
nbk_opt_found=false остаётся неактивным по построению сценариев (Тб<Тн).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

CORE_ANCHOR = "if (nbk_opt_in_progress) {"

# [Мутации] Полная строка формулы - якорь для обеих мутаций T5.
FORMULA_ANCHOR = (
    "      candidateP = max(candidateP - nbk_dP, nbk_dP); // шаг, а не -10%: "
    "при 15-20 л/ч 10% = 1.5-2 л/ч, в 3-4 раза больше dП\n"
)

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER
#define PWR_MSG "Мощность"
#define PWR_SIGN "Вт"
#define NBK_PUMP_LIMIT 30
#define portTICK_PERIOD_MS 1
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum NbkActuatorDeadlineTarget { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };

template <typename T> T max(T a, T b) { return a > b ? a : b; }

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(int value) : value_(std::to_string(value)) {}
  String(float value, int) : value_(std::to_string(value)) {}
  String operator+(const char* rhs) const { return String((value_ + (rhs ? rhs : "")).c_str()); }
  String operator+(const String& rhs) const { return String((value_ + rhs.value_).c_str()); }
  String& operator+=(const char* rhs) { value_ += (rhs ? rhs : ""); return *this; }
  String& operator+=(const String& rhs) { value_ += rhs.value_; return *this; }
  void reserve(size_t) {}
  bool contains(const char* needle) const { return value_.find(needle) != std::string::npos; }
 private:
  explicit String(const std::string& value) : value_(value) {}
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(lhs) + rhs;
}

struct SensorProbe { float avgTemp; };
static SensorProbe TankSensor{0};
static SensorProbe SteamSensor{0};

static bool overflowFlag = false;
bool overflow() { return overflowFlag; }
static int handleOverflowCalls = 0;
void handle_overflow(const String&, bool = true, uint32_t = 0, bool = false) { handleOverflowCalls++; }

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
static uint32_t nbk_opt_next_time = 0;
bool safety_deadline_expired(uint32_t now, uint32_t deadline) {
  return (int32_t)(now - deadline) >= 0;
}

static uint16_t nbk_opt_iter = 0;
static uint8_t ProgramNum = 5;
static bool nbk_opt_found = false;
static float nbk_Tb = 0, nbk_Tn = 95.0f, nbk_dD = 0.0f;
static float nbk_Tp = 0, nbk_Tp_lim = 100.0f;
static float nbk_M = 0, nbk_P = 0;
static float nbk_dP = 1.0f, nbk_dM = 50.0f, nbk_M_max = 3000.0f;
static float nbk_Mo = -1, nbk_Po = -1;
static uint16_t nbk_column_inertia = 180;
float fromPower(float value) { return value; }

// [Тарировка Тн] не предмет этого теста - флаг всегда взведён, блок T2
// молчит, но обязан компилироваться (входит в CORE_ANCHOR).
#define NBK_TN_AUTOCAL_MAX 102.0f
static bool nbk_tn_autocal_done = true;
struct NbkSessionConfig { float tankTemp; };
static NbkSessionConfig nbkSessionConfig{200.0f};

// [T1-2026-09-03] ветка предзахлёба по давлению (не предмет этого теста, но
// блок 1.10 включён в CORE_ANCHOR) - управляемый флаг по умолчанию false,
// поведение теста не меняется.
#define NBK_HIGH_TB_HOLD_TICKS 3
static uint8_t nbk_high_pressure_ticks = 0;
static bool nbk_opt_entry_by_pressure = false; // [T1] причина автовхода по давлению - не предмет этого теста
static int dirtyStreamCalls = 0;
void nbk_set_stream_dirty() { dirtyStreamCalls++; }
static bool pressureAboveCeilingFlag = false;
bool nbk_pressure_above_ceiling() { return pressureAboveCeilingFlag; }

static int runNbkProgramCalls = 0;
static uint8_t lastRunNum = 255;
static bool lastWorkConfirmed = true;
static bool lastOptimumEntry = true;
void run_nbk_program(uint8_t num, bool workConfirmed = false, bool optimumEntry = false) {
  runNbkProgramCalls++;
  lastRunNum = num;
  lastWorkConfirmed = workConfirmed;
  lastOptimumEntry = optimumEntry;
}

static int sendMsgCalls = 0;
static String lastMsg;
void SendMsg(const String& msg, int) {
  sendMsgCalls++;
  lastMsg = msg;
}

static bool scheduleShouldSucceed = true;
static int scheduleCalls = 0;
static float scheduleLastM = -1, scheduleLastP = -1;
static uint16_t scheduleLastIter = 65535;
bool nbk_schedule_actuator_command(float candidateM, float candidateP, NbkActuatorDeadlineTarget, uint32_t, uint16_t nextIteration) {
  scheduleCalls++;
  scheduleLastM = candidateM;
  scheduleLastP = candidateP;
  scheduleLastIter = nextIteration;
  return scheduleShouldSucceed;
}

static int enterSafeWaitCalls = 0;
void nbk_enter_safe_wait(const String&) { enterSafeWaitCalls++; }

@BODY@

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static bool close(float a, float b) { return (a > b ? a - b : b - a) < 0.001f; }

// Тб=80 (<Тн=95) и Тп=50 (<Тп_lim=100) -> устойчиво "не найдено", ядро всегда
// идёт в ветку снижения подачи / увеличения мощности (формула T5).
static void reset_fixture() {
  nbk_opt_iter = 10;
  ProgramNum = 5;
  overflowFlag = false;
  handleOverflowCalls = 0;
  fakeMillis = 1000;
  nbk_opt_next_time = 500; // дедлайн уже прошёл - ядро выполняется
  nbk_Tb = 0; nbk_Tp = 0;
  TankSensor.avgTemp = 80.0f;
  SteamSensor.avgTemp = 50.0f;
  nbk_M = 1000.0f; nbk_dM = 50.0f; nbk_M_max = 3000.0f;
  nbk_P = 0;
  nbk_Mo = -1; nbk_Po = -1;
  nbk_column_inertia = 180;
  nbk_opt_found = false;
  runNbkProgramCalls = 0;
  lastRunNum = 255;
  lastWorkConfirmed = true;
  lastOptimumEntry = true;
  sendMsgCalls = 0;
  lastMsg = String("");
  scheduleShouldSucceed = true;
  scheduleCalls = 0;
  scheduleLastM = -1; scheduleLastP = -1; scheduleLastIter = 65535;
  enterSafeWaitCalls = 0;
  nbk_high_pressure_ticks = 0;
  pressureAboveCeilingFlag = false;
  dirtyStreamCalls = 0;
  nbk_tn_autocal_done = true; // [Тарировка Тн] не предмет этого теста
}

// 1) П=15, dП=0.5 -> кандидат обязан снизиться РОВНО на dП (14.5), а не на 10%.
static void test_step_within_range() {
  reset_fixture();
  nbk_P = 15.0f;
  nbk_dP = 0.5f;
  core_tick();
  check(close(scheduleLastP, 14.5f), "1: П обязана снизиться ровно на dП (15-0.5=14.5), а не домножиться на 0.9");
  check(dirtyStreamCalls == 0, "1: без захлёба сервопривод потока не должен двигаться");
}

// 2) П=0.3, dП=0.5 -> без клампа ушло бы в минус (-0.2); обязан сработать
// нижний пол на dП (0.5), симметрично клампу нуля в ветке "Работа".
static void test_step_floor_clamp() {
  reset_fixture();
  nbk_P = 0.3f;
  nbk_dP = 0.5f;
  core_tick();
  check(close(scheduleLastP, 0.5f), "2: при П меньше dП кандидат обязан зажаться на dП (полу), а не уйти в минус");
}

// 3) Мощность по-прежнему растёт на dM в этой же ветке - формула T5 меняет
// только подачу, мощность не затронута.
static void test_power_still_rises_by_dM() {
  reset_fixture();
  nbk_P = 15.0f;
  nbk_dP = 0.5f;
  core_tick();
  check(close(scheduleLastM, 1050.0f), "3: М обязана вырасти на dM (1000+50=1050) независимо от формулы подачи");
}

int main() {
  test_step_within_range();
  test_step_floor_clamp();
  test_power_still_rises_by_dM();
  if (failures != 0) return 1;
  std::cout << "nbk opt feed step behaviour checks passed\n";
  return 0;
}
'''


def build_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, CORE_ANCHOR)
    wrapped = f"static void core_tick() {{{body}}}"
    return HARNESS.replace("@BODY@", wrapped)


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-opt-feed-step-") as temp_dir:
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
            if emit:
                sys.stderr.write("compile failed:\n")
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def mutate_revert_to_percent(source: str) -> str:
    if FORMULA_ANCHOR not in source:
        raise ValueError("mutation anchor missing: T5 feed step formula")
    mutated = FORMULA_ANCHOR.replace(
        "candidateP = max(candidateP - nbk_dP, nbk_dP);", "candidateP *= 0.9f;", 1
    )
    return source.replace(FORMULA_ANCHOR, mutated, 1)


def mutate_drop_floor_clamp(source: str) -> str:
    if FORMULA_ANCHOR not in source:
        raise ValueError("mutation anchor missing: T5 feed step formula")
    mutated = FORMULA_ANCHOR.replace(
        "candidateP = max(candidateP - nbk_dP, nbk_dP);", "candidateP = candidateP - nbk_dP;", 1
    )
    return source.replace(FORMULA_ANCHOR, mutated, 1)


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness, True) != 0:
        return 1

    mutations = [
        ("revert to *= 0.9f", mutate_revert_to_percent),
        ("drop floor clamp", mutate_drop_floor_clamp),
    ]
    for name, mutate_fn in mutations:
        try:
            mutated = mutate_fn(nbk_source)
        except ValueError as error:
            print(f"FAIL: {error}", file=sys.stderr)
            return 1
        if mutated == nbk_source:
            print(f"FAIL: mutation had no effect: {name}", file=sys.stderr)
            return 1
        mutated_harness = build_harness(mutated)
        if compile_and_run(mutated_harness, False) == 0:
            print(f"FAIL: mutation survived (expected failure): {name}", file=sys.stderr)
            return 1

    print("nbk opt feed step checks (behaviour + mutations) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
