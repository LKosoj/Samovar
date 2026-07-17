#!/usr/bin/env python3
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

from test_numeric_input_ui_browser import QuietHandler, cleanup, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CLI = Path("/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin/playwright-cli")


BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const viewports = [
    { name: "320x800", width: 320, height: 800 },
    { name: "390x844", width: 390, height: 844 },
    { name: "768x1024", width: 768, height: 1024 },
    { name: "1440x900", width: 1440, height: 900 }
  ];
  const themes = ["light", "dark"];
  const setupTabs = ["Main", "Temp", "Pump", "Beer", "NBK", "Other"];
  const setupStates = [
    "main-longest-mode", "other-long-values", "other-empty-values",
    "validation-error", "request-error", "visible-tooltip"
  ];
  const chartStates = [
    "messages-hidden", "messages-short", "messages-long", "messages-multiline",
    "chart-empty", "chart-data", "chart-error", "legend", "refresh"
  ];
  const expectedColors = {
    light: {
      "--accent": "#166b9d", "--bg-page": "#3498db", "--bg-form": "#fafafa",
      "--bg-input": "#fafafa", "--text-main": "#6b6b6b", "--text-strong": "#000",
      "--text-on-accent": "#fff", "--border-input": "#737373",
      "--border-soft": "#737373", "--state-danger-bg": "#b00020"
    },
    dark: {
      "--accent": "#166b9d", "--bg-page": "#1a2733", "--bg-form": "#21303d",
      "--bg-input": "#1a2733", "--text-main": "#cfd8e3", "--text-strong": "#f3f6f9",
      "--text-on-accent": "#fff", "--border-input": "#8da1b5",
      "--border-soft": "#8da1b5", "--state-danger-bg": "#b00020"
    }
  };
  const DESKTOP_GEOMETRY_TOLERANCE = 0.5;
  const DESKTOP_GEOMETRY_BASELINE = {
    "setup/Main": { form: {x:290,y:25,width:860,height:1308.13}, panel: {x:320,y:165,width:800,height:1084.13}, actions: {x:386,y:1249.13,width:668,height:54}, save: {x:396,y:1259.13,width:200,height:44}, return: {x:620,y:1259.13,width:200,height:44}, edit: {x:844,y:1259.13,width:200,height:44} },
    "setup/Temp": { form: {x:290,y:25,width:860,height:1600.55}, panel: {x:320,y:165,width:800,height:1376.55}, actions: {x:386,y:1541.55,width:668,height:54}, save: {x:396,y:1551.55,width:200,height:44}, return: {x:620,y:1551.55,width:200,height:44}, edit: {x:844,y:1551.55,width:200,height:44} },
    "setup/Pump": { form: {x:290,y:25,width:860,height:440.69}, panel: {x:320,y:165,width:800,height:216.69}, actions: {x:386,y:381.69,width:668,height:54}, save: {x:396,y:391.69,width:200,height:44}, return: {x:620,y:391.69,width:200,height:44}, edit: {x:844,y:391.69,width:200,height:44} },
    "setup/Beer": { form: {x:290,y:25,width:860,height:624.38}, panel: {x:320,y:165,width:800,height:400.38}, actions: {x:386,y:565.38,width:668,height:54}, save: {x:396,y:575.38,width:200,height:44}, return: {x:620,y:575.38,width:200,height:44}, edit: {x:844,y:575.38,width:200,height:44} },
    "setup/NBK": { form: {x:290,y:25,width:860,height:640.38}, panel: {x:320,y:165,width:800,height:416.38}, actions: {x:386,y:581.38,width:668,height:54}, save: {x:396,y:591.38,width:200,height:44}, return: {x:620,y:591.38,width:200,height:44}, edit: {x:844,y:591.38,width:200,height:44} },
    "setup/Other": { form: {x:290,y:25,width:860,height:1380.33}, panel: {x:320,y:165,width:800,height:1156.33}, actions: {x:386,y:1321.33,width:668,height:54}, save: {x:396,y:1331.33,width:200,height:44}, return: {x:620,y:1331.33,width:200,height:44}, edit: {x:844,y:1331.33,width:200,height:44} },
    "setup/main-longest-mode": { form: {x:290,y:25,width:860,height:1308.13}, panel: {x:320,y:165,width:800,height:1084.13}, actions: {x:386,y:1249.13,width:668,height:54}, save: {x:396,y:1259.13,width:200,height:44}, return: {x:620,y:1259.13,width:200,height:44}, edit: {x:844,y:1259.13,width:200,height:44} },
    "setup/other-long-values": { form: {x:290,y:25,width:860,height:1380.33}, panel: {x:320,y:165,width:800,height:1156.33}, actions: {x:386,y:1321.33,width:668,height:54}, save: {x:396,y:1331.33,width:200,height:44}, return: {x:620,y:1331.33,width:200,height:44}, edit: {x:844,y:1331.33,width:200,height:44} },
    "setup/other-empty-values": { form: {x:290,y:25,width:860,height:1380.33}, panel: {x:320,y:165,width:800,height:1156.33}, actions: {x:386,y:1321.33,width:668,height:54}, save: {x:396,y:1331.33,width:200,height:44}, return: {x:620,y:1331.33,width:200,height:44}, edit: {x:844,y:1331.33,width:200,height:44} },
    "setup/validation-error": { form: {x:290,y:25,width:860,height:1391.88}, panel: {x:320,y:248.75,width:800,height:1084.13}, actions: {x:386,y:1332.88,width:668,height:54}, save: {x:396,y:1342.88,width:200,height:44}, return: {x:620,y:1342.88,width:200,height:44}, edit: {x:844,y:1342.88,width:200,height:44} },
    "setup/request-error": { form: {x:290,y:25,width:860,height:1391.88}, panel: {x:320,y:248.75,width:800,height:1084.13}, actions: {x:386,y:1332.88,width:668,height:54}, save: {x:396,y:1342.88,width:200,height:44}, return: {x:620,y:1342.88,width:200,height:44}, edit: {x:844,y:1342.88,width:200,height:44} },
    "setup/visible-tooltip": { form: {x:290,y:25,width:860,height:1308.13}, panel: {x:320,y:165,width:800,height:1084.13}, actions: {x:386,y:1249.13,width:668,height:54}, save: {x:396,y:1259.13,width:200,height:44}, return: {x:620,y:1259.13,width:200,height:44}, edit: {x:844,y:1259.13,width:200,height:44} },
    "chart/messages-hidden": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/messages-short": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:107.83}, messages: {x:208,y:22,width:600,height:107.83} },
    "chart/messages-long": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:320.83}, messages: {x:208,y:22,width:600,height:320.83} },
    "chart/messages-multiline": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:173.48}, messages: {x:208,y:22,width:600,height:173.48} },
    "chart/chart-empty": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/chart-data": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/chart-error": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/legend": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/refresh": { chartdiv: {x:8,y:8,width:1424,height:500}, panel: {x:8,y:8,width:1424,height:568.36}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:290,y:533,width:860,height:641.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
  };
  const report = {
    expectedCells: 168, cells: [], failures: [], consoleProblems: [],
    expectedConsoleEvents: [], pageErrors: [], lifecycleProblems: [],
    requestTraces: [], desktopGeometry: {}
  };
  let scenario = "startup";
  let requests = [];

  const ajaxFixture = {
    version: "test", crnt_tm: "12:00:00", stm: "00:01:00", SteamTemp: 78.1,
    PipeTemp: 77.9, WaterTemp: 20.2, TankTemp: 82.3, ACPTemp: 40.1,
    bme_pressure: 760, start_pressure: 759.5, prvl: 1.2, VolumeAll: 1,
    ActualVolumePerHour: 100, WthdrwlProgress: 10, CurrrentSpeed: 0.1,
    CurrrentStepps: 10, TargetStepps: 20, WthdrwlStatus: 0, ProgramNum: 0,
    DetectorTrend: 0, DetectorStatus: 0, useautospeed: false,
    current_power_volt: 0, target_power_volt: 0, current_power_mode: "0",
    current_power_p: 0, WFtotalMl: 0, WFflowRate: 0, bme_temp: 24,
    heap: 200000, rssi: -50, fr_bt: 300000, UseBBuzzer: false, PauseOn: 0,
    PrgType: "", Status: "Готов", Lstatus: "", TimeRemaining: 0, TotalTime: 0,
    alc: 0, stm_alc: 0, ISspd: 0, wp_spd: 0, i2c_pump_present: 0,
    i2c_pump_running: 0, i2c_pump_remaining_ml: 0, i2c_pump_speed: 0,
    PowerOn: 0, StepperStepMl: 111, ProgNum: 0
  };
  const csvFixture = [
    "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum",
    "12:00:00,78.1,77.9,20.2,82.3,760,1",
    "12:00:15,78.2,78.0,20.3,82.5,761,2"
  ].join("\n");

  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error") {
      const entry = scenario + " console " + message.type() + ": " + message.text();
      if (scenario.endsWith("/request-error") && message.type() === "error" &&
          message.text().includes("status of 500")) {
        report.expectedConsoleEvents.push(entry);
      } else {
        report.consoleProblems.push(entry);
      }
    }
  });
  page.on("pageerror", error => report.pageErrors.push(scenario + ": " + error.message));
  page.on("crash", () => report.lifecycleProblems.push(scenario + ": page crashed"));
  page.on("close", () => report.lifecycleProblems.push(scenario + ": page closed"));
  page.on("dialog", async dialog => await dialog.dismiss());
  page.on("request", request => {
    const url = request.url();
    if (!url.startsWith(baseUrl)) return;
    const relative = url.slice(baseUrl.length);
    const queryIndex = relative.indexOf("?");
    const pathname = queryIndex === -1 ? relative : relative.slice(0, queryIndex);
    if (["/ajax", "/data.csv", "/save", "/program", "/command"].includes(pathname)) {
      requests.push(request.method() + " " + relative);
    }
  });
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(ajaxFixture)
  }));
  await page.route("**/data.csv", route => route.fulfill({
    status: 200, contentType: "text/csv", body: csvFixture
  }));
  await page.route("**/save", route => route.fulfill({
    status: 500, contentType: "text/plain", body: "planned request failure"
  }));

  const inspectPage = payload => {
    const cell = payload.cell;
    const failures = [];
    let desktopGeometry = null;
    function rounded(value) { return Math.round(value * 100) / 100; }
    function rectValue(element) {
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return {
        x: rounded(rect.x), y: rounded(rect.y), width: rounded(rect.width),
        height: rounded(rect.height), left: rounded(rect.left), right: rounded(rect.right),
        top: rounded(rect.top), bottom: rounded(rect.bottom),
        scrollWidth: element.scrollWidth, clientWidth: element.clientWidth
      };
    }
    function elementLabel(element) {
      if (!element) return "<missing>";
      if (element.id) return "#" + element.id;
      if (element.getAttribute("name")) return element.tagName.toLowerCase() + "[name=\"" + element.getAttribute("name") + "\"]";
      if (element.className) return "." + String(element.className).trim().replace(/\s+/g, ".");
      return element.tagName.toLowerCase();
    }
    function visible(element) {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" &&
        Number(style.opacity) > 0 && rect.width > 0 && rect.height > 0 &&
        rect.right > 0 && rect.bottom > 0;
    }
    function fail(kind, selector, element, ancestor, detail) {
      failures.push({
        scenario: cell.scenario, page: cell.page, viewport: cell.viewport,
        theme: cell.theme, state: cell.state, kind, selector,
        rect: rectValue(element), ancestorRect: rectValue(ancestor),
        documentScrollWidth: document.documentElement.scrollWidth,
        documentClientWidth: document.documentElement.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        bodyClientWidth: document.body.clientWidth,
        detail
      });
    }
    function checkPageWidth() {
      if (document.documentElement.scrollWidth > innerWidth) {
        fail("document-overflow", "html", document.documentElement, null,
          document.documentElement.scrollWidth + " > " + innerWidth);
      }
      if (document.body.scrollWidth > innerWidth) {
        fail("body-overflow", "body", document.body, null,
          document.body.scrollWidth + " > " + innerWidth);
      }
    }
    function checkInside(element, ancestor, selector) {
      if (!element) {
        fail("missing-selector", selector, null, ancestor, "required target missing");
        return;
      }
      const rect = element.getBoundingClientRect();
      const bounds = ancestor ? ancestor.getBoundingClientRect() : { left: 0, right: innerWidth };
      if (rect.left < bounds.left - 0.01 || rect.right > bounds.right + 0.01 ||
          rect.left < -0.01 || rect.right > innerWidth + 0.01) {
        fail("horizontal-containment", selector, element, ancestor,
          "target must fit viewport and containing block");
      }
    }
    function checkNotClipped(element, selector) {
      if (element && element.scrollWidth > element.clientWidth + 1 && !element.matches("input,select")) {
        fail("content-clipped", selector, element, element.parentElement,
          element.scrollWidth + " > " + element.clientWidth);
      }
    }
    function overlap(first, second) {
      const a = first.getBoundingClientRect();
      const b = second.getBoundingClientRect();
      return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    }
    function checkPairwise(elements, label) {
      for (let i = 0; i < elements.length; i++) {
        for (let j = i + 1; j < elements.length; j++) {
          if (overlap(elements[i], elements[j])) {
            fail("overlap", label, elements[i], elements[j],
              elementLabel(elements[i]) + " overlaps " + elementLabel(elements[j]));
          }
        }
      }
    }
    function checkColors() {
      const style = getComputedStyle(document.documentElement);
      Object.entries(payload.expectedColors).forEach(([name, expected]) => {
        const actual = style.getPropertyValue(name).trim().toLowerCase();
        if (actual !== expected) fail("color-invariant", "html", document.documentElement, null,
          name + "=" + actual + ", expected " + expected);
      });
    }

    if (payload.kind === "request") {
      fail("request-trace", "network", null, null, payload.detail);
      return { failures, desktopGeometry };
    }
    checkPageWidth();
    if (payload.kind === "setup") {
      const form = document.getElementById("setupform");
      const panelId = cell.state === "main-longest-mode" ||
        ["validation-error", "request-error", "visible-tooltip"].includes(cell.state) ? "Main" :
        cell.state === "other-long-values" || cell.state === "other-empty-values" ? "Other" : cell.state;
      const panel = document.getElementById(panelId);
      const actionOwner = document.getElementById("save").parentElement;
      const actions = ["save", "return", "edit"].map(id => document.getElementById(id));
      checkInside(form, null, "#setupform");
      checkInside(document.querySelector(".tab"), form, ".tab");
      checkInside(panel, form, "#" + panel.id);
      checkInside(actionOwner, form, ".setup-actions");
      actions.forEach(element => checkInside(element, actionOwner, "#" + element.id));
      checkPairwise(actions, ".setup-actions controls");
      const controls = Array.from(panel.querySelectorAll("input:not([type=hidden]), select, .button"))
        .filter(visible);
      controls.forEach(element => checkInside(element, panel, elementLabel(element)));
      if (panel.id === "Other") {
        ["blynkauth", "tgtoken", "tgchatid", "videourl"].forEach(name => {
          const element = document.querySelector('input[name="' + name + '"]');
          checkInside(element, element.parentElement, 'input[name="' + name + '"]');
        });
      }
      if (panel.id === "Main") {
        const mode = document.querySelector('#Main select[name="mode"]');
        checkInside(mode, mode.parentElement, '#Main select[name="mode"]');
      }
      if (cell.state === "visible-tooltip") {
        const tip = document.querySelector("#Main .tooltip .tooltiptext");
        checkInside(tip, null, ".tooltip .tooltiptext");
        checkNotClipped(tip, ".tooltip .tooltiptext");
      }
      const error = document.getElementById("request_error");
      if (error && getComputedStyle(error).display !== "none") checkInside(error, null, "#request_error");
      checkColors();
      const contract = {
        form: [form.name, form.getAttribute("action"), form.method],
        actions: actions.map(element => [element.id, element.name, element.type, element.value]),
        longInputs: ["blynkauth", "tgtoken", "tgchatid", "videourl"].map(name => {
          const element = form.elements[name]; return [element.name, element.type];
        }),
        tabs: Array.from(document.querySelectorAll(".tabcontent")).map(element => element.id)
      };
      const expected = {
        form: ["setupform", "/save", "post"],
        actions: [["save", "save", "submit", "Сохранить"], ["return", "return", "button", "На главную"], ["edit", "edit", "button", "Редактор"]],
        longInputs: [["blynkauth", "text"], ["tgtoken", "text"], ["tgchatid", "text"], ["videourl", "text"]],
        tabs: ["Main", "Temp", "Pump", "Beer", "NBK", "Other"]
      };
      if (JSON.stringify(contract) !== JSON.stringify(expected)) {
        fail("behavior-invariant", "#setupform", form, null, JSON.stringify(contract));
      }
      if (cell.viewport === "1440x900") {
        desktopGeometry = {
          form: rectValue(form), panel: rectValue(panel), actions: rectValue(actionOwner),
          save: rectValue(actions[0]), return: rectValue(actions[1]), edit: rectValue(actions[2])
        };
      }
    } else {
      const chartdiv = document.getElementById("chartdiv");
      const panel = document.querySelector(".chart-panel");
      const canvas = document.querySelector(".chart-canvas");
      const form = document.querySelector('form[action="none"]');
      const host = document.getElementById("messagesBox").parentElement;
      const messages = document.getElementById("messagesBox");
      checkInside(chartdiv, null, "#chartdiv");
      checkInside(panel, chartdiv, ".chart-panel");
      checkInside(canvas, panel, ".chart-canvas");
      checkInside(form, null, ".chart-status-form");
      Array.from(form.querySelectorAll(".container_column")).forEach((element, index) => {
        checkInside(element, element.parentElement, ".chart-status-form .container_column:nth(" + index + ")");
      });
      if (getComputedStyle(messages).display !== "none") {
        checkInside(host, null, ".chart-messages-host");
        checkInside(messages, host, "#messagesBox");
        checkNotClipped(messages, "#messagesBox");
        checkPairwise(Array.from(document.querySelectorAll(
          "#messages > .message_0, #messages > .message_1, #messages > .message_2"
        )), "#messages entries");
      }
      ["return", "getlog", "getoldlog"].forEach(id => checkInside(document.getElementById(id), form, "#" + id));
      checkColors();
      const context = canvas.getContext("2d");
      const image = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let nonTransparent = 0;
      for (let index = 3; index < image.length; index += 400) if (image[index] !== 0) nonTransparent++;
      const chartProof = {
        rows: chart.rows.length, canvasWidth: canvas.width,
        canvasHeight: canvas.height, nonTransparent
      };
      if (cell.state === "chart-data" && (chartProof.rows < 2 || chartProof.nonTransparent === 0)) {
        fail("chart-draw", ".chart-canvas", canvas, panel, JSON.stringify(chartProof));
      }
      if (cell.state === "legend" && document.querySelectorAll(".chart-legend-item").length !== 6) {
        fail("chart-legend", ".chart-legend", document.querySelector(".chart-legend"), panel,
          "expected six existing series");
      }
      const scripts = Array.from(document.scripts).map(script => script.getAttribute("src")).filter(Boolean);
      if (JSON.stringify(scripts) !== JSON.stringify(["app.js", "chart.js"]) ||
          form.getAttribute("action") !== "none" || document.getElementById("refresh").name !== "refresh") {
        fail("behavior-invariant", "chart.htm", form, null,
          JSON.stringify({ scripts, action: form.getAttribute("action") }));
      }
      if (cell.viewport === "1440x900") {
        desktopGeometry = {
          chartdiv: rectValue(chartdiv), panel: rectValue(panel), canvas: rectValue(canvas),
          form: rectValue(form), host: rectValue(host), messages: rectValue(messages)
        };
      }
    }
    return { failures, desktopGeometry };
  };
  function verifyDesktopGeometry(cell, actualGeometry) {
    const pageKey = cell.page === "setup.htm" ? "setup" : "chart";
    const baselineKey = pageKey + "/" + cell.state;
    const baselineGeometry = DESKTOP_GEOMETRY_BASELINE[baselineKey];
    if (!baselineGeometry) {
      throw new Error("missing desktop geometry baseline: " + baselineKey);
    }
    const expectedTargets = Object.keys(baselineGeometry).sort();
    const actualTargets = Object.keys(actualGeometry).sort();
    if (JSON.stringify(actualTargets) !== JSON.stringify(expectedTargets)) {
      report.failures.push({
        scenario: cell.scenario, page: cell.page, viewport: cell.viewport,
        theme: cell.theme, state: cell.state, kind: "desktop-geometry",
        selector: "targets", rect: null, ancestorRect: null,
        baseline: expectedTargets, actual: actualTargets, delta: null,
        detail: "desktop target keys changed"
      });
      return;
    }
    expectedTargets.forEach(target => {
      ["x", "y", "width", "height"].forEach(coordinate => {
        let expected = baselineGeometry[target][coordinate];
        if (pageKey === "chart" && target === "canvas" && coordinate === "width") {
          expected = baselineGeometry.panel.width -
            2 * (baselineGeometry.canvas.x - baselineGeometry.panel.x);
        }
        const actual = actualGeometry[target][coordinate];
        const delta = actual - expected;
        if (Math.abs(delta) > DESKTOP_GEOMETRY_TOLERANCE) {
          report.failures.push({
            scenario: cell.scenario, page: cell.page, viewport: cell.viewport,
            theme: cell.theme, state: cell.state, kind: "desktop-geometry",
            selector: target + "." + coordinate, rect: actualGeometry[target],
            ancestorRect: null, baseline: expected, actual, delta,
            detail: "desktop geometry delta exceeds " + DESKTOP_GEOMETRY_TOLERANCE
          });
        }
      });
    });
  }
  function functionalTrace() { return requests.slice().sort(); }
  async function checkTrace(cell, expected) {
    const actual = functionalTrace();
    const wanted = expected.slice().sort();
    report.requestTraces.push({ scenario: cell.scenario, actual });
    if (JSON.stringify(actual) !== JSON.stringify(wanted)) {
      const result = await page.evaluate(inspectPage, {
        kind: "request", cell, expectedColors: expectedColors[cell.theme],
        detail: "actual=" + JSON.stringify(actual) + " expected=" + JSON.stringify(wanted)
      });
      report.failures.push(...result.failures);
    }
  }
  async function setTheme(theme) {
    await page.emulateMedia({ colorScheme: theme });
    await page.evaluate(value => localStorage.setItem("theme", value), theme);
  }
  async function goto(file, theme) {
    await setTheme(theme);
    requests = [];
    const dataResponse = file === "chart.htm" ? page.waitForResponse(response =>
      response.url() === baseUrl + "/data.csv" && response.status() === 200
    ) : null;
    await page.goto(baseUrl + "/" + file, { waitUntil: "load" });
    if (dataResponse) await dataResponse;
    const applied = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    if (applied !== theme) throw new Error(file + " applied theme=" + applied + ", expected " + theme);
  }
  async function openSetupTab(tab) {
    await page.locator(".tablinks").filter({ hasText: new RegExp("^" + ({
      Main: "Основные", Temp: "Температура", Pump: "Насос", Beer: "Пиво",
      NBK: "НБК", Other: "Прочие"
    })[tab] + "$") }).click();
    await page.waitForFunction(name => getComputedStyle(document.getElementById(name)).display !== "none", tab);
  }
  async function applySetupState(state) {
    if (setupTabs.includes(state)) {
      await openSetupTab(state);
      return;
    }
    if (state === "main-longest-mode") {
      await openSetupTab("Main");
      await page.locator('#Main select[name="mode"]').selectOption("4");
    } else if (state === "other-long-values" || state === "other-empty-values") {
      await openSetupTab("Other");
      const value = state === "other-long-values" ? "длинное значение ".repeat(12) : "";
      await page.evaluate(text => ["blynkauth", "tgtoken", "tgchatid", "videourl"].forEach(name => {
        document.querySelector('input[name="' + name + '"]').value = text;
      }), value);
    } else if (state === "validation-error") {
      await openSetupTab("Main");
      await page.evaluate(() => {
        const input = document.querySelector('input[name="DistTemp"]');
        input.value = "not-a-number";
        SamovarApp.readNumericInput(input, { label: "DistTemp" });
      });
    } else if (state === "request-error") {
      await openSetupTab("Main");
      await page.evaluate(async () => {
        const response = await fetch("/save", { method: "POST", body: new FormData(document.forms.setupform) });
        SamovarApp.showRequestError(await SamovarApp.responseErrorText(response, "Настройки не сохранены"));
      });
      await page.waitForFunction(() => {
        const error = document.getElementById("request_error");
        return error && getComputedStyle(error).display !== "none";
      });
    } else if (state === "visible-tooltip") {
      await openSetupTab("Main");
      await page.locator("#Main .tooltip").first().hover();
      await page.waitForFunction(() => {
        const tip = document.querySelector("#Main .tooltip .tooltiptext");
        return tip && getComputedStyle(tip).visibility === "visible";
      });
    }
  }
  async function inspectSetup(cell) {
    const result = await page.evaluate(inspectPage, {
      kind: "setup", cell, expectedColors: expectedColors[cell.theme]
    });
    report.failures.push(...result.failures);
    if (result.desktopGeometry) {
      report.desktopGeometry[cell.scenario] = result.desktopGeometry;
      verifyDesktopGeometry(cell, result.desktopGeometry);
    }
  }
  async function applyChartState(state) {
    await page.waitForFunction(() => window.chart && chart.rows && chart.rows.length >= 2);
    if (state === "messages-hidden") {
      await page.evaluate(() => SamovarApp.clearMessages());
    } else if (state === "messages-short") {
      await page.evaluate(() => { SamovarApp.clearMessages(); SamovarApp.notify("Короткое сообщение", 2); });
    } else if (state === "messages-long") {
      await page.evaluate(() => { SamovarApp.clearMessages(); SamovarApp.notify("Длинное диагностическое сообщение ".repeat(16), 1); });
    } else if (state === "messages-multiline") {
      await page.evaluate(() => {
        SamovarApp.clearMessages();
        SamovarApp.notify("Первая строка", 2); SamovarApp.notify("Вторая строка", 1); SamovarApp.notify("Третья строка", 0);
      });
    } else if (state === "chart-empty") {
      await page.evaluate(() => { chart.setData([]); chart.draw(); });
    } else if (state === "chart-data") {
      await page.evaluate(() => chart.draw());
    } else if (state === "chart-error") {
      await page.evaluate(() => { chart.draw(); chart.setStatus("planned chart error", true); });
    } else if (state === "legend") {
      await page.evaluate(() => chart.draw());
    } else if (state === "refresh") {
      await page.locator("#refresh + label").click();
      const stopped = await page.evaluate(() => !chart.autoRefresh);
      await page.locator("#refresh + label").click();
      const resumed = await page.evaluate(() => chart.autoRefresh);
      if (!stopped || !resumed) throw new Error("refresh behavior changed");
    }
  }
  async function inspectChart(cell) {
    const result = await page.evaluate(inspectPage, {
      kind: "chart", cell, expectedColors: expectedColors[cell.theme]
    });
    report.failures.push(...result.failures);
    if (result.desktopGeometry) {
      report.desktopGeometry[cell.scenario] = result.desktopGeometry;
      verifyDesktopGeometry(cell, result.desktopGeometry);
    }
  }

  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const theme of themes) {
      for (const state of setupTabs.concat(setupStates)) {
        scenario = "setup/" + viewport.name + "/" + theme + "/" + state;
        const cell = { scenario, page: "setup.htm", viewport: viewport.name, theme, state };
        try {
          await goto("setup.htm", theme);
          await applySetupState(state);
          await inspectSetup(cell);
          await checkTrace(cell, state === "request-error" ? ["POST /save"] : []);
          report.cells.push(cell);
        } catch (error) {
          throw new Error(scenario + ": " + (error && error.stack ? error.stack : error));
        }
      }
      for (const state of chartStates) {
        scenario = "chart/" + viewport.name + "/" + theme + "/" + state;
        const cell = { scenario, page: "chart.htm", viewport: viewport.name, theme, state };
        try {
          await goto("chart.htm", theme);
          await applyChartState(state);
          await inspectChart(cell);
          await checkTrace(cell, ["GET /ajax?messageCursor=0", "GET /data.csv"]);
          report.cells.push(cell);
        } catch (error) {
          let diagnostics = null;
          if (error && String(error).includes("Timeout")) {
            const chartState = await page.evaluate(() => ({
              present: !!window.chart,
              rows: window.chart && Array.isArray(chart.rows) ? chart.rows.length : null,
              status: document.querySelector(".chart-status")?.textContent || null
            }));
            diagnostics = {
              chartState, requests: requests.slice(),
              consoleProblems: report.consoleProblems.slice(-5),
              pageErrors: report.pageErrors.slice(-5)
            };
          }
          throw new Error(scenario + ": " + (error && error.stack ? error.stack : error) +
            (diagnostics ? " diagnostics=" + JSON.stringify(diagnostics) : ""));
        }
      }
    }
  }
  if (report.cells.length !== 168) throw new Error("matrix cardinality=" + report.cells.length + ", expected 168");
  if (Object.keys(DESKTOP_GEOMETRY_BASELINE).length !== 21) {
    throw new Error("desktop baseline cardinality=" + Object.keys(DESKTOP_GEOMETRY_BASELINE).length + ", expected 21");
  }
  const expectedDesktopScenarios = Object.keys(DESKTOP_GEOMETRY_BASELINE).flatMap(key => {
    const parts = key.split("/");
    return themes.map(theme => parts[0] + "/1440x900/" + theme + "/" + parts[1]);
  }).sort();
  const actualDesktopScenarios = Object.keys(report.desktopGeometry).sort();
  if (JSON.stringify(actualDesktopScenarios) !== JSON.stringify(expectedDesktopScenarios)) {
    throw new Error("desktop scenario keys changed: " + JSON.stringify(actualDesktopScenarios));
  }
  if (report.expectedConsoleEvents.length !== 8) {
    throw new Error("expected HTTP 500 console cardinality=" + report.expectedConsoleEvents.length + ", expected 8");
  }
  await page.request.post(baseUrl + "/__u04_report", { data: report });
  await page.unrouteAll({ behavior: "ignoreErrors" });
  return { cells: report.cells.length, failures: report.failures.length };
}'''


class ReportHandler(QuietHandler):
    def do_POST(self) -> None:
        if self.path != "/__u04_report":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 16 * 1024 * 1024:
                raise ValueError("invalid report size")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("report must be an object")
            self.server.u04_report = payload  # type: ignore[attr-defined]
            self.send_response(204)
            self.end_headers()
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)


def verify_cli() -> str:
    cli = shutil.which("playwright-cli")
    if cli != str(EXPECTED_CLI):
        raise RuntimeError(f"isolated playwright-cli required, got {cli!r}")
    version = subprocess.run(
        [cli, "--version"], capture_output=True, text=True, check=False, timeout=30
    )
    if version.returncode != 0 or version.stdout.strip() != "0.1.17":
        raise RuntimeError(f"playwright-cli version mismatch: {version.stdout.strip()!r}")
    return cli


def main() -> int:
    try:
        cli = verify_cli()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"U-04 responsive browser gate failed: {error}", file=sys.stderr)
        return 2

    primary_error = None
    cleanup_errors: list[str] = []
    browser_report = None
    with tempfile.TemporaryDirectory(prefix="samovar-u04-browser-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(ReportHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.u04_report = None  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-u04-{os.getpid()}"
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({
                "browser": {
                    "browserName": "chromium",
                    "launchOptions": {"chromiumSandbox": False},
                }
            }), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            code = BROWSER_TEST.replace(
                "__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}")
            )
            run_cli(cli, session, ["run-code", code], temp, 300)
            browser_report = server.u04_report  # type: ignore[attr-defined]
            if not isinstance(browser_report, dict):
                raise RuntimeError("browser did not return the U-04 report")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if browser_report is not None:
        failures = browser_report.get("failures")
        console_problems = browser_report.get("consoleProblems")
        page_errors = browser_report.get("pageErrors")
        lifecycle = browser_report.get("lifecycleProblems")
        if isinstance(failures, list) and failures:
            for failure in failures[:40]:
                print(
                    "U-04 responsive browser failure: "
                    f"{failure.get('scenario')} {failure.get('selector')} "
                    f"{failure.get('kind')} {failure.get('detail')}",
                    file=sys.stderr,
                )
            if len(failures) > 40:
                print(f"U-04 responsive browser: {len(failures) - 40} more failures not shown", file=sys.stderr)
            primary_error = primary_error or f"{len(failures)} responsive failures"
        for label, values in (
            ("console", console_problems), ("pageerror", page_errors), ("lifecycle", lifecycle)
        ):
            if isinstance(values, list) and values:
                primary_error = primary_error or f"{len(values)} {label} failures"
                for value in values[:20]:
                    print(f"U-04 responsive {label} failure: {value}", file=sys.stderr)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"U-04 responsive browser gate failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"U-04 responsive browser cleanup failed: {error}", file=sys.stderr)
        return 1
    print("U-04 responsive browser gate passed: 168/168 cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
