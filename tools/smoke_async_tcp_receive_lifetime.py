#!/usr/bin/env python3
"""ASan regression check for AsyncTCP receive-callback object lifetime."""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
TCP_SOURCE = ROOT / "libraries/Async_TCP/src/AsyncTCP.cpp"
WEB_SOURCE = ROOT / "libraries/ESP_Async_WebServer/src/WebRequest.cpp"
WEB_HEADER = ROOT / "libraries/ESP_Async_WebServer/src/ESPAsyncWebServer.h"
TCP_HEADER = ROOT / "libraries/Async_TCP/src/AsyncTCP.h"

HARNESS = r'''
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <new>
#include <string>
#include <functional>

struct tcp_pcb {};
struct lwip_tcp_event_packet_t {};
struct pbuf {
  pbuf *next;
  void *payload;
  uint16_t len;
};
static size_t livePbufs = 0;
static size_t ackedPbufs = 0;
static size_t closeCalls = 0;
static void pbuf_free(pbuf *value) {
  if (!value) return;
  if (value->payload == reinterpret_cast<void *>(static_cast<uintptr_t>(0xDEAD))) std::abort();
  pbuf *next = value->next;
  value->payload = reinterpret_cast<void *>(static_cast<uintptr_t>(0xDEAD));
  if (livePbufs == 0) std::abort();
  livePbufs--;
  delete value;
  pbuf_free(next);
}
static void _tcp_recved(tcp_pcb **pcb, uint16_t len) {
  (void)pcb;
  (void)len;
  ackedPbufs++;
}
static uint32_t millis() { return 1; }

constexpr int ERR_OK = 0;
constexpr int ERR_ABRT = -13;
constexpr int ERR_CONN = -11;
#define async_tcp_log_elapsed(name, expression) (expression)
#define async_tcp_log_d(...) ((void)0)
#define async_ws_log_d(...) ((void)0)

class AsyncClient;
class AsyncWebServer {};
class AsyncWebServerRequest;
using DataCallback = void (*)(void *, AsyncClient *, void *, size_t);
using PacketCallback = void (*)(void *, AsyncClient *, pbuf *);
using DisconnectCallback = void (*)(void *, AsyncClient *);

class AsyncClient {
 public:
  tcp_pcb *_pcb = new tcp_pcb;
  bool _ack_pcb = true;
  uint32_t _rx_ack_len = 0;
  uint32_t _rx_last_packet = 0;
  void *_recv_cb_arg = nullptr;
  DataCallback _recv_cb = nullptr;
  void *_pb_cb_arg = nullptr;
  PacketCallback _pb_cb = nullptr;
  void *_discard_cb_arg = nullptr;
  DisconnectCallback _discard_cb = nullptr;
  void *_error_cb_arg = nullptr;
  void (*_error_cb)(void *, AsyncClient *, int8_t) = nullptr;
  lwip_tcp_event_packet_t *_error_event = nullptr;
  @RECV_ALIVE_FIELD@
  void *_async_queue_mutex = nullptr;

  ~AsyncClient();
  int8_t _recv(tcp_pcb *, pbuf *, int8_t);
  int8_t abort();
  int8_t _close();
  void _error(int8_t);
  void ackLater() { _ack_pcb = false; }
  void close() { _close(); }
  void onDisconnect(DisconnectCallback callback, void *arg = nullptr) {
    _discard_cb = callback;
    _discard_cb_arg = arg;
  }
};

static void _remove_events_for_client(AsyncClient *) {}
static int8_t _tcp_abort(tcp_pcb **pcb, AsyncClient *) {
  if (!pcb || !*pcb) return ERR_CONN;
  delete *pcb;
  *pcb = nullptr;
  return ERR_ABRT;
}
static int8_t _tcp_close(tcp_pcb **pcb, AsyncClient *) {
  if (pcb && *pcb) {
    delete *pcb;
    *pcb = nullptr;
  }
  return ERR_OK;
}

struct TestFile {
  explicit operator bool() const { return false; }
  void close() {}
};
struct TestResponse {};

class AsyncWebServerRequest {
 public:
  AsyncClient *_client;
  AsyncWebServer *_server;
  TestResponse *_response = nullptr;
  void *_tempObject = nullptr;
  void *_itemBuffer = nullptr;
  TestFile _tempFile;
  std::function<void()> _onDisconnectfn;
  bool _sent = false;
  bool _paused = false;
  int _parseState = 0;
  std::shared_ptr<AsyncWebServerRequest> _this;
  AsyncWebServerRequest(AsyncWebServer *server, AsyncClient *client) : _client(client), _server(server) {
    client->_recv_cb_arg = this;
    client->_recv_cb = [](void *request, AsyncClient *, void *data, size_t len) {
      static_cast<AsyncWebServerRequest *>(request)->_onData(data, len);
    };
  }
  ~AsyncWebServerRequest();
  void _onDisconnect();
  void _onData(void *, size_t);
  void abort();
  AsyncClient *client() { return _client; }
};

static void on_request_disconnect(void *arg, AsyncClient *) {
  static_cast<AsyncWebServerRequest *>(arg)->_onDisconnect();
}

constexpr int PARSE_REQ_START = 0;
constexpr int PARSE_REQ_FAIL = 4;

@TCP_METHODS@
@WEB_METHODS@

static std::shared_ptr<AsyncWebServerRequest> make_request(AsyncClient *client) {
  AsyncWebServer *server = nullptr;
  @FACTORY@
}

static pbuf *make_chain(size_t count) {
  pbuf *head = nullptr;
  pbuf **tail = &head;
  for (size_t index = 0; index < count; index++) {
    pbuf *item = new pbuf{nullptr, reinterpret_cast<void *>(static_cast<uintptr_t>(index + 1)), 1};
    livePbufs++;
    *tail = item;
    tail = &item->next;
  }
  return head;
}

static void on_ack_later(void *arg, AsyncClient *client, void *, size_t) {
  (void)arg;
  client->ackLater();
}

static void on_close(void *arg, AsyncClient *client, void *, size_t) {
  (void)arg;
  closeCalls++;
  client->close();
}

static void on_packet_delete(void *, AsyncClient *client, pbuf *value) {
  pbuf_free(value);
  delete client;
}

static void on_nested_receive(void *arg, AsyncClient *client, void *, size_t) {
  int &depth = *static_cast<int *>(arg);
  if (depth++ == 0) client->_recv(client->_pcb, make_chain(2), 0);
  else delete client;
}

static void on_nested_then_delete(void *arg, AsyncClient *client, void *, size_t) {
  int &depth = *static_cast<int *>(arg);
  if (depth++ == 0) {
    client->_recv(client->_pcb, make_chain(1), 0);
    delete client;
  }
}

static int run_case(size_t chainLength) {
  ackedPbufs = 0;
  livePbufs = 0;
  {
    AsyncClient *client = new AsyncClient;
    std::shared_ptr<AsyncWebServerRequest> owner = make_request(client);
    client->onDisconnect(on_request_disconnect, owner.get());
    owner.reset();
    uint8_t tlsByte = 0x16;
    pbuf *chain = make_chain(chainLength);
    chain->payload = &tlsByte;
    client->_recv(client->_pcb, chain, 0);
  }
  if (livePbufs != 0) return 1;
  ackedPbufs = 0;

  {
    AsyncClient *client = new AsyncClient;
    client->_recv_cb = on_ack_later;
    pbuf *chain = make_chain(chainLength);
    client->_recv(client->_pcb, chain, 0);
    if (client->_rx_ack_len != chainLength || ackedPbufs != 0 || livePbufs != 0) return 2;
    if (client->_recv_alive != nullptr) return 6;
    delete client;
  }

  {
    AsyncClient *client = new AsyncClient;
    client->_pb_cb = on_packet_delete;
    pbuf *chain = make_chain(chainLength);
    client->_recv(client->_pcb, chain, 0);
    if (livePbufs != 0) return 3;
  }

  {
    AsyncClient *client = new AsyncClient;
    std::shared_ptr<AsyncWebServerRequest> owner = make_request(client);
    client->onDisconnect(on_request_disconnect, owner.get());
    client->_recv_cb = on_close;
    closeCalls = 0;
    pbuf *chain = make_chain(chainLength);
    client->_recv(client->_pcb, chain, 0);
    if (livePbufs != 0 || closeCalls != 1) return 4;
    owner.reset();
  }
  {
    int depth = 0;
    AsyncClient *client = new AsyncClient;
    client->_recv_cb = on_nested_receive;
    client->_recv_cb_arg = &depth;
    client->_recv(client->_pcb, make_chain(chainLength), 0);
    if (livePbufs != 0 || depth != 2) return 7;
  }
  {
    ackedPbufs = 0;
    AsyncClient *client = new AsyncClient;
    client->_recv(client->_pcb, make_chain(chainLength), 0);
    if (ackedPbufs != chainLength || livePbufs != 0 || client->_recv_alive != nullptr) return 8;
    delete client;
  }
  {
    int depth = 0;
    AsyncClient *client = new AsyncClient;
    client->_recv_cb = on_nested_then_delete;
    client->_recv_cb_arg = &depth;
    client->_recv(client->_pcb, make_chain(chainLength), 0);
    if (livePbufs != 0 || depth != 2) return 9;
  }
  return livePbufs == 0 ? 0 : 5;
}

int main() {
  const int first = run_case(1);
  const int second = run_case(3);
  if (first || second) {
    std::cerr << "FAIL: receive ownership/ACK cases (pbuf chains 1 and 3): " << first << "," << second << '\n';
    return 1;
  }
  std::cout << "async tcp receive lifetime checks passed\n";
  return 0;
}
'''


