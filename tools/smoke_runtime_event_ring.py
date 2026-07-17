#!/usr/bin/env python3
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>
#include <utility>

#include "runtime_event_log.h"

RuntimeEventRing runtimeEventRing{};

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << '\n';
    failures++;
  }
}

class FaultText {
 public:
  static bool failReserve;
  static int failConcatCall;
  static int concatCalls;

  FaultText() : storage_(1, '\0') {}
  explicit FaultText(const char* value) : storage_(value), length_(storage_.size()) {
    storage_.push_back('\0');
  }
  FaultText(FaultText&&) = default;
  FaultText& operator=(FaultText&&) = default;
  FaultText(const FaultText&) = default;
  FaultText& operator=(const FaultText&) = default;

  bool reserve(size_t length) {
    if (failReserve) return false;
    storage_.reserve(length + 1);
    return true;
  }

  bool concat(const char* text, size_t length) {
    concatCalls++;
    if (failConcatCall == concatCalls) return false;
    const size_t newLength = length_ + length;
    storage_.resize(newLength + 1);
    std::memcpy(&storage_[length_], text, length + 1);
    length_ = newLength;
    return true;
  }

  size_t length() const { return length_; }
  char* begin() { return &storage_[0]; }
  const char* c_str() const { return storage_.data(); }
  std::string value() const { return std::string(storage_.data(), length_); }

  static void resetFaults() {
    failReserve = false;
    failConcatCall = 0;
    concatCalls = 0;
  }

 private:
  std::string storage_;
  size_t length_ = 0;
};

bool FaultText::failReserve = false;
int FaultText::failConcatCall = 0;
int FaultText::concatCalls = 0;

static RuntimeEventDescriptor select_event(
    const RuntimeEventRing& ring, uint32_t cursor, RuntimeEventSelectResult expected) {
  RuntimeEventDescriptor descriptor{};
  check(runtime_event_select_locked(ring, cursor, descriptor) == expected,
        "unexpected select result");
  return descriptor;
}

static std::string copy_event(
    const RuntimeEventRing& ring, const RuntimeEventDescriptor& descriptor) {
  FaultText::resetFaults();
  FaultText output;
  check(runtime_event_copy_text_locked(ring, descriptor, output) ==
            RUNTIME_EVENT_SNAPSHOT_OK,
        "event copy failed");
  check(output.c_str()[output.length()] == '\0', "event copy is not NUL terminated");
  return output.value();
}

static void test_empty_and_mixed_fifo() {
  RuntimeEventRing ring{};
  runtime_event_init(ring);
  check(runtime_event_validate_locked(ring), "initialized ring is invalid");
  check(ring.nextSequence == 1 && ring.count == 0 && ring.usedBytes == 0,
        "initialized metadata mismatch");
  check(ring.textPool[RUNTIME_EVENT_TEXT_POOL_BYTES] == '\0',
        "guard byte not initialized");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 2, "", 0) == RUNTIME_EVENT_APPEND_EMPTY,
        "empty append was not ignored");
  select_event(ring, 0, RUNTIME_EVENT_SELECT_NONE);

  uint32_t messageSequence = 0;
  uint32_t consoleSequence = 0;
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 1, "message", 7, &messageSequence) ==
            RUNTIME_EVENT_APPEND_OK,
        "message append failed");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, "console", 7, &consoleSequence) ==
            RUNTIME_EVENT_APPEND_OK,
        "console append failed");
  check(messageSequence == 1 && consoleSequence == 2,
        "mixed sequence mismatch");

  RuntimeEventDescriptor first = select_event(ring, 0, RUNTIME_EVENT_SELECT_FOUND);
  check(ring.textPool[first.offset + first.length] == 'c',
        "NUL test does not end before a retained event");
  check(first.kind == RUNTIME_EVENT_MESSAGE && first.level == 1 &&
            copy_event(ring, first) == "message",
        "message payload mismatch");
  RuntimeEventDescriptor second =
      select_event(ring, first.sequence, RUNTIME_EVENT_SELECT_FOUND);
  check(second.kind == RUNTIME_EVENT_CONSOLE && copy_event(ring, second) == "console",
        "console payload mismatch");
  select_event(ring, second.sequence, RUNTIME_EVENT_SELECT_NONE);

  RuntimeEventDescriptor latest{};
  check(runtime_event_select_latest_message_locked(ring, latest) ==
            RUNTIME_EVENT_SELECT_FOUND &&
            latest.sequence == first.sequence,
        "latest message selection mismatch");

  RuntimeEventDescriptor tabOne = select_event(ring, 0, RUNTIME_EVENT_SELECT_FOUND);
  RuntimeEventDescriptor tabTwo = select_event(ring, 0, RUNTIME_EVENT_SELECT_FOUND);
  check(tabOne.sequence == tabTwo.sequence && ring.count == 2,
        "independent cursors mutated the ring");
}

