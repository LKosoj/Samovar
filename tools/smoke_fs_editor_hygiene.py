#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, text: str, token: str) -> None:
    if token not in text:
        errors.append(f"{name} missing token: {token}")


web = strip_cpp_comments(read_text("WebServer.ino"))
editor = strip_cpp_comments(read_text("SPIFFSEditor.h"))
fs_raw = read_text("FS.ino")
fs = strip_cpp_comments(fs_raw)

if web:
    require_token("WebServer.ino pong route", web, 'server.on("/pong.htm", HTTP_GET')
    require_token("WebServer.ino pong route", web, '<!DOCTYPE html><html lang=\\"ru\\"')
    require_token("WebServer.ino pong route", web, '<audio controls autoplay src=\\"/alarm.mp3\\"></audio>')
    if 'serveStatic("/pong.htm", SPIFFS, "/alarm.mp3")' in web:
        errors.append('/pong.htm still serves alarm.mp3')

if editor:
    try:
        body = extract_function_body(editor, "bool SPIFFSEditor::canHandle")
    except ValueError as exc:
        errors.append(str(exc))
        body = ""
    if body:
        require_ordered_tokens(
            "SPIFFSEditor download opens its own argument",
            body,
            [
                'if (request->hasParam("download"))',
                'String p = request->arg("download");',
                "if (p.length() == 0)",
                "if (p[0] != '/') p = \"/\" + p;",
                'request->_tempFile = ref.open(p, "r");',
            ],
            errors,
        )
        if 'request->arg("edit")' in body.split('if (request->hasParam("download"))', 1)[-1]:
            errors.append("SPIFFSEditor download branch still reads edit argument")

if fs:
    if '"admin"' in fs or '"password"' in fs or "http_username" in fs or "http_password" in fs:
        errors.append("FS.ino keeps dead editor credentials")
    require_token(
        "FS.ino editor auth decision",
        fs_raw,
        "DIY device: /edit stays local-network only and intentionally unauthenticated.",
    )
    require_token("FS.ino editor registration", fs, "server.addHandler(new SPIFFSEditor(SPIFFS));")

if errors:
    print("FS/editor hygiene smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("FS/editor hygiene smoke passed")
