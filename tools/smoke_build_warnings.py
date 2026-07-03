#!/usr/bin/env python3
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def collect_section_values(text: str, section_name: str) -> list[str]:
    values: list[str] = []
    in_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = False
            continue
        if re.match(rf"^{re.escape(section_name)}\s*=", line):
            in_section = True
            remainder = line.partition("=")[2].strip()
            if remainder:
                values.append(remainder)
            continue
        if in_section:
            if "=" in line and not line.startswith("-"):
                in_section = False
                continue
            values.append(line)
    return values


platformio = read_text("platformio.ini")

if platformio:
    build_src_flags = collect_section_values(platformio, "build_src_flags")
    build_flags = collect_section_values(platformio, "build_flags")
    for flag in ["-Wall", "-Wextra"]:
        if flag not in build_src_flags:
            errors.append(f"platformio.ini build_src_flags missing {flag}")
        if flag in build_flags:
            errors.append(f"platformio.ini build_flags applies {flag} to dependencies; keep warning flags in build_src_flags")
    suppressions = [flag for flag in build_src_flags + build_flags if flag.startswith("-Wno-")]
    if suppressions:
        errors.append("warning suppressions must be documented separately before use: " + ", ".join(suppressions))

if errors:
    print("build warnings smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("build warnings smoke passed")
