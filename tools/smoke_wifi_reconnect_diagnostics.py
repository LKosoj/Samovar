#!/usr/bin/env python3
"""Проверяет интервалы Wi-Fi reconnect и сетевые callback-функции."""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
AUTO_RECONNECT = "WiFi.setAutoReconnect(true);"
GOT_IP_REGISTRATION = "WiFi.onEvent(captureWifiGotIp, ARDUINO_EVENT_WIFI_STA_GOT_IP);"
DISCONNECT_REGISTRATION = (
    "WiFi.onEvent(captureWifiDisconnectReason, "
    "ARDUINO_EVENT_WIFI_STA_DISCONNECTED);"
)
GOT_IP_SIGNATURE = "static void captureWifiGotIp(arduino_event_t *event)"
DISCONNECT_SIGNATURE = "static void captureWifiDisconnectReason(arduino_event_t *event)"
RECONNECT_SIGNATURE = "static void tick_wifi_reconnect()"
STORE_DISCONNECT_SIGNATURE = "static void store_wifi_disconnect_event(uint8_t reason)"
TAKE_DISCONNECT_SIGNATURE = "static bool take_wifi_disconnect_event(WifiDisconnectEvent& event)"
TICK_DISCONNECT_DIAGNOSTICS_SIGNATURE = "static void tick_wifi_disconnect_diagnostics()"
IPST_SET_SIGNATURE = "inline void ipst_set(const String& value)"
IPST_COPY_SIGNATURE = "inline void ipst_copy(char (&copy)[sizeof(ipst)])"
RECONNECT_CONSTANTS = (
    "static constexpr uint32_t WIFI_STATUS_CHECK_INTERVAL_MS = 1000UL;",
    "static constexpr uint32_t WIFI_DISCONNECT_CONFIRM_MS = 5000UL;",
    "static constexpr uint32_t WIFI_RECONNECT_INTERVAL_MS = 10000UL;",
)


