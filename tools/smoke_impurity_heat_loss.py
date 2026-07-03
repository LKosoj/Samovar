#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

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


detector = read_text("impurity_detector.h")
sensorinit = read_text("sensorinit.h")
distiller = read_text("distiller.h")
bk = read_text("BK.h")
mode_common = read_text("mode_common.h")
power = read_text("power_regulator.h")

require_token("impurity detector heat-loss delta", detector, "static const float HEAT_LOSS_MIN_DELTA_T = 15.0f;")

try:
    reset_body = extract_function_body(detector, "void reset_heat_loss_calculation()")
except ValueError as exc:
    errors.append(str(exc))
    reset_body = ""

if reset_body:
    require_ordered_tokens(
        "reset_heat_loss_calculation clears all heat-loss state",
        reset_body,
        [
            "CurrentHeatLoss = 0;",
            "heatStartMillis = 0;",
            "heatStartTemp = 0;",
            "heatLossCalculated = false;",
        ],
        errors,
    )

try:
    update_body = extract_function_body(detector, "void update_heat_loss_calculation()")
except ValueError as exc:
    errors.append(str(exc))
    update_body = ""

if update_body:
    require_ordered_tokens(
        "update_heat_loss_calculation delta guard before CurrentHeatLoss",
        update_body,
        [
            "if (heatLossCalculated || BoilerVolume <= 0 || !PowerOn) return;",
            "heatStartMillis = millis();",
            "heatStartTemp = TankSensor.avgTemp;",
            "float timeSec = (millis() - heatStartMillis) / 1000.0;",
            "if (timeSec > 60)",
            "float deltaT = TankSensor.avgTemp - heatStartTemp;",
            "if (deltaT < HEAT_LOSS_MIN_DELTA_T) return;",
            "float energyUsed = BoilerVolume * 4187.0f * deltaT;",
            "CurrentHeatLoss = (float)current_power_p - powerEffective;",
            "heatLossCalculated = true;",
        ],
        errors,
    )

try:
    reset_sensor_body = extract_function_body(sensorinit, "void reset_sensor_counter(void)")
except ValueError as exc:
    errors.append(str(exc))
    reset_sensor_body = ""

if reset_sensor_body:
    require_token("reset_sensor_counter", reset_sensor_body, "reset_heat_loss_calculation();")

try:
    start_body = extract_function_body(mode_common, "inline bool mode_start_heating_session")
except ValueError as exc:
    errors.append(str(exc))
    start_body = ""

if start_body:
    require_ordered_tokens(
        "mode_start_heating_session resets heat-loss before create_data",
        start_body,
        [
            "if (PowerOn || SamovarStatusInt != activeStatus || alarm_event) return false;",
            "if (resetHeatLoss) reset_heat_loss_calculation();",
            "create_data()",
        ],
        errors,
    )

try:
    power_body = extract_function_body(power, "void set_power(bool On, bool enqueueResetCommand)")
except ValueError as exc:
    errors.append(str(exc))
    power_body = ""

if power_body:
    require_ordered_tokens(
        "rectification heat-loss reset before enabling power",
        power_body,
        [
            "bool wasPowerOn = PowerOn;",
            "if (On && !wasPowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE)",
            "reset_heat_loss_calculation();",
            "PowerOn = On;",
        ],
        errors,
    )

try:
    dist_body = extract_function_body(distiller, "void distiller_proc()")
except ValueError as exc:
    errors.append(str(exc))
    dist_body = ""

if dist_body:
    require_ordered_tokens(
        "distiller start resets heat-loss through shared helper",
        dist_body,
        ["mode_start_heating_session(", '"Включен нагрев дистиллятора"', "true"],
        errors,
    )

try:
    bk_body = extract_function_body(bk, "void bk_proc()")
except ValueError as exc:
    errors.append(str(exc))
    bk_body = ""

if bk_body:
    require_ordered_tokens(
        "BK start keeps heat-loss reset disabled",
        bk_body,
        ["mode_start_heating_session(", '"Включен нагрев бражной колонны"', "false"],
        errors,
    )

if errors:
    print("impurity heat-loss smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("impurity heat-loss smoke passed")
