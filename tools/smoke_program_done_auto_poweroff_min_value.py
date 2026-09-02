#!/usr/bin/env python3
"""Пин значения PROGRAM_DONE_AUTO_POWEROFF_MIN (Часть2 п.5, "работа на себя").

Samovar_ini.h задаёт PROGRAM_DONE_AUTO_POWEROFF_MIN = 30 (минут удержания
статуса "Выполнение программы завершено" перед автоотключением). Поведение
самой функции (Menu.ino/logic.h) уже покрыто tools/smoke_program_done_auto_poweroff.py,
но там константа параметризована плейсхолдером @MIN@ - тест проходит для
ЛЮБОГО значения, включая 0 (то есть тихий откат к старому немедленному
поведению и фактическое отключение фичи). Этот тест пинит именно ЗНАЧЕНИЕ,
реально зашитое в прошивку.

Комментарии вырезаются ДО поиска (strip_cpp_comments) - иначе закомментированная
строка с "30" в тексте комментария молча прошла бы проверку. Извлечённая
#define-строка компилируется в static_assert - настоящая проверка компилятором
значения макроса, а не просто совпадение регулярного выражения.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

MACRO_NAME = "PROGRAM_DONE_AUTO_POWEROFF_MIN"
EXPECTED_VALUE = 30

DEFINE_PATTERN = re.compile(r"#define\s+" + MACRO_NAME + r"\s+(\d+)")


def extract_define_line(source: str) -> tuple[str, int]:
    stripped = strip_cpp_comments(source)
    matches = DEFINE_PATTERN.findall(stripped)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one active #define {MACRO_NAME}, found {len(matches)}"
        )
    match = DEFINE_PATTERN.search(stripped)
    assert match is not None
    return match.group(0), int(match.group(1))


def build_harness(define_line: str, expected: int) -> str:
    return f'''
{define_line}
static_assert({MACRO_NAME} == {expected}, "PROGRAM_DONE_AUTO_POWEROFF_MIN drifted away from the pinned value");

int main() {{
  return 0;
}}
'''


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-poweroff-min-value-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "poweroff_min_value_test.cpp"
        binary = temp / "poweroff_min_value_test"
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
    source = (ROOT / "Samovar_ini.h").read_text(encoding="utf-8")

    try:
        define_line, value = extract_define_line(source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if value != EXPECTED_VALUE:
        print(
            f"FAIL: {MACRO_NAME} is {value}, expected pinned value {EXPECTED_VALUE} "
            "(0 would silently disable the 'работа на себя' feature)",
            file=sys.stderr,
        )
        return 1

    rc = compile_and_run(build_harness(define_line, EXPECTED_VALUE), "PROGRAM_DONE_AUTO_POWEROFF_MIN pinned value")
    if rc != 0:
        return rc

    # --- Мутация: откатываем константу к 0 (тихое отключение фичи) - тест обязан покраснеть.
    mutated = source.replace(f"#define {MACRO_NAME} 30", f"#define {MACRO_NAME} 0", 1)
    if mutated == source:
        print("FAIL: mutation anchor missing (#define PROGRAM_DONE_AUTO_POWEROFF_MIN 30)", file=sys.stderr)
        return 1
    try:
        mutated_define_line, mutated_value = extract_define_line(mutated)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if mutated_value == EXPECTED_VALUE:
        print("FAIL: mutation did not actually change the extracted value", file=sys.stderr)
        return 1
    # static_assert сравнивает с ПИННЫМ значением (30) - при значении 0 в
    # исходнике компиляция обязана упасть на static_assert, а не пройти.
    mutation_rc = compile_and_run(
        build_harness(mutated_define_line, EXPECTED_VALUE), "mutation: rollback to 0"
    )
    if mutation_rc == 0:
        print("FAIL: mutation (rollback to 0) survived - static_assert should have failed", file=sys.stderr)
        return 1

    print("mutation check: rollback to 0 fails static_assert as expected (mutation caught)")
    print("PROGRAM_DONE_AUTO_POWEROFF_MIN pinned-value checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
