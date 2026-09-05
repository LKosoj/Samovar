#!/usr/bin/env python3
"""Проверяет ускорение и разворот GStepper2 без тяжёлых вызовов из ISR."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "libraries" / "GyverStepper" / "src"
HEADER = LIBRARY / "GyverStepper2.h"

ARDUINO_STUB = r"""
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdlib>
#define OUTPUT 1
inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline void delayMicroseconds(uint32_t) {}
inline uint32_t micros() { return 0; }
template <typename T> T constrain(T value, T low, T high) {
  return value < low ? low : (value > high ? high : value);
}
"""

HARNESS = r"""
#define GS_FAST_PROFILE 10
#include "GyverStepper2.h"
#include <algorithm>
#include <cstdio>

static bool run_to_target(GStepper2<STEPPER2WIRE>& stepper, int32_t target) {
  int32_t previous = stepper.getCurrent();
  bool movedForwardAfterRetarget = false;
  bool movedBackward = false;
  for (int i = 0; i < 200000 && stepper.getStatus(); ++i) {
    stepper.tickManual();
    int32_t current = stepper.getCurrent();
    movedForwardAfterRetarget |= current > previous;
    movedBackward |= current < previous;
    previous = current;
  }
  return !stepper.getStatus() && stepper.getCurrent() == target &&
         stepper.ready() && !stepper.ready() &&
         movedForwardAfterRetarget && movedBackward;
}

int main() {
  GStepper2<STEPPER2WIRE> stepper(200, 1, 2, 3);
  stepper.setMaxSpeed(1000);
  stepper.setAcceleration(200);
  stepper.setTarget(10000);
  for (int i = 0; i < 500; ++i) stepper.tickManual();
  int32_t retargetPosition = stepper.getCurrent();
  stepper.setTarget(-100);
  if (!run_to_target(stepper, -100)) {
    std::fprintf(stderr, "разворот с ускорением завершился неверно: start=%ld end=%ld status=%u\n",
                 static_cast<long>(retargetPosition),
                 static_cast<long>(stepper.getCurrent()), stepper.getStatus());
    return 1;
  }

  stepper.setCurrent(0);
  stepper.setTarget(800);
  uint32_t minPeriod = stepper.getPeriod();
  uint32_t maxPeriod = minPeriod;
  for (int i = 0; i < 200000 && stepper.getStatus(); ++i) {
    stepper.tickManual();
    minPeriod = std::min(minPeriod, stepper.getPeriod());
    maxPeriod = std::max(maxPeriod, stepper.getPeriod());
  }
  if (stepper.getCurrent() != 800 || !stepper.ready() || stepper.ready() ||
      minPeriod >= maxPeriod) {
    std::fprintf(stderr, "обычное движение с ускорением завершилось неверно\n");
    return 2;
  }

  stepper.setCurrent(0);
  stepper.setTarget(10000);
  stepper.setTarget(-1);
  for (int i = 0; i < 200000 && stepper.getStatus(); ++i) stepper.tickManual();
  if (stepper.getCurrent() != -1 || !stepper.ready() || stepper.ready()) {
    std::fprintf(stderr, "разворот с нулевым тормозным путём добавил лишний шаг\n");
    return 3;
  }

  stepper.setCurrent(0);
  stepper.setTarget(10000);
  for (int i = 0; i < 500; ++i) stepper.tickManual();
  stepper.setTarget(-100);
  stepper.pause();
  if (!run_to_target(stepper, -100)) {
    std::fprintf(stderr, "разворот после pause() не завершился как новое движение\n");
    return 4;
  }

  stepper.setCurrent(0);
  stepper.setAcceleration(400);
  stepper.setTarget(320);
  for (int i = 0; i < 200000 && stepper.getStatus(); ++i) stepper.tickManual();
  if (stepper.getCurrent() != 320 || !stepper.ready() || stepper.ready()) {
    std::fprintf(stderr, "второй профиль ускорения завершился неверно\n");
    return 5;
  }
  return 0;
}
"""


def compile_and_run(header: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="samovar-stepper-accel-") as temp_dir:
        temp = Path(temp_dir)
        (temp / "Arduino.h").write_text(ARDUINO_STUB, encoding="utf-8")
        (temp / "GyverStepper2.h").write_text(header, encoding="utf-8")
        shutil.copyfile(LIBRARY / "StepperCore.h", temp / "StepperCore.h")
        shutil.copyfile(LIBRARY / "GStypes.h", temp / "GStypes.h")
        harness = temp / "harness.cpp"
        binary = temp / "harness"
        harness.write_text(HARNESS, encoding="utf-8")
        compiled = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-Wno-sign-compare",
                "-Wno-type-limits",
                "-I",
                str(temp),
                str(harness),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            return [
                f"не собрался C++-харнесс настоящего GyverStepper2.h: {compiled.stderr.strip()}"
            ]
        executed = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        if executed.returncode != 0:
            return [
                f"C++-харнесс завершился с кодом {executed.returncode}: {executed.stderr.strip()}"
            ]
    return []


def validate(header: str) -> list[str]:
    errors: list[str] = []
    try:
        ticker = extract_function_body(header, "bool GS_ISR_INLINE tickManual()")
    except ValueError as error:
        return [str(error)]
    for forbidden in ("setTarget(", "makeMotionPlan(", "calcPlan(", "sqrt("):
        if forbidden in ticker:
            errors.append(
                f"tickManual() вызывает {forbidden}: расчёт маршрута всё ещё выполняется в ISR"
            )
    errors.extend(compile_and_run(header))
    return errors


def main() -> int:
    if shutil.which("g++") is None:
        print("FAIL: g++ не найден, невозможно проверить движение шагового двигателя")
        return 1

    header = HEADER.read_text(encoding="utf-8")
    errors = validate(header)

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    mutations = {
        "возврат setTarget() внутрь ISR": header.replace(
            "step();                 // шаг", "step(); setTarget(getTarget());", 1
        ),
        "не применяется подготовленный маршрут": header.replace(
            "applyMotionPlan(nextPlan);", "", 1
        ),
        "подготовленный маршрут не публикуется": header.replace(
            "nextPlanReady = true;", "nextPlanReady = false;", 1
        ),
        "после разворота сохраняется состояние паузы": header.replace(
            "status = 1;\n                        return status;",
            "return status;",
            1,
        ),
    }
    for name, mutant in mutations.items():
        if not validate(mutant):
            print(f"FAIL: проверка не обнаружила мутацию «{name}»")
            return 1

    print("PASS: ускорение и разворот работают без расчёта маршрута в ISR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