def build_harness(mutate=False):
    tcp = TCP_SOURCE.read_text(encoding="utf-8")
    web = WEB_SOURCE.read_text(encoding="utf-8")
    header = TCP_HEADER.read_text(encoding="utf-8")
    alive_field = re.search(r"bool\s*\*\s*_recv_alive\s*\{nullptr\}\s*;", header)
    if not alive_field:
        raise ValueError("AsyncClient header has no _recv_alive lifetime field")
    tcp_methods = []
    for signature in (
        "int8_t AsyncClient::_recv(tcp_pcb *pcb, pbuf *pb, int8_t err)",
        "int8_t AsyncClient::abort()",
        "int8_t AsyncClient::_close()",
        "void AsyncClient::_error(int8_t err)",
        "AsyncClient::~AsyncClient()",
    ):
        body = extract_function_body(tcp, signature)
        if mutate and signature == "AsyncClient::~AsyncClient()":
            body = body.replace("*_recv_alive = false;", "*_recv_alive = true;")
        tcp_methods.append(signature + " {" + body + "}\n")
    web_methods = []
    for signature in (
        "AsyncWebServerRequest::~AsyncWebServerRequest()",
        "void AsyncWebServerRequest::_onDisconnect()",
        "void AsyncWebServerRequest::abort()",
    ):
        web_methods.append(signature + " {" + extract_function_body(web, signature) + "}\n")
    on_data = extract_function_body(web, "void AsyncWebServerRequest::_onData(")
    on_data = on_data[:on_data.index("  size_t i = 0;")]
    web_methods.append("void AsyncWebServerRequest::_onData(void *buf, size_t len) {" + on_data + "}\n")
    factory = extract_function_body(
        WEB_HEADER.read_text(encoding="utf-8"),
        "static std::shared_ptr<AsyncWebServerRequest> create("
    )
    return HARNESS.replace("@TCP_METHODS@", "\n".join(tcp_methods)) \
        .replace("@RECV_ALIVE_FIELD@", alive_field.group(0)) \
        .replace("@WEB_METHODS@", "\n".join(web_methods)) \
        .replace("@FACTORY@", factory)


def compile_and_run(source_text, temp):
    source = temp / "receive_lifetime.cpp"
    binary = temp / "receive_lifetime"
    source.write_text(source_text, encoding="utf-8")
    result = subprocess.run(
        ["g++", "-std=c++17", "-Wall", "-Wextra", "-fsanitize=address", "-fno-omit-frame-pointer", str(source), "-o", str(binary)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return result
    return subprocess.run([str(binary)], capture_output=True, text=True, check=False)


def main():
    try:
        normal = build_harness()
        mutation = build_harness(mutate=True)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-async-receive-") as directory:
        temp = Path(directory)
        good = compile_and_run(normal, temp)
        if good.returncode != 0:
            sys.stderr.write(good.stdout + good.stderr)
            return 1
        bad = compile_and_run(mutation, temp)
        if bad.returncode == 0 or "heap-use-after-free" not in bad.stderr:
            sys.stderr.write(bad.stdout + bad.stderr)
            print("FAIL: lifetime mutation survived", file=sys.stderr)
            return 1
    print("async tcp receive lifetime checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
