#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens, strip_cpp_comments

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web_assets import resolve_includes


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
errors: list[str] = []


def read(path: Path) -> str:
    if not path.exists():
        errors.append(f"missing file: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def read_page(name: str) -> str:
    """Разворачивает <!--#include--> (data_raw/partials/) той же функцией, что
    использует сама сборка - не копией её логики."""
    path = DATA / name
    if not path.exists():
        errors.append(f"missing file: {path.relative_to(ROOT)}")
        return ""
    return resolve_includes(name, path.read_bytes()).decode("utf-8")


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

setup = read_page("setup.htm")
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

# [23.08.2026] П11 поднял серверный минимум DistTemp с 0 до 30 в WebServer.ino
# (kSaveFloatFields), но клиентская схема setupNumericSchema не была обновлена
# одновременно - ноль проходил браузерную проверку и падал на сервере с
# малопонятной ошибкой "Invalid DistTemp", валя заодно СОХРАНЕНИЕ ЦЕЛИКОМ (форма
# setup.htm одна на все поля, apply_save_settings отбивается при первом же
# провале). Проверки выше ловят только НАЛИЧИЕ поля в схеме, не совпадение
# границ - расхождение такого рода не ловилось. Ниже границы min/max сверяются
# из РЕАЛЬНОГО содержимого обоих файлов (а не из скопированного списка полей).
def _resolve_numeric_bound(token: str, named_constants: dict) -> float | None:
    token = token.strip().rstrip("fF")
    try:
        return float(token)
    except ValueError:
        return named_constants.get(token)


def _parse_server_field_bounds(source: str, table_token: str, named_constants: dict) -> dict:
    block, _ = extract_braced_block_after(source, table_token)
    block = strip_cpp_comments(block)
    bounds = {}
    for m in re.finditer(
        r'\{\s*"([A-Za-z0-9_]+)"\s*,\s*&SetupEEPROM::[A-Za-z0-9_]+\s*,\s*([^,]+?)\s*,\s*([^}]+?)\s*\}',
        block,
    ):
        name, raw_min, raw_max = m.group(1), m.group(2), m.group(3)
        bounds[name] = (
            _resolve_numeric_bound(raw_min, named_constants),
            _resolve_numeric_bound(raw_max, named_constants),
        )
    return bounds


def _extract_bracket_block(source: str, token: str) -> str:
    start = source.find(token)
    if start < 0:
        raise ValueError(f"block token not found: {token}")
    open_idx = source.find("[", start)
    if open_idx < 0:
        raise ValueError(f"block opening bracket not found: {token}")
    depth = 0
    for index in range(open_idx, len(source)):
        if source[index] == "[":
            depth += 1
        elif source[index] == "]":
            depth -= 1
            if depth == 0:
                return source[open_idx + 1:index]
    raise ValueError(f"block is not closed: {token}")


def _parse_client_schema_bounds(source: str) -> dict:
    schema_text = _extract_bracket_block(source, "const setupNumericSchema")
    bounds = {}
    for m in re.finditer(
        r"\{\s*name:\s*'([A-Za-z0-9_]+)'\s*,(?:\s*integer:\s*true\s*,)?\s*"
        r"min:\s*(-?[\d.]+)\s*,\s*max:\s*(-?[\d.]+)\s*\}",
        schema_text,
    ):
        bounds[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    return bounds


_control_numeric_input = read(ROOT / "control_numeric_input.h")
_named_float_constants = {
    m.group(1): float(m.group(2))
    for m in re.finditer(
        r"static\s+const\s+float\s+([A-Za-z0-9_]+)\s*=\s*(-?[\d.]+)f?\s*;",
        _control_numeric_input,
    )
}

_server_field_bounds: dict = {}
for _table_token in ("kSaveFloatFields[] = {", "kSaveU8Fields[] = {", "kSaveU16Fields[] = {"):
    _server_field_bounds.update(_parse_server_field_bounds(web, _table_token, _named_float_constants))
_client_field_bounds = _parse_client_schema_bounds(setup)

# autospeed: сервер допускает 0..99 (kSaveU8Fields), клиент ограничивает ввод 0..20 -
# расхождение УЖЕ было в HEAD до сегодняшней правки DistTemp (не в этом diff), решение
# по нему остаётся за владельцем. Если когда-нибудь границы сведут, эта запись должна
# исчезнуть - assert ниже не даст ей молча протухнуть в "разрешение", которое ничего
# не разрешает.
_KNOWN_LEGACY_BOUND_MISMATCHES = {"autospeed"}

for _name, (_smin, _smax) in _server_field_bounds.items():
    if _name not in _client_field_bounds:
        continue
    _cmin, _cmax = _client_field_bounds[_name]
    if _smin is None or _smax is None:
        errors.append(f"setup numeric schema bound check: cannot resolve server bound for {_name}")
        continue
    _bounds_match = abs(_smin - _cmin) <= 1e-9 and abs(_smax - _cmax) <= 1e-9
    if _name in _KNOWN_LEGACY_BOUND_MISMATCHES:
        if _bounds_match:
            errors.append(
                f"{_name} bounds now match server/client - remove it from "
                "_KNOWN_LEGACY_BOUND_MISMATCHES"
            )
        continue
    if not _bounds_match:
        errors.append(
            f"setup numeric schema bound mismatch for {_name}: "
            f"server=({_smin}, {_smax}) client=({_cmin}, {_cmax})"
        )

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
    text = read_page(page)
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
