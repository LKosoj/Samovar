#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


logic_text = strip_cpp_comments(read_text("logic.h"))
alarm_text = strip_cpp_comments(read_text("alarm.h"))
beer_text = strip_cpp_comments(read_text("beer.h"))
distiller_text = strip_cpp_comments(read_text("distiller.h"))
bk_text = strip_cpp_comments(read_text("BK.h"))
nbk_text = strip_cpp_comments(read_text("nbk.h"))
mode_common_text = strip_cpp_comments(read_text("mode_common.h"))

if alarm_text:
    try:
        body = extract_function_body(alarm_text, "inline bool sensor_reading_valid")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    # [П18] Пороги теперь сравниваются с локальным согласованным снимком (errCount/
    # avgTemp), а не с sensor.ErrCount/sensor.avgTemp напрямую - см. seqlock-приём
    # в alarm.h (защита от torn read между записью из задачи опроса датчиков и
    # чтением из аварийного надзора).
    for token in ["errCount <= 10", "avgTemp >= 2.0f", "avgTemp < 126.0f"]:
        if token not in body:
            errors.append(f"sensor_reading_valid contract missing: {token}")
    try:
        body = extract_function_body(alarm_text, "bool process_sensor_failed")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if "request_emergency_stop" not in body:
        errors.append("process_sensor_failed does not request emergency stop")

    try:
        body = extract_function_body(alarm_text, "void check_alarm()")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    rectification_guards = [
        "if (!rectification_ds_sensors_assigned()) {",
        "notify_rectification_sensors_unassigned();",
        "if (optional_sensor_failed(SteamSensor) && process_sensor_failed(\"Ректификация\", \"пара\")) return;",
        "if (!mode_check_powered_cooling_sensors(\"Ректификация\")) return;",
        "if (optional_sensor_failed(TankSensor) && process_sensor_failed(\"Ректификация\", \"куба\")) return;",
    ]
    for token in rectification_guards:
        if token not in body:
            errors.append(f"rectification sensor guard missing: {token}")
    require_ordered_tokens(
        "rectification sensor guards before temperature logic",
        body,
        rectification_guards + ["TankSensor.avgTemp >= 2"],
        errors,
    )
    if "!sensor_valid(SteamSensor) && process_sensor_failed" in body:
        errors.append(
            "rectification still treats unassigned steam sensor as process emergency"
        )
    if "!sensor_valid(TankSensor) && process_sensor_failed" in body:
        errors.append(
            "rectification still treats unassigned tank sensor as process emergency"
        )
    try:
        notify_body = extract_function_body(
            alarm_text, "inline void notify_rectification_sensors_unassigned()"
        )
    except ValueError as exc:
        errors.append(str(exc))
        notify_body = ""
    if "WARNING_MSG" not in notify_body:
        errors.append("unassigned-sensor notice must be WARNING_MSG, not a siren")
    if "ALARM_MSG" in notify_body:
        errors.append("unassigned-sensor notice must not use ALARM_MSG")

samovar_text = strip_cpp_comments(read_text("Samovar.ino"))
if samovar_text:
    power_label = "case SAMOVAR_POWER:"
    power_start = samovar_text.find(power_label)
    power_end = samovar_text.find("case ", power_start + len(power_label)) if power_start >= 0 else -1
    if power_start < 0 or power_end < 0:
        errors.append("Samovar.ino: case SAMOVAR_POWER: not found")
    else:
        power_branch = samovar_text[power_start:power_end]
        for token in [
            "rectification_ds_sensors_assigned()",
            "notify_rectification_sensors_unassigned();",
        ]:
            if token not in power_branch:
                errors.append(f"SAMOVAR_POWER missing unassigned-sensor refuse: {token}")
    try:
        degraded_body = extract_function_body(
            samovar_text, "static void setup_report_degraded_boot()"
        )
    except ValueError as exc:
        errors.append(str(exc))
        degraded_body = ""
    if "ALARM_MSG" in degraded_body:
        errors.append(
            "setup_report_degraded_boot must not publish ALARM_MSG (browser siren)"
        )
    if "WARNING_MSG" not in degraded_body:
        errors.append("setup_report_degraded_boot must publish WARNING_MSG")

if mode_common_text:
    try:
        body = extract_function_body(mode_common_text, "inline bool mode_check_powered_cooling_sensors")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    for token in [
        "if (!sensor_valid(WaterSensor) && process_sensor_failed(modeName, \"воды\")) return false;",
        "if (optional_sensor_failed(ACPSensor) && process_sensor_failed(modeName, \"ТСА\")) return false;",
        "return true;",
    ]:
        if token not in body:
            errors.append(f"mode cooling sensor helper missing: {token}")
    try:
        body = extract_function_body(mode_common_text, "inline bool mode_should_open_cooling")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    for token in [
        "includeAcp && sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP - 5)",
        "includeTank && PowerOn && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP",
    ]:
        if token not in body:
            errors.append(f"mode cooling open helper missing: {token}")

