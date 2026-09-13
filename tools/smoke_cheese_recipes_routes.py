#!/usr/bin/env python3
"""S5 static route/bootstrap and secret-handling contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
web = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
page = (ROOT / "data_raw/cheese-recipes.htm").read_text(encoding="utf-8")
assets = (ROOT / "tools/build_web_assets.py").read_text(encoding="utf-8")
errors = []

for token in (
    'serveStatic("/cheese-recipes.htm", SPIFFS, "/cheese-recipes.htm")',
    'server.on("/cheese-recipes-bootstrap", HTTP_GET',
    'response->addHeader("Cache-Control", "no-store")',
    'json_write_escaped(*response, token',
):
    if token not in web:
        errors.append("WebServer.ino missing " + token)

for token in (
    "https://www.samovar-tool.ru/cheesexml/v1/",
    "Authorization: 'Bearer ' + state.token",
    "new DOMParser()",
    "new FileReader()",
    "fetch('/program', { method: 'POST'",
    'id="themeToggle"',
    'onclick="SamovarApp.toggleTheme()"',
    "SamovarApp.initTheme({ dynamicThemeTitle: true, implicitSystemTheme: true });",
):
    if token not in page:
        errors.append("cheese-recipes.htm missing " + token)

for forbidden in ("localStorage.setItem", "sessionStorage.setItem", "console.log", "fetch('https://"):
    if forbidden in page:
        errors.append("cheese-recipes.htm forbidden token " + forbidden)

if '"cheese-recipes.htm"' not in assets:
    errors.append("build_web_assets.py does not generate cheese-recipes.htm.gz")

if errors:
    raise SystemExit("\n".join(errors))
print("cheese recipes route contract passed")
