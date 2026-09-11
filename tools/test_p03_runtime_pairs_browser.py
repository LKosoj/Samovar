#!/usr/bin/env python3
"""P03: живые @P1-пары появляются на текущем графике только из /ajax RAM."""

import contextlib
import functools
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import http.server
from pathlib import Path

from test_numeric_input_ui_browser import UI_BOOTSTRAP_FIXTURE, QuietHandler, cleanup, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]
CSV = "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\n12:00:00,78,77,20,82,760,1\n"

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const csv = __CSV__;
  const problems = [];
  const expect = (value, text) => { if (!value) throw new Error(text); };
  const p1 = (event, boot, pair, monotonic, utc, outcome = "FF") =>
    "@P1;s=00000065;b=" + boot + ";p=" + pair + ";e=" + event +
    ";m=0;r=01;q=03;o=" + outcome + ";t=" + monotonic +
    (utc ? ";u=" + utc : "") + "|Пауза";
  const telemetry = (event, sessionId = 101) => Object.assign({
    sessionId, crnt_tm:"12:00:00", stm:"00:00:00", SteamTemp:78, PipeTemp:77,
    WaterTemp:20, TankTemp:82, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0,
    WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1,
    bme_pressure:760, start_pressure:760, ISspd:0, prvl:1.2,
    current_power_volt:0, target_power_volt:0, current_power_mode:'0', current_power_p:0,
    CurrrentSpeed:0, CurrrentStepps:0, TargetStepps:0, WthdrwlStatus:0, ProgramNum:0,
    DetectorTrend:0, DetectorStatus:0, useautospeed:false, PauseOn:0,
    TimeRemaining:0, TotalTime:0, alc:0, stm_alc:0, wp_spd:0,
    WFtotalMl:0, WFflowRate:0, Lstatus:'', version:'test', BeerBrewOrder:'allinone',
    i2c_pump_present:0, i2c_pump_running:0, i2c_pump_remaining_ml:0, i2c_pump_speed:0,
    rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0, heaterAlarmLatched:0,
    heaterAlarmReason:"", latestMessageSequence:0
  }, event ? {events:[event]} : {});
  const events = {
    0: { Msg:p1("B", "0000000A", "00000001", "0020000000000000", "6AA3ED40"), msglvl:2, messageSequence:1 },
    1: { Msg:p1("E", "0000000A", "00000001", "0020000000000011", "6AA3ED4A", "00"), msglvl:2, messageSequence:2 },
    2: { Msg:p1("E", "0000000A", "00000001", "0020000000000012", "6AA3ED4A", "00"), msglvl:2, messageSequence:3 },
    3: { Msg:p1("B", "0000000A", "00000002", "0020000000000020", null), msglvl:2, messageSequence:4 },
    4: { Msg:p1("E", "0000000A", "00000002", "0020000000000030", null, "01"), msglvl:2, messageSequence:6 },
    6: { Msg:p1("B", "0000000B", "00000001", "0020000000000040", null), msglvl:2, messageSequence:7 },
    7: { Msg:p1("E", "0000000B", "00000003", "0020000000000050", null, "00"), msglvl:2, messageSequence:8 },
    8: { Msg:p1("B", "0000000B", "00000004", "0020000000000060", null), msglvl:2, messageSequence:9 },
    9: { Msg:p1("E", "0000000B", "00000004", "0020000000000050", null, "00"), msglvl:2, messageSequence:10 }
  };
  const trace = [];
  page.on("pageerror", error => problems.push(error.message));
  await page.route("**/ui-bootstrap", route => route.fulfill({
    status:200, contentType:"application/json", body:JSON.stringify(__BOOTSTRAP__)
  }));
  await page.route("**/data.csv", route => route.fulfill({status:200, contentType:"text/csv", body:csv}));
  await page.route("**/ajax?messageCursor=*", route => {
    const match = /[?&]messageCursor=(\d+)/.exec(route.request().url());
    const cursor = Number(match && match[1]);
    trace.push(cursor);
    if (trace.length === 1) return route.fulfill({status:200, contentType:"application/json", body:JSON.stringify(telemetry(null))});
    return route.fulfill({status:200, contentType:"application/json", body:JSON.stringify(telemetry(events[cursor] || null))});
  });
  await page.goto(baseUrl + "/chart.htm", {waitUntil:"load"});
  await page.waitForFunction(() => chart);
  const loaded = await page.evaluate(async () => {
    try { return {ok:await chart.loadCsv('/data.csv'), rows:chart.rows.length}; }
    catch (error) { return {error:String(error)}; }
  });
  expect(loaded.ok && loaded.rows === 1, 'Existing CSV history did not load: ' + JSON.stringify(loaded));
  for (let index = 0; index < 3; index++) await page.evaluate(() => SamovarApp.pollAjax(renderTelemetry));
  const closed = await page.evaluate(() => {
    const entry = chart.runtimePairs["00000065:0000000A:00000001"];
    return {summary:chart.runtimePairSummary(), duration:entry && entry.durationMs,
      end:entry && entry.end && entry.end.monotonicMs, beginUtc:entry && entry.begin && entry.begin.utc,
      endUtc:entry && entry.end && entry.end.utc};
  });
  expect(closed.summary.complete === 1 && closed.summary.open === 0,
    "BEGIN/END did not make exactly one confirmed interval: " + JSON.stringify(closed));
  expect(closed.duration === "17" && closed.end === "0020000000000011" &&
    closed.beginUtc === "6AA3ED40" && closed.endUtc === "6AA3ED4A",
    "duplicate END or UTC jump changed exact monotonic duration: " + JSON.stringify(closed));
  await page.evaluate(() => SamovarApp.pollAjax(renderTelemetry));
  await page.evaluate(() => SamovarApp.pollAjax(renderTelemetry));
  const afterGap = await page.evaluate(() => chart.runtimePairSummary());
  expect(afterGap.complete === 0 && afterGap.open === 1,
    "gap must discard BEGIN and retain only an explicitly incomplete END: " + JSON.stringify(afterGap));
  await page.evaluate(() => SamovarApp.pollAjax(renderTelemetry));
  const afterBoot = await page.evaluate(() => chart.runtimePairSummary());
  expect(afterBoot.complete === 0 && afterBoot.open === 1,
    "new boot did not start an isolated live pair: " + JSON.stringify(afterBoot));
  await page.evaluate(() => SamovarApp.pollAjax(renderTelemetry));
  await page.evaluate(() => SamovarApp.pollAjax(renderTelemetry));
  await page.evaluate(() => SamovarApp.pollAjax(renderTelemetry));
  const reversed = await page.evaluate(() => chart.runtimePairSummary());
  expect(reversed.complete === 0 && reversed.open === 3,
    "END before BEGIN became a confirmed interval: " + JSON.stringify(reversed));
  await page.evaluate(data => renderTelemetry(data), {
    sessionId:102, crnt_tm:"12:00:01", stm:"00:00:01", SteamTemp:78, PipeTemp:77,
    WaterTemp:20, TankTemp:82, ACPTemp:20, VolumeAll:0, ActualVolumePerHour:0,
    WthdrwlProgress:0, Status:"Готов", PrgType:"", bme_temp:20, heap:1,
    rssi:-50, fr_bt:1, UseBBuzzer:false, PowerOn:0
  });
  const afterSession = await page.evaluate(() => chart.runtimePairSummary());
  expect(afterSession.complete === 0 && afterSession.open === 0,
    "session change kept old RAM pair: " + JSON.stringify(afterSession));
  const canvasChecks = await page.evaluate(() => {
    const area = {left:50, top:10, width:300, height:100};
    const canvas = document.createElement('canvas');
    canvas.width = 400; canvas.height = 140;
    const ctx = canvas.getContext('2d');
    const utc = seconds => seconds.toString(16).toUpperCase().padStart(8, '0');
    const beginSec = Date.parse('2026-09-11T09:00:04Z') / 1000;
    const begin = {utc:utc(beginSec), monotonicMs:'0000000000001000', reason:'03'};
    const end = {utc:utc(beginSec + 8), monotonicMs:'0000000000002F40', reason:'03', outcome:'00'};
    function draw(zone, dates, changes = {}, span = {from:0, to:4}) {
      ctx.clearRect(0, 0, 400, 140);
      chart.options.timeZone = zone;
      chart.rows = dates.map(Date => ({Date}));
      chart.runtimePairs = {test:{begin, end, durationMs:'8000', ...changes}};
      chart.drawRuntimePairs(ctx, area, span);
      const alpha = (x,y=60) => ctx.getImageData(x,y,1,1).data[3];
      const pixels = ctx.getImageData(0,0,400,140).data.reduce((count,value,index) =>
        count + (index % 4 === 3 && value > 0 ? 1 : 0), 0);
      return {begin:alpha(125), fill:alpha(200), outside:alpha(20), alpha:ctx.globalAlpha, pixels};
    }
    const dates = prefix => [0,4,8,12,16].map(second => prefix + String(second).padStart(2,'0'));
    const zone3 = draw(3, dates('09-11 12:00:'));
    const zone5 = draw(5, dates('09-11 14:00:'));
    const zone19 = draw(19, dates('09-12 04:00:'));
    const invalidDate = draw(3, dates('09-10 36:00:'));
    const unknown = draw(undefined, dates('09-11 12:00:'));
    const noUtc = draw(3, dates('09-11 12:00:'), {begin:{...begin,utc:null}});
    const rollback = draw(3, dates('09-11 12:00:'), {end:{...end,utc:utc(beginSec - 4)}});
    const forwardJump = draw(3, dates('09-11 12:00:'), {durationMs:'17'});
    const duplicate = draw(3, ['09-11 12:00:00','09-11 12:00:04','09-11 12:00:08','09-11 12:00:04','09-11 12:00:16']);
    const clipped = draw(3, dates('09-11 12:00:'), {}, {from:2,to:4});
    const labels = [];
    const fillText = ctx.fillText.bind(ctx);
    ctx.fillText = (text, ...args) => { labels.push(text); fillText(text,...args); };
    chart.rows = [1,2,2,3,3].map(ProgNum => ({ProgNum}));
    chart.drawProgramMarkers(ctx, area, {from:1,to:4});
    return {zone3,zone5,zone19,invalidDate,unknown,noUtc,rollback,forwardJump,duplicate,clipped,labels};
  });
  for (const key of ['zone3','zone5','zone19']) expect(canvasChecks[key].begin > 200 &&
    canvasChecks[key].fill > 0 && canvasChecks[key].fill < 100 && canvasChecks[key].alpha === 1,
    'Canvas marker/timezone position or drawing state is incorrect: ' + key + ' ' + JSON.stringify(canvasChecks));
  for (const key of ['unknown','noUtc','duplicate','invalidDate']) expect(canvasChecks[key].pixels === 0,
    'Canvas invented a time position: ' + key + ' ' + JSON.stringify(canvasChecks));
  for (const key of ['rollback','forwardJump']) expect(canvasChecks[key].fill === 0,
    'Canvas filled an interval across a clock jump: ' + key + ' ' + JSON.stringify(canvasChecks));
  expect(canvasChecks.clipped.outside === 0, 'Canvas pause escaped selected plot area: ' + JSON.stringify(canvasChecks));
  expect(JSON.stringify(canvasChecks.labels) === JSON.stringify(['Строка 2','Строка 3']),
    'Canvas lost first visible row transition or double-incremented recorded row: ' + JSON.stringify(canvasChecks));
  const pages = [
    ["index.htm", 0], ["distiller.htm", 1], ["beer.htm", 2], ["bk.htm", 3],
    ["nbk.htm", 4], ["cheese.htm", 7], ["index.htm", 5], ["index.htm", 6]
  ];
  await page.setViewportSize({width:390, height:844});
  for (const [name, mode] of pages) {
    await page.goto(baseUrl + "/" + name, {waitUntil:"load"});
    await page.waitForFunction(() => window.SamovarApp);
    const rendered = await page.evaluate(({mode, telemetry}) => {
      const buttons = document.querySelectorAll('button,input[type="button"]').length;
      const ui = {m:mode,p:mode === 6 ? 12 : 1,e:1,es:1,eo:1,ev:0,eu:1,
        g:[{e:5,es:7,eo:3,ev:30,eu:6}], w:[{q:3,co:1}], n:2,
        c:[{k:1,r:0,a:true,u:8,s:0},{k:2,r:2,a:1,u:3,s:1}]};
      if (mode === 6) ui.ls = 'Lua без толкования';
      renderTelemetry({...telemetry, ui});
      const detail = document.getElementById('ui_details');
      const controls = document.getElementById('ui_control_details');
      return {detail:detail && detail.textContent, controls:controls && controls.textContent,
        buttons, after:document.querySelectorAll('button,input[type="button"]').length,
        narrow:document.documentElement.scrollWidth <= window.innerWidth};
    }, {mode, telemetry:telemetry(null)});
    expect(rendered.detail && rendered.detail.includes('Завершение: порог датчика: не ниже 0 °C по пару') &&
      rendered.detail.includes('Процесс: время: по истечении времени 30 с по таймеру') &&
      rendered.detail.includes('Ожидание: Ожидание температуры пара; автоматически') && rendered.detail.includes('Далее: строка 2'),
      "stage explanation is incomplete for mode " + mode + ": " + JSON.stringify(rendered));
    expect(rendered.controls && rendered.controls.includes('нагрев: задано выкл, применяется вкл (источник неизвестен)') &&
      rendered.controls.includes('отбор: задано 2 л/ч, применяется 1 л/ч (по программе)'),
      "control requested/applied/source is incomplete for mode " + mode + ": " + JSON.stringify(rendered));
    expect(rendered.buttons === rendered.after && rendered.narrow,
      "renderer added controls or broke narrow page for mode " + mode + ": " + JSON.stringify(rendered));
    if (mode === 6) expect(rendered.detail.includes('Lua: Lua без толкования'), "Lua status was interpreted or lost");
  }
  const unavailable = await page.evaluate(() => {
    SamovarApp.renderUiDetails({});
    const old = document.getElementById('ui_details').textContent;
    SamovarApp.renderUiDetails({ui:{m:0}});
    const malformed = document.getElementById('ui_details').textContent;
    const outsideLua = [0, 7].map(mode => {
      SamovarApp.renderUiDetails({ui:{m:mode,p:1,ls:'не Lua'}});
      return document.getElementById('ui_details').textContent;
    });
    SamovarApp.renderUiDetails({ui:{m:6,p:12,ls:'настоящий Lua'}});
    return {old, malformed, outsideLua, lua:document.getElementById('ui_details').textContent};
  });
  expect(unavailable.old.includes('отсутствуют или некорректны') && unavailable.malformed.includes('отсутствуют или некорректны'),
    "old or malformed ui is not explicitly unavailable: " + JSON.stringify(unavailable));
  expect(unavailable.outsideLua.every(text => text.includes('отсутствуют или некорректны')) &&
    unavailable.lua.includes('Lua: настоящий Lua'),
    "Lua status outside Lua was accepted or valid Lua status was lost: " + JSON.stringify(unavailable));
  expect(problems.length === 0, problems.join("\n"));
  return {trace, closed, afterGap, afterBoot, reversed, afterSession};
}'''


def run_browser(site: Path, temp: Path, label: str) -> str:
    cli = shutil.which("playwright-cli")
    if not cli:
        return "playwright-cli is required for P03 browser contract"
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = f"samovar-p03-pairs-{os.getpid()}-{label}"
    try:
        config = temp / f"playwright-{label}.json"
        config.write_text(json.dumps({"browser":{"browserName":"chromium","launchOptions":{"chromiumSandbox":False}}}), encoding="utf-8")
        run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
        code = (BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
                .replace("__CSV__", json.dumps(CSV)).replace("__BOOTSTRAP__", json.dumps(UI_BOOTSTRAP_FIXTURE)))
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                run_cli(cli, session, ["run-code", code], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            return captured.getvalue() or str(error)
        return ""
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        return str(error)
    finally:
        cleanup(cli, session, server, thread)


def expect_mutation(site: Path, temp: Path, path: Path, old: str, new: str, assertion: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    mutated = source.replace(old, new, 1)
    if mutated == source:
        raise RuntimeError(f"P03 {label} mutation anchor not found")
    path.write_text(mutated, encoding="utf-8")
    try:
        error = run_browser(site, temp, label)
    finally:
        path.write_text(source, encoding="utf-8")
    if assertion not in error.split("### Ran Playwright code", 1)[0]:
        raise RuntimeError(f"P03 {label} mutation did not fail expected assertion: {error}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-p03-pairs-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        error = run_browser(site, temp, "original")
        if error:
            print("P03 runtime pair browser contract failed: " + error, file=sys.stderr)
            return 1
        try:
            expect_mutation(site, temp, site / "app.js",
                "notifyRuntimePairListeners(null, deviceRestarted ? 'reboot' : 'gap');", "",
                "gap must discard BEGIN and retain only an explicitly incomplete END", "gap")
            expect_mutation(site, temp, site / "chart.js",
                "if (!entry.begin || entry.end) return false;",
                "if (!entry.begin || false) return false;",
                "duplicate END or UTC jump changed exact monotonic duration", "duplicate-end")
            expect_mutation(site, temp, site / "app.js",
                "lines.push('Завершение: ' + formatUiCondition(ui));", "",
                "stage explanation is incomplete", "stage-condition")
            expect_mutation(site, temp, site / "app.js",
                "ui.m !== 6 || ", "",
                "Lua status outside Lua was accepted", "lua-status-mode")
            expect_mutation(site, temp, site / "chart.js",
                "entry.end = pair;", "entry.end = null;",
                "BEGIN/END did not make exactly one confirmed interval", "ignore-end")
            expect_mutation(site, temp, site / "chart.js",
                "if (this.runtimePairs[key].begin && this.runtimePairs[key].end && this.runtimePairs[key].durationMs !== null) complete += 1;",
                "if (this.runtimePairs[key].begin && this.runtimePairs[key].end) complete += 1;",
                "END before BEGIN became a confirmed interval", "reversed-duration")
            expect_mutation(site, temp, site / "chart.js",
                "if (position !== null) return null;", "",
                "Canvas invented a time position", "ambiguous-time")
            expect_mutation(site, temp, site / "chart.js",
                "if (discrepancy <= -1000n || discrepancy >= 1000n) return;", "",
                "Canvas filled an interval across a clock jump", "clock-jump")
            expect_mutation(site, temp, site / "chart.js",
                "ctx.clip();", "",
                "Canvas pause escaped selected plot area", "plot-clip")
            expect_mutation(site, temp, site / "cheese.htm",
                "SamovarApp.renderUiDetails(data);", "",
                "stage explanation is incomplete for mode 7", "cheese-page")
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1
    print("P03 runtime pair browser contract passed; gap and duplicate-END mutations rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
