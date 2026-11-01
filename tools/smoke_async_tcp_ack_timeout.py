#!/usr/bin/env python3
"""Проверяет тайм-аут подтверждения в AsyncClient::_poll, в том числе после суток работы."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "libraries/Async_TCP/src/AsyncTCP.cpp"
HEADER = ROOT / "libraries/Async_TCP/src/AsyncTCP.h"
POLL_SIGNATURE = "int8_t AsyncClient::_poll(tcp_pcb *pcb)"
FIXED_CONDITION = "_tx_last_packet != 0 && (_rx_last_ack == 0 || (_rx_last_ack - _tx_last_packet + one_day) < one_day)"

HARNESS = r'''
#include <cinttypes>
#include <cstdint>
#include <iostream>

#define ERR_OK 0
#define async_tcp_log_d(...) ((void)0)
#define async_tcp_log_elapsed(name, expression) expression

struct tcp_pcb { int state = 0; };
static uint32_t currentMillis = 0;
static uint32_t millis() { return currentMillis; }
static int failures = 0;

class AsyncClient;
static int timeouts = 0, polls = 0, closes = 0;
static uint32_t lastTimeoutAge = 0;
static void onTimeout(void *, AsyncClient *, uint32_t age) { timeouts++; lastTimeoutAge = age; }
static void onPoll(void *, AsyncClient *) { polls++; }

class AsyncClient {
 public:
  tcp_pcb *_pcb = nullptr;
  uint32_t _tx_last_packet = 0, _rx_last_ack = 0, _rx_last_packet = 0;
  uint32_t _ack_timeout = 3000, _rx_timeout = 0;
  void *_timeout_cb_arg = nullptr, *_poll_cb_arg = nullptr;
  void (*_timeout_cb)(void *, AsyncClient *, uint32_t) = onTimeout;
  void (*_poll_cb)(void *, AsyncClient *) = onPoll;
  void _close() { closes++; }
  int8_t _poll(tcp_pcb *pcb);
};

int8_t AsyncClient::_poll(tcp_pcb *pcb) {
@POLL_BODY@
}

static constexpr uint32_t HOUR = 3600000UL;

static void poll(uint32_t tx, uint32_t ack, uint32_t now) {
  tcp_pcb pcb;
  AsyncClient client;
  client._pcb = &pcb;
  client._tx_last_packet = tx;
  client._rx_last_ack = ack;
  client._rx_last_packet = tx;
  currentMillis = now;
  timeouts = 0;
  polls = 0;
  lastTimeoutAge = 0;
  client._poll(&pcb);
}

static void expectTimeout(const char *name, uint32_t tx, uint32_t ack, uint32_t now) {
  poll(tx, ack, now);
  if (timeouts != 1 || polls != 0 || lastTimeoutAge != now - tx) {
    std::cerr << "FAIL: ack timeout missing: " << name << '\n';
    failures++;
  }
}

static void expectAlive(const char *name, uint32_t tx, uint32_t ack, uint32_t now) {
  poll(tx, ack, now);
  if (timeouts != 0 || polls != 1) {
    std::cerr << "FAIL: false ack timeout: " << name << '\n';
    failures++;
  }
}

int main() {
  expectTimeout("no ACK yet, first hour", 1 * HOUR, 0, 1 * HOUR + 3000);
  expectTimeout("no ACK yet, after one day", 25 * HOUR, 0, 25 * HOUR + 3000);
  expectTimeout("no ACK yet, after twenty days", 480 * HOUR, 0, 480 * HOUR + 7000);
  expectTimeout("newer data after old ACK", 25 * HOUR, 25 * HOUR - 500, 25 * HOUR + 3000);
  expectTimeout("millis wrap", 0xFFFFFF00UL, 0xFFFFFE00UL, 0x00000C00UL);

  expectAlive("nothing sent, after one day", 0, 0, 25 * HOUR);
  expectAlive("nothing sent, first hour", 0, 0, 1 * HOUR);
  expectAlive("no ACK yet, under the limit", 25 * HOUR, 0, 25 * HOUR + 2999);
  expectAlive("ACK after last data", 25 * HOUR, 25 * HOUR + 40, 25 * HOUR + 3000);
  expectAlive("ACK in the same millisecond", 25 * HOUR, 25 * HOUR, 25 * HOUR + 3000);
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(poll_body: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-ack-timeout-") as temp_dir:
        source_path = Path(temp_dir) / "harness.cpp"
        binary_path = Path(temp_dir) / "harness"
        source_path.write_text(HARNESS.replace("@POLL_BODY@", poll_body), encoding="utf-8")
        result = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return result.returncode, "COMPILE: " + result.stderr
        result = subprocess.run([str(binary_path)], capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr


def main() -> int:
    if "#define CONFIG_ASYNC_TCP_MAX_ACK_TIME 10000 " not in HEADER.read_text(encoding="utf-8"):
        print(
            "FAIL: ack timeout must stay 10 s: lwIP resends a lost packet after up to 3 s, "
            "a shorter limit cuts files on a lossy Wi-Fi",
            file=sys.stderr,
        )
        return 1

    body = extract_function_body(SOURCE.read_text(encoding="utf-8"), POLL_SIGNATURE)
    returncode, output = compile_and_run(body)
    if returncode != 0:
        print(output, file=sys.stderr)
        return 1

    mutants = (
        (
            "(_rx_last_ack - _tx_last_packet + one_day) < one_day",
            "FAIL: ack timeout missing: no ACK yet, after one day",
        ),
        (
            "_rx_last_ack == 0 || (_rx_last_ack - _tx_last_packet + one_day) < one_day",
            "FAIL: false ack timeout: nothing sent, after one day",
        ),
        ("true", "FAIL: false ack timeout: ACK after last data"),
    )
    for replacement, expected_failure in mutants:
        mutant = body.replace(FIXED_CONDITION, replacement, 1)
        if mutant == body:
            print("FAIL: could not create ack timeout mutation", file=sys.stderr)
            return 1
        returncode, output = compile_and_run(mutant)
        if returncode == 0 or expected_failure not in output:
            print(
                f"FAIL: ack timeout mutation survived or failed for the wrong reason: {replacement}\n{output}",
                file=sys.stderr,
            )
            return 1

    print("AsyncClient ack timeout scenarios and mutations were checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
