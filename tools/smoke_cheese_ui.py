#!/usr/bin/env python3
"""Static contract for the standalone cheese UI assets."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
errors: list[str] = []


def read(name: str) -> str:
    path = DATA / name
    if not path.is_file():
        errors.append(f"data_raw/{name} is missing")
        return ""
    return path.read_text(encoding="utf-8")


cheese = read("cheese.htm")
calibrate = read("calibrate_ph.htm")
cheese_lua = read("cheese.lua")
button1 = read("btn_cheese_button1.lua")
button2 = read("btn_cheese_button2.lua")

stage_values = re.findall(r'<option value="([A-Za-z])"', cheese)
expected_stages = list("MPCWALZfzds pvrnSR".replace(" ", ""))
if stage_values != expected_stages:
    errors.append(f"cheese editor stages are {stage_values}, expected {expected_stages}")

for token in (
    "CHEESE_PROGRAM_MAX_ROWS = 20",
    "CHEESE_PROGRAM_FIELDS = 6",
    "function parseCheeseProgram(",
    "function validateCheeseRow(",
    "function applyRowRules(",
    "function serializeCheeseRows(",
    "SamovarApp.postProgram(document.forms.mainform)",
    'maxlength="250"',
    "PROGRAM_BACKUP_VERSION = 1",
    "new TextEncoder().encode(description).length",
    "backup.version !== PROGRAM_BACKUP_VERSION",
):
    if token not in cheese:
        errors.append(f"cheese.htm missing contract token: {token}")

for forbidden in ("new XMLHttpRequest", "request.open(", "cdn.amcharts.com", "chartCh.htm"):
    if forbidden in cheese or forbidden in calibrate:
        errors.append(f"new cheese UI must not contain legacy token: {forbidden}")

if "row.parameter.disabled = rule.parameter !== true" not in cheese:
    errors.append("cheese.htm does not disable the per-row parameter outside the n stage")
if "type === 'n' && (time <= 0 || parameter <= 0 || parameter > 14)" not in cheese:
    errors.append("cheese.htm does not require timeout and target pH for the n stage")
if "type !== 'n' && parameter !== 0" not in cheese:
    errors.append("cheese.htm does not reject a non-zero parameter outside the n stage")

for field in ("CheesePhSlope", "CheesePhOffset", "CheesePhSmoothPercent"):
    if f'name="{field}"' not in calibrate:
        errors.append(f"calibrate_ph.htm missing profile field {field}")
for token in (
    "function capturePhPoint(",
    "function calculatePhCalibration(",
    "if (first.raw === second.raw)",
    "SamovarApp.readOperationAcceptance(response)",
    "SamovarApp.waitForOperation(accepted.operationId)",
    "CheesePhRaw",
    "CheesePhValid",
):
    if token not in calibrate:
        errors.append(f"calibrate_ph.htm missing calibration token: {token}")

if "setNextProgram()" not in cheese_lua:
    errors.append("cheese.lua must document the explicit stage-completion call")
if "--|Начать^" not in button1 or 'setNumVariable("SetScriptOff",0)' not in button1:
    errors.append("btn_cheese_button1.lua does not start the user Lua script")
if "--|Остановить^" not in button2 or 'setNumVariable("SetScriptOff",1)' not in button2:
    errors.append("btn_cheese_button2.lua does not stop the user Lua script")

if errors:
    print("cheese UI smoke failed:")
    for error in errors:
        print(f" - {error}")
    raise SystemExit(1)

print("cheese UI static contract passed")
