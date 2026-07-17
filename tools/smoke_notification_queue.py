#!/usr/bin/env python3
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]

FAILURE_CODES = (
    "notify_queue_push_lock_busy",
    "notify_queue_push_failed",
    "notify_queue_pop_lock_busy",
    "notify_queue_pop_failed",
    "notify_telegram_delivery_failed",
    "notify_blynk_disconnected",
)

HARNESS = r'''
#include <chrono>
#include <condition_variable>
#include <functional>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "simple_queue.h"

namespace {

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

struct DeliveryProbe {
  bool telegramConfigured = false;
  bool telegramFails = false;
  bool blynkConfigured = false;
  bool blynkConnected = false;
  int telegramCalls = 0;
  int blynkCalls = 0;
  std::function<void()> telegramHook;
};

class NotificationCoordinator {
 public:
  NotificationCoordinator() : queue_(5, 200) {}

  bool push(const std::string& message) {
    if (!mutex_.try_lock_for(std::chrono::milliseconds(50))) {
      codes.push_back("notify_queue_push_lock_busy");
      return false;
    }
    const bool pushed = queue_.push(message.c_str());
    mutex_.unlock();
    if (!pushed) codes.push_back("notify_queue_push_failed");
    return pushed;
  }

  bool consume(DeliveryProbe& probe) {
    char text[200] = {};
    bool hadMessage = false;
    bool popped = false;
    if (!mutex_.try_lock_for(std::chrono::milliseconds(50))) {
      codes.push_back("notify_queue_pop_lock_busy");
      return false;
    }
    hadMessage = !queue_.isEmpty();
    if (hadMessage) popped = queue_.pop(text);
    mutex_.unlock();

    if (hadMessage && !popped) {
      codes.push_back("notify_queue_pop_failed");
      return false;
    }
    if (!popped) return false;

    const std::string message(text);
    poppedMessages.push_back(message);
    bool telegramFailed = false;
    bool blynkDisconnected = false;
    if (probe.telegramConfigured) {
      probe.telegramCalls++;
      if (probe.telegramHook) probe.telegramHook();
      telegramFailed = probe.telegramFails;
    }
    if (probe.blynkConfigured) {
      if (probe.blynkConnected) {
        probe.blynkCalls++;
      } else {
        blynkDisconnected = true;
      }
    }
    if (telegramFailed) codes.push_back("notify_telegram_delivery_failed");
    if (blynkDisconnected) codes.push_back("notify_blynk_disconnected");
    return true;
  }

  size_t count() {
    std::lock_guard<std::timed_mutex> lock(mutex_);
    return queue_.getCount();
  }

  std::vector<std::string> codes;
  std::vector<std::string> poppedMessages;

 private:
  SimpleStringQueue queue_;
  std::timed_mutex mutex_;
};

void test_network_does_not_hold_queue_lock() {
  NotificationCoordinator coordinator;
  check(coordinator.push("A"), "failed to enqueue A");

  std::mutex barrierMutex;
  std::condition_variable barrierCv;
  bool enteredNetwork = false;
  bool releaseNetwork = false;
  DeliveryProbe probe;
  probe.telegramConfigured = true;
  probe.blynkConfigured = true;
  probe.blynkConnected = true;
  probe.telegramHook = [&]() {
    std::unique_lock<std::mutex> lock(barrierMutex);
    enteredNetwork = true;
    barrierCv.notify_all();
    barrierCv.wait(lock, [&]() { return releaseNetwork; });
  };

  std::thread consumer([&]() { coordinator.consume(probe); });
  {
    std::unique_lock<std::mutex> lock(barrierMutex);
    check(barrierCv.wait_for(lock, std::chrono::seconds(1),
                             [&]() { return enteredNetwork; }),
          "consumer did not enter fake Telegram I/O");
  }

  const auto started = std::chrono::steady_clock::now();
  check(coordinator.push("B"), "producer blocked during Telegram I/O");
  const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started);
  check(elapsed.count() < 100, "producer exceeded 100 ms during Telegram I/O");

  {
    std::lock_guard<std::mutex> lock(barrierMutex);
    releaseNetwork = true;
  }
  barrierCv.notify_all();
  consumer.join();
  check(probe.telegramCalls == 1 && probe.blynkCalls == 1,
        "one integration skipped the other");
  check(coordinator.count() == 1, "B was not retained while A was delivered");
}

void test_fifo_capacity_and_queue_failures() {
  NotificationCoordinator fifo;
  DeliveryProbe none;
  check(fifo.push("A") && fifo.push("B") && fifo.push("C"),
        "FIFO setup push failed");
  check(fifo.consume(none) && fifo.consume(none) && fifo.consume(none),
        "FIFO consume failed");
  check(fifo.poppedMessages == std::vector<std::string>({"A", "B", "C"}),
        "FIFO order changed");

  NotificationCoordinator full;
  for (int index = 0; index < 5; index++) {
    check(full.push("item-" + std::to_string(index)), "capacity setup failed");
  }
  check(!full.push("sixth"), "sixth item was accepted");
  check(full.count() == 5, "failed push changed queue capacity");
  check(full.codes == std::vector<std::string>({"notify_queue_push_failed"}),
        "full queue did not emit one exact code");

}

void test_delivery_failure_is_one_shot() {
  NotificationCoordinator telegram;
  check(telegram.push("A"), "Telegram setup push failed");
  DeliveryProbe telegramFailure;
  telegramFailure.telegramConfigured = true;
  telegramFailure.telegramFails = true;
  telegramFailure.blynkConfigured = true;
  telegramFailure.blynkConnected = true;
  check(telegram.consume(telegramFailure), "Telegram failure did not pop once");
  check(telegramFailure.telegramCalls == 1 && telegramFailure.blynkCalls == 1,
        "Telegram failure skipped Blynk");
  check(telegram.codes ==
            std::vector<std::string>({"notify_telegram_delivery_failed"}),
        "Telegram failure code mismatch");
  check(telegram.count() == 0 && !telegram.consume(telegramFailure),
        "delivery failure requeued the message");

}

}  // namespace

int main() {
  test_network_does_not_hold_queue_lock();
  test_fifo_capacity_and_queue_failures();
  test_delivery_failure_is_one_shot();
  if (failures != 0) return 1;
  std::cout << "notification queue behavioral checks passed\n";
  return 0;
}
'''


