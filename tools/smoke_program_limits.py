#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

SOURCE_FILES = [
    "Samovar.h",
    "Samovar.ino",
    "WebServer.ino",
    "logic.h",
    "beer.h",
    "distiller.h",
    "BK.h",
    "nbk.h",
    "lua.h",
    "program_types.h",
    "program_io.h",
]


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def strip_comments_and_literals(source: str) -> str:
    result: list[str] = []
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                result.append("\n")
            else:
                result.append(" ")
            index += 1
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                result.extend("  ")
                in_block_comment = False
                index += 2
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            result.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if in_char:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_char = False
            result.append("\n" if char == "\n" else " ")
            index += 1
            continue
        if char == "/" and next_char == "/":
            result.extend("  ")
            in_line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            result.extend("  ")
            in_block_comment = True
            index += 2
            continue
        if char == '"':
            in_string = True
            result.append(" ")
            index += 1
            continue
        if char == "'":
            in_char = True
            result.append(" ")
            index += 1
            continue
        result.append(char)
        index += 1
    return "".join(result)


program_types = read_text("program_types.h")
samovar_h = read_text("Samovar.h")

if program_types:
    for token in [
        "using ProgramType = char;",
        "constexpr ProgramType PROGRAM_TYPE_NONE = '\\0';",
        "constexpr uint8_t PROGRAM_MAX = CAPACITY_NUM * 2;",
        "constexpr uint8_t PROGRAM_END = PROGRAM_MAX;",
        "constexpr uint8_t NBK_PROGRAM_MAX = 4;",
        "static_assert(PROGRAM_MAX > 0 && PROGRAM_MAX < 255",
        "static_assert(PROGRAM_END == PROGRAM_MAX",
    ]:
        if token not in program_types:
            errors.append(f"program_types.h missing contract token: {token}")

if samovar_h:
    if not re.search(r"\bWProgram\s+program\s*\[\s*PROGRAM_MAX\s*\]\s*;", samovar_h):
        errors.append("Samovar.h must declare program as WProgram program[PROGRAM_MAX]")
    if "String WType" in samovar_h:
        errors.append("WProgram::WType must not be Arduino String")
    if not re.search(r"\bProgramType\s+WType\s*;", samovar_h):
        errors.append("WProgram::WType must use ProgramType")

for name in SOURCE_FILES:
    text = read_text(name)
    if not text:
        continue
    stripped = strip_comments_and_literals(text)
    if re.search(r"\bprogram\s*\[\s*30\s*\]", stripped):
        errors.append(f"{name} uses hardcoded program[30]")
    if name != "program_types.h" and re.search(r"\bCAPACITY_NUM\s*\*\s*2\b", stripped):
        errors.append(f"{name} uses CAPACITY_NUM*2 outside program_types.h")
    if re.search(r"\brun_program\s*\(\s*CAPACITY_NUM\s*\*\s*2\s*\)", stripped):
        errors.append(f"{name} calls run_program(CAPACITY_NUM*2)")

    lines = stripped.splitlines()
    for index, line in enumerate(lines):
        if "for" not in line or "<" not in line or "30" not in line:
            continue
        window = "\n".join(lines[index:index + 5])
        if re.search(r"for\s*\([^;\n]*;[^;\n]*<\s*30\b", line) and "program[" in window:
            errors.append(f"{name}:{index + 1} has program loop bounded by magic 30")

if errors:
    print("Program limit smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("Program limit smoke check passed")
