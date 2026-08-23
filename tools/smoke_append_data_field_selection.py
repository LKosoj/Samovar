#!/usr/bin/env python3
"""Поведенческая проверка append_data() (FS.ino): «первое изменившееся поле».

append_data() раньше был цепочкой if/else if по четырём датчикам, потом по
давлению, потом по номеру программы: "первый, кто изменился с прошлой
записи в лог - тот и решает, что писать и чей LogPrevTemp/bme_prev_pressure/
prev_ProgramNum обновить". Свёртка первых четырёх веток в цикл с break легко
могла бы перепутать пару (датчик, его позиция в CSV) - тест ловит именно
это, а не общий факт "что-то записалось".

Тело append_data() (FS.ino) вытаскивается через extract_function_body
дословно и подставляется в host-харнесс (образец -
tools/smoke_alarm_tank_overheat_escalation.py). Внешние зависимости
(SPIFFS/File/log_file_lock/format_float/SendMsg/vTaskDelay/...) - заглушки,
как и в образце; сама логика выбора победившего поля и порядок колонок CSV -
код, скопированный компилятором из настоящего файла, не переписанный тестом.

Два инварианта (оба обязательны):
  1) меняется только Pipe -> в CSV-строке все четыре температуры в порядке
     Steam,Pipe,Water,Tank, и LogPrevTemp обновляется ТОЛЬКО у Pipe.
  2) одновременно меняются Water и давление -> побеждает Water (датчики
     проверяются раньше давления), bme_prev_pressure НЕ обновляется.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

FUNCTION_SIGNATURE = "String append_data() {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using TickType_t = int;
#define pdMS_TO_TICKS(x) (x)
#define portTICK_PERIOD_MS 1
#define F(x) (x)

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String(int v) : value_(std::to_string(v)) {}
  String(unsigned v) : value_(std::to_string(v)) {}
  String(unsigned long v) : value_(std::to_string(v)) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  String& operator+=(const char* text) { value_ += (text ? text : ""); return *this; }
  String& operator+=(const String& other) { value_ += other.value_; return *this; }
  String& operator+=(int v) { value_ += std::to_string(v); return *this; }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

static String operator+(const char* lhs, const String& rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.value());
}

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

struct DSSensor {
  float avgTemp = 0.0f;
  float LogPrevTemp = 0.0f;
};

static const uint8_t DS_LOGGED_SENSOR_COUNT = 4;

static DSSensor SteamSensor;
static DSSensor PipeSensor;
static DSSensor WaterSensor;
static DSSensor TankSensor;

DSSensor* const sensorList[DS_LOGGED_SENSOR_COUNT] = {
    &SteamSensor, &PipeSensor, &WaterSensor, &TankSensor};

static bool data_log_ready = true;
static String Crt = "2026-08-23T00:00:00";
static float bme_pressure = 0.0f;
static float bme_prev_pressure = 0.0f;
static uint8_t ProgramNum = 0;
static uint8_t prev_ProgramNum = 0;
static volatile uint32_t log_write_seq = 0;
static uint32_t used_byte = 0;
static uint32_t total_byte = 100000;

#define WRITE_PROGNUM_IN_LOG

// Заглушка форматирования: реальный format_float (sensorinit.h) не является
// предметом этого теста, важно лишь, что каждое число превращается в СВОЙ
// узнаваемый текст, чтобы проверять порядок колонок CSV.
static String format_float(float v, int d) {
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%.*f", d, v);
  return String(buf);
}

static bool log_file_lock(TickType_t timeout = pdMS_TO_TICKS(50)) { (void)timeout; return true; }
static void log_file_unlock(bool locked) { (void)locked; }

static void vTaskDelay(int ticks) { (void)ticks; }

struct SerialStub {
  void println(const char* text) { (void)text; }
};
static SerialStub Serial;

struct FileStub {
  bool ok = true;
  operator bool() const { return ok; }
  size_t println(const String& text) { (void)text; return 1; }
};
static FileStub fileToAppend;

struct SpiffsStub {
  uint32_t usedBytes() { return used_byte; }
  bool exists(const char*) { return false; }
  bool remove(const char*) { return true; }
};
static SpiffsStub SPIFFS;

static int sendMsgCalls = 0;
static void SendMsg(const String& text, MESSAGE_TYPE type) {
  (void)text;
  (void)type;
  sendMsgCalls++;
}

String append_data() {
@BODY@
}

static int failures = 0;

static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  SteamSensor.avgTemp = 20.0f;
  PipeSensor.avgTemp = 20.0f;
  WaterSensor.avgTemp = 20.0f;
  TankSensor.avgTemp = 20.0f;
  SteamSensor.LogPrevTemp = 20.0f;
  PipeSensor.LogPrevTemp = 20.0f;
  WaterSensor.LogPrevTemp = 20.0f;
  TankSensor.LogPrevTemp = 20.0f;
  bme_pressure = 750.0f;
  bme_prev_pressure = 750.0f;
  ProgramNum = 3;
  prev_ProgramNum = 3;
  data_log_ready = true;
  sendMsgCalls = 0;
}

static std::vector<std::string> split_csv(const std::string& csv) {
  std::vector<std::string> fields;
  std::string current;
  for (char ch : csv) {
    if (ch == ',') {
      fields.push_back(current);
      current.clear();
    } else {
      current += ch;
    }
  }
  fields.push_back(current);
  return fields;
}

// Инвариант 1: меняется только Pipe -> все четыре температуры в CSV в
// порядке Steam,Pipe,Water,Tank, LogPrevTemp обновился только у Pipe.
static void test_pipe_only_change_orders_columns_and_updates_only_pipe() {
  reset_fixture();
  PipeSensor.avgTemp = 55.5f;  // изменился, остальные - нет

  String result = append_data();
  std::vector<std::string> fields = split_csv(result.value());

  check(fields.size() >= 6, "CSV-строка должна содержать дату + 4 температуры + давление");
  if (fields.size() >= 6) {
    check(fields[1] == "20.000", "Steam должен остаться прежним и стоять в колонке 2");
    check(fields[2] == "55.500", "Pipe должен быть изменённым значением и стоять в колонке 3");
    check(fields[3] == "20.000", "Water должен остаться прежним и стоять в колонке 4");
    check(fields[4] == "20.000", "Tank должен остаться прежним и стоять в колонке 5");
    check(fields[5] == "750.00", "давление должно остаться прежним и стоять в колонке 6");
  }

  check(PipeSensor.LogPrevTemp == 55.5f, "LogPrevTemp у Pipe должен обновиться до нового значения");
  check(SteamSensor.LogPrevTemp == 20.0f, "LogPrevTemp у Steam не должен измениться");
  check(WaterSensor.LogPrevTemp == 20.0f, "LogPrevTemp у Water не должен измениться");
  check(TankSensor.LogPrevTemp == 20.0f, "LogPrevTemp у Tank не должен измениться");
  check(bme_prev_pressure == 750.0f, "bme_prev_pressure не должен измениться, когда победил датчик");
}

// Инвариант 2: одновременно меняются Water и давление -> побеждает Water
// (датчики проверяются раньше давления), давление не "уезжает".
static void test_water_and_pressure_together_water_wins() {
  reset_fixture();
  WaterSensor.avgTemp = 33.25f;  // изменился
  bme_pressure = 760.0f;          // тоже изменилось

  String result = append_data();

  check(WaterSensor.LogPrevTemp == 33.25f, "LogPrevTemp у Water должен обновиться - Water победил");
  check(bme_prev_pressure == 750.0f,
        "РЕГРЕСС: bme_prev_pressure не должен обновляться, когда датчик меняется одновременно с давлением");
  check(SteamSensor.LogPrevTemp == 20.0f, "LogPrevTemp у Steam не должен измениться");
  check(PipeSensor.LogPrevTemp == 20.0f, "LogPrevTemp у Pipe не должен измениться");
  check(TankSensor.LogPrevTemp == 20.0f, "LogPrevTemp у Tank не должен измениться");
  (void)result;
}

int main() {
  test_pipe_only_change_orders_columns_and_updates_only_pipe();
  test_water_and_pressure_together_water_wins();
  if (failures != 0) return 1;
  std::cout << "append_data field-selection behaviour checks passed\n";
  return 0;
}
'''


def build_harness(fs_ino_path: Path) -> str:
    source = fs_ino_path.read_text(encoding="utf-8")
    body = extract_function_body(source, FUNCTION_SIGNATURE)
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-append-data-field-selection-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "append_data_field_selection_test.cpp"
        binary = temp / "append_data_field_selection_test"
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
        harness = build_harness(ROOT / "FS.ino")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return compile_and_run(harness, "FS.ino")


if __name__ == "__main__":
    raise SystemExit(main())
