#!/usr/bin/env python3
"""Calibration is owned by the selected Nano, never Samovar profile defaults."""

import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
I2C = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
SAMOVAR = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
errors = []


def body(source: str, signature: str) -> str:
  try:
    return extract_function_body(source, signature)
  except ValueError as exc:
    errors.append(str(exc))
    return ""


start = body(I2C, "inline bool start_second_i2c_pump(")
require_ordered_tokens("selected Nano calibration", start, [
    "i2c_stepper_selected_pump()", "device->config.stepsPerMl",
    "uint64_t(volumeMl) * device->config.stepsPerMl",
], errors)
if "StepperStepMlI2C" in start:
  errors.append("pump calibration must not read Samovar profile")

calibration_offset = SAMOVAR.rfind("static OperationError execute_pending_i2c_calibration")
calibration = body(SAMOVAR[calibration_offset:],
                   "static OperationError execute_pending_i2c_calibration")
require_ordered_tokens("Nano calibration confirmation", calibration, [
    "i2c_stepper_device(command.address)", "I2CSTEPPER_V3_CMD_CALIBRATE_FINISH",
    "confirm_i2c_candidate(candidate)", "*device = candidate",
    "I2CPumpCalibrating = false", "i2c_stepper_web_lease_clear(command.address)",
], errors)
if "save_profile_nvs(SamSetup)" in calibration:
  errors.append("external Nano calibration must not depend on Samovar profile persistence")
if "StepperStepMlI2C" in calibration:
  errors.append("calibration result must not be copied into SamSetup")

if errors:
  print("I2C pump calibration smoke failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)
print("I2C pump calibration smoke passed")
