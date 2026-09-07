#!/usr/bin/env python3
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body


ROOT = Path(__file__).resolve().parents[1]
CALLBACK_SIGNATURE = "static void captureWifiDisconnectReason(arduino_event_t *event)"
RECONNECT_TOKEN = "if (!ota_running && millis() - wifiReconnectTimer >= 20000) {"
REGISTRATION = (
    "WiFi.onEvent(captureWifiDisconnectReason, "
    "ARDUINO_EVENT_WIFI_STA_DISCONNECTED);"
)


def build_harness(callback_body: str, reconnect_body: str) -> str:
    return f'''#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>

using std::uint8_t;
using std::uint32_t;

enum wifi_err_reason_t {{
  WIFI_REASON_UNSPECIFIED = 1,
}};

struct WifiStaDisconnected {{
  uint8_t reason;
}};

struct ArduinoEventInfo {{
  WifiStaDisconnected wifi_sta_disconnected;
}};

struct arduino_event_t {{
  ArduinoEventInfo event_info;
}};

struct FakeWiFi {{
  int currentStatus = 0;
  int reconnectCalls = 0;

  int status() const {{ return currentStatus; }}

  const char* disconnectReasonName(wifi_err_reason_t reason) const {{
    if (static_cast<int>(reason) == 200) return "BEACON_TIMEOUT";
    if (static_cast<int>(reason) == 2) return "AUTH_EXPIRE";
    return "UNSPECIFIED";
  }}

  void reconnect() {{ reconnectCalls++; }}
}} WiFi;

struct FakeESP {{
  uint32_t freeHeap = 0;
  uint32_t maxAllocHeap = 0;
  uint32_t minFreeHeap = 0;

  uint32_t getFreeHeap() const {{ return freeHeap; }}
  uint32_t getMaxAllocHeap() const {{ return maxAllocHeap; }}
  uint32_t getMinFreeHeap() const {{ return minFreeHeap; }}
}} ESP;

volatile uint8_t lastWifiDisconnectReason = WIFI_REASON_UNSPECIFIED;
unsigned long wifiReconnectTimer = 0;
unsigned long currentMillis = 0;
std::string lastLog;
int failures = 0;

unsigned long millis() {{ return currentMillis; }}

void WriteConsoleLog(const char* message) {{
  lastLog = message;
}}

void check(bool condition, const char* message) {{
  if (!condition) {{
    std::cerr << "FAIL: " << message << '\\n';
    failures++;
  }}
}}

static void captureWifiDisconnectReason(arduino_event_t *event) {{
{callback_body}
}}

void runReconnectAttempt() {{
{reconnect_body}
}}

void setDisconnectReason(uint8_t reason) {{
  arduino_event_t event{{}};
  event.event_info.wifi_sta_disconnected.reason = reason;
  captureWifiDisconnectReason(&event);
}}

int main() {{
  setDisconnectReason(200);
  WiFi.currentStatus = 5;
  ESP.freeHeap = 50000;
  ESP.maxAllocHeap = 24000;
  ESP.minFreeHeap = 31000;
  currentMillis = 25000;
  runReconnectAttempt();

  check(lastLog.find("reason=200(BEACON_TIMEOUT)") != std::string::npos,
        "captured disconnect reason missing from diagnostic");
  check(lastLog.find("heap=50000 max_alloc=24000 min_heap=31000") != std::string::npos,
        "memory metrics missing from diagnostic");
  check(lastLog == "WiFi.reconnect status=5 reason=200(BEACON_TIMEOUT) heap=50000 max_alloc=24000 min_heap=31000",
        "first reconnect diagnostic changed");
  check(WiFi.reconnectCalls == 1, "reconnect was not called exactly once");
  check(wifiReconnectTimer == 25000, "reconnect timer was not updated");

  setDisconnectReason(2);
  WiFi.currentStatus = 6;
  ESP.freeHeap = 42000;
  ESP.maxAllocHeap = 17000;
  ESP.minFreeHeap = 26000;
  currentMillis = 51000;
  runReconnectAttempt();

  check(lastLog.find("reason=2(AUTH_EXPIRE)") != std::string::npos,
        "second disconnect reason missing from diagnostic");
  check(lastLog.find("heap=42000 max_alloc=17000 min_heap=26000") != std::string::npos,
        "second memory sample missing from diagnostic");
  check(WiFi.reconnectCalls == 2, "second reconnect was not called");
  check(wifiReconnectTimer == 51000, "second reconnect timer was not updated");

  if (failures != 0) return 1;
  std::cout << "WiFi reconnect diagnostics checks passed\\n";
  return 0;
}}
'''


def compile_and_run(source: str, label: str, emit_failure: bool) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-wifi-reconnect-") as temp_dir:
        source_path = Path(temp_dir) / "harness.cpp"
        binary_path = Path(temp_dir) / "harness"
        source_path.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source_path),
                "-o",
                str(binary_path),
            ],
            capture_output=True,
            text=True,
        )
        if compile_result.returncode != 0:
            if emit_failure:
                print(f"FAIL: {label} harness did not compile", file=sys.stderr)
                print(compile_result.stderr, file=sys.stderr)
            return compile_result.returncode, compile_result.stderr

        run_result = subprocess.run(
            [str(binary_path)], capture_output=True, text=True
        )
        output = run_result.stdout + run_result.stderr
        if emit_failure and run_result.returncode != 0:
            print(output, file=sys.stderr)
        return run_result.returncode, output


def main() -> int:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    callback_body = extract_function_body(source, CALLBACK_SIGNATURE)
    trigger_body = extract_function_body(source, "void triggerGetClock(void *parameter)")
    reconnect_body, _ = extract_braced_block_after(trigger_body, RECONNECT_TOKEN)
    setup_body = extract_function_body(source, "static void setup_wifi_stack_defaults()")

    if REGISTRATION not in setup_body:
        print("FAIL: disconnect callback is not registered", file=sys.stderr)
        return 1

    harness = build_harness(callback_body, reconnect_body)
    returncode, _ = compile_and_run(harness, "production", True)
    if returncode != 0:
        return 1

    mutations = (
        (
            callback_body.replace(
                "lastWifiDisconnectReason = event->event_info.wifi_sta_disconnected.reason;",
                "lastWifiDisconnectReason = event ? WIFI_REASON_UNSPECIFIED : WIFI_REASON_UNSPECIFIED;",
                1,
            ),
            reconnect_body,
            "disconnect reason capture",
            "captured disconnect reason missing from diagnostic",
        ),
        (
            callback_body,
            reconnect_body.replace(
                "ESP.getMaxAllocHeap()", "ESP.getFreeHeap()", 1
            ),
            "largest free block",
            "memory metrics missing from diagnostic",
        ),
    )
    for mutated_callback, mutated_reconnect, label, expected_failure in mutations:
        mutant = build_harness(mutated_callback, mutated_reconnect)
        returncode, output = compile_and_run(mutant, label, False)
        if returncode == 0:
            print(f"FAIL: {label} mutation survived", file=sys.stderr)
            return 1
        if expected_failure not in output:
            print(
                f"FAIL: {label} mutation failed for the wrong reason",
                file=sys.stderr,
            )
            print(output, file=sys.stderr)
            return 1

    print("WiFi reconnect diagnostic mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
