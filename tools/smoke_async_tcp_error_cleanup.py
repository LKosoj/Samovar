#!/usr/bin/env python3
"""Проверяет владение error-событиями AsyncTCP при отказах выделения памяти."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "libraries/Async_TCP/src/AsyncTCP.cpp"


def parts() -> dict[str, str]:
    source = SOURCE.read_text(encoding="utf-8")
    signatures = (
        "AsyncClient::AsyncClient(tcp_pcb *pcb)",
        "AsyncClient::~AsyncClient()",
        "bool AsyncClient::_reserve_error_event()",
        "void AsyncClient::_error(int8_t err)",
        "void AsyncTCP_detail::tcp_error(void *arg, int8_t err)",
        "int8_t AsyncTCP_detail::tcp_accept(void *arg, tcp_pcb *pcb, int8_t err)",
        "void AsyncTCP_detail::handle_async_event(lwip_tcp_event_packet_t *e)",
        "static void _free_event(lwip_tcp_event_packet_t *evpkt)",
        "static void _reset_tcp_callbacks(tcp_pcb *pcb, AsyncClient *client)",
    )
    methods = {signature: extract_function_body(source, signature) for signature in signatures}
    for signature, boundary in (
        ("bool AsyncClient::connect(ip_addr_t addr, uint16_t port)", "  tcp_pcb *pcb;"),
        ("bool AsyncClient::connect(const char *host, uint16_t port)", "  err_t err;"),
    ):
        # Only the actual admission path; no fake DNS/network implementation.
        body = extract_function_body(source, signature)
        if boundary not in body:
            raise ValueError("connect admission boundary not found")
        methods[signature] = body.split(boundary, 1)[0] + "return true;"
    return methods


PREFIX = r'''
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <functional>
#include <cstring>
#include <new>

static void *live[64];
static size_t live_count = 0, attempts = 0, fail_at = 0;
static bool deny_all = false, in_lwip = false;
static int wrong_context = 0;
static int abort_count = 0, unexpected_error_callback = 0, error_callbacks = 0, disconnect_callbacks = 0;
static void track(void *p) { if (live_count == 64) std::abort(); live[live_count++] = p; }
static void untrack(void *p) { for (size_t i = 0; i < live_count; ++i) if (live[i] == p) { live[i] = live[--live_count]; return; } std::cerr << "FAIL: double free\n"; std::exit(1); }
void *operator new(std::size_t n) { ++attempts; if (deny_all || (fail_at && attempts == fail_at)) throw std::bad_alloc(); void *p = std::malloc(n ? n : 1); if (!p) throw std::bad_alloc(); track(p); return p; }
void *operator new(std::size_t n, const std::nothrow_t &) noexcept { ++attempts; if (deny_all || (fail_at && attempts == fail_at)) return nullptr; void *p = std::malloc(n ? n : 1); if (p) track(p); return p; }
void operator delete(void *p) noexcept { if (p) { untrack(p); std::free(p); } }
void operator delete(void *p, std::size_t) noexcept { if (p) { untrack(p); std::free(p); } }
static void reset_alloc() { attempts = 0; fail_at = 0; deny_all = false; }
static void fail_next() { fail_at = attempts + 1; }
static void fail_all() { deny_all = true; }

using ip4_addr_t = int;
struct pbuf {};
static void pbuf_free(pbuf *) {}
struct tcp_pcb { void *arg = nullptr; void (*error)(void *, int8_t) = nullptr; int state = 0; };
static void tcp_arg(tcp_pcb *p, void *a) { p->arg = a; }
static void tcp_sent(tcp_pcb *, void *) {}
static void tcp_recv(tcp_pcb *, void *) {}
static void tcp_err(tcp_pcb *p, void (*fn)(void *, int8_t)) { p->error = fn; }
static void tcp_poll(tcp_pcb *, void *, int) {}
class AsyncClient;
static void _bind_tcp_callbacks(tcp_pcb *p, AsyncClient *c);
static void tcp_abort(tcp_pcb *p) { ++abort_count; if (p->error) { ++unexpected_error_callback; p->error(p->arg, -99); } }
static uint32_t millis() { return 1; }
static void async_tcp_log_e(const char *) {}
#define async_tcp_log_d(...) ((void)0)
#define async_tcp_log_elapsed(name, expression) expression
static void xTaskNotifyGive(void *) {}
static void * _async_service_task_handle = nullptr;
static int xSemaphoreTake(void *, int) { return 1; }
static void xSemaphoreGive(void *) {}
static void *_async_queue_mutex = nullptr;
static bool _start_async_task() { _async_queue_mutex = reinterpret_cast<void *>(1); return true; }
#define portMAX_DELAY 0
#define CONFIG_ASYNC_TCP_QUEUE_SIZE 16
#define ERR_OK 0
#define ERR_ABRT -1
#define ERR_MEM -2
using esp_err_t = int;
using ip_addr_t = int;
using AcConnectHandler = void (*)(void *, class AsyncClient *);
using AcErrorHandler = void (*)(void *, class AsyncClient *, int8_t);

enum lwip_tcp_event_t { LWIP_TCP_RECV, LWIP_TCP_FIN, LWIP_TCP_SENT, LWIP_TCP_POLL, LWIP_TCP_ERROR, LWIP_TCP_CONNECTED, LWIP_TCP_ACCEPT, LWIP_TCP_DNS };
struct lwip_tcp_event_packet_t {
  lwip_tcp_event_packet_t *next = nullptr;
  lwip_tcp_event_t event;
  class AsyncClient *client;
  union { struct { tcp_pcb *pcb; pbuf *pb; int8_t err; } recv; struct { tcp_pcb *pcb; int8_t err; } fin; struct { tcp_pcb *pcb; uint16_t len; } sent; struct { tcp_pcb *pcb; } poll; struct { int8_t err; } error; struct { tcp_pcb *pcb; int8_t err; } connected; struct { class AsyncServer *server; } accept; struct { const char *name; ip_addr_t addr; } dns; };
  lwip_tcp_event_packet_t(lwip_tcp_event_t e, AsyncClient *c) : event(e), client(c) {}
};
class AsyncTCP_detail;
'''

MIN_CLASSES = r'''
class AsyncClient {
public:
  tcp_pcb *_pcb = nullptr;
  lwip_tcp_event_packet_t *_error_event = nullptr;
  AcConnectHandler _connect_cb = nullptr;
  void *_connect_cb_arg = nullptr;
  AcConnectHandler _discard_cb = nullptr;
  void *_discard_cb_arg = nullptr;
  AcErrorHandler _error_cb = nullptr;
  void *_error_cb_arg = nullptr;
  uint32_t _rx_last_packet = 0;
  AsyncClient(tcp_pcb *pcb = nullptr);
  ~AsyncClient();
  tcp_pcb *pcb() { return _pcb; }
  bool _reserve_error_event();
  bool connect(ip_addr_t, uint16_t);
  bool connect(const char *, uint16_t);
  void setNoDelay(bool) {}
  void _error(int8_t);
  void _recv(tcp_pcb *, pbuf *, int8_t) {}
  void _fin(tcp_pcb *, int8_t) {}
  void _sent(tcp_pcb *, uint16_t) {}
  void _poll(tcp_pcb *) {}
  void _connected(tcp_pcb *, int8_t) {}
  void _dns_found(ip_addr_t *) {}
  int8_t _close() { _pcb = nullptr; return ERR_OK; }
  friend class AsyncTCP_detail;
};
class AsyncServer {
public:
  AcConnectHandler _connect_cb = nullptr;
  bool _noDelay = false;
  AsyncServer(uint16_t) {}
  int8_t _accepted(AsyncClient *c) { if (_connect_cb) _connect_cb(nullptr, c); return ERR_OK; }
  friend class AsyncTCP_detail;
};
'''


def harness(methods: dict[str, str]) -> str:
    body = {
        "constructor": methods["AsyncClient::AsyncClient(tcp_pcb *pcb)"],
        "destructor": methods["AsyncClient::~AsyncClient()"],
        "reserve": methods["bool AsyncClient::_reserve_error_event()"],
        "error_method": methods["void AsyncClient::_error(int8_t err)"],
        "tcp_error": methods["void AsyncTCP_detail::tcp_error(void *arg, int8_t err)"],
        "tcp_accept": methods["int8_t AsyncTCP_detail::tcp_accept(void *arg, tcp_pcb *pcb, int8_t err)"],
        "handle": methods["void AsyncTCP_detail::handle_async_event(lwip_tcp_event_packet_t *e)"],
        "free_event": methods["static void _free_event(lwip_tcp_event_packet_t *evpkt)"],
        "reset": methods["static void _reset_tcp_callbacks(tcp_pcb *pcb, AsyncClient *client)"],
    }
    definitions = (
        MIN_CLASSES
        + "\n"
        + "class AsyncTCP_detail { public: static void tcp_error(void *, int8_t); static int8_t tcp_accept(void *, tcp_pcb *, int8_t); static void handle_async_event(lwip_tcp_event_packet_t *); };\n"
        + "static void _bind_tcp_callbacks(tcp_pcb *p, AsyncClient *c){tcp_arg(p,c);tcp_err(p,&AsyncTCP_detail::tcp_error);}\n"
        + "static void _free_event(lwip_tcp_event_packet_t *); static void _reset_tcp_callbacks(tcp_pcb *, AsyncClient *);\n"
        + "class EventQueue { lwip_tcp_event_packet_t *head=nullptr,*tail=nullptr; public: "
          "void push_back(lwip_tcp_event_packet_t *e){e->next=nullptr;if(tail)tail->next=e;else head=e;tail=e;} "
          "void push_front(lwip_tcp_event_packet_t *e){e->next=head;head=e;if(!tail)tail=e;} "
          "lwip_tcp_event_packet_t *pop_front(){auto e=head;if(e){head=e->next;if(!head)tail=nullptr;}return e;} "
          "size_t size()const{size_t n=0;for(auto e=head;e;e=e->next)++n;return n;} }; "
          "static EventQueue _async_queue; "
          "static void _send_async_event(lwip_tcp_event_packet_t *e){if(e){_async_queue.push_back(e);xTaskNotifyGive(_async_service_task_handle);}} "
          "static void _prepend_async_event(lwip_tcp_event_packet_t *e){if(e){_async_queue.push_front(e);xTaskNotifyGive(_async_service_task_handle);}} "
          "class queue_mutex_guard{public:queue_mutex_guard(){xSemaphoreTake(_async_queue_mutex,portMAX_DELAY);}~queue_mutex_guard(){xSemaphoreGive(_async_queue_mutex);}operator bool()const{return true;}}; "
          "static size_t _remove_events_for_client(AsyncClient *client){size_t n=0;lwip_tcp_event_packet_t *keep=nullptr,*tail=nullptr;while(auto e=_async_queue.pop_front()){if(e->client==client){delete e;++n;}else{e->next=nullptr;if(tail)tail->next=e;else keep=e;tail=e;}}while(keep){auto e=keep;keep=keep->next;_async_queue.push_back(e);}return n;}\n"
        + "AsyncClient::AsyncClient(tcp_pcb *pcb){"
        + body["constructor"]
        + "}\nAsyncClient::~AsyncClient(){"
        + body["destructor"]
        + "}\nbool AsyncClient::_reserve_error_event(){"
        + body["reserve"]
        + "}\nvoid AsyncClient::_error(int8_t err){"
        + body["error_method"]
        + "}\nvoid AsyncTCP_detail::tcp_error(void *arg,int8_t err){"
        + body["tcp_error"]
        + "}\nint8_t AsyncTCP_detail::tcp_accept(void *arg,tcp_pcb *pcb,int8_t err){"
        + body["tcp_accept"]
        + "}\nvoid AsyncTCP_detail::handle_async_event(lwip_tcp_event_packet_t *e){"
        + body["handle"]
        + "}\nstatic void _free_event(lwip_tcp_event_packet_t *evpkt){"
        + body["free_event"]
        + "}\nstatic void _reset_tcp_callbacks(tcp_pcb *pcb,AsyncClient *client){"
        + body["reset"]
        + "}\n"
    )
    for signature, body in methods.items():
        if signature.startswith("bool AsyncClient::connect("):
            definitions += signature + "{" + body + "}\n"
    return PREFIX + definitions + r'''
static int fail(const char *s) { std::cerr << "FAIL: " << s << "\n"; return 1; }
static AsyncClient *accepted = nullptr;
static int observed[2] = {};
static void on_error(void *arg, AsyncClient *, int8_t err) {
  if (in_lwip) ++wrong_context;
  observed[*static_cast<int *>(arg)] = err;
  ++error_callbacks;
}
static void on_disconnect(void *, AsyncClient *c) {
  if (in_lwip) ++wrong_context;
  ++disconnect_callbacks;
  delete c;
}
static void drain() {
  while (auto e = _async_queue.pop_front()) AsyncTCP_detail::handle_async_event(e);
}
static int scenario() {
  _start_async_task();
  reset_alloc(); abort_count = unexpected_error_callback = error_callbacks = disconnect_callbacks = 0;
  AsyncServer server(0); server._connect_cb = [](void *, AsyncClient *c) { accepted = c; };
  tcp_pcb pcb;
  fail_at = 3;
  if (AsyncTCP_detail::tcp_accept(&server, &pcb, 0) != ERR_ABRT) return fail("accept failure not rejected");
  if (abort_count != 1 || unexpected_error_callback != 0) return fail("failed accept left callback bound");
  if (live_count != 0) return fail("failed accept leaked client or event");
  reset_alloc(); fail_next();
  pcb = {};
  AsyncClient initial(&pcb);
  if (initial.pcb() != nullptr || pcb.arg || live_count != 0) return fail("initial reserve failure bound pcb or leaked");
  reset_alloc(); abort_count = unexpected_error_callback = error_callbacks = disconnect_callbacks = 0;
  tcp_pcb pcbs[2];
  AsyncClient *clients[2];
  int indexes[2] = {0, 1};
  for (int i = 0; i != 2; ++i) {
    if (AsyncTCP_detail::tcp_accept(&server, &pcbs[i], 0) != ERR_OK) return fail("normal accept failed");
    drain();
    clients[i] = accepted;
    if (!clients[i] || !clients[i]->pcb()) return fail("accepted client not delivered");
    clients[i]->_error_cb = on_error;
    clients[i]->_error_cb_arg = &indexes[i];
    clients[i]->_discard_cb = on_disconnect;
  }
  fail_all();
  auto before = attempts;
  in_lwip = true;
  for (int i = 0; i != 2; ++i) AsyncTCP_detail::tcp_error(clients[i], i ? -8 : -3);
  in_lwip = false;
  if (attempts != before) return fail("terminal error attempted allocation");
  if (_async_queue.size() != 2) return fail("error event was not queued");
  if (error_callbacks || disconnect_callbacks) return fail("callbacks ran before async dispatch");
  drain();
  if (wrong_context || error_callbacks != 2 || disconnect_callbacks != 2 || observed[0] != -3 || observed[1] != -8)
    return fail("queued error callbacks count/context/payload mismatch");
  if (live_count != 0) return fail("normal teardown leaked");

  reset_alloc();
  {
    AsyncClient outgoing;
    fail_all();
    if (outgoing.connect(0, 80) || outgoing.connect("test", 80)) return fail("outgoing accepted without error reserve");
    reset_alloc();
    if (!outgoing.connect(0, 80)) return fail("outgoing admission failed");
    before = attempts;
    if (!outgoing.connect("test", 80) || attempts != before) return fail("duplicate reservation allocated");
    AsyncTCP_detail::tcp_error(&outgoing, -4);
    drain();
    if (outgoing._error_event) return fail("error reservation ownership not transferred");
    if (!outgoing.connect("test", 80) || !outgoing._error_event) return fail("reconnect did not reserve new error event");
  }
  if (live_count) return fail("reconnect teardown leaked");
  reset_alloc();
  auto pending = new AsyncClient(&pcbs[0]);
  AsyncTCP_detail::tcp_error(pending, -6);
  delete pending;
  if (_async_queue.size() || live_count) return fail("deleted client retained queued error");
  return 0;
}
int main() { try { return scenario(); } catch (const std::bad_alloc &) { return fail("allocation escaped cleanup path"); } }
'''


def run(methods: dict[str, str]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-async-tcp-") as tmp:
        root = Path(tmp)
        cpp, exe = root / "harness.cpp", root / "harness"
        cpp.write_text(harness(methods), encoding="utf-8")
        build = subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-variable", str(cpp), "-o", str(exe)], capture_output=True, text=True)
        if build.returncode:
            return build.returncode, build.stderr
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr


def main() -> int:
    try:
        methods = parts()
    except ValueError as exc:
        print(f"async TCP error cleanup smoke FAILED: {exc}", file=sys.stderr)
        return 1
    errors = []
    code, output = run(methods)
    if code:
        print("async TCP error cleanup smoke FAILED: baseline: " + output.strip(), file=sys.stderr)
        return 1
    mutations = (
        ("delete client removed", "int8_t AsyncTCP_detail::tcp_accept", "delete c;", "(void)c;"),
        ("error event allocation returned", "void AsyncTCP_detail::tcp_error", "lwip_tcp_event_packet_t *e = client->_error_event;", "lwip_tcp_event_packet_t *e = new (std::nothrow) lwip_tcp_event_packet_t{LWIP_TCP_ERROR, client}; if (!e) return;"),
        ("error transfer removed", "void AsyncTCP_detail::tcp_error", "client->_error_event = nullptr;", "(void)0;"),
        ("accept callback reset removed", "int8_t AsyncTCP_detail::tcp_accept", "_reset_tcp_callbacks(pcb, c);", "(void)&_reset_tcp_callbacks;"),
        ("initial reserve failure ignored", "AsyncClient::AsyncClient", "if (!_reserve_error_event())", "if (!_reserve_error_event() && false)"),
        ("outgoing IP reserve bypassed", "bool AsyncClient::connect(ip_addr_t", "if (!_reserve_error_event())", "if (false)"),
        ("outgoing DNS reserve bypassed", "bool AsyncClient::connect(const char", "if (!_reserve_error_event())", "if (false)"),
        ("pending cleanup removed", "AsyncClient::~AsyncClient", "_remove_events_for_client(this);", "(void)0;"),
    )
    for name, prefix, old, new in mutations:
        mutated = dict(methods)
        key = next(k for k in mutated if k.startswith(prefix))
        if old not in mutated[key]:
            errors.append(f"{name}: mutation token not found: {old}")
            continue
        mutated[key] = mutated[key].replace(old, new, 1)
        code, output = run(mutated)
        if code == 0 or "FAIL:" not in output:
            errors.append(f"{name}: mutation survived without semantic FAIL")
        else:
            print(f"  {name}: {output.strip()}")
    if errors:
        print("async TCP error cleanup smoke FAILED: " + "; ".join(errors), file=sys.stderr)
        return 1
    print("async TCP error cleanup checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
