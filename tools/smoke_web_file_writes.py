#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
ws_file = ROOT / "WebServer.ino"
if not ws_file.exists():
  print("ERROR: WebServer.ino not found")
  sys.exit(1)

errors = []
text = ws_file.read_text(encoding="utf-8", errors="ignore")

try:
  atomic_body = extract_function_body(text, "static bool write_web_file_atomic")
except ValueError as exc:
  errors.append(str(exc))
  atomic_body = ""

if atomic_body:
  require_ordered_tokens(
    "write_web_file_atomic stages and verifies tmp before final replace",
    atomic_body,
    [
      'String tmpPath = path + ".tmp";',
      'String backupPath = path + ".bak";',
      "SPIFFS.open(tmpPath, FILE_WRITE)",
      "wf.write((const uint8_t*)content.c_str(), content.length())",
      "written != content.length()",
      "SPIFFS.open(tmpPath, FILE_READ)",
      "rf.size()",
      "tmpSize != content.length()",
      "SPIFFS.exists(path)",
      "SPIFFS.rename(path, backupPath)",
      "SPIFFS.rename(tmpPath, path)",
      "SPIFFS.rename(backupPath, path)",
    ],
    errors,
  )
  if re.search(r"SPIFFS\.open\s*\(\s*path\s*,\s*FILE_WRITE\s*\)", atomic_body):
    errors.append("write_web_file_atomic writes directly to final path")
  if re.search(r"SPIFFS\.remove\s*\(\s*path\s*\)", atomic_body):
    errors.append("write_web_file_atomic removes final path on write failure")
  if "SPIFFS.remove(tmpPath)" not in atomic_body:
    errors.append("write_web_file_atomic does not clean tmp path on failure")
else:
  if "write_spiffs_file_checked" in text:
    errors.append("legacy write_spiffs_file_checked is still present")

if "write_spiffs_file_checked" in text:
  errors.append("legacy write_spiffs_file_checked is still used/present")

try:
  get_web_file_body = extract_function_body(text, "String get_web_file")
except ValueError as exc:
  errors.append(str(exc))
  get_web_file_body = ""

if get_web_file_body:
  if re.search(r"SPIFFS\.open\s*\(\s*\"/\"\s*\+\s*fn\s*,\s*FILE_WRITE\s*\)", get_web_file_body):
    errors.append("get_web_file writes directly through SPIFFS.open(\"/\" + fn)")
  if 'write_web_file_atomic("/" + fn, s)' not in get_web_file_body:
    errors.append("get_web_file does not use write_web_file_atomic for SAVE_FILE_*")
  require_ordered_tokens(
    "get_web_file rejects empty web update downloads before returning/writing",
    get_web_file_body,
    [
      "String s = http_sync_request_get(url);",
      'if (s == "<ERR>")',
      "web_file_content_empty_invalid(fn, type, s)",
      "if (type == GET_CONTENT)",
      'write_web_file_atomic("/" + fn, s)',
    ],
    errors,
  )

try:
  empty_body = extract_function_body(text, "static bool web_file_content_empty_invalid")
except ValueError as exc:
  errors.append(str(exc))
  empty_body = ""

if empty_body:
  for token in [
    "content.length() != 0",
    "type == GET_CONTENT",
    "type == SAVE_FILE_OVERRIDE",
    "type == SAVE_FILE_IF_NOT_EXIST",
    "empty body",
    "return true;",
  ]:
    if token not in empty_body:
      errors.append(f"empty body guard missing token: {token}")

try:
  interface_body = extract_function_body(text, "void get_web_interface")
except ValueError as exc:
  errors.append(str(exc))
  interface_body = ""

if interface_body:
  try:
    update_ok_body, update_ok_end = extract_braced_block_after(interface_body, "if (updateOk)")
    after_update_ok = interface_body[update_ok_end:]
  except ValueError as exc:
    errors.append(str(exc))
    update_ok_body = ""
    after_update_ok = ""
  if update_ok_body:
    if 'write_web_file_atomic("/version.txt", versionMarker)' not in update_ok_body:
      errors.append("version marker is not written with write_web_file_atomic inside updateOk")
    if "updateOk = false;" not in update_ok_body:
      errors.append("version marker write failure does not clear updateOk")
  if 'write_web_file_atomic("/version.txt"' in after_update_ok:
    errors.append("version marker can be written after updateOk block")
  if 'Serial.println("WEB interface update aborted; local version marker was not changed.")' not in interface_body:
    errors.append("get_web_interface does not log final update failure")
  if 'Serial.println("WEB interface update failed on version.txt")' not in interface_body:
    errors.append("get_web_interface does not log version download failure")

if errors:
  print("ERROR: web file write smoke failed")
  for error in errors:
    print(f"- {error}")
  sys.exit(1)

print("OK: web file writes are atomic and fail closed")
