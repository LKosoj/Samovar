#!/usr/bin/env python3
"""[П3-7] Поведенческая проверка get_detector_correction_step() (impurity_detector.h).

Шаг коррекции детектора теперь берётся из SamSetup.autospeed ("Процент изменения
скорости", 0-99%) вместо жёстко зашитых 5%/2%. Тест вытаскивает РЕАЛЬНОЕ тело
get_detector_correction_step() через extract_function_body - проверяется настоящая
формула клампа и дефолта, а не переписанная в тесте копия.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "inline float get_detector_correction_step()"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

struct SetupEEPROM {
  uint8_t autospeed = 0;
};

static SetupEEPROM SamSetup;

@GET_DETECTOR_CORRECTION_STEP_BODY@

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
  return diff < 0.0001f;
}

int main() {
  // Два разных "нормальных" значения процента дают разный шаг.
  SamSetup.autospeed = 5;
  check(nearly_equal(get_detector_correction_step(), 0.05f), "autospeed=5 должен дать шаг 0.05");

  SamSetup.autospeed = 15;
  check(nearly_equal(get_detector_correction_step(), 0.15f), "autospeed=15 должен дать шаг 0.15");

  // Кламп сверху: веб-форма допускает до 99%, шаг не должен превышать 20%.
  SamSetup.autospeed = 99;
  check(nearly_equal(get_detector_correction_step(), 0.20f), "autospeed=99 должен клампиться к 0.20");

  // Дефолт: 0 (не задано) -> 5%.
  SamSetup.autospeed = 0;
  check(nearly_equal(get_detector_correction_step(), 0.05f), "autospeed=0 должен давать дефолт 0.05");

  if (failures != 0) return 1;
  std::cout << "get_detector_correction_step behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    detector_source = (ROOT / "impurity_detector.h").read_text(encoding="utf-8")
    body = extract_function_body(detector_source, SIGNATURE)
    function = "inline float get_detector_correction_step() {" + body + "}"
    return HARNESS_TEMPLATE.replace("@GET_DETECTOR_CORRECTION_STEP_BODY@", function)


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-detector-correction-step-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "detector_correction_step_test.cpp"
        binary = temp / "detector_correction_step_test"
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
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
