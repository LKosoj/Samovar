#!/usr/bin/env python3
"""Проверяет Wi-Fi-владение NTPClient и атомарный снимок времени."""
import subprocess
import sys
import tempfile
import re
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
SETUP_WIFI_GUARD = "if (WiFi.status() != WL_CONNECTED) {"
PERIODIC_WIFI_GUARD = "if (WiFi.status() == WL_CONNECTED) {"


def production_ntp_inventory() -> dict[str, list[str]]:
    ignored_parts = {".git", ".pio", ".cli-proxy", "ai_docs_site", "libraries", "tools"}
    inventory: dict[str, list[str]] = {}
    for path in ROOT.rglob("*"):
        if path.suffix not in {".h", ".ino"} or ignored_parts.intersection(path.parts):
            continue
        calls = re.findall(r"\bNTP\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)", strip_cpp_comments(path.read_text(encoding="utf-8")))
        if calls:
            inventory[path.relative_to(ROOT).as_posix()] = calls
    return inventory


def require_before(errors: list[str], label: str, body: str, *tokens: str) -> None:
    positions = [body.find(token) for token in tokens]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append(f"{label}: required order is missing")


def require_pair_guard(
    errors: list[str], label: str, body: str, first: str, second: str
) -> None:
    require_before(
        errors,
        label,
        body,
        "portENTER_CRITICAL(&ntpSnapshotMux);",
        first,
        second,
        "portEXIT_CRITICAL(&ntpSnapshotMux);",
    )


def ntp_errors(source: str, ntp_client_source: str | None = None) -> list[str]:
    errors: list[str] = []
    setup = extract_function_body(source, "static void setup_start_ntp()")
    clock_task = extract_function_body(source, "void triggerGetClock(void *parameter)")
    publish = extract_function_body(source, "static void publish_ntp_snapshot(uint32_t epoch)")
    snapshot_now = extract_function_body(source, "static uint32_t ntp_snapshot_epoch_now()")
    clock_strings = extract_function_body(source, "static void tick_update_clock_strings()")
    format_snapshot = extract_function_body(
        source, "static void format_ntp_snapshot(uint32_t epoch, String& date, String& clock)"
    )
    session = extract_function_body(source, "void session_begin(const String& sessionDescription)")
    helpers = (ROOT / "runtime_helpers.h").read_text(encoding="utf-8")
    shared_state = (ROOT / "Samovar.h").read_text(encoding="utf-8")

    expected_inventory = {
        "Samovar.ino": [
            "update", "getEpochTime", "setTimeOffset", "setUpdateInterval", "begin",
        ]
    }
    if production_ntp_inventory() != expected_inventory:
        errors.append("direct NTPClient calls outside setup_start_ntp/triggerGetClock are forbidden")
    if source.count('NTPClient NTP(ntpUDP, "ru.pool.ntp.org");') != 1:
        errors.append("NTPClient object declaration must remain the one explicit non-runtime exception")

    require_before(
        errors,
        "NTP boot without WiFi",
        setup,
        SETUP_WIFI_GUARD,
        "NTP.begin();",
    )
    if "NTP.forceUpdate()" in setup or "NTP.update()" in setup:
        errors.append("setup must not block boot on an NTP request")
    require_before(
        errors,
        "periodic NTP update",
        clock_task,
        PERIODIC_WIFI_GUARD,
        "if (NTP.update()) publish_ntp_snapshot(NTP.getEpochTime());",
    )
    if clock_task.find("NTP.update()") > clock_task.find("#ifdef SAMOVAR_USE_BLYNK"):
        errors.append("NTP update must run independently before optional Blynk work")

    ntp_client = ntp_client_source
    if ntp_client is None:
        ntp_client = (ROOT / "libraries/NTPClient/NTPClient.cpp").read_text(encoding="utf-8")
    force_update = extract_function_body(ntp_client, "bool NTPClient::forceUpdate()")
    require_before(
        errors,
        "bounded NTP response wait",
        force_update,
        "if (!this->sendNTPPacket()) return false;",
        "delay ( 10 );",
        "if (timeout > 100) return false;",
    )
    require_pair_guard(
        errors,
        "snapshot writer guard",
        publish,
        "ntpSnapshotEpoch = epoch;",
        "ntpSnapshotMillis = capturedAtMillis;",
    )
    require_pair_guard(
        errors,
        "snapshot reader guard",
        snapshot_now,
        "epoch = ntpSnapshotEpoch;",
        "capturedAtMillis = ntpSnapshotMillis;",
    )
    require_before(
        errors,
        "snapshot time progression",
        snapshot_now,
        "if (epoch == 0) return 0;",
        "return epoch + ((millis() - capturedAtMillis) / 1000UL);",
    )
    require_before(
        errors,
        "SysTicker snapshot formatting",
        clock_strings,
        "const uint32_t epoch = ntp_snapshot_epoch_now();",
        "if (epoch == 0) return;",
        "format_ntp_snapshot(epoch, localCrt, localTime);",
    )
    if "NTP." in clock_strings or "NTP." in session:
        errors.append("SysTicker/session_begin must not read mutable NTPClient directly")
    for token in ("NTP.", "NtpLockGuard", "xNtpSemaphore"):
        if token in format_snapshot:
            errors.append(f"snapshot formatter must not access mutable NTPClient ({token})")
    for token in (
        "gmtime_r",
        'snprintf(dateBuffer, sizeof(dateBuffer), "%02d-%02d %02d:%02d:%02d",',
        "clock = dateBuffer + 6;",
    ):
        if token not in format_snapshot:
            errors.append(f"snapshot formatter is incomplete: {token}")
    require_before(
        errors,
        "session snapshot epoch",
        session,
        "const uint32_t epoch = ntp_snapshot_epoch_now();",
        "(epoch > NTP_PLAUSIBLE_MIN_EPOCH) ? epoch : esp_random();",
    )
    for token in ("xNtpSemaphore", "NtpLockGuard", "ntp_lock(", "LOCK_ORDER: 19  NTP"):
        if token in source or token in helpers or token in shared_state:
            errors.append(f"obsolete NTP mutex remains: {token}")
    return errors


