#!/usr/bin/env python3
"""Перевод программ пива из формата 6.x на странице beer.htm (01.10.2026).

В 6.x поле «Устройства» было из 4 чисел (тип^скорость^работа^пауза), в 7.00 - из 5
(тип^обороты I2C-мешалки^мл/ч I2C-насоса^работа^пауза). Старую программу вставляют
в текстовое поле - страница обязана перевести её в новый вид (обороты и насос 0,
работа и пауза на своих местах), сообщить об этом и не трогать строки нового
формата и строку Lua. Проверяются оба пути: правка текстового поля и кнопка
«Установить программу» (в /program уходит уже переведённый текст).
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

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const telemetry = {
    version:"test",crnt_tm:"12:00:00",stm:"00:01:00",
    SteamTemp:20,PipeTemp:20,WaterTemp:20,TankTemp:20,ACPTemp:20,
    bme_pressure:760,start_pressure:759.5,prvl:1.2,VolumeAll:0,
    ActualVolumePerHour:0,WthdrwlProgress:0,CurrrentSpeed:0,CurrrentStepps:0,
    TargetStepps:0,WthdrwlStatus:0,ProgramNum:0,DetectorTrend:0,
    DetectorStatus:0,useautospeed:false,
    BoilingEvidence:0,BoilingPrecisionSensorConfigured:0,
    current_power_volt:0,target_power_volt:0,current_power_mode:"SLEEP",
    current_power_p:0,WFtotalMl:0,WFflowRate:0,bme_temp:24,heap:200000,
    rssi:-50,fr_bt:300000,UseBBuzzer:false,PauseOn:0,BeerManualPause:0,
    PrgType:"M",Status:"Ожидание",
    Lstatus:"",TimeRemaining:0,RowTotalTime:0,ProcessTimeRemaining:0,
    TotalTime:0,RowPredictionAvailable:0,ProcessPredictionAvailable:0,
    RowPredictionReason:0,ProcessPredictionReason:0,alc:0,stm_alc:0,ISspd:0,
    wp_spd:0,i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,
    i2c_pump_speed:0,PowerOn:0,StepperStepMl:100,
    heaterAlarmLatched:0,heaterAlarmReason:'',latestMessageSequence:0
  };
  const consoleProblems = [];
  const programPosts = [];
  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error")
      consoleProblems.push(message.type() + ": " + message.text());
  });
  page.on("pageerror", error => consoleProblems.push("pageerror: " + error.message));
  await page.route("**/ajax*", route => {
    const operationMatch = route.request().url().match(/[?&]operationId=([^&]+)/);
    const body = operationMatch
      ? {operationId:Number(decodeURIComponent(operationMatch[1])),state:"succeeded",error:"none"}
      : telemetry;
    return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
  });
  await page.route("**/program", async route => {
    programPosts.push(route.request().postData() || "");
    return route.fulfill({status:202, contentType:"application/json",
      body:JSON.stringify({ok:true,err:"",program:"",operationId:41,state:"queued",error:"none"})});
  });
  function expect(value, message) { if (!value) throw new Error(message); }
  const messagesText = () => page.evaluate(() => document.getElementById("messages").textContent);

  // Две старые строки с разными типом, скоростью, работой и паузой, строка нового
  // формата и строка Lua (у неё 4 поля через ^, но это имя файла с параметрами).
  const legacy = "M;52.00;0;1^0.00^30^5;0\n" +
                 "P;63.00;30;3^-20.00^45^7;1\n" +
                 "W;0;0;0^0^0^0^0;0\n" +
                 "L;0;5;mash.lua^1^2^3;0\n";
  const converted = "M;52.00;0;1^0^0^30^5;0\n" +
                    "P;63.00;30;3^0^0^45^7;1\n" +
                    "W;0;0;0^0^0^0^0;0\n" +
                    "L;0;5;mash.lua^1^2^3;0\n";

  await page.goto(baseUrl + "/beer.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.getElementById("Status").textContent.includes("Ожидание"));
  await page.locator('input.tablinks[value="Программа"]').click();
  await page.locator("summary", {hasText: /^Описание программы затирки:$/}).click();

  // Путь 1: вставка в текстовое поле и уход из него (событие change).
  await page.locator("#WProgram").fill(legacy);
  await page.locator("#WProgram").dispatchEvent("change");
  const afterChange = await page.locator("#WProgram").inputValue();
  expect(afterChange === converted,
         "legacy program was not converted on change: " + JSON.stringify(afterChange));
  const tableDevices = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[id^="pmixer"]')).map(node => node.value));
  expect(JSON.stringify(tableDevices) === JSON.stringify(["1^0^0^30^5", "3^0^0^45^7", "0^0^0^0^0", "mash.lua^1^2^3"]),
         "program table did not get converted device fields: " + JSON.stringify(tableDevices));
  let text = await messagesText();
  expect(text.includes("Программа переведена из формата 6.x, строк: 2. Проверьте мешалку и насос."),
         "conversion notice with the row count is missing: " + text);
  expect(!text.includes("Ошибка программы"), "converted program was reported as invalid");

  // Путь 2: старая программа сразу на кнопку «Установить программу», без change.
  await page.evaluate(value => { document.getElementById("WProgram").value = value; },
                      "M;45.00;0;2^0.00^10^0;0\n");
  await page.locator("#setprogram").click();
  await page.waitForFunction(() => document.getElementById("messages").textContent.includes("Программа сохранена."));
  expect(programPosts.length === 1, "set_program did not post /program once: " + programPosts.length);
  expect(programPosts[0].includes("M;45.00;0;2^0^0^10^0;0"),
         "set_program posted a non-converted program: " + JSON.stringify(programPosts[0]));
  text = await messagesText();
  expect(text.includes("Программа переведена из формата 6.x, строк: 1. Проверьте мешалку и насос."),
         "conversion notice for set_program is missing: " + text);

  expect(consoleProblems.length === 0,
         "unexpected console warnings/errors: " + consoleProblems.join("; "));
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the beer legacy program browser gate", file=sys.stderr)
        return 1

    error = None
    cleanup_errors = []
    with tempfile.TemporaryDirectory(prefix="samovar-beer-legacy-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-beer-legacy-ui-{os.getpid()}"
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
            print(f"beer legacy program browser gate failed: {error}", file=sys.stderr)
        for cleanup_error in cleanup_errors:
            print(f"browser cleanup failed: {cleanup_error}", file=sys.stderr)
        return 1
    print("beer legacy program browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
