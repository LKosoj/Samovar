#!/usr/bin/env python3
"""Проверяет реальное выражение выбора pinMode() для ALARM_BTN_PIN в Samovar.ino:
на классическом ESP32 выводы 34-39 - только вход, без внутренних подтяжек (DEVKIT,
ALARM_BTN_PIN=35 из Samovar_pin.h), значит там нужен INPUT (внешняя подтяжка на
плате). На ESP32-S3 такого ограничения нет (ALARM_BTN_PIN=48), там подтяжка
INPUT_PULLUP реальна."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <iostream>

#define INPUT 0x01
#define INPUT_PULLUP 0x05

#define ALARM_BTN_PIN @PIN@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  int mode = @EXPR@;
  check(mode == @EXPECTED@, "@LABEL@ (ALARM_BTN_PIN=@PIN@): expected pinMode @EXPECTED_NAME@");
  return failures == 0 ? 0 : 1;
}
'''


def build_harness(expr: str, pin: str, expected_name: str, label: str) -> str:
    return (
        HARNESS_TEMPLATE.replace("@EXPR@", expr)
        .replace("@PIN@", pin)
        .replace("@EXPECTED@", expected_name)
        .replace("@EXPECTED_NAME@", expected_name)
        .replace("@LABEL@", label)
    )


def compile_and_run(harness: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-alarm-btn-pin-mode-") as temp_dir:
        source = Path(temp_dir) / "alarm_btn_pin_mode_test.cpp"
        binary = Path(temp_dir) / "alarm_btn_pin_mode_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        output = compile_result.stdout + compile_result.stderr
        if compile_result.returncode == 0:
            run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
            output = run_result.stdout + run_result.stderr
            code = run_result.returncode
        else:
            code = compile_result.returncode
        if show_output:
            sys.stdout.write(output)
        return code, output


BOARDS = [
    ("DEVKIT", "35", "INPUT", "GButton/энкодер класса выводов 34-39, только вход"),
    ("ESP32-S3", "48", "INPUT_PULLUP", "обычный вывод, внутренняя подтяжка реальна"),
]


def main() -> int:
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")

    match = re.search(r"pinMode\(ALARM_BTN_PIN,\s*(.+?)\);", samovar)
    if not match:
        print("FAIL: не найден pinMode(ALARM_BTN_PIN, ...) в Samovar.ino", file=sys.stderr)
        return 1
    expr = match.group(1)

    errors: list[str] = []
    for token in ("ALARM_BTN_PIN >= 34", "ALARM_BTN_PIN <= 39", "INPUT_PULLUP"):
        if token not in expr:
            errors.append(f"pinMode(ALARM_BTN_PIN, ...) не содержит {token!r}: {expr!r}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    for label, pin, expected_name, _comment in BOARDS:
        code, _ = compile_and_run(build_harness(expr, pin, expected_name, label))
        if code != 0:
            return 1

    # Мутация: вернуть старое безусловное INPUT_PULLUP (то, что было до фикса) и
    # убедиться, что тест на DEVKIT (ALARM_BTN_PIN=35, только вход) это ловит.
    mutant_expr = "INPUT_PULLUP"
    code, output = compile_and_run(
        build_harness(mutant_expr, "35", "INPUT", "DEVKIT"), show_output=False
    )
    if code == 0 or "expected pinMode INPUT" not in output:
        print("FAIL: мутация (безусловный INPUT_PULLUP) пережила тест для DEVKIT", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("ALARM_BTN_PIN pinMode mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
