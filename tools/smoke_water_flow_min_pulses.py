#!/usr/bin/env python3
"""Проверяет реальное тело tick_update_water_flow(): дребезг датчика протока должен
фильтроваться порогом WATER_FLOW_MIN_PULSES (7 импульсов за такт), а не старыми
3 импульсами, которые на практике неотличимы от дребезга при отсутствии потока."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "static void tick_update_water_flow(uint16_t waterPulses, unsigned long &oldTime)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

#define WF_CALIBRATION 98
#define WATER_FLOW_MIN_PULSES @THRESHOLD@

static bool demandWaterFlow = true;
inline bool mode_water_flow_demanded() { return demandWaterFlow; }

static volatile float WFflowRate = 0;
static volatile unsigned int WFflowMilliLitres = 0;
static volatile unsigned long WFtotalMilliLitres = 0;
static volatile int WFAlarmCount = 0;

static unsigned long fakeMillis = 1000;
unsigned long millis() { return fakeMillis; }

@TICK_UPDATE_WATER_FLOW@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static int run_row(const uint16_t* pulses, int count) {
  WFAlarmCount = 0;
  unsigned long oldTime = fakeMillis;
  for (int i = 0; i < count; i++) {
    fakeMillis += 1000;
    tick_update_water_flow(pulses[i], oldTime);
  }
  return WFAlarmCount;
}

int main() {
  demandWaterFlow = true;

  {
    uint16_t row[] = {0, 0, 0};
    check(run_row(row, 3) == 3, "0,0,0 must count as 3 bad ticks (no flow at all)");
  }
  {
    uint16_t row[] = {3, 3, 3};
    check(run_row(row, 3) == 3,
          "3,3,3 must count as 3 bad ticks (below WATER_FLOW_MIN_PULSES)");
  }
  {
    uint16_t row[] = {7, 7, 7};
    check(run_row(row, 3) == 0, "7,7,7 is real flow, must not count as bad ticks");
  }
  {
    uint16_t row[] = {7, 0, 7};
    check(run_row(row, 3) == 0, "a single bad tick between good ticks must not accumulate");
  }
  {
    uint16_t row[] = {6, 6, 6};
    check(run_row(row, 3) == 3, "6,6,6 is below threshold of 7 and must count as bad ticks");
  }

  return failures == 0 ? 0 : 1;
}
'''


def build_harness(body: str, threshold: str) -> str:
    harness = HARNESS_TEMPLATE.replace("@THRESHOLD@", threshold)
    return harness.replace(
        "@TICK_UPDATE_WATER_FLOW@",
        "static void tick_update_water_flow(uint16_t waterPulses, unsigned long &oldTime) {"
        + body
        + "}",
    )


def compile_and_run(harness: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-water-flow-min-pulses-") as temp_dir:
        source = Path(temp_dir) / "water_flow_min_pulses_test.cpp"
        binary = Path(temp_dir) / "water_flow_min_pulses_test"
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


def main() -> int:
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    ini = (ROOT / "Samovar_ini.h").read_text(encoding="utf-8")
    errors: list[str] = []

    try:
        body = extract_function_body(samovar, SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    threshold_match = re.search(r"#define\s+WATER_FLOW_MIN_PULSES\s+(\d+)", ini)
    if not threshold_match:
        print("FAIL: WATER_FLOW_MIN_PULSES не найден в Samovar_ini.h", file=sys.stderr)
        return 1
    threshold = threshold_match.group(1)
    if threshold != "7":
        errors.append(
            f"WATER_FLOW_MIN_PULSES = {threshold}, ожидалось 7 (матрица теста завязана на это значение)"
        )

    require_ordered_tokens(
        "water flow debounce order",
        body,
        [
            "if (waterPulses < WATER_FLOW_MIN_PULSES) waterPulses = 0;",
            "if (mode_water_flow_demanded() && waterPulses == 0)",
            "WFAlarmCount++",
        ],
        errors,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    code, _ = compile_and_run(build_harness(body, threshold))
    if code != 0:
        return 1

    mutant_body = body.replace("WATER_FLOW_MIN_PULSES", "3", 1)
    if mutant_body == body:
        print("FAIL: не удалось создать мутацию порога протока", file=sys.stderr)
        return 1
    code, output = compile_and_run(build_harness(mutant_body, threshold), show_output=False)
    if code == 0 or "below threshold of 7" not in output:
        print("FAIL: мутация порога протока (7 -> 3) пережила тест", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Water-flow min-pulses threshold mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
