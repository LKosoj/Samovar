#!/usr/bin/env python3
"""Проверяет, что GStepper2 сохраняет новую цель и на ранних выходах setTarget()."""

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEPPER_DIR = ROOT / "libraries" / "GyverStepper" / "src"
HEADER = STEPPER_DIR / "GyverStepper2.h"

ARDUINO_STUB = r"""
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdlib>
using std::abs;
template <typename T>
T constrain(T value, T low, T high) {
  return value < low ? low : (value > high ? high : value);
}
inline uint32_t micros() { return 0; }
inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, bool) {}
inline void delayMicroseconds(uint32_t) {}
#define OUTPUT 1
"""

HARNESS = r"""
#include <cstdlib>
#include <iostream>
#include "GyverStepper2.h"

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
  }
}

int main() {
  GStepper2<STEPPER2WIRE, STEPPER_VIRTUAL> stepper(200);

  stepper.setMaxSpeed(100);
  stepper.setCurrent(0);
  stepper.setTarget(500);
  stepper.brake();
  stepper.setTarget(0);
  check(stepper.getTarget() == 0,
        "setTarget(0) обязан очистить цель, когда текущая позиция уже равна нулю");

  stepper.setTarget(500);
  stepper.brake();
  stepper.setMaxSpeed(0);
  stepper.setTarget(0);
  check(stepper.getTarget() == 0,
        "setTarget(0) обязан очистить цель и при нулевой максимальной скорости");
}
"""


def compile_and_run(header_text: str, name: str, report_failure: bool = True) -> bool:
    with tempfile.TemporaryDirectory(prefix=f"samovar_{name}_") as temp_name:
        temp = Path(temp_name)
        (temp / "Arduino.h").write_text(ARDUINO_STUB, encoding="utf-8")
        for source_name in ("StepperCore.h", "GStypes.h"):
            (temp / source_name).write_bytes((STEPPER_DIR / source_name).read_bytes())
        (temp / "GyverStepper2.h").write_text(header_text, encoding="utf-8")
        (temp / "harness.cpp").write_text(HARNESS, encoding="utf-8")
        binary = temp / "harness"
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-Wno-type-limits",
             "-I", str(temp),
             str(temp / "harness.cpp"), "-o", str(binary)],
            text=True,
            capture_output=True,
        )
        if compile_result.returncode != 0:
            print(compile_result.stdout, end="", file=sys.stderr)
            print(compile_result.stderr, end="", file=sys.stderr)
            return False
        run_result = subprocess.run([str(binary)], text=True, capture_output=True, check=False)
        if run_result.returncode != 0 and report_failure:
            print(run_result.stdout, end="", file=sys.stderr)
            print(run_result.stderr, end="", file=sys.stderr)
        return run_result.returncode == 0


header_text = HEADER.read_text(encoding="utf-8")
if not compile_and_run(header_text, "baseline"):
    print("stepper reset target smoke FAILED", file=sys.stderr)
    sys.exit(1)

anchor = (
    "        int32_t requestedTar = (type == RELATIVE) ? ntar + pos : ntar;\n"
    "        tar = requestedTar;\n"
)
if header_text.count(anchor) != 1:
    print("stepper reset target smoke FAILED: mutation anchor missing", file=sys.stderr)
    sys.exit(1)

mutation = anchor.replace("        tar = requestedTar;\n", "")
if compile_and_run(header_text.replace(anchor, mutation, 1), "mutation", report_failure=False):
    print("stepper reset target smoke FAILED: target-assignment mutation survived", file=sys.stderr)
    sys.exit(1)

print("stepper reset target checks passed")
