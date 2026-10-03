#!/usr/bin/env python3
"""Проверяет, что ошибка копирования HTTP-ответа не выдаётся Lua как пустой успех."""

from pathlib import Path
import subprocess
import tempfile

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
errors: list[str] = []


def body(signature: str) -> str:
    try:
        return extract_function_body(SOURCE, signature, strip_comments=False)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


GET_BODY = body("String http_sync_request_get(String url)")
CUSTOM_BODY = body("String http_sync_request_custom(const String& method")
for name, source in (("get", GET_BODY), ("custom", CUSTOM_BODY)):
    if "String response = request.responseText();" not in source:
        errors.append(f"{name}: responseText() was not extracted")
    if "if (request.responseHTTPcode() < 0) return \"<ERR>\";" not in source:
        errors.append(f"{name}: negative response code guard is missing")


HARNESS = r'''
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>

class String : public std::string {
 public:
  using std::string::string;
  String() = default;
  String(const std::string& value) : std::string(value) {}
  String(int value) : std::string(std::to_string(value)) {}
  size_t length() const { return size(); }
};
static String operator+(const char* left, const String& right) { return String(std::string(left) + right); }
static String operator+(const String& left, const char* right) { return String(std::string(left) + right); }
static String operator+(const String& left, const String& right) { return String(std::string(left) + right); }

struct SerialProbe {
  template <typename T> void print(const T&) {}
  template <typename T> void println(const T&) {}
} Serial;
struct HeapProbe { uint32_t getFreeHeap() const { return 120000; } uint32_t getMaxAllocHeap() const { return 60000; } };
HeapProbe ESP;
static bool acquiredFlag = true;
static bool completionFlag = true;
struct HttpRequestLockGuard { bool acquired; HttpRequestLockGuard() : acquired(acquiredFlag) {} };

class asyncHTTPrequest {
 public:
  int code = 200;
  bool copyFails = false;
  String responseBody = "";
  size_t expectedLength = 0;
  void setDebug(bool) {}
  void setTimeout(uint32_t) {}
  size_t available() const { return responseBody.length(); }
  size_t responseLength() const { return expectedLength; }
  int responseHTTPcode() const { return code; }
  String responseText() {
    if (copyFails) { code = -8; return String(); }
    return responseBody;
  }
};
static asyncHTTPrequest sharedHttpRequest;

static bool http_sync_complete_get(asyncHTTPrequest&, const String&, uint32_t) {
  return completionFlag;
}
static bool http_sync_request_connect_and_send(const String&, const String&, const String&, const String&,
                                               bool, bool, uint32_t) {
  return completionFlag;
}

String http_sync_request_get(String url) { @GET@ }
String http_sync_request_custom(const String& method, const String& url, const String& body,
                                const String& contentType) { @CUSTOM@ }

static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
static void reset(const String& payload) {
  acquiredFlag = true; completionFlag = true;
  sharedHttpRequest = asyncHTTPrequest{};
  sharedHttpRequest.responseBody = payload;
  sharedHttpRequest.expectedLength = payload.length();
}

int main() {
  reset("first response");
  check(http_sync_request_get("http://one") == "first response", "GET must return the first successful body");
  reset("different second response");
  check(http_sync_request_custom("POST", "http://two", "body", "text/plain") == "different second response",
        "custom request must return a second successful body");

  reset("copy failure body");
  sharedHttpRequest.copyFails = true;
  sharedHttpRequest.expectedLength = 0;
  check(http_sync_request_get("http://copy-fail") == "<ERR>",
        "response copy failure must return <ERR>");
  reset("custom copy failure body");
  sharedHttpRequest.copyFails = true;
  sharedHttpRequest.expectedLength = 0;
  check(http_sync_request_custom("POST", "http://copy-fail", "body", "text/plain") == "<ERR>",
        "custom response copy failure must return <ERR>");

  reset("negative before copy");
  sharedHttpRequest.code = -8;
  check(http_sync_request_get("http://negative") == "<ERR>",
        "initial negative HTTP code must return <ERR>");

  reset("incomplete");
  completionFlag = false;
  check(http_sync_request_get("http://incomplete") == "<ERR>",
        "incomplete request must return <ERR>");
  reset("busy");
  acquiredFlag = false;
  check(http_sync_request_custom("POST", "http://busy", "body", "text/plain") == "<ERR>",
        "busy request lock must return <ERR>");
  return 0;
}
'''


def run_variant(name: str, get_body: str, custom_body: str, expected_success: bool) -> None:
    source = HARNESS.replace("@GET@", get_body).replace("@CUSTOM@", custom_body)
    with tempfile.TemporaryDirectory(prefix=f"samovar-http-copy-{name}-") as directory:
        root = Path(directory)
        cpp = root / "probe.cpp"
        cpp.write_text(source, encoding="utf-8")
        result = subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(root / "probe")], capture_output=True, text=True)
        if result.returncode:
            errors.append(f"{name} compile failed:\n{result.stderr}")
            return
        result = subprocess.run([str(root / "probe")], capture_output=True, text=True)
        if expected_success and result.returncode:
            errors.append(f"{name} behavior failed:\n{result.stdout}{result.stderr}")
        elif not expected_success:
            expected = ("custom response copy failure must return <ERR>"
                        if name == "missing_custom_copy_guard" else "response copy failure must return <ERR>")
            if result.returncode == 0 or "FAIL: " + expected not in result.stdout + result.stderr:
                errors.append(f"mutation {name} missed its assertion: {result.stdout}{result.stderr}")


if not errors:
    run_variant("current", GET_BODY, CUSTOM_BODY, True)
    run_variant("missing_get_copy_guard", GET_BODY.replace('  if (request.responseHTTPcode() < 0) return "<ERR>";\n', "", 1), CUSTOM_BODY, False)
    run_variant("missing_custom_copy_guard", GET_BODY, CUSTOM_BODY.replace('    if (request.responseHTTPcode() < 0) return "<ERR>";\n', "", 1), False)

if errors:
    print("HTTP response copy failure smoke failed:")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("HTTP response copy failure smoke passed")
