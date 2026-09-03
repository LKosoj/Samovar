#!/usr/bin/env python3
"""Поведенческая проверка [Ремонт-2026-09-02 П1/П2/П3/П10]: автовход в Работу
НБК с найденным в Оптимизации оптимумом идёт через ТУ ЖЕ машину паузы Работы,
что и обычный захлёб (nbk_work_in_pause/nbk_work_pause_stage), а не через
отдельный путь. Четыре харнесса, все дергают РЕАЛЬНЫЕ фрагменты nbk.h через
extract_braced_block_after/extract_function_body:

1. W-ветка run_nbk_program() (`if (program[num].WType == 'W') {`) - новый
   параметр optimumEntry: команда max(Mo/2, порог)/подача-насоса-3, пауза
   MULT*Ин, commit=true, commitKeepsOptimum=true, ОДНО сообщение; отказ при
   Mo<=0 или По<=0 или выключенном нагреве - safe wait без единой команды.
   Старые кейсы явного/автоматического входа сохранены, включая П5.3
   (нулевые Power/Speed строки W берут nbk_Mo/nbk_Po, если они > 0).
2. Блок коммита (`if (nbkActuatorCommand.commitProgram) {` в
   tick_nbk_actuator_command): при commitKeepsOptimum nbk_Mo/nbk_Po НЕ
   переписываются кандидатами, Работа уходит в паузу (stage=1,
   nbk_overflow_happened=false, потолок По синхронизирован); без
   commitKeepsOptimum - старое поведение (кандидаты становятся Mo/По, паузы
   нет).
3. Ветка захлёба в handle_nbk_stage_optimization() (`if (overflow()) {` внутри
   цикла оптимизации): при !nbk_opt_found - путь "оптимум не найден"
   (handle_overflow, ЛЮБОЙ текст без "Оптимизация завершена." - эту фразу
   теперь произносит autoentry-ветка run_nbk_program); при nbk_opt_found -
   ровно один вызов run_nbk_program(ProgramNum + 1, false, true) и НИ одного
   вызова handle_overflow.
1б. [Ревью R4] Порядок веток run_nbk_program (фрагмент от проверки датчиков
   до конца legacy-ветки «нагрев выключен»): safe wait на строке W обязан
   возобновлять Работу (W-ветка стоит раньше П8), на строке O - завершать
   сессию (П8); мутация переставляет П8 выше W.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

W_ANCHOR = "if (program[num].WType == 'W') {"
COMMIT_ANCHOR = "if (nbkActuatorCommand.commitProgram) {"
OVERFLOW_ANCHOR = "if (overflow()) { // Если захлёб по ДЗ или ДД"


# ==========================================================================
# Харнесс 1: W-ветка run_nbk_program(num, workConfirmed, optimumEntry)
# ==========================================================================
W_HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER
#define PWR_SIGN "Вт"
float fromPower(float value) { return value; }

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
enum NbkActuatorDeadlineTarget : uint8_t {
  NBK_ACTUATOR_WORK_DEADLINE = 2,
};
class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
  String(float value, int) : value_(std::to_string(value)) {}
  void reserve(size_t) {}
  String& operator+=(const char* text) { value_ += (text ? text : ""); return *this; }
  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  String(uint32_t value) : value_(std::to_string(value)) {}
  String operator+(const String& rhs) const { return String(value_ + rhs.value_); }
  const std::string& text() const { return value_; }
 private:
  explicit String(const std::string& value) : value_(value) {}
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(lhs) + rhs;
}
struct ProgramRow {
  char WType;
  float Power;
  float Speed;
};
struct SessionProbe { bool valid; };
static ProgramRow program[4] = {};
static SessionProbe nbkSessionConfig = {true};
static bool nbk_safe_waiting = false;
static bool nbk_safe_wait_feed_stopped = false;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
static bool PowerOn = true;
static bool transitionActive = false;
static uint16_t nbk_column_inertia = 180;
static uint16_t nbk_opt_iter = 7;
static float nbk_Mo = 0;
static float nbk_Po = 0;
static float feedRateStub = 0;
// [T1] автовход по давлению: флаг причины и значения для текста сообщения.
static bool nbk_opt_entry_by_pressure = false;
static float pressure_value = 0;
static float nbk_pressure_ceiling = 0;
 // [заглушка-зависимость] реальная скорость насоса, не nbk_Po
float nbk_actual_feed_rate() { return feedRateStub; }
float power_work_mode_threshold() { return 40.0f; } // [T14] нижняя граница в ваттном домене - юнит-конвертация проверяется отдельно
static float max(float left, float right) { return left > right ? left : right; }
#define NBK_MULT_PAUSE_OVERFLOW 2

static int safeWaitCalls = 0;
static int scheduleCalls = 0;
static int powerOnCalls = 0;
static bool scheduledCommit = false;
static uint8_t scheduledProgram = 255;
static float scheduledM = -1;
static float scheduledP = -1;
static bool scheduledKeepsOptimum = false;
static bool scheduleShouldSucceed = true;
static int sendMsgCalls = 0;

void nbk_enter_safe_wait(const String&) {
  safeWaitCalls++;
  nbk_safe_waiting = true;
  nbk_safe_wait_result = ACTUATOR_COMMAND_APPLIED;
  PowerOn = false;
}
void tick_nbk_safe_wait() {}
bool power_transition_active() { return transitionActive; }
void set_power(bool on, bool = true) {
  powerOnCalls++;
  PowerOn = on;
}
float toPower(float value) { return value * 2.0f; }
bool nbk_schedule_actuator_command(
    float power,
    float speed,
    NbkActuatorDeadlineTarget,
    uint32_t,
    uint16_t,
    bool commit = false,
    uint8_t programNum = 0,
    bool commitKeepsOptimum = false) {
  scheduleCalls++;
  scheduledM = power;
  scheduledP = speed;
  scheduledCommit = commit;
  scheduledProgram = programNum;
  scheduledKeepsOptimum = commitKeepsOptimum;
  return scheduleShouldSucceed;
}
static std::string lastMsg;
void SendMsg(const String& msg, MESSAGE_TYPE) { sendMsgCalls++; lastMsg = msg.text(); }

static void run_w(uint8_t num, bool workConfirmed, bool optimumEntry = false) {
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
  program[1] = {'W', 500, 6};
  nbkSessionConfig.valid = true;
  nbk_safe_waiting = false;
  nbk_safe_wait_feed_stopped = false;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  PowerOn = true;
  transitionActive = false;
  nbk_Mo = 0;
  nbk_Po = 0;
  feedRateStub = 0;
  safeWaitCalls = 0;
  scheduleCalls = 0;
  powerOnCalls = 0;
  scheduledCommit = false;
  scheduledProgram = 255;
  scheduledM = -1;
  scheduledP = -1;
  scheduledKeepsOptimum = false;
  scheduleShouldSucceed = true;
  sendMsgCalls = 0;
  lastMsg.clear();
  nbk_opt_entry_by_pressure = false;
  pressure_value = 25.0f;
  nbk_pressure_ceiling = 20.0f;
}
int main() {
  // --- [regression] Автоматический O->W без явного подтверждения и без
  // optimumEntry по-прежнему уходит в safe wait без единой команды. ---
  reset_fixture();
  run_w(1, false);
  check(safeWaitCalls == 1 && scheduleCalls == 0,
        "автоматический O->W обязан перейти в safe-wait без команды приводам");

  // --- [regression] Явный W с нулевой мощностью и БЕЗ сохранённых Mo/По -
  // остаётся в safe-wait. ---
  reset_fixture();
  program[1].Power = 0;
  program[1].Speed = 0;
  run_w(1, true);
  check(safeWaitCalls == 1 && scheduleCalls == 0,
        "явный W с нулевыми параметрами и без сохранённых Mo/По обязан остаться в safe-wait");

  // --- [П5.3] Явный W с нулевыми Power/Speed, но с сохранёнными nbk_Mo/По -
  // fallback на них БЕЗ повторной toPower()-конвертации (уже в ваттах). ---
  reset_fixture();
  program[1].Power = 0;
  program[1].Speed = 0;
  nbk_Mo = 800;
  nbk_Po = 4;
  run_w(1, true);
  check(safeWaitCalls == 0 && scheduleCalls == 1,
        "П5.3: fallback на сохранённые Mo/По обязан пройти без safe-wait");
  check(scheduledM == 800 && scheduledP == 4,
        "П5.3: fallback обязан передать nbk_Mo/nbk_Po без повторной конвертации toPower()");

  // --- [regression] Явный W с ненулевыми параметрами строки принимает их,
  // конвертируя Power через toPower(). ---
  reset_fixture();
  run_w(1, true);
  check(safeWaitCalls == 0 && scheduleCalls == 1,
        "явный W с ненулевыми параметрами должен принять одну команду");
  check(scheduledM == 1000 && scheduledP == 6 &&
            scheduledCommit && scheduledProgram == 1,
        "W должен передать точные M/P и отложенный commit строки");

  // --- [П1] optimumEntry: команда max(Mo/2, порог) и реальная подача/3,
  // commit=true, commitKeepsOptimum=true, ОДНО сообщение. Первое значение
  // Mo достаточно большое, чтобы Mo/2 победил порог. ---
  reset_fixture();
  nbk_Mo = 1000;
  nbk_Po = 6; // не используется напрямую - candidateP берёт реальную подачу насоса
  feedRateStub = 18.0f;
  run_w(1, true, true);
  check(scheduleCalls == 1 && safeWaitCalls == 0,
        "optimumEntry с валидными Mo/По обязан отправить ровно одну команду");
  check(scheduledM == 500.0f, "optimumEntry: candidateM = max(Mo/2, порог), Mo/2 побеждает");
  check(scheduledP == 6.0f, "optimumEntry: candidateP = реальная подача насоса / 3");
  check(scheduledCommit && scheduledKeepsOptimum && scheduledProgram == 1,
        "optimumEntry обязан коммититься с commitKeepsOptimum=true");
  check(sendMsgCalls == 1, "optimumEntry обязан дать РОВНО одно сообщение");
  check(lastMsg.find("по давлению") == std::string::npos,
        "[T1] обычный автовход (по температуре) не должен упоминать давление");

  // --- [T1] Автовход по давлению: ОДНО сообщение с причиной внутри, флаг
  // причины сбрасывается сразу (иначе следующий автовход по температуре
  // унаследует чужую причину). ---
  reset_fixture();
  nbk_Mo = 1000;
  nbk_Po = 6;
  feedRateStub = 18.0f;
  nbk_opt_entry_by_pressure = true;
  run_w(1, true, true);
  check(sendMsgCalls == 1, "[T1] автовход по давлению обязан дать РОВНО одно сообщение");
  check(lastMsg.find("по давлению") != std::string::npos && lastMsg.find("Оптимизация завершена") != std::string::npos,
        "[T1] единственное сообщение обязано содержать и итог, и причину (давление)");
  check(!nbk_opt_entry_by_pressure, "[T1] флаг причины обязан сброситься после использования");

  // --- [T1] Флаг сбрасывается и при отказе автовхода (safe-wait), чтобы не протухнуть. ---
  reset_fixture();
  nbk_Mo = 0; // оптимум невалиден -> safe-wait
  nbk_opt_entry_by_pressure = true;
  run_w(1, true, true);
  check(safeWaitCalls == 1, "[T1] невалидный оптимум обязан уйти в safe-wait");
  check(!nbk_opt_entry_by_pressure, "[T1] флаг причины обязан сброситься и при отказе автовхода");

  // --- [П1] optimumEntry: второе значение Mo - настолько малое, что Mo/2
  // ниже порога, ожидаем клампинг снизу. ---
  reset_fixture();
  nbk_Mo = 50; // Mo/2=25 < toPower(порог)=80
  nbk_Po = 4;
  feedRateStub = 9.0f;
  run_w(1, true, true);
  check(scheduleCalls == 1, "optimumEntry с малым Mo всё равно обязан отправить команду");
  check(scheduledM == 80.0f, "optimumEntry: candidateM обязан клэмпиться toPower(порога), когда Mo/2 ниже него");
  check(scheduledP == 3.0f, "optimumEntry: candidateP = 9.0/3");

  // --- [П1] optimumEntry с nbk_Mo<=0 - safe wait без единой команды. ---
  reset_fixture();
  nbk_Mo = 0;
  nbk_Po = 4;
  run_w(1, true, true);
  check(scheduleCalls == 0 && safeWaitCalls == 1,
        "optimumEntry с Mo<=0 обязан уйти в safe-wait без команды");

  // --- [П1] optimumEntry при выключенном нагреве - safe wait без команды,
  // даже если Mo/По валидны. ---
  reset_fixture();
  nbk_Mo = 900;
  nbk_Po = 5;
  PowerOn = false;
  run_w(1, true, true);
  check(scheduleCalls == 0 && safeWaitCalls == 1,
        "optimumEntry при выключенном нагреве обязан уйти в safe-wait без команды");

  return failures == 0 ? 0 : 1;
}
'''


def build_w_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, W_ANCHOR)
    return W_HARNESS.replace("@BODY@", body.replace("\r\n", "\n"))


# ==========================================================================
# Харнесс 1б [Ревью R4]: порядок веток run_nbk_program - W-ветка (возобновление
# после safe wait / явный вход) обязана стоять РАНЬШЕ ветки П8 «safe wait на
# H/S/O => nbk_finish», иначе «Следующая программа» на строке W во время safe
# wait завершала бы сессию вместо возобновления Работы. Фрагмент берётся
# ЦЕЛИКОМ: от проверки датчиков до конца legacy-ветки «нагрев выключен».
# ==========================================================================
TAIL_START_ANCHOR = "if (!nbk_stage_sensors_valid(program[num].WType)) return;"
TAIL_LEGACY_ANCHOR = "if (num > 0 && !PowerOn) {"
P8_FINISH_ANCHOR = "if (nbk_safe_waiting && num > 0) {"

TAIL_STUBS = r'''
bool nbk_stage_sensors_valid(char) { return true; }
static int finishCalls = 0;
void nbk_finish() { finishCalls++; }
static int cancelCalls = 0;
void nbk_cancel_program_start(const String&) { cancelCalls++; }
static bool fellThrough = false;
'''

TAIL_MAIN = r'''
static void reset_tail() {
  reset_fixture();
  finishCalls = 0;
  cancelCalls = 0;
  fellThrough = false;
}

int main() {
  // A: safe wait на строке W, явное подтверждение - обязано ВОЗОБНОВИТЬ Работу
  // (команда приводам), а не завершить сессию через П8.
  reset_tail();
  program[1] = {'W', 500, 6};
  nbk_safe_waiting = true;
  nbk_safe_wait_result = ACTUATOR_COMMAND_APPLIED;
  PowerOn = false;
  run_w(1, true);
  check(scheduleCalls == 1, "порядок веток: safe wait на строке W обязан возобновить Работу командой приводам");
  check(finishCalls == 0, "порядок веток: ветка П8 не должна перехватывать строку W");
  check(cancelCalls == 0, "порядок веток: отмены на строке W быть не должно");
  check(powerOnCalls == 1, "порядок веток: возобновление обязано включить нагрев");
  check(!fellThrough, "порядок веток: W-ветка обязана завершиться return");

  // B: safe wait на строке НЕ W (O) - штатное завершение сессии через П8.
  reset_tail();
  program[1] = {'O', 0, 0};
  nbk_safe_waiting = true;
  PowerOn = false;
  run_w(1, true);
  check(finishCalls == 1, "порядок веток: safe wait на строке O обязан завершить сессию (П8)");
  check(scheduleCalls == 0 && cancelCalls == 0, "порядок веток: на строке O ни команды, ни отмены");
  check(!fellThrough, "порядок веток: ветка П8 обязана завершиться return");

  // C: без safe wait и с переходом нагрева - legacy-отмена, не завершение.
  reset_tail();
  program[1] = {'O', 0, 0};
  nbk_safe_waiting = false;
  PowerOn = false;
  transitionActive = true;
  run_w(1, true);
  check(cancelCalls == 1 && finishCalls == 0, "порядок веток: переход нагрева без safe wait обязан отменить старт");

  return failures == 0 ? 0 : 1;
}
'''


def build_tail_harness(nbk_source: str) -> str:
    start = nbk_source.index(TAIL_START_ANCHOR)
    _, end_legacy = extract_braced_block_after(nbk_source, TAIL_LEGACY_ANCHOR, offset=start)
    combined = nbk_source[start:end_legacy].replace("\r\n", "\n")
    prelude = W_HARNESS.split("int main() {")[0]
    prelude = prelude.replace("static void run_w(", TAIL_STUBS + "static void run_w(", 1)
    prelude = prelude.replace("@BODY@", combined + "\n  fellThrough = true;")
    return prelude + TAIL_MAIN


# ==========================================================================
# Харнесс 2: блок коммита в tick_nbk_actuator_command
# ==========================================================================
COMMIT_HARNESS = r'''
#include <cstdint>
#include <iostream>

enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

struct NbkActuatorCommandState {
  bool commitProgram;
  bool commitKeepsOptimum;
  uint8_t candidateProgramNum;
  float candidateM;
  float candidateP;
};
static NbkActuatorCommandState nbkActuatorCommand = {};

static uint8_t ProgramNum = 0;
static float nbk_Mo = 0;
static float nbk_Po = 0;
static float nbk_Po_ceiling = 0;
static uint8_t nbk_high_temp_ticks = 0;
// [T1-2026-09-03] счётчик тиков высокого давления - коммит обязан сбрасывать
// его так же, как nbk_high_temp_ticks (тот же блок 1.5).
static uint8_t nbk_high_pressure_ticks = 9;
static bool nbk_pause_overflow_repeat_latched = false;
static bool nbk_work_in_pause = false;
static uint8_t nbk_work_pause_stage = 0;
static bool nbk_overflow_happened = false;
static bool nbk_safe_waiting = false;
static bool nbk_safe_wait_feed_stopped = false;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_APPLIED;

static void run_commit() {
  if (nbkActuatorCommand.commitProgram) {
@BODY@
  }
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- [П1] commitKeepsOptimum=true: Mo/По НЕ переписываются кандидатами -
  // Работа уходит в паузу автовхода (stage=1, overflow_happened сброшен). ---
  nbkActuatorCommand = {true, true, 5, 300.0f, 2.5f};
  ProgramNum = 0;
  nbk_Mo = 555.0f;
  nbk_Po = 7.5f;
  nbk_Po_ceiling = -1.0f;
  nbk_high_temp_ticks = 9;
  nbk_high_pressure_ticks = 9;
  nbk_pause_overflow_repeat_latched = true;
  nbk_work_in_pause = false;
  nbk_work_pause_stage = 0;
  nbk_overflow_happened = true;
  nbk_safe_waiting = true;
  nbk_safe_wait_feed_stopped = true;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  run_commit();
  check(ProgramNum == 5, "commit обязан перевести ProgramNum на строку кандидата");
  check(nbk_Mo == 555.0f && nbk_Po == 7.5f,
        "keepsOptimum: nbk_Mo/nbk_Po НЕ должны переписываться кандидатами");
  check(nbk_Po_ceiling == nbk_Po, "П10: потолок По обязан синхронизироваться с текущим По");
  check(nbk_high_temp_ticks == 0, "commit обязан сбросить счётчик тиков высокой Тб");
  check(nbk_high_pressure_ticks == 0, "commit обязан сбросить счётчик тиков высокого давления");
  check(!nbk_pause_overflow_repeat_latched, "commit обязан снять защёлку повторного захлёба");
  check(nbk_work_in_pause, "keepsOptimum обязан перевести Работу в паузу автовхода");
  check(nbk_work_pause_stage == 1, "keepsOptimum обязан выставить стадию паузы 1");
  check(!nbk_overflow_happened, "keepsOptimum обязан снять флаг захлёба (гарантия П3)");
  check(!nbk_safe_waiting && !nbk_safe_wait_feed_stopped,
        "commit обязан снять флаги безопасного ожидания");
  check(nbk_safe_wait_result == ACTUATOR_COMMAND_FAILED,
        "commit обязан сбросить результат безопасного ожидания");

  // --- [regression] commitKeepsOptimum=false (второе значение кандидатов):
  // старое поведение - кандидаты становятся новыми Mo/По, паузы нет. ---
  nbkActuatorCommand = {true, false, 9, 640.0f, 3.25f};
  ProgramNum = 0;
  nbk_Mo = 1.0f;
  nbk_Po = 1.0f;
  nbk_Po_ceiling = -1.0f;
  nbk_high_temp_ticks = 4;
  nbk_work_in_pause = true;
  nbk_work_pause_stage = 2;
  nbk_overflow_happened = true;
  run_commit();
  check(nbk_Mo == 640.0f && nbk_Po == 3.25f,
        "без keepsOptimum: nbk_Mo/nbk_Po обязаны стать кандидатами");
  check(nbk_Po_ceiling == 3.25f, "П10: потолок По обязан следовать за новым По");
  check(!nbk_work_in_pause, "без keepsOptimum: Работа не должна уходить в паузу");
  check(!nbk_overflow_happened, "commit безусловно снимает флаг захлёба");

  return failures == 0 ? 0 : 1;
}
'''


def build_commit_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, COMMIT_ANCHOR)
    return COMMIT_HARNESS.replace("@BODY@", body.replace("\r\n", "\n"))


# ==========================================================================
# Харнесс 3: ветка захлёба в ядре Оптимизации (О-сторона автоперехода)
# ==========================================================================
OVERFLOW_HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define PWR_MSG "Мощность"

class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
  String operator+(const String& rhs) const { return String(value_ + rhs.value_); }
  const std::string& text() const { return value_; }
 private:
  explicit String(const std::string& value) : value_(value) {}
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(lhs) + rhs;
}

static bool test_overflow = true;
bool overflow() { return test_overflow; }

static bool nbk_opt_found = false;
static uint8_t ProgramNum = 3;
static bool nbk_opt_entry_by_pressure = false; // [T1] причина автовхода - захлёб обязан её сбросить

static int handleOverflowCalls = 0;
static std::string lastHandleOverflowMsg;
void handle_overflow(const String& msg, bool = true, uint32_t = 0, bool = false) {
  handleOverflowCalls++;
  lastHandleOverflowMsg = msg.text();
}

static int runNbkProgramCalls = 0;
static uint8_t lastRunNum = 255;
static bool lastWorkConfirmed = true;
static bool lastOptimumEntry = false;
void run_nbk_program(uint8_t num, bool workConfirmed, bool optimumEntry) {
  runNbkProgramCalls++;
  lastRunNum = num;
  lastWorkConfirmed = workConfirmed;
  lastOptimumEntry = optimumEntry;
}

static bool didReturn = false;
static void run_overflow_tick() {
  handleOverflowCalls = 0;
  runNbkProgramCalls = 0;
  didReturn = false;
  if (overflow()) { // Если захлёб по ДЗ или ДД
@BODY@
  }
  didReturn = true; // extracted block всегда return-ит - до сюда доходить не должно
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- Оптимум НЕ найден: старый путь "оптимум не найден" - handle_overflow
  // с ЛЮБЫМ текстом, но БЕЗ фразы "Оптимизация завершена." (П2: эту фразу
  // теперь произносит autoentry-ветка run_nbk_program, не эта функция). ---
  test_overflow = true;
  nbk_opt_found = false;
  ProgramNum = 3;
  run_overflow_tick();
  check(handleOverflowCalls == 1, "!opt_found: обязан вызваться handle_overflow ровно один раз");
  check(runNbkProgramCalls == 0, "!opt_found: run_nbk_program(..., true) вызываться не должен");
  check(lastHandleOverflowMsg.find("Оптимизация завершена.") == std::string::npos,
        "П2: текст 'Оптимизация завершена.' сюда переехать не должен");

  // --- Оптимум найден: единственный вызов run_nbk_program(ProgramNum+1,
  // false, true) - автовход, без единого вызова handle_overflow. ---
  test_overflow = true;
  nbk_opt_found = true;
  ProgramNum = 6;
  run_overflow_tick();
  check(handleOverflowCalls == 0, "opt_found: handle_overflow вызываться не должен");
  check(runNbkProgramCalls == 1, "opt_found: run_nbk_program обязан вызваться ровно один раз");
  check(lastRunNum == 7 && !lastWorkConfirmed && lastOptimumEntry,
        "opt_found: переход обязан быть run_nbk_program(ProgramNum + 1, false, true)");

  // --- [T1] Флаг «по давлению» мог остаться от автовхода, сорвавшегося на
  // раннем return в run_nbk_program; захлёб обязан выставить свою причину явно. ---
  test_overflow = true;
  nbk_opt_found = true;
  nbk_opt_entry_by_pressure = true;
  run_overflow_tick();
  check(!nbk_opt_entry_by_pressure,
        "[T1] автовход по захлёбу обязан сбросить nbk_opt_entry_by_pressure до вызова run_nbk_program");

  return failures == 0 ? 0 : 1;
}
'''


def build_overflow_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, OVERFLOW_ANCHOR)
    return OVERFLOW_HARNESS.replace("@BODY@", body.replace("\r\n", "\n"))


def compile_and_run(harness: str, prefix: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
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


def mutate_w_optimum_entry_gate(source: str) -> str:
    anchor = "    if (optimumEntry) {"
    if anchor not in source:
        raise ValueError("mutation anchor missing: optimumEntry gate")
    # [Ревью R4] параметр остаётся использованным - мутант обязан погибнуть от check(),
    # а не от -Werror=unused-parameter.
    return source.replace(anchor, "    if (optimumEntry && false) {", 1)


def mutate_p8_before_w(source: str) -> str:
    # [Ревью R4] переставляет ветку П8 ВЫШЕ W-ветки - возобновление Работы после
    # safe wait превращается в завершение сессии (сценарий A обязан это поймать).
    if P8_FINISH_ANCHOR not in source or TAIL_START_ANCHOR not in source:
        raise ValueError("mutation anchor missing: P8 finish branch / tail start")
    idx = source.index(P8_FINISH_ANCHOR)
    _, end = extract_braced_block_after(source, P8_FINISH_ANCHOR, strip_comments=False)
    block = source[idx:end]
    removed = source[:idx] + source[end:]
    insert = removed.index(TAIL_START_ANCHOR) + len(TAIL_START_ANCHOR)
    return removed[:insert] + "\n  " + block + removed[insert:]


def mutate_commit_keeps_optimum(source: str) -> str:
    anchor = "    if (!nbkActuatorCommand.commitKeepsOptimum) {"
    if anchor not in source:
        raise ValueError("mutation anchor missing: commitKeepsOptimum guard")
    return source.replace(anchor, "    if (true) {", 1)


def mutate_opt_found_gate(source: str) -> str:
    anchor = "        if (!nbk_opt_found) {"
    if anchor not in source:
        raise ValueError("mutation anchor missing: nbk_opt_found guard")
    return source.replace(anchor, "        if (true) {", 1)


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        w_harness = build_w_harness(nbk_source)
        tail_harness = build_tail_harness(nbk_source)
        commit_harness = build_commit_harness(nbk_source)
        overflow_harness = build_overflow_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc1 = compile_and_run(w_harness, "samovar-nbk-auto-entry-w-", True)
    rc1b = compile_and_run(tail_harness, "samovar-nbk-auto-entry-tail-", True)
    rc2 = compile_and_run(commit_harness, "samovar-nbk-auto-entry-commit-", True)
    rc3 = compile_and_run(overflow_harness, "samovar-nbk-auto-entry-overflow-", True)
    if rc1 or rc1b or rc2 or rc3:
        return 1

    mutations = (
        ("W-branch: optimumEntry gate disabled", mutate_w_optimum_entry_gate, build_w_harness, "samovar-nbk-auto-entry-w-mut-"),
        ("tail: P8 finish branch moved above W-branch", mutate_p8_before_w, build_tail_harness, "samovar-nbk-auto-entry-tail-mut-"),
        ("commit: keepsOptimum guard inverted", mutate_commit_keeps_optimum, build_commit_harness, "samovar-nbk-auto-entry-commit-mut-"),
        ("overflow: opt_found guard inverted", mutate_opt_found_gate, build_overflow_harness, "samovar-nbk-auto-entry-overflow-mut-"),
    )
    for label, mutate, build, prefix in mutations:
        try:
            mutated_source = mutate(nbk_source)
        except ValueError as error:
            print(f"FAIL: {label}: {error}", file=sys.stderr)
            return 1
        if mutated_source == nbk_source:
            print(f"FAIL: mutation had no effect: {label}", file=sys.stderr)
            return 1
        mutated_harness = build(mutated_source)
        if compile_and_run(mutated_harness, prefix, False) == 0:
            print(f"FAIL: mutation survived (expected failure): {label}", file=sys.stderr)
            return 1

    print("nbk auto work entry (optimum) behaviour checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
