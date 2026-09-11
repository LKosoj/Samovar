#!/usr/bin/env python3
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]

FAILURE_CODES = (
    "notify_queue_push_lock_busy",
    "notify_queue_push_failed",
    "notify_queue_peek_lock_busy",
    "notify_queue_peek_failed",
    "notify_queue_pop_lock_busy",
    "notify_queue_pop_failed",
    "notify_queue_delivery_expired",
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
    const bool pushed = queue_.push(message.c_str(), nowMillis_);
    mutex_.unlock();
    if (!pushed) codes.push_back("notify_queue_push_failed");
    return pushed;
  }

  bool consume(DeliveryProbe& probe) {
    char text[200] = {};
    uint32_t queuedAtMillis = 0;
    bool hadMessage = false;
    bool peeked = false;
    if (!mutex_.try_lock_for(std::chrono::milliseconds(50))) {
      codes.push_back("notify_queue_peek_lock_busy");
      return false;
    }
    hadMessage = !queue_.isEmpty();
    if (hadMessage) peeked = queue_.peek(text, &queuedAtMillis);
    mutex_.unlock();

    if (hadMessage && !peeked) {
      codes.push_back("notify_queue_peek_failed");
      return false;
    }
    if (!peeked) return false;

    const std::string message(text);
    if (!probe.blynkConfigured || !probe.blynkConnected) {
      codes.push_back("notify_blynk_disconnected");
      return false;
    }
    probe.blynkCalls++;
    if (probe.telegramHook) probe.telegramHook();

    if (!mutex_.try_lock_for(std::chrono::milliseconds(50))) {
      codes.push_back("notify_queue_pop_lock_busy");
      return false;
    }
    const bool popped = queue_.pop(text);
    mutex_.unlock();
    if (!popped) {
      codes.push_back("notify_queue_pop_failed");
      return false;
    }
    poppedMessages.push_back(message);
    return true;
  }

  size_t count() {
    std::lock_guard<std::timed_mutex> lock(mutex_);
    return queue_.getCount();
  }

  void advance(uint32_t elapsedMillis) { nowMillis_ += elapsedMillis; }

  std::vector<std::string> codes;
  std::vector<std::string> poppedMessages;

 private:
  SimpleStringQueue queue_;
  std::timed_mutex mutex_;
  uint32_t nowMillis_ = 0;
};

void test_network_does_not_hold_queue_lock() {
  NotificationCoordinator coordinator;
  check(coordinator.push("A"), "failed to enqueue A");

  std::mutex barrierMutex;
  std::condition_variable barrierCv;
  bool enteredNetwork = false;
  bool releaseNetwork = false;
  DeliveryProbe probe;
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
  check(probe.blynkCalls == 1, "Blynk send was skipped");
  check(coordinator.count() == 1, "B was not retained while A was delivered");
}

