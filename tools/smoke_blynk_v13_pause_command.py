#!/usr/bin/env python3
"""Поведенческая проверка V13: команда задаёт, а не переключает паузу."""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

struct NumericParseResult {
  bool valid;
  bool ok() const { return valid; }
};

class Param {
 public:
  const char* asStr() const { return value.c_str(); }
  std::string value;
};

static Param param;
static bool PauseOn = false;
static bool beerManualPause = false;
static bool switching = false;
static int enterCalls = 0;
static int resumeCalls = 0;
static int errorCalls = 0;
static uint8_t lastErrorPin = 0;

bool mode_switch_in_progress() { return switching; }
NumericParseResult parse_exact_bool(const char* text, bool& out) {
  if (std::strcmp(text, "0") == 0) {
    out = false;
    return {true};
  }
  if (std::strcmp(text, "1") == 0) {
    out = true;
    return {true};
  }
  return {false};
}
void report_blynk_numeric_error(uint8_t pin, NumericParseResult) {
  errorCalls++;
  lastErrorPin = pin;
}
void enter_manual_pause() { enterCalls++; }
void resume_from_pause() { resumeCalls++; }

void blynk_v13() {
@HANDLER@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset(const char* value, bool rectPaused, bool beerPaused) {
  param.value = value;
  PauseOn = rectPaused;
  beerManualPause = beerPaused;
  switching = false;
  enterCalls = 0;
  resumeCalls = 0;
  errorCalls = 0;
  lastErrorPin = 0;
}

int main() {
  reset("1", false, false);
  blynk_v13();
  check(enterCalls == 1 && resumeCalls == 0, "V13=1 must enter pause when inactive");

  reset("1", true, false);
  blynk_v13();
  check(enterCalls == 0 && resumeCalls == 0, "repeated V13=1 must not resume rectification");

  reset("1", false, true);
  blynk_v13();
  check(enterCalls == 0 && resumeCalls == 0, "repeated V13=1 must not resume beer");

  reset("0", true, false);
  blynk_v13();
  check(enterCalls == 0 && resumeCalls == 1, "V13=0 must resume rectification");

  reset("0", false, true);
  blynk_v13();
  check(enterCalls == 0 && resumeCalls == 1, "V13=0 must resume beer");

  reset("0", false, false);
  blynk_v13();
  check(enterCalls == 0 && resumeCalls == 0, "repeated V13=0 must not change state");

  reset("1", false, false);
  switching = true;
  blynk_v13();
  check(enterCalls == 0 && resumeCalls == 0 && errorCalls == 0,
        "V13 during mode switching must not change state or report an error");

  const char* invalid[] = {"", "2", "true", "01", "1x"};
  for (const char* value : invalid) {
    reset(value, false, false);
    blynk_v13();
    check(enterCalls == 0 && resumeCalls == 0, "invalid V13 must not change state");
    check(errorCalls == 1 && lastErrorPin == 13, "invalid V13 must report pin 13");
  }

  if (failures != 0) return 1;
  std::cout << "Blynk V13 desired-state command checks passed\n";
  return 0;
}
'''


def main() -> int:
    source = strip_cpp_comments((ROOT / "Blynk.ino").read_text(encoding="utf-8"))
    try:
        handler, _ = extract_braced_block_after(source, "BLYNK_WRITE(V13)")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    harness = HARNESS_TEMPLATE.replace("@HANDLER@", handler)
    with tempfile.TemporaryDirectory(prefix="samovar-blynk-v13-") as temp_dir:
        directory = Path(temp_dir)
        cpp = directory / "v13.cpp"
        binary = directory / "v13"
        cpp.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            sys.stderr.write(compiled.stdout + compiled.stderr)
            return compiled.returncode
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(ran.stdout)
        sys.stderr.write(ran.stderr)
        return ran.returncode


if __name__ == "__main__":
    raise SystemExit(main())
