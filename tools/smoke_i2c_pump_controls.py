#!/usr/bin/env python3
"""Behavioral check for the restored "external I2C pump" tab controls.

The tab (index/bk/beer/distiller/nbk.htm) was silently dropped in commit
2a78aa5e when per-page JS was consolidated into data/app.js: only the
read-only status indicator (#i2c_pump_status/#i2c_status/#i2c_remaining/
#i2c_speed_cur, driven by SamovarApp.renderI2cPumpStatus) survived, so there
was no way left in the UI to actually start or stop the pump.

This test loads the REAL data/app.js in a Node vm context (fetch/DOM stubbed)
and drives SamovarApp.sendI2cPump()/stopI2cPump() exactly as the restored
buttons do, asserting on the resulting behavior - not on source text:

  - sendI2cPump() must fetch GET /i2cpump with exactly `speed` and `volume`
    (server contract: WebServer.ino handle_i2c_pump_request rejects any other
    parameter set with 400 "Invalid request: argument"). Since R6 ("Давай
    вернем OK"), a 200 response means only "the command was accepted into
    the queue" - a plain `text/plain "OK"`, not an operationId to poll. There
    is no "queued but failed" state on this route anymore.
  - stopI2cPump() must fetch GET /i2cpump with exactly `?stop=1` - one
    parameter, nothing else (adding speed/volume alongside stop is a 400
    per the same handler).
  - A rejected command (HTTP 400/503) must surface a visible error to the
    user, not fail silently (the old, since-removed inline JS did
    `.catch(() => {})` and swallowed everything).
  - Invalid client input (empty field, non-numeric text, non-positive speed -
    the server requires speed > 0 and 0 < volume <= 65535, see
    control_numeric_input.h parse_control_i2c_pump/parse_control_rate_steps)
    must never reach the network.
  - A dead network (fetch reject) must surface a visible error, not fail
    silently.

The operationId accept/poll machinery (readOperationAcceptance/
waitForOperation) is still alive in app.js - it backs /i2cstepper and
/calibrate, wired up from i2cstepper.htm, calibrate.htm and setup.htm, and is
covered by smoke_i2c_operation_results.py. /i2cpump no longer uses it.

A lightweight static pass (not a replacement for the above) additionally
confirms each of the five target pages still wires up a tab button and an
`id="I2CPump"` content block after this change.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
PAGES = ["index.htm", "bk.htm", "beer.htm", "distiller.htm", "nbk.htm"]

DRIVER = r'''
"use strict";
const fs = require("fs");
const vm = require("vm");

const appPath = process.argv[2];
const appSource = fs.readFileSync(appPath, "utf8");

const failures = [];
function check(condition, message) {
  if (!condition) failures.push(message);
}

function makeElement() {
  const el = {
    style: {},
    value: "",
    textContent: "",
    innerHTML: "",
    scrollTop: 0,
    scrollHeight: 0,
    _attrs: {},
  };
  el.setAttribute = function (name, val) { el._attrs[name] = val; };
  el.getAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(el._attrs, name) ? el._attrs[name] : null;
  };
  el.hasAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(el._attrs, name);
  };
  return el;
}

function setValue(elements, id, value) {
  if (!elements[id]) elements[id] = makeElement();
  elements[id].value = value;
}

function freshEnv() {
  const elements = {};
  const env = {
    window: {},
    document: {
      getElementById: function (id) {
        if (!elements[id]) elements[id] = makeElement();
        return elements[id];
      },
      createElement: function () { return makeElement(); },
      querySelector: function () { return null; },
      documentElement: {},
      body: makeElement(),
      addEventListener: function () {},
    },
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    AbortController: AbortController,
  };
  env.document.body.insertBefore = function () {};
  env.document.body.appendChild = function () {};
  return { env: env, elements: elements };
}

function loadApp(fetchImpl) {
  const fresh = freshEnv();
  fresh.env.fetch = fetchImpl;
  const context = vm.createContext(fresh.env);
  vm.runInContext(appSource, context, { filename: "app.js" });
  return { app: context.window.SamovarApp, elements: fresh.elements };
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    statusText: "",
    headers: { get: function (name) { return name === "Content-Type" ? "application/json" : null; } },
    json: function () { return Promise.resolve(body); },
    text: function () { return Promise.resolve(JSON.stringify(body)); },
  };
}

function textResponse(status, text) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    statusText: "",
    headers: { get: function (name) { return name === "Content-Type" ? "text/plain" : null; } },
    text: function () { return Promise.resolve(text); },
    json: function () { return Promise.reject(new Error("not json")); },
  };
}

function makeFetch(responder) {
  const calls = [];
  const fetchImpl = function (url) {
    calls.push(url);
    return Promise.resolve(responder(url, calls.length));
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

// Оборванная сеть: настоящий fetch отклоняет промис TypeError'ом, а не отвечает.
function makeFailingFetch(error) {
  const calls = [];
  const fetchImpl = function (url) {
    calls.push(url);
    return Promise.reject(error);
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

async function scenarioSendHappyPathWithCommaDecimal() {
  const fetchImpl = makeFetch(function (url) {
    check(url === "/i2cpump?speed=2.5&volume=100",
      "sendI2cPump must submit exactly speed+volume, comma normalized to dot (got: " + url + ")");
    return textResponse(200, "OK");
  });
  const { app, elements } = loadApp(fetchImpl);
  setValue(elements, "i2c_speed", "2,5");
  setValue(elements, "i2c_volume", "100");
  const result = await app.sendI2cPump();
  check(result === true, "sendI2cPump must resolve true on success");
  check(fetchImpl.calls.length === 1, "sendI2cPump must call fetch exactly once, got " + fetchImpl.calls.length);
  check(elements.request_error.style.display === "none",
    "a successful sendI2cPump must not leave an error visible");
}

async function scenarioStopHappyPath() {
  const fetchImpl = makeFetch(function (url) {
    check(url === "/i2cpump?stop=1", "stopI2cPump must submit exactly ?stop=1 (got: " + url + ")");
    return textResponse(200, "OK");
  });
  const { app, elements } = loadApp(fetchImpl);
  const result = await app.stopI2cPump();
  check(result === true, "stopI2cPump must resolve true on success");
  check(fetchImpl.calls.length === 1, "stopI2cPump must call fetch exactly once, got " + fetchImpl.calls.length);
  check(elements.request_error.style.display === "none",
    "a successful stopI2cPump must not leave an error visible");
}

async function scenarioServerRejects400() {
  const fetchImpl = makeFetch(function (url) {
    check(/^\/i2cpump\?speed=/.test(url), "expected a speed/volume submission, got: " + url);
    return textResponse(400, "Invalid speed: range");
  });
  const { app, elements } = loadApp(fetchImpl);
  setValue(elements, "i2c_speed", "5");
  setValue(elements, "i2c_volume", "100");
  const result = await app.sendI2cPump();
  check(result === false, "sendI2cPump must resolve false when the server rejects the command");
  check(fetchImpl.calls.length === 1, "a 400 response must not be followed by an operation poll, got " + fetchImpl.calls.length + " calls");
  check(elements.request_error.style.display === "block",
    "a rejected command must surface a visible error, not fail silently");
  check(elements.request_error.textContent.indexOf("Invalid speed: range") !== -1,
    "the error shown to the user must include the server-reported reason (got: " + elements.request_error.textContent + ")");
}

async function scenarioBusy503OnStop() {
  const fetchImpl = makeFetch(function (url) {
    check(url === "/i2cpump?stop=1", "expected the stop request, got: " + url);
    return textResponse(503, "BUSY");
  });
  const { app, elements } = loadApp(fetchImpl);
  const result = await app.stopI2cPump();
  check(result === false, "stopI2cPump must resolve false when the device is busy");
  check(elements.request_error.style.display === "block" &&
    elements.request_error.textContent.indexOf("BUSY") !== -1,
    "a BUSY response must surface a visible error naming BUSY (got: " + elements.request_error.textContent + ")");
}

async function scenarioEmptyInputBlocksRequest() {
  const fetchImpl = makeFetch(function (url) {
    check(false, "invalid input must never reach the network (got: " + url + ")");
    return jsonResponse(500, {});
  });
  const { app, elements } = loadApp(fetchImpl);
  setValue(elements, "i2c_speed", "");
  setValue(elements, "i2c_volume", "100");
  const result = await app.sendI2cPump();
  check(result === false, "sendI2cPump must reject an empty speed field");
  check(fetchImpl.calls.length === 0, "no fetch call must be made for invalid input");
  check(elements.request_error.style.display === "block", "invalid input must show a visible error");
}

async function scenarioNonNumericInputBlocksRequest() {
  const fetchImpl = makeFetch(function (url) {
    check(false, "invalid input must never reach the network (got: " + url + ")");
    return jsonResponse(500, {});
  });
  const { app, elements } = loadApp(fetchImpl);
  setValue(elements, "i2c_speed", "2.5");
  setValue(elements, "i2c_volume", "abc");
  const result = await app.sendI2cPump();
  check(result === false, "sendI2cPump must reject a non-numeric volume field");
  check(fetchImpl.calls.length === 0, "no fetch call must be made for invalid input");
}

async function scenarioNonPositiveSpeedBlocksRequest() {
  const fetchImpl = makeFetch(function (url) {
    check(false, "a non-positive speed must never reach the network (got: " + url + ")");
    return jsonResponse(500, {});
  });
  const { app, elements } = loadApp(fetchImpl);
  setValue(elements, "i2c_speed", "0");
  setValue(elements, "i2c_volume", "100");
  const result = await app.sendI2cPump();
  check(result === false, "sendI2cPump must reject a zero speed (server requires speed > 0)");
  check(fetchImpl.calls.length === 0, "a zero speed must not reach the network");
}

async function scenarioNetworkFailureSurfacesError() {
  const fetchImpl = makeFailingFetch(new TypeError("Failed to fetch"));
  const { app, elements } = loadApp(fetchImpl);
  setValue(elements, "i2c_speed", "2.5");
  setValue(elements, "i2c_volume", "100");
  const result = await app.sendI2cPump();
  check(result === false, "sendI2cPump must resolve false when the network is down");
  check(fetchImpl.calls.length === 1, "a dead network must not be followed by an operation poll, got " + fetchImpl.calls.length + " calls");
  // Если ошибку проглотили, элемент вообще не создан - подставляем пустой,
  // чтобы тест назвал дефект, а не рухнул на чтении undefined.
  const errorBox = elements.request_error || makeElement();
  check(errorBox.style.display === "block",
    "a network failure must surface a visible error, not fail silently");
  check(String(errorBox.textContent).indexOf("Failed to fetch") !== -1,
    "the network error must reach the user (got: " + errorBox.textContent + ")");
}

async function main() {
  await scenarioSendHappyPathWithCommaDecimal();
  await scenarioStopHappyPath();
  await scenarioServerRejects400();
  await scenarioBusy503OnStop();
  await scenarioEmptyInputBlocksRequest();
  await scenarioNonNumericInputBlocksRequest();
  await scenarioNonPositiveSpeedBlocksRequest();
  await scenarioNetworkFailureSurfacesError();

  if (failures.length) {
    for (const message of failures) console.error("FAIL: " + message);
    process.exit(1);
  }
  console.log("I2C pump controls smoke passed (8 scenarios)");
}

main().catch(function (err) {
  console.error("FAIL: uncaught error: " + (err && err.stack ? err.stack : err));
  process.exit(1);
});
'''


def run_driver(app_js_path: Path) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        print("FAIL: node executable not found on PATH", file=sys.stderr)
        raise SystemExit(1)
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-pump-controls-") as tmp:
        driver_path = Path(tmp) / "driver.js"
        driver_path.write_text(DRIVER, encoding="utf-8")
        return subprocess.run(
            [node, str(driver_path), str(app_js_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def check_pages_static() -> list[str]:
    errors = []
    for name in PAGES:
        path = DATA / name
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not re.search(
            r"class=\"tablinks\"[^>]*onclick=\"SamovarApp\.openTab\(event,\s*'I2CPump'\);\"[^>]*"
            r"style=\"display:\s*%I2CPumpTab%;\"",
            text,
        ):
            errors.append(f"{name}: missing the 'Внешний насос' tab button wired to %I2CPumpTab%")
        if not re.search(r"<div\s+id=\"I2CPump\"\s+class=\"tabcontent\"", text):
            errors.append(f"{name}: missing the #I2CPump tabcontent block")
        if "SamovarApp.sendI2cPump();" not in text:
            errors.append(f"{name}: missing a control wired to SamovarApp.sendI2cPump()")
        if "SamovarApp.stopI2cPump();" not in text:
            errors.append(f"{name}: missing a control wired to SamovarApp.stopI2cPump()")
        if text.count("id='i2c_speed'") != 1:
            errors.append(f"{name}: expected exactly one #i2c_speed input")
        if text.count("id='i2c_volume'") != 1:
            errors.append(f"{name}: expected exactly one #i2c_volume input")
    return errors


def check_app_js_exports() -> list[str]:
    errors = []
    text = (DATA / "app.js").read_text(encoding="utf-8", errors="ignore")
    for token in ["sendI2cPump: sendI2cPump,", "stopI2cPump: stopI2cPump,"]:
        if token not in text:
            errors.append(f"data_raw/app.js does not export {token}")
    return errors


def main() -> int:
    app_js_path = DATA / "app.js"
    errors = check_app_js_exports() + check_pages_static()

    result = run_driver(app_js_path)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
        errors.append("Node behavioral driver failed (see output above)")

    if errors:
        print("I2C pump controls smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
