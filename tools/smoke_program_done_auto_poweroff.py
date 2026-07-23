#!/usr/bin/env python3
"""[П3-6] Поведенческая проверка "работы на себя" после завершения программы.

Два места меняются вместе:
  - Menu.ino: ветка startval==SAMOVAR_STARTVAL_RECT_DONE внутри menu_samovar_start()
    - при PROGRAM_DONE_AUTO_POWEROFF_MIN<=0 ведёт себя по-старому (немедленный
      run_program(PROGRAM_END)); при >0 глушит насос/буззер, НЕ трогает нагрев,
      и ставит program_done_hold_since.
  - logic.h: новая ветка в самом начале withdrawal(), которая при
    startval==SAMOVAR_STARTVAL_RECT_DONE и истёкшем таймауте от
    program_done_hold_since вызывает run_program(PROGRAM_END).

PROGRAM_DONE_AUTO_POWEROFF_MIN - компилтайм-константа (#define в Samovar_ini.h),
поэтому обе ветки прогоняются ДВАЖДЫ - с MIN=5 (проверяем холд+таймаут) и с MIN=0
(проверяем, что старое немедленное поведение полностью сохранилось).

Извлекаются РЕАЛЬНЫЕ блоки кода через extract_braced_block_after - проверяется
настоящая логика, а не переписанная в тесте копия.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

MENU_TOKEN = "else if (startval == SAMOVAR_STARTVAL_RECT_DONE) {"
WITHDRAWAL_TOKEN = "if (startval == SAMOVAR_STARTVAL_RECT_DONE) {"

COMMON_PRELUDE = r'''
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}

  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  friend String operator+(String left, const String& right) { left += right; return left; }
  const std::string& raw() const { return value_; }

 private:
  std::string value_;
};

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

constexpr uint8_t PROGRAM_END = 20;
constexpr int16_t SAMOVAR_STARTVAL_RECT_DONE = 2;
constexpr int PROGRAM_DONE_AUTO_POWEROFF_MIN = @MIN@;

static unsigned long fake_millis_value = 1000000;
static unsigned long millis() { return fake_millis_value; }

static int runProgramCalls = 0;
static uint8_t lastRunProgramArg = 0;
static void run_program(uint8_t num) { runProgramCalls++; lastRunProgramArg = num; }

static int16_t startval = SAMOVAR_STARTVAL_RECT_DONE;
static unsigned long program_done_hold_since = 0;

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
'''

# Моки, нужные только ветке Menu.ino (withdrawal() их не вызывает вовсе).
MENU_ONLY_MOCKS = r'''
static int sendMsgCalls = 0;
static MESSAGE_TYPE lastMsgType = NOTIFY_MSG;
static void SendMsg(const String&, MESSAGE_TYPE type) { sendMsgCalls++; lastMsgType = type; }

static int stopServiceCalls = 0;
static void stopService() { stopServiceCalls++; }
static int stepperStopResetCalls = 0;
static void stepper_safe_stop_reset() { stepperStopResetCalls++; }
static int setCapacityCalls = 0;
static uint8_t lastCapacityArg = 255;
static void set_capacity(uint8_t v) { setCapacityCalls++; lastCapacityArg = v; }
static int setBuzzerCalls = 0;
static bool lastBuzzerArg = false;
static void set_buzzer(bool v) { setBuzzerCalls++; lastBuzzerArg = v; }
static int resetPauseStateCalls = 0;
static bool lastResumeStepperArg = true;
static void reset_rect_program_pause_state(bool resumeStepper) { resetPauseStateCalls++; lastResumeStepperArg = resumeStepper; }
'''

MENU_MAIN_TEMPLATE = r'''
static void menu_done_branch() {
  String Str;
@BLOCK@
}

int main() {
  // Сценарий 1: PROGRAM_DONE_AUTO_POWEROFF_MIN<=0 - старое немедленное поведение.
  startval = SAMOVAR_STARTVAL_RECT_DONE;
  runProgramCalls = 0;
  stopServiceCalls = 0;
  resetPauseStateCalls = 0;
  setBuzzerCalls = 0;
  program_done_hold_since = 0;
  menu_done_branch();
#if @MIN@ <= 0
  check(runProgramCalls == 1 && lastRunProgramArg == PROGRAM_END, "MIN<=0: должен был вызваться run_program(PROGRAM_END) немедленно");
  check(resetPauseStateCalls == 0, "MIN<=0: не должно было быть холд-ветки (reset_rect_program_pause_state)");
  check(program_done_hold_since == 0, "MIN<=0: program_done_hold_since не должен был выставляться");
#else
  check(runProgramCalls == 0, "MIN>0: run_program НЕ должен был вызываться немедленно");
  check(resetPauseStateCalls == 1 && lastResumeStepperArg == false, "MIN>0: должен был вызваться reset_rect_program_pause_state(false)");
  check(stopServiceCalls == 1, "MIN>0: должен был вызваться stopService()");
  check(stepperStopResetCalls == 1, "MIN>0: должен был вызваться stepper_safe_stop_reset()");
  check(setCapacityCalls == 1 && lastCapacityArg == 0, "MIN>0: должен был вызваться set_capacity(0)");
  check(setBuzzerCalls == 1 && lastBuzzerArg == true, "MIN>0: должен был включиться буззер");
  check(program_done_hold_since == fake_millis_value, "MIN>0: program_done_hold_since должен был выставиться в текущий millis()");
  check(sendMsgCalls == 1 && lastMsgType == ALARM_MSG, "MIN>0: должно было отправиться ALARM-сообщение");
#endif

  if (failures != 0) return 1;
  std::cout << "menu_samovar_start RECT_DONE branch behaviour checks passed (MIN=@MIN@)\n";
  return 0;
}
'''

WITHDRAWAL_MAIN_TEMPLATE = r'''
static void withdrawal_done_hold_check() {
@BLOCK@
}

int main() {
  // Сценарий: холд ещё не задан (program_done_hold_since==0) - вызов не должен
  // ничего делать (защита от срабатывания раньше времени, до того как Menu.ino
  // выставил метку).
  startval = SAMOVAR_STARTVAL_RECT_DONE;
  program_done_hold_since = 0;
  fake_millis_value = 1000000;
  runProgramCalls = 0;
  withdrawal_done_hold_check();
  check(runProgramCalls == 0, "program_done_hold_since==0: run_program не должен был вызываться");

  // Таймаут ещё не истёк (4 из 5 минут, если MIN>0) - не должен сработать.
  program_done_hold_since = 1000000;
  fake_millis_value = 1000000 + 4UL * 60000UL;
  runProgramCalls = 0;
  withdrawal_done_hold_check();
#if @MIN@ > 0
  check(runProgramCalls == 0, "таймаут ещё не истёк: run_program не должен был вызываться");

  // Таймаут истёк (6 из 5 минут) - должен сработать ровно один раз.
  fake_millis_value = 1000000 + 6UL * 60000UL;
  runProgramCalls = 0;
  withdrawal_done_hold_check();
  check(runProgramCalls == 1 && lastRunProgramArg == PROGRAM_END, "таймаут истёк: run_program(PROGRAM_END) должен был вызваться");
#else
  // MIN<=0: ветка полностью отключена (защитный guard "> 0"), даже если бы
  // кто-то по ошибке проставил program_done_hold_since и время давно вышло.
  check(runProgramCalls == 0, "MIN<=0: run_program не должен был вызываться даже после долгого ожидания");
#endif

  if (failures != 0) return 1;
  std::cout << "withdrawal() RECT_DONE hold/timeout behaviour checks passed (MIN=@MIN@)\n";
  return 0;
}
'''


def build_harness(main_template: str, block: str, min_value: int, extra_mocks: str = "") -> str:
    harness = COMMON_PRELUDE.replace("@MIN@", str(min_value))
    harness += extra_mocks
    harness += main_template.replace("@BLOCK@", block).replace("@MIN@", str(min_value))
    return harness


def compile_and_run(name: str, harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix=f"samovar-{name}-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / f"{name}.cpp"
        binary = temp / name
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(f"compile failed ({name}):\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        menu_source = (ROOT / "Menu.ino").read_text(encoding="utf-8")
        menu_block, _ = extract_braced_block_after(menu_source, MENU_TOKEN)
        withdrawal_source = (ROOT / "logic.h").read_text(encoding="utf-8")
        withdrawal_block, _ = extract_braced_block_after(withdrawal_source, WITHDRAWAL_TOKEN)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    overall = 0
    for min_value in (0, 5):
        overall |= compile_and_run(
            f"menu-done-branch-min{min_value}",
            build_harness(MENU_MAIN_TEMPLATE, menu_block, min_value, MENU_ONLY_MOCKS),
        )
        overall |= compile_and_run(
            f"withdrawal-done-hold-min{min_value}",
            build_harness(WITHDRAWAL_MAIN_TEMPLATE, withdrawal_block, min_value),
        )
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
