#!/usr/bin/env python3
"""Поведенческая проверка общего demand-gate протока в beer alarm-path."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <iostream>

static int beerCheckCoolingLimitsCalls = 0;
void beer_check_cooling_limits() { beerCheckCoolingLimitsCalls++; }

static int waterFlowEmergencyCalls = 0;
void mode_request_water_flow_emergency_if_needed() { waterFlowEmergencyCalls++; }

@MODE_ALARM_BEER@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  mode_alarm_beer();
  check(beerCheckCoolingLimitsCalls == 1,
        "beer alarm должен всегда проверять температурные пределы охлаждения");
  check(waterFlowEmergencyCalls == 1,
        "beer alarm должен делегировать контроль протока общему demand-gate");
  if (failures != 0) return 1;
  std::cout << "beer flow alarm delegates to shared demand gate\n";
  return 0;
}
'''


def compile_and_run(source: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-flow-") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / "beer_flow.cpp"
        binary_path = temp / "beer_flow"
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source_path),
                "-o",
                str(binary_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode
        result = subprocess.run(
            [str(binary_path)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode


def main() -> int:
    source = (ROOT / "mode_registry.h").read_text(encoding="utf-8")
    body = extract_function_body(source, "inline void mode_alarm_beer()")
    function = "void mode_alarm_beer() {" + body + "}"
    if "water_pulse_count_set" in body:
        print("FAIL: beer alarm всё ещё подменяет реальные импульсы протока", file=sys.stderr)
        return 1
    return compile_and_run(HARNESS_TEMPLATE.replace("@MODE_ALARM_BEER@", function))


if __name__ == "__main__":
    raise SystemExit(main())
