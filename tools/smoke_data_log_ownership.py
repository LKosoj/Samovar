#!/usr/bin/env python3
import sys
import re
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

SKIP_DIRS = {
    ".git",
    ".pio",
    ".ai-docs",
    "ai_docs_site",
    "libraries",
    "pro_mini_ntc",
}


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_route_handler_body(text: str, route: str) -> str:
    marker = f'server.on("{route}"'
    start = text.find(marker)
    if start == -1:
        raise ValueError(f"route {route} not found")
    lambda_start = text.find("[]", start)
    if lambda_start == -1:
        raise ValueError(f"route {route} lambda not found")
    brace_start = text.find("{", lambda_start)
    if brace_start == -1:
        raise ValueError(f"route {route} body not found")
    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start + 1:i]
    raise ValueError(f"route {route} body is not closed")


fs_ino = read_text("FS.ino")
samovar_ino = read_text("Samovar.ino")
webserver_ino = read_text("WebServer.ino")
api_h = read_text("samovar_api.h")

if fs_ino:
    for token in [
        "static File fileToAppend;",
        "static volatile bool data_log_ready = false;",
        "bool request_data_log_close()",
        "void process_pending_data_log_ops()",
    ]:
        if token not in fs_ino:
            errors.append(f"FS.ino missing data-log ownership token: {token}")

    try:
        close_body = extract_function_body(fs_ino, "bool close_data_log()")
        require_ordered_tokens(
            "close_data_log only marks unavailable after lock",
            close_body,
            [
                "bool locked = log_file_lock",
                "if (!locked)",
                "return false;",
                "data_log_ready = false;",
                "fileToAppend.close();",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        create_body = extract_function_body(fs_ino, "bool create_data()")
        if re.search(r"(?<![A-Za-z0-9_])append_data\s*\(", create_body):
            errors.append("create_data must not call append_data directly")
        for token in [
            "SteamSensor.LogPrevTemp = 0;",
            "PipeSensor.LogPrevTemp = 0;",
            "WaterSensor.LogPrevTemp = 0;",
            "TankSensor.LogPrevTemp = 0;",
            "pending_log_close_flag = false;",
        ]:
            if token not in create_body:
                errors.append(f"create_data missing log-state reset: {token}")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        request_close_body = extract_function_body(fs_ino, "bool request_data_log_close()")
        require_ordered_tokens(
            "request_data_log_close queues close under pending lock",
            request_close_body,
            [
                "bool locked = pending_command_lock",
                "if (!locked)",
                "return false;",
                "pending_log_close_flag = true;",
                "pending_log_flush_flag = false;",
                "pending_log_flush_seq = 0;",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        process_body = extract_function_body(fs_ino, "void process_pending_data_log_ops()")
        require_ordered_tokens(
            "process_pending_data_log_ops close supersedes flush",
            process_body,
            [
                "if (pending_log_close_flag)",
                "hasPendingLogClose = true;",
                "else if (pending_log_flush_flag)",
                "logFlushSeq = pending_log_flush_seq;",
                "hasPendingLogFlush = true;",
                "if (hasPendingLogClose)",
                "if (!close_data_log())",
                "return;",
                "pending_log_close_flag = false;",
                "pending_log_flush_flag = false;",
                "if (hasPendingLogFlush)",
                "if (!flush_data_log())",
                "pending_log_flush_seq <= logFlushSeq",
                "pending_log_flush_flag = false;",
            ],
            errors,
        )
        close_snapshot = process_body.find("if (pending_log_close_flag)")
        close_clear = process_body.find("pending_log_close_flag = false;")
        close_call = process_body.find("if (!close_data_log())")
        if close_snapshot == -1 or close_call == -1 or close_clear == -1 or close_clear < close_call:
            errors.append("process_pending_data_log_ops must clear close flag only after close_data_log succeeds")
        flush_snapshot = process_body.find("else if (pending_log_flush_flag)")
        flush_clear = process_body.find("pending_log_flush_flag = false;", process_body.find("if (hasPendingLogFlush)"))
        flush_call = process_body.find("if (!flush_data_log())")
        if flush_snapshot == -1 or flush_call == -1 or flush_clear == -1 or flush_clear < flush_call:
            errors.append("process_pending_data_log_ops must clear flush flag only after flush_data_log succeeds")
    except ValueError as exc:
        errors.append(str(exc))

if samovar_ino:
    if "volatile bool pending_log_close_flag = false;" not in samovar_ino:
        errors.append("Samovar.ino missing pending_log_close_flag")
    try:
        ticker_body = extract_function_body(samovar_ino, "void triggerSysTicker(void *parameter)")
        require_ordered_tokens(
            "triggerSysTicker owns pending data-log ops before append",
            ticker_body,
            [
                "process_pending_data_log_ops();",
                "if (startval != SAMOVAR_STARTVAL_IDLE)",
                "append_data();",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        loop_body = extract_function_body(samovar_ino, "void loop()")
        for token in ["pending_log_flush_flag", "flush_data_log()", "close_data_log()"]:
            if token in loop_body:
                errors.append(f"loop must not consume data-log ops directly: {token}")
    except ValueError as exc:
        errors.append(str(exc))

if webserver_ino:
    try:
        schedule_body = extract_function_body(webserver_ino, "static uint8_t schedule_log_flush_if_needed()")
        require_ordered_tokens(
            "schedule_log_flush_if_needed exposes ready/queued/busy state",
            schedule_body,
            [
                "if (log_flush_seq >= log_write_seq) return LOG_FLUSH_READY;",
                "bool locked = pending_command_lock",
                "if (!locked) return LOG_FLUSH_BUSY;",
                "pending_log_flush_flag = true;",
                "return LOG_FLUSH_QUEUED;",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        data_csv_body = extract_route_handler_body(webserver_ino, "/data.csv")
        require_ordered_tokens(
            "/data.csv serves only after ready flush state",
            data_csv_body,
            [
                "schedule_log_flush_if_needed() != LOG_FLUSH_READY",
                'request->send(503, "text/plain", "BUSY")',
                'request->send(SPIFFS, "/data.csv"',
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))
    try:
        get_data_log_body = extract_function_body(webserver_ino, "void get_data_log(AsyncWebServerRequest *request, String fn)")
        require_ordered_tokens(
            "get_data_log serves only after ready flush state",
            get_data_log_body,
            [
                "schedule_log_flush_if_needed() != LOG_FLUSH_READY",
                'request->send(503, "text/plain", "BUSY")',
                "request->beginResponse(SPIFFS",
            ],
            errors,
        )
    except ValueError as exc:
        errors.append(str(exc))

if api_h:
    for token in ["bool request_data_log_close();", "void process_pending_data_log_ops();"]:
        if token not in api_h:
            errors.append(f"samovar_api.h missing data-log API: {token}")
    for token in ["bool flush_data_log();", "bool close_data_log();"]:
        if token in api_h:
            errors.append(f"samovar_api.h exposes owner-only data-log helper: {token}")

for path in ROOT.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(ROOT)
    if any(part.startswith(".") for part in rel.parts):
        continue
    if any(part in SKIP_DIRS for part in rel.parts):
        continue
    if path.name == "FS.ino":
        continue
    if rel.parts[0] == "tools" and path.name.startswith("smoke_"):
        continue
    if rel.as_posix() == "tools/smoke_data_log_ownership.py":
        continue
    if path.suffix not in {".ino", ".h", ".cpp", ".hpp", ".py"}:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "fileToAppend" in text:
        errors.append(f"{rel} accesses fileToAppend outside FS.ino")
    if "fileToAppend.flush(" in text or "fileToAppend.close(" in text or "fileToAppend.println(" in text:
        errors.append(f"{rel} performs direct data-log file operation outside FS.ino")
    if re.search(r"(?<![A-Za-z0-9_])flush_data_log\s*\(", text):
        errors.append(f"{rel} calls owner-only flush_data_log outside FS.ino")
    if re.search(r"(?<![A-Za-z0-9_])close_data_log\s*\(", text):
        errors.append(f"{rel} calls owner-only close_data_log outside FS.ino")
    if re.search(r"(?<![A-Za-z0-9_])append_data\s*\(", text):
        if rel.as_posix() == "samovar_api.h":
            continue
        if rel.as_posix() == "Samovar.ino":
            try:
                ticker_body = extract_function_body(text, "void triggerSysTicker(void *parameter)")
            except ValueError:
                errors.append("Samovar.ino append_data call found but triggerSysTicker body was not parsed")
                continue
            if len(re.findall(r"(?<![A-Za-z0-9_])append_data\s*\(", ticker_body)) != 1:
                errors.append("Samovar.ino must call append_data exactly once inside triggerSysTicker")
            outside_ticker = text.replace(ticker_body, "")
            if re.search(r"(?<![A-Za-z0-9_])append_data\s*\(", outside_ticker):
                errors.append("Samovar.ino calls append_data outside triggerSysTicker")
            continue
        errors.append(f"{rel} calls append_data outside triggerSysTicker")

if errors:
    print("Data log ownership smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("Data log ownership smoke check passed")
