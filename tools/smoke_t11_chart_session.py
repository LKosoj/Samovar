#!/usr/bin/env python3
"""T11: /ajax передаёт фактический ID сессии через request-local snapshot."""

import sys
import subprocess
from pathlib import Path

import smoke_a05_state_owners as a05


ROOT = Path(__file__).resolve().parents[1]


def compile_ajax(source: str, label: str) -> str:
    section = a05.production_section(source, (ROOT / "string_utils.h").read_text(encoding="utf-8"))
    return a05.compile_matrix(section, label, [])


def main() -> int:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    required = (
        "uint32_t sessionId;",
        "snapshot.sessionId = currentSessionId;",
        'jsonFieldRaw(out, first, "sessionId", snapshot.sessionId);',
    )
    missing = [token for token in required if token not in source]
    if missing:
        print("T11 session snapshot source check failed: " + ", ".join(missing))
        return 1

    actual = compile_ajax(source, "t11-session")
    if '"sessionId":1001' not in actual:
        print("T11 session snapshot did not serialize the first real ID")
        return 1

    capture_mutant = source.replace(
        "snapshot.sessionId = currentSessionId;", "snapshot.sessionId = 0;", 1
    )
    if capture_mutant == source:
        print("T11 capture mutation anchor not found")
        return 1
    try:
        compile_ajax(capture_mutant, "t11-session-capture-mutant")
    except subprocess.CalledProcessError as error:
        if error.returncode != 14:
            print("T11 capture mutation failed outside the two-ID assertion")
            return 1
    else:
        print("T11 capture mutation did not fail the two-ID assertion")
        return 1

    writer_mutant = source.replace(
        'jsonFieldRaw(out, first, "sessionId", snapshot.sessionId);',
        'jsonFieldRaw(out, first, "otherSessionId", snapshot.sessionId);',
        1,
    )
    if writer_mutant == source:
        print("T11 writer mutation anchor not found")
        return 1
    try:
        compile_ajax(writer_mutant, "t11-session-writer-mutant")
    except subprocess.CalledProcessError as error:
        if error.returncode != 14:
            print("T11 writer mutation failed outside the sessionId assertion")
            return 1
    else:
        print("T11 writer mutation did not fail the sessionId assertion")
        return 1

    print("T11 source-derived /ajax session snapshot passed; two mutations rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
