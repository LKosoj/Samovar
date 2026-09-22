#!/usr/bin/env python3
"""Playwright: настройка скрывает схему во всех режимах прошивки."""

import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler, render_site, run_cli
from test_numeric_input_ui_browser import UI_BOOTSTRAP_FIXTURE


ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const bootstrap = __BOOTSTRAP__;
  const pages = [
    ["index.htm", 0], ["distiller.htm", 1], ["beer.htm", 2],
    ["bk.htm", 3], ["nbk.htm", 4], ["cheese.htm", 7]
  ];
  const ajax = {
    version:"test", crnt_tm:"12:00:00", stm:"00:01:00", SteamTemp:78.1, PipeTemp:77.9,
    WaterTemp:20.2, TankTemp:82.3, ACPTemp:40.1, bme_pressure:760, start_pressure:759.5,
    prvl:1.2, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0, CurrrentSpeed:0,
    CurrrentStepps:0, TargetStepps:0, WthdrwlStatus:0, ProgramNum:0, DetectorTrend:0,
    DetectorStatus:0, useautospeed:false, current_power_volt:0, target_power_volt:0,
    current_power_mode:"0", current_power_p:0, WFtotalMl:0, WFflowRate:0, bme_temp:24,
    heap:200000, rssi:-50, fr_bt:300000, UseBBuzzer:false, PauseOn:0, PrgType:"",
    Status:"Готов", Lstatus:"", TimeRemaining:0, TotalTime:0, alc:0, stm_alc:0,
    ISspd:0, wp_spd:0, i2c_pump_present:0, i2c_pump_running:0,
    i2c_pump_remaining_ml:0, i2c_pump_speed:0, PowerOn:0,
    heaterAlarmLatched:0, heaterAlarmReason:"", latestMessageSequence:0,
    BeerBrewOrder:"allinone"
  };
  let current = {...bootstrap};
  const problems = [];
  page.on("console", message => {
    if (["warning", "error"].includes(message.type())) problems.push(message.text());
  });
  page.on("pageerror", error => problems.push(error.message));
  await page.route("**/ui-bootstrap", route => route.fulfill({
    status:200, contentType:"application/json", body:JSON.stringify(current)
  }));
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status:200, contentType:"application/json", body:JSON.stringify(ajax)
  }));
  function expect(value, message) { if (!value) throw new Error(message); }
  for (const [name, mode] of pages) {
    for (const hidden of [false, true]) {
      current = {...bootstrap, mode, hideProcessScheme:hidden};
      await page.goto(baseUrl + "/" + name, {waitUntil:"load"});
      await page.waitForFunction(() => document.body.inert === false);
      const result = await page.locator("#sec-scheme").evaluate(node => ({
        hidden:node.hidden, display:getComputedStyle(node).display
      }));
      expect(result.hidden === hidden, name + " hidden=" + hidden + ": " + JSON.stringify(result));
      expect((result.display === "none") === hidden,
        name + " rendered visibility=" + hidden + ": " + JSON.stringify(result));
    }
  }
  expect(problems.length === 0, "console/page errors: " + problems.join("; "));
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the process scheme visibility gate")
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-scheme-visibility-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-scheme-visibility-{os.getpid()}"
        script = BROWSER_TEST.replace(
            "__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}")
        ).replace("__BOOTSTRAP__", json.dumps(UI_BOOTSTRAP_FIXTURE))
        try:
            config = temp / "playwright.json"
            config.write_text(
                json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}),
                encoding="utf-8",
            )
            run_cli(cli, session, ["open", f"--config={config}"], temp, timeout=30)
            run_cli(cli, session, ["run-code", script], ROOT, timeout=60)
        finally:
            run_cli(cli, session, ["close"], ROOT, timeout=15, check=False)
            server.shutdown()
            thread.join(timeout=5)
    print("process scheme visibility browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
