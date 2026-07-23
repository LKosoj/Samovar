#!/usr/bin/env python3
"""Поведенческая проверка П2 п.4: guard от "шторма" старта beer_proc().

Раньше при взведённой защёлке безопасности нагрева (heater_safety_latched())
beer_proc() всё равно доходил до resetBoilingDetector()/create_data() (и, при
включённом USE_MQTT, до открытия MQTT-сессии) каждый тик, хотя set_power(true)
ниже по коду всё равно молча откажет - t.е. процесс не мог стартовать, но лог
и MQTT-сессия пересоздавались бы впустую на каждый вызов. Отдельно: если
set_power(true) не поднял PowerOn, раньше старт тихо обрывался без сообщения
пользователю. Тест вытаскивает РЕАЛЬНОЕ тело beer_proc() из beer.h через
extract_function_body и проверяет поведение (счётчики вызовов), а не факт
наличия строк в исходнике.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

BEER_PROC_SIGNATURE = "void beer_proc()"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };
enum SAMOVAR_STATUS { SAMOVAR_STATUS_IDLE = 0, SAMOVAR_STATUS_BEER = 1 };

using ProgramType = char;
constexpr uint8_t PROGRAM_MAX = 8;
constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;
constexpr int16_t SAMOVAR_STARTVAL_BEER_START = 2000;

struct WProgram {
  ProgramType WType = 0;
  uint8_t TempSensor = 0;
};

static WProgram program[PROGRAM_MAX];
static volatile SAMOVAR_STATUS SamovarStatusInt = SAMOVAR_STATUS_BEER;
static volatile int16_t startval = SAMOVAR_STARTVAL_BEER_START;
static volatile bool PowerOn = false;

void SendMsg(const String&, MESSAGE_TYPE) {}

static int cancelProcessStartCalls = 0;
static std::string lastCancelMessage;
void mode_cancel_process_start(const String& message) {
  cancelProcessStartCalls++;
  lastCancelMessage = message.value();
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
}

static int warnLogCloseFailedCalls = 0;
void mode_warn_log_close_failed() { warnLogCloseFailedCalls++; }

static bool validateProgramResult = true;
bool beer_validate_program(String&) { return validateProgramResult; }

struct DSSensor {
  float avgTemp = 20;
};
static DSSensor TankSensor;
static bool sensorValidResult = true;
bool sensor_valid(const DSSensor&) { return sensorValidResult; }
void beer_control_sensor(uint8_t, const DSSensor*& sensor, const char*& name) {
  sensor = &TankSensor;
  name = "куба";
}

static bool sensorFailedResult = false;
bool process_sensor_failed(const String&, const char*) { return sensorFailedResult; }

static bool powerTransitionActiveResult = false;
bool power_transition_active() { return powerTransitionActiveResult; }

static bool heaterSafetyLatchedResult = false;
bool heater_safety_latched() { return heaterSafetyLatchedResult; }

static int resetBoilingDetectorCalls = 0;
void resetBoilingDetector() { resetBoilingDetectorCalls++; }

static bool createDataResult = true;
static int createDataCalls = 0;
bool create_data() { createDataCalls++; return createDataResult; }

static bool setPowerSucceeds = true;
static int setPowerCalls = 0;
void set_power(bool state) {
  setPowerCalls++;
  if (state) PowerOn = setPowerSucceeds;
  else PowerOn = false;
}

static int runBeerProgramCalls = 0;
void run_beer_program(uint8_t) { runBeerProgramCalls++; }

#define portTICK_PERIOD_MS 1
void vTaskDelay(int) {}

@BEER_PROC_BODY@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  SamovarStatusInt = SAMOVAR_STATUS_BEER;
  startval = SAMOVAR_STARTVAL_BEER_START;
  PowerOn = false;
  cancelProcessStartCalls = 0;
  lastCancelMessage.clear();
  warnLogCloseFailedCalls = 0;
  validateProgramResult = true;
  sensorValidResult = true;
  sensorFailedResult = false;
  powerTransitionActiveResult = false;
  heaterSafetyLatchedResult = false;
  resetBoilingDetectorCalls = 0;
  createDataResult = true;
  createDataCalls = 0;
  setPowerSucceeds = true;
  setPowerCalls = 0;
  runBeerProgramCalls = 0;
}

// [P2 п.4] Защёлка безопасности нагрева взведена: старт должен быть отменён
// ДО resetBoilingDetector()/create_data() - иначе лог пересоздаётся впустую
// на каждый тик, пока set_power(true) ниже по коду всё равно молча откажет.
static void test_safety_latch_blocks_start_before_reset_and_create_data() {
  reset_fixture();
  heaterSafetyLatchedResult = true;

  beer_proc();

  check(cancelProcessStartCalls == 1, "РЕГРЕСС: взведённая защёлка безопасности не отменила старт затирания");
  check(lastCancelMessage.find("защёлк") != std::string::npos ||
        lastCancelMessage.find("Защёлк") != std::string::npos,
        "сообщение об отмене старта должно упоминать защёлку безопасности");
  check(resetBoilingDetectorCalls == 0, "РЕГРЕСС: взведённая защёлка не должна была доходить до resetBoilingDetector()");
  check(createDataCalls == 0, "РЕГРЕСС: взведённая защёлка не должна была доходить до create_data()");
  check(setPowerCalls == 0, "РЕГРЕСС: взведённая защёлка не должна была доходить до set_power()");
  check(runBeerProgramCalls == 0, "РЕГРЕСС: взведённая защёлка не должна была запускать run_beer_program()");
}

// [P2 п.4] set_power(true) не поднял PowerOn (например, safety-транзиция
// перехватила включение) - старт должен быть явно отменён с сообщением, а не
// тихо оборван без объяснения пользователю.
static void test_power_on_failure_cancels_start_with_message() {
  reset_fixture();
  setPowerSucceeds = false;

  beer_proc();

  check(setPowerCalls == 1, "set_power(true) должен был быть вызван");
  check(PowerOn == false, "PowerOn не должен был подняться в этом сценарии");
  check(cancelProcessStartCalls == 1, "РЕГРЕСС: неудачное включение питания не отменило старт затирания с сообщением");
  check(lastCancelMessage.find("питание") != std::string::npos,
        "сообщение об отмене старта должно упоминать невозможность включить питание");
  check(warnLogCloseFailedCalls == 1, "РЕГРЕСС: при отмене старта из-за питания лог не был закрыт (mode_warn_log_close_failed)");
  check(runBeerProgramCalls == 0, "РЕГРЕСС: run_beer_program() не должен был запускаться при не поднявшемся PowerOn");
}

// Контрольный случай: защёлка снята, питание включается успешно - процесс
// должен нормально стартовать, без отмены и без лишних предупреждений.
static void test_no_latch_and_power_success_starts_program() {
  reset_fixture();

  beer_proc();

  check(cancelProcessStartCalls == 0, "РЕГРЕСС: штатный старт не должен был отменяться");
  check(resetBoilingDetectorCalls == 1, "штатный старт должен был сбросить детектор кипения");
  check(createDataCalls == 1, "штатный старт должен был создать файл лога");
  check(setPowerCalls == 1, "штатный старт должен был включить питание");
  check(warnLogCloseFailedCalls == 0, "штатный старт не должен был предупреждать о закрытии лога");
  check(runBeerProgramCalls == 1, "РЕГРЕСС: штатный старт должен был запустить run_beer_program(0)");
}

int main() {
  test_safety_latch_blocks_start_before_reset_and_create_data();
  test_power_on_failure_cancels_start_with_message();
  test_no_latch_and_power_success_starts_program();
  if (failures != 0) return 1;
  std::cout << "beer.h beer_proc storm guard behaviour checks passed\n";
  return 0;
}
'''


def build_harness(beer_header_path: Path) -> str:
    beer_source = beer_header_path.read_text(encoding="utf-8")
    beer_proc_body = extract_function_body(beer_source, BEER_PROC_SIGNATURE)
    beer_proc_fn = "void beer_proc() {" + beer_proc_body + "}"
    return HARNESS_TEMPLATE.replace("@BEER_PROC_BODY@", beer_proc_fn)


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-proc-storm-guard-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_proc_storm_guard_test.cpp"
        binary = temp / "beer_proc_storm_guard_test"
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
