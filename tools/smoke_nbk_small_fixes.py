#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
    strip_cpp_comments,
)

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, text: str, token: str) -> None:
    if token not in text:
        errors.append(f"{name} missing token: {token}")


nbk = read_text("nbk.h")
program_types = read_text("program_types.h")

if nbk:
    nbk_code = strip_cpp_comments(nbk)
    require_token("nbk overheat state", nbk_code, "uint32_t nbk_overheat_start_time = 0;")
    if "static uint32_t overheat_start_time" in nbk_code:
        errors.append("check_nbk_critical_alarms still uses local static overheat timer")

    try:
        run_body = extract_function_body(nbk_code, "void run_nbk_program")
    except ValueError as exc:
        errors.append(str(exc))
        run_body = ""

    if run_body:
        require_ordered_tokens(
            "run_nbk_program resets NBK overheat timer before first row",
            run_body,
            [
                "if (num == 0)",
                "nbk_overheat_start_time = 0;",
                "if (num >= ProgramLen || program_type_empty(program[num].WType))",
            ],
            errors,
        )
        try:
            invalid_row, _ = extract_braced_block_after(
                run_body,
                "if (num >= ProgramLen || program_type_empty(program[num].WType))",
            )
        except ValueError as exc:
            errors.append(str(exc))
            invalid_row = ""
        if invalid_row:
            require_token("NBK invalid row emergency", invalid_row, "request_emergency_stop(")
            require_token("NBK empty program message", invalid_row, '"Программа НБК не задана"')
            require_token("NBK invalid row message", invalid_row, '"Ошибка программы НБК: строка не задана"')
            if "nbk_finish(" in invalid_row:
                errors.append("NBK invalid row must not finish normally")
            if "SendMsg(" in invalid_row:
                errors.append("NBK invalid row should let emergency stop send the alarm message")

    try:
        alarm_body = extract_function_body(nbk_code, "bool check_nbk_critical_alarms")
    except ValueError as exc:
        errors.append(str(exc))
        alarm_body = ""

    if alarm_body:
        require_ordered_tokens(
            "NBK critical alarm uses resettable overheat timer",
            alarm_body,
            [
                "nbk_overheat_start_time = 0;",
                "if (nbk_overheat_start_time == 0) nbk_overheat_start_time = millis();",
                "millis() - nbk_overheat_start_time > 60000",
                "request_emergency_stop(\"Недостаточное охлаждение! Останов.\")",
                "nbk_overheat_start_time = 0;",
            ],
            errors,
        )

    try:
        finish_body = extract_function_body(nbk_code, "void nbk_finish_common")
    except ValueError as exc:
        errors.append(str(exc))
        finish_body = ""

    if finish_body:
        require_ordered_tokens(
            "nbk_finish_common resets alarm timer and only reports real session stats",
            finish_body,
            [
                "SetSpeed(0);",
                "nbk_overheat_start_time = 0;",
                "uint32_t totalTime = stats.startTime > 0",
                "if (stats.startTime > 0)",
                "String summary",
                "SendMsg(summary, NOTIFY_MSG);",
                "stats.startTime = 0;",
            ],
            errors,
        )

    require_token("NBK operating range float division", nbk_code, "NBK_OPERATING_RANGE / 100.0f")
    require_token(
        "NBK work stage initializes next deadline",
        nbk_code,
        "nbk_work_next_time = safety_deadline_after(millis(), (uint32_t)nbk_column_inertia * 1000);",
    )

if program_types:
    require_token("ProgramType compact representation", program_types, "using ProgramType = char;")

if errors:
    print("NBK small fixes smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("NBK small fixes smoke passed")
