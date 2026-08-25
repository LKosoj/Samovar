#!/usr/bin/env python3
"""[T27.3] Descr длиннее 250 байт не должен уходить на сервер.

Сервер (WebServer.ino web_program()) считает Descr в БАЙТАХ (Arduino
String::length()). Клиентская разметка <textarea maxlength='250'> считает
СИМВОЛЫ - кириллица в UTF-8 занимает 2 байта на символ, поэтому 250 введённых
кириллических символов браузер пропускает молча, а сервер отбивает как 500
байт непонятным для пользователя текстом.

postProgram() (data_raw/app.js) теперь считает РЕАЛЬНЫЕ байты через
TextEncoder ДО отправки запроса - при превышении 250 байт показывает причину
через showRequestError() и не шлёт /program вовсе (тот же контракт, что и
соседняя проверка vless).

Дополнение к tools/test_numeric_input_ui_browser.py (тот же сценарий 130
кириллических символов встроен в testProgram() того файла): та проверка
живёт внутри одного огромного 36-итерационного playwright-cli сценария и
эмпирически подтверждено (см. отчёт задачи), что assert'ы в этой части
сценария НЕ детектируются CLI как падение теста - это ПРЕДСУЩЕСТВУЮЩИЙ баг
инфраструктуры (воспроизводится и на СТАРОЙ, не связанной с Descr, проверке
allowlist в том же testProgram()), а не что-то, что можно починить в рамках
этой задачи. Здесь - независимый, детерминированный Node-харнесс на РЕАЛЬНОМ
data_raw/app.js, который действительно ловит мутацию.

Проверки:
  - 130 кириллических символов (260 байт) -> postProgram() возвращает
    ok:false, запрос на /program НЕ отправлен, показанная причина
    упоминает 250 байт.
  - 125 кириллических символов (250 байт, точно на границе) -> запрос
    ОТПРАВЛЕН (>250 не считает границу превышением).
  - 251 однобайтовый ASCII-символ -> тоже блокируется (проверка не завязана
    специально на кириллицу).

Мутация: замена TextEncoder-подсчёта байт на value.length (подсчёт символов)
обязана завалить харнесс - 130 кириллических символов пройдут как "130",
что меньше 250, и запрос уйдёт на сервер.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "data_raw" / "app.js"

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
    style: {}, value: "", textContent: "", innerHTML: "",
    scrollTop: 0, scrollHeight: 0, _attrs: {}, children: [], name: "",
  };
  el.setAttribute = function (name, val) { el._attrs[name] = val; };
  el.getAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(el._attrs, name) ? el._attrs[name] : null;
  };
  el.hasAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(el._attrs, name);
  };
  el.appendChild = function (child) { el.children.push(child); };
  el.querySelectorAll = function (selector) {
    const match = /\[name="([^"]+)"\]/.exec(selector);
    if (!match) return [];
    return el.children.filter(function (child) { return child.name === match[1]; });
  };
  return el;
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
    FormData: FormData,
    Response: Response,
    TextEncoder: TextEncoder,
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

function makeForm() {
  const form = makeElement();
  return form;
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

function makeFetch() {
  const calls = [];
  const fetchImpl = function (url) {
    calls.push(url);
    if (String(url).startsWith("/ajax?operationId=")) {
      return Promise.resolve(jsonResponse(200, { operationId: 42, state: "succeeded", error: "none" }));
    }
    return Promise.resolve(jsonResponse(202, {
      ok: true, err: "", program: "", operationId: 42, state: "queued", error: "none"
    }));
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

async function scenarioOverLimitCyrillicBlocked() {
  const fetchImpl = makeFetch();
  const { app, elements } = loadApp(fetchImpl);
  const form = makeForm();
  const descr = makeElement();
  descr.name = "Descr";
  descr.value = "И".repeat(130); // 130 символов = 260 байт UTF-8 - за лимитом 250 байт
  form.appendChild(descr);

  const result = await app.postProgram(form);
  check(result.ok === false, "260-byte Descr must be rejected client-side (got ok=" + result.ok + ")");
  check(fetchImpl.calls.length === 0,
    "260-byte Descr must never reach the network (got " + fetchImpl.calls.length + " calls)");
  check(elements.request_error && elements.request_error.style.display === "block",
    "260-byte Descr must show a visible error");
  check(elements.request_error && elements.request_error.textContent.indexOf("250") !== -1,
    "the shown reason must mention the 250-byte budget (got: " +
    (elements.request_error && elements.request_error.textContent) + ")");
}

async function scenarioAtLimitCyrillicAllowed() {
  const fetchImpl = makeFetch();
  const { app } = loadApp(fetchImpl);
  const form = makeForm();
  const descr = makeElement();
  descr.name = "Descr";
  descr.value = "И".repeat(125); // 125 символов = ровно 250 байт UTF-8 - разрешено
  form.appendChild(descr);

  const result = await app.postProgram(form);
  check(result.ok === true, "exactly-250-byte Descr must not be blocked client-side (got ok=" + result.ok + ")");
  check(fetchImpl.calls.length >= 1,
    "exactly-250-byte Descr must reach the network (got " + fetchImpl.calls.length + " calls)");
}

async function scenarioOverLimitAsciiBlocked() {
  const fetchImpl = makeFetch();
  const { app } = loadApp(fetchImpl);
  const form = makeForm();
  const descr = makeElement();
  descr.name = "Descr";
  descr.value = "x".repeat(251); // 251 однобайтовый символ = 251 байт - за лимитом
  form.appendChild(descr);

  const result = await app.postProgram(form);
  check(result.ok === false, "251-byte ASCII Descr must be rejected client-side (got ok=" + result.ok + ")");
  check(fetchImpl.calls.length === 0,
    "251-byte ASCII Descr must never reach the network (got " + fetchImpl.calls.length + " calls)");
}

async function main() {
  await scenarioOverLimitCyrillicBlocked();
  await scenarioAtLimitCyrillicAllowed();
  await scenarioOverLimitAsciiBlocked();

  if (failures.length) {
    for (const message of failures) console.error("FAIL: " + message);
    process.exit(1);
  }
  console.log("Descr byte-limit client-side gate passed (3 scenarios)");
}

main().catch(function (err) {
  console.error("FAIL: uncaught error: " + (err && err.stack ? err.stack : err));
  process.exit(1);
});
'''


def run_driver(app_js_path: Path) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        print("SMOKE_SKIP: node executable not found on PATH", file=sys.stderr)
        raise SystemExit(0)
    with tempfile.TemporaryDirectory(prefix="samovar-descr-byte-limit-") as tmp:
        driver_path = Path(tmp) / "driver.js"
        driver_path.write_text(DRIVER, encoding="utf-8")
        return subprocess.run(
            [node, str(driver_path), str(app_js_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def run_and_report(app_js_path: Path, show_output: bool = True) -> int:
    result = run_driver(app_js_path)
    if show_output:
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.returncode != 0 and result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    return result.returncode


def main() -> int:
    if not APP_JS.exists():
        print("FAIL: data_raw/app.js not found", file=sys.stderr)
        return 1

    if run_and_report(APP_JS) != 0:
        print("Descr byte-limit smoke failed", file=sys.stderr)
        return 1

    # ---- Мутация: TextEncoder-подсчёт байт -> value.length (символы) ----
    app_js_text = APP_JS.read_text(encoding="utf-8")
    original = "const byteLength = new TextEncoder().encode(fields[0].value).length;"
    mutated = "const byteLength = fields[0].value.length;"
    if original not in app_js_text:
        print(f"FAIL: mutation anchor not found in {APP_JS}: {original!r}", file=sys.stderr)
        return 1
    mutant_text = app_js_text.replace(original, mutated, 1)

    with tempfile.TemporaryDirectory(prefix="samovar-descr-byte-limit-mutant-") as tmp:
        mutant_path = Path(tmp) / "app.js"
        mutant_path.write_text(mutant_text, encoding="utf-8")
        if run_and_report(mutant_path, show_output=False) == 0:
            print(
                "FAIL: mutation (byte count -> char count) survived the test - "
                "130 Cyrillic characters (260 bytes) would again slip through as "
                "'130 <= 250' and reach the network",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
