#!/usr/bin/env python3
"""Проверяет, что файл начальных настроек покрывает текущую форму настройки."""

import json
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SetupFieldParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ("input", "select"):
            return
        attributes = dict(attrs)
        name = attributes.get("name")
        input_type = attributes.get("type", "select")
        if name and input_type not in ("button", "submit", "hidden", "file"):
            self.fields.add(name)


parser = SetupFieldParser()
parser.feed((ROOT / "data_raw" / "setup.htm").read_text(encoding="utf-8"))
settings = json.loads(
    (ROOT / "tools" / "Samovar_default_settings.txt").read_text(encoding="utf-8")
)

current_defaults = {
    "ColDiam": "1.5",
    "ColHeight": "0.5",
    "PackDens": "80",
    "useDetector": False,
    "MpxZeroAdc": "36.7",
    "MpxCountsPerMmHg": "12.0",
    "StepperStepMlI2C": "16000",
    "UseSecondI2CPump": False,
    "SecondI2CPumpRate": "0.0",
    "BeerBrewOrder": "0",
    "BKPower": "45.0",
    "CheesePhSmoothPercent": "90",
    "CheeseDoserSpeed": "200",
    "CheeseDoserSteps": "160",
    "NbkTn": "98.5",
    "NbkUseStreamServo": False,
    "MainsVoltage": "230.0",
}

missing = sorted(parser.fields - settings.keys())
allowed_empty = {"blynkauth", "tgtoken", "tgchatid", "videourl"}
empty = sorted(
    name
    for name in parser.fields
    if name in settings and settings[name] == "" and name not in allowed_empty
)

if missing:
    raise AssertionError("В начальных настройках отсутствуют поля: " + ", ".join(missing))
if empty:
    raise AssertionError("В начальных настройках не заполнены поля: " + ", ".join(empty))


def find_wrong_defaults(candidate: dict[str, object]) -> list[str]:
    return [
        f"{name}={candidate.get(name)!r}, ожидалось {expected!r}"
        for name, expected in current_defaults.items()
        if candidate.get(name) != expected
    ]


wrong_defaults = find_wrong_defaults(settings)
if wrong_defaults:
    raise AssertionError("Неверные начальные значения: " + "; ".join(wrong_defaults))

# Проверяем, что удаление реального поля ловится содержательной ошибкой.
mutant = dict(settings)
mutant.pop("CheesePhSmoothPercent")
mutant_missing = sorted(parser.fields - mutant.keys())
assert mutant_missing == ["CheesePhSmoothPercent"], (
    "Проверка полноты не обнаружила удалённое поле CheesePhSmoothPercent"
)
mutant = dict(settings)
mutant["CheesePhSmoothPercent"] = "0"
assert find_wrong_defaults(mutant) == [
    "CheesePhSmoothPercent='0', ожидалось '90'"
], (
    "Проверка значений не обнаружила подмену CheesePhSmoothPercent"
)

print("Default settings cover every current setup field")
