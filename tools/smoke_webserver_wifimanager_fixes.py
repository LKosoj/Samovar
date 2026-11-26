#!/usr/bin/env python3
"""ASan/UBSan regression tests for ESP_Async_WebServer and ESPAsyncWiFiManager fixes."""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
)

ROOT = Path(__file__).resolve().parents[1]
WEB_RESPONSES = ROOT / "libraries/ESP_Async_WebServer/src/WebResponses.cpp"
WEB_REQUEST = ROOT / "libraries/ESP_Async_WebServer/src/WebRequest.cpp"
WFM_HEADER = ROOT / "libraries/ESPAsyncWiFiManager/src/ESPAsyncWiFiManager.h"
WFM_CPP = ROOT / "libraries/ESPAsyncWiFiManager/src/ESPAsyncWiFiManager.cpp"

HARNESS = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <vector>

// Minimal Arduino-like String
class String {
 public:
  std::string s;
  String() = default;
  String(const char *p) : s(p ? p : "") {}
  String(const std::string &v) : s(v) {}
  String(unsigned int v) : s(std::to_string(v)) {}
  String(int v) : s(std::to_string(v)) {}
  const char *c_str() const { return s.c_str(); }
  size_t length() const { return s.size(); }
  bool startsWith(const String &prefix) const {
    return s.size() >= prefix.s.size() && s.compare(0, prefix.s.size(), prefix.s) == 0;
  }
  bool operator==(const String &other) const { return s == other.s; }
  bool operator==(const char *other) const { return s == (other ? other : ""); }
  String &operator+=(const String &other) {
    s += other.s;
    return *this;
  }
  String &operator+=(const char *other) {
    if (other) s += other;
    return *this;
  }
  String &operator+=(unsigned int v) {
    s += std::to_string(v);
    return *this;
  }
  String operator+(const String &other) const { return String(s + other.s); }
  void replace(const char *from, const String &to) {
    if (!from || !*from) return;
    std::string f(from);
    size_t pos = 0;
    while ((pos = s.find(f, pos)) != std::string::npos) {
      s.replace(pos, f.size(), to.s);
      pos += to.s.size();
    }
  }
  void replace(const char *from, const char *to) {
    replace(from, String(to ? to : ""));
  }
};

static inline String operator+(const char *lhs, const String &rhs) {
  return String(std::string(lhs ? lhs : "") + rhs.s);
}

#define F(x) (x)
#define FPSTR(x) (x)
#define PROGMEM
#define boolean bool
#define WIFI_AUTH_OPEN 0
#define WIFI_SCAN_FAILED (-2)
#define WIFI_SCAN_RUNNING (-1)
#define ASYNCWEBSERVER_USE_CHUNK_INFLIGHT 1
#define ASYNC_RESPONCE_BUFF_SIZE 1024
#define CONFIG_LWIP_TCP_WND_DEFAULT 5744
#define CONFIG_LWIP_TCP_MSS 1436
#define RESPONSE_TRY_AGAIN 0xFFFFFFFFUL

// ============================================================
// Part 1: WebResponses::write_send_buffs
// ============================================================
enum WebResponseState {
  RESPONSE_SETUP = 0,
  RESPONSE_HEADERS,
  RESPONSE_CONTENT,
  RESPONSE_WAIT_ACK,
  RESPONSE_END,
  RESPONSE_FAILED
};

struct StubClient {
  size_t nextAddResult = 0;
  bool forceAddZero = false;
  size_t spaceVal = 2048;
  bool sendOk = true;
  bool closed = false;
  int sendCalls = 0;
  int closeCalls = 0;
  bool canSendVal = true;
  std::function<void()> onCloseHook;

  size_t add(const char *, size_t len) {
    if (forceAddZero) return 0;
    if (nextAddResult > 0) {
      size_t r = std::min(len, nextAddResult);
      return r;
    }
    return len;
  }
  size_t space() const { return spaceVal; }
  bool send() {
    ++sendCalls;
    return sendOk;
  }
  void close() {
    closed = true;
    ++closeCalls;
    if (onCloseHook) onCloseHook();
  }
  bool canSend() const { return canSendVal; }
};

