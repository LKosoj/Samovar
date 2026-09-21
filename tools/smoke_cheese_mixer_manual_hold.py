#!/usr/bin/env python3
"""Сыр: ручной останов I2C-мешалки держится до возврата управления программе."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cheese.h").read_text(encoding="utf-8")

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
struct WProgram { char WType; float Volume; float Speed; float Power; uint8_t capacity_num; };
struct CheeseRuntimeState { uint32_t mixerDeadlineMs; uint8_t mixerDevice; bool mixerRunning, mixerOneShotComplete, mixerReversed; };
struct Setup { bool rele2 = true; } SamSetup;
static const int RELE_CHANNEL2 = 2;
static CheeseRuntimeState cheeseRuntime = {};
static bool mixer_status = false;
static volatile bool i2cStepperMixerManualHold = false;
static uint16_t i2cStepperMixerRpmOverride = 0;
static uint8_t i2cStepperMixerDirOverride = 0;
static int starts = 0, stops = 0;
void digitalWrite(int, bool) {}
bool i2c_stepper_mixer_present() { return true; }
static int directions[8] = {};
bool set_stepper_by_time(uint16_t rpm, bool direction, uint16_t) {
  if (rpm && starts < 8) directions[starts] = direction ? -1 : 1;
  (rpm ? starts : stops)++;
  return true;
}
inline bool cheese_mixer_is_i2c(uint8_t device) {@IS_I2C@}
inline bool cheese_mixer_start(const WProgram& row) {@START@}
inline bool cheese_mixer_stop() {@STOP@}
inline bool cheese_configure_mixer(const WProgram& row, uint32_t nowMs) {@CONFIGURE@}
inline bool cheese_mixer_tick(const WProgram& row, uint32_t nowMs) {@TICK@}
static int failures = 0;
static void check(bool ok, const char* message) {
  if (!ok) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}
static void run(float runSec, float pauseSec, const char* label) {
  WProgram row = {'M', runSec, 30.0f, pauseSec, 2};
  cheeseRuntime = {};
  starts = stops = 0;
  i2cStepperMixerManualHold = true;  // хвост прошлой строки
  check(cheese_configure_mixer(row, 1000) && !i2cStepperMixerManualHold && starts == 1 &&
        mixer_status, label);
  i2cStepperMixerManualHold = true;
  for (uint32_t now = 2000; now < 600000; now += 1000) cheese_mixer_tick(row, now);
  check(starts == 1 && stops == 0 && !mixer_status, label);
  i2cStepperMixerManualHold = false;
  cheese_mixer_tick(row, 600000);
  check(starts == 2 && mixer_status, label);
}
// Работа 10 с, пауза 20 с: три пуска. Устройство 3 меняет направление после каждой паузы,
// устройство 2 - никогда; знак оборотов задаёт только первое направление.
static void reverse(uint8_t device, float rpm, int first, int second, const char* label) {
  WProgram row = {'M', 10.0f, rpm, 20.0f, device};
  cheeseRuntime = {};
  starts = stops = 0;
  i2cStepperMixerManualHold = false;
  check(cheese_configure_mixer(row, 1000), label);
  for (uint32_t now = 2000; now <= 62000; now += 1000) cheese_mixer_tick(row, now);
  check(starts == 3 && stops == 2 && directions[0] == first && directions[1] == second &&
        directions[2] == first, label);
}
int main() {
  reverse(3, 30.0f, 1, -1, "реверс после паузы: прямое начало не чередуется");
  reverse(3, -30.0f, -1, 1, "реверс после паузы: обратное начало не чередуется");
  reverse(2, 30.0f, 1, 1, "обычная I2C-мешалка сменила направление");
  reverse(2, -30.0f, -1, -1, "обычная I2C-мешалка с обратным ходом сменила направление");
  run(10.0f, 20.0f, "цикл работа/пауза: удержание не выдержано или мешалка не вернулась");
  run(0.0f, 0.0f, "постоянное вращение: удержание не выдержано или мешалка не вернулась");
  return failures == 0 ? 0 : 1;
}
'''


def build() -> str:
    parts = {
        "@IS_I2C@": "inline bool cheese_mixer_is_i2c(uint8_t device)",
        "@START@": "inline bool cheese_mixer_start(const WProgram& row)",
        "@STOP@": "inline bool cheese_mixer_stop()",
        "@CONFIGURE@": "inline bool cheese_configure_mixer(const WProgram& row, uint32_t nowMs)",
        "@TICK@": "inline bool cheese_mixer_tick(const WProgram& row, uint32_t nowMs)",
    }
    source = HARNESS
    for token, signature in parts.items():
        source = source.replace(token, extract_function_body(SOURCE, signature))
    return source


def passes(source: str, quiet: bool = False) -> bool:
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-mixer-hold-") as temp:
        cpp = Path(temp) / "test.cpp"
        binary = Path(temp) / "test"
        cpp.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", str(cpp), "-o", str(binary)],
            capture_output=True, text=True)
        if compiled.returncode != 0:
            print(compiled.stderr)
            return False
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        if result.returncode != 0 and not quiet:
            print(result.stderr)
        return result.returncode == 0


def main() -> int:
    source = build()
    if not passes(source):
        return 1
    guard = "cheese_mixer_is_i2c(cheeseRuntime.mixerDevice) && i2cStepperMixerManualHold"
    if guard not in source or passes(source.replace(guard, guard + " && false"), quiet=True):
        print("FAIL: мутация без удержания мешалки не поймана")
        return 1
    for anchor, mutant, label in (
        ("if (row.capacity_num == 3) cheeseRuntime.mixerReversed",
         "if (row.capacity_num == 3 && false) cheeseRuntime.mixerReversed", "без смены направления"),
        ("if (row.capacity_num == 3) cheeseRuntime.mixerReversed",
         "if (row.capacity_num >= 2) cheeseRuntime.mixerReversed", "реверс у обычной I2C-мешалки"),
        ("(row.Speed < 0.0f) != cheeseRuntime.mixerReversed",
         "cheeseRuntime.mixerReversed", "знак оборотов не учитывается"),
        ("return device == 2 || device == 3;", "return device == 2;", "устройство 3 не I2C"),
    ):
        if anchor not in source or passes(source.replace(anchor, mutant), quiet=True):
            print("FAIL: мутация не поймана: " + label)
            return 1
    print("cheese mixer manual hold smoke passed; mutation rejected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
