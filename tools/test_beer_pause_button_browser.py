#!/usr/bin/env python3
"""[Пиво 02.09 C2] Browser contract for the beer.htm "Пауза/Продолжить" button.

До правки веб-точка входа action == "pause" (WebServer.ino) смотрела только на
PauseOn (для пива он всегда false), поэтому кнопка каждый раз слала одну и ту
же команду SAMOVAR_PAUSE и выйти из ручной паузы пива с веба было нельзя.
Этот тест проверяет ЖИВУЮ страницу beer.htm через playwright-cli (образец -
tools/test_mode_logic_ui_browser.py): кнопка "Пауза" при клике шлёт
action=pause, а когда /ajax отдаёт BeerManualPause=1, подпись меняется на
"Продолжить" и фон кнопки меняется, и повторный клик тоже шлёт action=pause
(сервер сам решает, продолжить или поставить на паузу, - см. C1).
"""
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
    QuietHandler,
    render_site,
    run_cli,
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
    DetectorStatus:2,useautospeed:true,
    BoilingEvidence:2,BoilingPrecisionSensorConfigured:1,
    current_power_volt:220,target_power_volt:220,current_power_mode:"WORK",
    current_power_p:2000,WFtotalMl:10,WFflowRate:2,bme_temp:24,heap:200000,
    rssi:-50,fr_bt:300000,UseBBuzzer:false,PauseOn:0,BeerManualPause:0,
    PrgType:"P",Status:"Работа",
    Lstatus:"",TimeRemaining:12,RowTotalTime:22,ProcessTimeRemaining:32,
    TotalTime:42,RowPredictionAvailable:1,ProcessPredictionAvailable:1,
    RowPredictionReason:2,ProcessPredictionReason:2,alc:50,stm_alc:70,ISspd:0,
    wp_spd:0,i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,
    i2c_pump_speed:0,PowerOn:1,StepperStepMl:100,
    heaterAlarmLatched:0,heaterAlarmReason:'',latestMessageSequence:0
  };
  let beerManualPauseFlag = 0;
  const consoleProblems = [];
  const commandPosts = [];
  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error")
      consoleProblems.push(message.type() + ": " + message.text());
  });
  page.on("pageerror", error => consoleProblems.push("pageerror: " + error.message));
  await page.route("**/ajax*", route => {
    const operationMatch = route.request().url().match(/[?&]operationId=([^&]+)/);
    let body;
    if (!operationMatch) {
      body = {...telemetry, BeerManualPause: beerManualPauseFlag};
    } else {
      body = {operationId:Number(decodeURIComponent(operationMatch[1])),state:"succeeded",error:"none"};
    }
    return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
  });
  await page.route("**/command", route => {
    const request = route.request();
    if (request.method() === "POST") commandPosts.push(request.postData() || "");
    return route.fulfill({status:200,contentType:"text/plain",body:"OK"});
  });
  function expect(value, message) { if (!value) throw new Error(message); }

  await page.goto(baseUrl + "/beer.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.getElementById("pause").value === "Пауза");

  const initialColor = await page.evaluate(() =>
    getComputedStyle(document.getElementById("pause")).backgroundColor);

  await page.locator("#pause").click();
  expect(commandPosts.length === 1 && commandPosts[0] === "pause=1",
         "click on 'Пауза' did not send action=pause (got: " + JSON.stringify(commandPosts) + ")");

  // Сервер сообщил, что ручная пауза пива активна - кнопка обязана переключиться
  // на "Продолжить" и сменить фон (по образцу index.htm/PauseOn), опрос телеметрии
  // раз в 2с (startPollLoop, app.js), поэтому ждём с запасом.
  beerManualPauseFlag = 1;
  await page.waitForFunction(
    () => document.getElementById("pause").value === "Продолжить",
    null, {timeout:5000}
  );
  const pausedColor = await page.evaluate(() =>
    getComputedStyle(document.getElementById("pause")).backgroundColor);
  expect(pausedColor !== initialColor,
         "pause button background did not change when BeerManualPause=1");

  // [C1] Второй клик ("Продолжить") обязан слать ту же команду action=pause -
  // сервер сам решает continue/pause по (PauseOn || beerManualPause).
  await page.locator("#pause").click();
  expect(commandPosts.length === 2 && commandPosts[1] === "pause=1",
         "click on 'Продолжить' did not send action=pause (got: " + JSON.stringify(commandPosts) + ")");

  expect(consoleProblems.length === 0,
         "unexpected console warnings/errors: " + consoleProblems.join("; "));
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the beer pause button browser gate", file=sys.stderr)
        return 1

    error = None
    cleanup_errors = []
    with tempfile.TemporaryDirectory(prefix="samovar-beer-pause-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-beer-pause-ui-{os.getpid()}"
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
            run_cli(cli, session, ["run-code", code], temp, 60)
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

    if error or cleanup_errors:
        if error:
            print(f"beer pause button browser gate failed: {error}", file=sys.stderr)
        for cleanup_error in cleanup_errors:
            print(f"browser cleanup failed: {cleanup_error}", file=sys.stderr)
        return 1
    print("beer pause button browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
