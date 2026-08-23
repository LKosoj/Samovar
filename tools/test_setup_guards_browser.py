#!/usr/bin/env python3
"""П52/П55 (WP23): setup.htm не должен молча терять несохранённые правки и не должен
молчать при загрузке файла настроек.

Проверяет:
 - dataset.dirty формы взводится при правке и снимается только настоящим сохранением;
 - window 'beforeunload' гасится (preventDefault) пока форма "грязная", и не гасится
   на чистой форме - это тот же самый признак, что уже считает существующий код
   (form.dataset.dirty), не второй, дублирующий;
 - три внутренние кнопки перехода (На главную/Редактор/Калибровка насоса) на "грязной"
   форме спрашивают confirm() и не уходят со страницы при отказе - и уходят при подтверждении
   или когда форма чистая (confirm вообще не вызывается);
 - loadFile() показывает результат через SamovarApp.showRequestError и для успеха, и для
   ошибки (битый JSON, не-объект, поле вне диапазона), а не молчит.
"""
import functools
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web_assets import resolve_includes

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const errors = [];
  const passed = [];

  page.on("console", message => {
    if (message.type() === "error") errors.push("console: " + message.text());
  });
  page.on("pageerror", error => errors.push("pageerror: " + error.message));

  function waitForUrlIncludes(fragment, timeoutMs) {
    const start = Date.now();
    return new Promise(resolve => {
      (function poll() {
        if (page.url().includes(fragment)) return resolve(true);
        if (Date.now() - start > timeoutMs) return resolve(false);
        setTimeout(poll, 50);
      })();
    });
  }

  async function waitForRequestError(timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const state = await page.evaluate(() => {
        const el = document.getElementById("request_error");
        return el ? { text: el.textContent, visible: getComputedStyle(el).display !== "none" } : null;
      });
      if (state && state.visible && state.text) return state;
      await new Promise(r => setTimeout(r, 50));
    }
    throw new Error("request_error did not appear within " + timeoutMs + "ms");
  }

  await page.setViewportSize({ width: 1440, height: 900 });

  // ---------- П52: dirty-флаг и beforeunload ----------
  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });

  const initialDirty = await page.evaluate(() => document.getElementById("setupform").dataset.dirty);
  if (initialDirty !== "false") throw new Error("form starts dirty=" + initialDirty);

  const preventedClean = await page.evaluate(() => {
    const ev = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(ev);
    return ev.defaultPrevented;
  });
  if (preventedClean) throw new Error("beforeunload guarded on a clean form");
  passed.push("clean form does not guard beforeunload");

  await page.evaluate(() => {
    const input = document.getElementById("DistTemp");
    input.value = "77";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const dirtyAfterEdit = await page.evaluate(() => document.getElementById("setupform").dataset.dirty);
  if (dirtyAfterEdit !== "true") throw new Error("editing a field did not set dataset.dirty");

  const preventedDirty = await page.evaluate(() => {
    const ev = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(ev);
    return ev.defaultPrevented;
  });
  if (!preventedDirty) throw new Error("beforeunload NOT guarded on a dirty form - this is the regression П52 must catch");
  passed.push("dirty form guards beforeunload (preventDefault)");

  // ---------- П52: внутренние кнопки перехода ----------
  async function checkGuardedButton(buttonId, targetFragment, revealTabId) {
    // Свежая "грязная" форма, отказ в confirm() -> остаёмся на странице.
    await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
    await page.evaluate(() => {
      const input = document.getElementById("DistTemp");
      input.value = "77";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    if (revealTabId) {
      await page.evaluate(id => { document.getElementById(id).style.display = "block"; }, revealTabId);
    }
    await page.evaluate(id => {
      window.__confirmCalls = 0;
      window.confirm = function () { window.__confirmCalls++; return false; };
      document.getElementById(id).click();
    }, buttonId);
    await new Promise(r => setTimeout(r, 300));
    const callsAfterCancel = await page.evaluate(() => window.__confirmCalls);
    if (callsAfterCancel !== 1) throw new Error(buttonId + ": confirm() was not called on a dirty form (calls=" + callsAfterCancel + ")");
    if (page.url().includes(targetFragment)) throw new Error(buttonId + ": navigated away despite confirm() cancel");

    // Тот же "грязный" confirm(), но подтверждаем -> должны уйти.
    await page.evaluate(id => {
      window.__confirmCalls = 0;
      window.confirm = function () { window.__confirmCalls++; return true; };
      document.getElementById(id).click();
    }, buttonId);
    const navigatedAccept = await waitForUrlIncludes(targetFragment, 5000);
    if (!navigatedAccept) throw new Error(buttonId + ": did not navigate to " + targetFragment + " after confirm() accept");

    // Чистая форма -> confirm() вообще не должен вызываться.
    await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
    if (revealTabId) {
      await page.evaluate(id => { document.getElementById(id).style.display = "block"; }, revealTabId);
    }
    await page.evaluate(id => {
      window.__confirmCalls = 0;
      window.confirm = function () { window.__confirmCalls++; return false; };
      document.getElementById(id).click();
    }, buttonId);
    const navigatedClean = await waitForUrlIncludes(targetFragment, 5000);
    const callsClean = await page.evaluate(() => window.__confirmCalls);
    if (!navigatedClean) throw new Error(buttonId + ": clean form did not navigate to " + targetFragment);
    if (callsClean !== 0) throw new Error(buttonId + ": clean form still called confirm()");
  }

  await checkGuardedButton("return", "index.htm", null);
  passed.push("#return (На главную) guarded by confirmLeaveIfDirty");
  await checkGuardedButton("edit", "/edit", null);
  passed.push("#edit (Редактор) guarded by confirmLeaveIfDirty");
  await checkGuardedButton("setstvolume", "calibrate.htm", "Pump");
  passed.push("#setstvolume (Калибровка насоса) guarded by confirmLeaveIfDirty");

  // ---------- П55: loadFile показывает результат ----------
  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });

  await page.evaluate(() => {
    const file = new File(["not json"], "bad.txt", { type: "text/plain" });
    loadFile(file);
  });
  const badJsonState = await waitForRequestError(3000);
  if (!/JSON|формат/i.test(badJsonState.text)) {
    throw new Error("bad JSON did not produce a readable error: " + badJsonState.text);
  }
  passed.push("loadFile reports unreadable/invalid JSON via showRequestError");

  await page.evaluate(() => {
    const file = new File(["[1,2,3]"], "array.txt", { type: "text/plain" });
    loadFile(file);
  });
  const arrayState = await waitForRequestError(3000);
  if (!/формат/i.test(arrayState.text)) {
    throw new Error("non-object JSON did not produce a format error: " + arrayState.text);
  }
  passed.push("loadFile rejects non-object JSON via showRequestError");

  await page.evaluate(() => {
    const file = new File([JSON.stringify({ DistTemp: "999" })], "outofrange.txt", { type: "text/plain" });
    loadFile(file);
  });
  const outOfRangeState = await waitForRequestError(3000);
  if (!/DistTemp/.test(outOfRangeState.text)) {
    throw new Error("out-of-range field was not named in the error: " + outOfRangeState.text);
  }
  const distTempApplied = await page.evaluate(() => document.getElementById("DistTemp").value);
  if (distTempApplied !== "999") throw new Error("out-of-range value was not mapped into the form field");
  passed.push("loadFile reports the specific out-of-range field via showRequestError");

  await page.evaluate(() => {
    const file = new File([JSON.stringify({ DistTemp: "80" })], "good.txt", { type: "text/plain" });
    loadFile(file);
  });
  const okState = await waitForRequestError(3000);
  if (!/загружен/i.test(okState.text) || !/Сохранить/.test(okState.text)) {
    throw new Error("success path did not explain that Save is still required: " + okState.text);
  }
  const distTempOk = await page.evaluate(() => document.getElementById("DistTemp").value);
  if (distTempOk !== "80") throw new Error("valid value was not mapped into the form field");
  passed.push("loadFile reports success and reminds to press Save");

  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { passed: passed };
}'''


class QuietHandler(http.server.SimpleHTTPRequestHandler):
  def log_message(self, format, *args):
    pass

  def send_head(self):
    path = self.translate_path(self.path)
    if path.endswith(".htm") and os.path.isfile(path):
      try:
        data = resolve_includes(os.path.basename(path), Path(path).read_bytes())
      except ValueError as exc:
        self.send_error(500, str(exc))
        return None
      self.send_response(200)
      self.send_header("Content-type", "text/html; charset=utf-8")
      self.send_header("Content-Length", str(len(data)))
      self.end_headers()
      return io.BytesIO(data)
    return super().send_head()


def run_cli(cli, session, arguments, cwd, timeout, check=True):
  result = subprocess.run(
    [cli, f"-s={session}", *arguments],
    cwd=cwd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    check=False,
    timeout=timeout,
  )
  if result.stdout:
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
  if check and (result.returncode != 0 or "### Error" in result.stdout):
    raise RuntimeError(f"playwright-cli {' '.join(arguments[:1])} failed")
  return result.returncode


def cleanup_resources(cli, session, server, thread):
  errors = []
  try:
    try:
      if run_cli(cli, session, ["close"], ROOT, 30, check=False) != 0:
        errors.append("playwright-cli close failed")
    except (OSError, subprocess.TimeoutExpired) as error:
      errors.append(f"playwright-cli close failed: {error}")
  finally:
    try:
      server.shutdown()
    except Exception as error:
      errors.append(f"HTTP server shutdown failed: {error}")
    try:
      server.server_close()
    except Exception as error:
      errors.append(f"HTTP server close failed: {error}")
    thread.join(timeout=5)
    if thread.is_alive():
      errors.append("HTTP server thread did not stop")
  return errors


def main():
  cli = shutil.which("playwright-cli")
  if not cli:
    print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
    return 2

  handler = functools.partial(QuietHandler, directory=str(DATA))
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  session = f"samovar-setup-guards-{os.getpid()}"
  primary_error = None
  cleanup_errors = []

  try:
    with tempfile.TemporaryDirectory(prefix="samovar-setup-guards-browser-") as temp_dir:
      open_args = ["open"]
      if hasattr(os, "geteuid") and os.geteuid() == 0:
        config = Path(temp_dir) / "playwright.json"
        config.write_text(json.dumps({
          "browser": {
            "browserName": "chromium",
            "launchOptions": {"chromiumSandbox": False},
          }
        }), encoding="utf-8")
        open_args.append(f"--config={config}")

      run_cli(cli, session, open_args, temp_dir, 30)
      base_url = f"http://127.0.0.1:{server.server_port}"
      browser_test = BROWSER_TEST.replace("__BASE_URL__", json.dumps(base_url))
      run_cli(cli, session, ["run-code", browser_test], temp_dir, 180)
  except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
    primary_error = str(error)
  finally:
    cleanup_errors = cleanup_resources(cli, session, server, thread)

  if primary_error or cleanup_errors:
    if primary_error:
      print(f"Setup guards UI browser contract failed: {primary_error}", file=sys.stderr)
    for error in cleanup_errors:
      print(f"Setup guards UI browser cleanup failed: {error}", file=sys.stderr)
    return 1

  print("Setup guards UI browser contract passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
