#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
HEAVY_ALARM_TOKENS = [
    "set_power(false)",
    "delay(",
    "run_nbk_program(",
    "stop_process(",
    "beer_finish(",
    "distiller_finish(",
    "bk_finish(",
    "nbk_finish(",
]


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, body: str, token: str) -> None:
    if token not in body:
        errors.append(f"{name} missing token: {token}")


def forbid_token(name: str, body: str, token: str) -> None:
    if token in body:
        errors.append(f"{name} contains forbidden token: {token}")


mode_common = strip_cpp_comments(read_text("mode_common.h"))
logic = strip_cpp_comments(read_text("logic.h"))
alarm = strip_cpp_comments(read_text("alarm.h"))
distiller = strip_cpp_comments(read_text("distiller.h"))
bk = strip_cpp_comments(read_text("BK.h"))
nbk = strip_cpp_comments(read_text("nbk.h"))
safety_transition = strip_cpp_comments(read_text("safety_transition.h"))

if safety_transition:
    for signature, tokens in [
        (
            "inline bool safety_deadline_expired",
            ["(int32_t)(now - deadline) >= 0"],
        ),
        (
            "inline uint32_t safety_deadline_after",
            ["return now + delayMs;"],
        ),
    ]:
        try:
            body = extract_function_body(safety_transition, signature)
        except ValueError as exc:
            errors.append(str(exc))
            body = ""
        for token in tokens:
            require_token(signature, body, token)

for name, text in [
    ("logic.h", logic),
    ("distiller.h", distiller),
    ("BK.h", bk),
    ("nbk.h", nbk),
]:
    require_token(name, text, '#include "mode_common.h"')

