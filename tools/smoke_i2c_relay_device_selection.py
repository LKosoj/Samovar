#!/usr/bin/env python3
"""Поведенческая проверка правила приоритета mixer/pump в select_relay_capable_device
(I2CStepper.h): если mixer на связи и умеет CAP_RELAY - берём его, иначе pump с
CAP_RELAY. Тело функции берётся дословно из реального файла через extract_function_body,
а не копируется в тест."""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

#define I2CSTEPPER_CAP_RELAY @CAP_RELAY@

struct I2CStepperDevice {
  uint8_t caps = 0;
};

I2CStepperDevice i2cStepperMixer;
I2CStepperDevice i2cStepperPump;

static int mixerRefreshCalls = 0;
static int pumpRefreshCalls = 0;
static bool mixerRefreshResult = false;
static bool pumpRefreshResult = false;

bool i2c_stepper_refresh(I2CStepperDevice& dev) {
  if (&dev == &i2cStepperMixer) { mixerRefreshCalls++; return mixerRefreshResult; }
  if (&dev == &i2cStepperPump) { pumpRefreshCalls++; return pumpRefreshResult; }
  return false;
}

@SELECT_RELAY_CAPABLE_DEVICE@

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_counters() {
  mixerRefreshCalls = 0;
  pumpRefreshCalls = 0;
}

int main() {
  // (1) оба на связи и оба с CAP_RELAY -> выбран mixer
  mixerRefreshResult = true;
  i2cStepperMixer.caps = I2CSTEPPER_CAP_RELAY;
  pumpRefreshResult = true;
  i2cStepperPump.caps = I2CSTEPPER_CAP_RELAY;
  reset_counters();
  I2CStepperDevice* selected1 = select_relay_capable_device();
  check(selected1 == &i2cStepperMixer,
        "сценарий 1: если оба устройства годны, приоритет должен быть у mixer");
  check(pumpRefreshCalls == 0,
        "сценарий 1: refresh для pump не должен вызываться, если mixer уже годен (лишний обмен по I2C)");

  // (2) mixer без CAP_RELAY, pump с CAP_RELAY -> выбран pump
  mixerRefreshResult = true;
  i2cStepperMixer.caps = 0;
  pumpRefreshResult = true;
  i2cStepperPump.caps = I2CSTEPPER_CAP_RELAY;
  reset_counters();
  I2CStepperDevice* selected2 = select_relay_capable_device();
  check(selected2 == &i2cStepperPump,
        "сценарий 2: если у mixer нет CAP_RELAY, должен выбираться pump");

  // (3) mixer не отвечает (refresh=false), pump годен -> выбран pump
  mixerRefreshResult = false;
  i2cStepperMixer.caps = I2CSTEPPER_CAP_RELAY;
  pumpRefreshResult = true;
  i2cStepperPump.caps = I2CSTEPPER_CAP_RELAY;
  reset_counters();
  I2CStepperDevice* selected3 = select_relay_capable_device();
  check(selected3 == &i2cStepperPump,
        "сценарий 3: если mixer не на связи, должен выбираться pump");

  // (4) ни один не годится -> nullptr
  mixerRefreshResult = false;
  i2cStepperMixer.caps = I2CSTEPPER_CAP_RELAY;
  pumpRefreshResult = false;
  i2cStepperPump.caps = I2CSTEPPER_CAP_RELAY;
  reset_counters();
  I2CStepperDevice* selected4 = select_relay_capable_device();
  check(selected4 == nullptr,
        "сценарий 4: если ни mixer, ни pump не годны, результат должен быть nullptr");

  if (failures != 0) return 1;
  std::cout << "i2c relay device selection: mixer/pump priority verified\n";
  return 0;
}
'''


def compile_and_run(source: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-relay-") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / "i2c_relay.cpp"
        binary_path = temp / "i2c_relay"
        source_path.write_text(source, encoding="utf-8")
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
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode
        result = subprocess.run(
            [str(binary_path)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode


def main() -> int:
    source = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")

    cap_relay_match = re.search(r"#define\s+I2CSTEPPER_CAP_RELAY\s+(\S+)", source)
    if not cap_relay_match:
        print("FAIL: I2CSTEPPER_CAP_RELAY macro not found in I2CStepper.h", file=sys.stderr)
        return 1
    cap_relay = cap_relay_match.group(1)

    signature = "inline I2CStepperDevice* select_relay_capable_device()"
    try:
        body = extract_function_body(source, signature)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    function = "I2CStepperDevice* select_relay_capable_device() {" + body + "}"

    harness = HARNESS_TEMPLATE.replace("@CAP_RELAY@", cap_relay).replace(
        "@SELECT_RELAY_CAPABLE_DEVICE@", function
    )
    return compile_and_run(harness)


if __name__ == "__main__":
    raise SystemExit(main())
