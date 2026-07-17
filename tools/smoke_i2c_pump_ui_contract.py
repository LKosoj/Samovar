#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
APP_JS = DATA / "app.js"
BROWSER_HARNESS = ROOT / "tools" / "test_i2c_pump_ui_browser.py"
PAGES = [
  DATA / "index.htm",
  DATA / "beer.htm",
  DATA / "distiller.htm",
  DATA / "bk.htm",
  DATA / "nbk.htm",
]
ELEMENT_IDS = ["i2c_pump_status", "i2c_status", "i2c_remaining", "i2c_speed_cur"]
RENDER_CALL = "SamovarApp.renderI2cPumpStatus(myObj);"


def read_text(path):
  return path.read_text(encoding="utf-8", errors="ignore")


def check_app(errors):
  text = read_text(APP_JS)
  try:
    renderer = extract_function_body(text, "function renderI2cPumpStatus(data)")
    required_lookup = extract_function_body(text, "function requiredI2cPumpElement(id)")
  except ValueError as exc:
    errors.append(str(exc))
    return

  required_bindings = [
    ("panel", "i2c_pump_status"),
    ("status", "i2c_status"),
    ("remaining", "i2c_remaining"),
    ("speed", "i2c_speed_cur"),
  ]
  for variable, element_id in required_bindings:
    token = f"const {variable} = requiredI2cPumpElement('{element_id}');"
    if token not in renderer:
      errors.append(f"data_raw/app.js renderer does not unconditionally require #{element_id}")
  renderer_tokens = [
    "panel.hidden = !present;",
    "data.i2c_pump_present === 1",
    "data.i2c_pump_running === 1",
    "status.textContent = present",
    ": 'Не подключён';",
    "remaining.textContent = present ? data.i2c_pump_remaining_ml : '0';",
    "speed.textContent = present ? data.i2c_pump_speed : '0';",
  ]
  for token in renderer_tokens:
    if token not in renderer:
      errors.append(f"data_raw/app.js missing I2C pump contract token: {token}")

  lookup_positions = [
    renderer.find(f"const {variable} = requiredI2cPumpElement('{element_id}');")
    for variable, element_id in required_bindings
  ]
  assignment_positions = [
    renderer.find("panel.hidden = !present;"),
    renderer.find("status.textContent = present"),
    renderer.find("remaining.textContent = present"),
    renderer.find("speed.textContent = present"),
  ]
  if min(lookup_positions + assignment_positions) >= 0 and max(lookup_positions) > min(assignment_positions):
    errors.append("data_raw/app.js I2C pump renderer assigns fields before requiring every mount")

  if "throw new Error(" not in required_lookup:
    errors.append("data_raw/app.js required I2C mount lookup does not fail explicitly")
  for forbidden, description in [
    ("innerHTML", "innerHTML"),
    ("insertAdjacentHTML", "insertAdjacentHTML"),
    ("eval(", "eval"),
    ("?.", "optional chaining"),
  ]:
    if forbidden in renderer:
      errors.append(f"data_raw/app.js I2C pump renderer uses {description}")
  if "renderI2cPumpStatus: renderI2cPumpStatus" not in text:
    errors.append("data_raw/app.js does not export renderI2cPumpStatus")


def check_pages(errors):
  for page in PAGES:
    text = read_text(page)
    rel = page.relative_to(ROOT)
    if text.count(RENDER_CALL) != 1:
      errors.append(f"{rel} must call the shared I2C pump renderer exactly once")
    if re.search(r"if\s*\(\s*myObj\.i2c_pump_present", text):
      errors.append(f"{rel} still contains a local I2C pump renderer")
    if "document.getElementById('i2c_" in text or 'document.getElementById("i2c_' in text:
      errors.append(f"{rel} still writes I2C pump DOM fields directly")

    for element_id in ELEMENT_IDS:
      count = len(re.findall(r"\bid\s*=\s*['\"]" + re.escape(element_id) + r"['\"]", text))
      if count != 1:
        errors.append(f"{rel} must contain exactly one #{element_id}, found {count}")

    section = re.search(r"<section\b[^>]*\bid\s*=\s*['\"]i2c_pump_status['\"][^>]*>", text, flags=re.I)
    if not section:
      errors.append(f"{rel} does not use a section for the I2C pump status mount")
    elif "aria-label=" not in section.group(0) or not re.search(r"\bhidden\b", section.group(0)):
      errors.append(f"{rel} I2C pump status mount must be labelled and initially hidden")

    call_pos = text.find(RENDER_CALL)
    power_pos = text.find("document.getElementById('power').value", call_pos)
    if call_pos == -1 or power_pos == -1:
      errors.append(f"{rel} does not prove rendering continues from I2C status to power state")


def check_browser_harness(errors):
  text = read_text(BROWSER_HARNESS)
  for token in [
    'PowerOn: 1',
    'document.getElementById("power").value === "Выключить нагрев"',
    'const remainingAttack = \'<img src=x onerror="window.__i2cInjected=1">\';',
    'const speedAttack = \'<img src=x onerror="window.__i2cInjected=2">\';',
    'primary_error = None',
    'cleanup_errors = []',
    'server.shutdown()',
    'server.server_close()',
    'thread.join(timeout=5)',
  ]:
    if token not in text:
      errors.append(f"tools/test_i2c_pump_ui_browser.py missing browser gate token: {token}")


def main():
  errors = []
  check_app(errors)
  check_pages(errors)
  check_browser_harness(errors)
  if errors:
    print("I2C pump UI contract smoke failed:")
    for error in errors:
      print(f"- {error}")
    return 1
  print("I2C pump UI contract smoke passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
