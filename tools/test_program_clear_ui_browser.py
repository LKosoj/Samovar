#!/usr/bin/env python3
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const pages = ["index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm", "program.htm"];
  const viewports = [
    { name: "desktop", width: 1440, height: 900 },
    { name: "mobile", width: 390, height: 844 }
  ];
  const ajaxFixture = {
    version: "test", crnt_tm: "12:00:00", stm: "00:01:00", SteamTemp: 78.1, PipeTemp: 77.9,
    WaterTemp: 20.2, TankTemp: 82.3, ACPTemp: 40.1, bme_pressure: 760, start_pressure: 759.5,
    prvl: 1.2, VolumeAll: 0, ActualVolumePerHour: 0, WthdrwlProgress: 0, CurrrentSpeed: 0,
    CurrrentStepps: 0, TargetStepps: 0, WthdrwlStatus: 0, ProgramNum: 0, DetectorTrend: 0,
    DetectorStatus: 0, useautospeed: false, current_power_volt: 0, target_power_volt: 0,
    current_power_mode: "0", current_power_p: 0, WFtotalMl: 0, WFflowRate: 0, bme_temp: 24,
    heap: 200000, rssi: -50, fr_bt: 300000, UseBBuzzer: false, PauseOn: 0, PrgType: "",
    Status: "Готов", Lstatus: "", TimeRemaining: 0,
    TotalTime: 0, alc: 0, stm_alc: 0, ISspd: 0, wp_spd: 0, i2c_pump_present: 0,
    i2c_pump_running: 0, i2c_pump_remaining_ml: 0, i2c_pump_speed: 0, PowerOn: 0
  };
  const columnFixture = {
    maxFlow: 1000, headsSpeed: 100, bodySpeedMin: 200, bodySpeedMax: 400,
    theoreticalPlates: 20, note: "test"
  };
  const errors = [];
  const passed = [];
  let totalRequests = 0;
  let scenario = "setup";

  page.on("console", message => {
    if (message.type() === "error") errors.push(scenario + " console: " + message.text());
  });
  page.on("pageerror", error => errors.push(scenario + " pageerror: " + error.message));
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(ajaxFixture)
  }));
  await page.route("**/ajax_col_params?*", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(columnFixture)
  }));
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const file of pages) {
      scenario = viewport.name + "/" + file;
      await page.goto(baseUrl + "/" + file, { waitUntil: "load" });
      await page.evaluate(() => {
        window.__programRequests = [];
        window.__operationRequests = [];
        window.__programStatus = 202;
        const nativeFetch = window.fetch.bind(window);
        window.fetch = (url, options) => {
          if (typeof url === "string" && url.startsWith("/ajax?operationId=")) {
            window.__operationRequests.push(url);
            return Promise.resolve(new Response(
              JSON.stringify({ operationId: 1, state: "succeeded", error: "none" }),
              { status: 200, headers: { "Content-Type": "application/json" } }
            ));
          }
          if (url !== "/program") return nativeFetch(url, options);
          const entries = Array.from(options.body.entries());
          window.__programRequests.push({ method: options.method, entries: entries });
          const status = window.__programStatus;
          const ok = status === 202;
          const body = { ok: ok, err: ok ? "" : "E" + status, program: "" };
          if (ok) Object.assign(body, { operationId: 1, state: "queued", error: "none" });
          return Promise.resolve(new Response(
            JSON.stringify(body),
            { status: status, headers: { "Content-Type": "application/json" } }
          ));
        };
      });
      const buttonCount = await page.locator("#clearprogram").count();
      if (buttonCount !== 1) throw new Error(scenario + " clear button count=" + buttonCount);
      await page.locator("#clearprogram").evaluate(button => {
        const tab = button.closest(".tabcontent");
        if (tab) tab.style.display = "block";
      });
      const box = await page.locator("#clearprogram").boundingBox();
      if (!box || box.width <= 0 || box.height <= 0) throw new Error(scenario + " clear button is not visible");

      const beforeCancel = await page.evaluate(() => window.__programRequests.length);
      const cancelled = await page.evaluate(() => {
        window.confirm = () => false;
        return SamovarApp.clearProgram();
      });
      const afterCancel = await page.evaluate(() => window.__programRequests.length);
      if (cancelled !== false || afterCancel !== beforeCancel) {
        throw new Error(scenario + " cancelled confirmation sent a request");
      }

      for (const status of [202, 400, 409, 503]) {
        const before = await page.evaluate(statusValue => {
          window.__programStatus = statusValue;
          localStorage.removeItem("samovarHistoryV2");
          return window.__programRequests.length;
        }, status);
        const result = await page.evaluate(() => {
          window.confirm = () => true;
          return SamovarApp.clearProgram();
        });
        const requestState = await page.evaluate(() => ({
          count: window.__programRequests.length,
          sent: window.__programRequests[window.__programRequests.length - 1]
        }));
        if (requestState.count !== before + 1) {
          throw new Error(scenario + " status " + status + " request count mismatch");
        }
        const sent = requestState.sent;
        if (sent.method !== "POST" || JSON.stringify(sent.entries) !== JSON.stringify([["clear", "1"]])) {
          throw new Error(scenario + " status " + status + " invalid clear body: " + JSON.stringify(sent));
        }
        const history = await page.evaluate(() => JSON.parse(localStorage.getItem("samovarHistoryV2") || "[]"));
        const lastMessage = history.length ? history[history.length - 1].msg : "";
        const feedback = await page.evaluate(() => {
          const box = document.getElementById("messagesBox");
          const list = document.getElementById("messages");
          return {
            visible: !!box && getComputedStyle(box).display !== "none",
            text: list ? list.textContent : ""
          };
        });
        if (!feedback.visible) {
          throw new Error(scenario + " status " + status + " feedback is not visible");
        }
        if (status === 202) {
          if (result !== true || lastMessage !== "Программа очищена." ||
              !feedback.text.includes(lastMessage)) {
            throw new Error(scenario + " terminal response mismatch: " + JSON.stringify({ result, lastMessage, feedback }));
          }
        } else if (result !== false || !lastMessage.includes("HTTP " + status) ||
                   !lastMessage.includes("E" + status) || !feedback.text.includes(lastMessage)) {
          throw new Error(scenario + " error response mismatch: " + JSON.stringify({ status, result, lastMessage, feedback }));
        }
      }
      totalRequests += await page.evaluate(() => window.__programRequests.length);
      passed.push(scenario);
    }
  }

  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { passed: passed, requests: totalRequests };
}'''


class QuietHandler(http.server.SimpleHTTPRequestHandler):
  def log_message(self, format, *args):
    pass


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
  session = f"samovar-program-clear-{os.getpid()}"
  primary_error = None

  try:
    with tempfile.TemporaryDirectory(prefix="samovar-program-clear-browser-") as temp_dir:
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
      print(f"Program clear UI browser contract failed: {primary_error}", file=sys.stderr)
    for error in cleanup_errors:
      print(f"Program clear UI browser cleanup failed: {error}", file=sys.stderr)
    return 1

  print("Program clear UI browser contract passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
