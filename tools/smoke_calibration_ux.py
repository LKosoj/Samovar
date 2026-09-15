#!/usr/bin/env python3
"""Source-derived contract for local and selected Nano calibration UI."""

import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "data_raw" / "calibrate.htm").read_text(encoding="utf-8")
WEB = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
errors: list[str] = []

if "StepperStepMlI2C" in PAGE or "pump_type" in PAGE:
    errors.append("external calibration must not expose the retired Samovar pump selector")
for token in (
    "Калибровка внешнего I2C-насоса",
    "Калибровка внешнего насоса сейчас недоступна.",
    "'/i2cstepper?address=' + externalAddress",
    "'/i2cstepper.htm?address=' + externalAddress",
    "bootstrap.processRunning || calibrationRunning",
    "document.getElementById('save').remove();",
    "fetch('/i2cstepper?address=' + externalAddress + '&cmd=lease'",
    "window.setInterval(touchExternalLease, 2000)",
):
    if token not in PAGE:
        errors.append(f"external calibration UI missing {token}")

try:
    calibrate = extract_function_body(PAGE, "async function calibrate()")
    readback = extract_function_body(PAGE, "async function readExternalCalibration()")
except ValueError as exc:
    errors.append(str(exc))
    calibrate = readback = ""

require_ordered_tokens(
    "external finish waits for the terminal operation before Nano readback",
    calibrate,
    [
        "params.set('address', String(externalAddress))",
        "params.set('finish', '1')",
        "SamovarApp.readOperationAcceptance(response)",
        "SamovarApp.waitForOperation(acceptance.operationId)",
        "calibrationRunning = !wasRunning;",
        "await readExternalCalibration();",
    ],
    errors,
)

if "leaseTimer" in (ROOT / "data_raw" / "i2cstepper.htm").read_text(encoding="utf-8"):
    errors.append("operational I2C page must not own the calibration lease")
require_ordered_tokens(
    "external readback uses selected address",
    readback,
    [
        "'/i2cstepper?address=' + externalAddress",
        "await response.json();",
        "payload.selected",
        "device.config.stepsPerMl",
        "externalStepsPerMl = Number(device.config.stepsPerMl);",
    ],
    errors,
)

handler = extract_function_body(WEB, "void calibrate_command")
for token in (
    'param->name() == "address"',
    "select_i2c_stepper_device(request, address)",
    "!device->present",
    "I2CSTEPPER_V3_CAP_FILLING",
    "I2CSTEPPER_V3_STATUS_RUNNING",
    "command.address = address;",
    "isFinish ? !deviceCalibrating : deviceRunning || deviceCalibrating",
):
    if token not in handler:
        errors.append(f"/calibrate selected Nano guard missing {token}")

if errors:
    print("Calibration UX smoke check failed:")
    for error in errors:
        print(" - " + error)
    sys.exit(1)
print("Calibration UX smoke check passed")
