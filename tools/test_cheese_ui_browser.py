#!/usr/bin/env python3
"""Browser contract for the cheese editor and two-point pH calibration."""

import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const consoleProblems = [];
  const programPosts = [];
  const savePosts = [];
  let rawPh = 1000;
  let failSave = true;
  page.on("console", message => {
    if (["warning", "error"].includes(message.type())) consoleProblems.push(message.text());
  });
  page.on("pageerror", error => consoleProblems.push(error.message));
  await page.route("**/ajax*", route => {
    const match = route.request().url().match(/[?&]operationId=([0-9]+)/);
    const operationId = match ? match[1] : null;
    const body = operationId ? {operationId:Number(operationId),state:"succeeded",error:"none"} : {
      version:"test", crnt_tm:"12:00:00", stm:"00:01:00", SteamTemp:78.1,
      PipeTemp:77.9, WaterTemp:20.2, TankTemp:32.3, ACPTemp:31.8,
      bme_pressure:760, start_pressure:760, prvl:0, VolumeAll:0,
      ActualVolumePerHour:0, WthdrwlProgress:25, CurrrentSpeed:0,
      CurrrentStepps:0, TargetStepps:0, WthdrwlStatus:0, ProgramNum:0,
      DetectorTrend:0, DetectorStatus:0, useautospeed:false,
      current_power_volt:0, target_power_volt:0, current_power_mode:"0",
      current_power_p:0, WFtotalMl:0, WFflowRate:0, bme_temp:24, heap:200000,
      rssi:-50, fr_bt:300000, UseBBuzzer:false, PauseOn:0,
      PrgType:"n", Status:"Набор кислотности", Lstatus:"",
      TimeRemaining:10, TotalTime:30, alc:0, stm_alc:0, ISspd:0, wp_spd:0,
      i2c_pump_present:0, i2c_pump_running:0, i2c_pump_remaining_ml:0,
      i2c_pump_speed:0, PowerOn:0, heaterAlarmLatched:0, heaterAlarmReason:"",
      latestMessageSequence:0, CheesePhRaw:rawPh, CheesePhRawValid:1,
      CheesePh:99, CheesePhValid:0
    };
    return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
  });
  await page.route("**/program", async route => {
    programPosts.push(await route.request().postDataBuffer());
    return route.fulfill({status:202,contentType:"application/json",body:JSON.stringify({ok:true,err:"",program:"",operationId:41,state:"queued",error:"none"})});
  });
  await page.route("**/save", async route => {
    savePosts.push(await route.request().postDataBuffer());
    if (failSave) return route.fulfill({status:500,contentType:"application/json",body:"{}"});
    return route.fulfill({status:202,contentType:"application/json",body:JSON.stringify({operationId:42,state:"queued",error:"none"})});
  });
  function expect(value, message) { if (!value) throw new Error(message); }

  await page.goto(baseUrl + "/cheese.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.querySelectorAll("#programRows .cheese-row").length === 1);
  const allTypes = await page.locator(".cheese-type option").evaluateAll(nodes => nodes.map(n => n.value));
  expect(allTypes.join("") === "MPCWALZfzds pvrnSR".replace(" ", ""), "not all cheese stages are offered");
  await page.getByRole("button", {name:"Программа"}).click();
  for (const type of allTypes) {
    await page.locator(".cheese-type").selectOption(type);
    const controls = await page.locator(".cheese-row").evaluate(row => ({
      time:!row.querySelector(".cheese-time").disabled,
      device:!row.querySelector(".cheese-device").disabled,
      parameter:!row.querySelector(".cheese-parameter").disabled
    }));
    expect(controls.parameter === (type === "n"), "wrong parameter rule for " + type);
    expect(controls.time === "PZfzds pvrnS".replace(" ", "").includes(type), "wrong time rule for " + type);
    expect(controls.device === "MPCZfzds pvrn".replace(" ", "").includes(type), "wrong device rule for " + type);
  }
  await page.locator(".cheese-type").selectOption("n");
  const nState = await page.locator(".cheese-row").evaluate(row => ({
    parameter:row.querySelector(".cheese-parameter").disabled,
    time:row.querySelector(".cheese-time").disabled,
    parameterLabel:row.querySelector(".cheese-parameter").getAttribute("aria-label")
  }));
  expect(!nState.parameter && !nState.time && nState.parameterLabel.includes("pH"), "n stage controls are wrong");
  await page.locator(".cheese-temperature").fill("30");
  await page.locator(".cheese-parameter").fill("5.2");
  await page.locator(".cheese-time").fill("0");
  await page.locator("#setprogram").click();
  expect(programPosts.length === 0, "invalid n timeout was submitted");
  await page.locator(".cheese-time").fill("90");
  await page.locator("#setprogram").click();
  await page.waitForFunction(() => getComputedStyle(document.getElementById("request_error")).display === "none");
  expect(programPosts.length === 1, "valid cheese program was not submitted once");
  const serialized = await page.locator("#WProgram").inputValue();
  expect(serialized === "n;30;90;0^0^0^0;0;5.2\n", "unexpected cheese serialization: " + serialized);
  await page.evaluate(() => loadFile(new File([JSON.stringify({
    version:1, program:"M;31;0;0^0^0^0;0;0\nn;30;45;0^0^0^0;0;5.1\n", description:"Тестовая программа"
  })], "cheese.json", {type:"application/json"})));
  await page.waitForFunction(() => document.querySelectorAll("#programRows .cheese-row").length === 2);
  expect(await page.locator("#Descr").inputValue() === "Тестовая программа", "JSON description was not restored");
  await page.evaluate(() => loadFile(new File(["M;32;0;0^0^0^0;0;0\n"], "legacy.txt", {type:"text/plain"})));
  await page.waitForFunction(() => document.querySelector(".cheese-temperature").value === "32");
  expect(await page.locator("#Descr").inputValue() === "Тестовая программа", "plain text import replaced description");
  await page.evaluate(() => loadFile(new File(["{broken"], "broken.json", {type:"application/json"})));
  await page.waitForFunction(() => document.getElementById("request_error").textContent.includes("JSON"));
  expect(await page.locator(".cheese-temperature").inputValue() === "32", "malformed JSON fell back to plain text");

  await page.goto(baseUrl + "/calibrate_ph.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.getElementById("phRaw").textContent === "1000");
  await page.locator("#point1Ph").fill("7.00");
  await page.locator("#capturePoint1").click();
  rawPh = 2000;
  await page.waitForFunction(() => document.getElementById("phRaw").textContent === "2000", null, {timeout:5000});
  await page.locator("#point2Ph").fill("4.00");
  await page.locator("#capturePoint2").click();
  await page.locator("#calculatePh").click();
  expect(await page.locator("#CheesePhSlope").inputValue() === "-0.003000", "wrong pH slope");
  expect(await page.locator("#CheesePhOffset").inputValue() === "10.000000", "wrong pH offset");
  await page.locator("#savePh").click();
  await page.waitForFunction(() => document.getElementById("phStatus").textContent.includes("не сохранена"));
  expect(savePosts.length === 1, "failed calibration save was not attempted once");
  expect(consoleProblems.length === 1 && consoleProblems[0].includes("500"), "unexpected browser diagnostics for failed save");
  consoleProblems.length = 0;
  failSave = false;
  await page.locator("#savePh").click();
  await page.waitForFunction(() => document.getElementById("phStatus").textContent.includes("сохранена"));
  expect(savePosts.length === 2, "calibration profile retry was not saved once");

  await page.setViewportSize({width:390,height:844});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(!overflow, "pH calibration has horizontal overflow on mobile");
  expect(consoleProblems.length === 0, "console/page errors: " + consoleProblems.join("; "));
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the cheese UI browser gate")
        return 1
    error = None
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site))
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-cheese-ui-{os.getpid()}"
        opened = False
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser":{"browserName":"chromium","launchOptions":{"chromiumSandbox":False}}}), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            opened = True
            code = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
            run_cli(cli, session, ["run-code", code], temp, 60)
        except (OSError, RuntimeError) as caught:
            error = str(caught)
        finally:
            if opened:
                run_cli(cli, session, ["close"], temp, 30, check=False)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    if error:
        print(f"cheese UI browser gate failed: {error}")
        return 1
    print("cheese UI browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
