#!/usr/bin/env python3
"""Host-harness общего demand-gate счётчика и аварии протока."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <iostream>

#define USE_WATER_PUMP
#define USE_WATERSENSOR
#define WF_ALARM_COUNT 3

enum SamovarMode {
  SAMOVAR_RECTIFICATION_MODE = 0,
  SAMOVAR_BEER_MODE = 3,
};

struct Setup {
  bool UseWS;
};

static Setup SamSetup = {};
static bool PowerOn = false;
static bool valve_status = false;
static bool pump_started = false;
static SamovarMode Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
static bool beerCoolingPumpActive = false;
static int WFAlarmCount = 0;
static int buzzerCalls = 0;
static int emergencyCalls = 0;

void set_buzzer(bool) { buzzerCalls++; }
void request_emergency_stop(const char*) { emergencyCalls++; }
bool beer_cooling_pump_demanded() { return beerCoolingPumpActive; }

@DEMAND@
@EMERGENCY@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  SamSetup.UseWS = false;
  PowerOn = false;
  valve_status = false;
  pump_started = false;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  beerCoolingPumpActive = false;
  WFAlarmCount = WF_ALARM_COUNT + 1;
  buzzerCalls = 0;
  emergencyCalls = 0;
}

static void expect_demand(
    bool power, bool useSensor, bool valve, bool pump, bool expected,
    const char* label) {
  reset_fixture();
  PowerOn = power;
  SamSetup.UseWS = useSensor;
  valve_status = valve;
  pump_started = pump;
  check(mode_water_flow_demanded() == expected, label);
  mode_request_water_flow_emergency_if_needed();
  check((emergencyCalls == 1) == expected, label);
  check((buzzerCalls == 1) == expected, label);
}

static void expect_beer_pump_demand(bool coolingPump, bool expected,
                                    const char* label) {
  reset_fixture();
  SamSetup.UseWS = true;
  Samovar_Mode = SAMOVAR_BEER_MODE;
  pump_started = true;
  beerCoolingPumpActive = coolingPump;
  check(mode_water_flow_demanded() == expected, label);
  mode_request_water_flow_emergency_if_needed();
  check((emergencyCalls == 1) == expected, label);
}

int main() {
  expect_demand(true, true, true, false, true,
                "открытый клапан при нагреве должен требовать проток");
  expect_demand(true, true, false, true, true,
                "работающий насос охлаждения должен требовать проток");
  expect_demand(true, true, false, false, false,
                "без открытого тракта проток не требуется");
  expect_demand(false, true, true, true, true,
                "охлаждение после выключения нагрева должно требовать проток");
  expect_demand(true, false, true, true, false,
                "при выключенном UseWS авария протока запрещена");
  expect_beer_pump_demand(false, false,
                           "насос расписания мешалки Beer не должен требовать проток");
  expect_beer_pump_demand(true, true,
                           "активный насос охлаждения Beer должен требовать проток");

  reset_fixture();
  PowerOn = true;
  SamSetup.UseWS = true;
  valve_status = true;
  WFAlarmCount = WF_ALARM_COUNT;
  mode_request_water_flow_emergency_if_needed();
  check(emergencyCalls == 0,
        "счётчик на границе не должен преждевременно вызывать аварию");

  if (failures != 0) return 1;
  std::cout << "water flow demand matrix passed\n";
  return 0;
}
'''


def main() -> int:
    source = (ROOT / "mode_common.h").read_text(encoding="utf-8")
    demand = extract_function_body(source, "inline bool mode_water_flow_demanded()")
    emergency = extract_function_body(
        source, "inline void mode_request_water_flow_emergency_if_needed()"
    )
    harness = HARNESS.replace(
        "@DEMAND@", "bool mode_water_flow_demanded() {" + demand + "}"
    ).replace(
        "@EMERGENCY@",
        "void mode_request_water_flow_emergency_if_needed() {" + emergency + "}",
    )
    with tempfile.TemporaryDirectory(prefix="samovar-flow-demand-") as temp_dir:
        temp = Path(temp_dir)
        def compile_and_run(name: str, text: str) -> subprocess.CompletedProcess[str]:
            source_path = temp / f"{name}.cpp"
            binary_path = temp / name
            source_path.write_text(text, encoding="utf-8")
            result = subprocess.run(
                [
                    "g++",
                    "-std=c++11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(source_path),
                    "-o",
                    str(binary_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return result
            return subprocess.run(
                [str(binary_path)], capture_output=True, text=True, check=False
            )

        result = compile_and_run("flow_demand", harness)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode != 0:
            return result.returncode

        mutant = harness.replace(
            "if (valve_status) return true;",
            "if (valve_status) return false;",
            1,
        )
        if mutant == harness:
            print("FAIL: не удалось построить мутацию valve demand", file=sys.stderr)
            return 1
        if compile_and_run("flow_demand_mutant", mutant).returncode == 0:
            print("FAIL: мутация valve demand пережила тест", file=sys.stderr)
            return 1

        beer_mutant = harness.replace(
            "return beer_cooling_pump_demanded();", "return pump_started;", 1
        )
        if beer_mutant == harness:
            print("FAIL: не удалось построить мутацию Beer demand", file=sys.stderr)
            return 1
        if compile_and_run("flow_demand_beer_mutant", beer_mutant).returncode == 0:
            print("FAIL: мутация Beer demand пережила тест", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
