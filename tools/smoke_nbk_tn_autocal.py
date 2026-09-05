#!/usr/bin/env python3
"""Поведенческая проверка [Тарировка Тн] (план nbk-2026-09-03-B, T2): один раз
за сессию, на первой итерации ядра Оптимизации, опорная температура барды
nbkSessionConfig.tankTemp уточняется ВВЕРХ по фактическому показанию датчика
барды (nbk_Tb - dD), если это показание выше текущего снимка и не выше
NBK_TN_AUTOCAL_MAX (102 °C). nbk_Tn (рабочая копия, которую nbk_proc()
перезаписывает из снимка каждый тик) правится синхронно, чтобы уточнение
подействовало сразу на этой же итерации.

Харнесс вытаскивает РЕАЛЬНОЕ тело "if (nbk_opt_in_progress) {...}" (та же
обёртка core_tick(), что и в smoke_nbk_opt_found.py/smoke_nbk_pressure_ceiling.py
блок D) из handle_nbk_stage_optimization() через extract_braced_block_after -
блок автотарировки логически расположен между блоком коррекции dD
(USE_NBK_DELTA_PRESSURE) и блоком предзахлёба по давлению [T1-2026-09-03], и
проверяется поэтому в составе полного ядра, а не изолированно.

Плюс статический пин порядка блоков в теле handle_nbk_stage_optimization:
dD -> автотарировка Тн -> давление (T1) -> currentM/currentP - и 4 мутации
(после strip_cpp_comments, каждая обязана провалить харнесс):
  - убрать вычитание dD из измеренной Тб (ломает нормализацию по dD).
  - убрать верхнюю границу NBK_TN_AUTOCAL_MAX (ломает "выше потолка - без изменений").
  - разрешить снижение снимка (> заменить на !=) (ломает "без изменений при просадке").
  - убрать однократность (флаг всегда true) (ломает "второй тик не меняет снимок").
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

CORE_ANCHOR = "if (nbk_opt_in_progress) {"

FLAG_ANCHOR = (
    "if (!nbk_tn_autocal_done) { // [Тарировка Тн] один раз за сессию — на "
    "первой итерации ядра O, до проверки давления и температурного ветвления"
)
MEASURED_TN_ANCHOR = (
    "const float measuredTn = nbk_Tb - nbk_dD; // минус dD: поправка по "
    "давлению не должна учитываться дважды"
)
CEILING_ANCHOR = (
    "if (measuredTn > nbkSessionConfig.tankTemp && measuredTn <= NBK_TN_AUTOCAL_MAX) {"
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
static int dirtyStreamCalls = 0;
void nbk_set_stream_dirty() { dirtyStreamCalls++; }

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

// [Тарировка Тн] предмет этого теста.
@AUTOCAL_MAX_DEFINE@
static bool nbk_tn_autocal_done = false;
struct NbkSessionConfig { float tankTemp; };
static NbkSessionConfig nbkSessionConfig{200.0f};

// [T1-2026-09-03] ветка предзахлёба по давлению (не предмет этого теста, но
// блок 1.10 включён в CORE_ANCHOR) - управляемый флаг по умолчанию false,
// поведение теста не меняется.
#define NBK_HIGH_TB_HOLD_TICKS 3
static uint8_t nbk_high_pressure_ticks = 0;
static bool nbk_opt_entry_by_pressure = false; // [T1] причина автовхода по давлению - не предмет этого теста
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
static int autocalMsgCalls = 0;
static String lastAutocalMsg;
void SendMsg(const String& msg, int) {
  sendMsgCalls++;
  lastMsg = msg;
  if (msg.contains("уточнена")) {
    autocalMsgCalls++;
    lastAutocalMsg = msg;
  }
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

static void reset_fixture() {
  nbk_opt_iter = 10;
  ProgramNum = 5;
  overflowFlag = false;
  handleOverflowCalls = 0;
  fakeMillis = 1000;
  nbk_opt_next_time = 500; // дедлайн уже прошёл - ядро выполняется
  nbk_Tb = 0; nbk_Tp = 0;
  TankSensor.avgTemp = 0; SteamSensor.avgTemp = 0;
  nbk_M = 1000.0f; nbk_P = 5.0f;
  nbk_Mo = -1; nbk_Po = -1;
  nbk_column_inertia = 180;
  nbk_opt_found = false;
  runNbkProgramCalls = 0;
  lastRunNum = 255;
  lastWorkConfirmed = true;
  lastOptimumEntry = true;
  sendMsgCalls = 0;
  lastMsg = String("");
  autocalMsgCalls = 0;
  lastAutocalMsg = String("");
  scheduleShouldSucceed = true;
  scheduleCalls = 0;
  scheduleLastM = -1; scheduleLastP = -1; scheduleLastIter = 65535;
  enterSafeWaitCalls = 0;
  nbk_high_pressure_ticks = 0;
  pressureAboveCeilingFlag = false;
  nbk_dD = 0.0f;
  nbk_Tn = 95.0f;
  nbk_tn_autocal_done = false; // [Тарировка Тн] по умолчанию попытка ещё не потрачена
  nbkSessionConfig.tankTemp = 200.0f; // высокий по умолчанию - явно перевзводится в сценариях
  // Тп заведомо ниже предела - температурная ветка ядра идёт по "else"
  // (Тп < Тп мин), не мешая проверкам автотарировки лишними early-return.
  SteamSensor.avgTemp = 50.0f;
  nbk_Tp_lim = 100.0f;
}

// 1) Измеренная Тб выше снимка и в пределах потолка - снимок и nbk_Tn
// поднимаются РОВНО до measuredTn, уходит ровно одно сообщение "уточнена".
static void test_raises_when_above_snapshot() {
  reset_fixture();
  nbkSessionConfig.tankTemp = 98.5f;
  TankSensor.avgTemp = 99.7f; // dD=0 -> measuredTn = 99.7
  core_tick();
  check(close(nbkSessionConfig.tankTemp, 99.7f), "1: снимок tankTemp обязан подняться ровно до измеренной Тб (99.7)");
  check(close(nbk_Tn, 99.7f), "1: nbk_Tn обязан обновиться синхронно со снимком");
  check(autocalMsgCalls == 1, "1: уточнение обязано отправить ровно одно сообщение");
  check(nbk_tn_autocal_done, "1: флаг однократности обязан взвестись");
}

// 2) Измеренная Тб НИЖЕ снимка - снимок не опускается, попытка всё равно
// потрачена (флаг взведён), сообщений нет.
static void test_no_change_when_below_snapshot() {
  reset_fixture();
  nbkSessionConfig.tankTemp = 98.5f;
  TankSensor.avgTemp = 97.9f; // < 98.5
  core_tick();
  check(close(nbkSessionConfig.tankTemp, 98.5f), "2: снимок не должен опускаться при измерении ниже него");
  check(autocalMsgCalls == 0, "2: без изменения снимка сообщения быть не должно");
  check(nbk_tn_autocal_done, "2: попытка тратится независимо от результата");
}

// 3) Измеренная Тб выше NBK_TN_AUTOCAL_MAX - снимок не меняется.
static void test_no_change_when_above_ceiling() {
  reset_fixture();
  nbkSessionConfig.tankTemp = 98.5f;
  TankSensor.avgTemp = 105.0f; // > NBK_TN_AUTOCAL_MAX(102)
  core_tick();
  check(close(nbkSessionConfig.tankTemp, 98.5f), "3: измерение выше потолка 102 не должно менять снимок");
  check(autocalMsgCalls == 0, "3: без изменения снимка сообщения быть не должно");
}

// 4) Однократность: второй тик той же сессии (флаг уже взведён) не должен
// повторно трогать снимок, даже если Тб сильно изменилась.
static void test_second_tick_is_noop() {
  reset_fixture();
  nbkSessionConfig.tankTemp = 98.5f;
  TankSensor.avgTemp = 99.7f;
  core_tick(); // первая итерация - уточнение срабатывает
  check(close(nbkSessionConfig.tankTemp, 99.7f), "4: первая итерация обязана поднять снимок до 99.7");
  check(autocalMsgCalls == 1, "4: после первой итерации ровно одно сообщение");

  TankSensor.avgTemp = 100.5f; // выше нового снимка - без флага тоже поднял бы его
  core_tick();
  check(close(nbkSessionConfig.tankTemp, 99.7f), "4: вторая итерация НЕ должна снова менять снимок");
  check(autocalMsgCalls == 1, "4: вторая итерация не должна добавить сообщение");
}

// 5) Нормализация по dD: поправка по давлению должна вычитаться ДО сравнения
// и ДО записи в снимок - иначе поправка учлась бы дважды (ещё раз в
// nbk_proc()/сравнениях, использующих dD отдельно).
static void test_normalizes_by_dD() {
  reset_fixture();
  nbkSessionConfig.tankTemp = 98.5f;
  nbk_dD = 0.4f;
  TankSensor.avgTemp = 99.7f; // measuredTn = 99.7 - 0.4 = 99.3
  core_tick();
  check(close(nbkSessionConfig.tankTemp, 99.3f), "5: снимок обязан учитывать вычитание dD (99.7-0.4=99.3)");
  check(close(nbk_Tn, 99.3f), "5: nbk_Tn обязан совпасть со скорректированным снимком");
  check(autocalMsgCalls == 1, "5: корректное уточнение всё равно обязано отправить сообщение");
}

int main() {
  test_raises_when_above_snapshot();
  test_no_change_when_below_snapshot();
  test_no_change_when_above_ceiling();
  test_second_tick_is_noop();
  test_normalizes_by_dD();
  check(dirtyStreamCalls == 0, "тарировка Тн без захлёба не должна переключать поток");
  if (failures != 0) return 1;
  std::cout << "nbk Tn autocal behaviour checks passed\n";
  return 0;
}
'''


def build_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, CORE_ANCHOR)
    wrapped = f"static void core_tick() {{{body}}}"

    define_start = nbk_source.find("#define NBK_TN_AUTOCAL_MAX")
    if define_start < 0:
        raise ValueError("NBK_TN_AUTOCAL_MAX define not found in nbk.h")
    define_end = nbk_source.find("\n", define_start)
    autocal_max_define = nbk_source[define_start:define_end].replace("\r", "").strip()

    harness = HARNESS.replace("@AUTOCAL_MAX_DEFINE@", autocal_max_define)
    return harness.replace("@BODY@", wrapped)


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-tn-autocal-") as temp_dir:
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


def check_core_order_pin(nbk_source: str) -> list:
    """[Пин без компиляции] Порядок блоков в ядре Оптимизации обязан
    оставаться: коррекция dD -> автотарировка Тн -> предзахлёб по давлению
    (T1) -> currentM/currentP - иначе автотарировка либо не видела бы
    актуальный dD, либо срабатывала бы после/внутри других решений ядра."""
    stripped = strip_cpp_comments(nbk_source)
    errors: list = []
    try:
        body, _ = extract_braced_block_after(stripped, CORE_ANCHOR, strip_comments=False)
    except ValueError as error:
        errors.append(f"O-core anchor not found: {error}")
        return errors
    require_ordered_tokens(
        "O core order",
        body,
        [
            "#endif",
            "if (!nbk_tn_autocal_done) {",
            "if (nbk_opt_found && nbk_pressure_above_ceiling()) {",
            "const float currentM = nbk_M;",
        ],
        errors,
    )
    return errors


def mutate_drop_dd(source: str) -> str:
    if MEASURED_TN_ANCHOR not in source:
        raise ValueError("mutation anchor missing: measuredTn dD subtraction")
    mutated = MEASURED_TN_ANCHOR.replace("nbk_Tb - nbk_dD", "nbk_Tb", 1)
    return source.replace(MEASURED_TN_ANCHOR, mutated, 1)


def mutate_remove_ceiling(source: str) -> str:
    if CEILING_ANCHOR not in source:
        raise ValueError("mutation anchor missing: NBK_TN_AUTOCAL_MAX ceiling check")
    mutated = CEILING_ANCHOR.replace(
        "measuredTn > nbkSessionConfig.tankTemp && measuredTn <= NBK_TN_AUTOCAL_MAX",
        "measuredTn > nbkSessionConfig.tankTemp && true",
        1,
    )
    return source.replace(CEILING_ANCHOR, mutated, 1)


def mutate_allow_decrease(source: str) -> str:
    if CEILING_ANCHOR not in source:
        raise ValueError("mutation anchor missing: tankTemp comparison operator")
    mutated = CEILING_ANCHOR.replace(
        "measuredTn > nbkSessionConfig.tankTemp", "measuredTn != nbkSessionConfig.tankTemp", 1
    )
    return source.replace(CEILING_ANCHOR, mutated, 1)


def mutate_disable_once(source: str) -> str:
    if FLAG_ANCHOR not in source:
        raise ValueError("mutation anchor missing: nbk_tn_autocal_done once-only gate")
    mutated = FLAG_ANCHOR.replace("if (!nbk_tn_autocal_done) {", "if (true) {", 1)
    return source.replace(FLAG_ANCHOR, mutated, 1)


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness, True) != 0:
        return 1

    pin_errors = check_core_order_pin(nbk_source)
    if pin_errors:
        for error in pin_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    mutations = [
        ("drop dD subtraction", mutate_drop_dd),
        ("remove NBK_TN_AUTOCAL_MAX ceiling", mutate_remove_ceiling),
        ("allow snapshot decrease", mutate_allow_decrease),
        ("disable once-only gate", mutate_disable_once),
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

    print("nbk Tn autocal checks (behaviour + order pin + mutations) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