struct WebRespRequestStub {
  StubClient *c;
  StubClient *client() { return c; }
};

class AsyncAbstractResponse {
 public:
  WebResponseState _state = RESPONSE_HEADERS;
  size_t _in_flight = 0;
  size_t _in_flight_credit = 1;
  bool _chunked = false;
  bool _sendContentLength = true;
  size_t _sentLength = 0;
  size_t _contentLength = 0;
  size_t _ackedLength = 0;
  size_t _writtenLength = 0;
  size_t _writtenHeadersLength = 0;
  String _assembled_headers;
  std::unique_ptr<std::array<uint8_t, ASYNC_RESPONCE_BUFF_SIZE>> _send_buffer;
  size_t _send_buffer_len = 0;
  size_t _send_buffer_offset = 0;
  bool sourceValid = true;
  size_t fillResult = 0;

  bool _sourceValid() const { return sourceValid; }
  size_t _fillBufferAndProcessTemplates(uint8_t *data, size_t maxLen) {
    if (fillResult == RESPONSE_TRY_AGAIN) return RESPONSE_TRY_AGAIN;
    size_t n = std::min(maxLen, fillResult);
    if (n > 0) std::memset(data, 'A', n);
    fillResult -= n;
    return n;
  }

  size_t write_send_buffs(WebRespRequestStub *request, size_t len, uint32_t time) {
@WRITE_SEND_BUFFS_BODY@
  }
};

static void test_write_send_buffs() {
  // 1) Partial header send with pcb_written == 0 must not decrement _in_flight_credit or underflow
  {
    StubClient client;
    client.forceAddZero = true;
    WebRespRequestStub req{&client};
    AsyncAbstractResponse resp;
    resp._state = RESPONSE_HEADERS;
    resp._assembled_headers = "HTTP/1.1 200 OK\r\n\r\n";
    resp._in_flight = 0;
    resp._in_flight_credit = 0;
    resp._chunked = false;
    resp._sendContentLength = true;
    resp._sentLength = 0;

    size_t written = resp.write_send_buffs(&req, 0, 0);
    assert(written == 0);
    assert(resp._in_flight == 0);
    assert(resp._in_flight_credit == 0);
  }

  // 2) Partial header send with pcb_written > 0 decrements credit safely without underflow
  {
    StubClient client;
    client.nextAddResult = 5;
    WebRespRequestStub req{&client};
    AsyncAbstractResponse resp;
    resp._state = RESPONSE_HEADERS;
    resp._assembled_headers = "HTTP/1.1 200 OK\r\n\r\n";
    resp._in_flight = 0;
    resp._in_flight_credit = 0;

    size_t written = resp.write_send_buffs(&req, 0, 0);
    assert(written == 5);
    assert(resp._in_flight == 5);
    assert(resp._in_flight_credit == 0);

    resp._in_flight_credit = 2;
    written = resp.write_send_buffs(&req, 0, 0);
    assert(written == 5);
    assert(resp._in_flight == 10);
    assert(resp._in_flight_credit == 1);
  }

  // 3) Content send with payloadlen == 0 (RESPONSE_TRY_AGAIN) must not decrement credit or underflow
  {
    StubClient client;
    WebRespRequestStub req{&client};
    AsyncAbstractResponse resp;
    resp._state = RESPONSE_CONTENT;
    resp._in_flight = 10;
    resp._in_flight_credit = 0;
    resp.fillResult = RESPONSE_TRY_AGAIN;

    size_t written = resp.write_send_buffs(&req, 0, 0);
    assert(written == 0);
    assert(resp._in_flight == 10);
    assert(resp._in_flight_credit == 0);

    resp._in_flight_credit = 2;
    written = resp.write_send_buffs(&req, 0, 0);
    assert(written == 0);
    assert(resp._in_flight == 10);
    assert(resp._in_flight_credit == 2);
  }

  // 4) Content send with payloadlen > 0 updates _in_flight and decrements credit safely
  {
    StubClient client;
    WebRespRequestStub req{&client};
    AsyncAbstractResponse resp;
    resp._state = RESPONSE_CONTENT;
    resp._contentLength = 100;
    resp._in_flight = 0;
    resp._in_flight_credit = 0;
    resp.fillResult = 100;

    size_t written = resp.write_send_buffs(&req, 0, 0);
    assert(written == 100);
    assert(resp._in_flight == 100);
    assert(resp._in_flight_credit == 0);

    resp._state = RESPONSE_CONTENT;
    resp._sentLength = 0;
    resp._in_flight_credit = 3;
    resp.fillResult = 50;
    written = resp.write_send_buffs(&req, 0, 0);
    assert(written == 50);
    assert(resp._in_flight == 150);
    assert(resp._in_flight_credit == 2);
  }
}

