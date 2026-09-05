#!/usr/bin/env python3
"""Контракт второго I2C-насоса над царгой пастеризации."""

from pathlib import Path
from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
LOGIC = (ROOT / "logic.h").read_text(encoding="utf-8")
I2C = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
MENU = (ROOT / "Menu.ino").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


enabled = extract_function_body(LOGIC, "inline bool rect_second_i2c_pump_enabled()")
require("SamSetup.UseSecondI2CPump" in enabled,
        "second pump must be opt-in")
require("use_I2C_dev == I2CSTEPPER_PUMP_ADDR" in enabled,
        "second pump must use only the device discovered at startup")

start = extract_function_body(I2C, "inline bool start_second_i2c_pump(")
stop = extract_function_body(I2C, "inline bool stop_second_i2c_pump()")
require("i2c_stepper_send_confirmed_command" in start and "I2CSTEP_CMD_START" in start,
        "second pump start must use the ten-send confirmed command")
require("i2c_stepper_send_confirmed_command" in stop and "I2CSTEP_CMD_STOP" in stop,
        "second pump stop must use the ten-send confirmed command")

apply_row = extract_function_body(LOGIC, "inline bool rect_apply_second_pump_for_row(")
require("row.WType == 'H'" in apply_row,
        "heads row must run the I2C pump in filling mode")
require("program_type_one_of(row.WType, \"BC\")" in apply_row,
        "body and pre-flood rows must run the I2C pump continuously")
require("SamSetup.SecondI2CPumpRate" in apply_row,
        "body/preflood rate must come from the dedicated setting")
require("stop_second_i2c_pump()" in apply_row,
        "other rows must stop the second pump")

run_program = extract_function_body(LOGIC, "void run_program(uint8_t num)")
require("rect_apply_second_pump_for_row(program[num])" in run_program,
        "every rectification row must apply second-pump routing")
require("rect_fail_second_i2c_pump" in run_program,
        "an unconfirmed row command must end with an explicit error")
require("if (!rectSecondPumpHeadsRow)" in run_program,
        "local pump must stay stopped while heads use the I2C pump")

pause = extract_function_body(LOGIC, "void pause_withdrawal(bool Pause)")
require("rect_pause_second_i2c_pump()" in pause,
        "manual pause must stop the second pump")
require("rect_resume_second_i2c_pump()" in pause,
        "manual resume must restore the second pump")

menu = extract_function_body(MENU, "void menu_samovar_start()")
require(menu.count("if (rectProgramCommandFailed) return;") >= 2,
        "initial start and row continuation must not overwrite I2C failure state")

print("OK: rectification routes the startup-discovered I2C pump without fallback")
