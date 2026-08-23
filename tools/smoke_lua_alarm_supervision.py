#!/usr/bin/env python3
"""[P8] Static checks for Lua alarm supervision (check_alarm_lua).

Pins:
- lua.h::check_alarm_lua treats water/ACP/tank sensors as OPTIONAL (Lua scripts
  decide which sensors they need) and calls the three mode_common.h helpers.
- mode_registry.h's LUA row wires the alarm slot to SAMOVAR_LUA_ALARM_FN, not nullptr.
- samovar_api.h defines SAMOVAR_LUA_ALARM_FN in both the USE_LUA and non-USE_LUA branches.
"""
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


def forbid_token(name: str, body: str, token: str) -> None:
    if token in body:
        errors.append(f"{name} contains forbidden token: {token}")


lua = strip_cpp_comments(read_text("lua.h"))
mode_registry = strip_cpp_comments(read_text("mode_registry.h"))
api = strip_cpp_comments(read_text("samovar_api.h"))
mode_common = strip_cpp_comments(read_text("mode_common.h"))

# --- [П3] mode_common.h::mode_request_overheat_emergency_if_needed ------------------------
# Тот же разрыв, что и в check_alarm_lua: без Lua-флага отсечка по перегреву не
# сработает, если Lua греет каналом мимо PowerOn.
if mode_common:
    try:
        overheat_body = extract_function_body(
            mode_common, "inline void mode_request_overheat_emergency_if_needed()"
        )
    except ValueError as exc:
        errors.append(str(exc))
        overheat_body = ""
    if overheat_body:
        require_token(
            "mode_common.h overheat helper",
            overheat_body,
            "&& (PowerOn || lua_heater_channel_raised())",
        )
    require_token(
        "mode_common.h",
        mode_common,
        "#ifndef USE_LUA\ninline bool lua_heater_channel_raised() { return false; }\n#endif",
    )

# --- lua.h::check_alarm_lua body checks -------------------------------------------------
if lua:
    try:
        check_alarm_lua = extract_function_body(lua, "inline void check_alarm_lua()")
    except ValueError as exc:
        errors.append(str(exc))
        check_alarm_lua = ""

    if check_alarm_lua:
        require_ordered_tokens(
            "check_alarm_lua",
            check_alarm_lua,
            [
                "mode_clear_alarm_pause_if_expired();",
                "if (PowerOn || lua_heater_channel_raised())",
                'optional_sensor_failed(WaterSensor) && process_sensor_failed("Lua", "воды")',
                'optional_sensor_failed(ACPSensor) && process_sensor_failed("Lua", "ТСА")',
                'optional_sensor_failed(TankSensor) && process_sensor_failed("Lua", "куба")',
                "mode_request_overheat_emergency_if_needed();",
                "mode_request_water_flow_emergency_if_needed();",
            ],
            errors,
        )
        # ALL three sensors must be optional - Lua scripts decide which sensors they need.
        # A hard sensor_valid(...) requirement on any of them would stall the mode whenever
        # a script that doesn't use that sensor runs on hardware without it wired up.
        forbid_token("check_alarm_lua", check_alarm_lua, "sensor_valid(WaterSensor)")
        forbid_token("check_alarm_lua", check_alarm_lua, "sensor_valid(ACPSensor)")
        forbid_token("check_alarm_lua", check_alarm_lua, "sensor_valid(TankSensor)")
        require_token(
            "check_alarm_lua",
            check_alarm_lua,
            "#ifdef SAMOVAR_USE_POWER",
        )
        require_token("check_alarm_lua", check_alarm_lua, "check_power_error();")

# --- mode_registry.h LUA row --------------------------------------------------------------
# Field positions in a table row are read by NAME (via the real member order of
# struct ModeOps), not by a hardcoded count/index - mode_registry.h grew from 12 to
# 16 fields (tick/stopProcess/buildAvailable/unavailableReason appended) and a
# position-pinned check silently breaks (or worse, silently reads the wrong field)
# every time the struct grows again. This check self-adjusts.
def parse_modeops_field_names(source: str) -> list[str]:
    """Ordered member names of struct ModeOps, as declared in mode_registry.h."""
    match = re.search(r"struct\s+ModeOps\s*\{", source)
    if match is None:
        raise ValueError("mode_registry.h: struct ModeOps not found")
    start = match.end()
    end = source.find("};", start)
    if end < 0:
        raise ValueError("mode_registry.h: struct ModeOps closing '};' not found")
    names = []
    for stmt in source[start:end].split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", stmt)
        if not m:
            raise ValueError(f"mode_registry.h: struct ModeOps: cannot parse member from {stmt!r}")
        names.append(m.group(1))
    return names