// ============================================================
// Part 2: WebRequest::_onPoll, send, text/plain body check
// ============================================================
static int g_responseDestructions = 0;

class AsyncWebServerRequest;

class AsyncWebServerResponse {
 public:
  bool finished = false;
  bool finishOnAck = false;
  int ackCalls = 0;
  int id = 0;

  explicit AsyncWebServerResponse(int i = 0) : id(i) {}
  virtual ~AsyncWebServerResponse() { ++g_responseDestructions; }

  bool _finished() const { return finished; }
  size_t _ack(AsyncWebServerRequest *, size_t, uint32_t) {
    ++ackCalls;
    if (finishOnAck) finished = true;
    return 0;
  }
};

static const String T_app_xform_urlencoded("application/x-www-form-urlencoded");
static const String T_text_plain("text/plain");

static inline bool isParamChar(char c) {
  return std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-';
}

class AsyncWebServerRequest {
 public:
  std::shared_ptr<AsyncWebServerRequest> _this;
  AsyncWebServerResponse *_response = nullptr;
  StubClient *_client = nullptr;
  bool _sent = false;
  bool _paused = false;
  int sendInternalCalls = 0;
  String _contentType;
  bool _isPlainPost = false;

  ~AsyncWebServerRequest() {
    delete _response;
    _response = nullptr;
  }

  void _send() {
    ++sendInternalCalls;
    _sent = true;
  }

  void _onPoll() {
@ON_POLL_BODY@
  }

  void send(AsyncWebServerResponse *response) {
@SEND_BODY@
  }

  void checkPlainPost(void *buf, size_t len) {
    _isPlainPost = false;
@PLAIN_POST_BODY@
  }
};

