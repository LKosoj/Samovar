#!/usr/bin/env python3
"""Проверка сборки: ALARM_WATER_TEMP обязан быть ниже MAX_WATER_TEMP (Samovar.h)."""

import re
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
HEADER = (ROOT / "Samovar.h").read_text(encoding="utf-8")
MESSAGE = "ALARM_WATER_TEMP must be below MAX_WATER_TEMP"


def compile_with(assertion: str, alarm: str, maximum: str) -> subprocess.CompletedProcess:
    source = f"#define ALARM_WATER_TEMP {alarm}\n#define MAX_WATER_TEMP {maximum}\n{assertion}\n"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "check.cpp"
        path.write_text(source, encoding="utf-8")
        return subprocess.run(
            ["g++", "-std=gnu++17", "-fsyntax-only", str(path)],
            capture_output=True,
            text=True,
        )


def main() -> None:
    match = re.search(r"^static_assert\(ALARM_WATER_TEMP\b.*$", HEADER, re.MULTILINE)
    if match is None:
        raise SystemExit("FAIL: в Samovar.h нет проверки ALARM_WATER_TEMP < MAX_WATER_TEMP")
    assertion = match.group(0)

    errors: list[str] = []
    require_ordered_tokens(
        "water alarm check after user override",
        HEADER,
        ['#include "user_config_override.h"', "static_assert(ALARM_WATER_TEMP < MAX_WATER_TEMP"],
        errors,
    )
    if errors:
        raise SystemExit("FAIL: " + "; ".join(errors))

    for alarm, maximum in (("70", "75"), ("73.4", "73.5")):
        result = compile_with(assertion, alarm, maximum)
        if result.returncode != 0:
            raise SystemExit(f"FAIL: сборка отвергла верные пороги {alarm} < {maximum}:\n{result.stderr}")

    for alarm, maximum in (("75", "75"), ("80", "75"), ("73.6", "73.5")):
        result = compile_with(assertion, alarm, maximum)
        if result.returncode == 0:
            raise SystemExit(f"FAIL: сборка пропустила неверные пороги {alarm} и {maximum}")
        if MESSAGE not in result.stderr:
            raise SystemExit(f"FAIL: нет понятного сообщения для порогов {alarm} и {maximum}:\n{result.stderr}")

    print("OK: порядок порогов воды проверяется при сборке")


if __name__ == "__main__":
    main()
