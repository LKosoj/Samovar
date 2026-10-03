#!/usr/bin/env python3
"""Файл пишется раз в 16 секунд, сервер получает свежие показания раз в 4.

Исполняет блок настоящего SysTicker и сборщик текущих показаний из FS.ino.
Отказ записи файла не должен менять частоту отправки на сервер.
"""
import re
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
using String = std::string;
@CONSTANTS@
struct Sensor { float avgTemp; };
Sensor SteamSensor, PipeSensor, WaterSensor, TankSensor;
float bme_pressure;
uint8_t ProgramNum;
int second;
bool fileAvailable;
std::vector<int> fileTimes, serverTimes;
std::vector<String> serverLines;

// Форматирование зависит от всех переданных показаний, а не возвращает константу.
static String format_log_base_fields(const float values[], float pressure, uint8_t row, bool fileLog) {
  (void)fileLog;
  String result;
  for (uint8_t i = 0; i < DS_LOGGED_SENSOR_COUNT; ++i)
    result += std::to_string(static_cast<int>(values[i])) + ",";
  return result + std::to_string(static_cast<int>(pressure)) + "," + std::to_string(row);
}
static String build_current_log_base_line() { @BASE_BODY@ }
String append_data() {
  fileTimes.push_back(second);
  return fileAvailable ? build_current_log_base_line() : String();
}
void tick_publish_log_line(const String& line) {
  if (line.empty()) return;
  serverTimes.push_back(second);
  serverLines.push_back(line);
}
constexpr int SAMOVAR_STARTVAL_IDLE = 0;
int startval;
uint8_t tcntST = 0;
void tick() { @TICK_BLOCK@ }
void check(bool ok, const char* message) {
  if (!ok) { std::cerr << message << '\n'; std::exit(1); }
}
void run(bool available, int seconds) {
  fileAvailable = available;
  fileTimes.clear(); serverTimes.clear(); serverLines.clear();
  tcntST = 0;
  startval = 1;
  for (second = 1; second <= seconds; ++second) {
    SteamSensor.avgTemp = 100 + second;
    PipeSensor.avgTemp = 200 + second;
    WaterSensor.avgTemp = 300 + second;
    TankSensor.avgTemp = 400 + second;
    bme_pressure = 500 + second;
    ProgramNum = second;
    tick();
  }
  check(fileTimes.size() == static_cast<size_t>(seconds / 16),
        "file interval must be 16 seconds");
  check(serverTimes.size() == static_cast<size_t>(seconds / 4),
        "server interval must remain 4 seconds even when file writing fails");
  for (size_t i = 0; i < fileTimes.size(); ++i)
    check(fileTimes[i] == static_cast<int>((i + 1) * 16), "wrong file write time");
  for (size_t i = 0; i < serverTimes.size(); ++i)
    check(serverTimes[i] == static_cast<int>((i + 1) * 4), "wrong server publish time");
  check(serverLines[0] == "104,204,304,404,504,4", "server must sample current readings at 4 seconds");
  check(serverLines[1] == "108,208,308,408,508,8", "server must sample new readings at 8 seconds");
  startval = SAMOVAR_STARTVAL_IDLE;
  const auto filesBefore = fileTimes.size(), serverBefore = serverTimes.size();
  for (int i = 0; i < 24; ++i) tick();
  check(fileTimes.size() == filesBefore && serverTimes.size() == serverBefore,
        "active log intervals must not run while idle");
}
int main() {
  run(true, 36);
  run(false, 24);
}
'''


def main():
    header = (ROOT / "Samovar.h").read_text()
    fs = (ROOT / "FS.ino").read_text()
    ticker = extract_function_body(
        (ROOT / "Samovar.ino").read_text(), "void triggerSysTicker(void *parameter)"
    )
    token = "if (startval != SAMOVAR_STARTVAL_IDLE)"
    _, end = extract_braced_block_after(ticker, token)
    block = ticker[ticker.index(token):end]
    base = extract_function_body(fs, "static String build_current_log_base_line()")
    constants = "\n".join(
        re.search(rf"static const(?:expr)? uint8_t {name} = \d+;", source).group()
        for name, source in [
            ("LOG_PERIOD_S", header), ("FILE_LOG_PERIOD_S", header),
            ("DS_LOGGED_SENSOR_COUNT", fs),
        ]
    )
    harness = (HARNESS.replace("@CONSTANTS@", constants)
               .replace("@BASE_BODY@", base).replace("@TICK_BLOCK@", block))
    mutations = [
        ("file interval", harness.replace("FILE_LOG_PERIOD_S = 16", "FILE_LOG_PERIOD_S = 4"),
         "file interval must be 16 seconds"),
        ("server interval", harness.replace("LOG_PERIOD_S = 4", "LOG_PERIOD_S = 16"),
         "server interval must remain 4 seconds"),
        ("file coupling", harness.replace("tick_publish_log_line(build_current_log_base_line());",
                                          "tick_publish_log_line(append_data());"),
         "file interval must be 16 seconds"),
        ("stale sensor", harness.replace("SteamSensor.avgTemp, PipeSensor.avgTemp",
                                         "0, PipeSensor.avgTemp"),
         "server must sample current readings"),
    ]
    with tempfile.TemporaryDirectory(prefix="samovar-log-intervals-") as tmp:
        source = Path(tmp) / "test.cpp"
        binary = Path(tmp) / "test"
        for name, code, expected in [("baseline", harness, None), *mutations]:
            if name != "baseline" and code == harness:
                raise AssertionError(f"{name}: mutation anchor missing")
            source.write_text(code)
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True, capture_output=True, text=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            if expected is None:
                assert result.returncode == 0, result.stderr
            else:
                assert result.returncode != 0 and expected in result.stderr, (
                    f"{name}: mutation survived or failed for an unrelated reason: {result.stderr}"
                )
    print("PASS: file 16s, server 4s, fresh readings, file failure, idle; 4 mutations caught")


if __name__ == "__main__":
    main()
