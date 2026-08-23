#!/usr/bin/env python3
"""Поведенческая проверка needReset в logic.h::run_program().

Формула определяет, надо ли сбрасывать детектор примесей при переходе на новую
строку программы: needReset истинен по умолчанию (первая строка программы,
предыдущая или текущая строка не определены), а на паре заданных строк - это
XOR принадлежности к "накоплению тела" (типы B/C): сброс происходит при входе
в накопление тела или выходе из него, и НЕ происходит при переходе B<->C.

Тест вытаскивает РЕАЛЬНЫЙ фрагмент needReset из logic.h (find по
"bool needReset = true;" + extract_braced_block_after) и реальные тела
program_type_empty()/program_type_one_of() из program_types.h
(extract_function_body) - логика в тесте не переписывается руками.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

NEED_RESET_TOKEN = "bool needReset = true;"
PROGRAM_TYPE_EMPTY_SIGNATURE = "inline bool program_type_empty(ProgramType type)"
PROGRAM_TYPE_ONE_OF_SIGNATURE = "inline bool program_type_one_of(ProgramType type, const char *allowedTypes)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_MAX = 6;

// ---- Реальные функции из program_types.h (extract_function_body) ----
inline bool program_type_empty(ProgramType type) {
@PROGRAM_TYPE_EMPTY_BODY@
}

inline bool program_type_one_of(ProgramType type, const char *allowedTypes) {
@PROGRAM_TYPE_ONE_OF_BODY@
}

// ---- Фикстура программы ----
struct WProgram {
  ProgramType WType = PROGRAM_TYPE_NONE;
};
static WProgram program[PROGRAM_MAX];

static void reset_program() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i].WType = PROGRAM_TYPE_NONE;
}

// ---- Реальный фрагмент needReset из logic.h::run_program() ----
static bool compute_need_reset(uint8_t num) {
@NEED_RESET_FRAGMENT@
  return needReset;
}

// ---- Тесты ----
static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static std::string describe(bool value) {
  return value ? "true" : "false";
}

// num=0 - первая строка программы: сброс обязателен для ЛЮБОГО типа текущей
// строки, включая незаданный. Проверено на 6 разных значениях типа.
static void test_first_row_always_resets() {
  const ProgramType types[] = {'H', 'B', 'C', 'T', 'P', PROGRAM_TYPE_NONE};
  for (ProgramType t : types) {
    reset_program();
    program[0].WType = t;
    bool actual = compute_need_reset(0);
    check(actual == true,
          std::string("num=0, тип текущей строки '") + t + "': ожидание needReset=true, получено " + describe(actual));
  }
}

// num=1 с незаданной предыдущей строкой - предыдущая программа "не определена",
// сброс обязателен независимо от текущего типа. Проверено на двух разных типах.
static void test_empty_prev_row_resets() {
  const ProgramType currentTypes[] = {'H', 'T'};
  for (ProgramType t : currentTypes) {
    reset_program();
    program[0].WType = PROGRAM_TYPE_NONE;
    program[1].WType = t;
    bool actual = compute_need_reset(1);
    check(actual == true,
          std::string("num=1, предыдущая строка пуста, текущий тип '") + t +
              "': ожидание needReset=true, получено " + describe(actual));
  }
}

// num=1 с незаданной ТЕКУЩЕЙ строкой - сброс обязателен независимо от
// предыдущего типа. Проверено на двух разных типах.
static void test_empty_current_row_resets() {
  const ProgramType prevTypes[] = {'H', 'B'};
  for (ProgramType t : prevTypes) {
    reset_program();
    program[0].WType = t;
    program[1].WType = PROGRAM_TYPE_NONE;
    bool actual = compute_need_reset(1);
    check(actual == true,
          std::string("num=1, предыдущий тип '") + t +
              "', текущая строка пуста: ожидание needReset=true, получено " + describe(actual));
  }
}

// Полная матрица переходов при обеих заданных строках. Сброс должен
// происходить только на входе/выходе из "накопления тела" (B/C).
struct TransitionCase {
  ProgramType prevType;
  ProgramType currentType;
  bool expected;
};

static const TransitionCase transitions[] = {
    {'H', 'T', false},  // головы -> хвосты, минуя тело - сброс не нужен
    {'H', 'B', true},   // головы -> тело: вход в накопление тела
    {'B', 'T', true},   // тело -> хвосты: выход из накопления тела
    {'B', 'C', false},  // тело -> предзахлеб: оба входят в накопление тела
    {'C', 'B', false},  // предзахлеб -> тело: оба входят в накопление тела
    {'B', 'B', false},  // тело -> тело: без смены принадлежности
    {'T', 'H', false},  // хвосты -> головы: обе строки вне накопления тела
    {'T', 'B', true},   // хвосты -> тело: вход в накопление тела
    {'P', 'C', true},   // пауза -> предзахлеб: вход в накопление тела
};

static void test_transition_matrix() {
  for (const TransitionCase& c : transitions) {
    reset_program();
    program[0].WType = c.prevType;
    program[1].WType = c.currentType;
    bool actual = compute_need_reset(1);
    check(actual == c.expected,
          std::string("переход '") + c.prevType + "' -> '" + c.currentType +
              "': ожидание needReset=" + describe(c.expected) + ", получено " + describe(actual));
  }
}

int main() {
  test_first_row_always_resets();
  test_empty_prev_row_resets();
  test_empty_current_row_resets();
  test_transition_matrix();

  if (failures != 0) return 1;
  std::cout << "run_program needReset matrix checks passed\n";
  return 0;
}
'''


def extract_need_reset_fragment(logic_source: str) -> str:
    start = logic_source.find(NEED_RESET_TOKEN)
    if start < 0:
        raise ValueError(f"needReset declaration not found: {NEED_RESET_TOKEN}")
    _, end = extract_braced_block_after(logic_source, NEED_RESET_TOKEN)
    return logic_source[start:end]


def build_harness(fragment: str, empty_body: str, one_of_body: str) -> str:
    harness = HARNESS_TEMPLATE
    harness = harness.replace("@PROGRAM_TYPE_EMPTY_BODY@", empty_body)
    harness = harness.replace("@PROGRAM_TYPE_ONE_OF_BODY@", one_of_body)
    harness = harness.replace("@NEED_RESET_FRAGMENT@", fragment)
    return harness


def compile_and_run(harness: str, emit: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-run-program-need-reset-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "run_program_need_reset_test.cpp"
        binary = temp / "run_program_need_reset_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            if emit:
                sys.stderr.write("compile failed:\n")
                sys.stderr.write(compile_result.stdout)
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")
    types_source = (ROOT / "program_types.h").read_text(encoding="utf-8")

    try:
        fragment = extract_need_reset_fragment(logic_source)
        empty_body = extract_function_body(types_source, PROGRAM_TYPE_EMPTY_SIGNATURE)
        one_of_body = extract_function_body(types_source, PROGRAM_TYPE_ONE_OF_SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if compile_and_run(build_harness(fragment, empty_body, one_of_body), True) != 0:
        return 1

    # Мутация 1: != -> == в сравнении принадлежности "накоплению тела".
    # Должна ловиться на внутренних переходах матрицы (H->B, B->C и т.д.).
    mutated_cmp = fragment.replace(
        "needReset = (prevWasBodyPick != currentIsBodyPick);",
        "needReset = (prevWasBodyPick == currentIsBodyPick);",
        1,
    )
    if mutated_cmp == fragment:
        print("FAIL: не удалось построить мутацию (!= -> ==)", file=sys.stderr)
        return 1
    if compile_and_run(build_harness(mutated_cmp, empty_body, one_of_body), False) == 0:
        print("FAIL: мутация (!= -> ==) осталась незамеченной", file=sys.stderr)
        return 1

    # Мутация 2: needReset по умолчанию false вместо true.
    # Должна ловиться на граничных случаях (num=0, пустая предыдущая/текущая строка).
    mutated_default = fragment.replace(
        "bool needReset = true;",
        "bool needReset = false;",
        1,
    )
    if mutated_default == fragment:
        print("FAIL: не удалось построить мутацию (needReset default true -> false)", file=sys.stderr)
        return 1
    if compile_and_run(build_harness(mutated_default, empty_body, one_of_body), False) == 0:
        print("FAIL: мутация (needReset default true -> false) осталась незамеченной", file=sys.stderr)
        return 1

    print("run_program needReset mutation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
