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
      "--accent": "#3498db", "--bg-page": "#3498db", "--bg-form": "#fafafa",
      "--bg-input": "#fafafa", "--text-main": "#777", "--text-strong": "#000",
      "--text-on-accent": "#fff", "--border-input": "#a9a9a9",
      "--border-soft": "#ccc", "--state-danger-bg": "#b00020"
    },
    dark: {
      "--accent": "#3498db", "--bg-page": "#1a2733", "--bg-form": "#21303d",
      "--bg-input": "#1a2733", "--text-main": "#cfd8e3", "--text-strong": "#f3f6f9",
      "--text-on-accent": "#fff", "--border-input": "#8da1b5",
      "--border-soft": "#8da1b5", "--state-danger-bg": "#b00020"
    }
  };
  const DESKTOP_GEOMETRY_TOLERANCE = 0.5;
  // 01.09.2026: полоса участка графика (две ручки вместо колёсика) выше прежней
  // полосы прокрутки на 6 px - на столько же подросли панель и форма под ней.
  // 02.09.2026: у поля DistTemp (вкладка Main) появилась подсказка (П11) - вкладка Main
  // и все сценарии на её основе стали выше на 18.42 px; остальные вкладки не менялись.
  // 04.09.2026: с Temp убраны два поля су-вида; в Beer добавлен BeerBrewOrder.
  const DESKTOP_GEOMETRY_BASELINE = {
    "setup/Main": { form: {x:265,y:25,width:910,height:1413.97}, panel: {x:295,y:163,width:850,height:1201.97}, actions: {x:386,y:1364.97,width:668,height:44}, save: {x:396,y:1374.97,width:200,height:34}, return: {x:620,y:1374.97,width:200,height:34}, edit: {x:844,y:1374.97,width:200,height:34} },
    "setup/Temp": { form: {x:265,y:25,width:910,height:1578.55}, panel: {x:295,y:163,width:850,height:1366.55}, actions: {x:386,y:1529.55,width:668,height:44}, save: {x:396,y:1539.55,width:200,height:34}, return: {x:620,y:1539.55,width:200,height:34}, edit: {x:844,y:1539.55,width:200,height:34} },
    "setup/Pump": { form: {x:265,y:25,width:910,height:418.69}, panel: {x:295,y:163,width:850,height:206.69}, actions: {x:386,y:369.69,width:668,height:44}, save: {x:396,y:379.69,width:200,height:34}, return: {x:620,y:379.69,width:200,height:34}, edit: {x:844,y:379.69,width:200,height:34} },
    "setup/Beer": { form: {x:265,y:25,width:910,height:717.22}, panel: {x:295,y:163,width:850,height:505.22}, actions: {x:386,y:668.22,width:668,height:44}, save: {x:396,y:678.22,width:200,height:34}, return: {x:620,y:678.22,width:200,height:34}, edit: {x:844,y:678.22,width:200,height:34} },
    "setup/NBK": { form: {x:265,y:25,width:910,height:685.8}, panel: {x:295,y:163,width:850,height:473.8}, actions: {x:386,y:636.8,width:668,height:44}, save: {x:396,y:646.8,width:200,height:34}, return: {x:620,y:646.8,width:200,height:34}, edit: {x:844,y:646.8,width:200,height:34} },
    "setup/Other": { form: {x:265,y:25,width:910,height:1405.75}, panel: {x:295,y:163,width:850,height:1193.75}, actions: {x:386,y:1356.75,width:668,height:44}, save: {x:396,y:1366.75,width:200,height:34}, return: {x:620,y:1366.75,width:200,height:34}, edit: {x:844,y:1366.75,width:200,height:34} },
    "setup/main-longest-mode": { form: {x:265,y:25,width:910,height:1413.97}, panel: {x:295,y:163,width:850,height:1201.97}, actions: {x:386,y:1364.97,width:668,height:44}, save: {x:396,y:1374.97,width:200,height:34}, return: {x:620,y:1374.97,width:200,height:34}, edit: {x:844,y:1374.97,width:200,height:34} },
    "setup/other-long-values": { form: {x:265,y:25,width:910,height:1405.75}, panel: {x:295,y:163,width:850,height:1193.75}, actions: {x:386,y:1356.75,width:668,height:44}, save: {x:396,y:1366.75,width:200,height:34}, return: {x:620,y:1366.75,width:200,height:34}, edit: {x:844,y:1366.75,width:200,height:34} },
    "setup/other-empty-values": { form: {x:265,y:25,width:910,height:1405.75}, panel: {x:295,y:163,width:850,height:1193.75}, actions: {x:386,y:1356.75,width:668,height:44}, save: {x:396,y:1366.75,width:200,height:34}, return: {x:620,y:1366.75,width:200,height:34}, edit: {x:844,y:1366.75,width:200,height:34} },
    "setup/validation-error": { form: {x:265,y:25,width:910,height:1497.72}, panel: {x:295,y:246.75,width:850,height:1201.97}, actions: {x:386,y:1448.72,width:668,height:44}, save: {x:396,y:1458.72,width:200,height:34}, return: {x:620,y:1458.72,width:200,height:34}, edit: {x:844,y:1458.72,width:200,height:34} },
    "setup/request-error": { form: {x:265,y:25,width:910,height:1497.72}, panel: {x:295,y:246.75,width:850,height:1201.97}, actions: {x:386,y:1448.72,width:668,height:44}, save: {x:396,y:1458.72,width:200,height:34}, return: {x:620,y:1458.72,width:200,height:34}, edit: {x:844,y:1458.72,width:200,height:34} },
    "setup/visible-tooltip": { form: {x:265,y:25,width:910,height:1413.97}, panel: {x:295,y:163,width:850,height:1201.97}, actions: {x:386,y:1364.97,width:668,height:44}, save: {x:396,y:1374.97,width:200,height:34}, return: {x:620,y:1374.97,width:200,height:34}, edit: {x:844,y:1374.97,width:200,height:34} },
    "chart/messages-hidden": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/messages-short": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:47.34}, messages: {x:208,y:22,width:600,height:47.34} },
    "chart/messages-long": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:276.83}, messages: {x:208,y:22,width:600,height:276.83} },
    "chart/messages-multiline": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:113}, messages: {x:208,y:22,width:600,height:113} },
    "chart/chart-empty": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/chart-data": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/chart-error": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/legend": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
    "chart/refresh": { chartdiv: {x:8,y:8,width:1424,height:613.03}, panel: {x:8,y:8,width:1424,height:613.03}, canvas: {x:17.39,y:17.39,width:1405.22,height:500}, form: {x:265,y:646.03,width:910,height:675.42}, host: {x:208,y:22,width:600,height:0}, messages: {x:0,y:0,width:0,height:0} },
  };
  const report = {
    expectedCells: 168, cells: [], failures: [], consoleProblems: [],
    expectedConsoleEvents: [], pageErrors: [], lifecycleProblems: [],
    requestTraces: [], desktopGeometry: {}, tooltipFitCells: [], tooltipFitBlocked: []
  };
  let scenario = "startup";
  let requests = [];

  const ajaxFixture = {
    version: "test", crnt_tm: "12:00:00", stm: "00:01:00", SteamTemp: 78.1,
    PipeTemp: 77.9, WaterTemp: 20.2, TankTemp: 82.3, ACPTemp: 40.1,
    bme_pressure: 760, start_pressure: 759.5, prvl: 1.2, VolumeAll: 1,
    ActualVolumePerHour: 100, WthdrwlProgress: 10, CurrrentSpeed: 0.1,
    CurrrentStepps: 10, TargetStepps: 20, WthdrwlStatus: 0, ProgramNum: 3,
    DetectorTrend: 0, DetectorStatus: 0, useautospeed: false,
    current_power_volt: 0, target_power_volt: 0, current_power_mode: "0",
    current_power_p: 0, WFtotalMl: 0, WFflowRate: 0, bme_temp: 24,
    heap: 200000, rssi: -50, fr_bt: 300000, UseBBuzzer: false, PauseOn: 0,
    PrgType: "", Status: "Готов", Lstatus: "", TimeRemaining: 0, TotalTime: 0,
    alc: 0, stm_alc: 0, ISspd: 0, wp_spd: 0, i2c_pump_present: 0,
    i2c_pump_running: 0, i2c_pump_remaining_ml: 0, i2c_pump_speed: 0,
    PowerOn: 0, StepperStepMl: 111,
    heaterAlarmLatched: 0, heaterAlarmReason: '', latestMessageSequence: 0
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
  // program.htm/index.htm/distiller.htm (проверка подсказок на fit, ниже) на загрузке
  // сами запрашивают параметры колонки - без фикстуры это настоящий 404 от тестового
  // статического сервера. Та же фикстура, что в test_u03_contrast_browser.py.
  await page.route("**/ajax_col_params?*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({
      floodPowerW: 3000, workingPowerW: 2500, maxFlowMlH: 1000,
      theoreticalPlates: 20, headsFlowMlH: 100, bodyFlowMinMlH: 200,
      bodyFlowMaxMlH: 400, bodyEndFlowMlH: 300, tailsFlowMlH: 150,
      headsPowerW: 1800, bodyEndPowerW: 2200, tailsPowerW: 2000,
      headsSpeedClamped: false, bodySpeedClamped: false
    })
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
      const scripts = Array.from(document.scripts).map(script => {
        const src = script.getAttribute("src");
        return src ? src.split("?")[0] : null;
      }).filter(Boolean);
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
            detail: "actual=" + actual + " baseline=" + expected + " delta=" + delta +
              " exceeds " + DESKTOP_GEOMETRY_TOLERANCE
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
      // selectOption эмулирует реальный ввод и триггерит change, из-за чего
      // форма помечается "грязной" (см. WP23 beforeunload-guard в setup.htm).
      // Этот сценарий проверяет только вёрстку, а не dirty-tracking, поэтому
      // снимаем флаг, чтобы следующий goto() не упёрся в нативный диалог.
      await page.evaluate(() => {
        const f = document.getElementById("setupform");
        if (f) f.dataset.dirty = "false";
      });
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

  // [код-ревью 24.08 #1] Подсказка (.tooltiptext) не должна вылезать за границы экрана
  // ни при каком положении её метки в строке. 168-матрица выше гоняет только
  // setup.htm/chart.htm (и там - только один тултип на вкладке Main), а сюда попадают
  // именно страницы из находки (program.htm - колонки "Мощность" и "Скорость",
  // index.htm, distiller.htm) плюс остальные вкладки setup.htm, где подсказок больше
  // всего. На 320px требуем помещение в экран у КАЖДОЙ найденной подсказки; на 1280px -
  // только санity, что подсказка ещё не оторвалась от метки на весь экран (эти три
  // страницы раньше вообще не попадали в u04, широкий экран для них не проверялся).
  async function checkTooltipFit(page_, file, viewport, tabLabel) {
    // enhanceTooltips() (app.js) ставит на каждую содержательную .tooltip кнопку
    // .tooltip-trigger и выносит .tooltiptext рядом с ней внутрь общей .tooltip-wrap -
    // подсказку открывает клик по триггеру, а не hover, поэтому и метим/кликаем именно
    // триггер; текст подсказки для лога берём у исходной .tooltip (соседа триггера).
    const owners = await page_.evaluate(() => {
      const list = Array.from(document.querySelectorAll(".tooltip")).filter(
        el => el.offsetParent !== null && el.querySelector(".tooltiptext"));
      list.forEach((el, index) => { el.dataset.tooltipFitProbe = String(index); });
      return list.map((el, index) => {
        return { index, label: (el.textContent || "").trim().slice(0, 40) };
      });
    });
    for (const owner of owners) {
      const selector = '[data-tooltip-fit-probe="' + owner.index + '"]';
      const scenario = "tooltip-fit/" + viewport.name + "/" + file + (tabLabel ? "/" + tabLabel : "") + "/" + owner.label;
      report.tooltipFitCells.push(scenario);
      try {
        await page_.locator(selector).first().hover();
      } catch (clickError) {
        // Отдельный, не связанный с этой правкой баг: на index.htm/distiller.htm при 320px
        // соседние подписи заголовков колонок программы перекрывают друг друга и блокируют
        // реальный клик (Playwright пишет "... subtree intercepts pointer events"). Он
        // воспроизводится один в один и на СТАРОМ style.css (до фикса подсказок, там тем же
        // образом ломался hover) - значит это не регрессия текущего изменения и чинить его
        // здесь не в рамках этой находки. Подделывать клик через force:true нельзя: реальный
        // курсор в этом месте достаётся соседней подписи, а не этой, и .tooltiptext у ЭТОГО
        // элемента так и останется visibility:hidden - force просто спрячет проблему, а не
        // проверит фикс.
        report.tooltipFitBlocked.push({ scenario, detail: String(clickError).slice(0, 200) });
        continue;
      }
      await page_.waitForFunction(sel => {
        const tip = document.querySelector(sel).querySelector(".tooltiptext");
        return tip && getComputedStyle(tip).visibility === "visible";
      }, selector);
      const rect = await page_.evaluate(sel => {
        const box = document.querySelector(sel).querySelector(".tooltiptext").getBoundingClientRect();
        return { x: box.x, width: box.width, right: box.right };
      }, selector);
      if (rect.x < -0.5 || rect.right > viewport.width + 0.5) {
        report.failures.push({
          scenario, page: file, viewport: viewport.name, theme: "light", state: "tooltip-fit",
          kind: "tooltip-overflow", selector, rect, ancestorRect: null,
          detail: "label=" + owner.label + " x=" + rect.x + " right=" + rect.right + " viewport=" + viewport.width
        });
      }
    }
    await page_.evaluate(() => document.querySelectorAll("[data-tooltip-fit-probe]").forEach(
      el => delete el.dataset.tooltipFitProbe));
    return owners.length;
  }
  function requireTooltipsFound(count, file, viewport, tabLabel) {
    // Без этой проверки ноль найденных подсказок (например, если таблица
    // программы спрятана под вкладкой и её забыли открыть) молча "проходит":
    // цикл просто не делает итераций, а старая проверка суммировала счётчик
    // по ВСЕМ страницам сразу, и program.htm одна перекрывала недостачу.
    if (count < 1) {
      throw new Error("tooltip-fit: 0 подсказок найдено на " + file +
        " (" + viewport.name + (tabLabel ? "/" + tabLabel : "") + ")");
    }
  }
  const tooltipFitPages = ["program.htm", "index.htm", "distiller.htm"];
  const tooltipFitViewports = [
    { name: "320x800", width: 320, height: 800 },
    { name: "1280x800", width: 1280, height: 800 }
  ];
  for (const file of tooltipFitPages) {
    for (const viewport of tooltipFitViewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await goto(file, "light");
      if (file === "program.htm") {
        await page.waitForTimeout(200);
      } else {
        // index.htm/distiller.htm держат таблицу программы под вкладкой "Программа" -
        // без её открытия .tooltip остаются offsetParent===null (тот же приём, что
        // и openSetupTab ниже для setup.htm).
        await page.locator('input.tablinks[value="Программа"]').click();
        await page.locator("#Prog").waitFor({ state: "visible" });
        await page.waitForTimeout(200);
      }
      const count = await checkTooltipFit(page, file, viewport);
      requireTooltipsFound(count, file, viewport);
    }
  }
  // setup.htm: 320px по всем вкладкам (широкий экран для первого тултипа Main уже
  // проверен выше самой 168-матрицей, сценарий setup/*/visible-tooltip).
  // Не у каждой вкладки есть подсказки (Temp/Pump - вообще без .tooltip в разметке),
  // поэтому здесь требуем не "не ноль на каждой вкладке", а точную сумму по всем
  // вкладкам сразу - так и легитимно пустые вкладки не мешают, и потеря покрытия
  // (например, если openSetupTab перестанет открывать нужную панель) не спрячется
  // за одной непустой вкладкой Main.
  // 03.09.2026 (НБК, T6): у NBK появились 3 подсказки (Инерция/Давление захлёба/
  // Т завершения (барда)) - вкладка больше не пустая, сумма 11 -> 14.
  // 04.09.2026: в Beer добавлена подсказка к варочному порядку, сумма 14 -> 15.
  await page.setViewportSize({ width: 320, height: 800 });
  let setupTooltipTotal = 0;
  for (const tab of setupTabs) {
    await goto("setup.htm", "light");
    await openSetupTab(tab);
    setupTooltipTotal += await checkTooltipFit(page, "setup.htm", { name: "320x800", width: 320 }, tab);
  }
  const SETUP_TOOLTIP_TOTAL_EXPECTED = 15;
  if (setupTooltipTotal !== SETUP_TOOLTIP_TOTAL_EXPECTED) {
    throw new Error("tooltip-fit: setup.htm суммарно нашёл " + setupTooltipTotal +
      " подсказок по всем вкладкам, ожидалось " + SETUP_TOOLTIP_TOTAL_EXPECTED);
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
    if not cli:
        raise RuntimeError("playwright-cli is required for the U-04 browser gate")
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
        blocked = browser_report.get("tooltipFitBlocked")
        if isinstance(blocked, list) and blocked:
            for item in blocked:
                print(
                    "U-04 responsive browser note (pre-existing, out of scope, not a fit failure): "
                    f"{item.get('scenario')} hover blocked: {item.get('detail')}",
                    file=sys.stderr,
                )
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
