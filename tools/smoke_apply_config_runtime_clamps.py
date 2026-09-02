#!/usr/bin/env python3
"""Поведенческая проверка двух клэмпов в Samovar.ino::apply_config_runtime():

  - StepperStepMl == 0 -> STEPPER_STEP_ML (Б1.2: насос отбора не откалиброван,
    без клэмпа TargetStepps в run_program() всегда 0, и переход строки по
    объёму в ректификации никогда не наступит).
  - PackDens вне 60..100 -> 80 (Б9: форма расчёта колонны column_math.h ожидает
    плотность насадки строго в этом диапазоне).

Сейчас ни одна из этих двух строк не вызывается ни одним тестом - удаление
любой из них пройдёт незамеченным. Извлекается РЕАЛЬНЫЙ код через
extract_function_body(apply_config_runtime) - проверяется настоящая логика
(с сохранённым STEPPER_STEP_ML, прочитанным из Samovar_pin.h), а не
переписанная в тесте копия. Samovar.ino только читается, не редактируется.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "void apply_config_runtime()"
STEPPER_LINE = "if (SamSetup.StepperStepMl == 0) SamSetup.StepperStepMl = STEPPER_STEP_ML;"
PACKDENS_LINE = "if (SamSetup.PackDens < 60 || SamSetup.PackDens > 100) SamSetup.PackDens = 80;"

COMMON_PRELUDE = r'''
#include <cstdint>
#include <iostream>

struct SetupEEPROM {
  uint16_t StepperStepMl;
  uint8_t PackDens;
};
static SetupEEPROM SamSetup;

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    failures++;
  }
}
'''


def read_stepper_step_ml_default() -> int:
    source = (ROOT / "Samovar_pin.h").read_text(encoding="utf-8")
    match = re.search(r"#define\s+STEPPER_STEP_ML\s+(\d+)", source)
    if not match:
        raise ValueError("STEPPER_STEP_ML define not found in Samovar_pin.h")
    return int(match.group(1))


def extract_clamp_lines(ino_source: str) -> str:
    body = extract_function_body(ino_source, SIGNATURE)
    if STEPPER_LINE not in body:
        raise ValueError(f"clamp line not found in apply_config_runtime(): {STEPPER_LINE}")
    if PACKDENS_LINE not in body:
        raise ValueError(f"clamp line not found in apply_config_runtime(): {PACKDENS_LINE}")
    return STEPPER_LINE + "\n  " + PACKDENS_LINE


def build_harness(clamp_lines: str, stepper_default: int) -> str:
    return COMMON_PRELUDE + f"\nstatic const uint16_t STEPPER_STEP_ML = {stepper_default};\n" + r'''
static void apply_clamps() {
  ''' + clamp_lines + r'''
}

int main() {
  // StepperStepMl == 0 (насос не откалиброван) -> заводская калибровка.
  SamSetup.StepperStepMl = 0;
  SamSetup.PackDens = 80;
  apply_clamps();
  check(SamSetup.StepperStepMl == STEPPER_STEP_ML,
        "StepperStepMl==0 обязан подтягиваться к STEPPER_STEP_ML");

  // Ненулевое значение (в т.ч. отличное от заводского) - клэмп не должен его трогать.
  SamSetup.StepperStepMl = 777;
  apply_clamps();
  check(SamSetup.StepperStepMl == 777,
        "РЕГРЕСС: ненулевой StepperStepMl не должен подменяться клэмпом");

  // PackDens ниже 60 -> заводской дефолт 80.
  SamSetup.StepperStepMl = 500;
  SamSetup.PackDens = 10;
  apply_clamps();
  check(SamSetup.PackDens == 80, "PackDens < 60 обязан подтягиваться к 80");

  // PackDens выше 100 -> заводской дефолт 80.
  SamSetup.PackDens = 250;
  apply_clamps();
  check(SamSetup.PackDens == 80, "PackDens > 100 обязан подтягиваться к 80");

  // Границы диапазона включительно валидны - клэмп их трогать не должен.
  SamSetup.PackDens = 60;
  apply_clamps();
  check(SamSetup.PackDens == 60, "РЕГРЕСС: PackDens==60 (нижняя граница) не должен клэмпиться");

  SamSetup.PackDens = 100;
  apply_clamps();
  check(SamSetup.PackDens == 100, "РЕГРЕСС: PackDens==100 (верхняя граница) не должен клэмпиться");

  if (failures != 0) return 1;
  std::cout << "apply_config_runtime clamp checks passed\n";
  return 0;
}
'''


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-apply-config-clamps-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "clamps_test.cpp"
        binary = temp / "clamps_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compiled.stdout)
            sys.stderr.write(compiled.stderr)
            return compiled.returncode
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(f"[{label}] ")
        sys.stdout.write(ran.stdout)
        sys.stderr.write(ran.stderr)
        return ran.returncode


def main() -> int:
    ino_source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    stepper_default = read_stepper_step_ml_default()
    try:
        clamp_lines = extract_clamp_lines(ino_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rc = compile_and_run(build_harness(clamp_lines, stepper_default), "apply_config_runtime clamps")
    if rc != 0:
        return rc

    # --- Мутация: убираем клэмп StepperStepMl - тест обязан покраснеть.
    mutated_stepper = clamp_lines.replace(STEPPER_LINE, "")
    if mutated_stepper == clamp_lines:
        print("FAIL: mutation anchor missing (StepperStepMl clamp)", file=sys.stderr)
        return 1
    mutation_rc = compile_and_run(
        build_harness(mutated_stepper, stepper_default), "mutation: StepperStepMl clamp removed"
    )
    if mutation_rc == 0:
        print("FAIL: mutation (removed StepperStepMl clamp) survived", file=sys.stderr)
        return 1

    # --- Мутация: убираем клэмп PackDens - тест обязан покраснеть.
    mutated_packdens = clamp_lines.replace(PACKDENS_LINE, "")
    if mutated_packdens == clamp_lines:
        print("FAIL: mutation anchor missing (PackDens clamp)", file=sys.stderr)
        return 1
    mutation_rc2 = compile_and_run(
        build_harness(mutated_packdens, stepper_default), "mutation: PackDens clamp removed"
    )
    if mutation_rc2 == 0:
        print("FAIL: mutation (removed PackDens clamp) survived", file=sys.stderr)
        return 1

    print("apply_config_runtime clamp mutation checks: FAIL as expected without clamps (mutations killed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
