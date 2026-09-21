#!/usr/bin/env python3
"""Доза I2C-насоса: шаги и итог берутся у подключённого насоса, а не у адреса 2."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")

HARNESS = r'''
#include <cstdint>
#include <iostream>
enum { I2CSTEPPER_V3_STOP_NONE = 0, I2CSTEPPER_V3_STOP_COMPLETE = 1, I2CSTEPPER_V3_STOP_REMOTE = 2,
       I2CSTEPPER_V3_STOP_LOCAL = 3, I2CSTEPPER_V3_STOP_SENSOR = 4, I2CSTEPPER_V3_STOP_HEARTBEAT = 5 };
static const uint32_t I2CSTEPPER_V3_TARGET_STEPS_MAX = 2000000000UL;
struct I2CStepperDevice {
  uint8_t address; bool present;
  struct { uint16_t stepsPerMl; } config;
  struct { uint8_t stopReason; } status;
};
// Два насоса на чётных адресах. Как в I2CStepper.h: в процессе насос закреплён за сессией
// (даже если пропал), вне процесса выбран наименьший подключённый.
static I2CStepperDevice pumps[2] = {{2, false, {100}, {0}}, {4, false, {400}, {0}}};
static I2CStepperDevice* sessionPump = nullptr;
I2CStepperDevice* i2c_stepper_selected_pump() {
  if (sessionPump) return sessionPump;
  for (I2CStepperDevice& pump : pumps) if (pump.present) return &pump;
  return nullptr;
}
enum I2CStepperDoseState : uint8_t { I2C_STEPPER_DOSE_RUNNING, I2C_STEPPER_DOSE_DONE, I2C_STEPPER_DOSE_FAILED };
inline I2CStepperDoseState second_i2c_pump_dose_state() {@STATE@}
inline uint32_t i2c_get_step_by_liquid_volume(float volumeMl) {@STEPS@}
static int failures = 0;
static void check(bool ok, const char* text) { if (!ok) { std::cerr << "FAIL: " << text << '\n'; ++failures; } }
int main() {
  check(second_i2c_pump_dose_state() == I2C_STEPPER_DOSE_FAILED, "доза без насоса не считается сбоем");
  check(i2c_get_step_by_liquid_volume(10.0f) == 0, "без насоса получены шаги");
  pumps[1].present = true;  // подключён только насос с адресом 4
  check(i2c_get_step_by_liquid_volume(10.0f) == 4000, "шаги посчитаны не по калибровке подключённого насоса 4");
  check(i2c_get_step_by_liquid_volume(2.5f) == 1000, "дробная доза посчитана неверно");
  check(i2c_get_step_by_liquid_volume(0.001f) == 0, "доза меньше одного шага принята");
  check(i2c_get_step_by_liquid_volume(0.0f) == 0 && i2c_get_step_by_liquid_volume(-1.0f) == 0,
        "нулевая или отрицательная доза принята");
  check(i2c_get_step_by_liquid_volume(6000000.0f) == 0, "доза больше предела Nano принята");
  pumps[1].config.stepsPerMl = 0;
  check(i2c_get_step_by_liquid_volume(10.0f) == 0, "неоткалиброванный насос выдал шаги");
  pumps[1].config.stepsPerMl = 400;
  pumps[1].status.stopReason = I2CSTEPPER_V3_STOP_NONE;
  pumps[0].status.stopReason = I2CSTEPPER_V3_STOP_COMPLETE;  // отключённый насос 2 не влияет
  check(second_i2c_pump_dose_state() == I2C_STEPPER_DOSE_RUNNING, "работающая доза не считается идущей");
  pumps[1].status.stopReason = I2CSTEPPER_V3_STOP_COMPLETE;
  check(second_i2c_pump_dose_state() == I2C_STEPPER_DOSE_DONE, "выданная доза не считается готовой");
  const uint8_t interrupted[] = {I2CSTEPPER_V3_STOP_REMOTE, I2CSTEPPER_V3_STOP_LOCAL,
                                 I2CSTEPPER_V3_STOP_SENSOR, I2CSTEPPER_V3_STOP_HEARTBEAT};
  for (uint8_t reason : interrupted) {
    pumps[1].status.stopReason = reason;
    check(second_i2c_pump_dose_state() == I2C_STEPPER_DOSE_FAILED, "прерванная доза не считается сбоем");
  }
  sessionPump = &pumps[1]; pumps[1].present = false; pumps[0].present = true;
  pumps[1].status.stopReason = I2CSTEPPER_V3_STOP_NONE;
  check(second_i2c_pump_dose_state() == I2C_STEPPER_DOSE_FAILED && i2c_get_step_by_liquid_volume(10.0f) == 0,
        "насос сессии пропал, а доза продолжается или подменена соседним насосом");
  sessionPump = nullptr;  // вне процесса выбран подключённый насос 2
  check(second_i2c_pump_dose_state() == I2C_STEPPER_DOSE_DONE && i2c_get_step_by_liquid_volume(10.0f) == 1000,
        "после смены насоса используется не подключённый");
  return failures == 0 ? 0 : 1;
}
'''


def passes(source: str, quiet: bool = False) -> bool:
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-dose-state-") as temp:
        cpp = Path(temp) / "test.cpp"
        binary = Path(temp) / "test"
        cpp.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", str(cpp), "-o", str(binary)],
            capture_output=True, text=True, check=False)
        if compiled.returncode != 0:
            raise AssertionError("harness did not compile\n" + compiled.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if result.returncode != 0 and not quiet:
            print(result.stderr, file=sys.stderr)
        return result.returncode == 0


def main() -> int:
    try:
        state = extract_function_body(SOURCE, "inline I2CStepperDoseState second_i2c_pump_dose_state()")
        steps = extract_function_body(SOURCE, "inline uint32_t i2c_get_step_by_liquid_volume(float volumeMl)")
        source = HARNESS.replace("@STATE@", state).replace("@STEPS@", steps)
        if not passes(source):
            return 1
        for old, new, label in (
            ("== I2CSTEPPER_V3_STOP_NONE) return I2C_STEPPER_DOSE_RUNNING",
             "!= I2CSTEPPER_V3_STOP_COMPLETE) return I2C_STEPPER_DOSE_RUNNING", "прерванная доза считается идущей"),
            ("? I2C_STEPPER_DOSE_DONE : I2C_STEPPER_DOSE_FAILED",
             "? I2C_STEPPER_DOSE_DONE : I2C_STEPPER_DOSE_DONE", "прерванная доза считается выданной"),
            ("!device->present) return I2C_STEPPER_DOSE_FAILED", "false) return I2C_STEPPER_DOSE_FAILED",
             "пропавший насос не замечен"),
            ("steps <= I2CSTEPPER_V3_TARGET_STEPS_MAX", "true", "доза больше предела"),
            ("!(volumeMl > 0.0f)", "false", "нулевая доза"),
        ):
            if old not in source:
                raise AssertionError("mutation anchor missing: " + old)
            if passes(source.replace(old, new, 1), quiet=True):
                print("FAIL: мутация не поймана: " + label, file=sys.stderr)
                return 1
    except (AssertionError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("OK: I2C pump dose steps and outcome follow the connected pump; mutations rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
