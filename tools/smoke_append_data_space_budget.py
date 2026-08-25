#!/usr/bin/env python3
"""Поведенческая проверка append_data() (FS.ino): бюджет свободного места проверяется
при ЛЮБОМ исходе записи, а не только при успешной.

[T19 п.17] Раньше проверка свободного места и уборка data_old.csv жили ВНУТРИ ветки
успешной записи (written != 0 - то есть ЛЮБАЯ ненулевая запись, включая частичную при
почти полном диске). Получалось, что уборка недостижима именно тогда, когда нужнее
всего: диск почти полон -> запись частичная -> written != 0 всё равно true (кроме
случая written==0) -> код "успеха" срабатывает, а если бы и не сработал (written==0),
блок уборки был ПОСЛЕ него и тоже не выполнялся.

Теперь enforce_data_log_free_space_budget() вызывается ПЕРВЫМ действием внутри
"if (changedField > 0)" - до захвата лока, до проверки файла, до самой записи - поэтому
уборка/предупреждение срабатывают независимо от исхода записи. Условие успеха записи
тоже ужесточено: println(const String&) ядра ESP32 = print(s) (s.length() байт) +
println() ("\r\n", 2 байта), так что полный успех - это written == str.length() + 2,
а не просто written != 0.

Тела enforce_data_log_free_space_budget() и append_data() (FS.ino) вытаскиваются через
extract_function_body дословно и подставляются в host-харнесс (образец -
tools/smoke_append_data_field_selection.py). Порог DATA_LOG_CLEANUP_THRESHOLD_BYTES
тоже вытаскивается из FS.ino как есть - тест не дублирует число руками.

Каждый сценарий запускается в ОТДЕЛЬНОМ процессе (через argv), а не в одном main():
enforce_data_log_free_space_budget() держит внутри function-local static счётчики
(space_check_countdown, memory_warning_sent), которые иначе переносились бы между
сценариями одного запуска и искажали бы результат первого же полного пересчёта
used_byte = SPIFFS.usedBytes().

Три сценария (все обязательны):
  а) частичная запись -> append_data() вернул "" и LogPrevTemp НЕ обновился (значение
     повторится на следующем такте, а не потеряется молча);
  б) свободно 5000 байт (строго между старым порогом 400 и новым
     DATA_LOG_CLEANUP_THRESHOLD_BYTES) и data_old.csv существует -> SPIFFS.remove вызван;
  в) мало места И запись одновременно проваливается -> уборка всё равно случилась
     (доказывает, что проверка вызывается ДО записи, а не зависит от её исхода).
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

APPEND_DATA_SIGNATURE = "String append_data() {"
BUDGET_SIGNATURE = "static void enforce_data_log_free_space_budget() {"
THRESHOLD_NAME = "DATA_LOG_CLEANUP_THRESHOLD_BYTES"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>

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
  size_t length() const { return value_.size(); }
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
static String Crt = "2026-08-24T00:00:00";
static float bme_pressure = 0.0f;
static float bme_prev_pressure = 0.0f;
static uint8_t ProgramNum = 0;
static uint8_t prev_ProgramNum = 0;
static volatile uint32_t log_write_seq = 0;
static uint32_t used_byte = 0;
static uint32_t total_byte = 100000;

#define WRITE_PROGNUM_IN_LOG

// Заглушка форматирования: реальный format_float (sensorinit.h) не является
// предметом этого теста.
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
  // Управляет сценарием (а)/(в): при true println() отдаёт content.length() байт БЕЗ
  // завершающих "\r\n" - ровно та частичная запись, которую старое условие
  // (written != 0) молча принимало за успех.
  bool simulate_partial_write = false;
  operator bool() const { return ok; }
  size_t println(const String& text) {
    if (simulate_partial_write) return text.length();
    return text.length() + 2;
  }
};
static FileStub fileToAppend;

static int removeCalls = 0;
static bool data_old_exists = false;
struct SpiffsStub {
  uint32_t usedBytes() { return used_byte; }
  bool exists(const char* path) {
    if (std::string(path) == "/data_old.csv") return data_old_exists;
    return false;
  }
  bool remove(const char* path) {
    if (std::string(path) == "/data_old.csv") removeCalls++;
    return true;
  }
};
static SpiffsStub SPIFFS;

static int sendMsgCalls = 0;
static void SendMsg(const String& text, MESSAGE_TYPE type) {
  (void)text;
  (void)type;
  sendMsgCalls++;
}

@THRESHOLD_DECL@

static void enforce_data_log_free_space_budget() {
@BUDGET_BODY@
}

String append_data() {
@APPEND_BODY@
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
  fileToAppend.ok = true;
  fileToAppend.simulate_partial_write = false;
  data_old_exists = false;
  removeCalls = 0;
  sendMsgCalls = 0;
  used_byte = 0;
  total_byte = 100000;
}

// (а) частичная запись -> append_data() вернул "" и LogPrevTemp НЕ обновился.
static void scenario_a_partial_write() {
  reset_fixture();
  PipeSensor.avgTemp = 55.5f;  // изменился -> changedField=2, запись пойдёт
  total_byte = 100000;
  used_byte = 0;  // места достаточно - эта проверка не о пороге, а об условии успеха записи
  fileToAppend.simulate_partial_write = true;

  String result = append_data();

  check(result.length() == 0,
        "РЕГРЕСС: частичная запись (written < str.length()+2) должна вернуть \"\", "
        "а не приниматься за успех");
  check(PipeSensor.LogPrevTemp == 20.0f,
        "РЕГРЕСС: LogPrevTemp обновился, хотя запись была частичной - значение "
        "потеряется молча вместо повтора на следующем такте");
}

// (б) свободно 5000 байт (между старым порогом 400 и новым DATA_LOG_CLEANUP_THRESHOLD_BYTES),
// data_old.csv существует -> SPIFFS.remove вызван.
static void scenario_b_cleanup_between_old_and_new_threshold() {
  reset_fixture();
  WaterSensor.avgTemp = 33.0f;  // изменился -> changedField=3, запись пойдёт
  total_byte = 100000;
  used_byte = 95000;  // total_byte - used_byte == 5000
  data_old_exists = true;
  fileToAppend.simulate_partial_write = false;  // запись успешна - уборка всё равно должна сработать

  String result = append_data();

  check(result.length() > 0, "запись в этом сценарии должна быть успешной (проверяем не её)");
  check(removeCalls == 1,
        "РЕГРЕСС: при 5000 свободных байт (между старым порогом 400 и новым "
        "DATA_LOG_CLEANUP_THRESHOLD_BYTES) уборка data_old.csv не сработала - "
        "старый порог 400 здесь недостаточен, нужен новый");
}

// (в) мало места И запись проваливается одновременно -> уборка всё равно случилась,
// потому что enforce_data_log_free_space_budget() вызывается ДО попытки записи.
static void scenario_c_cleanup_even_when_write_fails() {
  reset_fixture();
  TankSensor.avgTemp = 44.0f;  // изменился -> changedField=4, запись пойдёт
  total_byte = 100000;
  used_byte = 99900;  // total_byte - used_byte == 100, меньше любого из порогов
  data_old_exists = true;
  fileToAppend.simulate_partial_write = true;  // запись провалится

  String result = append_data();

  check(result.length() == 0, "запись в этом сценарии должна провалиться (проверяем не её)");
  check(removeCalls == 1,
        "РЕГРЕСС: уборка не выполнилась при провалившейся записи - значит проверка "
        "места по-прежнему зависит от исхода записи, а не выполняется первым действием");
}

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: <binary> <a|b|c>\n";
    return 2;
  }
  const std::string scenario = argv[1];
  if (scenario == "a") {
    scenario_a_partial_write();
  } else if (scenario == "b") {
    scenario_b_cleanup_between_old_and_new_threshold();
  } else if (scenario == "c") {
    scenario_c_cleanup_even_when_write_fails();
  } else {
    std::cerr << "unknown scenario: " << scenario << "\n";
    return 2;
  }
  if (failures != 0) return 1;
  std::cout << "scenario " << scenario << " passed\n";
  return 0;
}
'''


def extract_top_level_const(source: str, name: str) -> str:
    marker = f"uint32_t {name}"
    idx = source.find(marker)
    if idx < 0:
        raise ValueError(f"constant not found: {name}")
    start = source.rfind("static const", 0, idx)
    if start < 0:
        raise ValueError(f"constant declaration prefix not found: {name}")
    end = source.find(";", idx)
    if end < 0:
        raise ValueError(f"constant declaration not terminated: {name}")
    return source[start : end + 1]


def build_harness(fs_ino_path: Path) -> str:
    source = fs_ino_path.read_text(encoding="utf-8")
    append_body = extract_function_body(source, APPEND_DATA_SIGNATURE)
    budget_body = extract_function_body(source, BUDGET_SIGNATURE)
    threshold_decl = extract_top_level_const(source, THRESHOLD_NAME)

    match = re.search(r"=\s*(\d+)", threshold_decl)
    if not match:
        raise ValueError(f"could not parse numeric value out of: {threshold_decl}")
    threshold_value = int(match.group(1))
    # Сценарий (б) полагается на 5000 как значение СТРОГО между старым порогом (400) и
    # новым DATA_LOG_CLEANUP_THRESHOLD_BYTES. Если константа когда-нибудь опустится
    # до/ниже 5000, сценарий перестанет проверять то, что заявлено в докстринге - лучше
    # упасть здесь явно, чем молча проверять не то.
    if not (400 < 5000 < threshold_value):
        raise ValueError(
            f"DATA_LOG_CLEANUP_THRESHOLD_BYTES = {threshold_value} больше не оставляет "
            "5000 байт строго между старым порогом (400) и новым - сценарий (б) нужно "
            "пересчитать"
        )

    harness = HARNESS_TEMPLATE
    harness = harness.replace("@THRESHOLD_DECL@", threshold_decl)
    harness = harness.replace("@BUDGET_BODY@", budget_body)
    harness = harness.replace("@APPEND_BODY@", append_body)
    return harness


def compile_harness(harness: str, temp_dir: Path) -> Path:
    source = temp_dir / "append_data_space_budget_test.cpp"
    binary = temp_dir / "append_data_space_budget_test"
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
        raise RuntimeError("compilation failed")
    return binary


def run_scenario(binary: Path, scenario: str) -> int:
    run_result = subprocess.run([str(binary), scenario], capture_output=True, text=True, check=False)
    sys.stdout.write(run_result.stdout)
    sys.stderr.write(run_result.stderr)
    return run_result.returncode


def main() -> int:
    try:
        harness = build_harness(ROOT / "FS.ino")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-append-data-space-budget-") as temp_dir:
        try:
            binary = compile_harness(harness, Path(temp_dir))
        except RuntimeError:
            return 1

        # Каждый сценарий - отдельный процесс: enforce_data_log_free_space_budget()
        # держит внутри function-local static счётчики, их нельзя делить между сценариями.
        exit_code = 0
        for scenario in ("a", "b", "c"):
            code = run_scenario(binary, scenario)
            if code != 0:
                exit_code = 1
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
