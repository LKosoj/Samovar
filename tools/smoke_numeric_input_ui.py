#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
errors: list[str] = []


def read(path: Path) -> str:
    if not path.exists():
        errors.append(f"missing file: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


app = read(DATA / "app.js")
validator = body(app, "function validateNumericInput")
post_program = body(app, "async function postProgram")
send_power = body(app, "function sendPowerCommand")
send_command = body(app, "async function sendCommand")

for token in [
    "DECIMAL_PATTERN",
    "INTEGER_PATTERN",
    "normalizedNumericText(input.value)",
    "Number.isFinite(value)",
    "Number.isSafeInteger(value)",
    "FLOAT32_MIN_NORMAL",
    "FLOAT32_MAX",
    "spec.exclusiveMin",
    "spec.accept(value)",
    "aria-invalid",
]:
    if token not in validator and token not in app[: app.find("function validateNumericInput")]:
        errors.append(f"shared numeric validator missing token: {token}")

require_ordered_tokens(
    "postProgram sends only its explicit allowlist",
    post_program,
    [
        "const body = new FormData();",
        "const allowedFields = ['WProgram', 'vless', 'Descr'];",
        "form.querySelectorAll",
        "fields.length > 1",
        "body.append(name, fields[0].value);",
        "fetch('/program', { method: 'POST', body: body })",
    ],
    errors,
)
for token in [
    "requestErrorRevision++",
    "function currentRequestErrorRevision()",
    "function clearRequestErrorIfUnchanged(revision)",
]:
    if token not in app:
        errors.append(f"shared request-error sequencing missing token: {token}")
if "new FormData(form)" in post_program:
    errors.append("postProgram serializes non-allowlisted form controls")

for token in ["Number.isFinite(maxValue)", "max: maxValue", "Promise.resolve(false)"]:
    if token not in send_power:
        errors.append(f"power snapshot validation missing token: {token}")

require_ordered_tokens(
    "HTTP failure wins over a contradictory success body",
    send_command,
    ["if (!resp.ok)", "if (knownToken && result.ok)"],
    errors,
)

web = read(ROOT / "WebServer.ino")
processor = body(web, "String indexKeyProcessor(const String &var)")
for token in [
    'var == "HeaterMaxPower"',
    "control_power_input_max(",
    "SamSetup.HeaterResistant",
    "result.ok() ? String(maxValue, 9) : String()",
]:
    if token not in processor:
        errors.append(f"server-rendered power maximum missing token: {token}")

setup = read(DATA / "setup.htm")
setup_submit = body(setup, "async function submitSetupForm")
require_ordered_tokens(
    "setup validates before POST and preserves server errors",
    setup_submit,
    [
        "event.preventDefault();",
        "SamovarApp.validateNumericFields(form, setupNumericSchema)",
        "new FormData(form)",
        "if (!response.ok)",
        "SamovarApp.responseErrorText",
        "form.dataset.dirty = 'false';",
    ],
    errors,
)
for field in [
    "mode", "DistTemp", "DistTimeF", "ColDiam", "ColHeight", "PackDens",
    "MaxPressureValue", "DeltaSteamTemp", "SetSteamTemp", "SteamDelay",
    "DeltaPipeTemp", "SetPipeTemp", "PipeDelay", "DeltaWaterTemp",
    "SetWaterTemp", "WaterDelay", "DeltaTankTemp", "SetTankTemp",
    "TankDelay", "DeltaACPTemp", "SetACPTemp", "ACPDelay", "SteamAddr",
    "PipeAddr", "WaterAddr", "TankAddr", "ACPAddr", "StepperStepMl",
    "StepperStepMlI2C", "Kp", "Ki", "Kd", "StbVoltage", "BVolt",
    "NbkIn", "NbkDelta", "NbkDM", "NbkDP", "NbkSteamT", "NbkOwPress",
    "TimeZone", "HeaterR", "LogPeriod", "rele1", "rele2", "rele3", "rele4",
]:
    if f"name: '{field}'" not in setup:
        errors.append(f"setup numeric schema missing {field}")
if "this.value = this.value.replace(',', '.')" in setup:
    errors.append("setup still normalizes every text field during typing")
for token in [
    "setupForm.dataset.dirty = 'false';",
    "setupForm.dataset.dirty = 'true';",
    "setupForm.addEventListener('submit', submitSetupForm);",
]:
    if token not in setup:
        errors.append(f"setup dirty/submit contract missing token: {token}")

page_contracts = {
    "index.htm": ["sendPowerCommand('Voltage'", "sendNumericCommand('pumpspeed'"],
    "beer.htm": ["sendPowerCommand('Voltage'", "sendNumericCommand('watert'"],
    "bk.htm": ["sendPowerCommand('Voltage'", "sendNumericCommand('watert'"],
    "distiller.htm": ["sendPowerCommand('Voltage'"],
    "nbk.htm": ["sendPowerCommand('Voltage'", "sendNumericCommand('pnbk'", "value < 8000"],
}
for page, tokens in page_contracts.items():
    text = read(DATA / page)
    for token in ["Number('%HeaterMaxPower%')", *tokens]:
        if token not in text:
            errors.append(f"{page} missing numeric UI token: {token}")

program = read(DATA / "program.htm")
for token in [
    "SamovarApp.readNumericInput(matSelect",
    "SamovarApp.responseErrorText(response",
    "SamovarApp.validateNumericInput('vless'",
    "min: 0.001, max: 10000",
    "SamovarApp.initTheme();",
    'id="heaterMaxPower" value="" disabled',
    "heaterPowerInput.value = String(Math.round(mainsVolt * mainsVolt / heaterResistance));",
    "heaterPowerInput.disabled = false;",
    "heaterPowerInput.value = '';",
    "heaterPowerInput.disabled = true;",
]:
    if token not in program:
        errors.append(f"program.htm missing numeric UI token: {token}")
if "|| 3500" in program:
    errors.append("program.htm still falls back to a fabricated heater power")

calibrate = read(DATA / "calibrate.htm")
calibrate_body = body(calibrate, "async function calibrate")
require_ordered_tokens(
    "calibration validates start and handles HTTP failure before state change",
    calibrate_body,
    [
        "new URLSearchParams()",
        "SamovarApp.readNumericInput('kstepperspd'",
        "integer: true, min: 1, max: 8000",
        "params.set('start', '1')",
        "if (!resp.ok)",
        "SamovarApp.responseErrorText",
        "calibrationRunning = nextCalibrationRunning;",
    ],
    errors,
)
for token in ['params.set(\'finish\', \'1\')', '<script src="app.js"></script>', "SamovarApp.initTheme();"]:
    if token not in calibrate:
        errors.append(f"calibrate.htm missing token: {token}")
for token in [
    "Number('%CalibrationRunning%') === 1",
    "calibrationRunning ? '%CalibrationPump%' : ''",
    "if (calibrationInFlight) return false;",
    "document.getElementById('pump_type').disabled = calibrationRunning || calibrationInFlight;",
    "const pump = calibrationRunning ? calibrationPump : getPumpType();",
    "calibrationPump = calibrationRunning ? pump : '';",
]:
    if token not in calibrate:
        errors.append(f"calibrate state hydration/lock missing token: {token}")

calibrate_processor = body(web, "String calibrateKeyProcessor(const String &var)")
for token in [
    'var == "CalibrationRunning"',
    "startval == SAMOVAR_STARTVAL_CALIBRATION || I2CPumpCalibrating",
    'var == "CalibrationPump"',
    'I2CPumpCalibrating ? "i2c" : "local"',
]:
    if token not in calibrate_processor:
        errors.append(f"calibrate server state processor missing token: {token}")

i2c = read(DATA / "i2cstepper.htm")
request_json = body(i2c, "async function requestJson")
send_device = body(i2c, "function sendDevice")
device_url = body(i2c, "function deviceUrl")
render_polled_device = body(i2c, "function renderPolledDevice")
config_snapshot = body(i2c, "function configSnapshot")
for token in ["SamovarApp.responseErrorText", "return false;", "SamovarApp.showRequestError"]:
    if token not in request_json:
        errors.append(f"i2c request error contract missing token: {token}")
if "alert(" in request_json:
    errors.append("i2c requestJson still uses alert instead of shared error renderer")
require_ordered_tokens(
    "i2c validation occurs before in-flight mutation",
    send_device,
    ["deviceUrl(device, cmd)", "if (!url)", "return false;", "setActionInFlight(device, action, true)"],
    errors,
)
for token in [
    "if (deviceActionInFlight(device)) return false;",
    "pendingDeviceConfig[device] = snapshot;",
    "snapshot.accepted = true;",
    "var fullConfig = cmd === 'apply' || cmd === 'save' || cmd === 'start';",
    "var snapshot = fullConfig ? configSnapshot(url, deviceEditVersion[device]) : null;",
]:
    if token not in send_device:
        errors.append(f"i2c per-device serialization/confirmation missing token: {token}")
for token in [
    "pending.accepted",
    "pending.editVersion === deviceEditVersion[device]",
    "configMatches(data, pending)",
]:
    if token not in render_polled_device:
        errors.append(f"i2c stale-poll dirty guard missing token: {token}")
if "document.getElementById(device + '_relayMask').value = relayMask;" not in i2c:
    errors.append("i2c confirmed relay state does not update the authoritative hidden mask")
if "'relayMask'" in config_snapshot:
    errors.append("i2c ordinary form snapshot incorrectly owns the live relay mask")
for token in [
    "SamovarApp.currentRequestErrorRevision()",
    "i2cRequestErrorOwner = errorOwner;",
    "SamovarApp.clearRequestErrorIfUnchanged(errorRevision)",
]:
    if token not in request_json:
        errors.append(f"i2c request sequencing missing token: {token}")
for token in [
    "cmd === 'stop' || cmd === 'calfinish'",
    "new URLSearchParams()",
    "mixerParams(cmd, params)",
    "pumpParams(cmd, params)",
]:
    if token not in device_url:
        errors.append(f"i2c command-specific URL missing token: {token}")
for field in [
    "mixerRpm", "mixerRunSec", "mixerPauseSec", "pumpMlHour",
    "pumpPauseSec", "fillingMl", "fillingMlHour", "stepsPerMl",
]:
    if not re.search(rf"appendInteger\(params, '{field}'", i2c):
        errors.append(f"i2c integer validation missing {field}")

browser = read(ROOT / "tools" / "test_numeric_input_ui_browser.py")
if browser:
    for token in [
        '"setup.htm", "index.htm", "beer.htm", "bk.htm", "distiller.htm",',
        '{ name: "desktop", width: 1440, height: 900 }',
        '{ name: "mobile", width: 390, height: 844 }',
        'const themes = ["light", "dark"]',
        'page.on("pageerror"',
        'message.type() === "warning" || message.type() === "error"',
        "playwright-cli is required",
    ]:
        if token not in browser:
            errors.append(f"numeric browser gate missing token: {token}")

if errors:
    print("Numeric input UI smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Numeric input UI smoke passed")
