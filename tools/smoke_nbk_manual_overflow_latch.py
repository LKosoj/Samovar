#!/usr/bin/env python3
"""Поведенческая проверка [Ремонт-2026-09-02 П6]: защёлка захлёба на Ручной
настройке (handle_nbk_stage_manual) держится МИНИМУМ MULT*Ин после снижения,
а не снимается мгновенно по первому же сухому такту.

До этой правки было `else if (manual_overflow && !hasOverflow)
manual_overflow = false;` - один сухой такт датчика (в т.ч. дребезг) сразу
снимал защёлку и возвращал М/П на прежние (уже избыточные для мокрой колонны)
значения, хотя в Оптимизации и Работе такая же пауза выдерживается по времени
(NBK_MULT_PAUSE_OVERFLOW * Ин). Теперь защёлка снимается только когда И сухо,
И прошло время дедлайна.

Харнесс вытаскивает РЕАЛЬНОЕ тело handle_nbk_stage_manual() через
extract_function_body - логика снижения/латча не копируется. Модель времени -
управляемый fakeMillis + РЕАЛЬНЫЕ safety_deadline_after/safety_deadline_expired
(арифметика простая и стабильная, как в smoke_nbk_work_pause_overflow.py).

Второй, отдельный пин (без компиляции C++, только strip_cpp_comments):
run_nbk_program() обязан сбрасывать manual_overflow/nbk_manual_overflow_until
и на новом старте сессии (num==0), и при входе на строку S - иначе латч
предыдущей сессии/строки доживает туда, где датчик мог успеть высохнуть по
другой причине.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "void handle_nbk_stage_manual() {"

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define SAMOVAR_USE_POWER
#define NBK_MULT_PAUSE_OVERFLOW 2
enum { NBK_ACTUATOR_NO_DEADLINE = 0 };
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

class String {
 public:
  String(const char* value = "") : value_(value ? value : "") {}
  String operator+(const String& rhs) const { return String(value_ + rhs.value_); }
 private:
  explicit String(const std::string& value) : value_(value) {}
  std::string value_;
};
String operator+(const char* lhs, const String& rhs) {
  return String(lhs) + rhs;
}

void vTaskDelay(int) {}
#define portTICK_PERIOD_MS 1

static bool overflowFlag = false;
bool overflow() { return overflowFlag; }
const char* nbk_overflow_source() { return "ДЗ"; }

static bool manual_overflow = false;
static uint32_t nbk_manual_overflow_until = 0;
static uint16_t nbk_opt_iter = 0;
static uint16_t nbk_column_inertia = 180;
static float target_power_volt = 0;

static float feedRateStub = 0; // [зависимость от состояния] реальная подача насоса
float nbk_actual_feed_rate() { return feedRateStub; }
float toPower(float value) { return value * 2.0f; }
float power_work_mode_threshold() { return 40.0f; }
static float max(float left, float right) { return left > right ? left : right; }

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t safety_deadline_after(uint32_t now, uint32_t delayMs) { return now + delayMs; }
bool safety_deadline_expired(uint32_t now, uint32_t deadline) {
  return (int32_t)(now - deadline) >= 0;
}

static int scheduleCalls = 0;
static float lastM = -1;
static float lastP = -1;
static bool scheduleShouldSucceed = true;
bool nbk_schedule_actuator_command(float candidateM, float candidateP, int, uint32_t, uint16_t) {
  scheduleCalls++;
  lastM = candidateM;
  lastP = candidateP;
  return scheduleShouldSucceed;
}
static int enterSafeWaitCalls = 0;
void nbk_enter_safe_wait(const String&) { enterSafeWaitCalls++; }
static int sendMsgCalls = 0;
void SendMsg(const String&, int) { sendMsgCalls++; }

// [T1-2026-09-03] обучение потолка давления (не предмет этого теста, но
// теперь вызывается из handle_nbk_stage_manual при первом захлёбе).
void nbk_learn_pressure_ceiling() {}

@BODY@

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(uint16_t inertia, float feedRate, float voltage) {
  overflowFlag = false;
  manual_overflow = false;
  nbk_manual_overflow_until = 0;
  nbk_column_inertia = inertia;
  feedRateStub = feedRate;
  target_power_volt = voltage;
  fakeMillis = 1000;
  scheduleCalls = 0;
  lastM = -1;
  lastP = -1;
  scheduleShouldSucceed = true;
  enterSafeWaitCalls = 0;
  sendMsgCalls = 0;
}

// Полный сценарий "сухо -> залито -> сухо в паузе -> залито в паузе ->
// сухо ЗА паузой -> залито после освобождения латча" для одной пары
// (Ин, реальная скорость насоса, target_power_volt).
static void test_latch_sequence_for(uint16_t inertia, float feedRate, float voltage) {
  reset_fixture(inertia, feedRate, voltage);
  const float expectedM = max(toPower(voltage) / 2.0f, toPower(power_work_mode_threshold()));
  const float expectedP = feedRate / 3.0f;
  const uint32_t deadlineMs = uint32_t(NBK_MULT_PAUSE_OVERFLOW) * inertia * 1000;

  // 1) сухо, латча ещё нет - полный no-op.
  handle_nbk_stage_manual();
  check(scheduleCalls == 0 && !manual_overflow, "сухой такт без предшествующего захлёба обязан быть no-op");

  // 2) залито впервые - одна команда снижения, латч взведён, дедлайн выставлен.
  overflowFlag = true;
  handle_nbk_stage_manual();
  check(scheduleCalls == 1, "первый захлёб обязан отправить ровно одну команду снижения");
  check(lastM == expectedM, "команда снижения обязана использовать max(toPower(target_power_volt)/2, порог)");
  check(lastP == expectedP, "команда снижения обязана использовать реальную подачу насоса / 3");
  check(manual_overflow, "первый захлёб обязан взвести защёлку");
  check(nbk_manual_overflow_until == safety_deadline_after(1000, deadlineMs),
        "дедлайн защёлки обязан считаться от MULT*Ин, а не быть захардкожен");
  check(sendMsgCalls == 1, "первый захлёб обязан дать ровно одно сообщение");

  // 3) сухо, НО В ПРЕДЕЛАХ дедлайна - латч держится, повторного снижения нет.
  fakeMillis += deadlineMs / 2;
  overflowFlag = false;
  handle_nbk_stage_manual();
  check(scheduleCalls == 1, "РЕГРЕСС П6: сухой такт в пределах паузы не должен снимать латч мгновенно");
  check(manual_overflow, "латч обязан держаться в пределах MULT*Ин после снижения");
  check(sendMsgCalls == 1, "в пределах паузы новых сообщений быть не должно");

  // 4) залито СНОВА в пределах дедлайна - латч уже взведён, повторной
  // реакции быть не должно (не спам).
  overflowFlag = true;
  handle_nbk_stage_manual();
  check(scheduleCalls == 1, "повторный залив в пределах паузы не должен давать вторую команду (не спам)");
  check(sendMsgCalls == 1, "повторный залив в пределах паузы не должен давать второе сообщение");

  // 5) продвигаем время ЗА дедлайн, датчик сухой - латч обязан освободиться.
  fakeMillis = nbk_manual_overflow_until + 1;
  overflowFlag = false;
  handle_nbk_stage_manual();
  check(!manual_overflow, "по истечении дедлайна при сухом датчике латч обязан сняться");
  check(nbk_manual_overflow_until == 0, "снятие латча обязано обнулить дедлайн");
  check(scheduleCalls == 1, "снятие латча само по себе не должно посылать команду");

  // 6) новый залив ПОСЛЕ освобождения латча - это уже вторая, отдельная реакция.
  overflowFlag = true;
  handle_nbk_stage_manual();
  check(scheduleCalls == 2, "новый захлёб после освобождения латча обязан дать вторую команду");
  check(sendMsgCalls == 2, "новый захлёб после освобождения латча обязан дать второе сообщение");
  check(manual_overflow, "новый захлёб обязан снова взвести латч");
}

int main() {
  test_latch_sequence_for(180, 9.0f, 210.0f);
  test_latch_sequence_for(60, 15.0f, 235.0f);
  if (failures != 0) return 1;
  std::cout << "nbk manual overflow latch behaviour checks passed\n";
  return 0;
}
'''


def build_harness(nbk_source: str) -> str:
    body = extract_function_body(nbk_source, SIGNATURE)
    return HARNESS.replace("@BODY@", f"void handle_nbk_stage_manual() {{{body}}}")


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-manual-overflow-latch-") as temp_dir:
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


def mutate_drop_deadline_check(source: str) -> str:
    # Возвращает старое поведение: латч снимается по первому же сухому такту,
    # без ожидания дедлайна - должно сломать шаг 3 сценария выше.
    anchor = "manual_overflow && !hasOverflow && safety_deadline_expired(millis(), nbk_manual_overflow_until)"
    if anchor not in source:
        raise ValueError("mutation anchor missing: latch deadline condition")
    return source.replace(anchor, "manual_overflow && !hasOverflow", 1)


def check_reset_sites_pin(nbk_source: str) -> list:
    """[Небольшой пин без компиляции] run_nbk_program() обязан сбрасывать
    латч и на старте сессии (num==0), и при входе на строку S - иначе латч
    предыдущей сессии/строки доживает не туда."""
    stripped = strip_cpp_comments(nbk_source)
    errors: list = []
    try:
        num0_block, _ = extract_braced_block_after(stripped, "if (ProgramNum == 0) {")
    except ValueError as error:
        errors.append(f"num==0 session-start block not found: {error}")
        num0_block = ""
    if "manual_overflow = false;" not in num0_block:
        errors.append("num==0 session start does not reset manual_overflow")
    if "nbk_manual_overflow_until = 0;" not in num0_block:
        errors.append("num==0 session start does not reset nbk_manual_overflow_until")

    try:
        s_block, _ = extract_braced_block_after(stripped, "if (program[ProgramNum].WType == 'S') {")
    except ValueError as error:
        errors.append(f"S-row entry block not found: {error}")
        s_block = ""
    if "manual_overflow = false;" not in s_block:
        errors.append("entry to S row does not reset manual_overflow")
    if "nbk_manual_overflow_until = 0;" not in s_block:
        errors.append("entry to S row does not reset nbk_manual_overflow_until")
    return errors


def main() -> int:
    nbk_source = (ROOT / "nbk.h").read_text(encoding="utf-8")

    try:
        harness = build_harness(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(harness, True) != 0:
        return 1

    reset_errors = check_reset_sites_pin(nbk_source)
    if reset_errors:
        for error in reset_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        mutated = mutate_drop_deadline_check(nbk_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated == nbk_source:
        print("FAIL: mutation had no effect", file=sys.stderr)
        return 1
    mutated_harness = build_harness(mutated)
    if compile_and_run(mutated_harness, False) == 0:
        print("FAIL: mutation survived (expected failure): latch deadline check removed", file=sys.stderr)
        return 1

    print("nbk manual overflow latch checks (behaviour + reset-site pin + mutation) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
