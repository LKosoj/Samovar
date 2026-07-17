#!/usr/bin/env python3
import hashlib
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
# Сборка: сюда build_web_assets.py кладёт .gz. Содержимое читаем из источника,
# продукты сжатия - отсюда.
BUILD = ROOT / "data"
MODE_PAGES = {
    "index.htm": 3,
    "beer.htm": 3,
    "distiller.htm": 3,
    "bk.htm": 3,
    "nbk.htm": 4,
}
ALL_PAGES = (*MODE_PAGES, "chart.htm")
FROZEN_HASHES = {
    "edit.htm": "26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6",
    "edit.htm.gz": "86e2801e2370cd45420ed84005194b752cc22198e7ab85faa33129bd28a50cac",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\bfunction\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    require(match is not None, f"missing function {name}")
    start = match.end() - 1
    depth = 0
    quote = None
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:index]
    raise AssertionError(f"unterminated function {name}")


def main() -> int:
    app = (DATA / "app.js").read_text(encoding="utf-8")
    pages = {name: (DATA / name).read_text(encoding="utf-8") for name in ALL_PAGES}

    require(len(re.findall(r"\bfunction\s+startTelemetryPage\s*\(", app)) == 1,
            "app.js must define exactly one startTelemetryPage")
    require(app.count("startTelemetryPage: startTelemetryPage") == 1,
            "startTelemetryPage must be the only new lifecycle export")
    start_body = function_body(app, "startTelemetryPage")
    require("DOMContentLoaded" not in start_body and "addEventListener('load'" not in start_body,
            "startTelemetryPage must not own a startup event")
    require("startPollLoop" in start_body and "pollAjax" in start_body,
            "startTelemetryPage must compose the existing poll owners")
    require("telemetryPageStarted" in start_body,
            "startTelemetryPage must reject duplicate starts")

    option_match = re.search(r"const TELEMETRY_OPTION_KEYS\s*=\s*\[([^]]+)\]", app, re.S)
    require(option_match is not None, "missing closed telemetry option allowlist")
    option_keys = re.findall(r"['\"]([A-Za-z]+)['\"]", option_match.group(1))
    require(option_keys == [
        "threshold", "onReady", "connectionIds", "storeMessageHistory",
        "dynamicThemeTitle", "implicitSystemTheme", "onLastMessageRemoved",
    ], f"unexpected telemetry option allowlist: {option_keys}")
    require("Неизвестная опция telemetry lifecycle" in start_body,
            "unknown lifecycle options must fail loudly")
    require("typeof renderFn !== 'function'" in start_body,
            "render callback must be validated")
    require("typeof pageOptions.dynamicThemeTitle !== 'boolean'" in start_body and
            "typeof pageOptions.implicitSystemTheme !== 'boolean'" in start_body,
            "both theme options must have boolean validation")

    init_theme = function_body(app, "initTheme")
    toggle_theme = function_body(app, "toggleTheme")
    remove_message = function_body(app, "removeLastMessage")
    clear_messages = function_body(app, "clearMessages")
    require("root.removeAttribute('data-theme')" in app,
            "implicit chart theme must leave data-theme unset")
    require("systemTheme()" in init_theme and "implicitSystemTheme" in init_theme,
            "initTheme must retain the implicit system policy")
    require("localStorage.getItem('theme')" in init_theme,
            "initTheme must read the existing theme key")
    require("implicitSystemTheme" in toggle_theme and "localStorage.setItem('theme', next)" in toggle_theme,
            "toggleTheme must retain explicit and implicit policies")
    require("messages.length === 0" in remove_message and "messages.pop()" in remove_message,
            "removeLastMessage must distinguish empty and actual removal")
    require(remove_message.index("messages.pop()") < remove_message.index("onLastMessageRemoved(messages.length)"),
            "removal callback must run after pop with remaining count")
    require("onLastMessageRemoved" not in clear_messages,
            "clearMessages must not invoke the removal callback")

    forbidden_local = (
        "async function loadDoc", "SamovarApp.startPollLoop(", "function ConnectError",
    )
    for name, threshold in MODE_PAGES.items():
        source = pages[name]
        require(source.count("SamovarApp.startTelemetryPage(") == 1,
                f"{name}: expected one shared lifecycle start")
        require("function renderTelemetry(myObj)" in source,
                f"{name}: missing local telemetry renderer")
        require("function setPowerUnit" in source,
                f"{name}: page-specific power owner was removed")
        for marker in forbidden_local:
            require(marker not in source, f"{name}: legacy lifecycle marker remains: {marker}")
        require(re.search(rf"threshold:\s*{threshold}\b", source) is not None,
                f"{name}: wrong offline threshold")
        require("storeMessageHistory: true" in source,
                f"{name}: mode message history policy changed")
        require("dynamicThemeTitle: false" in source and "implicitSystemTheme: false" in source,
                f"{name}: mode theme policy changed")
        require("onLastMessageRemoved" not in source,
                f"{name}: chart-only removal callback leaked into mode page")
        onload = source.index("window.onload = function()")
        start = source.index("SamovarApp.startTelemetryPage(")
        require(onload < start, f"{name}: lifecycle start left window.onload")

    chart = pages["chart.htm"]
    require(chart.count("SamovarApp.startTelemetryPage(") == 1,
            "chart: expected one shared lifecycle start")
    require("function renderTelemetry(myObj)" in chart,
            "chart: missing local telemetry renderer")
    for marker in (
        "async function loadDoc", "SamovarApp.startPollLoop(", "function ConnectError",
        "function playSound", "function addMessage", "function removeLastMessage",
        "function showMessages", "function clearMessages", "function escapeHtml",
        "function applyTheme", "function toggleTheme", "function setPowerUnit",
        "Messages_Array", "sound_is_playing", "is_ALARM",
    ):
        require(marker not in chart, f"chart: duplicate shared owner remains: {marker}")
    require("SamovarApp.initTheme({ implicitSystemTheme: true, dynamicThemeTitle: true });" in chart,
            "chart: missing parse-time shared theme apply")
    theme_pos = chart.index("SamovarApp.initTheme({ implicitSystemTheme: true, dynamicThemeTitle: true });")
    require(chart.index('<script src="chart.js"></script>') < theme_pos < chart.index("function initChart"),
            "chart: parse-time theme call moved from its former inline position")
    require(chart.index("document.addEventListener('DOMContentLoaded'") <
            chart.index("SamovarApp.startTelemetryPage("),
            "chart: lifecycle start left the existing DOMContentLoaded owner")
    for marker in (
        "threshold: 1", "storeMessageHistory: false", "dynamicThemeTitle: true",
        "implicitSystemTheme: true", "online: 'GreenT'", "offline: 'RedT'",
        "if (remainingCount === 0) IsCalmingPause = false",
        "SamovarApp.addMessage(importantStatus, 1)",
        "SamovarApp.setSoundEnabled(!!myObj.UseBBuzzer)",
        "chart.loadCsv('data.csv')", "appendChartPoint(myObj)",
    ):
        require(marker in chart, f"chart: missing preserved contract: {marker}")
    require("onclick=\"SamovarApp.toggleTheme()\"" in chart and
            "onclick='SamovarApp.clearMessages()'" in chart,
            "chart markup must call shared owners directly")

    require("SamovarChart" not in app and "data.csv" not in app,
            "chart-specific rendering leaked into app.js")
    for name, expected in FROZEN_HASHES.items():
        # .gz - продукт сборки, сырьё - источник.
        source = (BUILD if name.endswith(".gz") else DATA) / name
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        require(actual == expected, f"frozen {name} changed: {actual}")

    print("Shared UI controller static contract passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as error:
        print(f"Shared UI controller static contract failed: {error}", file=sys.stderr)
        sys.exit(1)
