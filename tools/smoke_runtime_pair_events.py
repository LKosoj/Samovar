#!/usr/bin/env python3
"""P02 PairCore: source-derived `@P1` serializer and active-pair RAM contract."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "runtime_pair_events.h"
SAMOVAR = ROOT / "Samovar.ino"


def compile_and_run(header: str) -> tuple[bool, int, str]:
    source = r'''
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <climits>
#include <cstdlib>
#include <string>
#include <vector>
#define F(value) value
class String {
 public:
  String(const char* value) : value_(value) {}
  const std::string& value() const { return value_; }
 private:
  std::string value_;
};
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };
static bool runtimeLockHeld = false;
static std::vector<std::string> sent;
void SendMsg(const String& text, MESSAGE_TYPE) {
  if (runtimeLockHeld) std::abort();
  sent.push_back(text.value());
}
static int64_t fakeMicros = 0;
int64_t esp_timer_get_time() { return fakeMicros; }
uint32_t millis() { return 7; }
constexpr uint32_t NTP_PLAUSIBLE_MIN_EPOCH = 1700000000UL;
#include "runtime_pair_events.h"

static bool has(const std::string& value, const char* token) {
  return value.find(token) != std::string::npos;
}
static bool expect(bool value, const char* message) {
  if (!value) std::fprintf(stderr, "ASSERT: %s\\n", message);
  return value;
}
static int expect(bool value, int code) {
  if (!value) std::fprintf(stderr, "ASSERT: contract check %d failed\\n", code);
  return value ? 0 : code;
}

int main() {
  RuntimePairState state;
  runtime_pair_state_init(state, 0xA1B2C3D4UL);
  RuntimePairPendingEvent pending;
  fakeMicros = 0x100000002ULL * 1000ULL;
  const uint64_t monotonic = runtime_pair_monotonic_ms();
  if (!expect(monotonic == 0x100000002ULL, "monotonic time keeps 64-bit value")) return 1;
  if (!expect(runtime_pair_utc_epoch(1700010800UL, 3) == 1700000000UL, "UTC subtracts positive timezone")) return 2;
  if (!expect(runtime_pair_utc_epoch(1700018000UL, 5) == 1700000000UL, "UTC subtracts five-hour timezone")) return 3;

  const std::string fullTail = std::string(106, 'x') + "\xD0\xAF";
  RuntimePairEventFacts first = {0x10203040UL, 7, RUNTIME_PAIR_ROW_NONE, 23,
                                 monotonic, 1700018100UL, 5};
  runtimeLockHeld = true;
  if (!expect(runtime_pair_prepare_begin(state, first, fullTail.c_str(), WARNING_MSG, pending) == RUNTIME_PAIR_PREPARED, "begin prepares valid full payload")) return 4;
  runtimeLockHeld = false;
  if (!expect(pending.ready && std::strlen(pending.payload) == 198, "payload has exact 198-byte boundary")) return 5;
  if (!expect(has(pending.payload, "@P1;s=10203040;b=A1B2C3D4;p=00000001;e=B;m=7;r=FF;q=17;o=FF;t=0000000100000002;u=6553F164|"), "begin header contains full identity and UTC")) return 6;
  if (!expect(runtime_pair_dispatch(pending) == RUNTIME_PAIR_SENT_TO_SENDMSG && sent.size() == 1, "dispatch occurs after runtime unlock")) return 7;
  runtimeLockHeld = true;
  if (!expect(runtime_pair_prepare_begin(state, first, "duplicate", WARNING_MSG, pending) == RUNTIME_PAIR_DUPLICATE && !pending.ready, "duplicate begin is silent")) return 8;
  RuntimePairEventFacts changed = {0xFFFFFFFFUL, 0, 1, 23, monotonic + 1, 1700010900UL, 3};
  if (!expect(runtime_pair_prepare_end(state, changed, RUNTIME_PAIR_USER_STOP, "Остановлено", WARNING_MSG, pending) == RUNTIME_PAIR_PREPARED, "end preserves begin identity")) return 9;
  runtimeLockHeld = false;
  if (!expect(has(pending.payload, ";s=10203040;") && has(pending.payload, ";e=E;m=7;r=FF;q=17;o=02;") && has(pending.payload, ";u=6553F164|"), "end keeps begin session mode row and outcome")) return 10;
  if (!expect(runtime_pair_dispatch(pending) == RUNTIME_PAIR_SENT_TO_SENDMSG && sent.size() == 2, "end dispatches once")) return 11;
  runtimeLockHeld = true;
  if (!expect(runtime_pair_prepare_end(state, changed, RUNTIME_PAIR_USER_STOP, "again", WARNING_MSG, pending) == RUNTIME_PAIR_DUPLICATE && !pending.ready, "inactive end is silent")) return 12;

  RuntimePairEventFacts causeOne = {1, 0, 1, 1, 10, 0, 3};
  RuntimePairEventFacts causeTwo = {1, 0, 2, 2, 11, 0, 3};
  if (expect(runtime_pair_prepare_begin(state, causeOne, "one", NOTIFY_MSG, pending) == RUNTIME_PAIR_PREPARED, 13)) return 13;
  runtimeLockHeld = false; runtime_pair_dispatch(pending); runtimeLockHeld = true;
  if (expect(runtime_pair_prepare_begin(state, causeTwo, "two", NOTIFY_MSG, pending) == RUNTIME_PAIR_PREPARED, 14)) return 14;
  runtimeLockHeld = false; runtime_pair_dispatch(pending); runtimeLockHeld = true;
  if (expect(runtime_pair_prepare_end(state, causeOne, RUNTIME_PAIR_RESUMED, "one end", NOTIFY_MSG, pending) == RUNTIME_PAIR_PREPARED, 15)) return 15;
  runtimeLockHeld = false; runtime_pair_dispatch(pending); runtimeLockHeld = true;
  if (expect(runtime_pair_prepare_end(state, causeTwo, RUNTIME_PAIR_ROW_CHANGE, "two end", NOTIFY_MSG, pending) == RUNTIME_PAIR_PREPARED, 16)) return 16;
  runtimeLockHeld = false; runtime_pair_dispatch(pending); runtimeLockHeld = true;

  for (uint8_t outcome = RUNTIME_PAIR_RESUMED; outcome <= RUNTIME_PAIR_ERROR; outcome++) {
    RuntimePairEventFacts facts = {2, 1, static_cast<uint8_t>(outcome + 1), static_cast<uint8_t>(outcome + 3), 20, 0, 3};
    if (expect(runtime_pair_prepare_begin(state, facts, "begin", WARNING_MSG, pending) == RUNTIME_PAIR_PREPARED, 20 + outcome)) return 20 + outcome;
    runtimeLockHeld = false; runtime_pair_dispatch(pending); runtimeLockHeld = true;
    if (expect(runtime_pair_prepare_end(state, facts, static_cast<RuntimePairOutcome>(outcome), "end", WARNING_MSG, pending) == RUNTIME_PAIR_PREPARED, 30 + outcome)) return 30 + outcome;
    const char outcomes[] = "01234";
    runtimeLockHeld = false;
    if (expect(has(pending.payload, (std::string(";o=0") + outcomes[outcome] + ";").c_str()), 40 + outcome)) return 40 + outcome;
    runtime_pair_dispatch(pending); runtimeLockHeld = true;
  }

  const std::string tooLong(109, 'x');
  RuntimePairEventFacts sizeFacts = {3, 2, 1, 14, 30, 1700010801UL, 3};
  if (expect(runtime_pair_prepare_begin(state, sizeFacts, tooLong.c_str(), WARNING_MSG, pending) == RUNTIME_PAIR_TEXT_TOO_LONG && !pending.ready, 50)) return 50;
  if (expect(runtime_pair_prepare_begin(state, sizeFacts, "\xC0\xAF", WARNING_MSG, pending) == RUNTIME_PAIR_TEXT_INVALID_UTF8 && !pending.ready, 51)) return 51;
  if (expect(runtime_pair_prepare_begin(state, sizeFacts, "", WARNING_MSG, pending) == RUNTIME_PAIR_TEXT_EMPTY && !pending.ready, 52)) return 52;
  RuntimePairEventFacts invalid = {0, 8, 0, 0, 1, 0, 0};
  if (expect(runtime_pair_prepare_begin(state, invalid, "bad", WARNING_MSG, pending) == RUNTIME_PAIR_INVALID_ARGUMENT, 53)) return 53;

  runtime_pair_state_init(state, 0xCAFEBABEUL);
  if (expect(runtime_pair_prepare_end(state, changed, RUNTIME_PAIR_ERROR, "no invented end", WARNING_MSG, pending) == RUNTIME_PAIR_DUPLICATE && !pending.ready, 54)) return 54;
  RuntimePairEventFacts secondSession = {2, 2, 1, 1, 44, 0, 3};
  if (expect(runtime_pair_prepare_begin(state, secondSession, "new boot", WARNING_MSG, pending) == RUNTIME_PAIR_PREPARED && has(pending.payload, ";b=CAFEBABE;p=00000001;"), 55)) return 55;
  return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="samovar-runtime-pair-") as temp:
        temp_path = Path(temp)
        (temp_path / "esp_timer.h").write_text("#include <cstdint>\nint64_t esp_timer_get_time();\n", encoding="utf-8")
        (temp_path / "runtime_pair_events.h").write_text(header, encoding="utf-8")
        cpp = temp_path / "test.cpp"
        binary = temp_path / "test"
        cpp.write_text(source, encoding="utf-8")
        result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-I", str(temp_path),
             str(cpp), "-o", str(binary)], capture_output=True, text=True
        )
        if result.returncode:
            return False, result.returncode, result.stderr
        run = subprocess.run([str(binary)], capture_output=True, text=True)
        return True, run.returncode, run.stdout + run.stderr


def compile_wrapper_race(header: str, current_facts: str, begin: str,
                         end: str, close_mode: str) -> tuple[bool, int, str]:
    source = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#define F(value) value
class String { public: String(const char* v) : value(v) {} const std::string& str() const { return value; } private: std::string value; };
enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100 };
enum SAMOVAR_MODE : uint8_t { SAMOVAR_RECTIFICATION_MODE = 0, SAMOVAR_SUVID_MODE = 5, SAMOVAR_LUA_MODE = 6 };
static bool locked = false, inject = false, injected = false;
static std::vector<std::string> sent;
void SendMsg(const String& text, MESSAGE_TYPE) { if (locked) std::abort(); sent.push_back(text.str()); }
static int64_t fakeMicros = 1000;
int64_t esp_timer_get_time() { return fakeMicros; }
uint32_t millis() { return 7; }
constexpr uint32_t NTP_PLAUSIBLE_MIN_EPOCH = 1700000000UL;
#include "runtime_pair_events.h"
static RuntimePairState runtimePairState;
static uint32_t currentSessionId = 7;
static bool PowerOn = true;
static SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
static uint8_t ProgramNum = 0, ProgramLen = 1;
static char current_program_type() { return 'P'; }
static bool program_type_empty(char type) { return type == '\0'; }
static bool ui_has_active_program_row() { return ProgramNum < ProgramLen && !program_type_empty(current_program_type()); }
struct Setup { uint8_t TimeZone; } SamSetup = {3};
static uint32_t ntp_snapshot_epoch_now() { return 0; }
static int pdMS_TO_TICKS(int value) { return value; }
static void WriteConsoleLog(const char*) {}
static void runtime_pair_report_failure(const char*, UiWaitReason, RuntimePairPrepareResult) {}
void runtime_pair_begin(UiWaitReason, const char*, MESSAGE_TYPE);
void runtime_pair_end(UiWaitReason, RuntimePairOutcome, const char*, MESSAGE_TYPE, uint32_t = 0);
static bool runtime_state_lock(int) { locked = true; return true; }
static void runtime_state_unlock(bool) {
  locked = false;
  if (inject && !injected) {
    injected = true;
    runtime_pair_end(UI_WAIT_MANUAL_RECT, RUNTIME_PAIR_ROW_CHANGE, "old closed", NOTIFY_MSG);
    runtime_pair_begin(UI_WAIT_MANUAL_RECT, "new begin", NOTIFY_MSG);
  }
}
static RuntimePairEventFacts runtime_pair_current_facts(UiWaitReason reason, uint32_t localEpoch) { @FACTS@ }
void runtime_pair_begin(UiWaitReason reason, const char* tail, MESSAGE_TYPE level) { @BEGIN@ }
void runtime_pair_end(UiWaitReason reason, RuntimePairOutcome outcome, const char* tail, MESSAGE_TYPE level, uint32_t expectedPairId) { @END@ }
void runtime_pair_close_mode(SAMOVAR_MODE mode, RuntimePairOutcome outcome, const char* tail, MESSAGE_TYPE level) { @CLOSE@ }
static bool check(bool value, const char* message) { if (!value) std::fprintf(stderr, "ASSERT: %s\n", message); return value; }
int main() {
  runtime_pair_state_init(runtimePairState, 9);
  runtime_pair_begin(UI_WAIT_MANUAL_RECT, "old begin", NOTIFY_MSG);
  runtime_pair_begin(UI_WAIT_RECT_STEAM, "second old begin", NOTIFY_MSG);
  const uint32_t oldId = runtimePairState.active[0].pairId;
  const uint32_t secondOldId = runtimePairState.active[2].pairId;
  sent.clear(); inject = true;
  runtime_pair_close_mode(SAMOVAR_RECTIFICATION_MODE, RUNTIME_PAIR_PROCESS_END, "mode close", NOTIFY_MSG);
  const RuntimePairState::ActivePair& replacement = runtimePairState.active[0];
  if (!check(injected && replacement.active && replacement.pairId != oldId && replacement.pairId != secondOldId, "replacement pair must remain active")) return 1;
  if (!check(!runtimePairState.active[2].active, "second snapshot pair must close normally")) return 2;
  if (!check(sent.size() == 3, "close_mode must not emit END for replacement pair")) return 3;
  if (!check(sent[0].find(";p=00000001;e=E;") != std::string::npos && sent[1].find(";p=00000003;e=B;") != std::string::npos && sent[2].find(";p=00000002;e=E;") != std::string::npos, "two old IDs close while replacement only begins")) return 4;
  return 0;
}
'''.replace("@FACTS@", current_facts).replace("@BEGIN@", begin).replace("@END@", end).replace("@CLOSE@", close_mode)
    with tempfile.TemporaryDirectory(prefix="samovar-runtime-pair-race-") as temp:
        path = Path(temp)
        (path / "esp_timer.h").write_text("#include <cstdint>\nint64_t esp_timer_get_time();\n", encoding="utf-8")
        (path / "runtime_pair_events.h").write_text(header, encoding="utf-8")
        cpp, binary = path / "test.cpp", path / "test"
        cpp.write_text(source, encoding="utf-8")
        result = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-I", str(path), str(cpp), "-o", str(binary)], capture_output=True, text=True)
        if result.returncode:
            return False, result.returncode, result.stderr
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        return True, result.returncode, result.stdout + result.stderr


def main() -> int:
    header = HEADER.read_text(encoding="utf-8")
    samovar = SAMOVAR.read_text(encoding="utf-8")
    required = [
        "inline uint64_t runtime_pair_monotonic_ms()",
        "inline uint32_t runtime_pair_utc_epoch(uint32_t localEpoch, int8_t timeZone)",
        "inline RuntimePairPrepareResult runtime_pair_prepare_begin(",
        "inline RuntimePairPrepareResult runtime_pair_prepare_end(",
        "inline RuntimePairDispatchResult runtime_pair_dispatch(RuntimePairPendingEvent& pending)",
    ]
    try:
        bodies = [extract_function_body(header, signature) for signature in required]
    except ValueError as exc:
        print(f"runtime pair source extraction failed: {exc}")
        return 1
    if "esp_timer_get_time()" not in bodies[0] or "timeZone) * 3600" not in bodies[1]:
        print("runtime pair time source or timezone correction is absent")
        return 1
    if "SendMsg(String(pending.payload), pending.level);" not in bodies[-1]:
        print("runtime pair dispatch no longer uses the existing SendMsg signature")
        return 1
    harness_compiled, harness_code, harness_output = compile_and_run(header)
    if not harness_compiled:
        print("runtime pair harness did not compile:\n" + harness_output)
        return 1
    if harness_code:
        print("runtime pair harness failed:\n" + harness_output)
        return 1
    try:
        current_facts = extract_function_body(samovar, "static RuntimePairEventFacts runtime_pair_current_facts(UiWaitReason reason,")
        begin = extract_function_body(samovar, "void runtime_pair_begin(UiWaitReason reason, const char* tail, MESSAGE_TYPE level)")
        end = extract_function_body(samovar, "void runtime_pair_end(UiWaitReason reason, RuntimePairOutcome outcome,")
        close_mode = extract_function_body(samovar, "void runtime_pair_close_mode(SAMOVAR_MODE mode, RuntimePairOutcome outcome,")
    except ValueError as exc:
        print(f"runtime pair wrapper extraction failed: {exc}")
        return 1
    wrappers_compiled, wrappers_code, wrappers_output = compile_wrapper_race(
        header, current_facts, begin, end, close_mode)
    if not wrappers_compiled:
        print("runtime pair close-mode identity harness did not compile:\n" + wrappers_output)
        return 1
    if wrappers_code:
        print("runtime pair close-mode identity harness failed:\n" + wrappers_output)
        return 1
    close_mutant = close_mode.replace("activePairs[index].pairId", "0", 1)
    if close_mutant == close_mode:
        print("runtime pair close-mode pairId mutation setup failed")
        return 1
    mutant_compiled, mutant_code, mutant_output = compile_wrapper_race(
        header, current_facts, begin, end, close_mutant)
    expected_mutant_assert = "ASSERT: replacement pair must remain active"
    if not mutant_compiled:
        print("runtime pair close-mode pairId mutation did not compile:\n" + mutant_output)
        return 1
    if mutant_code == 0 or expected_mutant_assert not in mutant_output:
        print("runtime pair close-mode pairId mutation lacked semantic assert:\n" + mutant_output)
        return 1
    print("runtime pair close-mode pairId mutation rejected by replacement-pair assert")
    millis_mutant = header.replace("esp_timer_get_time()", "millis()", 1)
    if millis_mutant == header:
        print("runtime pair 64-bit monotonic mutation setup failed")
        return 1
    millis_compiled, millis_code, millis_output = compile_and_run(millis_mutant)
    expected_millis_assert = "ASSERT: monotonic time keeps 64-bit value"
    if not millis_compiled:
        print("runtime pair 64-bit monotonic mutation did not compile:\n" + millis_output)
        return 1
    if millis_code == 0 or expected_millis_assert not in millis_output:
        print("runtime pair 64-bit monotonic mutation lacked semantic assert:\n" + millis_output)
        return 1
    timezone_mutant = header.replace("static_cast<int64_t>(timeZone) * 3600", "static_cast<int64_t>(timeZone) * 0", 1)
    if timezone_mutant == header:
        print("runtime pair timezone mutation setup failed")
        return 1
    timezone_compiled, timezone_code, timezone_output = compile_and_run(timezone_mutant)
    expected_timezone_assert = "ASSERT: UTC subtracts positive timezone"
    if not timezone_compiled:
        print("runtime pair timezone mutation did not compile:\n" + timezone_output)
        return 1
    if timezone_code == 0 or expected_timezone_assert not in timezone_output:
        print("runtime pair timezone mutation lacked semantic assert:\n" + timezone_output)
        return 1
    print("runtime pair events smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
