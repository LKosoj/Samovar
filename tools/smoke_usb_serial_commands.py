#!/usr/bin/env python3
"""Проверяет USB-команду получения IP без перезагрузки ESP."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
SIGNATURE = "inline void tick_usb_serial_command()"


def harness(body: str) -> str:
    return r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#define F(value) value

struct FakeSerial {
  std::string input;
  std::string output;
  size_t position = 0;
  int available() const { return position < input.size(); }
  int read() { return static_cast<unsigned char>(input[position++]); }
  void print(const char *value) { output += value; }
  void println(const char *value) { output += value; output += "\n"; }
  void feed(const char *value) { input += value; }
} Serial;

char ipst[16] = "192.168.1.37";

inline void tick_usb_serial_command() {
''' + body + r'''
}

static bool expect(const std::string &actual, const std::string &expected, const char *label) {
  if (actual == expected) return true;
  std::cerr << label << ": expected [" << expected << "] got [" << actual << "]\n";
  return false;
}

int main() {
  Serial.feed("SAMOVAR:IP?");
  tick_usb_serial_command();
  if (!expect(Serial.output, "", "fragment must wait for newline")) return 1;
  Serial.feed("\n");
  tick_usb_serial_command();
  if (!expect(Serial.output, "SAMOVAR:IP=192.168.1.37\n", "first address")) return 2;

  Serial.output.clear();
  Serial.feed("UNKNOWN\n");
  tick_usb_serial_command();
  if (!expect(Serial.output, "", "unknown command")) return 3;

  std::strcpy(ipst, "10.0.0.8");
  Serial.feed("0123456789012345678901234567890123456789\nSAMOVAR:IP?\n");
  tick_usb_serial_command();
  if (!expect(Serial.output, "SAMOVAR:IP=10.0.0.8\n", "overflow recovery")) return 4;
  return 0;
}
'''


def compile_and_run(body: str, name: str) -> subprocess.CompletedProcess[str]:
    compiler = shutil.which("g++")
    if not compiler:
        raise RuntimeError("g++ not found")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / (name + ".cpp")
        binary = Path(directory) / name
        source.write_text(harness(body), encoding="utf-8")
        built = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True,
        )
        if built.returncode:
            return built
        return subprocess.run([str(binary)], capture_output=True, text=True)


def main() -> int:
    body = extract_function_body(SOURCE, SIGNATURE)
    result = compile_and_run(body, "usb_serial_commands")
    if result.returncode:
        print("FAIL: USB serial command behavior: " + (result.stderr or result.stdout))
        return 1

    loop_body = extract_function_body(SOURCE, "void loop()")
    if loop_body.count("tick_usb_serial_command();") != 1:
        print("FAIL: loop() must call tick_usb_serial_command() exactly once")
        return 1

    mutations = (
        ('strcmp(command, "SAMOVAR:IP?") == 0', "false", "command recognition"),
        ('Serial.print(F("SAMOVAR:IP="));', 'Serial.print(F("BROKEN="));', "response prefix"),
    )
    for old, new, label in mutations:
        if body.count(old) != 1:
            print("FAIL: mutation target missing: " + label)
            return 1
        mutant = body.replace(old, new)
        if compile_and_run(mutant, "usb_serial_mutant").returncode == 0:
            print("FAIL: test did not reject mutation: " + label)
            return 1

    print("USB serial IP command checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
