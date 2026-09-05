#!/usr/bin/env python3
"""T37 п.9: chart.htm - статическая страница наблюдения без Lua-кнопок."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART_HTM = ROOT / "data_raw" / "chart.htm"
WEBSERVER = ROOT / "WebServer.ino"

errors: list[str] = []

chart_htm = CHART_HTM.read_text(encoding="utf-8", errors="ignore")
webserver = WEBSERVER.read_text(encoding="utf-8", errors="ignore")

for token in ("AddLuaButtons", "%btn_list%", "samovar_lua_btn_list", "run_lua(", "threshold: 1"):
    if token in chart_htm:
        errors.append(f"data_raw/chart.htm still contains dead Lua-buttons token: {token}")

if "threshold: 3" not in chart_htm:
    errors.append("data_raw/chart.htm does not use the shared offline threshold 3")

chart_route = 'server.serveStatic("/chart.htm", SPIFFS, "/chart.htm")'
if chart_route not in webserver:
    errors.append("WebServer.ino: /chart.htm должен отдаваться статически")
chart_line = next((line for line in webserver.splitlines() if chart_route in line), "")
if "setTemplateProcessor" in chart_line:
    errors.append("WebServer.ino: статический /chart.htm не должен иметь template callback")
if "send_index_template_response" in webserver:
    errors.append("WebServer.ino: удалённый template helper всё ещё остался")

if errors:
    print("chart.htm Lua-buttons skip smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("chart.htm Lua-buttons skip smoke check passed")
