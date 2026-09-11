#!/usr/bin/env python3
"""T09: staged /save pH pair and real Cheese validity helpers."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]


def compile_and_run(source: str, label: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-t09-ph-") as temp_dir:
        source_path = Path(temp_dir) / "ph.cpp"
        binary_path = Path(temp_dir) / "ph"
        source_path.write_text(source, encoding="utf-8")
        built = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True, text=True, check=False)
        if built.returncode:
            return built.returncode, built.stdout + built.stderr
        ran = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def main() -> int:
    web = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
    cheese = (ROOT / "cheese.h").read_text(encoding="utf-8")
    errors: list[str] = []
    try:
        shared = extract_function_body(
            cheese, "inline bool cheese_ph_calibration_valid(float slope, float offset)")
        save = extract_function_body(web, "void handleSave(AsyncWebServerRequest *request)")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    require_ordered_tokens(
        "pH /save validates final staged pair before commit",
        save,
        ["apply_save_float_arg", "cheese_ph_calibration_valid(",
         "queue_profile_operation("], errors)
    if "cheese_ph_calibration_requested(request)" not in save:
        errors.append("pH final-pair validation is not limited to pH partial POST")
    if errors:
        print("\n".join(f"FAIL: {error}" for error in errors), file=sys.stderr)
        return 1

    harness = f'''\
#include <cmath>
#include <iostream>
using std::isfinite;
struct SetupEEPROM {{ float CheesePhSlope; float CheesePhOffset; }};
inline bool cheese_ph_calibration_valid(float slope, float offset) {{
{shared}
}}
int main() {{
  const SetupEEPROM positive = {{0.003f, 7.0f}};
  const SetupEEPROM negative = {{-0.003f, 7.0f}};
  const SetupEEPROM zero = {{0.0f, 7.0f}};
  const SetupEEPROM invalid = {{NAN, 7.0f}};
  const SetupEEPROM range = {{0.003f, 101.0f}};
  if (!cheese_ph_calibration_valid(positive.CheesePhSlope, positive.CheesePhOffset) ||
      !cheese_ph_calibration_valid(negative.CheesePhSlope, negative.CheesePhOffset) ||
      cheese_ph_calibration_valid(zero.CheesePhSlope, zero.CheesePhOffset) ||
      cheese_ph_calibration_valid(invalid.CheesePhSlope, invalid.CheesePhOffset) ||
      cheese_ph_calibration_valid(range.CheesePhSlope, range.CheesePhOffset)) {{
    std::cerr << "FAIL: final candidate pH pair validity" << std::endl;
    return 1;
  }}
  return 0;
}}
'''
    code, output = compile_and_run(harness, "pH staged pair")
    if code:
        sys.stderr.write(output)
        return 1
    mutant = harness.replace("slope != 0.0f", "true", 1)
    code, output = compile_and_run(mutant, "zero pH slope mutation")
    if code == 0 or "final candidate pH pair validity" not in output:
        print("FAIL: mutation survived: zero pH slope", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("T09 staged pH calibration server contract passed; mutation rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