if mode_common:
    for signature, tokens in [
        (
            "inline void mode_clear_alarm_pause_if_expired",
            ["alarm_t_min > 0", "safety_deadline_expired(millis(), alarm_t_min)", "alarm_t_min = 0;"],
        ),
        (
            "inline void mode_set_alarm_pause_ms",
            ["alarm_t_min = safety_deadline_after(millis(), delayMs);"],
        ),
        (
            "inline bool mode_check_powered_cooling_sensors",
            [
                "sensor_valid(WaterSensor)",
                "process_sensor_failed(modeName, \"воды\")",
                "optional_sensor_failed(ACPSensor)",
                "process_sensor_failed(modeName, \"ТСА\")",
            ],
        ),
        (
            "inline bool mode_should_open_cooling",
            [
                "if (valve_status) return false;",
                "if (requirePower && !PowerOn) return false;",
                "includeAcp && sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP - 5)",
                "includeTank && PowerOn && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP",
            ],
        ),
        (
            "inline bool mode_should_close_cooling",
            [
                "PowerOn || is_self_test || !valve_status",
                "WaterSensor.avgTemp > closeTemp",
                "requireAcpCoolEnough",
                "ACPSensor.avgTemp <= MAX_ACP_TEMP - 10",
            ],
        ),
        (
            "inline void mode_request_water_flow_emergency_if_needed",
            [
                "#ifdef USE_WATERSENSOR",
                "WFAlarmCount > WF_ALARM_COUNT && PowerOn",
                "set_buzzer(true);",
                "request_emergency_stop(\"Аварийное отключение! Прекращена подача воды.\")",
            ],
        ),
        (
            "inline bool mode_water_pre_alarm_due",
            [
                "WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5",
                "PowerOn",
                "alarm_t_min == 0",
            ],
        ),
        (
            "inline void mode_update_water_pump_pid",
            [
                "#ifdef USE_WATER_PUMP",
                "if (!valve_status) return;",
                "sensor_configured(ACPSensor)",
                "sensor_reading_valid(ACPSensor)",
                "ACPSensor.avgTemp > acpBoostThreshold",
                "ACPSensor.avgTemp > WaterSensor.avgTemp",
                "set_pump_speed_pid(SamSetup.SetWaterTemp + 3)",
                "set_pump_speed_pid(WaterSensor.avgTemp)",
            ],
        ),
        (
            "inline void mode_reduce_power_for_water_alarm_by_volts",
            [
                "#ifdef SAMOVAR_USE_POWER",
                "WaterSensor.avgTemp >= ALARM_WATER_TEMP",
                "set_buzzer(true);",
                "SendMsg(alarmMessage, ALARM_MSG);",
                "set_current_power(reduce_power_by_volts(target_power_volt, reduceVolts));",
            ],
        ),
        (
            "inline void mode_update_water_valve_by_setpoint",
            [
                "#ifdef USE_WATER_VALVE",
                "WaterSensor.avgTemp >= SamSetup.SetWaterTemp + 1",
                "digitalWrite(WATER_PUMP_PIN, USE_WATER_VALVE);",
                "WaterSensor.avgTemp <= SamSetup.SetWaterTemp - 1",
                "digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);",
            ],
        ),
        (
            "inline ModeHeatingStartResult mode_begin_heating_session",
            [
                "PowerOn || SamovarStatusInt != activeStatus || heater_safety_latched()",
                "if (resetHeatLoss) reset_heat_loss_calculation();",
                "create_data()",
                "copy_mqtt_session_description",
                "MODE_HEATING_PHASE_WAIT_POWER",
                "set_power(true);",
                "if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn)",
                "mode_fail_heating_start()",
            ],
        ),
        (
            "inline ModeHeatingStartResult mode_tick_heating_session",
            [
                "power_transition_start_pending()",
                "MODE_HEATING_PHASE_WAIT_STABILIZE",
                "safety_deadline_after(millis(), 1000)",
                "safety_transition_due",
                "SteamSensor.Start_Pressure = bme_pressure;",
                "MqttSendMsg",
                "SendMsg(modeHeatingStart.heatingMessage, NOTIFY_MSG);",
                "MODE_HEATING_START_SUCCEEDED",
            ],
        ),
    ]:
        try:
            body = extract_function_body(mode_common, signature)
        except ValueError as exc:
            errors.append(str(exc))
            body = ""
        for token in tokens:
            require_token(signature, body, token)

    try:
        body = extract_function_body(mode_common, "inline ModeHeatingStartResult mode_begin_heating_session")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "mode start begin alarm gates",
        body,
        [
            "PowerOn || SamovarStatusInt != activeStatus || heater_safety_latched()",
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
        body = extract_function_body(mode_common, "inline ModeHeatingStartResult mode_tick_heating_session")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "mode start tick waits without repeating setup",
        body,
        [
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn)",
            "MODE_HEATING_PHASE_WAIT_POWER",
            "power_transition_start_pending()",
            "MODE_HEATING_PHASE_WAIT_STABILIZE",
            "safety_deadline_after(millis(), 1000)",
            "safety_transition_due",
            "SteamSensor.Start_Pressure = bme_pressure;",
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn)",
            "MqttSendMsg",
            "if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn)",
            "SendMsg(modeHeatingStart.heatingMessage, NOTIFY_MSG);",
            "mode_clear_heating_start();",
            "MODE_HEATING_START_SUCCEEDED",
        ],
        errors,
    )
    for token in ["create_data()", "copy_mqtt_session_description", "set_power(true);"]:
        forbid_token("mode start tick", body, token)

    for signature in [
        "inline bool mode_check_powered_cooling_sensors",
        "inline bool mode_should_open_cooling",
        "inline bool mode_should_close_cooling",
        "inline void mode_stop_cooling_pump_if_started",
        "inline void mode_request_water_flow_emergency_if_needed",
        "inline bool mode_water_pre_alarm_due",
    ]:
        try:
            body = extract_function_body(mode_common, signature)
        except ValueError:
            continue
        for token in HEAVY_ALARM_TOKENS:
            forbid_token(f"{signature} alarm helper", body, token)

