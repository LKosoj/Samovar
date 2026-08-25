#!/usr/bin/env python3
"""Поведенческая проверка [T1]: повторный захлёб в паузе W (handle_nbk_stage_work).

Тест вытаскивает РЕАЛЬНЫЙ фрагмент из nbk.h — "if (overflow()) { ... }" внутри
"if (nbk_work_in_pause)" плюс непосредственно следующую за ним строку сброса
латча ("nbk_pause_overflow_repeat_latched = false;") — через
extract_braced_block_after и подставляет в минимальный host-харнесс, замокав
только downstream-вызовы (overflow, SendMsg,
nbk_schedule_actuator_command).

Регресс, который тест защищает: до задачи 1 повторный захлёб в паузе W вообще
не отслеживался (пауза просто истекала по таймеру). Задача 1 добавила опрос
overflow() и латч nbk_pause_overflow_repeat_latched, подавляющий спам
одинаковых SendMsg на каждом тике, но обязанный отпускать латч и снова слать
сообщение при новом (не первом) захлёбе после промежутка без него.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

# Якорь ищем в СЫРОМ (не очищенном от комментариев) исходнике: комментарий
# "// [T1] повторный" — единственное, что отличает этот "if (overflow()) {" от
# двух других (в handle_nbk_stage_optimization), где та же голая сигнатура
# тоже встречается с меткой [T1], но другим текстом комментария.
ANCHOR = "if (overflow()) { // [T1] повторный"
RESET_STMT = "nbk_pause_overflow_repeat_latched = false;"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
static float max(float left, float right) { return left > right ? left : right; }

#define NBK_MULT_PAUSE_OVERFLOW 2

// Минимальная замена Arduino String: реальный SendMsg в nbk.h принимает
// const String&, а тело блока (после находки 3 код-ревью) склеивает текст
// сообщения через "..." + String(nbk_overflow_source()) + "...".
class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

static String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

uint16_t nbk_column_inertia = 180;
float nbk_Mo = 100.0f;
float nbk_P = 9.0f;
uint16_t nbk_opt_iter = 0;
uint8_t nbk_work_pause_stage = 0;
bool nbk_overflow_happened = false;
bool nbk_pause_overflow_repeat_latched = false;
uint32_t nbk_work_next_time = 0;
enum NbkActuatorDeadlineTarget : uint8_t {
  NBK_ACTUATOR_WORK_DEADLINE = 2,
};

// [T14 п.1/п.8] Нижняя граница - в этом харнессе оставляем toPower() тождественной
// (unit-конвертация волюм<->ватт для НБК проверяется отдельно, в
// smoke_nbk_session_config.py); важно только само наличие клэмпа.
float power_work_mode_threshold() { return 40.0f; }
float toPower(float value) { return value; }

static bool overflowFlag = false;
bool overflow() { return overflowFlag; }
// [Ревью П1, находка 3] источник overflow() для текста сообщения — фиксированное
// значение достаточно: этот тест проверяет количество/тайминг SendMsg, а не текст.
const char* nbk_overflow_source() { return "ДЗ"; }

static int sendMsgCalls = 0;
// Заглушки НЕ static: единственный вызов каждой лежит во вклеенном теле блока,
// и со static мутация, убравшая вызов, роняла бы компилятор по
// unused-function вместо содержательного assert-а. Держится это на проверках
// sendMsgCalls/powerCalls/lastPower ниже: без них снятие static меняет ложный
// улов на молчаливую слепую зону, что хуже.
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

static int scheduleCalls = 0;
static float lastPower = -1.0f;
static float lastSpeed = -1.0f;
bool nbk_schedule_actuator_command(
    float power,
    float speed,
    NbkActuatorDeadlineTarget,
    uint32_t,
    uint16_t) {
  scheduleCalls++;
  lastPower = power;
  lastSpeed = speed;
  return true;
}
void nbk_enter_safe_wait(const String&) {}

static uint32_t fakeMillis = 1000;
uint32_t millis() { return fakeMillis; }
uint32_t safety_deadline_after(uint32_t now, uint32_t ms) { return now + ms; }

static void run_pause_overflow_tick() {
  if (overflow()) {
@BODY@
  }
  @RESET@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(float mo) {
  nbk_Mo = mo;
  nbk_work_pause_stage = 0;
  nbk_overflow_happened = false;
  nbk_pause_overflow_repeat_latched = false;
  nbk_work_next_time = 0;
  sendMsgCalls = 0;
  scheduleCalls = 0;
  lastPower = -1.0f;
  lastSpeed = -1.0f;
  overflowFlag = false;
}

// Основной сценарий для одного значения nbk_Mo: 5 тиков подряд с overflow=true
// должны дать РОВНО одно сообщение (латч подавляет повтор), но
// составная команда обязана приниматься на КАЖДОМ тике со сниженной вдвое
// мощностью. Затем overflow отпускает (false), латч сбрасывается, и при новом
// overflow=true сообщение должно появиться СНОВА.
static void test_repeat_overflow_for(float mo) {
  reset_fixture(mo);
  overflowFlag = true;
  const float expectedPower = max(mo / 2.0f, power_work_mode_threshold());
  for (int tick = 0; tick < 5; tick++) {
    run_pause_overflow_tick();
    check(scheduleCalls == tick + 1, "повторный захлёб должен принимать новую составную команду");
    check(lastPower == expectedPower, "составная команда должна снижать мощность nbk_Mo/2, но не ниже порога WORK");
    check(lastSpeed == nbk_P, "повторный захлёб не должен подменять текущую подачу");
    check(nbk_work_pause_stage == 1, "во время повторного захлёба стадия паузы должна оставаться 1");
    check(nbk_overflow_happened, "флаг nbk_overflow_happened обязан быть выставлен во время повторного захлёба");
  }
  check(sendMsgCalls == 1, "5 тиков подряд с overflow=true должны дать РОВНО одно сообщение (латч подавляет повтор)");

  // overflow отпустил на один тик — латч должен сброситься, сообщений больше нет
  overflowFlag = false;
  run_pause_overflow_tick();
  check(sendMsgCalls == 1, "тик без захлёба не должен добавлять сообщений");
  check(!nbk_pause_overflow_repeat_latched, "после overflow=false латч обязан быть сброшен");

  // Новый (не первый) захлёб после промежутка без него — сообщение снова
  overflowFlag = true;
  run_pause_overflow_tick();
  check(sendMsgCalls == 2, "РЕГРЕСС: после false->true сообщение о повторном захлёбе должно появиться снова");
}

int main() {
  test_repeat_overflow_for(100.0f);
  test_repeat_overflow_for(260.0f);

  // [T14 п.1/п.8, ПИНИМ] nbk_Mo=50 -> nbk_Mo/2=25, ниже порога WORK (40) - без
  // клэмпа команда ушла бы приводам с 25 Вт, а set_current_power() ниже по
  // цепочке молча схлопнул бы это в SLEEP (нагрев погас бы посреди паузы).
  reset_fixture(50.0f);
  overflowFlag = true;
  run_pause_overflow_tick();
  check(lastPower == 40.0f, "РЕГРЕСС: составная команда обязана клэмпиться к порогу WORK, а не уходить ниже него");

  if (failures != 0) return 1;
  std::cout << "nbk work-pause repeat-overflow behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    body, end = extract_braced_block_after(source, ANCHOR)
    body = body.replace("\r\n", "\n")
    tail = source[end:end + 200].replace("\r\n", "\n")
    reset_index = tail.find(RESET_STMT)
    if reset_index < 0:
        raise ValueError(f"reset statement not found right after anchor block: {RESET_STMT}")
    harness = HARNESS_TEMPLATE.replace("@BODY@", body)
    harness = harness.replace("@RESET@", RESET_STMT)
    return harness


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-nbk-work-pause-overflow-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "nbk_work_pause_overflow_test.cpp"
        binary = temp / "nbk_work_pause_overflow_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
