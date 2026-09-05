#!/usr/bin/env python3
"""Browser contract for Task 3A bootstrap on rectification and beer pages."""

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
  const defaults = __BOOTSTRAP_FIXTURE__;
  const requests = [];
  const problems = [];
  let plan = {kind:"success", index:0};
  page.on("console", message => {
    if (["warning", "error"].includes(message.type())) problems.push(message.text());
  });
  page.on("pageerror", error => problems.push(error.message));
  await page.route("**/ui-bootstrap", route => {
    requests.push("bootstrap");
    if (plan.kind === "error") return route.fulfill({status:503, contentType:"text/plain", body:"BUSY"});
    const index = plan.index;
    const common = {
      ...defaults,
      version:index ? "bootstrap-two" : "bootstrap-one",
      powerUnit:index ? "P" : "V",
      description:index ? "Второе описание" : "Первое описание",
      luaButtonList:index ? "second|Вторая Lua" : "first|Первая Lua",
      i2cStepperVisible:!!index,
      i2cPumpVisible:!index,
      beerBrewOrder:index ? "rims" : "herms",
      pwmLow:index ? 100 : 20,
      pwmValue:index ? 700 : 300,
      steamColor:index ? "#445566" : "#112233",
      pipeColor:index ? "#778899" : "#223344",
      waterColor:index ? "#AABBCC" : "#334455",
      tankColor:index ? "#DDEEFF" : "#556677",
      acpColor:index ? "#102030" : "#778899"
    };
    const program = plan.page === "beer.htm"
      ? (index ? "P;66;2;0^0^0^0;0\n" : "M;45;0;0^0^0^0;0\n")
      : (index ? "B;500;0.5;2;0;100\n" : "H;100;0.1;1;0;120\n");
    return route.fulfill({status:200, contentType:"application/json",
      body:JSON.stringify({...common, program})});
  });
  await page.route("**/ajax*", route => {
    requests.push("ajax");
    return route.fulfill({status:200, contentType:"application/json", body:JSON.stringify({
      version:"telemetry",crnt_tm:"12:00:00",stm:"00:01:00",SteamTemp:78.1,PipeTemp:77.9,
      WaterTemp:20.2,TankTemp:82.3,ACPTemp:40.1,bme_pressure:760,start_pressure:759.5,
      prvl:1.2,VolumeAll:0,ActualVolumePerHour:0,WthdrwlProgress:0,CurrrentSpeed:0,
      CurrrentStepps:0,TargetStepps:0,WthdrwlStatus:0,ProgramNum:0,DetectorTrend:0,
      DetectorStatus:0,useautospeed:false,current_power_volt:0,target_power_volt:0,
      current_power_mode:"0",current_power_p:0,WFtotalMl:0,WFflowRate:0,bme_temp:24,
      heap:200000,rssi:-50,fr_bt:300000,UseBBuzzer:false,PauseOn:0,PrgType:"",Status:"Готов",
      Lstatus:"",TimeRemaining:0,TotalTime:0,alc:0,stm_alc:0,ISspd:0,wp_spd:0,
      i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,i2c_pump_speed:0,
      PowerOn:0,heaterAlarmLatched:0,heaterAlarmReason:"",latestMessageSequence:0,
      BeerBrewOrder:"allinone"
    })});
  });
  function expect(value, message) { if (!value) throw new Error(message); }
  async function open(pageName, nextPlan) {
    const ajaxBefore = requests.filter(item => item === "ajax").length;
    plan = {...nextPlan, page:pageName};
    await page.goto(baseUrl + "/" + pageName, {waitUntil:"load"});
    if (plan.kind === "error") {
      await page.waitForFunction(() => document.getElementById("request_error").style.display !== "none");
      expect(await page.locator("body").evaluate(node => node.inert),
        pageName + " did not lock after bootstrap error");
      expect(requests.filter(item => item === "ajax").length === ajaxBefore,
        pageName + " started telemetry after bootstrap error");
      return;
    }
    await page.waitForFunction(() => document.querySelector("#prg").children.length > 0);
    expect(requests.at(-2) === "bootstrap" && requests.at(-1) === "ajax",
      pageName + " telemetry did not start after bootstrap");
    const expectedProgram = pageName === "beer.htm"
      ? (plan.index ? "P;66;2;0^0^0^0;0\n" : "M;45;0;0^0^0^0;0\n")
      : (plan.index ? "B;500;0.5;2;0;100\n" : "H;100;0.1;1;0;120\n");
    expect(await page.locator("#WProgram").inputValue() === expectedProgram,
      pageName + " bootstrap program was not applied");
    expect(await page.locator("#Descr").inputValue() === (plan.index ? "Второе описание" : "Первое описание"),
      pageName + " bootstrap description was not applied");
    expect(await page.locator('input[type="button"][value="' + (plan.index ? "Вторая Lua" : "Первая Lua") + '"]').count() === 1,
      pageName + " bootstrap Lua button was not applied");
    expect(await page.locator("#i2cStepperTab").evaluate(node => getComputedStyle(node).display !== "none") === !!plan.index,
      pageName + " I2C stepper visibility was not applied");
    expect(await page.locator("#i2cPumpTab").evaluate(node => getComputedStyle(node).display !== "none") === !plan.index,
      pageName + " I2C pump visibility was not applied");
    const expectedColors = plan.index
      ? {
          SteamTemp:"rgb(68, 85, 102)", PipeTemp:"rgb(119, 136, 153)",
          WaterTemp:"rgb(170, 187, 204)", TankTemp:"rgb(221, 238, 255)",
          ACPTemp:"rgb(16, 32, 48)"
        }
      : {
          SteamTemp:"rgb(17, 34, 51)", PipeTemp:"rgb(34, 51, 68)",
          WaterTemp:"rgb(51, 68, 85)", TankTemp:"rgb(85, 102, 119)",
          ACPTemp:"rgb(119, 136, 153)"
        };
    for (const [id, expected] of Object.entries(expectedColors)) {
      expect(await page.locator("#" + id).evaluate((node, color) => {
        const style = getComputedStyle(node.parentElement);
        return style.color === color && style.textDecorationColor === color;
      }, expected),
        pageName + " bootstrap color mapping is wrong for " + id);
    }
    expect((await page.locator("#set_power_label").textContent()).includes(plan.index ? "Мощность" : "Напряжение"),
      pageName + " bootstrap power unit was not applied");
    if (pageName === "beer.htm") {
      expect(await page.locator("body").getAttribute("data-beer-brew-order") === (plan.index ? "rims" : "herms"),
        "beer brew order was not applied");
      expect(await page.locator("#PWM").getAttribute("min") === String(plan.index ? 100 : 20),
        "beer PWM minimum was not applied");
      expect(await page.locator("#PWM").inputValue() === String(plan.index ? 700 : 300),
        "beer PWM value was not applied");
    }
  }
  for (const pageName of ["index.htm", "beer.htm"]) {
    await open(pageName, {kind:"success", index:0});
    await open(pageName, {kind:"success", index:1});
    await open(pageName, {kind:"error", index:0});
  }
  problems.length = 0;
  await page.setViewportSize({width:390,height:844});
  await open("beer.htm", {kind:"success", index:0});
  expect(!await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth),
    "beer bootstrap page has horizontal overflow on mobile");
  if (problems.length) throw new Error("console/page errors: " + problems.join("; "));
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the mode bootstrap browser gate")
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-mode-bootstrap-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-mode-bootstrap-{os.getpid()}"
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        script = BROWSER_TEST.replace("__BASE_URL__", json.dumps(base_url)).replace(
            "__BOOTSTRAP_FIXTURE__", json.dumps(UI_BOOTSTRAP_FIXTURE)
        )
        try:
            config = temp / "playwright.json"
            config.write_text(
                json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}),
                encoding="utf-8",
            )
            run_cli(cli, session, ["open", f"--config={config}"], temp, timeout=30)
            run_cli(cli, session, ["run-code", script], ROOT, timeout=45)
        finally:
            run_cli(cli, session, ["close"], ROOT, timeout=15, check=False)
            server.shutdown()
            thread.join(timeout=5)
    print("mode bootstrap browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
