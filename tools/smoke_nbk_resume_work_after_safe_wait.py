#!/usr/bin/env python3
"""Поведенческая проверка [П9]: возобновление Работы НБК после безопасного
ожидания, вызванного сбоем подтверждения приводов ПОСРЕДИ Работы.

Работа - последняя строка программы НБК. До этой правки run_nbk_program(
ProgramNum+1, true) (именно так работает кнопка "Следующая программа") на
последней строке уходил прямиком в nbk_finish(), теряя весь накопленный
nbk_Mo/nbk_Po при одном неподтверждённом ответе привода. Теперь перед этой
проверкой добавлен перехват: если ожидание безопасности активно, а ТЕКУЩАЯ
(не следующая) строка - Работа, кнопка "Следующая программа" трактуется как
запрос на возобновление и уходит в nbk_resume_work_after_safe_wait(), которая
продолжает ЖИВЫМИ nbk_Mo/nbk_Po (а не program[].Power/Speed).

Часть 1: реальный фрагмент-перехватчик из run_nbk_program() (nbk.h) -
извлекается по тексту условия, оборачивается в тестовую функцию, чтобы
убедиться, что он срабатывает ТОЛЬКО в нужном сценарии (не путает обычный
рестарт сессии num==0 и не трогает переход из не-W строки).

Часть 2: реальное тело nbk_resume_work_after_safe_wait() (nbk.h) -
извлекается через extract_function_body, проверяется на всех
предохранителях (авария, невалидный snapshot, невалидные датчики, команда
приводов уже в полёте, PENDING/не-APPLIED результат безопасного ожидания,
нагрев не включился) и на успешном возобновлении живыми Mo/Po.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

GATE_ANCHOR = "if (nbk_safe_waiting && num == uint16_t(ProgramNum) + 1 &&"
RESUME_SIGNATURE = "inline void nbk_resume_work_after_safe_wait() {"
# [Дефект 2, ПИНИМ] Реальный фрагмент handle_nbk_stage_work(), обрабатывающий
# паузу после захлёба - используется, чтобы доказать, что после сброса
# состояния паузы в nbk_resume_work_after_safe_wait() следующий тик НЕ входит
# повторно в ветку nbk_work_pause_stage==1 (не шлёт повторную команду/сообщение).
PAUSE_ANCHOR = "if (nbk_work_in_pause) {"

GATE_HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

struct ProgramRow { char WType; };
static const int PROGRAM_SLOTS = 8;
static ProgramRow program[PROGRAM_SLOTS];
static uint8_t ProgramNum = 0;
static uint8_t ProgramLen = 0;
static bool nbk_safe_waiting = false;

static bool resumeCalled = false;
void nbk_resume_work_after_safe_wait() { resumeCalled = true; }

static bool fellThrough = false;
static void fake_run_nbk_program(uint8_t num) {
  resumeCalled = false;
  fellThrough = false;
@GATE_FRAGMENT@
  fellThrough = true;
}

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- Основной сценарий: ожидание активно, текущая строка - Работа,
  // запрошен переход на следующую (несуществующую) строку -> возобновление.
  for (int i = 0; i < PROGRAM_SLOTS; i++) program[i].WType = 'H';
  ProgramNum = 3;
  ProgramLen = 4;
  program[3].WType = 'W';
  nbk_safe_waiting = true;
  fake_run_nbk_program(4);
  check(resumeCalled, "РЕГРЕСС: 'Следующая программа' во время ожидания на строке W обязана возобновлять Работу");
  check(!fellThrough, "перехват возобновления обязан return'ить, не проваливаясь дальше к nbk_finish()");

  // --- Ожидание НЕ активно - обычный переход на следующую (несуществующую)
  // строку, поведение (падение в nbk_finish() ниже по коду) не должно
  // подменяться. ---
  nbk_safe_waiting = false;
  fake_run_nbk_program(4);
  check(!resumeCalled, "без активного ожидания перехват не должен срабатывать");
  check(fellThrough, "без активного ожидания фрагмент обязан провалиться дальше");

  // --- Ожидание активно, но num - это НЕ 'следующая после текущей' (например,
  // num==0 - рестарт сессии). Не должно перехватываться как возобновление -
  // иначе рестарт после отказа резолва станет невозможен. ---
  nbk_safe_waiting = true;
  fake_run_nbk_program(0);
  check(!resumeCalled, "рестарт сессии (num==0) не должен приниматься за возобновление Работы");
  check(fellThrough, "рестарт сессии обязан провалиться дальше по обычному пути");

  // --- Ожидание активно, num==ProgramNum+1, но ТЕКУЩАЯ строка - НЕ Работа
  // (например, Оптимизация) - это уже существующий путь перехода, его нельзя
  // перехватывать. ---
  program[3].WType = 'O';
  nbk_safe_waiting = true;
  fake_run_nbk_program(4);
  check(!resumeCalled, "переход из строки, отличной от W, не должен перехватываться как возобновление");
  check(fellThrough, "переход из не-W строки обязан провалиться дальше по обычному пути");

  if (failures != 0) return 1;
  std::cout << "nbk resume-work gate behaviour checks passed\n";
  return 0;
}
'''

RESUME_HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum ActuatorCommandResult {
  ACTUATOR_COMMAND_FAILED,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_ACCEPTED,
};
enum NbkActuatorDeadlineTarget { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};

// --- Управляемые тестом заглушки предохранителей ---
static bool test_latched = false;
bool heater_safety_latched() { return test_latched; }

struct NbkSessionConfig { bool valid; };
static NbkSessionConfig nbkSessionConfig = {true};

static int sensorsValidCalls = 0;
static char sensorsValidArg = 0;
static bool test_sensorsValid = true;
bool nbk_stage_sensors_valid(char wtype) {
  sensorsValidCalls++;
  sensorsValidArg = wtype;
  return test_sensorsValid;
}

struct NbkActuatorCommandState { bool active; };
static NbkActuatorCommandState nbkActuatorCommand = {false};

static int tickSafeWaitCalls = 0;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
void tick_nbk_safe_wait() { tickSafeWaitCalls++; }

static int setPowerCalls = 0;
static bool test_setPowerTurnsOn = true;
bool PowerOn = false;
void set_power(bool on) {
  setPowerCalls++;
  if (on) PowerOn = test_setPowerTurnsOn;
}

bool nbk_safe_waiting = true;
bool nbk_safe_wait_feed_stopped = true;

static int enterSafeWaitCalls = 0;
static std::string lastEnterSafeWaitReason;
void nbk_enter_safe_wait(const String& reason) {
  enterSafeWaitCalls++;
  lastEnterSafeWaitReason = reason.value();
  nbk_safe_waiting = true;
}

static int scheduleCalls = 0;
static float lastCandidateM = -1;
static float lastCandidateP = -1;
static bool test_scheduleSucceeds = true;
bool nbk_schedule_actuator_command(float candidateM, float candidateP,
                                    NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  lastCandidateM = candidateM;
  lastCandidateP = candidateP;
  return test_scheduleSucceeds;
}

static int sendMsgCalls = 0;
void SendMsg(const String&, int) { sendMsgCalls++; }
void SendMsg(const char*, int) { sendMsgCalls++; }

uint32_t nbk_column_inertia = 180;
uint16_t nbk_opt_iter = 0;
float nbk_Mo = 0;
float nbk_Po = 0;

// [Дефект 2] Состояние паузы по захлёбу - nbk_resume_work_after_safe_wait()
// теперь обязана сбрасывать его при успешном возобновлении (иначе
// handle_nbk_stage_work() на следующем тике снова войдёт в ветку
// nbk_work_pause_stage==1 и повторно отправит уже отправленную команду).
bool nbk_work_in_pause = false;
uint8_t nbk_work_pause_stage = 0;
bool nbk_overflow_happened = false;
bool nbk_pause_overflow_repeat_latched = false;

@RESUME_BODY@

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  test_latched = false;
  nbkSessionConfig.valid = true;
  test_sensorsValid = true;
  sensorsValidCalls = 0;
  nbkActuatorCommand.active = false;
  tickSafeWaitCalls = 0;
  nbk_safe_wait_result = ACTUATOR_COMMAND_APPLIED;
  setPowerCalls = 0;
  test_setPowerTurnsOn = true;
  PowerOn = false;
  nbk_safe_waiting = true;
  nbk_safe_wait_feed_stopped = true;
  enterSafeWaitCalls = 0;
  scheduleCalls = 0;
  lastCandidateM = -1;
  lastCandidateP = -1;
  test_scheduleSucceeds = true;
  sendMsgCalls = 0;
  nbk_Mo = 777.5f;
  nbk_Po = 3.25f;
  // "Застрявшее" состояние паузы, как в сценарии из код-ревью: захлёб в
  // Работе вызвал nbk_work_pause_stage=1, nbk_overflow_happened=true,
  // а прежде принятая команда снижения так и не подтвердилась (safe-wait).
  nbk_work_in_pause = true;
  nbk_work_pause_stage = 1;
  nbk_overflow_happened = true;
  nbk_pause_overflow_repeat_latched = true;
}

int main() {
  // --- Авария зафиксирована - остаёмся в ожидании, ничего не трогаем. ---
  reset_fixture();
  test_latched = true;
  nbk_resume_work_after_safe_wait();
  check(scheduleCalls == 0, "авария обязана заблокировать возобновление");
  check(setPowerCalls == 0, "авария не должна пытаться включать нагрев");
  check(nbk_safe_waiting, "после отказа по аварии остаёмся в safe-wait");

  // --- Невалидный snapshot конфигурации сессии. ---
  reset_fixture();
  nbkSessionConfig.valid = false;
  nbk_resume_work_after_safe_wait();
  check(scheduleCalls == 0, "невалидный snapshot обязан заблокировать возобновление");

  // --- Датчики стадии Работы невалидны. ---
  reset_fixture();
  test_sensorsValid = false;
  nbk_resume_work_after_safe_wait();
  check(scheduleCalls == 0, "невалидные датчики обязаны заблокировать возобновление");
  check(sensorsValidCalls == 1 && sensorsValidArg == 'W', "датчики обязаны проверяться для стадии W");

  // --- Команда приводов уже в полёте - не мешаем ей, не шлём вторую. ---
  reset_fixture();
  nbkActuatorCommand.active = true;
  nbk_resume_work_after_safe_wait();
  check(scheduleCalls == 0, "команда приводов в полёте обязана заблокировать повторное возобновление");

  // --- Безопасное ожидание ещё не завершено (PENDING) - ждём дальше. ---
  reset_fixture();
  nbk_safe_wait_result = ACTUATOR_COMMAND_PENDING;
  nbk_resume_work_after_safe_wait();
  check(scheduleCalls == 0 && setPowerCalls == 0, "PENDING обязан просто подождать, не включая нагрев");

  // --- Останов насоса не подтверждён (FAILED) - явная авария, не пытаемся включать. ---
  reset_fixture();
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  nbk_resume_work_after_safe_wait();
  check(scheduleCalls == 0 && setPowerCalls == 0, "неподтверждённый останов насоса не должен пытаться включать нагрев");

  // --- Нагрев не включился по команде set_power(true) - обратно в safe-wait
  // с понятной причиной, ProgramNum/Mo/Po не теряем (их тут не трогаем). ---
  reset_fixture();
  test_setPowerTurnsOn = false;
  nbk_resume_work_after_safe_wait();
  check(setPowerCalls == 1, "обязана быть попытка включить нагрев");
  check(scheduleCalls == 0, "без включённого нагрева команда приводам не должна уходить");
  check(enterSafeWaitCalls == 1, "неудачное включение нагрева обязано вернуть в safe-wait с причиной");

  // --- Успех: причина устранена, нагрев включается, приводам уходят ЖИВЫЕ
  // nbk_Mo/nbk_Po (регресс-точка П9 - не program[].Power/Speed). ---
  reset_fixture();
  nbk_Mo = 642.0f;
  nbk_Po = 1.75f;
  nbk_resume_work_after_safe_wait();
  check(setPowerCalls == 1, "успешное возобновление обязано включить нагрев");
  check(scheduleCalls == 1, "успешное возобновление обязано отправить ровно одну команду приводам");
  check(lastCandidateM == 642.0f, "команда приводам обязана использовать живой nbk_Mo, а не program[].Power");
  check(lastCandidateP == 1.75f, "команда приводам обязана использовать живой nbk_Po, а не program[].Speed");
  check(!nbk_safe_waiting, "успешное возобновление обязано снять флаг ожидания");
  // --- [Дефект 2] Успешное возобновление обязано разрешить "застрявшее"
  // состояние паузы (а не оставить его как было в момент срыва в safe-wait) -
  // иначе следующий тик handle_nbk_stage_work() снова войдёт в ветку
  // nbk_work_pause_stage==1 и повторно отправит ту же команду. ---
  check(!nbk_work_in_pause, "РЕГРЕСС [Дефект 2]: успешное возобновление обязано снять nbk_work_in_pause");
  check(nbk_work_pause_stage == 0, "РЕГРЕСС [Дефект 2]: успешное возобновление обязано обнулить nbk_work_pause_stage");
  check(!nbk_overflow_happened, "РЕГРЕСС [Дефект 2]: успешное возобновление обязано сбросить nbk_overflow_happened");
  check(!nbk_pause_overflow_repeat_latched, "РЕГРЕСС [Дефект 2]: успешное возобновление обязано сбросить nbk_pause_overflow_repeat_latched");

  // --- Приводы не приняли параметры - назад в safe-wait, попытка не теряется молча. ---
  reset_fixture();
  test_scheduleSucceeds = false;
  nbk_resume_work_after_safe_wait();
  check(scheduleCalls == 1, "попытка отправки команды обязана быть сделана");
  check(enterSafeWaitCalls == 1, "отказ приводов принять команду обязан вернуть в safe-wait");

  if (failures != 0) return 1;
  std::cout << "nbk resume-work-after-safe-wait behaviour checks passed\n";
  return 0;
}
'''


PAUSE_HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum NbkActuatorDeadlineTarget { NBK_ACTUATOR_NO_DEADLINE, NBK_ACTUATOR_OPTIMIZATION_DEADLINE, NBK_ACTUATOR_WORK_DEADLINE };

#define NBK_MULT_PAUSE_OVERFLOW 2

// Минимальная замена Arduino String - реальный блок склеивает текст сообщения
// через "..." + String(...) + "..." и использует msg.reserve()/msg +=.
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

static String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

bool nbk_work_in_pause = false;
uint8_t nbk_work_pause_stage = 0;
bool nbk_overflow_happened = false;
bool nbk_pause_overflow_repeat_latched = false;
bool nbk_work_entry_overflow_pending = false;
uint32_t nbk_work_next_time = 0;
uint16_t nbk_column_inertia = 180;
uint16_t nbk_opt_iter = 0;
float nbk_Mo = 100.0f;
float nbk_Po = 5.0f;
float nbk_P = 5.0f;
float nbk_dM = 10.0f;
float nbk_dP = 1.0f;

static bool test_overflow = false;
bool overflow() { return test_overflow; }
const char* nbk_overflow_source() { return "ДЗ"; }

float fromPower(float value) { return value; }
// [T14 п.1/п.8] Нижняя граница - toPower() тождественна, unit-конвертация
// проверяется отдельно (smoke_nbk_session_config.py); важен сам факт клэмпа.
float power_work_mode_threshold() { return 40.0f; }
float toPower(float value) { return value; }
static float max(float left, float right) { return left > right ? left : right; }

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t safety_deadline_after(uint32_t now, uint32_t ms) { return now + ms; }
bool safety_deadline_expired(uint32_t, uint32_t) { return true; }

static int scheduleCalls = 0;
bool nbk_schedule_actuator_command(float, float, NbkActuatorDeadlineTarget, uint32_t, uint16_t) {
  scheduleCalls++;
  return true;
}

static int enterSafeWaitCalls = 0;
void nbk_enter_safe_wait(const String&) { enterSafeWaitCalls++; }

static int sendMsgCalls = 0;
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

static void run_pause_tick() {
  if (nbk_work_in_pause) {
@PAUSE_BLOCK@
  }
}

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- Положительный контроль: "застрявшее" состояние паузы (как оно и
  // остаётся БЕЗ фикса Дефекта 2) обязано СНОВА войти в ветку
  // nbk_work_pause_stage==1 и повторно отправить команду/сообщение -
  // доказывает, что харнесс вообще способен различить повтор. ---
  nbk_work_in_pause = true;
  nbk_work_pause_stage = 1;
  nbk_overflow_happened = true;
  test_overflow = false;
  scheduleCalls = 0;
  sendMsgCalls = 0;
  run_pause_tick();
  check(scheduleCalls == 1, "sanity: застрявший stage==1 обязан повторно слать команду приводам");
  check(sendMsgCalls == 1, "sanity: застрявший stage==1 обязан повторно слать сообщение о возобновлении");

  // --- [Дефект 2, ПИНИМ] Состояние ПОСЛЕ успешного
  // nbk_resume_work_after_safe_wait() (все четыре флага паузы сброшены) -
  // следующий тик обязан быть ПОЛНЫМ no-op: ни команды, ни сообщения. ---
  nbk_work_in_pause = false;
  nbk_work_pause_stage = 0;
  nbk_overflow_happened = false;
  nbk_pause_overflow_repeat_latched = false;
  scheduleCalls = 0;
  sendMsgCalls = 0;
  run_pause_tick();
  check(scheduleCalls == 0, "РЕГРЕСС [Дефект 2]: после сброса паузы тик не должен слать повторную команду приводам");
  check(sendMsgCalls == 0, "РЕГРЕСС [Дефект 2]: после сброса паузы тик не должен слать повторное сообщение");

  if (failures != 0) return 1;
  std::cout << "nbk pause-state no-reentry-after-resume checks passed\n";
  return 0;
}
'''


def build_gate_harness() -> str:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    start = nbk_source.index(GATE_ANCHOR)
    _, end = extract_braced_block_after(nbk_source, GATE_ANCHOR)
    gate_fragment = nbk_source[start:end]
    return GATE_HARNESS_TEMPLATE.replace("@GATE_FRAGMENT@", gate_fragment)


def build_resume_harness() -> str:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    body = extract_function_body(nbk_source, RESUME_SIGNATURE)
    return RESUME_HARNESS_TEMPLATE.replace(
        "@RESUME_BODY@", f"void nbk_resume_work_after_safe_wait() {{{body}}}"
    )


def build_pause_harness() -> str:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    block, _ = extract_braced_block_after(nbk_source, PAUSE_ANCHOR)
    return PAUSE_HARNESS_TEMPLATE.replace("@PAUSE_BLOCK@", block)


def compile_and_run(harness: str, prefix: str) -> int:
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
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        gate_harness = build_gate_harness()
        resume_harness = build_resume_harness()
        pause_harness = build_pause_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc1 = compile_and_run(gate_harness, "samovar-nbk-resume-gate-")
    rc2 = compile_and_run(resume_harness, "samovar-nbk-resume-body-")
    rc3 = compile_and_run(pause_harness, "samovar-nbk-resume-pause-")
    return rc1 or rc2 or rc3


if __name__ == "__main__":
    raise SystemExit(main())
