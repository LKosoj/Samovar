#!/usr/bin/env python3
"""Source-derived checks for Cheese F fixation and unified Next behavior."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cheese.h").read_text(encoding="utf-8")
SAMOVAR = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
REGISTRY = (ROOT / "mode_registry.h").read_text(encoding="utf-8")
BLYNK = (ROOT / "Blynk.ino").read_text(encoding="utf-8")
WEB = (ROOT / "WebServer.ino").read_text(encoding="utf-8")


def body(signature: str) -> str:
    return extract_function_body(SOURCE, signature, strip_comments=False)


HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(char value) : value_(1, value) {}
  String(uint32_t value) : value_(std::to_string(value)) {}
  void reserve(size_t size) { value_.reserve(size); }
  String& operator+=(const char* value) { value_ += value; return *this; }
  String& operator+=(char value) { value_ += value; return *this; }
  String& operator+=(const String& value) { value_ += value.value_; return *this; }
  friend String operator+(const char* lhs, const String& rhs) { return String(lhs) += rhs; }
  friend String operator+(const String& lhs, const char* rhs) { String out(lhs); return out += rhs; }
  const char* c_str() const { return value_.c_str(); }
  size_t length() const { return value_.length(); }
 private:
  std::string value_;
};

enum { SAMOVAR_CHEESE_MODE = 7, NOTIFY_MSG = 2 };
typedef char ProgramType;
struct WProgram {
  ProgramType WType;
  float Time;
  union { float Param; uint32_t FlocMultiplierMilli; };
};
struct CheeseRuntimeState {
  uint32_t enteredMs;
  bool flocFixed;
  uint32_t flocActualSeconds;
  uint32_t flocMultiplierMilli;
  uint32_t flocCutSeconds;
  uint32_t flocTimeoutSeconds;
};

static WProgram program[20] = {};
static CheeseRuntimeState cheeseRuntime = {};
static uint8_t ProgramNum = 0, ProgramLen = 1;
static const uint8_t PROGRAM_END = 20;
static int Samovar_Mode = SAMOVAR_CHEESE_MODE;
static bool PowerOn = true;
static uint32_t currentSessionId = 0x6AA3CDEF, fakeMs = 0;
static int transitions = 0, aborts = 0, events = 0;
static uint8_t transitionTarget = 0;
static String lastEvent;

uint32_t millis() { return fakeMs; }
uint32_t program_load_cheese_f_multiplier(const WProgram& row) { return row.FlocMultiplierMilli; }
void cheese_run_program_direct(uint8_t target) { ++transitions; transitionTarget = target; }
void cheese_abort(const char*) { ++aborts; }
void SendMsg(const String& message, int) { ++events; lastEvent = message; }

inline uint32_t cheese_f_elapsed_seconds(uint32_t nowMs) { @ELAPSED@ }
inline uint32_t cheese_f_timeout_seconds(const WProgram& row) { @TIMEOUT@ }
inline bool cheese_f_cut_seconds(uint32_t actualSeconds, uint32_t multiplierMilli,
                                 uint32_t& cutSeconds) { @CUT@ }
inline void cheese_f_append_hex(String& out, uint32_t value, uint8_t width) { @HEX@ }
inline String cheese_f_event_payload(uint32_t sessionId, uint8_t row,
                                     uint32_t actualSeconds, uint32_t multiplierMilli,
                                     uint32_t cutSeconds, uint32_t timeoutSeconds) { @PAYLOAD@ }
inline void cheese_handle_next() { @NEXT@ }
void run_cheese_program(uint8_t num) { @RUN@ }

static int failures = 0;
static void check(bool value, const char* message) {
  if (!value) { std::cerr << "FAIL: " << message << '\n'; ++failures; }
}
static void reset() {
  program[0] = {'F', 1.0f, {0.0f}};
  program[0].FlocMultiplierMilli = 2500;
  cheeseRuntime = {};
  ProgramNum = 0; ProgramLen = 1; Samovar_Mode = SAMOVAR_CHEESE_MODE;
  PowerOn = true; currentSessionId = 0x6AA3CDEF; fakeMs = 0;
  transitions = aborts = events = 0; transitionTarget = 0; lastEvent = String();
}

int main() {
  reset();
  run_cheese_program(ProgramNum + 1);
  check(!cheeseRuntime.flocFixed && events == 0 && aborts == 0 && transitions == 0,
        "zero-second Next created a fact or transition");

  reset(); ProgramNum = 2; ProgramLen = 4; program[2] = program[0]; fakeMs = 12000;
  run_cheese_program(ProgramNum + 1);
  check(cheeseRuntime.flocFixed && cheeseRuntime.flocActualSeconds == 12 &&
        cheeseRuntime.flocMultiplierMilli == 2500 && cheeseRuntime.flocCutSeconds == 30 &&
        cheeseRuntime.flocTimeoutSeconds == 60 && events == 1 && transitions == 0 && aborts == 0,
        "first Next did not store one valid F fact");
  check(std::string(lastEvent.c_str()) ==
        "@F1;s=6AA3CDEF;r=03;a=0000000C;m=000009C4;c=0000001E;x=0000003C|Флок зафиксирован: 12 с",
        "F1 payload is not strict or uses wrong row/session values");
  check(lastEvent.length() <= 500, "F1 payload exceeds the wire limit");
  run_cheese_program(ProgramNum + 1);
  check(transitions == 1 && transitionTarget == 3 && events == 1 && aborts == 0,
        "second Next did not advance exactly once");

  reset(); fakeMs = 60000;
  run_cheese_program(ProgramNum + 1);
  check(aborts == 1 && events == 0 && transitions == 0 && !cheeseRuntime.flocFixed,
        "timeout edge created a fact");

  reset(); fakeMs = 30000;
  run_cheese_program(ProgramNum + 1);
  check(aborts == 1 && events == 0 && transitions == 0 && !cheeseRuntime.flocFixed,
        "cut after timeout created a fact");

  reset(); fakeMs = 1000; currentSessionId = 0;
  run_cheese_program(ProgramNum + 1);
  check(aborts == 1 && events == 0 && !cheeseRuntime.flocFixed,
        "missing session created a fact");

  reset(); cheeseRuntime.enteredMs = 0xFFFFFFF0; fakeMs = 984;
  run_cheese_program(ProgramNum + 1);
  check(cheeseRuntime.flocFixed && cheeseRuntime.flocActualSeconds == 1 && events == 1,
        "millis rollover broke F elapsed time");

  reset(); program[0].WType = 'W';
  run_cheese_program(ProgramNum + 1);
  check(transitions == 1 && transitionTarget == 1 && events == 0,
        "legacy Cheese Next behavior changed");

  uint32_t cut = 0;
  check(cheese_f_cut_seconds(1, 2501, cut) && cut == 3,
        "cut formula is not ceil(a*m/1000)");
  check(!cheese_f_cut_seconds(1001, UINT32_MAX, cut),
        "overflowing uint64 result was narrowed to uint32");
  return failures;
}
'''


def source(next_body: str, cut_body: str) -> str:
    replacements = {
        "@ELAPSED@": body("inline uint32_t cheese_f_elapsed_seconds(uint32_t nowMs)"),
        "@TIMEOUT@": body("inline uint32_t cheese_f_timeout_seconds(const WProgram& row)"),
        "@CUT@": cut_body,
        "@HEX@": body("inline void cheese_f_append_hex(String& out, uint32_t value, uint8_t width)"),
        "@PAYLOAD@": body("inline String cheese_f_event_payload(uint32_t sessionId, uint8_t row,"),
        "@NEXT@": next_body,
        "@RUN@": body("inline void run_cheese_program(uint8_t num)"),
    }
    result = HARNESS
    for marker, replacement in replacements.items():
        result = result.replace(marker, replacement)
    return result


def run(cpp_source: str, label: str, expect_success: bool) -> bool:
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-f-") as tmp:
        path = Path(tmp)
        cpp, binary = path / "f.cpp", path / "f"
        cpp.write_text(cpp_source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode != 0:
            print(f"FAIL: {label} compile\n{compiled.stderr}", file=sys.stderr)
            return False
        finished = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if (finished.returncode == 0) != expect_success:
            print(f"FAIL: {label}\n{finished.stdout}{finished.stderr}", file=sys.stderr)
            return False
    return True


def main() -> int:
    prepare_body = body("inline bool cheese_prepare_stage(uint8_t targetProgram)")
    process_body = body("void cheese_proc()")
    convergence = {
        "encoder": "inline void mode_button_press_cheese() {\n  run_cheese_program(ProgramNum + 1);\n}" in REGISTRY,
        "command dispatcher": "case SAMOVAR_CHEESE_NEXT:\n        run_cheese_program(ProgramNum + 1);" in SAMOVAR,
        "Blynk V12": "SamovarCommands command = mode_start_command(Samovar_Mode);" in BLYNK,
        "web Next": "SamovarCommands command = mode_start_command(Samovar_Mode);" in WEB,
        "Cheese registry command": "SAMOVAR_CHEESE, SAMOVAR_CHEESE_NEXT" in REGISTRY,
        "unified handler": "cheese_handle_next();" in body("inline void run_cheese_program(uint8_t num)"),
        "row reset": "cheeseRuntime = {};" in prepare_body,
        "session before first row": process_body.find("session_begin(sessionDescription)") <
            process_body.find("run_cheese_program(0)") and
            process_body.find("session_begin(sessionDescription)") >= 0,
    }
    missing = [name for name, present in convergence.items() if not present]
    if missing:
        print("FAIL: Next does not converge: " + ", ".join(missing), file=sys.stderr)
        return 1
    next_body = body("inline void cheese_handle_next()")
    cut_body = body("inline bool cheese_f_cut_seconds(uint32_t actualSeconds, uint32_t multiplierMilli,")
    if not run(source(next_body, cut_body), "F runtime", True):
        return 1
    mutations = [
        (next_body, "if (cheeseRuntime.flocFixed)", "if (false)", "second Next"),
        (next_body, "cutSeconds > timeoutSeconds", "false", "cut after timeout"),
        (next_body, "cheeseRuntime.flocFixed = true;", "", "single fixation"),
        (next_body, "cutSeconds, timeoutSeconds), NOTIFY_MSG);",
         "cutSeconds, timeoutSeconds), NOTIFY_MSG); SendMsg(\"duplicate\", NOTIFY_MSG);",
         "event count"),
        (cut_body, "product % 1000ULL != 0", "false", "ceil formula"),
    ]
    for original, old, new, label in mutations:
        mutant = original.replace(old, new, 1)
        if mutant == original:
            print(f"FAIL: {label} mutation anchor missing", file=sys.stderr)
            return 1
        mutated_next = mutant if original == next_body else next_body
        mutated_cut = mutant if original == cut_body else cut_body
        if not run(source(mutated_next, mutated_cut), f"mutation {label}", False):
            return 1
    print("Cheese F runtime/Next/F1 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
