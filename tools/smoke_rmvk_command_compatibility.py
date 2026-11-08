#!/usr/bin/env python3
"""РМВ-К: как в 6.26, ответы на команды не обрывают их выполнение."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = (
    ("mod_rmv.ino", "uint16_t RMVK_set_out_voltge(uint16_t voltge, uint64_t powerGeneration)"),
    ("power_regulator_rmvk.h", "inline bool apply_regulator_voltage_blocking(float Volt, uint64_t powerGeneration)"),
    ("power_regulator_rmvk.h", "inline bool apply_regulator_mode_blocking(SafetyRegulatorMode mode, uint64_t powerGeneration)"),
)
HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
using String = std::string;
enum SafetyRegulatorMode { SAFETY_REGULATOR_MODE_SLEEP, SAFETY_REGULATOR_MODE_SPEED };
enum { RMVK_INT, RMVK_ERROR = 255, MAX_VOLTAGE = 230, RMVK_READ_DELAY = 200, portTICK_PERIOD_MS = 1 };
#define POWER_DEBUG_LOG(...) do {} while (0)
struct { bool on = false; } rmvk;
float target_power_volt = 0, current_power_volt = 0, current_power_p = 0;
int response;
std::vector<std::string> commands;
void vTaskDelay(int) {}
String regulator_mode_text(SafetyRegulatorMode mode) { return mode == SAFETY_REGULATOR_MODE_SLEEP ? "S" : "F"; }
bool set_current_power_mode_value(String) { return true; }
void arm_pending_power_mode_retry(SafetyRegulatorMode) {}
uint16_t RMVK_set_on(uint16_t state, uint64_t) {
  commands.push_back(state ? "ON" : "OFF");
  return response;
}
uint8_t RMVK_cmd(const char* cmd, int, bool, uint64_t) {
  commands.push_back(cmd);
  return response;
}
@FUNCTIONS@
void check(bool ok, const char* message) {
  if (!ok) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
int main() {
  for (int answer : {255, 0, 1}) {
    response = answer;
    commands.clear();
    check(apply_regulator_mode_blocking(SAFETY_REGULATOR_MODE_SPEED, 7),
          "RMVK speed must ignore command response");
    check(commands == std::vector<std::string>({"ON", "ON", "AT+VS=230"}),
          "RMVK speed must send voltage even without ON confirmation");
    commands.clear();
    target_power_volt = 100;
    current_power_volt = 90;
    current_power_p = 1200;
    check(apply_regulator_mode_blocking(SAFETY_REGULATOR_MODE_SLEEP, 8),
          "RMVK sleep must ignore command response");
    check(commands == std::vector<std::string>({"OFF"}), "RMVK sleep must send OFF");
    check(target_power_volt == 0 && current_power_volt == 0 && current_power_p == 0,
          "RMVK sleep must clear power values");
    for (int voltage : {123, 210}) {
      commands.clear();
      check(apply_regulator_voltage_blocking(voltage, 9),
            "RMVK voltage must ignore command response");
      check(commands == std::vector<std::string>({"ON", "AT+VS=" + std::to_string(voltage)}),
            "RMVK voltage command must be sent without ON confirmation");
      check(target_power_volt == voltage, "RMVK target must match requested voltage");
    }
  }
}
'''


def run(sources):
    functions = "\n".join(signature + " {\n" + extract_function_body(sources[name], signature) + "\n}"
                          for name, signature in FUNCTIONS)
    with tempfile.TemporaryDirectory(prefix="samovar-rmvk-compat-") as tmp:
        source, binary = Path(tmp) / "test.cpp", Path(tmp) / "test"
        source.write_text(HARNESS.replace("@FUNCTIONS@", functions))
        subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], check=True)
        return subprocess.run([str(binary)], capture_output=True, text=True)


def main():
    sources = {name: (ROOT / name).read_text() for name, _ in FUNCTIONS}
    result = run(sources)
    if result.returncode:
        raise SystemExit(result.stderr)
    mutations = (
        ("mod_rmv.ino", "RMVK_set_on(1, powerGeneration);", "if (RMVK_set_on(1, powerGeneration) == RMVK_ERROR) return RMVK_ERROR;"),
        ("power_regulator_rmvk.h", "RMVK_set_on(0, 0);", "if (RMVK_set_on(0, 0) == RMVK_ERROR) return false;"),
        ("power_regulator_rmvk.h", "RMVK_set_on(1, powerGeneration);", "if (RMVK_set_on(1, powerGeneration) == RMVK_ERROR) return false;"),
        ("power_regulator_rmvk.h", "RMVK_set_out_voltge(MAX_VOLTAGE, powerGeneration);", "if (RMVK_set_out_voltge(MAX_VOLTAGE, powerGeneration) == RMVK_ERROR) return false;"),
        ("power_regulator_rmvk.h", "RMVK_set_out_voltge(Volt, powerGeneration);", "if (RMVK_set_out_voltge(Volt, powerGeneration) == RMVK_ERROR) return false;"),
    )
    for name, old, new in mutations:
        assert old in sources[name], f"Missing mutation target: {old}"
        mutated = dict(sources)
        mutated[name] = sources[name].replace(old, new, 1)
        result = run(mutated)
        assert result.returncode and "FAIL: RMVK" in result.stderr, result.stderr
    print("RMVK command compatibility and 5 mutation checks passed")


if __name__ == "__main__":
    main()
