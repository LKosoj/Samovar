#!/usr/bin/env python3
"""Source-derived contract for the Task 4 static bootstrap pages."""

import re
from pathlib import Path

from build_web_assets import resolve_includes


ROOT = Path(__file__).resolve().parents[1]
PAGE_NAMES = ("chart.htm", "program.htm", "calibrate.htm", "calibrate_ph.htm")


def validate(pages: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for name in PAGE_NAMES:
        expanded = resolve_includes(name, pages[name].encode()).decode()
        if re.search(r"%[A-Za-z0-9_.]+%|%%", expanded):
            errors.append(f"{name}: template placeholder remains after include expansion")
        if "SamovarApp.loadUiBootstrap(" not in pages[name]:
            errors.append(f"{name}: shared bootstrap loader is missing")

    required = {
        "chart.htm": (
            "data.steamColor", "data.pipeColor", "data.waterColor", "data.tankColor",
            "data.acpColor", "Steam: !data.steamVisible", "Pipe: !data.pipeVisible",
            "Water: !data.waterVisible", "Tank: !data.tankVisible",
            "Pressure: !data.pressureVisible", "ProgNum: !data.programNumberVisible",
        ),
        "program.htm": (
            "pwr_unit = data.powerUnit", "heaterResistance = data.heaterResistance",
            "mainsVolt = data.mainsVoltage", "data.columnDiameter", "data.columnHeight",
            "data.packDensity", "data.version", "data.program",
            "'option[value=\"' + requestedDiameter + '\"]'",
            "? requestedDiameter : ''",
            "SamovarApp.postProgram(document.forms.mainform)",
        ),
        "calibrate.htm": (
            "stepperStepMlLocal = data.stepperStepsPerMl",
            "stepperStepMlI2C = data.i2cStepperStepsPerMl",
            "calibrationRunning = data.calibrationRunning",
            "calibrationPump = calibrationRunning ? data.calibrationPump : ''",
            "data.stepperMaxSpeed", "data.i2cPumpVisible",
            "fetch('/calibrate?'", "fetch('/save'",
        ),
        "calibrate_ph.htm": (
            "data.cheesePhSlope", "data.cheesePhOffset",
            "fetch('/save'", "SamovarApp.startTelemetryPage(renderCalibrationTelemetry",
        ),
    }
    for name, tokens in required.items():
        for token in tokens:
            if token not in pages[name]:
                errors.append(f"{name}: missing Task 4 token {token}")

    calibrate = pages["calibrate.htm"]
    for token in (
        "data.stepperStepsPerMl * 100",
        "data.i2cStepperStepsPerMl * 100",
    ):
        if token in calibrate:
            errors.append(f"calibrate.htm: bootstrap value is already per 100 ml: {token}")

    chart = pages["chart.htm"]
    if chart.find("await SamovarApp.loadUiBootstrap") > chart.find("SamovarApp.startTelemetryPage"):
        errors.append("chart.htm: telemetry starts before bootstrap")
    if "function applyChartBootstrap(data)" not in chart or "initChart(data);" not in chart:
        errors.append("chart.htm: bootstrap callback does not initialize the chart")

    program = pages["program.htm"]
    if program.find("await SamovarApp.loadUiBootstrap") > program.find("getProgramFromFile(loadProgramSelect"):
        errors.append("program.htm: template/column request starts before bootstrap")
    if 'diamSelect.value = "1.5"' not in program:
        errors.append("program.htm: the existing 1.5 diameter fallback changed")

    calibrate_ph = pages["calibrate_ph.htm"]
    if "CheesePhSmoothPercent" in calibrate_ph:
        errors.append("calibrate_ph.htm: retired pH smoothing field remains")
    if calibrate_ph.find("await SamovarApp.loadUiBootstrap") > calibrate_ph.find(
        "SamovarApp.startTelemetryPage(renderCalibrationTelemetry"
    ):
        errors.append("calibrate_ph.htm: telemetry starts before bootstrap")
    return errors


def main() -> int:
    pages = {
        name: (ROOT / "data_raw" / name).read_text(encoding="utf-8")
        for name in PAGE_NAMES
    }
    errors = validate(pages)

    mutations = (
        ("chart visibility inversion", "chart.htm", "Steam: !data.steamVisible", "Steam: data.steamVisible"),
        ("program numeric bootstrap", "program.htm", "mainsVolt = data.mainsVoltage", "mainsVolt = 230"),
        ("program unsupported diameter guard", "program.htm", "? requestedDiameter : ''", "? requestedDiameter : requestedDiameter"),
        ("calibration endpoint units", "calibrate.htm", "stepperStepMlLocal = data.stepperStepsPerMl", "stepperStepMlLocal = data.stepperStepsPerMl * 100"),
        ("pH bootstrap mapping", "calibrate_ph.htm", "data.cheesePhSlope", "data.cheesePhOffset"),
    )
    if not errors:
        for label, name, old, new in mutations:
            if old not in pages[name]:
                errors.append(f"mutation setup failed: {label}")
                continue
            mutated = dict(pages)
            mutated[name] = mutated[name].replace(old, new, 1)
            if not validate(mutated):
                errors.append(f"mutation survived: {label}")

    if errors:
        raise SystemExit("\n".join(errors))
    print("Task 4 static bootstrap UI contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
