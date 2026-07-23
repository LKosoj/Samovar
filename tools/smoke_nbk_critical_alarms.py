#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def forbid_tokens(name: str, body: str, tokens: list[str]) -> None:
    for token in tokens:
        if token in body:
            errors.append(f"{name} contains forbidden token: {token}")


nbk_text = read_text("nbk.h")
alarm_text = read_text("alarm.h")
api_text = read_text("samovar_api.h")

if nbk_text:
    try:
        body = extract_function_body(nbk_text, "bool check_nbk_critical_alarms")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    for token in [
        "request_emergency_stop(\"Недостаточное охлаждение! Останов.\")",
    ]:
        if token not in body:
            errors.append(f"NBK critical alarm missing emergency request: {token}")

    # [Ревью П1, находка 2] ранний return (режим сменился/питание снято/старт ещё не
    # дошёл до RUNNING) обязан сбрасывать nbk_dry_steam_start_time симметрично
    # nbk_overheat_start_time — иначе рестарт НБК сразу на 'S' с горячим
    # парогенератором даст мгновенный ложный стоп без выдержки 60с.
    try:
        early_return_body, _ = extract_braced_block_after(
            body,
            "if (SamovarStatusInt != SAMOVAR_STATUS_NBK || !PowerOn || startval < SAMOVAR_STARTVAL_NBK_RUNNING) {",
        )
    except ValueError as exc:
        errors.append(str(exc))
        early_return_body = ""

    if early_return_body:
        require_ordered_tokens(
            "[Ревью П1, находка 2] early return resets both critical-alarm timers before leaving NBK mode",
            early_return_body,
            [
                "nbk_overheat_start_time = 0;",
                "nbk_dry_steam_start_time = 0;",
                "return false;",
            ],
            errors,
        )

    try:
        mash_depleted_body, _ = extract_braced_block_after(
            body, "if (SteamSensor.avgTemp > 98.0) {"
        )
    except ValueError as exc:
        errors.append(str(exc))
        mash_depleted_body = ""

    if mash_depleted_body:
        require_ordered_tokens(
            "NBK ran-out-of-mash finishes gracefully via command queue, emergency stop only as fallback",
            mash_depleted_body,
            [
                "SendMsg(\"Кончилась брага. Программа НБК завершена.\", NOTIFY_MSG);",
                "if (!queue_samovar_command(SAMOVAR_POWER)) {",
                "request_emergency_stop(\"Аварийное отключение! Не удалось штатно завершить программу НБК (кончилась брага)\");",
            ],
            errors,
        )

    # [T3] верхний предел Тп на Ручной настройке (S) — защита от сухого хода парогенератора
    require_ordered_tokens(
        "NBK dry-steam upper limit on manual setup stage",
        body,
        [
            "} else if (SteamSensor.avgTemp >= 100.0) {",
            "nbk_dry_steam_start_time == 0",
            "millis() - nbk_dry_steam_start_time > 60000",
            "queue_samovar_command(SAMOVAR_POWER)",
        ],
        errors,
    )

    forbid_tokens(
        "check_nbk_critical_alarms",
        body,
        [
            "delay(",
            "SetSpeed(",
            "run_nbk_program(",
            "nbk_finish(",
            "set_power(",
            "set_current_power(",
            "nbk_M =",
            "nbk_P =",
        ],
    )

    try:
        body = extract_function_body(nbk_text, "void nbk_finish_common")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    for token in [
        "SetSpeed(0);",
        "stats.avgSpeed",
        "ProgramNum = 0;",
        "startval = SAMOVAR_STARTVAL_IDLE;",
        "SamovarStatusInt = SAMOVAR_STATUS_IDLE;",
        "stats.startTime = 0;",
        "stats.totalVolume = 0;",
    ]:
        if token not in body:
            errors.append(f"NBK finish common missing: {token}")
    forbid_tokens("nbk_finish_common", body, ["delay(", "set_power(", "run_nbk_program("])

    try:
        body = extract_function_body(nbk_text, "void nbk_emergency_finish")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "NBK emergency finish uses common cleanup and closes log",
        body,
        ["nbk_finish_common(true);", "nbk_close_data_log();"],
        errors,
    )
    forbid_tokens("nbk_emergency_finish", body, ["delay(", "set_power(", "run_nbk_program(", "nbk_finish("])

    try:
        body = extract_function_body(nbk_text, "void nbk_finish()")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "NBK normal finish starts deferred power-off cleanup",
        body,
        [
            "nbk_finish_common(false);",
            "safety_transition_begin(",
            "NBK_TRANSITION_FINISH_WAIT",
            "safety_deadline_after(millis(), 1000)",
        ],
        errors,
    )
    forbid_tokens("nbk_finish", body, ["delay(", "reset_sensor_counter(", "nbk_close_data_log("])
    for token in ["heatStartupPending", "set_power(false, false)"]:
        if token not in body:
            errors.append(f"nbk_finish missing owned heat-start cancellation: {token}")

    try:
        body = extract_function_body(nbk_text, "void tick_nbk_transition")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "NBK finish transition performs delayed cleanup",
        body,
        [
            "if (!finishOwnerValid && phase != NBK_TRANSITION_FINISH_WAIT_POWER_OFF)",
            "set_power(false, false);",
            "safety_transition_due(nbkTransition.transition, millis())",
            "set_power(false);",
            "safety_transition_advance(",
            "if (power_transition_active()) return;",
            "reset_sensor_counter();",
            "if (!nbk_close_data_log()) return;",
            "cancel_nbk_transition();",
        ],
        errors,
    )
    forbid_tokens("tick_nbk_transition", body, ["delay(", "vTaskDelay("])

if alarm_text:
    try:
        body = extract_function_body(alarm_text, "void perform_emergency_stop")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""

    require_ordered_tokens(
        "perform_emergency_stop calls NBK cleanup before generic hardware stop",
        body,
        [
            "if (Samovar_Mode == SAMOVAR_NBK_MODE) nbk_emergency_finish();",
            "set_power(false);",
            "set_stepper_target(0, 0, 0);",
        ],
        errors,
    )

if api_text and "void nbk_emergency_finish();" not in api_text:
    errors.append("samovar_api.h missing nbk_emergency_finish declaration")

if errors:
    print("NBK critical alarm smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("NBK critical alarm smoke check passed")
