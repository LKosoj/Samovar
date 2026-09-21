#!/usr/bin/env python3
"""Старт сессии сохраняется при отключённом Blynk, отправка V35 — нет."""
import subprocess
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]


def check_session(body: str) -> None:
    for enabled in (False, True):
        command = ["g++", "-E", "-P", "-x", "c++", "-"]
        if enabled:
            command.insert(1, "-DSAMOVAR_USE_BLYNK")
        result = subprocess.run(command, input=body, text=True, capture_output=True, check=True)
        active = result.stdout
        assert ("blynk_stage_session_start(line);" in active) == enabled, \
            "V35 staging must exist only when Blynk is enabled"
        assert ("const String line" in active) == enabled, \
            "V35 payload must exist only when Blynk is enabled"
        for token in ("i2c_stepper_session_begin();", "currentSessionId = sessionResumeId;",
                      "new_random_session_id();", "sessionResumeAvailable = false;"):
            assert token in active, f"Session lifecycle must remain enabled: {token}"


def main() -> None:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    body = extract_function_body(source, "void session_begin(const String& sessionDescription)")
    check_session(body)
    mutant = body.replace("#ifdef SAMOVAR_USE_BLYNK", "#if 1")
    assert mutant != body, "Missing Blynk compile-time guard"
    try:
        check_session(mutant)
    except AssertionError as exc:
        assert str(exc) == "V35 staging must exist only when Blynk is enabled", str(exc)
    else:
        raise AssertionError("Unconditional V35 staging mutation survived")
    print("PASS: session lifecycle with and without Blynk; unguarded V35 mutation rejected")


if __name__ == "__main__":
    main()
