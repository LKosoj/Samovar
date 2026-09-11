#!/usr/bin/env python3
"""Browser contract for T08 invalid alcohol telemetry rendering."""

import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler, render_site, run_cli, run_cli_report


APP_GUARD = """    v._alcCube = typeof data.alc === 'number' && Number.isFinite(data.alc) && data.alc >= 0
      ? data.alc : null;"""
DISTILLER_GUARD = """          document.getElementById('alc').innerHTML = alcoholText(myObj.alc, 1);"""

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const mutationOnly = __MUTATION_ONLY__;
  const telemetry = {
    version:"test",crnt_tm:"12:00:00",stm:"00:01:00",
    SteamTemp:78.1,PipeTemp:77.9,WaterTemp:20.2,TankTemp:82.3,ACPTemp:40.1,
    bme_pressure:760,start_pressure:759.5,prvl:1.2,VolumeAll:0,
    ActualVolumePerHour:0,WthdrwlProgress:0,CurrrentSpeed:0,CurrrentStepps:0,
    TargetStepps:0,WthdrwlStatus:0,ProgramNum:0,DetectorTrend:0.012,
    DetectorStatus:2,useDetector:true,useautospeed:true,
    current_power_volt:220,target_power_volt:220,current_power_mode:"WORK",
    current_power_p:2000,WFtotalMl:10,WFflowRate:2,bme_temp:24,heap:200000,
    rssi:-50,fr_bt:300000,UseBBuzzer:false,PauseOn:0,PrgType:"L",Status:"Работа",
    Lstatus:"",TimeRemaining:12,RowTotalTime:22,ProcessTimeRemaining:32,
    TotalTime:42,RowPredictionAvailable:1,ProcessPredictionAvailable:1,
    RowPredictionReason:2,ProcessPredictionReason:2,alc:50,stm_alc:70,ISspd:0,
    wp_spd:0,i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,
    i2c_pump_speed:0,PowerOn:1,StepperStepMl:100,
    heaterAlarmLatched:0,heaterAlarmReason:'',latestMessageSequence:0,
    BeerBrewOrder:"allinone"
  };
  const failures = [];
  const consoleProblems = [];
  function expect(value, message) { if (!value) failures.push(message); }
  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error")
      consoleProblems.push(message.type() + ": " + message.text());
  });
  page.on("pageerror", error => consoleProblems.push("pageerror: " + error.message));
  await page.addInitScript(() => {
    window.Audio = function() { this.play = () => Promise.resolve(); this.pause = () => {}; };
  });
  await page.route("**/ajax*", route => route.fulfill({
    status:200,contentType:"application/json",body:JSON.stringify(telemetry)
  }));
  await page.goto(baseUrl + "/distiller.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.getElementById("TimeRemaining").textContent !== "--");

  async function alcoholValues(cube, steam) {
    await page.evaluate(values => {
      const next = Object.assign({}, values.telemetry, {alc: values.cube, stm_alc: values.steam});
      renderTelemetry(next);
      SamovarApp.renderScheme(next);
    }, {telemetry, cube, steam});
    return {
      legacyCube: (await page.locator("#alc").textContent()).trim(),
      legacySteam: (await page.locator("#stm_alc").textContent()).trim(),
      schemeCube: (await page.locator('[data-tele="_alcCube"]').allTextContents()).map(value => value.trim()),
      schemeSteam: (await page.locator('[data-tele="_alcSteam"]').allTextContents()).map(value => value.trim())
    };
  }
  function expectAlcohol(values, cube, steam, label) {
    expect(values.legacyCube === cube.legacy,
           label + " cube legacy card must show " + cube.legacy + ", got " + values.legacyCube);
    expect(values.legacySteam === steam.legacy,
           label + " steam legacy card must show " + steam.legacy + ", got " + values.legacySteam);
    expect(values.schemeCube.length === 2 && values.schemeCube.every(value => value === cube.scheme),
           label + " cube key and diagram must show " + cube.scheme + ", got " + JSON.stringify(values.schemeCube));
    expect(values.schemeSteam.length === 2 && values.schemeSteam.every(value => value === steam.scheme),
           label + " steam key and diagram must show " + steam.scheme + ", got " + JSON.stringify(values.schemeSteam));
  }

  expectAlcohol(await alcoholValues(-1, -1),
                {legacy:"—", scheme:"—"}, {legacy:"—", scheme:"—"},
                "negative invalid alcohol");
  if (!mutationOnly) {
    expectAlcohol(await alcoholValues(0, 63.456),
                  {legacy:"0.0", scheme:"0.0"}, {legacy:"63.46", scheme:"63.5"},
                  "valid alcohol");
    expectAlcohol(await alcoholValues(null, NaN),
                  {legacy:"—", scheme:"—"}, {legacy:"—", scheme:"—"},
                  "non-numeric invalid alcohol");
  }
  expect(consoleProblems.length === 0, consoleProblems.join("\n"));
  return "__U05_RESULT__" + JSON.stringify({failures});
}'''


def run_case(cli: str, temp: Path, port: int, label: str,
             mutation_only: bool = False) -> tuple[dict[str, object], str | None, list[str]]:
    session = f"samovar-t08-alcohol-{label}-{os.getpid()}"
    opened = False
    cleanup_errors = []
    try:
        config = temp / f"playwright-{label}.json"
        config.write_text(json.dumps({"browser": {"browserName": "chromium",
                                               "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
        run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
        opened = True
        code = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{port}"))
        code = code.replace("__MUTATION_ONLY__", "true" if mutation_only else "false")
        return run_cli_report(cli, session, code, temp, 120), None, cleanup_errors
    except (OSError, RuntimeError) as caught:
        return {}, str(caught), cleanup_errors
    finally:
        if opened:
            if run_cli(cli, session, ["close"], temp, 30, check=False) != 0:
                cleanup_errors.append(f"{label}: playwright-cli close failed")


def require_mutation_assertion(cli: str, temp: Path, site: Path, port: int, label: str,
                               path: Path, source: str, replacement: str,
                               expected_assertion: str) -> str | None:
    original = path.read_text(encoding="utf-8")
    if original.count(source) != 1:
        return f"{label}: source guard was not found exactly once"
    path.write_text(original.replace(source, replacement), encoding="utf-8")
    try:
        report, error, cleanup_errors = run_case(cli, temp, port, label, mutation_only=True)
    finally:
        path.write_text(original, encoding="utf-8")
    if error:
        return f"{label}: browser execution failed before assertion: {error}"
    if cleanup_errors:
        return "; ".join(cleanup_errors)
    failures = [str(item) for item in report.get("failures", [])]
    if not any(item.startswith(expected_assertion) for item in failures):
        return f"{label}: expected assertion was not reported: {expected_assertion}"
    return None


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the T08 alcohol UI browser gate")
        return 1
    errors = []
    with tempfile.TemporaryDirectory(prefix="samovar-t08-alcohol-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report, error, cleanup_errors = run_case(cli, temp, server.server_port, "normal")
            errors.extend(cleanup_errors)
            if error:
                errors.append(error)
            elif report.get("failures"):
                errors.append("normal: " + str(report["failures"][0]))
            else:
                for args in (
                    ("mutate-app", site / "app.js", APP_GUARD, "    v._alcCube = num(data.alc);",
                     "negative invalid alcohol cube key and diagram must show —"),
                    ("mutate-distiller", site / "distiller.htm", DISTILLER_GUARD,
                     "          document.getElementById('alc').innerHTML = myObj.alc.toFixed(1);",
                     "negative invalid alcohol cube legacy card must show —"),
                ):
                    mutation_error = require_mutation_assertion(
                        cli, temp, site, server.server_port, *args
                    )
                    if mutation_error:
                        errors.append(mutation_error)
                        break
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    if errors:
        print("T08 alcohol UI browser gate failed: " + "; ".join(errors))
        return 1
    print("T08 alcohol UI browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