def policy_errors(source: str) -> list[str]:
    errors: list[str] = []
    helpers = (ROOT / "runtime_helpers.h").read_text(encoding="utf-8")
    blynk = (ROOT / "Blynk.ino").read_text(encoding="utf-8")
    menu = (ROOT / "Menu.ino").read_text(encoding="utf-8")
    samovar_header = (ROOT / "Samovar.h").read_text(encoding="utf-8")
    setup_body = extract_function_body(source, "static void setup_wifi_stack_defaults()")
    trigger_body = extract_function_body(source, "void triggerGetClock(void *parameter)")
    if "struct WifiDisconnectEvent;" not in source[:source.find("#include <Arduino.h>")]:
        errors.append("WifiDisconnectEvent forward declaration must precede Arduino prototypes")
    try:
        got_ip_body = extract_function_body(source, GOT_IP_SIGNATURE)
        disconnect_body = extract_function_body(source, DISCONNECT_SIGNATURE)
        reconnect_body = extract_function_body(source, RECONNECT_SIGNATURE)
        store_disconnect_body = extract_function_body(source, STORE_DISCONNECT_SIGNATURE)
        take_disconnect_body = extract_function_body(source, TAKE_DISCONNECT_SIGNATURE)
        diagnostics_body = extract_function_body(source, TICK_DISCONNECT_DIAGNOSTICS_SIGNATURE)
        ipst_set_body = extract_function_body(helpers, IPST_SET_SIGNATURE)
        ipst_copy_body = extract_function_body(helpers, IPST_COPY_SIGNATURE)
        blynk_slow_body = extract_function_body(blynk, "static void blynk_push_slow(bool force)")
        usb_body = extract_function_body(source, "inline void tick_usb_serial_command()")
        config_body = extract_function_body(source, "void apply_config_runtime()")
    except ValueError as error:
        return [f"required WiFi helper is missing: {error}"]

    if AUTO_RECONNECT not in setup_body:
        errors.append("auto-reconnect WiFi core is not enabled")
    for constant in RECONNECT_CONSTANTS:
        if constant not in source:
            errors.append(f"WiFi reconnect timing changed or missing: {constant}")
    if trigger_body.count("tick_wifi_reconnect();") != 3:
        errors.append("GetClockTicker must check WiFi during OTA, after sensors and each one-second wait")
    if trigger_body.count("tick_wifi_disconnect_diagnostics();") != 1:
        errors.append("GetClockTicker must print queued WiFi disconnect diagnostics")
    if setup_body.count(GOT_IP_REGISTRATION) != 1:
        errors.append("GOT_IP callback must be registered exactly once")
    if setup_body.count(DISCONNECT_REGISTRATION) != 1:
        errors.append("disconnect callback must be registered exactly once")
    if "ipst_set(WiFi.localIP().toString());" not in got_ip_body:
        errors.append("GOT_IP callback does not update ipst from WiFi.localIP")
    for forbidden in ("Blynk", "Serial", "WriteConsoleLog", "WiFi.reconnect"):
        if forbidden in got_ip_body:
            errors.append(f"GOT_IP callback performs forbidden work: {forbidden}")
        if forbidden in disconnect_body:
            errors.append(f"disconnect callback performs forbidden work: {forbidden}")
    if "lastWifiDisconnectReason = reason;" not in disconnect_body:
        errors.append("disconnect callback does not retain the reason")
    if "store_wifi_disconnect_event(reason);" not in disconnect_body:
        errors.append("disconnect callback does not queue every system event")
    for token in ("millis()", "portENTER_CRITICAL", "wifiDisconnectEvents", "portEXIT_CRITICAL"):
        if token not in store_disconnect_body:
            errors.append(f"WiFi disconnect event storage misses {token}")
    for token in ("portENTER_CRITICAL", "wifiDisconnectEvents", "portEXIT_CRITICAL"):
        if token not in take_disconnect_body:
            errors.append(f"WiFi disconnect event extraction misses {token}")
    for token in ("take_wifi_disconnect_event(event)", "Serial.printf", "event.atMillis", "event.reason"):
        if token not in diagnostics_body:
            errors.append(f"safe WiFi disconnect diagnostic misses {token}")
    for token in (
        "WiFi.status()",
        "WIFI_STATUS_CHECK_INTERVAL_MS",
        "WIFI_DISCONNECT_CONFIRM_MS",
        "WIFI_RECONNECT_INTERVAL_MS",
        "WiFi.reconnect()",
        "lastWifiDisconnectReason",
        "ota_running",
        "wifiAP",
    ):
        if token not in reconnect_body:
            errors.append(f"WiFi reconnect state machine misses {token}")
    if "portMUX_TYPE ipstMux = portMUX_INITIALIZER_UNLOCKED;" not in source or \
            "extern portMUX_TYPE ipstMux;" not in helpers:
        errors.append("ipst mutex is missing")
    if not (ipst_set_body.find("copyStringSafe(copy, value);") <
            ipst_set_body.find("portENTER_CRITICAL(&ipstMux);") <
            ipst_set_body.find("memcpy(ipst, copy, sizeof(ipst));") <
            ipst_set_body.find("portEXIT_CRITICAL(&ipstMux);")):
        errors.append("ipst_set must copy String before its short critical section")
    if not (ipst_copy_body.find("portENTER_CRITICAL(&ipstMux);") <
            ipst_copy_body.find("memcpy(copy, ipst, sizeof(ipst));") <
            ipst_copy_body.find("portEXIT_CRITICAL(&ipstMux);")):
        errors.append("ipst_copy must take a complete atomic snapshot")
    if "String" in ipst_copy_body:
        errors.append("ipst_copy must not build String under the critical section")
    if "ipst_set(StIP);" not in source:
        errors.append("AP initial ipst write bypasses atomic setter")
    for name, body in (
        ("Blynk V15", blynk_slow_body),
        ("USB IP", usb_body),
        ("apply_config V15", config_body),
        ("menu IP", menu),
    ):
        if "ipst_copy(ip);" not in body:
            errors.append(f"{name} does not use an ipst snapshot")
    if "String(ipst)" in blynk or "V15, ipst" in source or \
            "Serial.println(ipst)" in source or "return ipstr;" in menu or "char* ipstr" in samovar_header:
        errors.append("raw ipst reader remains")
    return errors


