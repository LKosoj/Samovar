#!/usr/bin/env python3
"""Единый валидатор режима и запрет прямой Lua-мутации режима."""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

web = (ROOT / "WebServer.ino").read_text(encoding="utf-8", errors="ignore")
samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8", errors="ignore")
samovar_h = (ROOT / "Samovar.h").read_text(encoding="utf-8", errors="ignore")
api = (ROOT / "samovar_api.h").read_text(encoding="utf-8", errors="ignore")
lua = (ROOT / "lua.h").read_text(encoding="utf-8", errors="ignore")

mode_enum_match = re.search(r"enum SAMOVAR_MODE \{[^}]*\};", samovar_h)
mode_enum = mode_enum_match.group(0) if mode_enum_match else ""
if not mode_enum:
    errors.append("enum SAMOVAR_MODE not found")

try:
    validator = extract_function_body(web, "bool is_valid_samovar_mode(long mode) {")
except ValueError as exc:
    errors.append(str(exc))
    validator = ""

mode_clamp_match = re.search(
    r"if \(.*?\) SamSetup\.Mode = 0;\n\s*Samovar_Mode = \(SAMOVAR_MODE\)SamSetup\.Mode;",
    samovar,
)
mode_clamp = mode_clamp_match.group(0) if mode_clamp_match else ""
if not mode_clamp:
    errors.append("mode clamp block not found")

try:
    queue_body = extract_function_body(
        web, "static OperationError queue_profile_operation("
    )
except ValueError as exc:
    errors.append(str(exc))
    queue_body = ""
if queue_body:
    for token in [
        "is_valid_samovar_mode(sourceMode)",
        "is_valid_samovar_mode(targetMode)",
    ]:
        if token not in queue_body:
            errors.append(f"compound profile transaction missing validator: {token}")

try:
    change_body = extract_function_body(web, "void change_samovar_mode() {")
except ValueError as exc:
    errors.append(str(exc))
    change_body = ""
if change_body:
    require_ordered_tokens(
        "change_samovar_mode validator",
        change_body,
        [
            "if (!is_valid_samovar_mode(Samovar_Mode)) {",
            "Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;",
        ],
        errors,
    )

for source_name, source in [
    ("Samovar.ino", samovar),
    ("samovar_api.h", api),
    ("lua.h", lua),
]:
    for forbidden in ["LuaModeTarget", "set_lua_mode_value"]:
        if forbidden in source:
            errors.append(
                f"{source_name} still exposes forbidden direct Lua mode mutation: {forbidden}"
            )

HARNESS = r'''
#include <iostream>

@MODE_ENUM@

struct Setup {
  int Mode;
};
static Setup SamSetup;
static SAMOVAR_MODE Samovar_Mode;

static bool is_valid_samovar_mode(long mode) {
@VALIDATOR@
}

static void apply_loaded_mode_clamp() {
@CLAMP@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  check(!is_valid_samovar_mode(-1), "negative mode must fail");
  check(is_valid_samovar_mode(SAMOVAR_RECTIFICATION_MODE), "first mode must pass");
  check(is_valid_samovar_mode(SAMOVAR_LUA_MODE), "last mode must pass");
  check(!is_valid_samovar_mode(SAMOVAR_LUA_MODE + 1), "one-past-last must fail");

  SamSetup.Mode = -1;
  apply_loaded_mode_clamp();
  check(SamSetup.Mode == SAMOVAR_RECTIFICATION_MODE,
        "negative persisted mode must be clamped");
  SamSetup.Mode = SAMOVAR_LUA_MODE;
  apply_loaded_mode_clamp();
  check(Samovar_Mode == SAMOVAR_LUA_MODE, "valid persisted mode must survive");

  if (failures != 0) return 1;
  std::cout << "Samovar mode validation and Lua read-only route passed\n";
  return 0;
}
'''

if not errors:
    source = (
        HARNESS.replace("@MODE_ENUM@", mode_enum)
        .replace("@VALIDATOR@", validator)
        .replace("@CLAMP@", mode_clamp)
    )
    with tempfile.TemporaryDirectory(prefix="samovar-mode-validation-") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / "mode_validation.cpp"
        binary_path = temp / "mode_validation"
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source_path),
                "-o",
                str(binary_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            errors.append("compile failed:\n" + result.stdout + result.stderr)
        else:
            result = subprocess.run(
                [str(binary_path)], capture_output=True, text=True, check=False
            )
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            if result.returncode != 0:
                errors.append("runtime validation failed")

if errors:
    print("Samovar mode validation smoke check failed:")
    for error in errors:
        print(f" - {error}")
    raise SystemExit(1)

print("Samovar mode validation smoke check passed")
