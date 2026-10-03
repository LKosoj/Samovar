#!/usr/bin/env python3
"""Поведенческая проверка ограничений памяти и блокировок HTTP-клиента."""

from pathlib import Path
import subprocess
import tempfile

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "libraries/asyncHTTPrequest/src/asyncHTTPrequest.cpp").read_text()
errors: list[str] = []


def body(signature: str) -> str:
    try:
        return extract_function_body(SOURCE, signature, strip_comments=False)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


ON_DATA = body("void  asyncHTTPrequest::_onData(void* Vbuf, size_t len)")
SET_MAX = body("void asyncHTTPrequest::setMaxResponseBufferSize(uint16_t bytes)")
SEND = body("bool\tasyncHTTPrequest::send()")
BUILD_REQUEST = body("bool   asyncHTTPrequest::_buildRequest()")
FAIL_REQUEST = body("void asyncHTTPrequest::_failRequest(int code)")
ON_ERROR = body("void  asyncHTTPrequest::_onError(AsyncClient* client, int8_t error)")
PROCESS_CHUNKS = body("void  asyncHTTPrequest::_processChunks()")
COLLECT_HEADERS = body("bool  asyncHTTPrequest::_collectHeaders()")

required = {
    "_onData": (ON_DATA, "_maxResponseBufferBytes", "_release;"),
    "send": (SEND, "_buildRequest()", "_release;"),
    "_buildRequest": (BUILD_REQUEST, "_request->available() != expected", "HTTPCODE_TOO_LESS_RAM"),
    "_failRequest": (FAIL_REQUEST, "_client->abort()", "_setReadyState(readyStateDone)"),
    "_onError": (ON_ERROR, "if(_HTTPcode >= 0)", "_HTTPcode = error"),
    "_processChunks": (PROCESS_CHUNKS, "copied != expected", "HTTPCODE_TOO_LESS_RAM"),
    "_collectHeaders": (COLLECT_HEADERS, "if( ! headerLine.length())", "return false"),
}
if not SET_MAX or "_maxResponseBufferBytes = bytes" not in SET_MAX:
    errors.append("setMaxResponseBufferSize was not extracted")
for name, (source, *tokens) in required.items():
    if not source:
        errors.append(f"{name} was not extracted")
    for token in tokens:
        if token not in source:
            errors.append(f"{name} missing source token: {token}")

