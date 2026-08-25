#!/usr/bin/env python3
"""T37 п.9: chart.htm - страница наблюдения, кнопок Lua не показывает.

Проверяет:
  - в data_raw/chart.htm нет мёртвой AddLuaButtons()/%btn_list%/samovar_lua_btn_list;
  - chart.htm использует общий offline-порог 3 (как остальные страницы), а не 1;
  - WebServer.ino не берёт мьютекс runtime_state и не копирует список Lua-скриптов
    при отдаче /chart.htm (эта работа нужна только страницам с #lua_btn);
  - страницы, которым кнопки Lua действительно нужны, копирование НЕ теряют.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body

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

try:
    body = extract_function_body(webserver, "void send_index_template_response(")
except ValueError as exc:
    errors.append(str(exc))
    body = ""

if body:
    if 'strcmp(spiffsPath, "/chart.htm")' not in body:
        errors.append(
            "WebServer.ino: send_index_template_response() no longer distinguishes /chart.htm "
            "before collecting the Lua button list"
        )
    if "copy_lua_button_list_cache(luaButtonList)" not in body:
        errors.append(
            "WebServer.ino: send_index_template_response() no longer collects the Lua button "
            "list for pages that use it"
        )
    # Условие должно ОХРАНЯТЬ вызов copy_lua_button_list_cache, а не идти отдельной веткой -
    # иначе chart.htm снова получит бесполезный лок мьютекса runtime_state.
    guard_pos = body.find('strcmp(spiffsPath, "/chart.htm")')
    call_pos = body.find("copy_lua_button_list_cache(luaButtonList)")
    if guard_pos == -1 or call_pos == -1 or call_pos < guard_pos:
        errors.append(
            "WebServer.ino: strcmp(spiffsPath, \"/chart.htm\") guard must precede "
            "copy_lua_button_list_cache(luaButtonList)"
        )

if errors:
    print("chart.htm Lua-buttons skip smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("chart.htm Lua-buttons skip smoke check passed")
