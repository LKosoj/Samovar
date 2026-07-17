#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
CHART_HTM = ROOT / "data_raw" / "chart.htm"
CHART_JS = ROOT / "data_raw" / "chart.js"
WEBSERVER = ROOT / "WebServer.ino"

errors: list[str] = []


def read_text(path: Path) -> str:
    if not path.exists():
        errors.append(f"{path.relative_to(ROOT)} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


chart_htm = read_text(CHART_HTM)
chart_js = read_text(CHART_JS)
webserver = read_text(WEBSERVER)

if chart_htm:
    for token in ["cdn.amcharts.com", "am4core", "am4charts", "am4themes"]:
        if token in chart_htm:
            errors.append(f"data_raw/chart.htm still depends on external/amCharts token: {token}")
    for token in ["reloadFrequency", "dataSource", "chart.dataSource"]:
        if token in chart_htm:
            errors.append(f"data_raw/chart.htm contains forbidden full-reload chart token: {token}")

    if '<script src="chart.js"></script>' not in chart_htm:
        errors.append("data_raw/chart.htm does not load local chart.js")
    for token in [
        "function initChart ()",
        "typeof SamovarChart !== 'function'",
        "chart = new SamovarChart('chartdiv'",
        "function templateBool (value)",
        "chart.loadCsv('data.csv')",
        "function appendChartPoint(myObj)",
        "chart.appendAjaxPoint(myObj)",
        "SamovarApp.initTheme({ implicitSystemTheme: true, dynamicThemeTitle: true });",
        "SamovarApp.startTelemetryPage(renderTelemetry, {",
    ]:
        if token not in chart_htm:
            errors.append(f"data_raw/chart.htm missing W7 chart token: {token}")

    try:
        dom_body = extract_function_body(chart_htm, "document.addEventListener('DOMContentLoaded', function ()")
        ready_pos = dom_body.find("onReady: initChart")
        poll_pos = dom_body.find("SamovarApp.startTelemetryPage(renderTelemetry, {")
        if ready_pos == -1 or poll_pos == -1:
            errors.append(
                "data_raw/chart.htm DOMContentLoaded does not start shared telemetry "
                "with initChart as onReady"
            )
        elif ready_pos < poll_pos:
            errors.append("data_raw/chart.htm chart onReady escaped shared lifecycle options")
    except ValueError as exc:
        errors.append(str(exc))

    theme_pos = chart_htm.find(
        "SamovarApp.initTheme({ implicitSystemTheme: true, dynamicThemeTitle: true });"
    )
    chart_script_pos = chart_htm.find('<script src="chart.js"></script>')
    init_function_pos = chart_htm.find("function initChart ()")
    if not (chart_script_pos != -1 and chart_script_pos < theme_pos < init_function_pos):
        errors.append("data_raw/chart.htm parse-time shared theme call moved out of former IIFE position")

    try:
        init_body = extract_function_body(chart_htm, "function initChart ()")
        for token in ["chartBlock.textContent", "try {", "catch (err)", "chart.loadCsv('data.csv').catch"]:
            if token not in init_body:
                errors.append(f"data_raw/chart.htm initChart() does not fail explicitly without blocking polling: {token}")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        append_body = extract_function_body(chart_htm, "function appendChartPoint(myObj)")
        for token in ["chartLastAppendMs", "15000", "chart.appendAjaxPoint(myObj)"]:
            if token not in append_body:
                errors.append(f"data_raw/chart.htm appendChartPoint() does not enforce throttled ajax append: {token}")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        refresh_body = extract_function_body(chart_htm, "function refresh_chart ()")
        if "loadCsv" in refresh_body or "data.csv" in refresh_body:
            errors.append("data_raw/chart.htm refresh_chart() reloads full data.csv")
        if "chart.setAutoRefresh" not in refresh_body:
            errors.append("data_raw/chart.htm refresh_chart() does not toggle local auto refresh")
    except ValueError as exc:
        errors.append(str(exc))

if chart_js:
    for token in ["SamovarChart", "parseCsv(text)", "MAX_RENDER_POINTS = 600", "appendAjaxPoint", "decimate(rows)"]:
        if token not in chart_js:
            errors.append(f"data_raw/chart.js missing local renderer token: {token}")
    for token in ["cdn.amcharts.com", "am4core", "am4charts", "reloadFrequency", "dataSource"]:
        if token in chart_js:
            errors.append(f"data_raw/chart.js contains forbidden chart dependency/reload token: {token}")
    if not re.search(r"fetch\(url,\s*\{\s*cache:\s*['\"]no-store['\"]\s*\}\)", chart_js):
        errors.append("data_raw/chart.js initial CSV load is not explicit no-store fetch")

if webserver:
    if 'server.on("/data.csv", (WebRequestMethodComposite)(HTTP_GET | HTTP_HEAD)' not in webserver:
        errors.append("WebServer.ino /data.csv route must support GET and HEAD")
    if "AmCharts" in webserver:
        errors.append("WebServer.ino still has stale AmCharts comment")

if errors:
    print("Chart UI smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("Chart UI smoke check passed")
