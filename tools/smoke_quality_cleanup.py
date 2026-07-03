#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = (
    "quality" + ".h",
    "quality" + "__h",
    "Quality" + "Params",
    "getQuality" + "Assessment",
    "overall" + "Score",
    "steamTemp" + "History",
)

SKIP_DIRS = {
    ".git",
    ".pio",
    "." + "cli-" + "pro" + "xy",
    ".claude",
    "node_modules",
    "pro" + "xy",
}

SKIP_FILES = {
    "AUDIT.md",
    "AUDIT_REMEDIATION_PLAN.md",
    "smoke_quality_cleanup.py",
}

TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".h",
    ".htm",
    ".html",
    ".ino",
    ".js",
    ".json",
    ".lua",
    ".md",
    ".py",
    ".txt",
    ".yml",
}

errors: list[str] = []

removed_header = "quality" + ".h"
if (ROOT / removed_header).exists():
    errors.append(f"{removed_header} still exists")

for path in ROOT.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in rel.parts):
        continue
    if rel.name in SKIP_FILES:
        continue
    if path.suffix not in TEXT_SUFFIXES:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for token in FORBIDDEN:
        if token in text:
            errors.append(f"{rel}: contains {token}")

if errors:
    print("quality cleanup smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("quality cleanup smoke check passed")