static void test_two_cursor_full_fifo() {
  RuntimeEventRing ring{};
  runtime_event_init(ring);
  const char* payloads[] = {"one", "two", "three", "four", "five"};
  for (uint8_t index = 0; index < 5; index++) {
    check(runtime_event_append_locked(
              ring, index % 2 == 0 ? RUNTIME_EVENT_MESSAGE : RUNTIME_EVENT_CONSOLE,
              index, payloads[index], std::strlen(payloads[index])) ==
              RUNTIME_EVENT_APPEND_OK,
          "two-cursor setup append failed");
  }

  uint32_t cursorA = 0;
  uint32_t cursorB = 0;
  uint8_t indexA = 0;
  uint8_t indexB = 0;
  const char schedule[] = {'A', 'A', 'B', 'A', 'B', 'B', 'A', 'B', 'A', 'B'};
  for (char client : schedule) {
    uint32_t& cursor = client == 'A' ? cursorA : cursorB;
    uint8_t& index = client == 'A' ? indexA : indexB;
    RuntimeEventDescriptor selected =
        select_event(ring, cursor, RUNTIME_EVENT_SELECT_FOUND);
    check(selected.sequence == static_cast<uint32_t>(index + 1) &&
              copy_event(ring, selected) == payloads[index],
          "independent cursor FIFO traversal mismatch");
    cursor = selected.sequence;
    index++;
  }
  check(indexA == 5 && indexB == 5 && ring.count == 5,
        "independent cursors did not traverse the full retained FIFO");
  select_event(ring, cursorA, RUNTIME_EVENT_SELECT_NONE);
  select_event(ring, cursorB, RUNTIME_EVENT_SELECT_NONE);
}

static void test_descriptor_and_pool_overflow() {
  RuntimeEventRing ring{};
  runtime_event_init(ring);
  for (uint32_t index = 1; index <= 17; index++) {
    const char value = static_cast<char>('a' + index - 1);
    check(runtime_event_append_locked(
              ring, RUNTIME_EVENT_CONSOLE, 100, &value, 1) ==
              RUNTIME_EVENT_APPEND_OK,
          "descriptor-pressure append failed");
  }
  check(ring.count == RUNTIME_EVENT_DESCRIPTOR_CAPACITY && ring.usedBytes == 16,
        "descriptor pressure metadata mismatch");
  RuntimeEventDescriptor oldest = select_event(ring, 1, RUNTIME_EVENT_SELECT_FOUND);
  check(oldest.sequence == 2 && copy_event(ring, oldest) == "b",
        "evicted cursor did not select oldest retained event");

  runtime_event_init(ring);
  const std::string first(6000, 'a');
  const std::string second(4000, 'b');
  const std::string wrapped(1000, 'c');
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, first.data(), first.size()) ==
            RUNTIME_EVENT_APPEND_OK,
        "first pool-pressure append failed");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, second.data(), second.size()) ==
            RUNTIME_EVENT_APPEND_OK,
        "second pool-pressure append failed");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, wrapped.data(), wrapped.size()) ==
            RUNTIME_EVENT_APPEND_OK,
        "wrapped pool-pressure append failed");
  check(ring.count == 2 && ring.usedBytes == 5000 && ring.writeOffset == 760,
        "pool pressure did not evict exact oldest payload");
  RuntimeEventDescriptor retained = select_event(ring, 0, RUNTIME_EVENT_SELECT_FOUND);
  RuntimeEventDescriptor wrappedDescriptor =
      select_event(ring, retained.sequence, RUNTIME_EVENT_SELECT_FOUND);
  check(wrappedDescriptor.offset == 10000 && wrappedDescriptor.length == 1000 &&
            copy_event(ring, wrappedDescriptor) == wrapped,
        "wrapped event mismatch");
  check(ring.textPool[RUNTIME_EVENT_TEXT_POOL_BYTES] == '\0',
        "wrapped append modified guard byte");
}

static void test_snapshot_failures_are_atomic() {
  RuntimeEventRing ring{};
  runtime_event_init(ring);
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 2, "payload", 7) == RUNTIME_EVENT_APPEND_OK,
        "snapshot setup append failed");
  RuntimeEventDescriptor selected = select_event(ring, 0, RUNTIME_EVENT_SELECT_FOUND);

  FaultText output("unchanged");
  FaultText::resetFaults();
  FaultText::failReserve = true;
  check(runtime_event_copy_text_locked(ring, selected, output) ==
            RUNTIME_EVENT_SNAPSHOT_NO_MEMORY &&
            output.value() == "unchanged",
        "reserve failure leaked partial output");

  FaultText::resetFaults();
  FaultText::failConcatCall = 1;
  check(runtime_event_copy_text_locked(ring, selected, output) ==
            RUNTIME_EVENT_SNAPSHOT_NO_MEMORY &&
            output.value() == "unchanged",
        "first concat failure leaked partial output");

  RuntimeEventDescriptor corrupt = selected;
  corrupt.length++;
  FaultText::resetFaults();
  check(runtime_event_copy_text_locked(ring, corrupt, output) ==
            RUNTIME_EVENT_SNAPSHOT_CORRUPT &&
            output.value() == "unchanged",
        "corrupt descriptor was copied");

  runtime_event_init(ring);
  const std::string prefix(10000, 'p');
  const std::string wrapped(500, 'w');
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, prefix.data(), prefix.size()) ==
            RUNTIME_EVENT_APPEND_OK,
        "wrapped failure prefix append failed");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, wrapped.data(), wrapped.size()) ==
            RUNTIME_EVENT_APPEND_OK,
        "wrapped failure event append failed");
  selected = select_event(ring, 1, RUNTIME_EVENT_SELECT_FOUND);
  check(selected.offset == 10000, "wrapped failure event did not wrap");
  FaultText::resetFaults();
  FaultText::failConcatCall = 2;
  check(runtime_event_copy_text_locked(ring, selected, output) ==
            RUNTIME_EVENT_SNAPSHOT_NO_MEMORY &&
            output.value() == "unchanged",
        "second concat failure leaked partial output");
}

