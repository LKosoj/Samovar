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

    require_token("[T1] pause overflow repeat latch", nbk_code, "bool nbk_pause_overflow_repeat_latched = false;")
    require_token("[T2] Po ceiling state", nbk_code, "float nbk_Po_ceiling = 0;")
    require_token("[T2] high temp ticks counter", nbk_code, "uint8_t nbk_high_temp_ticks = 0;")
    require_token("[T3] dry steam start time", nbk_code, "uint32_t nbk_dry_steam_start_time = 0;")
    # [Ремонт-2026-09-02 П1] флаг-обходной путь удалён целиком - его работу
    # теперь делает прямой автовход run_nbk_program(num, false, true).
    if "nbk_work_entry_overflow_pending" in nbk_code:
        errors.append("[Ремонт-2026-09-02 П1] nbk_work_entry_overflow_pending must stay removed")
    if "NBK_OPERATING_RANGE" in nbk_code:
        errors.append("[Ремонт-2026-09-02] dead NBK_OPERATING_RANGE constant must stay removed")
    if "nbk_Mo_temp" in nbk_code or "nbk_Po_temp" in nbk_code:
        errors.append("[Ремонт-2026-09-02] dead nbk_Mo_temp/nbk_Po_temp must stay removed")

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
                # [Ревью П1, находка 2] симметричный сброс — иначе рестарт НБК на 'S' с
                # горячим парогенератором даёт мгновенный ложный стоп без выдержки 60с
                "nbk_dry_steam_start_time = 0;",
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

        # [T5] переход строки НБК запрещён, если нагрев уже выключен (num > 0)
        try:
            num_zero_block, num_zero_end = extract_braced_block_after(run_body, "if (num == 0) {")
        except ValueError as exc:
            errors.append(str(exc))
            num_zero_block, num_zero_end = "", -1

        if "if (num > 0 && !PowerOn)" in num_zero_block:
            errors.append("[T5] guard num>0 && !PowerOn must not live inside the num==0 branch")

        require_ordered_tokens(
            "[T5] run_nbk_program refuses line transition when heating already off",
            run_body,
            [
                "if (num > 0 && !PowerOn) {",
                "nbk_cancel_program_start(",
                "ProgramNum = num;",
            ],
            errors,
        )
        guard_index = run_body.find("if (num > 0 && !PowerOn) {")
        if guard_index >= 0 and num_zero_end >= 0 and guard_index < num_zero_end:
            errors.append("[T5] guard num>0 && !PowerOn is positioned before the end of the num==0 branch")

        # W разрешён только явной командой и коммитит строку после APPLIED.
        require_ordered_tokens(
            "run_nbk_program W-branch requires explicit confirmation and schedules commit",
            run_body,
            [
                "if (program[num].WType == 'W') {",
                "if (!workConfirmed) {",
                # [Ремонт-2026-09-02 П5.3] нулевая строка W разрешена, если есть
                # сохранённые nbk_Mo/nbk_Po - составное условие вместо одиночного.
                "if ((program[num].Power <= 0 || program[num].Speed <= 0) &&",
                "!(nbk_Mo > 0 && nbk_Po > 0)) {",
                "const float candidateM = program[num].Power > 0",
                "? toPower(program[num].Power)",
                ": nbk_Mo;",
                "const float candidateP = program[num].Speed > 0",
                "? program[num].Speed",
                ": nbk_Po;",
                "nbk_schedule_actuator_command(",
                "true,",
                "num))",
            ],
            errors,
        )
        if ": 500" in run_body or "? program[num].Speed : 1" in run_body:
            errors.append("run_nbk_program contains forbidden W fallback")

        # [T10] точка отсчёта статистики — на входе в S, не в H
        try:
            s_branch, _ = extract_braced_block_after(run_body, "if (program[ProgramNum].WType == 'S') {")
        except ValueError as exc:
            errors.append(str(exc))
            s_branch = ""
        if s_branch:
            require_ordered_tokens(
                "[T10] S-branch resets stats accounting point before SetSpeed",
                s_branch,
                [
                    "begintime = 0;",
                    "time_speed = millis();",
                    "nbk_schedule_actuator_command(",
                ],
                errors,
            )

    # [T8/П1] handle_nbk_stage_optimization: захлёб без найденного оптимума -
    # обычный handle_overflow(finish=true); захлёб ПОСЛЕ найденного оптимума -
    # прямой автовход в Работу (run_nbk_program(..., false, true)), а не флаг.
    try:
        # сигнатура с открывающей скобкой: у функции есть прототип в разделе
        # "Прототипы функций для этапов", extract_function_body без "{" нашёл бы его.
        opt_body = extract_function_body(nbk_code, "void handle_nbk_stage_optimization() {")
    except ValueError as exc:
        errors.append(str(exc))
        opt_body = ""

    if opt_body:
        require_ordered_tokens(
            "[T8/П1] optimization overflow without found optimum stops; with found optimum auto-enters W",
            opt_body,
            [
                "if (overflow()) {",
                "if (!nbk_opt_found) {",
                "handle_overflow(",
                "} else {",
                "run_nbk_program(ProgramNum + 1, false, true);",
                "}",
                "return;",
            ],
            errors,
        )

    # Снимок НБК применяется до любых переходов стадии.
    try:
        proc_body = extract_function_body(nbk_code, "void nbk_proc()")
    except ValueError as exc:
        errors.append(str(exc))
        proc_body = ""

    if proc_body:
        require_ordered_tokens(
            "nbk_proc applies session snapshot before transition guard",
            proc_body,
            [
                "nbk_M_max = nbkSessionConfig.maxPower;",
                "if (nbk_transition_blocks_process()) return;",
            ],
            errors,
        )

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
                "SetSpeed(0)",
                "nbk_overheat_start_time = 0;",
                "uint32_t totalTime = stats.startTime > 0",
                "if (stats.startTime > 0)",
                "String summary",
                "SendMsg(summary, NOTIFY_MSG);",
                "stats.startTime = 0;",
            ],
            errors,
        )

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
