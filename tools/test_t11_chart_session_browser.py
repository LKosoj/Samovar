#!/usr/bin/env python3
"""T11: история графика не смешивает две сессии при запоздалом CSV."""

import contextlib
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

from test_numeric_input_ui_browser import UI_BOOTSTRAP_FIXTURE, QuietHandler, cleanup, render_site, run_cli


CSV_A = "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\nA-csv,71,70,20,80,760,1\n"
CSV_B = "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\nB-csv,82,81,21,90,761,2\n"
CSV_C = "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\nC-csv,83,82,22,91,762,3\n"
CSV_D = "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\nD-csv,84,83,23,92,763,4\n"

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const csvA = __CSV_A__;
  const csvB = __CSV_B__;
  const csvC = __CSV_C__;
  const csvD = __CSV_D__;
  let csvRequests = 0;
  let firstCsvBusy = true;
  let manualFailure = "";
  let delayOldA = false;
  let oldAStarted = false;
  let releaseOldA;
  const oldAReleased = new Promise(resolve => { releaseOldA = resolve; });
  const errors = [];

  const telemetry = (sessionId, time, steam) => ({
    sessionId, crnt_tm: time, stm: "00:00:00", SteamTemp: steam, PipeTemp: steam - 1,
    WaterTemp: 20, TankTemp: 80, ACPTemp: 20, VolumeAll: 0, ActualVolumePerHour: 0,
    WthdrwlProgress: 0, Status: "Готов", PrgType: "", bme_temp: 20, heap: 1,
    rssi: -50, fr_bt: 1, UseBBuzzer: false, PowerOn: 0
  });

  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/ui-bootstrap", route => route.fulfill({status: 200, contentType: "application/json", body: JSON.stringify(__BOOTSTRAP__)}));
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({status: 200, contentType: "application/json", body: JSON.stringify(telemetry(101, "A-poll", 71))}));
  await page.route("**/data.csv", async route => {
    csvRequests += 1;
    if (firstCsvBusy) {
      firstCsvBusy = false;
      await route.fulfill({status: 503, contentType: "text/plain", body: "BUSY"});
      return;
    }
    if (manualFailure) {
      const failure = manualFailure;
      manualFailure = "";
      if (failure === "network") {
        await route.abort("failed");
      } else {
        await route.fulfill({status: 500, contentType: "text/plain", body: "failure"});
      }
      return;
    }
    if (delayOldA) {
      delayOldA = false;
      oldAStarted = true;
      await oldAReleased;
      await route.fulfill({status: 200, contentType: "text/csv", body: csvA});
      return;
    }
    const sessionId = await page.evaluate(() => chartSessionId);
    await route.fulfill({status: 200, contentType: "text/csv", body: sessionId === 202 ? csvB : sessionId === 303 ? csvC : sessionId === 404 ? csvD : csvA});
  });

  await page.goto(baseUrl + "/chart.htm", {waitUntil: "load"});
  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.fetch = async function () {
      const response = await originalFetch.apply(this, arguments);
      if (!window.__delayNextCsvText) return response;
      window.__delayNextCsvText = false;
      const originalText = response.text.bind(response);
      response.text = function () {
        window.__oldCsvTextHeld = true;
        return new Promise(function (resolve, reject) {
          window.__rejectOldCsvText = function () { reject(new Error("late A body failed")); };
          window.__releaseOldCsvText = function () { originalText().then(resolve, reject); };
        });
      };
      return response;
    };
  });
  try {
    await page.waitForFunction(() => chart && chart.rows.length === 1, null, {timeout: 10000});
  } catch (error) {
    throw new Error("initial CSV after 503 did not load: " + JSON.stringify(await page.evaluate(() => ({
      chart: !!chart, rows: chart ? chart.rows.length : -1, status: chart ? chart.status.textContent : ""
    }))));
  }

  await page.evaluate(() => renderTelemetry({
    sessionId: 101, crnt_tm: "A-first", stm: "00:00:00", SteamTemp: 71, PipeTemp: 70,
    WaterTemp: 20, TankTemp: 80, ACPTemp: 20, VolumeAll: 0, ActualVolumePerHour: 0,
    WthdrwlProgress: 0, Status: "Готов", PrgType: "", bme_temp: 20, heap: 1,
    rssi: -50, fr_bt: 1, UseBBuzzer: false, PowerOn: 0
  }));
  await page.waitForFunction(() => chartSessionId === 101 && chartCsvSessionId === 101 && chart.rows[0].Date === "A-csv");
  const beforeNormal = csvRequests;
  await page.evaluate(() => {
    chartLastAppendMs = 0;
    renderTelemetry({sessionId:101, crnt_tm:"A-ajax-1", stm:"00", SteamTemp:72, PipeTemp:71, WaterTemp:20, TankTemp:80, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0});
    chartLastAppendMs = 0;
    renderTelemetry({sessionId:101, crnt_tm:"A-ajax-2", stm:"00", SteamTemp:73, PipeTemp:72, WaterTemp:20, TankTemp:80, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0});
  });
  if (csvRequests !== beforeNormal) throw new Error("ordinary session must not reload full CSV for each AJAX point");

  delayOldA = true;
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await page.waitForFunction(() => true, null, {timeout: 50}).catch(() => {});
  const oldDeadline = Date.now() + 1000;
  while (!oldAStarted && Date.now() < oldDeadline) await page.waitForTimeout(10);
  if (!oldAStarted) throw new Error("visible tab must request CSV for the active session");

  await page.evaluate(() => renderTelemetry({sessionId:202, crnt_tm:"B-first", stm:"00", SteamTemp:82, PipeTemp:81, WaterTemp:21, TankTemp:90, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0}));
  await page.waitForFunction(() => chartSessionId === 202 && chartCsvSessionId === 202 && chart.rows.length === 1 && chart.rows[0].Date === "B-csv");
  releaseOldA();
  await page.waitForTimeout(100);
  const afterLateA = await page.evaluate(() => ({
    rows: chart.rows.map(row => row.Date), session: chartSessionId
  }));
  if (afterLateA.session !== 202 || afterLateA.rows.some(date => date.indexOf("A-") === 0) || !afterLateA.rows.includes("B-csv")) {
    throw new Error("late A CSV must not overwrite B: " + JSON.stringify(afterLateA));
  }
  await page.evaluate(() => {
    chartLastAppendMs = 0;
    renderTelemetry({sessionId:202, crnt_tm:"B-ajax", stm:"00", SteamTemp:83, PipeTemp:82, WaterTemp:21, TankTemp:90, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0});
  });
  const finalRows = await page.evaluate(() => chart.rows.map(row => row.Date));
  if (!finalRows.includes("B-ajax") || finalRows.some(date => date.indexOf("A-") === 0)) {
    throw new Error("new session must contain only its CSV and AJAX points: " + JSON.stringify(finalRows));
  }
  await page.evaluate(() => {
    window.__delayNextCsvText = true;
    renderTelemetry({sessionId:101, crnt_tm:"A-error", stm:"00", SteamTemp:72, PipeTemp:71, WaterTemp:20, TankTemp:80, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0});
  });
  await page.waitForFunction(() => window.__oldCsvTextHeld === true);
  await page.evaluate(() => renderTelemetry({sessionId:202, crnt_tm:"B-error", stm:"00", SteamTemp:83, PipeTemp:82, WaterTemp:21, TankTemp:90, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0}));
  await page.waitForFunction(() => chartSessionId === 202 && chartCsvSessionId === 202 && chart.rows[0].Date === "B-csv");
  await page.evaluate(() => window.__rejectOldCsvText());
  await page.waitForTimeout(100);
  const afterLateError = await page.evaluate(() => ({
    rows: chart.rows.map(row => row.Date), status: chart.status.textContent
  }));
  if (afterLateError.rows.some(date => date.indexOf("A-") === 0) ||
      afterLateError.status.indexOf("Ошибка загрузки графика") !== -1) {
    throw new Error("late A body error must not replace B status: " + JSON.stringify(afterLateError));
  }
  manualFailure = "http";
  await page.evaluate(() => renderTelemetry({sessionId:303, crnt_tm:"C-first", stm:"00", SteamTemp:83, PipeTemp:82, WaterTemp:22, TankTemp:91, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0}));
  await page.waitForFunction(() => chartSessionId === 303 && !chart.loading && chart.status.querySelector("button"));
  await page.locator(".chart-status button").click();
  await page.waitForFunction(() => chartCsvSessionId === 303 && chart.rows.length === 1 && chart.rows[0].Date === "C-csv").catch(() => {
    throw new Error("manual HTTP retry did not confirm the current session");
  });
  await page.evaluate(() => {
    chartLastAppendMs = 0;
    renderTelemetry({sessionId:303, crnt_tm:"C-ajax", stm:"00", SteamTemp:84, PipeTemp:83, WaterTemp:22, TankTemp:91, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0});
  });
  if (!(await page.evaluate(() => chart.rows.map(row => row.Date))).includes("C-ajax")) {
    throw new Error("manual HTTP retry must restore session completion before AJAX points");
  }

  manualFailure = "network";
  await page.evaluate(() => renderTelemetry({sessionId:404, crnt_tm:"D-first", stm:"00", SteamTemp:84, PipeTemp:83, WaterTemp:23, TankTemp:92, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0}));
  await page.waitForFunction(() => chartSessionId === 404 && !chart.loading && chart.status.querySelector("button"));
  await page.locator(".chart-status button").click();
  await page.waitForFunction(() => chartCsvSessionId === 404 && chart.rows.length === 1 && chart.rows[0].Date === "D-csv").catch(() => {
    throw new Error("manual network retry did not confirm the current session");
  });
  await page.evaluate(() => {
    chartLastAppendMs = 0;
    renderTelemetry({sessionId:404, crnt_tm:"D-ajax", stm:"00", SteamTemp:85, PipeTemp:84, WaterTemp:23, TankTemp:92, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1, rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0});
  });
  if (!(await page.evaluate(() => chart.rows.map(row => row.Date))).includes("D-ajax")) {
    throw new Error("manual network retry must restore session completion before AJAX points");
  }
  if (csvRequests < 8) throw new Error("expected retries, visible reload, session reloads, and manual retries: " + csvRequests);
  if (errors.length) throw new Error(errors.join("\n"));
  return {requests: csvRequests, rows: finalRows};
}'''


def run_browser(site: Path, temp: Path, label: str) -> str:
    cli = shutil.which("playwright-cli")
    if not cli:
        return "playwright-cli is required for T11 browser contract"
    handler = functools.partial(QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = f"samovar-t11-chart-{os.getpid()}-{label}"
    try:
        args = ["open"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            config = temp / f"playwright-{label}.json"
            config.write_text(json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
            args.append(f"--config={config}")
        run_cli(cli, session, args, temp, 30)
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                code = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}")).replace("__CSV_A__", json.dumps(CSV_A)).replace("__CSV_B__", json.dumps(CSV_B)).replace("__CSV_C__", json.dumps(CSV_C)).replace("__CSV_D__", json.dumps(CSV_D)).replace("__BOOTSTRAP__", json.dumps(UI_BOOTSTRAP_FIXTURE))
                run_cli(cli, session, ["run-code", code], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            return captured.getvalue() or str(error)
        print(captured.getvalue(), end="")
        return ""
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        return str(error)
    finally:
        cleanup(cli, session, server, thread)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-t11-chart-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        page = site / "chart.js"
        source = page.read_text(encoding="utf-8")
        original_error = run_browser(site, temp, "original")
        if original_error:
            print("T11 chart browser contract failed: " + original_error, file=sys.stderr)
            return 1
        mutant = source.replace("if (!isCurrentLoad()) return false;", "if (false) return false;")
        if mutant == source:
            print("T11 late-response mutation anchor not found", file=sys.stderr)
            return 1
        page.write_text(mutant, encoding="utf-8")
        mutation_error = run_browser(site, temp, "late-response-mutant")
        error_section = mutation_error.split("### Ran Playwright code", 1)[0]
        if "late A CSV must not overwrite B" not in error_section:
            print("T11 late-response mutation did not fail expected assertion", file=sys.stderr)
            return 1
        page.write_text(source, encoding="utf-8")
        body_error_mutant = source.replace(
            "if (!isCurrentLoad()) return false;\n          this.setStatus('Ошибка загрузки графика: ' + err, true, retry);",
            "if (false) return false;\n          this.setStatus('Ошибка загрузки графика: ' + err, true, retry);",
            1,
        )
        if body_error_mutant == source:
            print("T11 late-body-error mutation anchor not found", file=sys.stderr)
            return 1
        page.write_text(body_error_mutant, encoding="utf-8")
        mutation_error = run_browser(site, temp, "late-body-error-mutant")
        error_section = mutation_error.split("### Ran Playwright code", 1)[0]
        if "late A body error must not replace B status" not in error_section:
            print("T11 late-body-error mutation did not fail expected assertion", file=sys.stderr)
            return 1
        page.write_text(source, encoding="utf-8")
        retry_mutant = source.replace(
            "const retry = retryFn || function () { self.loadCsv(url); };",
            "const retry = function () { self.loadCsv(url); };",
            1,
        )
        if retry_mutant == source:
            print("T11 manual-retry mutation anchor not found", file=sys.stderr)
            return 1
        page.write_text(retry_mutant, encoding="utf-8")
        mutation_error = run_browser(site, temp, "manual-retry-mutant")
        error_section = mutation_error.split("### Ran Playwright code", 1)[0]
        if "manual HTTP retry did not confirm the current session" not in error_section:
            print("T11 manual-retry mutation did not fail expected assertion", file=sys.stderr)
            return 1
    print("T11 chart browser contract passed; stale-response mutation rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