def build_harness(
    publish_body: str,
    snapshot_now_body: str,
    format_body: str,
    periodic_statement: str,
    uptime_body: str,
    tick_body: str,
) -> str:
    return f"""
#include <cstdint>
#include <ctime>
#include <cstdio>
#include <cstdlib>
#include <string>

using uint32_t = std::uint32_t;
class String {{
 public:
  String() = default;
  String(const char* value) : value_(value) {{}}
  String(unsigned long value) : value_(std::to_string(value)) {{}}
  String(int value) : value_(std::to_string(value)) {{}}
  String& operator+=(const String& value) {{ value_ += value.value_; return *this; }}
  String& operator+=(const char* value) {{ value_ += value; return *this; }}
  const char* c_str() const {{ return value_.c_str(); }}
  bool operator==(const char* value) const {{ return value_ == value; }}
 private:
  std::string value_;
}};
static String operator+(const String& left, const String& right) {{
  String result = left;
  result += right;
  return result;
}}
struct portMUX_TYPE {{}};
portMUX_TYPE ntpSnapshotMux;
static bool lockHeld = false;
static int lockEnters = 0;
static int lockExits = 0;
static void enterCritical(portMUX_TYPE*) {{
  if (lockHeld) std::abort();
  lockHeld = true;
  ++lockEnters;
}}
static void exitCritical(portMUX_TYPE*) {{
  if (!lockHeld) std::abort();
  lockHeld = false;
  ++lockExits;
}}
#define portENTER_CRITICAL(mux) enterCritical(mux)
#define portEXIT_CRITICAL(mux) exitCritical(mux)

static uint32_t fakeMillis = 0;
uint32_t millis() {{ return fakeMillis++; }}
static uint32_t ntpSnapshotEpoch = 0;
static uint32_t ntpSnapshotMillis = 0;
static char tst[32] = {{}};
static String Crt;
static String StrCrt;
static bool runtime_state_lock(unsigned long) {{ return true; }}
static void runtime_state_unlock(bool) {{}}
#define pdMS_TO_TICKS(value) (value)

constexpr int WL_CONNECTED = 3;
constexpr int WL_DISCONNECTED = 6;
struct FakeWiFi {{
  int state = WL_DISCONNECTED;
  int status() const {{ return state; }}
}} WiFi;
struct FakeNtp {{
  bool updateResult = false;
  uint32_t epoch = 0;
  int updateCalls = 0;
  bool update() {{ ++updateCalls; return updateResult; }}
  uint32_t getEpochTime() const {{ return epoch; }}
}} NTP;
static int counter = 0;

static void publish_ntp_snapshot(uint32_t epoch) {{
{publish_body}
}}

static uint32_t ntp_snapshot_epoch_now() {{
{snapshot_now_body}
}}

static void format_ntp_snapshot(uint32_t epoch, String& date, String& clock) {{
{format_body}
}}

static String format_uptime(unsigned long seconds) {{
{uptime_body}
}}

static void run_production_periodic_ntp() {{
{periodic_statement}
}}

static void tick_update_clock_strings() {{
{tick_body}
}}

static void expect(bool condition, const char* message) {{
  if (!condition) {{
    std::fputs(message, stderr);
    std::fputc('\\n', stderr);
    std::exit(1);
  }}
}}

int main() {{
  WiFi.state = WL_DISCONNECTED;
  NTP.updateResult = true;
  NTP.epoch = 1704067200UL;
  run_production_periodic_ntp();
  expect(NTP.updateCalls == 0 && ntp_snapshot_epoch_now() == 0,
         "offline boot must not start NTP update or publish a snapshot");

  WiFi.state = WL_CONNECTED;
  fakeMillis = 100;
  run_production_periodic_ntp();
  expect(NTP.updateCalls == 1, "later WiFi connection must update NTP once");
  fakeMillis = 2100;
  expect(ntp_snapshot_epoch_now() == 1704067202UL,
         "successful later WiFi update must publish its snapshot");

  ntpSnapshotEpoch = 0;
  ntpSnapshotMillis = 0;
  fakeMillis = UINT32_MAX - 499UL;
  publish_ntp_snapshot(1704067200UL);
  fakeMillis = 500;
  expect(ntp_snapshot_epoch_now() == 1704067201UL,
         "millis rollover must add elapsed time from the matching snapshot");

  fakeMillis = 100;
  ntpSnapshotEpoch = 0;
  ntpSnapshotMillis = 0;
  publish_ntp_snapshot(1700000000UL);
  expect(!lockHeld && lockEnters == lockExits,
         "publish/read must each release the snapshot guard");
  fakeMillis = 2100;
  expect(ntp_snapshot_epoch_now() == 1700000002UL,
         "snapshot must advance from its matching epoch/millis pair");
  String date;
  String clock;
  format_ntp_snapshot(1704067200UL, date, clock);
  expect(date == "01-01 00:00:00" && clock == "00:00:00",
         "first epoch must keep the complete Crt date/time format");
  format_ntp_snapshot(1720000000UL, date, clock);
  expect(date == "07-03 09:46:40" && clock == "09:46:40",
         "second epoch must keep the complete Crt date/time format");

  fakeMillis = 0;
  ntpSnapshotEpoch = 0;
  ntpSnapshotMillis = 0;
  publish_ntp_snapshot(1704067200UL);
  tick_update_clock_strings();
  expect(Crt == "01-01 00:00:00", "tick must publish complete Crt from snapshot");
  expect(StrCrt == "00:00:00     00:00:00",
         "tick must publish StrCrt from snapshot time and uptime");
  expect(std::string(tst) == "00:00:00   00:00:00",
         "tick must publish tst from snapshot time and uptime");
  return 0;
}}
"""


