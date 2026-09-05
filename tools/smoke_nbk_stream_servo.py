#!/usr/bin/env python3
"""Поведенческий контракт переключения чистого/грязного потока НБК."""

from pathlib import Path
import subprocess
import tempfile
import textwrap

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "nbk.h").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


dirty_body = extract_function_body(SOURCE, "inline void nbk_set_stream_dirty()")
clean_body = extract_function_body(SOURCE, "inline void nbk_set_stream_clean()")
require(dirty_body, "nbk_set_stream_dirty() is missing")
require(clean_body, "nbk_set_stream_clean() is missing")

harness = textwrap.dedent(
    f"""
    #include <stdint.h>
    #include <stdio.h>

    struct SetupEEPROM {{ bool NbkUseStreamServo; }};
    static SetupEEPROM SamSetup{{}};
    static int positions[4] = {{}};
    static int positionCount = 0;
    static void set_capacity(uint8_t position) {{ positions[positionCount++] = position; }}

    static void nbk_set_stream_dirty() {{
    {dirty_body}
    }}

    static void nbk_set_stream_clean() {{
    {clean_body}
    }}

    static void expect(bool condition, const char* message) {{
      if (!condition) {{ fprintf(stderr, "FAIL: %s\\n", message); throw 1; }}
    }}

    int main() {{
      SamSetup.NbkUseStreamServo = false;
      nbk_set_stream_dirty();
      nbk_set_stream_clean();
      expect(positionCount == 0, "disabled option must not move the servo");

      SamSetup.NbkUseStreamServo = true;
      nbk_set_stream_dirty();
      expect(positionCount == 1 && positions[0] == 1,
             "overflow must select dirty stream position 1");
      nbk_set_stream_clean();
      expect(positionCount == 2 && positions[1] == 0,
             "completed recovery must return clean stream position 0");
      return 0;
    }}
    """
)

with tempfile.TemporaryDirectory(prefix="samovar-nbk-stream-") as tmp:
    source = Path(tmp) / "test.cpp"
    binary = Path(tmp) / "test"
    source.write_text(harness, encoding="utf-8")
    subprocess.run(
        ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)

handle_overflow = extract_function_body(
    SOURCE,
    "void handle_overflow(const String& msg, bool finish, uint32_t pause_ms, bool graceful)",
)
work_stage = extract_function_body(SOURCE, "void handle_nbk_stage_work() {")
finish_common = extract_function_body(SOURCE, "void nbk_finish_common(bool resetWorkState)")

require("nbk_set_stream_dirty();" in handle_overflow,
        "every centralized NBK overflow must switch to dirty stream")
require(
    "nbk_work_pause_stage == 2" in work_stage and
    work_stage.find("nbk_set_stream_clean();", work_stage.find("nbk_work_pause_stage == 2")) >= 0,
    "clean stream must be restored only after recovery stage 2 completes",
)
require("nbk_set_stream_clean();" in finish_common,
        "NBK finish and emergency finish must restore clean stream")

print("OK: NBK servo keeps dirty stream through the full recovery pause")
