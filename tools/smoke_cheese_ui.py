#!/usr/bin/env python3
"""Static contract for the six-field universal Cheese editor."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "data_raw" / "cheese.htm").read_text(encoding="utf-8")
errors: list[str] = []


def require(token: str, message: str) -> None:
    if token not in source:
        errors.append(message)


require("CHEESE_PROGRAM_FIELDS = 6", "editor does not pin six fields")
require("TYPE;VALUE1;VALUE2;VALUE3;MIXER;VALUE4", "six-field wire format is undocumented in source")
require("function validateCheeseRow(values)", "missing Cheese row validator")
require("function serializeCheeseRows()", "missing Cheese serializer")
require("function parseCheeseProgram(program)", "missing Cheese parser")
require("function applyRowRules(row, reset)", "type change does not reset a row")
require("applyRowRules(row, true)", "type change can inherit previous row state")
require("function validateMixer(row, allowed)", "missing dedicated mixer validation")
require("type === 'P' && (!positive(three, 1440) || three < two)", "P permits a total timeout shorter than its hold")
require("value.trim() === ''", "empty mixer component is converted to zero")
require("NONE", "mixer has no NONE selection")
require("RELAY", "mixer has no RELAY selection")
require("I2C", "mixer has no I2C selection")
require("manualConfirmationRequired", "manual confirmation is missing")
require("SamovarApp.sendCommand('start=1')", "confirmation does not use existing next command")
require("CheeseWorkSeconds", "UI does not reserve work-time telemetry")
require("CheeseTimeoutRemainingSeconds", "UI does not reserve timeout telemetry")
require("SamovarApp.loadUiBootstrap(applyCheeseBootstrap)", "bootstrap lifecycle was removed")
require("cheeseCoolingScheme", "Cheese UI does not show the cooling scheme")
require("two-valves", "Cheese UI does not localize two-valve cooling")
require("SamovarApp.postProgram(document.forms.mainform)", "program save does not use existing endpoint")
require("acceptedCheeseProgram", "telemetry still reads an unsaved editor draft")
require("function acceptedCheeseRows()", "missing accepted-program telemetry state")
require("row[0] === 'W' || row[0] === 'S'", "W and S do not require confirmation")

options = re.findall(r'<option value="([A-Za-z])">(?:Нагрев|Выдержка|Охлаждение|Перемешивание|Дозирование|Ожидание pH|Ручное действие|Слив|Lua)</option>', source)
if options != list("HPCMDNWSL"):
    errors.append(f"Cheese types are {options}, expected HPCMDNWSL")

for forbidden in (
    'id="Descr"', 'name="Descr"', "PROGRAM_BACKUP_VERSION", "device_schedule_modal.htm",
    "<option value=\"A\"", "<option value=\"Z\"", "<option value=\"f\"",
    "<option value=\"z\"", "<option value=\"d\"", "<option value=\"n\"",
    "<option value=\"R\"", "Описание сырной программы",
):
    if forbidden in source:
        errors.append(f"obsolete Cheese UI token remains: {forbidden}")

for token in (
    'class="cheese-value1"', 'class="cheese-value2"', 'class="cheese-value3"',
    'class="cheese-value4"', 'class="cheese-mixer-device"',
    'class="cheese-mixer-speed"', 'class="cheese-mixer-direction"', 'class="cheese-mixer-on"',
    'class="cheese-mixer-off"', 'class="cheese-action-code"',
):
    require(token, f"missing editor control {token}")

if errors:
    print("cheese UI smoke failed:", file=sys.stderr)
    for error in errors:
        print(f" - {error}", file=sys.stderr)
    raise SystemExit(1)

print("cheese UI static contract passed")
