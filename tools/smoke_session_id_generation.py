#!/usr/bin/env python3
"""Проверяет, что случайный ID сессии никогда не становится нулём."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
HELPER_SIGNATURE = "static uint32_t new_random_session_id()"


def compile_and_run(body: str) -> subprocess.CompletedProcess[str]:
    harness = f'''
#include <cstddef>
#include <cstdint>

static const uint32_t values[] = {{0, 0, 57}};
static size_t calls = 0;

uint32_t esp_random() {{ return values[calls++]; }}

static uint32_t new_random_session_id() {{
{body}
}}

int main() {{
  if (new_random_session_id() != 57) return 1;
  return calls == 3 ? 0 : 2;
}}
'''
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "session_id.cpp"
        binary = Path(directory) / "session_id"
        source.write_text(harness, encoding="utf-8")
        build = subprocess.run(["g++", "-std=c++17", str(source), "-o", str(binary)], capture_output=True, text=True)
        if build.returncode != 0:
            raise RuntimeError(build.stderr)
        return subprocess.run([str(binary)], capture_output=True, text=True)


def main() -> int:
    if shutil.which("g++") is None:
        print("SMOKE_SKIP: g++ is unavailable")
        return 0
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    body = extract_function_body(source, HELPER_SIGNATURE)
    session = extract_function_body(source, "void session_begin(const String& sessionDescription)")
    if "currentSessionId = (epoch > NTP_PLAUSIBLE_MIN_EPOCH) ? epoch : new_random_session_id();" not in session:
        print("FAIL: session_begin does not use the nonzero random ID helper", file=sys.stderr)
        return 1
    result = compile_and_run(body)
    if result.returncode != 0:
        print("FAIL: zero random values were not rejected", file=sys.stderr)
        return 1
    mutant = body.replace("while (sessionId == 0)", "while (false)", 1)
    if mutant == body:
        print("FAIL: zero-rejection mutation anchor not found", file=sys.stderr)
        return 1
    result = compile_and_run(mutant)
    if result.returncode == 0:
        print("FAIL: zero-rejection mutation survived", file=sys.stderr)
        return 1
    print("Random session ID rejects zero without remapping another value")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
