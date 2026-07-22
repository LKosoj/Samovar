#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "data_raw" / "calibrate.htm"
WEB = ROOT / "WebServer.ino"

errors = []

if not PAGE.exists():
  errors.append("data_raw/calibrate.htm not found")
  text = ""
else:
  text = PAGE.read_text(encoding="utf-8", errors="ignore")

if text:
  for token in [
    "let calibrationRunning = Number('%CalibrationRunning%') === 1;",
    "let calibrationPump = calibrationRunning ? '%CalibrationPump%' : '';",
    "let calibrationInFlight = false;",
    "function updateCalibrationButton()",
    "calibrationRunning ? 'Зафиксировать 100 мл' : 'Начать калибровку'",
    "document.getElementById('pump_type').disabled = calibrationRunning || calibrationInFlight;",
  ]:
    if token not in text:
      errors.append(f"data_raw/calibrate.htm missing calibration state token: {token}")

  if re.search(r"calibrateid['\"]\)\.value\s*==", text):
    errors.append("calibrate() still derives calibration state from button text")

  try:
    calibrate_body = extract_function_body(text, "async function calibrate()")
  except ValueError as exc:
    errors.append(str(exc))
    calibrate_body = ""
  if calibrate_body:
    require_ordered_tokens(
      "calibrate UI state changes only after successful response",
      calibrate_body,
      [
        "if (!calibrationRunning)",
        "SamovarApp.readNumericInput('kstepperspd'",
        "nextCalibrationRunning = true;",
        "nextCalibrationRunning = false;",
        "let resp = await fetch('/calibrate?' + params.toString());",
        "if (!resp.ok)",
        "SamovarApp.responseErrorText",
        "return false;",
        "SamovarApp.readOperationAcceptance(resp);",
        "SamovarApp.waitForOperation(acceptance.operationId);",
        "calibrationRunning = nextCalibrationRunning;",
        "calibrationPump = calibrationRunning ? pump : '';",
        "if (!nextCalibrationRunning)",
        "readConfirmedCalibrationValue(pump)",
        "SamovarApp.clearRequestError();",
      ],
      errors,
    )
    resp_ok_pos = calibrate_body.find("if (!resp.ok)")
    terminal_pos = calibrate_body.find("SamovarApp.waitForOperation(acceptance.operationId);")
    state_pos = calibrate_body.find("calibrationRunning = nextCalibrationRunning;")
    if state_pos < 0:
      errors.append("calibrate() does not update explicit state")
    elif resp_ok_pos >= 0 and state_pos < resp_ok_pos:
      errors.append("calibrate() changes calibration state before resp.ok check")
    elif terminal_pos < 0 or state_pos < terminal_pos:
      errors.append("calibrate() changes calibration state before terminal success")
    for forbidden in ("await resp.text()", "text !== 'OK'", 'text !== "OK"'):
      if forbidden in calibrate_body:
        errors.append(f"calibrate() retains pre-operation response contract: {forbidden}")
    for token in [
      "if (calibrationInFlight) return false;",
      "calibrationInFlight = true;",
      "calibrationInFlight = false;",
      "const pump = calibrationRunning ? calibrationPump : getPumpType();",
    ]:
      if token not in calibrate_body:
        errors.append(f"calibrate() missing in-flight/pump lock token: {token}")

  try:
    confirmed_body = extract_function_body(
      text, "async function readConfirmedCalibrationValue(pump)")
  except ValueError as exc:
    errors.append(str(exc))
    confirmed_body = ""
  if confirmed_body:
    require_ordered_tokens(
      "finish reads the confirmed calibration value without fallback",
      confirmed_body,
      [
        "pump === 'i2c' ? '/i2cstepper?device=pump' : '/ajax?messageCursor=0'",
        "await fetch(url, { cache: 'no-store' });",
        "if (!resp.ok)",
        "await resp.json();",
        "pump === 'i2c' ? data.stepsPerMl : data.StepperStepMl",
        "Number.isInteger(stepsPerMl)",
        "return stepsPerMl * 100;",
      ],
      errors,
    )
    for token in ("stepperStepMlLocal", "stepperStepMlI2C", "catch"):
      if token in confirmed_body:
        errors.append(f"confirmed calibration read contains fallback path: {token}")

  try:
    onload_body = extract_function_body(text, "window.onload = function()")
  except ValueError as exc:
    errors.append(str(exc))
    onload_body = ""
  if onload_body and "updateCalibrationButton();" not in onload_body:
    errors.append("window.onload does not initialize calibration button from explicit state")

if not WEB.exists():
  errors.append("WebServer.ino not found")
else:
  web = WEB.read_text(encoding="utf-8", errors="ignore")
  try:
    processor = extract_function_body(web, "String calibrateKeyProcessor(const String &var)")
  except ValueError as exc:
    errors.append(str(exc))
    processor = ""
  for token in [
    'var == "CalibrationRunning"',
    "startval == SAMOVAR_STARTVAL_CALIBRATION || I2CPumpCalibrating",
    'var == "CalibrationPump"',
    'I2CPumpCalibrating ? "i2c" : "local"',
  ]:
    if token not in processor:
      errors.append(f"calibrate server hydration missing token: {token}")

if errors:
  print("Calibration UX smoke check failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)

print("Calibration UX smoke check passed")