static void test_long_boundaries_and_sequence_wrap() {
  RuntimeEventRing ring{};
  runtime_event_init(ring);
  const std::string lua(8691, 'l');
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, lua.data(), lua.size()) ==
            RUNTIME_EVENT_APPEND_OK,
        "8691-byte Lua payload rejected");
  RuntimeEventDescriptor selected = select_event(ring, 0, RUNTIME_EVENT_SELECT_FOUND);
  check(copy_event(ring, selected) == lua, "8691-byte Lua payload changed");

  runtime_event_init(ring);
  const std::string maximum(10000, 'm');
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, maximum.data(), maximum.size()) ==
            RUNTIME_EVENT_APPEND_OK,
        "10000-byte payload rejected");
  selected = select_event(ring, 0, RUNTIME_EVENT_SELECT_FOUND);
  check(copy_event(ring, selected) == maximum, "10000-byte payload changed");
  const RuntimeEventRing before = ring;
  const std::string oversized(10001, 'x');
  uint32_t sequence = 77;
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_CONSOLE, 100, oversized.data(), oversized.size(),
            &sequence) == RUNTIME_EVENT_TEXT_TOO_LONG,
        "10001-byte payload was accepted");
  check(std::memcmp(&before, &ring, sizeof(ring)) == 0 && sequence == 77,
        "oversize append mutated ring or sequence output");

  runtime_event_init(ring);
  ring.nextSequence = UINT32_MAX;
  uint32_t maximumSequence = 0;
  uint32_t wrappedSequence = 0;
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 0, "first", 5, &maximumSequence) ==
            RUNTIME_EVENT_APPEND_OK,
        "UINT32_MAX append failed");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 0, "second", 6, &wrappedSequence) ==
            RUNTIME_EVENT_APPEND_OK,
        "wrapped sequence append failed");
  check(maximumSequence == UINT32_MAX && wrappedSequence == 1 && ring.nextSequence == 2,
        "sequence did not wrap without zero");
  selected = select_event(ring, UINT32_MAX, RUNTIME_EVENT_SELECT_FOUND);
  check(selected.sequence == 1, "physical order failed across sequence wrap");
  runtime_event_init(ring);
  check(ring.nextSequence == 1 && ring.count == 0, "reinit did not reset volatile ring");
}

static void test_reboot_stale_cursor_limitations() {
  RuntimeEventRing ring{};
  runtime_event_init(ring);
  for (uint8_t index = 0; index < 5; index++) {
    check(runtime_event_append_locked(
              ring, RUNTIME_EVENT_MESSAGE, 0, "old", 3) ==
              RUNTIME_EVENT_APPEND_OK,
          "stale cursor setup append failed");
  }
  const uint32_t staleMismatchCursor = 5;
  const uint32_t staleCollisionCursor = 1;

  runtime_event_init(ring);
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 0, "new-one", 7) ==
            RUNTIME_EVENT_APPEND_OK,
        "post-reboot first append failed");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 0, "new-two", 7) ==
            RUNTIME_EVENT_APPEND_OK,
        "post-reboot second append failed");

  RuntimeEventDescriptor mismatch =
      select_event(ring, staleMismatchCursor, RUNTIME_EVENT_SELECT_FOUND);
  check(mismatch.sequence == 1 && copy_event(ring, mismatch) == "new-one" &&
            mismatch.sequence != runtime_event_next_sequence(staleMismatchCursor),
        "stale reboot mismatch is not detectable");

  RuntimeEventDescriptor collision =
      select_event(ring, staleCollisionCursor, RUNTIME_EVENT_SELECT_FOUND);
  check(collision.sequence == 2 && copy_event(ring, collision) == "new-two" &&
            collision.sequence == runtime_event_next_sequence(staleCollisionCursor),
        "stale reboot collision limitation changed");
}

static void test_cursor_parser_and_size_contract() {
  uint32_t cursor = 99;
  check(runtime_event_parse_cursor("0", 1, cursor) && cursor == 0,
        "cursor zero rejected");
  check(runtime_event_parse_cursor("4294967295", 10, cursor) && cursor == UINT32_MAX,
        "maximum cursor rejected");
  const char* invalid[] = {"", "+1", "-1", " 1", "1 ", "1x", "4294967296", "00000000000"};
  for (const char* value : invalid) {
    cursor = 123;
    check(!runtime_event_parse_cursor(value, std::strlen(value), cursor) && cursor == 123,
          "invalid cursor accepted or output mutated");
  }
  check(sizeof(RuntimeEventDescriptor) <= 12, "descriptor exceeds size cap");
  check(sizeof(RuntimeEventRing) <= 10464, "ring exceeds size cap");
  check(sizeof(runtimeEventRing.textPool) == RUNTIME_EVENT_TEXT_POOL_BYTES + 1,
        "guard byte changed logical pool size");
}

static void test_latest_sequence_helper() {
  RuntimeEventRing ring{};
  runtime_event_init(ring);
  check(runtime_event_latest_sequence_locked(ring) == 0,
        "latest sequence on empty ring must be zero");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 0, "first", 5) == RUNTIME_EVENT_APPEND_OK,
        "latest sequence setup append 1 failed");
  check(runtime_event_latest_sequence_locked(ring) == 1,
        "latest sequence did not track single append");
  check(runtime_event_append_locked(
            ring, RUNTIME_EVENT_MESSAGE, 0, "second", 6) == RUNTIME_EVENT_APPEND_OK,
        "latest sequence setup append 2 failed");
  check(runtime_event_latest_sequence_locked(ring) == 2,
        "latest sequence did not advance to newest append");
  for (uint8_t index = 0; index < 16; index++) {
    check(runtime_event_append_locked(
              ring, RUNTIME_EVENT_CONSOLE, 0, "x", 1) == RUNTIME_EVENT_APPEND_OK,
          "latest sequence eviction setup append failed");
  }
  check(runtime_event_latest_sequence_locked(ring) == 18,
        "latest sequence did not follow ring after eviction");
}

