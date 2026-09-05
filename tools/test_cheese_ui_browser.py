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
  const commandPosts = [];
  const i2cPumpRequests = [];
  const requestOrder = [];
  const bootstrapRequests = [];
  let rawPh = 1000;
  let failSave = true;
  let bootstrapPlan = {kind:"success", index:0};
  const bootstrapData = [
    {
      mode:7, version:"bootstrap-one", powerUnit:"W",
      program:"M;31;0;0^0^0^0;0;0", description:"Первое описание",
      luaButtonList:"first|Первая Lua",
      steamColor:"#111111", pipeColor:"#222222", waterColor:"#333333", tankColor:"#444444", acpColor:"#555555",
      steamVisible:true, pipeVisible:false, waterVisible:true, tankVisible:false, pressureVisible:true,
      programNumberVisible:true, i2cStepperVisible:false, i2cPumpVisible:false,
      beerBrewOrder:"allinone", pwmLow:0, pwmValue:0, nbkDp:0, columnDiameter:2,
      columnHeight:1.5, packDensity:80, heaterResistance:10, mainsVoltage:220, heaterMaxPower:4840,
      stepperMaxSpeed:1000, stepperStepsPerMl:100, i2cStepperStepsPerMl:100,
      calibrationRunning:false, calibrationPump:"local", cheesePhSlope:1, cheesePhOffset:0,
      cheesePhSmoothPercent:20
    },
    {
      mode:7, version:"bootstrap-two", powerUnit:"W",
      program:"P;32;20;0^0^0^0;0;0", description:"Второе описание",
      luaButtonList:"second|Вторая Lua",
      steamColor:"#AAAAAA", pipeColor:"#BBBBBB", waterColor:"#CCCCCC", tankColor:"#DDDDDD", acpColor:"#EEEEEE",
      steamVisible:false, pipeVisible:true, waterVisible:false, tankVisible:true, pressureVisible:false,
      programNumberVisible:false, i2cStepperVisible:true, i2cPumpVisible:true,
      beerBrewOrder:"rims", pwmLow:20, pwmValue:30, nbkDp:1.25, columnDiameter:1.5,
      columnHeight:2, packDensity:90, heaterResistance:12, mainsVoltage:230, heaterMaxPower:4408,
      stepperMaxSpeed:1200, stepperStepsPerMl:120, i2cStepperStepsPerMl:130,
      calibrationRunning:true, calibrationPump:"i2c", cheesePhSlope:2, cheesePhOffset:-1,
      cheesePhSmoothPercent:40
    }
  ];
  page.on("console", message => {
    if (["warning", "error"].includes(message.type())) consoleProblems.push(message.text());
  });
  page.on("pageerror", error => consoleProblems.push(error.message));
  await page.route("**/ui-bootstrap", route => {
    requestOrder.push("bootstrap");
    bootstrapRequests.push({url:route.request().url(), method:route.request().method()});
    if (bootstrapPlan.kind === "network") return route.abort("failed");
    if (bootstrapPlan.kind === "malformed") {
      return route.fulfill({status:200,contentType:"application/json",body:"{"});
    }
    if (bootstrapPlan.kind === "status") {
      return route.fulfill({status:bootstrapPlan.status,contentType:"text/plain",body:"BUSY"});
    }
    const body = Object.assign({}, bootstrapData[bootstrapPlan.index]);
    if (bootstrapPlan.kind === "missing") delete body.program;
    if (bootstrapPlan.kind === "wrongType") body.calibrationRunning = 1;
    if (bootstrapPlan.kind === "wrongNumber") body.nbkDp = "1.25";
    if (bootstrapPlan.kind === "badEnum") body.beerBrewOrder = "invalid";
    if (bootstrapPlan.kind === "tooLong") body.description = "ы".repeat(126);
    if (bootstrapPlan.kind === "infinite") {
      return route.fulfill({status:200,contentType:"application/json",
        body:JSON.stringify(body).replace('"nbkDp":0', '"nbkDp":1e400')});
    }
    return route.fulfill({status:200,contentType:"application/json",
      body:JSON.stringify(body)});
  });
  await page.route("**/ajax*", route => {
    requestOrder.push("ajax");
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
  await page.route("**/command", async route => {
    commandPosts.push(await route.request().postDataBuffer());
    return route.fulfill({status:200,contentType:"text/plain",body:"OK"});
  });
  await page.route("**/i2cpump*", route => {
    i2cPumpRequests.push(route.request().url());
    return route.fulfill({status:200,contentType:"text/plain",body:"OK"});
  });
  await page.route("**/save", async route => {
    savePosts.push(await route.request().postDataBuffer());
    if (failSave) return route.fulfill({status:500,contentType:"application/json",body:"{}"});
    return route.fulfill({status:202,contentType:"application/json",body:JSON.stringify({operationId:42,state:"queued",error:"none"})});
  });
  function expect(value, message) { if (!value) throw new Error(message); }
  async function waitFor(label, predicate, options) {
    try {
      await page.waitForFunction(predicate, null, options);
    } catch (error) {
      const state = await page.evaluate(() => {
        const requestError = document.getElementById("request_error");
        return {
          error: requestError ? requestError.textContent : "missing",
          errorVisible: requestError ? requestError.style.display : "missing",
          inert: document.body ? document.body.inert : null
        };
      });
      throw new Error(label + " timed out at " + page.url() + ": " + error.message +
        "; state=" + JSON.stringify(state) + "; requests=" + JSON.stringify(requestOrder));
    }
  }

  async function openCheese(plan) {
    const bootstrapBefore = bootstrapRequests.length;
    const ajaxBefore = requestOrder.filter(item => item === "ajax").length;
    const commandBefore = commandPosts.length;
    const programBefore = programPosts.length;
    bootstrapPlan = plan;
    await page.goto(baseUrl + "/cheese.htm", {waitUntil:"load"});
    await waitFor("Cheese error container", () => document.querySelector("#request_error") !== null);
    expect(bootstrapRequests.length === bootstrapBefore + 1,
      "exactly one bootstrap request was not made for cheese page");
    const bootstrapRequest = bootstrapRequests[bootstrapRequests.length - 1];
    expect(bootstrapRequest.method === "GET" && bootstrapRequest.url.endsWith("/ui-bootstrap"),
      "bootstrap request is not a parameterless GET");
    if (plan.kind !== "success") {
      await waitFor("Bootstrap error visibility", () => document.getElementById("request_error").style.display !== "none");
      const bootstrapError = await page.locator("#request_error").textContent();
      expect(requestOrder.filter(item => item === "ajax").length === ajaxBefore,
        "telemetry started after failed bootstrap");
      expect(await page.locator("body").evaluate(body => body.inert === true),
        "failed bootstrap did not lock the page");
      const error = await page.evaluate(async () => {
        const result = {};
        try { SamovarApp.sendCommand("power=1"); result.command = ""; }
        catch (caught) { result.command = String(caught.message || caught); }
        try { SamovarApp.postProgram(document.forms.mainform); result.program = ""; }
        catch (caught) { result.program = String(caught.message || caught); }
        window.confirm = () => true;
        result.clear = await SamovarApp.clearProgram();
        result.i2cPump = await SamovarApp.stopI2cPump();
        return result;
      });
      expect(error.command.includes("Начальные данные"), "command was not rejected before bootstrap success");
      expect(error.program.includes("Начальные данные"), "program save was not rejected before bootstrap success");
      expect(error.clear === false, "program clear was not rejected before bootstrap success");
      expect(error.i2cPump === false, "I2C pump command was not rejected before bootstrap success");
      expect(commandPosts.length === commandBefore, "command reached server before bootstrap success");
      expect(programPosts.length === programBefore, "program save reached server before bootstrap success");
      expect(i2cPumpRequests.length === 0, "I2C pump request reached server before bootstrap success");
      return bootstrapError;
    }
    await waitFor("Bootstrap program row", () => document.querySelectorAll("#programRows .cheese-row").length === 1);
    expect(requestOrder[requestOrder.length - 2] === "bootstrap" && requestOrder[requestOrder.length - 1] === "ajax",
      "telemetry ajax did not follow bootstrap");
    expect(await page.locator("body").evaluate(body => body.inert === false),
      "successful bootstrap left the page locked");
  }

  await openCheese({kind:"success", index:0});
  await waitFor("Initial Cheese program row", () => document.querySelectorAll("#programRows .cheese-row").length === 1);
  expect(await page.locator("#Descr").inputValue() === "Первое описание", "first bootstrap description was not applied");
  expect(await page.locator("#WProgram").inputValue() === bootstrapData[0].program, "first bootstrap program was not applied");
  expect(await page.locator('input[type="button"][value="Первая Lua"]').count() === 1, "first bootstrap Lua button was not applied");
  const repeatedBootstrapRequests = bootstrapRequests.length;
  const repeatedAjaxRequests = requestOrder.filter(item => item === "ajax").length;
  expect(await page.evaluate(() => SamovarApp.loadUiBootstrap(() => {})) === false,
    "second bootstrap call did not fail explicitly");
  expect((await page.locator("#request_error").textContent()).includes("уже загружены"),
    "second bootstrap call did not show an explicit error");
  expect(bootstrapRequests.length === repeatedBootstrapRequests,
    "second bootstrap call issued another request");
  expect(requestOrder.filter(item => item === "ajax").length === repeatedAjaxRequests,
    "second bootstrap call started another telemetry lifecycle");
  expect(await page.getByRole("button", {name:"Настройки"}).count() === 1, "settings button is missing");
  expect(await page.getByRole("button", {name:"История"}).count() === 1, "history button is missing");
  await page.getByRole("button", {name:"Настройки"}).click();
  await page.waitForURL("**/setup.htm");
  await openCheese({kind:"success", index:1});
  expect(await page.locator("#Descr").inputValue() === "Второе описание", "second bootstrap description was not applied");
  expect(await page.locator("#WProgram").inputValue() === bootstrapData[1].program, "second bootstrap program was not applied");
  expect(await page.locator('input[type="button"][value="Вторая Lua"]').count() === 1, "second bootstrap Lua button was not applied");
  const temperatureColors = await page.evaluate(() =>
    ['SteamTemp', 'PipeTemp', 'WaterTemp', 'TankTemp', 'ACPTemp'].map(id => {
      const style = getComputedStyle(document.getElementById(id).parentElement);
      return [style.color, style.textDecorationColor];
    }));
  const expectedTemperatureColors = [
    'rgb(170, 170, 170)', 'rgb(187, 187, 187)', 'rgb(204, 204, 204)',
    'rgb(221, 221, 221)', 'rgb(238, 238, 238)'
  ];
  expect(temperatureColors.every((value, index) =>
    value[0] === expectedTemperatureColors[index] && value[1] === expectedTemperatureColors[index]),
    "cheese temperature text and underline colors were not applied");
  await page.getByRole("button", {name:"История"}).click();
  expect(await page.locator("#historyBox").isVisible(), "history panel did not open");
  await page.evaluate(() => SamovarApp.showHistory());
  const allTypes = await page.locator(".cheese-type option").evaluateAll(nodes => nodes.map(n => n.value));
  expect(allTypes.join("") === "MPCWALZfzds pvrnSR".replace(" ", ""), "not all cheese stages are offered");
  await page.getByRole("button", {name:"Программа"}).click();
  expect(await page.locator("#programRows.prg .prgline.cheese-row").count() === 1,
    "cheese rows do not use the standard program-row layout");
  expect(await page.locator(".cheese-row .program-row-action").count() === 2,
    "cheese row does not have standard plus/minus actions");
  expect(await page.locator('.cheese-add img[src="plus.png"], .cheese-remove img[src="minus.png"]').count() === 2,
    "cheese row does not use the standard plus/minus icons");
  expect(await page.locator(".cheese-row").evaluate(row => row.scrollWidth <= row.parentElement.clientWidth),
    "cheese program row does not fit its standard program container");
  await page.locator(".cheese-row .cheese-add").click();
  expect(await page.locator(".cheese-row").count() === 2, "row plus did not insert a stage");
  expect((await page.locator(".cheese-row-number").allTextContents()).join(",") === "01,02",
    "cheese rows were not numbered after insert");
  await page.locator(".cheese-row").nth(1).locator(".cheese-remove").click();
  expect(await page.locator(".cheese-row").count() === 1, "row minus did not remove a stage");
  await page.locator(".cheese-device").focus();
  await waitFor("Device schedule modal", () => getComputedStyle(document.getElementById("popup")).display === "block");
  await page.locator("#m_type").selectOption("3");
  await page.locator("#m_direction").selectOption("-1");
  await page.locator("#m_time").fill("12");
  await page.locator("#m_pause").fill("4");
  await page.locator("#yes-btn").click();
  expect(await page.locator(".cheese-device").inputValue() === "3^-1^12^4", "device modal did not update the row");
  expect(await page.locator(".cheese-row").evaluate(row => getComputedStyle(row).backgroundColor !== "rgba(0, 0, 0, 0)"), "cheese row has no standard stage color");
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
  await waitFor("Program save success", () => getComputedStyle(document.getElementById("request_error")).display === "none");
  expect(programPosts.length === 1, "valid cheese program was not submitted once");
  const serialized = await page.locator("#WProgram").inputValue();
  expect(serialized === "n;30;90;0^0^0^0;0;5.2\n", "unexpected cheese serialization: " + serialized);
  await page.evaluate(() => loadFile(new File([JSON.stringify({
    version:1, program:"M;31;0;0^0^0^0;0;0\nn;30;45;0^0^0^0;0;5.1\n", description:"Тестовая программа"
  })], "cheese.json", {type:"application/json"})));
  await waitFor("JSON import rows", () => document.querySelectorAll("#programRows .cheese-row").length === 2);
  expect(await page.locator("#Descr").inputValue() === "Тестовая программа", "JSON description was not restored");
  await page.evaluate(() => loadFile(new File(["M;32;0;0^0^0^0;0;0\n"], "legacy.txt", {type:"text/plain"})));
  await waitFor("Plain-text import row", () => document.querySelector(".cheese-temperature").value === "32");
  expect(await page.locator("#Descr").inputValue() === "Тестовая программа", "plain text import replaced description");
  await page.evaluate(() => loadFile(new File(["{broken"], "broken.json", {type:"application/json"})));
  await waitFor("Malformed program import error", () => document.getElementById("request_error").textContent.includes("JSON"));
  expect(await page.locator(".cheese-temperature").inputValue() === "32", "malformed JSON fell back to plain text");
  await page.getByRole("button", {name:"Дополнительно"}).click();
  expect(await page.getByRole("button", {name:"Калибровка pH"}).count() === 1, "pH calibration action is missing");
  expect(await page.locator("#lua_str_i").count() === 1, "standard Lua controls are missing");
  await page.setViewportSize({width:390,height:844});
  expect(!await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), "cheese page has horizontal overflow on mobile");

  for (const plan of [
    {kind:"status", status:400, text:"HTTP 400"},
    {kind:"status", status:503, text:"HTTP 503"},
    {kind:"network", text:"Ошибка сети"},
    {kind:"malformed", text:"Некорректный JSON"},
    {kind:"missing", index:0, text:"Некорректные начальные данные"},
    {kind:"wrongType", index:0, text:"Некорректные начальные данные"},
    {kind:"wrongNumber", index:0, text:"Некорректные начальные данные"},
    {kind:"badEnum", index:0, text:"Некорректные начальные данные"},
    {kind:"tooLong", index:0, text:"Некорректные начальные данные"},
    {kind:"infinite", index:0, text:"Некорректные начальные данные"}
  ]) {
    const bootstrapError = await openCheese(plan);
    expect(bootstrapError.includes(plan.text),
      "bootstrap error is not visible for " + plan.kind + (plan.status || ""));
  }
  consoleProblems.length = 0;

  bootstrapPlan = {kind:"success", index:0};
  await page.goto(baseUrl + "/calibrate_ph.htm", {waitUntil:"load"});
  await waitFor("Initial pH raw value", () => document.getElementById("phRaw").textContent === "1000");
  expect(await page.locator("form#phForm").count() === 1, "pH page is not using the standard form layout");
  expect(await page.getByRole("button", {name:"Настройки"}).count() === 1, "pH settings button is missing");
  await page.locator("#point1Ph").fill("7.00");
  await page.locator("#capturePoint1").click();
  rawPh = 2000;
  await waitFor("Updated pH raw value", () => document.getElementById("phRaw").textContent === "2000", {timeout:5000});
  await page.locator("#point2Ph").fill("4.00");
  await page.locator("#capturePoint2").click();
  await page.locator("#calculatePh").click();
  expect(await page.locator("#CheesePhSlope").inputValue() === "-0.003000", "wrong pH slope");
  expect(await page.locator("#CheesePhOffset").inputValue() === "10.000000", "wrong pH offset");
  await page.locator("#savePh").click();
  await waitFor("Failed pH save status", () => document.getElementById("phStatus").textContent.includes("не сохранена"));
  expect(savePosts.length === 1, "failed calibration save was not attempted once");
  expect(consoleProblems.length === 1 && consoleProblems[0].includes("500"),
    "unexpected browser diagnostics for failed save: " + consoleProblems.join("; "));
  consoleProblems.length = 0;
  failSave = false;
  await page.locator("#savePh").click();
  await waitFor("Successful pH save status", () => document.getElementById("phStatus").textContent.includes("сохранена"));
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
    cheese_source = (ROOT / "data_raw" / "cheese.htm").read_text(encoding="utf-8")
    if any(token in cheese_source for token in ("%WProgram%", "%Descr%", "%btn_list%")):
        print("cheese UI browser gate refuses template placeholders in its fixture source")
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