if mode_registry:
    lua_row_token = '{SAMOVAR_LUA_MODE,'
    row_start = mode_registry.find(lua_row_token)
    if row_start < 0:
        errors.append("mode_registry.h: SAMOVAR_LUA_MODE row not found")
    else:
        try:
            field_names = parse_modeops_field_names(mode_registry)
        except ValueError as exc:
            errors.append(str(exc))
            field_names = []
        row_end = mode_registry.find("},", row_start)
        row = mode_registry[row_start:row_end + 1]
        require_token("mode_registry.h LUA row", row, "SAMOVAR_LUA_ALARM_FN")
        fields = [f.strip() for f in row.strip("{}").rstrip(",").split(",")]
        if field_names and len(fields) != len(field_names):
            errors.append(
                f"mode_registry.h LUA row: expected {len(field_names)} fields (per struct "
                f"ModeOps), found {len(fields)}: {row}"
            )
        elif field_names:
            row_fields = dict(zip(field_names, fields))
            if row_fields["alarm"] != "SAMOVAR_LUA_ALARM_FN":
                errors.append(
                    "mode_registry.h LUA row: alarm field must be SAMOVAR_LUA_ALARM_FN, "
                    f"got {row_fields['alarm']}"
                )
            # finish/status must be left untouched (nullptr).
            if row_fields["finish"] != "nullptr" or row_fields["status"] != "nullptr":
                errors.append(
                    "mode_registry.h LUA row: finish/status fields must remain nullptr "
                    f"(got finish={row_fields['finish']!r}, status={row_fields['status']!r})"
                )
            # buttonPressAction/startBusyName must stay nullptr:
            # режим Lua не обслуживает основную кнопку.
            if row_fields["buttonPressAction"] != "nullptr" or row_fields["startBusyName"] != "nullptr":
                errors.append(
                    "mode_registry.h LUA row: buttonPressAction/startBusyName must remain nullptr "
                    f"(got buttonPressAction={row_fields['buttonPressAction']!r}, "
                    f"startBusyName={row_fields['startBusyName']!r})"
                )

# --- samovar_api.h macro definitions -------------------------------------------------------
if api:
    require_token("samovar_api.h", api, "#define SAMOVAR_LUA_ALARM_FN check_alarm_lua")
    require_token("samovar_api.h", api, "#define SAMOVAR_LUA_ALARM_FN nullptr")
    require_token("samovar_api.h", api, "inline void check_alarm_lua();")
    require_token("samovar_api.h", api, "inline void mode_clear_alarm_pause_if_expired();")
    require_token(
        "samovar_api.h", api, "inline void mode_request_overheat_emergency_if_needed();"
    )
    # mode_request_water_flow_emergency_if_needed already has an unconditional forward
    # declaration elsewhere in this file - it must NOT be duplicated inside the USE_LUA block.
    if api.count("inline void mode_request_water_flow_emergency_if_needed();") != 1:
        errors.append(
            "samovar_api.h: mode_request_water_flow_emergency_if_needed forward declaration "
            "must appear exactly once (must not be duplicated for USE_LUA)"
        )
    # Both #define branches for the macro must exist under proper guards.
    define_lua = api.find("#define SAMOVAR_LUA_ALARM_FN check_alarm_lua")
    define_else = api.find("#define SAMOVAR_LUA_ALARM_FN nullptr")
    guard_ifdef = api.rfind("#ifdef USE_LUA", 0, define_lua) if define_lua >= 0 else -1
    guard_else = api.find("#else", define_lua) if define_lua >= 0 else -1
    if not (
        define_lua >= 0
        and define_else >= 0
        and guard_ifdef >= 0
        and guard_ifdef < define_lua < guard_else < define_else
    ):
        errors.append(
            "samovar_api.h: SAMOVAR_LUA_ALARM_FN must be defined in both the #ifdef USE_LUA "
            "branch (check_alarm_lua) and the #else branch (nullptr)"
        )

# --- [П3] check_alarm_lua поведение: PowerOn=false, но Lua поднял heater-канал ------------
# Плановые сценарии: (a) канал поднят, PowerOn=false, датчик воды упал -> надзор
# срабатывает так же, как при PowerOn=true; (b) канал НЕ поднят, PowerOn=false,
# датчик воды упал -> надзор молчит (это старое, ожидаемое поведение вне Lua-режима).
HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