void test_fifo_capacity_and_queue_failures() {
  NotificationCoordinator fifo;
  DeliveryProbe connected;
  connected.blynkConfigured = true;
  connected.blynkConnected = true;
  check(fifo.push("A") && fifo.push("B") && fifo.push("C"),
        "FIFO setup push failed");
  check(fifo.consume(connected) && fifo.consume(connected) && fifo.consume(connected),
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

void test_delivery_failure_is_retained() {
  NotificationCoordinator coordinator;
  check(coordinator.push("A"), "notification setup push failed");
  DeliveryProbe disconnected;
  disconnected.blynkConfigured = true;
  check(!coordinator.consume(disconnected), "disconnected Blynk accepted notification");
  check(coordinator.count() == 1 && coordinator.poppedMessages.empty(),
        "disconnected Blynk lost notification");

  disconnected.blynkConnected = true;
  check(coordinator.consume(disconnected), "reconnected Blynk did not consume notification");
  check(disconnected.blynkCalls == 1 && coordinator.poppedMessages ==
            std::vector<std::string>({"A"}),
        "reconnected Blynk did not deliver the retained notification");
}

}  // namespace

int main() {
  test_network_does_not_hold_queue_lock();
  test_fifo_capacity_and_queue_failures();
  test_delivery_failure_is_retained();
  if (failures != 0) return 1;
  std::cout << "notification queue behavioral checks passed\n";
  return 0;
}
'''


PRODUCTION_BLOCK_HARNESS = r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#define F(value) value
#define SAMOVAR_USE_BLYNK
#define V26 26
#define pdTRUE 1
#define portTICK_RATE_MS 1
#define portTICK_PERIOD_MS 1
#define WL_CONNECTED 3

using BaseType_t = int;
using TickType_t = int;

enum MESSAGE_TYPE { ALARM_MSG, WARNING_MSG, NOTIFY_MSG, NONE_MSG };

class String {
 public:
  String(const char* value) : value_(value ? value : "") {}
  String(char value) : value_(1, value) {}
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
  bool peekResult = true;
  bool popResult = true;
  int emptyCalls = 0;
  int pushCalls = 0;
  int peekCalls = 0;
  int popCalls = 0;
  int flushCalls = 0;
  uint32_t queuedAtMillis = 0;
  const char* message = "2A";

  bool isEmpty() {
    emptyCalls++;
    return empty;
  }
  bool push(const char*, uint32_t queuedAt) {
    pushCalls++;
    queuedAtMillis = queuedAt;
    return pushResult;
  }
  bool peek(char* output, uint32_t* queuedAt) {
    peekCalls++;
    if (peekResult) {
      std::strcpy(output, message);
      if (queuedAt != nullptr) *queuedAt = queuedAtMillis;
    }
    return peekResult;
  }
  bool pop(char* output) {
    popCalls++;
    if (popResult) {
      std::strcpy(output, "A");
      empty = true;
    }
    return popResult;
  }
  void flush() {
    flushCalls++;
    empty = true;
  }
};

int blynkCheckCalls = 0;
int blynkWriteCalls = 0;
int blynkNotifyCalls = 0;
bool blynkConnected = true;
bool disconnectAfterWrite = false;
bool disconnectAfterNotify = false;
bool blynkTokenInvalid = false;
std::vector<std::string> actions;

struct SetupProbe {
  char blynkauth[2];
} SamSetup = {};

struct BlynkProbe {
  bool connected() const {
    blynkCheckCalls++;
    actions.push_back("blynk_check");
    return blynkConnected;
  }
  bool isTokenInvalid() const { return blynkTokenInvalid; }
  void virtualWrite(int, const String&) {
    blynkWriteCalls++;
    actions.push_back("blynk_write");
    if (disconnectAfterWrite) blynkConnected = false;
  }
  // Push через сервер Blynk идёт сразу после virtualWrite(V26) под тем же замком;
  // отдельного шага в последовательности действий не даёт.
  void notify(const String&) {
    blynkNotifyCalls++;
    actions.push_back("blynk_notify");
    if (disconnectAfterNotify) blynkConnected = false;
  }
} Blynk;

// Заглушка RAII-стража замка Blynk (runtime_helpers.h): библиотека Blynk не
// потокобезопасна, консьюмер уведомлений обязан брать замок и пропускать доставку,
// если его держит loop().
bool blynkLockAvailable = true;
int blynkLockTakes = 0;
#ifndef pdMS_TO_TICKS
#define pdMS_TO_TICKS(x) (x)
#endif
struct BlynkLockGuard {
  bool acquired;
  explicit BlynkLockGuard(TickType_t) : acquired(blynkLockAvailable) {
    blynkLockTakes++;
    actions.push_back(acquired ? "blynk_lock" : "blynk_lock_busy");
  }
  ~BlynkLockGuard() {}
  BlynkLockGuard(const BlynkLockGuard&) = delete;
  BlynkLockGuard& operator=(const BlynkLockGuard&) = delete;
  explicit operator bool() const { return acquired; }
};

QueueProbe msg_q;
void* xMsgSemaphore = nullptr;
BaseType_t takeResult = pdTRUE;
int failOnTakeCall = 0;
int takeCalls = 0;
int giveCalls = 0;
std::vector<std::string> codes;
int failures = 0;
uint32_t fakeMillis = 0;
constexpr uint32_t NOTIFY_DELIVERY_TTL_MS = 15UL * 60UL * 1000UL;
bool notificationTokenInvalid = false;
bool notifyQueuePushFailedLogged = false;
bool notifyBlynkDisconnectedLogged = false;
bool ota_running = false;

uint32_t millis() { return fakeMillis; }
bool is_notification_token_invalid() { return notificationTokenInvalid; }
void set_notification_token_invalid(bool invalid) { notificationTokenInvalid = invalid; }

struct WiFiProbe {
  int state = WL_CONNECTED;
  int status() const { return state; }
} WiFi;

BaseType_t xSemaphoreTake(void*, TickType_t) {
  takeCalls++;
  if (takeCalls == failOnTakeCall) return 0;
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
  const String m("payload");
  const MESSAGE_TYPE msg_type = NONE_MSG;
@PRODUCER_BLOCK@
}

void runConsumerBlock() {
@CONSUMER_BLOCK@
}

void resetProbe() {
  pendingV35 = false;
  msg_q = QueueProbe{};
  takeResult = pdTRUE;
  failOnTakeCall = 0;
  takeCalls = 0;
  giveCalls = 0;
  codes.clear();
  actions.clear();
  blynkCheckCalls = 0;
  blynkWriteCalls = 0;
  blynkNotifyCalls = 0;
  blynkConnected = true;
  disconnectAfterWrite = false;
  disconnectAfterNotify = false;
  blynkLockAvailable = true;
  blynkLockTakes = 0;
  blynkTokenInvalid = false;
  notificationTokenInvalid = false;
  notifyQueuePushFailedLogged = false;
  notifyBlynkDisconnectedLogged = false;
  fakeMillis = 0;
  ota_running = false;
  WiFi.state = WL_CONNECTED;
  SamSetup.blynkauth[0] = '\0';
}

void configureIntegrations() {
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
  check(takeCalls == 0 && msg_q.pushCalls == 0 && giveCalls == 0 && codes.empty(),
        "unconfigured Blynk must not enqueue notification");

  resetProbe();
  configureIntegrations();
  fakeMillis = 1234;
  runProducerBlock();
  check(takeCalls == 1 && msg_q.pushCalls == 1 && giveCalls == 1 &&
            msg_q.queuedAtMillis == 1234 && codes.empty() &&
            actions == std::vector<std::string>({"give"}),
        "producer success must store enqueue time and give once without diagnostics");

  resetProbe();
  configureIntegrations();
  msg_q.pushResult = false;
  runProducerBlock();
  runProducerBlock();
  msg_q.pushResult = true;
  runProducerBlock();
  msg_q.pushResult = false;
  runProducerBlock();
  check(msg_q.pushCalls == 4 && giveCalls == 4 &&
            codes == std::vector<std::string>({
                "notify_queue_push_failed", "notify_queue_push_failed"}) &&
            actions == std::vector<std::string>({
                "give", "log:notify_queue_push_failed", "give", "give",
                "give", "log:notify_queue_push_failed"}),
        "producer push failure must be diagnosed once per full-state transition");

  resetProbe();
  configureIntegrations();
  notificationTokenInvalid = true;
  runProducerBlock();
  check(msg_q.pushCalls == 0 && codes.empty(),
        "known invalid token must not enqueue or grow the log");

  resetProbe();
  configureIntegrations();
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
  check(msg_q.emptyCalls == 1 && msg_q.peekCalls == 0 && msg_q.popCalls == 0 && giveCalls == 1 &&
            codes.empty() && actions == std::vector<std::string>({"give"}) &&
            blynkCheckCalls == 0 && blynkWriteCalls == 0,
        "empty consumer path must give once without diagnostics");

  resetProbe();
  msg_q.empty = false;
  runConsumerBlock();
  check(msg_q.peekCalls == 1 && msg_q.flushCalls == 1 && msg_q.popCalls == 0 && codes.empty(),
        "unconfigured Blynk must clear stale notifications without diagnostics");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  notificationTokenInvalid = true;
  runConsumerBlock();
  check(msg_q.flushCalls == 1 && msg_q.popCalls == 0 && codes.empty(),
        "known invalid token must clear the queue without diagnostics");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  blynkTokenInvalid = true;
  runConsumerBlock();
  check(notificationTokenInvalid && msg_q.flushCalls == 1 && codes.empty(),
        "library TOKEN_INVALID must be cached and clear the queue");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  msg_q.peekResult = false;
  runConsumerBlock();
  check(msg_q.peekCalls == 1 && msg_q.popCalls == 0 && giveCalls == 1 &&
            codes == std::vector<std::string>({"notify_queue_peek_failed"}) &&
            actions == std::vector<std::string>({
                "give", "log:notify_queue_peek_failed"}) &&
            blynkCheckCalls == 0 && blynkWriteCalls == 0,
        "consumer peek failure must give before its only diagnostic");

  resetProbe();
  configureIntegrations();
  takeResult = 0;
  runConsumerBlock();
  check(msg_q.emptyCalls == 0 && msg_q.peekCalls == 0 && msg_q.popCalls == 0 && giveCalls == 0 &&
            codes == std::vector<std::string>({"notify_queue_peek_lock_busy"}) &&
            actions == std::vector<std::string>({
                "log:notify_queue_peek_lock_busy"}) &&
            blynkCheckCalls == 0 && blynkWriteCalls == 0,
        "consumer take failure must not give and must emit only lock_busy");
}

void checkIntegrationPaths() {
  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  msg_q.message = "2@P1;s=00000001";
  pendingV35 = true;
  runConsumerBlock();
  check(blynkWriteCalls == 0 && msg_q.popCalls == 0,
        "typed pair must remain queued until V35 is sent");
  pendingV35 = false;
  runConsumerBlock();
  check(blynkWriteCalls == 1 && msg_q.popCalls == 1,
        "typed pair must be sent after V35 is no longer pending");
  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  runConsumerBlock();
  check(blynkNotifyCalls == blynkWriteCalls, "blynk_notify_follows_v26_write");
  check(blynkCheckCalls == 3 && blynkWriteCalls == 1 && msg_q.popCalls == 1 && giveCalls == 2 &&
            codes.empty() && actions == std::vector<std::string>({
                "give", "blynk_lock", "blynk_check", "blynk_write", "blynk_check",
                "blynk_notify", "blynk_check", "give"}),
        "successful Blynk delivery must not emit diagnostics");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  blynkConnected = false;
  runConsumerBlock();
  runConsumerBlock();
  check(blynkCheckCalls == 2 && blynkWriteCalls == 0 &&
            msg_q.popCalls == 0 &&
            codes == std::vector<std::string>({"notify_blynk_disconnected"}) &&
            actions == std::vector<std::string>({
                "give", "blynk_lock", "blynk_check",
                "log:notify_blynk_disconnected", "give", "blynk_lock", "blynk_check"}),
        "unchanged Blynk disconnect must be diagnosed only once");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  fakeMillis = NOTIFY_DELIVERY_TTL_MS;
  runConsumerBlock();
  runConsumerBlock();
  check(blynkWriteCalls == 0 && msg_q.popCalls == 1 &&
            codes == std::vector<std::string>({"notify_queue_delivery_expired"}),
        "expired notification must be removed with exactly one diagnostic");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  WiFi.state = 0;
  fakeMillis = NOTIFY_DELIVERY_TTL_MS - 1;
  runConsumerBlock();
  check(blynkWriteCalls == 0 && msg_q.popCalls == 0 && codes.empty(),
        "temporary offline state before TTL must retain notification");

  // Замок Blynk держит loop(): доставка пропускается, но такт не блокируется и
  // пользователь узнаёт об этом из журнала (notify_blynk_lock_busy).
  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  blynkLockAvailable = false;
  runConsumerBlock();
  check(blynkLockTakes == 1 && blynkCheckCalls == 0 &&
            blynkWriteCalls == 0 && msg_q.popCalls == 0 &&
            codes == std::vector<std::string>({"notify_blynk_lock_busy"}) &&
            actions == std::vector<std::string>({
                "give", "blynk_lock_busy",
                "log:notify_blynk_lock_busy"}),
        "busy Blynk lock must skip delivery and log it once");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  disconnectAfterWrite = true;
  runConsumerBlock();
  check(blynkWriteCalls == 1 && blynkNotifyCalls == 0 && msg_q.popCalls == 0 &&
            codes == std::vector<std::string>({"notify_blynk_disconnected"}),
        "disconnect after V26 must retain notification");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  disconnectAfterNotify = true;
  runConsumerBlock();
  check(blynkWriteCalls == 1 && blynkNotifyCalls == 1 && msg_q.popCalls == 0 &&
            codes == std::vector<std::string>({"notify_blynk_disconnected"}),
        "disconnect after notify must retain notification");

  resetProbe();
  configureIntegrations();
  msg_q.empty = false;
  failOnTakeCall = 2;
  runConsumerBlock();
  check(blynkWriteCalls == 1 && blynkNotifyCalls == 1 && msg_q.popCalls == 0 &&
            codes == std::vector<std::string>({"notify_queue_pop_lock_busy"}),
        "second message lock failure must retain accepted notification");

  failOnTakeCall = 0;
  runConsumerBlock();
  check(blynkWriteCalls == 2 && blynkNotifyCalls == 2 && msg_q.popCalls == 1 &&
            codes == std::vector<std::string>({"notify_queue_pop_lock_busy"}),
        "retained notification must be retried after accepted send");
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


def check_source_contract(source: str | None = None) -> list[str]:
    errors: list[str] = []
    if source is None:
        source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    source = strip_cpp_comments(source)
    queue_source = strip_cpp_comments(
        (ROOT / "libraries/simple_queue/simple_queue.h").read_text(encoding="utf-8")
    )
    try:
        send_body = extract_function_body(source, "void SendMsg(")
        clock_body = extract_function_body(source, "void triggerGetClock(")
        setup_body = extract_function_body(source, "static void setup_connect_wifi_and_notify()")
        log_body = extract_function_body(source, "void WriteConsoleLog(")
    except ValueError as error:
        return [str(error)]

    require("SimpleStringQueue msg_q(5, 200);" in source,
            "queue capacity/item size changed", errors)
    require("bool push(const char* item, uint32_t queuedAt)" in queue_source and
            "bool peek(char* item, uint32_t* queuedAt) const" in queue_source and
            "bool pop(char* item)" in queue_source,
            "vendor queue result API changed", errors)
    require(send_body.count("msg_q.push(") == 1,
            "SendMsg must perform exactly one push", errors)
    require(clock_body.count("msg_q.isEmpty()") == 1,
            "consumer must make one locked empty check", errors)
    require(clock_body.count("msg_q.peek(") == 1,
            "consumer must peek exactly one FIFO head", errors)
    require(clock_body.count("msg_q.pop(") == 1,
            "consumer must perform at most one pop", errors)
    require("queuePushResult = msg_q.push(" in send_body,
            "push result is not checked", errors)
    require("queuePopResult = msg_q.pop(" in clock_body,
            "pop result is not checked", errors)

    require_order(
        send_body,
        ("const uint32_t queuedAtMillis = millis();", "xSemaphoreTake(",
         "msg_q.push(MsgPl.c_str(), queuedAtMillis)",
         "xSemaphoreGive(", "WriteConsoleLog("),
        "SendMsg",
        errors,
    )
    require_order(
        clock_body,
        ("xSemaphoreTake(", "msg_q.isEmpty()", "msg_q.peek(c, &queuedAtMillis)",
         "xSemaphoreGive(", "deliveryExpired", "String qMsg", "Blynk.virtualWrite(",
         "Blynk.notify(", "blynkDeliveryAccepted", "msg_q.pop(c)"),
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

    enqueue_guard = "#ifdef SAMOVAR_USE_BLYNK"
    require(enqueue_guard in send_body and
            send_body.find(enqueue_guard) < send_body.find("msg_q.push("),
            "Blynk enqueue guard changed", errors)
    enqueue_condition = "if (SamSetup.blynkauth[0] != 0 && !is_notification_token_invalid())"
    require(enqueue_condition in send_body and
            send_body.find(enqueue_condition) < send_body.find("msg_q.push("),
            "empty or known-invalid Blynk token must not enqueue notification", errors)
    require("millis() - queuedAtMillis >= NOTIFY_DELIVERY_TTL_MS" in clock_body,
            "notification delivery TTL is missing or not rollover-safe", errors)
    require("msg_q.flush();" in clock_body and "discardQueue = tokenUnavailable" in clock_body,
            "empty or invalid token must clear retained notifications", errors)
    require("notifyQueuePushFailedLogged" in send_body,
            "queue-full diagnostic state suppression is missing", errors)
    require("blynkDisconnected && !notifyBlynkDisconnectedLogged" in clock_body,
            "disconnect diagnostic state suppression is missing", errors)
    require("if (Blynk.connected()) notifyBlynkDisconnectedLogged = false;" in clock_body,
            "disconnect diagnostic is not reset after reconnection", errors)
    require("!Blynk.isTokenInvalid()" in clock_body and
            "set_notification_token_invalid(tokenInvalid);" in clock_body,
            "periodic Blynk connect does not cache/stop on TOKEN_INVALID", errors)
    require_order(
        setup_body,
        ("Blynk.connect(BLYNK_TIMEOUT_MS);",
         "set_notification_token_invalid(Blynk.isTokenInvalid());"),
        "setup Blynk invalid-token state",
        errors,
    )
    require("String pushMsg = String(msgLevel == '0' ? \"Тревога! \"" in clock_body,
            "Blynk/V26 alarm prefix changed (apps detect alarms by it)", errors)
    require("#ifdef USE_MQTT" not in send_body and "MqttSendMsg(" not in send_body,
            "MQTT удалён в T3, но в теле SendMsg() остался след MqttSendMsg/USE_MQTT", errors)
    require("#ifdef SAMOVAR_USE_BLYNK" in clock_body,
            "Blynk delivery guard changed", errors)
    require("Blynk.connected()" in clock_body and
            "SamSetup.blynkauth[0] != 0" in clock_body,
            "Blynk configured/disconnected check missing", errors)
    require("msg_q.push(" not in clock_body and "msg_q.pop(" not in send_body,
            "queue consumer/producer ownership changed", errors)
    require("SendMsg(" not in log_body and "msg_q." not in log_body and
            "xMsgSemaphore" not in log_body,
            "WriteConsoleLog recurses into notification queue", errors)

    for code in FAILURE_CODES:
        require(source.count(f'F("{code}")') == 1,
                f"failure code {code!r} must appear exactly once", errors)
    return errors


def build_production_block_harness(source: str | None = None) -> str:
    if source is None:
        source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    send_body = extract_function_body(source, "void SendMsg(")
    clock_body = extract_function_body(source, "void triggerGetClock(", strip_comments=False)

    producer_start = send_body.find(
        "if (SamSetup.blynkauth[0] != 0 && !is_notification_token_invalid())"
    )
    producer_end = send_body.find("#endif", producer_start)
    if producer_start < 0 or producer_end < 0:
        raise ValueError("SendMsg queue block not found")
    producer_block = send_body[producer_start:producer_end]
    consumer_block, _ = extract_braced_block_after(
        clock_body, "// Возраст очереди проверяется и без Wi-Fi"
    )
    defer_signature = "static bool defer_typed_pair_until_v35(const char* message)"
    defer_function = "bool pendingV35 = false;\nbool blynk_session_start_pending() { return pendingV35; }\n" + defer_signature + " {" + extract_function_body(source, defer_signature) + "}\n"
    return (PRODUCTION_BLOCK_HARNESS
            .replace("void runConsumerBlock() {", defer_function + "void runConsumerBlock() {")
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


def run_harness(source: str | None = None) -> list[str]:
    compiler = shutil.which("g++")
    if compiler is None:
        return ["g++ is required for the notification queue behavioral gate"]
    try:
        production_harness = build_production_block_harness(source)
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
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    send_start = source.find("void SendMsg(")
    unguarded = source[:send_start] + source[send_start:].replace(
        "if (SamSetup.blynkauth[0] != 0 && !is_notification_token_invalid())", "if (true)", 1
    )
    if "empty or known-invalid Blynk token must not enqueue notification" not in check_source_contract(unguarded):
        errors.append("empty/invalid Blynk token enqueue mutation survived")

    no_disconnect_reset = source.replace(
        "if (Blynk.connected()) notifyBlynkDisconnectedLogged = false;", "", 1
    )
    if "disconnect diagnostic is not reset after reconnection" not in check_source_contract(
        no_disconnect_reset
    ):
        errors.append("disconnect diagnostic reset mutation survived")

    no_invalid_cache = source.replace(
        "set_notification_token_invalid(tokenInvalid);", "", 1
    )
    if "periodic Blynk connect does not cache/stop on TOKEN_INVALID" not in check_source_contract(
        no_invalid_cache
    ):
        errors.append("invalid-token cache mutation survived")
    errors.extend(run_harness())

    for label, mutant, expected_failure in (
        (
            "TTL boundary",
            source.replace(
                "millis() - queuedAtMillis >= NOTIFY_DELIVERY_TTL_MS",
                "millis() - queuedAtMillis > NOTIFY_DELIVERY_TTL_MS",
                1,
            ),
            "expired notification must be removed with exactly one diagnostic",
        ),
        (
            "disconnect diagnostic suppression",
            source.replace(
                "blynkDisconnected && !notifyBlynkDisconnectedLogged",
                "blynkDisconnected",
                1,
            ),
            "unchanged Blynk disconnect must be diagnosed only once",
        ),
        (
            "queue-full diagnostic suppression",
            source.replace(
                "} else if (!notifyQueuePushFailedLogged) {",
                "} else {",
                1,
            ),
            "producer push failure must be diagnosed once per full-state transition",
        ),
    ):
        mutation_output = "\n".join(run_harness(mutant))
        if expected_failure not in mutation_output:
            errors.append(f"{label} mutation survived or failed for the wrong reason")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("Notification queue checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
