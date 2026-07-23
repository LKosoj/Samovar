#!/usr/bin/env python3
import re
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


def require_token(name: str, body: str, token: str) -> None:
    if token not in body:
        errors.append(f"{name} missing token: {token}")


def forbid_blocking_delay(name: str, body: str) -> None:
    code = strip_cpp_comments(body)
    if re.search(r"\b(?:delay|vTaskDelay)\s*\(", code):
        errors.append(f"{name} must not block with delay/vTaskDelay")


pwm = read_text("pumppwm.h")
bk = read_text("BK.h")
samovar = read_text("Samovar.ino")
web = read_text("WebServer.ino")

try:
    init_body = extract_function_body(pwm, "void init_pump_pwm(uint8_t pin, int freq)")
except ValueError as exc:
    errors.append(str(exc))
    init_body = ""

try:
    pwm_body = extract_function_body(pwm, "void set_pump_pwm(float duty)")
except ValueError as exc:
    errors.append(str(exc))
    pwm_body = ""

try:
    pid_body = extract_function_body(pwm, "void set_pump_speed_pid(float temp)")
except ValueError as exc:
    errors.append(str(exc))
    pid_body = ""

try:
    bk_alarm_body = extract_function_body(bk, "void check_alarm_bk()")
except ValueError as exc:
    errors.append(str(exc))
    bk_alarm_body = ""

try:
    apply_config_body = extract_function_body(samovar, "void apply_config_runtime()")
except ValueError as exc:
    errors.append(str(exc))
    apply_config_body = ""

try:
    loop_body = extract_function_body(samovar, "void loop()")
except ValueError as exc:
    errors.append(str(exc))
    loop_body = ""

try:
    handle_save_body = extract_function_body(web, "void handleSave(AsyncWebServerRequest *request)")
except ValueError as exc:
    errors.append(str(exc))
    handle_save_body = ""

if init_body:
    require_token("init_pump_pwm", init_body, "pump_regulator.setpoint = SamSetup.SetWaterTemp;")

if pwm_body:
    forbid_blocking_delay("set_pump_pwm", pwm_body)
    require_ordered_tokens(
        "set_pump_pwm nonblocking startup",
        pwm_body,
        [
            "if (!pump_started && duty > 0)",
            "pump_pwm.write(PWM_START_VALUE * 10);",
            "pump_started = true;",
            "return;",
            "if (duty > 0 && wp_count < 10 && pump_started)",
            "wp_count++;",
            "return;",
        ],
        errors,
    )

if pid_body:
    forbid_blocking_delay("set_pump_speed_pid", pid_body)
    require_ordered_tokens(
        "set_pump_speed_pid setpoint before PID result",
        pid_body,
        [
            "pump_regulator.setpoint = SamSetup.SetWaterTemp;",
            "pump_regulator.input = temp;",
            "set_pump_pwm(pump_regulator.getResultNow());",
        ],
        errors,
    )

if bk_alarm_body:
    require_ordered_tokens(
        "BK custom pump PWM continues after valve open",
        bk_alarm_body,
        [
            "bool coolingOpenedThisTick = false;",
            "if (mode_should_open_cooling(false, true, true))",
            "set_pump_pwm(bk_pwm);",
            "coolingOpenedThisTick = true;",
            "if (!coolingOpenedThisTick && valve_status && pump_started && bk_pwm != PWM_LOW_VALUE * 40 && wp_count < 10)",
            "set_pump_pwm(bk_pwm);",
        ],
        errors,
    )

if apply_config_body:
    require_token("apply_config_runtime", apply_config_body, "pump_regulator.setpoint = SamSetup.SetWaterTemp;")

commit_signature = "static OperationError commit_profile_operation()"
commit_offset = samovar.rfind(commit_signature)
commit_body = extract_function_body(samovar[commit_offset:], commit_signature) if commit_offset >= 0 else ""
if commit_body:
    require_ordered_tokens(
        "profile owner reapplies runtime config",
        commit_body,
        [
            "save_profile_nvs(active_profile_operation.settings)",
            "if (persistResult != PERSIST_OK)",
            "SamSetup = active_profile_operation.settings;",
            "if (hasSettings) apply_config_runtime();",
        ],
        errors,
    )

if handle_save_body:
    if re.search(r"\bSamSetup\.SetWaterTemp\s*=", handle_save_body):
        errors.append("handleSave must not write SamSetup.SetWaterTemp directly")
    require_token("handleSave staged SetWaterTemp", handle_save_body, 'apply_save_float_arg(request, "SetWaterTemp", staged.SetWaterTemp')

if errors:
    print("pump PWM nonblocking smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("pump PWM nonblocking smoke passed")
