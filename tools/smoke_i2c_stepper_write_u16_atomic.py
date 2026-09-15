#!/usr/bin/env python3
"""Проверяет v3 codec + один i2c_stepper_write_block для uint16_t."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "libraries" / "I2CStepperProtocol" / "src"
SIGNATURE = "inline bool i2c_stepper_write_u16(uint8_t address, uint8_t reg, uint16_t value)"

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <vector>
#include <I2CStepperV3.h>

struct Call { uint8_t address; uint8_t reg; std::vector<uint8_t> payload; };
static std::vector<Call> calls;
bool i2c_stepper_write_block(uint8_t address, uint8_t reg, const uint8_t* payload,
                             uint8_t size) {
  calls.push_back({address, reg, std::vector<uint8_t>(payload, payload + size)});
  return true;
}
inline bool i2c_stepper_write_u16(uint8_t address, uint8_t reg, uint16_t value) {
@BODY@
}
int main() {
  assert(i2c_stepper_write_u16(2, 13, 0x1234));
  assert(calls.size() == 1 && calls[0].address == 2 && calls[0].reg == 13);
  assert(calls[0].payload.size() == 2 && calls[0].payload[0] == 0x12 &&
         calls[0].payload[1] == 0x34);
  return 0;
}
'''


def compile_and_run(body: str, name: str) -> subprocess.CompletedProcess[str]:
    compiler = shutil.which("g++")
    assert compiler is not None, "g++ is required"
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-u16-") as directory:
        source = Path(directory) / f"{name}.cpp"
        binary = Path(directory) / name
        source.write_text(HARNESS.replace("@BODY@", body), encoding="utf-8")
        built = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(PROTOCOL),
             str(source), "-o", str(binary)], capture_output=True, text=True, check=False)
        if built.returncode != 0:
            return built
        return subprocess.run([str(binary)], capture_output=True, text=True, check=False)


def main() -> int:
    try:
        body = extract_function_body(
            (ROOT / "I2CStepper.h").read_text(encoding="utf-8", errors="ignore"), SIGNATURE)
    except ValueError as error:
        print(f"FAIL: write_u16 helper missing: {error}", file=sys.stderr)
        return 1
    result = compile_and_run(body, "write_u16")
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        return 1
    mutated = body.replace("i2cstepper_v3_write_u16_be(bytes, value);", "bytes[0] = 0; bytes[1] = 0;", 1)
    if mutated == body:
        print("FAIL: write_u16 codec mutation anchor missing", file=sys.stderr)
        return 1
    mutation = compile_and_run(mutated, "write_u16_mutated")
    if mutation.returncode == 0:
        print("FAIL: write_u16 codec mutation survived", file=sys.stderr)
        return 1
    print("i2c v3 write_u16 codec/write_block smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
