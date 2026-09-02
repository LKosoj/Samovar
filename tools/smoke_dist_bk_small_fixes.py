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


def forbid(name: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token in source:
            errors.append(f"{name} contains forbidden token: {token}")


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
        "mode_handle_water_pre_alarm_if_due();",
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
            "BK.h check_boiling() runs before the pending-power short-circuit",
            bk_alarm_body,
            ["bool boilingNow = check_boiling();", "bk_work_power_pending"],
            errors,
        )

        # [П6] Message-before-power-reduction ordering and the dead-#else check for the
        # water pre-alarm now live in smoke_mode_common_alarms.py, against the shared
        # mode_handle_water_pre_alarm_if_due() body - BK.h only needs to call it.
        require_token(
            "BK.h water pre-alarm uses the shared helper",
            bk_alarm_body,
            "mode_handle_water_pre_alarm_if_due();",
        )

        # [A1 п.1/п.8] bk_apply_work_power() (BK.h) - единственная точка применения
        # BKPower/POWER_WORK_MODE, вызывается и по факту кипения, и по пред-аварии
        # воды (если переход ещё не случился). [T16] мёртвое предупреждение
        # (SamSetup.BKPower < power_work_mode_threshold(), недостижимо - поле
        # клампится этим же порогом при сохранении формы и миграции NVS) удалено
        # целиком вместе со старым #else-веткой check_alarm_bk() - осталась только
        # общая функция.
        apply_calls = bk_alarm_body.count("bk_apply_work_power();")
        if apply_calls != 2:
            errors.append(
                "BK.h check_alarm_bk must call bk_apply_work_power() exactly twice "
                f"(boiling branch + water pre-alarm branch), found {apply_calls}"
            )
        require_ordered_tokens(
            "BK.h applies BKPower on boiling, then (if still pending) on water pre-alarm, before the shared helper",
            bk_alarm_body,
            [
                "bool boilingNow = check_boiling();",
                "bk_work_power_pending && (boilingNow",
                "bk_apply_work_power();",
                "mode_water_pre_alarm_due()",
                "bk_apply_work_power();",
                "mode_handle_water_pre_alarm_if_due();",
            ],
            errors,
        )
        forbid(
            "BK.h check_alarm_bk",
            bk_alarm_body,
            (
                "current_power_mode_is(POWER_SLEEP_MODE)",
                "SamSetup.BKPower < power_work_mode_threshold()",
            ),
        )

    try:
        bk_finish_body = extract_function_body(bk_text, "void bk_finish()")
    except ValueError as exc:
        errors.append(str(exc))
        bk_finish_body = ""
    if bk_finish_body:
        require_token(
            "BK.h bk_finish resets bk_work_power_pending",
            bk_finish_body,
            "bk_work_power_pending = false;",
        )

    try:
        bk_apply_work_power_body = extract_function_body(bk_text, "static void bk_apply_work_power()")
    except ValueError as exc:
        errors.append(str(exc))
        bk_apply_work_power_body = ""
    if bk_apply_work_power_body:
        require_token(
            "BK.h bk_apply_work_power resets bk_work_power_pending",
            bk_apply_work_power_body,
            "bk_work_power_pending = false;",
        )
        # [9b] Мощность строки 0 (если задана) применяется сразу после BKPower, а
        # запуск программы БК (run_bk_program(0)) - после снятия флага, тем же
        # порядком, каким distiller_proc() зовёт run_dist_program(0) после старта.
        require_token(
            "BK.h bk_apply_work_power applies row 0 power",
            bk_apply_work_power_body,
            "apply_program_power_row(program[0].Power);",
        )
        require_token(
            "BK.h bk_apply_work_power starts the program at row 0",
            bk_apply_work_power_body,
            "run_bk_program(0);",
        )
        require_ordered_tokens(
            "BK.h bk_apply_work_power applies BKPower, then row 0 power, then starts the program",
            bk_apply_work_power_body,
            [
                "set_current_power(SamSetup.BKPower);",
                "apply_program_power_row(program[0].Power);",
                "bk_work_power_pending = false;",
                "run_bk_program(0);",
            ],
            errors,
        )

    try:
        bk_proc_body = extract_function_body(bk_text, "void bk_proc()")
    except ValueError as exc:
        errors.append(str(exc))
        bk_proc_body = ""
    if bk_proc_body:
        # [A1 п.6] В BK.h (в отличие от distiller.h) плато проверяется ДО DistTemp -
        # это новая функциональность для БК, порядок задан явно в плане.
        require_token(
            "BK.h bk_proc calls the shared plateau helper",
            bk_proc_body,
            "dist_plateau_finish_due()",
        )
        require_ordered_tokens(
            "BK.h bk_proc checks the plateau before DistTemp",
            bk_proc_body,
            ["dist_plateau_finish_due()", "TankSensor.avgTemp >= SamSetup.DistTemp"],
            errors,
        )
        # [9b] Переход по строкам программы БК использует тот же общий хелпер, что
        # и дистилляция, и происходит после обеих проверок финиша.
        require_token(
            "BK.h bk_proc uses the shared row-threshold helper",
            bk_proc_body,
            "program_threshold_row_done(program[ProgramNum])",
        )
        require_token(
            "BK.h bk_proc advances to the next program row",
            bk_proc_body,
            "run_bk_program(ProgramNum + 1)",
        )
        require_ordered_tokens(
            "BK.h bk_proc checks both finish conditions before the row transition",
            bk_proc_body,
            [
                "dist_plateau_finish_due()",
                "TankSensor.avgTemp >= SamSetup.DistTemp",
                "program_threshold_row_done",
            ],
            errors,
        )

    try:
        run_bk_program_body = extract_function_body(bk_text, "void run_bk_program(uint8_t num)")
    except ValueError as exc:
        errors.append(str(exc))
        run_bk_program_body = ""
    if run_bk_program_body:
        # [9b] По образцу run_dist_program: мощность ЗАВЕРШИВШЕЙСЯ строки
        # применяется при переходе, уставка воды взводится из НОВОЙ строки.
        require_token(
            "run_bk_program applies the finished row's power",
            run_bk_program_body,
            "apply_program_power_row(program[num - 1].Power)",
        )
        require_token(
            "run_bk_program arms the water setpoint from the new row",
            run_bk_program_body,
            "bk_water_auto = program[num].Temp > 0;",
        )