PRODUCTION_BLOCK_HARNESS = r'''
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#define F(value) value
#define SAMOVAR_USE_BLYNK
#define USE_TELEGRAM
#define V26 26
#define pdTRUE 1
#define portTICK_RATE_MS 1
#define portTICK_PERIOD_MS 1

using BaseType_t = int;
using TickType_t = int;

class String {
 public:
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  const char* c_str() const { return value_.c_str(); }
  bool operator==(const char* value) const {
    return value_ == (value ? value : "");
  }

  friend String operator+(const String& left, const char* right) {
    return String(left.value_ + (right ? right : ""));
  }
  friend String operator+(const String& left, const String& right) {
    return String(left.value_ + right.value_);
  }

 private:
  std::string value_;
};

struct QueueProbe {
  bool empty = true;
  bool pushResult = true;
  bool popResult = true;
  int emptyCalls = 0;
  int pushCalls = 0;
  int popCalls = 0;

  bool isEmpty() {
    emptyCalls++;
    return empty;
  }
  bool push(const char*) {
    pushCalls++;
    return pushResult;
  }
  bool pop(char* output) {
    popCalls++;
    if (popResult) std::strcpy(output, "A");
    return popResult;
  }
};

int telegramCalls = 0;
int blynkCheckCalls = 0;
int blynkWriteCalls = 0;
bool blynkConnected = true;
String telegramResponse("OK");
std::vector<std::string> actions;

struct SetupProbe {
  char tg_token[2];
  char tg_chat_id[2];
  char blynkauth[2];
} SamSetup = {};

struct BlynkProbe {
  bool connected() const {
    blynkCheckCalls++;
    actions.push_back("blynk_check");
    return blynkConnected;
  }
  void virtualWrite(int, const String&) {
    blynkWriteCalls++;
    actions.push_back("blynk_write");
  }
} Blynk;

String urlEncode(const String& value) { return value; }

String http_sync_request_get(String) {
  telegramCalls++;
  actions.push_back("telegram");
  return telegramResponse;
}

QueueProbe msg_q;
void* xMsgSemaphore = nullptr;
BaseType_t takeResult = pdTRUE;
int takeCalls = 0;
int giveCalls = 0;
std::vector<std::string> codes;
int failures = 0;

BaseType_t xSemaphoreTake(void*, TickType_t) {
  takeCalls++;
  return takeResult;
}

BaseType_t xSemaphoreGive(void*) {
  giveCalls++;
  actions.push_back("give");
  return pdTRUE;
}

void WriteConsoleLog(const char* code) {
  codes.emplace_back(code);
  actions.push_back(std::string("log:") + code);
}

void vTaskDelay(int) {}

void runProducerBlock() {
  String MsgPl("payload");
@PRODUCER_BLOCK@
}

void runConsumerBlock() {
@CONSUMER_BLOCK@
}

void resetProbe() {
  msg_q = QueueProbe{};
  takeResult = pdTRUE;
  takeCalls = 0;
  giveCalls = 0;
  codes.clear();
  actions.clear();
  telegramCalls = 0;
  blynkCheckCalls = 0;
  blynkWriteCalls = 0;
  telegramResponse = "OK";
  blynkConnected = true;
  SamSetup.tg_token[0] = '\0';
  SamSetup.tg_chat_id[0] = '\0';
  SamSetup.blynkauth[0] = '\0';
}

void configureIntegrations() {
  SamSetup.tg_token[0] = 't';
  SamSetup.tg_chat_id[0] = 'c';
  SamSetup.blynkauth[0] = 'b';
}

void check(bool condition, const char* message) {
  if (condition) return;
  std::cerr << "FAIL: " << message << '\n';
  failures++;
}

void checkProducerReleasePaths() {
  resetProbe();
  runProducerBlock();
  check(takeCalls == 1 && msg_q.pushCalls == 1 && giveCalls == 1 &&
            codes.empty() && actions == std::vector<std::string>({"give"}),
        "producer success must give once without diagnostics");

  resetProbe();
  msg_q.pushResult = false;
  runProducerBlock();
  check(msg_q.pushCalls == 1 && giveCalls == 1 &&
            codes == std::vector<std::string>({"notify_queue_push_failed"}) &&
            actions == std::vector<std::string>({
                "give", "log:notify_queue_push_failed"}),
        "producer push failure must give before its only diagnostic");

  resetProbe();
  takeResult = 0;
  runProducerBlock();
  check(msg_q.pushCalls == 0 && giveCalls == 0 &&
            codes == std::vector<std::string>({"notify_queue_push_lock_busy"}) &&
            actions == std::vector<std::string>({
                "log:notify_queue_push_lock_busy"}),
        "producer take failure must not give and must emit only lock_busy");
}

void checkConsumerReleasePaths() {
  resetProbe();
  runConsumerBlock();
  check(msg_q.emptyCalls == 1 && msg_q.popCalls == 0 && giveCalls == 1 &&
            codes.empty() && actions == std::vector<std::string>({"give"}) &&
            telegramCalls == 0 && blynkCheckCalls == 0 && blynkWriteCalls == 0,
        "empty consumer path must give once without diagnostics");

  resetProbe();
  msg_q.empty = false;
  runConsumerBlock();
  check(msg_q.popCalls == 1 && giveCalls == 1 && codes.empty(),
        "successful consumer pop must give once");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  msg_q.popResult = false;
  runConsumerBlock();
  check(msg_q.popCalls == 1 && giveCalls == 1 &&
            codes == std::vector<std::string>({"notify_queue_pop_failed"}) &&
            actions == std::vector<std::string>({
                "give", "log:notify_queue_pop_failed"}) &&
            telegramCalls == 0 && blynkCheckCalls == 0 && blynkWriteCalls == 0,
        "consumer pop failure must give before its only diagnostic");

  resetProbe();
  configureIntegrations();
  takeResult = 0;
  runConsumerBlock();
  check(msg_q.emptyCalls == 0 && msg_q.popCalls == 0 && giveCalls == 0 &&
            codes == std::vector<std::string>({"notify_queue_pop_lock_busy"}) &&
            actions == std::vector<std::string>({
                "log:notify_queue_pop_lock_busy"}) &&
            telegramCalls == 0 && blynkCheckCalls == 0 && blynkWriteCalls == 0,
        "consumer take failure must not give and must emit only lock_busy");
}

void checkIntegrationPaths() {
  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  telegramResponse = "<ERR>";
  runConsumerBlock();
  check(telegramCalls == 1 && blynkCheckCalls == 1 && blynkWriteCalls == 1 &&
            codes == std::vector<std::string>({
                "notify_telegram_delivery_failed"}) &&
            actions == std::vector<std::string>({
                "give", "telegram", "blynk_check", "blynk_write",
                "log:notify_telegram_delivery_failed"}),
        "Telegram failure must not skip connected Blynk before its diagnostic");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  blynkConnected = false;
  runConsumerBlock();
  check(telegramCalls == 1 && blynkCheckCalls == 1 && blynkWriteCalls == 0 &&
            codes == std::vector<std::string>({"notify_blynk_disconnected"}) &&
            actions == std::vector<std::string>({
                "give", "telegram", "blynk_check",
                "log:notify_blynk_disconnected"}),
        "Blynk disconnect must be diagnosed after successful Telegram");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  telegramResponse = "<ERR>";
  blynkConnected = false;
  runConsumerBlock();
  check(telegramCalls == 1 && blynkCheckCalls == 1 && blynkWriteCalls == 0 &&
            codes == std::vector<std::string>({
                "notify_telegram_delivery_failed", "notify_blynk_disconnected"}) &&
            actions == std::vector<std::string>({
                "give", "telegram", "blynk_check",
                "log:notify_telegram_delivery_failed",
                "log:notify_blynk_disconnected"}),
        "both diagnostics must follow both failed integration attempts");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  runConsumerBlock();
  check(telegramCalls == 1 && blynkCheckCalls == 1 && blynkWriteCalls == 1 &&
            codes.empty() && actions == std::vector<std::string>({
                "give", "telegram", "blynk_check", "blynk_write"}),
        "successful integrations must not emit diagnostics");
}

int main() {
  checkProducerReleasePaths();
  checkConsumerReleasePaths();
  checkIntegrationPaths();
  if (failures != 0) return 1;
  std::cout << "production queue blocks passed\n";
  return 0;
}
'''


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def require_order(body: str, tokens: tuple[str, ...], name: str, errors: list[str]) -> None:
    offset = 0
    for token in tokens:
        found = body.find(token, offset)
        if found < 0:
            errors.append(f"{name}: missing ordered token {token!r}")
            return
        offset = found + len(token)


