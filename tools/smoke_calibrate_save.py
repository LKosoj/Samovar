#!/usr/bin/env python3
"""Behavioral check for saving the stepper calibration from data/calibrate.htm.

The page carries `<form action='/save' method="post">` with two editable fields.
Until this change nothing intercepted its submission, so pressing Enter in either
field navigated the browser to POST /save and dumped the raw text/plain reply over
the calibration screen. Worse, the form had no save control at all: a hand-typed
"Шагов на 100 мл" was silently discarded.

Restoring a naive submit would corrupt settings, hence the assertions below:

  - Each pump keeps its OWN steps setting (SamSetup.StepperStepMl for the built-in
    pump, StepperStepMlI2C for the external one), while the page shows a single
    field. The lowercase `stepperstepml` param that the old markup posted is mapped
    by handleSave() to the BUILT-IN pump unconditionally (WebServer.ino), so saving
    while "Внешний (I2C)" is selected would overwrite the built-in pump's
    calibration with the I2C pump's value and lose the I2C one.
  - `kstepperspd` is NOT in save_param_name_allowed() (WebServer.ino): %StepperStep%
    is the compile-time STEPPER_MAX_SPEED default and a per-run argument of
    /calibrate?stpstep=, not a stored setting. Posting it earns 400 "not_allowed",
    so the handler must not send it.
  - The field is steps per 100 ml, the controller stores steps per 1 ml, so the
    value must be a multiple of 100 and is divided before it is sent.
  - Saving must not be possible while a calibration is running: the finish step
    persists its own result (pump_calibrate -> save_profile_nvs in logic.h) and a
    concurrent write would race it.

The driver loads the real page script in a Node vm with fetch/DOM stubbed and
drives the submit handler, asserting on the request that actually leaves.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "data_raw" / "calibrate.htm"
WEBSERVER = ROOT / "WebServer.ino"

DRIVER = r'''
"use strict";
const fs = require("fs");
const vm = require("vm");

const pageSource = fs.readFileSync(process.argv[2], "utf8");

// Скрипт страницы - второй <script> (первый лишь подключает app.js).
const blocks = [...pageSource.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)];
if (blocks.length !== 1) {
  console.error("FAIL: expected exactly one inline <script> in calibrate.htm, got " + blocks.length);
  process.exit(1);
}
let script = blocks[0][1];

const failures = [];
function check(condition, message) {
  if (!condition) failures.push(message);
}

function makeElement(id) {
  return {
    id: id, value: "", disabled: false, style: {}, textContent: "",
    _attrs: {},
    setAttribute: function (n, v) { this._attrs[n] = v; },
    getAttribute: function (n) { return this._attrs[n] === undefined ? null : this._attrs[n]; },
    focus: function () {},
  };
}

// Значения шаблонных плейсхолдеров прошивки.
function render(vars) {
  let out = script;
  for (const [key, value] of Object.entries(vars)) {
    out = out.split("%" + key + "%").join(String(value));
  }
  return out;
}

function makeEnv(vars, fetchImpl) {
  const elements = {};
  for (const id of ["calibrateid", "pump_type", "kstepperspd", "stepperstepml", "save", "request_error"]) {
    elements[id] = makeElement(id);
  }
  elements.pump_type.value = "local";
  elements.pump_type.style.display = "inline-block";
  elements.kstepperspd.value = String(vars.StepperStep);
  elements.stepperstepml.value = String(vars.StepperStepMl);

  let submitHandler = null;
  const form = {
    addEventListener: function (type, fn) { if (type === "submit") submitHandler = fn; },
  };

  const shown = [];
  const env = {
    console: console,
    fetch: fetchImpl,
    URLSearchParams: URLSearchParams,
    Number: Number,
    String: String,
    document: {
      getElementById: function (id) { return elements[id] || null; },
      forms: { setupform: form },
    },
    window: {},
    // Заглушка SamovarApp: настоящая логика валидации живёт в app.js и покрыта
    // своими тестами; здесь важно, ЧТО страница отправляет и когда.
    SamovarApp: {
      initTheme: function () {},
      showRequestError: function (text) { shown.push(String(text)); },
      clearRequestError: function () {},
      readNumericInput: function (id, opts) {
        const input = elements[id];
        const raw = String(input.value).replace(",", ".");
        if (!/^-?\d+$/.test(raw)) { shown.push("Поле «" + opts.label + "» должно содержать одно число."); return null; }
        const value = Number(raw);
        if (opts.min !== undefined && value < opts.min) { shown.push("Поле «" + opts.label + "»: минимум " + opts.min + "."); return null; }
        if (opts.max !== undefined && value > opts.max) { shown.push("Поле «" + opts.label + "»: максимум " + opts.max + "."); return null; }
        if (opts.accept && !opts.accept(value)) { shown.push(opts.acceptMessage || "недопустимо"); return null; }
        return { ok: true, number: value, text: raw, input: input };
      },
      responseErrorText: async function (resp, prefix) {
        return prefix + ": " + (await resp.text());
      },
      readOperationAcceptance: async function (resp) { return await resp.json(); },
      waitForOperation: async function () { return { state: "succeeded" }; },
    },
  };
  env.window = env;
  const context = vm.createContext(env);
  vm.runInContext(render(vars), context, { filename: "calibrate.htm" });
  context.window.onload();
  return { context: context, elements: elements, shown: shown, submit: function () {
    return submitHandler({ preventDefault: function () {} });
  }, calibrate: function () { return context.calibrate(); } };
}

function makeFetch(responder) {
  const calls = [];
  const impl = function (url, init) {
    calls.push({ url: url, init: init, body: init && init.body ? String(init.body) : "" });
    return Promise.resolve(responder(url));
  };
  impl.calls = calls;
  return impl;
}

function accepted() {
  return {
    ok: true, status: 202,
    headers: { get: function () { return "application/json"; } },
    json: function () { return Promise.resolve({ operationId: 3, state: "queued", error: "none" }); },
    text: function () { return Promise.resolve(""); },
  };
}

function rejected(status, text) {
  return {
    ok: false, status: status,
    headers: { get: function () { return "text/plain"; } },
    text: function () { return Promise.resolve(text); },
    json: function () { return Promise.reject(new Error("not json")); },
  };
}

const BASE = { StepperStepMl: 2500, StepperStepMlI2C: 3300, CalibrationRunning: 0, CalibrationPump: "", StepperStep: 800, I2CPumpTab: "inline-block" };

async function scenarioBuiltInPumpSavesOwnSetting() {
  const fetchImpl = makeFetch(accepted);
  const env = makeEnv(BASE, fetchImpl);
  env.elements.pump_type.value = "local";
  env.elements.stepperstepml.value = "2500";
  const ok = await env.submit();
  check(ok === true, "saving the built-in pump must resolve true");
  check(fetchImpl.calls.length === 1, "expected exactly one POST, got " + fetchImpl.calls.length);
  const call = fetchImpl.calls[0];
  check(call.url === "/save", "must post to /save, got " + call.url);
  check(call.init.method === "POST", "must use POST");
  check(call.body === "StepperStepMl=25",
    "built-in pump must save 2500 per 100 ml as StepperStepMl=25 per ml (got: " + call.body + ")");
}

async function scenarioI2cPumpDoesNotClobberBuiltIn() {
  const fetchImpl = makeFetch(accepted);
  const env = makeEnv(BASE, fetchImpl);
  env.elements.pump_type.value = "i2c";
  env.elements.stepperstepml.value = "3300";
  const ok = await env.submit();
  check(ok === true, "saving the I2C pump must resolve true");
  const body = fetchImpl.calls[0].body;
  check(body === "StepperStepMlI2C=33",
    "the I2C pump must save StepperStepMlI2C=33, not the built-in setting (got: " + body + ")");
  check(body.indexOf("stepperstepml") === -1 && /StepperStepMl=/.test(body) === false,
    "saving the I2C pump must never send the built-in pump's param - it would overwrite its calibration (got: " + body + ")");
}

async function scenarioSpeedIsNeverSent() {
  const fetchImpl = makeFetch(accepted);
  const env = makeEnv(BASE, fetchImpl);
  env.elements.kstepperspd.value = "1234";
  await env.submit();
  const body = fetchImpl.calls[0].body;
  check(body.indexOf("kstepperspd") === -1,
    "kstepperspd is not accepted by /save (400 not_allowed) and must not be sent (got: " + body + ")");
}

async function scenarioNonMultipleOfHundredIsRejectedLocally() {
  const fetchImpl = makeFetch(accepted);
  const env = makeEnv(BASE, fetchImpl);
  env.elements.stepperstepml.value = "2534";
  const ok = await env.submit();
  check(ok === false, "a value that is not a multiple of 100 must be rejected");
  check(fetchImpl.calls.length === 0,
    "a non-multiple of 100 must never reach the network - the controller stores steps per 1 ml");
  check(env.shown.length > 0, "the user must be told why the value was rejected");
}

async function scenarioSavingIsBlockedWhileCalibrating() {
  const fetchImpl = makeFetch(accepted);
  const env = makeEnv(Object.assign({}, BASE, { CalibrationRunning: 1, CalibrationPump: "local" }), fetchImpl);
  check(env.elements.save.disabled === true,
    "the save control must be disabled while a calibration is running");
  const ok = await env.submit();
  check(ok === false, "submitting during a calibration must be refused");
  check(fetchImpl.calls.length === 0,
    "the calibration finish persists its own result; a concurrent save would race it");
}

async function scenarioServerRejectionSurfaces() {
  const fetchImpl = makeFetch(function () { return rejected(400, "Invalid request field: not_allowed"); });
  const env = makeEnv(BASE, fetchImpl);
  const ok = await env.submit();
  check(ok === false, "a rejected save must resolve false");
  check(env.shown.some(function (m) { return m.indexOf("not_allowed") !== -1; }),
    "the server's reason must reach the user (shown: " + JSON.stringify(env.shown) + ")");
  check(env.elements.save.disabled === false, "the save control must be re-enabled after a failure");
}

async function scenarioNetworkFailureSurfaces() {
  const calls = [];
  const fetchImpl = function (url, init) { calls.push(url); return Promise.reject(new TypeError("Failed to fetch")); };
  fetchImpl.calls = calls;
  const env = makeEnv(BASE, fetchImpl);
  const ok = await env.submit();
  check(ok === false, "a dead network must resolve false");
  check(env.shown.some(function (m) { return m.indexOf("Failed to fetch") !== -1; }),
    "a network failure must surface, not fail silently (shown: " + JSON.stringify(env.shown) + ")");
  check(env.elements.save.disabled === false, "the save control must be re-enabled after a network failure");
}

// calibrationInFlight - общий флаг взаимного исключения calibrate() и saveCalibration().
// Если сохранение его не выставляет, кнопка "Начать калибровку" остаётся живой, и
// старт калибровки уедет на контроллер поверх ещё не завершённой записи настройки.
async function scenarioCalibrateIsBlockedWhileSaveIsInFlight() {
  let releaseSave = null;
  const saveGate = new Promise(function (resolve) { releaseSave = resolve; });
  const calls = [];
  const fetchImpl = function (url, init) {
    calls.push({ url: url, body: init && init.body ? String(init.body) : "" });
    if (url === "/save") return saveGate.then(accepted);
    return Promise.resolve(accepted());
  };
  const env = makeEnv(BASE, fetchImpl);

  const savePromise = env.submit();
  await Promise.resolve();
  await Promise.resolve();

  check(env.elements.calibrateid.disabled === true,
    "the calibrate control must be disabled while a save is in flight");
  const calibrateResult = await env.calibrate();
  check(calibrateResult === false,
    "calibrate() must refuse to start while a save is in flight");
  check(calls.filter(function (c) { return c.url.indexOf("/calibrate") === 0; }).length === 0,
    "no /calibrate request may be issued while a save is still in flight");

  releaseSave();
  check(await savePromise === true, "the save itself must still succeed");
  check(env.elements.calibrateid.disabled === false,
    "the calibrate control must be re-enabled once the save finishes");
}

async function main() {
  await scenarioBuiltInPumpSavesOwnSetting();
  await scenarioI2cPumpDoesNotClobberBuiltIn();
  await scenarioSpeedIsNeverSent();
  await scenarioNonMultipleOfHundredIsRejectedLocally();
  await scenarioSavingIsBlockedWhileCalibrating();
  await scenarioServerRejectionSurfaces();
  await scenarioNetworkFailureSurfaces();
  await scenarioCalibrateIsBlockedWhileSaveIsInFlight();

  if (failures.length) {
    for (const message of failures) console.error("FAIL: " + message);
    process.exit(1);
  }
  console.log("calibrate save smoke passed (8 scenarios)");
}

main().catch(function (err) {
  console.error("FAIL: uncaught error: " + (err && err.stack ? err.stack : err));
  process.exit(1);
});
'''


def check_server_contract() -> list[str]:
    """The assumptions the driver encodes must still hold in the firmware."""
    errors = []
    text = WEBSERVER.read_text(encoding="utf-8", errors="ignore")

    if 'name == "kstepperspd"' in text:
        errors.append(
            "WebServer.ino now allows kstepperspd in /save - calibrate.htm deliberately "
            "does not send it; revisit tools/smoke_calibrate_save.py"
        )
    for param in ('name == "StepperStepMl"', 'name == "StepperStepMlI2C"'):
        if param not in text:
            errors.append(f"WebServer.ino: /save no longer allows {param}")
    if "staged.StepperStepMl = (uint16_t)(stepsPer100Ml / 100);" not in text:
        errors.append(
            "WebServer.ino: the lowercase stepperstepml -> built-in pump mapping changed; "
            "the per-pump routing in calibrate.htm may no longer be correct"
        )
    return errors


def check_page_markup() -> list[str]:
    errors = []
    text = PAGE.read_text(encoding="utf-8", errors="ignore")
    if not re.search(r"<input\s+id='save'\s+type='submit'", text):
        errors.append("data_raw/calibrate.htm: no submit control to save the calibration with")
    if "addEventListener('submit', saveCalibration)" not in text:
        errors.append(
            "data_raw/calibrate.htm: the form's submit is not intercepted - Enter in a field "
            "would navigate to POST /save and render the raw reply"
        )
    return errors


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("calibrate save smoke skipped: node not available")
        return 0

    errors = check_page_markup() + check_server_contract()

    with tempfile.TemporaryDirectory(prefix="samovar-calibrate-save-") as tmp:
        driver = Path(tmp) / "driver.js"
        driver.write_text(DRIVER, encoding="utf-8")
        result = subprocess.run(
            [node, str(driver), str(PAGE)], cwd=ROOT, capture_output=True, text=True, check=False
        )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
        errors.append("Node behavioral driver failed (see output above)")

    if errors:
        print("calibrate save smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
