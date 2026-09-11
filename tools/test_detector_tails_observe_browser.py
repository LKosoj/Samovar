#!/usr/bin/env python3
"""Browser contract for observation-only impurity-detector tails."""

import argparse
import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler, render_site, run_cli, run_cli_report


ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const telemetry = {
    version: "test", crnt_tm: "12:00:00", stm: "00:01:00", SteamTemp: 78.1,
    PipeTemp: 77.9, WaterTemp: 20.2, TankTemp: 82.3, ACPTemp: 40.1,
    bme_pressure: 760, start_pressure: 759.5, prvl: 1.2, VolumeAll: 0,
    ActualVolumePerHour: 0, WthdrwlProgress: 0, CurrrentSpeed: 0,
    CurrrentStepps: 0, TargetStepps: 0, WthdrwlStatus: 0, ProgramNum: 1,
    DetectorTrend: 0, DetectorStatus: 0, DetectorIdle: 0, useDetector: true,
    useautospeed: true, current_power_volt: 0, target_power_volt: 0,
    current_power_mode: "0", current_power_p: 0, WFtotalMl: 0, WFflowRate: 0,
    bme_temp: 24, heap: 200000, rssi: -50, fr_bt: 300000, UseBBuzzer: false,
    PauseOn: 0, PrgType: "T", Status: "Работа", Lstatus: "",
    TimeRemaining: 0, TotalTime: 0, alc: 0, stm_alc: 0, ISspd: 0, wp_spd: 0,
    i2c_pump_present: 0, i2c_pump_running: 0, i2c_pump_remaining_ml: 0,
    i2c_pump_speed: 0, PowerOn: 0, StepperStepMl: 100,
    heaterAlarmLatched: 0, heaterAlarmReason: "", latestMessageSequence: 0
  };
  const failures = [];
  const consoleProblems = [];
  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error")
      consoleProblems.push(message.type() + ": " + message.text());
  });
  page.on("pageerror", error => consoleProblems.push("pageerror: " + error.message));
  await page.addInitScript(() => {
    window.Audio = function() { this.play = () => Promise.resolve(); this.pause = () => {}; };
  });
  await page.route("**/ui-bootstrap", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({
      mode: 0, version: "test", powerUnit: "V", program: "T;0;0;0;0;0",
      description: "", luaButtonList: "", steamColor: "#000", pipeColor: "#000",
      waterColor: "#000", tankColor: "#000", acpColor: "#000", steamVisible: true,
      pipeVisible: true, waterVisible: true, tankVisible: true, pressureVisible: true,
      programNumberVisible: true, i2cStepperVisible: false, i2cPumpVisible: false,
      beerBrewOrder: "allinone", pwmLow: 0, pwmValue: 0, nbkDp: 0,
      columnDiameter: 2, columnHeight: 1, packDensity: 80, heaterResistance: 10,
      mainsVoltage: 230, heaterMaxPower: 230, stepperMaxSpeed: 1000,
      stepperStepsPerMl: 100, i2cStepperStepsPerMl: 100,
      calibrationRunning: false, calibrationPump: "local", cheesePhSlope: 1,
      cheesePhOffset: 0, cheeseCoolingScheme: "pump", cheesePhAvailable: true,
      cheesePhAds1115Address: 0
    })
  }));
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(telemetry)
  }));
  function expect(value, message) { if (!value) failures.push(message); }
  await page.goto(baseUrl + "/index.htm", {waitUntil: "load"});
  async function show(next, cardText, diagramText, trendText) {
    Object.assign(telemetry, next);
    await page.reload({waitUntil: "load"});
    await page.waitForSelector("#detector_status_text");
    await page.waitForFunction(() => {
      const diagramNode = document.querySelector('[data-tele="_detectorText"]');
      const cardNode = document.getElementById("detector_status_text");
      return cardNode && cardNode.textContent !== "" && diagramNode && diagramNode.textContent !== "";
    });
    const card = await page.locator("#detector_status_text").textContent();
    const diagram = await page.locator('[data-tele="_detectorText"]').textContent();
    expect(card.includes(cardText), "card: expected " + cardText + ", got " + card);
    if (diagramText) expect(diagram.includes(diagramText), "diagram: expected " + diagramText + ", got " + diagram);
    if (trendText) {
      const trend = await page.locator("#detector_trend").textContent();
      expect(trend.includes(trendText), "trend: expected " + trendText + ", got " + trend);
    }
  }
  for (const trend of [-0.019, 0, 0.064]) {
    await show({PrgType: "T", DetectorIdle: 8, DetectorStatus: 0, DetectorTrend: trend,
      useDetector: true}, "Хвосты: наблюдение", "наблюдение",
      trend === 0 ? "0.000" : trend.toFixed(3));
  }
  await show({PrgType: "H", DetectorIdle: 2, DetectorStatus: 2, DetectorTrend: 0.011},
    "Головы: наблюдение", null, "+0.011");
  await show({PrgType: "B", DetectorIdle: 0, DetectorStatus: 1, useautospeed: true},
    "снижаю скорость", "снижаю скорость");
  await show({PrgType: "C", DetectorIdle: 0, DetectorStatus: 2}, "ПРОСКОК", "проскок");
  await show({PrgType: "T", DetectorIdle: 0, DetectorStatus: 2}, "ПРОСКОК", "проскок");
  await show({PrgType: "T", DetectorIdle: 7, DetectorStatus: 2}, "Пауза", "пауза");
  Object.assign(telemetry, {useDetector: false, DetectorIdle: 8, DetectorStatus: 2});
  await page.reload({waitUntil: "load"});
  await page.waitForFunction(() => document.getElementById("detector_block").style.display === "none");
  expect((await page.locator('[data-tele="_detectorText"]').textContent()).includes("выкл"),
    "diagram: detector off must remain off");
  expect(consoleProblems.length === 0, consoleProblems.join("\n"));
  return "__U05_RESULT__" + JSON.stringify({failures, consoleProblems});
}'''


def served_app(source: Path, mutation: str | None) -> str:
    app = source.read_text(encoding="utf-8")
    if mutation == "card":
        needle = "case 8: return '👁 Хвосты: наблюдение';"
        assert needle in app, "card mutation target is absent"
        return app.replace(needle, "case 8: return '';", 1)
    if mutation == "diagram":
        needle = ": detIdle === 8 ? 'наблюдение'"
        assert needle in app, "diagram mutation target is absent"
        return app.replace(needle, ": detIdle === 8 ? '—'", 1)
    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=ROOT / "data_raw" / "app.js")
    parser.add_argument("--mutation", choices=("card", "diagram"))
    args = parser.parse_args()
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the detector tails browser gate", file=sys.stderr)
        return 1
    error = None
    cleanup_errors = []
    report = {}
    with tempfile.TemporaryDirectory(prefix="samovar-detector-tails-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        (site / "app.js").write_text(served_app(args.app, args.mutation), encoding="utf-8")
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-detector-tails-ui-{os.getpid()}"
        opened = False
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            opened = True
            report = run_cli_report(cli, session, BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}")), temp, 120)
        except (OSError, RuntimeError) as caught:
            error = str(caught)
        finally:
            if opened:
                try:
                    if run_cli(cli, session, ["close"], temp, 30, check=False) != 0:
                        cleanup_errors.append("playwright-cli close failed")
                except OSError as caught:
                    cleanup_errors.append(str(caught))
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    failures = [str(item) for item in report.get("failures", [])]
    if failures and error is None:
        error = f"{len(failures)} assertions failed; first: {failures[0]}"
    if error or cleanup_errors:
        if error:
            print(f"detector tails browser gate failed: {error}", file=sys.stderr)
        for cleanup_error in cleanup_errors:
            print(f"browser cleanup failed: {cleanup_error}", file=sys.stderr)
        return 1
    print("detector tails browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
