#!/usr/bin/env python3
"""Проверяет единственного владельца Wi-Fi reconnect и GOT_IP callback."""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
AUTO_RECONNECT = "WiFi.setAutoReconnect(true);"
MANUAL_RECONNECT = "WiFi.reconnect();"
GOT_IP_REGISTRATION = "WiFi.onEvent(captureWifiGotIp, ARDUINO_EVENT_WIFI_STA_GOT_IP);"
GOT_IP_SIGNATURE = "static void captureWifiGotIp(arduino_event_t *event)"
IPST_SET_SIGNATURE = "inline void ipst_set(const String& value)"
IPST_COPY_SIGNATURE = "inline void ipst_copy(char (&copy)[sizeof(ipst)])"
DISCONNECT_ORPHANS = (
    "lastWifiDisconnectReason",
    "captureWifiDisconnectReason",
)


def policy_errors(source: str) -> list[str]:
    errors: list[str] = []
    helpers = (ROOT / "runtime_helpers.h").read_text(encoding="utf-8")
    blynk = (ROOT / "Blynk.ino").read_text(encoding="utf-8")
    menu = (ROOT / "Menu.ino").read_text(encoding="utf-8")
    samovar_header = (ROOT / "Samovar.h").read_text(encoding="utf-8")
    setup_body = extract_function_body(source, "static void setup_wifi_stack_defaults()")
    trigger_body = extract_function_body(source, "void triggerGetClock(void *parameter)")
    try:
        got_ip_body = extract_function_body(source, GOT_IP_SIGNATURE)
        ipst_set_body = extract_function_body(helpers, IPST_SET_SIGNATURE)
        ipst_copy_body = extract_function_body(helpers, IPST_COPY_SIGNATURE)
        blynk_slow_body = extract_function_body(blynk, "static void blynk_push_slow(bool force)")
        usb_body = extract_function_body(source, "inline void tick_usb_serial_command()")
        config_body = extract_function_body(source, "void apply_config_runtime()")
    except ValueError:
        return ["GOT_IP/ipst helper is missing"]

    if AUTO_RECONNECT not in setup_body:
        errors.append("auto-reconnect WiFi core is not enabled")
    if MANUAL_RECONNECT in trigger_body:
        errors.append("GetClockTicker still manually restarts WiFi")
    for token in DISCONNECT_ORPHANS:
        if token in source:
            errors.append(f"manual reconnect diagnostic orphan remains: {token}")
    if setup_body.count(GOT_IP_REGISTRATION) != 1:
        errors.append("GOT_IP callback must be registered exactly once")
    if "ipst_set(WiFi.localIP().toString());" not in got_ip_body:
        errors.append("GOT_IP callback does not update ipst from WiFi.localIP")
    for forbidden in ("Blynk", "WriteConsoleLog", "WiFi.reconnect"):
        if forbidden in got_ip_body:
            errors.append(f"GOT_IP callback performs forbidden work: {forbidden}")
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
    returncode, _ = compile_and_run(
        build_harness(ipst_set_body, ipst_copy_body, callback_body), True
    )
    if returncode != 0:
        return 1

    policy_mutants = (
        (
            source.replace(AUTO_RECONNECT, "WiFi.setAutoReconnect(false);", 1),
            "auto-reconnect WiFi core is not enabled",
        ),
        (
            source.replace("counter++;", "counter++;\n    WiFi.reconnect();", 1),
            "GetClockTicker still manually restarts WiFi",
        ),
    )
    for mutant, expected_error in policy_mutants:
        if expected_error not in policy_errors(mutant):
            print(f"FAIL: WiFi policy mutation survived: {expected_error}", file=sys.stderr)
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

    print("WiFi reconnect and GOT_IP mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
