#!/usr/bin/env python3
"""Проверяет неизменяемый снимок конфигурации НБК на всю сессию."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <set>
#include <string>

#define NBK_COLUMN_INERTIA_DEFAULT 180
#define NBK_OVERFLOW_PRESSURE_DEFAULT 40
#define NBK_TN_DEFAULT 98.5
#define NBK_DT_DEFAULT 0.5
#define NBK_DM_DEFAULT 100
#define NBK_DP_DEFAULT 0.5
#define NBK_TP_DEFAULT 81

struct SetupProbe {
  float NbkIn;
  float NbkDelta;
  float NbkTn;
  float NbkOwPress;
  float NbkDM;
  float NbkDP;
  float NbkSteamT;
  float MainsVoltage;
  float HeaterResistant;
};
static SetupProbe SamSetup = {};
static constexpr float CONTROL_HEATER_R_MIN = 2.0f;
static constexpr float CONTROL_HEATER_R_MAX = 65.0f;
static constexpr float CONTROL_HEATER_R_DEFAULT = 15.2f;
float trusted_heater_resistance(float value) {
  return std::isfinite(value) &&
             value >= CONTROL_HEATER_R_MIN &&
             value <= CONTROL_HEATER_R_MAX
      ? value
      : CONTROL_HEATER_R_DEFAULT;
}

struct NbkSessionConfig {
@STATE_BODY@
};
static NbkSessionConfig nbkSessionConfig = {};
static const char* nbkSessionConfigError = "";
static bool nbkHeaterResistanceInputValid = true;
static bool nbkMainsVoltageInputValid = true;
static bool nbkPreserveStartupInputValidity = false;

inline void nbk_preserve_startup_input_validity(
    float heaterResistance, float mainsVoltage) {
@PRESERVE_BODY@
}
inline void nbk_capture_runtime_input_validity(
    float heaterResistance, float mainsVoltage) {
@RUNTIME_BODY@
}

inline bool nbk_capture_session_config() {
@CAPTURE_BODY@
}
inline void nbk_clear_session_config() {
@CLEAR_BODY@
}
float toPower(float value) {
@TO_POWER_BODY@
}
float fromPower(float value) {
@FROM_POWER_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static bool near(float lhs, float rhs) {
  return std::fabs(lhs - rhs) < 0.001f;
}
static SetupProbe config_a() {
  return {210, 0.7f, 97.4f, 48, 120, 0.8f, 89, 220, 16};
}
static SetupProbe config_defaults() {
  // [SOLUTIONS_2026-08-24.md, Н1] заводские дефолты профиля (profile_setup_fields.h
  // подставляет сюда NBK_*_DEFAULT из nbk.h) - после сброса к заводским настройкам
  // старт НБК не должен отклоняться валидацией nbk_capture_session_config().
  return {NBK_COLUMN_INERTIA_DEFAULT, NBK_DT_DEFAULT, NBK_TN_DEFAULT,
          NBK_OVERFLOW_PRESSURE_DEFAULT, NBK_DM_DEFAULT, NBK_DP_DEFAULT,
          NBK_TP_DEFAULT, 230, CONTROL_HEATER_R_DEFAULT};
}
static SetupProbe config_b() {
  return {330, 0.9f, 96.8f, 55, 170, 1.2f, 95, 240, 20};
}
static void expect_rejected(SetupProbe invalid, const char* message, const char* expectedReasonSubstring) {
  SamSetup = config_a();
  check(nbk_capture_session_config(), "valid baseline должен фиксироваться");
  SamSetup = invalid;
  check(!nbk_capture_session_config() && !nbkSessionConfig.valid, message);
  const std::string reason = nbkSessionConfigError;
  check(reason.find(expectedReasonSubstring) != std::string::npos,
        (std::string(message) + ": nbkSessionConfigError должен называть конкретное поле").c_str());
}

int main() {
  SamSetup = config_a();
  check(nbk_capture_session_config(), "первая валидная конфигурация должна фиксироваться");
  check(nbkSessionConfig.valid &&
            nbkSessionConfig.columnInertia == 210 &&
            near(nbkSessionConfig.deltaT, 0.7f) &&
            near(nbkSessionConfig.tankTemp, 97.4f) &&
            near(nbkSessionConfig.overflowPressure, 48) &&
            near(nbkSessionConfig.deltaPower, 120) &&
            near(nbkSessionConfig.deltaFeed, 0.8f) &&
            near(nbkSessionConfig.steamTempLimit, 89) &&
            near(nbkSessionConfig.mainsVoltage, 220) &&
            near(nbkSessionConfig.heaterResistance, 16) &&
            near(nbkSessionConfig.maxPower, 3025),
        "snapshot A должен содержать все параметры расчёта НБК");
  const float powerA = toPower(200);
  const float voltageA = fromPower(625);

  SamSetup = config_b();
  check(nbkSessionConfig.columnInertia == 210 &&
            near(nbkSessionConfig.deltaT, 0.7f) &&
            near(nbkSessionConfig.tankTemp, 97.4f) &&
            near(nbkSessionConfig.mainsVoltage, 220) &&
            near(nbkSessionConfig.heaterResistance, 16),
        "изменение SamSetup внутри сессии не должно менять snapshot");
  check(near(toPower(200), powerA) && near(fromPower(625), voltageA),
        "конверсия H/S/O/W должна использовать snapshot, а не живой SamSetup");

  nbk_clear_session_config();
  check(!nbkSessionConfig.valid, "clear обязан инвалидировать snapshot");
  check(nbk_capture_session_config(), "вторая валидная конфигурация должна фиксироваться");
  check(nbkSessionConfig.columnInertia == 330 &&
            near(nbkSessionConfig.deltaT, 0.9f) &&
            near(nbkSessionConfig.tankTemp, 96.8f) &&
            near(nbkSessionConfig.overflowPressure, 55) &&
            near(nbkSessionConfig.deltaPower, 170) &&
            near(nbkSessionConfig.deltaFeed, 1.2f) &&
            near(nbkSessionConfig.steamTempLimit, 95) &&
            near(nbkSessionConfig.mainsVoltage, 240) &&
            near(nbkSessionConfig.heaterResistance, 20) &&
            near(nbkSessionConfig.maxPower, 2880),
        "следующая сессия должна получить независимый snapshot B");

  SetupProbe invalid = config_a();
  invalid.NbkIn = 1;
  expect_rejected(invalid, "NbkIn<=1 должен отклонять старт", "инерция колонны");
  invalid = config_a(); invalid.NbkDelta = 0;
  expect_rejected(invalid, "NbkDelta<=0 должен отклонять старт", "поправка dT");
  invalid = config_a(); invalid.NbkTn = 0;
  expect_rejected(invalid, "NbkTn<=0 должен отклонять старт", "температура куба");
  invalid = config_a(); invalid.NbkOwPress = 1;
  expect_rejected(invalid, "NbkOwPress<=1 должен отклонять старт", "давление захлёба");
  invalid = config_a(); invalid.NbkDM = 1;
  expect_rejected(invalid, "NbkDM<=1 должен отклонять старт", "шаг мощности");
  invalid = config_a(); invalid.NbkDP = 0;
  expect_rejected(invalid, "NbkDP<=0 должен отклонять старт", "шаг подачи");
  invalid = config_a(); invalid.NbkSteamT = 80;
  expect_rejected(invalid, "NbkSteamT<=80 должен отклонять старт", "температуры пара");
  invalid = config_a(); invalid.NbkSteamT = 98;
  expect_rejected(invalid, "NbkSteamT>97 должен отклонять старт без clamp", "температуры пара");
  invalid = config_a(); invalid.MainsVoltage = 0;
  expect_rejected(invalid, "MainsVoltage<=0 должен отклонять старт", "напряжение сети вне диапазона");
  invalid = config_a(); invalid.MainsVoltage = 1000;
  expect_rejected(invalid, "повреждённый MainsVoltage не должен подменяться 230В", "напряжение сети вне диапазона");
  invalid = config_a(); invalid.HeaterResistant = 1;
  expect_rejected(invalid, "недоверенное HeaterResistance должно отклонять старт", "сопротивление ТЭНа вне диапазона");
  invalid = config_a(); invalid.HeaterResistant = 66;
  expect_rejected(invalid, "слишком большое HeaterResistance должно отклонять старт без default", "сопротивление ТЭНа вне диапазона");
  invalid = config_a(); invalid.HeaterResistant = std::numeric_limits<float>::quiet_NaN();
  expect_rejected(invalid, "NaN HeaterResistance должен отклонять старт без default", "сопротивление ТЭНа вне диапазона");

  // [П70в] РАЗНЫЕ поля обязаны давать РАЗНЫЙ текст причины (не общее "плохая
  // конфигурация НБК") - иначе field-specific сообщение не выполняет свою задачу.
  {
    auto capture_reason = [](SetupProbe broken) -> std::string {
      SamSetup = config_a();
      nbk_capture_session_config();
      SamSetup = broken;
      nbk_capture_session_config();
      return nbkSessionConfigError;
    };
    std::set<std::string> distinctReasons;
    SetupProbe c;
    c = config_a(); c.NbkIn = 1; distinctReasons.insert(capture_reason(c));
    c = config_a(); c.NbkDelta = 0; distinctReasons.insert(capture_reason(c));
    c = config_a(); c.NbkTn = 0; distinctReasons.insert(capture_reason(c));
    c = config_a(); c.NbkOwPress = 1; distinctReasons.insert(capture_reason(c));
    c = config_a(); c.NbkDM = 1; distinctReasons.insert(capture_reason(c));
    c = config_a(); c.NbkDP = 0; distinctReasons.insert(capture_reason(c));
    c = config_a(); c.NbkSteamT = 80; distinctReasons.insert(capture_reason(c));
    c = config_a(); c.MainsVoltage = 0; distinctReasons.insert(capture_reason(c));
    c = config_a(); c.HeaterResistant = 1; distinctReasons.insert(capture_reason(c));
    check(distinctReasons.size() == 9,
          "разные поля обязаны давать РАЗНЫЙ текст причины отказа (нашли меньше 9 уникальных)");
  }

  SamSetup = config_a();
  nbk_preserve_startup_input_validity(1, 230);
  SamSetup.HeaterResistant = 16;
  check(!nbk_capture_session_config(),
        "метка битого сопротивления должна блокировать НБК отдельно от сети");
  nbk_preserve_startup_input_validity(16, 0);
  SamSetup.MainsVoltage = 230;
  check(!nbk_capture_session_config(),
        "метка битой сети должна блокировать НБК отдельно от сопротивления");

  SamSetup = config_a();
  nbk_preserve_startup_input_validity(1, 0);
  SamSetup.HeaterResistant = 16;
  SamSetup.MainsVoltage = 230;
  check(!nbk_capture_session_config(),
        "исходно битый профиль НБК должен отклоняться после общих boot-defaults");
  nbk_capture_runtime_input_validity(16, 230);
  check(!nbk_capture_session_config(),
        "первый runtime apply обязан сохранить метку исходной boot-ошибки");
  nbk_capture_runtime_input_validity(20, 240);
  SamSetup.HeaterResistant = 20;
  SamSetup.MainsVoltage = 240;
  check(nbk_capture_session_config(),
        "после явной корректировки оператором следующий старт НБК должен разрешаться");

  // [SOLUTIONS_2026-08-24.md, Н1] заводские дефолты (NBK_*_DEFAULT) обязаны
  // сами по себе проходить валидацию старта НБК - это доказывает не только
  // "байты совпадают" (golden в smoke_profile_store.py), а что НБК реально
  // стартует после сброса к заводским настройкам.
  SamSetup = config_defaults();
  nbk_capture_runtime_input_validity(SamSetup.HeaterResistant, SamSetup.MainsVoltage);
  check(nbk_capture_session_config(),
        "заводские дефолты NBK_*_DEFAULT должны проходить валидацию старта НБК");
  return failures == 0 ? 0 : 1;
}
'''

START_ROUTE_HARNESS = r'''
#include <cstdint>
#include <iostream>

enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};
static constexpr int16_t SAMOVAR_STARTVAL_IDLE = 0;
static constexpr int16_t SAMOVAR_STARTVAL_NBK_START = 4000;
static constexpr int16_t SAMOVAR_STARTVAL_NBK_RUNNING = 4001;

static bool nbk_safe_waiting = false;
static bool nbk_safe_wait_feed_stopped = false;
static ActuatorCommandResult nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
static int16_t startval = SAMOVAR_STARTVAL_IDLE;
static ActuatorCommandResult tickResult = ACTUATOR_COMMAND_FAILED;
static int tickCalls = 0;
static int captureCalls = 0;
struct CommandProbe { bool active; };
static CommandProbe nbkActuatorCommand = {false};

static void tick_nbk_safe_wait() {
  tickCalls++;
  nbk_safe_wait_result = tickResult;
}
static void tick_nbk_actuator_command() {}
static void run_nbk_program(uint8_t num) {
  if (num == 0) captureCalls++;
  startval = SAMOVAR_STARTVAL_NBK_RUNNING;
}
static void nbk_proc_start_route() {
@PROC_START_PREFIX@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}
static void reset(ActuatorCommandResult result, int16_t requestedStart) {
  nbk_safe_waiting = true;
  nbk_safe_wait_feed_stopped = true;
  nbk_safe_wait_result = ACTUATOR_COMMAND_FAILED;
  startval = requestedStart;
  tickResult = result;
  tickCalls = 0;
  captureCalls = 0;
}

int main() {
  reset(ACTUATOR_COMMAND_APPLIED, SAMOVAR_STARTVAL_NBK_START);
  nbk_proc_start_route();
  check(tickCalls == 1 && captureCalls == 1,
        "APPLIED safe-stop обязан возобновить capture/start ровно один раз");
  check(!nbk_safe_waiting && !nbk_safe_wait_feed_stopped &&
            nbk_safe_wait_result == ACTUATOR_COMMAND_FAILED &&
            startval == SAMOVAR_STARTVAL_NBK_RUNNING,
        "APPLIED safe-stop обязан очистить wait-state перед запуском");

  reset(ACTUATOR_COMMAND_PENDING, SAMOVAR_STARTVAL_NBK_START);
  nbk_proc_start_route();
  check(tickCalls == 1 && captureCalls == 0 && nbk_safe_waiting &&
            startval == SAMOVAR_STARTVAL_NBK_START,
        "PENDING safe-stop не должен запускать НБК или очищать wait-state");

  reset(ACTUATOR_COMMAND_FAILED, SAMOVAR_STARTVAL_NBK_START);
  nbk_proc_start_route();
  check(tickCalls == 1 && captureCalls == 0 && nbk_safe_waiting &&
            startval == SAMOVAR_STARTVAL_NBK_START,
        "FAILED safe-stop не должен запускать НБК или очищать wait-state");

  reset(ACTUATOR_COMMAND_APPLIED, SAMOVAR_STARTVAL_NBK_RUNNING);
  nbk_proc_start_route();
  check(tickCalls == 1 && captureCalls == 0 && nbk_safe_waiting,
        "APPLIED без повторной START-команды не должен покидать safe-wait");
  return failures == 0 ? 0 : 1;
}
'''


def build(source: str) -> str:
    state, _ = extract_braced_block_after(source, "struct NbkSessionConfig {")
    capture = extract_function_body(source, "inline bool nbk_capture_session_config() {")
    preserve = extract_function_body(
        source,
        "inline void nbk_preserve_startup_input_validity(\n    float heaterResistance, float mainsVoltage) {",
    )
    runtime = extract_function_body(
        source,
        "inline void nbk_capture_runtime_input_validity(\n    float heaterResistance, float mainsVoltage) {",
    )
    clear = extract_function_body(source, "inline void nbk_clear_session_config() {")
    to_power = extract_function_body(source, "float toPower(float value) {")
    from_power = extract_function_body(source, "float fromPower(float value) {")
    replacements = {
        "@STATE_BODY@": state,
        "@CAPTURE_BODY@": capture,
        "@PRESERVE_BODY@": preserve,
        "@RUNTIME_BODY@": runtime,
        "@CLEAR_BODY@": clear,
        "@TO_POWER_BODY@": to_power,
        "@FROM_POWER_BODY@": from_power,
    }
    harness = HARNESS
    for token, value in replacements.items():
        harness = harness.replace(token, value.replace("\r\n", "\n"))
    return harness


def build_start_route(source: str) -> str:
    proc = extract_function_body(source, "void nbk_proc()")
    snapshot_guard = "  if (!nbkSessionConfig.valid)"
    if snapshot_guard not in proc:
        raise ValueError("nbk_proc snapshot guard not found")
    prefix = proc[: proc.index(snapshot_guard)]
    return START_ROUTE_HARNESS.replace(
        "@PROC_START_PREFIX@", prefix.replace("\r\n", "\n")
    )


def run_start_route(source: str, emit: bool) -> int:
    try:
        harness = build_start_route(source)
    except ValueError as error:
        if emit:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-start-route-") as temp_dir:
        temp = Path(temp_dir)
        cpp = temp / "test.cpp"
        binary = temp / "test"
        cpp.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode:
            if emit:
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
        return result.returncode


def run(source: str, emit: bool) -> int:
    try:
        harness = build(source)
    except ValueError as error:
        if emit:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-session-config-") as temp_dir:
        temp = Path(temp_dir)
        cpp = temp / "test.cpp"
        binary = temp / "test"
        cpp.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode:
            if emit:
                sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if emit:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
        return result.returncode


def nbk_start_route_errors(source: str) -> list[str]:
    errors = []
    try:
        proc = extract_function_body(source, "void nbk_proc()")
        start_branch = (
            "if (startval == SAMOVAR_STARTVAL_NBK_START) {\n"
            "    run_nbk_program(0);\n"
            "    return;\n"
            "  }"
        )
        snapshot_guard = "if (!nbkSessionConfig.valid)"
        if start_branch not in proc or snapshot_guard not in proc:
            errors.append("nbk_proc не содержит стартовую ветку и guard snapshot")
        elif proc.index(start_branch) > proc.index(snapshot_guard):
            errors.append("старт НБК блокируется до захвата snapshot")

        run_program = extract_function_body(
            source, "void run_nbk_program(uint8_t num, bool workConfirmed) {"
        )
        capture = "if (!nbk_capture_session_config())"
        running = "if (num == 0 && startval == SAMOVAR_STARTVAL_NBK_START)"
        if capture not in run_program or running not in run_program:
            errors.append("run_nbk_program не фиксирует snapshot или не переводит старт в running")
        elif run_program.index(capture) > run_program.index(running):
            errors.append("НБК переходит в running до захвата snapshot")
    except ValueError as error:
        errors.append(str(error))
    return errors


def check_production_start_route(source: str) -> list[str]:
    errors = nbk_start_route_errors(source)
    registry = (ROOT / "mode_registry.h").read_text(encoding="utf-8")
    samovar = (ROOT / "Samovar.h").read_text(encoding="utf-8")
    try:
        start_command = extract_function_body(
            registry, "inline bool mode_apply_power_on_command(SamovarCommands command) {"
        )
    except ValueError as error:
        return errors + [str(error)]

    required_registry_tokens = (
        # [T40 А3] Между startvalRangeHigh и pagePath добавились statusRangeLow/High
        # (границы SamovarStatusInt для mode_status_belongs) - см. ModeOps в mode_registry.h.
        "{SAMOVAR_NBK_MODE, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK + 1000, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK + 1, \"/nbk.htm\", SAMOVAR_NBK",
        "SamovarStatusInt = ops->activeStatus;",
        "startval = ops->activeStatus;",
    )
    for token in required_registry_tokens:
        if token not in registry and token not in start_command:
            errors.append(f"командный маршрут НБК потерял {token}")
    if (
        "SamovarStatusInt = ops->activeStatus;" in start_command
        and "startval = ops->activeStatus;" in start_command
        and start_command.index("SamovarStatusInt = ops->activeStatus;")
        > start_command.index("startval = ops->activeStatus;")
    ):
        errors.append("командный маршрут НБК записывает startval раньше activeStatus")
    required_constants = (
        "constexpr int16_t SAMOVAR_STATUS_NBK               = 4000;",
        "constexpr int16_t SAMOVAR_STARTVAL_NBK_START      = 4000;",
        "constexpr int16_t SAMOVAR_STARTVAL_NBK_RUNNING    = 4001;",
    )
    for token in required_constants:
        if token not in samovar:
            errors.append(f"публичный контракт НБК потерял {token}")
    return errors


def main() -> int:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    if run(source, True) != 0:
        return 1
    if run_start_route(source, True) != 0:
        return 1

    route_errors = check_production_start_route(source)
    if route_errors:
        for error in route_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    function_names = (
        "void handle_nbk_stage_heatup() {",
        "void handle_nbk_stage_manual() {",
        "void handle_nbk_stage_optimization() {",
        "void handle_nbk_stage_work() {",
        "void run_nbk_program(uint8_t num, bool workConfirmed) {",
    )
    for signature in function_names:
        try:
            body = extract_function_body(source, signature)
        except ValueError as error:
            print(f"FAIL: {error}", file=sys.stderr)
            return 1
        for forbidden in (
            "SamSetup.Nbk",
            "SamSetup.MainsVoltage",
            "SamSetup.HeaterResistant",
        ):
            if forbidden in body:
                print(
                    f"FAIL: {signature} читает {forbidden} мимо snapshot",
                    file=sys.stderr,
                )
                return 1

    validation_terms = (
        "SamSetup.NbkIn > 1",
        "SamSetup.NbkDelta > 0",
        "SamSetup.NbkTn > 0",
        "SamSetup.NbkOwPress > 1",
        "SamSetup.NbkDM > 1",
        "SamSetup.NbkDP > 0",
        "SamSetup.NbkSteamT > 80",
        "SamSetup.NbkSteamT <= 97",
        "SamSetup.MainsVoltage > 0",
        "SamSetup.MainsVoltage < 1000",
        "heaterResistance >= CONTROL_HEATER_R_MIN",
        "heaterResistance <= CONTROL_HEATER_R_MAX",
        "nbkMainsVoltageInputValid",
        "nbkHeaterResistanceInputValid",
    )
    def remove_last_validation_term(term: str) -> str:
        index = source.rfind(term)
        if index < 0:
            return source
        return source[:index] + "true" + source[index + len(term):]

    mutations = [remove_last_validation_term(term) for term in validation_terms]
    mutations.extend((
        source.replace(
            "const float R = nbkSessionConfig.heaterResistance;",
            "const float R = SamSetup.HeaterResistant;",
            1,
        ),
        source.replace(
            "return sqrtf(value * nbkSessionConfig.heaterResistance);",
            "return sqrtf(value * SamSetup.HeaterResistant);",
            1,
        ),
    ))
    if any(mutation == source for mutation in mutations):
        print("FAIL: snapshot mutation anchor missing", file=sys.stderr)
        return 1
    for mutation in mutations:
        if run(mutation, False) == 0:
            print("FAIL: snapshot mutation survived", file=sys.stderr)
            return 1

    start_branch = (
        "  if (startval == SAMOVAR_STARTVAL_NBK_START) {\n"
        "    run_nbk_program(0);\n"
        "    return;\n"
        "  }\n"
    )
    snapshot_guard = (
        "  if (!nbkSessionConfig.valid) {\n"
        "    nbk_enter_safe_wait(\"Конфигурация сессии НБК не зафиксирована.\");\n"
        "    return;\n"
        "  }\n"
    )
    reordered = source.replace(
        start_branch + snapshot_guard, snapshot_guard + start_branch, 1
    )
    if reordered == source:
        print("FAIL: start-route mutation anchor missing", file=sys.stderr)
        return 1
    if not nbk_start_route_errors(reordered):
        print("FAIL: NBK start-route mutation survived", file=sys.stderr)
        return 1

    unsafe_resume = source.replace(
        "nbk_safe_wait_result != ACTUATOR_COMMAND_APPLIED",
        "false",
        1,
    )
    if unsafe_resume == source:
        print("FAIL: safe-wait resume mutation anchor missing", file=sys.stderr)
        return 1
    if run_start_route(unsafe_resume, False) == 0:
        print("FAIL: unsafe safe-wait resume mutation survived", file=sys.stderr)
        return 1
    print("nbk session snapshot and production start-route checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