def compile_and_run(
    publish_body: str,
    snapshot_now_body: str,
    format_body: str,
    periodic_statement: str,
    uptime_body: str,
    tick_body: str,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / "ntp_snapshot.cpp"
        binary_path = temp_path / "ntp_snapshot"
        source_path.write_text(
            build_harness(
                publish_body, snapshot_now_body, format_body,
                periodic_statement, uptime_body, tick_body,
            ),
            encoding="utf-8",
        )
        build = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        if build.returncode:
            return build
        return subprocess.run([str(binary_path)], text=True, capture_output=True, check=False)


def main() -> int:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    errors = ntp_errors(strip_cpp_comments(source))
    if errors:
        print("NTP WiFi/snapshot smoke check failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1

    publish = extract_function_body(source, "static void publish_ntp_snapshot(uint32_t epoch)")
    snapshot_now = extract_function_body(source, "static uint32_t ntp_snapshot_epoch_now()")
    format_snapshot = extract_function_body(
        source, "static void format_ntp_snapshot(uint32_t epoch, String& date, String& clock)"
    )
    clock_task = extract_function_body(source, "void triggerGetClock(void *parameter)")
    periodic_start = clock_task.find(PERIODIC_WIFI_GUARD)
    _, periodic_end = extract_braced_block_after(clock_task, PERIODIC_WIFI_GUARD)
    periodic_statement = clock_task[periodic_start:periodic_end]
    uptime = extract_function_body(
        (ROOT / "time_utils.h").read_text(encoding="utf-8"),
        "inline String format_uptime(unsigned long seconds)",
    )
    tick = extract_function_body(source, "static void tick_update_clock_strings()")
    result = compile_and_run(
        publish, snapshot_now, format_snapshot, periodic_statement, uptime, tick
    )
    if result.returncode:
        print("NTP snapshot harness failed:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    guard_scope_mutant = source.replace(
        "ntpSnapshotEpoch = epoch;\n  ntpSnapshotMillis = capturedAtMillis;\n  portEXIT_CRITICAL(&ntpSnapshotMux);",
        "ntpSnapshotEpoch = epoch;\n  portEXIT_CRITICAL(&ntpSnapshotMux);\n  ntpSnapshotMillis = capturedAtMillis;",
        1,
    )
    if "snapshot writer guard: required order is missing" not in ntp_errors(
        strip_cpp_comments(guard_scope_mutant)
    ):
        print("FAIL: NTP mutation survived: snapshot writer guard scope", file=sys.stderr)
        return 1

    mixed_pair_publish = publish.replace(
        "ntpSnapshotMillis = capturedAtMillis;", "ntpSnapshotMillis = capturedAtMillis + 1UL;", 1
    )
    result = compile_and_run(
        mixed_pair_publish, snapshot_now, format_snapshot, periodic_statement, uptime, tick
    )
    if result.returncode == 0 or "successful later WiFi update must publish" not in result.stderr:
        print("FAIL: NTP mutation survived: mixed snapshot pair", file=sys.stderr)
        return 1

    date_only_format = format_snapshot.replace(
        "date = dateBuffer;", "dateBuffer[5] = '\\0';\n  date = dateBuffer;", 1
    )
    result = compile_and_run(
        publish, snapshot_now, date_only_format, periodic_statement, uptime, tick
    )
    if result.returncode == 0 or "complete Crt date/time format" not in result.stderr:
        print("FAIL: NTP mutation survived: Crt date lost its time", file=sys.stderr)
        return 1

    offline_periodic = periodic_statement.replace(PERIODIC_WIFI_GUARD, "if (true) {", 1)
    result = compile_and_run(
        publish, snapshot_now, format_snapshot, offline_periodic, uptime, tick
    )
    if result.returncode == 0 or "offline boot must not start NTP update" not in result.stderr:
        print("FAIL: NTP mutation survived: offline boot update", file=sys.stderr)
        return 1

    rollover_snapshot = snapshot_now.replace(
        "return epoch + ((millis() - capturedAtMillis) / 1000UL);",
        "return epoch + ((millis() + capturedAtMillis) / 1000UL);",
        1,
    )
    result = compile_and_run(
        publish, rollover_snapshot, format_snapshot, periodic_statement, uptime, tick
    )
    if result.returncode == 0 or "millis rollover must add elapsed time" not in result.stderr:
        print("FAIL: NTP mutation survived: millis rollover", file=sys.stderr)
        return 1

    tick_without_crt = tick.replace("Crt = localCrt;", 'Crt = "";', 1)
    result = compile_and_run(
        publish, snapshot_now, format_snapshot, periodic_statement, uptime, tick_without_crt
    )
    if result.returncode == 0 or "tick must publish complete Crt" not in result.stderr:
        print("FAIL: NTP mutation survived: tick Crt publication", file=sys.stderr)
        return 1

    direct_getter_mutant = source.replace(
        "const uint32_t epoch = ntp_snapshot_epoch_now();",
        "const uint32_t epoch = NTP.getEpochTime();",
        1,
    )
    if "SysTicker/session_begin must not read mutable NTPClient directly" not in ntp_errors(
        strip_cpp_comments(direct_getter_mutant)
    ):
        print("FAIL: NTP mutation survived: direct runtime NTP getter", file=sys.stderr)
        return 1

    blocking_setup_mutant = source.replace(
        "NTP.begin();\n}", "NTP.begin();\n  NTP.forceUpdate();\n}", 1
    )
    if "setup must not block boot on an NTP request" not in ntp_errors(
        strip_cpp_comments(blocking_setup_mutant)
    ):
        print("FAIL: NTP mutation survived: blocking setup request", file=sys.stderr)
        return 1

    ntp_client = (ROOT / "libraries/NTPClient/NTPClient.cpp").read_text(encoding="utf-8")
    unbounded_wait = ntp_client.replace("if (timeout > 100) return false;", "", 1)
    if "bounded NTP response wait: required order is missing" not in ntp_errors(
        strip_cpp_comments(source), unbounded_wait
    ):
        print("FAIL: NTP mutation survived: unbounded response wait", file=sys.stderr)
        return 1

    print("NTP WiFi and snapshot mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
