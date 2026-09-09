#!/usr/bin/env python3
"""Browser contract for the universal six-field Cheese editor."""

import functools
import json
import os
import shutil
import tempfile
import threading
import http.server
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]

BOOTSTRAP = {
    "mode": 7, "version": "cheese-test", "powerUnit": "W",
    "program": "D;10;30;2;0^0^0^0;1\n", "description": "ignored",
    "luaButtonList": "", "steamColor": "#111111", "pipeColor": "#222222",
    "waterColor": "#333333", "tankColor": "#444444", "acpColor": "#555555",
    "steamVisible": True, "pipeVisible": True, "waterVisible": True,
    "tankVisible": True, "pressureVisible": True, "programNumberVisible": True,
    "i2cStepperVisible": True, "i2cPumpVisible": False, "beerBrewOrder": "allinone",
    "pwmLow": 0, "pwmValue": 0, "nbkDp": 0, "columnDiameter": 2,
    "columnHeight": 1.5, "packDensity": 80, "heaterResistance": 10,
    "mainsVoltage": 220, "heaterMaxPower": 4840, "stepperMaxSpeed": 1000,
    "stepperStepsPerMl": 100, "i2cStepperStepsPerMl": 100,
    "calibrationRunning": False, "calibrationPump": "local", "cheesePhSlope": 1,
    "cheesePhOffset": 0, "cheeseCoolingScheme": "pump",
}

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const bootstrap = __BOOTSTRAP__;
  const posts = [], commands = [], problems = [];
  let programPlan = "success";
  const expect = (condition, message) => { if (!condition) throw new Error(message); };
  const telemetry = programNum => ({
    version:"cheese-test", crnt_tm:"12:00", stm:"00:01", SteamTemp:40, PipeTemp:35,
    WaterTemp:20, TankTemp:31.25, ACPTemp:30, Status:"Дозирование", PrgType:"D",
    ProgramNum:programNum, WthdrwlProgress:25, CheesePh:5.3, CheesePhValid:true,
    CheeseWorkSeconds:75, CheeseTimeoutRemainingSeconds:1725, PowerOn:1,
    latestMessageSequence:0, heaterAlarmLatched:0, heaterAlarmReason:""
  });
  page.on("console", message => {
    if (["warning", "error"].includes(message.type())) problems.push(message.text());
  });
  page.on("pageerror", error => problems.push(error.message));
  await page.route("**/ui-bootstrap", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(bootstrap)
  }));
  await page.route("**/ajax*", async route => {
    const match = route.request().url().match(/[?&]operationId=(\d+)/);
    if (match) return route.fulfill({status:200, contentType:"application/json",
      body:JSON.stringify({operationId:Number(match[1]),state:"succeeded",error:"none"})});
    return route.fulfill({status:200, contentType:"application/json", body:JSON.stringify(telemetry(1))});
  });
  await page.route("**/program", async route => {
    posts.push(await route.request().postDataBuffer());
    if (programPlan === "failure") return route.fulfill({status:200, contentType:"application/json",
      body:JSON.stringify({ok:false,err:"rejected by test",program:"",operationId:0,state:"failed",error:"rejected by test"})});
    return route.fulfill({status:202, contentType:"application/json",
      body:JSON.stringify({ok:true,err:"",program:"",operationId:41,state:"queued",error:"none"})});
  });
  await page.route("**/command", async route => {
    commands.push(await route.request().postDataBuffer());
    return route.fulfill({status:200, contentType:"text/plain",body:"OK"});
  });

  await page.goto(baseUrl + "/cheese.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.querySelectorAll("#programRows .cheese-row").length === 1);
  await page.waitForFunction(() => document.getElementById("stageNumber").textContent === "1 из 1");
  expect(await page.locator("#Descr").count() === 0, "obsolete description field remains");
  expect(await page.locator("#stageType").textContent() === "Дозирование", "stage name is not localized");
  expect(await page.locator("#cheeseCoolingScheme").textContent() === "насос", "pump cooling is not localized");
  expect(await page.locator("#stageCurrent").textContent() === "—", "non-temperature stage shows a false sensor temperature");
  expect(await page.locator("#stageWorkTime").textContent() === "1 мин 15 с", "work time telemetry is wrong");
  expect(await page.locator("#stageTimeout").textContent() === "28 мин 45 с", "timeout telemetry is wrong");
  expect(await page.locator("#start").inputValue() === "Подтвердить", "manual dose is not a confirmation");
  await page.evaluate(() => { window.confirm = () => true; });
  await page.locator("#start").click();
  expect(commands.length === 1 && String(commands[0]).includes("start=1"), "confirmation did not use existing next command");

  await page.getByRole("button", {name:"Программа"}).click();
  const types = await page.locator(".cheese-type option").evaluateAll(nodes => nodes.map(node => node.value));
  expect(types.join("") === "HPCMDNWSL", "editor offers obsolete Cheese types: " + types);
  for (let index = 0; index < types.length; index++) {
    if (index) await page.locator(".cheese-row").last().locator(".cheese-add").click();
    const row = page.locator(".cheese-row").last();
    await row.locator(".cheese-type").selectOption(types[index]);
    if (types[index] === "L") {
      await row.locator(".cheese-lua-call").evaluate(node => { node.value = "test.lua"; });
    }
    const visible = await row.locator(".cheese-field").evaluateAll(nodes => nodes.filter(node => !node.hidden).map(node => node.querySelector("label").textContent));
    expect(visible.every(text => text && !text.includes("VALUE")), "technical field name is visible for " + types[index]);
  }
  expect(await page.locator(".cheese-row").count() === 9, "all nine types were not created");
  expect((await page.locator(".cheese-row-number").allTextContents()).join(",") === "01,02,03,04,05,06,07,08,09", "rows were not renumbered");

  const heat = page.locator(".cheese-row").filter({has: page.locator(".cheese-type")}).first();
  await heat.locator(".cheese-type").selectOption("H");
  await heat.locator(".cheese-mixer-device").selectOption("2");
  await heat.locator(".cheese-mixer-speed").fill("120");
  await heat.locator(".cheese-mixer-direction").selectOption("-1");
  await heat.locator(".cheese-mixer-on").fill("0");
  await heat.locator(".cheese-mixer-off").fill("0");
  const manualDose = page.locator(".cheese-row").nth(4);
  await manualDose.locator(".cheese-type").selectOption("D");
  await manualDose.locator(".cheese-value4").selectOption("1");
  await manualDose.locator(".cheese-action-code").selectOption("2");
  expect(await manualDose.locator(".cheese-field").nth(2).locator("label").textContent() === "Компонент", "manual dose component label is wrong");
  expect(await manualDose.locator(".cheese-action-code").isVisible(), "manual dose has no component selector");
  const action = page.locator(".cheese-row").nth(6);
  await action.locator(".cheese-type").selectOption("W");
  expect(await action.locator(".cheese-action-code").isVisible(), "manual action has no action selector");
  await action.locator(".cheese-action-code").selectOption("7");

  await page.locator("#setprogram").click();
  await page.waitForFunction(() => document.getElementById("request_error").style.display === "none");
  expect(posts.length === 1, "valid program was not posted once");
  const serialized = await page.locator("#WProgram").inputValue();
  const lines = serialized.trim().split("\n");
  expect(lines.length === 9 && lines.every(line => line.split(";").length === 6), "program is not six-field: " + serialized);
  expect(lines[0].split(";")[4] === "2^-120^0^0", "I2C mixer was not serialized");
  expect(lines[4] === "D;10;30;2;0^0^0^0;1", "manual dosing serialization is wrong: " + lines[4]);
  expect(lines[6] === "W;0;30;7;0^0^0^0;0", "manual action serialization is wrong: " + lines[6]);

  await page.getByRole("button", {name:"Процесс"}).click();
  await page.evaluate(data => renderTelemetry(data), telemetry(7));
  expect(await page.locator("#start").inputValue() === "Подтвердить", "W is not a confirmation");
  await page.locator("#start").click();
  await page.evaluate(data => renderTelemetry(data), telemetry(8));
  expect(await page.locator("#start").inputValue() === "Подтвердить", "S is not a confirmation");
  await page.locator("#start").click();
  expect(commands.length === 3, "W and S confirmations did not use the existing next command");

  const exported = await page.evaluate(() => {
    var oldClick = HTMLAnchorElement.prototype.click, href = '';
    HTMLAnchorElement.prototype.click = function() { href = this.href; };
    try { SaveProgramToFile(); } finally { HTMLAnchorElement.prototype.click = oldClick; }
    return decodeURIComponent(href.split(',')[1]);
  });
  const exportedRows = exported.trim().split("\n").map(line => line.split(";"));
  const markerProgram = "N;31;91;5.1;0^0^0^0;0\n";
  await page.evaluate(marker => {
    document.getElementById("WProgram").value = marker;
    renderProgram(marker);
  }, markerProgram);
  await page.waitForFunction(marker => document.getElementById("WProgram").value === marker, markerProgram);
  await page.evaluate(text => loadFile(new File([text], "round-trip.txt", {type:"text/plain"})), exported);
  await page.waitForFunction(text => document.getElementById("WProgram").value === text, exported);
  const importedRows = await page.evaluate(() => serializeCheeseRows().trim().split("\n").map(line => line.split(";")));
  expect(importedRows.length === exportedRows.length && importedRows.every(row => row.length === 6), "import did not restore all six fields");
  expect(JSON.stringify(importedRows) === JSON.stringify(exportedRows), "export/import changed one of the six fields");

  await page.getByRole("button", {name:"Программа"}).click();
  await page.locator(".cheese-row").last().locator(".cheese-remove").click();
  await page.waitForFunction(() => document.querySelectorAll("#programRows .cheese-row").length === 8);
  const remainingTypes = await page.locator(".cheese-type").evaluateAll(nodes => nodes.map(node => node.value));
  expect(!remainingTypes.includes("L"), "remove did not delete the selected row");

  const beforeInvalid = posts.length;
  await heat.locator(".cheese-mixer-device").selectOption("1");
  await heat.locator(".cheese-mixer-speed").fill("10");
  await page.locator("#setprogram").click();
  expect(posts.length === beforeInvalid, "invalid relay RPM reached server");
  expect((await page.locator("#request_error").textContent()).includes("этапа 1"), "invalid field error is not shown");
  await heat.locator(".cheese-mixer-speed").fill("0");

  const hold = page.locator(".cheese-row").nth(1);
  await hold.locator(".cheese-value2").fill("60");
  await hold.locator(".cheese-value3").fill("30");
  await page.locator("#setprogram").click();
  expect(posts.length === beforeInvalid, "P with total timeout shorter than hold reached server");
  await hold.locator(".cheese-value3").fill("60");

  const beforeBadMixerImport = await page.evaluate(() => serializeCheeseRows());
  const beforeBadMixerDraft = await page.locator("#WProgram").inputValue();
  await page.evaluate(() => loadFile(new File(["H;30;60;1;^^^;0\n"], "bad-mixer.txt", {type:"text/plain"})));
  await page.waitForFunction(() => document.getElementById("request_error").style.display !== "none");
  const afterBadMixerImport = await page.evaluate(() => serializeCheeseRows());
  expect(afterBadMixerImport === beforeBadMixerImport, "empty mixer import replaced input");
  expect(await page.locator("#WProgram").inputValue() === beforeBadMixerDraft,
    "empty mixer import replaced hidden draft");

  await page.evaluate(() => loadFile(new File(["N;30;90;5.2;0^0^0^0;0\n"], "cheese.txt", {type:"text/plain"})));
  await page.waitForFunction(() => document.querySelector(".cheese-type").value === "N");
  expect(await page.locator(".cheese-row").count() === 1, "new-format import did not replace rows");
  await page.evaluate(() => loadFile(new File(["A;30;0;0^0^0^0;0;0\n"], "old.txt", {type:"text/plain"})));
  await page.waitForFunction(() => document.getElementById("request_error").style.display !== "none");
  expect(await page.locator(".cheese-type").inputValue() === "N", "rejected old program replaced input");

  await page.locator(".cheese-value2").fill("91");
  const failedDraft = await page.evaluate(() => serializeCheeseRows());
  programPlan = "failure";
  await page.locator("#setprogram").click();
  await page.waitForFunction(() => document.getElementById("request_error").style.display !== "none");
  expect(await page.evaluate(() => serializeCheeseRows()) === failedDraft, "failed /program request discarded entered values");
  await page.evaluate(data => renderTelemetry(data), telemetry(7));
  expect(await page.locator("#stageType").textContent() === "Ручное действие", "active stage used unsaved draft instead of accepted program");

  for (const [scheme, expected] of [["two-valves", "два клапана"], ["unavailable", "недоступно"]]) {
    bootstrap.cheeseCoolingScheme = scheme;
    await page.goto(baseUrl + "/cheese.htm", {waitUntil:"load"});
    await page.waitForFunction(() => document.querySelectorAll("#programRows .cheese-row").length === 1);
    expect(await page.locator("#cheeseCoolingScheme").textContent() === expected,
      "cooling scheme " + scheme + " is not localized");
  }

  await page.setViewportSize({width:390,height:844});
  expect(!await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), "mobile editor has horizontal overflow");
  expect(problems.length === 0, "console/page errors: " + problems.join("; "));
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the cheese UI browser gate")
        return 1
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
        error = None
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            opened = True
            code = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}")).replace("__BOOTSTRAP__", json.dumps(BOOTSTRAP))
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
