#!/usr/bin/env python3
"""Проверяет реальный спрос на проток в Beer без подмены тела прошивки."""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "inline bool mode_water_flow_demanded()"

HARNESS_TEMPLATE = r'''
#include <iostream>

#define USE_WATER_PUMP
#define USE_WATERSENSOR

enum SamovarMode {
  SAMOVAR_RECTIFICATION_MODE = 0,
  SAMOVAR_BEER_MODE = 3,
};

struct SetupEEPROM { bool UseWS = true; };
static SetupEEPROM SamSetup;
static SamovarMode Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
static bool valve_status = false;
static bool pump_started = false;
static bool beerCoolingPumpActive = false;
static int WFAlarmCount = 0;
constexpr int WF_ALARM_COUNT = 3;
static int emergencyRequests = 0;
bool beer_cooling_pump_demanded() { return beerCoolingPumpActive; }
void set_buzzer(bool) {}
void request_emergency_stop(const char*) { emergencyRequests++; }

@MODE_WATER_FLOW_DEMANDED@
@MODE_WATER_FLOW_EMERGENCY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  SamSetup.UseWS = true;
  Samovar_Mode = SAMOVAR_BEER_MODE;
  valve_status = false;
  pump_started = true;
  beerCoolingPumpActive = false;
  check(!mode_water_flow_demanded(),
        "плановый насос мешалки без охлаждения создал спрос на проток");
  WFAlarmCount = WF_ALARM_COUNT + 1;
  mode_request_water_flow_emergency_if_needed();
  check(emergencyRequests == 0,
        "плановый насос мешалки без охлаждения вызвал аварию протока");

  beerCoolingPumpActive = true;
  check(mode_water_flow_demanded(),
        "активный насос охлаждения Beer не создал спрос на проток");

  beerCoolingPumpActive = false;
  valve_status = true;
  check(mode_water_flow_demanded(),
        "открытый клапан Beer не создал спрос на проток");

  valve_status = false;
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  check(mode_water_flow_demanded(),
        "насос охлаждения другого режима не создал спрос на проток");

  SamSetup.UseWS = false;
  check(!mode_water_flow_demanded(),
        "отключенный датчик протока оставил спрос на проток");
  return failures == 0 ? 0 : 1;
}
'''


def build_harness(demand_body: str, emergency_body: str) -> str:
    harness = HARNESS_TEMPLATE.replace(
        "@MODE_WATER_FLOW_DEMANDED@",
        "inline bool mode_water_flow_demanded() {" + demand_body + "}",
    )
    return harness.replace(
        "@MODE_WATER_FLOW_EMERGENCY@",
        "inline void mode_request_water_flow_emergency_if_needed() {" + emergency_body + "}",
    )


def compile_and_run(harness: str, label: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-water-flow-") as temp_dir:
        source = Path(temp_dir) / "beer_water_flow_test.cpp"
        binary = Path(temp_dir) / "beer_water_flow_test"
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
    mode_common = (ROOT / "mode_common.h").read_text(encoding="utf-8")
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    registry = (ROOT / "mode_registry.h").read_text(encoding="utf-8")
    errors: list[str] = []
    try:
        demand_body = extract_function_body(mode_common, SIGNATURE)
        emergency_body = extract_function_body(
            mode_common, "inline void mode_request_water_flow_emergency_if_needed()"
        )
        beer_alarm = extract_function_body(registry, "inline void mode_alarm_beer()")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    require_ordered_tokens(
        "Beer flow demand",
        demand_body,
        [
            "if (!SamSetup.UseWS) return false;",
            "if (valve_status) return true;",
            "if (Samovar_Mode == SAMOVAR_BEER_MODE) return beer_cooling_pump_demanded();",
            "return pump_started;",
        ],
        errors,
    )
    require_ordered_tokens(
        "Beer flow counter and emergency",
        samovar,
        ["if (mode_water_flow_demanded() && waterPulses == 0)", "WFAlarmCount++"],
        errors,
    )
    require_ordered_tokens(
        "Beer flow emergency",
        emergency_body,
        ["mode_water_flow_demanded()", "WFAlarmCount > WF_ALARM_COUNT"],
        errors,
    )
    require_ordered_tokens(
        "Beer alarm routing",
        beer_alarm,
        ["mode_request_water_flow_emergency_if_needed();"],
        errors,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = build_harness(demand_body, emergency_body)
    code, _ = compile_and_run(harness, "Beer flow demand")
    if code != 0:
        return 1

    mutant_body = demand_body.replace(
        "return beer_cooling_pump_demanded();", "return pump_started;", 1
    )
    if mutant_body == demand_body:
        print("FAIL: не удалось создать мутацию Beer-предиката", file=sys.stderr)
        return 1
    code, output = compile_and_run(
        build_harness(mutant_body, emergency_body), "Beer flow mutant", show_output=False
    )
    if code == 0 or "плановый насос мешалки без охлаждения" not in output:
        print("FAIL: мутация Beer-предиката пережила тест", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Beer water-flow demand mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