static void test_web_request() {
  // 1) _onPoll: ack finishes response -> closes client; self stays alive even if close drops _this
  {
    StubClient client;
    auto req = new AsyncWebServerRequest();
    req->_this = std::shared_ptr<AsyncWebServerRequest>(req);
    req->_client = &client;
    req->_response = new AsyncWebServerResponse(1);
    req->_response->finishOnAck = true;

    std::weak_ptr<AsyncWebServerRequest> weak = req->_this;
    client.onCloseHook = [req]() {
      std::shared_ptr<AsyncWebServerRequest> keep = std::move(req->_this);
    };

    req->_onPoll();
    assert(client.closeCalls == 1);
    assert(weak.expired());
  }

  // 2) _onPoll: already finished -> closes client without calling _ack
  {
    StubClient client;
    auto req = new AsyncWebServerRequest();
    req->_this = std::shared_ptr<AsyncWebServerRequest>(req);
    req->_client = &client;
    req->_response = new AsyncWebServerResponse(2);
    req->_response->finished = true;

    req->_onPoll();
    assert(req->_response->ackCalls == 0);
    assert(client.closeCalls == 1);
    req->_this.reset();
  }

  // 3) send(): when _sent == true, deletes different response; does not double-free same response
  {
    g_responseDestructions = 0;
    AsyncWebServerRequest req;
    auto *r1 = new AsyncWebServerResponse(10);
    auto *r2 = new AsyncWebServerResponse(20);
    req._response = r1;
    req._sent = true;

    req.send(r2);
    assert(g_responseDestructions == 1);
    assert(req._response == r1);

    req.send(r1);
    assert(g_responseDestructions == 1);
    assert(req._response == r1);
  }
  assert(g_responseDestructions == 2);

  // 4) send(): when _sent == false, replaces old response; passing same pointer does not UAF
  {
    g_responseDestructions = 0;
    AsyncWebServerRequest req;
    auto *r1 = new AsyncWebServerResponse(30);
    auto *r2 = new AsyncWebServerResponse(40);
    req.send(r1);
    assert(req._response == r1);
    assert(g_responseDestructions == 0);

    req.send(r1);
    assert(req._response == r1);
    assert(g_responseDestructions == 0);

    req.send(r2);
    assert(req._response == r2);
    assert(g_responseDestructions == 1);
  }
  assert(g_responseDestructions == 2);

  // 5) text/plain OOB read and len == 0 check under ASan
  {
    AsyncWebServerRequest req;
    req._contentType = T_text_plain;

    // Exact-size heap allocation with no '=': old code read buf[len]!
    char *noEq = new char[3];
    std::memcpy(noEq, "abc", 3);
    req.checkPlainPost(noEq, 3);
    assert(!req._isPlainPost);
    delete[] noEq;

    // Exact-size heap allocation ending with '='
    char *withEq = new char[4];
    std::memcpy(withEq, "abc=", 4);
    req.checkPlainPost(withEq, 4);
    assert(req._isPlainPost);
    delete[] withEq;

    // Exact-size heap allocation with value after '='
    char *kv = new char[5];
    std::memcpy(kv, "k1=v2", 5);
    req.checkPlainPost(kv, 5);
    assert(req._isPlainPost);
    delete[] kv;

    // Non-param first char
    char *bad = new char[4];
    std::memcpy(bad, "!a=1", 4);
    req.checkPlainPost(bad, 4);
    assert(!req._isPlainPost);
    delete[] bad;

    // len == 0 with nullptr must not dereference buf[0]
    req.checkPlainPost(nullptr, 0);
    assert(!req._isPlainPost);
  }
}

// ============================================================
// Part 3: ESPAsyncWiFiManager
// ============================================================
typedef int16_t wifi_ssid_count_t;
static const char HTTP_ITEM[] = "<div><a href='#p' onclick='c(this)'>{v}</a>&nbsp;<span class='q {i}'>{r}%</span></div>";
static const char WFM_HTTP_HEAD[] = "<head><title>{v}</title>";
static const char HTTP_SCRIPT[] = "<script></script>";
static const char HTTP_STYLE[] = "<style></style>";
static const char HTTP_HEAD_END[] = "</head><body>";
static const char HTTP_FORM_START[] = "<form>";
static const char HTTP_FORM_PARAM[] = "<input id='{i}' name='{n}' length={l} placeholder='{p}' value='{v}' {c}>";
static const char HTTP_FORM_END[] = "</form>";
static const char HTTP_SCAN_LINK[] = "<a href='/wifi'>Scan</a>";
static const char HTTP_END[] = "</body>";

class AsyncWiFiManagerParameter {
 public:
  const char *_id = nullptr;
  const char *_placeholder = nullptr;
  char *_value = nullptr;
  unsigned int _length = 0;
  const char *_customHTML = nullptr;

  AsyncWiFiManagerParameter(const char *id, const char *placeholder, const char *defaultValue, unsigned int length, const char *custom = "") {
    init(id, placeholder, defaultValue, length, custom);
  }
  ~AsyncWiFiManagerParameter() {
@PARAM_DTOR_BODY@
  }
  AsyncWiFiManagerParameter(const AsyncWiFiManagerParameter &) = delete;
  AsyncWiFiManagerParameter &operator=(const AsyncWiFiManagerParameter &) = delete;

