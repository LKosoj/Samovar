#!/usr/bin/env python3
"""Поведенческая проверка таймера выдержки Сувида (П6, 22.07.2026).

Тест вытаскивает РЕАЛЬНЫЙ фрагмент кода из check_alarm_suvid (suvid.h) —
от `static bool suvidHeaterOn = false;` (термостат) до конца тела функции
(таймер выдержки), т.е. включая ветку `if (!PowerOn) { ... }` — и подставляет
его в минимальный host-харнесс. Мокаются только downstream-вызовы
(set_buzzer, SendMsg, queue_samovar_command, request_emergency_stop,
setHeaterPosition, suvid_target_temp, millis()); дедлайн-идиомы
(safety_deadline_after/safety_deadline_expired) берутся из РЕАЛЬНОГО
safety_transition.h, HEAT_DELTA — из РЕАЛЬНОГО Samovar_ini.h.

Регресс, который тест защищает: до фикса у Сувида не было таймера выдержки
вовсе (только релейный термостат). Задача: program[0].Time (мин) должно
запускать отсчёт ПОСЛЕ первого достижения уставки TankSensor.avgTemp, гаситься
guard'ом WType==PROGRAM_TYPE_NONE/holdMinutes<=0, не запускаться повторно после
fired, завершаться ТОЛЬКО через queue_samovar_command(SAMOVAR_POWER) с fallback
на request_emergency_stop при занятой очереди (никогда set_power(false)
напрямую) — И (ревью 23.07.2026) ветка `!PowerOn` обязана полностью сбрасывать
suvidHold (active/fired/deadlineMs), иначе fired-защёлка переживёт конец
сессии и таймер выдержки перестанет запускаться во ВСЕХ следующих сессиях
Сувида. Без этой проверки потеря строки `suvidHold = {false, false, 0};`
не покраснила бы ни один тест.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

THERMOSTAT_START_ANCHOR = "static bool suvidHeaterOn = false;"
STRUCT_ANCHOR = "struct SuvidHoldState"
STATIC_INSTANCE = "static SuvidHoldState suvidHold;"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include "safety_transition.h"

@HEAT_DELTA_DEFINE@

using ProgramType = char;
constexpr ProgramType PROGRAM_TYPE_NONE = '\0';

enum SamovarCommands { SAMOVAR_NONE = 0, SAMOVAR_POWER = 1 };
constexpr int NOTIFY_MSG = 2;

struct WProgram { ProgramType WType; float Time; };
static WProgram program[1];

struct TankSensorMock { float avgTemp; };
static TankSensorMock TankSensor;

@HOLD_STRUCT@

static bool PowerOn = false;
static bool heater_state = false;

static uint32_t fakeMillis = 0;
inline uint32_t millis() { return fakeMillis; }

static int buzzerCalls = 0;
static bool buzzerState = false;
inline void set_buzzer(bool on) { buzzerCalls++; buzzerState = on; }

static int sendMsgCalls = 0;
inline void SendMsg(const char* msg, int type) { (void)msg; (void)type; sendMsgCalls++; }

static int queueCalls = 0;
static bool queueShouldSucceed = true;
static SamovarCommands lastQueuedCommand = SAMOVAR_NONE;
inline bool queue_samovar_command(SamovarCommands cmd) {
  queueCalls++;
  lastQueuedCommand = cmd;
  return queueShouldSucceed;
}

static int emergencyCalls = 0;
inline void request_emergency_stop(const char* reason) { (void)reason; emergencyCalls++; }

static int setHeaterCalls = 0;
inline void setHeaterPosition(bool state) { (void)state; setHeaterCalls++; }

// Реальная suvid_target_temp() читает SamSetup.SuvidTemp - в харнессе её не
// реплицируем (не предмет этого теста, покрыта отдельным пином в
// smoke_suvid_mode_fixes.py), подменяем контролируемым значением.
static float mockSetpoint = 60.0f;
inline float suvid_target_temp() { return mockSetpoint; }

static void run_tick() {
@SNIPPET@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture(char wtype, float holdMinutes, bool queueSucceeds, float setpoint = 60.0f) {
  PowerOn = true;
  program[0].WType = wtype;
  program[0].Time = holdMinutes;
  suvidHold.active = false;
  suvidHold.fired = false;
  suvidHold.deadlineMs = 0;
  fakeMillis = 0;
  TankSensor.avgTemp = 0.0f;
  mockSetpoint = setpoint;
  heater_state = false;
  buzzerCalls = 0;
  buzzerState = false;
  sendMsgCalls = 0;
  queueCalls = 0;
  queueShouldSucceed = queueSucceeds;
  lastQueuedCommand = SAMOVAR_NONE;
  emergencyCalls = 0;
  setHeaterCalls = 0;
}

// Отсчёт не должен стартовать раньше первого достижения уставки, дедлайн
// обязан масштабироваться РОВНО как holdMinutes*60000 от millis() момента
// старта, и завершение обязано случиться ровно на дедлайне (не раньше).
static void test_scaling_for(float holdMinutes) {
  reset_fixture('S', holdMinutes, true);

  fakeMillis = 1000;
  TankSensor.avgTemp = mockSetpoint - 5.0f;
  run_tick();
  check(!suvidHold.active, "hold must not start before TankSensor reaches setpoint");

  TankSensor.avgTemp = mockSetpoint;
  run_tick();
  check(suvidHold.active, "hold must start once TankSensor reaches setpoint");
  const uint32_t expectedDeadline = fakeMillis + (uint32_t)(holdMinutes * 60000.0f);
  check(suvidHold.deadlineMs == expectedDeadline,
        "deadline must scale as holdMinutes*60000 from the tick that started the hold");

  fakeMillis = expectedDeadline - 1000;
  run_tick();
  check(queueCalls == 0, "must not fire before the deadline elapses");
  check(!suvidHold.fired, "fired latch must stay clear before the deadline");

  fakeMillis = expectedDeadline;
  run_tick();
  check(queueCalls == 1, "must queue exactly once when the deadline elapses");
  check(lastQueuedCommand == SAMOVAR_POWER, "must queue SAMOVAR_POWER to end the hold gracefully");
  check(buzzerCalls == 1 && buzzerState, "must sound the buzzer on hold completion");
  check(sendMsgCalls == 1, "must notify the operator on hold completion");
  check(suvidHold.fired, "fired latch must be set after completion");

  fakeMillis += 60000;
  run_tick();
  check(queueCalls == 1, "REGRESSION: must not refire after the fired latch is set");
  check(emergencyCalls == 0, "REGRESSION: must not fall back to emergency stop when queueing succeeded");
}

// WType == PROGRAM_TYPE_NONE means program[0] holds a stale value left by
// another mode (no Суvid string was actually set) - the timer must never start.
static void test_guard_wtype_none() {
  reset_fixture(PROGRAM_TYPE_NONE, 5.0f, true);
  TankSensor.avgTemp = mockSetpoint;
  for (int i = 0; i < 5; i++) {
    fakeMillis += 1000;
    run_tick();
  }
  check(!suvidHold.active, "REGRESSION: WType==PROGRAM_TYPE_NONE must block the hold timer entirely");
  check(queueCalls == 0, "no completion action must fire while the WType guard blocks the start");
}

// holdMinutes <= 0 means no hold duration was configured - must not start either.
static void test_guard_zero_minutes() {
  reset_fixture('S', 0.0f, true);
  TankSensor.avgTemp = mockSetpoint;
  for (int i = 0; i < 5; i++) {
    fakeMillis += 1000;
    run_tick();
  }
  check(!suvidHold.active, "REGRESSION: holdMinutes<=0 must not start a hold timer");
}

// If the command queue is busy, completion must fall back to request_emergency_stop
// (never a silent no-op, and never a direct set_power(false) call).
static void test_fallback_emergency_when_queue_busy() {
  reset_fixture('S', 2.0f, false);
  fakeMillis = 500;
  TankSensor.avgTemp = mockSetpoint;
  run_tick();
  const uint32_t deadline = suvidHold.deadlineMs;

  fakeMillis = deadline;
  run_tick();
  check(queueCalls == 1, "must still attempt queue_samovar_command even when it will fail");
  check(emergencyCalls == 1, "REGRESSION: busy queue must fall back to request_emergency_stop");
  check(suvidHold.fired, "fired latch must be set even on the fallback path");
}

// [Ревью 23.07.2026] Сессия 1 доводит выдержку до fired. !PowerOn обязан
// полностью сбросить suvidHold (не только active - ИМЕННО fired тоже),
// иначе сессия 2 никогда не сможет запустить отсчёт снова: guard
// "!suvidHold.fired" будет вечно ложным после первого же использования режима.
static void test_poweroff_between_sessions_allows_restart() {
  reset_fixture('S', 1.0f, true);

  fakeMillis = 1000;
  TankSensor.avgTemp = mockSetpoint;
  run_tick();
  check(suvidHold.active, "session 1 setup: hold must start");
  const uint32_t deadline1 = suvidHold.deadlineMs;

  fakeMillis = deadline1;
  run_tick();
  check(suvidHold.fired, "session 1 setup: hold must fire");
  check(queueCalls == 1, "session 1 setup: must queue exactly once");

  // Конец сессии 1: питание выключено.
  PowerOn = false;
  fakeMillis += 500;
  run_tick();
  check(!suvidHold.active, "REGRESSION: !PowerOn must reset suvidHold.active");
  check(!suvidHold.fired,
        "REGRESSION: !PowerOn must clear the fired latch, or the hold timer "
        "dies forever after the first use across every following Суvid session");
  check(suvidHold.deadlineMs == 0, "REGRESSION: !PowerOn must reset suvidHold.deadlineMs");

  // Сессия 2: питание снова включено, куб снова достигает уставки - таймер
  // обязан запуститься и завершиться заново, как будто это первая сессия.
  PowerOn = true;
  fakeMillis += 1000;
  TankSensor.avgTemp = mockSetpoint;
  run_tick();
  check(suvidHold.active,
        "REGRESSION: session 2 must be able to start a new hold after session 1 fired");
  const uint32_t deadline2 = suvidHold.deadlineMs;
  check(deadline2 != deadline1, "session 2's deadline must be recomputed, not reused from session 1");

  fakeMillis = deadline2;
  run_tick();
  check(queueCalls == 2,
        "REGRESSION: session 2's hold must fire and queue again "
        "(fired must not persist across PowerOn cycles)");
}

int main() {
  test_scaling_for(1.0f);
  test_scaling_for(5.0f);
  test_guard_wtype_none();
  test_guard_zero_minutes();
  test_fallback_emergency_when_queue_busy();
  test_poweroff_between_sessions_allows_restart();
  if (failures != 0) return 1;
  std::cout << "suvid hold timer behaviour checks passed\n";
  return 0;
}
'''


def extract_thermostat_and_hold_snippet(source: str) -> str:
    body = extract_function_body(source, "inline void check_alarm_suvid")
    start = body.find(THERMOSTAT_START_ANCHOR)
    if start < 0:
        raise ValueError(f"anchor not found in check_alarm_suvid: {THERMOSTAT_START_ANCHOR}")
    return body[start:]


def extract_hold_state_decl(source: str) -> str:
    start = source.find(STRUCT_ANCHOR)
    if start < 0:
        raise ValueError(f"struct not found in suvid.h: {STRUCT_ANCHOR}")
    static_idx = source.find(STATIC_INSTANCE, start)
    if static_idx < 0:
        raise ValueError(f"static instance not found in suvid.h: {STATIC_INSTANCE}")
    return source[start:static_idx + len(STATIC_INSTANCE)]


def extract_heat_delta_define(source: str) -> str:
    idx = source.find("#define HEAT_DELTA")
    if idx < 0:
        raise ValueError("HEAT_DELTA define not found in Samovar_ini.h")
    end = source.find("\n", idx)
    return source[idx:end if end >= 0 else len(source)].strip()


def build_harness(snippet: str, hold_struct: str, heat_delta_define: str) -> str:
    harness = HARNESS_TEMPLATE.replace("@HEAT_DELTA_DEFINE@", heat_delta_define)
    harness = harness.replace("@HOLD_STRUCT@", hold_struct)
    harness = harness.replace("@SNIPPET@", snippet)
    return harness


def main() -> int:
    suvid_path = ROOT / "suvid.h"
    ini_path = ROOT / "Samovar_ini.h"
    if not suvid_path.exists():
        print("FAIL: suvid.h not found", file=sys.stderr)
        return 1
    if not ini_path.exists():
        print("FAIL: Samovar_ini.h not found", file=sys.stderr)
        return 1
    source = suvid_path.read_text(encoding="utf-8", errors="ignore")
    ini_source = ini_path.read_text(encoding="utf-8", errors="ignore")

    try:
        snippet = extract_thermostat_and_hold_snippet(source)
        hold_struct = extract_hold_state_decl(source)
        heat_delta_define = extract_heat_delta_define(ini_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    require_ordered_tokens(
        "suvid thermostat + hold timer wiring (incl. !PowerOn reset)",
        snippet,
        [
            "if (!PowerOn) {",
            "suvidHeaterOn = false;",
            "heater_state = false;",
            "suvidHold = {false, false, 0};",
            "return;",
            "const float setpoint = suvid_target_temp();",
            "const float holdMinutes = program[0].Time;",
            "program[0].WType != PROGRAM_TYPE_NONE",
            "TankSensor.avgTemp >= setpoint",
            "safety_deadline_after(millis(), (uint32_t)(holdMinutes * 60000.0f));",
            "safety_deadline_expired(millis(), suvidHold.deadlineMs)",
            "queue_samovar_command(SAMOVAR_POWER)",
        ],
        errors,
    )
    if "set_power(false)" in snippet:
        errors.append(
            "hold timer must stop the process only via queue_samovar_command/"
            "request_emergency_stop, not a direct set_power(false)"
        )

    if errors:
        print("suvid hold timer smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    harness = build_harness(snippet, hold_struct, heat_delta_define)
    with tempfile.TemporaryDirectory(prefix="samovar-suvid-hold-timer-") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / "suvid_hold_timer_test.cpp"
        binary_path = temp / "suvid_hold_timer_test"
        source_path.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I", str(ROOT),
                str(source_path),
                "-o", str(binary_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run(
            [str(binary_path)], capture_output=True, text=True, check=False
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
