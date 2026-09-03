#!/usr/bin/env python3
"""Поведенческая проверка [Ремонт-2026-09-02 П7 + П8]:

П7: раньше повторное нажатие "Включить нагрев" во время nbk_safe_waiting
(насос/нагрев ещё не подтвердили останов) просто тихо возвращалось из
nbk_proc() и НИЧЕГО не повторяло - ни повторной попытки SetSpeed(0)/
set_power(false,...), ни сообщения оператору. Теперь на каждый такой такт
делается ОДНА попытка довести останов до конца, а если не получилось -
явная отмена попытки старта с причиной (насос vs нагрев).

П8: run_nbk_program() при активном nbk_safe_waiting и переходе на num>0
(любая строка после нулевой) обязан завершить сессию через nbk_finish(),
а НЕ провалиться в старую ветку "нагрев выключен -> nbk_cancel_program_start",
которая писала неверное сообщение и не сбрасывала состояние сессии.

Оба харнесса вытаскивают РЕАЛЬНЫЙ текст веток через extract_braced_block_after/
срез по индексам - логика не копируется руками.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

P7_ANCHOR = "if (nbk_safe_waiting) {"
P8_ANCHOR_FINISH = "if (nbk_safe_waiting && num > 0) {"
P8_ANCHOR_LEGACY = "if (num > 0 && !PowerOn) {"

P7_MUTATION_ANCHOR = """    if (startval == SAMOVAR_STARTVAL_NBK_START &&
        nbk_safe_wait_result != ACTUATOR_COMMAND_APPLIED &&
        !power_transition_active()) {"""

COMMON_PRELUDE = r'''
#include <cstdint>
#include <iostream>
#include <string>

enum { SAMOVAR_STARTVAL_NBK_START = 4000 };
enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
  String(int value) : value_(std::to_string(value)) {}
  String operator+(const String& rhs) const { return String(value_ + rhs.value_); }
  bool contains(const char* needle) const { return value_.find(needle) != std::string::npos; }
 private:
  explicit String(const std::string& value) : value_(value) {}
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(lhs) + rhs;
}

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
'''

P7_HARNESS = r'''
#include <vector>

static volatile int16_t startval = SAMOVAR_STARTVAL_NBK_START;
static bool PowerOn = false;
static bool nbk_safe_waiting = true;
static bool nbk_safe_wait_feed_stopped = false;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;

// [зависимость от состояния] очередь результатов на каждый вызов
// tick_nbk_safe_wait() - реальная функция опрашивает насос/нагрев и
// перезаписывает nbk_safe_wait_result, здесь это управляемая модель.
static std::vector<ActuatorCommandResult> tickQueue;
static size_t tickIndex = 0;
static int tickCalls = 0;
void tick_nbk_safe_wait() {
  tickCalls++;
  if (tickIndex < tickQueue.size()) {
    nbk_safe_wait_result = tickQueue[tickIndex];
    tickIndex++;
  }
}

static bool powerTransitionActive = false;
bool power_transition_active() { return powerTransitionActive; }

static int setSpeedCalls = 0;
static ActuatorCommandResult setSpeedResult = ACTUATOR_COMMAND_FAILED;
ActuatorCommandResult SetSpeed(float) {
  setSpeedCalls++;
  return setSpeedResult;
}

static int setPowerCalls = 0;
void set_power(bool, bool) { setPowerCalls++; }

static int cancelCalls = 0;
static String lastCancelReason;
void nbk_cancel_program_start(const String& message) {
  cancelCalls++;
  lastCancelReason = message;
}

@BODY@

static void reset_fixture() {
  startval = SAMOVAR_STARTVAL_NBK_START;
  nbk_safe_waiting = true;
  nbk_safe_wait_feed_stopped = false;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  tickQueue.clear();
  tickIndex = 0;
  tickCalls = 0;
  powerTransitionActive = false;
  setSpeedCalls = 0;
  setSpeedResult = ACTUATOR_COMMAND_FAILED;
  setPowerCalls = 0;
  cancelCalls = 0;
  lastCancelReason = String("");
}

// Одна симуляция такта nbk_proc() при активном safe-waiting. Каждый вызов -
// это ОДНО "нажатие" (nbk_cancel_program_start в реальной прошивке уводит
// startval из SAMOVAR_STARTVAL_NBK_START; здесь это выставляет тест, чтобы
// смоделировать следующее отдельное нажатие).
static void press() { fake_safe_wait_tick(); }

// Сценарий A: насос не подтверждает останов (SetSpeed всегда FAILED) - два
// отдельных нажатия обязаны дать ДВЕ попытки SetSpeed(0) и ДВЕ отмены с
// причиной "насос не подтвердил останов".
static void test_pump_never_confirms() {
  reset_fixture();
  setSpeedResult = ACTUATOR_COMMAND_FAILED;

  tickQueue = {ACTUATOR_COMMAND_FAILED, ACTUATOR_COMMAND_FAILED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START;
  press();
  check(setSpeedCalls == 1, "П7 A: первое нажатие обязано вызвать SetSpeed(0) ровно один раз");
  check(cancelCalls == 1, "П7 A: неподтверждённый останов обязан дать одну отмену");
  check(lastCancelReason.contains("насос не подтвердил останов"),
        "П7 A: причина отмены обязана указывать на насос, если он не подтвердил останов");
  check(setPowerCalls == 0, "П7 A: при уже выключенном нагреве повторный set_power(false) не нужен");
  check(nbk_safe_waiting, "П7 A: отмена не должна снимать флаг ожидания");

  tickQueue = {ACTUATOR_COMMAND_FAILED, ACTUATOR_COMMAND_FAILED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START; // повторное нажатие оператора
  press();
  check(setSpeedCalls == 2, "П7 A: второе нажатие обязано ПОВТОРИТЬ попытку SetSpeed(0) (это и есть суть П7)");
  check(cancelCalls == 2, "П7 A: второе нажатие тоже обязано дать отмену");
}

// Сценарий B: насос останавливается сразу (feed_stopped защёлкивается), но
// нагрев ещё не подтверждён - причина отмены обязана переключиться на
// нагрев, а повторный SetSpeed(0) на втором нажатии уже НЕ нужен (защёлка).
static void test_heater_still_on() {
  reset_fixture();
  setSpeedResult = ACTUATOR_COMMAND_APPLIED;

  tickQueue = {ACTUATOR_COMMAND_FAILED, ACTUATOR_COMMAND_FAILED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START;
  press();
  check(setSpeedCalls == 1, "П7 B: первое нажатие вызывает SetSpeed(0) один раз");
  check(nbk_safe_wait_feed_stopped, "П7 B: успешный SetSpeed(0) обязан защёлкнуть feed_stopped");
  check(cancelCalls == 1, "П7 B: незавершённый останов нагрева тоже обязан дать отмену");
  check(lastCancelReason.contains("нагрев ещё не выключен"),
        "П7 B: причина отмены обязана указывать на нагрев, если насос уже подтверждён");

  tickQueue = {ACTUATOR_COMMAND_FAILED, ACTUATOR_COMMAND_FAILED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START;
  press();
  check(setSpeedCalls == 1, "П7 B: второе нажатие НЕ обязано повторять SetSpeed(0) - насос уже подтверждён");
  check(cancelCalls == 2, "П7 B: второе нажатие снова отменяется, пока нагрев не выключен");
  check(lastCancelReason.contains("нагрев ещё не выключен"), "П7 B: причина остаётся про нагрев");
}

// Сценарий C: на повторной попытке (второй tick внутри ОДНОГО нажатия) всё
// подтверждается - отмены быть не должно, ожидание снимается сразу.
static void test_retry_succeeds_within_one_press() {
  reset_fixture();
  setSpeedResult = ACTUATOR_COMMAND_APPLIED;
  tickQueue = {ACTUATOR_COMMAND_FAILED, ACTUATOR_COMMAND_APPLIED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START;
  press();
  check(setSpeedCalls == 1, "П7 C: ровно одна попытка SetSpeed(0) внутри нажатия");
  check(cancelCalls == 0, "П7 C: успешный повтор не должен отменять старт");
  check(!nbk_safe_waiting, "П7 C: успешный повтор обязан снять флаг ожидания");
  check(!nbk_safe_wait_feed_stopped, "П7 C: успешный выход из ожидания обязан сбросить feed_stopped");
}

// Сценарий D: результат уже APPLIED на первом же тике - ретрай не нужен
// вообще, SetSpeed(0) не вызывается.
static void test_already_applied_no_retry() {
  reset_fixture();
  tickQueue = {ACTUATOR_COMMAND_APPLIED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START;
  press();
  check(setSpeedCalls == 0, "П7 D: если насос/нагрев уже подтверждены - повторной команды быть не должно");
  check(cancelCalls == 0, "П7 D: уже подтверждённое ожидание не отменяется");
  check(!nbk_safe_waiting, "П7 D: флаг ожидания обязан сняться");
}

// Сценарий E: идёт активный переходный процесс (power_transition_active) -
// ретрай обязан быть отложен, а не заспамлен командами поверх перехода.
static void test_skips_retry_during_transition() {
  reset_fixture();
  powerTransitionActive = true;
  tickQueue = {ACTUATOR_COMMAND_FAILED, ACTUATOR_COMMAND_FAILED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START;
  press();
  check(setSpeedCalls == 0, "П7 E: во время активного перехода повторная команда не отправляется");
  check(cancelCalls == 0, "П7 E: во время активного перехода отмены быть не должно - просто ждём");
  check(nbk_safe_waiting, "П7 E: ожидание обязано остаться активным");
}

// Сценарий F: нагрев формально ещё включён (PowerOn) - повторная попытка
// обязана переотправить set_power(false, false), а не только SetSpeed(0).
// Два нажатия - две повторные команды нагреву.
static void test_heater_retry_when_power_on() {
  reset_fixture();
  PowerOn = true;
  setSpeedResult = ACTUATOR_COMMAND_APPLIED;
  tickQueue = {ACTUATOR_COMMAND_FAILED, ACTUATOR_COMMAND_FAILED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START;
  press();
  check(setPowerCalls == 1, "П7 F: при включённом нагреве повторная попытка обязана вызвать set_power(false,false) ровно один раз");
  check(cancelCalls == 1, "П7 F: незавершённый останов обязан дать отмену");
  check(lastCancelReason.contains("нагрев ещё не выключен"), "П7 F: причина отмены - нагрев");

  tickQueue = {ACTUATOR_COMMAND_FAILED, ACTUATOR_COMMAND_FAILED};
  tickIndex = 0;
  startval = SAMOVAR_STARTVAL_NBK_START;
  press();
  check(setPowerCalls == 2, "П7 F: второе нажатие обязано ПОВТОРИТЬ set_power(false,false)");
  PowerOn = false;
}

int main() {
  test_pump_never_confirms();
  test_heater_still_on();
  test_retry_succeeds_within_one_press();
  test_already_applied_no_retry();
  test_skips_retry_during_transition();
  test_heater_retry_when_power_on();
  if (failures != 0) return 1;
  std::cout << "nbk safe-wait restart retry behaviour checks passed\n";
  return 0;
}
'''

P8_HARNESS = r'''
static bool nbk_safe_waiting = false;
static bool PowerOn = false;
// Нагрев ещё выключается после входа в safe wait: заглушка читает управляемое
// состояние - сценарий 4 переключает его, чтобы поймать порядок веток.
// Не static: мутант со старым порядком веток вырезает вызов из фрагмента, и
// -Werror=unused-function убил бы его на компиляции вместо содержательного assert.
static bool powerTransitionActive = false;
bool power_transition_active() { return powerTransitionActive; }

static int finishCalls = 0;
void nbk_finish() { finishCalls++; }

static int sendMsgCalls = 0;
static int notifyMsgCalls = 0;
void SendMsg(const String&, int type) {
  sendMsgCalls++;
  if (type == NOTIFY_MSG) notifyMsgCalls++;
}

static int cancelCalls = 0;
static String lastCancelText;
void nbk_cancel_program_start(const String& message) {
  cancelCalls++;
  lastCancelText = message;
}

static bool fellThrough = false;

void fake_run_nbk_program_tail(uint8_t num) {
@BODY@
  fellThrough = true;
}

static void reset_fixture() {
  nbk_safe_waiting = false;
  PowerOn = false;
  powerTransitionActive = false;
  finishCalls = 0;
  sendMsgCalls = 0;
  notifyMsgCalls = 0;
  cancelCalls = 0;
  lastCancelText = String("");
  fellThrough = false;
}

// Случай 1: активное safe-waiting и переход на строку >0 обязан завершить
// сессию через nbk_finish(), а не свалиться в старую ветку "нагрев выключен".
static void test_safe_waiting_finishes_session() {
  reset_fixture();
  nbk_safe_waiting = true;
  PowerOn = true; // даже если нагрев формально включён - должно быть неважно
  fake_run_nbk_program_tail(2);
  check(finishCalls == 1, "П8: активное safe-waiting при num>0 обязано вызвать nbk_finish() ровно один раз");
  check(notifyMsgCalls == 1, "П8: завершение по safe-waiting обязано дать одно уведомление оператору");
  check(cancelCalls == 0, "П8: старая ветка nbk_cancel_program_start не должна вызываться при safe-waiting");
  check(!fellThrough, "П8: ветка safe-waiting обязана завершиться return, не проваливаясь дальше");
}

// Случай 2: без safe-waiting и с выключенным нагревом - старый путь (anchor
// B) обязан отработать как раньше: отмена перехода строки с текстом.
static void test_legacy_path_without_safe_waiting() {
  reset_fixture();
  nbk_safe_waiting = false;
  PowerOn = false;
  fake_run_nbk_program_tail(2);
  check(finishCalls == 0, "П8 регресс: без safe-waiting nbk_finish() вызываться не должен");
  check(cancelCalls == 1, "П8 регресс: старая ветка 'нагрев выключен' обязана продолжать работать");
  check(lastCancelText.contains("строке №3"), "П8 регресс: отмена обязана называть номер строки num+1");
  check(!fellThrough, "П8 регресс: ветка отмены обязана завершиться return");
}

// Случай 3: ни safe-waiting, ни выключенного нагрева - обе ветки должны
// быть пропущены, выполнение проваливается дальше (к нормальному переходу).
static void test_neither_branch_triggers() {
  reset_fixture();
  nbk_safe_waiting = false;
  PowerOn = true;
  fake_run_nbk_program_tail(2);
  check(finishCalls == 0, "П8: без safe-waiting nbk_finish() не вызывается");
  check(cancelCalls == 0, "П8: при включённом нагреве старая ветка отмены не должна срабатывать");
  check(fellThrough, "П8: обе ветки должны быть пропущены и выполнение обязано пойти дальше");
}

// Случай 4: safe-waiting, нагрев уже снят, но регулятор ещё в переходе выключения.
// Ветка П8 стоит ДО проверки power_transition_active(): нажатие обязано завершить
// сессию, а не уйти в "Выключение нагрева ещё не завершено. Старт отменён".
static void test_safe_waiting_wins_over_power_transition() {
  reset_fixture();
  nbk_safe_waiting = true;
  PowerOn = false;
  powerTransitionActive = true;
  fake_run_nbk_program_tail(1);
  check(finishCalls == 1, "П8: safe-waiting во время выключения нагрева обязано завершить сессию через nbk_finish()");
  check(cancelCalls == 0, "П8: ветка 'выключение нагрева ещё не завершено' не должна перехватывать safe-waiting");
  check(!fellThrough, "П8: ветка safe-waiting при переходе нагрева обязана завершиться return");
}

// Случай 5: без safe-waiting переход нагрева по-прежнему отменяет старт (регресс).
static void test_power_transition_cancels_without_safe_waiting() {
  reset_fixture();
  nbk_safe_waiting = false;
  PowerOn = false;
  powerTransitionActive = true;
  fake_run_nbk_program_tail(1);
  check(finishCalls == 0, "П8 регресс: без safe-waiting переход нагрева не должен завершать сессию");
  check(cancelCalls == 1, "П8 регресс: переход нагрева без safe-waiting обязан отменить старт");
  check(lastCancelText.contains("ещё не завершено"), "П8 регресс: отмена при переходе нагрева обязана назвать причину");
}

int main() {
  test_safe_waiting_finishes_session();
  test_legacy_path_without_safe_waiting();
  test_neither_branch_triggers();
  test_safe_waiting_wins_over_power_transition();
  test_power_transition_cancels_without_safe_waiting();
  if (failures != 0) return 1;
  std::cout << "nbk safe-wait run_nbk_program tail behaviour checks passed\n";
  return 0;
}
'''


def build_p7_harness(nbk_source: str) -> str:
    body, _ = extract_braced_block_after(nbk_source, P7_ANCHOR)
    wrapped = f"static void fake_safe_wait_tick() {{{body}}}"
    return COMMON_PRELUDE + P7_HARNESS.replace("@BODY@", wrapped)


def build_p8_harness(nbk_source: str, finish_anchor: str = P8_ANCHOR_FINISH) -> str:
    start = nbk_source.index(finish_anchor)
    _, end_legacy = extract_braced_block_after(nbk_source, P8_ANCHOR_LEGACY, offset=start)
    combined = nbk_source[start:end_legacy]
    return COMMON_PRELUDE + P8_HARNESS.replace("@BODY@", combined)


def compile_and_run(harness: str, emit: bool, tag: str) -> int:
    with tempfile.TemporaryDirectory(prefix=f"samovar-nbk-safe-wait-{tag}-") as temp_dir:
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


def mutate_drop_retry(source: str) -> str:
    # Возвращает старое поведение П7: повторная попытка останова никогда не
    # предпринимается - должно сломать сценарии A и B (нет отмены/повтора).
    if P7_MUTATION_ANCHOR not in source:
        raise ValueError("mutation anchor missing: safe-wait retry condition")
    return source.replace(P7_MUTATION_ANCHOR, "    if (false) {", 1)


P7_HEATER_RETRY_ANCHOR = "      if (PowerOn) set_power(false, false);"


def mutate_drop_heater_retry(source: str) -> str:
    # [Ревью R4] вторая половина повторной попытки - нагрев - обязана быть покрыта
    # отдельно от SetSpeed(0): без неё сценарий F не увидит set_power.
    if P7_HEATER_RETRY_ANCHOR not in source:
        raise ValueError("mutation anchor missing: safe-wait heater retry")
    return source.replace(P7_HEATER_RETRY_ANCHOR, "      (void)PowerOn;", 1)


def mutate_drop_finish_branch(source: str) -> str:
    # Отключает ветку П8 (nbk_finish при safe-waiting) - должно сломать
    # сценарий 1 (finishCalls останется 0, выполнение провалится в anchor B).
    if P8_ANCHOR_FINISH not in source:
        raise ValueError("mutation anchor missing: safe-waiting finish branch")
    return source.replace(P8_ANCHOR_FINISH, "if (false && num > 0) {", 1)


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        p7_harness = build_p7_harness(nbk_source)
        p8_harness = build_p8_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(p7_harness, True, "p7") != 0:
        return 1
    if compile_and_run(p8_harness, True, "p8") != 0:
        return 1

    try:
        mutated_p7 = mutate_drop_retry(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated_p7 == nbk_source:
        print("FAIL: П7 mutation had no effect", file=sys.stderr)
        return 1
    mutated_p7_harness = build_p7_harness(mutated_p7)
    if compile_and_run(mutated_p7_harness, False, "p7-mut") == 0:
        print("FAIL: П7 mutation survived (expected failure): retry disabled", file=sys.stderr)
        return 1

    try:
        mutated_p7_heater = mutate_drop_heater_retry(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if compile_and_run(build_p7_harness(mutated_p7_heater), False, "p7-heater-mut") == 0:
        print("FAIL: П7 mutation survived (expected failure): heater retry disabled", file=sys.stderr)
        return 1

    try:
        mutated_p8 = mutate_drop_finish_branch(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated_p8 == nbk_source:
        print("FAIL: П8 mutation had no effect", file=sys.stderr)
        return 1
    mutated_p8_harness = build_p8_harness(mutated_p8, finish_anchor="if (false && num > 0) {")
    if compile_and_run(mutated_p8_harness, False, "p8-mut") == 0:
        print("FAIL: П8 mutation survived (expected failure): finish branch disabled", file=sys.stderr)
        return 1

    print("nbk safe-wait restart checks (П7 + П8, behaviour + mutations) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