  void init(const char *id, const char *placeholder, const char *defaultValue, unsigned int length, const char *custom) {
@PARAM_INIT_BODY@
  }
  const char *getID() { return _id; }
  const char *getValue() { return _value; }
  const char *getPlaceholder() { return _placeholder; }
  unsigned int getValueLength() { return _length; }
  const char *getCustomHTML() { return _customHTML; }
};

class WiFiResult {
 public:
  bool duplicate = false;
  String SSID;
  uint8_t encryptionType = 0;
  int32_t RSSI = -100;
  uint8_t *BSSID = nullptr;
  int32_t channel = 1;
  bool isHidden = false;
};

struct StubWiFi {
  std::atomic<int> generation{0};
  void getNetworkInfo(wifi_ssid_count_t i, String &ssid, uint8_t &enc, int32_t &rssi, uint8_t *&bssid, int32_t &ch) {
    int g = generation.load();
    // Include duplicate SSID to exercise deduplication and sorting
    if (i == 1) {
      ssid = String("Net_") + String(g) + String("_0");
      rssi = -80;
    } else {
      ssid = String("Net_") + String(g) + String("_") + String(static_cast<int>(i));
      rssi = -90 + static_cast<int>(i) * 5;
    }
    enc = (i % 2 == 0) ? WIFI_AUTH_OPEN : 3;
    bssid = nullptr;
    ch = 6;
  }
};
static StubWiFi WiFi;

struct WfmRequestStub {
  int lastCode = 0;
  String lastPage;
  void send(int code, const char *, const String &page) {
    lastCode = code;
    lastPage = page;
  }
};

struct StubIP {
  explicit operator bool() const { return false; }
  String toString() const { return "0.0.0.0"; }
};

struct StubAsyncWebServer {};
struct StubDNSServer {};

class AsyncWiFiManager {
 public:
  StubAsyncWebServer *server = nullptr;
  StubDNSServer *dnsServer = nullptr;
  WiFiResult *wifiSSIDs;
  wifi_ssid_count_t wifiSSIDCount;
  boolean wifiSSIDscan;
  boolean _modeless;
  boolean shouldscan;
  unsigned long scannow = 0;
  unsigned int _minimumQuality = 0;
  boolean _removeDuplicateAPs = true;
  const char *_customHeadElement = "";
  unsigned int _paramsCount = 0;
  AsyncWiFiManagerParameter *_params[10] = {};
  StubIP _sta_static_ip, _sta_static_gw, _sta_static_sn, _sta_static_dns1, _sta_static_dns2;
  std::mutex _wifiSSIDsMutex;

  AsyncWiFiManager(StubAsyncWebServer *server, StubDNSServer *dns) : server(server), dnsServer(dns) {
@WFM_CTOR_BODY@
  }
  ~AsyncWiFiManager() {
@WFM_DTOR_BODY@
  }
  AsyncWiFiManager(const AsyncWiFiManager &) = delete;
  AsyncWiFiManager &operator=(const AsyncWiFiManager &) = delete;

  template <typename T>
  void DEBUG_WM(T) {}

  unsigned int getRSSIasQuality(int RSSI) {
    if (RSSI <= -100) return 0;
    if (RSSI >= -50) return 100;
    return static_cast<unsigned int>(2 * (RSSI + 100));
  }

  String networkListAsString() {
@NETWORK_LIST_BODY@
  }

  void copySSIDInfo(wifi_ssid_count_t n) {
@COPY_SSID_BODY@
  }

  void handleWifi(WfmRequestStub *request, boolean scan) {
@HANDLE_WIFI_BODY@
  }
};

