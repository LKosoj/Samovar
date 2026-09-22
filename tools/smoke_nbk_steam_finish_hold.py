#!/usr/bin/env python3
"""Проверяет минутную выдержку Тп > 98°C перед завершением НБК."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cstdint>
#include <iostream>

enum MESSAGE_TYPE { NOTIFY_MSG = 2 };
enum SamovarCommands { SAMOVAR_POWER = 1 };
struct SensorProbe { float avgTemp; };
static SensorProbe SteamSensor{0};
static uint32_t fakeMillis = 0;
static uint32_t nbk_end_steam_start_time = 0;
static uint32_t nbk_dry_steam_start_time = 0;
static int queueCalls = 0;
static int messageCalls = 0;
static int emergencyCalls = 0;

uint32_t millis() { return fakeMillis; }
void SendMsg(const char*, MESSAGE_TYPE) { messageCalls++; }
bool queue_samovar_command(SamovarCommands) { queueCalls++; return true; }
void request_emergency_stop(const char*) { emergencyCalls++; }

static bool check_steam() {
@BODY@
  return false;
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(uint32_t now) {
  fakeMillis = now;
  SteamSensor.avgTemp = 98.1f;
  nbk_end_steam_start_time = 0;
  nbk_dry_steam_start_time = 77;
  queueCalls = 0;
  messageCalls = 0;
  emergencyCalls = 0;
}

int main() {
  reset_fixture(1000);
  check(!check_steam() && nbk_end_steam_start_time == 1000,
        "первое превышение должно только запустить отсчёт");
  fakeMillis = 60999;
  check(!check_steam() && queueCalls == 0,
        "до полной минуты завершения быть не должно");
  SteamSensor.avgTemp = 98.0f;
  check(!check_steam() && nbk_end_steam_start_time == 0,
        "возврат к 98°C должен сбросить отсчёт");

  reset_fixture(70000);
  check(!check_steam(), "новый отсчёт не должен завершать Оптимизацию сразу");
  fakeMillis = 129999;
  check(!check_steam(), "59999 мс недостаточно для завершения");
  fakeMillis = 130000;
  check(check_steam() && queueCalls == 1 && messageCalls == 1 && emergencyCalls == 0,
        "60 секунд непрерывного превышения должны штатно завершить НБК");

  return failures == 0 ? 0 : 1;
}
'''


def build_harness(source: str) -> str:
    alarm = extract_function_body(source, "bool check_nbk_critical_alarms() {")
    body, _ = extract_braced_block_after(alarm, "if (currentType != 'S') {")
    return HARNESS.replace("@BODY@", body)


def compile_and_run(source: str, emit: bool) -> int:
    harness = build_harness(source)
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-steam-hold-") as temp_dir:
        cpp = Path(temp_dir) / "test.cpp"
        binary = Path(temp_dir) / "test"
        cpp.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            if emit:
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    if compile_and_run(source, True) != 0:
        return 1

    mutations = (
        source.replace(">= 60000", ">= 0", 1),
        source.replace(
            "} else {\n      nbk_end_steam_start_time = 0;",
            "} else {",
            1,
        ),
    )
    if any(mutated == source for mutated in mutations):
        print("FAIL: NBK steam hold mutation anchor missing", file=sys.stderr)
        return 1
    for mutated in mutations:
        if compile_and_run(mutated, False) == 0:
            print("FAIL: NBK steam hold mutation survived", file=sys.stderr)
            return 1

    print("NBK steam finish 60-second hold checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
