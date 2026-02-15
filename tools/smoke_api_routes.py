#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ws_file = ROOT / "WebServer.ino"
if not ws_file.exists():
    print("ERROR: WebServer.ino not found")
    sys.exit(1)

text = ws_file.read_text(encoding="utf-8", errors="ignore")

route_re = re.compile(r'server\.on\("(?P<path>/[^\"]*)"\s*,\s*(?P<method>HTTP_[A-Z| ]+)')
routes = {}
for match in route_re.finditer(text):
    path = match.group("path")
    method = match.group("method").replace(" ", "")
    routes.setdefault(path, set()).add(method)

required = {
    "/": None,
    "/ajax": "HTTP_GET",
    "/command": "HTTP_GET",
    "/program": "HTTP_POST",
    "/save": "HTTP_POST",
    "/wifi/save": "HTTP_POST",
    "/wifi/clear": "HTTP_POST",
    "/calibrate": "HTTP_GET",
    "/i2cpump": "HTTP_GET",
    "/getlog": "HTTP_GET",
}

errors = []
for path, method in required.items():
    if path not in routes:
        errors.append(f"missing route: {path}")
        continue
    if method and method not in routes[path]:
        errors.append(f"route {path} missing method {method}; found {sorted(routes[path])}")

# Streaming JSON contract for /ajax
if "send_ajax_json(request);" not in text:
    errors.append("/ajax handler does not use send_ajax_json(request)")

# Keep CORS presence visible for security review (not a hard failure)
if "Access-Control-Allow-Origin" not in text:
    errors.append("CORS header declaration missing")

if errors:
    print("API smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("API smoke check passed")
print(f"Discovered routes: {len(routes)}")
