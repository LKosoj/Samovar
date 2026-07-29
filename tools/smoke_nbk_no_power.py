#!/usr/bin/env python3
"""Пинит явный отказ и полный cleanup НБК в Samovar_no_power."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

SETPOINT_HARNESS = r'''
#include <cstdint>
#include <iostream>

enum ActuatorCommandResult : uint8_t {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
static int setCurrentCalls = 0;
float fromPower(float watts) { return watts / 10.0f; }
ActuatorCommandResult set_current_power(float volts, uint64_t* generation) {
  setCurrentCalls++;
  if (volts != 90.0f) return ACTUATOR_COMMAND_FAILED;
  *generation = 77;
  return ACTUATOR_COMMAND_PENDING;
}
inline ActuatorCommandResult nbk_set_power(float watts, uint64_t* generation = nullptr) {
@BODY@
}
int main() {
  uint64_t generation = 19;
  const ActuatorCommandResult result = nbk_set_power(900.0f, &generation);
#ifdef SAMOVAR_USE_POWER
  if (result != ACTUATOR_COMMAND_PENDING || generation != 77 || setCurrentCalls != 1) return 1;
#else
  if (result != ACTUATOR_COMMAND_FAILED || generation != 0 || setCurrentCalls != 0) return 2;
#endif
  return 0;
}
'''


def run_setpoint_matrix(body: str, emit: bool) -> int:
    for enabled in (False, True):
        with tempfile.TemporaryDirectory(prefix="samovar-nbk-no-power-") as temp_dir:
            temp = Path(temp_dir)
            source = temp / "nbk_set_power.cpp"
            binary = temp / "nbk_set_power"
            source.write_text(SETPOINT_HARNESS.replace("@BODY@", body), encoding="utf-8")
            command = ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror"]
            if enabled:
                command.append("-DSAMOVAR_USE_POWER")
            command.extend([str(source), "-o", str(binary)])
            build = subprocess.run(command, capture_output=True, text=True, check=False)
            if build.returncode:
                if emit:
                    sys.stderr.write(build.stderr)
                return build.returncode
            result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
            if result.returncode:
                if emit:
                    sys.stderr.write(result.stderr)
                return result.returncode
    return 0

nbk = (ROOT / "nbk.h").read_text(encoding="utf-8")
samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")

try:
    run_body = extract_function_body(
        nbk, "void run_nbk_program(uint8_t num, bool workConfirmed) {"
    )
except ValueError as error:
    errors.append(str(error))
    run_body = ""

if run_body:
    start = run_body.find("#ifndef SAMOVAR_USE_POWER")
    end = run_body.find("#endif", start)
    if start < 0 or end < 0:
        errors.append("run_nbk_program missing explicit no-power branch")
    else:
        no_power = run_body[start:end]
        require_ordered_tokens(
            "no-power NBK rejects before normal start and performs cleanup",
            no_power,
            [
                "if (num == 0) {",
                "nbk_reset_actuator_command();",
                "SetSpeed(0);",
                "set_power(false, false);",
                "cancel_nbk_transition();",
                '"Запуск НБК отклонён: регулятор мощности недоступен',
                "ProgramNum = 0;",
                "startval = SAMOVAR_STARTVAL_IDLE;",
                "SamovarStatusInt = SAMOVAR_STATUS_IDLE;",
                "nbk_M = 0;",
                "feedResult == ACTUATOR_COMMAND_APPLIED;",
                "nbk_clear_session_config();",
                "nbk_close_data_log();",
                "return;",
            ],
            errors,
        )
        normal_start = run_body.find("if (nbk_finish_transition_active())")
        if normal_start >= 0 and end > normal_start:
            errors.append("no-power rejection occurs after normal NBK start logic")
        if "nbk_P = 0;" in no_power:
            errors.append("no-power cleanup claims feed=0 before SetSpeed APPLIED")

try:
    set_power_body = extract_function_body(
        nbk,
        "inline ActuatorCommandResult nbk_set_power(float watts, uint64_t* generation = nullptr) {",
    )
except ValueError as error:
    errors.append(str(error))
    set_power_body = ""

if set_power_body:
    require_ordered_tokens(
        "no-power regulated setpoint is never emulated",
        set_power_body,
        [
            "#ifdef SAMOVAR_USE_POWER",
            "set_current_power(fromPower(watts), generation)",
            "#else",
            "*generation = 0;",
            "return ACTUATOR_COMMAND_FAILED;",
        ],
        errors,
    )

try:
    tick_body = extract_function_body(nbk, "inline void tick_nbk_actuator_command() {")
except ValueError as error:
    errors.append(str(error))
    tick_body = ""

if tick_body:
    require_ordered_tokens(
        "no-power pending regulator state terminates as FAILED",
        tick_body,
        [
            "ACTUATOR_COMMAND_PENDING",
            "#ifdef SAMOVAR_USE_POWER",
            "current_power_command_status(",
            "#else",
            "nbkActuatorCommand.result = ACTUATOR_COMMAND_FAILED;",
        ],
        errors,
    )

case_start = samovar.find("case SAMOVAR_NBK:")
case_end = samovar.find("break;", case_start)
if case_start < 0 or case_end < 0:
    errors.append("Samovar.ino missing SAMOVAR_NBK dispatch")
else:
    dispatch = samovar[case_start:case_end]
    require_ordered_tokens(
        "no-power dispatch rejects before mode start",
        dispatch,
        [
            "#ifdef SAMOVAR_USE_POWER",
            "mode_apply_power_on_command(commandMsg.command);",
            "#else",
            '"Запуск НБК отклонён: регулятор мощности недоступен',
        ],
        errors,
    )

if "inline void set_current_power" in nbk:
    errors.append("nbk.h must not reintroduce a no-power set_current_power shim")

if set_power_body and run_setpoint_matrix(set_power_body.replace("\r\n", "\n"), True) != 0:
    errors.append("nbk_set_power feature matrix failed")
if set_power_body:
    mutation = set_power_body.replace(
        "return ACTUATOR_COMMAND_FAILED;",
        "return ACTUATOR_COMMAND_APPLIED;",
        1,
    )
    if mutation == set_power_body:
        errors.append("nbk_set_power no-power mutation anchor missing")
    elif run_setpoint_matrix(mutation.replace("\r\n", "\n"), False) == 0:
        errors.append("nbk_set_power no-power mutation survived")

if errors:
    print("NBK no-power smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("NBK no-power rejection and cleanup smoke passed")
