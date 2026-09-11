#!/usr/bin/env python3
"""T08: Lai/OIML alcohol table, boundaries and independent Kamihama check."""
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools/fixtures/t08_vle_points.json"
OIML = [998.2012300, -192.9769495, 389.1238958, -1668.103923, 13522.15441,
        -88292.78388, 306287.4042, -613838.1234, 747017.2998, -547846.1354,
        223446.0334, -39032.85426]


def abv20(x: float) -> float:
    w = x * 46.06844 / (x * 46.06844 + (1 - x) * 18.01528)
    density = sum(value * w ** power for power, value in enumerate(OIML))
    return 100 * w * density / 789.24


def points(name: str) -> list[tuple[float, float, float]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))[name]["points"]
    return data if name == "lai" else [(temperature, x, y) for x, temperature, y in data]


def extract(source: str) -> tuple[str, str, str, str]:
    table = re.search(r"struct AlcoholTablePoint \{.*?\n\};\n\nstatic const AlcoholTablePoint ALCOHOL_TABLE\[\] = \{.*?\n\};", source, re.S)
    if not table:
        raise ValueError("AlcoholTablePoint/ALCOHOL_TABLE not found")
    return (table.group(0), extract_function_body(source, "inline float get_alcohol_from_table"),
            extract_function_body(source, "float get_steam_alcohol"),
            extract_function_body(source, "float get_alcohol(float t)"))


def harness(source: str) -> str:
    table, helper, steam, tank = extract(source)
    lai = points("lai")
    source_checks = []
    interval_checks = []
    for index, (temperature, x, y) in enumerate(lai):
        celsius = temperature - 273.15
        source_checks += [
            f'  close_to(get_alcohol({celsius:.5f}f), {abv20(x):.7f}f, "Lai tank node {index}");',
            f'  close_to(get_steam_alcohol({celsius:.5f}f), {abv20(y):.7f}f, "Lai steam node {index}");']
    for index, (high, low) in enumerate(zip(lai, lai[1:])):
        high_t, high_x, high_y = high
        low_t, low_x, low_y = low
        for temperature in (high_t - 273.16, low_t - 273.14):
            fraction = (temperature - (low_t - 273.15)) / (high_t - low_t)
            tank_expected = abv20(low_x) + (abv20(high_x) - abv20(low_x)) * fraction
            steam_expected = abv20(low_y) + (abv20(high_y) - abv20(low_y)) * fraction
            interval_checks += [
                f'  close_to(get_alcohol({temperature:.5f}f), {tank_expected:.7f}f, "tank interval {index}");',
                f'  close_to(get_steam_alcohol({temperature:.5f}f), {steam_expected:.7f}f, "steam interval {index}");']
        midpoint = (high_t + low_t) / 2 - 273.15
        interval_checks += [
            f'  check(get_alcohol({midpoint + .01:.5f}f) < get_alcohol({midpoint - .01:.5f}f), "tank monotonic {index}");',
            f'  check(get_steam_alcohol({midpoint + .01:.5f}f) < get_steam_alcohol({midpoint - .01:.5f}f), "steam monotonic {index}");']
    stats = []
    for temperature, x, y in points("kamihama"):
        celsius = temperature - 273.15
        stats += [f'  accumulate(get_alcohol({celsius:.5f}f), {abv20(x):.7f}f, tankMax, tankSquares);',
                  f'  accumulate(get_steam_alcohol({celsius:.5f}f), {abv20(y):.7f}f, steamMax, steamSquares);',
                  '  ++kamihamaCount;']
    return f'''#include <cmath>
#include <cstdint>
#include <iostream>
static bool boil_started = true;
using std::isfinite;
{table}
inline float get_alcohol_from_table(float t, bool steam) {{{helper}}}
float get_steam_alcohol(float t) {{{steam}}}
float get_alcohol(float t) {{{tank}}}
static int failures = 0;
static void check(bool ok, const char* message) {{ if (!ok) {{ std::cerr << "FAIL: " << message << '\\n'; ++failures; }} }}
static void close_to(float actual, float expected, const char* message) {{ check(std::fabs(actual - expected) < .002f, message); }}
static void accumulate(float actual, float expected, float& maximum, float& squares) {{ const float error = std::fabs(actual - expected); if (error > maximum) maximum = error; squares += error * error; }}
int main() {{
{chr(10).join(source_checks)}
{chr(10).join(interval_checks)}
  close_to(get_alcohol(94.29f), 7.6437f, "tank interpolation");
  close_to(get_steam_alcohol(94.29f), 45.3218f, "steam interpolation");
  check(get_alcohol(39) == -1 && get_steam_alcohol(39) == -1, "39C unavailable");
  check(get_alcohol(78.15f) == -1 && get_steam_alcohol(78.15f) == -1, "lower boundary unavailable");
  check(get_alcohol(78.2f) >= 0 && get_steam_alcohol(78.2f) >= 0, "just inside lower boundary valid");
  check(get_alcohol(97) >= 0 && get_steam_alcohol(98) >= 0 && get_alcohol(99) >= 0, "interior valid");
  check(get_alcohol(100) == 0 && get_steam_alcohol(100) == 0, "100C real zero");
  check(get_alcohol(100.1f) == -1 && get_steam_alcohol(102) == -1 && get_alcohol(106) == -1, "upper boundary unavailable");
  check(get_alcohol(NAN) == -1 && get_steam_alcohol(NAN) == -1 && get_alcohol(INFINITY) == -1 && get_steam_alcohol(-INFINITY) == -1, "nonfinite unavailable");
  boil_started = false;
  check(get_alcohol(90) == -1 && get_steam_alcohol(90) == -1, "warmup unavailable both phases");
  boil_started = true;
  float tankMax = 0, tankSquares = 0, steamMax = 0, steamSquares = 0;
  int kamihamaCount = 0;
{chr(10).join(stats)}
  const float tankRmse = std::sqrt(tankSquares / kamihamaCount);
  const float steamRmse = std::sqrt(steamSquares / kamihamaCount);
  check(kamihamaCount == 14, "Kamihama in-range point count");
  close_to(tankMax, 3.363f, "Kamihama tank max error");
  close_to(tankRmse, 2.084f, "Kamihama tank RMSE");
  close_to(steamMax, 2.031f, "Kamihama steam max error");
  close_to(steamRmse, .882f, "Kamihama steam RMSE");
  std::cout << "Kamihama tank max=" << tankMax << " rmse=" << tankRmse << '\\n';
  std::cout << "Kamihama steam max=" << steamMax << " rmse=" << steamRmse << '\\n';
  return failures ? 1 : 0;
}}'''


