#!/usr/bin/env python3
"""Behavioral check for the /command?luastr= caret-escape convention.

Compiles the real expandLuaCaretEscapes() out of string_utils.h with g++
(-Wall -Wextra -Werror) and runs it, so the assertions exercise the shipped
decoder rather than a regex reflection of its source.

Convention (predates URL-encoding of the field, kept for compatibility):
  '^'  -> space      (what users typed before the client encoded the query)
  '^^' -> '^'        (Lua's exponentiation operator, otherwise unwritable)

The decode MUST be a single left-to-right pass. Two chained replace() calls
("^^"->"^" then "^"->" ") collapse an escaped caret into a space and silently
corrupt every script that uses a power.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
STRING_UTILS = ROOT / "string_utils.h"

HARNESS = r'''
#include <cstddef>
#include <iostream>
#include <string>

// Заглушка Arduino String: наследуемся, чтобы добавить charAt() и reserve(),
// которыми пользуется извлекаемая функция.
class String : public std::string {
 public:
  String() = default;
  String(const char* s) : std::string(s) {}
  String(const std::string& s) : std::string(s) {}
  char charAt(unsigned int index) const { return at(index); }
};

__EXTRACTED__

static int failures = 0;

static void check(const char* input, const char* expected, const char* what) {
  const String actual = expandLuaCaretEscapes(String(input));
  if (actual != std::string(expected)) {
    std::cerr << "FAIL: " << what << "\n  вход:    '" << input
              << "'\n  ожидали: '" << expected << "'\n  получили:'"
              << actual << "'\n";
    failures++;
  }
}

int main() {
  // Ради чего всё затевалось: степень выразима и не превращается в пробел.
  check("x=2^^3", "x=2^3", "'^^' раскрывается в оператор степени");
  check("x^^2+y^^2", "x^2+y^2", "несколько степеней в одном выражении");

  // Обратная совместимость: старая привычка писать '^' вместо пробела.
  check("print^'hi'", "print 'hi'", "одиночный '^' остаётся пробелом");
  check("a^=^1", "a = 1", "несколько одиночных '^'");

  // Ловушка двух проходов: replace("^^","^") + replace("^"," ") дало бы "x=2 3".
  check("x^=^2^^3", "x = 2^3", "смесь пробелов и степени в одной строке");

  // Реальные пробелы едут через encodeURIComponent и не трогаются.
  check("x = 2^^3", "x = 2^3", "настоящие пробелы сохраняются как есть");
  check("no carets here", "no carets here", "строка без '^' не меняется");

  // Границы.
  check("", "", "пустая строка");
  check("^", " ", "одиночный '^' в конце строки");
  check("^^", "^", "только экранированная степень");
  check("2^^", "2^", "'^^' в самом конце");
  check("^^^", "^ ", "нечётная серия: '^^' затем одиночный '^'");
  check("^^^^", "^^", "чётная серия целиком экранирована");

  if (failures) {
    std::cerr << "lua caret escape smoke failed: " << failures << " failures\n";
    return 1;
  }
  std::cout << "lua caret escape smoke passed\n";
  return 0;
}
'''


def main() -> int:
    if shutil.which("g++") is None:
        print("lua caret escape smoke skipped: g++ not available")
        return 0

    source = STRING_UTILS.read_text(encoding="utf-8", errors="ignore")
    try:
        body = extract_function_body(source, "inline String expandLuaCaretEscapes")
    except ValueError as err:
        print(f"lua caret escape smoke failed: {err}")
        return 1

    extracted = "inline String expandLuaCaretEscapes(const String& s) {" + body + "}"
    program = HARNESS.replace("__EXTRACTED__", extracted)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "harness.cpp"
        binary = Path(tmp) / "harness"
        src.write_text(program, encoding="utf-8")
        compile_proc = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", str(binary), str(src)],
            capture_output=True,
            text=True,
        )
        if compile_proc.returncode != 0:
            print("lua caret escape smoke failed: harness did not compile")
            print(compile_proc.stderr)
            return 1
        run_proc = subprocess.run([str(binary)], capture_output=True, text=True)
        sys.stdout.write(run_proc.stdout)
        sys.stderr.write(run_proc.stderr)
        return run_proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
