#!/usr/bin/env python3
"""Поведенческая проверка П34: доля выполнения строки в ректификации не выходит за [0;1].

Samovar.ino, RECT-ветка tick_update_withdrawal_progress(): wp = CurrrentStepps /
TargetStepps без клампа мог быть больше 1 (CurrrentStepps > TargetStepps), и тогда
WthdrwTime = Time * (1 - wp) уходил в минус. Ниже по функции WthdrwTime приводится к
unsigned int - приведение отрицательного float к беззнаковому типу - неопределённое
поведение. В BEER-ветке той же функции клампы уже были, в RECT - нет.

'P'-ветка (пауза) клампила WthdrwTime только сверху: если пауза уже просрочена
(t_min в прошлом), WthdrwTime уходил в минус тем же путём, а wp (используется в обеих
ветках как WthdrwlProgress = wp * 100, отдаётся в веб) - больше 1.

Тест берёт РЕАЛЬНОЕ тело tick_update_withdrawal_progress() (через extract_function_body -
без переписывания логики) и подставляет его в host-харнесс с подменёнными глобалами
(program[], TargetStepps, CurrrentStepps, t_min/millis() и т.д.), наблюдая фактические
WthdrwTime/WthdrwlProgress после клампа.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>

using TickType_t = uint32_t;
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(unsigned char value) : value_(std::to_string(value)) {}
  String(unsigned short value) : value_(std::to_string(value)) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  String(unsigned long value) : value_(std::to_string(value)) {}
  String(int value) : value_(std::to_string(value)) {}
  String(long value) : value_(std::to_string(value)) {}
  String(float value) : value_(format_float(value)) {}
  String(double value) : value_(format_float(value)) {}

  size_t length() const { return value_.size(); }
  const char* c_str() const { return value_.c_str(); }

  String& operator+=(const String& other) {
    value_ += other.value_;
    return *this;
  }

  friend String operator+(String left, const String& right) {
    left += right;
    return left;
  }

 private:
  static std::string format_float(double value) {
    char buffer[48] = {0};
    std::snprintf(buffer, sizeof(buffer), "%.2f", value);
    return buffer;
  }

  std::string value_;
};

using ProgramType = char;

enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE,
};

struct WProgram {
  float Time;
};

static const uint8_t PROGRAM_MAX = 16;

volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
WProgram program[PROGRAM_MAX];
volatile uint8_t ProgramNum = 0;
volatile uint8_t ProgramLen = 1;
volatile unsigned int CurrrentStepps = 0;
volatile unsigned int TargetStepps = 0;
unsigned long begintime = 0;
unsigned long t_min = 0;
volatile float WthdrwTimeAll = 0;
volatile float WthdrwTime = 0;
volatile uint8_t WthdrwlProgress = 0;
String WthdrwTimeAllS;
String WthdrwTimeS;

static unsigned long mockMillis = 0;
static unsigned long millis() { return mockMillis; }

static bool runtime_state_lock(TickType_t timeout = pdMS_TO_TICKS(50)) {
  (void)timeout;
  return true;
}
static void runtime_state_unlock(bool) {}

static void tick_update_withdrawal_progress(ProgramType tickerProgramType) {
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
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  ProgramNum = 0;
  ProgramLen = 1;
  program[0].Time = 60;  // минут на строку
  CurrrentStepps = 0;
  TargetStepps = 0;
  mockMillis = 0;
  t_min = 0;
  WthdrwTime = 0;
  WthdrwTimeAll = 0;
  WthdrwlProgress = 0;
}

// (1) CurrrentStepps > TargetStepps -> wp не выше 1, WthdrwTime не отрицательное,
// приведение к unsigned int (внутри самой функции, строками ниже по коду) даёт 0.
static void test_overshoot_steps_clamped_to_one() {
  reset_fixture();
  TargetStepps = 100;
  CurrrentStepps = 150;  // перебор - без клампа wp = 1.5
  tick_update_withdrawal_progress('M');
  check(WthdrwTime >= 0.0f, "REGRESS: WthdrwTime ушёл в минус при перевыполнении шагов");
  check(WthdrwlProgress <= 100, "WthdrwlProgress вышел за 100% при перевыполнении шагов");
  check((unsigned int)WthdrwTime == 0,
        "приведение WthdrwTime к unsigned int дало не 0 при wp, зажатом в 1");
}

// (2) CurrrentStepps == 0 -> wp == 0, поведение (контрольная точка) не изменилось.
static void test_zero_steps_unchanged() {
  reset_fixture();
  TargetStepps = 100;
  CurrrentStepps = 0;
  tick_update_withdrawal_progress('M');
  check(WthdrwlProgress == 0, "REGRESS: контрольное поведение при CurrrentStepps == 0 изменилось");
  check(WthdrwTime == program[0].Time,
        "REGRESS: WthdrwTime при wp == 0 должен совпадать с длительностью строки");
}

// (3) 'P'-ветка с просроченной паузой (t_min в прошлом) -> WthdrwTime не отрицательное,
// WthdrwlProgress не выше 100.
static void test_overdue_pause_clamped() {
  reset_fixture();
  program[0].Time = 60;  // минут
  // millis() далеко впереди t_min - пауза просрочена на несколько часов.
  t_min = 0;
  mockMillis = (unsigned long)10 * 60 * 60 * 1000;  // +10 часов
  tick_update_withdrawal_progress('P');
  check(WthdrwTime >= 0.0f, "REGRESS: WthdrwTime ушёл в минус в просроченной паузе ('P')");
  check(WthdrwlProgress <= 100, "WthdrwlProgress вышел за 100% в просроченной паузе ('P')");
}

int main() {
  test_overshoot_steps_clamped_to_one();
  test_zero_steps_unchanged();
  test_overdue_pause_clamped();

  if (failures != 0) return 1;
  std::cout << "rectification withdrawal progress clamp checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8", errors="ignore")
    body = extract_function_body(
        source, "static void tick_update_withdrawal_progress(ProgramType tickerProgramType) {"
    )
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-rect-progress-clamp-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "rect_progress_clamp_test.cpp"
        binary = temp / "rect_progress_clamp_test"
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
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
