#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

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


checks = [
    ("distiller.h", "void check_alarm_distiller"),
    ("BK.h", "void check_alarm_bk"),
]

for file_name, signature in checks:
    text = strip_cpp_comments(read_text(file_name))
    if not text:
        continue
    try:
        body = extract_function_body(text, signature)
    except ValueError as exc:
        errors.append(str(exc))
        continue

    require_token(
        f"{file_name} uses common overheat emergency helper",
        body,
        "mode_request_overheat_emergency_if_needed();",
    )

    require_token(
        f"{file_name} uses common PWR_FACTOR-aware reduction helper",
        body,
        "mode_reduce_power_for_water_alarm_by_volts(",
    )
    if "target_power_volt - 5 * PWR_FACTOR" in body or "target_power_volt - 5" in body:
        errors.append(f"{file_name} contains raw power reduction instead of helper")

mode_common_text = strip_cpp_comments(read_text("mode_common.h"))
if mode_common_text:
    try:
        helper_body = extract_function_body(
            mode_common_text, "inline void mode_request_overheat_emergency_if_needed"
        )
    except ValueError as exc:
        errors.append(str(exc))
        helper_body = ""

    if helper_body:
        require_ordered_tokens(
            "mode_common overheat helper reports simultaneous water and ACP overheat",
            helper_body,
            [
                "String s = \"\";",
                "if (WaterSensor.avgTemp >= MAX_WATER_TEMP)",
                "s = s + \" Воды\";",
                "if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP))",
                "s = s + \" ТСА\";",
                "request_emergency_stop(\"Аварийное отключение! Превышена максимальная температура\" + s);",
            ],
            errors,
        )
        if "else if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP))" in helper_body:
            errors.append("mode_common overheat helper hides ACP overheat when water overheat is active")

# [П4.1] BK.h check_alarm_bk: check_boiling() must run unconditionally each tick,
# not only inside the POWER_SPEED_MODE short-circuit that can stop calling it.
# [П4.8] Same function: the water pre-alarm SendMsg must fire unconditionally,
# before the optional (SAMOVAR_USE_POWER-gated) power-reduction branch.
bk_text = strip_cpp_comments(read_text("BK.h"))
if bk_text:
    try:
        bk_alarm_body = extract_function_body(bk_text, "void check_alarm_bk()")
    except ValueError as exc:
        errors.append(str(exc))
        bk_alarm_body = ""
    if bk_alarm_body:
        # [П4.1 fix] check_boiling() returns true ONLY on the single call where
        # boiling is first detected (boil_started latches false afterwards) - a
        # second direct call in the condition would always observe false and
        # silently disable the boiling branch. Enforce exactly one call whose
        # result is captured and reused.
        boiling_call_count = bk_alarm_body.count("check_boiling()")
        if boiling_call_count != 1:
            errors.append(
                "BK.h check_alarm_bk must call check_boiling() exactly once "
                f"(found {boiling_call_count}) - a second call would swallow the one-shot true return"
            )
        require_ordered_tokens(
            "BK.h check_alarm_bk stores check_boiling() result and reuses it in the condition",
            bk_alarm_body,
            ["bool boilingNow = check_boiling();", "boilingNow ||"],
            errors,
        )
        require_ordered_tokens(
            "BK.h check_boiling() runs before the power-mode short-circuit",
            bk_alarm_body,
            ["bool boilingNow = check_boiling();", "current_power_mode_is(POWER_SPEED_MODE)"],
            errors,
        )

        require_ordered_tokens(
            "BK.h water pre-alarm sends message unconditionally before power reduction",
            bk_alarm_body,
            [
                "mode_water_pre_alarm_due()",
                "SendMsg((\"Критическая температура воды!\")",
                "#ifdef SAMOVAR_USE_POWER",
                "mode_reduce_power_for_water_alarm_by_volts(",
            ],
            errors,
        )

        pre_alarm_start = bk_alarm_body.find("mode_water_pre_alarm_due()")
        pause_call = bk_alarm_body.find("mode_set_alarm_pause_ms(30000)")
        if pre_alarm_start >= 0 and pause_call > pre_alarm_start:
            if "#else" in bk_alarm_body[pre_alarm_start:pause_call]:
                errors.append("BK.h water pre-alarm still has a dead #else branch")
        else:
            errors.append("BK.h water pre-alarm range not found for #else check")

