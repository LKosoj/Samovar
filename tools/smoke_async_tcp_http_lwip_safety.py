#!/usr/bin/env python3
"""Проверяет потокобезопасность lwIP в AsyncTCP и защиту ресурсов/мьютекса в asyncHTTPrequest."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
ASYNC_TCP_SRC = ROOT / "libraries/Async_TCP/src/AsyncTCP.cpp"
ASYNC_HTTP_SRC = ROOT / "libraries/asyncHTTPrequest/src/asyncHTTPrequest.cpp"


def extract_tcp_parts(source: str) -> dict[str, str]:
    signatures = (
        "static void _apply_nodelay_lwip(tcp_pcb *pcb, bool nodelay)",
        "static err_t _tcp_abort_api(struct tcpip_api_call_data *api_call_msg)",
        "static esp_err_t _tcp_abort(tcp_pcb **pcb, AsyncClient *client)",
        "static err_t _tcp_connect_api(struct tcpip_api_call_data *api_call_msg)",
        "static esp_err_t _tcp_connect(tcp_pcb **pcb, AsyncClient *client, uint8_t ip_type, ip_addr_t *addr, uint16_t port, tcp_connected_fn cb)",
        "static err_t _dns_gethostbyname_api(struct tcpip_api_call_data *api_call_msg)",
        "static err_t _dns_gethostbyname(const char *host, ip_addr_t *addr, dns_found_callback cb, void *arg)",
        "static err_t _tcp_server_begin_api(struct tcpip_api_call_data *api_call_msg)",
        "static esp_err_t _tcp_server_begin(tcp_pcb **pcb, uint8_t ip_type, ip_addr_t *addr, uint16_t port, uint8_t backlog, AsyncServer *server)",
        "static err_t _tcp_server_end_api(struct tcpip_api_call_data *api_call_msg)",
        "static esp_err_t _tcp_server_end(tcp_pcb **pcb)",
        "static err_t _tcp_set_nodelay_api(struct tcpip_api_call_data *api_call_msg)",
        "static esp_err_t _tcp_set_nodelay(tcp_pcb **pcb, bool nodelay)",
        "static err_t _tcp_get_nodelay_api(struct tcpip_api_call_data *api_call_msg)",
        "static bool _tcp_get_nodelay(tcp_pcb **pcb)",
        "static err_t _tcp_set_keepalive_api(struct tcpip_api_call_data *api_call_msg)",
        "static esp_err_t _tcp_set_keepalive(tcp_pcb **pcb, uint32_t ms, uint8_t cnt)",
        "static err_t _tcp_get_state_api(struct tcpip_api_call_data *api_call_msg)",
        "static uint8_t _tcp_get_state(tcp_pcb *const *pcb)",
        "static err_t _tcp_space_api(struct tcpip_api_call_data *api_call_msg)",
        "static size_t _tcp_space(tcp_pcb *const *pcb)",
        "static err_t _tcp_mss_api(struct tcpip_api_call_data *api_call_msg)",
        "static uint16_t _tcp_mss(tcp_pcb *const *pcb)",
        "static err_t _tcp_get_endpoints_api(struct tcpip_api_call_data *api_call_msg)",
        "static bool _tcp_get_endpoints(tcp_pcb *const *pcb, tcp_endpoints_t *out)",
        "bool AsyncClient::connect(ip_addr_t addr, uint16_t port)",
        "bool AsyncClient::connect(const char *host, uint16_t port)",
        "size_t AsyncClient::space() const",
        "bool AsyncClient::free()",
        "void AsyncClient::setNoDelay(bool nodelay) const",
        "bool AsyncClient::getNoDelay()",
        "void AsyncClient::setKeepAlive(uint32_t ms, uint8_t cnt)",
        "uint16_t AsyncClient::getMss() const",
        "uint32_t AsyncClient::getRemoteAddress() const",
        "uint16_t AsyncClient::getRemotePort() const",
        "uint32_t AsyncClient::getLocalAddress() const",
        "uint16_t AsyncClient::getLocalPort() const",
        "ip4_addr_t AsyncClient::getRemoteAddress4() const",
        "ip4_addr_t AsyncClient::getLocalAddress4() const",
        "uint8_t AsyncClient::state() const",
        "bool AsyncClient::connected() const",
        "bool AsyncClient::connecting() const",
        "bool AsyncClient::disconnecting() const",
        "bool AsyncClient::disconnected() const",
        "bool AsyncClient::freeable() const",
        "void AsyncServer::begin()",
        "void AsyncServer::end()",
        "int8_t AsyncTCP_detail::tcp_accept(void *arg, tcp_pcb *pcb, int8_t err)",
        "uint8_t AsyncServer::status() const",
    )
    return {sig: extract_function_body(source, sig, strip_comments=False) for sig in signatures}


def extract_http_parts(source: str) -> dict[str, str]:
    signatures = (
        "bool\tasyncHTTPrequest::open(const char* method, const char* URL)",
        "String\tasyncHTTPrequest::responseText()",
        "bool  asyncHTTPrequest::_connect()",
        "void  asyncHTTPrequest::_processChunks()",
        "void  asyncHTTPrequest::_onData(void* Vbuf, size_t len)",
    )
    parts = {sig: extract_function_body(source, sig, strip_comments=False) for sig in signatures}
    guard_start = source.find("struct ThreadLockGuard {")
    if guard_start < 0:
        raise ValueError("ThreadLockGuard not found in asyncHTTPrequest.cpp")
    guard_end = source.find("};", guard_start)
    if guard_end < 0:
        raise ValueError("ThreadLockGuard end not found in asyncHTTPrequest.cpp")
    parts["ThreadLockGuard"] = source[guard_start:guard_end + 2]
    return parts


TCP_HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iostream>
#include <new>

static int fail(const char *msg) {
  std::cerr << "FAIL: " << msg << "\n";
  std::exit(1);
}

static void check(bool cond, const char *msg) {
  if (!cond) fail(msg);
}

// --- lwIP / FreeRTOS mock ---
#define ERR_OK 0
#define ERR_MEM -1
#define ERR_ARG -16
#define ERR_ALREADY -10
#define ERR_CONN -11
#define ERR_ABRT -13
#define ERR_INPROGRESS -5
#define ESP_OK 0
#define IPADDR_TYPE_V4 0
#define IPADDR_TYPE_ANY 46
#define LWIP_IPV4 1
#define LWIP_IPV6 0
#define SOF_KEEPALIVE 0x08U
#define ESP_IDF_VERSION_MAJOR 5
#define async_tcp_log_e(...) ((void)0)
#define async_tcp_log_d(...) ((void)0)
#define async_tcp_log_elapsed(tag, expr) (expr)

enum tcp_state {
  CLOSED = 0,
  LISTEN = 1,
  SYN_SENT = 2,
  SYN_RCVD = 3,
  ESTABLISHED = 4,
  FIN_WAIT_1 = 5,
  FIN_WAIT_2 = 6,
  CLOSE_WAIT = 7,
  CLOSING = 8,
  LAST_ACK = 9,
  TIME_WAIT = 10
};

using err_t = int8_t;
using esp_err_t = int;

struct ip4_addr_t {
  uint32_t addr;
};
using ip_addr_t = ip4_addr_t;
static void ip4_addr_set_zero(ip4_addr_t *a) { a->addr = 0; }

struct tcp_pcb {
  uint8_t state = CLOSED;
  uint16_t snd_buf = 0;
  uint16_t mss = 0;
  ip_addr_t remote_ip{};
  ip_addr_t local_ip{};
  uint16_t remote_port = 0;
  uint16_t local_port = 0;
  uint8_t so_options = 0;
  uint32_t keep_idle = 0;
  uint32_t keep_intvl = 0;
  uint8_t keep_cnt = 0;
  bool nagle_disabled = false;
  void *arg = nullptr;
  void *accept_fn = nullptr;
  bool closed = false;
  bool aborted = false;
};

struct tcpip_api_call_data {};
using tcpip_api_call_fn = err_t (*)(struct tcpip_api_call_data *);
using tcp_connected_fn = err_t (*)(void *, tcp_pcb *, err_t);
using dns_found_callback = void (*)(const char *, const ip_addr_t *, void *);

class AsyncClient;
class AsyncServer;

static bool in_lwip_thread = false;
static int rpc_calls = 0;
static std::function<void()> before_rpc_hook;

static err_t tcpip_api_call(tcpip_api_call_fn fn, struct tcpip_api_call_data *call) {
  check(!in_lwip_thread, "self-deadlock: tcpip_api_call invoked on lwIP thread");
  ++rpc_calls;
  if (before_rpc_hook) {
    auto hook = before_rpc_hook;
    before_rpc_hook = nullptr;
    hook();
  }
  in_lwip_thread = true;
  err_t res = fn(call);
  in_lwip_thread = false;
  return res;
}

static bool fail_next_new_client = false;
static bool fail_next_new_event = false;
static int active_pcbs = 0;
static int abort_calls = 0;
static int close_calls = 0;
static int bind_callbacks_calls = 0;
static int reset_callbacks_calls = 0;
static int remove_events_calls = 0;
static size_t queued_events_to_remove = 0;

static err_t next_tcp_connect_err = ERR_OK;
static bool fail_tcp_new = false;
static err_t next_tcp_bind_err = ERR_OK;
static bool fail_tcp_listen = false;
static err_t next_tcp_close_err = ERR_OK;
static err_t next_dns_err = ERR_INPROGRESS;
static ip_addr_t next_dns_addr{};
static bool connect_saw_pcb_stored = false;
static int dns_calls = 0;
static uint16_t dns_seen_connect_port = 0;

static tcp_pcb *tcp_new_ip_type(uint8_t) {
  check(in_lwip_thread, "tcp_new_ip_type must run on lwIP thread");
  if (fail_tcp_new) return nullptr;
  ++active_pcbs;
  return new tcp_pcb();
}

static err_t tcp_connect(tcp_pcb *pcb, const ip_addr_t *, uint16_t, tcp_connected_fn);
static err_t tcp_bind(tcp_pcb *pcb, const ip_addr_t *, uint16_t) {
  check(in_lwip_thread, "tcp_bind must run on lwIP thread");
  return next_tcp_bind_err;
}
static tcp_pcb *tcp_listen_with_backlog(tcp_pcb *pcb, uint8_t) {
  check(in_lwip_thread, "tcp_listen_with_backlog must run on lwIP thread");
  if (fail_tcp_listen) return nullptr;
  pcb->state = LISTEN;
  return pcb;
}
static err_t tcp_close(tcp_pcb *pcb) {
  check(in_lwip_thread, "tcp_close must run on lwIP thread");
  ++close_calls;
  if (next_tcp_close_err != ERR_OK) return next_tcp_close_err;
  pcb->closed = true;
  --active_pcbs;
  delete pcb;
  return ERR_OK;
}
static void tcp_abort(tcp_pcb *pcb) {
  check(in_lwip_thread, "tcp_abort must run on lwIP thread");
  ++abort_calls;
  if (pcb) {
    pcb->aborted = true;
    --active_pcbs;
    delete pcb;
  }
}
static void tcp_arg(tcp_pcb *pcb, void *arg) {
  check(in_lwip_thread, "tcp_arg must run on lwIP thread");
  pcb->arg = arg;
}
static void tcp_accept(tcp_pcb *pcb, int8_t (*fn)(void *, tcp_pcb *, int8_t)) {
  check(in_lwip_thread, "tcp_accept must run on lwIP thread");
  pcb->accept_fn = reinterpret_cast<void *>(fn);
}
static void tcp_nagle_disable(tcp_pcb *pcb) {
  check(in_lwip_thread, "tcp_nagle_disable must run on lwIP thread");
  pcb->nagle_disabled = true;
}
static void tcp_nagle_enable(tcp_pcb *pcb) {
  check(in_lwip_thread, "tcp_nagle_enable must run on lwIP thread");
  pcb->nagle_disabled = false;
}
static bool tcp_nagle_disabled(tcp_pcb *pcb) {
  check(in_lwip_thread, "tcp_nagle_disabled must run on lwIP thread");
  return pcb->nagle_disabled;
}
static size_t tcp_sndbuf(tcp_pcb *pcb) {
  check(in_lwip_thread, "tcp_sndbuf must run on lwIP thread");
  return pcb->snd_buf;
}
static uint16_t tcp_mss(tcp_pcb *pcb) {
  check(in_lwip_thread, "tcp_mss must run on lwIP thread");
  return pcb->mss;
}

static bool _start_async_task() { return true; }
static err_t _tcp_connected(void *, tcp_pcb *, err_t) { return ERR_OK; }
static void _tcp_dns_found(const char *, ip_addr_t *, void *) {}

enum lwip_tcp_event_t { LWIP_TCP_ACCEPT = 1 };
struct lwip_tcp_event_packet_t {
  lwip_tcp_event_t event;
  AsyncClient *client;
  struct { AsyncServer *server; } accept;
  lwip_tcp_event_packet_t(lwip_tcp_event_t e, AsyncClient *c) : event(e), client(c), accept{nullptr} {}
  static void *operator new(std::size_t sz, const std::nothrow_t &) noexcept {
    if (fail_next_new_event) { fail_next_new_event = false; return nullptr; }
    return std::malloc(sz);
  }
  static void operator delete(void *p) noexcept { std::free(p); }
};

struct queue_mutex_guard {};
static int prepended_events = 0;
static lwip_tcp_event_packet_t *last_event = nullptr;
static void _prepend_async_event(lwip_tcp_event_packet_t *e) {
  ++prepended_events;
  delete last_event;
  last_event = e;
}

static size_t _remove_events_for_client(AsyncClient *, bool = false) {
  ++remove_events_calls;
  size_t r = queued_events_to_remove;
  queued_events_to_remove = 0;
  return r;
}

static void _bind_tcp_callbacks(tcp_pcb *pcb, AsyncClient *c) {
  check(in_lwip_thread, "_bind_tcp_callbacks must run on lwIP thread");
  ++bind_callbacks_calls;
  pcb->arg = c;
}
static void _reset_tcp_callbacks(tcp_pcb *pcb, AsyncClient *c) {
  check(in_lwip_thread, "_reset_tcp_callbacks must run on lwIP thread");
  ++reset_callbacks_calls;
  pcb->arg = nullptr;
  if (c) _remove_events_for_client(c);
}

using AcConnectHandler = void (*)(void *, AsyncClient *);

class AsyncTCP_detail {
 public:
  static int8_t tcp_accept(void *arg, tcp_pcb *pcb, int8_t err);
};

class AsyncClient {
 public:
  tcp_pcb *_pcb = nullptr;
  uint16_t _connect_port = 0;
  explicit AsyncClient(tcp_pcb *pcb = nullptr) : _pcb(pcb) {}
  static void *operator new(std::size_t sz, const std::nothrow_t &) noexcept {
    if (fail_next_new_client) { fail_next_new_client = false; return nullptr; }
    return std::malloc(sz);
  }
  static void operator delete(void *p) noexcept { std::free(p); }
  tcp_pcb *pcb() { return _pcb; }
  bool _reserve_error_event() { return true; }
  bool connect(ip_addr_t addr, uint16_t port);
  bool connect(const char *host, uint16_t port);
  size_t space() const;
  bool free();
  void setNoDelay(bool nodelay) const;
  bool getNoDelay();
  void setKeepAlive(uint32_t ms, uint8_t cnt);
  uint16_t getMss() const;
  uint32_t getRemoteAddress() const;
  uint16_t getRemotePort() const;
  uint32_t getLocalAddress() const;
  uint16_t getLocalPort() const;
  ip4_addr_t getRemoteAddress4() const;
  ip4_addr_t getLocalAddress4() const;
  uint8_t state() const;
  bool connected() const;
  bool connecting() const;
  bool disconnecting() const;
  bool disconnected() const;
  bool freeable() const;
  friend class AsyncTCP_detail;
};

class AsyncServer {
 public:
  uint16_t _port = 80;
  ip_addr_t _addr{};
  bool _noDelay = false;
  tcp_pcb *_pcb = nullptr;
  AcConnectHandler _connect_cb = nullptr;
  void *_connect_cb_arg = nullptr;
  void begin();
  void end();
  uint8_t status() const;
  friend class AsyncTCP_detail;
};

static err_t tcp_connect(tcp_pcb *pcb, const ip_addr_t *, uint16_t, tcp_connected_fn) {
  check(in_lwip_thread, "tcp_connect must run on lwIP thread");
  auto *client = reinterpret_cast<AsyncClient *>(pcb->arg);
  connect_saw_pcb_stored = (client != nullptr && client->_pcb == pcb);
  return next_tcp_connect_err;
}

static err_t dns_gethostbyname(const char *, ip_addr_t *addr, dns_found_callback, void *arg) {
  check(in_lwip_thread, "dns_gethostbyname must run on lwIP thread");
  ++dns_calls;
  auto *client = reinterpret_cast<AsyncClient *>(arg);
  dns_seen_connect_port = client ? client->_connect_port : 0;
  if (next_dns_err == ERR_OK && addr) *addr = next_dns_addr;
  return next_dns_err;
}

typedef struct {
  ip_addr_t remote_ip;
  ip_addr_t local_ip;
  uint16_t remote_port;
  uint16_t local_port;
  bool valid;
} tcp_endpoints_t;

typedef struct {
  struct tcpip_api_call_data call;
  tcp_pcb **pcb;
  int8_t err;
  union {
    AsyncClient *close;
    struct { const char *data; size_t size; uint8_t apiflags; } write;
    size_t received;
    struct { AsyncClient *client; ip_addr_t *addr; uint16_t port; uint8_t ip_type; tcp_connected_fn cb; } connect;
    struct { const char *host; ip_addr_t *addr; dns_found_callback cb; void *arg; } dns;
    struct { ip_addr_t *addr; uint16_t port; uint8_t ip_type; uint8_t backlog; AsyncServer *server; } server_begin;
    struct { bool enable; bool disabled; } nodelay;
    struct { uint32_t ms; uint8_t cnt; } keepalive;
    uint8_t state;
    size_t space;
    uint16_t mss;
    tcp_endpoints_t endpoints;
  };
} tcp_api_call_t;

// --- Extracted real functions from AsyncTCP.cpp ---
static void _apply_nodelay_lwip(tcp_pcb *pcb, bool nodelay) { @_apply_nodelay_lwip@ }
static err_t _tcp_abort_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_abort_api@ }
static esp_err_t _tcp_abort(tcp_pcb **pcb, AsyncClient *client) { @_tcp_abort@ }
static err_t _tcp_connect_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_connect_api@ }
static esp_err_t _tcp_connect(tcp_pcb **pcb, AsyncClient *client, uint8_t ip_type, ip_addr_t *addr, uint16_t port, tcp_connected_fn cb) { @_tcp_connect@ }
static err_t _dns_gethostbyname_api(struct tcpip_api_call_data *api_call_msg) { @_dns_gethostbyname_api@ }
static err_t _dns_gethostbyname(const char *host, ip_addr_t *addr, dns_found_callback cb, void *arg) { @_dns_gethostbyname@ }
static err_t _tcp_server_begin_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_server_begin_api@ }
static esp_err_t _tcp_server_begin(tcp_pcb **pcb, uint8_t ip_type, ip_addr_t *addr, uint16_t port, uint8_t backlog, AsyncServer *server) { @_tcp_server_begin@ }
static err_t _tcp_server_end_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_server_end_api@ }
static esp_err_t _tcp_server_end(tcp_pcb **pcb) { @_tcp_server_end@ }
static err_t _tcp_set_nodelay_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_set_nodelay_api@ }
static esp_err_t _tcp_set_nodelay(tcp_pcb **pcb, bool nodelay) { @_tcp_set_nodelay@ }
static err_t _tcp_get_nodelay_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_get_nodelay_api@ }
static bool _tcp_get_nodelay(tcp_pcb **pcb) { @_tcp_get_nodelay@ }
static err_t _tcp_set_keepalive_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_set_keepalive_api@ }
static esp_err_t _tcp_set_keepalive(tcp_pcb **pcb, uint32_t ms, uint8_t cnt) { @_tcp_set_keepalive@ }
static err_t _tcp_get_state_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_get_state_api@ }
static uint8_t _tcp_get_state(tcp_pcb *const *pcb) { @_tcp_get_state@ }
static err_t _tcp_space_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_space_api@ }
static size_t _tcp_space(tcp_pcb *const *pcb) { @_tcp_space@ }
static err_t _tcp_mss_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_mss_api@ }
static uint16_t _tcp_mss(tcp_pcb *const *pcb) { @_tcp_mss@ }
static err_t _tcp_get_endpoints_api(struct tcpip_api_call_data *api_call_msg) { @_tcp_get_endpoints_api@ }
static bool _tcp_get_endpoints(tcp_pcb *const *pcb, tcp_endpoints_t *out) { @_tcp_get_endpoints@ }

bool AsyncClient::connect(ip_addr_t addr, uint16_t port) { @client_connect_ip@ }
bool AsyncClient::connect(const char *host, uint16_t port) { @client_connect_host@ }
size_t AsyncClient::space() const { @client_space@ }
bool AsyncClient::free() { @client_free@ }
void AsyncClient::setNoDelay(bool nodelay) const { @client_setNoDelay@ }
bool AsyncClient::getNoDelay() { @client_getNoDelay@ }
void AsyncClient::setKeepAlive(uint32_t ms, uint8_t cnt) { @client_setKeepAlive@ }
uint16_t AsyncClient::getMss() const { @client_getMss@ }
uint32_t AsyncClient::getRemoteAddress() const { @client_getRemoteAddress@ }
uint16_t AsyncClient::getRemotePort() const { @client_getRemotePort@ }
uint32_t AsyncClient::getLocalAddress() const { @client_getLocalAddress@ }
uint16_t AsyncClient::getLocalPort() const { @client_getLocalPort@ }
ip4_addr_t AsyncClient::getRemoteAddress4() const { @client_getRemoteAddress4@ }
ip4_addr_t AsyncClient::getLocalAddress4() const { @client_getLocalAddress4@ }
uint8_t AsyncClient::state() const { @client_state@ }
bool AsyncClient::connected() const { @client_connected@ }
bool AsyncClient::connecting() const { @client_connecting@ }
bool AsyncClient::disconnecting() const { @client_disconnecting@ }
bool AsyncClient::disconnected() const { @client_disconnected@ }
bool AsyncClient::freeable() const { @client_freeable@ }
void AsyncServer::begin() { @server_begin@ }
void AsyncServer::end() { @server_end@ }
int8_t AsyncTCP_detail::tcp_accept(void *arg, tcp_pcb *pcb, int8_t err) { @tcp_accept@ }
uint8_t AsyncServer::status() const { @server_status@ }

static void dummy_on_client(void *, AsyncClient *) {}

int main() {
  // 1. _tcp_abort must purge queued events even when *pcb == nullptr
  {
    AsyncClient c;
    c._pcb = nullptr;
    queued_events_to_remove = 2;
    remove_events_calls = 0;
    check(_tcp_abort(&c._pcb, &c) == ERR_OK, "_tcp_abort with null pcb must purge queued events and return ERR_OK");
    check(remove_events_calls == 1, "_tcp_abort with null pcb did not call _remove_events_for_client");
    queued_events_to_remove = 0;
    check(_tcp_abort(&c._pcb, &c) == ERR_CONN, "_tcp_abort with null pcb and no events must return ERR_CONN");
  }

  // 2. Combined connect RPC: stores *pcb before tcp_connect, cleans up on error
  {
    AsyncClient c;
    ip_addr_t addr{0x01020304};
    next_tcp_connect_err = ERR_OK;
    connect_saw_pcb_stored = false;
    check(c.connect(addr, 8080), "connect(ip) must succeed");
    check(connect_saw_pcb_stored, "_tcp_connect_api must store *msg->pcb BEFORE tcp_connect");
    check(c._pcb != nullptr, "connect(ip) must leave _pcb set");
    // Second connect while active returns ERR_ALREADY
    check(_tcp_connect(&c._pcb, &c, IPADDR_TYPE_V4, &addr, 8080, _tcp_connected) == ERR_ALREADY,
          "_tcp_connect_api must return ERR_ALREADY if *pcb != nullptr");
    // Clean up pcb
    in_lwip_thread = true;
    tcp_abort(c._pcb);
    in_lwip_thread = false;
    c._pcb = nullptr;

    // Error path cleans up pcb & resets callbacks
    next_tcp_connect_err = ERR_MEM;
    reset_callbacks_calls = 0;
    abort_calls = 0;
    check(!c.connect(addr, 8080), "connect(ip) must fail on tcp_connect error");
    check(c._pcb == nullptr, "failed connect must clear _pcb");
    check(reset_callbacks_calls == 1 && abort_calls == 1, "failed connect must reset callbacks and abort pcb");
    check(active_pcbs == 0, "failed connect leaked pcb");
  }

  // 3. DNS via tcpip_api_call sets _connect_port BEFORE call
  {
    AsyncClient c;
    dns_calls = 0;
    dns_seen_connect_port = 0;
    next_dns_err = ERR_INPROGRESS;
    check(c.connect("example.com", 443), "connect(host) in-progress must return true");
    check(dns_calls == 1 && dns_seen_connect_port == 443, "connect(host) must set _connect_port before _dns_gethostbyname");
  }

  // 4. AsyncServer::begin & end atomic RPC + cleanup on bind/listen failure
  {
    AsyncServer s;
    s._port = 80;
    next_tcp_bind_err = ERR_MEM;
    active_pcbs = 0;
    s.begin();
    check(s._pcb == nullptr && active_pcbs == 0, "server begin bind failure must close pcb");

    next_tcp_bind_err = ERR_OK;
    fail_tcp_listen = true;
    s.begin();
    check(s._pcb == nullptr && active_pcbs == 0, "server begin listen failure must close original pcb");

    fail_tcp_listen = false;
    s.begin();
    check(s._pcb != nullptr && s.status() == LISTEN, "server begin must set LISTEN pcb");
    s.end();
    check(s._pcb == nullptr && active_pcbs == 0 && s.status() == CLOSED, "server end must close and null pcb");
  }

  // 5. tcp_accept on lwIP thread: NO self-deadlock on setNoDelay, and ERR_ABRT on OOM/no-cb
  {
    AsyncServer s;
    s._connect_cb = dummy_on_client;
    for (bool nd : {true, false}) {
      s._noDelay = nd;
      in_lwip_thread = true;
      tcp_pcb *pcb = tcp_new_ip_type(IPADDR_TYPE_V4);
      int8_t rc = AsyncTCP_detail::tcp_accept(&s, pcb, ERR_OK);
      in_lwip_thread = false;
      check(rc == ERR_OK, "tcp_accept must succeed without self-deadlock");
      check(pcb->nagle_disabled == nd, "tcp_accept must apply server->_noDelay directly on lwIP thread");
      check(last_event && last_event->client && last_event->client->_pcb == pcb, "tcp_accept must queue event");
      delete last_event->client;
      delete last_event;
      last_event = nullptr;
      in_lwip_thread = true;
      tcp_abort(pcb);
      in_lwip_thread = false;
    }

    // OOM allocating AsyncClient -> must abort pcb and return ERR_ABRT (not ERR_OK)
    fail_next_new_client = true;
    in_lwip_thread = true;
    tcp_pcb *oom_pcb = tcp_new_ip_type(IPADDR_TYPE_V4);
    int8_t oom_rc = AsyncTCP_detail::tcp_accept(&s, oom_pcb, ERR_OK);
    in_lwip_thread = false;
    check(oom_rc == ERR_ABRT, "tcp_accept OOM must return ERR_ABRT");
    check(active_pcbs == 0, "tcp_accept OOM must abort pcb");

    // No callback -> must abort pcb and return ERR_ABRT
    s._connect_cb = nullptr;
    in_lwip_thread = true;
    tcp_pcb *nocb_pcb = tcp_new_ip_type(IPADDR_TYPE_V4);
    int8_t nocb_rc = AsyncTCP_detail::tcp_accept(&s, nocb_pcb, ERR_OK);
    in_lwip_thread = false;
    check(nocb_rc == ERR_ABRT && active_pcbs == 0, "tcp_accept without callback must return ERR_ABRT");
  }

  // 6. setNoDelay / getNoDelay / setKeepAlive / state / space / mss / endpoints via RPC
  //    Test with two distinct values + concurrent null-and-free race (ASan catches any unsafe deref)
  {
    AsyncClient c;
    tcp_pcb *p = new tcp_pcb();
    p->state = ESTABLISHED;
    p->snd_buf = 1460;
    p->mss = 536;
    p->remote_ip.addr = 0x0A000001;
    p->local_ip.addr = 0x0A000002;
    p->remote_port = 1234;
    p->local_port = 80;
    c._pcb = p;

    c.setNoDelay(true);
    check(c.getNoDelay() == true, "setNoDelay(true) must persist");
    c.setNoDelay(false);
    check(c.getNoDelay() == false, "setNoDelay(false) must persist");

    c.setKeepAlive(5000, 3);
    check((p->so_options & SOF_KEEPALIVE) && p->keep_idle == 5000 && p->keep_cnt == 3, "setKeepAlive enable");
    c.setKeepAlive(0, 0);
    check((p->so_options & SOF_KEEPALIVE) == 0, "setKeepAlive disable");

    check(c.state() == ESTABLISHED && c.connected() && !c.connecting() && !c.disconnecting() && !c.disconnected() && !c.freeable() && !c.free(),
          "ESTABLISHED state checks");
    check(c.space() == 1460 && c.getMss() == 536, "space and mss for first values");
    check(c.getRemoteAddress() == 0x0A000001 && c.getLocalAddress() == 0x0A000002, "remote/local addr");
    check(c.getRemotePort() == 1234 && c.getLocalPort() == 80, "remote/local port");
    check(c.getRemoteAddress4().addr == 0x0A000001 && c.getLocalAddress4().addr == 0x0A000002, "addr4");

    p->state = FIN_WAIT_1;
    p->snd_buf = 2920;
    p->mss = 1460;
    check(c.state() == FIN_WAIT_1 && !c.connected() && c.disconnecting() && c.freeable() && c.free() && c.space() == 0 && c.getMss() == 1460,
          "FIN_WAIT_1 state checks");

    // Concurrent _pcb null-and-free race right before RPC executes:
    auto race_null = [&](auto fn) {
      tcp_pcb *victim = new tcp_pcb();
      victim->state = ESTABLISHED;
      victim->snd_buf = 1000;
      victim->mss = 500;
      c._pcb = victim;
      before_rpc_hook = [&]() {
        c._pcb = nullptr;
        delete victim;  // ASan poisons freed memory immediately
      };
      fn();
      check(before_rpc_hook == nullptr, "accessor bypassed tcpip_api_call");
    };
    race_null([&]() { check(c.state() == CLOSED, "raced state() must return CLOSED"); });
    race_null([&]() { check(!c.connected(), "raced connected() must return false"); });
    race_null([&]() { check(c.disconnected(), "raced disconnected() must return true"); });
    race_null([&]() { check(c.freeable(), "raced freeable() must return true"); });
    race_null([&]() { check(c.free(), "raced free() must return true"); });
    race_null([&]() { check(c.space() == 0, "raced space() must return 0"); });
    race_null([&]() { check(c.getMss() == 0, "raced getMss() must return 0"); });
    race_null([&]() { check(!c.getNoDelay(), "raced getNoDelay() must return false"); });
    race_null([&]() { c.setNoDelay(true); });
    race_null([&]() { c.setKeepAlive(1000, 2); });
    race_null([&]() { check(c.getRemoteAddress() == 0, "raced getRemoteAddress() must return 0"); });
    race_null([&]() { check(c.getRemotePort() == 0, "raced getRemotePort() must return 0"); });
    race_null([&]() { check(c.getLocalAddress() == 0, "raced getLocalAddress() must return 0"); });
    race_null([&]() { check(c.getLocalPort() == 0, "raced getLocalPort() must return 0"); });

    delete p;
  }

  return 0;
}
'''


HTTP_HARNESS_TEMPLATE = r'''
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <new>
#include <string>
#include <strings.h>

#define ESP32 1
#define DEBUG_HTTP(...) if (false) {}
#define PSTR(s) s
#define strcasecmp_P strcasecmp
#define portMAX_DELAY 0

static void check(bool cond, const char *msg) {
  if (!cond) {
    std::cerr << "FAIL: " << msg << "\n";
    std::exit(1);
  }
}

struct FakeRecursiveMutex {
  int depth = 0;
  int maxDepth = 0;
  int takes = 0;
  int gives = 0;
};
using SemaphoreHandle_t = FakeRecursiveMutex *;

static void xSemaphoreTakeRecursive(SemaphoreHandle_t m, int) {
  check(m != nullptr, "take on null mutex");
  ++m->depth;
  ++m->takes;
  if (m->depth > m->maxDepth) m->maxDepth = m->depth;
}
static void xSemaphoreGiveRecursive(SemaphoreHandle_t m) {
  check(m != nullptr, "give on null mutex");
  check(m->depth > 0, "mutex underflow");
  --m->depth;
  ++m->gives;
}

#define _seize xSemaphoreTakeRecursive(threadLock, portMAX_DELAY)
#define _release xSemaphoreGiveRecursive(threadLock)

@ThreadLockGuard@

class String {
 public:
  String() = default;
  String(const char *s) : v_(s ? s : "") {}
  String(const std::string &s) : v_(s) {}
  size_t length() const { return v_.size(); }
  const char *c_str() const { return v_.c_str(); }
  String substring(size_t a, size_t b = std::string::npos) const { return v_.substr(a, b); }
 private:
  std::string v_;
};

struct xbuf {
  std::string data;
  bool failReadString = false;
  size_t available() const { return data.size(); }
  size_t write(const uint8_t *p, size_t n) { data.append(reinterpret_cast<const char *>(p), n); return n; }
  size_t write(xbuf *src, size_t n) {
    size_t c = std::min(n, src->available());
    data.append(src->data.data(), c);
    src->data.erase(0, c);
    return c;
  }
  int indexOf(const char *needle) const {
    auto pos = data.find(needle);
    return pos == std::string::npos ? -1 : static_cast<int>(pos);
  }
  String readStringUntil(const char *delim) {
    auto pos = data.find(delim);
    if (pos == std::string::npos) return String();
    size_t len = pos + std::strlen(delim);
    String r(data.substr(0, len));
    data.erase(0, len);
    return r;
  }
  String readString(size_t n) {
    if (failReadString) return String();
    size_t c = std::min(n, data.size());
    String r(data.substr(0, c));
    data.erase(0, c);
    return r;
  }
  String peekString(size_t n) const { return String(data.substr(0, n)); }
};

class asyncHTTPrequest;
struct AsyncClient {
  bool isConnected = false;
  bool nextConnectResult = true;
  int closeCalls = 0;
  int abortCalls = 0;
  bool connected() const { return isConnected; }
  bool connect(const char *, int) { return nextConnectResult; }
  void close() { ++closeCalls; }
  void abort() { ++abortCalls; }
  template <typename F> void onConnect(F, void *) {}
  template <typename F> void onDisconnect(F, void *) {}
  template <typename F> void onPoll(F, void *) {}
  template <typename F> void onError(F, void *) {}
};

class asyncHTTPrequest {
 public:
  static constexpr int HTTPCODE_NOT_CONNECTED = -4;
  static constexpr int HTTPCODE_TOO_LESS_RAM = -8;
  static constexpr int HTTPCODE_RESPONSE_TOO_LARGE = -12;
  enum readyStates { readyStateUnsent = 0, readyStateOpened = 1, readyStateHdrsRecvd = 2, readyStateLoading = 3, readyStateDone = 4 };
  enum { HTTPmethodGET, HTTPmethodPOST } _HTTPmethod = HTTPmethodGET;

  struct URL {
    char *host = nullptr;
    int port = 80;
    ~URL() { delete[] host; }
  };
  struct header { int dummy = 0; };

  FakeRecursiveMutex mutexObj;
  SemaphoreHandle_t threadLock = &mutexObj;
  readyStates _readyState = readyStateUnsent;
  int _HTTPcode = 0;
  bool _chunked = false;
  uint32_t _timeout = 3;
  uint32_t _lastActivity = 0;
  uint32_t _requestStartTime = 0;
  uint32_t _requestEndTime = 0;
  URL *_URL = nullptr;
  char *_connectedHost = nullptr;
  int _connectedPort = -1;
  AsyncClient *_client = nullptr;
  size_t _contentLength = 0;
  size_t _contentRead = 0;
  uint16_t _maxResponseBufferBytes = 16 * 1024;
  xbuf *_request = nullptr;
  xbuf *_response = nullptr;
  xbuf *_chunks = nullptr;
  header *_headers = nullptr;
  void (*_onDataCB)(void *, asyncHTTPrequest *, size_t) = nullptr;
  void *_onDataCBarg = nullptr;

  bool parseShouldSucceed = true;
  const char *connectionHeaderValue = nullptr;

  uint32_t millis() const { return 42; }
  size_t available() const { return _response ? _response->available() : 0; }
  void _setReadyState(readyStates s) { _readyState = s; }
  void _failRequest(int code) { _HTTPcode = code; _setReadyState(readyStateDone); }
  bool _parseURL(const char *url) {
    if (!parseShouldSucceed || !url) return false;
    delete _URL;
    _URL = new URL();
    _URL->host = new char[16];
    std::strcpy(_URL->host, "example.com");
    _URL->port = 80;
    return true;
  }
  header *_addHeader(const char *, const char *) {
    if (!_headers) _headers = new header();
    return _headers;
  }
  bool _collectHeaders() { _readyState = readyStateHdrsRecvd; return true; }
  char *respHeaderValue(const char *) { return const_cast<char *>(connectionHeaderValue); }
  void _onConnect(AsyncClient *) { _seize; _setReadyState(readyStateOpened); _release; }
  void _onDisconnect(AsyncClient *) {}
  void _onPoll(AsyncClient *) {}
  void _onError(AsyncClient *, uint32_t) {}

  bool open(const char *method, const char *URL);
  String responseText();
  bool _connect();
  void _processChunks();
  void _onData(void *Vbuf, size_t len);

  ~asyncHTTPrequest() {
    delete _client;
    delete _URL;
    delete[] _connectedHost;
    delete _request;
    delete _response;
    delete _chunks;
    delete _headers;
  }
};

bool asyncHTTPrequest::open(const char *method, const char *URL) { @http_open@ }
String asyncHTTPrequest::responseText() { @http_responseText@ }
bool asyncHTTPrequest::_connect() { @http_connect@ }
void asyncHTTPrequest::_processChunks() { @http_processChunks@ }
void asyncHTTPrequest::_onData(void *Vbuf, size_t len) { @http_onData@ }

int main() {
  // 1. open() + _connect() recursive mutex balance on all paths
  {
    asyncHTTPrequest req;
    req._readyState = asyncHTTPrequest::readyStateLoading;
    check(!req.open("GET", "http://example.com/"), "open during active state must fail");
    check(req.mutexObj.depth == 0 && req.mutexObj.takes == 1 && req.mutexObj.gives == 1,
          "open early return (readyState) must acquire and release mutex");

    req._readyState = asyncHTTPrequest::readyStateUnsent;
    check(!req.open("PUT", "http://example.com/"), "open with unsupported method must fail");
    check(req.mutexObj.depth == 0 && req.mutexObj.takes == 2 && req.mutexObj.gives == 2,
          "open early return (method) must balance mutex");

    req.parseShouldSucceed = false;
    check(!req.open("GET", "bad://url"), "open with bad URL must fail");
    check(req.mutexObj.depth == 0 && req.mutexObj.takes == 3 && req.mutexObj.gives == 3,
          "open early return (parseURL) must balance mutex");

    req.parseShouldSucceed = true;
    req.mutexObj = FakeRecursiveMutex{};
    check(req.open("GET", "http://example.com/"), "open normal path must succeed");
    check(req.mutexObj.depth == 0 && req.mutexObj.maxDepth >= 2 && req.mutexObj.takes == req.mutexObj.gives,
          "open -> _connect must nest recursive mutex (depth >= 2) and balance");

    // Already-connected path invokes _onConnect (depth >= 3)
    req._readyState = asyncHTTPrequest::readyStateDone;
    req._client->isConnected = true;
    req.mutexObj = FakeRecursiveMutex{};
    check(req.open("POST", "http://example.com/"), "open reuse connected client must succeed");
    check(req.mutexObj.depth == 0 && req.mutexObj.maxDepth >= 3 && req.mutexObj.takes == req.mutexObj.gives,
          "open -> _connect -> _onConnect must nest recursive mutex (depth >= 3) and balance");

    // _connect failure path
    req._readyState = asyncHTTPrequest::readyStateDone;
    req._client->isConnected = false;
    req._client->nextConnectResult = false;
    req.mutexObj = FakeRecursiveMutex{};
    check(!req.open("GET", "http://example.com/"), "open with connect failure must fail");
    check(req.mutexObj.depth == 0 && req.mutexObj.takes == req.mutexObj.gives,
          "open with connect failure must balance mutex");
  }

  // 2. responseText() OOM with _client == nullptr must not crash
  {
    asyncHTTPrequest req;
    req._readyState = asyncHTTPrequest::readyStateLoading;
    req._response = new xbuf{"hello", true};
    req._client = nullptr;
    String out = req.responseText();
    check(out.length() == 0 && req._HTTPcode == asyncHTTPrequest::HTTPCODE_TOO_LESS_RAM && req.mutexObj.depth == 0,
          "responseText OOM with null _client must set TOO_LESS_RAM, release lock, and not crash");

    req._HTTPcode = 200;
    req._client = new AsyncClient();
    out = req.responseText();
    check(req._client->abortCalls == 1 && req._HTTPcode == asyncHTTPrequest::HTTPCODE_TOO_LESS_RAM,
          "responseText OOM with live _client must call abort");
  }

  // 3. Connection: close (not "disconnect") + null _client guard in _onData and _processChunks
  {
    // Non-chunked: Connection: close -> closes TCP
    asyncHTTPrequest req;
    req._readyState = asyncHTTPrequest::readyStateHdrsRecvd;
    req._response = new xbuf{};
    req._client = new AsyncClient();
    req._contentLength = 4;
    req.connectionHeaderValue = "close";
    const char payload[] = "data";
    req._onData(const_cast<char *>(payload), 4);
    check(req._client->closeCalls == 1 && req._readyState == asyncHTTPrequest::readyStateDone,
          "_onData must close client on Connection: close");

    // Non-chunked: Connection: disconnect -> does NOT close TCP
    asyncHTTPrequest req2;
    req2._readyState = asyncHTTPrequest::readyStateHdrsRecvd;
    req2._response = new xbuf{};
    req2._client = new AsyncClient();
    req2._contentLength = 4;
    req2.connectionHeaderValue = "disconnect";
    req2._onData(const_cast<char *>(payload), 4);
    check(req2._client->closeCalls == 0, "_onData must NOT close on non-standard Connection: disconnect");

    // Non-chunked: Connection: close with _client == nullptr -> must not crash
    asyncHTTPrequest req3;
    req3._readyState = asyncHTTPrequest::readyStateHdrsRecvd;
    req3._response = new xbuf{};
    req3._client = nullptr;
    req3._contentLength = 4;
    req3.connectionHeaderValue = "Close";
    req3._onData(const_cast<char *>(payload), 4);
    check(req3._readyState == asyncHTTPrequest::readyStateDone, "_onData with null _client must finish safely");

    // Chunked: Connection: close -> closes TCP
    asyncHTTPrequest creq;
    creq._chunked = true;
    creq._response = new xbuf{};
    creq._chunks = new xbuf{"0\r\n", false};
    creq._client = new AsyncClient();
    creq.connectionHeaderValue = "close";
    creq._processChunks();
    check(creq._client->closeCalls == 1 && creq._readyState == asyncHTTPrequest::readyStateDone,
          "_processChunks must close client on Connection: close");

    // Chunked: Connection: close with _client == nullptr -> must not crash
    asyncHTTPrequest creq2;
    creq2._chunked = true;
    creq2._response = new xbuf{};
    creq2._chunks = new xbuf{"0\r\n", false};
    creq2._client = nullptr;
    creq2.connectionHeaderValue = "close";
    creq2._processChunks();
    check(creq2._readyState == asyncHTTPrequest::readyStateDone, "_processChunks with null _client must finish safely");
  }

  return 0;
}
'''


def build_tcp_harness(parts: dict[str, str]) -> str:
    replacements = {
        "@_apply_nodelay_lwip@": parts["static void _apply_nodelay_lwip(tcp_pcb *pcb, bool nodelay)"],
        "@_tcp_abort_api@": parts["static err_t _tcp_abort_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_abort@": parts["static esp_err_t _tcp_abort(tcp_pcb **pcb, AsyncClient *client)"],
        "@_tcp_connect_api@": parts["static err_t _tcp_connect_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_connect@": parts["static esp_err_t _tcp_connect(tcp_pcb **pcb, AsyncClient *client, uint8_t ip_type, ip_addr_t *addr, uint16_t port, tcp_connected_fn cb)"],
        "@_dns_gethostbyname_api@": parts["static err_t _dns_gethostbyname_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_dns_gethostbyname@": parts["static err_t _dns_gethostbyname(const char *host, ip_addr_t *addr, dns_found_callback cb, void *arg)"],
        "@_tcp_server_begin_api@": parts["static err_t _tcp_server_begin_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_server_begin@": parts["static esp_err_t _tcp_server_begin(tcp_pcb **pcb, uint8_t ip_type, ip_addr_t *addr, uint16_t port, uint8_t backlog, AsyncServer *server)"],
        "@_tcp_server_end_api@": parts["static err_t _tcp_server_end_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_server_end@": parts["static esp_err_t _tcp_server_end(tcp_pcb **pcb)"],
        "@_tcp_set_nodelay_api@": parts["static err_t _tcp_set_nodelay_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_set_nodelay@": parts["static esp_err_t _tcp_set_nodelay(tcp_pcb **pcb, bool nodelay)"],
        "@_tcp_get_nodelay_api@": parts["static err_t _tcp_get_nodelay_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_get_nodelay@": parts["static bool _tcp_get_nodelay(tcp_pcb **pcb)"],
        "@_tcp_set_keepalive_api@": parts["static err_t _tcp_set_keepalive_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_set_keepalive@": parts["static esp_err_t _tcp_set_keepalive(tcp_pcb **pcb, uint32_t ms, uint8_t cnt)"],
        "@_tcp_get_state_api@": parts["static err_t _tcp_get_state_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_get_state@": parts["static uint8_t _tcp_get_state(tcp_pcb *const *pcb)"],
        "@_tcp_space_api@": parts["static err_t _tcp_space_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_space@": parts["static size_t _tcp_space(tcp_pcb *const *pcb)"],
        "@_tcp_mss_api@": parts["static err_t _tcp_mss_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_mss@": parts["static uint16_t _tcp_mss(tcp_pcb *const *pcb)"],
        "@_tcp_get_endpoints_api@": parts["static err_t _tcp_get_endpoints_api(struct tcpip_api_call_data *api_call_msg)"],
        "@_tcp_get_endpoints@": parts["static bool _tcp_get_endpoints(tcp_pcb *const *pcb, tcp_endpoints_t *out)"],
        "@client_connect_ip@": parts["bool AsyncClient::connect(ip_addr_t addr, uint16_t port)"],
        "@client_connect_host@": parts["bool AsyncClient::connect(const char *host, uint16_t port)"],
        "@client_space@": parts["size_t AsyncClient::space() const"],
        "@client_free@": parts["bool AsyncClient::free()"],
        "@client_setNoDelay@": parts["void AsyncClient::setNoDelay(bool nodelay) const"],
        "@client_getNoDelay@": parts["bool AsyncClient::getNoDelay()"],
        "@client_setKeepAlive@": parts["void AsyncClient::setKeepAlive(uint32_t ms, uint8_t cnt)"],
        "@client_getMss@": parts["uint16_t AsyncClient::getMss() const"],
        "@client_getRemoteAddress@": parts["uint32_t AsyncClient::getRemoteAddress() const"],
        "@client_getRemotePort@": parts["uint16_t AsyncClient::getRemotePort() const"],
        "@client_getLocalAddress@": parts["uint32_t AsyncClient::getLocalAddress() const"],
        "@client_getLocalPort@": parts["uint16_t AsyncClient::getLocalPort() const"],
        "@client_getRemoteAddress4@": parts["ip4_addr_t AsyncClient::getRemoteAddress4() const"],
        "@client_getLocalAddress4@": parts["ip4_addr_t AsyncClient::getLocalAddress4() const"],
        "@client_state@": parts["uint8_t AsyncClient::state() const"],
        "@client_connected@": parts["bool AsyncClient::connected() const"],
        "@client_connecting@": parts["bool AsyncClient::connecting() const"],
        "@client_disconnecting@": parts["bool AsyncClient::disconnecting() const"],
        "@client_disconnected@": parts["bool AsyncClient::disconnected() const"],
        "@client_freeable@": parts["bool AsyncClient::freeable() const"],
        "@server_begin@": parts["void AsyncServer::begin()"],
        "@server_end@": parts["void AsyncServer::end()"],
        "@tcp_accept@": parts["int8_t AsyncTCP_detail::tcp_accept(void *arg, tcp_pcb *pcb, int8_t err)"],
        "@server_status@": parts["uint8_t AsyncServer::status() const"],
    }
    src = TCP_HARNESS_TEMPLATE
    for k, v in replacements.items():
        src = src.replace(k, v)
    return src


def build_http_harness(parts: dict[str, str]) -> str:
    replacements = {
        "@ThreadLockGuard@": parts["ThreadLockGuard"],
        "@http_open@": parts["bool\tasyncHTTPrequest::open(const char* method, const char* URL)"],
        "@http_responseText@": parts["String\tasyncHTTPrequest::responseText()"],
        "@http_connect@": parts["bool  asyncHTTPrequest::_connect()"],
        "@http_processChunks@": parts["void  asyncHTTPrequest::_processChunks()"],
        "@http_onData@": parts["void  asyncHTTPrequest::_onData(void* Vbuf, size_t len)"],
    }
    src = HTTP_HARNESS_TEMPLATE
    for k, v in replacements.items():
        src = src.replace(k, v)
    return src


def compile_and_run(source: str, prefix: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        root = Path(tmp)
        cpp = root / "harness.cpp"
        exe = root / "harness"
        cpp.write_text(source, encoding="utf-8")
        build = subprocess.run(
            [
                "g++", "-std=c++17", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                "-Wall", "-Wextra", "-Wno-unused-parameter", "-Wno-unused-variable",
                str(cpp), "-o", str(exe),
            ],
            capture_output=True, text=True,
        )
        if build.returncode:
            return build.returncode, "COMPILE ERROR:\n" + build.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        return run.returncode, run.stdout + run.stderr


def main() -> int:
    tcp_parts = extract_tcp_parts(ASYNC_TCP_SRC.read_text(encoding="utf-8"))
    http_parts = extract_http_parts(ASYNC_HTTP_SRC.read_text(encoding="utf-8"))

    errors: list[str] = []

    code, out = compile_and_run(build_tcp_harness(tcp_parts), "samovar-tcp-lwip-")
    if code != 0:
        print("TCP lwIP safety baseline FAILED:\n" + out, file=sys.stderr)
        return 1

    code, out = compile_and_run(build_http_harness(http_parts), "samovar-http-lwip-")
    if code != 0:
        print("HTTP safety baseline FAILED:\n" + out, file=sys.stderr)
        return 1

    # Mutation tests to verify semantic assertions catch regressions
    tcp_mutations = (
        ("_tcp_abort null-pcb short-circuit", "static esp_err_t _tcp_abort(tcp_pcb **pcb, AsyncClient *client)", "if (!pcb)", "if (!pcb || !*pcb)"),
        ("tcp_accept self-deadlock", "int8_t AsyncTCP_detail::tcp_accept(void *arg, tcp_pcb *pcb, int8_t err)", "_apply_nodelay_lwip(pcb, server->_noDelay);", "c->setNoDelay(server->_noDelay);"),
        ("tcp_accept OOM returns ERR_OK", "int8_t AsyncTCP_detail::tcp_accept(void *arg, tcp_pcb *pcb, int8_t err)", "  tcp_abort(pcb);\n  return ERR_ABRT;", "  tcp_abort(pcb);\n  return ERR_OK;"),
        ("state() direct pcb deref", "uint8_t AsyncClient::state() const", "return _tcp_get_state(&_pcb);", "return _pcb ? _pcb->state : 0;"),
    )
    for name, key, old, new in tcp_mutations:
        mut = dict(tcp_parts)
        if old not in mut[key]:
            errors.append(f"{name}: token not found")
            continue
        mut[key] = mut[key].replace(old, new, 1)
        rc, out = compile_and_run(build_tcp_harness(mut), "samovar-tcp-mut-")
        if rc == 0 or ("FAIL:" not in out and "AddressSanitizer" not in out):
            errors.append(f"{name}: mutation survived (rc={rc}, out={out.strip()})")

    http_mutations = (
        ("_onData Connection: disconnect regression", "void  asyncHTTPrequest::_onData(void* Vbuf, size_t len)", 'PSTR("close")', 'PSTR("disconnect")'),
        ("_processChunks Connection: disconnect regression", "void  asyncHTTPrequest::_processChunks()", 'PSTR("close")', 'PSTR("disconnect")'),
        ("open() missing ThreadLockGuard", "bool\tasyncHTTPrequest::open(const char* method, const char* URL)", "ThreadLockGuard lockGuard(threadLock);", "(void)threadLock;"),
    )
    for name, key, old, new in http_mutations:
        mut = dict(http_parts)
        if old not in mut[key]:
            errors.append(f"{name}: token not found")
            continue
        mut[key] = mut[key].replace(old, new, 1)
        rc, out = compile_and_run(build_http_harness(mut), "samovar-http-mut-")
        if rc == 0 or "FAIL:" not in out:
            errors.append(f"{name}: mutation survived (rc={rc}, out={out.strip()})")

    if errors:
        print("async TCP/HTTP lwIP safety smoke FAILED:\n - " + "\n - ".join(errors), file=sys.stderr)
        return 1

    print("async TCP/HTTP lwIP safety smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