int main() {
  test_empty_and_mixed_fifo();
  test_two_cursor_full_fifo();
  test_descriptor_and_pool_overflow();
  test_snapshot_failures_are_atomic();
  test_long_boundaries_and_sequence_wrap();
  test_reboot_stale_cursor_limitations();
  test_cursor_parser_and_size_contract();
  test_latest_sequence_helper();
  if (failures != 0) return 1;
  std::cout << "runtime event ring smoke passed\n";
  return 0;
}
'''


def run_host_harness() -> None:
    with tempfile.TemporaryDirectory(prefix="samovar-runtime-event-") as temp_dir:
        source = Path(temp_dir) / "runtime_event_ring_test.cpp"
        binary = Path(temp_dir) / "runtime_event_ring_test"
        source.write_text(HARNESS, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                "-I",
                str(ROOT),
                str(source),
                "-o",
                str(binary),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            raise SystemExit(1)
        test_result = subprocess.run(
            [str(binary)], text=True, capture_output=True, check=False
        )
        sys.stdout.write(test_result.stdout)
        sys.stderr.write(test_result.stderr)
        if test_result.returncode != 0:
            raise SystemExit(test_result.returncode)


def compile_and_run(source_text: str, prefix: str) -> None:
    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
        source = Path(temp_dir) / "test.cpp"
        binary = Path(temp_dir) / "test"
        source.write_text(source_text, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                str(source),
                "-o",
                str(binary),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            raise SystemExit(1)
        result = subprocess.run(
            [str(binary)], text=True, capture_output=True, check=False
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode != 0:
            raise SystemExit(result.returncode)


def run_checked_writer_harness(samovar_text: str) -> None:
    definitions: list[str] = []
    signatures = [
        "static bool runtimeEventWrite(Print& out, const char* value, size_t length)",
        "static bool runtimeEventWriteEscaped(Print& out, const String& value)",
        "static bool runtimeEventWriteUnsigned(Print& out, uint32_t value)",
        "static bool runtimeEventWriteSection(\n    Print& out, const RuntimeEventDescriptor& event, const String& eventText)",
        "static bool sendRuntimeEventResponse(\n    AsyncWebServerRequest* request, AsyncResponseStream* response,\n    const RuntimeEventDescriptor& event, const String& eventText)",
    ]
    lookup_signatures = [
        signatures[0],
        signatures[1],
        signatures[2],
        "static bool runtimeEventWriteSection(",
        "static bool sendRuntimeEventResponse(",
    ]
    for signature, lookup in zip(signatures, lookup_signatures):
        definitions.append(f"{signature} {{\n{extract_function_body(samovar_text, lookup)}\n}}")

    harness = r'''
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>

static const uint8_t RUNTIME_EVENT_MESSAGE = 1;
static const uint8_t RUNTIME_EVENT_CONSOLE = 2;

struct RuntimeEventDescriptor {
  uint32_t sequence;
  uint16_t offset;
  uint16_t length;
  uint8_t kind;
  uint8_t level;
};

class String {
 public:
  explicit String(const char* value) : value_(value) {}
  explicit String(const std::string& value) : value_(value) {}
  size_t length() const { return value_.length(); }
  char operator[](size_t index) const { return value_[index]; }
  const char* c_str() const { return value_.c_str(); }

 private:
  std::string value_;
};

class Print {
 public:
  explicit Print(size_t failCall = 0) : failCall_(failCall) {}

  size_t write(const uint8_t* data, size_t length) {
    calls_++;
    if (calls_ == failCall_) {
      const size_t partial = length == 0 ? 0 : length - 1;
      output_.append(reinterpret_cast<const char*>(data), partial);
      return partial;
    }
    output_.append(reinterpret_cast<const char*>(data), length);
    return length;
  }

  size_t calls() const { return calls_; }
  const std::string& output() const { return output_; }

 private:
  size_t failCall_;
  size_t calls_ = 0;
  std::string output_;
};

class AsyncWebServerResponse {
 public:
  AsyncWebServerResponse(int status, const char* contentType, const char* body)
      : status(status), contentType(contentType), body(body) {}
  virtual ~AsyncWebServerResponse() = default;

  void addHeader(const char* name, const char* value) {
    if (std::string(name) == "Cache-Control") cacheControl = value;
  }

  int status;
  std::string contentType;
  std::string body;
  std::string cacheControl;
};

class AsyncResponseStream : public AsyncWebServerResponse, public Print {
 public:
  static int destroyed;

  explicit AsyncResponseStream(size_t failCall = 0)
      : AsyncWebServerResponse(200, "application/json", ""), Print(failCall) {}
  ~AsyncResponseStream() override { destroyed++; }
};

int AsyncResponseStream::destroyed = 0;

class AsyncWebServerRequest {
 public:
  AsyncWebServerResponse* beginResponse(
      int status, const char* contentType, const char* body) {
    return new AsyncWebServerResponse(status, contentType, body);
  }

  void send(AsyncWebServerResponse* response) {
    sent = response;
    sendCount++;
  }

  AsyncWebServerResponse* sent = nullptr;
  int sendCount = 0;
};
''' + "\n".join(definitions) + r'''

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << '\n';
    failures++;
  }
}