# [П4.4] distiller.h: BOOST heater is gated off exactly once, on the first row
# transition where the program starts supplying its own Power.
# [П4.6] distiller.h: sessionStartTime (not the per-row timePredictor.startTime)
# must back the session-wide "Общее время" figures.
distiller_text = strip_cpp_comments(read_text("distiller.h"))
if distiller_text:
    try:
        run_dist_program_body = extract_function_body(distiller_text, "void run_dist_program(uint8_t num)")
    except ValueError as exc:
        errors.append(str(exc))
        run_dist_program_body = ""
    if run_dist_program_body:
        require_token(
            "run_dist_program latches distBoostGated",
            run_dist_program_body,
            "distBoostGated = true;",
        )
        require_token(
            "run_dist_program gates on the previous row's Power",
            run_dist_program_body,
            "program[num - 1].Power != 0",
        )
        require_ordered_tokens(
            "run_dist_program applies the power row before latching the BOOST gate",
            run_dist_program_body,
            [
                "set_capacity(program[num - 1].capacity_num);",
                "apply_program_power_row(program[num - 1].Power);",
                "distBoostGated = true;",
            ],
            errors,
        )

    try:
        distiller_proc_body = extract_function_body(distiller_text, "void distiller_proc()")
    except ValueError as exc:
        errors.append(str(exc))
        distiller_proc_body = ""
    if distiller_proc_body:
        require_token(
            "distiller_proc resets distBoostGated on (re)start",
            distiller_proc_body,
            "distBoostGated = false;",
        )

    try:
        distiller_finish_body = extract_function_body(distiller_text, "void distiller_finish()")
    except ValueError as exc:
        errors.append(str(exc))
        distiller_finish_body = ""
    if distiller_finish_body:
        require_token(
            "distiller_finish reports elapsed time via sessionStartTime",
            distiller_finish_body,
            "millis() - sessionStartTime",
        )
        if "millis() - timePredictor.startTime" in distiller_finish_body:
            errors.append("distiller_finish still reads timePredictor.startTime for total time")

    try:
        update_predictor_body = extract_function_body(distiller_text, "void updateTimePredictor()")
    except ValueError as exc:
        errors.append(str(exc))
        update_predictor_body = ""
    if update_predictor_body:
        session_count = update_predictor_body.count("(currentTime - sessionStartTime)")
        if session_count != 2:
            errors.append(
                f"updateTimePredictor sessionStartTime usage count mismatch: expected 2, got {session_count}"
            )
        require_token(
            "updateTimePredictor keeps the per-row rate denominator on timePredictor.startTime",
            update_predictor_body,
            "(currentTime - timePredictor.startTime)",
        )

# [П4.7] logic.h: get_distiller_status_text must not fabricate a phantom program
# row once ProgramNum reaches ProgramLen.
logic_text = strip_cpp_comments(read_text("logic.h"))
if logic_text:
    try:
        status_body = extract_function_body(logic_text, "String get_distiller_status_text()")
    except ValueError as exc:
        errors.append(str(exc))
        status_body = ""
    if status_body:
        require_token(
            "get_distiller_status_text branches on ProgramNum < ProgramLen",
            status_body,
            "if (ProgramNum < ProgramLen)",
        )
        require_token(
            "get_distiller_status_text reports program exhaustion",
            status_body,
            "Программы выполнены, отбор до T куба ",
        )
        require_token(
            "get_distiller_status_text reports DistTemp on exhaustion",
            status_body,
            "String(SamSetup.DistTemp, 1)",
        )

        prg_token = "\"Прг №\" + String(ProgramNum + 1)"
        occurrences = status_body.count(prg_token)
        if occurrences != 1:
            errors.append(f"get_distiller_status_text \"Прг №\" token count mismatch: expected 1, got {occurrences}")
        branch_index = status_body.find("if (ProgramNum < ProgramLen)")
        prg_index = status_body.find(prg_token)
        if branch_index < 0 or prg_index < 0 or prg_index < branch_index:
            errors.append(
                "get_distiller_status_text builds the \"Прг №\" branch before checking ProgramNum < ProgramLen"
            )

if errors:
    print("dist/BK small fixes smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("dist/BK small fixes smoke passed")
