#!/usr/bin/env python3
"""Поведенческая проверка [Ремонт-2026-09-02 П11]: дедупликация команд и
сообщений в handle_nbk_stage_work().

До этой правки на КАЖДОМ такте, пока держится температурное условие,
уходили и повторное сообщение, и повторная команда актуатору - даже если
цель (candidateM/candidateP) не изменилась относительно уже применённой
(currentM/currentP), и даже пока счётчик NBK_HIGH_TB_HOLD_TICKS ещё не
набрал нужное число тиков для реального повышения подачи. Теперь:
1) команда уходит, только если candidateP/candidateM реально отличаются
   от currentP/currentM (иначе просто продлевается таймер паузы);
2) сообщение "снижаем"/"увеличиваем" уходит, только если nbk_Po реально
   изменилась в ЭТОМ такте (сравнение с previousPo ДО ветвлений).

Харнесс вытаскивает РЕАЛЬНОЕ тело "if (!nbk_work_in_pause) {...}" из
handle_nbk_stage_work() через extract_braced_block_after - счётчик тиков,
клампы и дедуп-условия не копируются руками.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

CORE_ANCHOR = "if (!nbk_work_in_pause ) {"

COMMAND_DEDUP_ANCHOR = (
    "const bool commandNeeded = (candidateP != currentP) || (candidateM != currentM);"
)
MESSAGE_DEDUP_ANCHOR = "if (nbk_Po > previousPo) {"

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define NBK_HIGH_TB_HOLD_TICKS 3
#define NBK_SPILL_DT_MULT 3
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum NbkActuatorDeadlineTarget { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };
#define NBK_MULT_PAUSE_OVERFLOW 2

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(float value, int) : value_(std::to_string(value)) {}
  String& operator+=(const char* rhs) { value_ += (rhs ? rhs : ""); return *this; }
  String& operator+=(const String& rhs) { value_ += rhs.value_; return *this; }
  void reserve(size_t) {}
  bool contains(const char* needle) const { return value_.find(needle) != std::string::npos; }
 private:
  std::string value_;
};

struct SensorProbe { float avgTemp; };
static SensorProbe TankSensor{0};
static SensorProbe SteamSensor{0};

static bool overflowFlag = false;
bool overflow() { return overflowFlag; }
static int handleOverflowCalls = 0;
void handle_overflow(const String&, bool = true, uint32_t = 0) { handleOverflowCalls++; }

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
static uint32_t nbk_work_next_time = 0;
bool safety_deadline_expired(uint32_t now, uint32_t deadline) {
  return (int32_t)(now - deadline) >= 0;
}
uint32_t safety_deadline_after(uint32_t now, uint32_t delayMs) { return now + delayMs; }

static float nbk_Tb = 0, nbk_Tp = 0;
static float nbk_Tn = 95.0f, nbk_dT = 1.0f, nbk_dD = 0.0f, nbk_Tp_lim = 100.0f;
static float nbk_M = 0, nbk_P = 0;
static float nbk_Mo = 0, nbk_Po = 0, nbk_Po_ceiling = 999.0f;
static float nbk_dP = 1.0f;
static uint16_t nbk_high_temp_ticks = 0;
static uint16_t nbk_column_inertia = 180;
static uint16_t nbk_opt_iter = 0;

// [T1-2026-09-03] ветка по давлению (не предмет этого теста, но должна
// компилироваться) - управляемый флаг по умолчанию false, поведение теста
// не меняется.
static uint8_t nbk_high_pressure_ticks = 0;
static float pressure_value = 0;
static float nbk_pressure_ceiling = 0;
static bool pressureAboveCeilingFlag = false;
bool nbk_pressure_above_ceiling() { return pressureAboveCeilingFlag; }

static int sendMsgCalls = 0;
static String lastMsg;
void SendMsg(const String& msg, int) {
  sendMsgCalls++;
  lastMsg = msg;
}

static bool scheduleShouldSucceed = true;
static int scheduleCalls = 0;
static float scheduleLastM = -1, scheduleLastP = -1;
bool nbk_schedule_actuator_command(float candidateM, float candidateP, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  scheduleLastM = candidateM;
  scheduleLastP = candidateP;
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

// Один такт всегда "уже готов" по таймеру - тестируем счётчик/дедуп-логику,
// а не сам таймер (он реальный, но безусловно взводится expired перед тактом).
static void tick() {
  nbk_work_next_time = fakeMillis - 1;
  fake_work_core_tick();
  fakeMillis += 1;
}

static void reset_fixture() {
  overflowFlag = false;
  handleOverflowCalls = 0;
  fakeMillis = 1000;
  nbk_work_next_time = 0;
  nbk_Tb = 0; nbk_Tp = 0;
  TankSensor.avgTemp = 0; SteamSensor.avgTemp = 0;
  nbk_high_temp_ticks = 0;
  nbk_column_inertia = 180;
  nbk_opt_iter = 0;
  nbk_high_pressure_ticks = 0;
  pressureAboveCeilingFlag = false;
  sendMsgCalls = 0;
  lastMsg = String("");
  scheduleShouldSucceed = true;
  scheduleCalls = 0;
  scheduleLastM = -1; scheduleLastP = -1;
  enterSafeWaitCalls = 0;
}

// Высокая Тб (выше Тн+dT) - подача растёт только раз в NBK_HIGH_TB_HOLD_TICKS
// тактов. Тики 1..HOLD-1 обязаны быть полностью тихими (ни команды, ни
// сообщения), HOLD-й - ровно одна команда и одно сообщение.
static void test_raise_branch_hold_gate() {
  reset_fixture();
  TankSensor.avgTemp = 101.0f; // > Тн(95)+dT(1)
  SteamSensor.avgTemp = 105.0f;
  nbk_M = 1200.0f; nbk_Mo = 1200.0f; // М не участвует в этой ветке - совпадает заранее
  nbk_P = 5.0f; nbk_Po = 5.0f;       // По==Р - до первого реального повышения кандидаты совпадают

  for (int i = 1; i < NBK_HIGH_TB_HOLD_TICKS; ++i) {
    tick();
    check(scheduleCalls == 0, "raise: тик " + std::to_string(i) + " до HOLD не должен слать команду");
    check(sendMsgCalls == 0, "raise: тик " + std::to_string(i) + " до HOLD не должен слать сообщение");
  }
  tick(); // HOLD-й такт
  check(scheduleCalls == 1, "raise: HOLD-й такт обязан отправить РОВНО одну команду");
  check(sendMsgCalls == 1, "raise: HOLD-й такт обязан отправить РОВНО одно сообщение");
  check(lastMsg.contains("увеличиваем подачу"), "raise: сообщение обязано быть про увеличение подачи");
  check(scheduleLastP > 5.0f, "raise: команда обязана нести увеличенную По");
  check(nbk_high_temp_ticks == 0, "raise: счётчик обязан сброситься после срабатывания");
}

// Низкая Тб, но По уже на полу (0) и М/П совпадают с целью - кандидаты не
// меняются вообще, значит ни команды, ни сообщения "снижаем" быть не должно.
static void test_lower_branch_no_op_at_floor() {
  reset_fixture();
  TankSensor.avgTemp = 90.0f; // < Тн(95)-dT(1)
  SteamSensor.avgTemp = 105.0f;
  nbk_M = 800.0f; nbk_Mo = 800.0f;
  nbk_P = 0.0f; nbk_Po = 0.0f; // уже на полу - снижать некуда

  tick();
  check(scheduleCalls == 0, "floor: без реального изменения кандидатов команда не должна уйти");
  check(sendMsgCalls == 0, "floor: без реального снижения По сообщение 'снижаем' не должно уйти");
  check(nbk_work_next_time > fakeMillis - 2, "floor: пауза обязана продлиться таймером, а не командой");
}

// Низкая Тб, есть куда снижать - сообщение и команда уходят СРАЗУ на первом
// же качественном такте (у понижения нет HOLD-задержки, в отличие от повышения).
static void test_lower_branch_reacts_immediately() {
  reset_fixture();
  TankSensor.avgTemp = 93.0f; // [Пролив] < Тн(95)-dT(1)=94, но НЕ ниже порога пролива 92 (Тн-3dT)
  SteamSensor.avgTemp = 105.0f;
  nbk_M = 800.0f; nbk_Mo = 800.0f;
  nbk_P = 5.0f; nbk_Po = 5.0f;

  tick();
  check(scheduleCalls == 1, "lower: первый же такт с реальным снижением обязан отправить команду");
  check(sendMsgCalls == 1, "lower: первый же такт с реальным снижением обязан отправить сообщение");
  check(lastMsg.contains("снижаем подачу"), "lower: сообщение обязано быть про снижение подачи");
  check(scheduleLastP < 5.0f, "lower: команда обязана нести уменьшенную По");
}

// [Ревью R4] Вторая половина условия commandNeeded: По на полу (не меняется),
// но применённая мощность nbk_M разошлась с целевой nbk_Mo - команда обязана
// уйти ради одной только мощности, а сообщение "снижаем" - нет (По не изменилась).
static void test_command_sent_for_power_only() {
  reset_fixture();
  TankSensor.avgTemp = 93.0f; // [Пролив] < Тн(95)-dT(1)=94, но НЕ ниже порога пролива 92 (Тн-3dT) - ветка снижения, candidateM = nbk_Mo
  SteamSensor.avgTemp = 105.0f;
  nbk_M = 800.0f; nbk_Mo = 900.0f; // М разошлась с целью
  nbk_P = 0.0f; nbk_Po = 0.0f;     // По на полу - candidateP == currentP

  tick();
  check(scheduleCalls == 1, "power-only: расхождение М с Мо при неизменной По обязано отправить команду");
  check(scheduleLastM == 900.0f, "power-only: команда обязана нести целевую Мо");
  check(scheduleLastP == 0.0f, "power-only: По в команде остаётся на полу");
  check(sendMsgCalls == 0, "power-only: без реального снижения По сообщения быть не должно");
}

int main() {
  test_raise_branch_hold_gate();
  test_lower_branch_no_op_at_floor();
  test_lower_branch_reacts_immediately();
  test_command_sent_for_power_only();
  if (failures != 0) return 1;
  std::cout << "nbk work message/command dedup checks passed\n";
  return 0;
}
'''


def build_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, CORE_ANCHOR)
    wrapped = f"static void fake_work_core_tick() {{{body}}}"
    return HARNESS.replace("@BODY@", wrapped)


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-work-dedup-") as temp_dir:
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


def mutate_always_send_command(source: str) -> str:
    # П11 п.1: команда уходит на КАЖДОМ такте, а не только при реальном
    # изменении кандидатов - должно сломать тики 1..HOLD-1 (scheduleCalls>0).
    if COMMAND_DEDUP_ANCHOR not in source:
        raise ValueError("mutation anchor missing: commandNeeded dedup condition")
    return source.replace(COMMAND_DEDUP_ANCHOR, "const bool commandNeeded = true;", 1)


def mutate_command_ignores_power(source: str) -> str:
    # [Ревью R4] потеря половины условия по мощности - ловится только сценарием power-only.
    if COMMAND_DEDUP_ANCHOR not in source:
        raise ValueError("mutation anchor missing: command dedup (power half)")
    return source.replace(COMMAND_DEDUP_ANCHOR, "const bool commandNeeded = (candidateP != currentP);", 1)


def mutate_always_send_raise_message(source: str) -> str:
    # П11 п.2: сообщение "увеличиваем подачу" уходит независимо от реального
    # изменения По - должно сломать тики 1..HOLD-1 (sendMsgCalls>0).
    if MESSAGE_DEDUP_ANCHOR not in source:
        raise ValueError("mutation anchor missing: raise-message dedup condition")
    return source.replace(MESSAGE_DEDUP_ANCHOR, "if (true) {", 1)


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness, True) != 0:
        return 1

    try:
        mutated_command = mutate_always_send_command(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated_command == nbk_source:
        print("FAIL: command-dedup mutation had no effect", file=sys.stderr)
        return 1
    mutated_harness = build_harness(mutated_command)
    if compile_and_run(mutated_harness, False) == 0:
        print("FAIL: command-dedup mutation survived (expected failure): always send command", file=sys.stderr)
        return 1

    try:
        mutated_power = mutate_command_ignores_power(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if compile_and_run(build_harness(mutated_power), False) == 0:
        print("FAIL: command-dedup mutation survived (expected failure): power half dropped", file=sys.stderr)
        return 1

    try:
        mutated_message = mutate_always_send_raise_message(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated_message == nbk_source:
        print("FAIL: message-dedup mutation had no effect", file=sys.stderr)
        return 1
    mutated_message_harness = build_harness(mutated_message)
    if compile_and_run(mutated_message_harness, False) == 0:
        print("FAIL: message-dedup mutation survived (expected failure): always send raise message", file=sys.stderr)
        return 1

    print("nbk work message/command dedup checks (behaviour + mutations) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
