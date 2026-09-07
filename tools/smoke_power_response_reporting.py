#!/usr/bin/env python3
"""Поведенческая проверка подавления ошибок регулятора при CheckPower=false."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "static inline void report_power_response_error("
GUARD = "if (!SamSetup.CheckPower) return;"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}

  String& operator+=(const char* value) {
    value_ += value ? value : "";
    return *this;
  }

  const char* c_str() const { return value_.c_str(); }

 private:
  std::string value_;
};

enum NumericParseError : uint8_t {
  NUMERIC_PARSE_EMPTY = 1,
  NUMERIC_PARSE_INVALID_FORMAT = 2,
};

struct NumericParseResult {
  NumericParseError error;
};

struct SetupState {
  bool CheckPower;
};

static SetupState SamSetup{false};
static uint32_t nowMs = 1000;
static uint32_t millis() { return nowMs; }

static const char* numeric_parse_error_code(NumericParseError error) {
  return error == NUMERIC_PARSE_EMPTY ? "empty" : "invalid_format";
}

enum MESSAGE_TYPE : uint8_t { WARNING_MSG = 1 };
static std::vector<std::string> sentMessages;

static void SendMsg(const String& message, MESSAGE_TYPE) {
  sentMessages.emplace_back(message.c_str());
}

static constexpr uint32_t POWER_RESPONSE_ERROR_INTERVAL_MS = 5000;

static inline void report_power_response_error(
    const char* responseName,
    NumericParseResult result) {
@BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  SamSetup.CheckPower = false;
  report_power_response_error("KVIC", {NUMERIC_PARSE_EMPTY});
  check(sentMessages.empty(), "CheckPower=false emitted KVIC warning");

  SamSetup.CheckPower = true;
  report_power_response_error("KVIC", {NUMERIC_PARSE_EMPTY});
  check(sentMessages.size() == 1 &&
            sentMessages[0] == "Invalid power response KVIC: empty",
        "CheckPower=true did not emit KVIC warning");

  SamSetup.CheckPower = false;
  report_power_response_error("SEM +SS?", {NUMERIC_PARSE_INVALID_FORMAT});
  check(sentMessages.size() == 1,
        "CheckPower=false emitted SEM warning");

  SamSetup.CheckPower = true;
  report_power_response_error("SEM +SS?", {NUMERIC_PARSE_INVALID_FORMAT});
  check(sentMessages.size() == 2 &&
            sentMessages[1] == "Invalid power response SEM +SS?: invalid_format",
        "CheckPower=true did not emit SEM warning");

  if (failures != 0) return 1;
  std::cout << "power response reporting checks passed\n";
  return 0;
}
'''


def build_harness(body: str) -> str:
    return HARNESS_TEMPLATE.replace("@BODY@", body)


def compile_and_run(harness: str, label: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix=f"samovar-power-report-{label}-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "power_response_reporting_test.cpp"
        binary = temp / "power_response_reporting_test"
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
            return compile_result
        return subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )


def main() -> int:
    try:
        source = (ROOT / "power_regulator.h").read_text(encoding="utf-8")
        body = extract_function_body(source, SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    production = compile_and_run(build_harness(body), "production")
    sys.stdout.write(production.stdout)
    sys.stderr.write(production.stderr)
    if production.returncode != 0:
        return production.returncode

    if body.count(GUARD) != 1:
        print("FAIL: CheckPower reporting guard must appear exactly once", file=sys.stderr)
        return 1

    mutant = compile_and_run(build_harness(body.replace(GUARD, "", 1)), "mutant")
    if mutant.returncode == 0:
        print("FAIL: removing CheckPower guard did not fail the harness", file=sys.stderr)
        return 1
    expected_failure = "FAIL: CheckPower=false emitted KVIC warning"
    if expected_failure not in mutant.stderr:
        print("FAIL: guard mutation failed for an unrelated reason", file=sys.stderr)
        sys.stderr.write(mutant.stdout)
        sys.stderr.write(mutant.stderr)
        return 1

    print("power response reporting mutation check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
