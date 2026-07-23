#!/usr/bin/env python3
"""Поведенческая проверка power_regulator.h::apply_program_power_row().

Хелпер унифицирует логику, которая раньше была продублирована в
logic.h::run_program и distiller.h::run_dist_program (и багованно
воспроизведена в alarm.h без ветвления): |Power| выше порога и Power > 0 -
абсолютная уставка, иначе (кроме 0) - дельта к target_power_volt, 0 - строка
не трогает регулятор.

Тест вытаскивает РЕАЛЬНЫЙ код из power_regulator.h через extract_function_body
(тело функции) и текстовый срез ifdef-блока константы PROGRAM_POWER_ABS_THRESHOLD
- без переписывания логики - и подставляет их в минимальный host-харнесс,
замокав только downstream-вызов set_current_power и target_power_volt.

Компилируется ДВАЖДЫ - с -DSAMOVAR_USE_SEM_AVR (порог 400, Вт) и без
(порог 40, В) - так проверяется, что оба ifdef-варианта константы реально
собираются и ведут себя как задумано, а не только текстовое наличие обеих
веток (образец двойной компиляции: tools/smoke_nbk_po_floor.py компилирует
реальный код в изолированном харнессе; здесь то же самое повторяется для
двух значений SAMOVAR_USE_SEM_AVR).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

FUNC_SIGNATURE = "inline void apply_program_power_row(float power)"
THRESHOLD_CONST = "static constexpr float PROGRAM_POWER_ABS_THRESHOLD"
IFDEF_MARKER = "#ifdef SAMOVAR_USE_SEM_AVR"

HARNESS_TEMPLATE = r'''
#include <iostream>

// Arduino's abs() is a generic macro; здесь харнесс собирается без Arduino.h,
// поэтому даём собственный float-overload с идентичной семантикой.
inline float abs(float x) { return x < 0 ? -x : x; }

static int callCount = 0;
static float lastArg = -999.0f;
// Заглушка НЕ static: единственный вызов лежит во вклеенном теле
// apply_program_power_row ниже, и со static мутация, убравшая вызов, роняла
// бы компилятор по unused-function вместо содержательного assert-а. Держится
// это на проверках callCount/lastArg: без них снятие static меняет ложный
// улов на молчаливую слепую зону, что хуже.
void set_current_power(float Volt) { callCount++; lastArg = Volt; }

volatile float target_power_volt = 0.0f;

@SNIPPET@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset(float baseline) {
  callCount = 0;
  lastArg = -999.0f;
  target_power_volt = baseline;
}

int main() {
  // power == 0 при target_power_volt == 0 -> ни одна ветка не должна
  // сработать (строка программы явно "не трогать регулятор").
  reset(0.0f);
  apply_program_power_row(0.0f);
  check(callCount == 0, "power==0 при target_power_volt==0 не должен вызывать set_current_power");

  // power == 0 при НЕнулевом target_power_volt - тот же инвариант, но так
  // ловится мутация, которая превратила бы "else if (power != 0)" в голый
  // "else" (тогда 0 попал бы в дельта-ветку как 0 + target_power_volt).
  reset(77.0f);
  apply_program_power_row(0.0f);
  check(callCount == 0, "power==0 при ненулевом target_power_volt не должен вызывать set_current_power");

  // Чуть выше порога и > 0 -> абсолютная уставка (аргумент равен самому power).
  reset(0.0f);
  const float aboveThreshold = PROGRAM_POWER_ABS_THRESHOLD + 10.0f;
  apply_program_power_row(aboveThreshold);
  check(callCount == 1, "значение выше порога должно вызвать set_current_power ровно один раз");
  check(lastArg == aboveThreshold, "значение выше порога должно уйти как абсолютная уставка без изменений");

  // Отрицательный большой модуль -> ДЕЛЬТА, а не абсолют. Ловит мутацию,
  // которая убрала бы "&& power > 0" из условия (abs(power) > порога всё
  // равно истинно и для отрицательного значения).
  reset(100.0f);
  const float negativeLarge = -(PROGRAM_POWER_ABS_THRESHOLD + 10.0f);
  apply_program_power_row(negativeLarge);
  check(callCount == 1, "отрицательный большой модуль должен вызвать set_current_power ровно один раз");
  check(lastArg == 100.0f + negativeLarge,
        "отрицательный большой модуль должен уйти как дельта к target_power_volt, а не как абсолют");

  // Малая положительная дельта.
  reset(30.0f);
  apply_program_power_row(5.0f);
  check(callCount == 1, "малая положительная дельта должна вызвать set_current_power ровно один раз");
  check(lastArg == 35.0f, "малая положительная дельта должна прибавиться к target_power_volt");

  // Граница: power == порог РОВНО -> строгое ">" не должно сработать,
  // ветка абсолюта не должна выбраться, ожидаем дельту.
  reset(30.0f);
  apply_program_power_row(PROGRAM_POWER_ABS_THRESHOLD);
  check(callCount == 1, "power==порог должен вызвать set_current_power ровно один раз");
  check(lastArg == 30.0f + PROGRAM_POWER_ABS_THRESHOLD,
        "power==порог обязан попасть в дельта-ветку (строгое >, а не >=)");

  if (failures != 0) return 1;
  std::cout << "apply_program_power_row behaviour checks passed\n";
  return 0;
}
'''


def build_snippet(source: str) -> str:
    first = source.find(THRESHOLD_CONST)
    if first < 0:
        raise ValueError(f"constant not found: {THRESHOLD_CONST}")
    start = source.rfind(IFDEF_MARKER, 0, first)
    if start < 0:
        raise ValueError(f"enclosing {IFDEF_MARKER} not found before threshold constant")
    endif_idx = source.find("#endif", first)
    if endif_idx < 0:
        raise ValueError("closing #endif for threshold constant not found")
    endif_idx += len("#endif")
    const_block = source[start:endif_idx]

    func_body = extract_function_body(source, FUNC_SIGNATURE)
    func_full = FUNC_SIGNATURE + " {" + func_body + "}"

    return const_block + "\n\n" + func_full


def compile_and_run(harness: str, label: str, extra_define: str | None) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-program-power-row-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "program_power_row_test.cpp"
        binary = temp / "program_power_row_test"
        source.write_text(harness, encoding="utf-8")
        cmd = ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror"]
        if extra_define:
            cmd.append(extra_define)
        cmd += [str(source), "-o", str(binary)]
        compile_result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if compile_result.returncode != 0:
            sys.stderr.write(f"[{label}] compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(f"[{label}] ")
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    source = (ROOT / "power_regulator.h").read_text(encoding="utf-8")
    try:
        snippet = build_snippet(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = HARNESS_TEMPLATE.replace("@SNIPPET@", snippet)

    rc = compile_and_run(harness, "KVIC/RMVK (no SAMOVAR_USE_SEM_AVR)", None)
    if rc != 0:
        return rc
    rc = compile_and_run(harness, "SEM_AVR (-DSAMOVAR_USE_SEM_AVR)", "-DSAMOVAR_USE_SEM_AVR")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
