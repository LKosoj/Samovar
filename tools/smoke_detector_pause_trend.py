#!/usr/bin/env python3
"""[П3-4] Поведенческая проверка тренд-сэмплирования во время детекторной паузы
(impurity_detector.h, ветка isDetectorOwnPause в process_impurity_detector) +
статическая проверка LUA-исключения/заглушки в tick_status_fsm (logic.h).

Часть (а): вытаскивает РЕАЛЬНОЕ тело ветки "SamovarStatusInt == AUTOPAUSE || PAUSED"
process_impurity_detector() через extract_braced_block_after - проверяется, что
сэмплирование (update_detector_history/calculate_temperature_trend/lastSampleTime)
происходит ТОЛЬКО когда isDetectorOwnPause истинно (program_Wait && тип паузы ==
PROGRAM_WAIT_DETECTOR), а не переписанная в тесте копия условия.

Существующий smoke_withdrawal_pause_resume.py проверяет только ПОТРЕБИТЕЛЯ
(detector_trend_settled), подставляя currentTrend напрямую - здесь проверяется
сам код сэмплирования.

Часть (б): вытаскивает РЕАЛЬНОЕ тело tick_status_fsm() (logic.h) и проверяет
текстовым порядком токенов, что ветка "Разгон колонны" содержит исключение LUA
(Samovar_Mode != SAMOVAR_LUA_MODE), а для LUA-режима в той же цепочке есть
заглушка с текстом "Выполнение Lua скрипта" (иначе local остаётся пустым).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]

PAUSE_BRANCH_TOKEN = (
    "SamovarStatusInt == SAMOVAR_STATUS_RECT_AUTOPAUSE || "
    "SamovarStatusInt == SAMOVAR_STATUS_PAUSED)"
)

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

enum ProgramWaitType : uint8_t { PROGRAM_WAIT_NONE = 0, PROGRAM_WAIT_STEAM, PROGRAM_WAIT_PIPE, PROGRAM_WAIT_DETECTOR };

struct DSSensor {
  float avgTemp = 0;
};

struct ImpurityDetector {
  uint8_t detectorStatus = 0;
  float currentTrend = 0;
  unsigned long lastSampleTime = 0;
};

// ---- Глобальное состояние ----
static bool program_Wait = false;
static int8_t detector_last_pipe_sensor = -1;
static DSSensor PipeSensor;
static DSSensor SteamSensor;
static ImpurityDetector impurityDetector;

static unsigned long fake_millis_value = 100000;
static unsigned long millis() { return fake_millis_value; }

// ---- Моки внешних примитивов (не относятся к проверяемой логике) ----
static ProgramWaitType currentWaitTypeFixture = PROGRAM_WAIT_NONE;
static bool copy_program_wait_type(ProgramWaitType& out) { out = currentWaitTypeFixture; return true; }

static int updateDetectorHistoryCalls = 0;
static float lastHistoryTemp = 0;
static void update_detector_history(float columnTemp) { updateDetectorHistoryCalls++; lastHistoryTemp = columnTemp; }

static float trendFixture = 0;
static int calculateTrendCalls = 0;
static float calculate_temperature_trend() { calculateTrendCalls++; return trendFixture; }

// ---- Реальный код под тестом (extract_braced_block_after) ----
static void detector_pause_tick() {
@PAUSE_BRANCH_BODY@
}

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  program_Wait = false;
  detector_last_pipe_sensor = -1;
  PipeSensor = DSSensor{};
  SteamSensor = DSSensor{};
  impurityDetector = ImpurityDetector{};
  fake_millis_value = 100000;
  currentWaitTypeFixture = PROGRAM_WAIT_NONE;
  updateDetectorHistoryCalls = 0;
  lastHistoryTemp = 0;
  trendFixture = 0;
  calculateTrendCalls = 0;
}

// Сценарий 1: детекторная пауза (program_Wait && тип == PROGRAM_WAIT_DETECTOR) -
// сэмплирование должно произойти (история/тренд/lastSampleTime обновляются).
static void test_detector_pause_samples() {
  reset_fixture();
  program_Wait = true;
  currentWaitTypeFixture = PROGRAM_WAIT_DETECTOR;
  detector_last_pipe_sensor = 0;  // источник - пар
  SteamSensor.avgTemp = 91.5f;
  impurityDetector.lastSampleTime = 0;  // now(100000) - 0 >= 2000
  trendFixture = 0.42f;

  detector_pause_tick();

  check(updateDetectorHistoryCalls == 1, "детекторная пауза: update_detector_history должен был вызваться");
  check(lastHistoryTemp == 91.5f, "детекторная пауза: в историю должна была попасть текущая Т пара");
  check(calculateTrendCalls == 1, "детекторная пауза: calculate_temperature_trend должен был вызваться");
  check(impurityDetector.currentTrend == 0.42f, "детекторная пауза: currentTrend должен был обновиться");
  check(impurityDetector.lastSampleTime == fake_millis_value, "детекторная пауза: lastSampleTime должен был обновиться");
}

// Сценарий 2: недетекторная автопауза (тот же program_Wait=true, но тип паузы -
// по датчику пара) - сэмплирование НЕ должно происходить, состояние заморожено.
static void test_non_detector_pause_does_not_sample() {
  reset_fixture();
  program_Wait = true;
  currentWaitTypeFixture = PROGRAM_WAIT_STEAM;
  detector_last_pipe_sensor = 0;
  SteamSensor.avgTemp = 91.5f;
  impurityDetector.lastSampleTime = 0;
  impurityDetector.currentTrend = 7.0f;  // заведомо иное значение, чтобы увидеть, что оно НЕ тронуто
  trendFixture = 0.42f;

  detector_pause_tick();

  check(updateDetectorHistoryCalls == 0, "недетекторная пауза: update_detector_history НЕ должен был вызываться");
  check(calculateTrendCalls == 0, "недетекторная пауза: calculate_temperature_trend НЕ должен был вызываться");
  check(impurityDetector.currentTrend == 7.0f, "недетекторная пауза: currentTrend должен был остаться замороженным");
  check(impurityDetector.lastSampleTime == 0, "недетекторная пауза: lastSampleTime не должен был обновиться");
}

// Сценарий 3 (доп. контроль): ручная пауза (program_Wait=false, PauseOn-путь) -
// даже если тип паузы, оставшийся от предыдущей автопаузы, равен DETECTOR,
// program_Wait=false сам по себе должен блокировать сэмплирование.
static void test_manual_pause_does_not_sample_even_with_stale_detector_wait_type() {
  reset_fixture();
  program_Wait = false;
  currentWaitTypeFixture = PROGRAM_WAIT_DETECTOR;  // протухший тип с прошлой автопаузы
  detector_last_pipe_sensor = 0;
  SteamSensor.avgTemp = 91.5f;
  impurityDetector.lastSampleTime = 0;

  detector_pause_tick();

  check(updateDetectorHistoryCalls == 0, "ручная пауза: update_detector_history НЕ должен был вызываться");
  check(calculateTrendCalls == 0, "ручная пауза: calculate_temperature_trend НЕ должен был вызываться");
  check(impurityDetector.lastSampleTime == 0, "ручная пауза: lastSampleTime не должен был обновиться");
}

int main() {
  test_detector_pause_samples();
  test_non_detector_pause_does_not_sample();
  test_manual_pause_does_not_sample_even_with_stale_detector_wait_type();

  if (failures != 0) return 1;
  std::cout << "detector pause trend sampling behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    detector_source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")
    body, _ = extract_braced_block_after(detector_source, PAUSE_BRANCH_TOKEN)
    return HARNESS_TEMPLATE.replace("@PAUSE_BRANCH_BODY@", body)


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-detector-pause-trend-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "detector_pause_trend_test.cpp"
        binary = temp / "detector_pause_trend_test"
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


# ---- Часть (б): статическая проверка LUA-ветки в tick_status_fsm (logic.h) ----
def check_tick_status_fsm_lua_branch() -> list[str]:
    errors: list[str] = []
    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")
    try:
        body = extract_function_body(logic_source, "String tick_status_fsm()")
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    require_ordered_tokens(
        "tick_status_fsm: LUA исключён из «Разгона колонны», но получает свой текст статуса",
        body,
        [
            "Samovar_Mode != SAMOVAR_LUA_MODE",
            'F("Разгон колонны")',
            "Samovar_Mode == SAMOVAR_LUA_MODE",
            'F("Выполнение Lua скрипта")',
        ],
        errors,
    )
    return errors


def main() -> int:
    static_errors = check_tick_status_fsm_lua_branch()
    if static_errors:
        print("detector pause trend smoke failed:")
        for error in static_errors:
            print(f" - {error}")
        return 1

    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