def compile_and_run(code: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-t08-") as directory:
        cpp = Path(directory) / "test.cpp"
        binary = Path(directory) / "test"
        cpp.write_text(code, encoding="utf-8")
        compiled = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)], capture_output=True, text=True)
        if compiled.returncode:
            return compiled.returncode, "COMPILE FAIL:\n" + compiled.stderr
        run = subprocess.run([str(binary)], capture_output=True, text=True)
        return run.returncode, run.stdout + run.stderr


def reject_mutant(name: str, source: str) -> bool:
    result, output = compile_and_run(harness(source))
    if result == 0:
        print(f"FAIL: {name} mutation survived", file=sys.stderr)
        return False
    if "FAIL:" not in output or "COMPILE FAIL:" in output:
        print(f"FAIL: {name} mutation did not fail an assertion:\n{output}", file=sys.stderr)
        return False
    print(f"{name} mutation rejected:\n{output}", end="")
    return True


def main() -> int:
    if not FIXTURE.is_file():
        print(f"FAIL: fixture absent: {FIXTURE}", file=sys.stderr)
        return 1
    source = (ROOT / "logic.h").read_text(encoding="utf-8")
    result, output = compile_and_run(harness(source))
    sys.stdout.write(output)
    if result:
        return 1
    mutants = [
        ("table", source.replace("{96.120000f, 4.708548f, 35.359976f}", "{96.120000f, 40.708548f, 35.359976f}", 1)),
        ("range", source.replace("t < ALCOHOL_TABLE[13].temperature", "t < ALCOHOL_TABLE[12].temperature", 1)),
        ("phase", source.replace("return get_alcohol_from_table(t, true);", "return get_alcohol_from_table(t, false);", 1)),
    ]
    if any(mutant == source or not reject_mutant(name, mutant) for name, mutant in mutants):
        return 1
    print("T08 alcohol model: primary nodes, intervals, boundaries and mutations passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
