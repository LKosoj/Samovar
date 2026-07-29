#!/usr/bin/env python3
"""Browser contract for mode-logic telemetry and controls."""

import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import (
    EXPECTED_CLI,
    QuietHandler,
    render_site,
    run_cli,
    run_cli_report,
)

ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const telemetry = {
    version:"test",crnt_tm:"12:00:00",stm:"00:01:00",
    SteamTemp:78.1,PipeTemp:77.9,WaterTemp:20.2,TankTemp:82.3,ACPTemp:40.1,
    bme_pressure:760,start_pressure:759.5,prvl:1.2,VolumeAll:0,
    ActualVolumePerHour:0,WthdrwlProgress:0,CurrrentSpeed:0,CurrrentStepps:0,
    TargetStepps:0,WthdrwlStatus:0,ProgramNum:0,DetectorTrend:0.012,
    DetectorStatus:2,useautospeed:true,DetectorSteamSpan:0.03,
    DetectorSteamVariance:0.0002,DetectorSteamStableSeconds:125,
    DetectorSteamStabilityReason:3,DetectorSteamSpanThreshold:0.1,
    DetectorSteamVarianceThreshold:0.000625,DetectorRecoveryThreshold:0.02,
    DetectorRecoveryReady:1,BoilingEvidence:2,BoilingPrecisionSensorConfigured:1,
    current_power_volt:220,target_power_volt:220,current_power_mode:"WORK",
    current_power_p:2000,WFtotalMl:10,WFflowRate:2,bme_temp:24,heap:200000,
    rssi:-50,fr_bt:300000,UseBBuzzer:false,PauseOn:0,PrgType:"L",Status:"Работа",
    Lstatus:"",TimeRemaining:12,RowTotalTime:22,ProcessTimeRemaining:32,
    TotalTime:42,RowPredictionAvailable:1,ProcessPredictionAvailable:1,
    RowPredictionReason:2,ProcessPredictionReason:2,alc:50,stm_alc:70,ISspd:0,
    wp_spd:0,i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,
    i2c_pump_speed:0,PowerOn:1,StepperStepMl:100,
    heaterAlarmLatched:0,latestMessageSequence:0
  };
  const failures = [];
  const consoleProblems = [];
  const beerProgramPosts = [];
  let legacyDetectorPayload = false;
  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error")
      consoleProblems.push(message.type() + ": " + message.text());
  });
  page.on("pageerror", error => consoleProblems.push("pageerror: " + error.message));
  await page.addInitScript(() => {
    window.Audio = function() {
      this.play = () => Promise.resolve(); this.pause = () => {};
    };
  });
  await page.route("**/ajax*", route => {
    const operationMatch = route.request().url().match(/[?&]operationId=([^&]+)/);
    const operationId = operationMatch && Number(decodeURIComponent(operationMatch[1]));
    let body;
    if (operationId === null) {
      body = {...telemetry};
      if (legacyDetectorPayload) {
        for (const field of [
          "DetectorSteamSpan","DetectorSteamVariance","DetectorSteamStableSeconds",
          "DetectorSteamStabilityReason","DetectorSteamSpanThreshold",
          "DetectorSteamVarianceThreshold","DetectorRecoveryThreshold",
          "DetectorRecoveryReady"
        ]) delete body[field];
      }
    } else {
      body = {operationId:operationId,state:"succeeded",error:"none"};
    }
    return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
  });
  await page.route("**/program", route => {
    const request = route.request();
    if (request.method() === "POST") beerProgramPosts.push(request.postData() || "");
    return route.fulfill({
      status:202,
      contentType:"application/json",
      body:JSON.stringify({
        ok:true,err:"",program:"W;0;0;0^0^0^0;4",
        operationId:41,state:"queued",error:"none"
      })
    });
  });
  function expect(value, message) { if (!value) failures.push(message); }
  for (const viewport of [{width:390,height:844},{width:1440,height:900}]) {
    await page.setViewportSize(viewport);
    for (const theme of ["light","dark"]) {
      await page.goto(baseUrl + "/app.js");
      await page.evaluate(value => localStorage.setItem("theme", value), theme);

      await page.goto(baseUrl + "/index.htm", {waitUntil:"load"});
      await page.waitForFunction(() =>
        document.getElementById("detector_steam_stability").textContent !== "-"
      );
      const detector = await page.locator("#detector_steam_stability").textContent();
      expect(detector.includes("0.012 < 0.0200") &&
             detector.includes("условие выполнено"),
             "index recovery condition is not rendered");

      legacyDetectorPayload = true;
      await page.goto(baseUrl + "/index.htm", {waitUntil:"load"});
      await page.waitForFunction(() =>
        document.getElementById("detector_steam_stability").textContent.includes("недоступна")
      );
      expect((await page.locator("#SteamTemp").textContent()).trim() === "78.100",
             "legacy detector payload stopped core telemetry rendering");
      expect((await page.locator("#detector_trend").textContent()).includes("0.012"),
             "legacy detector payload stopped detector trend rendering");
      legacyDetectorPayload = false;

      await page.goto(baseUrl + "/distiller.htm", {waitUntil:"load"});
      await page.waitForFunction(() =>
        document.getElementById("TimeRemaining").textContent !== "--"
      );
      expect((await page.locator("#TimeRemaining").textContent()).trim() === "12",
             "row remaining forecast missing");
      expect((await page.locator("#ProcessTimeRemaining").textContent()).trim() === "32",
             "process remaining forecast missing");

      await page.goto(baseUrl + "/bk.htm", {waitUntil:"load"});
      await page.waitForFunction(() =>
        document.getElementById("boiling_evidence").textContent.includes("царга")
      );
      const boiling = page.locator("#boiling_evidence");
      expect((await boiling.textContent()).includes("царга"),
             "BK boiling evidence missing");
      expect(await boiling.getAttribute("data-precision") === "precise",
             "BK precise evidence is not marked");

      await page.goto(baseUrl + "/beer.htm", {waitUntil:"load"});
      expect((await page.locator("body").textContent()).includes(
               "Вход ждёт подтверждённый запуск Lua-job"),
             "Beer Lua-stage safety explanation missing");
      const beerPostCount = beerProgramPosts.length;
      const beerW = await page.evaluate(async () => {
        const valid = "W;0;0;0^0^0^0;4";
        const invalid = "W;0;0;0^0^0^0;5";
        document.getElementById("WProgram").value = valid;
        await set_program();
        return {
          accepted:check_program(valid),
          rejected:!check_program(invalid),
          saved:document.getElementById("WProgram").value
        };
      });
      expect(beerW.accepted,
             "Beer W row with sensor 4 is rejected by UI validation");
      expect(beerW.rejected,
             "Beer W row with out-of-range sensor 5 is accepted by UI validation");
      expect(beerW.saved === "W;0;0;0^0^0^0;4",
             "Beer W row with sensor 4 changed before save");
      const beerWPost = beerProgramPosts[beerProgramPosts.length - 1] || "";
      expect(beerProgramPosts.length === beerPostCount + 1 && beerWPost.includes("W;0;0;0^0^0^0;4"),
             "Beer W row with sensor 4 was not sent to /program");

      await page.goto(baseUrl + "/setup.htm", {waitUntil:"load"});
      expect(await page.locator("#SuvidTemp").count() === 1 &&
             await page.locator("#SuvidHoldMinutes").count() === 1,
             "Suvid controls missing");
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth
      );
      expect(overflow <= 1, "setup horizontal overflow " + overflow);
    }
  }
  expect(consoleProblems.length === 0, consoleProblems.join("\n"));
  return "__U05_RESULT__" + JSON.stringify({failures,consoleProblems});
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli or Path(cli).resolve() != EXPECTED_CLI.resolve():
        print(f"stable playwright-cli is required at {EXPECTED_CLI}", file=sys.stderr)
        return 1

    error = None
    cleanup_errors = []
    report = {}
    with tempfile.TemporaryDirectory(prefix="samovar-mode-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-mode-logic-ui-{os.getpid()}"
        opened = False
        try:
            config = temp / "playwright.json"
            config.write_text(
                json.dumps({
                    "browser": {
                        "browserName": "chromium",
                        "launchOptions": {"chromiumSandbox": False},
                    }
                }),
                encoding="utf-8",
            )
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            opened = True
            code = BROWSER_TEST.replace(
                "__BASE_URL__",
                json.dumps(f"http://127.0.0.1:{server.server_port}"),
            )
            report = run_cli_report(cli, session, code, temp, 120)
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
            print(f"mode logic UI browser gate failed: {error}", file=sys.stderr)
        for cleanup_error in cleanup_errors:
            print(f"browser cleanup failed: {cleanup_error}", file=sys.stderr)
        return 1
    print("mode logic UI browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
