#!/usr/bin/env python3
"""Static contract for the Task 3A mode-page bootstrap callbacks."""

import re
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web_assets import resolve_includes


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "data_raw" / "app.js").read_text(encoding="utf-8")
PAGES = {
    "index.htm": (ROOT / "data_raw" / "index.htm").read_text(encoding="utf-8"),
    "beer.htm": (ROOT / "data_raw" / "beer.htm").read_text(encoding="utf-8"),
}
MODE_PAGES = ("index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm")
errors: list[str] = []

for name, source in PAGES.items():
    for placeholder in ("%WProgram%", "%Descr%", "%btn_list%", "%I2CStepperTab%", "%I2CPumpTab%"):
        if placeholder in source:
            errors.append(f"{name} still contains bootstrap placeholder {placeholder}")
    for token in (
        "SamovarApp.loadUiBootstrap(apply",
        "SamovarApp.startTelemetryPage(renderTelemetry",
        "JSON.stringify(data.luaButtonList)",
        "data.i2cStepperVisible",
        "data.i2cPumpVisible",
        "SamovarApp.postProgram(document.forms.mainform)",
    ):
        if token not in source:
            errors.append(f"{name} missing bootstrap contract token {token}")
    if source.find("SamovarApp.loadUiBootstrap(apply") > source.find("SamovarApp.startTelemetryPage(renderTelemetry"):
        errors.append(f"{name} starts telemetry before bootstrap")

beer = PAGES["beer.htm"]
for placeholder in ("%BeerBrewOrderId%", "%PWM_LV%", "%PWM_V%"):
    if placeholder in beer:
        errors.append(f"beer.htm still contains bootstrap placeholder {placeholder}")
for token in ("data.beerBrewOrder", "data.pwmLow", "data.pwmValue", "SamovarApp.descriptionByteLength(description)"):
    if token not in beer:
        errors.append(f"beer.htm missing typed bootstrap value {token}")

if "async function loadUiBootstrap(applyBootstrap)" not in APP:
    errors.append("app.js no longer provides the shared bootstrap loader")

partial = ROOT / "data_raw" / "partials"
runtime_vars = (partial / "power_unit_runtime_vars.htm").read_text(encoding="utf-8")
for token in ("var pwr_unit = '';", "var powerInputMax = 0;"):
    if token not in runtime_vars:
        errors.append(f"power_unit_runtime_vars.htm missing neutral bootstrap value {token}")
if re.search(r"%[A-Za-z0-9_.]+%|%%", runtime_vars):
    errors.append("power_unit_runtime_vars.htm still contains a template placeholder")
for name in ("ui_sensors_top.htm", "ui_sensors_rest.htm"):
    source = (partial / name).read_text(encoding="utf-8")
    if "text-decoration-color:" in source or re.search(r"%[A-Za-z0-9_.]+%|%%", source):
        errors.append(f"{name} still contains a template temperature color")

for name in MODE_PAGES:
    source_path = ROOT / "data_raw" / name
    try:
        expanded = resolve_includes(name, source_path.read_bytes()).decode("utf-8")
    except ValueError as error:
        errors.append(f"{name} include expansion failed: {error}")
        continue
    if re.search(r"%[A-Za-z0-9_.]+%|%%", expanded):
        errors.append(f"{name} contains a template placeholder after include expansion")
    telemetry_at = source_path.read_text(encoding="utf-8").find("SamovarApp.startTelemetryPage(renderTelemetry")
    for token in (
        "data.steamColor", "data.pipeColor", "data.waterColor", "data.tankColor", "data.acpColor",
        "pwr_unit = data.powerUnit;", "powerInputMax = data.heaterMaxPower;",
    ):
        token_at = source_path.read_text(encoding="utf-8").find(token)
        if token_at < 0 or token_at > telemetry_at:
            errors.append(f"{name} does not apply {token} before telemetry")

if errors:
    raise SystemExit("\n".join(errors))
print("mode bootstrap UI static contract passed")
