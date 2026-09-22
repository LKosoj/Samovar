#!/usr/bin/env python3
"""Контракт настройки видимости схемы процесса."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


setup = (ROOT / "data_raw" / "setup.htm").read_text(encoding="utf-8")
app = (ROOT / "data_raw" / "app.js").read_text(encoding="utf-8")
style = (ROOT / "data_raw" / "style.css").read_text(encoding="utf-8")
header = (ROOT / "Samovar.h").read_text(encoding="utf-8")
fields = (ROOT / "profile_setup_fields.h").read_text(encoding="utf-8")
server = (ROOT / "WebServer.ino").read_text(encoding="utf-8")

require("bool HideProcessScheme;" in header, "SetupEEPROM не хранит HideProcessScheme")
require(
    "X(BOOL, HideProcessScheme, 1, candidate.HideProcessScheme = false, V9ONLY)" in fields,
    "профиль не задаёт выключенный по умолчанию HideProcessScheme",
)
require('name="HideProcessScheme"' in setup, "в setup.htm нет настройки HideProcessScheme")
require("%HideProcessSchemeChecked%" in setup, "setup.htm не показывает сохранённое значение")
require(
    '{"HideProcessSchemeChecked", &SetupEEPROM::HideProcessScheme}' in server,
    "templateProcessor не читает HideProcessScheme",
)
require(
    '{"HideProcessScheme", &SetupEEPROM::HideProcessScheme}' in server,
    "/save не сохраняет HideProcessScheme",
)
require(
    '"hideProcessScheme", snapshot.setup.HideProcessScheme' in server,
    "/ui-bootstrap не отдаёт HideProcessScheme",
)
require("'hideProcessScheme'" in app, "bootstrap-контракт не содержит hideProcessScheme")
require(
    "scheme.hidden = data.hideProcessScheme;" in app
    and "schemeColumn.hidden = data.hideProcessScheme;" in app
    and "modeGrid.classList.toggle('grid-without-scheme', data.hideProcessScheme);" in app,
    "общий bootstrap не скрывает колонку схемы или не перестраивает сетку",
)
require(".grid.grid-without-scheme" in style, "style.css не содержит сетку без схемы")

for page in ("index.htm", "distiller.htm", "bk.htm", "nbk.htm", "beer.htm", "cheese.htm"):
    source = (ROOT / "data_raw" / page).read_text(encoding="utf-8")
    require('id="sec-scheme"' in source or "scheme_" in source, f"{page}: нет панели схемы")

print("process scheme visibility static contract passed")
