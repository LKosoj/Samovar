#!/usr/bin/env python3
"""[П3-2] Поведенческая проверка apply_row_stop_pause_policy() (impurity_detector.h).

После PROGRAM_ROW_STOP_PAUSE_LIMIT подряд идущих стоп-пауз одной строки программы
базовая скорость строки (CurrentBaseSpeedRate) должна автоматически снижаться на
PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT процентов, а счётчик - сбрасываться. Смена
строки (эмулируемая сбросом RowStopPauseCount, как это делает
reset_rect_program_pause_state()) должна прерывать накопление и не давать
снижению сработать преждевременно.

Тест вытаскивает РЕАЛЬНОЕ тело apply_row_stop_pause_policy() вместе с реальными
get_speed_from_rate()/get_liquid_rate_by_step()/get_liquid_volume_by_step()/
set_pump_speed() - проверяется настоящая арифметика снижения скорости, а не
переписанная в тесте копия.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURES = {
    "apply_row_stop_pause_policy": ("inline void apply_row_stop_pause_policy()", "impurity_detector.h"),
    "get_speed_from_rate": ("float get_speed_from_rate(float volume_per_hour)", "logic.h"),
    "get_liquid_rate_by_step": ("float get_liquid_rate_by_step(int StepperSpeed)", "logic.h"),
    "get_liquid_volume_by_step": ("float get_liquid_volume_by_step(float StepCount)", "logic.h"),
    "set_pump_speed": ("void set_pump_speed(float pumpspeed, bool continue_process, bool updateBase)", "logic.h"),
}

# Значения по умолчанию из Samovar_ini.h на момент написания теста. Захардкожены
# по тому же принципу, что и PAUSE_RESUME_HYSTERESIS_DELTA в smoke_withdrawal_pause_resume.py -
# тест проверяет ПОВЕДЕНИЕ apply_row_stop_pause_policy() при данных константах,
# а не сами константы.
PROGRAM_ROW_STOP_PAUSE_LIMIT = 3
PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT = 10

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

using std::round;

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}
  String(float value) : value_(std::to_string(value)) {}
  String(float value, int) : value_(std::to_string(value)) {}

  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  friend String operator+(String left, const String& right) { left += right; return left; }
  const std::string& raw() const { return value_; }

 private:
  std::string value_;
};

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

constexpr uint8_t PROGRAM_ROW_STOP_PAUSE_LIMIT = @LIMIT@;
constexpr int PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT = @CUT_PCT@;

constexpr int16_t SAMOVAR_STATUS_RECT_WITHDRAWAL = 10;
constexpr int16_t SAMOVAR_STATUS_RECT_AUTOPAUSE = 15;
constexpr int16_t SAMOVAR_STATUS_PAUSED = 40;

struct SetupEEPROM {
  uint16_t StepperStepMl = 1000;
};

struct WProgram {
  float Time = 0;
  float Volume = 0;
};

// ---- Глобальное состояние ----
static SetupEEPROM SamSetup;
static WProgram program[4];
static uint8_t ProgramNum = 1;
static volatile float CurrentBaseSpeedRate = 0.0f;
static volatile uint8_t RowStopPauseCount = 0;
static int16_t SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
static uint16_t CurrrentStepperSpeed = 100;
static float ActualVolumePerHour = 0;

// ---- Моки внешних примитивов, не относящихся к проверяемой логике ----
static int sendMsgCalls = 0;
static MESSAGE_TYPE lastMsgType = NOTIFY_MSG;
static void SendMsg(const String&, MESSAGE_TYPE type) { sendMsgCalls++; lastMsgType = type; }
static bool stepper_safe_get_state() { return true; }
static void stopService() {}
static void startService() {}
static void stepper_safe_set_max_speed(uint16_t) {}
static uint32_t stepper_safe_get_target() { return 0; }
static void stepper_safe_set_target(uint32_t) {}

static void set_pump_speed(float pumpspeed, bool continue_process, bool updateBase = true);

// ---- Реальный код под тестом ----
@GET_LIQUID_VOLUME_BY_STEP_BODY@
@GET_LIQUID_RATE_BY_STEP_BODY@
@GET_SPEED_FROM_RATE_BODY@
@SET_PUMP_SPEED_BODY@
@APPLY_ROW_STOP_PAUSE_POLICY_BODY@

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static bool nearly_equal(float a, float b, float eps = 0.001f) {
  float diff = a - b;
  if (diff < 0) diff = -diff;
  return diff < eps;
}

static void reset_state() {
  ProgramNum = 1;
  SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
  sendMsgCalls = 0;
  lastMsgType = NOTIFY_MSG;
}

// Ниже лимита (LIMIT-1 стоп-пауз подряд) - снижение НЕ должно срабатывать.
static void test_below_limit_no_reduction() {
  reset_state();
  CurrentBaseSpeedRate = 0.6f;
  RowStopPauseCount = 0;
  for (uint8_t i = 0; i < PROGRAM_ROW_STOP_PAUSE_LIMIT - 1; i++) {
    RowStopPauseCount++;
    apply_row_stop_pause_policy();
  }
  check(nearly_equal(CurrentBaseSpeedRate, 0.6f), "ниже лимита база не должна была измениться");
  check(RowStopPauseCount == PROGRAM_ROW_STOP_PAUSE_LIMIT - 1, "ниже лимита счётчик не должен был сброситься");
  check(sendMsgCalls == 0, "ниже лимита сообщение не должно было отправляться");
}

// На лимите (ровно LIMIT стоп-пауз подряд) - снижение на CUT_PCT% и сброс счётчика.
// Проверено на двух разных базовых скоростях (0.6 и 0.4), чтобы исключить константу-заглушку.
static void test_at_limit_reduces_speed(float baseRate) {
  reset_state();
  CurrentBaseSpeedRate = baseRate;
  RowStopPauseCount = 0;
  for (uint8_t i = 0; i < PROGRAM_ROW_STOP_PAUSE_LIMIT; i++) {
    RowStopPauseCount++;
    apply_row_stop_pause_policy();
  }
  float expected = baseRate * (1.0f - PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT / 100.0f);
  check(nearly_equal(CurrentBaseSpeedRate, expected, 0.01f), "на лимите база должна была снизиться на процент");
  check(CurrentBaseSpeedRate < baseRate, "снижение должно было уменьшить скорость, а не оставить как есть");
  check(RowStopPauseCount == 0, "на лимите счётчик должен был сброситься");
  check(sendMsgCalls == 1 && lastMsgType == ALARM_MSG, "на лимите должно было отправиться ALARM-сообщение");
}

// Контроль: смена строки между паузами (эмулируется сбросом счётчика, как это
// делает reset_rect_program_pause_state()) прерывает накопление - снижение НЕ
// срабатывает, даже если после смены строки снова случится пауза.
static void test_row_change_prevents_premature_trigger() {
  reset_state();
  CurrentBaseSpeedRate = 0.6f;
  RowStopPauseCount = 0;
  RowStopPauseCount++;  // пауза №1 на строке A
  apply_row_stop_pause_policy();
  RowStopPauseCount++;  // пауза №2 на строке A
  apply_row_stop_pause_policy();
  check(RowStopPauseCount == PROGRAM_ROW_STOP_PAUSE_LIMIT - 1, "после 2 пауз счётчик должен быть LIMIT-1");

  // Смена строки программы.
  RowStopPauseCount = 0;

  RowStopPauseCount++;  // пауза №1 на НОВОЙ строке B
  apply_row_stop_pause_policy();
  check(nearly_equal(CurrentBaseSpeedRate, 0.6f), "смена строки должна была прервать накопление - снижение не должно было произойти");
  check(RowStopPauseCount == 1, "после смены строки счётчик не должен был сброситься политикой (лимит не достигнут)");
  check(sendMsgCalls == 0, "после смены строки сообщение о снижении не должно было отправляться");
}

int main() {
  test_below_limit_no_reduction();
  test_at_limit_reduces_speed(0.6f);
  test_at_limit_reduces_speed(0.4f);
  test_row_change_prevents_premature_trigger();

  if (failures != 0) return 1;
  std::cout << "apply_row_stop_pause_policy behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    bodies = {}
    files_cache = {}
    for key, (signature, filename) in SIGNATURES.items():
        if filename not in files_cache:
            files_cache[filename] = (ROOT / filename).read_text(encoding="utf-8")
        bodies[key] = extract_function_body(files_cache[filename], signature)

    harness = HARNESS_TEMPLATE
    harness = harness.replace("@LIMIT@", str(PROGRAM_ROW_STOP_PAUSE_LIMIT))
    harness = harness.replace("@CUT_PCT@", str(PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT))
    harness = harness.replace(
        "@GET_LIQUID_VOLUME_BY_STEP_BODY@",
        "static float get_liquid_volume_by_step(float StepCount) {" + bodies["get_liquid_volume_by_step"] + "}",
    )
    harness = harness.replace(
        "@GET_LIQUID_RATE_BY_STEP_BODY@",
        "static float get_liquid_rate_by_step(int StepperSpeed) {" + bodies["get_liquid_rate_by_step"] + "}",
    )
    harness = harness.replace(
        "@GET_SPEED_FROM_RATE_BODY@",
        "static float get_speed_from_rate(float volume_per_hour) {" + bodies["get_speed_from_rate"] + "}",
    )
    harness = harness.replace(
        "@SET_PUMP_SPEED_BODY@",
        "static void set_pump_speed(float pumpspeed, bool continue_process, bool updateBase) {" + bodies["set_pump_speed"] + "}",
    )
    harness = harness.replace(
        "@APPLY_ROW_STOP_PAUSE_POLICY_BODY@",
        "static void apply_row_stop_pause_policy() {" + bodies["apply_row_stop_pause_policy"] + "}",
    )
    return harness


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-row-stop-pause-policy-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "row_stop_pause_policy_test.cpp"
        binary = temp / "row_stop_pause_policy_test"
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
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