if beer_text:
    try:
        body = extract_function_body(beer_text, "inline bool beer_control_sensor")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    for token in ["case 0:", "case 1:", "case 2:", "case 3:", "case 4:", "return false;"]:
        if token not in body:
            errors.append(f"beer control sensor resolver missing: {token}")
    try:
        body = extract_function_body(beer_text, "void beer_proc()")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "beer_proc sensor guard before heating",
        body,
        [
            "beer_validate_program(programError)",
            "beer_control_sensor(program[0].TempSensor",
            "sensor_valid(*controlSensor)",
            "process_sensor_failed(\"Пиво\", controlSensorName)",
            "create_data()",
            "set_power(true);",
        ],
        errors,
    )
    try:
        body = extract_function_body(beer_text, "void beer_stage_tick()")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "beer runtime sensor guard",
        body,
        [
            "beer_control_sensor(program[ProgramNum].TempSensor",
            "sensor_valid(*controlSensor)",
            "process_sensor_failed(\"Пиво\", controlSensorName)",
            "temp = controlSensor->avgTemp;",
        ],
        errors,
    )
    require_ordered_tokens(
        "beer invalid sensor triggers orderly stop, not emergency latch",
        body,
        [
            "beer_control_sensor(program[ProgramNum].TempSensor",
            "beer_abort_config_error(\"Ошибка программы: неверный датчик температуры в строке \" + String(ProgramNum + 1))",
            "return;",
            "sensor_valid(*controlSensor)",
        ],
        errors,
    )

for name, text, proc_signature, expected_sensor in [
    ("distiller", distiller_text, "void distiller_proc()", "if (!sensor_valid(TankSensor) && process_sensor_failed(\"Дистилляция\", \"куба\")) return;"),
    ("BK", bk_text, "void bk_proc()", "if (!sensor_valid(TankSensor) && process_sensor_failed(\"БК\", \"куба\")) return;"),
]:
    if not text:
        continue
    try:
        body = extract_function_body(text, proc_signature)
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        f"{name} start sensor guard before heating",
        body,
        [expected_sensor, "mode_run_heating_start("],
        errors,
    )
    for token in [
        "create_data()",
        "copy_mqtt_session_description",
        "MqttSendMsg",
        "set_power(true);",
        "delay(1000)",
        "set_power_mode(POWER_SPEED_MODE)",
        "set_current_power_mode_value(POWER_SPEED_MODE)",
    ]:
        if token in body:
            errors.append(f"{name} start path still contains direct shared heating operation: {token}")
    if name == "distiller":
        require_ordered_tokens(
            "distiller start helper parameters and side effects",
            body,
            [
                "if (SamovarStatusInt != SAMOVAR_STATUS_DISTILLATION) return;",
                expected_sensor,
                "if (!PowerOn || mode_heating_start_pending(SAMOVAR_STATUS_DISTILLATION))",
                "mode_run_heating_start(",
                "SAMOVAR_STATUS_DISTILLATION",
                "Ошибка создания файла лога. Старт дистилляции отменён.",
                "Описание сессии занято. Старт дистилляции отменён.",
                "get_dist_program()",
                "Включен нагрев дистиллятора",
                "true",
                "run_dist_program(0);",
            ],
            errors,
        )
    else:
        require_ordered_tokens(
            "BK start helper parameters",
            body,
            [
                "if (SamovarStatusInt != SAMOVAR_STATUS_BK) return;",
                expected_sensor,
                "if (!PowerOn || mode_heating_start_pending(SAMOVAR_STATUS_BK))",
                "mode_run_heating_start(",
                "SAMOVAR_STATUS_BK",
                "Ошибка создания файла лога. Старт БК отменён.",
                "Описание сессии занято. Старт БК отменён.",
                "String(\"BK\")",
                "Включен нагрев бражной колонны",
                "false",
            ],
            errors,
        )

