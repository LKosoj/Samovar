#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

APP_JS = DATA / "app.js"
I2CSTEPPER_PAGE = DATA / "i2cstepper.htm"
STYLE_CSS = DATA / "style.css"
PAGES = [
  DATA / "index.htm",
  DATA / "beer.htm",
  DATA / "distiller.htm",
  DATA / "nbk.htm",
  DATA / "bk.htm",
]

COMMON_FUNCTIONS = [
  "ConnectError",
  "playSound",
  "getHistory",
  "saveHistory",
  "addMessage",
  "showMessages",
  "removeLastMessage",
  "clearMessages",
  "applyTheme",
  "toggleTheme",
  "openTab",
  "escapeHtml",
  "sendbutton",
  "sendI2CPump",
  "stopI2CPump",
  "run_lua",
  "run_strlua",
]

COMMAND_TOKENS = ["OK", "BUSY", "IGNORED", "POWER_OFF", "BAD_REQUEST"]


def read_text(path):
  if not path.exists():
    return None
  return path.read_text(encoding="utf-8", errors="ignore")


def line_of(text, offset):
  return text.count("\n", 0, offset) + 1


def inline_scripts_without_app_src(text):
  blocks = []
  for match in re.finditer(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>", text, flags=re.I | re.S):
    attrs = match.group("attrs")
    if re.search(r"\bsrc\s*=", attrs, flags=re.I):
      continue
    blocks.append((match.start("body"), match.group("body")))
  return blocks


def has_app_script(text):
  return bool(re.search(r'<script\s+src=["\']app\.js["\']\s*>\s*</script>', text, flags=re.I))


def check_pages(errors):
  stale_call_re = re.compile(
    r"(?<![\w.$])(?P<name>" + "|".join(re.escape(name) for name in COMMON_FUNCTIONS) + r")\s*\("
  )

  for page in PAGES:
    text = read_text(page)
    if text is None:
      errors.append(f"{page.relative_to(ROOT)} not found")
      continue

    rel = page.relative_to(ROOT)
    if not has_app_script(text):
      errors.append(f"{rel} does not include exact app script tag: <script src=\"app.js\"></script>")

    if "ConnectError" in text:
      errors.append(f"{rel} still contains ConnectError")

    if re.search(r"<input\b[^>]*\btype\s*=\s*['\"]submit['\"]", text, flags=re.I):
      errors.append(f"{rel} still contains submit input buttons")
    if re.search(r"<button\b[^>]*\btype\s*=\s*['\"]submit['\"]", text, flags=re.I):
      errors.append(f"{rel} still contains submit button elements")
    if re.search(r"<button\b(?![^>]*\btype\s*=)", text, flags=re.I):
      errors.append(f"{rel} contains button without explicit type")
    if not re.search(r"<form\b[^>]*\bonsubmit\s*=\s*['\"]return\s+false['\"]", text, flags=re.I):
      errors.append(f"{rel} main form does not disable submit with onsubmit='return false'")
    if 'id="I2CPump"' in text or "id='I2CPump'" in text:
      errors.append(f"{rel} still contains dead I2CPump tab")

    without_comments = strip_cpp_comments(text)
    if re.search(r"\balert\s*\(", without_comments):
      errors.append(f"{rel} still contains blocking alert() in polling/alarm UI")

    for body_offset, body in inline_scripts_without_app_src(text):
      for name in COMMON_FUNCTIONS:
        definition_re = re.compile(r"\b(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(")
        for match in definition_re.finditer(body):
          errors.append(f"{rel}:{line_of(text, body_offset + match.start())} defines stale common function {name}()")

    for match in stale_call_re.finditer(text):
      name = match.group("name")
      before = text[max(0, match.start() - 32):match.start()]
      if before.endswith("SamovarApp.") or re.search(r"\bfunction\s+$", before):
        continue
      errors.append(f"{rel}:{line_of(text, match.start())} calls stale common helper {name}()")

    if re.search(r"\bfetch\s*\(\s*['\"]\/command\?", text):
      errors.append(f"{rel} calls /command through fetch() instead of SamovarApp.sendCommand()")
    if re.search(r"\bXMLHttpRequest\b|\.open\s*\(\s*['\"]GET['\"]\s*,\s*['\"]\/command\?", text):
      errors.append(f"{rel} contains legacy XMLHttpRequest /command flow")
    if "/command?" in text and "SamovarApp.sendCommand" not in text:
      errors.append(f"{rel} references /command without SamovarApp.sendCommand()")

    command_alert_re = re.compile(
      r"SamovarApp\.sendCommand\s*\([^;]*(?:;|$)(?:(?!\n\s*function\b).){0,240}?"
      r"alert\s*\(\s*['\"](?:Установлено|Ok)['\"]\s*\)",
      flags=re.S,
    )
    reverse_command_alert_re = re.compile(
      r"alert\s*\(\s*['\"](?:Установлено|Ok)['\"]\s*\)(?:(?!\n\s*function\b).){0,240}?"
      r"SamovarApp\.sendCommand\s*\(",
      flags=re.S,
    )
    if command_alert_re.search(text) or reverse_command_alert_re.search(text):
      errors.append(f"{rel} has stale success alert around SamovarApp.sendCommand()")

    if page.name == "beer.htm" and re.search(r"\bfunction\s+sendpumpspeed\s*\(", text):
      errors.append("data/beer.htm still defines dead sendpumpspeed()")
    if page.name == "nbk.htm":
      if re.search(r"\bfunction\s+sendwaterpwm\s*\(", text):
        errors.append("data/nbk.htm still defines dead sendwaterpwm()")
      for line_no, line in enumerate(text.splitlines(), start=1):
        if line.strip() == "myObj.PipeTemp.toFixed(3)":
          errors.append(f"data/nbk.htm:{line_no} still contains dangling PipeTemp.toFixed expression")
    if page.name == "bk.htm":
      if re.search(r"\bid\s*=\s*['\"]Prog['\"]", text):
        errors.append("data/bk.htm still contains unreachable Prog tab")
      if "SamovarApp.openTab(event, 'Prog')" in text or 'SamovarApp.openTab(event, "Prog")' in text:
        errors.append("data/bk.htm still links to unreachable Prog tab")


def check_app_js(errors):
  text = read_text(APP_JS)
  if text is None:
    errors.append("data/app.js not found")
    return

  if not re.search(r"\bconst\s+HISTORY_LIMIT\s*=\s*500\s*;", text):
    errors.append("data/app.js missing const HISTORY_LIMIT = 500")

  try:
    tokens_body = extract_function_body(text, "const COMMAND_TOKENS =")
  except ValueError as exc:
    errors.append(str(exc))
    tokens_body = ""
  for token in COMMAND_TOKENS:
    if not re.search(r"\b" + re.escape(token) + r"\s*:", tokens_body):
      errors.append(f"data/app.js COMMAND_TOKENS missing {token}")

  try:
    send_command_body = extract_function_body(text, "async function sendCommand(command, options)")
  except ValueError as exc:
    errors.append(str(exc))
    send_command_body = ""
  if send_command_body:
    for token in [
      "const commandBody = command.indexOf('=') === -1 ? command + '=1' : command;",
      "await fetch('/command',",
      "method: 'POST'",
      "'Content-Type': 'application/x-www-form-urlencoded'",
      "body: commandBody",
    ]:
      if token not in send_command_body:
        errors.append(f"data/app.js sendCommand() missing POST command transport token: {token}")
    if "/command?" in send_command_body or "method: 'GET'" in send_command_body:
      errors.append("data/app.js sendCommand() still uses GET /command transport")
    known_token_match = re.search(
      r"const\s+knownToken\s*=\s*([^;]*Object\.prototype\.hasOwnProperty\.call\(COMMAND_TOKENS,\s*token\)[^;]*);",
      send_command_body,
    )
    known_token_pos = known_token_match.start() if known_token_match else -1
    known_branch_pos = send_command_body.find("if (knownToken)")
    http_branch_pos = send_command_body.find("if (!resp.ok)")
    if not known_token_match:
      errors.append("data/app.js sendCommand() does not identify known command tokens")
    elif "token &&" not in known_token_match.group(1):
      errors.append("data/app.js sendCommand() known-token check does not guard empty tokens")
    if known_branch_pos == -1:
      errors.append("data/app.js sendCommand() does not branch on known command tokens")
    if http_branch_pos == -1:
      errors.append("data/app.js sendCommand() missing generic HTTP error fallback")
    if known_branch_pos != -1 and http_branch_pos != -1 and http_branch_pos < known_branch_pos:
      errors.append("data/app.js sendCommand() handles HTTP errors before known command tokens")
    if "addMessage(result.text, result.level);" not in send_command_body:
      errors.append("data/app.js sendCommand() does not render non-OK command tokens with result.level")
    if re.search(
      r"body\s*\|\|\s*\(\s*resp\.ok\s*\?\s*['\"]OK['\"]\s*:\s*['\"]BAD_REQUEST['\"]\s*\)",
      send_command_body,
    ):
      errors.append("data/app.js sendCommand() synthesizes BAD_REQUEST for empty HTTP errors")

  try:
    play_body = extract_function_body(text, "function playSound(play)")
  except ValueError as exc:
    errors.append(str(exc))
    play_body = ""
  if play_body and not re.search(r"\.play\s*\(\s*\)[\s\S]*\.catch\s*\(", play_body):
    errors.append("data/app.js playSound() does not catch play() rejection")

  try:
    unlock_body = extract_function_body(text, "function unlockAudio()")
  except ValueError as exc:
    errors.append(str(exc))
    unlock_body = ""
  if unlock_body:
    for token in ["soundPlaying = false;", "if (soundEnabled && alarmActive) playSound(true);"]:
      if token not in unlock_body:
        errors.append(f"data/app.js unlockAudio() missing active-alarm resume token: {token}")

  if "getHistory().map(renderHistoryEntry).join('')" not in text:
    errors.append("data/app.js history render does not use map(...).join('')")
  if "messages.map(renderMessage).join('')" not in text:
    errors.append("data/app.js message render does not use map(...).join('')")
  if re.search(r"\.innerHTML\s*\+=", text):
    errors.append("data/app.js contains innerHTML +=")
  if "function cssVar(name)" not in text or "cssVar: cssVar" not in text:
    errors.append("data/app.js missing shared cssVar() helper/export for theme tokens")
  for token in [
    "function pushMessage(msg, level)",
    "function notify(msg, level)",
    "notify: notify",
  ]:
    if token not in text:
      errors.append(f"data/app.js missing nonblocking notify token: {token}")
  for token in ["sendI2CPump", "stopI2CPump", "/i2cpump"]:
    if token in text:
      errors.append(f"data/app.js still contains dead I2C pump helper token: {token}")

  try:
    poll_body = extract_function_body(text, "async function pollAjax(renderFn)")
  except ValueError as exc:
    errors.append(str(exc))
    poll_body = ""
  if poll_body:
    if "reportUiError(err)" not in poll_body:
      errors.append("data/app.js pollAjax() does not report DOM render errors through reportUiError(err)")
    if "setConnectionError" in poll_body:
      errors.append("data/app.js pollAjax() catches DOM render errors through setConnectionError")


def check_theme_tokens_w68(errors):
  style = read_text(STYLE_CSS)
  if style is None:
    errors.append("data/style.css not found")
    return

  for token in [
    "--bg-status:",
    "--bg-program-panel:",
    "--bg-program-example:",
    "--text-status:",
    "--text-history-link:",
    "--text-history-action:",
    "--state-danger-bg:",
    "--state-active-bg:",
    "--detector-ok-text:",
    "--detector-ok-bg:",
    "--detector-warn-text:",
    "--detector-warn-bg:",
    "--detector-alarm-text:",
    "--detector-alarm-bg:",
  ]:
    if token not in style:
      errors.append(f"data/style.css missing W6.8 theme token {token}")

  stale_patterns = [
    r"color:\s*#FFF;",
    r"color:\s*#000000;",
    r"background-color:\s*#7cfc0063;",
    r"color:\s*#333\b",
    r"background-color:\s*#F7F7F7",
    r"background-color:\s*#f2f2f2",
    r"powerstyle\s*=\s*['\"](?:red|lightgreen)['\"]",
    r"pausestyle\s*=\s*['\"](?:lightgreen|#3498db)['\"]",
    r"detStatus\.style\.color\s*=\s*['\"](?:green|orange|red)['\"]",
    r"detBlock\.style\.backgroundColor\s*=\s*['\"](?:#7cfc001a|#ffa5001a|#ff00001a)['\"]",
  ]
  for page in PAGES:
    text = read_text(page)
    if text is None:
      continue
    rel = page.relative_to(ROOT)
    for pattern in stale_patterns:
      if re.search(pattern, text):
        errors.append(f"{rel} still contains W6.8 stale theme literal: {pattern}")


def check_nbk_get_program_w69(errors):
  nbk = DATA / "nbk.htm"
  text = read_text(nbk)
  if text is None:
    errors.append("data/nbk.htm not found")
    return

  try:
    body = extract_function_body(text, "function getProgram()")
  except ValueError as exc:
    errors.append(str(exc))
    return

  required_tokens = [
    "if (!programText)",
    "return true;",
    "if (!check_program(programText))",
    "return false;",
    "const maxProgramLines = t.length - 1;",
    "if (lines.length > maxProgramLines)",
    "const parsedLines = [];",
    "parsedLines.push(parts);",
    "for (let i = 0; i < parsedLines.length; i++)",
  ]
  for token in required_tokens:
    if token not in body:
      errors.append(f"data/nbk.htm W6.9 getProgram() missing token: {token}")

  empty_guard_pos = body.find("if (!programText)")
  first_message_pos = body.find("SamovarApp.notify(")
  if empty_guard_pos == -1 or first_message_pos == -1 or first_message_pos < empty_guard_pos:
    errors.append("data/nbk.htm W6.9 getProgram() reports errors before empty-program guard")
  max_guard_pos = body.find("if (lines.length > maxProgramLines)")
  apply_loop_pos = body.find("for (let i = 0; i < parsedLines.length; i++)")
  if max_guard_pos == -1 or apply_loop_pos == -1 or apply_loop_pos < max_guard_pos:
    errors.append("data/nbk.htm W6.9 getProgram() applies UI rows before max-line guard")


def check_webserver(errors):
  webserver = ROOT / "WebServer.ino"
  text = read_text(webserver)
  if text is None:
    errors.append("WebServer.ino not found")
    return

  code = strip_cpp_comments(text)
  if 'server.serveStatic("/", SPIFFS, "/")' not in code:
    errors.append('WebServer.ino missing server.serveStatic("/", SPIFFS, "/") for app.js')


def check_i2cstepper_w610(errors):
  text = read_text(I2CSTEPPER_PAGE)
  if text is None:
    errors.append("data/i2cstepper.htm not found")
    return

  if re.search(r"setTimeout\s*\(\s*pollDevices\s*,\s*2000\s*\)", text):
    errors.append("data/i2cstepper.htm W6.10 uses fixed setTimeout(pollDevices, 2000)")

  for token in [
    "inFlightActions",
    "actionInFlight(device, action)",
    "setActionInFlight(device, action, true)",
    "button.disabled = disabled",
    "setDeviceUnavailable(device,",
  ]:
    if token not in text:
      errors.append(f"data/i2cstepper.htm W6.10 missing in-flight/disabled token: {token}")

  try:
    send_body = extract_function_body(text, "function sendDevice(device, cmd)")
  except ValueError as exc:
    errors.append(str(exc))
    send_body = ""
  if send_body:
    if "if (actionInFlight(device, action)) return;" not in send_body:
      errors.append("data/i2cstepper.htm W6.10 sendDevice() does not guard duplicate device/action clicks")
    if "setActionInFlight(device, action, false);" not in send_body:
      errors.append("data/i2cstepper.htm W6.10 sendDevice() does not release action after response/render path")
    if "setDeviceUnavailable(device, 'Ошибка выполнения команды I2CStepper.', true)" not in send_body:
      errors.append("data/i2cstepper.htm W6.10 sendDevice() does not keep command errors explicit")

  try:
    relay_body = extract_function_body(text, "function toggleRelay(device, relayNum)")
  except ValueError as exc:
    errors.append(str(exc))
    relay_body = ""
  if relay_body:
    if "if (actionInFlight(device, action)) return;" not in relay_body:
      errors.append("data/i2cstepper.htm W6.10 toggleRelay() does not guard duplicate relay clicks")
    if "setActionInFlight(device, action, false);" not in relay_body:
      errors.append("data/i2cstepper.htm W6.10 toggleRelay() does not release relay action after response/render path")
    if "setDeviceUnavailable(device, 'Ошибка переключения реле I2CStepper.', true)" not in relay_body:
      errors.append("data/i2cstepper.htm W6.10 toggleRelay() does not keep relay errors explicit")

  try:
    delay_body = extract_function_body(text, "function nextPollDelay()")
  except ValueError as exc:
    errors.append(str(exc))
    delay_body = ""
  if delay_body:
    for token in ["hasInFlightActions()", "state.present && state.supported && state.active", "state.present && state.supported && !state.error"]:
      if token not in delay_body:
        errors.append(f"data/i2cstepper.htm W6.10 nextPollDelay() missing adaptive polling token: {token}")


def main():
  errors = []
  check_pages(errors)
  check_app_js(errors)
  check_theme_tokens_w68(errors)
  check_nbk_get_program_w69(errors)
  check_webserver(errors)
  check_i2cstepper_w610(errors)

  if errors:
    print("ERROR: W6 UI foundations smoke failed")
    for error in errors:
      print(f"- {error}")
    return 1

  print("OK: W6 UI foundations smoke passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
