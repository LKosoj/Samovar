#!/usr/bin/env python3
"""Playwright contract for Task 4 bootstrap pages and startup ordering."""

import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler
from test_numeric_input_ui_browser import UI_BOOTSTRAP_FIXTURE, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const defaults = __BOOTSTRAP_FIXTURE__;
  const requests = [];
  let plan = {index:0};
  function expect(value, message) { if (!value) throw new Error(message); }
  page.on("request", request => {
    const raw = request.url();
    const scheme = raw.indexOf("://");
    const path = raw.slice(raw.indexOf("/", scheme + 3)).split("?")[0];
    if (["/ui-bootstrap", "/data.csv", "/ajax", "/ajax_col_params", "/program_fruit.txt", "/program_grain.txt", "/program_shugar.txt"].includes(path)) {
      requests.push(path);
    }
  });
  await page.route("**/ui-bootstrap", route => {
    const i = plan.index;
    return route.fulfill({status:200, contentType:"application/json", body:JSON.stringify({
      ...defaults,
      mode:i,
      version:i ? "task4-two" : "task4-one",
      powerUnit:i ? "P" : "V",
      program:i ? "B;500;0.5;2;0;100\n" : "H;100;0.1;1;0;120\n",
      steamColor:i ? "#445566" : "#112233",
      pipeColor:i ? "#778899" : "#223344",
      waterColor:i ? "#AABBCC" : "#334455",
      tankColor:i ? "#DDEEFF" : "#556677",
      acpColor:i ? "#102030" : "#778899",
      steamVisible:!i, pipeVisible:!!i, waterVisible:!i, tankVisible:!!i,
      pressureVisible:!i, programNumberVisible:!!i,
      columnDiameter:plan.diameter === undefined ? (i ? 3 : 2) : plan.diameter, columnHeight:i ? 1.8 : 1.2,
      packDensity:i ? 92 : 71, heaterResistance:i ? 20 : 10,
      mainsVoltage:i ? 220 : 230,
      stepperMaxSpeed:i ? 2400 : 1200,
      stepperStepsPerMl:i ? 65400 : 32100,
      i2cSteppers:Array(10).fill({}),
      calibrationRunning:!!i, processRunning:false, calibrationPump:"local",
      cheesePhSlope:i ? -0.006543 : -0.00321,
      cheesePhOffset:i ? 18.25 : 14.75,
      cheesePhAvailable:!i,
      cheesePhAds1115Address:i ? 72 : 0,
      cheeseCoolingScheme:i ? "two-valves" : "pump"
    })});
  });
  await page.route("**/data.csv", route => route.fulfill({status:200, contentType:"text/csv", body:""}));
  await page.route("**/i2cstepper?address=2", route => route.fulfill({
    status:200, contentType:"application/json", body:JSON.stringify({
      devices:[{address:2,present:true}], selected:{address:2,present:true,
        capabilities:4,config:{stepsPerMl:43200,relayMask:0},
        motion:{speedStepsPerSec:1200,targetSteps:100},
        status:{flags:0,currentSpeedStepsPerSec:0,remainingSteps:0}}
    })
  }));
  await page.route("**/ajax_col_params?*", route => route.fulfill({status:200, contentType:"application/json", body:JSON.stringify({
    floodPowerW:3000,workingPowerW:2500,maxFlowMlH:1000,theoreticalPlates:20,
    headsFlowMlH:100,bodyFlowMinMlH:200,bodyFlowMaxMlH:400,bodyEndFlowMlH:300,
    tailsFlowMlH:150,headsPowerW:1800,bodyEndPowerW:2200,tailsPowerW:2000,
    headsSpeedClamped:false,bodySpeedClamped:false
  })}));
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({status:200, contentType:"application/json", body:JSON.stringify({
    version:"test",crnt_tm:"12:00:00",stm:"00:01:00",SteamTemp:78,PipeTemp:77,
    WaterTemp:20,TankTemp:82,ACPTemp:30,bme_pressure:760,start_pressure:759.5,
    prvl:1.2,VolumeAll:0,ActualVolumePerHour:0,WthdrwlProgress:0,CurrrentSpeed:0,
    CurrrentStepps:0,TargetStepps:0,WthdrwlStatus:0,ProgramNum:0,DetectorTrend:0,
    DetectorStatus:0,useautospeed:false,current_power_volt:0,target_power_volt:0,
    current_power_mode:"0",current_power_p:0,WFtotalMl:0,WFflowRate:0,bme_temp:24,
    heap:100000,rssi:-40,fr_bt:200000,UseBBuzzer:false,PauseOn:0,PrgType:"",
    Status:"Готов",Lstatus:"",TimeRemaining:0,TotalTime:0,alc:0,stm_alc:0,ISspd:0,
    wp_spd:0,i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,
    i2c_pump_speed:0,PowerOn:0,heaterAlarmLatched:0,heaterAlarmReason:"",
    latestMessageSequence:0,CheesePhRaw:1234,CheesePhRawValid:1,CheesePh:6.75,
    CheesePhValid:1
  })}));

  async function openSuccess(pageName, index) {
    plan = {index};
    const before = requests.length;
    await page.goto(baseUrl + "/" + pageName, {waitUntil:"load"});
    try {
      await page.waitForFunction(() => document.body.inert === false);
    } catch (error) {
      throw new Error(pageName + " bootstrap state " + JSON.stringify(await page.evaluate(() => ({
        inert:document.body.inert, error:document.getElementById("request_error")?.textContent || ""
      }))));
    }
    expect(requests[before] === "/ui-bootstrap", pageName + " bootstrap order");
    return before;
  }
  for (const i of [0, 1]) {
    let before = await openSuccess("chart.htm", i);
    await page.waitForFunction(() => window.chart);
    await page.waitForTimeout(50);
    let own = requests.slice(before);
    expect(own.indexOf("/data.csv") > own.indexOf("/ui-bootstrap"), "chart CSV order");
    expect(own.indexOf("/ajax") > own.indexOf("/ui-bootstrap"), "chart ajax order");
    const chartState = await page.evaluate(() => ({hidden:chart.hiddenSeries, colors:["SteamTemp","PipeTemp","WaterTemp","TankTemp","ACPTemp"].map(id => { const style = getComputedStyle(document.getElementById(id).parentElement); return [style.color, style.textDecorationColor]; })}));
    expect(await page.locator('.page-nav a[href="/program.htm"]').isHidden() === !!i,
      "chart calculation link visibility " + i);
    expect(chartState.hidden.Steam === !!i && chartState.hidden.Pipe === !i && chartState.hidden.Water === !!i && chartState.hidden.Tank === !i && chartState.hidden.Pressure === !!i && chartState.hidden.ProgNum === !i, "chart visibility " + i);
    const expectedColors = i ? ["rgb(68, 85, 102)","rgb(119, 136, 153)","rgb(170, 187, 204)","rgb(221, 238, 255)","rgb(16, 32, 48)"] : ["rgb(17, 34, 51)","rgb(34, 51, 68)","rgb(51, 68, 85)","rgb(85, 102, 119)","rgb(119, 136, 153)"];
    expect(chartState.colors.every((value, index) => value[0] === expectedColors[index] && value[1] === expectedColors[index]), "chart colors " + i);

    if (i === 0) {
      before = await openSuccess("program.htm", i);
      await page.waitForFunction(() => document.querySelector("#prg").children.length > 0);
      await page.waitForTimeout(50);
      own = requests.slice(before);
      expect(own.indexOf("/ajax_col_params") > own.indexOf("/ui-bootstrap"), "program request order");
      const program = await page.evaluate(() => ({unit:pwr_unit, resistance:heaterResistance, voltage:mainsVolt, diameter:document.getElementById("coldiam").value, height:document.getElementById("columnHeight").textContent, density:document.getElementById("packDensity").textContent, version:document.getElementById("version").textContent, program:document.getElementById("WProgram").value, heater:document.getElementById("heaterMaxPower").value}));
      expect(program.unit === "V" && program.resistance === 10 && program.voltage === 230, "program power");
      expect(program.diameter === "2.0" && program.height === "1.2" && program.density === "71", "program column");
      expect(program.version === "task4-one" && program.program.length > 0, "program text");
      expect(program.heater === String(Math.round(230*230/10)), "program heater");
    }

    await openSuccess("calibrate.htm", i);
    const calibration = await page.evaluate(() => ({speed:document.getElementById("kstepperspd").value, steps:document.getElementById("stepperstepml").value, local:localStepsPerMl, external:externalAddress, externalSteps:externalStepsPerMl, running:calibrationRunning, save:document.getElementById("save").disabled, speedDisabled:document.getElementById("kstepperspd").disabled}));
    expect(calibration.speed === String(i ? 2400 : 1200) && calibration.local === (i ? 65400 : 32100) && calibration.steps === String((i ? 65400 : 32100) * 100), "calibration numbers " + i);
    expect(calibration.running === !!i && calibration.external === 0 && calibration.externalSteps === 0 && calibration.save === !!i && calibration.speedDisabled === !!i, "local calibration state " + i);

    before = await openSuccess("calibrate_ph.htm", i);
    if (!i) await page.waitForFunction(() => document.getElementById("phCurrent").textContent === "6.75");
    own = requests.slice(before);
    expect(own.indexOf("/ajax") > own.indexOf("/ui-bootstrap"), "pH ajax order");
    const ph = await page.evaluate(() => [
      document.getElementById("CheesePhSlope").value,
      document.getElementById("CheesePhOffset").value,
      document.getElementById("savePh").disabled,
      document.getElementById("phStatus").textContent,
      document.getElementById("phConnection").textContent
    ]);
    expect(ph[0] === (i ? "-0.006543" : "-0.00321") && ph[1] === (i ? "18.25" : "14.75"), "pH values " + i);
    expect(ph[2] === !!i, "pH calibration blocking " + i);
    expect(i ? ph[3].includes("ADS1115 не найден") && ph[4].includes("AIN0") : ph[3] === "" && ph[4].includes("LUA_PIN"), "pH source text " + i);
  }

  for (const mode of [1, 2, 3, 4, 5, 6, 7]) {
    plan = {index:mode};
    const before = requests.length;
    await page.goto(baseUrl + "/program.htm", {waitUntil:"load"});
    await page.waitForFunction(() => document.body.inert === false && !document.getElementById("programUnavailable").hidden);
    const unavailable = await page.evaluate(() => ({
      calculatorHidden: document.getElementById("programCalculator").hidden,
      themeInitialized: document.documentElement.hasAttribute("data-theme"),
      message: document.querySelector("#programUnavailable p").textContent,
      href: document.querySelector("#programUnavailable a").getAttribute("href"),
      linkLabel: document.querySelector("#programUnavailable a").textContent
    }));
    expect(unavailable.calculatorHidden, "program calculator remains visible for mode " + mode);
    expect(unavailable.themeInitialized, "program unavailable did not initialize theme for mode " + mode);
    expect(unavailable.message === "Расчёт программы отбора доступен только в режиме «Ректификация».", "program unavailable text for mode " + mode + ": " + unavailable.message);
    expect(unavailable.href === "/", "program unavailable mode link for mode " + mode);
    expect(unavailable.linkLabel === "Перейти к режиму", "program unavailable link label for mode " + mode);
    const own = requests.slice(before);
    expect(own.filter(path => path === "/ui-bootstrap").length === 1, "program unavailable bootstrap count for mode " + mode + ": " + own);
    expect(!own.some(path => ["/ajax_col_params", "/program_fruit.txt", "/program_grain.txt", "/program_shugar.txt"].includes(path)), "program unavailable started calculator work for mode " + mode + ": " + own);
  }

  plan = {index:0};
  await page.goto(baseUrl + "/setup.htm", {waitUntil:"load"});
  await page.waitForFunction(() => !document.querySelector('[data-mode-navigation-slot]').hidden);
  expect(await page.locator('.page-nav [data-mode-navigation-slot]').isVisible(),
    "setup hides calculation link in rectification mode");
  plan = {index:1};
  await page.goto(baseUrl + "/setup_nonrect.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.querySelector('[data-mode-navigation-slot]').hidden);
  expect(await page.locator('.page-nav [data-mode-navigation-slot]').isHidden(),
    "setup shows calculation link outside rectification mode");

  plan = {index:0, diameter:4};
  await page.goto(baseUrl + "/program.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.querySelector("#prg").children.length > 0);
  const unsupported = await page.evaluate(() => ({
    selected:document.getElementById("coldiam").value,
    current:currentColumnDiameterValue
  }));
  expect(unsupported.selected === "1.5" && unsupported.current === "1.5",
    "unsupported diameter did not use existing 1.5 fallback: " + JSON.stringify(unsupported));

  await page.unrouteAll({behavior:"ignoreErrors"});
  return "ok";
}'''

FAILURE_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const requests = [];
  function expect(value, message) { if (!value) throw new Error(message); }
  page.on("request", request => {
    const raw = request.url();
    const path = raw.slice(raw.indexOf("/", raw.indexOf("://") + 3)).split("?")[0];
    if (["/ui-bootstrap","/data.csv","/ajax","/ajax_col_params","/program_fruit.txt","/program_grain.txt","/program_shugar.txt","/calibrate","/save","/program"].includes(path)) requests.push(path);
  });
  await page.route("**/ui-bootstrap", route => route.fulfill({status:503, contentType:"text/plain", body:"BUSY"}));
  for (const pageName of ["chart.htm","program.htm","calibrate.htm","calibrate_ph.htm"]) {
    const before = requests.length;
    await page.goto(baseUrl + "/" + pageName, {waitUntil:"load"});
    await page.waitForFunction(() => document.getElementById("request_error") && document.getElementById("request_error").style.display !== "none");
    const own = requests.slice(before);
    expect(await page.locator("body").evaluate(node => node.inert), pageName + " failure unlocked");
    if (pageName === "program.htm") {
      expect(await page.locator("#programCalculator").isHidden(), "program failure revealed calculator");
      expect(await page.locator("#programUnavailable").isHidden(), "program failure revealed unavailable message");
    }
    expect(own.filter(path => path === "/ui-bootstrap").length === 1, pageName + " bootstrap count");
    expect(!own.some(path => path !== "/ui-bootstrap"), pageName + " work after failure: " + own);
  }
  return "ok";
}'''


def compact_js(source: str) -> str:
    """Remove transport-only whitespace without changing quoted fixture data."""
    result: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        if quote:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char in "'\"`":
            quote = char
            result.append(char)
            index += 1
            continue
        if char.isspace():
            next_index = index + 1
            while next_index < len(source) and source[next_index].isspace():
                next_index += 1
            previous = result[-1] if result else ""
            following = source[next_index] if next_index < len(source) else ""
            if (previous.isalnum() or previous in "_$") and (following.isalnum() or following in "_$"):
                result.append(" ")
            index = next_index
            continue
        result.append(char)
        index += 1
    return "".join(result)


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the Task 4 browser gate")
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-task4-bootstrap-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        setup = (site / "setup.htm").read_text(encoding="utf-8")
        (site / "setup_nonrect.htm").write_text(
            setup.replace('<option value="2" >', '<option value="2" selected>', 1),
            encoding="utf-8",
        )
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-task4-bootstrap-{os.getpid()}"
        script = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_address[1]}")).replace("__BOOTSTRAP_FIXTURE__", json.dumps(UI_BOOTSTRAP_FIXTURE))
        script = compact_js(script)
        failure_script = compact_js(FAILURE_TEST.replace(
            "__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_address[1]}")
        ))
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser":{"browserName":"chromium","launchOptions":{"chromiumSandbox":False}}}), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, timeout=30)
            run_cli(cli, session, ["run-code", script], ROOT, timeout=60)
            run_cli(cli, session, ["run-code", failure_script], ROOT, timeout=30)
        finally:
            run_cli(cli, session, ["close"], ROOT, timeout=15, check=False)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    print("Task 4 bootstrap browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
