#!/usr/bin/env python3
"""Проверяет отдачу страниц режимов: кэш браузера со сверкой по ETag и ответ 304."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "WebServer.ino"
PAGE_SIGNATURE = "void send_mode_page(AsyncWebServerRequest *request, const char *spiffsPath)"
CALLERS = (
    ("void send_index_page(AsyncWebServerRequest *request)", "send_mode_page(request, get_index_page_path());"),
    (
        "void send_mode_specific_htm(AsyncWebServerRequest *request, const char *spiffsPath, SAMOVAR_MODE requiredMode)",
        "send_mode_page(request, spiffsPath);",
    ),
)

HARNESS = r'''
#include <iostream>
#include <map>
#include <string>
#include <vector>

using String = std::string;
struct FakeFs {} SPIFFS;
static int failures = 0, liveResponses = 0;

class AsyncWebHeader {
 public:
  AsyncWebHeader(String n, String v) : name(n), text(v) {}
  const String &value() const { return text; }
  String name, text;
};

class AsyncWebServerResponse {
 public:
  explicit AsyncWebServerResponse(int c) : code(c) { liveResponses++; }
  virtual ~AsyncWebServerResponse() { liveResponses--; }
  bool addHeader(const char *name, const String &value) {
    for (AsyncWebHeader &header : headers) {
      if (header.name == name) { header.text = value; return true; }
    }
    headers.emplace_back(name, value);
    return true;
  }
  const AsyncWebHeader *getHeader(const char *name) const {
    for (const AsyncWebHeader &header : headers) {
      if (header.name == name) return &header;
    }
    return nullptr;
  }
  int code;
  std::vector<AsyncWebHeader> headers;
};

// Как настоящий AsyncFileResponse: ETag есть только у файла .gz, нет файла - нет ответа.
static const std::map<String, String> gzEtags = {{"/index.htm", "\"AAAA1111\""}, {"/beer.htm", "\"BBBB2222\""}};

class AsyncWebServerRequest {
 public:
  explicit AsyncWebServerRequest(String condition) : ifNoneMatch(condition) {}
  AsyncWebServerResponse *beginResponse(FakeFs &, const String &path, const char *, bool, void *) {
    if (path == "/missing.htm") return nullptr;
    AsyncWebServerResponse *response = new AsyncWebServerResponse(200);
    auto file = gzEtags.find(path);
    if (file != gzEtags.end()) {
      response->addHeader("ETag", file->second);
      response->addHeader("Cache-Control", "no-cache");
    }
    return response;
  }
  AsyncWebServerResponse *beginResponse(int code) { return new AsyncWebServerResponse(code); }
  const String &header(const char *) const { return ifNoneMatch; }
  void send(AsyncWebServerResponse *response) { sent.push_back(response); }
  void send(int code) { sent.push_back(new AsyncWebServerResponse(code)); }
  String ifNoneMatch;
  std::vector<AsyncWebServerResponse *> sent;
};

void send_mode_page(AsyncWebServerRequest *request, const char *spiffsPath) {
@PAGE_BODY@
}

static void check(const char *name, const char *path, const String &condition, int code, const char *etag) {
  AsyncWebServerRequest request(condition);
  send_mode_page(&request, path);
  if (request.sent.size() != 1) {
    std::cerr << "FAIL: page must send one response: " << name << '\n';
    failures++;
    return;
  }
  AsyncWebServerResponse *response = request.sent[0];
  const AsyncWebHeader *etagHeader = response->getHeader("ETag");
  const AsyncWebHeader *cache = response->getHeader("Cache-Control");
  if (response->code != code) {
    std::cerr << "FAIL: wrong status: " << name << " got " << response->code << '\n';
    failures++;
  }
  if (etag != nullptr && (etagHeader == nullptr || etagHeader->value() != etag)) {
    std::cerr << "FAIL: wrong ETag: " << name << '\n';
    failures++;
  }
  if (code != 404 && (cache == nullptr || cache->value() != "no-cache")) {
    std::cerr << "FAIL: page must be stored and revalidated: " << name << '\n';
    failures++;
  }
  if (liveResponses != 1) {
    std::cerr << "FAIL: file response leaked: " << name << '\n';
    failures++;
  }
  delete response;
  liveResponses = 0;
}

int main() {
  check("first open", "/index.htm", "", 200, "\"AAAA1111\"");
  check("same page", "/index.htm", "\"AAAA1111\"", 304, "\"AAAA1111\"");
  check("same other page", "/beer.htm", "\"BBBB2222\"", 304, "\"BBBB2222\"");
  check("page changed", "/index.htm", "\"BBBB2222\"", 200, "\"AAAA1111\"");
  check("file without ETag", "/plain.htm", "", 200, nullptr);
  check("file without ETag, browser has copy", "/plain.htm", "\"AAAA1111\"", 200, nullptr);
  check("no file", "/missing.htm", "", 404, nullptr);
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(page_body: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-mode-page-") as temp_dir:
        source_path = Path(temp_dir) / "harness.cpp"
        binary_path = Path(temp_dir) / "harness"
        source_path.write_text(HARNESS.replace("@PAGE_BODY@", page_body), encoding="utf-8")
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
    source = SOURCE.read_text(encoding="utf-8")
    for signature, call in CALLERS:
        if call not in extract_function_body(source, signature):
            print(f"FAIL: page must go through send_mode_page: {signature}", file=sys.stderr)
            return 1

    body = extract_function_body(source, PAGE_SIGNATURE)
    returncode, output = compile_and_run(body)
    if returncode != 0:
        print(output, file=sys.stderr)
        return 1

    condition = 'etag != nullptr && request->header("If-None-Match") == etag->value()'
    mutants = (
        (condition, "false", "FAIL: wrong status: same page got 200"),
        (condition, "etag != nullptr", "FAIL: wrong status: page changed got 304"),
        ('notModified->addHeader("ETag", etag->value());', "", "FAIL: wrong ETag: same page"),
        ("delete response;", "", "FAIL: file response leaked: same page"),
        (
            'response->addHeader("Cache-Control", "no-cache");',
            'response->addHeader("Cache-Control", "no-store");',
            "FAIL: page must be stored and revalidated: first open",
        ),
        (
            'notModified->addHeader("Cache-Control", "no-cache");',
            "",
            "FAIL: page must be stored and revalidated: same page",
        ),
    )
    for original, replacement, expected_failure in mutants:
        mutant = body.replace(original, replacement, 1)
        if mutant == body:
            print(f"FAIL: could not create mutation: {original}", file=sys.stderr)
            return 1
        returncode, output = compile_and_run(mutant)
        if returncode == 0 or expected_failure not in output:
            print(f"FAIL: mutation survived or failed for the wrong reason: {original}\n{output}", file=sys.stderr)
            return 1

    print("Mode page cache scenarios and mutations were checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