def build_reconnect_harness(
    reconnect_body: str,
    disconnect_body: str,
    store_disconnect_body: str,
    take_disconnect_body: str,
    diagnostics_body: str,
) -> str:
    return f'''#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

using std::uint8_t;
using std::uint32_t;

#define F(value) value

enum wl_status_t {{ WL_IDLE_STATUS = 0, WL_CONNECTED = 3 }};
enum wifi_err_reason_t {{ WIFI_REASON_UNSPECIFIED = 1, WIFI_REASON_AUTH_EXPIRE = 2 }};

class String {{
 public:
  String() = default;
  String(const char* value) : value_(value) {{}}
  const char* c_str() const {{ return value_.c_str(); }}

 private:
  std::string value_;
}};

struct FakeIP {{
  String toString() const {{ return String("192.168.1.77"); }}
}};

struct FakeWiFi {{
  wl_status_t state = WL_CONNECTED;
  int reconnectCalls = 0;
  bool reconnectAccepted = true;

  wl_status_t status() const {{ return state; }}
  bool reconnect() {{ reconnectCalls++; return reconnectAccepted; }}
  FakeIP localIP() const {{ return FakeIP{{}}; }}
  const char* disconnectReasonName(wifi_err_reason_t reason) const {{
    return reason == WIFI_REASON_AUTH_EXPIRE ? "AUTH_EXPIRE" : "UNSPECIFIED";
  }}
}} WiFi;

struct WifiStaDisconnected {{ uint8_t reason; }};
struct ArduinoEventInfo {{ WifiStaDisconnected wifi_sta_disconnected; }};
struct arduino_event_t {{ ArduinoEventInfo event_info; }};

static constexpr uint32_t WIFI_STATUS_CHECK_INTERVAL_MS = 1000UL;
static constexpr uint32_t WIFI_DISCONNECT_CONFIRM_MS = 5000UL;
static constexpr uint32_t WIFI_RECONNECT_INTERVAL_MS = 10000UL;
static constexpr uint8_t WIFI_DISCONNECT_EVENT_CAPACITY = 8;
volatile uint8_t lastWifiDisconnectReason = WIFI_REASON_UNSPECIFIED;
bool ota_running = false;
bool wifiAP = false;
uint32_t currentMillis = 0;
std::vector<std::string> logs;
std::vector<std::string> serialLines;
int failures = 0;

struct WifiDisconnectEvent {{
  uint32_t atMillis;
  uint8_t reason;
}};

struct portMUX_TYPE {{}};
#define portMUX_INITIALIZER_UNLOCKED {{}}
static portMUX_TYPE wifiDisconnectEventMux = portMUX_INITIALIZER_UNLOCKED;
static WifiDisconnectEvent wifiDisconnectEvents[WIFI_DISCONNECT_EVENT_CAPACITY] = {{}};
static volatile uint8_t wifiDisconnectEventRead = 0;
static volatile uint8_t wifiDisconnectEventCount = 0;
static volatile uint32_t wifiDisconnectEventsDropped = 0;

void portENTER_CRITICAL(portMUX_TYPE*) {{}}
void portEXIT_CRITICAL(portMUX_TYPE*) {{}}

struct SerialProbe {{
  void printf(const char* format, ...) {{
    char line[192];
    va_list args;
    va_start(args, format);
    vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    serialLines.emplace_back(line);
  }}
}} Serial;

uint32_t millis() {{ return currentMillis; }}
void WriteConsoleLog(String message) {{ logs.emplace_back(message.c_str()); }}

static void store_wifi_disconnect_event(uint8_t reason) {{
{store_disconnect_body}
}}

static bool take_wifi_disconnect_event(WifiDisconnectEvent& event) {{
{take_disconnect_body}
}}

static void tick_wifi_disconnect_diagnostics() {{
{diagnostics_body}
}}

static void captureWifiDisconnectReason(arduino_event_t *event) {{
{disconnect_body}
}}

static void tick_wifi_reconnect() {{
{reconnect_body}
}}

void check(bool condition, const char* message) {{
  if (!condition) {{
    std::cerr << "FAIL: " << message << '\\n';
    failures++;
  }}
}}

void tickAt(uint32_t at) {{
  currentMillis = at;
  tick_wifi_reconnect();
}}

bool hasLog(const char* part) {{
  for (const std::string& entry : logs) {{
    if (entry.find(part) != std::string::npos) return true;
  }}
  return false;
}}

bool hasSerial(const char* part) {{
  for (const std::string& entry : serialLines) {{
    if (entry.find(part) != std::string::npos) return true;
  }}
  return false;
}}

int countLogs(const char* part) {{
  int count = 0;
  for (const std::string& entry : logs) {{
    if (entry.find(part) != std::string::npos) count++;
  }}
  return count;
}}

int main() {{
  arduino_event_t unspecified{{{{WIFI_REASON_UNSPECIFIED}}}};
  arduino_event_t authExpire{{{{WIFI_REASON_AUTH_EXPIRE}}}};
  currentMillis = 100;
  captureWifiDisconnectReason(&unspecified);
  currentMillis = 200;
  captureWifiDisconnectReason(&authExpire);
  tick_wifi_disconnect_diagnostics();
  check(hasSerial("WiFi disconnected at_ms=100 reason=1(UNSPECIFIED)"),
        "first immediate system disconnect diagnostic is missing");
  check(hasSerial("WiFi disconnected at_ms=200 reason=2(AUTH_EXPIRE)"),
        "second immediate system disconnect diagnostic is missing");

  tickAt(1000);
  captureWifiDisconnectReason(&authExpire);
  WiFi.state = WL_IDLE_STATUS;
  for (uint32_t at = 2000; at <= 6000; at += 1000) tickAt(at);
  check(WiFi.reconnectCalls == 0, "short or unconfirmed outage triggered reconnect");

  tickAt(6500);
  check(WiFi.reconnectCalls == 0, "sub-second check changed reconnect state");
  tickAt(7000);
  check(WiFi.reconnectCalls == 1, "confirmed five-second outage did not reconnect once");
  check(hasLog("WiFi disconnected status=0 reason=2(AUTH_EXPIRE)"),
        "confirmed outage diagnostic is missing");
  check(hasLog("WiFi.reconnect attempt=1 accepted=1"),
        "first reconnect result is missing");

  for (uint32_t at = 8000; at <= 16000; at += 1000) tickAt(at);
  check(WiFi.reconnectCalls == 1, "reconnect repeated before ten seconds elapsed");
  tickAt(17000);
  check(WiFi.reconnectCalls == 2, "ten-second reconnect retry is missing");

  WiFi.state = WL_CONNECTED;
  tickAt(18000);
  check(hasLog("WiFi restored ip=192.168.1.77 outage_ms=16000"),
        "recovery diagnostic or outage duration is missing");

  WiFi.reconnectAccepted = false;
  WiFi.state = WL_IDLE_STATUS;
  for (uint32_t at = 19000; at <= 24000; at += 1000) tickAt(at);
  check(WiFi.reconnectCalls == 3, "second independent outage did not restart the state machine");
  check(countLogs("WiFi.reconnect attempt=1") == 2,
        "new outage did not reset the attempt number");
  check(hasLog("WiFi.reconnect attempt=1 accepted=0"),
        "rejected reconnect result is missing");

  WiFi.reconnectAccepted = true;
  WiFi.state = WL_CONNECTED;
  tickAt(25000);
  ota_running = true;
  WiFi.state = WL_IDLE_STATUS;
  for (uint32_t at = 26000; at <= 40000; at += 1000) tickAt(at);
  check(WiFi.reconnectCalls == 3, "OTA outage triggered reconnect");
  ota_running = false;
  for (uint32_t at = 41000; at <= 46000; at += 1000) tickAt(at);
  check(WiFi.reconnectCalls == 4, "outage after OTA was not confirmed from a fresh timer");

  return failures == 0 ? 0 : 1;
}}
'''


