#!/usr/bin/env python3
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from test_numeric_input_ui_browser import QuietHandler, cleanup, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CLI = Path("/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin/playwright-cli")
DEFAULT_SENSOR_COLORS = {
    "SteamColor": "#ff0000",
    "PipeColor": "#0000ff",
    "WaterColor": "#00bfff",
    "TankColor": "#008000",
    "ACPColor": "#800080",
}
PROGRAM_FIXTURES = {
    "index.htm": "\n".join((
        "H;100;0.1;0;0;120", "B;200;0.2;1;0;120", "C;300;0.3;2;0;120",
        "T;400;0.4;3;0;120", "P;60;0;4;0;120",
    )),
    "beer.htm": "\n".join((
        "P;65;10;0^0^0^0;0", "M;66;0;0^0^0^0;0", "B;100;10;0^0^0^0;0",
        "C;20;0;0^0^0^0;1", "W;0;10;0^0^0^0;0", "F;25;10;0^0^0^0;0",
        "A;65;10;0^0^0^0;0", "L;0;0;0^0^0^0;0",
    )),
    "distiller.htm": "\n".join((
        "T;80;0;120", "S;30;1;120", "A;20;2;120", "P;90;3;120", "R;40;4;120",
    )),
    "nbk.htm": "\n".join(("H;10;120", "S;11;121", "O;12;122", "W;13;123")),
}


BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const mainPages = [
    "index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "program.htm", "setup.htm", "chart.htm", "i2cstepper.htm", "calibrate.htm"
  ];
  const sensorPages = [
    "index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm", "setup.htm", "chart.htm"
  ];
  const modePages = ["index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm"];
  const tooltipPages = [
    "index.htm", "beer.htm", "distiller.htm", "nbk.htm", "program.htm", "setup.htm"
  ];
  const togglePages = [
    "index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "setup.htm", "chart.htm", "i2cstepper.htm"
  ];
  const viewports = [
    { name: "desktop", width: 1440, height: 900 },
    { name: "mobile", width: 390, height: 844 },
    { name: "narrow", width: 320, height: 800 }
  ];
  const themes = ["light", "dark"];
  const expectedSensorColors = {
    SteamColor: "#ff0000", PipeColor: "#0000ff", WaterColor: "#00bfff",
    TankColor: "#008000", ACPColor: "#800080"
  };
  const report = {
    baselineCells: [], brewxmlCells: [], stateCases: [], failures: [],
    exemptions: [], consoleProblems: [], lifecycleProblems: [], parity: {}
  };
  const parity = new Map();
  let scenario = "startup";
  let requestLog = [];

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
  const i2cMixer = {
    present: 1, address: 16, role: 1, mode: 1, caps: 25, status: 0, error: 0,
    relayMask: 0, sensorFlags: 0, optionFlags: 0, mixerRpm: 100,
    mixerRunSec: 10, mixerPauseSec: 5, pumpMlHour: 0, pumpPauseSec: 0,
    fillingMl: 0, fillingMlHour: 0, stepsPerMl: 1, remaining: 0, currentSpeed: 0
  };
  const i2cPump = {
    present: 1, address: 17, role: 2, mode: 3, caps: 30, status: 0, error: 0,
    relayMask: 0, sensorFlags: 0, optionFlags: 0, mixerRpm: 0,
    mixerRunSec: 0, mixerPauseSec: 0, pumpMlHour: 100, pumpPauseSec: 0,
    fillingMl: 100, fillingMlHour: 100, stepsPerMl: 100, remaining: 0,
    currentSpeed: 0
  };
  const csvFixture = [
    "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum",
    "12:00:00,78.1,77.9,20.2,82.3,760,1",
    "12:00:15,78.2,78.0,20.3,82.5,761,2"
  ].join("\n");

  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error") {
      report.consoleProblems.push(scenario + " console " + message.type() + ": " + message.text());
    }
  });
  page.on("pageerror", error => report.consoleProblems.push(scenario + " pageerror: " + error.message));
  page.on("request", request => {
    const url = request.url();
    if (url.startsWith(baseUrl)) requestLog.push(url.slice(baseUrl.length));
  });
  page.on("close", () => report.lifecycleProblems.push(scenario + " page closed"));
  page.on("crash", () => report.lifecycleProblems.push(scenario + " page crashed"));
  page.on("dialog", async dialog => await dialog.dismiss());

  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(ajaxFixture)
  }));
  await page.route("**/ajax_col_params?*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({
      floodPowerW: 3000, workingPowerW: 2500, maxFlowMlH: 1000,
      theoreticalPlates: 20, headsFlowMlH: 100, bodyFlowMinMlH: 200,
      bodyFlowMaxMlH: 400, bodyEndFlowMlH: 300, tailsFlowMlH: 150,
      headsPowerW: 1800, bodyEndPowerW: 2200, tailsPowerW: 2000
    })
  }));
  await page.route("**/i2cstepper?device=mixer", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(i2cMixer)
  }));
  await page.route("**/i2cstepper?device=pump", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(i2cPump)
  }));
  await page.route("**/data.csv", route => route.fulfill({
    status: 200, contentType: "text/csv", body: csvFixture
  }));

  function addFailure(label, selector, state, value) {
    report.failures.push({
      scenario: label, selector, state,
      foreground: value && value.foreground || null,
      background: value && value.background || null,
      ratio: value && value.ratio !== undefined ? value.ratio : null,
      threshold: value && value.threshold !== undefined ? value.threshold : null,
      detail: value && value.detail || "contrast contract failed"
    });
  }

  async function setTheme(root, theme) {
    await page.goto(baseUrl + "/" + root + "/app.js", { waitUntil: "load" });
    await page.evaluate(value => localStorage.setItem("theme", value), theme);
  }

  async function gotoPage(root, file, theme, waitMs = 90, manualTheme = false) {
    await setTheme(root, theme);
    scenario = root + "/" + theme + "/" + file;
    requestLog = [];
    await page.goto(baseUrl + "/" + root + "/" + file, { waitUntil: "load" });
    if (manualTheme) {
      await page.evaluate(value => document.documentElement.setAttribute("data-theme", value), theme);
    }
    await page.waitForTimeout(waitMs);
    const applied = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    if (applied !== theme) {
      addFailure(scenario, "html", "theme", { detail: "applied theme=" + applied });
    }
  }

  const browserMetrics = () => {
    function parseColor(value) {
      const input = String(value || "").trim().toLowerCase();
      if (input === "transparent") return [0, 0, 0, 0];
      let match = input.match(/^rgba?\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/);
      if (match) return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])];
      match = input.match(/^#([0-9a-f]{3,8})$/i);
      if (!match) return null;
      let raw = match[1];
      if (raw.length === 3 || raw.length === 4) raw = raw.split("").map(ch => ch + ch).join("");
      if (raw.length !== 6 && raw.length !== 8) return null;
      return [parseInt(raw.slice(0, 2), 16), parseInt(raw.slice(2, 4), 16), parseInt(raw.slice(4, 6), 16), raw.length === 8 ? parseInt(raw.slice(6, 8), 16) / 255 : 1];
    }
    function composite(top, bottom) {
      const alpha = top[3] + bottom[3] * (1 - top[3]);
      if (alpha <= 0) return [0, 0, 0, 0];
      return [0, 1, 2].map(index => (top[index] * top[3] + bottom[index] * bottom[3] * (1 - top[3])) / alpha).concat(alpha);
    }
    function background(element) {
      const layers = [];
      for (let node = element; node && node.nodeType === Node.ELEMENT_NODE; node = node.parentElement) {
        const parsed = parseColor(getComputedStyle(node).backgroundColor);
        if (!parsed) return null;
        layers.push(parsed);
      }
      let result = [255, 255, 255, 1];
      for (let index = layers.length - 1; index >= 0; index--) result = composite(layers[index], result);
      return result;
    }
    function luminance(color) {
      const channels = color.slice(0, 3).map(value => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    }
    function ratio(first, second) {
      const one = luminance(first);
      const two = luminance(second);
      return (Math.max(one, two) + 0.05) / (Math.min(one, two) + 0.05);
    }
    function rgb(color) {
      return color ? "rgb(" + color.slice(0, 3).map(value => Math.round(value)).join(", ") + ")" : null;
    }
    function visible(element) {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) > 0 && rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0;
    }
    function textMetric(element, pseudo) {
      const style = getComputedStyle(element, pseudo || null);
      const bg = background(element);
      const fgRaw = parseColor(style.color);
      if (!bg || !fgRaw) return { detail: "unresolved foreground/background" };
      const fg = composite(fgRaw, bg);
      const size = Number.parseFloat(style.fontSize);
      const weight = Number.parseInt(style.fontWeight, 10) || (style.fontWeight === "bold" ? 700 : 400);
      const threshold = size >= 24 || (size >= 18.6667 && weight >= 700) ? 3 : 4.5;
      return { foreground: rgb(fg), background: rgb(bg), ratio: ratio(fg, bg), threshold };
    }
    function boundaryMetric(element, pseudo) {
      const style = getComputedStyle(element, pseudo || null);
      const parentBg = background(element.parentElement || element);
      const ownBg = background(element);
      const border = parseColor(style.borderTopColor);
      if (!parentBg || !ownBg || !border) return { detail: "unresolved control boundary" };
      const borderOnParent = composite(border, parentBg);
      return {
        foreground: rgb(borderOnParent), background: rgb(parentBg),
        ratio: Math.max(ratio(borderOnParent, parentBg), ratio(ownBg, parentBg)), threshold: 3
      };
    }
    function decorationMetric(element) {
      const style = getComputedStyle(element);
      const bg = background(element);
      const color = parseColor(style.textDecorationColor);
      if (!bg || !color) return { detail: "unresolved decoration color" };
      return { foreground: rgb(composite(color, bg)), background: rgb(bg), ratio: ratio(composite(color, bg), bg), threshold: 0 };
    }
    return { parseColor, composite, background, ratio, rgb, visible, textMetric, boundaryMetric, decorationMetric };
  };
  await page.addInitScript("window.browserMetrics = " + browserMetrics.toString() + ";");

  async function scanDocument(label) {
    const result = await page.evaluate((scenarioLabel) => {
      const metrics = browserMetrics();
      const failures = [];
      const exemptions = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.nodeValue.replace(/\s+/g, " ").trim();
        const element = node.parentElement;
        if (!text || !element || ["SCRIPT", "STYLE", "OPTION"].includes(element.tagName) || !metrics.visible(element)) continue;
        const value = metrics.textMetric(element);
        const selector = element.id ? "#" + element.id : element.className ? "." + String(element.className).trim().replace(/\s+/g, ".") : element.tagName.toLowerCase();
        if (element.matches(":disabled") || element.closest("[aria-disabled=true]")) {
          exemptions.push({ scenario: scenarioLabel, selector, ratio: value.ratio || null, reason: "disabled" });
        } else if (!value.ratio || value.ratio + 1e-9 < value.threshold) {
          failures.push({ scenario: scenarioLabel, selector, state: "text", ...value });
        }
      }
      const controls = new Set(document.querySelectorAll(
        "button, select, textarea, input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]):not([type=file]), .button, .custom-file-upload"
      ));
      controls.forEach(element => {
        if (!metrics.visible(element)) return;
        const selector = element.id ? "#" + element.id : element.className ? "." + String(element.className).trim().replace(/\s+/g, ".") : element.tagName.toLowerCase();
        const disabled = element.matches(":disabled") || element.getAttribute("aria-disabled") === "true";
        const text = metrics.textMetric(element);
        const boundary = metrics.boundaryMetric(element);
        if (disabled) {
          exemptions.push({ scenario: scenarioLabel, selector, ratio: text.ratio || null, reason: "disabled" });
          return;
        }
        if (!text.ratio || text.ratio + 1e-9 < text.threshold) failures.push({ scenario: scenarioLabel, selector, state: "control-text", ...text });
        if (!boundary.ratio || boundary.ratio + 1e-9 < boundary.threshold) failures.push({ scenario: scenarioLabel, selector, state: "control-boundary", ...boundary });
      });
      const elements = Array.from(document.querySelectorAll("body *"));
      const structure = elements.map(element => [element.tagName, element.id, String(element.className)]);
      const textClone = document.body.cloneNode(true);
      textClone.querySelectorAll("script, style, #themeToggle").forEach(element => element.remove());
      const text = textClone.textContent.replace(/\s+/g, " ").trim();
      const geometry = elements.filter(element => element.id !== "themeToggle" && metrics.visible(element)).map(element => {
        const rect = element.getBoundingClientRect();
        return [element.tagName, element.id, String(element.className), ...[rect.x, rect.y, rect.width, rect.height].map(value => Math.round(value * 10) / 10)];
      });
      return { failures, exemptions, structure, text, geometry };
    }, label);
    report.failures.push(...result.failures);
    report.exemptions.push(...result.exemptions);
    return result;
  }

  async function verifySensors(label, customOnly) {
    let values = await page.evaluate(() => {
      const metrics = browserMetrics();
      return Array.from(document.querySelectorAll('[style*="text-decoration-color"]')).map(element => {
        const style = getComputedStyle(element);
        return {
          inline: element.getAttribute("style"), line: style.textDecorationLine,
          decoration: metrics.rgb(metrics.parseColor(style.textDecorationColor)),
          text: metrics.textMetric(element)
        };
      });
    });
    if (customOnly) values = values.filter(item => item.decoration === "rgb(33, 48, 61)");
    const expected = customOnly ? ["rgb(33, 48, 61)"] : Object.values(expectedSensorColors).map(value => {
      const raw = value.slice(1);
      return "rgb(" + [0, 2, 4].map(index => parseInt(raw.slice(index, index + 2), 16)).join(", ") + ")";
    });
    if (values.length !== (customOnly ? 1 : 5)) {
      addFailure(label, "[style*=text-decoration-color]", "sensor-cardinality", { detail: "got " + values.length });
      return;
    }
    expected.forEach(color => {
      const value = values.find(item => item.decoration === color);
      if (!value) addFailure(label, "sensor", "configured-accent", { detail: "missing " + color });
      else {
        if (value.line !== "underline") addFailure(label, "sensor", "underline", { detail: "line=" + value.line });
        if (!value.text.ratio || value.text.ratio + 1e-9 < value.text.threshold) addFailure(label, "sensor", "readable-text", value.text);
      }
    });
  }

  async function verifyChart(label) {
    const value = await page.evaluate(() => {
      const metrics = browserMetrics();
      const canvas = document.querySelector(".chart-canvas");
      const panel = document.querySelector(".chart-panel");
      const background = metrics.background(panel);
      const swatches = Array.from(document.querySelectorAll(".chart-legend-swatch")).map(element => {
        const color = metrics.parseColor(getComputedStyle(element).backgroundColor);
        return color && background ? {
          foreground: metrics.rgb(color), background: metrics.rgb(background),
          ratio: metrics.ratio(color, background), threshold: 3
        } : { detail: "unresolved series color" };
      });
      const grid = metrics.parseColor(getComputedStyle(document.documentElement).getPropertyValue("--border-soft"));
      let pixelColors = 0;
      if (canvas) {
        const context = canvas.getContext("2d");
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
        const unique = new Set();
        for (let index = 0; index < pixels.length; index += Math.max(4, Math.floor(pixels.length / 2000 / 4) * 4)) {
          unique.add([pixels[index], pixels[index + 1], pixels[index + 2], pixels[index + 3]].join(","));
        }
        pixelColors = unique.size;
      }
      return {
        rows: window.chart && chart.rows ? chart.rows.length : 0, swatches,
        grid: grid && background ? {
          foreground: metrics.rgb(grid), background: metrics.rgb(background),
          ratio: metrics.ratio(grid, background), threshold: 3
        } : null,
        pixelColors
      };
    });
    if (value.rows < 2 || value.pixelColors < 2) addFailure(label, ".chart-canvas", "real-data-draw", { detail: JSON.stringify(value) });
    if (value.swatches.length !== 6) addFailure(label, ".chart-legend-swatch", "series-cardinality", { detail: "got " + value.swatches.length });
    value.swatches.forEach((series, index) => {
      if (!series.ratio || series.ratio + 1e-9 < series.threshold) addFailure(label, ".chart-legend-swatch:nth-of-type(" + (index + 1) + ")", "canvas-series", series);
    });
    if (!value.grid || !value.grid.ratio || value.grid.ratio + 1e-9 < value.grid.threshold) addFailure(label, ".chart-canvas", "canvas-grid", value.grid || { detail: "missing grid color" });
  }

  function rememberParity(key, theme, value, requests) {
    const current = {
      structure: JSON.stringify(value.structure), text: value.text,
      geometry: JSON.stringify(value.geometry), requests: JSON.stringify(Array.from(new Set(requests)).sort())
    };
    if (theme === "light") parity.set(key, current);
    else {
      const baseline = parity.get(key);
      if (!baseline) addFailure(key, "document", "parity-baseline", { detail: "missing light baseline" });
      else Object.keys(current).forEach(field => {
        if (current[field] !== baseline[field]) addFailure(key, "document", "light-dark-" + field + "-parity", { detail: "signature changed" });
      });
    }
  }

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const theme of themes) {
      for (const file of mainPages) {
        await gotoPage("default", file, theme, file === "program.htm" || file === "chart.htm" ? 180 : 90);
        const label = viewport.name + "/" + theme + "/" + file;
        const scan = await scanDocument(label);
        if (sensorPages.includes(file)) await verifySensors(label, false);
        if (file === "chart.htm") await verifyChart(label);
        rememberParity(viewport.name + "/" + file, theme, scan, requestLog);
        report.baselineCells.push(label);
      }
      await gotoPage("default", "brewxml.htm", theme, 90, true);
      const brewLabel = viewport.name + "/" + theme + "/brewxml.htm";
      const brew = await scanDocument(brewLabel);
      rememberParity(viewport.name + "/brewxml.htm", theme, brew, requestLog);
      report.brewxmlCells.push(brewLabel);
    }
  }

  await page.setViewportSize({ width: 1440, height: 900 });

  for (const theme of themes) {
    for (const file of togglePages) {
      await gotoPage("default", file, theme);
      const target = theme === "light" ? "dark" : "light";
      await page.click("#themeToggle");
      const toggled = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
      await page.reload({ waitUntil: "load" });
      const persisted = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
      const label = "toggle/" + theme + "/" + file;
      report.stateCases.push(label);
      if (toggled !== target || persisted !== target) addFailure(label, "#themeToggle", "toggle-reload", { detail: toggled + "/" + persisted });
    }

    for (const file of modePages) {
      await gotoPage("default", file, theme);
      const label = "history/" + theme + "/" + file;
      await page.evaluate(() => { SamovarApp.notify("История U03", 2); SamovarApp.showHistory(); });
      const value = await page.evaluate(() => browserMetrics().textMetric(document.querySelector("#historyList > *")));
      report.stateCases.push(label);
      if (!value.ratio || value.ratio + 1e-9 < value.threshold) addFailure(label, "#historyList > *", "opened", value);
    }

    for (const file of tooltipPages) {
      await gotoPage("default", file, theme, file === "program.htm" ? 180 : 90);
      const programTab = page.locator('input.tablinks[value="Программа"]');
      if (await programTab.count()) {
        await programTab.first().click();
        await page.locator("#Prog").waitFor({ state: "visible" });
      }
      const found = await page.evaluate((fileName) => {
        const metrics = browserMetrics();
        const selector = fileName === "nbk.htm" ? "#Prog .tooltip" : ".tooltip";
        const owners = Array.from(document.querySelectorAll(selector)).filter(metrics.visible);
        const owner = owners.find(element => element.querySelector(".tooltiptext")) ||
          (fileName === "nbk.htm" ? owners[0] : null);
        if (!owner) return { exists: false };
        owner.dataset.u03Tooltip = "1";
        return { exists: true, hasText: Boolean(owner.querySelector(".tooltiptext")) };
      }, file);
      const label = "tooltip/" + theme + "/" + file;
      report.stateCases.push(label);
      if (!found.exists) addFailure(label, ".tooltip", "visible", { detail: "missing tooltip owner" });
      else {
        await page.hover('[data-u03-tooltip="1"]');
        const value = await page.evaluate((hasText) => {
          const owner = document.querySelector('[data-u03-tooltip="1"]');
          const element = hasText ? owner.querySelector(".tooltiptext") : owner;
          return { visibility: getComputedStyle(element).visibility, metric: browserMetrics().textMetric(element) };
        }, found.hasText);
        if (value.visibility !== "visible" || !value.metric.ratio || value.metric.ratio + 1e-9 < value.metric.threshold) addFailure(label, ".tooltiptext", "visible", value.metric);
      }
    }

    await gotoPage("default", "index.htm", theme);
    for (const level of [0, 1, 2]) {
      await page.evaluate(value => { SamovarApp.clearMessages(); SamovarApp.notify("Сообщение U03", value); }, level);
      const label = "message/" + theme + "/" + level;
      const value = await page.evaluate(() => browserMetrics().textMetric(document.querySelector("#messages > *")));
      report.stateCases.push(label);
      if (!value.ratio || value.ratio + 1e-9 < value.threshold) addFailure(label, ".message_" + level, "visible", value);
    }

    await gotoPage("default", "chart.htm", theme, 180);
    await page.evaluate(() => chart.setStatus("Ошибка U03", true));
    {
      const label = "chart-status-error/" + theme;
      const value = await page.evaluate(() => browserMetrics().textMetric(document.querySelector(".chart-status-error")));
      report.stateCases.push(label);
      if (!value.ratio || value.ratio + 1e-9 < value.threshold) addFailure(label, ".chart-status-error", "error", value);
    }

    for (const file of modePages) {
      await gotoPage("default", file, theme);
      for (const powerOn of [0, 1]) {
        const result = await page.evaluate(({ fixture, state }) => {
          const value = JSON.parse(JSON.stringify(fixture));
          value.PowerOn = state;
          renderTelemetry(value);
          const element = document.getElementById("power");
          return { metric: browserMetrics().textMetric(element), text: element && element.value };
        }, { fixture: ajaxFixture, state: powerOn });
        const label = "power/" + theme + "/" + file + "/" + powerOn;
        report.stateCases.push(label);
        if (!result.text || !result.metric.ratio || result.metric.ratio + 1e-9 < result.metric.threshold) addFailure(label, "#power", powerOn ? "on" : "off", result.metric);
      }
    }

    await gotoPage("default", "index.htm", theme);
    for (const detectorState of [0, 1, 2]) {
      const result = await page.evaluate(({ fixture, state }) => {
        const value = JSON.parse(JSON.stringify(fixture));
        value.useautospeed = true;
        value.DetectorStatus = state;
        renderTelemetry(value);
        const element = document.getElementById("detector_status_text");
        return { metric: browserMetrics().textMetric(element), text: element.textContent };
      }, { fixture: ajaxFixture, state: detectorState });
      const label = "detector/" + theme + "/" + detectorState;
      report.stateCases.push(label);
      if (!/[✅⚠🛑]/u.test(result.text) || !result.metric.ratio || result.metric.ratio + 1e-9 < result.metric.threshold) addFailure(label, "#detector_status_text", "state-" + detectorState, result.metric);
    }

    await gotoPage("default", "i2cstepper.htm", theme, 180);
    for (const state of ["state-on", "state-off"]) {
      await page.evaluate(value => {
        const element = document.getElementById("mixer_run_toggle");
        element.className = "button state-button " + value;
        element.value = value === "state-on" ? "Остановить мешалку" : "Запустить мешалку";
      }, state);
      if (state === "state-on") await page.hover("#mixer_run_toggle");
      else await page.mouse.move(0, 0);
      const result = await page.evaluate(() => {
        const element = document.getElementById("mixer_run_toggle");
        return { metric: browserMetrics().textMetric(element), text: element.value };
      });
      const label = "i2c/" + theme + "/" + state;
      report.stateCases.push(label);
      if (!result.text || !result.metric.ratio || result.metric.ratio + 1e-9 < result.metric.threshold) addFailure(label, ".state-button." + state, state, result.metric);
    }

    const rowTypes = {
      "index.htm": ["H", "B", "C", "T", "P"],
      "beer.htm": ["P", "M", "B", "C", "W", "F", "A", "L"],
      "distiller.htm": ["T", "S", "A", "P", "R"],
      "nbk.htm": ["H", "S", "O", "W"],
      "program.htm": ["H", "B", "C", "T", "P"]
    };
    for (const [file, types] of Object.entries(rowTypes)) {
      await gotoPage("default", file, theme, file === "program.htm" ? 300 : 150);
      const programTab = page.locator('input.tablinks[value="Программа"]');
      if (await programTab.count()) {
        await programTab.first().click();
        await page.locator("#Prog").waitFor({ state: "visible" });
      }
      await page.waitForFunction(() => document.querySelector(".prgline[id^=prgln]"));
      for (const type of types) {
        const result = await page.evaluate(({ fileName, typeName }) => {
          const metrics = browserMetrics();
          const rowMetric = candidate => {
            const targets = Array.from(candidate.querySelectorAll("label, input:not([type=hidden]), select, span")).filter(metrics.visible);
            const values = targets.map(element => metrics.textMetric(element)).filter(value => value.ratio);
            const text = candidate.textContent.trim() || (candidate.querySelector("select") && candidate.querySelector("select").value) || typeName;
            if (!values.length) return { detail: "missing visible row text", text };
            values.sort((left, right) => left.ratio - right.ratio);
            return { ...values[0], text };
          };
          const rows = Array.from(document.querySelectorAll(".prgline[id^=prgln]"));
          let row = null;
          if (fileName === "nbk.htm") {
            const index = ["H", "S", "O", "W"].indexOf(typeName);
            row = document.getElementById("prgln" + (index + 1));
          } else {
            row = rows.find(candidate => {
              const select = candidate.querySelector("select[id^=ptype]");
              return select && select.value === typeName;
            });
          }
          if (!row) return { normal: { detail: "missing row", text: "" }, active: null };
          if (fileName !== "index.htm") return { normal: rowMetric(row), active: null };

          const rowIndex = Number(row.id.slice("prgln".length));
          current_progNum = 0;
          set_bgcolor(rowIndex);
          const normal = rowMetric(row);
          current_progNum = rowIndex + 1;
          set_bgcolor(rowIndex);
          const active = rowMetric(row);
          current_progNum = 0;
          set_bgcolor(rowIndex);
          return { normal, active };
        }, { fileName: file, typeName: type });
        const label = "program-row/" + theme + "/" + file + "/" + type;
        report.stateCases.push(label);
        if (!result.normal.text || !result.normal.ratio || result.normal.ratio + 1e-9 < result.normal.threshold) addFailure(label, ".prgline", type + "-normal", result.normal);
        if (file === "index.htm" && (!result.active || !result.active.text || !result.active.ratio || result.active.ratio + 1e-9 < result.active.threshold)) {
          addFailure(label, ".prgline", type + "-active", result.active || { detail: "missing active row metric" });
        }
      }
    }

    for (const file of sensorPages) {
      await gotoPage("custom", file, theme);
      const label = "custom-sensor/" + theme + "/" + file;
      report.stateCases.push(label);
      await verifySensors(label, true);
    }

    await gotoPage("default", "beer.htm", theme, 180);
    await page.evaluate(() => popup_modal(0));
    {
      const label = "beer-popup/" + theme;
      const value = await page.evaluate(() => {
        const metrics = browserMetrics();
        const targets = Array.from(document.querySelectorAll("#popup .popup__title, #popup .popup__button")).map(element => metrics.textMetric(element));
        targets.sort((left, right) => (left.ratio || 0) - (right.ratio || 0));
        return targets[0] || { detail: "missing popup content" };
      });
      report.stateCases.push(label);
      if (!value.ratio || value.ratio + 1e-9 < value.threshold) addFailure(label, "#popup", "open", value);
    }

    await gotoPage("default", "index.htm", theme);
    const buttonSelector = "#power";
    await page.hover(buttonSelector);
    {
      const label = "button-hover/" + theme;
      const value = await page.evaluate(selector => browserMetrics().textMetric(document.querySelector(selector)), buttonSelector);
      report.stateCases.push(label);
      if (!value.ratio || value.ratio + 1e-9 < value.threshold) addFailure(label, buttonSelector, "hover", value);
    }
    await page.focus(buttonSelector);
    {
      const label = "button-focus/" + theme;
      const value = await page.evaluate(selector => {
        const element = document.querySelector(selector);
        const metrics = browserMetrics();
        const style = getComputedStyle(element);
        const outline = metrics.parseColor(style.outlineColor);
        const bg = metrics.background(element);
        return outline && bg ? { foreground: metrics.rgb(outline), background: metrics.rgb(bg), ratio: metrics.ratio(outline, bg), threshold: 3 } : { detail: "missing focus outline" };
      }, buttonSelector);
      report.stateCases.push(label);
      if (!value.ratio || value.ratio + 1e-9 < value.threshold) addFailure(label, buttonSelector, "focus", value);
    }
    const box = await page.locator(buttonSelector).boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
    }
    {
      const label = "button-active/" + theme;
      const value = await page.evaluate(selector => browserMetrics().textMetric(document.querySelector(selector)), buttonSelector);
      report.stateCases.push(label);
      if (!value.ratio || value.ratio + 1e-9 < value.threshold) addFailure(label, buttonSelector, "active", value);
    }
    if (box) { await page.mouse.move(0, 0); await page.mouse.up(); }

    await gotoPage("default", "program_invalid.htm", theme, 180);
    {
      const label = "disabled/" + theme;
      const result = await page.evaluate(() => {
        const element = document.getElementById("heaterMaxPower");
        return { disabled: element.disabled, metric: browserMetrics().textMetric(element) };
      });
      report.stateCases.push(label);
      if (!result.disabled) addFailure(label, "#heaterMaxPower", "disabled", { detail: "control is enabled" });
      else report.exemptions.push({ scenario: label, selector: "#heaterMaxPower", ratio: result.metric.ratio || null, reason: "disabled" });
    }

    await gotoPage("default", "chart.htm", theme, 180);
    for (const checked of [true, false]) {
      const value = await page.evaluate(state => {
        const input = document.getElementById("refresh");
        input.checked = state;
        const label = document.querySelector('label[for="refresh"]');
        const metrics = browserMetrics();
        const before = metrics.boundaryMetric(label, "::before");
        const afterStyle = getComputedStyle(label, "::after");
        const mark = metrics.parseColor(afterStyle.borderLeftColor);
        const bg = metrics.background(label);
        const after = mark && bg ? { foreground: metrics.rgb(mark), background: metrics.rgb(bg), ratio: metrics.ratio(mark, bg), threshold: 3 } : { detail: "missing checkbox mark" };
        return { before, after };
      }, checked);
      const label = "refresh/" + theme + "/" + checked;
      report.stateCases.push(label);
      if (!value.before.ratio || value.before.ratio + 1e-9 < value.before.threshold) addFailure(label, 'label[for="refresh"]::before', checked ? "checked" : "unchecked", value.before);
      if (checked && (!value.after.ratio || value.after.ratio + 1e-9 < value.after.threshold)) addFailure(label, 'label[for="refresh"]::after', "checked-mark", value.after);
    }

    await gotoPage("default", "index.htm", theme);
    await page.focus("select");
    {
      const label = "select-focus/" + theme;
      const value = await page.evaluate(() => {
        const element = document.querySelector("select");
        const metrics = browserMetrics();
        const style = getComputedStyle(element);
        const outline = metrics.parseColor(style.outlineColor);
        const bg = metrics.background(element);
        const focus = outline && bg ? {
          foreground: metrics.rgb(outline), background: metrics.rgb(bg),
          ratio: metrics.ratio(outline, bg), threshold: 3
        } : { detail: "missing select focus" };
        let arrow = { detail: "missing or unparseable select arrow" };
        const image = style.backgroundImage.trim();
        if (image.startsWith("url(") && image.endsWith(")") && bg) {
          try {
            let payload = image.slice(4, -1).trim();
            if ((payload.startsWith('"') && payload.endsWith('"')) ||
                (payload.startsWith("'") && payload.endsWith("'"))) {
              payload = payload.slice(1, -1);
            }
            payload = decodeURIComponent(payload);
            const comma = payload.indexOf(",");
            const documentNode = comma === -1 ? null : new DOMParser().parseFromString(payload.slice(comma + 1), "image/svg+xml");
            const path = documentNode && documentNode.querySelector("path");
            const fill = path && metrics.parseColor(path.getAttribute("fill"));
            if (fill) {
              arrow = {
                foreground: metrics.rgb(fill), background: metrics.rgb(bg),
                ratio: metrics.ratio(fill, bg), threshold: 3
              };
            }
          } catch (error) {
            arrow = { detail: "missing or unparseable select arrow" };
          }
        }
        return { focus, arrow };
      });
      report.stateCases.push(label);
      if (!value.focus.ratio || value.focus.ratio + 1e-9 < value.focus.threshold) addFailure(label, "select", "focus", value.focus);
      if (!value.arrow.ratio || value.arrow.ratio + 1e-9 < value.arrow.threshold) addFailure(label, "select", "arrow", value.arrow);
    }
  }

  if (report.baselineCells.length !== 60) addFailure("cardinality", "baseline", "cells", { detail: "got " + report.baselineCells.length });
  if (report.brewxmlCells.length !== 6) addFailure("cardinality", "brewxml", "cells", { detail: "got " + report.brewxmlCells.length });
  if (report.stateCases.length !== 160) addFailure("cardinality", "states", "cases", { detail: "got " + report.stateCases.length });
  if (report.consoleProblems.length) report.consoleProblems.forEach(problem => addFailure("console", "window", "warning/error", { detail: problem }));
  if (report.lifecycleProblems.length) report.lifecycleProblems.forEach(problem => addFailure("lifecycle", "page", "close/crash", { detail: problem }));
  if (parity.size !== 33) addFailure("cardinality", "parity", "entries", { detail: "got " + parity.size });
  report.parity = { compared: parity.size, expected: 33 };
  const reportStatus = await page.evaluate(async ({ url, value }) => {
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value)
    });
    return response.status;
  }, { url: baseUrl + "/__u03_report", value: report });
  if (reportStatus !== 204) throw new Error("report upload failed: " + reportStatus);
  return { baseline: report.baselineCells.length, brewxml: report.brewxmlCells.length, states: report.stateCases.length, failures: report.failures.length };
}'''


class ReportHandler(QuietHandler):
    def do_POST(self) -> None:
        if self.path != "/__u03_report":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 8 * 1024 * 1024:
                raise ValueError("invalid report size")
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise ValueError("report must be an object")
            self.server.u03_report = value  # type: ignore[attr-defined]
            self.send_response(204)
            self.end_headers()
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)


def inject_program_fixture(path: Path, fixture: str) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(<textarea[^>]+id=['\"]WProgram['\"][^>]*>)(.*?)(</textarea>)", re.DOTALL)
    text, count = pattern.subn(lambda match: match.group(1) + fixture + match.group(3), text, count=1)
    if count != 1:
        raise RuntimeError(f"WProgram fixture target missing: {path.name}")
    path.write_text(text, encoding="utf-8")


def prepare_site(target: Path, colors: dict[str, str]) -> None:
    render_site(target, color_tokens=colors)
    for name, fixture in PROGRAM_FIXTURES.items():
        inject_program_fixture(target / name, fixture)


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
        print(f"U-03 contrast browser gate failed: {error}", file=sys.stderr)
        return 2

    primary_error = None
    cleanup_errors: list[str] = []
    browser_report = None
    with tempfile.TemporaryDirectory(prefix="samovar-u03-browser-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        prepare_site(site / "default", DEFAULT_SENSOR_COLORS)
        custom_colors = dict(DEFAULT_SENSOR_COLORS)
        custom_colors["PipeColor"] = "#21303d"
        prepare_site(site / "custom", custom_colors)
        handler = functools.partial(ReportHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.u03_report = None  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-u03-{os.getpid()}"
        try:
            open_args = ["open"]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                config = temp / "playwright.json"
                config.write_text(json.dumps({
                    "browser": {
                        "browserName": "chromium",
                        "launchOptions": {"chromiumSandbox": False},
                    }
                }), encoding="utf-8")
                open_args.append(f"--config={config}")
            run_cli(cli, session, open_args, temp, 30)
            code = BROWSER_TEST.replace(
                "__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}")
            )
            run_file = temp / "u03-browser-run.js"
            run_file.write_text(code, encoding="utf-8")
            run_cli(cli, session, ["run-code", f"--filename={run_file}"], temp, 300)
            browser_report = server.u03_report  # type: ignore[attr-defined]
            if not isinstance(browser_report, dict):
                raise RuntimeError("browser did not return the U-03 report")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if browser_report is not None:
        failures = browser_report.get("failures")
        if isinstance(failures, list) and failures:
            for failure in failures[:40]:
                print(
                    "U-03 contrast failure: "
                    f"{failure.get('scenario')} {failure.get('selector')} {failure.get('state')} "
                    f"fg={failure.get('foreground')} bg={failure.get('background')} "
                    f"ratio={failure.get('ratio')} threshold={failure.get('threshold')} "
                    f"detail={failure.get('detail')}",
                    file=sys.stderr,
                )
            if len(failures) > 40:
                print(f"U-03 contrast browser gate: {len(failures) - 40} more failures not shown", file=sys.stderr)
            primary_error = primary_error or f"{len(failures)} contrast/parity failures"

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"U-03 contrast browser gate failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"U-03 contrast browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("U-03 contrast browser gate passed: 60 baseline + 6 brewxml + 160 states")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
