#!/usr/bin/env python3
"""Проверка снимка F, V27 и надёжной отправки F1 после V35."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]


def body(source: str, signature: str) -> str:
    return extract_function_body(source, signature, strip_comments=False)


def source_errors(cheese: str, samovar: str, blynk: str) -> list[str]:
    errors: list[str] = []
    try:
        telemetry = body(cheese, "inline void cheese_capture_floc_telemetry(uint32_t nowMs, CheeseFlocTelemetry& value)")
        remaining = body(cheese, "inline uint32_t cheese_f_remaining_seconds(uint32_t deadlineSeconds, uint32_t nowMs)")
        capture = body(samovar, "static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot(")
        ajax = body(samovar, "static void writeAjaxTelemetryFields(")
        v27 = body(blynk, "static void write_blynk_mode_json(Print& out, const AjaxTelemetrySnapshot& s)")
        f1_stage = body(blynk, "void blynk_stage_floc_event(const String& line)")
        f1_session = body(blynk, "static bool blynk_push_pending_floc_session_start()")
        f1_push = body(blynk, "static void blynk_push_pending_floc_event()")
        tick = body(blynk, "void blynk_push_tick()")
    except ValueError as exc:
        return [str(exc)]

    for token in (
        "if (!cheese_runtime_active() || program[ProgramNum].WType != 'F') return;",
        "value.fixed = cheeseRuntime.flocFixed;",
        "program_load_cheese_f_multiplier(row)",
        "value.actualSeconds = cheeseRuntime.flocActualSeconds;",
        "value.cutSeconds = cheeseRuntime.flocCutSeconds;",
        "cheese_f_remaining_seconds(value.cutSeconds, nowMs)",
        "cheese_f_remaining_seconds(cheese_f_timeout_seconds(row), nowMs)",
    ):
        if token not in telemetry:
            errors.append(f"снимок F не содержит: {token}")
    for token in (
        "const uint32_t elapsedMs = nowMs - cheeseRuntime.enteredMs;",
        "if (elapsedMs >= deadlineMs) return 0;",
        "remainingMs / 1000UL + (remainingMs % 1000UL != 0 ? 1UL : 0UL)",
    ):
        if token not in remaining:
            errors.append(f"остаток F не содержит: {token}")
    for field in (
        "snapshot.cheeseFlocActive = flocTelemetry.active;",
        "snapshot.cheeseFlocFixed = flocTelemetry.fixed;",
        "snapshot.cheeseFlocActualSeconds = flocTelemetry.actualSeconds;",
        "snapshot.cheeseFlocMultiplierMilli = flocTelemetry.multiplierMilli;",
        "snapshot.cheeseFlocCutSeconds = flocTelemetry.cutSeconds;",
        "snapshot.cheeseFlocRemainingSeconds = flocTelemetry.remainingSeconds;",
    ):
        if field not in capture:
            errors.append(f"Ajax-снимок не копирует поле F: {field}")
    for key in (
        "CheeseFlocActive", "CheeseFlocFixed", "CheeseFlocActualSeconds",
        "CheeseFlocMultiplierMilli", "CheeseFlocCutSeconds", "CheeseFlocRemainingSeconds",
    ):
        if f'"{key}"' not in ajax:
            errors.append(f"/ajax не отдаёт поле F: {key}")

    require_ordered_tokens(
        "V27 F",
        v27,
        [
            "if (s.cheeseFlocActive)",
            'jsonFieldBool(out, first, "ff", s.cheeseFlocFixed);',
            'jsonFieldRaw(out, first, "fm", s.cheeseFlocMultiplierMilli);',
            "if (s.cheeseFlocFixed)",
            'jsonFieldRaw(out, first, "fa", s.cheeseFlocActualSeconds);',
            'jsonFieldRaw(out, first, "fc", s.cheeseFlocCutSeconds);',
            'jsonFieldRaw(out, first, "fr", s.cheeseFlocRemainingSeconds);',
        ],
        errors,
    )
    for field in ("cheeseFlocActive", "cheeseFlocFixed", "cheeseFlocActualSeconds",
                  "cheeseFlocMultiplierMilli", "cheeseFlocCutSeconds", "cheeseFlocRemainingSeconds"):
        if f"s.{field}" not in v27:
            errors.append(f"V27 читает F не из общего снимка: {field}")

    for token in (
        "sessionReady = s_pendingV35Ready;",
        "strlcpy(sessionLine, s_pendingV35Line, sizeof(sessionLine));",
        "if (!s_pendingF1Ready)",
        "strlcpy(s_pendingF1Line, line.c_str(), sizeof(s_pendingF1Line));",
        "s_pendingF1SessionReady = sessionReady;",
        "s_pendingF1SessionRevision = s_pendingF1Revision;",
        "s_pendingF1SessionV35Revision = sessionRevision;",
        "s_pendingF1Ready = true;",
    ):
        if token not in f1_stage:
            errors.append(f"F1 не ставится в pending-слот: {token}")
    require_ordered_tokens(
        "сохранённый V35 перед F1",
        f1_session,
        [
            "if (!ready) return true;",
            "if (!Blynk.connected()) return false;",
            "Blynk.virtualWrite(V35, line);",
            "if (!Blynk.connected()) return false;",
            "s_pendingF1SessionReady = false;",
            "s_pendingV35Revision == sessionRevision",
            "strcmp(s_pendingV35Line, line) == 0",
            "s_pendingV35Ready = false;",
        ],
        errors,
    )
    require_ordered_tokens(
        "отправка pending F1",
        f1_push,
        [
            "if (!ready || !Blynk.connected()) return;",
            "Blynk.virtualWrite(V26, line);",
            "if (!Blynk.connected()) return;",
            "if (s_pendingF1Ready && s_pendingF1Revision == revision) s_pendingF1Ready = false;",
        ],
        errors,
    )
    require_ordered_tokens(
        "V35 перед F1",
        tick,
        [
            "const bool canPushF1 = blynk_push_pending_floc_session_start();",
            "if (canPushF1) blynk_push_pending_floc_event();",
            "const bool canPushV34 = blynk_push_pending_session_start();",
            "if (canPushV34) blynk_push_pending_log_line(",
        ],
        errors,
    )
    return errors


def compile_and_run(source: str, label: str) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        cpp = Path(directory) / "check.cpp"
        binary = Path(directory) / "check"
        cpp.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            text=True, capture_output=True,
        )
        if compile_result.returncode:
            return [f"{label}: компиляция не прошла: {compile_result.stderr.strip()}"]
        run_result = subprocess.run([str(binary)], text=True, capture_output=True)
        if run_result.returncode:
            return [f"{label}: {run_result.stderr.strip()}"]
    return []


def telemetry_harness(cheese: str) -> str:
    timeout = body(cheese, "inline uint32_t cheese_f_timeout_seconds(const WProgram& row)")
    remaining = body(cheese, "inline uint32_t cheese_f_remaining_seconds(uint32_t deadlineSeconds, uint32_t nowMs)")
    capture = body(cheese, "inline void cheese_capture_floc_telemetry(uint32_t nowMs, CheeseFlocTelemetry& value)")
    return f'''#include <cmath>
#include <cstdint>
#include <iostream>
using std::ceil;
struct WProgram {{ char WType; float Time; uint32_t FlocMultiplierMilli; }};
struct CheeseRuntimeState {{ uint32_t enteredMs, flocActualSeconds, flocMultiplierMilli, flocCutSeconds; bool flocFixed; }} cheeseRuntime = {{}};
struct CheeseFlocTelemetry {{ bool active, fixed; uint32_t actualSeconds, multiplierMilli, cutSeconds, remainingSeconds; }};
static WProgram program[20] = {{}};
static uint8_t ProgramNum = 0, ProgramLen = 1;
static const uint8_t PROGRAM_END = 20;
static const int SAMOVAR_CHEESE_MODE = 7, SAMOVAR_STATUS_CHEESE = 5000, SAMOVAR_STARTVAL_CHEESE_START = 7000;
static int Samovar_Mode = SAMOVAR_CHEESE_MODE, SamovarStatusInt = SAMOVAR_STATUS_CHEESE, startval = SAMOVAR_STARTVAL_CHEESE_START + 1;
static bool PowerOn = true, cheeseFinishPending = false;
inline bool cheese_runtime_active() {{ return Samovar_Mode == SAMOVAR_CHEESE_MODE && SamovarStatusInt == SAMOVAR_STATUS_CHEESE && PowerOn && startval > SAMOVAR_STARTVAL_CHEESE_START && !cheeseFinishPending && ProgramNum < ProgramLen && ProgramNum < PROGRAM_END; }}
inline uint32_t program_load_cheese_f_multiplier(const WProgram& row) {{ return row.FlocMultiplierMilli; }}
inline uint32_t cheese_f_timeout_seconds(const WProgram& row) {{ {timeout} }}
inline uint32_t cheese_f_remaining_seconds(uint32_t deadlineSeconds, uint32_t nowMs) {{ {remaining} }}
inline void cheese_capture_floc_telemetry(uint32_t nowMs, CheeseFlocTelemetry& value) {{ {capture} }}
static int failures = 0;
static void check(bool ok, const char* text) {{ if (!ok) {{ std::cerr << text << '\\n'; ++failures; }} }}
int main() {{
  program[0] = {{'F', 1.0f, 2500}};
  cheeseRuntime.enteredMs = 0;
  CheeseFlocTelemetry value{{}};
  cheese_capture_floc_telemetry(1001, value);
  check(value.active && !value.fixed && value.multiplierMilli == 2500 && value.remainingSeconds == 59 && value.actualSeconds == 0 && value.cutSeconds == 0, "F до фиксации");
  cheeseRuntime.flocFixed = true; cheeseRuntime.flocActualSeconds = 12; cheeseRuntime.flocMultiplierMilli = 2500; cheeseRuntime.flocCutSeconds = 30;
  cheese_capture_floc_telemetry(12001, value);
  check(value.active && value.fixed && value.actualSeconds == 12 && value.multiplierMilli == 2500 && value.cutSeconds == 30 && value.remainingSeconds == 18, "F после фиксации");
  cheeseRuntime.enteredMs = 0xfffffff0UL; cheeseRuntime.flocFixed = false;
  cheese_capture_floc_telemetry(984, value);
  check(value.active && value.remainingSeconds == 59, "F через переполнение millis");
  program[0].WType = 'H'; cheese_capture_floc_telemetry(984, value);
  check(!value.active && !value.fixed && value.actualSeconds == 0 && value.multiplierMilli == 0 && value.cutSeconds == 0 && value.remainingSeconds == 0, "поля F вне F сброшены");
  return failures;
}}
'''


def delivery_harness(blynk: str) -> str:
    stage = body(blynk, "void blynk_stage_floc_event(const String& line)")
    v35_push = body(blynk, "static bool blynk_push_pending_session_start()")
    session = body(blynk, "static bool blynk_push_pending_floc_session_start()")
    push = body(blynk, "static void blynk_push_pending_floc_event()")
    tick = body(blynk, "void blynk_push_tick()")
    return f'''#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
class String {{ public: String() = default; String(const char* value) : value_(value) {{}} const char* c_str() const {{ return value_.c_str(); }} private: std::string value_; }};
size_t strlcpy(char* dst, const char* src, size_t size) {{ size_t length = std::strlen(src); if (size) {{ size_t count = length < size - 1 ? length : size - 1; std::memcpy(dst, src, count); dst[count] = 0; }} return length; }}
struct Mux {{}}; static Mux s_blynkFlocMux, s_blynkSessionMux;
#define portENTER_CRITICAL(x) do {{ (void)(x); }} while (0)
#define portEXIT_CRITICAL(x) do {{ (void)(x); }} while (0)
static char s_pendingV35Line[320] = {{}}; static bool s_pendingV35Ready = false; static uint32_t s_pendingV35Revision = 0;
static char s_pendingF1Line[512] = {{}}; static bool s_pendingF1Ready = false; static uint32_t s_pendingF1Revision = 0;
static char s_pendingF1SessionLine[320] = {{}}; static bool s_pendingF1SessionReady = false; static uint32_t s_pendingF1SessionRevision = 0; static uint32_t s_pendingF1SessionV35Revision = 0;
static char s_pendingV34Line[288] = {{}}; static bool s_pendingV34Ready = false; static uint32_t s_pendingV34Revision = 0;
static const int V26 = 26, V34 = 34, V35 = 35;
struct FakeBlynk {{ bool online = false; std::vector<std::string> writes; bool connected() const {{ return online; }} void virtualWrite(int pin, const char* value) {{ if (pin == V26 || pin == V35) writes.push_back(std::to_string(pin) + ":" + value); }} void virtualWrite(int pin, const String& value) {{ virtualWrite(pin, value.c_str()); }} }} Blynk;
static void blynk_push_slow(bool) {{}}
static void stage_session(const char* value) {{ strlcpy(s_pendingV35Line, value, sizeof(s_pendingV35Line)); ++s_pendingV35Revision; s_pendingV35Ready = true; }}
static bool blynk_snapshot_pending_log_line(char (&line)[sizeof(s_pendingV34Line)], uint32_t& revision) {{ if (!s_pendingV34Ready) return false; strlcpy(line, s_pendingV34Line, sizeof(line)); revision = s_pendingV34Revision; return true; }}
static void blynk_push_pending_log_line(const char*, uint32_t, bool) {{}}
static String build_idle_v34_line() {{ return String(""); }}
static unsigned long fakeMillis = 10000; static unsigned long millis() {{ return fakeMillis; }}
static const int SAMOVAR_STARTVAL_IDLE = 0; static int startval = 1;
static bool s_blynkPushResendAll = false; static const uint8_t kBlynkFastPushCount = 0; static const unsigned long BLYNK_PUSH_PERIOD_MS = 5000, BLYNK_PUSH_SLOW_PERIOD_MS = 60000; static const uint8_t BLYNK_PUSH_PER_TICK = 3; typedef void (*PushFn)(); static PushFn kBlynkFastPush[1] = {{nullptr}};
void blynk_stage_floc_event(const String& line) {{ {stage} }}
static bool blynk_push_pending_session_start() {{ {v35_push} }}
static bool blynk_push_pending_floc_session_start() {{ {session} }}
static void blynk_push_pending_floc_event() {{ {push} }}
void blynk_push_tick() {{ {tick} }}
static int failures = 0; static void check(bool ok, const char* text) {{ if (!ok) {{ std::cerr << text << '\\n'; ++failures; }} }}
static void reset_pending() {{ s_pendingV35Line[0] = s_pendingF1Line[0] = s_pendingF1SessionLine[0] = 0; s_pendingV35Ready = s_pendingF1Ready = s_pendingF1SessionReady = false; s_pendingV35Revision = s_pendingF1Revision = s_pendingF1SessionRevision = s_pendingF1SessionV35Revision = 0; Blynk.writes.clear(); Blynk.online = true; }}
int main() {{
  reset_pending(); stage_session("A");
  blynk_stage_floc_event(String("@F1;s=00000001"));
  check(s_pendingF1SessionReady && std::string(s_pendingF1SessionLine) == "A" && s_pendingF1SessionV35Revision == s_pendingV35Revision, "F1 не сохранил свой V35 и его ревизию");
  blynk_push_tick();
  check(!s_pendingV35Ready && !s_pendingF1Ready && Blynk.writes.size() == 2 && Blynk.writes[0] == "35:A" && Blynk.writes[1] == "26:@F1;s=00000001", "A-only повторно отправил V35 или нарушил V35->F1");

  reset_pending(); stage_session("A");
  blynk_stage_floc_event(String("@F1;s=00000001"));
  blynk_stage_floc_event(String("@F1;s=00000002"));
  check(s_pendingF1Ready && s_pendingF1Revision == 1, "повтор создал второй pending F1");
  stage_session("B");
  check(std::string(s_pendingV35Line) == "B", "новая офлайн-сессия не сменила общий V35");
  blynk_push_tick();
  check(!s_pendingV35Ready && std::string(s_pendingV35Line) == "B" && !s_pendingF1Ready && Blynk.writes.size() == 3 && Blynk.writes[0] == "35:A" && Blynk.writes[1] == "26:@F1;s=00000001" && Blynk.writes[2] == "35:B", "A->F1-A->B нарушен или B потерян");
  return failures;
}}
'''


def main() -> int:
    cheese = (ROOT / "cheese.h").read_text(encoding="utf-8")
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    blynk = (ROOT / "Blynk.ino").read_text(encoding="utf-8")
    errors = source_errors(cheese, samovar, blynk)
    errors += compile_and_run(telemetry_harness(cheese), "снимок F")
    errors += compile_and_run(delivery_harness(blynk), "доставка F1")

    mutations = (
        ("V27 ff", blynk.replace('jsonFieldBool(out, first, "ff", s.cheeseFlocFixed);', "", 1)),
        ("F1 после V35", blynk.replace("if (canPushF1) blynk_push_pending_floc_event();", "", 1)),
        ("V35 A перед F1", blynk.replace("const bool canPushF1 = blynk_push_pending_floc_session_start();", "const bool canPushF1 = true;", 1)),
        ("F1 без V35 A", blynk.replace("s_pendingF1SessionReady = sessionReady;", "s_pendingF1SessionReady = false;", 1)),
        ("разные ревизии V35/F1", blynk.replace("s_pendingF1SessionRevision = s_pendingF1Revision;", "s_pendingF1SessionRevision = s_pendingV35Revision;", 1)),
        ("очистка F1 до отправки", blynk.replace("if (!Blynk.connected()) return;\n\n  portENTER_CRITICAL(&s_blynkFlocMux);", "portENTER_CRITICAL(&s_blynkFlocMux);", 1)),
        ("очистка A-only V35", blynk.replace("s_pendingV35Revision == sessionRevision", "false", 1)),
        ("ревизия V35 для F1", blynk.replace("s_pendingF1SessionV35Revision = sessionRevision;", "s_pendingF1SessionV35Revision = 0;", 1)),
        ("снимок без fm", cheese.replace("                                       program_load_cheese_f_multiplier(row);", "                                       0;", 1)),
    )
    for label, mutated in mutations:
        mutation_errors = source_errors(mutated if label == "снимок без fm" else cheese,
                                        samovar,
                                        mutated if label != "снимок без fm" else blynk)
        if not mutation_errors:
            errors.append(f"мутация пережила проверку: {label}")
        if label == "очистка A-only V35" and not compile_and_run(delivery_harness(mutated), "мутация A-only V35"):
            errors.append(f"мутация пережила поведенческий blynk_push_tick: {label}")

    if errors:
        print("Cheese F telemetry/F1 checks failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print("Cheese F telemetry, V27 and V35→F1 delivery checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