def build_harness(ipst_set_body: str, ipst_copy_body: str, callback_body: str) -> str:
    return f'''#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>

class String {{
 public:
  String() = default;
  String(const char* text) : text_(text) {{}}
  size_t length() const {{ return text_.size(); }}
  const char* c_str() const {{ return text_.c_str(); }}

 private:
  std::string text_;
}};

struct FakeIP {{
  String value;
  String toString() const {{ return value; }}
}};

struct FakeWiFi {{
  FakeIP ip;
  FakeIP localIP() const {{ return ip; }}
}} WiFi;

struct arduino_event_t {{}};
struct portMUX_TYPE {{}};
portMUX_TYPE ipstMux;
char ipst[16] = {{}};
int failures = 0;
int ipstLockTakes = 0;
int ipstLockGives = 0;

void portENTER_CRITICAL(portMUX_TYPE*) {{ ipstLockTakes++; }}
void portEXIT_CRITICAL(portMUX_TYPE*) {{ ipstLockGives++; }}

template <size_t N>
void copyStringSafe(char (&destination)[N], const String& source) {{
  const size_t length = source.length() < N ? source.length() : N - 1;
  std::memcpy(destination, source.c_str(), length);
  destination[length] = '\\0';
}}

inline void ipst_set(const String& value) {{
{ipst_set_body}
}}

inline void ipst_copy(char (&copy)[sizeof(ipst)]) {{
{ipst_copy_body}
}}

void check(bool condition, const char* message) {{
  if (!condition) {{
    std::cerr << "FAIL: " << message << '\\n';
    failures++;
  }}
}}

static void captureWifiGotIp(arduino_event_t *event) {{
{callback_body}
}}

void publishGotIp(const char* address) {{
  WiFi.ip.value = String(address);
  arduino_event_t event{{}};
  captureWifiGotIp(&event);
}}

int main() {{
  char snapshot[sizeof(ipst)] = {{}};
  publishGotIp("192.168.1.10");
  ipst_copy(snapshot);
  check(std::strcmp(snapshot, "192.168.1.10") == 0,
        "first GOT_IP event did not atomically update ipst");
  publishGotIp("10.42.0.77");
  ipst_copy(snapshot);
  check(std::strcmp(snapshot, "10.42.0.77") == 0,
        "second GOT_IP event did not atomically replace ipst");
  check(ipstLockTakes == 4 && ipstLockGives == 4,
        "two IP updates and snapshots did not use the ipst mutex");
  return failures == 0 ? 0 : 1;
}}
'''


