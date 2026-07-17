#!/usr/bin/env python3
import gzip
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "data_raw" / "style.css"
# .gz - продукт сборки: в data/ сырого style.css уже нет, он уезжает только сжатым.
STYLE_GZ = ROOT / "data" / "style.css.gz"

errors = []

if not STYLE.exists():
  errors.append("data/style.css not found")
  css = ""
else:
  css = STYLE.read_text(encoding="utf-8", errors="ignore")

if css:
  for forbidden in [
    ".prgline input,\nimg,\nselect",
    ".prgline input:enabled,\nimg,\nselect",
  ]:
    if forbidden in css:
      errors.append(f"style.css still has global prgline selector: {forbidden!r}")
  for token in [
    ".prgline input,\n.prgline .program-row-action,\n.prgline select",
    ".prgline input:enabled,\n.prgline .program-row-action,\n.prgline select",
  ]:
    if token not in css:
      errors.append(f"style.css missing scoped prgline selector: {token!r}")

  message_box_rules = [
    match.group("selector")
    for match in re.finditer(r"(?P<selector>[^{}]*\.messages_box[^{}]*)\{", css)
  ]
  if not message_box_rules:
    errors.append("style.css missing .messages_box rules")
  for selector in message_box_rules:
    if ".message-box" not in selector:
      errors.append(f"style.css .messages_box rule is not aliased to .message-box: {selector.strip()}")

  for selector in [
    ".card-bordered",
    ".card-padded",
    ".row-between",
    ".row-around",
    ".text-center",
    ".bold",
    ".button_mob",
    ".button_img",
    ".pointer",
    ".infotext",
  ]:
    if selector in css:
      errors.append(f"style.css still contains removed dead selector {selector}")

  active_bg_values = [value.strip().lower() for value in re.findall(r"--state-active-bg\s*:\s*([^;]+);", css)]
  if not active_bg_values:
    errors.append("style.css missing --state-active-bg")
  else:
    for active_bg in active_bg_values:
      if active_bg == "lightgreen":
        errors.append("--state-active-bg still uses low-contrast lightgreen")
      if active_bg != "#2f7d4a":
        errors.append(f"--state-active-bg expected #2f7d4a, got {active_bg}")

if STYLE.exists() and STYLE_GZ.exists():
  try:
    if gzip.decompress(STYLE_GZ.read_bytes()) != STYLE.read_bytes():
      errors.append("data/style.css.gz is not synchronized with data_raw/style.css")
  except OSError as exc:
    errors.append(f"data/style.css.gz is not valid gzip: {exc}")
elif STYLE.exists():
  errors.append("data/style.css.gz not found")

if errors:
  print("Style cleanup smoke check failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)

print("Style cleanup smoke check passed")
