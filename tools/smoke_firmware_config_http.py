#!/usr/bin/env python3
"""Проверяет GET /firmware-config и единый writer JSON конфигурации."""

from pathlib import Path

from smoke_helpers import extract_braced_block_after, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
WEBSERVER = ROOT / "WebServer.ino"
REPORT = ROOT / "firmware_config_report.h"


def route_errors(source: str) -> list[str]:
    errors: list[str] = []
    token = 'server.on("/firmware-config", HTTP_GET,'
    if source.count(token) != 1:
        return ["/firmware-config must be registered exactly once as GET"]
    try:
        body, _ = extract_braced_block_after(source, token)
    except ValueError as error:
        return [str(error)]
    require_ordered_tokens(
        "/firmware-config request contract",
        body,
        [
            "request->params() != 0",
            'send_no_store_response(request, 400, "text/plain", "BAD_REQUEST")',
            "AsyncResponseStream *response = request->beginResponseStream(\"application/json\")",
            'response->addHeader("Cache-Control", "no-store")',
            "write_firmware_config_json(*response)",
            "delete response",
            'send_no_store_response(request, 503, "text/plain", "BUSY")',
            "request->send(response)",
        ],
        errors,
    )
    for forbidden in ("SPIFFS", "nvs_", "Wire.", "delay(", "queue_", "Preferences", "auth"):
        if forbidden in body:
            errors.append("/firmware-config async handler contains forbidden token: " + forbidden)
    return errors


def writer_errors(source: str) -> list[str]:
    errors: list[str] = []
    try:
        body, _ = extract_braced_block_after(source, "inline bool write_firmware_config_json(Print& out)")
    except ValueError as error:
        return [str(error)]
    require_ordered_tokens(
        "shared firmware config writer",
        body,
        [
            '"type", "samovar_firmware_config"',
            '"schema", 1',
            '"settings"',
            '"wifi_ssid"',
            '"wifi_password"',
        ],
        errors,
    )
    if "Serial" in body:
        errors.append("shared firmware config writer must not own a transport")
    return errors


def replace_after(source: str, marker: str, old: str, new: str) -> str:
    start = source.find(marker)
    if start < 0:
        return source
    return source[:start] + source[start:].replace(old, new)


def main() -> int:
    errors: list[str] = []
    webserver = WEBSERVER.read_text(encoding="utf-8")
    report = REPORT.read_text(encoding="utf-8")
    if '#include "firmware_config_report.h"' not in webserver:
        errors.append("WebServer.ino does not include the shared firmware config writer")
    errors.extend(route_errors(webserver))
    errors.extend(writer_errors(report))

    mutations = (
        (
            webserver,
            'server.on("/firmware-config", HTTP_GET,',
            'request->params() != 0',
            "false",
            route_errors,
            "query parameter rejection",
        ),
        (
            webserver,
            'server.on("/firmware-config", HTTP_GET,',
            "write_firmware_config_json(*response)",
            "false",
            route_errors,
            "shared writer invocation",
        ),
        (
            report,
            "inline bool write_firmware_config_json(Print& out)",
            '"schema", 1',
            '"schema", 2',
            writer_errors,
            "schema version",
        ),
        (
            report,
            "inline bool write_firmware_config_json(Print& out)",
            '"wifi_password"',
            '"password_removed"',
            writer_errors,
            "password field",
        ),
    )
    for source, marker, old, new, check, label in mutations:
        mutant = replace_after(source, marker, old, new)
        if mutant == source:
            errors.append("mutation target missing: " + label)
        elif not check(mutant):
            errors.append("test did not reject mutation: " + label)

    if errors:
        print("FAIL: " + "\nFAIL: ".join(errors))
        return 1
    print("Firmware config HTTP route checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