HARNESS = r'''
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <strings.h>
#include <new>

using size_t = std::size_t;
class asyncHTTPrequest;
struct AsyncClient { asyncHTTPrequest* owner = nullptr; bool aborted = false; void abort(); void close() {} };
struct Header {
  char* name; char* value; Header* next = nullptr;
  ~Header() { delete[] name; delete[] value; delete next; }
};
struct URL { char* path; char* query; ~URL() { delete[] path; delete[] query; } };
class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const std::string& value) : value_(value) {}
  String(int value) : value_(std::to_string(value)) {}
  size_t length() const { return value_.length(); }
  const char* c_str() const { return value_.c_str(); }
  String substring(size_t start, size_t length = std::string::npos) const { return value_.substr(start, length); }
  int indexOf(char value, size_t start = 0) const { auto pos = value_.find(value, start); return pos == std::string::npos ? -1 : static_cast<int>(pos); }
  void trim() { const auto first = value_.find_first_not_of(" \t"); const auto last = value_.find_last_not_of(" \t"); value_ = first == std::string::npos ? "" : value_.substr(first, last - first + 1); }
  int toInt() const { return std::atoi(value_.c_str()); }
  String& operator+=(const char* value) { value_ += value; return *this; }
  String& operator+=(char value) { value_ += value; return *this; }
  bool operator==(const char* value) const { return value_ == value; }
 private:
  std::string value_;
};
struct Buf {
  std::string data;
  size_t maxWrite = static_cast<size_t>(-1);
  size_t available() const { return data.size(); }
  size_t write(const char* source) { return write(reinterpret_cast<const uint8_t*>(source), std::strlen(source)); }
  size_t write(char value) { return write(reinterpret_cast<const uint8_t*>(&value), 1); }
  size_t write(const uint8_t* source, size_t length) {
    const size_t copied = std::min(length, maxWrite);
    data.append(reinterpret_cast<const char*>(source), copied);
    return copied;
  }
  size_t write(Buf* source, size_t length) {
    const size_t copied = std::min({length, source->available(), maxWrite});
    data.append(source->data.data(), copied);
    source->data.erase(0, copied);
    return copied;
  }
  String readStringUntil(const char* delimiter) {
    const auto pos = data.find(delimiter);
    if (pos == std::string::npos) return String();
    const size_t length = pos + std::strlen(delimiter);
    String result(data.substr(0, length));
    data.erase(0, length);
    return result;
  }
  int indexOf(const char* needle) const {
    const auto pos = data.find(needle);
    return pos == std::string::npos ? -1 : static_cast<int>(pos);
  }
  String peekString(int length) const { return String(data.substr(0, length)); }
};

class asyncHTTPrequest {
 public:
  static constexpr int HTTPCODE_TOO_LESS_RAM = -8;
  static constexpr int HTTPCODE_RESPONSE_TOO_LARGE = -12;
  static constexpr int HTTPCODE_CONNECTION_LOST = -5;
  enum Ready { readyStateOpened = 1, readyStateHdrsRecvd = 2, readyStateLoading = 3, readyStateDone = 4 };
  int lockDepth = 0;
  int _HTTPcode = 200;
  bool _chunked = false;
  Ready _readyState = readyStateOpened;
  uint32_t _lastActivity = 0, _requestEndTime = 0, _timeout = 1;
  size_t _contentLength = 0, _contentRead = 0;
  uint16_t _maxResponseBufferBytes = 16 * 1024;
  enum Method { HTTPmethodGET, HTTPmethodPOST };
  Method _HTTPmethod = HTTPmethodGET;
  URL* _URL = nullptr;
  Buf* _request = nullptr;
  Buf* _response = nullptr;
  Buf* _chunks = nullptr;
  Header* _headers = nullptr;
  AsyncClient* _client = nullptr;
  bool callbackCalled = false;
  bool hasConnectionDisconnect = false;
  using DataCB = void(*)(void*, asyncHTTPrequest*, size_t);
  DataCB _onDataCB = nullptr;
  void* _onDataCBarg = nullptr;

  int available() const { return _response ? static_cast<int>(_response->available()) : 0; }
  void setMaxResponseBufferSize(uint16_t bytes);
  void _setReadyState(Ready state) { _readyState = state; }
  void _onError(AsyncClient*, int8_t);
  void _failRequest(int);
  bool _buildRequest();
  bool _collectHeaders();
  void _processChunks();
  void _onData(void*, size_t);
  bool send();
  size_t _send() { return 0; }
  Header* _addHeader(const char* name, const char* value) { auto* h = new Header{ strdup(name), strdup(value), _headers }; _headers = h; return h; }
  Header* _getHeader(const char* name) { for (auto* h = _headers; h; h = h->next) if (h->name == name) return h; return nullptr; }
  char* respHeaderValue(const char*) { return hasConnectionDisconnect ? const_cast<char*>("disconnect") : nullptr; }
  uint32_t millis() const { return 1; }
};

#define _seize ++lockDepth
#define _release --lockDepth
#define DEBUG_HTTP(...) do {} while (0)
#define PSTR(value) value
#define strcasecmp_P strcasecmp
using header = Header;
using xbuf = Buf;

void AsyncClient::abort() { aborted = true; if (owner) owner->_onError(this, -13); }
void asyncHTTPrequest::setMaxResponseBufferSize(uint16_t bytes) { @SET_MAX@ }
void asyncHTTPrequest::_onError(AsyncClient* client, int8_t error) { @ON_ERROR@ }
void asyncHTTPrequest::_failRequest(int code) { @FAIL_REQUEST@ }
bool asyncHTTPrequest::_buildRequest() { @BUILD_REQUEST@ }
bool asyncHTTPrequest::send() { @SEND@ }
void asyncHTTPrequest::_processChunks() { @PROCESS_CHUNKS@ }
bool asyncHTTPrequest::_collectHeaders() { @COLLECT_HEADERS@ }
void asyncHTTPrequest::_onData(void* Vbuf, size_t len) { @ON_DATA@ }

static void check(bool value, const char* message) {
  if (!value) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
static void setup(asyncHTTPrequest& request) {
  request._client = new AsyncClient{&request};
  request._response = new Buf;
  request._readyState = asyncHTTPrequest::readyStateOpened;
  request._HTTPcode = 200;
}
static void cleanup(asyncHTTPrequest& request) {
  delete request._client; delete request._response; delete request._chunks; delete request._request; delete request._URL;
  delete request._headers;
  request._headers = nullptr;
}

int main() {
  {
    asyncHTTPrequest request; setup(request);
    const char first[] = "HTTP/1.1 200 OK\r\nContent-Length: 3\r\n";
    request._onData((void*)first, sizeof(first) - 1);
    check(request.lockDepth == 0, "incomplete headers must release the recursive lock");
    const char second[] = "\r\nabc";
    request._onData((void*)second, sizeof(second) - 1);
    check(request.lockDepth == 0 && request._readyState == asyncHTTPrequest::readyStateDone,
          "complete headers and body must finish without a locked request");
    cleanup(request);
  }
  {
    asyncHTTPrequest request; request._request = new Buf; request._HTTPcode = 0;
    request._client = new AsyncClient{&request};
    check(!request.send() && request.lockDepth == 0, "send build failure must release the recursive lock");
    cleanup(request);
  }
  {
    asyncHTTPrequest request; request._client = new AsyncClient{&request};
    request._HTTPmethod = asyncHTTPrequest::HTTPmethodGET;
    request._URL = new URL{strdup("/status"), strdup("?full=1")};
    request._addHeader("Host", "example");
    request._addHeader("X-Test", "two");
    check(request.send(), "complete request build must succeed");
    check(request._request->data == "GET /status?full=1 HTTP/1.1\r\nX-Test:two\r\nHost:example\r\n\r\n",
          "complete request build must serialize the exact request");
    cleanup(request);
  }
  {
    asyncHTTPrequest request; request._client = new AsyncClient{&request};
    request._request = new Buf; request._request->maxWrite = 2;
    request._URL = new URL{strdup("/long-path"), strdup("?q=2")};
    request._addHeader("Host", "example");
    check(!request.send() && request._HTTPcode == asyncHTTPrequest::HTTPCODE_TOO_LESS_RAM &&
              request._client->aborted && request.lockDepth == 0,
          "partial request build must report low RAM, abort, and release the lock");
    cleanup(request);
  }
  {
    asyncHTTPrequest request; setup(request);
    request.setMaxResponseBufferSize(16 * 1024);
    request._response->data.assign(16 * 1024, 'x');
    const char byte = 'y';
    request._onData((void*)&byte, 1);
    check(request._HTTPcode == asyncHTTPrequest::HTTPCODE_RESPONSE_TOO_LARGE && request.lockDepth == 0 && request._client->aborted,
          "normal response limit must abort the client and preserve its negative code");
    cleanup(request);
  }
  {
    asyncHTTPrequest request; setup(request); request._chunks = new Buf;
    request.setMaxResponseBufferSize(UINT16_MAX);
    request._chunks->data.assign(UINT16_MAX - 1, 'x');
    request._response->data = "z";
    const char bytes[] = "12";
    request._onData((void*)bytes, sizeof(bytes) - 1);
    check(request._HTTPcode == asyncHTTPrequest::HTTPCODE_RESPONSE_TOO_LARGE,
          "chunked response limit must include response and chunk buffers");
    cleanup(request);
  }
  {
    asyncHTTPrequest request; setup(request); request._response->maxWrite = 0;
    const char body[] = "HTTP/1.1 200 OK\r\n";
    request._onData((void*)body, sizeof(body) - 1);
    check(request._HTTPcode == asyncHTTPrequest::HTTPCODE_TOO_LESS_RAM && request.lockDepth == 0 && request._client->aborted,
          "response allocation failure must report low RAM and release the lock");
    cleanup(request);
  }
  {
    asyncHTTPrequest request; request._chunks = new Buf; request._response = new Buf; request._client = new AsyncClient{&request};
    request._chunks->data = "3\r\nabc\r\n"; request._response->maxWrite = 2;
    request._contentLength = 0;
    request._processChunks();
    check(request._HTTPcode == asyncHTTPrequest::HTTPCODE_TOO_LESS_RAM,
          "short chunk transfer must not be treated as success");
    cleanup(request);
  }
  return 0;
}
'''