# [П4.4/T21-1] distiller.h: BOOST heater is gated off exactly once, on the first
# row transition (num > 0), regardless of the leaving row's Power - Power == 0
# means "pass-through, don't touch the regulator", not "no power set", so it must
# not block the gate. See smoke_dist_boost_gate.py for the behavioral check.
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
        # [A1 п.6] Плато DistTimeF вынесено в общий хелпер dist_plateau_finish_due()
        # (используется и BK.h) - тело плато не должно копипаститься рядом с вызовом.
        require_token(
            "distiller_proc calls the shared plateau helper",
            distiller_proc_body,
            "dist_plateau_finish_due()",
        )
        forbid(
            "distiller_proc",
            distiller_proc_body,
            ("TankSensor.avgTemp - d_s_temp_finish",),
        )
        # [9b] Условие завершения строки программы (T/A/S/P/R) вынесено в общий
        # хелпер program_threshold_row_done() (используется и BK.h) - здесь не
        # должно оставаться копии инлайновых WType-веток.
        require_token(
            "distiller_proc uses the shared row-threshold helper",
            distiller_proc_body,
            "program_threshold_row_done(program[ProgramNum])",
        )
        forbid(
            "distiller_proc",
            distiller_proc_body,
            ("program[ProgramNum].WType == 'T'",),
        )

    try:
        row_done_body = extract_function_body(
            distiller_text, "inline bool program_threshold_row_done"
        )
    except ValueError as exc:
        errors.append(str(exc))
        row_done_body = ""
    if row_done_body:
        for row_type_token in ["'T'", "'A'", "'S'", "'P'", "'R'"]:
            require_token(
                "program_threshold_row_done handles WType " + row_type_token,
                row_done_body,
                row_type_token,
            )

    try:
        dist_plateau_body = extract_function_body(
            distiller_text, "inline bool dist_plateau_finish_due()"
        )
    except ValueError as exc:
        errors.append(str(exc))
        dist_plateau_body = ""
    if dist_plateau_body:
        require_token(
            "dist_plateau_finish_due restarts the plateau timer on temperature movement",
            dist_plateau_body,
            "d_s_time_min = millis();",
        )
        require_token(
            "dist_plateau_finish_due reports the out-of-alcohol message",
            dist_plateau_body,
            "В кубе не осталось спирта",
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
        require_token(
            "distiller_finish guards the session timer",
            distiller_finish_body,
            "if (sessionTimerValid)",
        )
        if "millis() - timePredictor.startTime" in distiller_finish_body:
            errors.append("distiller_finish still reads timePredictor.startTime for total time")

    try:
        update_predictor_body = extract_function_body(distiller_text, "void updateTimePredictor()")
    except ValueError as exc:
        errors.append(str(exc))
        update_predictor_body = ""
    if update_predictor_body:
        require_token(
            "updateTimePredictor keeps the per-row rate denominator on timePredictor.startTime",
            update_predictor_body,
            "(currentTime - timePredictor.startTime)",
        )
        require_token(
            "updateTimePredictor keeps process estimation after program rows",
            update_predictor_body,
            "timePredictor.processRemainingTime",
        )
        require_token(
            "updateTimePredictor guards pre-boil predictions",
            update_predictor_body,
            "!timePredictor.baselineValid || !sessionTimerValid",
        )
        if "ProgramNum >= ProgramLen" in update_predictor_body and \
                "timePredictor.predictedTotalTime = elapsedMinutes" in update_predictor_body:
            errors.append(
                "updateTimePredictor still forces process forecast to elapsed time after rows"
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

# [БК п.4] Сброс bk_pwm в дефолт только для остановленного насоса: у ещё
# крутящегося насоса охлаждения подача воды не должна проседать до стартовых
# 400 после остановки процесса.
sensorinit_text = strip_cpp_comments(read_text("sensorinit.h"))
if sensorinit_text:
    try:
        reset_state_body = extract_function_body(sensorinit_text, "void reset_process_state(void)")
    except ValueError as exc:
        errors.append(str(exc))
        reset_state_body = ""
    if reset_state_body:
        require_token(
            "sensorinit.h reset_process_state resets bk_pwm only for a stopped pump",
            reset_state_body,
            "if (!pump_started) bk_pwm = PWM_LOW_VALUE * 40;",
        )
        if reset_state_body.count("bk_pwm =") != 1:
            errors.append(
                "sensorinit.h reset_process_state must assign bk_pwm exactly once (guarded by !pump_started)"
            )

if errors:
    print("dist/BK small fixes smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("dist/BK small fixes smoke passed")
