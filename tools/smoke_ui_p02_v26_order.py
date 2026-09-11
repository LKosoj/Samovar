#!/usr/bin/env python3
"""Typed V26 не уходит раньше уже staged V35 той же сессии."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]


def compile_and_run(body: str) -> int:
    source = f'''\
#include <cstring>
static bool pendingV35 = false;
bool blynk_session_start_pending() {{ return pendingV35; }}
static bool defer_typed_pair_until_v35(const char* message) {{
{body}
}}
int main() {{
  pendingV35 = true;
  if (!defer_typed_pair_until_v35("@P1;s=1")) return 1;
  if (defer_typed_pair_until_v35("ordinary V26")) return 2;
  pendingV35 = false;
  if (defer_typed_pair_until_v35("@P1;s=1")) return 3;
  return 0;
}}
'''
    with tempfile.TemporaryDirectory(prefix="samovar-v26-order-") as temp:
        cpp = Path(temp) / "test.cpp"
        binary = Path(temp) / "test"
        cpp.write_text(source, encoding="utf-8")
        result = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-pedantic",
                                 "-DSAMOVAR_USE_BLYNK", str(cpp), "-o", str(binary)], capture_output=True, text=True)
        if result.returncode:
            print(result.stderr, end="")
            return 1
        return subprocess.run([str(binary)]).returncode


def main() -> int:
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    blynk = (ROOT / "Blynk.ino").read_text(encoding="utf-8")
    body = extract_function_body(samovar, "static bool defer_typed_pair_until_v35(const char* message)")
    trigger = strip_cpp_comments(extract_function_body(samovar, "void triggerGetClock(void *parameter)"))
    if "const bool deferTypedPair = defer_typed_pair_until_v35(c + 1);" not in trigger or \
       "!deferTypedPair" not in trigger or "Blynk.virtualWrite(V26, pushMsg);" not in trigger:
        print("V26 typed defer is not between queue read and V26 send")
        return 1
    if "s_pendingV35Ready" not in extract_function_body(blynk, "bool blynk_session_start_pending()"):
        print("V35 pending helper does not read staged V35 state")
        return 1
    if compile_and_run(body):
        print("V26/V35 schedule harness failed")
        return 1
    mutant = body.replace('strncmp(message, "@P1;", 4) == 0', "false")
    if mutant == body or compile_and_run(mutant) == 0:
        print("V26/V35 mutation survived")
        return 1
    print("P02 V35-before-typed-V26 smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