for marker, source in (
    ("@SET_MAX@", SET_MAX),
    ("@ON_ERROR@", ON_ERROR), ("@FAIL_REQUEST@", FAIL_REQUEST),
    ("@BUILD_REQUEST@", BUILD_REQUEST), ("@SEND@", SEND),
    ("@PROCESS_CHUNKS@", PROCESS_CHUNKS), ("@COLLECT_HEADERS@", COLLECT_HEADERS),
    ("@ON_DATA@", ON_DATA),
):
    HARNESS = HARNESS.replace(marker, source)


def run_variant(name: str, source: str, expected_success: bool) -> None:
    with tempfile.TemporaryDirectory(prefix=f"samovar-http-{name}-") as directory:
        root = Path(directory)
        cpp = root / "probe.cpp"
        cpp.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(["g++", "-std=c++17", str(cpp), "-o", str(root / "probe")], capture_output=True, text=True)
        if compile_result.returncode:
            errors.append(f"{name} compile failed:\n{compile_result.stderr}")
            return
        result = subprocess.run([str(root / "probe")], capture_output=True, text=True)
        if expected_success and result.returncode:
            errors.append(f"behavior failed:\n{result.stdout}{result.stderr}")
        if not expected_success:
            expected = {
                "missing_on_data_release": "incomplete headers must release the recursive lock",
                "missing_send_release": "send build failure must release the recursive lock",
                "disabled_build_short_write_check": "partial request build must report low RAM, abort, and release the lock",
                "disabled_limit": "normal response limit must abort the client and preserve its negative code",
                "disabled_short_write_check": "short chunk transfer must not be treated as success",
            }[name]
            if result.returncode == 0 or "FAIL: " + expected not in result.stdout + result.stderr:
                errors.append(f"mutation {name} missed its assertion: {result.stdout}{result.stderr}")


if not errors:
    run_variant("current", HARNESS, True)
    run_variant("missing_on_data_release", HARNESS.replace("if( ! _collectHeaders()){\n            _release;", "if( ! _collectHeaders()){\n            /* mutated */"), False)
    run_variant("missing_send_release", HARNESS.replace("if( ! _buildRequest()){\n        _release;", "if( ! _buildRequest()){\n        /* mutated */"), False)
    run_variant("disabled_build_short_write_check", HARNESS.replace("if(_request->available() != expected){", "if(false && _request->available() != expected){"), False)
    run_variant("disabled_limit", HARNESS.replace("if(buffered > _maxResponseBufferBytes || len > _maxResponseBufferBytes - buffered){", "if(false && (buffered > _maxResponseBufferBytes || len > _maxResponseBufferBytes - buffered)){"), False)
    run_variant("disabled_short_write_check", HARNESS.replace("if(copied != expected){", "if(false && copied != expected){"), False)

if errors:
    print("HTTP request memory smoke failed:")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("HTTP request memory smoke passed")
