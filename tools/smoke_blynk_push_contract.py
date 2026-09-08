#!/usr/bin/env python3
"""Статическая проверка контракта push-отдачи пинов Blynk (Blynk.ino).

С 2026-09 сервер не опрашивает железо (в эталонном проекте frequency=0): прошивка сама
шлёт пины из blynk_push_tick(), который tick_blynk() (Samovar.ino) зовёт под BlynkLockGuard
после Blynk.run(). Проверяется:
- обработчиков BLYNK_READ не осталось (иначе вернётся двойной путь к тем же данным);
- каждый быстрый пин отдаётся ровно тем выражением, что и раньше (контракт PIN_SPEC.md §2),
  и включён в таблицу kBlynkFastPush; V0/V1/V6/V7/V9/V25/V23 (T2, blynk-log-channel.md)
  из быстрых пинов убраны - те же значения теперь идут 25 полями в V34;
- быстрые пины шлются порциями (BLYNK_PUSH_PER_TICK), а не все за одну итерацию loop();
- медленные пины (V3, V4, V13, V15, V20, V19, V16, V24) шлются из blynk_push_slow
  только при изменении/force, V24 - по отпечатку program[] (blynk_program_fingerprint),
  program_io.h при этом не трогается (он заморожен другими smoke-тестами); V5 (T2) тоже
  убран - дублируется в V34;
- после (пере)подключения всё переотправляется (BLYNK_CONNECTED -> s_blynkPushResendAll),
  и медленные пины повторяются раз в BLYNK_PUSH_SLOW_PERIOD_MS: сервер стирает значения
  виджетов при синхронизации проекта из приложения (2026-09-07: после синхронизации в
  приложении пропали режим и программа);
- tick_blynk() зовёт blynk_push_tick() после Blynk.run();
- V34 (строка лога, staging-буфер blynk_stage_log_line/blynk_push_pending_log_line) и V35
  (начало сессии, blynk_stage_session_start/blynk_push_pending_session_start) кладутся в
  буфер под portENTER_CRITICAL/portEXIT_CRITICAL и уходят из blynk_push_tick() ДО его
  прежней ранней точки возврата (см. T2, blynk-log-channel.md); V35 форсирует
  blynk_push_slow(true) перед своей отправкой, чтобы V24 (программа) сервер получил не
  позже V35.
"""
import shutil
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


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


def pending_v34_snapshot_errors(source: str) -> list[str]:
    required = (
        "portENTER_CRITICAL(&s_blynkLogLineMux);",
        "revision = s_pendingV34Revision;",
        "portEXIT_CRITICAL(&s_blynkLogLineMux);",
        "return ready;",
    )
    return [f"missing {token}" for token in required if token not in source]


def pending_v34_delivery_errors(source: str) -> list[str]:
    required = (
        "if (!ready || !Blynk.connected()) return;",
        "Blynk.virtualWrite(V34, line);",
        "if (!Blynk.connected()) return;",
        "portENTER_CRITICAL(&s_blynkLogLineMux);",
        "if (s_pendingV34Ready && s_pendingV34Revision == revision) s_pendingV34Ready = false;",
        "portEXIT_CRITICAL(&s_blynkLogLineMux);",
    )
    return [f"missing {token}" for token in required if token not in source]


def session_v35_gate_errors(source: str) -> list[str]:
    required = (
        "if (!ready) return true;",
        "if (!Blynk.connected()) return false;",
        "bool sentCurrent = false;",
        "if (s_pendingV35Ready && s_pendingV35Revision == revision) {",
        "s_pendingV35Ready = false;",
        "sentCurrent = true;",
        "return sentCurrent;",
    )
    return [f"missing {token}" for token in required if token not in source]


def idle_v34_snapshot_errors(source: str) -> list[str]:
    build = "if (idleV34Ready) idleV34Line = build_idle_v34_line();"
    gate = "const bool canPushV34 = blynk_push_pending_session_start();"
    send = "Blynk.virtualWrite(V34, idleV34Line);"
    if source.count("blynk_push_pending_session_start()") != 1:
        return ["idle V34 must not add a second V35 gate"]
    if source.find(build) < 0 or source.find(gate) < 0 or source.find(send) < 0:
        return ["idle V34 snapshot tokens are missing"]
    if not source.find(build) < source.find(gate) < source.find(send):
        return ["idle V34 snapshot must precede V35 gate"]
    if "if (canPushV34 && idleV34Ready)" not in source:
        return ["idle V34 must use its pre-gate snapshot only after V35 gate"]
    return []


