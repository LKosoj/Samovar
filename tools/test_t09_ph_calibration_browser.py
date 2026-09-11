#!/usr/bin/env python3
"""T09: настоящая страница калибровки pH через playwright-cli."""

import functools
import contextlib
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

from test_numeric_input_ui_browser import QuietHandler, cleanup, render_site, run_cli


BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const posts = [];
  await page.route("**/ui-bootstrap", route => route.fulfill({status:200, contentType:"application/json", body:JSON.stringify({
    mode:4, version:"t09", powerUnit:"V", program:"", description:"", luaButtonList:"",
    steamColor:"#111", pipeColor:"#222", waterColor:"#333", tankColor:"#444", acpColor:"#555",
    steamVisible:true, pipeVisible:true, waterVisible:true, tankVisible:true, pressureVisible:true,
    programNumberVisible:true, i2cStepperVisible:false, i2cPumpVisible:false, pwmLow:0, pwmValue:0,
    nbkDp:0, columnDiameter:2, columnHeight:1.5, packDensity:80, heaterResistance:10,
    mainsVoltage:230, heaterMaxPower:5290, stepperMaxSpeed:1000, stepperStepsPerMl:100,
    i2cStepperStepsPerMl:100, calibrationRunning:false, calibrationPump:"local",
    cheesePhSlope:0.003, cheesePhOffset:7, cheesePhAvailable:true, cheesePhAds1115Address:0,
    cheeseCoolingScheme:"pump"
  })}));
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({status:200, contentType:"application/json", body:JSON.stringify({
    latestMessageSequence:0, heaterAlarmLatched:0, heaterAlarmReason:"", CheesePhRaw:100,
    CheesePhRawValid:1, CheesePh:7.3, CheesePhValid:1
  })}));
  await page.route("**/save", async route => {
    posts.push(await route.request().postData());
    await route.fulfill({status:202, contentType:"application/json", body:JSON.stringify({
      ok:true, err:"", program:"", operationId:1, state:"queued", error:"none"
    })});
  });
  await page.goto(baseUrl + "/calibrate_ph.htm", {waitUntil:"load"});
  await page.waitForFunction(() => window.phAvailable === true);
  const result = await page.evaluate(async () => {
    const out = {};
    latestPh = {raw:100, value:7, rawValid:true, valid:true};
    document.getElementById("point1Ph").value = "";
    out.empty = capturePhPoint(0);
    document.getElementById("point1Ph").value = "6";
    out.first = capturePhPoint(0);
    latestPh.raw = 200;
    document.getElementById("point2Ph").value = "6";
    out.samePh = calculatePhCalibration();
    calibrationPoints[1] = {raw:100, ph:7};
    out.sameRaw = calculatePhCalibration();
    calibrationPoints = [{raw:100, ph:4}, {raw:200, ph:6}];
    out.positive = calculatePhCalibration();
    out.positiveSlope = Number(document.getElementById("CheesePhSlope").value);
    calibrationPoints = [{raw:100, ph:8}, {raw:200, ph:6}];
    out.negative = calculatePhCalibration();
    out.negativeSlope = Number(document.getElementById("CheesePhSlope").value);
    document.getElementById("CheesePhSlope").value = "0";
    document.getElementById("CheesePhOffset").value = "7";
    out.zeroSave = await savePhCalibration();
    return out;
  });
  if (result.empty) throw new Error("empty pH point must be rejected");
  if (!result.first || result.samePh || result.sameRaw || !result.positive || !result.negative ||
      !(result.positiveSlope > 0) || !(result.negativeSlope < 0)) {
    throw new Error("pH points must reject equal values and accept both polarities: " + JSON.stringify(result));
  }
  if (result.zeroSave || posts.length !== 0) {
    throw new Error("zero pH slope must not POST /save: " + JSON.stringify({result, posts}));
  }
  return result;
}'''


def run_browser(site: Path, temp: Path, label: str) -> str:
    cli = shutil.which("playwright-cli")
    if not cli:
        return "playwright-cli is required for T09 browser contract"
    handler = functools.partial(QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = f"samovar-t09-ph-{os.getpid()}-{label}"
    try:
        open_args = ["open"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            config = temp / f"playwright-{label}.json"
            config.write_text(json.dumps({"browser":{"browserName":"chromium","launchOptions":{"chromiumSandbox":False}}}), encoding="utf-8")
            open_args.append(f"--config={config}")
        run_cli(cli, session, open_args, temp, 30)
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                run_cli(cli, session, ["run-code", BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            return captured.getvalue() or str(error)
        print(captured.getvalue(), end="")
        return ""
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        return str(error)
    finally:
        cleanup(cli, session, server, thread)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-t09-ph-browser-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        page = site / "calibrate_ph.htm"
        source = page.read_text(encoding="utf-8")
        original_error = run_browser(site, temp, "original")
        if original_error:
            print(f"T09 original pH browser contract failed: {original_error}", file=sys.stderr)
            return 1
        for label, old, new, expected_error in (
            ("empty pH", "!phText || ", "", "empty pH point must be rejected"),
            ("zero slope", "!slopeText || !offsetText || !Number.isFinite(slope) || !Number.isFinite(offset) || slope === 0", "!slopeText || !offsetText || !Number.isFinite(slope) || !Number.isFinite(offset) || false", "zero pH slope must not POST /save"),
        ):
            mutated = source.replace(old, new, 1)
            if mutated == source:
                print(f"T09 {label} mutation anchor not found", file=sys.stderr)
                return 1
            page.write_text(mutated, encoding="utf-8")
            mutation_error = run_browser(site, temp, label)
            error_section = mutation_error.split("### Ran Playwright code", 1)[0]
            if expected_error not in error_section:
                print(f"T09 {label} mutation did not fail with expected assertion", file=sys.stderr)
                return 1
            page.write_text(source, encoding="utf-8")
    print("T09 pH browser contract passed; mutations rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
