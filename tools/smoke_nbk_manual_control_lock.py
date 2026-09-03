#!/usr/bin/env python3
"""Поведенческая проверка [Ремонт-2026-09-02 П4/П5.1]: ручной ввод не должен
обходить алгоритм НБК на Оптимизации и в Работе.

До этой правки /command?Voltage=... и /command?pnbk=... применялись
исполнителями Samovar.ino (tick_apply_pending_voltage/tick_apply_pending_pnbk)
БЕЗ проверки текущей строки программы НБК - оператор мог руками задать
мощность/подачу прямо во время автоматического регулирования, и следующий тик
алгоритма даже не заметил бы вмешательства (см. память проекта: п.4 плана
"ручные правки видимы алгоритму"). Теперь оба исполнителя проверяют реальный
предикат nbk_manual_control_locked() (nbk.h) и, если он true, глушат команду
одним предупреждением вместо применения.

Кнопка "Установить как оптимальные" (tick_apply_pending_nbkopt, П5.1) - другой
контракт: она обязана писать РЕАЛЬНЫЕ значения (регулятор, насос) и разрешена
только на строках S/W (доступна оператору именно там, где раньше писала нули).

Три харнесса в одном файле, все дергают РЕАЛЬНЫЕ тела функций через
extract_function_body - логика не копируется:
  1. nbk_manual_control_locked() (nbk.h) - матрица статус x тип строки.
  2. tick_apply_pending_voltage()/tick_apply_pending_pnbk() (Samovar.ino) -
     поведение исполнителей при locked/unlocked.
  3. tick_apply_pending_nbkopt() (Samovar.ino) - разрешённые строки (S/W)
     против запрещённых (O/H).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

LOCK_SIGNATURE = "inline bool nbk_manual_control_locked() {"
VOLTAGE_SIGNATURE = "static void tick_apply_pending_voltage() {"
PNBK_SIGNATURE = "static void tick_apply_pending_pnbk() {"
NBKOPT_SIGNATURE = "static void tick_apply_pending_nbkopt() {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
  String(float value, int) : value_(std::to_string(value)) {}
  String operator+(const String& rhs) const { return String(value_ + rhs.value_); }
  const std::string& text() const { return value_; }
 private:
  explicit String(const std::string& value) : value_(value) {}
  std::string value_;
};
static String operator+(const char* lhs, const String& rhs) {
  return String(lhs) + rhs;
}

#define PWR_SIGN "Вт"
float fromPower(float value) { return value; }

using ProgramType = char;

// --- Состояние процесса, разделяемое обеими проверяемыми зонами ---
static int16_t SamovarStatusInt = 0;
static int16_t startval = 0;
static constexpr int16_t SAMOVAR_STATUS_NBK = 4000;          // Samovar.h
static constexpr int16_t SAMOVAR_STARTVAL_NBK_RUNNING = 4001; // Samovar.h

static char programTypeStub = 'H';
ProgramType current_program_type() { return programTypeStub; }

@LOCK_BODY@

// --- Заглушки исполнителей (Samovar.ino) ---
static bool lockAvailable = true;
struct PendingCommandLockGuard {
  bool held;
  PendingCommandLockGuard() : held(lockAvailable) {}
  explicit operator bool() const { return held; }
};

template <typename T>
static bool take_pending_value(volatile bool& flag, volatile T& valueSlot, T& out) {
  PendingCommandLockGuard guard;
  bool has = false;
  if (guard && flag) {
    out = valueSlot;
    flag = false;
    has = true;
  }
  return has;
}
static bool take_pending_flag(volatile bool& flag) {
  PendingCommandLockGuard guard;
  bool has = false;
  if (guard && flag) {
    flag = false;
    has = true;
  }
  return has;
}

static bool PowerOn = true;
static int sendMsgCalls = 0;
void SendMsg(const char*, MESSAGE_TYPE) { sendMsgCalls++; }
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

// --- tick_apply_pending_voltage ---
static volatile bool pending_voltage_flag = false;
static volatile float pending_voltage_value = 0;
static int setCurrentPowerCalls = 0;
static float lastSetCurrentPowerVolt = -1;
void set_current_power(float voltage) {
  setCurrentPowerCalls++;
  lastSetCurrentPowerVolt = voltage;
}

@VOLTAGE_BODY@

// --- tick_apply_pending_pnbk ---
enum ControlNbkKind : uint8_t {
  CONTROL_NBK_STOP = 0,
  CONTROL_NBK_ABSOLUTE,
  CONTROL_NBK_DECREMENT,
  CONTROL_NBK_INCREMENT,
};
struct ControlNbkCommand {
  ControlNbkKind kind;
  uint16_t stepSpeed;
};
static volatile bool pending_pnbk_flag = false;
static ControlNbkCommand pending_pnbk_value = {};

struct NumericParseResult {
  bool okValue;
  bool ok() const { return okValue; }
};
static constexpr int NUMERIC_PARSE_OK = 0;
static NumericParseResult numeric_parse_result(int) { return NumericParseResult{true}; }
static NumericParseResult checked_rate_to_step_speed(float, uint16_t, uint16_t& out) {
  out = 0;
  return NumericParseResult{true};
}
static uint16_t stepperSpeedStub = 0;
uint16_t get_stepper_speed() { return stepperSpeedStub; }
static int setStepperTargetCalls = 0;
static uint16_t lastStepperTargetSpeed = 0;
bool set_stepper_target(uint16_t spd, uint8_t, uint32_t, bool = false) {
  setStepperTargetCalls++;
  lastStepperTargetSpeed = spd;
  return true;
}
void feedLoopWDT() {}
struct SamSetupType {
  float NbkDP;
  uint16_t StepperStepMlI2C;
};
static SamSetupType SamSetup = {0.5f, 16000};

@PNBK_BODY@

// --- tick_apply_pending_nbkopt ---
static volatile bool pending_nbkopt_flag = false;
static float target_power_volt = 0;
static float nbk_Mo = -1;
static float nbk_Po = -1;
static float nbk_Po_ceiling = -1;
static uint8_t nbk_high_temp_ticks = 0;
static float feedRateStub = 0;
float nbk_actual_feed_rate() { return feedRateStub; }
float toPower(float value) { return value * 2.0f; } // произвольный, но не тождественный множитель — ловит пропуск вызова

@NBKOPT_BODY@

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

// === Часть 1: nbk_manual_control_locked() — статус x тип строки ===
static void reset_status(int16_t status, int16_t sv, char rowType) {
  SamovarStatusInt = status;
  startval = sv;
  programTypeStub = rowType;
}

static void test_lock_matrix() {
  // Статус НБК, строка после прогрева (RUNNING): O и W заблокированы, S - нет.
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'O');
  check(nbk_manual_control_locked(), "НБК/RUNNING/O обязана быть locked");
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'W');
  check(nbk_manual_control_locked(), "НБК/RUNNING/W обязана быть locked");
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'S');
  check(!nbk_manual_control_locked(), "НБК/RUNNING/S не должна быть locked (Ручная настройка)");

  // Второй статус: не-НБК режим (дистилляция) с тем же startval/типом — не locked.
  reset_status(1000, SAMOVAR_STARTVAL_NBK_RUNNING, 'O');
  check(!nbk_manual_control_locked(), "чужой режим (не НБК) не должен блокировать ручной ввод");

  // Статус НБК, но ещё разгон (startval < RUNNING) — не locked.
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING - 1, 'O');
  check(!nbk_manual_control_locked(), "НБК до RUNNING (разгон) не должен блокировать ручной ввод");

  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'H');
  check(!nbk_manual_control_locked(), "строка H под НБК/RUNNING не должна блокировать ручной ввод");
}

// === Часть 2: tick_apply_pending_voltage ===
static void test_voltage_locked() {
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'O');
  pending_voltage_flag = true;
  pending_voltage_value = 211.5f;
  setCurrentPowerCalls = 0;
  sendMsgCalls = 0;
  tick_apply_pending_voltage();
  check(setCurrentPowerCalls == 0, "locked: set_current_power не должен вызываться");
  check(sendMsgCalls == 1, "locked: ровно одно сообщение о блокировке");
  check(!pending_voltage_flag, "locked: pending-флаг обязан быть снят");
}

static void test_voltage_unlocked() {
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'S');
  pending_voltage_flag = true;
  pending_voltage_value = 187.25f; // второе, отличное от locked-кейса значение
  setCurrentPowerCalls = 0;
  sendMsgCalls = 0;
  tick_apply_pending_voltage();
  check(setCurrentPowerCalls == 1, "unlocked: set_current_power обязан вызваться");
  check(lastSetCurrentPowerVolt == 187.25f, "unlocked: применённое значение обязано совпасть с pending-значением");
  check(sendMsgCalls == 0, "unlocked: сообщения о блокировке быть не должно");
  check(!pending_voltage_flag, "unlocked: pending-флаг обязан быть снят");
}

// === Часть 3: tick_apply_pending_pnbk ===
static void test_pnbk_locked_on_optimization() {
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'O');
  PowerOn = true;
  pending_pnbk_flag = true;
  pending_pnbk_value = {CONTROL_NBK_ABSOLUTE, 500};
  setStepperTargetCalls = 0;
  sendMsgCalls = 0;
  tick_apply_pending_pnbk();
  check(setStepperTargetCalls == 0, "locked(O): set_stepper_target не должен вызываться");
  check(sendMsgCalls == 1, "locked(O): ровно одно сообщение о блокировке");
  check(!pending_pnbk_flag, "locked(O): pending-флаг обязан быть снят");
}

static void test_pnbk_locked_on_work() {
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'W');
  PowerOn = true;
  pending_pnbk_flag = true;
  pending_pnbk_value = {CONTROL_NBK_ABSOLUTE, 900}; // второе значение
  setStepperTargetCalls = 0;
  sendMsgCalls = 0;
  tick_apply_pending_pnbk();
  check(setStepperTargetCalls == 0, "locked(W): set_stepper_target не должен вызываться");
  check(sendMsgCalls == 1, "locked(W): ровно одно сообщение о блокировке");
  check(!pending_pnbk_flag, "locked(W): pending-флаг обязан быть снят");
}

static void test_pnbk_unlocked() {
  reset_status(SAMOVAR_STATUS_NBK, SAMOVAR_STARTVAL_NBK_RUNNING, 'S');
  PowerOn = true;
  pending_pnbk_flag = true;
  pending_pnbk_value = {CONTROL_NBK_ABSOLUTE, 777};
  setStepperTargetCalls = 0;
  sendMsgCalls = 0;
  tick_apply_pending_pnbk();
  check(setStepperTargetCalls == 1, "unlocked: set_stepper_target обязан вызваться");
  check(lastStepperTargetSpeed == 777, "unlocked: применённая скорость обязана совпасть с командой");
  check(sendMsgCalls == 0, "unlocked: сообщения о блокировке быть не должно");
  check(!pending_pnbk_flag, "unlocked: pending-флаг обязан быть снят");
}

// === Часть 4: tick_apply_pending_nbkopt (П5.1) ===
static void reset_nbkopt_state() {
  SamovarStatusInt = SAMOVAR_STATUS_NBK; // кнопка принадлежит НБК; чужой режим проверяется отдельно
  startval = SAMOVAR_STARTVAL_NBK_RUNNING;
  nbk_Mo = -111.0f;
  nbk_Po = -111.0f;
  nbk_Po_ceiling = -111.0f;
  nbk_high_temp_ticks = 9;
}

static void test_nbkopt_on_manual() {
  reset_nbkopt_state();
  programTypeStub = 'S';
  PowerOn = true;
  target_power_volt = 210.0f;
  feedRateStub = 4.5f;
  pending_nbkopt_flag = true;
  sendMsgCalls = 0;
  tick_apply_pending_nbkopt();
  check(nbk_Mo == toPower(210.0f), "S: nbk_Mo обязан взять toPower(target_power_volt)");
  check(nbk_Po == 4.5f, "S: nbk_Po обязан взять реальную подачу насоса");
  check(nbk_Po_ceiling == -111.0f, "S: потолок По не должен трогаться вне строки W");
  check(nbk_high_temp_ticks == 9, "S: счётчик тиков не должен трогаться вне строки W");
  check(sendMsgCalls == 1, "S: одно сообщение об успехе");
  check(!pending_nbkopt_flag, "S: pending-флаг обязан быть снят");
}

static void test_nbkopt_on_work() {
  reset_nbkopt_state();
  programTypeStub = 'W';
  PowerOn = true;
  target_power_volt = 235.0f; // второе значение
  feedRateStub = 6.25f;       // вторая скорость
  pending_nbkopt_flag = true;
  sendMsgCalls = 0;
  tick_apply_pending_nbkopt();
  check(nbk_Mo == toPower(235.0f), "W: nbk_Mo обязан взять toPower(target_power_volt)");
  check(nbk_Po == 6.25f, "W: nbk_Po обязан взять реальную подачу насоса");
  check(nbk_Po_ceiling == 6.25f, "П10: потолок По обязан следовать за новым nbk_Po на строке W");
  check(nbk_high_temp_ticks == 0, "W: счётчик тиков высокой Тб обязан сброситься");
  check(sendMsgCalls == 1, "W: одно сообщение об успехе");
}

static void test_nbkopt_rejected_on(char rowType) {
  reset_nbkopt_state();
  programTypeStub = rowType;
  PowerOn = true;
  target_power_volt = 999.0f;
  feedRateStub = 42.0f;
  pending_nbkopt_flag = true;
  sendMsgCalls = 0;
  tick_apply_pending_nbkopt();
  check(nbk_Mo == -111.0f, std::string("отказ на строке ") + rowType + ": nbk_Mo не должен меняться");
  check(nbk_Po == -111.0f, std::string("отказ на строке ") + rowType + ": nbk_Po не должен меняться");
  check(sendMsgCalls == 1, std::string("отказ на строке ") + rowType + ": одно сообщение об отказе");
  check(!pending_nbkopt_flag, std::string("отказ на строке ") + rowType + ": pending-флаг всё равно снимается");
}

// [Ревью R3] Строки 'S' (стабилизация БК/дистилляции) и 'W' (ожидание пива) существуют
// и в других режимах: вне НБК кнопка обязана отказывать даже на «правильной» букве.
static void test_nbkopt_rejected_in_foreign_mode(char rowType, int16_t status) {
  reset_nbkopt_state();
  SamovarStatusInt = status;
  programTypeStub = rowType;
  PowerOn = true;
  target_power_volt = 777.0f;
  feedRateStub = 13.0f;
  pending_nbkopt_flag = true;
  sendMsgCalls = 0;
  tick_apply_pending_nbkopt();
  check(nbk_Mo == -111.0f, std::string("чужой режим, строка ") + rowType + ": nbk_Mo не должен меняться");
  check(nbk_Po == -111.0f, std::string("чужой режим, строка ") + rowType + ": nbk_Po не должен меняться");
  check(nbk_Po_ceiling == -111.0f, std::string("чужой режим, строка ") + rowType + ": потолок По не должен меняться");
  check(sendMsgCalls == 1, std::string("чужой режим, строка ") + rowType + ": одно сообщение об отказе");
  check(!pending_nbkopt_flag, std::string("чужой режим, строка ") + rowType + ": pending-флаг снимается");
}

int main() {
  test_lock_matrix();
  test_voltage_locked();
  test_voltage_unlocked();
  test_pnbk_locked_on_optimization();
  test_pnbk_locked_on_work();
  test_pnbk_unlocked();
  test_nbkopt_on_manual();
  test_nbkopt_on_work();
  test_nbkopt_rejected_on('O');
  test_nbkopt_rejected_on('H');
  test_nbkopt_rejected_in_foreign_mode('S', 2000); // дистилляция/БК: стабилизация
  test_nbkopt_rejected_in_foreign_mode('W', 3000); // пиво: ожидание
  if (failures != 0) return 1;
  std::cout << "nbk manual control lock behaviour checks passed\n";
  return 0;
}
'''


def build_harness(nbk_source: str, ino_source: str) -> str:
    lock_body = extract_function_body(nbk_source, LOCK_SIGNATURE)
    voltage_body = extract_function_body(ino_source, VOLTAGE_SIGNATURE)
    pnbk_body = extract_function_body(ino_source, PNBK_SIGNATURE)
    nbkopt_body = extract_function_body(ino_source, NBKOPT_SIGNATURE)

    harness = HARNESS_TEMPLATE
    harness = harness.replace(
        "@LOCK_BODY@", f"bool nbk_manual_control_locked() {{{lock_body}}}"
    )
    harness = harness.replace(
        "@VOLTAGE_BODY@", f"static void tick_apply_pending_voltage() {{{voltage_body}}}"
    )
    harness = harness.replace(
        "@PNBK_BODY@", f"static void tick_apply_pending_pnbk() {{{pnbk_body}}}"
    )
    harness = harness.replace(
        "@NBKOPT_BODY@", f"static void tick_apply_pending_nbkopt() {{{nbkopt_body}}}"
    )
    return harness


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-manual-lock-") as temp_dir:
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


def mutate_lock_row_check(nbk_source: str, ino_source: str):
    anchor = "(current_program_type() == 'O' || current_program_type() == 'W');"
    if anchor not in nbk_source:
        raise ValueError("mutation anchor missing: lock row-type check")
    return nbk_source.replace(anchor, "true;", 1), ino_source


def mutate_voltage_skip_lock(nbk_source: str, ino_source: str):
    anchor = "static void tick_apply_pending_voltage() {"
    start = ino_source.find(anchor)
    if start < 0:
        raise ValueError("mutation anchor missing: tick_apply_pending_voltage")
    branch = "if (nbk_manual_control_locked()) {"
    branch_index = ino_source.find(branch, start)
    if branch_index < 0:
        raise ValueError("mutation anchor missing: voltage lock branch")
    mutated = (
        ino_source[:branch_index]
        + "if (false) {"
        + ino_source[branch_index + len(branch):]
    )
    return nbk_source, mutated


def mutate_nbkopt_accept_any_row(nbk_source: str, ino_source: str):
    anchor = "if (!PowerOn || SamovarStatusInt != SAMOVAR_STATUS_NBK || (currentType != 'S' && currentType != 'W')) {"
    if anchor not in ino_source:
        raise ValueError("mutation anchor missing: nbkopt row guard")
    return nbk_source, ino_source.replace(anchor, "if (false) {", 1)


def mutate_nbkopt_ignore_mode(nbk_source: str, ino_source: str):
    # [Ревью R3] кнопка обязана проверять сам режим НБК, а не только букву строки.
    anchor = "if (!PowerOn || SamovarStatusInt != SAMOVAR_STATUS_NBK || (currentType != 'S' && currentType != 'W')) {"
    if anchor not in ino_source:
        raise ValueError("mutation anchor missing: nbkopt mode guard")
    return nbk_source, ino_source.replace(
        anchor, "if (!PowerOn || (currentType != 'S' && currentType != 'W')) {", 1
    )


MUTATIONS = (
    ("lock row-type check disabled", mutate_lock_row_check),
    ("voltage executor ignores lock", mutate_voltage_skip_lock),
    ("nbkopt accepts any row", mutate_nbkopt_accept_any_row),
    ("nbkopt ignores mode", mutate_nbkopt_ignore_mode),
)


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    ino_source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")

    try:
        harness = build_harness(nbk_source, ino_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness, True) != 0:
        return 1

    for label, mutate in MUTATIONS:
        try:
            mutated_nbk, mutated_ino = mutate(nbk_source, ino_source)
        except ValueError as error:
            print(f"FAIL: {label}: {error}", file=sys.stderr)
            return 1
        if mutated_nbk == nbk_source and mutated_ino == ino_source:
            print(f"FAIL: mutation had no effect: {label}", file=sys.stderr)
            return 1
        mutated_harness = build_harness(mutated_nbk, mutated_ino)
        if compile_and_run(mutated_harness, False) == 0:
            print(f"FAIL: mutation survived (expected failure): {label}", file=sys.stderr)
            return 1

    print("nbk manual control lock mutations caught")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