static void test_exact_message_and_console() {
  const RuntimeEventDescriptor message{42, 0, 3, RUNTIME_EVENT_MESSAGE, 1};
  const String messageText("a\"b");
  Print messageOut;
  check(runtimeEventWriteSection(messageOut, message, messageText),
        "message writer failed");
  check(messageOut.output() ==
            ",\"Msg\":\"a\\\"b\",\"msglvl\":1,\"messageSequence\":42}",
        "message bytes mismatch");

  const RuntimeEventDescriptor console{UINT32_MAX, 0, 4, RUNTIME_EVENT_CONSOLE, 100};
  const String consoleText("x\\\ny");
  Print consoleOut;
  check(runtimeEventWriteSection(consoleOut, console, consoleText),
        "console writer failed");
  check(consoleOut.output() ==
            ",\"LogMsg\":\"x\\\\\\ny\",\"messageSequence\":4294967295}",
        "console bytes mismatch");

  std::string controlBytes;
  for (uint8_t value = 0; value < 0x20; value++) {
    controlBytes.push_back(static_cast<char>(value));
  }
  controlBytes += "\"\\";
  const RuntimeEventDescriptor controls{7, 0, 34, RUNTIME_EVENT_CONSOLE, 100};
  const String controlText(controlBytes);
  Print controlOut;
  check(runtimeEventWriteSection(controlOut, controls, controlText),
        "control-byte writer failed");
  check(controlOut.output() ==
            ",\"LogMsg\":\""
            "\\u0000\\u0001\\u0002\\u0003\\u0004\\u0005\\u0006\\u0007"
            "\\b\\t\\n\\u000B\\f\\r\\u000E\\u000F"
            "\\u0010\\u0011\\u0012\\u0013\\u0014\\u0015\\u0016\\u0017"
            "\\u0018\\u0019\\u001A\\u001B\\u001C\\u001D\\u001E\\u001F"
            "\\\"\\\\\",\"messageSequence\":7}",
        "control-byte JSON escaping mismatch");
}

static void test_every_short_write_fails_closed() {
  const RuntimeEventDescriptor message{42, 0, 3, RUNTIME_EVENT_MESSAGE, 1};
  const String messageText("a\"b");
  Print successful;
  check(runtimeEventWriteSection(successful, message, messageText),
        "short-write baseline failed");
  const size_t writeCalls = successful.calls();
  check(writeCalls >= 8, "writer did not separate checked event fragments");

  AsyncResponseStream::destroyed = 0;
  AsyncWebServerRequest successRequest;
  AsyncResponseStream* successStream = new AsyncResponseStream();
  successStream->addHeader("Cache-Control", "no-store");
  check(sendRuntimeEventResponse(
            &successRequest, successStream, message, messageText),
        "successful event stream selected fallback response");
  check(successRequest.sendCount == 1 && successRequest.sent == successStream &&
            successStream->output() == successful.output() &&
            successStream->cacheControl == "no-store" &&
            AsyncResponseStream::destroyed == 0,
        "successful event stream wire mismatch");
  delete successRequest.sent;

  for (size_t failCall = 1; failCall <= writeCalls; failCall++) {
    AsyncResponseStream::destroyed = 0;
    AsyncWebServerRequest request;
    AsyncResponseStream* failing = new AsyncResponseStream(failCall);
    failing->addHeader("Cache-Control", "no-store");
    check(!sendRuntimeEventResponse(&request, failing, message, messageText),
          "short write was accepted by response sender");
    check(request.sendCount == 1 && request.sent &&
              dynamic_cast<AsyncResponseStream*>(request.sent) == nullptr &&
              request.sent->status == 503 &&
              request.sent->contentType == "text/plain" &&
              request.sent->body == "Runtime event response unavailable" &&
              request.sent->cacheControl == "no-store" &&
              AsyncResponseStream::destroyed == 1,
          "short write did not send exact fail-closed response");
    delete request.sent;
  }
}

int main() {
  test_exact_message_and_console();
  test_every_short_write_fails_closed();
  if (failures != 0) return 1;
  std::cout << "runtime event checked writer smoke passed\n";
  return 0;
}
'''
    compile_and_run(harness, "samovar-runtime-event-writer-")


def run_query_dispatch_harness(samovar_text: str, header_text: str) -> None:
    parser = (
        "inline bool runtime_event_parse_cursor("
        "const char* text, size_t length, uint32_t& cursor) {\n"
        + extract_function_body(header_text, "inline bool runtime_event_parse_cursor(")
        + "\n}"
    )
    classifier = (
        "static RuntimeAjaxQuery classifyRuntimeAjaxQuery("
        "AsyncWebServerRequest* request) {\n"
        + extract_function_body(samovar_text, "static RuntimeAjaxQuery classifyRuntimeAjaxQuery(")
        + "\n}"
    )
    error_sender = (
        "static bool sendRuntimeAjaxQueryError("
        "AsyncWebServerRequest* request, RuntimeAjaxQueryKind kind) {\n"
        + extract_function_body(samovar_text, "static bool sendRuntimeAjaxQueryError(")
        + "\n}"
    )

    harness = r'''
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <iostream>
#include <string>
#include <vector>

class String {
 public:
  explicit String(const char* value) : value_(value) {}
  const char* c_str() const { return value_.c_str(); }
  size_t length() const { return value_.length(); }
  bool operator==(const char* value) const { return value_ == value; }
  bool operator!=(const char* value) const { return value_ != value; }

 private:
  std::string value_;
};