def check_source_contract() -> list[str]:
    errors: list[str] = []
    source = strip_cpp_comments((ROOT / "Samovar.ino").read_text(encoding="utf-8"))
    queue_source = strip_cpp_comments(
        (ROOT / "libraries/simple_queue/simple_queue.h").read_text(encoding="utf-8")
    )
    try:
        send_body = extract_function_body(source, "void SendMsg(")
        clock_body = extract_function_body(source, "void triggerGetClock(")
        log_body = extract_function_body(source, "void WriteConsoleLog(")
    except ValueError as error:
        return [str(error)]

    require("SimpleStringQueue msg_q(5, 200);" in source,
            "queue capacity/item size changed", errors)
    require("bool push(const char* item)" in queue_source and
            "bool pop(char* item)" in queue_source,
            "vendor queue result API changed", errors)
    require(send_body.count("msg_q.push(") == 1,
            "SendMsg must perform exactly one push", errors)
    require(clock_body.count("msg_q.isEmpty()") == 1,
            "consumer must make one locked empty check", errors)
    require(clock_body.count("msg_q.pop(") == 1,
            "consumer must perform at most one pop", errors)
    require("queuePushResult = msg_q.push(" in send_body,
            "push result is not checked", errors)
    require("queuePopResult = msg_q.pop(" in clock_body,
            "pop result is not checked", errors)

    require_order(
        send_body,
        ("MqttSendMsg(", "xSemaphoreTake(", "msg_q.push(",
         "xSemaphoreGive(", "WriteConsoleLog("),
        "SendMsg",
        errors,
    )
    require_order(
        clock_body,
        ("xSemaphoreTake(", "msg_q.isEmpty()", "msg_q.pop(",
         "xSemaphoreGive(", "String qMsg", "http_sync_request_get(",
         "Blynk.virtualWrite(", "WriteConsoleLog("),
        "triggerGetClock notification block",
        errors,
    )

    send_take = send_body.find("xSemaphoreTake(")
    send_give = send_body.find("xSemaphoreGive(", send_take)
    clock_take = clock_body.find("xSemaphoreTake(", clock_body.find("queueTakeResult"))
    clock_give = clock_body.find("xSemaphoreGive(", clock_take)
    for name, critical in (
        ("SendMsg", send_body[send_take:send_give]),
        ("triggerGetClock", clock_body[clock_take:clock_give]),
    ):
        for forbidden in ("WriteConsoleLog(", "http_sync_request_get(",
                          "Blynk.", "String ", "vTaskDelay("):
            require(forbidden not in critical,
                    f"{name}: {forbidden} remains under xMsgSemaphore", errors)

    require("#ifdef USE_TELEGRAM" in send_body and
            send_body.find("#ifdef USE_TELEGRAM") < send_body.find("msg_q.push("),
            "Telegram-only enqueue guard changed", errors)
    require("#ifdef USE_MQTT" in send_body and "MqttSendMsg(" in send_body,
            "MQTT side effect/guard changed", errors)
    require("#ifdef SAMOVAR_USE_BLYNK" in clock_body,
            "Blynk delivery guard changed", errors)
    require('== "<ERR>"' in clock_body,
            "Telegram <ERR> result is not checked", errors)
    require("Blynk.connected()" in clock_body and
            "SamSetup.blynkauth[0] != 0" in clock_body,
            "Blynk configured/disconnected check missing", errors)
    require(clock_body.find("http_sync_request_get(") <
            clock_body.find("Blynk.virtualWrite(") <
            clock_body.find("notify_telegram_delivery_failed"),
            "integration attempts must finish before delivery diagnostics", errors)
    require("msg_q.push(" not in clock_body and "msg_q.pop(" not in send_body,
            "queue retry/requeue path added", errors)
    require("SendMsg(" not in log_body and "msg_q." not in log_body and
            "xMsgSemaphore" not in log_body,
            "WriteConsoleLog recurses into notification queue", errors)

    for code in FAILURE_CODES:
        require(source.count(f'F("{code}")') == 1,
                f"failure code {code!r} must appear exactly once", errors)
    return errors


