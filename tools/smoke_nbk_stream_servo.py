#!/usr/bin/env python3
"""Поведенческий контракт переключения чистого/грязного потока НБК."""

from pathlib import Path
import subprocess
import tempfile
import textwrap

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
)


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
manual_stage = extract_function_body(SOURCE, "void handle_nbk_stage_manual() {")
optimization_stage = extract_function_body(SOURCE, "void handle_nbk_stage_optimization() {")
resume_work = extract_function_body(SOURCE, "inline void nbk_resume_work_after_safe_wait()")
run_program = extract_function_body(
    SOURCE, "void run_nbk_program(uint8_t num, bool workConfirmed, bool optimumEntry)"
)
finish_common = extract_function_body(SOURCE, "void nbk_finish_common(bool resetWorkState)")
errors: list[str] = []

require("nbk_set_stream_dirty();" in handle_overflow,
        "every centralized NBK overflow must switch to dirty stream")
require_ordered_tokens(
    "manual S overflow switches to dirty before actuator reduction",
    manual_stage,
    [
        "if (hasOverflow && !manual_overflow)",
        "nbk_set_stream_dirty();",
        "nbk_schedule_actuator_command(",
        "manual_overflow = true;",
    ],
    errors,
)
require_ordered_tokens(
    "O overflow after a found optimum switches to dirty before recovery entry",
    optimization_stage,
    [
        "if (overflow())",
        "if (!nbk_opt_found)",
        "} else {",
        "nbk_set_stream_dirty();",
        "run_nbk_program(ProgramNum + 1, false, true);",
    ],
    errors,
)

stage_one, _ = extract_braced_block_after(
    work_stage, "if (nbk_work_pause_stage == 1)"
)
stage_two, _ = extract_braced_block_after(
    work_stage, "else if (nbk_work_pause_stage == 2)"
)
require("nbk_set_stream_clean();" not in stage_one,
        "dirty stream must remain selected throughout recovery pause stage 1")
require_ordered_tokens(
    "clean stream is restored only when recovery pause stage 2 completes",
    stage_two,
    [
        "nbk_set_stream_clean();",
        "nbk_work_in_pause = false;",
        "nbk_work_pause_stage = 0;",
    ],
    errors,
)
require_ordered_tokens(
    "manual resume of an interrupted W stage restores clean before scheduling work",
    resume_work,
    [
        "nbk_safe_wait_result != ACTUATOR_COMMAND_APPLIED",
        "set_power(true);",
        "if (!PowerOn)",
        "nbk_set_stream_clean();",
        "nbk_safe_waiting = false;",
        "nbk_schedule_actuator_command(",
    ],
    errors,
)
require_ordered_tokens(
    "manual entry to W from safe wait restores clean before scheduling work",
    run_program,
    [
        "if (nbk_safe_waiting)",
        "nbk_safe_wait_result != ACTUATOR_COMMAND_APPLIED",
        "set_power(true);",
        "if (!PowerOn)",
        "nbk_set_stream_clean();",
        "nbk_safe_waiting = false;",
        "nbk_schedule_actuator_command(",
    ],
    errors,
)
require("nbk_set_stream_clean();" in finish_common,
        "NBK finish and emergency finish must restore clean stream")
require(not errors, "\n".join(errors))

mutation_specs = [
    (
        "manual S dirty",
        "      nbk_set_stream_dirty();\n      const float candidateP",
        "      const float candidateP",
        "void handle_nbk_stage_manual() {",
        ["if (hasOverflow && !manual_overflow)", "nbk_set_stream_dirty();", "nbk_schedule_actuator_command("],
    ),
    (
        "O optimum dirty",
        "          nbk_set_stream_dirty();\n          nbk_opt_entry_by_pressure = false;",
        "          nbk_opt_entry_by_pressure = false;",
        "void handle_nbk_stage_optimization() {",
        ["if (overflow())", "nbk_set_stream_dirty();", "run_nbk_program(ProgramNum + 1, false, true);"],
    ),
    (
        "resume helper clean",
        "  nbk_set_stream_clean();\n  nbk_safe_waiting = false;",
        "  nbk_safe_waiting = false;",
        "inline void nbk_resume_work_after_safe_wait()",
        ["if (!PowerOn)", "nbk_set_stream_clean();", "nbk_safe_waiting = false;"],
    ),
    (
        "explicit W clean",
        "      nbk_set_stream_clean();\n      nbk_safe_waiting = false;",
        "      nbk_safe_waiting = false;",
        "void run_nbk_program(uint8_t num, bool workConfirmed, bool optimumEntry)",
        ["if (!PowerOn)", "nbk_set_stream_clean();", "nbk_safe_waiting = false;"],
    ),
]
for label, original, replacement, signature, tokens in mutation_specs:
    mutated = SOURCE.replace(original, replacement, 1)
    require(mutated != SOURCE, f"{label}: mutation anchor is stale")
    mutation_errors: list[str] = []
    require_ordered_tokens(
        label,
        extract_function_body(mutated, signature),
        tokens,
        mutation_errors,
    )
    require(mutation_errors, f"{label}: removing the servo transition must fail the contract")

print("OK: NBK servo keeps dirty stream through the full recovery pause")
