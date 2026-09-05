#!/usr/bin/env python3
"""Проверяет snapshot строки и максимум один переход withdrawal за tick."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <iostream>

using ProgramType = char;

struct WProgram {
  ProgramType WType;
  uint16_t Volume;
  float Speed;
  uint8_t capacity_num;
  float Temp;
  float Power;
  uint8_t TempSensor;
  float Time;
};

constexpr int16_t SAMOVAR_STARTVAL_RECT_RUNNING = 1;
constexpr int16_t SAMOVAR_STARTVAL_RECT_DONE = 2;

@HELPER@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  WProgram absolute = {'B', 100, 1.0f, 1, 79.5f, 0, 0, 0};
  check(rect_row_transition_requested(
            absolute, 100, 100, SAMOVAR_STARTVAL_RECT_RUNNING, 80.0f, 77.0f),
        "одновременное достижение объёма и температуры должно запросить один переход");

  WProgram relative = {'P', 0, 0, 0, 1.5f, 0, 0, 10};
  check(!rect_row_transition_requested(
            relative, 0, 0, SAMOVAR_STARTVAL_RECT_RUNNING, 79.4f, 78.0f),
        "относительный порог P не должен срабатывать раньше времени");
  check(rect_row_transition_requested(
            relative, 0, 0, SAMOVAR_STARTVAL_RECT_RUNNING, 79.6f, 78.0f),
        "ненулевой Temp строки P должен использовать snapshot StartProgTemp");

  WProgram disabled = {'B', 0, 0, 0, 0, 0, 0, 0};
  check(!rect_row_transition_requested(
            disabled, 0, 50, SAMOVAR_STARTVAL_RECT_RUNNING, 99.0f, 78.0f),
        "нулевые объём и Temp не должны менять строку");

  // [Б3] currentStartval == RECT_DONE недостижим (withdrawal() делает ранний
  // return раньше вызова этой функции) - даже при выполненном условии по шагам
  // переход по объёму больше не должен срабатывать в этой ветке.
  WProgram doneRow = {'B', 100, 1.0f, 1, 0, 0, 0, 0};
  check(!rect_row_transition_requested(
            doneRow, 100, 100, SAMOVAR_STARTVAL_RECT_DONE, 80.0f, 77.0f),
        "[Б3] currentStartval == RECT_DONE с выполненным условием по шагам должен вернуть false");

  if (failures != 0) return 1;
  std::cout << "rectification row transition snapshot checks passed\n";
  return 0;
}
'''


def main() -> int:
    source = (ROOT / "logic.h").read_text(encoding="utf-8")
    clean = strip_cpp_comments(source)
    helper_body = extract_function_body(
        source, "inline bool rect_row_transition_requested"
    )
    withdrawal_body = extract_function_body(source, "void withdrawal(void)")

    snapshot_tokens = [
        "const uint8_t currentProgram = ProgramNum;",
        "const WProgram currentRow",
        "const ProgramType currentType = program_type_at(currentProgram);",
        "const float currentSteamTemp = SteamSensor.avgTemp;",
        "const float currentSteamStartTemp = SteamSensor.StartProgTemp;",
        "const uint32_t currentTargetSteps = TargetStepps;",
        "const uint32_t currentCompletedSteps = rect_current_withdrawal_steps();",
        "const int16_t currentStartval = startval;",
        "process_impurity_detector();",
        "(!detectorWaitWasActive && program_Wait)",
        "rect_row_transition_requested(",
        "menu_samovar_start();",
        "return;",
    ]
    cursor = 0
    for token in snapshot_tokens:
        cursor = withdrawal_body.find(token, cursor)
        if cursor < 0:
            print(f"FAIL: withdrawal snapshot/return contract missing: {token}", file=sys.stderr)
            return 1
        cursor += len(token)
    transition_call = withdrawal_body.find("rect_row_transition_requested(")
    tail = withdrawal_body[transition_call:]
    if "program[ProgramNum]" in tail:
        print(
            "FAIL: withdrawal повторно читает активную строку после snapshot",
            file=sys.stderr,
        )
        return 1
    if clean.count("inline bool rect_row_transition_requested") != 1:
        print("FAIL: helper перехода должен иметь единственного владельца", file=sys.stderr)
        return 1

    helper = (
        "bool rect_row_transition_requested("
        "const WProgram& row, uint32_t targetSteps, uint32_t currentSteps, "
        "int16_t currentStartval, float steamTemp, float steamStartTemp) {"
        + helper_body
        + "}"
    )
    harness = HARNESS.replace("@HELPER@", helper)
    with tempfile.TemporaryDirectory(prefix="samovar-rect-transition-") as temp_dir:
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

        result = compile_and_run("rect_transition", harness)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode != 0:
            return result.returncode

        mutant = harness.replace(
            "const float threshold =\n"
            "      row.Temp > 0 && row.Temp < 20 ? row.Temp + steamStartTemp : row.Temp;",
            "const float threshold = row.Temp;",
            1,
        )
        if mutant == harness:
            print("FAIL: не удалось построить мутацию относительного порога", file=sys.stderr)
            return 1
        if compile_and_run("rect_transition_mutant", mutant).returncode == 0:
            print("FAIL: мутация относительного порога пережила тест", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
