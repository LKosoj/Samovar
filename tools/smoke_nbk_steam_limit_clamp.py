#!/usr/bin/env python3
"""Проверяет строгую валидацию NbkSteamT без default/clamp fallback."""

import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "nbk.h").read_text(encoding="utf-8")
errors: list[str] = []

try:
    body = extract_function_body(source, "inline bool nbk_capture_session_config() {")
except ValueError as error:
    errors.append(str(error))
    body = ""

if body:
    require_ordered_tokens(
        "NbkSteamT validates before snapshot commit",
        body,
        [
            "SamSetup.NbkSteamT > 80",
            "SamSetup.NbkSteamT <= 97",
            "if (reason != nullptr)",
            "return false;",
            "nbkSessionConfig.steamTempLimit = SamSetup.NbkSteamT;",
        ],
        errors,
    )
    for forbidden in (
        "NBK_TP_DEFAULT",
        "steamSetting",
        "steamTempLimit = 97",
        "> 97 ? 97",
    ):
        if forbidden in body:
            errors.append(f"NbkSteamT contains forbidden fallback/clamp: {forbidden}")

if errors:
    print("NBK steam limit validation smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("NBK steam limit strict validation smoke passed")
