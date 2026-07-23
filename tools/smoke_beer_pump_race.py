#!/usr/bin/env python3
"""Поведенческая проверка [P2 п.1] в beer.h::set_mixer_state() и связанной с
ней находки в beer_finish().

Плановое выключение насоса по расписанию мешалки (OFF-ветка set_mixer_state,
вызываемая из check_mixer_state()) не должно глушить насос, если охлаждение
('C'/'F' в beer_stage_tick()) активно прямо сейчас — иначе гонка между двумя
источниками управления насосом обрывает охлаждение раньше времени.

[Находка] beer_finish() обязан сбрасывать beerCoolingPumpActive: иначе при
ручной остановке пива во время активного 'C'/'F' флаг остаётся true до
следующего старта, и если в этот промежуток set_mixer(false) дёрнут из
другого режима/Lua, set_pump_pwm(0) внутри set_mixer_state молча не
выполнится из-за устаревшего флага.

Тест вытаскивает РЕАЛЬНЫЕ тела set_mixer_state() и beer_finish() из beer.h
через extract_function_body — без переписывания логики.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SET_MIXER_STATE_SIGNATURE = "void set_mixer_state(bool state, bool dir)"
BEER_FINISH_SIGNATURE = "void beer_finish()"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdlib>
#include <iostream>

#define BitIsSet(reg, bit) ((reg & (1 << bit)) != 0)
#define RELE_CHANNEL2 2
#define USE_WATER_PUMP

struct WProgram {
  uint8_t capacity_num = 0;
  int Volume = 0;
  int Speed = 0;
};

struct SetupEEPROM {
  bool rele2 = false;
};

constexpr uint8_t PROGRAM_MAX = 8;

static WProgram program[PROGRAM_MAX];
static SetupEEPROM SamSetup;
static uint8_t ProgramNum = 0;
static bool mixer_status = false;
static unsigned long alarm_c_min = 0;
static unsigned long alarm_c_low_min = 0;
static bool beerCoolingPumpActive = false;
static bool pump_started = false;

static int digitalWriteCalls = 0;
void digitalWrite(int, bool) { digitalWriteCalls++; }

static int pumpPwmCalls = 0;
static float lastPumpPwm = -1;
void set_pump_pwm(float duty) { lastPumpPwm = duty; pumpPwmCalls++; }

bool i2c_stepper_mixer_present() { return false; }
bool i2c_stepper_pump_present() { return false; }
void set_stepper_by_time(int, bool, int) {}
void set_mixer_pump_target(int) {}

// --- Зависимости beer_finish(), не относящиеся к гонке насоса/мешалки ---
static bool valve_status = false;
static int openValveCalls = 0;
void open_valve(bool val, bool /*msg*/) { valve_status = val; openValveCalls++; }

static int resetBoilingDetectorCalls = 0;
void resetBoilingDetector() { resetBoilingDetectorCalls++; }

static bool heater_state = true;
static int setHeaterPositionCalls = 0;
void setHeaterPosition(bool) { setHeaterPositionCalls++; }

static bool beerManualPause = false;
static unsigned long beerStageIdleAccumMs = 0;
static unsigned long beerStageIdleSinceMs = 0;
static uint8_t beerSkipConfirmProgramNum = 0xFF;
static unsigned long begintime = 0;

constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;
static int16_t startval = 5;

static int stopProcessCalls = 0;
void stop_process(const char*) { stopProcessCalls++; }

@SET_MIXER_STATE_BODY@

@BEER_FINISH_BODY@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  program[0].capacity_num = 0b10;  // насос (бит 1) назначен этой ёмкости
  ProgramNum = 0;
  mixer_status = true;
  alarm_c_min = 0;
  alarm_c_low_min = 0;
  digitalWriteCalls = 0;
  pumpPwmCalls = 0;
  lastPumpPwm = -1;
  pump_started = false;
  valve_status = false;
  openValveCalls = 0;
  resetBoilingDetectorCalls = 0;
  heater_state = true;
  setHeaterPositionCalls = 0;
  beerManualPause = false;
  beerStageIdleAccumMs = 0;
  beerStageIdleSinceMs = 0;
  beerSkipConfirmProgramNum = 0xFF;
  begintime = 0;
  startval = 5;
  stopProcessCalls = 0;
}

// Активное охлаждение 'C'/'F' - плановое выключение мешалки/насоса НЕ должно
// глушить насос: set_pump_pwm(0) не должен вызываться вовсе.
static void test_active_cooling_blocks_planned_pump_off() {
  reset_fixture();
  beerCoolingPumpActive = true;

  set_mixer_state(false, false);

  check(mixer_status == false, "set_mixer_state должен был обновить mixer_status");
  check(pumpPwmCalls == 0,
        "РЕГРЕСС: плановое выключение заглушило насос активного охлаждения (set_pump_pwm вызван)");
}

// Охлаждение неактивно - плановое выключение мешалки штатно глушит насос.
static void test_no_cooling_allows_planned_pump_off() {
  reset_fixture();
  beerCoolingPumpActive = false;

  set_mixer_state(false, false);

  check(mixer_status == false, "set_mixer_state должен был обновить mixer_status");
  check(pumpPwmCalls == 1, "плановое выключение без активного охлаждения должно было выключить насос");
  check(lastPumpPwm == 0, "плановое выключение должно было установить скважность насоса в 0");
}

// [Находка] beer_finish() во время активного 'C'/'F' обязан сбросить
// beerCoolingPumpActive, иначе он остаётся true до следующего старта пива.
static void test_beer_finish_resets_cooling_pump_flag() {
  reset_fixture();
  beerCoolingPumpActive = true;
  pump_started = true;
  valve_status = true;

  beer_finish();

  check(beerCoolingPumpActive == false,
        "РЕГРЕСС: beer_finish не сбросил beerCoolingPumpActive");
  check(pump_started == false, "beer_finish должен был сбросить pump_started");
}

// Поведенческий сценарий: после beer_finish() устаревший флаг больше не
// должен глушить последующий set_mixer_state(false, false), вызванный извне
// (другим режимом или Lua через set_mixer(false)).
static void test_beer_finish_then_external_mixer_off_mutes_pump() {
  reset_fixture();
  beerCoolingPumpActive = true;
  pump_started = true;
  valve_status = true;

  beer_finish();

  // Сбрасываем счётчики, чтобы проверить именно СЛЕДУЮЩИЙ, внешний вызов -
  // не побочный эффект самого beer_finish().
  pumpPwmCalls = 0;
  lastPumpPwm = -1;

  set_mixer_state(false, false);

  check(pumpPwmCalls == 1,
        "РЕГРЕСС: устаревший beerCoolingPumpActive после beer_finish заблокировал внешний set_mixer_state(false)");
  check(lastPumpPwm == 0, "внешний set_mixer_state(false) после beer_finish должен был обнулить скважность насоса");
}

int main() {
  test_active_cooling_blocks_planned_pump_off();
  test_no_cooling_allows_planned_pump_off();
  test_beer_finish_resets_cooling_pump_flag();
  test_beer_finish_then_external_mixer_off_mutes_pump();
  if (failures != 0) return 1;
  std::cout << "beer.h set_mixer_state pump race behaviour checks passed\n";
  return 0;
}
'''


def build_harness(beer_header_path: Path) -> str:
    beer_source = beer_header_path.read_text(encoding="utf-8")
    mixer_body = extract_function_body(beer_source, SET_MIXER_STATE_SIGNATURE)
    mixer_fn = "void set_mixer_state(bool state, bool dir) {" + mixer_body + "}"
    finish_body = extract_function_body(beer_source, BEER_FINISH_SIGNATURE)
    finish_fn = "void beer_finish() {" + finish_body + "}"
    harness = HARNESS_TEMPLATE.replace("@SET_MIXER_STATE_BODY@", mixer_fn)
    harness = harness.replace("@BEER_FINISH_BODY@", finish_fn)
    return harness


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-pump-race-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_pump_race_test.cpp"
        binary = temp / "beer_pump_race_test"
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
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        harness = build_harness(ROOT / "beer.h")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return compile_and_run(harness, "beer.h")


if __name__ == "__main__":
    raise SystemExit(main())