class AsyncWebParameter {
 public:
  AsyncWebParameter(
      const char* name, const char* value, bool file = false, bool post = false)
      : name_(name), value_(value), file_(file), post_(post) {}
  const String& name() const { return name_; }
  const String& value() const { return value_; }
  bool isFile() const { return file_; }
  bool isPost() const { return post_; }

 private:
  String name_;
  String value_;
  bool file_;
  bool post_;
};

class AsyncWebServerResponse {
 public:
  AsyncWebServerResponse(int status, const char* contentType, const char* body)
      : status(status), contentType(contentType), body(body) {}
  void addHeader(const char* name, const char* value) {
    if (std::string(name) == "Cache-Control") cacheControl = value;
  }

  int status;
  std::string contentType;
  std::string body;
  std::string cacheControl;
};

class AsyncWebServerRequest {
 public:
  AsyncWebServerRequest(std::initializer_list<AsyncWebParameter> parameters)
      : parameters_(parameters) {}
  size_t params() const { return parameters_.size(); }
  const AsyncWebParameter* getParam(size_t index) const {
    return index < parameters_.size() ? &parameters_[index] : nullptr;
  }
  AsyncWebServerResponse* beginResponse(
      int status, const char* contentType, const char* body) {
    return new AsyncWebServerResponse(status, contentType, body);
  }
  void send(AsyncWebServerResponse* response) {
    sent = response;
    sendCount++;
  }

  AsyncWebServerResponse* sent = nullptr;
  int sendCount = 0;

 private:
  std::vector<AsyncWebParameter> parameters_;
};

enum RuntimeAjaxQueryKind : uint8_t {
  RUNTIME_AJAX_QUERY_OPERATION = 0,
  RUNTIME_AJAX_QUERY_TELEMETRY,
  RUNTIME_AJAX_QUERY_INVALID_OPERATION,
  RUNTIME_AJAX_QUERY_BAD_REQUEST,
};

struct RuntimeAjaxQuery {
  RuntimeAjaxQueryKind kind;
  uint32_t value;
};

enum OperationError : uint8_t {
  OPERATION_ERROR_INVALID_ID = 1,
};

static const char* operation_error_code(OperationError error) {
  return error == OPERATION_ERROR_INVALID_ID ? "invalid_operation_id" : "unknown";
}
''' + parser + "\n" + classifier + "\n" + error_sender + r'''

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << '\n';
    failures++;
  }
}

static void checkQuery(
    const char* name, std::initializer_list<AsyncWebParameter> parameters,
    RuntimeAjaxQueryKind expectedKind, uint32_t expectedValue) {
  AsyncWebServerRequest request(parameters);
  const RuntimeAjaxQuery query = classifyRuntimeAjaxQuery(&request);
  check(query.kind == expectedKind && query.value == expectedValue, name);

  const bool errorSent = sendRuntimeAjaxQueryError(&request, query.kind);
  const bool expectError = expectedKind == RUNTIME_AJAX_QUERY_INVALID_OPERATION ||
                           expectedKind == RUNTIME_AJAX_QUERY_BAD_REQUEST;
  check(errorSent == expectError, "query error dispatch mismatch");
  if (expectError) {
    const bool invalidOperation = expectedKind == RUNTIME_AJAX_QUERY_INVALID_OPERATION;
    check(request.sendCount == 1 && request.sent && request.sent->status == 400 &&
              request.sent->contentType ==
                  (invalidOperation ? "application/json" : "text/plain") &&
              request.sent->body ==
                  (invalidOperation
                       ? "{\"operationId\":0,\"error\":\"invalid_operation_id\"}"
                       : "BAD_REQUEST") &&
              request.sent->cacheControl == "no-store",
          "query error wire contract mismatch");
  } else {
    check(request.sendCount == 0 && request.sent == nullptr,
          "valid query was rejected before its branch");
  }
  delete request.sent;
}

