#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "data" / "calibrate.htm"

errors = []

if not PAGE.exists():
  errors.append("data/calibrate.htm not found")
  text = ""
else:
  text = PAGE.read_text(encoding="utf-8", errors="ignore")

if text:
  for token in [
    "let calibrationRunning = false;",
    "function updateCalibrationButton()",
    "calibrationRunning ? 'Зафиксировать 100 мл' : 'Начать калибровку'",
  ]:
    if token not in text:
      errors.append(f"data/calibrate.htm missing calibration state token: {token}")

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
        "nextCalibrationRunning = true;",
        "nextCalibrationRunning = false;",
        "let resp = await fetch('/calibrate?' + command + '=1');",
        "if (!resp.ok) { alert(resp.status + ': ' + resp.statusText); return; }",
        "let text = await resp.text();",
        "calibrationRunning = nextCalibrationRunning;",
        "updateCalibrationButton();",
        "if (text !== \"OK\") document.getElementById('stepperstepml').value = text;",
      ],
      errors,
    )
    resp_ok_pos = calibrate_body.find("if (!resp.ok)")
    state_pos = calibrate_body.find("calibrationRunning = nextCalibrationRunning;")
    label_pos = calibrate_body.find("updateCalibrationButton();")
    if state_pos < 0 or label_pos < 0:
      errors.append("calibrate() does not update explicit state and button label")
    elif resp_ok_pos >= 0 and (state_pos < resp_ok_pos or label_pos < resp_ok_pos):
      errors.append("calibrate() changes state/button before resp.ok check")

  try:
    onload_body = extract_function_body(text, "window.onload = function()")
  except ValueError as exc:
    errors.append(str(exc))
    onload_body = ""
  if onload_body and "updateCalibrationButton();" not in onload_body:
    errors.append("window.onload does not initialize calibration button from explicit state")

if errors:
  print("Calibration UX smoke check failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)

print("Calibration UX smoke check passed")
