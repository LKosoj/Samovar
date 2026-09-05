#!/usr/bin/env python3
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_source(name: str) -> str:
    path = ROOT / name
    if not path.is_file():
        errors.append(f"{name} not found")
        return ""
    return strip_cpp_comments(path.read_text(encoding="utf-8", errors="ignore"))


def function_body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as error:
        errors.append(str(error))
        return ""


def require(name: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token not in source:
            errors.append(f"{name} missing token: {token}")


def forbid(name: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token in source:
            errors.append(f"{name} contains forbidden token: {token}")


power = read_source("power_regulator.h")
alarm = read_source("alarm.h")
mode_common = read_source("mode_common.h")
mode_registry = read_source("mode_registry.h")
selftest = read_source("selftest.h")
nbk = read_source("nbk.h")
samovar = read_source("Samovar.ino")
samovar_header = read_source("Samovar.h")
menu = read_source("Menu.ino")
webserver = read_source("WebServer.ino")
mode_switch = read_source("mode_switch.h")
beer = read_source("beer.h")
distiller = read_source("distiller.h")
bk = read_source("BK.h")
lua = read_source("lua.h")
rmvk = read_source("mod_rmv.ino")
rmvk_header = read_source("mod_rmvk.h")
platformio = read_source("platformio.ini")
ini = read_source("Samovar_ini.h")
command_queue = read_source("samovar_command_queue.h")
blynk = read_source("Blynk.ino")
ci = read_source(".github/workflows/firmware-ci.yml")
safety_transition_source = read_source("safety_transition.h")

# The mode-switch barrier must always be releasable: SAFETY_MODE_SWITCH_FAILED was a
# terminal dead phase with no way back to IDLE except a reboot. It must never come back.
for name, source in (
    ("safety_transition.h", safety_transition_source),
    ("WebServer.ino", webserver),
    ("mode_switch.h", mode_switch),
):
    forbid(
        name,
        source,
        ("SAFETY_MODE_SWITCH_FAILED", "safety_mode_switch_fail(", "safety_mode_switch_failed("),
    )

# Loop-driven state machines must remain non-blocking. The regulator worker owns
# protocol waits; the emergency button has its own high-priority task.
blocking_tokens = (
    "delay(",
    "vTaskDelay(",
    "xSemaphoreTake(",
    "Serial2.",
    "RMVK_",
    "apply_regulator_",
)
for signature, source in (
    ("inline void tick_power_transition", power),
    ("inline ActuatorCommandResult set_power(bool On, bool enqueueResetCommand)", power),
    ("inline ActuatorCommandResult set_current_power", power),
    ("inline void set_power_mode", power),
    ("inline ModeHeatingStartResult mode_tick_heating_session", mode_common),
    ("inline void tick_self_test", selftest),
    ("inline void tick_nbk_transition", nbk),
):
    forbid(signature, function_body(source, signature), blocking_tokens)

# All energizing UART writes carry the heater epoch into one bounded commit.
uart_enqueue = function_body(power, "inline bool heater_uart_enqueue")
require_ordered_tokens(
    "heater UART enqueue",
    uart_enqueue,
    [
        "uart_wait_tx_done",
        "portENTER_CRITICAL(&emergencyStopMux)",
        "safety_uart_commit_locked",
        "portEXIT_CRITICAL(&emergencyStopMux)",
    ],
    errors,
)
power_kvic = read_source("power_regulator_kvic.h")
power_rmvk = read_source("power_regulator_rmvk.h")
power_sem = read_source("power_regulator_sem.h")

# Epoch-carrying UART commit differs per backend: KVIC/SEM still funnel through
# heater_uart_enqueue (SEM via sem_avr_write_samovar_command, which wraps it in the
# same file); RMVK-only calls the RMVK_* protocol functions directly. Checking the
# combined pre-split text let dead KVIC text satisfy the RMVK-only build - see
# AGENTS.md "Инварианты, которые выглядят как дефект" note on this file.
backend_epoch_commit = {
    "power_regulator_kvic.h": (
        power_kvic,
        {
            "inline bool apply_regulator_mode_blocking": ("powerGeneration", "heater_uart_enqueue"),
            "inline bool apply_regulator_voltage_blocking": ("powerGeneration", "heater_uart_enqueue"),
        },
    ),
    "power_regulator_rmvk.h": (
        power_rmvk,
        {
            "inline bool apply_regulator_mode_blocking": ("powerGeneration", "RMVK_set_on"),
            "inline bool apply_regulator_voltage_blocking": ("powerGeneration", "RMVK_set_out_voltge"),
        },
    ),
    "power_regulator_sem.h": (
        power_sem,
        {
            "inline bool apply_regulator_mode_blocking": ("powerGeneration", "sem_avr_write_samovar_command"),
            "inline bool apply_regulator_voltage_blocking": ("powerGeneration", "sem_avr_write_samovar_command"),
        },
    ),
}
for label, (source, sig_map) in backend_epoch_commit.items():
    for signature, required_tokens in sig_map.items():
        body = function_body(source, signature)
        require(f"{label}: {signature}", body, required_tokens)
        forbid(f"{label}: {signature}", body, ("heater_safety_latched()", "Serial2.print"))

rmvk_cmd = function_body(rmvk, "uint8_t RMVK_cmd(")
require(
    "RMVK epoch commit",
    rmvk_cmd,
    ("powerGeneration", "heater_uart_enqueue", "energizing", "uart_read_bytes"),
)
forbid("RMVK epoch commit", rmvk_cmd, ("uart_write_bytes", "heater_safety_latched()"))
if "bool energizing =" in rmvk_header:
    errors.append("RMVK command must not hide an epoch-less default argument")
if not re.search(r"uart_driver_install\(RMVK_UART,\s*BUF_SIZE \* 2,\s*0,", rmvk):
    errors.append("RMVK UART must use the zero-sized TX buffer required by uart_tx_chars")

# The worker owns deadlines and every non-sleep failure is fail-closed. A failed
# SLEEP command is terminal and may not create an unbounded retry loop.
worker = function_body(power, "inline void process_pending_power_request")
require(
    "regulator worker",
    worker,
    (
        "safety_regulator_expire_request",
        "safety_regulator_worker_claim",
        "safety_regulator_snapshot_allowed",
        "apply_regulator_mode_blocking(snapshot.mode, snapshot.powerGeneration)",
        "apply_regulator_voltage_blocking(snapshot.voltage, snapshot.powerGeneration)",
        "safety_regulator_finish_apply",
        "fail_close_regulator_locked",
        "terminate_sleep_fault_locked",
    ),
)
power_backends_combined = power_kvic + power_rmvk + power_sem
if power_backends_combined.count("process_pending_power_request();") != 3:
    errors.append("all three backend triggerPowerStatus variants must run the regulator worker")
terminate_sleep = function_body(power, "inline void terminate_sleep_fault_locked")
require(
    "terminal SLEEP failure",
    terminate_sleep,
    ("force_heater_output_off_locked(false)", "POWER_TRANSITION_OFF_RESET_WAIT"),
)
forbid("terminal SLEEP failure", terminate_sleep, ("request_regulator_state_locked",))

setup = function_body(samovar, "void setup()")
require_ordered_tokens(
    "regulator worker startup",
    setup,
    [
        "powerTaskCreated = xTaskCreatePinnedToCore",
        "powerTaskReady = powerTaskCreated == pdPASS",
        "set_power_worker_ready(powerTaskReady)",
        "if (powerTaskReady)",
        "set_power_mode(POWER_SLEEP_MODE)",
    ],
    errors,
)

# RELE_CHANNEL2 на некоторых платах сидит на strapping-выводе, подтянутом вверх при
# сбросе (см. Samovar_pin.h) - уровни реле должны стать безопасными раньше вообще
# всего остального в setup(), в частности раньше Serial.begin(), который к выводам
# питания отношения не имеет. Startup-задержка стоит ПОСЛЕ apply_loaded_relay_polarity_off():
# если бы она шла сразу за init_power_outputs_safe_off(), окно неверного уровня на
# платах с releN=true держалось бы все 500+ мс вместо десятков миллисекунд чтения профиля.
require_ordered_tokens(
    "safe relay levels first in setup(), startup delay after polarity window closes",
    setup,
    [
        "init_power_outputs_safe_off();",
        "Serial.begin(115200);",
        "apply_loaded_relay_polarity_off();",
        "vTaskDelay(500 / portTICK_PERIOD_MS);",
    ],
    errors,
)
set_power = function_body(power, "inline ActuatorCommandResult set_power(bool On, bool enqueueResetCommand)")
require(
    "heater ON worker and reservation gate",
    set_power,
    ("powerWorkerReady && PowerStatusTask != nullptr", "!heaterSafetyState.exclusiveOwnerActive"),
)

# Emergency trip cuts both local outputs before any deferred work or reporting.
request_alarm = function_body(alarm, "inline void request_emergency_stop")
require_ordered_tokens(
    "emergency atomic barrier",
    request_alarm,
    [
        "portENTER_CRITICAL(&emergencyStopMux)",
        "emergency_trip_heater_outputs_locked()",
        "pending_emergency_stop_flag = true",
        "portEXIT_CRITICAL(&emergencyStopMux)",
    ],
    errors,
)
trip_locked = function_body(power, "inline bool emergency_trip_heater_outputs_locked")
require(
    "emergency trip state",
    trip_locked,
    (
        "safety_heater_emergency_trip",
        "apply_heater_outputs_off_locked()",
        "safety_transition_cancel(powerTransition.transition)",
        "SAFETY_REGULATOR_MODE_SLEEP",
    ),
)
forbid("emergency trip state", trip_locked, ("String", "SendMsg", "delay(", "vTaskDelay(", "Serial2."))

require(
    "independent emergency button",
    samovar,
    (
        "void IRAM_ATTR emergencyButtonInterrupt()",
        "vTaskNotifyGiveFromISR",
        "void triggerEmergencyButton(void *parameter)",
        "request_emergency_stop(\"Аварийное отключение: нажата аварийная кнопка\")",
        "xTaskCreatePinnedToCore",
        "attachInterrupt(ALARM_BTN_PIN, emergencyButtonInterrupt, FALLING)",
    ),
)
loop = function_body(samovar, "void loop()")
# P8: сторож стека вынесен из loop() в tick_check_stack_headroom() (Samovar.ino), вызываемую
# первой же строкой loop(). Конкатенация сохраняет прежний порядок проверяемых токенов,
# но сама по себе не докажет, что loop() эту функцию вызывает, поэтому вызов проверяем явно.
if "tick_check_stack_headroom();" not in loop:
    errors.append("low-stack fail closed: loop() не вызывает tick_check_stack_headroom()")
# П4: наблюдатель живучести SysTicker тоже обязан вызываться из loop() - иначе
# зависание задачи надзора (mode_dispatch_alarm) никем не замечается.
if "tick_check_systicker_liveness();" not in loop:
    errors.append("systicker liveness watchdog: loop() не вызывает tick_check_systicker_liveness()")
stack_headroom_body = function_body(samovar, "static void tick_check_stack_headroom()")
loop_with_stack_check = loop + stack_headroom_body
require_ordered_tokens(
    "low-stack fail closed",
    loop_with_stack_check,
    [
        # Порог в байтах: uxTaskGetStackHighWaterMark в ESP-IDF считает байты, и прежние
        # 325 не оставляли места самому аварийному пути (отсечка + SendMsg ≈ 200 байт).
        "if (uxTaskGetStackHighWaterMark(NULL) < 1024)",
        "request_emergency_stop(\"Аварийное отключение: критически малый остаток стека\")",
        "SendMsg(\"Стек переполнился. Перезагрузка\"",
        "vTaskDelay(5000)",
        # П24: проверка текущей задачи (loop()) - это только первая часть функции;
        # дальше идёт обход таблицы остальных наблюдаемых задач (SysTicker,
        # GetClockTicker, PowerStatusTask, ...), см. tools/smoke_stack_headroom_all_tasks.py.
        "for (size_t i = 0; i < sizeof(stackWatchTable) / sizeof(stackWatchTable[0]); i++)",
        "if (handle == nullptr) continue;",
        "if (uxTaskGetStackHighWaterMark(handle) < 1024)",
    ],
    errors,
)

# Lua's heater pins are whitelisted again (HEAD parity): pinMode/digitalWrite both
# accept RELE_CHANNEL1/RELE_CHANNEL4 like the other whitelisted pins and are gated
# by the same lua_state_mutation_allowed() mode-switch barrier every other mutating
# wrapper uses - the dedicated heater runtime block is gone. On top of that barrier,
# RELE_CHANNEL1/RELE_CHANNEL4 are also gated by heater_safety_latched() (R7 for
# digitalWrite, R10 for pinMode): while the emergency latch is armed, both wrappers
# silently no-op on those two channels instead of raising a luaL_error. That latch
# behavior is pinned by tools/smoke_lua_relay_polarity.py, not by the checks below.
forbid(
    "heater pin runtime guard removed",
    lua,
    ("heater pins are protected; use setPower",),
)
for signature in ("static int lua_wrapper_pinMode", "static int lua_wrapper_digitalWrite"):
    body = function_body(lua, signature)
    require(
        signature,
        body,
        (
            "a == RELE_CHANNEL1",
            "a == RELE_CHANNEL4",
            "lua_state_mutation_allowed()",
            "lua_reject_state_mutation(lua_state)",
        ),
    )
    if body.count("RELE_CHANNEL1") != 1 or body.count("RELE_CHANNEL4") != 1:
        errors.append(f"{signature} heater pin whitelist entry count changed")

# Mode publication waits for explicit owner cleanup and log close completion;
# old-mode dispatch is barred throughout the cleanup phase.
#
# [WP17 п.40] stop_active_process_for_mode() used to be a handwritten
# switch(Samovar_Mode) with one case per mode (RECT/DIST/BEER/BK/NBK), each calling
# its own finish-style function; SUVID/LUA fell through to a shared default reset.
# That switch is gone - the function now looks up mode_ops_by_mode(Samovar_Mode)
# and calls ops->stopProcess() when the registry provides one, falling back to the
# same generic reset otherwise. The protection that must survive the rewrite: every
# mode's active process really does get torn down on a mode switch. Expressed now
# as two parts - (1) the function actually dispatches through the registry and
# still has the generic fallback, and (2) the registry table wires stopProcess to
# a real, mode-specific finish function for every mode that owns its own process.
stop_mode = function_body(mode_switch, "void stop_active_process_for_mode")
require_ordered_tokens(
    "stop_active_process_for_mode dispatches through the mode registry",
    stop_mode,
    [
        "mode_ops_by_mode(Samovar_Mode)",
        "ops != nullptr && ops->stopProcess != nullptr",
        "ops->stopProcess();",
        "return;",
        "SamovarStatusInt = SAMOVAR_STATUS_IDLE;",
        "startval = SAMOVAR_STARTVAL_IDLE;",
        "ProgramNum = 0;",
        "set_power(false);",
    ],
    errors,
)

# mode_registry.h table: stopProcess per mode. Field is matched by NAME (index
# into struct ModeOps's real member order), not a fixed position - the struct has
# grown before (12 -> 16 fields) and a position-pinned check silently reads the
# wrong field instead of failing loudly when it grows again.
def parse_modeops_field_names(source: str) -> list[str]:
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


try:
    modeops_field_names = parse_modeops_field_names(mode_registry)
    stop_process_idx = modeops_field_names[1:].index("stopProcess")  # row text excludes leading `mode`
except ValueError as exc:
    errors.append(str(exc))
    stop_process_idx = None

if stop_process_idx is not None:
    registry_table = function_body(
        mode_registry, "inline const ModeOps* mode_registry_table(size_t& count)"
    )
    registry_rows = dict(
        re.findall(r"\{\s*(SAMOVAR_[A-Z_]+_MODE)\s*,([^{}]*)\}", registry_table)
    )
    # RECT is special - it has no .finish in the table (that slot stays nullptr;
    # .finish there is reserved for the SAMOVAR_POWER command path), so its
    # stopProcess is a dedicated wrapper around run_program(PROGRAM_END), not a
    # *_finish function like the other four.
    EXPECTED_STOP_PROCESS = {
        "SAMOVAR_RECTIFICATION_MODE": "mode_stop_process_rectification",
        "SAMOVAR_DISTILLATION_MODE": "distiller_finish",
        "SAMOVAR_BEER_MODE": "beer_finish",
        "SAMOVAR_BK_MODE": "bk_finish",
        "SAMOVAR_NBK_MODE": "nbk_finish",
    }
    for mode, expected_fn in EXPECTED_STOP_PROCESS.items():
        rest = registry_rows.get(mode)
        if rest is None:
            errors.append(f"mode_registry table: row for {mode} not found")
            continue
        fields = [f.strip() for f in rest.split(",")]
        if len(fields) <= stop_process_idx:
            errors.append(f"mode_registry table: row for {mode} too short: {rest}")
            continue
        actual_fn = fields[stop_process_idx]
        if actual_fn != expected_fn:
            errors.append(
                f"mode_registry table: {mode} stopProcess = {actual_fn!r}, "
                f"expected {expected_fn!r}"
            )
    require(
        "mode_stop_process_rectification wraps run_program(PROGRAM_END)",
        function_body(mode_registry, "inline void mode_stop_process_rectification()"),
        ("run_program(PROGRAM_END);",),
    )
    # SUVID/LUA deliberately have no per-mode process to tear down - stopProcess
    # stays nullptr and they fall through to the generic reset above, same as the
    # old switch's shared `case SAMOVAR_SUVID_MODE: case SAMOVAR_LUA_MODE: default:`.
    for mode in ("SAMOVAR_SUVID_MODE", "SAMOVAR_LUA_MODE"):
        rest = registry_rows.get(mode)
        if rest is None:
            errors.append(f"mode_registry table: row for {mode} not found")
            continue
        fields = [f.strip() for f in rest.split(",")]
        actual = fields[stop_process_idx] if len(fields) > stop_process_idx else "<missing>"
        if actual != "nullptr":
            errors.append(
                f"mode_registry table: {mode} stopProcess must remain nullptr (falls "
                f"through to the generic reset), got {actual!r}"
            )
force_complete_mode_switch = function_body(
    mode_switch, "static ModeSwitchResult force_complete_mode_switch_failed(const char* warning)")
require_ordered_tokens(
    "force-complete releases the barrier on every failure path",
    force_complete_mode_switch,
    [
        "portENTER_CRITICAL(&emergencyStopMux)",
        "force_heater_output_off_locked(true)",
        "safety_mode_switch_complete(modeSwitchState)",
        "clear_mode_switch_barrier_locked()",
        "portEXIT_CRITICAL(&emergencyStopMux)",
        "notify_power_worker()",
        "SendMsg(warning, WARNING_MSG)",
        "return MODE_SWITCH_FAILED",
    ],
    errors,
)

switch_mode = function_body(mode_switch, "ModeSwitchResult switch_samovar_mode")
require_ordered_tokens(
    "deferred mode switch",
    switch_mode,
    [
        "safety_mode_switch_begin",
        "stop_active_process_for_mode()",
        "request_lua_mode_stop()",
        "discard_samovar_commands",
        "discard_pending_mode_control_commands",
        "force_complete_mode_switch_failed(",
        "safety_mode_switch_wait_cleanup",
        "lua_mode_owner_idle()",
        "tick_mode_actuator_cleanup(luaIdle)",
        "mode_control_queues_idle()",
        "heater_power_on()",
        "power_transition_active()",
        "nbk_transition_active()",
        "mode_heating_start_active()",
        "self_test_active()",
        "mode_runtime_owner_idle()",
        "safety_mode_switch_cleanup_ready(",
        # R11: выход по дедлайну обязан опираться на ЕДИНЫЙ расчёт готовности.
        # Без этого токена скан бесполезен против регрессии R11: нижний гейт
        # `if (!cleanupReady) ...` остаётся на месте при любом условии выхода,
        # поэтому и старая дефектная проверка из 5 термов проходила скан насквозь.
        # `&&` тут не украшение - он отличает выход от нижнего гейта.
        "&& !cleanupReady) {",
        "force_complete_mode_switch_failed(warning)",
        "if (!modeSwitchState.logCloseRequested)",
        "request_data_log_close()",
        "safety_mode_switch_mark_log_close_requested",
        "if (!cleanupReady) return MODE_SWITCH_PENDING",
        "commit_profile_operation()",
        "if (commitError != OPERATION_ERROR_NONE)",
        "force_complete_mode_switch_failed(",
        "safety_mode_switch_complete",
        "clear_mode_switch_barrier_locked()",
        "return MODE_SWITCH_SUCCEEDED",
    ],
    errors,
)
forbid(
    "deferred mode switch never parks in a terminal dead phase",
    switch_mode,
    ("safety_mode_switch_fail(", "safety_mode_switch_failed(", "SAFETY_MODE_SWITCH_FAILED"),
)
# Барьер смены режима глушит только режимный тик (mode_dispatch_loop), а не
# аварийный надзор (mode_dispatch_alarm) - см. mode_registry.h. Аварийный надзор
# обязан идти всегда, поэтому проверки разведены: require для loop, forbid для alarm.
require(
    "mode_dispatch_loop",
    function_body(mode_registry, "inline void mode_dispatch_loop"),
    ("if (mode_switch_in_progress()) return",),
)
forbid(
    "mode_dispatch_alarm must never skip on the mode-switch barrier",
    function_body(mode_registry, "inline void mode_dispatch_alarm"),
    ("mode_switch_in_progress()",),
)

logic = read_source("logic.h")
rect_finish_start = logic.find("if (num >= PROGRAM_MAX)")
rect_finish_end = logic.find("return;", rect_finish_start)
rect_finish = logic[rect_finish_start:rect_finish_end] if rect_finish_start >= 0 and rect_finish_end >= 0 else ""
require("rectification finish", rect_finish, ("ProgramNum = 0", "startval = SAMOVAR_STARTVAL_IDLE"))
for name, source, signature in (
    ("distillation finish", distiller, "void distiller_finish"),
    ("beer finish", beer, "void beer_finish"),
    ("BK finish", bk, "void bk_finish"),
):
    body = function_body(source, signature)
    require(name, body, ("ProgramNum = 0", "startval = SAMOVAR_STARTVAL_IDLE"))
forbid("beer finish", function_body(beer, "void beer_finish"), ("delay(", "vTaskDelay("))

# Self-test is an explicit safety owner. A pending switch, active heater, epoch
# change, or emergency latch cancels every hardware phase immediately.
start_selftest = function_body(selftest, "inline void start_self_test")
require(
    "self-test start barrier",
    start_selftest,
    (
        "mode_switch_in_progress()",
        "safety_owner_generation_acquire(selfTestOwnerGeneration)",
    ),
)
tick_selftest = function_body(selftest, "inline void tick_self_test")
require("self-test owner validation", tick_selftest, ("abort_self_test_if_owner_lost()",))
require(
    "self-test generation validation",
    function_body(selftest, "inline bool abort_self_test_if_owner_lost"),
    ("mode_switch_in_progress()", "safety_owner_generation_valid(selfTestOwnerGeneration)"),
)
require(
    "self-test terminal heater cutoff",
    function_body(selftest, "inline void finish_self_test_now"),
    ("heater_power_on() || PowerOn", "set_power(false, false)", "safety_owner_generation_release"),
)

require(
    "mode barrier command queue",
    command_queue,
    (
        "if (mode_switch_in_progress())",
        "discard_samovar_commands",
        "samovar_command_queue_idle",
    ),
)
setup_save = function_body(webserver, "static OperationError queue_profile_operation(")
require_ordered_tokens(
    "profile queue checks the mode barrier under the pending-command lock",
    setup_save,
    [
        "PendingCommandLockGuard guard;",
        "profile_operation_phase_load() != PROFILE_OPERATION_EMPTY",
        "mode_switch_in_progress()",
        "operation_store_reserve_locked(",
    ],
    errors,
)
require(
    "main-loop mode barrier",
    loop,
    (
        "while (!mode_switch_in_progress() && receive_samovar_command",
        "if (mode_switch_in_progress())",
        "process_buzzer()",
        "return",
    ),
)
require(
    "actuator cleanup",
    mode_switch,
    (
        "stop_local_mode_actuators",
        "stop_i2c_mode_actuator",
        "I2CSTEP_CMD_CALIBRATE_FINISH",
        "i2c_stepper_stop",
        "mode_actuators_idle",
        "force_complete_mode_switch_failed",
    ),
)
require_ordered_tokens(
    "external actuator stop precedes Lua-idle publication gate",
    function_body(mode_switch, "static bool tick_mode_actuator_cleanup"),
    [
        "stop_i2c_mode_actuator(i2cStepperMixer, false)",
        "stop_i2c_mode_actuator(",
        "modeActuatorCleanup.pumpStopped = luaIdle && stopped",
        "if (!luaIdle) return false",
        "mode_actuators_idle()",
    ],
    errors,
)
process_profile = function_body(
    samovar[samovar.rfind("static void process_profile_operation()") :],
    "static void process_profile_operation()",
)
require_ordered_tokens(
    "profile owner publishes terminal mode-switch result without a second path",
    process_profile,
    [
        "profile_operation_phase_load() == PROFILE_OPERATION_MODE_SWITCH",
        "switch_samovar_mode(",
        "if (switchResult == MODE_SWITCH_PENDING) return",
        "OPERATION_ERROR_MODE_SWITCH_FAILED",
        "set_profile_operation_terminal(",
        "publish_profile_operation_terminal();",
    ],
    errors,
)

lua_mutating_wrappers = (
    "lua_wrapper_pinMode",
    "lua_wrapper_digitalWrite",
    "lua_wrapper_set_pause_withdrawal",
    "lua_wrapper_set_power",
    "lua_wrapper_set_mixer",
    "lua_wrapper_open_valve",
    "lua_wrapper_set_current_power",
    "lua_wrapper_set_body_temp",
    "lua_wrapper_set_next_program",
    "lua_wrapper_set_num_variable",
    "lua_wrapper_set_str_variable",
    "lua_wrapper_set_capacity",
    "lua_wrapper_set_pump_pwm",
    "lua_wrapper_set_stepper_by_time",
    "lua_wrapper_set_stepper_target",
    "lua_wrapper_i2cpump_start",
    "lua_wrapper_i2cpump_stop",
    "lua_wrapper_set_mixer_pump_target",
    "lua_wrapper_set_i2c_rele_state",
)
for wrapper in lua_mutating_wrappers:
    signature = f"static int {wrapper}"
    if wrapper in ("lua_wrapper_set_current_power", "lua_wrapper_set_pump_pwm") and signature not in lua:
        continue
    require(
        f"Lua mutation barrier {wrapper}",
        function_body(lua, signature),
        ("lua_state_mutation_allowed()", "lua_reject_state_mutation(lua_state)"),
    )
require(
    "Lua mutation error",
    function_body(lua, "inline int lua_reject_state_mutation"),
    ("luaL_error", "mode switch blocks state changes"),
)

for virtual_pin in ("V16", "V17", "V18", "V12", "V13", "V3", "V4"):
    require(
        f"Blynk mutation barrier {virtual_pin}",
        function_body(blynk, f"BLYNK_WRITE({virtual_pin})"),
        ("mode_switch_in_progress()",),
    )

# The cited process paths may fail explicitly when a shared description is busy,
# but may not block the main loop forever.
for name, source in (
    ("mode common", mode_common),
    ("beer", beer),
    ("NBK", nbk),
    ("rectification menu", menu),
):
    forbid(name, source, ("portMAX_DELAY",))

# All heater ON writes remain centralized.
on_write = re.compile(r"digitalWrite\(RELE_CHANNEL([14]),\s*SamSetup\.rele\1\)")
all_heater_sources = "\n".join(
    strip_cpp_comments(path.read_text(encoding="utf-8", errors="ignore"))
    for pattern in ("*.h", "*.ino")
    for path in ROOT.glob(pattern)
)
enable_locked = function_body(power, "inline bool heater_outputs_enable_locked")
if sorted(on_write.findall(all_heater_sources)) != ["1", "4"] or sorted(on_write.findall(enable_locked)) != ["1", "4"]:
    errors.append("heater ON writes must exist only once inside heater_outputs_enable_locked")

# All BOOST (RELE_CHANNEL4) heater OFF writes remain centralized.
# Samovar.ino содержит два законных boot-time raw digitalWrite(RELE_CHANNEL4, ...):
# apply_loaded_relay_polarity_off() и pin-init в setup_init_output_pins(). Это установка
# исходного состояния реле до старта runtime heater-пути. Исключаем ровно эти две функции,
# а не весь файл, иначе новый сырой digitalWrite в любой другой части Samovar.ino
# (например, в tick_*) прошёл бы мимо проверки.
off4_write = re.compile(r"digitalWrite\(RELE_CHANNEL4,\s*!SamSetup\.rele4\)")
samovar_runtime = samovar
for boot_signature in (
    "static void apply_loaded_relay_polarity_off()",
    "static void setup_init_output_pins()",
):
    boot_body = function_body(samovar, boot_signature)
    if boot_body:
        samovar_runtime = samovar_runtime.replace(boot_body, "", 1)
off4_scope_sources = all_heater_sources.replace(samovar, samovar_runtime)
boost_off_helper = function_body(power, "inline void heater_boost_output_off")
if len(off4_write.findall(off4_scope_sources)) != 1 or not off4_write.search(boost_off_helper):
    errors.append("heater BOOST OFF writes must exist only once inside heater_boost_output_off()")

require(
    "compile macro profiles",
    platformio,
    (
        "[env:Samovar_no_power]",
        "[env:Samovar_rmvk]",
        "[env:Samovar_sem]",
        "[env:Samovar_lua_mqtt]",
        "[env:Samovar_alarm_button]",
        "-DSAMOVAR_BUILD_LUA",
        "-DSAMOVAR_BUILD_MQTT",
    ),
)
for environment in (
    "Samovar",
    "Samovar_s3",
    "Samovar_no_power",
    "Samovar_rmvk",
    "Samovar_sem",
    "Samovar_lua_mqtt",
    "Samovar_alarm_button",
):
    if environment not in ci:
        errors.append(f"CI build matrix missing environment: {environment}")
require(
    "transparent manual power selector",
    ini,
    (
        "#define SAMOVAR_USE_POWER",
    ),
)
if re.search(r"^\s*#define SAMOVAR_USE_RMVK", ini, re.MULTILINE):
    errors.append("manual power selector must leave SAMOVAR_USE_RMVK disabled by default")
if re.search(r"^\s*#define SAMOVAR_USE_SEM_AVR", ini, re.MULTILINE):
    errors.append("manual power selector must leave SAMOVAR_USE_SEM_AVR disabled by default")
if "SAMOVAR_BUILD_NO_POWER" in ini or "SAMOVAR_BUILD_RMVK" in ini or "SAMOVAR_BUILD_SEM" in ini:
    errors.append("PlatformIO build selectors must not obscure the manual selector in Samovar_ini.h")
require(
    "non-power compile macro selectors",
    ini,
    (
        "SAMOVAR_BUILD_LUA",
        "SAMOVAR_BUILD_MQTT",
    ),
)
require(
    "compile macro selectors",
    samovar_header,
    (
        "SAMOVAR_BUILD_NO_POWER",
        "SAMOVAR_BUILD_RMVK",
        "SAMOVAR_BUILD_SEM",
    ),
)
if not re.search(
    r"#if defined\(SAMOVAR_BUILD_RMVK\) \|\| defined\(SAMOVAR_BUILD_SEM\)\s+"
    r"(?:#ifndef SAMOVAR_USE_RMVK\s+)?#define SAMOVAR_USE_RMVK",
    samovar_header,
):
    errors.append("SEM build selector must enter the nested SEM/RMVK protocol branch")
if not re.search(
    r"#ifdef SAMOVAR_USE_SEM_AVR\s+#ifndef SAMOVAR_USE_RMVK\s+"
    r"#define SAMOVAR_USE_RMVK",
    samovar_header,
):
    errors.append("manual SEM selector must enable the RMVK protocol dependency")
if not re.search(
    r"#ifdef SAMOVAR_USE_RMVK[\s\S]*?#ifndef SAMOVAR_USE_POWER\s+"
    r"#define SAMOVAR_USE_POWER",
    samovar_header,
):
    errors.append("manual RMVK selector must enable the base power-regulator dependency")

host_source = r'''
#include <cstdint>
#include <string>
#include "safety_transition.h"

struct FakeUart {
  int calls;
  int acceptedLength;
  std::string bytes;
};

static int fake_uart_enqueue(void* context, const char* data, size_t length) {
  FakeUart* uart = static_cast<FakeUart*>(context);
  uart->calls++;
  uart->bytes.assign(data, length);
  return uart->acceptedLength < 0 ? static_cast<int>(length) : uart->acceptedLength;
}

struct FakeHardware {
  SafetyHeaterBarrierState heater;
  SafetyRegulatorRequestState regulator;
  bool mainRelay;
  bool boostRelay;
};

static FakeHardware fresh() {
  FakeHardware hw = {};
  hw.regulator.desiredMode = SAFETY_REGULATOR_MODE_SLEEP;
  hw.regulator.appliedMode = SAFETY_REGULATOR_MODE_SLEEP;
  return hw;
}

static bool fake_heater_start(FakeHardware& hw) {
  if (!safety_heater_enable(hw.heater, true)) return false;
  hw.mainRelay = true;
  return true;
}

static void fake_emergency_trip(FakeHardware& hw) {
  safety_heater_emergency_trip(hw.heater);
  hw.mainRelay = false;
  hw.boostRelay = false;
  safety_regulator_invalidate_energizing(hw.regulator);
}

static SafetyRegulatorWorkerClaim fake_worker_step(
  FakeHardware& hw,
  uint32_t now,
  bool driverSuccess,
  bool tripBeforeFinish
) {
  SafetyRegulatorRequestSnapshot snapshot = {};
  const SafetyRegulatorWorkerClaim claim = safety_regulator_worker_claim(
    hw.regulator, now, snapshot
  );
  if (claim != SAFETY_REGULATOR_WORKER_CLAIMED) return claim;
  bool success = safety_regulator_snapshot_allowed(snapshot, hw.heater);
  if (tripBeforeFinish) fake_emergency_trip(hw);
  success = success && driverSuccess &&
            safety_regulator_snapshot_allowed(snapshot, hw.heater);
  safety_regulator_finish_apply(hw.regulator, snapshot, success);
  return claim;
}

int main() {
  if (safety_deadline_expired(0xFFFFFFF0u, 0x10u)) return 1;
  if (!safety_deadline_expired(0x10u, 0x10u)) return 2;
  if (safety_deadline_after(0xFFFFFFF0u, 0x20u) != 0x10u) return 3;

  // Alarm before start: no fake GPIO or UART action can energize.
  FakeHardware before = fresh();
  fake_emergency_trip(before);
  if (fake_heater_start(before) || before.mainRelay || before.boostRelay) return 4;
  FakeUart beforeUart = {0, -1, {}};
  if (safety_uart_commit_locked(before.heater, 0, true, "M1\r", 3, fake_uart_enqueue, &beforeUart)) return 5;
  if (beforeUart.calls != 0) return 6;

  // Alarm after start invalidates the exact epoch; stale and ABA writers lose.
  FakeHardware active = fresh();
  if (!fake_heater_start(active)) return 7;
  const uint64_t firstEpoch = active.heater.generation;
  FakeUart activeUart = {0, -1, {}};
  if (!safety_uart_commit_locked(active.heater, firstEpoch, true, "M1\r", 3, fake_uart_enqueue, &activeUart)) return 8;
  if (activeUart.calls != 1 || activeUart.bytes != "M1\r") return 9;
  fake_emergency_trip(active);
  if (active.mainRelay || active.boostRelay || active.heater.powerOn) return 10;
  if (safety_uart_commit_locked(active.heater, firstEpoch, true, "S100\r", 5, fake_uart_enqueue, &activeUart)) return 11;
  if (activeUart.calls != 1) return 12;
  if (!safety_uart_commit_locked(active.heater, 0, false, "M0\r", 3, fake_uart_enqueue, &activeUart)) return 13;

  // Partial UART enqueue is a hard failure; no success is inferred.
  FakeHardware partial = fresh();
  if (!fake_heater_start(partial)) return 14;
  FakeUart partialUart = {0, 2, {}};
  if (safety_uart_commit_locked(partial.heater, partial.heater.generation, true, "M1\r", 3, fake_uart_enqueue, &partialUart)) return 15;

  // Latest request wins and 64-bit generations cross the uint32 boundary.
  FakeHardware latest = fresh();
  if (!fake_heater_start(latest)) return 16;
  latest.regulator.nextGeneration = UINT32_MAX;
  const uint64_t g1 = safety_regulator_request(
    latest.regulator, SAFETY_REGULATOR_MODE_WORK, true, 100,
    latest.heater.generation, 100, false
  );
  const uint64_t g2 = safety_regulator_request(
    latest.regulator, SAFETY_REGULATOR_MODE_WORK, true, 120,
    latest.heater.generation, 100, false
  );
  if (g1 <= UINT32_MAX || g2 != g1 + 1) return 17;
  if (safety_regulator_request_status(latest.regulator, g1) != SAFETY_REGULATOR_REQUEST_SUPERSEDED) return 18;
  SafetyRegulatorRequestSnapshot latestSnapshot = {};
  if (!safety_regulator_begin_apply(latest.regulator, latestSnapshot)) return 19;
  if (latestSnapshot.generation != g2 || latestSnapshot.voltage != 120) return 20;
  safety_regulator_finish_apply(latest.regulator, latestSnapshot, true);
  if (safety_regulator_request_status(latest.regulator, g2) != SAFETY_REGULATOR_REQUEST_APPLIED) return 21;

  // The production worker claim seam expires before invoking a driver.
  SafetyRegulatorRequestState queuedTimeout = {};
  const uint64_t queued = safety_regulator_request(
    queuedTimeout, SAFETY_REGULATOR_MODE_WORK, false, 0, 1, 50, false
  );
  SafetyRegulatorRequestSnapshot noSnapshot = {};
  if (safety_regulator_worker_claim(queuedTimeout, 50, noSnapshot) != SAFETY_REGULATOR_WORKER_TIMED_OUT) return 22;
  if (safety_regulator_begin_apply(queuedTimeout, noSnapshot)) return 23;
  if (safety_regulator_request_status(queuedTimeout, queued) != SAFETY_REGULATOR_REQUEST_TIMED_OUT) return 24;

  // Deadline while in flight stays TIMED_OUT even if a late response says OK.
  SafetyRegulatorRequestState inFlight = {};
  const uint64_t flight = safety_regulator_request(
    inFlight, SAFETY_REGULATOR_MODE_WORK, false, 0, 1, 75, false
  );
  SafetyRegulatorRequestSnapshot flightSnapshot = {};
  if (!safety_regulator_begin_apply(inFlight, flightSnapshot)) return 25;
  if (!safety_regulator_expire_request(inFlight, flight, 75)) return 26;
  safety_regulator_finish_apply(inFlight, flightSnapshot, true);
  if (inFlight.workerBusy) return 27;
  if (safety_regulator_request_status(inFlight, flight) != SAFETY_REGULATOR_REQUEST_TIMED_OUT) return 28;

  // Explicit driver failure is terminal, including SLEEP; no retry appears.
  SafetyRegulatorRequestState failed = {};
  const uint64_t failedWork = safety_regulator_request(
    failed, SAFETY_REGULATOR_MODE_WORK, false, 0, 1, 100, false
  );
  SafetyRegulatorRequestSnapshot failedSnapshot = {};
  if (!safety_regulator_begin_apply(failed, failedSnapshot)) return 29;
  safety_regulator_finish_apply(failed, failedSnapshot, false);
  if (safety_regulator_request_status(failed, failedWork) != SAFETY_REGULATOR_REQUEST_FAILED) return 30;
  const uint64_t failedSleep = safety_regulator_request(
    failed, SAFETY_REGULATOR_MODE_SLEEP, false, 0, 2, 200, true
  );
  SafetyRegulatorRequestSnapshot sleepSnapshot = {};
  if (!safety_regulator_begin_apply(failed, sleepSnapshot)) return 31;
  safety_regulator_finish_apply(failed, sleepSnapshot, false);
  if (failed.pending || failed.workerBusy) return 32;
  if (safety_regulator_request_status(failed, failedSleep) != SAFETY_REGULATOR_REQUEST_FAILED) return 33;

  // A stale command from an earlier heater epoch cannot pass after OFF -> ON.
  FakeHardware aba = fresh();
  if (!fake_heater_start(aba)) return 34;
  const uint64_t oldEpoch = aba.heater.generation;
  const uint64_t oldRequest = safety_regulator_request(
    aba.regulator, SAFETY_REGULATOR_MODE_WORK, true, 90, oldEpoch, 100, false
  );
  SafetyRegulatorRequestSnapshot oldSnapshot = {};
  if (!safety_regulator_begin_apply(aba.regulator, oldSnapshot) || oldRequest == 0) return 35;
  safety_heater_force_off(aba.heater);
  if (!fake_heater_start(aba)) return 36;
  if (aba.heater.generation == oldEpoch || safety_regulator_snapshot_allowed(oldSnapshot, aba.heater)) return 37;

  // Self-test owns an exclusive reservation: ON loses until release, and an
  // emergency invalidates the owner token without permitting a stale release.
  FakeHardware reserved = fresh();
  uint64_t owner = 0;
  if (!safety_heater_owner_acquire(reserved.heater, owner) || owner == 0) return 38;
  if (!safety_heater_owner_valid(reserved.heater, owner)) return 39;
  if (fake_heater_start(reserved) || reserved.mainRelay) return 40;
  if (!safety_heater_owner_release(reserved.heater, owner)) return 41;
  if (!fake_heater_start(reserved)) return 42;
  safety_heater_force_off(reserved.heater);
  if (!safety_heater_owner_acquire(reserved.heater, owner)) return 43;
  fake_emergency_trip(reserved);
  if (safety_heater_owner_valid(reserved.heater, owner) ||
      safety_heater_owner_release(reserved.heater, owner) ||
      fake_heater_start(reserved)) return 44;

  // A claimed production worker request cannot survive an emergency between
  // its fake driver phases; a normal request completes through the same seam.
  FakeHardware worker = fresh();
  if (!fake_heater_start(worker)) return 45;
  const uint64_t workerGeneration = safety_regulator_request(
    worker.regulator, SAFETY_REGULATOR_MODE_WORK, true, 110,
    worker.heater.generation, 500, false
  );
  if (fake_worker_step(worker, 100, true, true) != SAFETY_REGULATOR_WORKER_CLAIMED) return 46;
  if (safety_regulator_request_status(worker.regulator, workerGeneration) == SAFETY_REGULATOR_REQUEST_APPLIED) return 47;
  FakeHardware workerOk = fresh();
  if (!fake_heater_start(workerOk)) return 48;
  const uint64_t workerOkGeneration = safety_regulator_request(
    workerOk.regulator, SAFETY_REGULATOR_MODE_WORK, false, 0,
    workerOk.heater.generation, 500, false
  );
  if (fake_worker_step(workerOk, 100, true, false) != SAFETY_REGULATOR_WORKER_CLAIMED) return 49;
  if (safety_regulator_request_status(workerOk.regulator, workerOkGeneration) != SAFETY_REGULATOR_REQUEST_APPLIED) return 50;

  // Publication waits for explicit log request, all transitions, and owner idle.
  SafetyModeSwitchState modeSwitch = {SAFETY_MODE_SWITCH_IDLE, 0, false, false, 0};
  if (!safety_mode_switch_begin(modeSwitch, 4)) return 51;
  safety_mode_switch_wait_cleanup(modeSwitch);
  if (safety_mode_switch_cleanup_ready(modeSwitch, false, false, false, false, false, false, true, true, true, true)) return 52;
  safety_mode_switch_mark_log_close_requested(modeSwitch);
  if (safety_mode_switch_cleanup_ready(modeSwitch, false, false, false, false, false, false, false, true, true, true)) return 53;
  if (safety_mode_switch_cleanup_ready(modeSwitch, false, true, false, false, false, false, true, true, true, true)) return 54;
  if (safety_mode_switch_cleanup_ready(modeSwitch, false, false, false, false, false, false, true, false, true, true)) return 55;
  if (safety_mode_switch_cleanup_ready(modeSwitch, false, false, false, false, false, false, true, true, false, true)) return 56;
  if (safety_mode_switch_cleanup_ready(modeSwitch, false, false, false, false, false, false, true, true, true, false)) return 57;
  if (!safety_mode_switch_cleanup_ready(modeSwitch, false, false, false, false, false, false, true, true, true, true)) return 58;

  // The barrier must always be releasable: there is no SAFETY_MODE_SWITCH_FAILED dead
  // phase to park in any more. safety_mode_switch_complete() resets to IDLE from
  // WAIT_CLEANUP unconditionally, and a fresh begin() is accepted right after.
  // Завершение обязано оставлять структуру чистой: иначе счётчик попыток
  // перечитывания Lua-скрипта доживёт до следующей смены режима и та упадёт
  // в принудительный провал раньше положенных десяти попыток.
  modeSwitch.commitDone = true;
  modeSwitch.luaReloadAttempts = 5;
  safety_mode_switch_complete(modeSwitch);
  if (modeSwitch.phase != SAFETY_MODE_SWITCH_IDLE || modeSwitch.logCloseRequested) return 59;
  if (modeSwitch.commitDone || modeSwitch.luaReloadAttempts != 0) return 61;
  if (!safety_mode_switch_begin(modeSwitch, 7) ||
      modeSwitch.phase != SAFETY_MODE_SWITCH_STOP_REQUESTED) return 60;
  return 0;
}
'''

with tempfile.TemporaryDirectory() as temp_dir:
    source_path = Path(temp_dir) / "safety_interleavings.cpp"
    binary_path = Path(temp_dir) / "safety_interleavings"
    source_path.write_text(host_source, encoding="utf-8")
    compiled = subprocess.run(
        [
            "g++",
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(ROOT),
            str(source_path),
            "-o",
            str(binary_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        errors.append("production safety core host compile failed: " + compiled.stderr.strip())
    else:
        executed = subprocess.run([str(binary_path)], capture_output=True, text=True, check=False)
        if executed.returncode != 0:
            errors.append(f"production safety interleaving harness failed with exit {executed.returncode}")

if errors:
    print("Safety timing smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Safety timing/interleaving checks passed; physical logic-analyzer gate remains pending")