def compile_and_run(source: str, emit_failure: bool) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-got-ip-") as temp_dir:
        source_path = Path(temp_dir) / "harness.cpp"
        binary_path = Path(temp_dir) / "harness"
        source_path.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
        )
        if compile_result.returncode != 0:
            if emit_failure:
                print(compile_result.stderr, file=sys.stderr)
            return compile_result.returncode, compile_result.stderr
        run_result = subprocess.run([str(binary_path)], capture_output=True, text=True)
        output = run_result.stdout + run_result.stderr
        if emit_failure and run_result.returncode != 0:
            print(output, file=sys.stderr)
        return run_result.returncode, output


def main() -> int:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    errors = policy_errors(source)
    if errors:
        print("WiFi reconnect policy smoke check failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1

    helpers = (ROOT / "runtime_helpers.h").read_text(encoding="utf-8")
    ipst_set_body = extract_function_body(helpers, IPST_SET_SIGNATURE)
    ipst_copy_body = extract_function_body(helpers, IPST_COPY_SIGNATURE)
    callback_body = extract_function_body(source, GOT_IP_SIGNATURE)
    disconnect_body = extract_function_body(source, DISCONNECT_SIGNATURE)
    reconnect_body = extract_function_body(source, RECONNECT_SIGNATURE)
    store_disconnect_body = extract_function_body(source, STORE_DISCONNECT_SIGNATURE)
    take_disconnect_body = extract_function_body(source, TAKE_DISCONNECT_SIGNATURE)
    diagnostics_body = extract_function_body(source, TICK_DISCONNECT_DIAGNOSTICS_SIGNATURE)
    returncode, _ = compile_and_run(
        build_harness(ipst_set_body, ipst_copy_body, callback_body), True
    )
    if returncode != 0:
        return 1

    returncode, _ = compile_and_run(
        build_reconnect_harness(
            reconnect_body,
            disconnect_body,
            store_disconnect_body,
            take_disconnect_body,
            diagnostics_body,
        ),
        True,
    )
    if returncode != 0:
        return 1

    policy_mutants = (
        (
            source.replace(AUTO_RECONNECT, "WiFi.setAutoReconnect(false);", 1),
            "auto-reconnect WiFi core is not enabled",
        ),
    )
    for mutant, expected_error in policy_mutants:
        if expected_error not in policy_errors(mutant):
            print(f"FAIL: WiFi policy mutation survived: {expected_error}", file=sys.stderr)
            return 1

    reconnect_mutants = (
        reconnect_body.replace(
            "WIFI_DISCONNECT_CONFIRM_MS", "WIFI_STATUS_CHECK_INTERVAL_MS", 1
        ),
        reconnect_body.replace(
            "WIFI_RECONNECT_INTERVAL_MS", "WIFI_DISCONNECT_CONFIRM_MS", 1
        ),
        reconnect_body.replace("WiFi.reconnect()", "true", 1),
        reconnect_body.replace("status == WL_CONNECTED", "false", 1),
    )
    for mutant in reconnect_mutants:
        returncode, output = compile_and_run(
            build_reconnect_harness(
                mutant,
                disconnect_body,
                store_disconnect_body,
                take_disconnect_body,
                diagnostics_body,
            ),
            False,
        )
        if returncode == 0 or "FAIL:" not in output:
            print("FAIL: WiFi reconnect behavior mutation survived", file=sys.stderr)
            return 1

    timestamp_mutant = store_disconnect_body.replace(
        "const WifiDisconnectEvent event = {millis(), reason};",
        "const WifiDisconnectEvent event = {0, reason};",
        1,
    )
    reason_mutant = store_disconnect_body.replace(
        "const WifiDisconnectEvent event = {millis(), reason};",
        "const WifiDisconnectEvent event = {millis(), static_cast<uint8_t>(reason + 1)};",
        1,
    )
    if timestamp_mutant == store_disconnect_body or reason_mutant == store_disconnect_body:
        print("FAIL: could not create WiFi disconnect diagnostic mutations", file=sys.stderr)
        return 1
    for mutant, expected_failure in (
        (timestamp_mutant, "first immediate system disconnect diagnostic is missing"),
        (reason_mutant, "second immediate system disconnect diagnostic is missing"),
    ):
        returncode, output = compile_and_run(
            build_reconnect_harness(
                reconnect_body,
                disconnect_body,
                mutant,
                take_disconnect_body,
                diagnostics_body,
            ),
            False,
        )
        if returncode == 0 or expected_failure not in output:
            print("FAIL: WiFi disconnect diagnostic mutation survived or failed for the wrong reason", file=sys.stderr)
            return 1

    broken_callback = callback_body.replace(
        "ipst_set(WiFi.localIP().toString());",
        'ipst_set(String("0.0.0.0"));',
        1,
    )
    returncode, output = compile_and_run(
        build_harness(ipst_set_body, ipst_copy_body, broken_callback), False
    )
    if returncode == 0 or "first GOT_IP event did not atomically update ipst" not in output:
        print("FAIL: GOT_IP callback mutation survived or failed for the wrong reason", file=sys.stderr)
        return 1

    broken_set = ipst_set_body.replace(
        "memcpy(ipst, copy, sizeof(ipst));", "memset(ipst, 0, sizeof(ipst));", 1
    )
    returncode, output = compile_and_run(
        build_harness(broken_set, ipst_copy_body, callback_body), False
    )
    if returncode == 0 or "first GOT_IP event did not atomically update ipst" not in output:
        print("FAIL: ipst_set mutation survived or failed for the wrong reason", file=sys.stderr)
        return 1

    print("WiFi reconnect timing, recovery and GOT_IP mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