static void test_wifimanager() {
  // 1) AsyncWiFiManagerParameter NUL termination when defaultValue >= length
  {
    AsyncWiFiManagerParameter param("id", "ph", "ABCDEFGH", 4);
    assert(param.getValue()[4] == '\0');
    assert(std::strcmp(param.getValue(), "ABCD") == 0);
  }

  // 2) Constructor initializes wifiSSIDCount == 0 and wifiSSIDs == nullptr
  {
    StubAsyncWebServer srv;
    StubDNSServer dns;
    AsyncWiFiManager wm(&srv, &dns);
    assert(wm.wifiSSIDs == nullptr);
    assert(wm.wifiSSIDCount == 0);

    // handleWifi with no networks
    WfmRequestStub req;
    wm.handleWifi(&req, true);
    assert(req.lastCode == 200);
    assert(req.lastPage.s.find("No networks found") != std::string::npos);

    // Populate networks and check handleWifi + deduplication
    wm.copySSIDInfo(4);
    assert(wm.wifiSSIDCount == 4);
    wm.handleWifi(&req, true);
    assert(req.lastCode == 200);
    assert(req.lastPage.s.find("Net_0_0") != std::string::npos);
    assert(req.lastPage.s.find("No networks found") == std::string::npos);

    // Concurrent writer (copySSIDInfo) and reader (networkListAsString / handleWifi)
    std::atomic<bool> stop{false};
    std::thread writer([&]() {
      for (int iter = 0; iter < 400; ++iter) {
        WiFi.generation.store(iter);
        wm.copySSIDInfo(static_cast<wifi_ssid_count_t>((iter % 5) + 1));
      }
      stop.store(true);
    });
    std::thread reader([&]() {
      WfmRequestStub r;
      while (!stop.load()) {
        String list = wm.networkListAsString();
        (void)list;
        wm.handleWifi(&r, true);
      }
    });
    writer.join();
    reader.join();
  }
}