int main() {
  checkQuery("zero params", {}, RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("valid operation", {{"operationId", "1"}},
             RUNTIME_AJAX_QUERY_OPERATION, 1);
  checkQuery("max operation", {{"operationId", "4294967295"}},
             RUNTIME_AJAX_QUERY_OPERATION, UINT32_MAX);
  checkQuery("empty operation", {{"operationId", ""}},
             RUNTIME_AJAX_QUERY_INVALID_OPERATION, 0);
  checkQuery("zero operation", {{"operationId", "0"}},
             RUNTIME_AJAX_QUERY_INVALID_OPERATION, 0);
  checkQuery("signed operation", {{"operationId", "+1"}},
             RUNTIME_AJAX_QUERY_INVALID_OPERATION, 0);
  checkQuery("overflow operation", {{"operationId", "4294967296"}},
             RUNTIME_AJAX_QUERY_INVALID_OPERATION, 0);
  checkQuery("file operation", {{"operationId", "1", true, false}},
             RUNTIME_AJAX_QUERY_INVALID_OPERATION, 0);
  checkQuery("post operation", {{"operationId", "1", false, true}},
             RUNTIME_AJAX_QUERY_INVALID_OPERATION, 0);
  checkQuery("duplicate operations",
             {{"operationId", "1"}, {"operationId", "2"}},
             RUNTIME_AJAX_QUERY_INVALID_OPERATION, 0);
  checkQuery("duplicate invalid operations",
             {{"operationId", "bad"}, {"operationId", "0"}},
             RUNTIME_AJAX_QUERY_INVALID_OPERATION, 0);

  checkQuery("bootstrap cursor", {{"messageCursor", "0"}},
             RUNTIME_AJAX_QUERY_TELEMETRY, 0);
  checkQuery("max cursor", {{"messageCursor", "4294967295"}},
             RUNTIME_AJAX_QUERY_TELEMETRY, UINT32_MAX);
  checkQuery("empty cursor", {{"messageCursor", ""}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("signed cursor", {{"messageCursor", "-1"}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("overflow cursor", {{"messageCursor", "4294967296"}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("file cursor", {{"messageCursor", "0", true, false}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("post cursor", {{"messageCursor", "0", false, true}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("duplicate cursors",
             {{"messageCursor", "0"}, {"messageCursor", "1"}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("unknown param", {{"unknown", "1"}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("mixed operation cursor",
             {{"operationId", "1"}, {"messageCursor", "0"}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("mixed operation unknown",
             {{"operationId", "1"}, {"unknown", "0"}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);
  checkQuery("two unknown params", {{"a", "1"}, {"b", "2"}},
             RUNTIME_AJAX_QUERY_BAD_REQUEST, 0);

  if (failures != 0) return 1;
  std::cout << "runtime ajax query dispatch smoke passed\n";
  return 0;
}
'''
    compile_and_run(harness, "samovar-runtime-ajax-query-")


def run_source_contracts() -> None:
    errors: list[str] = []

    def read(name: str) -> str:
        path = ROOT / name
        if not path.exists():
            errors.append(f"{name} missing")
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")

    header = read("runtime_event_log.h")
    runtime = read("runtime_helpers.h")
    samovar_h = read("Samovar.h")
    samovar = read("Samovar.ino")
    lua = read("lua.h")
    static_sources = read("tools/static_analysis_sources.json")

    if "char textPool[RUNTIME_EVENT_TEXT_POOL_BYTES + 1]" not in header:
        errors.append("runtime event pool lost its guard byte")
    for token in ("String ", "std::vector", "std::list", "new ", "xTaskCreate", "Semaphore"):
        owner = extract_function_body(header, "struct RuntimeEventRing") if token == "String " else header
        if token in owner:
            errors.append(f"runtime event owner contains forbidden token: {token.strip()}")
    if "sizeof(RuntimeEventRing) <= 10464" not in header:
        errors.append("runtime event owner size gate missing")
    if "runtime_event_parse_cursor" not in header:
        errors.append("strict cursor parser missing")
    copy_text = extract_function_body(
        header, "inline RuntimeEventSnapshotResult runtime_event_copy_text_locked(")
    if "candidate.begin()[candidate.length()] = '\\0';" not in copy_text:
        errors.append("runtime event snapshot does not restore String NUL termination")
    if re.search(r"ring\.textPool\[[^]]+\]\s*=", copy_text):
        errors.append("runtime event snapshot mutates the const ring")
    if static_sources.count('"runtime_event_log.h"') != 1:
        errors.append("static analysis inventory must contain runtime_event_log.h once")

    stripped_h = strip_cpp_comments(samovar_h)
    for declaration in (
        r"\bString\s+Msg\s*;",
        r"\bString\s+LogMsg\s*;",
        r"\buint8_t\s+msg_level\s*;",
    ):
        if re.search(declaration, stripped_h):
            errors.append(f"obsolete shared message global remains: {declaration}")
    if samovar.count("RuntimeEventRing runtimeEventRing{};") != 1:
        errors.append("Samovar.ino must define exactly one runtime event owner")
    if "runtime_event_init(runtimeEventRing);" not in samovar:
        errors.append("runtime event owner is not initialized before use")

    for helper in (
        "copy_web_message_raw",
        "copy_ajax_runtime_snapshot",
        "append_web_message",
        "append_console_log",
    ):
        if helper not in runtime:
            errors.append(f"runtime helper missing: {helper}")
    for obsolete in ("set_web_message_raw", "consume_ajax_runtime_snapshot"):
        if obsolete in runtime:
            errors.append(f"obsolete destructive helper remains: {obsolete}")
    message_adapter = extract_function_body(runtime, "inline RuntimeEventPublishResult append_runtime_event(")
    for forbidden in ("Serial", "WebSerial", "json", "delay("):
        if forbidden in message_adapter:
            errors.append(f"runtime event adapter performs I/O under lock: {forbidden}")
    expected_order = [
        "runtime_state_lock(timeout)",
        "runtime_event_append_locked(",
        "runtime_state_unlock(true);",
    ]
    positions = [message_adapter.find(token) for token in expected_order]
    if not (positions[0] >= 0 and positions == sorted(positions)):
        errors.append("runtime event append lock boundary is incorrect")
    for precheck in (
        "text.length() == 0",
        "text.length() > RUNTIME_EVENT_MAX_TEXT_BYTES",
    ):
        if message_adapter.find(precheck) < 0 or message_adapter.find(precheck) > positions[0]:
            errors.append(f"runtime event precheck is not before semaphore: {precheck}")

    ajax = extract_function_body(samovar, "void send_ajax_json(AsyncWebServerRequest *request)")
    telemetry_capture = extract_function_body(
        samovar,
        "static RuntimeAjaxSnapshotResult captureAjaxTelemetrySnapshot(",
    )
    telemetry_writer = extract_function_body(
        samovar,
        "static void writeAjaxTelemetryFields(",
    )
    required_ajax_tokens = (
        "classifyRuntimeAjaxQuery(request)",
        "sendRuntimeAjaxQueryError(request, query.kind)",
        "captureAjaxTelemetrySnapshot(messageCursor, snapshot)",
        '"Runtime event snapshot unavailable"',
        "writeAjaxTelemetryFields(out, snapshot)",
        "snapshot.runtimeEvent, snapshot.eventText",
    )
    for token in required_ajax_tokens:
        if token not in ajax:
            errors.append(f"strict /ajax contract token missing: {token}")
    if telemetry_capture.count("copy_ajax_runtime_snapshot(") != 1:
        errors.append("telemetry capture must own exactly one runtime event snapshot call")
    if 'jsonAddKey(out, first, "Lstatus")' not in telemetry_writer:
        errors.append("telemetry writer no longer ends with the existing Lstatus field")
    if ajax.find("writeAjaxTelemetryFields(out, snapshot)") > ajax.find(
        "sendRuntimeEventResponse("
    ):
        errors.append("runtime event section is not after existing telemetry fields")
    event_call = ajax.find("sendRuntimeEventResponse(")
    tail = ajax[event_call:] if event_call >= 0 else ""
    if "out.print" in tail or "jsonAddKey" in tail or "jsonPrintEscaped" in tail:
        errors.append("unchecked response write exists after event section starts")

    send_msg = extract_function_body(samovar, "void SendMsg(const String& m, MESSAGE_TYPE msg_type)")
    send_positions = [
        send_msg.find("MqttSendMsg("),
        send_msg.find("msg_q.push("),
        send_msg.find("append_web_message("),
    ]
    present_positions = [position for position in send_positions if position >= 0]
    if not present_positions or present_positions[-1] != send_positions[-1]:
        errors.append("SendMsg no longer appends after existing external side effects")
    if "if (!append_web_message" in send_msg or "RuntimeEventPublishResult" not in send_msg:
        errors.append("SendMsg does not handle typed publish results")
    console_log = extract_function_body(samovar, "void WriteConsoleLog(String StringLogMsg)")
    for token in ("append_console_log(StringLogMsg)", "printRuntimeEventPublishFailure"):
        if token not in console_log:
            errors.append(f"WriteConsoleLog typed path missing: {token}")

    if (
        "static bool lua_str_set_Msg" in lua
        or '{"Msg", lua_str_get_Msg, nullptr, LUA_VAR_RW, "Msg busy"}' not in lua
    ):
        errors.append("Lua Msg descriptor did not keep getter/RW with specialized setter")
    set_string = extract_function_body(lua, "static int lua_wrapper_set_str_variable(")
    for token in (
        'if (Var == "Msg")',
        "append_web_message(Val, NOTIFY_MSG)",
        '"Msg busy"',
        '"Msg too long"',
    ):
        if token not in set_string:
            errors.append(f"Lua specialized Msg setter token missing: {token}")

    lua_sizes = [path.stat().st_size for path in (ROOT / "data_raw").glob("*.lua")]
    if not lua_sizes or max(lua_sizes) != 8691 or max(lua_sizes) > RUNTIME_MAX_TEXT_BYTES:
        errors.append("tracked Lua size evidence no longer matches 8691/10000 contract")

    app = read("data_raw/app.js")
    for token in (
        "let messageCursor = 0;",
        "let telemetryRequestInFlight = false;",
        "async function pollAjax(renderFn, sinks)",
        "fetch('/ajax?messageCursor=' + String(messageCursor)",
        "Пропущены сообщения: обнаружен разрыв последовательности.",
    ):
        if token not in app:
            errors.append(f"shared UI cursor contract token missing: {token}")
    if app.count("async function pollAjax(renderFn, sinks)") != 1:
        errors.append("app.js must own exactly one cursor-aware pollAjax")
    if "messageCursor" in app and re.search(
        r"localStorage\.(?:getItem|setItem)\([^\n]*messageCursor", app
    ):
        errors.append("message cursor must not persist in localStorage")

    for page in ("index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm"):
        page_text = read(f"data/{page}")
        if page_text.count("SamovarApp.startTelemetryPage(renderTelemetry, {") != 1:
            errors.append(f"data/{page} does not use one shared telemetry lifecycle")
        if "SamovarApp.pollAjax(" in page_text or "SamovarApp.startPollLoop(" in page_text:
            errors.append(f"data/{page} retains local polling ownership")
        if re.search(r"\bmyObj\.(?:Msg|LogMsg)\b", page_text):
            errors.append(f"data/{page} retains a duplicate runtime event consumer")

    chart = read("data_raw/chart.htm")
    if '<script src="app.js"></script>' not in chart:
        errors.append("chart.htm does not load the shared cursor owner")
    if "fetch('/ajax" in chart or 'fetch("/ajax' in chart:
        errors.append("chart.htm retains a raw telemetry fetch")
    if chart.count("SamovarApp.startTelemetryPage(renderTelemetry, {") != 1:
        errors.append("chart.htm must start exactly one shared telemetry loop")
    for option_token in (
        "connectionIds: { online: 'GreenT', offline: 'RedT' }",
        "storeMessageHistory: false",
        "onLastMessageRemoved: function(remainingCount)",
    ):
        if option_token not in chart:
            errors.append(f"chart.htm shared lifecycle option missing: {option_token}")

    calibrate = read("data_raw/calibrate.htm")
    if calibrate.count("/ajax?messageCursor=0") != 1:
        errors.append("calibrate.htm confirmed readback must use exact cursor telemetry URL")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
    run_query_dispatch_harness(samovar, header)
    run_checked_writer_harness(samovar)
    print("runtime event backend source contracts passed")


RUNTIME_MAX_TEXT_BYTES = 10000


if __name__ == "__main__":
    run_host_harness()
    run_source_contracts()
