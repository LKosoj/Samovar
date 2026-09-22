#!/usr/bin/env python3
"""Source-derived contract for the Task 4 static bootstrap pages."""

import re
from pathlib import Path

from build_web_assets import resolve_includes
from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
PAGE_NAMES = ("chart.htm", "program.htm", "calibrate.htm", "calibrate_ph.htm")
SETUP = ROOT / "data_raw" / "setup.htm"
I2C_PAGE = ROOT / "data_raw" / "i2cstepper.htm"


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
            "SamovarApp.loadUiBootstrap(data => { bootstrap = data; })",
            "localStepsPerMl = Number(bootstrap.stepperStepsPerMl)",
            "calibrationRunning = Boolean(bootstrap.calibrationRunning)",
            "bootstrap.processRunning", "await readExternalCalibration()",
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
    if "StepperStepMlI2C" in calibrate:
        errors.append("calibrate.htm: retired Samovar I2C calibration remains")

    chart = pages["chart.htm"]
    if chart.find("await SamovarApp.loadUiBootstrap") > chart.find("SamovarApp.startTelemetryPage"):
        errors.append("chart.htm: telemetry starts before bootstrap")
    if "function applyChartBootstrap(data)" not in chart or "initChart(data);" not in chart:
        errors.append("chart.htm: bootstrap callback does not initialize the chart")

    program = pages["program.htm"]
    try:
        program_bootstrap = extract_function_body(program, "function applyProgramBootstrap(data)")
    except ValueError as exc:
        errors.append(f"program.htm: {exc}")
        program_bootstrap = ""
    if program_bootstrap:
        require_ordered_tokens(
            "program calculator availability bootstrap",
            program_bootstrap,
            [
                "SamovarApp.applyModeNavigation(data.mode);",
                "const calculatorAvailable = Number(data.mode) === 0;",
                "calculator.hidden = !calculatorAvailable;",
                "unavailable.hidden = calculatorAvailable;",
                "if (!calculatorAvailable) return;",
                "pwr_unit = data.powerUnit;",
            ],
            errors,
        )
    for token in (
        'id="programUnavailable" class="card" hidden',
        'Расчёт программы отбора доступен только в режиме «Ректификация».',
        '<a href="/" class="button">Перейти к режиму</a>',
        'id="programCalculator" hidden',
        'name="mainform" id="mainform"',
        "if (document.getElementById('programCalculator').hidden) return;",
    ):
        if token not in program:
            errors.append(f"program.htm: unavailable-calculator contract missing {token}")
    try:
        program_onload = extract_function_body(program, "window.onload = async function()")
    except ValueError as exc:
        errors.append(f"program.htm: {exc}")
        program_onload = ""
    if program_onload:
        require_ordered_tokens(
            "program unavailable theme initialization",
            program_onload,
            [
                "await SamovarApp.loadUiBootstrap(applyProgramBootstrap)",
                "SamovarApp.initTheme();",
                "if (document.getElementById('programCalculator').hidden) return;",
            ],
            errors,
        )
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
    setup = SETUP.read_text(encoding="utf-8")
    i2c_page = I2C_PAGE.read_text(encoding="utf-8")
    for token in (
        "id=\"I2CStepper\"", "refreshSetupI2c", "saveSetupI2c",
        "cmd: 'save'", "i2c-newAddress", "i2c-stepsPerMl",
    ):
        if token not in setup:
            errors.append(f"setup.htm: I2CStepper settings tab missing {token}")
    for token in ("saveNano", "newAddress", "stepsPerMl", "mixerRpm"):
        if token in i2c_page:
            errors.append(f"i2cstepper.htm: operational page retains Nano settings token {token}")

    mutations = (
        ("chart visibility inversion", "chart.htm", "Steam: !data.steamVisible", "Steam: data.steamVisible"),
        ("program numeric bootstrap", "program.htm", "mainsVolt = data.mainsVoltage", "mainsVolt = 230"),
        ("program calculator mode guard", "program.htm", "const calculatorAvailable = Number(data.mode) === 0;", "const calculatorAvailable = true;"),
        ("program unavailable theme initialization", "program.htm", "SamovarApp.initTheme();", "SamovarApp.initThemeUnavailable();"),
        ("program unavailable early return", "program.htm", "if (document.getElementById('programCalculator').hidden) return;", "if (false) return;"),
        ("program unsupported diameter guard", "program.htm", "? requestedDiameter : ''", "? requestedDiameter : requestedDiameter"),
        ("external calibration process guard", "calibrate.htm", "bootstrap.processRunning", "bootstrap.processBusy"),
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
