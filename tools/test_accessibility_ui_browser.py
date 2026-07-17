#!/usr/bin/env python3
import argparse
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from test_numeric_input_ui_browser import QuietHandler, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CLI = Path("/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin/playwright-cli")
UPLOAD_CASES = (
    ("beer.htm", "loadFile", "beer.txt"),
    ("program.htm", "loadFile", "program.txt"),
    ("setup.htm", "loadFile", "setup.txt"),
    ("brewxml.htm", "loadBeerXML", "recipe.xml"),
)


BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const focused = __FOCUSED__;
  const runMatrix = __RUN_MATRIX__;
  const runActions = __RUN_ACTIONS__;
  const pages = [
    "index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "program.htm", "setup.htm", "chart.htm", "calibrate.htm",
    "i2cstepper.htm", "brewxml.htm"
  ];
  const modePages = new Set(["index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm"]);
  const viewports = focused ? [{name:"390x844",width:390,height:844}] : [
    {name:"320x800",width:320,height:800}, {name:"390x844",width:390,height:844},
    {name:"768x1024",width:768,height:1024}, {name:"1440x900",width:1440,height:900}
  ];
  const themes = focused ? ["light"] : ["light", "dark"];
  const activationKinds = focused ? ["Enter"] : ["click", "Enter", "Space"];
  const actionFamilies = {
    "index.htm": {history:true,messages:true,rows:"H;0;0;0;0;0",details:["Descr","WProgram"],tabs:3,theme:"shared"},
    "beer.htm": {history:true,messages:true,rows:"W;0;0;;0",details:["WProgram","Descr"],tabs:3,theme:"shared"},
    "distiller.htm": {history:true,messages:true,rows:"T;100;0;0",details:["Descr","WProgram"],tabs:3,theme:"shared"},
    "bk.htm": {history:true,messages:true,tabs:2,theme:"shared"},
    "nbk.htm": {history:true,messages:true,details:["WProgram","Descr"],tabs:3,theme:"shared"},
    "program.htm": {messages:true,rows:"0;1;0;H;0"},
    "setup.htm": {rescan:true,tabs:6,theme:"local"},
    "chart.htm": {messages:true,theme:"shared"},
    "i2cstepper.htm": {theme:"local"},
    "brewxml.htm": {}
  };
  const ajaxFixture = {
    version:"test",crnt_tm:"12:00:00",stm:"00:01:00",SteamTemp:78.1,PipeTemp:77.9,
    WaterTemp:20.2,TankTemp:82.3,ACPTemp:40.1,bme_pressure:760,start_pressure:759.5,
    prvl:1.2,VolumeAll:0,ActualVolumePerHour:0,WthdrwlProgress:0,CurrrentSpeed:0,
    CurrrentStepps:0,TargetStepps:0,WthdrwlStatus:0,ProgramNum:0,DetectorTrend:0,
    DetectorStatus:0,useautospeed:false,current_power_volt:0,target_power_volt:0,
    current_power_mode:"0",current_power_p:0,WFtotalMl:0,WFflowRate:0,bme_temp:24,
    heap:200000,rssi:-50,fr_bt:300000,UseBBuzzer:false,PauseOn:0,PrgType:"",
    Status:"Готов",Lstatus:"",TimeRemaining:0,TotalTime:0,alc:0,stm_alc:0,ISspd:0,
    wp_spd:0,i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,
    i2c_pump_speed:0,PowerOn:0,StepperStepMl:100
  };
  const i2cFixture = {
    present:1,address:16,role:1,mode:1,caps:25,status:0,error:0,relayMask:0,
    sensorFlags:0,optionFlags:0,mixerRpm:100,mixerRunSec:10,mixerPauseSec:5,
    pumpMlHour:100,pumpPauseSec:0,fillingMl:100,fillingMlHour:100,stepsPerMl:100,
    remaining:0,currentSpeed:0
  };
  const report = {expectedCells:runMatrix ? viewports.length*themes.length*pages.length : 0,cells:[],
    expectedActionCases:runActions ? 69*activationKinds.length : 0,actionCases:[],focusPages:[],failures:[],consoleProblems:[]};
  let scenario = "startup";
  const mutationRequests = [];
  function expect(value, message) {
    if (!value) report.failures.push(message);
    return value;
  }

  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error") {
      report.consoleProblems.push(scenario + " console " + message.type() + ": " + message.text());
    }
  });
  page.on("pageerror", error => report.consoleProblems.push(scenario + " pageerror: " + error.message));
  page.on("request", request => {
    const requestUrl = request.url();
    const scheme = requestUrl.indexOf("://");
    const pathStart = scheme < 0 ? 0 : requestUrl.indexOf("/", scheme + 3);
    const relative = pathStart < 0 ? "/" : requestUrl.slice(pathStart);
    const queryStart = relative.indexOf("?");
    const pathname = queryStart < 0 ? relative : relative.slice(0, queryStart);
    if (["/command","/program","/save","/i2cpump","/i2cstepper"].includes(pathname) &&
        !/[?&]device=/.test(relative)) mutationRequests.push({scenario,method:request.method(),url:requestUrl});
  });
  await page.addInitScript(() => {
    window.Audio = function() {
      this.play = () => Promise.resolve(); this.pause = () => {}; this.loop = false;
      this.preload = ""; this.autoplay = false;
    };
    window.confirm = () => false;
  });
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status:200,contentType:"application/json",body:JSON.stringify(ajaxFixture)
  }));
  await page.route("**/ajax_col_params?*", route => route.fulfill({
    status:200,contentType:"application/json",body:JSON.stringify({
      floodPowerW:3000,workingPowerW:2500,maxFlowMlH:1000,theoreticalPlates:20,
      headsFlowMlH:100,bodyFlowMinMlH:200,bodyFlowMaxMlH:400,bodyEndFlowMlH:300,
      tailsFlowMlH:150,headsPowerW:1800,bodyEndPowerW:2200,tailsPowerW:2000
    })
  }));
  await page.route("**/i2cstepper?device=*", route => route.fulfill({
    status:200,contentType:"application/json",body:JSON.stringify(i2cFixture)
  }));
  await page.route("**/data.csv", route => route.fulfill({
    status:200,contentType:"text/csv",body:"Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\n"
  }));

  async function setTheme(theme) {
    await page.goto(baseUrl + "/app.js", {waitUntil:"load"});
    await page.evaluate(value => localStorage.setItem("theme", value), theme);
  }
  async function stopI2c() {
    if (!page.url().endsWith("/i2cstepper.htm")) return;
    await page.waitForTimeout(80);
    await page.evaluate(() => { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; scheduleNextPoll = function() {}; });
  }

  async function checkTabOrder() {
    const count = await page.evaluate(() => {
      const selector = 'a[href],button,input:not([type="hidden"]),select,textarea,summary,[tabindex]';
      window.__u05FocusableNodes = Array.from(document.querySelectorAll(selector)).filter(node => {
        const style = getComputedStyle(node);
        return !node.disabled && node.tabIndex >= 0 && style.display !== "none" &&
          style.visibility !== "hidden" && node.getClientRects().length > 0;
      });
      document.body.tabIndex = -1;
      document.body.focus();
      return window.__u05FocusableNodes.length;
    });
    const seen = new Set();
    for (let index=0; index<count; index++) {
      await page.keyboard.press("Tab");
      const state = await page.evaluate(() => {
        const active = document.activeElement;
        const order = window.__u05FocusableNodes || [];
        const labelledInput = active && active.matches('input[type="file"],input[type="checkbox"]');
        const owner = labelledInput
          ? active.labels && active.labels[0]
          : active;
        if (!active || !owner) return {index:-1,focusVisible:false,hit:false,clipped:false};
        const rect = owner.getBoundingClientRect();
        const x = rect.left + rect.width / 2;
        const y = rect.top + rect.height / 2;
        const hit = document.elementFromPoint(x, y);
        const ownerStyle = getComputedStyle(owner);
        return {
          index:order.indexOf(active),
          identity:active.id || active.name || active.className || active.tagName,
          focusVisible:active.matches(":focus-visible") &&
            ownerStyle.outlineStyle !== "none" && parseFloat(ownerStyle.outlineWidth) > 0,
          hit:hit === owner || owner.contains(hit),
          hitIdentity:hit && (hit.id || hit.className || hit.tagName),
          rect:{left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom},
          clipped:rect.left < -0.5 || rect.right > innerWidth + 0.5 ||
            rect.top < -0.5 || rect.bottom > innerHeight + 0.5
        };
      });
      const details = " at " + index + " " + JSON.stringify(state);
      expect(state.index >= 0, scenario + " Tab left the bounded page order" + details);
      expect(state.focusVisible, scenario + " focused control lacks visible focus" + details);
      expect(state.hit, scenario + " focused control center is obscured" + details);
      expect(!state.clipped, scenario + " focused control is clipped" + details);
      if (state.index >= 0) seen.add(state.index);
    }
    expect(seen.size === count, scenario + " Tab order repeated/trapped " + seen.size + "/" + count);
    await page.evaluate(() => {
      document.body.removeAttribute("tabindex");
      delete window.__u05FocusableNodes;
    });
  }

  const interactiveRoles = new Set(["button","checkbox","combobox","option","slider","textbox"]);
  if (runMatrix) {
    for (const viewport of viewports) {
      await page.setViewportSize({width:viewport.width,height:viewport.height});
      for (const theme of themes) {
        await setTheme(theme);
        for (const file of pages) {
          scenario = viewport.name + "/" + theme + "/" + file;
          try {
            await page.goto(baseUrl + "/" + file, {waitUntil:"load"});
            if (file === "program.htm") {
              await page.waitForFunction(() => programTemplateLoaded && columnParams !== null);
            }
            await stopI2c();
            if (viewport.width <= 390 && modePages.has(file)) {
              const topState = await page.evaluate(() => {
                scrollTo(0, 0);
                const bounds = node => {
                  const rect = node.getBoundingClientRect();
                  return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom};
                };
                const firstTab = Array.from(document.querySelectorAll(".tablinks")).find(node => {
                  const style = getComputedStyle(node);
                  return style.display !== "none" && style.visibility !== "hidden" &&
                    node.getClientRects().length > 0;
                });
                const tab = firstTab && bounds(firstTab);
                const overlaps = node => {
                  if (!node || !tab) return false;
                  const rect = bounds(node);
                  return Math.min(rect.right, tab.right) - Math.max(rect.left, tab.left) > 0.5 &&
                    Math.min(rect.bottom, tab.bottom) - Math.max(rect.top, tab.top) > 0.5;
                };
                return {
                  firstTab:Boolean(firstTab),
                  theme:overlaps(document.querySelector(".theme-toggle")),
                  history:overlaps(document.querySelector(".history-trigger"))
                };
              });
              expect(topState.firstTab && !topState.theme && !topState.history,
                scenario + " top controls overlap first tab " + JSON.stringify(topState));

              await page.evaluate(() => {
                const trigger = Array.from(document.querySelectorAll(".tablinks")).find(node =>
                  String(node.getAttribute("onclick") || "").includes("'Other'")
                );
                if (!trigger) throw new Error("Other tab trigger missing");
                trigger.click();
                document.getElementById("samovar_lua_btn_list").textContent =
                  JSON.stringify("1|Lua fixture");
                SamovarApp.addLuaButtons();
                document.getElementById("lua_str_i").value = "return 1";
              });
              await page.locator("#lua_str_i").focus();
              const inputFocus = await page.evaluate(() => {
                const node = document.activeElement;
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                const outline = parseFloat(style.outlineWidth) +
                  parseFloat(style.outlineOffset);
                return {
                  id:node.id,
                  visible:node.matches(":focus-visible") && style.outlineStyle !== "none" &&
                    parseFloat(style.outlineWidth) > 0,
                  outerClipped:rect.left - outline < -0.5 ||
                    rect.right + outline > innerWidth + 0.5
                };
              });
              await page.keyboard.press("Tab");
              const luaState = await page.evaluate(() => {
                const controls = Array.from(document.querySelectorAll(
                  '#lua_str_d > input:not([type="file"])'
                ));
                const input = controls.find(node => node.id === "lua_str_i");
                const run = controls.find(node => node.name === "lua_str_b");
                const label = document.querySelector('label[for="lua_str_i"]');
                const block = document.getElementById("lua_btn");
                const frame = block && block.querySelector(":scope > .container_row");
                const panel = block && block.closest(".tabcontent");
                const labelStyle = label && getComputedStyle(label);
                const active = document.activeElement;
                const activeStyle = getComputedStyle(active);
                const clipped = node => {
                  const rect = node.getBoundingClientRect();
                  return rect.left < -0.5 || rect.right > innerWidth + 0.5;
                };
                const contained = (node, owner) => {
                  if (!node || !owner) return false;
                  const rect = node.getBoundingClientRect();
                  const bounds = owner.getBoundingClientRect();
                  return rect.left >= bounds.left - 0.5 && rect.right <= bounds.right + 0.5;
                };
                const focusOuterClipped = node => {
                  const rect = node.getBoundingClientRect();
                  const style = getComputedStyle(node);
                  const outline = parseFloat(style.outlineWidth) +
                    parseFloat(style.outlineOffset);
                  return rect.left - outline < -0.5 ||
                    rect.right + outline > innerWidth + 0.5;
                };
                return {
                  label:label && label.textContent.trim(),
                  labelVisible:Boolean(label && labelStyle.display !== "none" &&
                    labelStyle.visibility !== "hidden" && label.getClientRects().length > 0),
                  inputValue:input && input.value,
                  overflow:document.documentElement.scrollWidth - document.documentElement.clientWidth,
                  inputClipped:!input || clipped(input),
                  runClipped:!run || clipped(run),
                  inputInFrame:contained(input, frame),
                  runInFrame:contained(run, frame),
                  inputInPanel:contained(input, panel),
                  runInPanel:contained(run, panel),
                  runFocused:active === run,
                  runFocusVisible:active === run && active.matches(":focus-visible") &&
                    activeStyle.outlineStyle !== "none" && parseFloat(activeStyle.outlineWidth) > 0,
                  runFocusOuterClipped:active !== run || focusOuterClipped(active)
                };
              });
              expect(inputFocus.id === "lua_str_i" && inputFocus.visible &&
                !inputFocus.outerClipped,
                scenario + " Lua input focus mismatch " + JSON.stringify(inputFocus));
              expect(luaState.label === "Lua:" && luaState.labelVisible &&
                luaState.inputValue === "return 1", scenario + " Lua visible fixture mismatch " +
                JSON.stringify(luaState));
              expect(luaState.overflow <= 1 && !luaState.inputClipped && !luaState.runClipped,
                scenario + " Lua horizontal clipping " + JSON.stringify(luaState));
              expect(luaState.inputInFrame && luaState.runInFrame &&
                luaState.inputInPanel && luaState.runInPanel,
                scenario + " Lua owner containment mismatch " + JSON.stringify(luaState));
              expect(luaState.runFocused && luaState.runFocusVisible &&
                !luaState.runFocusOuterClipped,
                scenario + " Lua run focus mismatch " + JSON.stringify(luaState));
            }
            const dom = await page.evaluate(() => {
              const ids = Array.from(document.querySelectorAll("[id]"), node => node.id);
              const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
              const critical = Array.from(document.querySelectorAll(
                ".theme-toggle,.tablinks,.button,.history-trigger,.history-clear,.messages-clear,.message-dismiss,.program-row-action"
              )).filter(node => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && !node.disabled &&
                  !node.matches('input[type="file"]') && node.getClientRects().length > 0 &&
                  rect.width > 0 && rect.height > 0;
              }).map(node => {
                node.scrollIntoView({block:"center",inline:"nearest"});
                const rect = node.getBoundingClientRect();
                const hit = document.elementFromPoint(
                  rect.left + rect.width / 2, rect.top + rect.height / 2
                );
                return {
                  name:node.id || node.className,width:rect.width,height:rect.height,
                  hit:hit === node || node.contains(hit),
                  clipped:rect.left < -0.5 || rect.right > innerWidth + 0.5 ||
                    rect.top < -0.5 || rect.bottom > innerHeight + 0.5
                };
              });
              return {
                lang:document.documentElement.lang,duplicates,
                overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
                critical
              };
            });
            expect(dom.lang === "ru", scenario + " lang=" + dom.lang);
            expect(dom.duplicates.length === 0, scenario + " duplicate IDs " + dom.duplicates.join(","));
            expect(dom.overflow <= 1, scenario + " horizontal overflow " + dom.overflow);
            for (const target of dom.critical) {
              expect(target.width >= 43.5 && target.height >= 43.5,
                scenario + " target below 44x44 " + JSON.stringify(target));
              expect(target.hit, scenario + " target center obscured " + JSON.stringify(target));
              expect(!target.clipped, scenario + " target clipped " + JSON.stringify(target));
            }
            const cdp = await page.context().newCDPSession(page);
            const tree = await cdp.send("Accessibility.getFullAXTree");
            await cdp.detach();
            const unnamed = tree.nodes.filter(node => !node.ignored && node.role &&
              interactiveRoles.has(node.role.value) && (!node.name || !String(node.name.value || "").trim()));
            expect(unnamed.length === 0, scenario + " unnamed AX controls=" + unnamed.length);
            if (viewport.name === "390x844" && theme === "light") {
              await checkTabOrder();
              report.focusPages.push(file);
            }
            report.cells.push(scenario);
          } catch (error) {
            report.failures.push(scenario + " exception: " + String(error));
          }
        }
      }
    }
  }

  async function activate(selector, kind) {
    const target = page.locator(selector).first();
    if (kind === "click") await target.click();
    else { await target.focus(); await page.keyboard.press(kind); }
  }
  async function countCall(owner, symbol, selector, kind) {
    await page.evaluate(({owner,symbol}) => {
      const target = owner === "SamovarApp" ? window.SamovarApp : window;
      const original = target[symbol];
      window.__u05Calls = 0;
      window.__u05Original = original;
      target[symbol] = function() { window.__u05Calls++; return original.apply(this, arguments); };
    }, {owner,symbol});
    let count;
    try {
      await activate(selector, kind);
      count = await page.evaluate(() => window.__u05Calls);
    } finally {
      await page.evaluate(({owner,symbol}) => {
        const target = owner === "SamovarApp" ? window.SamovarApp : window;
        target[symbol] = window.__u05Original;
        delete window.__u05Original;
      }, {owner,symbol});
    }
    expect(count === 1, scenario + " " + selector + " called " + count + " times");
    report.actionCases.push(scenario + "/" + selector);
  }
  async function countRowChange(selector, delta, kind) {
    await page.evaluate(value => {
      const target = document.querySelector(value);
      const panel = target && target.closest(".tabcontent");
      if (!panel || getComputedStyle(panel).display !== "none") return;
      const trigger = Array.from(document.querySelectorAll(".tablinks")).find(node =>
        String(node.getAttribute("onclick") || "").includes("'" + panel.id + "'")
      );
      if (!trigger) throw new Error("row-action tab trigger missing for " + panel.id);
      trigger.click();
    }, selector);
    const before = await page.locator(".prgline").count();
    await activate(selector, kind);
    const after = await page.locator(".prgline").count();
    expect(after - before === delta,
      scenario + " " + selector + " row delta " + (after - before) + ", expected " + delta);
    report.actionCases.push(scenario + "/" + selector);
  }
  async function checkDetails(controlId, kind) {
    const selector = `details:has(#${controlId}) > summary`;
    await page.evaluate(id => {
      const control = document.getElementById(id);
      const details = control && control.closest("details");
      if (!details) throw new Error("details owner missing for " + id);
      const panel = details.closest(".tabcontent");
      if (panel && getComputedStyle(panel).display === "none") {
        const trigger = Array.from(document.querySelectorAll(".tablinks")).find(node =>
          String(node.getAttribute("onclick") || "").includes("'" + panel.id + "'")
        );
        if (!trigger) throw new Error("details tab trigger missing for " + panel.id);
        trigger.click();
      }
      details.open = false;
    }, controlId);
    await activate(selector, kind);
    const state = await page.evaluate(id => {
      const control = document.getElementById(id);
      const details = control && control.closest("details");
      const label = details && details.querySelector(`label[for="${id}"]`);
      const style = label && getComputedStyle(label);
      const rect = label && label.getBoundingClientRect();
      return {
        open:Boolean(details && details.open),
        labelInside:Boolean(label),
        labelVisible:Boolean(label && style.display !== "none" &&
          style.visibility !== "hidden" && rect.width > 0 && rect.height > 0)
      };
    }, controlId);
    expect(state.open && state.labelInside && state.labelVisible,
      scenario + " details " + controlId + " state " + JSON.stringify(state));
    report.actionCases.push(scenario + "/" + selector);
  }
  async function checkTabState(selector) {
    const state = await page.evaluate(value => {
      const target = document.querySelector(value);
      return {
        targetPressed:target && target.getAttribute("aria-pressed") === "true",
        pressed:Array.from(document.querySelectorAll('.tablinks[aria-pressed="true"]')).length,
        visible:Array.from(document.querySelectorAll('.tabcontent[aria-hidden="false"]')).length
      };
    }, selector);
    expect(state.targetPressed && state.pressed === 1 && state.visible === 1,
      scenario + " tab semantic state mismatch " + JSON.stringify(state));
  }
  if (runActions) {
    await page.setViewportSize({width:1440,height:900});
    await setTheme("light");
    for (const kind of activationKinds) {
      for (const [file, families] of Object.entries(actionFamilies)) {
        scenario = "actions/" + kind + "/" + file;
        try {
          await page.goto(baseUrl + "/" + file, {waitUntil:"load"});
          if (file === "program.htm") {
            await page.waitForFunction(() => programTemplateLoaded && columnParams !== null);
          }
          await stopI2c();
          if (families.history) {
            await countCall("SamovarApp", "showHistory", ".history-trigger", kind);
            const historyState = await page.evaluate(() => ({
              expanded:document.querySelector(".history-trigger").getAttribute("aria-expanded"),
              visible:getComputedStyle(document.getElementById("historyBox")).display !== "none"
            }));
            expect(historyState.expanded === "true" && historyState.visible,
              scenario + " history semantic state mismatch " + JSON.stringify(historyState));
            await countCall("SamovarApp", "clearHistory", ".history-clear", kind);
            const closedHistoryState = await page.evaluate(() => {
              SamovarApp.showHistory();
              return {
                expanded:document.querySelector(".history-trigger").getAttribute("aria-expanded"),
                visible:getComputedStyle(document.getElementById("historyBox")).display !== "none"
              };
            });
            expect(closedHistoryState.expanded === "false" && !closedHistoryState.visible,
              scenario + " history cleanup state mismatch " + JSON.stringify(closedHistoryState));
          }
          if (families.messages) {
            await page.evaluate(() => SamovarApp.notify("Проверка", 1));
            await countCall("SamovarApp", "clearMessages", ".messages-clear", kind);
            await page.evaluate(() => SamovarApp.notify("Проверка", 1));
            await countCall("SamovarApp", "removeLastMessage", ".message-dismiss", kind);
          }
          if (families.rows) {
            await page.evaluate(seed => { for (let i=0;i<3;i++) addLine(false, seed); }, families.rows);
            await countRowChange(".program-row-action:nth-of-type(1)", 1, kind);
            await countRowChange(".program-row-action:nth-of-type(2)", -1, kind);
          }
          for (const controlId of (families.details || [])) {
            await checkDetails(controlId, kind);
          }
          if (families.rescan) {
            await page.evaluate(() => {
              const trigger = Array.from(document.querySelectorAll(".tablinks")).find(node =>
                String(node.getAttribute("onclick") || "").includes("'Temp'")
              );
              if (!trigger) throw new Error("sensor rescan tab trigger missing");
              trigger.click();
              window.__u05OriginalSendbutton = window.sendbutton;
              window.__u05RescanCommands = [];
              window.sendbutton = function(command) {
                window.__u05RescanCommands.push(command);
                return Promise.resolve(false);
              };
            });
            try {
              await countCall("window", "rescanSensors", "#scanSensorsButton", kind);
              const commands = await page.evaluate(() => window.__u05RescanCommands.slice());
              expect(JSON.stringify(commands) === JSON.stringify(["rescands"]),
                scenario + " sensor rescan commands " + JSON.stringify(commands));
            } finally {
              await page.evaluate(() => {
                window.sendbutton = window.__u05OriginalSendbutton;
                delete window.__u05OriginalSendbutton;
                delete window.__u05RescanCommands;
              });
            }
          }
          for (let index=0; index<(families.tabs || 0); index++) {
            const selector = `.tablinks[aria-pressed]:nth-of-type(${index+1})`;
            await countCall(file === "setup.htm" ? "window" : "SamovarApp", "openTab",
              selector, kind);
            await checkTabState(selector);
          }
          if (families.theme) {
            const themeBefore = await page.evaluate(() =>
              document.documentElement.getAttribute("data-theme")
            );
            await countCall(families.theme === "shared" ? "SamovarApp" : "window", "toggleTheme", ".theme-toggle", kind);
            const themeState = await page.evaluate(() => {
              const target = document.querySelector(".theme-toggle");
              return {
                theme:document.documentElement.getAttribute("data-theme"),
                pressed:target.getAttribute("aria-pressed"),
                label:target.getAttribute("aria-label")
              };
            });
            const expectedTheme = themeBefore === "dark" ? "light" : "dark";
            const expectedPressed = expectedTheme === "dark" ? "true" : "false";
            const expectedLabel = expectedTheme === "dark"
              ? "Включить светлую тему" : "Включить тёмную тему";
            expect((themeBefore === "light" || themeBefore === "dark") &&
              themeState.theme === expectedTheme && themeState.pressed === expectedPressed &&
              themeState.label === expectedLabel,
              scenario + " theme semantic state mismatch " + JSON.stringify(themeState));
          }
        } catch (error) {
          report.failures.push(scenario + " exception: " + String(error));
        }
      }
    }
  }
  expect(report.cells.length === report.expectedCells,
    "page cells " + report.cells.length + "/" + report.expectedCells);
  if (runMatrix) expect(report.focusPages.length === pages.length,
    "focus pages " + report.focusPages.length + "/" + pages.length);
  expect(report.actionCases.length === report.expectedActionCases,
    "action cases " + report.actionCases.length + "/" + report.expectedActionCases);
  expect(mutationRequests.length === 0, "unexpected mutation requests " + JSON.stringify(mutationRequests));
  expect(report.consoleProblems.length === 0, report.consoleProblems.join("\n"));
  return "__U05_RESULT__" + JSON.stringify(report);
}'''

UPLOAD_TRIGGER = r'''async page => {
  const baseUrl = __BASE_URL__;
  const file = __FILE__;
  const handler = __HANDLER__;
  const kind = __KIND__;
  await page.goto(baseUrl + "/" + file, {waitUntil:"load"});
  await page.evaluate(() => {
    const input = document.getElementById("fileToLoad");
    const panel = input && input.closest(".tabcontent");
    if (!panel || getComputedStyle(panel).display !== "none") return;
    const trigger = Array.from(document.querySelectorAll(".tablinks")).find(node =>
      String(node.getAttribute("onclick") || "").includes("'" + panel.id + "'")
    );
    if (!trigger) throw new Error("upload tab trigger missing for " + panel.id);
    trigger.click();
  });
  await page.evaluate(symbol => {
    const original = window[symbol];
    if (typeof original !== "function") throw new Error("missing upload handler " + symbol);
    window.__u05UploadCalls = 0;
    window.__u05UploadChanges = 0;
    window.__u05UploadMutations = [];
    window.__u05UploadErrors = [];
    window[symbol] = function() {
      window.__u05UploadCalls++;
      return original.apply(this, arguments);
    };
    document.getElementById("fileToLoad").addEventListener(
      "change", () => window.__u05UploadChanges++
    );
    window.addEventListener("error", event => {
      window.__u05UploadErrors.push(event.message || "window error");
    });
    window.addEventListener("unhandledrejection", event => {
      window.__u05UploadErrors.push(String(event.reason || "unhandled rejection"));
    });
    const recordMutation = raw => {
      const value = String(raw || "");
      const markers = ["/command", "/program", "/save", "/i2cpump", "/i2cstepper"];
      if (markers.some(marker => value.includes(marker))) {
        window.__u05UploadMutations.push(value);
      }
    };
    const nativeFetch = window.fetch.bind(window);
    window.fetch = function(input, options) {
      recordMutation(typeof input === "string" ? input : input && input.url);
      return nativeFetch(input, options);
    };
    const nativeOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
      recordMutation(url);
      return nativeOpen.apply(this, arguments);
    };
  }, handler);
  const input = page.locator("#fileToLoad");
  if (kind === "click") await input.evaluate(node => node.click());
  else await input.press(kind);
}'''

UPLOAD_VERIFY = r'''async page => {
  await page.waitForTimeout(300);
  const result = await page.evaluate(() => ({
    calls:window.__u05UploadCalls,
    changes:window.__u05UploadChanges,
    files:document.getElementById("fileToLoad").files.length,
    mutations:window.__u05UploadMutations,
    errors:window.__u05UploadErrors
  }));
  return "__U05_RESULT__" + JSON.stringify(result);
}'''


def run_cli_report(
    cli: str, session: str, code: str, cwd: Path, timeout: int
) -> dict[str, object]:
    result = subprocess.run(
        [cli, f"-s={session}", "run-code", code],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode != 0 or "### Error" in result.stdout:
        raise RuntimeError("playwright-cli run-code failed")
    marker = "### Result\n"
    start = result.stdout.rfind(marker)
    if start < 0:
        raise RuntimeError("playwright-cli result marker missing")
    start += len(marker)
    end = result.stdout.find("\n### Ran Playwright code", start)
    encoded = result.stdout[start : end if end >= 0 else None].strip()
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as caught:
        raise RuntimeError("playwright-cli result is not JSON") from caught
    prefix = "__U05_RESULT__"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise RuntimeError("playwright-cli U-05 result prefix missing")
    try:
        report = json.loads(value[len(prefix) :])
    except json.JSONDecodeError as caught:
        raise RuntimeError("playwright-cli U-05 report is not JSON") from caught
    if not isinstance(report, dict):
        raise RuntimeError("playwright-cli U-05 report must be an object")
    return report


def run_cli_filechooser(
    cli: str, session: str, code: str, cwd: Path, timeout: int
) -> None:
    result = subprocess.run(
        [cli, f"-s={session}", "run-code", code],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    modal = "- [File chooser]: can be handled by upload"
    if (
        result.returncode != 0
        or "### Error" in result.stdout
        or result.stdout.count(modal) != 1
        or "### Result" in result.stdout
    ):
        raise RuntimeError("playwright-cli filechooser trigger contract failed")


def run_upload_cases(
    cli: str,
    session: str,
    cwd: Path,
    base_url: str,
    fixtures: dict[str, Path],
    focused: bool,
) -> dict[str, object]:
    kinds = ("Enter",) if focused else ("click", "Enter", "Space")
    report: dict[str, object] = {
        "stage": "uploads",
        "expectedActionCases": len(UPLOAD_CASES) * len(kinds),
        "actionCases": [],
        "failures": [],
    }
    action_cases = report["actionCases"]
    failures = report["failures"]
    assert isinstance(action_cases, list) and isinstance(failures, list)
    for kind in kinds:
        for file, handler, fixture_name in UPLOAD_CASES:
            scenario = f"actions/{kind}/{file}/upload"
            trigger = (
                UPLOAD_TRIGGER
                .replace("__BASE_URL__", json.dumps(base_url))
                .replace("__FILE__", json.dumps(file))
                .replace("__HANDLER__", json.dumps(handler))
                .replace("__KIND__", json.dumps(kind))
            )
            run_cli_filechooser(cli, session, trigger, cwd, 30)
            run_cli(
                cli,
                session,
                ["upload", str(fixtures[fixture_name])],
                cwd,
                30,
            )
            values = run_cli_report(cli, session, UPLOAD_VERIFY, cwd, 30)
            action_cases.append(scenario)
            if (
                values.get("calls") != 1
                or values.get("changes") != 1
                or values.get("files") != 1
                or values.get("mutations") != []
                or values.get("errors") != []
            ):
                failures.append(f"{scenario} count/side-effect mismatch: {values}")
    if len(action_cases) != report["expectedActionCases"]:
        failures.append(
            f"upload action cases {len(action_cases)}/{report['expectedActionCases']}"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focused", action="store_true")
    args = parser.parse_args()
    cli = shutil.which("playwright-cli")
    if not cli or Path(cli).resolve() != EXPECTED_CLI.resolve():
        print(f"stable playwright-cli is required at {EXPECTED_CLI}", file=sys.stderr)
        return 2

    error: str | None = None
    cleanup_errors: list[str] = []
    stage_reports: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="samovar-u05-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        fixtures = {
            "beer.txt": temp / "beer.txt",
            "program.txt": temp / "program.txt",
            "setup.txt": temp / "setup.txt",
            "recipe.xml": temp / "recipe.xml",
        }
        fixtures["beer.txt"].write_text("W;0;0;;0\n", encoding="utf-8")
        fixtures["program.txt"].write_text("0;1;100;H;0\n", encoding="utf-8")
        fixtures["setup.txt"].write_text("{}\n", encoding="utf-8")
        fixtures["recipe.xml"].write_bytes(
            (ROOT / "Тестовые рецепты пива" / "SMaSH.xml").read_bytes()
        )
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser":{"browserName":"chromium","launchOptions":{"chromiumSandbox":False}}}), encoding="utf-8")
            for stage in ("matrix", "actions"):
                session = f"samovar-u05-ui-{stage}-{os.getpid()}"
                opened = False
                try:
                    run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
                    opened = True
                    code = (BROWSER_TEST
                            .replace("__BASE_URL__", json.dumps(base_url))
                            .replace("__FOCUSED__", "true" if args.focused else "false")
                            .replace("__RUN_MATRIX__", "true" if stage == "matrix" else "false")
                            .replace("__RUN_ACTIONS__", "true" if stage == "actions" else "false"))
                    report = run_cli_report(cli, session, code, temp, 360)
                    report["stage"] = stage
                    stage_reports.append(report)
                    if stage == "actions":
                        stage_reports.append(
                            run_upload_cases(
                                cli, session, temp, base_url, fixtures, args.focused
                            )
                        )
                finally:
                    if opened:
                        try:
                            if run_cli(cli, session, ["close"], temp, 30, check=False) != 0:
                                cleanup_errors.append(f"playwright-cli {stage} close failed")
                        except (OSError, subprocess.TimeoutExpired) as caught:
                            cleanup_errors.append(f"playwright-cli {stage} close failed: {caught}")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as caught:
            error = str(caught)
        finally:
            try:
                server.shutdown()
                server.server_close()
            except OSError as caught:
                cleanup_errors.append(f"HTTP server cleanup failed: {caught}")
            thread.join(timeout=5)
            if thread.is_alive():
                cleanup_errors.append("HTTP server thread did not stop")

    failures = [
        str(failure)
        for report in stage_reports
        for failure in report.get("failures", [])
    ]
    activation_count = 1 if args.focused else 3
    action_count = sum(
        len(report.get("actionCases", []))
        for report in stage_reports
        if report.get("stage") in ("actions", "uploads")
    )
    if action_count != 73 * activation_count:
        failures.append(
            f"combined action cases {action_count}/{73 * activation_count}"
        )
    if error is None and failures:
        error = f"{len(failures)} browser assertions failed; first: {failures[0]}"

    if error or cleanup_errors:
        if error:
            print(f"U-05 accessibility browser gate failed: {error}", file=sys.stderr)
        for cleanup_error in cleanup_errors:
            print(f"U-05 browser cleanup failed: {cleanup_error}", file=sys.stderr)
        return 1
    print("U-05 accessibility browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