for name, text, signature, ordered in [
    (
        "alarm.h",
        alarm,
        "void check_alarm()",
        [
            "mode_clear_alarm_pause_if_expired();",
            "mode_check_powered_cooling_sensors(\"Ректификация\")",
            "mode_should_open_cooling(false, true, true)",
            "mode_should_close_cooling(SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE, true)",
            "mode_update_water_pump_pid(39.0f);",
            "mode_request_water_flow_emergency_if_needed();",
            "mode_water_pre_alarm_due()",
            "mode_reduce_power_for_water_alarm_by_volts(",
            "mode_set_alarm_pause_ms(30000);",
            "mode_update_water_valve_by_setpoint();",
        ],
    ),
    (
        "distiller.h",
        distiller,
        "void check_alarm_distiller()",
        [
            "mode_clear_alarm_pause_if_expired();",
            "mode_check_powered_cooling_sensors(\"Дистилляция\")",
            "mode_should_open_cooling(false, true, true)",
            "mode_should_close_cooling(SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE, false)",
            "mode_update_water_pump_pid(SamSetup.SetACPTemp);",
            "mode_request_water_flow_emergency_if_needed();",
            "mode_water_pre_alarm_due()",
            "mode_reduce_power_for_water_alarm_by_volts(",
            "mode_set_alarm_pause_ms(30000);",
            "mode_update_water_valve_by_setpoint();",
        ],
    ),
    (
        "BK.h",
        bk,
        "void check_alarm_bk()",
        [
            "mode_clear_alarm_pause_if_expired();",
            "mode_check_powered_cooling_sensors(\"БК\")",
            "mode_should_open_cooling(false, true, true)",
            "set_pump_pwm(bk_pwm);",
            "mode_should_close_cooling(SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE, false)",
            "mode_request_water_flow_emergency_if_needed();",
            "mode_water_pre_alarm_due()",
            "mode_reduce_power_for_water_alarm_by_volts(",
            "mode_set_alarm_pause_ms(30000);",
        ],
    ),
    (
        "nbk.h",
        nbk,
        "void check_alarm_nbk()",
        [
            "mode_should_close_cooling(TARGET_WATER_TEMP - 20, false)",
            "if (!PowerOn)",
            "mode_clear_alarm_pause_if_expired();",
            "mode_should_open_cooling(true, false, true)",
            "mode_update_water_pump_pid(SamSetup.SetACPTemp);",
            "mode_request_water_flow_emergency_if_needed();",
            "mode_water_pre_alarm_due()",
            "mode_set_alarm_pause_ms(60000);",
        ],
    ),
]:
    if not text:
        continue
    try:
        body = extract_function_body(text, signature)
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(f"{name} W5.1 helper order", body, ordered, errors)
    for token in [
        "WFAlarmCount > WF_ALARM_COUNT",
        "alarm_t_min > 0 &&",
        "alarm_t_min = millis()",
        "WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5",
    ]:
        forbid_token(signature, body, token)

    if signature in [
        "void check_alarm()",
        "void check_alarm_distiller()",
        "void check_alarm_nbk()",
    ]:
        for token in [
            "sensor_configured(ACPSensor) && sensor_reading_valid(ACPSensor)",
            "set_pump_speed_pid(",
        ]:
            forbid_token(f"{signature} raw water PID", body, token)

    if signature in [
        "void check_alarm()",
        "void check_alarm_distiller()",
    ]:
        forbid_token(f"{signature} raw water valve", body, "digitalWrite(WATER_PUMP_PIN")

    if signature in [
        "void check_alarm_distiller()",
        "void check_alarm_bk()",
    ]:
        forbid_token(
            f"{signature} raw water power reduction",
            body,
            "set_current_power(reduce_power_by_volts(target_power_volt, 5))",
        )

    if signature == "void check_alarm()":
        forbid_token(f"{signature} raw PWR_FACTOR reduction", body, "target_power_volt - 5 * PWR_FACTOR")

    if signature == "void check_alarm_nbk()":
        forbid_token(f"{signature} NBK keeps warning-only pre-alarm", body, "mode_reduce_power_for_water_alarm_by_volts(")

if nbk:
    for token in [
        "nbk_opt_next_time = millis() +",
        "nbk_work_next_time = millis() +",
        "(int32_t)(millis() - nbk_opt_next_time)",
        "(int32_t)(millis() - nbk_work_next_time)",
    ]:
        forbid_token("nbk deadlines", nbk, token)
    for token in [
        "nbk_opt_next_time = safety_deadline_after(millis(),",
        "nbk_work_next_time = safety_deadline_after(millis(),",
        "safety_deadline_expired(millis(), nbk_opt_next_time)",
        "safety_deadline_expired(millis(), nbk_work_next_time)",
    ]:
        require_token("nbk deadlines", nbk, token)
    try:
        body = extract_function_body(nbk, "bool check_nbk_critical_alarms")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    require_ordered_tokens(
        "NBK critical sensor helper before temperature checks",
        body,
        [
            "if (!mode_check_powered_cooling_sensors(\"НБК\")) return true;",
            "SteamSensor.avgTemp > 98.0",
        ],
        errors,
    )

for name, text, signature in [
    ("alarm", alarm, "void check_alarm()"),
    ("distiller", distiller, "void check_alarm_distiller()"),
    ("BK", bk, "void check_alarm_bk()"),
    ("NBK", nbk, "void check_alarm_nbk()"),
    ("NBK", nbk, "bool check_nbk_critical_alarms"),
]:
    try:
        body = extract_function_body(text, signature)
    except ValueError:
        continue
    for token in HEAVY_ALARM_TOKENS:
        forbid_token(f"{name} alarm path", body, token)

if errors:
    print("Mode common alarm smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Mode common alarm smoke check passed")
