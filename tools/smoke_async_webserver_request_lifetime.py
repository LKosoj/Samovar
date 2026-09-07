#!/usr/bin/env python3
"""Проверяет backport защиты HTTP-запроса для AsyncTCP 3.5.0."""

import sys
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "libraries" / "ESP_Async_WebServer" / "src"


def validate(header: str, request: str, server: str) -> list[str]:
    errors = []
    try:
        factory = extract_function_body(
            header, "static std::shared_ptr<AsyncWebServerRequest> create("
        )
        on_data = extract_function_body(request, "void AsyncWebServerRequest::_onData(")
        on_poll = extract_function_body(request, "void AsyncWebServerRequest::_onPoll()")
        on_ack = extract_function_body(request, "void AsyncWebServerRequest::_onAck(")
        on_disconnect = extract_function_body(
            request, "void AsyncWebServerRequest::_onDisconnect()"
        )
        constructor = extract_function_body(
            server, "AsyncWebServer::AsyncWebServer(uint16_t port)"
        )
    except ValueError as exc:
        return [str(exc)]

    required = {
        "factory owns request": "req->_this = std::shared_ptr<AsyncWebServerRequest>(req)",
        "data callback keeps request alive": "std::shared_ptr<AsyncWebServerRequest> self = _this;",
        "poll callback keeps request alive": "std::shared_ptr<AsyncWebServerRequest> self = _this;",
        "ack callback keeps request alive": "std::shared_ptr<AsyncWebServerRequest> self = _this;",
        "disconnect releases owner last": "std::shared_ptr<AsyncWebServerRequest> self = std::move(_this);",
        "server uses owning factory": "AsyncWebServerRequest::create(static_cast<AsyncWebServer *>(s), c)",
    }
    sources = {
        "factory owns request": factory,
        "data callback keeps request alive": on_data,
        "poll callback keeps request alive": on_poll,
        "ack callback keeps request alive": on_ack,
        "disconnect releases owner last": on_disconnect,
        "server uses owning factory": constructor,
    }
    for name, token in required.items():
        if sources[name].count(token) != 1:
            errors.append(name)

    forbidden = {
        "manual request deletion": "delete request;",
        "disconnect delete callback": "_server->_handleDisconnect(this);",
        "non-owning paused request": "std::shared_ptr<AsyncWebServerRequest>(this, doNotDelete)",
    }
    combined = header + request + server
    for name, token in forbidden.items():
        if token in combined:
            errors.append(name)
    return errors


header = (LIB / "ESPAsyncWebServer.h").read_text(encoding="utf-8")
request = (LIB / "WebRequest.cpp").read_text(encoding="utf-8")
server = (LIB / "WebServer.cpp").read_text(encoding="utf-8")

errors = validate(header, request, server)
if errors:
    print("async webserver request lifetime smoke FAILED: " + ", ".join(errors), file=sys.stderr)
    sys.exit(1)

mutated_request = request.replace(
    "std::shared_ptr<AsyncWebServerRequest> self = std::move(_this);",
    "_server->_handleDisconnect(this);",
    1,
)
if not validate(header, mutated_request, server):
    print("async webserver request lifetime smoke FAILED: lifetime mutation survived", file=sys.stderr)
    sys.exit(1)

mutated_server = server.replace(
    "AsyncWebServerRequest::create(static_cast<AsyncWebServer *>(s), c)",
    "new AsyncWebServerRequest((AsyncWebServer *)s, c)",
    1,
)
if not validate(header, request, mutated_server):
    print("async webserver request lifetime smoke FAILED: factory mutation survived", file=sys.stderr)
    sys.exit(1)

print("async webserver request lifetime checks passed")
