#!/usr/bin/env python3
"""Поведенческая проверка [Ремонт-2026-09-02 П5.2/П13]: флаг nbk_opt_found -
"хотя бы одна итерация Оптимизации нашла рабочую точку (Тб>=Тн и Тп>=Тп_lim)".

До этой правки при упоре в предел мощности или лимит итераций сообщение
всегда звучало как успех ("Достигнута предельная мощность"/"Достигнут лимит
итераций"), даже если ни одна итерация так и не подтвердила рабочую точку -
оператор не мог отличить реальный оптимум от "перебрали все итерации
впустую". Теперь при !nbk_opt_found обе ветки говорят "Оптимум не найден",
а nbk_Mo/nbk_Po при входе в Оптимизацию НЕ обнуляются - flag "найден ли
оптимум СЕЙЧАС" живёт отдельно от последних реальных М/П.

Харнесс вытаскивает РЕАЛЬНОЕ тело "if (nbk_opt_in_progress) {...}" (ядро
цикла Оптимизации) из handle_nbk_stage_optimization() через
extract_braced_block_after - арифметика и ветвление не копируются.
Дихотомия handle_overflow/run_nbk_program(...,true) внутри этого же блока
уже отдельно и подробно пропиннена в smoke_nbk_auto_work_entry.py - здесь
overflow() держится ложным, чтобы дойти до температурного ядра.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

CORE_ANCHOR = "if (nbk_opt_in_progress) {"
INIT_START_ANCHOR = "nbk_opt_in_progress = true;"
INIT_SAFE_WAIT_ANCHOR = "nbk_enter_safe_wait("

# Ветка "упёрлись в предел мощности" - именно её nbk_opt_found-развилку и
# мутируем ниже (в файле есть вторая, отдельная if(nbk_opt_found) в ветке
# лимита итераций - у неё другой хвост, поэтому этот якорь уникален).
POWER_LIMIT_MUTATION_ANCHOR = (
    '        if (nbk_opt_found) {\n'
    '          SendMsg("Достигнута предельная мощность.'
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

template <typename T> T max(T a, T b) { return a > b ? a : b; }

// [Тарировка Тн] не предмет этого теста, но блок 1.10 включён в CORE_ANCHOR -
// флаг всегда взведён заранее (reset_fixture), поведение теста не меняется.
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

static void reset_fixture() {
  nbk_opt_iter = 10;
  ProgramNum = 5;
  overflowFlag = false;
  handleOverflowCalls = 0;
  fakeMillis = 1000;
  nbk_opt_next_time = 500; // дедлайн уже прошёл - ядро выполняется
  nbk_Tb = 0; nbk_Tp = 0;
  TankSensor.avgTemp = 0; SteamSensor.avgTemp = 0;
  nbk_M = 0; nbk_P = 0;
  nbk_Mo = -1; nbk_Po = -1;
  nbk_column_inertia = 180;
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
  dirtyStreamCalls = 0;
  pressureAboveCeilingFlag = false;
  nbk_tn_autocal_done = true;
}

// 0) Итерации уже за пределом лимита на входе в тик - немедленный переход,
// температурное ядро вообще не вычисляется.
static void test_iteration_cap_short_circuits() {
  reset_fixture();
  nbk_opt_iter = 300;
  core_tick();
  check(runNbkProgramCalls == 1 && lastRunNum == ProgramNum + 1,
        "0: превышение лимита итераций на входе обязано сразу перейти к следующей строке");
  check(scheduleCalls == 0, "0: температурное ядро не должно вычисляться при уже превышенном лимите");
}

// 1) Тб>=Тн и Тп>=Тп_lim, подача в пределах насоса - оптимум найден,
// Мо/По фиксируются реальными текущими значениями, идёт "увеличиваем подачу".
static void test_found_within_pump_limit() {
  reset_fixture();
  nbk_opt_found = false;
  TankSensor.avgTemp = 96.0f; SteamSensor.avgTemp = 101.0f; // >= Тн(95) и >= Тп_lim(100)
  nbk_M = 1500.0f; nbk_P = 8.0f;
  core_tick();
  check(nbk_opt_found, "1: успешная итерация обязана взвести nbk_opt_found");
  check(nbk_Mo == 1500.0f && nbk_Po == 8.0f, "1: Мо/По обязаны зафиксировать реальные текущие М/П этой итерации");
  check(scheduleCalls == 1, "1: команда на увеличение подачи обязана уйти ровно один раз");
  check(scheduleLastM == 1500.0f, "1: М не меняется в ветке увеличения подачи");
  check(scheduleLastP == 9.0f, "1: П обязана увеличиться на dП (8+1)");
  check(lastMsg.contains("увеличиваем подачу"), "1: сообщение обязано говорить про увеличение подачи");
  check(runNbkProgramCalls == 0, "1: переход к следующей строке здесь не нужен");
  check(enterSafeWaitCalls == 0, "1: успешная подача команды не должна уходить в safe-wait");
  check(dirtyStreamCalls == 0, "1: без захлёба сервопривод потока не должен двигаться");
}

// 2) Тот же успех, но кандидат подачи ПРЕВЫШАЕТ предел насоса - отдельная
// ветка "предельная подача", nbk_opt_found всё равно взводится.
static void test_found_exceeds_pump_limit() {
  reset_fixture();
  nbk_opt_found = false;
  TankSensor.avgTemp = 96.0f; SteamSensor.avgTemp = 101.0f;
  nbk_M = 1500.0f; nbk_P = 29.5f; // 29.5 + dП(1) = 30.5 > NBK_PUMP_LIMIT(30)
  core_tick();
  check(nbk_opt_found, "2: nbk_opt_found обязан взвестись до проверки предела насоса");
  check(nbk_Mo == 1500.0f && nbk_Po == 29.5f, "2: Мо/По фиксируются до проверки предела насоса");
  check(lastMsg.contains("Достигнута предельная подача"), "2: сообщение о пределе насоса обязано отправиться");
  check(runNbkProgramCalls == 1 && lastRunNum == ProgramNum + 1,
        "2: предел насоса обязан завершить Оптимизацию переходом к следующей строке");
  check(scheduleCalls == 0, "2: при пределе насоса новая команда не планируется");
}

// 3) Тб/Тп ещё не достигли порогов, мощность в пределах - обычная итерация
// подъёма мощности; nbk_opt_found НЕ трогается этой веткой вообще (не
// сбрасывается в false, если был найден раньше).
static void test_not_found_within_power_limit() {
  reset_fixture();
  nbk_opt_found = true; // был найден на прошлой итерации этой же Оптимизации
  TankSensor.avgTemp = 80.0f;        // < Тн(95)
  SteamSensor.avgTemp = 50.0f;        // < Тп_lim(100) -> ветка "Тп < Тп мин"
  nbk_M = 1000.0f; nbk_P = 5.0f; // 1000+dM(50)=1050 <= M_max(3000)
  core_tick();
  check(nbk_opt_found, "3: обычный шаг подъёма мощности не должен трогать nbk_opt_found");
  check(scheduleLastM == 1050.0f, "3: М обязана вырасти на dM");
  check(scheduleLastP == 4.0f, "3: П обязана снизиться на шаг dП (5 - dП(1) = 4), а не домножиться на 0.9");
  check(lastMsg.contains("Тп < Тп мин"), "3: при низком Тп сообщение обязано быть про Тп");
  check(runNbkProgramCalls == 0, "3: обычная итерация не переходит к следующей строке");
}

static void test_not_found_high_steam_message() {
  reset_fixture();
  nbk_opt_found = false;
  TankSensor.avgTemp = 80.0f;
  SteamSensor.avgTemp = 150.0f; // >= Тп_lim -> ветка "Тб < Тн"
  nbk_M = 1000.0f; nbk_P = 5.0f;
  core_tick();
  check(lastMsg.contains("Тб < Тн"), "3б: при уже достаточном Тп сообщение обязано быть про Тб");
}

// 4) Мощность упёрлась в предел (currentM+dM > M_max) - здесь и живёт
// развилка П5.2: без найденного оптимума текст "Оптимум не найден",
// с найденным - "Достигнута предельная мощность".
static void test_power_limit_not_found_message() {
  reset_fixture();
  nbk_opt_found = false;
  TankSensor.avgTemp = 80.0f; SteamSensor.avgTemp = 50.0f;
  nbk_M = 2960.0f; nbk_P = 5.0f; // 2960+50=3010 > 3000
  core_tick();
  check(lastMsg.contains("Оптимум не найден"),
        "4а: без найденного оптимума упор в мощность обязан явно сказать 'Оптимум не найден'");
  check(!lastMsg.contains("Достигнута предельная мощность"),
        "4а: старый текст успеха не должен звучать, если оптимум не найден");
  check(runNbkProgramCalls == 1 && lastRunNum == ProgramNum + 1,
        "4а: упор в мощность всё равно обязан перейти к следующей строке");
}

static void test_power_limit_found_message() {
  reset_fixture();
  nbk_opt_found = true;
  nbk_Po = 12.5f; // результат прошлой удачной итерации
  TankSensor.avgTemp = 80.0f; SteamSensor.avgTemp = 50.0f;
  nbk_M = 2960.0f; nbk_P = 5.0f;
  core_tick();
  check(lastMsg.contains("Достигнута предельная мощность"),
        "4б: с найденным оптимумом сообщение обязано говорить про предел мощности, а не 'не найден'");
  check(!lastMsg.contains("Оптимум не найден"), "4б: текст 'не найден' не должен звучать при найденном оптимуме");
}

// 5) Лимит итераций достигнут ИМЕННО на этом тике (nextIteration==300) -
// та же П5.2-развилка, но в другой ветке кода.
static void test_iteration_limit_not_found_message() {
  reset_fixture();
  nbk_opt_iter = 299; // nextIteration станет 300
  nbk_opt_found = false;
  TankSensor.avgTemp = 80.0f; SteamSensor.avgTemp = 50.0f;
  nbk_M = 1000.0f; nbk_P = 5.0f; // в пределах мощности - обычная итерация
  core_tick();
  check(scheduleLastIter == 300, "5а: nextIteration обязана дойти до 300 ровно на этом тике");
  check(sendMsgCalls == 2, "5а: обязаны уйти оба сообщения - шаг итерации И итог по лимиту");
  check(lastMsg.contains("Оптимум не найден"), "5а: на пределе итераций без находки обязано звучать 'Оптимум не найден'");
}

static void test_iteration_limit_found_message() {
  reset_fixture();
  nbk_opt_iter = 299;
  nbk_opt_found = false; // будет найден именно на этой итерации
  TankSensor.avgTemp = 96.0f; SteamSensor.avgTemp = 101.0f; // успешная итерация -> найдёт оптимум прямо сейчас
  nbk_M = 1500.0f; nbk_P = 8.0f;
  core_tick();
  check(nbk_opt_found, "5б: успешная итерация на пределе обязана взвести nbk_opt_found");
  check(lastMsg.contains("Достигнут лимит итераций"), "5б: с найденным оптимумом итог обязан звучать как успех");
  check(!lastMsg.contains("Оптимум не найден"), "5б: текст 'не найден' не должен звучать при найденном оптимуме");
}

// 6) Команда отклонена планировщиком - safe-wait, а не тихий возврат, и
// НИКАКОГО сообщения по лимиту итераций (early return до этой проверки).
static void test_schedule_rejected_enters_safe_wait() {
  reset_fixture();
  nbk_opt_iter = 299;
  TankSensor.avgTemp = 96.0f; SteamSensor.avgTemp = 101.0f;
  nbk_M = 1500.0f; nbk_P = 8.0f;
  scheduleShouldSucceed = false;
  core_tick();
  check(enterSafeWaitCalls == 1, "6: отклонённая команда обязана уйти в safe-wait");
  check(sendMsgCalls == 1, "6: до safe-wait успевает уйти только сообщение шага итерации, не итог по лимиту");
  check(runNbkProgramCalls == 0, "6: safe-wait не должен переходить к следующей строке");
}

int main() {
  test_iteration_cap_short_circuits();
  test_found_within_pump_limit();
  test_found_exceeds_pump_limit();
  test_not_found_within_power_limit();
  test_not_found_high_steam_message();
  test_power_limit_not_found_message();
  test_power_limit_found_message();
  test_iteration_limit_not_found_message();
  test_iteration_limit_found_message();
  test_schedule_rejected_enters_safe_wait();
  if (failures != 0) return 1;
  std::cout << "nbk opt_found core behaviour checks passed\n";
  return 0;
}
'''


def build_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, CORE_ANCHOR)
    wrapped = f"static void core_tick() {{{body}}}"
    return HARNESS.replace("@BODY@", wrapped)


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-opt-found-") as temp_dir:
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


def check_mo_po_not_reset_pin(nbk_source: str) -> list:
    """[Пин без компиляции] Вход в Оптимизацию НЕ обязан обнулять nbk_Mo/
    nbk_Po - только nbk_opt_found. Иначе "Установить как оптимальные" на
    Работе после мгновенного повторного захода в Оптимизацию потеряло бы
    последний реальный результат ещё ДО первой успешной итерации."""
    errors: list = []
    start = nbk_source.find(INIT_START_ANCHOR)
    if start < 0:
        errors.append("O-stage init anchor not found: nbk_opt_in_progress = true;")
        return errors
    end = nbk_source.find(INIT_SAFE_WAIT_ANCHOR, start)
    if end < 0:
        errors.append("O-stage init end anchor not found: nbk_enter_safe_wait(")
        return errors
    segment = strip_cpp_comments(nbk_source[start:end])
    if "nbk_opt_found = false;" not in segment:
        errors.append("O-stage init does not reset nbk_opt_found to false")
    if "nbk_Mo = 0" in segment:
        errors.append("П5.2 regression: O-stage init resets nbk_Mo to 0 (must keep last real value)")
    if "nbk_Po = 0" in segment:
        errors.append("П5.2 regression: O-stage init resets nbk_Po to 0 (must keep last real value)")
    return errors


def mutate_invert_power_limit_found_check(source: str) -> str:
    # Меняет местами тексты "Достигнута предельная мощность" и "Оптимум не
    # найден" - должно сломать сценарии 4а/4б (найденный/ненайденный оптимум).
    if POWER_LIMIT_MUTATION_ANCHOR not in source:
        raise ValueError("mutation anchor missing: power-limit nbk_opt_found branch")
    mutated_anchor = POWER_LIMIT_MUTATION_ANCHOR.replace(
        "if (nbk_opt_found) {", "if (!nbk_opt_found) {", 1
    )
    return source.replace(POWER_LIMIT_MUTATION_ANCHOR, mutated_anchor, 1)


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness, True) != 0:
        return 1

    pin_errors = check_mo_po_not_reset_pin(nbk_source)
    if pin_errors:
        for error in pin_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        mutated = mutate_invert_power_limit_found_check(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated == nbk_source:
        print("FAIL: mutation had no effect", file=sys.stderr)
        return 1
    mutated_harness = build_harness(mutated)
    if compile_and_run(mutated_harness, False) == 0:
        print("FAIL: mutation survived (expected failure): power-limit found-check inverted", file=sys.stderr)
        return 1

    print("nbk opt_found checks (behaviour + init pin + mutation) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