if mode_common_text:
    try:
        begin_body = extract_function_body(mode_common_text, "inline ModeHeatingStartResult mode_begin_heating_session")
    except ValueError as exc:
        errors.append(str(exc))
        begin_body = ""
    require_ordered_tokens(
        "shared start begin blocks alarm restart before heating",
        begin_body,
        [
            "PowerOn || SamovarStatusInt != activeStatus || heater_safety_latched()",
            "if (resetHeatLoss) reset_heat_loss_calculation();",
            "create_data()",
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus)",
            "copy_mqtt_session_description",
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus)",
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus)",
            "set_power(true);",
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn)",
            "mode_fail_heating_start()",
        ],
        errors,
    )
    try:
        tick_body = extract_function_body(mode_common_text, "inline ModeHeatingStartResult mode_tick_heating_session")
    except ValueError as exc:
        errors.append(str(exc))
        tick_body = ""
    require_ordered_tokens(
        "shared start tick preserves alarm gates",
        tick_body,
        [
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn)",
            "power_transition_start_pending()",
            "safety_transition_due",
            "SteamSensor.Start_Pressure = bme_pressure;",
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn)",
            "MqttSendMsg",
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn)",
            "SendMsg(modeHeatingStart.heatingMessage, NOTIFY_MSG);",
        ],
        errors,
    )
    for token in ["create_data()", "copy_mqtt_session_description", "set_power(true);"]:
        if token in tick_body:
            errors.append(f"shared start tick repeats start-only work: {token}")

for name, text, signature, tokens in [
    (
        "distiller",
        distiller_text,
        "void check_alarm_distiller()",
        ["if (PowerOn && !mode_check_powered_cooling_sensors(\"Дистилляция\")) return;"],
    ),
    (
        "BK",
        bk_text,
        "void check_alarm_bk()",
        ["if (PowerOn && !mode_check_powered_cooling_sensors(\"БК\")) return;"],
    ),
]:
    if not text:
        continue
    try:
        body = extract_function_body(text, signature)
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    for token in tokens:
        if token not in body:
            errors.append(f"{name} alarm sensor guard missing: {token}")
    require_ordered_tokens(
        f"{name} alarm sensor guards before temperature logic",
        body,
        tokens + ["mode_should_open_cooling"],
        errors,
    )
    if name == "BK":
        # Критический перегрев воды/ТСА вынесен в общий хелпер
        # mode_common.h::mode_request_overheat_emergency_if_needed (его тело пинит
        # smoke_dist_bk_small_fixes.py); здесь — что пред-аварийное открытие
        # охлаждения предшествует критическому останову.
        require_ordered_tokens(
            "BK ACP pre-alarm opens cooling before critical stop",
            body,
            [
                "mode_should_open_cooling(false, true, true)",
                "open_valve(true, true)",
                "mode_request_overheat_emergency_if_needed()",
            ],
            errors,
        )

if nbk_text:
    try:
        body = extract_function_body(nbk_text, "bool nbk_stage_sensors_valid")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    for token in [
        "if (!sensor_valid(SteamSensor) && process_sensor_failed(\"НБК\", \"пара\")) return false;",
        "if (!sensor_valid(TankSensor) && process_sensor_failed(\"НБК\", \"куба\")) return false;",
    ]:
        if token not in body:
            errors.append(f"NBK stage sensor guard missing: {token}")
    try:
        body = extract_function_body(nbk_text, "void run_nbk_program")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "NBK stage sensor guard before heating",
        body,
        [
            "nbk_stage_sensors_valid(program[num].WType)",
            "ProgramNum = num;",
            "set_power(true);",
        ],
        errors,
    )
    try:
        body = extract_function_body(nbk_text, "bool check_nbk_critical_alarms")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    for token in [
        "if (!mode_check_powered_cooling_sensors(\"НБК\")) return true;",
    ]:
        if token not in body:
            errors.append(f"NBK critical sensor guard missing: {token}")
    require_ordered_tokens(
        "NBK critical sensor guards before temperature logic",
        body,
        [
            "if (!mode_check_powered_cooling_sensors(\"НБК\")) return true;",
            "SteamSensor.avgTemp > 98.0",
        ],
        errors,
    )

for name, text, signatures in [
    ("alarm", alarm_text, ["void check_alarm()"]),
    ("distiller", distiller_text, ["void check_alarm_distiller()"]),
    ("BK", bk_text, ["void check_alarm_bk()"]),
    ("NBK", nbk_text, ["bool check_nbk_critical_alarms"]),
]:
    for signature in signatures:
        if not text:
            continue
        try:
            body = extract_function_body(text, signature)
        except ValueError:
            continue
        for token in ["set_power(false)", "delay(", "SetSpeed(", "run_nbk_program(", "beer_finish("]:
            if token in body:
                errors.append(f"{name} alarm path contains direct hardware/flow operation: {token}")

if errors:
    print("Heating sensor validity smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("Heating sensor validity smoke check passed")
