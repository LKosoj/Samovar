#!/usr/bin/env python3
import re
import subprocess
import sys
import tempfile
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
    pwm_body = extract_function_body(
        pwm, "ActuatorCommandResult set_pump_pwm(float duty)"
    )
except ValueError as exc:
    errors.append(str(exc))
    pwm_body = ""

try:
    pid_body = extract_function_body(pwm, "void set_pump_speed_pid(float temp, bool soften)")
except ValueError as exc:
    errors.append(str(exc))
    pid_body = ""

try:
    soften_body = extract_function_body(pwm, "inline float pump_pid_soften_factor(float pwm)")
except ValueError as exc:
    errors.append(str(exc))
    soften_body = ""

try:
    water_pid_body = extract_function_body(
        read_text("mode_common.h"),
        "inline void mode_update_water_pump_pid(float acpBoostThreshold)",
    )
except ValueError as exc:
    errors.append(str(exc))
    water_pid_body = ""

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
            "return ACTUATOR_COMMAND_APPLIED;",
            "if (duty > 0 && wp_count < 10 && pump_started)",
            "wp_count++;",
            "return ACTUATOR_COMMAND_APPLIED;",
        ],
        errors,
    )

PID_HARNESS = r'''
#include <cmath>
#include <cstdio>
#include <cstdlib>

#define PWM_LOW_VALUE 10
#define constrain(amt, low, high) ((amt) < (low) ? (low) : ((amt) > (high) ? (high) : (amt)))

struct SetupStub { float SetWaterTemp; } SamSetup = {30.0f};
struct RegulatorStub {
  float setpoint; float input;
  float getResultNow() { return 555.0f; }
} pump_regulator = {0.0f, 0.0f};
static bool pump_started = true;
static int wp_count = 10;
static float water_pump_speed = 100.0f;
static float writtenDuty = -1.0f;
void set_pump_pwm(float duty) { writtenDuty = duty; }

inline float pump_pid_soften_factor(float pwm) {
@SOFTEN_BODY@
}

void set_pump_speed_pid(float temp, bool soften) {
@PID_BODY@
}

static void check(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

static bool near(float a, float b) { return std::fabs(a - b) < 0.001f; }

int main() {
  check(near(pump_pid_soften_factor(1023.0f), 1.0f), "full PWM must keep the 6.27 regulator");
  check(near(pump_pid_soften_factor(390.0f), 1.0f), "PWM from 390 up must keep the 6.27 regulator");
  check(near(pump_pid_soften_factor(100.0f), 60.0f / 350.0f), "minimum PWM must soften the regulator");
  check(near(pump_pid_soften_factor(0.0f), 0.15f), "soften factor must not drop below 0.15");
  check(pump_pid_soften_factor(200.0f) > pump_pid_soften_factor(150.0f),
        "soften factor must grow with PWM");

  set_pump_speed_pid(32.0f, true);
  check(near(pump_regulator.setpoint, 30.0f), "setpoint must follow SetWaterTemp");
  check(near(pump_regulator.input, 30.0f + 2.0f * 60.0f / 350.0f),
        "low PWM must soften the water temperature deviation");
  check(near(writtenDuty, 555.0f), "PID result must reach set_pump_pwm");

  set_pump_speed_pid(33.0f, false);
  check(near(pump_regulator.input, 33.0f), "hot ACP substitute must reach the regulator unchanged");

  wp_count = 9;
  set_pump_speed_pid(32.0f, true);
  check(near(pump_regulator.input, 32.0f), "soft start must keep the 6.27 regulator input");
  wp_count = 10;

  pump_started = false;
  set_pump_speed_pid(32.0f, true);
  check(near(pump_regulator.input, 32.0f), "stopped pump must keep the 6.27 regulator input");
  pump_started = true;

  water_pump_speed = 800.0f;
  set_pump_speed_pid(32.0f, true);
  check(near(pump_regulator.input, 32.0f), "high PWM must keep the 6.27 regulator input");
  return 0;
}
'''


def run_pid_harness(source_text: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "pump_pid_test.cpp"
        binary = Path(temp_dir) / "pump_pid_test"
        source.write_text(source_text, encoding="utf-8")
        built = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            text=True, capture_output=True,
        )
        if built.returncode != 0:
            return built, None
        return built, subprocess.run([str(binary)], text=True, capture_output=True)


if pid_body and soften_body:
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
    harness = PID_HARNESS.replace("@SOFTEN_BODY@", soften_body).replace("@PID_BODY@", pid_body)
    built, ran = run_pid_harness(harness)
    if built.returncode != 0:
        errors.append("pump PID harness compile failed:\n" + built.stderr)
    elif ran is None or ran.returncode != 0:
        errors.append("pump PID harness failed:\n" + (ran.stderr if ran else "not run"))

    pid_mutations = (
        ("ACP substitute softened", "if (soften &&", "if ((soften || true) &&",
         "hot ACP substitute must reach the regulator unchanged"),
        ("soft start softened", "wp_count >= 10", "wp_count >= 0",
         "soft start must keep the 6.27 regulator input"),
        ("stopped pump softened", "&& pump_started &&", "&& (pump_started || true) &&",
         "stopped pump must keep the 6.27 regulator input"),
        ("softening removed", "pump_pid_soften_factor(water_pump_speed)", "1.0f",
         "low PWM must soften the water temperature deviation"),
        ("softening reaches high PWM", "+ 60.0f) / 350.0f", "+ 60.0f) / 3500.0f",
         "full PWM must keep the 6.27 regulator"),
        ("soften floor removed", ", 0.15f, 1.0f)", ", 0.0f, 1.0f)",
         "soften factor must not drop below 0.15"),
    )
    for name, old, new, expected_failure in pid_mutations:
        if harness.count(old) != 1:
            errors.append(f"pump PID mutation {name}: token is not unique: {old}")
            continue
        built, ran = run_pid_harness(harness.replace(old, new))
        if built.returncode != 0:
            errors.append(f"pump PID mutation {name} did not compile:\n{built.stderr}")
        elif ran is None or ran.returncode == 0 or expected_failure not in ran.stderr:
            errors.append(f"pump PID mutation {name} was not rejected by {expected_failure}")

if water_pid_body:
    # Пороги ТСА и подстановка "уставка + 3" - как в 6.27; смягчение в этой ветке выключено.
    require_ordered_tokens(
        "hot ACP branch bypasses softening",
        strip_cpp_comments(water_pid_body),
        [
            "if (!valve_status) return;",
            "ACPSensor.avgTemp > acpBoostThreshold && ACPSensor.avgTemp > WaterSensor.avgTemp",
            "set_pump_speed_pid(SamSetup.SetWaterTemp + 3, false);",
            "} else {",
            "set_pump_speed_pid(WaterSensor.avgTemp);",
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
            "if (!coolingOpenedThisTick && valve_status && pump_started && wp_count <= 10)",
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
    # handleSave стейджит SetWaterTemp через общую таблицу kSaveFloatFields (generic-цикл),
    # а не построчным apply_save_float_arg(..., "SetWaterTemp", ...). Проверяем и цикл,
    # и сам инициализатор поля в таблице.
    require_token(
        "handleSave staged SetWaterTemp",
        handle_save_body,
        "for (const SaveFloatField &f : kSaveFloatFields)",
    )
    if '{"SetWaterTemp", &SetupEEPROM::SetWaterTemp, 0.0f, 150.0f}' not in web:
        errors.append("kSaveFloatFields missing the SetWaterTemp entry")

if errors:
    print("pump PWM nonblocking smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("pump PWM nonblocking smoke passed")
