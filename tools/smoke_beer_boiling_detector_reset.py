#!/usr/bin/env python3
"""Поведенческая проверка сброса детектора кипения в beer.h::run_beer_program().

[п.11] Несмежная строка 'B' — это новое кипячение на остывшей жидкости, и
накопленная история/стабильность детектора должна сбрасываться. Смежные
'B'->'B' (продолжение одного кипячения ради разных всыпок хмеля) детектор
трогать НЕ должны — иначе засыпка нового хмеля посреди уже идущего кипячения
заново гоняла бы историю через полное окно стабилизации.

Тест вытаскивает РЕАЛЬНОЕ тело run_beer_program() из beer.h через
extract_function_body — без переписывания логики перехода. Чтобы проверять
настоящее поведение, а не факт вызова, вместе с ним вытаскиваются также
реальные тела resetBoilingDetector() (beer.h) и program_type_at()
(runtime_helpers.h): assert-ы читают итоговое состояние структуры
BoilingDetector (isBoiling/stableCount), а не мок-счётчик вызовов.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

RUN_BEER_PROGRAM_SIGNATURE = "void run_beer_program(uint8_t num)"
RESET_BOILING_DETECTOR_SIGNATURE = "static inline void resetBoilingDetector()"
PROGRAM_TYPE_AT_SIGNATURE = "inline ProgramType program_type_at(uint8_t index)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String(int v) : value_(std::to_string(v)) {}
  String(unsigned int v) : value_(std::to_string(v)) {}
  String(float v) : value_(std::to_string(v)) {}
  String(double v) : value_(std::to_string(v)) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  String& operator+=(const char* text) { value_ += (text ? text : ""); return *this; }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

static String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum SAMOVAR_MODE { SAMOVAR_RECTIFICATION_MODE = 0, SAMOVAR_BEER_MODE };

using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_MAX = 8;
constexpr uint8_t PROGRAM_END = PROGRAM_MAX;
constexpr int16_t SAMOVAR_STARTVAL_BEER_START = 2000;
constexpr int16_t SAMOVAR_STARTVAL_BEER_HEATING = 2001;

struct WProgram {
  ProgramType WType = PROGRAM_TYPE_NONE;
  uint16_t Volume = 0;
  float Speed = 0;
  uint8_t capacity_num = 0;
  float Temp = 0;
  float Power = 0;
  uint8_t TempSensor = 0;
  float Time = 0;
};

struct SetupEEPROM {
  bool ChangeProgramBuzzer = false;
};

#define TEMP_HISTORY_SIZE 10

struct BoilingDetector {
    float tempHistory[TEMP_HISTORY_SIZE];
    uint8_t historyIndex = 0;
    uint8_t samplesFilled = 0;
    bool isBoiling = false;
    unsigned long lastUpdateTime = 0;
    uint8_t stableCount = 0;
};

static BoilingDetector boilingDetector;
static WProgram program[PROGRAM_MAX];
static SetupEEPROM SamSetup;

static volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_BEER_MODE;
static volatile bool PowerOn = true;
static volatile int16_t startval = 2001;
static volatile uint8_t ProgramNum = 0;
static volatile uint8_t ProgramLen = 0;
static volatile bool SetScriptOff = false;
static volatile bool loop_lua_fl = false;
static bool msgfl = false;
static unsigned long begintime = 0;
static int currentstepcnt = 0;
static unsigned long alarm_c_min = 0;
static unsigned long alarm_c_low_min = 0;

static int startAutoTuneCalls = 0;
void StartAutoTune() { startAutoTuneCalls++; }

static int beerFinishCalls = 0;
void beer_finish() { beerFinishCalls++; }

static int sendMsgCalls = 0;
void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

static int setBuzzerCalls = 0;
void set_buzzer(bool) { setBuzzerCalls++; }

static ProgramType program_type_at(uint8_t index) {
@PROGRAM_TYPE_AT_BODY@
}

static void resetBoilingDetector() {
@RESET_BOILING_DETECTOR_BODY@
}

@RUN_BEER_PROGRAM_BODY@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  ProgramLen = 0;
  ProgramNum = 0;
  startval = 2001;
  Samovar_Mode = SAMOVAR_BEER_MODE;
  PowerOn = true;
  SetScriptOff = false;
  loop_lua_fl = false;
  msgfl = false;
  begintime = 123;  // ненулевое, чтобы видеть, что run_beer_program сбросил его в 0
  currentstepcnt = 7;
  alarm_c_min = 55;
  alarm_c_low_min = 66;
  startAutoTuneCalls = 0;
  beerFinishCalls = 0;
  sendMsgCalls = 0;
  setBuzzerCalls = 0;
}

// Состояние "после кипения": детектор уже накопил полную стабильную серию.
static void set_boiling_detector_post_boil_state() {
  boilingDetector.isBoiling = true;
  boilingDetector.stableCount = 255;
  boilingDetector.samplesFilled = TEMP_HISTORY_SIZE;
  boilingDetector.historyIndex = 3;
  boilingDetector.lastUpdateTime = 999999;
  for (int i = 0; i < TEMP_HISTORY_SIZE; i++) boilingDetector.tempHistory[i] = 99.0f;
}

// Переход C -> B (несмежная 'B'): предыдущая строка кипячением не была,
// значит это НОВОЕ кипячение на остывшей жидкости - детектор обязан сброситься.
static void test_transition_from_cooling_resets_detector() {
  reset_fixture();
  set_boiling_detector_post_boil_state();
  program[0].WType = 'C';
  program[1].WType = 'B';
  ProgramLen = 2;

  run_beer_program(1);

  check(ProgramNum == 1, "run_beer_program должен был перейти на строку 1");
  check(begintime == 0, "run_beer_program должен был сбросить begintime для новой строки");
  check(beerFinishCalls == 0, "переход на существующую строку не должен завершать программу");
  check(sendMsgCalls == 1, "run_beer_program должен был отправить уведомление о переходе");
  check(boilingDetector.isBoiling == false,
        "РЕГРЕСС: переход C->B (несмежное кипячение) не сбросил isBoiling");
  check(boilingDetector.stableCount == 0,
        "РЕГРЕСС: переход C->B (несмежное кипячение) не сбросил stableCount");
}

// Переход B -> B (смежная 'B'): продолжение уже идущего кипячения ради новой
// всыпки хмеля - накопленную стабильность детектора трогать нельзя.
static void test_adjacent_boiling_transition_keeps_detector() {
  reset_fixture();
  set_boiling_detector_post_boil_state();
  program[0].WType = 'B';
  program[1].WType = 'B';
  ProgramLen = 2;

  run_beer_program(1);

  check(ProgramNum == 1, "run_beer_program должен был перейти на строку 1");
  check(begintime == 0, "run_beer_program должен был сбросить begintime для новой строки");
  check(beerFinishCalls == 0, "переход на существующую строку не должен завершать программу");
  check(sendMsgCalls == 1, "run_beer_program должен был отправить уведомление о переходе");
  check(boilingDetector.isBoiling == true,
        "РЕГРЕСС: смежный переход B->B не должен был сбрасывать isBoiling");
  check(boilingDetector.stableCount == 255,
        "РЕГРЕСС: смежный переход B->B не должен был сбрасывать stableCount");
}

// Контрольный кейс: переход на строку, не являющуюся 'B' (например 'P'),
// вообще не должен трогать детектор - защита от мутации, сбрасывающей
// детектор на любом переходе строки.
static void test_non_boiling_transition_keeps_detector() {
  reset_fixture();
  set_boiling_detector_post_boil_state();
  program[0].WType = 'C';
  program[1].WType = 'P';
  ProgramLen = 2;

  run_beer_program(1);

  check(ProgramNum == 1, "run_beer_program должен был перейти на строку 1");
  check(begintime == 0, "run_beer_program должен был сбросить begintime для новой строки");
  check(beerFinishCalls == 0, "переход на существующую строку не должен завершать программу");
  check(sendMsgCalls == 1, "run_beer_program должен был отправить уведомление о переходе");
  check(boilingDetector.isBoiling == true,
        "РЕГРЕСС: переход на строку без кипячения не должен был сбрасывать isBoiling");
  check(boilingDetector.stableCount == 255,
        "РЕГРЕСС: переход на строку без кипячения не должен был сбрасывать stableCount");
}

int main() {
  test_transition_from_cooling_resets_detector();
  test_adjacent_boiling_transition_keeps_detector();
  test_non_boiling_transition_keeps_detector();
  if (failures != 0) return 1;
  std::cout << "beer.h boiling detector reset behaviour checks passed\n";
  return 0;
}
'''


def build_harness(beer_header_path: Path, runtime_helpers_path: Path) -> str:
    beer_source = beer_header_path.read_text(encoding="utf-8")
    runtime_source = runtime_helpers_path.read_text(encoding="utf-8")

    run_beer_program_body = extract_function_body(beer_source, RUN_BEER_PROGRAM_SIGNATURE)
    reset_boiling_detector_body = extract_function_body(beer_source, RESET_BOILING_DETECTOR_SIGNATURE)
    program_type_at_body = extract_function_body(runtime_source, PROGRAM_TYPE_AT_SIGNATURE)

    run_beer_program_fn = "void run_beer_program(uint8_t num) {" + run_beer_program_body + "}"

    harness = HARNESS_TEMPLATE.replace("@RUN_BEER_PROGRAM_BODY@", run_beer_program_fn)
    harness = harness.replace("@RESET_BOILING_DETECTOR_BODY@", reset_boiling_detector_body)
    harness = harness.replace("@PROGRAM_TYPE_AT_BODY@", program_type_at_body)
    return harness


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-boiling-reset-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_boiling_detector_reset_test.cpp"
        binary = temp / "beer_boiling_detector_reset_test"
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
        harness = build_harness(ROOT / "beer.h", ROOT / "runtime_helpers.h")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return compile_and_run(harness, "beer.h")


if __name__ == "__main__":
    raise SystemExit(main())
