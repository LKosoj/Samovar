#!/usr/bin/env python3
"""Поведенчески проверяет обе средние скорости НБК на независимых интервалах."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>

struct StatsProbe {
  float avgSpeed;
  float avgActiveSpeed;
  float totalVolume;
  float activeVolume;
  uint32_t startTime;
  uint32_t activeFeedMs;
};
static StatsProbe stats = {};
static uint32_t now = 0;
uint32_t millis() { return now; }

static void calculate_averages() {
@BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static bool near(float lhs, float rhs) { return std::fabs(lhs - rhs) < 0.001f; }
static void check_case(
    float totalVolume, float activeVolume, uint32_t totalMs, uint32_t activeMs,
    float expectedSession, float expectedActive) {
  stats = {};
  stats.startTime = 1000;
  now = stats.startTime + totalMs;
  stats.totalVolume = totalVolume;
  stats.activeVolume = activeVolume;
  stats.activeFeedMs = activeMs;
  calculate_averages();
  check(near(stats.avgSpeed, expectedSession), "средняя по сессии рассчитана неверно");
  check(near(stats.avgActiveSpeed, expectedActive), "средняя при работающем насосе рассчитана неверно");
}
int main() {
  check_case(10.0f, 8.0f, 2UL * 60 * 60 * 1000, 60UL * 60 * 1000, 5.0f, 8.0f);
  check_case(3.0f, 1.5f, 15UL * 60 * 1000, 5UL * 60 * 1000, 12.0f, 18.0f);
  return failures == 0 ? 0 : 1;
}
'''


def formulas(source: str) -> str:
    body = extract_function_body(source, "void nbk_finish_common(bool resetWorkState) {")
    start = body.index("uint32_t totalTime =")
    end = body.index("\n\n  if (stats.startTime > 0)", start)
    return body[start:end].replace("\r\n", "\n")


def run(body: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-stats-averages-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "test.cpp"
        binary = temp / "test"
        source.write_text(HARNESS.replace("@BODY@", body), encoding="utf-8")
        build = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if build.returncode:
            if emit:
                sys.stderr.write(build.stderr)
            return build.returncode
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
        return result.returncode


def main() -> int:
    try:
        body = formulas((ROOT / "nbk.h").read_text(encoding="utf-8"))
    except (ValueError, IndexError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if run(body, True) != 0:
        return 1
    mutations = (
        body.replace("(stats.totalVolume * 3600.0) / (float)totalTime", "stats.totalVolume", 1),
        body.replace("stats.activeVolume * 3600000.0f / stats.activeFeedMs", "stats.activeVolume", 1),
    )
    if any(mutation == body for mutation in mutations):
        print("FAIL: average formula mutation anchor missing", file=sys.stderr)
        return 1
    for mutation in mutations:
        if run(mutation, False) == 0:
            print("FAIL: average formula mutation survived", file=sys.stderr)
            return 1
    print("nbk session and active average speed checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
