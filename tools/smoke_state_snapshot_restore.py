#!/usr/bin/env python3
"""Снимок последнего состояния (/state.csv): сохранение программы и её возврат после сбоя.

Жалоба с форума на 6.26/6.27: устройство уходило в перезагрузку, "соответственно все
программы сбрасываются". Механизм записи /state.csv существовал, но писал только четыре
режима, не содержал даже номера режима и никем не читался - ни прошивкой, ни интерфейсом.

Тест собирает РЕАЛЬНЫЕ функции снимка из FS.ino (запись, период, разбор, чтение) и
Samovar.ino (восстановление и отчёт) поверх мока файловой системы и НАСТОЯЩЕГО
program_io.h. Проверяется поведение:
  - период записи выдерживается, а в простое файл переписывается только когда
    программа действительно изменилась (иначе снимок жёг бы флеш круглые сутки);
  - запись и чтение сходятся: программа переживает "перезагрузку" через файл;
  - снимок чужого режима не подставляется в текущий буфер программы;
  - предупреждение уходит только если в снимке нагрев был включён;
  - файл прежнего формата (без номера режима) и переросший файл отвергаются.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

# (файл, сигнатура) - функции, которые харнесс обязан взять из исходника, а не повторить.
EXTRACTED = [
    ("FS.ino", "static uint32_t state_snapshot_hash_bytes(uint32_t hash, const void* data, size_t len)"),
    ("FS.ino", "static uint32_t state_snapshot_program_signature()"),
    ("FS.ino", "static String state_snapshot_header()"),
    ("FS.ino", "bool write_state_snapshot()"),
    ("FS.ino", "void process_state_snapshot()"),
    ("FS.ino", "void state_snapshot_mark_saved()"),
    ("FS.ino", "static bool state_snapshot_field(const String& header, const char* key, String& value)"),
    ("FS.ino", "static bool state_snapshot_uint8(const String& header, const char* key, uint8_t& value)"),
    ("FS.ino", "bool read_state_snapshot(StateSnapshot& snapshot)"),
    ("Samovar.ino", "static void restore_state_snapshot()"),
    ("Samovar.ino", "static void state_snapshot_report_pending()"),
]

ARDUINO_STUB = r'''
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>

#define F(text) (text)

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(char value) : value_(1, value) {}
  String(unsigned char value) : value_(std::to_string(value)) {}
  String(unsigned short value) : value_(std::to_string(value)) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  String(unsigned long value) : value_(std::to_string(value)) {}
  String(signed char value) : value_(std::to_string(value)) {}
  String(short value) : value_(std::to_string(value)) {}
  String(int value) : value_(std::to_string(value)) {}
  String(long value) : value_(std::to_string(value)) {}
  String(float value) : value_(format_float(value)) {}
  String(double value) : value_(format_float(value)) {}

  size_t length() const { return value_.length(); }
  const char* c_str() const { return value_.c_str(); }
  char charAt(size_t index) const { return value_.at(index); }
  void reserve(size_t size) { value_.reserve(size); }
  const std::string& std_str() const { return value_; }

  int indexOf(char needle, int from) const {
    if (from < 0) from = 0;
    if (static_cast<size_t>(from) > value_.size()) return -1;
    const size_t found = value_.find(needle, static_cast<size_t>(from));
    return found == std::string::npos ? -1 : static_cast<int>(found);
  }

  String substring(int from) const {
    if (from < 0) from = 0;
    if (static_cast<size_t>(from) >= value_.size()) return String();
    return String(value_.substr(static_cast<size_t>(from)));
  }

  String substring(int from, int to) const {
    if (from < 0) from = 0;
    if (to < from) return String();
    if (static_cast<size_t>(from) >= value_.size()) return String();
    return String(value_.substr(static_cast<size_t>(from), static_cast<size_t>(to - from)));
  }

  bool startsWith(const String& prefix) const {
    return value_.compare(0, prefix.value_.size(), prefix.value_) == 0;
  }

  bool operator==(const String& other) const { return value_ == other.value_; }

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
'''

HARNESS = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#include "Arduino.h"

#define __SAMOVAR_H_
#define CAPACITY_NUM 10
#include "program_types.h"

struct WProgram {
  ProgramType WType;
  uint16_t Volume;
  float Speed;
  uint8_t capacity_num;
  float Temp;
  float Power;
  uint8_t TempSensor;
  float Time;
};

WProgram program[PROGRAM_MAX];
volatile uint8_t ProgramLen = 0;

enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE,
};

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };

#include "string_utils.h"
#include "program_io.h"

// ---- Состояние прошивки, от которого зависит снимок ----
@SNAPSHOT_STRUCT@
@STARTVAL_IDLE@

volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
volatile int16_t SamovarStatusInt = 0;
volatile int16_t startval = 0;
volatile uint8_t ProgramNum = 0;
volatile bool PowerOn = false;
String WthdrwTimeS;
uint8_t STcnt = 0;

struct FakeSensor { float avgTemp = 0; };
static FakeSensor TankSensor;
static FakeSensor SteamSensor;

static int liquidVolumeFixture = 0;
static int get_liquid_volume() { return liquidVolumeFixture; }

static String format_float(float value, int decimals) {
  char buffer[32] = {0};
  std::snprintf(buffer, sizeof(buffer), "%.*f", decimals, static_cast<double>(value));
  return String(buffer);
}

// ---- Мок файловой системы: один файл в памяти ----
class File {
 public:
  File() = default;
  File(std::string* storage, bool writable)
      : storage_(storage), valid_(true), writable_(writable) {}

  explicit operator bool() const { return valid_; }

  size_t size() const { return storage_ ? storage_->size() : 0; }

  size_t println(const String& value) {
    if (!valid_ || !writable_ || !storage_) return 0;
    *storage_ += value.std_str();
    *storage_ += "\n";
    return value.length() + 1;
  }

  size_t print(const String& value) {
    if (!valid_ || !writable_ || !storage_) return 0;
    *storage_ += value.std_str();
    return value.length();
  }

  String readStringUntil(char terminator) {
    if (!valid_ || !storage_) return String();
    const size_t found = storage_->find(terminator, pos_);
    if (found == std::string::npos) {
      String rest(storage_->substr(pos_));
      pos_ = storage_->size();
      return rest;
    }
    String line(storage_->substr(pos_, found - pos_));
    pos_ = found + 1;
    return line;
  }

  String readString() {
    if (!valid_ || !storage_ || pos_ >= storage_->size()) return String();
    String rest(storage_->substr(pos_));
    pos_ = storage_->size();
    return rest;
  }

  void close() { valid_ = false; }

 private:
  std::string* storage_ = nullptr;
  size_t pos_ = 0;
  bool valid_ = false;
  bool writable_ = false;
};

#define FILE_WRITE "w"
#define FILE_READ "r"

struct FakeFilesystem {
  std::string data;
  bool present = false;
  bool failOpen = false;

  File open(const char* path, const char* mode) {
    (void)path;
    if (failOpen) return File();
    if (std::strcmp(mode, FILE_WRITE) == 0) {
      data.clear();
      present = true;
      return File(&data, true);
    }
    if (!present) return File();
    return File(&data, false);
  }
};

static FakeFilesystem SPIFFS;

// ---- Мок примитивов синхронизации и вывода ----
#define pdMS_TO_TICKS(ms) (ms)
static bool logFileLockAvailable = true;
static int logFileLockDepth = 0;
static bool log_file_lock(unsigned long timeout) {
  (void)timeout;
  if (!logFileLockAvailable) return false;
  logFileLockDepth++;
  return true;
}
static void log_file_unlock(bool locked) {
  if (locked) logFileLockDepth--;
}

struct FakeSerial {
  void print(const String&) {}
  void println(const String&) {}
  void print(const char*) {}
  void println(const char*) {}
};
static FakeSerial Serial;

static int sendMsgCalls = 0;
static MESSAGE_TYPE lastMsgType = NONE_MSG;
static String lastMsgText;
static void SendMsg(const String& message, MESSAGE_TYPE type) {
  sendMsgCalls++;
  lastMsgType = type;
  lastMsgText = message;
}

static int consoleLogCalls = 0;
static void WriteConsoleLog(const String&) { consoleLogCalls++; }

// Отложенный текст предупреждения живёт в Samovar.ino рядом с restore_state_snapshot.
static String pendingStateSnapshotNotice;

// ---- Реальный код под тестом ----
@STATE_SNAPSHOT_CONSTANTS@

static int writeSnapshotCalls = 0;

@EXTRACTED_FUNCTIONS@

// ---- Тесты ----
static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static bool nearly_equal(float a, float b) {
  float diff = a - b;
  if (diff < 0) diff = -diff;
  return diff < 0.01f;
}

static void seed_rect_program() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = {};
  program[0].WType = 'H';
  program[0].Volume = 500;
  program[0].Speed = 0.6f;
  program[0].capacity_num = 1;
  program[0].Temp = 78.5f;
  program[0].Power = 210.0f;
  program[1].WType = 'B';
  program[1].Volume = 4000;
  program[1].Speed = 2.4f;
  program[1].capacity_num = 2;
  program[1].Temp = 0.0f;
  program[1].Power = 220.0f;
  program[2].WType = 'T';
  program[2].Volume = 1500;
  program[2].Speed = 3.0f;
  program[2].capacity_num = 3;
  program[2].Temp = 93.0f;
  program[2].Power = 230.0f;
  ProgramLen = 3;
}

static void tick_snapshot(int times) {
  for (int i = 0; i < times; i++) process_state_snapshot();
}

static void reset_world() {
  SPIFFS.data.clear();
  SPIFFS.present = false;
  SPIFFS.failOpen = false;
  logFileLockAvailable = true;
  logFileLockDepth = 0;
  writeSnapshotCalls = 0;
  sendMsgCalls = 0;
  consoleLogCalls = 0;
  lastMsgText = String();
  pendingStateSnapshotNotice = String();
  state_snapshot_program_hash = 0;
  STcnt = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  PowerOn = false;
  ProgramNum = 0;
  SamovarStatusInt = 0;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  WthdrwTimeS = String("00:00:00");
  liquidVolumeFixture = 0;
}

int main() {
  // 1. Период выдерживается: до STATE_SNAPSHOT_PERIOD_S тиков файла не касаемся.
  reset_world();
  seed_rect_program();
  startval = 1;  // сессия идёт
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S - 1);
  check(writeSnapshotCalls == 0, "раньше срока снимок писаться не должен");
  tick_snapshot(1);
  check(writeSnapshotCalls == 1, "на STATE_SNAPSHOT_PERIOD_S-м тике снимок обязан записаться");
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S);
  check(writeSnapshotCalls == 2, "работающая сессия пишет снимок каждый период");

  // 2. В простое файл переписывается только при изменении программы.
  reset_world();
  seed_rect_program();
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S);
  check(writeSnapshotCalls == 1, "первый снимок в простое нужен: на диске ещё чужое состояние");
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S * 3);
  check(writeSnapshotCalls == 1, "в простое без правок программы снимок переписывать нечем");
  program[1].Speed = 1.9f;  // владелец поправил программу
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S);
  check(writeSnapshotCalls == 2, "правка программы обязана попасть в снимок и без запуска сессии");
  ProgramLen = 2;
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S);
  check(writeSnapshotCalls == 3, "изменение числа строк - тоже правка программы");

  // 3. Нагрев без отбора (Пиво/Сувид на выдержке) считается работающей сессией.
  reset_world();
  seed_rect_program();
  Samovar_Mode = SAMOVAR_BEER_MODE;
  PowerOn = true;
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S);
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S);
  check(writeSnapshotCalls == 2, "при включённом нагреве снимок обновляется каждый период");

  // 4. Круг "запись - перезагрузка - чтение - восстановление".
  reset_world();
  seed_rect_program();
  ProgramNum = 1;
  PowerOn = true;
  startval = 1;
  SamovarStatusInt = 10;
  liquidVolumeFixture = 1250;
  check(write_state_snapshot(), "снимок обязан записаться");
  const std::string savedFile = SPIFFS.data;

  program_clear();  // "перезагрузка": буфер программы пуст
  check(ProgramLen == 0, "перед восстановлением программа должна быть пустой");
  PowerOn = false;
  ProgramNum = 0;
  restore_state_snapshot();
  check(ProgramLen == 3, "программа из снимка должна вернуться целиком");
  check(program[0].WType == 'H' && program[2].WType == 'T', "типы строк должны совпасть");
  check(nearly_equal(program[0].Temp, 78.5f), "температура строки должна совпасть");
  check(nearly_equal(program[1].Speed, 2.4f), "скорость строки должна совпасть");
  check(program[2].Volume == 1500, "объём строки должен совпасть");
  check(pendingStateSnapshotNotice.length() > 0, "о прерванной сессии нужно предупредить");
  check(sendMsgCalls == 0, "предупреждение уходит не из restore, а из отчёта в конце setup");
  state_snapshot_report_pending();
  check(sendMsgCalls == 1, "отчёт обязан отправить предупреждение");
  check(lastMsgType == WARNING_MSG, "предупреждение о прерванной сессии - не тревога");
  check(consoleLogCalls == 1, "предупреждение должно попасть и в журнал");
  state_snapshot_report_pending();
  check(sendMsgCalls == 1, "повторный отчёт не должен дублировать предупреждение");

  // 5. Восстановленная программа считается уже сохранённой: файл не переписывается.
  writeSnapshotCalls = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  tick_snapshot(STATE_SNAPSHOT_PERIOD_S * 2);
  check(writeSnapshotCalls == 0, "после восстановления в простое переписывать снимок нечем");

  // 6. Снимок чужого режима не подставляется в текущий буфер.
  reset_world();
  seed_rect_program();
  Samovar_Mode = SAMOVAR_BEER_MODE;
  ProgramNum = 1;
  PowerOn = true;
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = {};
  program[0].WType = 'P';
  program[0].Temp = 62.0f;
  program[0].Time = 60.0f;
  program[0].capacity_num = 0;
  program[0].Speed = 0;
  program[0].Volume = 0;
  program[0].Power = 0;
  program[0].TempSensor = 1;
  ProgramLen = 1;
  check(write_state_snapshot(), "снимок режима Пиво обязан записаться");

  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;  // владелец сменил режим до перезагрузки
  seed_rect_program();
  restore_state_snapshot();
  check(ProgramLen == 3, "программа текущего режима не должна пострадать от чужого снимка");
  check(program[0].WType == 'H', "чужой снимок не должен подменять строки программы");
  check(pendingStateSnapshotNotice.length() == 0, "о чужом снимке предупреждать не о чем");

  // 7. Нагрев в снимке выключен: программу вернуть, но не тревожить.
  reset_world();
  seed_rect_program();
  ProgramNum = 2;
  PowerOn = false;
  check(write_state_snapshot(), "снимок без нагрева тоже пишется");
  program_clear();
  restore_state_snapshot();
  check(ProgramLen == 3, "программа возвращается независимо от нагрева");
  check(pendingStateSnapshotNotice.length() == 0, "выключились штатно - предупреждать не о чем");

  // 8. Файл прежнего формата (без номера режима) читать нечем.
  reset_world();
  seed_rect_program();
  SPIFFS.data = "P=1;V=0.00\n";
  SPIFFS.present = true;
  StateSnapshot legacy;
  check(!read_state_snapshot(legacy), "снимок без режима обязан быть отвергнут");
  restore_state_snapshot();
  check(ProgramLen == 3, "старый снимок не должен трогать программу");

  // 9. Переросший файл - мусор, читать его нельзя.
  reset_world();
  SPIFFS.data = std::string("M=0;P=1;H=1\n") + std::string(STATE_SNAPSHOT_MAX_BYTES + 1, 'X');
  SPIFFS.present = true;
  StateSnapshot oversized;
  check(!read_state_snapshot(oversized), "файл больше предела обязан быть отвергнут");

  // 10. Занятый файл: снимок пропускаем, прежнее содержимое цело.
  reset_world();
  seed_rect_program();
  check(write_state_snapshot(), "первый снимок обязан записаться");
  const std::string before = SPIFFS.data;
  logFileLockAvailable = false;
  check(!write_state_snapshot(), "при занятом файле снимок должен вернуть отказ");
  check(SPIFFS.data == before, "неудачная попытка не должна портить прежний снимок");
  logFileLockAvailable = true;
  check(logFileLockDepth == 0, "лок обязан отпускаться на всех путях");

  // 11. Заголовок снимка несёт режим, статус, строку и признак нагрева.
  reset_world();
  seed_rect_program();
  Samovar_Mode = SAMOVAR_NBK_MODE;
  SamovarStatusInt = 4001;
  ProgramNum = 2;
  PowerOn = true;
  startval = 4001;
  const String header = state_snapshot_header();
  String field;
  check(state_snapshot_field(header, "M", field) && field == String("4"), "режим обязан быть в снимке");
  check(state_snapshot_field(header, "S", field) && field == String("4001"), "статус обязан быть в снимке");
  check(state_snapshot_field(header, "P", field) && field == String("3"), "номер строки 1-based");
  check(state_snapshot_field(header, "L", field) && field == String("3"), "длина программы обязана быть в снимке");
  check(state_snapshot_field(header, "H", field) && field == String("1"), "признак нагрева обязан быть в снимке");
  check(!state_snapshot_field(header, "ZZ", field), "несуществующее поле не должно находиться");

  if (failures != 0) return 1;
  std::cout << "state snapshot restore behaviour checks passed\n";
  return 0;
}
'''


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def extract_snapshot_struct(samovar_h: str) -> str:
    match = re.search(r"struct StateSnapshot \{.*?\n\};", samovar_h, re.S)
    if not match:
        raise ValueError("Samovar.h: struct StateSnapshot не найдена")
    return match.group(0)


def extract_startval_idle(samovar_h: str) -> str:
    match = re.search(r"constexpr int16_t SAMOVAR_STARTVAL_IDLE\s*=\s*\d+;", samovar_h)
    if not match:
        raise ValueError("Samovar.h: SAMOVAR_STARTVAL_IDLE не найдена")
    return match.group(0)


def extract_constants(fs_ino: str) -> str:
    tokens = [
        r'static const char\* const STATE_SNAPSHOT_FILE = "[^"]+";',
        r"static const uint8_t STATE_SNAPSHOT_PERIOD_S = \d+;",
        r"static const size_t STATE_SNAPSHOT_MAX_BYTES = \d+;",
        r"static uint32_t state_snapshot_program_hash = \d+;",
    ]
    found = []
    for token in tokens:
        match = re.search(token, fs_ino)
        if not match:
            raise ValueError(f"FS.ino: не найдена константа снимка ({token})")
        found.append(match.group(0))
    return "\n".join(found)


def extract_functions() -> str:
    sources = {name: read(name) for name in {relative for relative, _ in EXTRACTED}}
    parts = []
    for relative, signature in EXTRACTED:
        body = extract_function_body(sources[relative], signature)
        # write_state_snapshot в харнессе ещё и считает вызовы: счётчик нужен тестам
        # про период, а сама запись остаётся настоящей.
        if signature == "bool write_state_snapshot()":
            body = "\n  writeSnapshotCalls++;" + body
        parts.append(f"{signature} {{{body}}}\n")
    return "\n".join(parts)


def build_harness() -> str:
    samovar_h = read("Samovar.h")
    fs_ino = read("FS.ino")
    harness = HARNESS
    harness = harness.replace("@SNAPSHOT_STRUCT@", extract_snapshot_struct(samovar_h))
    harness = harness.replace("@STARTVAL_IDLE@", extract_startval_idle(samovar_h))
    harness = harness.replace("@STATE_SNAPSHOT_CONSTANTS@", extract_constants(fs_ino))
    harness = harness.replace("@EXTRACTED_FUNCTIONS@", extract_functions())
    return harness


def static_checks() -> list[str]:
    errors: list[str] = []
    fs_ino = strip_cpp_comments(read("FS.ino"))
    samovar_ino = strip_cpp_comments(read("Samovar.ino"))

    # Снимок отвязан от журнала: append_data() к state.csv больше не прикасается.
    append_body = extract_function_body(fs_ino, "String append_data()")
    if "state.csv" in append_body:
        errors.append("append_data всё ещё пишет state.csv - снимок должен быть отдельным")

    # Программа в /prg.csv пишется для всех режимов, а не для перечисленных вручную.
    create_body = extract_function_body(fs_ino, "bool create_data()")
    if "serialize_program_for_mode(Samovar_Mode)" not in create_body:
        errors.append("create_data должна писать программу через serialize_program_for_mode")
    for token in ("get_beer_program()", "get_dist_program()", "get_nbk_program()"):
        if token in create_body:
            errors.append(f"create_data снова перечисляет режимы вручную: {token}")

    # Снимок пишется из SysTicker и не спрятан под гейт активного отбора.
    ticker_body = extract_function_body(samovar_ino, "void triggerSysTicker(void *parameter)")
    snapshot_call = ticker_body.find("process_state_snapshot();")
    startval_gate = ticker_body.find("if (startval != SAMOVAR_STARTVAL_IDLE)")
    if snapshot_call == -1:
        errors.append("triggerSysTicker не вызывает process_state_snapshot")
    elif startval_gate != -1 and snapshot_call > startval_gate:
        errors.append("process_state_snapshot попал под гейт активного отбора")

    # Восстановление - после загрузки дефолтной программы режима, отчёт - в конце setup.
    setup_body = extract_function_body(samovar_ino, "void setup()")
    default_load = setup_body.find("load_default_program_for_mode(Samovar_Mode)")
    restore_call = setup_body.find("restore_state_snapshot();")
    report_call = setup_body.find("state_snapshot_report_pending();")
    if default_load == -1 or restore_call == -1:
        errors.append("setup не восстанавливает снимок после загрузки дефолтной программы")
    elif restore_call < default_load:
        errors.append("restore_state_snapshot вызывается до дефолтной программы - её затрёт дефолт")
    if report_call == -1:
        errors.append("setup не публикует отчёт о прерванной сессии")
    elif report_call < restore_call:
        errors.append("отчёт публикуется раньше восстановления")

    # Нагрев по снимку не возобновляется: восстановление не трогает питание.
    restore_body = extract_function_body(samovar_ino, "static void restore_state_snapshot()")
    for token in ("PowerOn = true", "set_power", "start_heating"):
        if token in restore_body:
            errors.append(f"restore_state_snapshot трогает нагрев: {token}")
    return errors


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-state-snapshot-") as temp_dir:
        temp = Path(temp_dir)
        (temp / "Arduino.h").write_text(ARDUINO_STUB, encoding="utf-8")
        source = temp / "state_snapshot_test.cpp"
        binary = temp / "state_snapshot_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{temp}",
                f"-I{ROOT}",
                str(source),
                "-o",
                str(binary),
            ],
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

    exit_code = compile_and_run(harness)

    errors = static_checks()
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    if errors:
        return 1
    if exit_code == 0:
        print("state snapshot static checks passed")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