int main() {
  test_write_send_buffs();
  test_web_request();
  test_wifimanager();
  std::cout << "webserver_wifimanager_fixes OK\n";
  return 0;
}
'''


def check_structural_contracts(wfm_header: str, wfm_cpp: str) -> list[str]:
    errors: list[str] = []

    # Deleted copy constructors & assignments and destructors in header
    required_header = [
        "~AsyncWiFiManagerParameter();",
        "AsyncWiFiManagerParameter(const AsyncWiFiManagerParameter &) = delete;",
        "AsyncWiFiManagerParameter &operator=(const AsyncWiFiManagerParameter &) = delete;",
        "~AsyncWiFiManager();",
        "AsyncWiFiManager(const AsyncWiFiManager &) = delete;",
        "AsyncWiFiManager &operator=(const AsyncWiFiManager &) = delete;",
        "std::mutex _wifiSSIDsMutex;",
    ]
    for token in required_header:
        if token not in wfm_header:
            errors.append(f"ESPAsyncWiFiManager.h missing: {token}")

    setup_portal = extract_function_body(wfm_cpp, "void AsyncWiFiManager::setupConfigPortal()")
    require_ordered_tokens(
        "setupConfigPortal",
        setup_portal,
        ["server->end();", "server->reset();"],
        errors,
    )

    start_portal = extract_function_body(wfm_cpp, "boolean AsyncWiFiManager::startConfigPortal(")
    require_ordered_tokens(
        "startConfigPortal exit",
        start_portal,
        ["dnsServer->stop();", "server->end();", "delay(100);", "server->reset();"],
        errors,
    )

    handle_wifi = extract_function_body(wfm_cpp, "void AsyncWiFiManager::handleWifi(")
    if "wifiSSIDCount == 0" in handle_wifi:
        errors.append("handleWifi still contains unsynchronized wifiSSIDCount == 0")

    return errors


def preprocess_esp32(source: str) -> str:
    """Keep #else branch of #if defined(ESP8266) and #ifdef USE_EADNS blocks for ESP32."""
    source = re.sub(
        r"#if defined\(ESP8266\).*?#else\s*\n(.*?)#endif",
        r"\1",
        source,
        flags=re.DOTALL,
    )
    source = re.sub(
        r"#ifdef USE_EADNS\s*\n.*?#else\s*\n(.*?)#endif",
        r"\1",
        source,
        flags=re.DOTALL,
    )
    return source


def main() -> int:
    web_responses = WEB_RESPONSES.read_text(encoding="utf-8")
    web_request = WEB_REQUEST.read_text(encoding="utf-8")
    wfm_header = WFM_HEADER.read_text(encoding="utf-8")
    wfm_cpp_raw = WFM_CPP.read_text(encoding="utf-8")
    wfm_cpp = preprocess_esp32(wfm_cpp_raw)

    errors = check_structural_contracts(wfm_header, wfm_cpp)
    if errors:
        print("FAIL structural checks:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    write_send_buffs_body = extract_function_body(
        web_responses, "size_t AsyncAbstractResponse::write_send_buffs("
    )
    on_poll_body = extract_function_body(
        web_request, "void AsyncWebServerRequest::_onPoll()"
    )
    send_body = extract_function_body(
        web_request, "void AsyncWebServerRequest::send(AsyncWebServerResponse *response)"
    )
    on_data_body = extract_function_body(
        web_request, "void AsyncWebServerRequest::_onData(void *buf, size_t len)"
    )
    plain_post_body, _ = extract_braced_block_after(on_data_body, "if (_parsedLength == 0)")

    param_dtor_body = extract_function_body(
        wfm_cpp, "AsyncWiFiManagerParameter::~AsyncWiFiManagerParameter()"
    )
    param_init_body = extract_function_body(
        wfm_cpp, "void AsyncWiFiManagerParameter::init("
    )
    # Extract the body of AsyncWiFiManager constructor after `#else`
    ctor_pos = wfm_cpp.find("AsyncWiFiManager::AsyncWiFiManager(AsyncWebServer *server,\n                                   DNSServer *dns)")
    if ctor_pos < 0:
        print("FAIL: AsyncWiFiManager constructor not found", file=sys.stderr)
        return 1
    wfm_ctor_body, _ = extract_braced_block_after(wfm_cpp, "DNSServer *dns) : server(server), dnsServer(dns)", ctor_pos)
    wfm_dtor_body = extract_function_body(
        wfm_cpp, "AsyncWiFiManager::~AsyncWiFiManager()"
    )
    network_list_body = extract_function_body(
        wfm_cpp, "String AsyncWiFiManager::networkListAsString()"
    )
    copy_ssid_body = extract_function_body(
        wfm_cpp, "void AsyncWiFiManager::copySSIDInfo(wifi_ssid_count_t n)"
    )
    handle_wifi_body = extract_function_body(
        wfm_cpp, "void AsyncWiFiManager::handleWifi("
    )

    source = (
        HARNESS
        .replace("@WRITE_SEND_BUFFS_BODY@", write_send_buffs_body)
        .replace("@ON_POLL_BODY@", on_poll_body)
        .replace("@SEND_BODY@", send_body)
        .replace("@PLAIN_POST_BODY@", plain_post_body)
        .replace("@PARAM_DTOR_BODY@", param_dtor_body)
        .replace("@PARAM_INIT_BODY@", param_init_body)
        .replace("@WFM_CTOR_BODY@", wfm_ctor_body)
        .replace("@WFM_DTOR_BODY@", wfm_dtor_body)
        .replace("@NETWORK_LIST_BODY@", network_list_body)
        .replace("@COPY_SSID_BODY@", copy_ssid_body)
        .replace("@HANDLE_WIFI_BODY@", handle_wifi_body)
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        cpp_path = Path(tmpdir) / "harness.cpp"
        bin_path = Path(tmpdir) / "harness"
        cpp_path.write_text(source, encoding="utf-8")

        compile_res = subprocess.run(
            [
                "g++",
                "-std=c++17",
                "-O1",
                "-g",
                "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer",
                "-pthread",
                str(cpp_path),
                "-o",
                str(bin_path),
            ],
            capture_output=True,
            text=True,
        )
        if compile_res.returncode != 0:
            print("FAIL compiling harness:", file=sys.stderr)
            print(compile_res.stderr, file=sys.stderr)
            return 1

        run_res = subprocess.run([str(bin_path)], capture_output=True, text=True)
        if run_res.returncode != 0:
            print("FAIL running harness:", file=sys.stderr)
            print(run_res.stdout, file=sys.stderr)
            print(run_res.stderr, file=sys.stderr)
            return 1
        print(run_res.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