def session_v35_harness(session_body: str, snapshot_body: str, log_body: str) -> str:
    return f'''#include <cstdint>
#include <cstring>
#include <iostream>
#include <vector>

#define V34 34
#define V35 35

struct portMUX_TYPE {{}};
portMUX_TYPE s_blynkSessionMux;
portMUX_TYPE s_blynkLogLineMux;
void portENTER_CRITICAL(portMUX_TYPE*) {{}}
void portEXIT_CRITICAL(portMUX_TYPE*) {{}}
size_t strlcpy(char* destination, const char* source, size_t size) {{
  const size_t sourceSize = std::strlen(source);
  if (size == 0) return sourceSize;
  std::strncpy(destination, source, size - 1);
  destination[size - 1] = '\\0';
  return sourceSize;
}}

char s_pendingV35Line[320] = "session";
bool s_pendingV35Ready = false;
uint32_t s_pendingV35Revision = 0;
char s_pendingV34Line[288] = "old-log";
bool s_pendingV34Ready = false;
uint32_t s_pendingV34Revision = 0;

struct BlynkProbe {{
  bool isConnected = true;
  bool stageDuringV35 = false;
  std::vector<int> pins;
  std::vector<std::string> payloads;

  bool connected() const {{ return isConnected; }}
  void virtualWrite(int pin, const char* line) {{
    pins.push_back(pin);
    payloads.push_back(line);
    if (pin == V35 && stageDuringV35) {{
      s_pendingV35Ready = true;
      s_pendingV35Revision++;
    }}
  }}
}} Blynk;

void blynk_push_slow(bool) {{}}

static bool blynk_push_pending_session_start() {{
{session_body}
}}

static bool blynk_snapshot_pending_log_line(char (&line)[sizeof(s_pendingV34Line)], uint32_t& revision) {{
{snapshot_body}
}}

static void blynk_push_pending_log_line(const char* line, uint32_t revision, bool ready) {{
{log_body}
}}

int failures = 0;
void check(bool value, const char* message) {{
  if (!value) {{
    std::cerr << "FAIL: " << message << '\\n';
    failures++;
  }}
}}

void reset(bool pending) {{
  Blynk = BlynkProbe{{}};
  s_pendingV35Ready = pending;
  s_pendingV35Revision = 7;
  std::strcpy(s_pendingV34Line, "old-log");
  s_pendingV34Ready = false;
  s_pendingV34Revision = 3;
}}

void run_tick_model() {{
  if (blynk_push_pending_session_start()) Blynk.virtualWrite(V34, "log");
}}

int main() {{
  reset(false);
  run_tick_model();
  check(Blynk.pins == std::vector<int>{{V34}}, "no pending V35 must allow V34");

  reset(true);
  run_tick_model();
  check(Blynk.pins == std::vector<int>{{V35, V34}} && !s_pendingV35Ready,
        "sent current V35 must precede V34");

  reset(true);
  Blynk.stageDuringV35 = true;
  run_tick_model();
  check(Blynk.pins == std::vector<int>{{V35}} && s_pendingV35Ready,
        "interleaved V35 must block V34 and remain pending");

  reset(true);
  Blynk.isConnected = false;
  run_tick_model();
  check(Blynk.pins.empty() && s_pendingV35Ready,
        "disconnected pending V35 must block V34 and remain pending");

  reset(true);
  s_pendingV34Ready = true;
  char v34Snapshot[sizeof(s_pendingV34Line)] = {{}};
  uint32_t v34Revision = 0;
  const bool v34Ready = blynk_snapshot_pending_log_line(v34Snapshot, v34Revision);
  const bool canPushV34 = blynk_push_pending_session_start();
  s_pendingV35Ready = true;
  s_pendingV35Revision++;
  std::strcpy(s_pendingV34Line, "new-log");
  s_pendingV34Ready = true;
  s_pendingV34Revision++;
  if (canPushV34) blynk_push_pending_log_line(v34Snapshot, v34Revision, v34Ready);
  check(Blynk.pins == std::vector<int>{{V35, V34}} && Blynk.payloads[1] == "old-log",
        "after-session V34 must use the pre-V35 snapshot");
  check(s_pendingV34Ready && s_pendingV34Revision == 4 &&
            std::strcmp(s_pendingV34Line, "new-log") == 0,
        "after-session V34 must remain pending for the next tick");
  return failures == 0 ? 0 : 1;
}}
'''


