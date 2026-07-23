#!/usr/bin/env python3
"""[П3-5] Поведенческая проверка validate_rect_program_startable() (logic.h).

До этой правки menu_samovar_start() запускал пустую программу ректификации
(ProgramLen==0) или строку без условия завершения (Volume==0 и Temp==0 для
H/B/C/T) молча - статус переходил в "работает", а колонна никогда не
останавливалась сама. Тест вытаскивает РЕАЛЬНОЕ тело
validate_rect_program_startable() через extract_function_body.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "inline bool validate_rect_program_startable(String& errorMessage)"

ARDUINO_STUB = r'''
#pragma once
#include <cstdint>
#include <string>

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(char value) : value_(1, value) {}
  String(int value) : value_(std::to_string(value)) {}
  String(unsigned int value) : value_(std::to_string(value)) {}

  const char* c_str() const { return value_.c_str(); }
  bool operator==(const char* other) const { return value_ == other; }

  String& operator+=(const String& other) {
    value_ += other.value_;
    return *this;
  }
  String& operator+=(char c) {
    value_ += c;
    return *this;
  }

  friend String operator+(String left, const String& right) {
    left += right;
    return left;
  }

  const std::string& raw() const { return value_; }

 private:
  std::string value_;
};
'''

HARNESS_TEMPLATE = r'''
#include <iostream>

#include "Arduino.h"

#define CAPACITY_NUM 10
#include "program_types.h"

struct WProgram {
  ProgramType WType;
  uint16_t Volume;
  float Speed;
  uint8_t capacity_num;
  float Temp;
  float Power;
  uint8_t TempSensor;
  float Time;
};

static WProgram program[PROGRAM_MAX];
static uint8_t ProgramLen = 0;

@VALIDATE_BODY@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_program() {
  for (uint8_t i = 0; i < PROGRAM_MAX; i++) program[i] = WProgram{};
  ProgramLen = 0;
}

int main() {
  // 1. Пустая программа: ProgramLen == 0 -> старт должен быть отклонён.
  reset_program();
  String err1;
  check(!validate_rect_program_startable(err1), "ProgramLen==0 должен быть отклонён");

  // 2. Строка B без объёма и температуры (никогда не завершится).
  reset_program();
  program[0].WType = 'H';
  program[0].Volume = 500;
  program[0].Temp = 0;
  program[1].WType = 'B';
  program[1].Volume = 0;
  program[1].Temp = 0;
  ProgramLen = 2;
  String err2;
  bool result2 = validate_rect_program_startable(err2);
  check(!result2, "строка B с Volume=0 и Temp=0 должна быть отклонена");
  check(err2.raw().find("2") != std::string::npos,
        "сообщение об ошибке должно называть номер строки (2)");

  // 3. Та же топология, но у строки B задана температура -> валидна.
  reset_program();
  program[0].WType = 'H';
  program[0].Volume = 500;
  program[0].Temp = 0;
  program[1].WType = 'B';
  program[1].Volume = 0;
  program[1].Temp = 5;
  ProgramLen = 2;
  String err3;
  check(validate_rect_program_startable(err3), "строка B с заданной температурой должна быть валидна");

  if (failures != 0) return 1;
  std::cout << "validate_rect_program_startable behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    logic_source = (ROOT / "logic.h").read_text(encoding="utf-8")
    body = extract_function_body(logic_source, SIGNATURE)
    function = "inline bool validate_rect_program_startable(String& errorMessage) {" + body + "}"
    return HARNESS_TEMPLATE.replace("@VALIDATE_BODY@", function)


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-rect-program-startable-") as temp_dir:
        temp = Path(temp_dir)
        (temp / "Arduino.h").write_text(ARDUINO_STUB, encoding="utf-8")
        source = temp / "rect_program_startable_test.cpp"
        binary = temp / "rect_program_startable_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(temp), "-I", str(ROOT),
                str(source), "-o", str(binary),
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
