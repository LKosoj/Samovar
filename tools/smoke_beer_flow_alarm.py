#!/usr/bin/env python3
"""Поведенческая проверка П2 п.8: mode_alarm_beer() требует проток воды,

когда клапан охлаждения ('C'/'F') реально открыт, вместо безусловного
глушения аварии по протоку. Раньше water_pulse_count_set(100) вызывался
всегда, даже когда valve_status==true и вода в тракте охлаждения реально
должна течь - авария по прекращению подачи воды в этом случае не могла
сработать никогда. Тест вытаскивает РЕАЛЬНОЕ тело mode_alarm_beer() из
mode_registry.h через extract_function_body.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

MODE_ALARM_BEER_SIGNATURE = "inline void mode_alarm_beer()"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

static bool valve_status = false;

static int beerCheckCoolingLimitsCalls = 0;
void beer_check_cooling_limits() { beerCheckCoolingLimitsCalls++; }

static int waterFlowEmergencyCalls = 0;
void mode_request_water_flow_emergency_if_needed() { waterFlowEmergencyCalls++; }

static int waterPulseCountSetCalls = 0;
static uint16_t lastWaterPulseCountSetValue = 0;
void water_pulse_count_set(uint16_t value) {
  waterPulseCountSetCalls++;
  lastWaterPulseCountSetValue = value;
}

@MODE_ALARM_BEER_BODY@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  valve_status = false;
  beerCheckCoolingLimitsCalls = 0;
  waterFlowEmergencyCalls = 0;
  waterPulseCountSetCalls = 0;
  lastWaterPulseCountSetValue = 0;
}

// [P2 п.8] Клапан охлаждения открыт ('C'/'F' реально гоняют воду через
// тракт) - требуем контроль протока, не глушим аварию.
static void test_open_valve_requires_water_flow() {
  reset_fixture();
  valve_status = true;

  mode_alarm_beer();

  check(beerCheckCoolingLimitsCalls == 1, "mode_alarm_beer должен был всегда проверять температурные лимиты охлаждения");
  check(waterFlowEmergencyCalls == 1,
        "РЕГРЕСС: при открытом клапане охлаждения авария по прекращению протока воды не проверяется");
  check(waterPulseCountSetCalls == 0,
        "РЕГРЕСС: при открытом клапане охлаждения счётчик протока не должен глушиться");
}

// Контроль: клапан закрыт - протока в тракте нет намеренно, авария по нему
// глушится, как и раньше.
static void test_closed_valve_keeps_suppressing_flow_alarm() {
  reset_fixture();
  valve_status = false;

  mode_alarm_beer();

  check(beerCheckCoolingLimitsCalls == 1, "mode_alarm_beer должен был всегда проверять температурные лимиты охлаждения");
  check(waterFlowEmergencyCalls == 0,
        "РЕГРЕСС: при закрытом клапане не должно быть проверки протока (протока в этот момент нет намеренно)");
  check(waterPulseCountSetCalls == 1 && lastWaterPulseCountSetValue == 100,
        "при закрытом клапане счётчик протока должен глушиться значением 100, как раньше");
}

int main() {
  test_open_valve_requires_water_flow();
  test_closed_valve_keeps_suppressing_flow_alarm();
  if (failures != 0) return 1;
  std::cout << "mode_registry.h beer flow alarm gating behaviour checks passed\n";
  return 0;
}
'''


def build_harness(mode_registry_path: Path) -> str:
    mode_registry_source = mode_registry_path.read_text(encoding="utf-8")
    body = extract_function_body(mode_registry_source, MODE_ALARM_BEER_SIGNATURE)
    fn = "void mode_alarm_beer() {" + body + "}"
    return HARNESS_TEMPLATE.replace("@MODE_ALARM_BEER_BODY@", fn)


def compile_and_run(harness: str, label: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-flow-alarm-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "beer_flow_alarm_test.cpp"
        binary = temp / "beer_flow_alarm_test"
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
            sys.stderr.write(f"[{label}] compile failed:\n")
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
    try:
        harness = build_harness(ROOT / "mode_registry.h")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    return compile_and_run(harness, "mode_registry.h")


if __name__ == "__main__":
    raise SystemExit(main())
