#!/usr/bin/env python3
"""Static contract for Task 3B bootstrap pages."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
errors = []

for name in ("distiller.htm", "bk.htm", "nbk.htm"):
    source = (ROOT / "data_raw" / name).read_text(encoding="utf-8")
    if re.search(r"%[A-Za-z0-9_.]+%|%%", source):
        errors.append(f"{name} still contains a template placeholder or escaped percent")
    for token in (
        "SamovarApp.loadUiBootstrap(apply",
        "function apply",
        "data.program",
        "data.description",
        "data.luaButtonList",
        "SamovarApp.startTelemetryPage(renderTelemetry",
    ):
        if token not in source:
            errors.append(f"{name} lacks bootstrap token {token}")
    if source.find("SamovarApp.loadUiBootstrap") > source.find("SamovarApp.startTelemetryPage"):
        errors.append(f"{name} starts telemetry before bootstrap")

special = {
    "distiller.htm": ("applyDistillerBootstrap", "i2cStepperTab", "data.steamColor"),
    "bk.htm": ("applyBkBootstrap", "data.pwmLow", "data.pwmValue", "pwmLowTick"),
    "nbk.htm": ("applyNbkBootstrap", "data.nbkDp", "nbkDpLabel", "i2cPumpTab"),
}
for name, tokens in special.items():
    source = (ROOT / "data_raw" / name).read_text(encoding="utf-8")
    for token in tokens:
        if token not in source:
            errors.append(f"{name} lacks Task 3B field {token}")

if errors:
    for error in errors:
        print("ERROR:", error)
    raise SystemExit(1)
print("PASS: Task 3B static bootstrap contract")
