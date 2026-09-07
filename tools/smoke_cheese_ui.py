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
# Шапка (история, тема, сообщения) с 07.09.2026 живёт в partial'ах ui_header_*.htm;
# для проверки контрактных токенов страница нужна в собранном виде.
for _partial in ("ui_header_open.htm", "ui_header_close.htm"):
    cheese += read("partials/" + _partial)
calibrate = read("calibrate_ph.htm")
cheese_lua = read("cheese.lua")
button1 = read("btn_cheese_button1.lua")
button2 = read("btn_cheese_button2.lua")
device_modal = read("partials/device_schedule_modal.htm")
app = read("app.js")


if "%%" in calibrate:
    errors.append("calibrate_ph.htm still escapes ordinary percent for template processing")

for placeholder in ("%WProgram%", "%Descr%", "%btn_list%"):
    if placeholder in cheese:
        errors.append(f"cheese.htm still contains template placeholder {placeholder}")
if "%%" in cheese:
    errors.append("cheese.htm still escapes ordinary percent for template processing")
for token in (
    "clip-path: inset(50%);",
    "SamovarApp.loadUiBootstrap(applyCheeseBootstrap)",
    "function applyCheeseBootstrap(data)",
    "JSON.stringify(data.luaButtonList)",
):
    if token not in cheese:
        errors.append(f"cheese.htm missing UI bootstrap token: {token}")

for token in (
    "async function loadUiBootstrap(applyBootstrap)",
    "fetch('/ui-bootstrap', { cache: 'no-store' })",
    "bootstrapPending = true;",
    "bootstrapPending = false;",
    "Начальные данные недоступны: HTTP ",
    "Некорректный JSON начальных данных.",
    "function validateUiBootstrap(data)",
    "hasExactKeys(data, UI_BOOTSTRAP_KEYS)",
    "descriptionByteLength(data.description) > 250",
    "bootstrapStarted = true;",
    "Начальные данные уже загружены.",
    "async function requestI2cPump(url, fallbackText)",
    "async function clearProgram()",
):
    if token not in app:
        errors.append(f"app.js missing UI bootstrap contract: {token}")
if app.count("fetch('/ui-bootstrap', { cache: 'no-store' })") != 1:
    errors.append("app.js must issue exactly one no-store UI bootstrap fetch")


def function_body(signature: str) -> str:
    start = app.find(signature)
    if start < 0:
        return ""
    open_brace = app.find("{", start)
    depth = 0
    for index in range(open_brace, len(app)):
        if app[index] == "{":
            depth += 1
        elif app[index] == "}":
            depth -= 1
            if depth == 0:
                return app[open_brace + 1:index]
    return ""


for signature in (
    "async function sendCommandRequest(command, options)",
    "async function requestI2cPump(url, fallbackText)",
    "async function postProgramRequest(form)",
    "async function clearProgram()",
):
    body = function_body(signature)
    assert_at = body.find("assertOnline();")
    fetch_at = body.find("fetch(")
    if assert_at < 0 or fetch_at < 0 or assert_at > fetch_at:
        errors.append(f"{signature} can mutate before bootstrap succeeds")

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
    "SamovarApp.openDeviceScheduleModal(row.device)",
    "function serializeCheeseRows(",
    "SamovarApp.postProgram(document.forms.mainform)",
    'maxlength="250"',
    "PROGRAM_BACKUP_VERSION = 1",
    "SamovarApp.descriptionByteLength(description)",
    "backup.version !== PROGRAM_BACKUP_VERSION",
    'value="Настройки"',
    "SamovarApp.showHistory()",
    '<!--#include lua_field.htm-->',
    'class="prg" id="programRows"',
    'class="prgline" id="cheeseProgramHeader"',
    'class="prglabel cheese-row-number"',
    'class="program-row-action cheese-add"',
    'class="program-row-action cheese-remove"',
    '<img src="plus.png" alt="">',
    '<img src="minus.png" alt="">',
    "function setCheeseRowNumbers()",
):
    if token not in cheese:
        errors.append(f"cheese.htm missing contract token: {token}")

if "Добавить этап" in cheese:
    errors.append("cheese.htm still uses a separate add-stage button instead of row + controls")

for token in (
    '<form id="phForm"',
    '<h1>Калибровка pH</h1>',
    'class="tabcontent" style="display: block;',
    'class="container_column"',
    'class="container_row"',
):
    if token not in calibrate:
        errors.append(f"calibrate_ph.htm missing standard calibration layout token: {token}")

if 'id="popup"' not in device_modal or "SamovarApp.saveDeviceScheduleModal()" not in device_modal:
    errors.append("shared device modal does not save through SamovarApp")

modal_contract = (
    "function openDeviceScheduleModal(input, onSave)",
    "function saveDeviceScheduleModal()",
    "deviceScheduleInput.value = byId('m_type').value + '^' + byId('m_direction').value + '^' + run.text + '^' + pause.text",
)
if any(token not in app for token in modal_contract):
    errors.append("app.js is missing the shared device-modal behavior")
modal_mutant = app.replace("deviceScheduleInput.value = ", "const ignoredDeviceSchedule = ", 1)
if modal_mutant == app or all(token in modal_mutant for token in modal_contract):
    errors.append("device-modal save mutation was not rejected")

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
    "CheesePhRawValid",
    "CheesePhValid",
):
    if token not in calibrate:
        errors.append(f"calibrate_ph.htm missing calibration token: {token}")

if "latestPh.rawValid" not in calibrate or "if (!latestPh.rawValid" not in calibrate:
    errors.append("calibrate_ph.htm cannot capture raw ADC before pH is calibrated")
if '<option value="1">Вода</option>' not in cheese or '<option value="3">Пар</option>' not in cheese:
    errors.append("cheese.htm sensor labels disagree with beer_control_sensor")

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