def build_production_block_harness() -> str:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    send_body = extract_function_body(source, "void SendMsg(")
    clock_body = extract_function_body(source, "void triggerGetClock(")

    producer_start = send_body.find("const BaseType_t queueTakeResult =")
    producer_end = send_body.find("#endif", producer_start)
    if producer_start < 0 or producer_end < 0:
        raise ValueError("SendMsg queue block not found")
    producer_block = send_body[producer_start:producer_end]
    consumer_block = extract_function_body(
        clock_body, "if (WiFi.status() == WL_CONNECTED && !ota_running)"
    )
    return (PRODUCTION_BLOCK_HARNESS
            .replace("@PRODUCER_BLOCK@", producer_block)
            .replace("@CONSUMER_BLOCK@", consumer_block))


def compile_and_run_harness(
    compiler: str,
    temp: Path,
    name: str,
    harness: str,
    success_marker: str,
) -> list[str]:
    source = temp / f"{name}.cpp"
    binary = temp / name
    source.write_text(harness, encoding="utf-8")
    command = [
        compiler,
        "-std=c++11",
        "-pthread",
        "-Wall",
        "-Wextra",
        "-Werror",
        f"-I{temp}",
        f"-I{ROOT / 'libraries/simple_queue'}",
        str(source),
        "-o",
        str(binary),
    ]
    compiled = subprocess.run(command, text=True, capture_output=True)
    if compiled.returncode != 0:
        return [f"{name} compile failed:\n{compiled.stdout}{compiled.stderr}"]
    executed = subprocess.run([str(binary)], text=True, capture_output=True)
    if executed.returncode != 0:
        return [f"{name} failed:\n{executed.stdout}{executed.stderr}"]
    if success_marker not in executed.stdout:
        return [f"{name} did not emit its success marker"]
    return []


def run_harness() -> list[str]:
    compiler = shutil.which("g++")
    if compiler is None:
        return ["g++ is required for the notification queue behavioral gate"]
    try:
        production_harness = build_production_block_harness()
    except ValueError as error:
        return [str(error)]
    with tempfile.TemporaryDirectory(prefix="samovar-notification-queue-") as directory:
        temp = Path(directory)
        (temp / "Arduino.h").write_text(
            "#pragma once\n#include <cstddef>\n#include <cstdint>\n#include <cstring>\n",
            encoding="utf-8",
        )
        errors = compile_and_run_harness(
            compiler,
            temp,
            "notification_queue_behavioral",
            HARNESS,
            "notification queue behavioral checks passed",
        )
        errors.extend(compile_and_run_harness(
            compiler,
            temp,
            "notification_queue_production_blocks",
            production_harness,
            "production queue blocks passed",
        ))
        if errors:
            return errors
    return []


def main() -> int:
    errors = check_source_contract()
    errors.extend(run_harness())
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("Notification queue checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
