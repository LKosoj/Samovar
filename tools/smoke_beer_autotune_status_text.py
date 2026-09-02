#!/usr/bin/env python3
"""[Пиво 02.09 A7] Текст статуса строки 'A' (автокалибровка) обязан различать
«это последняя строка программы» (после завершения питание выключится) от
«есть ещё строки» (программа продолжится дальше) - раньше фраза "После
завершения питание будет выключено" выводилась безусловно, даже если после
'A' в программе идут ещё строки.

Тест вытаскивает РЕАЛЬНЫЙ подблок currentType=='A' из get_beer_status_text()
(logic.h) через extract_function_body + extract_braced_block_after - без
переписывания условия "последняя строка".
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

GET_BEER_STATUS_TEXT_SIGNATURE = "String get_beer_status_text()"
A_BRANCH_TOKEN = "} else if (currentType == 'A') {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}
  String operator+(const char* text) const { return String(value_ + (text ? text : "")); }
  String operator+(const String& other) const { return String(value_ + other.value_); }
  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';
constexpr uint8_t PROGRAM_MAX = 8;

struct WProgram { ProgramType WType = PROGRAM_TYPE_NONE; };
static WProgram program[PROGRAM_MAX];
static uint8_t ProgramNum = 0;
static uint8_t ProgramLen = 0;

inline bool program_type_empty(ProgramType type) { return type == PROGRAM_TYPE_NONE; }
inline ProgramType program_type_at(uint8_t index) {
  if (index >= PROGRAM_MAX) return PROGRAM_TYPE_NONE;
  return program[index].WType;
}

// Реальный подблок currentType=='A' из get_beer_status_text() (logic.h).
static String run_a_branch() {
  String local = "";
@A_BRANCH_BODY@
  return local;
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static bool ends_with(const String& s, const char* suffix) {
  const std::string& v = s.value();
  const std::string suf(suffix);
  return v.size() >= suf.size() && v.compare(v.size() - suf.size(), suf.size(), suf) == 0;
}

int main() {
  // ProgramLen == 1: строка 'A' - единственная (последняя) строка программы.
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  program[0].WType = 'A';
  ProgramNum = 0;
  ProgramLen = 1;
  String textLast = run_a_branch();
  check(ends_with(textLast, "питание будет выключено"),
        "РЕГРЕСС (Пиво 02.09 A7): последняя строка 'A' должна была сообщить про выключение питания");

  // ProgramLen == 2, следующая строка 'P' (непустая): строка 'A' НЕ последняя.
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  program[0].WType = 'A';
  program[1].WType = 'P';
  ProgramNum = 0;
  ProgramLen = 2;
  String textNext = run_a_branch();
  check(ends_with(textNext, "переход к следующей строке"),
        "РЕГРЕСС (Пиво 02.09 A7): строка 'A' с непустой следующей строкой должна сообщить про переход дальше, а не про выключение питания");

  if (failures != 0) return 1;
  std::cout << "logic.h get_beer_status_text 'A' branch text checks passed\n";
  return 0;
}
'''


def build_harness(logic_source: str) -> str:
    body = extract_function_body(logic_source, GET_BEER_STATUS_TEXT_SIGNATURE)
    a_branch, _ = extract_braced_block_after(body, A_BRANCH_TOKEN)
    return HARNESS_TEMPLATE.replace("@A_BRANCH_BODY@", a_branch)


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-autotune-status-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_autotune_status_text_test.cpp"
        binary = temp / "beer_autotune_status_text_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(logic_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
