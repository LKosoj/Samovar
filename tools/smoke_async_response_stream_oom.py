#!/usr/bin/env python3
"""Проверяет отказоустойчивость AsyncResponseStream при нехватке памяти."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "libraries" / "ESP_Async_WebServer" / "src" / "WebResponseImpl.h"
SOURCE = ROOT / "libraries" / "ESP_Async_WebServer" / "src" / "WebResponses.cpp"


def extract_class(source: str) -> str:
    start = source.find("class AsyncResponseStream")
    if start < 0:
        raise ValueError("class not found: AsyncResponseStream")
    body, end = extract_braced_block_after(source, "class AsyncResponseStream", start)
    brace = source.find("{", start)
    return source[start : brace + 1] + body + source[end - 1 : end + 1]


def extract_parts(header: str, source: str) -> tuple[str, dict[str, str]]:
    declaration = extract_class(header)
    signatures = (
        "AsyncResponseStream::AsyncResponseStream(const char *contentType, size_t bufferSize)",
        "size_t AsyncResponseStream::_fillBuffer(uint8_t *buf, size_t maxLen)",
        "size_t AsyncResponseStream::write(const uint8_t *data, size_t len)",
        "size_t AsyncResponseStream::write(uint8_t data)",
    )
    methods = {signature: extract_function_body(source, signature) for signature in signatures}
    return declaration, methods


HARNESS_PREFIX = r'''
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <new>
#include <string>

static void *active[32];
static size_t active_count = 0;
static size_t allocation_attempt = 0;
static size_t fail_attempt = 0;

static void track_alloc(void *ptr) {
  if (active_count >= 32) std::abort();
  active[active_count++] = ptr;
}

static void track_free(void *ptr) {
  for (size_t i = 0; i < active_count; ++i) {
    if (active[i] == ptr) {
      active[i] = active[--active_count];
      return;
    }
  }
  std::abort();
}

void *operator new[](std::size_t size) {
  ++allocation_attempt;
  if (fail_attempt && allocation_attempt == fail_attempt) throw std::bad_alloc();
  void *ptr = std::malloc(size ? size : 1);
  if (!ptr) throw std::bad_alloc();
  track_alloc(ptr);
  return ptr;
}

void *operator new[](std::size_t size, const std::nothrow_t &) noexcept {
  ++allocation_attempt;
  if (fail_attempt && allocation_attempt == fail_attempt) return nullptr;
  void *ptr = std::malloc(size ? size : 1);
  if (ptr) track_alloc(ptr);
  return ptr;
}

void operator delete[](void *ptr) noexcept {
  if (ptr) {
    track_free(ptr);
    std::free(ptr);
  }
}

void operator delete[](void *ptr, std::size_t) noexcept {
  if (ptr) {
    track_free(ptr);
    std::free(ptr);
  }
}

static void reset_failures() {
  allocation_attempt = 0;
  fail_attempt = 0;
}

static void fail_next_allocation() {
  fail_attempt = allocation_attempt + 1;
}

struct String {
  String() = default;
  String(const char *value) : value(value ? value : "") {}
  String &operator=(const char *value) {
    this->value = value ? value : "";
    return *this;
  }
  const char *c_str() const { return value.c_str(); }
  std::string value;
};

class Print {
public:
  virtual ~Print() = default;
  virtual size_t write(uint8_t) = 0;
};

enum WebResponseState {
  RESPONSE_SETUP,
  RESPONSE_HEADERS,
  RESPONSE_CONTENT,
  RESPONSE_WAIT_ACK,
  RESPONSE_END,
  RESPONSE_FAILED
};

class AsyncAbstractResponse {
protected:
  int _code = 0;
  String _contentType;
  size_t _contentLength = 0;
  WebResponseState _state = RESPONSE_SETUP;

public:
  virtual ~AsyncAbstractResponse() = default;
  virtual bool _sourceValid() const { return false; }
  virtual size_t _fillBuffer(uint8_t *, size_t) { return 0; }
  bool _started() const { return _state != RESPONSE_SETUP; }
};

void async_ws_log_e(const char *) {}
'''


def harness(declaration: str, methods: dict[str, str]) -> str:
    return (
        HARNESS_PREFIX
        + "\n"
        + declaration
        + "\n"
        + "\n".join(signature + " {" + body + "}" for signature, body in methods.items())
        + r'''
class Probe : public AsyncResponseStream {
public:
  Probe(const char *type, size_t size) : AsyncResponseStream(type, size) {}
  size_t length() const { return _contentLength; }
  void mark_started() { _state = RESPONSE_CONTENT; }
};

static int check(bool condition, const char *message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    return 1;
  }
  return 0;
}

static int normal_stream(size_t reserve, uint8_t seed) {
  reset_failures();
  uint8_t payload[1463];
  for (size_t i = 0; i < sizeof(payload); ++i) {
    payload[i] = static_cast<uint8_t>(seed + i * 13);
  }
  payload[3] = 0;
  payload[reserve - 1] = static_cast<uint8_t>(seed ^ 0x5a);
  {
    Probe response("text/plain", reserve);
    if (check(response.write(payload, reserve) == reserve, "exact write failed")) return 1;
    const uint8_t suffix[] = {0x00, seed, 0xff};
    if (check(response.write(suffix, sizeof(suffix)) == sizeof(suffix), "growth write failed")) return 1;
    std::memcpy(payload + reserve, suffix, sizeof(suffix));
    const size_t total = reserve + sizeof(suffix);
    if (check(response._sourceValid(), "successful response became invalid")) return 1;
    if (check(response.length() == total, "content length mismatch")) return 1;
    if (check(response.available() == total, "available mismatch before read")) return 1;
    uint8_t first[3] = {};
    if (check(response._fillBuffer(first, sizeof(first)) == sizeof(first), "first chunk size mismatch")) return 1;
    if (check(std::memcmp(first, payload, sizeof(first)) == 0, "first chunk data mismatch")) return 1;
    uint8_t rest[1463] = {};
    size_t rest_len = response._fillBuffer(rest, sizeof(rest));
    if (check(rest_len == total - sizeof(first), "remaining chunk size mismatch")) return 1;
    if (check(std::memcmp(rest, payload + sizeof(first), rest_len) == 0, "remaining chunk offset mismatch")) return 1;
    if (check(response.available() == 0, "available mismatch after read")) return 1;
  }
  return check(active_count == 0, "response buffer leaked");
}

static int zero_reserve() {
  reset_failures();
  uint8_t payload[] = {0x00, 0x7f, 0xff, 0x42};
  {
    Probe response("application/octet-stream", 0);
    if (check(response.write(payload, sizeof(payload)) == sizeof(payload), "zero reserve write failed")) return 1;
    if (check(response.length() == sizeof(payload), "zero reserve length mismatch")) return 1;
  }
  return check(active_count == 0, "zero reserve buffer leaked");
}

static int started_rejects_write() {
  reset_failures();
  uint8_t value = 9;
  {
    Probe response("text/plain", 16);
    response.mark_started();
    if (check(response.write(&value, 1) == 0, "started response accepted write")) return 1;
    if (check(response.length() == 0, "started response changed length")) return 1;
  }
  return check(active_count == 0, "started response leaked");
}

static int initial_failure(size_t reserve) {
  reset_failures();
  fail_next_allocation();
  {
    Probe response("text/plain", reserve);
    uint8_t value = 1;
    if (check(response.write(&value, 1) == 0, "initial allocation failure accepted write")) return 1;
    if (check(!response._sourceValid(), "initial allocation failure remained valid")) return 1;
  }
  return check(active_count == 0, "initial failure leaked");
}

static int growth_failure_latches(size_t reserve) {
  reset_failures();
  uint8_t first[1460] = {};
  uint8_t next = 8;
  {
    Probe response("text/plain", reserve);
    if (check(response.write(first, reserve) == reserve, "initial write failed")) return 1;
    fail_next_allocation();
    if (check(response.write(&next, 1) == 0, "growth allocation failure wrote partial data")) return 1;
    if (check(response.length() == reserve, "growth failure changed length")) return 1;
    if (check(!response._sourceValid(), "growth failure remained valid")) return 1;
    reset_failures();
    if (check(response.write(&next, 1) == 0, "latched failure recovered unexpectedly")) return 1;
  }
  return check(active_count == 0, "growth failure leaked");
}

int main() {
  try {
    if (normal_stream(16, 0x11) || normal_stream(1460, 0x83) || zero_reserve() ||
        started_rejects_write() || initial_failure(16) || initial_failure(1460) ||
        growth_failure_latches(16) || growth_failure_latches(1460)) return 1;
  } catch (const std::bad_alloc &) {
    std::cerr << "FAIL: allocation failure escaped response\n";
    return 2;
  }
  if (active_count != 0) {
    std::cerr << "FAIL: response buffer leaked\n";
    return 1;
  }
  return 0;
}
'''
    )


def run_harness(declaration: str, methods: dict[str, str]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-response-stream-") as directory:
        root = Path(directory)
        cpp = root / "harness.cpp"
        binary = root / "harness"
        cpp.write_text(harness(declaration, methods), encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
        )
        if compile_result.returncode:
            return compile_result.returncode, compile_result.stderr
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr


def main() -> int:
    try:
        declaration, methods = extract_parts(HEADER.read_text(encoding="utf-8"), SOURCE.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"async response stream OOM smoke FAILED: {exc}", file=sys.stderr)
        return 1

    errors = []
    code, output = run_harness(declaration, methods)
    if code:
        errors.append(f"baseline failed: {output.strip()}")

    constructor, fill, write, _ = methods
    mutations = (
        (constructor, "new (std::nothrow) uint8_t[", "new uint8_t[",
         "allocation failure escaped response"),
        (write, "new (std::nothrow) uint8_t[", "new uint8_t[",
         "allocation failure escaped response"),
        (write, "_allocationFailed = true;", "(void)0;", "growth failure remained valid"),
        (None, "&& !_allocationFailed", "&& true", "initial allocation failure remained valid"),
        (fill, "_readOffset += len", "_readOffset += maxLen", "available mismatch after read"),
        (write, "memcpy(content.get(), _content.get(), _contentLength);",
         "memset(content.get(), 0, _contentLength);", "first chunk data mismatch"),
    )
    for target, old, new, expected in mutations:
        original = methods[target] if target else declaration
        if original.count(old) != 1:
            errors.append(f"mutation token not unique: {old}")
            continue
        mutated = original.replace(old, new, 1)
        changed_methods = dict(methods)
        if target:
            changed_methods[target] = mutated
        code, output = run_harness(declaration if target else mutated, changed_methods)
        if code == 0 or "FAIL: " + expected not in output:
            errors.append(f"mutation {old!r} did not fail semantically: {output.strip()}")

    if errors:
        print("async response stream OOM smoke FAILED: " + "; ".join(errors), file=sys.stderr)
        return 1
    print("async response stream OOM checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