class String : public std::string {
 public:
  using std::string::operator=;
  String() = default;
  String(const char* value) : std::string(value ? value : "") {}
  String(const std::string& value) : std::string(value) {}
};
String operator+(const String& left, const char* right) {
  return String(static_cast<const std::string&>(left) + (right ? right : ""));
}

#define RELE_CHANNEL1 2
#define RELE_CHANNEL4 40

static bool PowerOn = false;

struct SensorMock { bool failed = false; };
static SensorMock WaterSensor;
static SensorMock ACPSensor;
static SensorMock TankSensor;
static bool optional_sensor_failed(const SensorMock& s) { return s.failed; }

static int processSensorFailedCalls = 0;
static const char* lastProcessSensorFailedWhat = "";
static bool process_sensor_failed(const char*, const char* what) {
  processSensorFailedCalls++;
  lastProcessSensorFailedWhat = what;
  return true;
}

static void mode_clear_alarm_pause_if_expired() {}
static void mode_request_overheat_emergency_if_needed() {}
static void mode_request_water_flow_emergency_if_needed() {}

static bool luaHeaterChannel1Raised = false;
static bool luaHeaterChannel4Raised = false;

@HEATER_RAISED_BODY@

@SET_HEATER_RAISED_BODY@

@CHECK_ALARM_LUA_BODY@

static int failures = 0;
static void check(bool cond, const char* msg) {
  if (!cond) { std::cerr << "FAIL: " << msg << "\n"; failures++; }
}

int main() {
  // (a) PowerOn=false, Lua поднял RELE_CHANNEL1, датчик воды упал -> надзор
  // обязан сработать (процесс отказа датчика вызван).
  PowerOn = false;
  lua_set_heater_channel_raised(RELE_CHANNEL1, true);
  WaterSensor.failed = true;
  processSensorFailedCalls = 0;
  check_alarm_lua();
  check(processSensorFailedCalls == 1,
        "PowerOn=false + Lua поднял канал + датчик воды упал: надзор обязан сработать");

  // (b) PowerOn=false, канал Lua НЕ поднят, тот же упавший датчик -> надзор
  // молчит (сценарий вне Lua-режима: датчик неопционален только под PowerOn).
  lua_set_heater_channel_raised(RELE_CHANNEL1, false);
  processSensorFailedCalls = 0;
  check_alarm_lua();
  check(processSensorFailedCalls == 0,
        "PowerOn=false + канал не поднят: надзор обязан промолчать (старое поведение)");

  WaterSensor.failed = false;

  if (failures != 0) return 1;
  std::cout << "Lua alarm supervision (PowerOn||lua_heater_channel_raised) behavior passed\n";
  return 0;
}
'''


def run_behavioral_checks() -> list[str]:
    behavior_errors: list[str] = []
    if not lua:
        return behavior_errors
    try:
        heater_raised_body = (
            "inline bool lua_heater_channel_raised() {\n"
            + extract_function_body(lua, "inline bool lua_heater_channel_raised()")
            + "\n}\n"
        )
        set_heater_raised_body = (
            "inline void lua_set_heater_channel_raised(int pin, bool raised) {\n"
            + extract_function_body(
                lua, "inline void lua_set_heater_channel_raised(int pin, bool raised)"
            )
            + "\n}\n"
        )
        check_alarm_lua_body = (
            "static void check_alarm_lua() {\n"
            + extract_function_body(lua, "inline void check_alarm_lua()")
            + "\n}\n"
        )
    except ValueError as exc:
        return [str(exc)]

    harness = HARNESS_TEMPLATE.replace("@HEATER_RAISED_BODY@", heater_raised_body)
    harness = harness.replace("@SET_HEATER_RAISED_BODY@", set_heater_raised_body)
    harness = harness.replace("@CHECK_ALARM_LUA_BODY@", check_alarm_lua_body)

    with tempfile.TemporaryDirectory(prefix="samovar-lua-alarm-supervision-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "check_alarm_lua_test.cpp"
        binary = temp / "check_alarm_lua_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compile_result.returncode != 0:
            behavior_errors.append(
                "check_alarm_lua behavioral harness failed to compile:\n"
                + compile_result.stdout + compile_result.stderr
            )
            return behavior_errors
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if run_result.returncode != 0:
            behavior_errors.append(
                "check_alarm_lua behavioral harness failed:\n" + run_result.stdout + run_result.stderr
            )
    return behavior_errors


errors.extend(run_behavioral_checks())

if errors:
    for err in errors:
        print(f"FAIL: {err}")
    sys.exit(1)

print("Lua alarm supervision smoke check passed")
sys.exit(0)