def run_session_v35_harness(session_body: str, snapshot_body: str, log_body: str) -> tuple[int, str]:
    compiler = shutil.which("g++")
    if compiler is None:
        return 1, "g++ is required for V35 ordering harness"
    with tempfile.TemporaryDirectory(prefix="samovar-v35-order-") as directory:
        source = Path(directory) / "harness.cpp"
        binary = Path(directory) / "harness"
        source.write_text(session_v35_harness(session_body, snapshot_body, log_body), encoding="utf-8")
        build = subprocess.run(
            [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
        )
        if build.returncode:
            return build.returncode, build.stdout + build.stderr
        run = subprocess.run([str(binary)], capture_output=True, text=True)
        return run.returncode, run.stdout + run.stderr


blynk = strip_cpp_comments(read_text("Blynk.ino"))
samovar = strip_cpp_comments(read_text("Samovar.ino"))

if blynk and "BLYNK_READ(" in blynk:
    errors.append("BLYNK_READ handlers must be gone: pins are pushed from blynk_push_tick()")
if blynk and "BLYNK_READ_SIMPLE" in blynk:
    errors.append("BLYNK_READ_SIMPLE must not be used (Arduino IDE extern/static conflict)")

fast_pushes = {
    "blynk_push_v2": "Blynk.virtualWrite(V2, WthdrwlProgress);",
    "blynk_push_v8": "Blynk.virtualWrite(V8, get_liquid_volume());",
    "blynk_push_v21": 'Blynk.virtualWrite(V21, "Тек:" + (String)current_power_volt + " Цель:" + (String)target_power_volt);',
    "blynk_push_v27": "Blynk.virtualWrite(V27, json);",
}
removed_fast_pushes = ["blynk_push_v0", "blynk_push_v1", "blynk_push_v6", "blynk_push_v7",
                        "blynk_push_v9", "blynk_push_v25", "blynk_push_v23"]
if blynk:
    for name, write in fast_pushes.items():
        # V21 объявлена с __attribute__((unused)): в сборках без регулятора её нет в таблице.
        attr = " __attribute__((unused))" if name == "blynk_push_v21" else ""
        fn_body = body(blynk, f"static void{attr} {name}()")
        if fn_body and write not in fn_body:
            errors.append(f"{name} must contain: {write}")
    for name in removed_fast_pushes:
        if f" {name}(" in blynk or f"\t{name}(" in blynk:
            errors.append(f"{name} must be removed (T2: значение теперь в V34)")
    strings_body = body(blynk, "static void blynk_push_strings()")
    require_ordered_tokens(
        "blynk_push_strings (один захват замка на V10/V11/V14)",
        strings_body,
        [
            "runtime_state_lock(pdMS_TO_TICKS(50))",
            "timesCopy = WthdrwTimeS + \"; \" + WthdrwTimeAllS;",
            "strCrtCopy = StrCrt;",
            "statusCopy = SamovarStatus;",
            "runtime_state_unlock(true);",
            "Blynk.virtualWrite(V10, timesCopy);",
            "Blynk.virtualWrite(V11, strCrtCopy);",
            "Blynk.virtualWrite(V14, statusCopy);",
        ],
        errors,
    )
    if strings_body.count("runtime_state_lock(") != 1:
        errors.append("blynk_push_strings must take runtime_state_lock exactly once")

    table_start = blynk.find("static const BlynkPushFn kBlynkFastPush[] = {")
    table = blynk[table_start: blynk.find("};", table_start)] if table_start >= 0 else ""
    if not table:
        errors.append("kBlynkFastPush table not found")
    for name in list(fast_pushes) + ["blynk_push_strings"]:
        if table and name not in table:
            errors.append(f"{name} missing from kBlynkFastPush")

    slow_body = body(blynk, "static void blynk_push_slow(bool force)")
    for write in [
        "Blynk.virtualWrite(V3, process);",
        "Blynk.virtualWrite(V4, (int)PowerOn);",
        "Blynk.virtualWrite(V13, (int)PauseOn);",
        "Blynk.virtualWrite(V15, ip);",
        "Blynk.virtualWrite(V20, Samovar_Mode);",
        "Blynk.virtualWrite(V19, SAMOVAR_VERSION);",
        "Blynk.virtualWrite(V16, target_power_volt);",
        "Blynk.virtualWrite(V24, serialize_program_for_mode(Samovar_Mode));",
    ]:
        if slow_body and write not in slow_body:
            errors.append(f"blynk_push_slow must contain: {write}")
    require_ordered_tokens(
        "blynk_push_slow V15 uses ipst snapshot",
        slow_body,
        ["ipst_copy(ip);", "String(ip)", "Blynk.virtualWrite(V15, ip);"],
        errors,
    )
    if slow_body and "Blynk.virtualWrite(V5" in slow_body:
        errors.append("blynk_push_slow must NOT send V5 anymore (T2: дублируется в V34)")
    if slow_body and "blynk_program_fingerprint()" not in slow_body:
        errors.append("blynk_push_slow must gate V24 by blynk_program_fingerprint()")
    fp_body = body(blynk, "static uint32_t blynk_program_fingerprint()")
    for token in ("sizeof(WProgram) * PROGRAM_END", "ProgramLen"):
        if fp_body and token not in fp_body:
            errors.append(f"blynk_program_fingerprint must cover {token}")

    tick_body = body(blynk, "void blynk_push_tick()")
    require_ordered_tokens(
        "blynk_push_tick (V34/V35 pending до ранней точки return, порции, период, переотправка)",
        tick_body,
        [
            "const bool idleV34Ready = startval == SAMOVAR_STARTVAL_IDLE",
            "if (idleV34Ready) idleV34Line = build_idle_v34_line();",
            "const bool pendingV34Ready = blynk_snapshot_pending_log_line(pendingV34Line, pendingV34Revision);",
            "const bool canPushV34 = blynk_push_pending_session_start();",
            "if (canPushV34) blynk_push_pending_log_line(pendingV34Line, pendingV34Revision, pendingV34Ready);",
            "if (canPushV34 && idleV34Ready)",
            "Blynk.virtualWrite(V34, idleV34Line);",
            "BLYNK_PUSH_PERIOD_MS",
            "now - slowSentAt >= BLYNK_PUSH_SLOW_PERIOD_MS",
            "blynk_push_slow(force);",
            "if (force) slowSentAt = now;",
            "s_blynkPushResendAll = false;",
            "n < BLYNK_PUSH_PER_TICK",
            "kBlynkFastPush[next++]();",
        ],
        errors,
    )
    for problem in idle_v34_snapshot_errors(tick_body):
        errors.append(f"blynk_push_tick idle V34 snapshot: {problem}")
    idle_build = "if (idleV34Ready) idleV34Line = build_idle_v34_line();"
    idle_gate = "const bool canPushV34 = blynk_push_pending_session_start();"
    idle_late_mutant = tick_body.replace(idle_build, "", 1).replace(
        idle_gate, idle_gate + "\n  " + idle_build, 1
    )
    if "idle V34 snapshot must precede V35 gate" not in idle_v34_snapshot_errors(idle_late_mutant):
        errors.append("idle V34 post-gate snapshot mutation survived")
    resend_body = body(blynk, "BLYNK_WRITE(V33)")
    if resend_body and "s_blynkPushResendAll = true;" not in resend_body:
        errors.append("BLYNK_WRITE(V33) must request full resend (s_blynkPushResendAll = true)")
    connected_body = body(blynk, "BLYNK_CONNECTED()")
    if connected_body and "s_blynkPushResendAll = true;" not in connected_body:
        errors.append("BLYNK_CONNECTED must request full resend (s_blynkPushResendAll = true)")

    # V34 (строка лога, T2): staging-буфер под критической секцией, приём - из
    # blynk_push_tick() выше. Пишущая сторона (SysTicker, Samovar.ino) не должна звать
    # библиотеку Blynk напрямую - только копировать строку под portENTER/EXIT_CRITICAL.
    stage_log_body = body(blynk, "void blynk_stage_log_line(const String& line)")
    require_ordered_tokens(
        "blynk_stage_log_line (атомарная запись под критической секцией)",
        stage_log_body,
        ["portENTER_CRITICAL(&s_blynkLogLineMux);", "strlcpy(s_pendingV34Line", "portEXIT_CRITICAL(&s_blynkLogLineMux);"],
        errors,
    )
    if stage_log_body and "Blynk." in stage_log_body:
        errors.append("blynk_stage_log_line must not call Blynk library directly (staging only)")
    if "s_pendingV34Revision++;" not in stage_log_body:
        errors.append("blynk_stage_log_line must advance V34 revision")

    snapshot_log_body = body(
        blynk,
        "static bool blynk_snapshot_pending_log_line(char (&line)[sizeof(s_pendingV34Line)], uint32_t& revision)",
    )
    for problem in pending_v34_snapshot_errors(snapshot_log_body):
        errors.append(f"blynk_snapshot_pending_log_line contract: {problem}")
    pending_log_body = body(blynk, "static void blynk_push_pending_log_line(const char* line, uint32_t revision, bool ready)")
    for problem in pending_v34_delivery_errors(pending_log_body):
        errors.append(f"blynk_push_pending_log_line delivery contract: {problem}")

    # V35 (начало сессии, T2): тот же приём, плюс форс-переотправка медленных пинов ДО
    # самой отправки V35 - см. session_begin()/архитектурное обоснование в T2.md.
    stage_session_body = body(blynk, "void blynk_stage_session_start(const String& line)")
    require_ordered_tokens(
        "blynk_stage_session_start (атомарная запись под критической секцией)",
        stage_session_body,
        ["portENTER_CRITICAL(&s_blynkSessionMux);", "strlcpy(s_pendingV35Line", "portEXIT_CRITICAL(&s_blynkSessionMux);"],
        errors,
    )
    if stage_session_body and "Blynk." in stage_session_body:
        errors.append("blynk_stage_session_start must not call Blynk library directly (staging only)")
    if stage_session_body.count("s_pendingV35Revision++;") != 2:
        errors.append("blynk_stage_session_start must advance V35 revision on both staging paths")

    pending_session_body = body(blynk, "static bool blynk_push_pending_session_start()")
    for problem in session_v35_gate_errors(pending_session_body):
        errors.append(f"blynk_push_pending_session_start V35/V34 gate: {problem}")
    require_ordered_tokens(
        "blynk_push_pending_session_start (slow pins before V35)",
        pending_session_body,
        ["if (!ready) return true;", "blynk_push_slow(true);", "Blynk.virtualWrite(V35, line);", "return sentCurrent;"],
        errors,
    )
    if pending_session_body:
        returncode, output = run_session_v35_harness(
            pending_session_body, snapshot_log_body, pending_log_body
        )
        if returncode:
            errors.append(f"V35/V34 interleaving harness failed: {output}")
        revision_mutant = pending_session_body.replace(
            "s_pendingV35Revision == revision", "s_pendingV35Revision >= revision", 1
        )
        returncode, output = run_session_v35_harness(
            revision_mutant, snapshot_log_body, pending_log_body
        )
        if returncode == 0 or "interleaved V35 must block V34 and remain pending" not in output:
            errors.append("V35 revision interleaving mutation survived or failed for the wrong reason")

    for label, mutant in (
        ("disconnect guard", pending_log_body.replace(" || !Blynk.connected()", "", 1)),
        ("revision guard", pending_log_body.replace(
            "s_pendingV34Revision == revision", "s_pendingV34Revision >= revision", 1
        )),
    ):
        if not pending_v34_delivery_errors(mutant):
            errors.append(f"{label} mutation survived V34 delivery contract")
    revision_mutant = pending_log_body.replace(
        "s_pendingV34Revision == revision", "s_pendingV34Revision >= revision", 1
    )
    returncode, output = run_session_v35_harness(
        pending_session_body, snapshot_log_body, revision_mutant
    )
    if returncode == 0 or "after-session V34 must remain pending for the next tick" not in output:
        errors.append("V34 post-session revision mutation survived or failed for the wrong reason")

if samovar:
    require_ordered_tokens(
        "tick_blynk зовёт push после Blynk.run()",
        body(samovar, "static void tick_blynk()"),
        ["BlynkLockGuard", "Blynk.run();", "blynk_push_tick();"],
        errors,
    )

if errors:
    print("Blynk push contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Blynk push contract smoke check passed")
