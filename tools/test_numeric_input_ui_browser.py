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


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const pages = [
    "setup.htm", "index.htm", "beer.htm", "bk.htm", "distiller.htm",
    "nbk.htm", "program.htm", "calibrate.htm", "i2cstepper.htm"
  ];
  const viewports = [
    { name: "desktop", width: 1440, height: 900 },
    { name: "mobile", width: 390, height: 844 }
  ];
  const themes = ["light", "dark"];
  const ajaxFixture = {
    version: "test", crnt_tm: "12:00:00", stm: "00:01:00", SteamTemp: 78.1,
    PipeTemp: 77.9, WaterTemp: 20.2, TankTemp: 82.3, ACPTemp: 40.1,
    bme_pressure: 760, start_pressure: 759.5, prvl: 1.2, VolumeAll: 0,
    ActualVolumePerHour: 0, WthdrwlProgress: 0, CurrrentSpeed: 0,
    CurrrentStepps: 0, TargetStepps: 0, WthdrwlStatus: 0, ProgramNum: 0,
    DetectorTrend: 0, DetectorStatus: 0, useautospeed: false,
    current_power_volt: 0, target_power_volt: 0, current_power_mode: "0",
    current_power_p: 0, WFtotalMl: 0, WFflowRate: 0, bme_temp: 24,
    heap: 200000, rssi: -50, fr_bt: 300000, UseBBuzzer: false, PauseOn: 0,
    PrgType: "", Status: "Готов", Lstatus: "",
    TimeRemaining: 0, TotalTime: 0, alc: 0, stm_alc: 0, ISspd: 0, wp_spd: 0,
    i2c_pump_present: 0, i2c_pump_running: 0, i2c_pump_remaining_ml: 0,
    i2c_pump_speed: 0, PowerOn: 0, StepperStepMl: 111
  };
  const columnFixture = {
    floodPowerW: 3000, workingPowerW: 2500, maxFlowMlH: 1000,
    theoreticalPlates: 20, headsFlowMlH: 100, bodyFlowMinMlH: 200,
    bodyFlowMaxMlH: 400, bodyEndFlowMlH: 300, tailsFlowMlH: 150,
    headsPowerW: 1800, bodyEndPowerW: 2200, tailsPowerW: 2000
  };
  const i2cFixtures = {
    mixer: {
      present: 1, address: 16, role: 1, mode: 1, caps: 25, status: 0, error: 0,
      relayMask: 0, sensorFlags: 0, optionFlags: 0, mixerRpm: 100,
      mixerRunSec: 10, mixerPauseSec: 5, pumpMlHour: 0, pumpPauseSec: 0,
      fillingMl: 0, fillingMlHour: 0, stepsPerMl: 1, remaining: 0, currentSpeed: 0
    },
    pump: {
      present: 1, address: 17, role: 2, mode: 3, caps: 30, status: 0, error: 0,
      relayMask: 0, sensorFlags: 0, optionFlags: 0, mixerRpm: 0,
      mixerRunSec: 0, mixerPauseSec: 0, pumpMlHour: 100, pumpPauseSec: 0,
      fillingMl: 100, fillingMlHour: 100, stepsPerMl: 100,
      remaining: 0, currentSpeed: 0
    }
  };
  const consoleProblems = [];
  const lifecycleEvents = [];
  const covered = [];
  let activeRouteHandlers = 0;
  let scenario = "startup";

  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error") {
      consoleProblems.push(scenario + " console " + message.type() + ": " + message.text());
    }
  });
  page.on("pageerror", error => consoleProblems.push(scenario + " pageerror: " + error.message));
  page.on("close", () => lifecycleEvents.push(scenario + " page closed"));
  page.on("crash", () => lifecycleEvents.push(scenario + " page crashed"));
  page.on("dialog", async dialog => {
    lifecycleEvents.push(scenario + " dialog: " + dialog.message());
    await dialog.dismiss();
  });
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(ajaxFixture)
  }));
  await page.route("**/ajax_col_params?*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(columnFixture)
  }));
  async function fulfillI2cRoute(route, fixture) {
    activeRouteHandlers++;
    try {
      await route.fulfill({
        status: 200, contentType: "application/json", body: JSON.stringify(fixture)
      });
    } finally {
      activeRouteHandlers--;
    }
  }
  await page.route("**/i2cstepper?device=mixer", route => fulfillI2cRoute(route, i2cFixtures.mixer));
  await page.route("**/i2cstepper?device=pump", route => fulfillI2cRoute(route, i2cFixtures.pump));

  async function stopI2cPolling() {
    await page.waitForFunction(() =>
      typeof pollInFlight !== "undefined" && !pollInFlight &&
      document.getElementById("pump_panel").style.display === "block"
    );
    await page.evaluate(() => {
      if (pollTimer) clearTimeout(pollTimer);
      pollTimer = null;
      scheduleNextPoll = function() {};
    });
    const deadline = Date.now() + 1000;
    while (activeRouteHandlers && Date.now() < deadline) {
      await page.waitForTimeout(10);
    }
    if (activeRouteHandlers) {
      throw new Error("I2C route handlers did not settle: " + activeRouteHandlers);
    }
  }

  async function setOriginTheme(theme) {
    await page.goto(baseUrl + "/app.js", { waitUntil: "load" });
    await page.evaluate(value => localStorage.setItem("theme", value), theme);
  }

  async function verifySharedValidator(label) {
    const result = await page.evaluate(() => {
      const input = document.createElement("input");
      input.id = "numeric-browser-probe";
      document.body.appendChild(input);
      const invalid = ["", "garbage", "NaN", "Inf", "1e999", "1e-40"];
      const rejected = invalid.every(value => {
        input.value = value;
        return SamovarApp.readNumericInput(input, { label: "Проверка", min: 0, max: 10 }) === null;
      });
      input.value = "1,5";
      const localized = SamovarApp.readNumericInput(input, { label: "Проверка", min: 0, max: 10 });
      const normalized = localized && localized.text === "1.5" && input.value === "1.5";
      input.remove();
      SamovarApp.clearRequestError();
      return { rejected, normalized };
    });
    if (!result.rejected || !result.normalized) {
      throw new Error(label + " shared validator mismatch: " + JSON.stringify(result));
    }
  }

  async function installRecorder(path, responseKind) {
    await page.evaluate(({ expectedPath, kind }) => {
      window.__numericRequests = [];
      window.__numericOperationRequests = [];
      window.__numericOperationId = 901;
      window.__numericOperationState = expectedPath === "/save" ? "failed" : "succeeded";
      window.__numericOperationError = expectedPath === "/save" ? "operation_runtime_busy" : "none";
      window.__numericStatus = expectedPath === "/save" || expectedPath === "/calibrate" ||
        expectedPath === "/i2cstepper" ? 202 : 200;
      window.__numericDelayMs = 0;
      window.__numericResponseText = null;
      window.__numericPlans = [];
      const nativeFetch = window.fetch.bind(window);
      window.fetch = async (url, options) => {
        const raw = typeof url === "string" ? url : url.url;
        if (raw.startsWith("/ajax?operationId=")) {
          window.__numericOperationRequests.push(raw);
          return new Response(JSON.stringify({
            operationId: window.__numericOperationId,
            state: window.__numericOperationState,
            error: window.__numericOperationError
          }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (!raw.startsWith(expectedPath)) return nativeFetch(url, options);
        let body = null;
        if (options && options.body instanceof FormData) body = Array.from(options.body.entries());
        else if (options && options.body !== undefined) body = String(options.body);
        window.__numericRequests.push({ url: raw, method: options && options.method || "GET", body });
        const isI2cMutation = kind === "json" &&
          new URL(raw, window.location.origin).searchParams.has("cmd");
        if (kind === "json" && !isI2cMutation) return nativeFetch(url, options);
        const plan = window.__numericPlans.length ? window.__numericPlans.shift() : null;
        const status = plan && plan.status !== undefined ? plan.status : window.__numericStatus;
        const responseText = plan && plan.text !== undefined ? plan.text : window.__numericResponseText;
        const delayMs = plan && plan.delayMs !== undefined ? plan.delayMs : window.__numericDelayMs;
        if (delayMs) {
          await new Promise(resolve => setTimeout(resolve, delayMs));
        }
        if (kind === "program") {
          const body = { ok: status === 202, err: status === 202 ? "" : "E" + status, program: "" };
          if (status === 202) Object.assign(body, {
            operationId: window.__numericOperationId, state: "queued", error: "none"
          });
          return new Response(JSON.stringify(body), {
            status, headers: { "Content-Type": "application/json" }
          });
        }
        if (kind === "save") {
          const body = status === 202
            ? { operationId: window.__numericOperationId, state: "queued", error: "none" }
            : { error: status === 503 ? "operation_runtime_busy" : "Invalid field", code: "range" };
          return new Response(JSON.stringify(body), {
            status, headers: { "Content-Type": "application/json" }
          });
        }
        if (kind === "calibrate" && status === 202) {
          return new Response(JSON.stringify({
            operationId: window.__numericOperationId, state: "queued", error: "none"
          }), { status, headers: { "Content-Type": "application/json" } });
        }
        if (kind === "json") {
          return new Response(status === 202
            ? JSON.stringify({
                operationId: window.__numericOperationId, state: "queued", error: "none"
              })
            : JSON.stringify({ error: status === 503 ? "BUSY" : "Invalid field", code: "range" }),
            { status, headers: { "Content-Type": "application/json" } });
        }
        const text = responseText !== null
          ? String(responseText)
          : status === 200 ? "OK" : status === 503 ? "BUSY" : "BAD_REQUEST";
        return new Response(text, { status, headers: { "Content-Type": "text/plain" } });
      };
    }, { expectedPath: path, kind: responseKind });
  }

  async function requestState() {
    return page.evaluate(() => ({
      requests: window.__numericRequests.slice(),
      errorVisible: (() => {
        const node = document.getElementById("request_error");
        return !!node && getComputedStyle(node).display !== "none" && node.textContent.trim() !== "";
      })()
    }));
  }

  async function testSetup() {
    await installRecorder("/save", "save");
    const result = await page.evaluate(async () => {
      const form = document.getElementById("setupform");
      const submit = () => submitSetupForm({ preventDefault() {}, currentTarget: form });
      function setBoundary(which) {
        setupNumericSchema.forEach(rule => {
          const input = form.elements[rule.name];
          const value = which === "max"
            ? (rule.max !== undefined ? rule.max : 1)
            : (rule.min !== undefined ? rule.min : rule.exclusiveMin !== undefined ? rule.exclusiveMin + 1 : 0);
          if (input.tagName === "SELECT" && !Array.from(input.options).some(option => option.value === String(value))) {
            input.add(new Option(String(value), String(value)));
          }
          input.value = String(value);
        });
      }
      setBoundary("min");
      form.dispatchEvent(new Event("input", { bubbles: true }));
      const minOk = await submit();
      setBoundary("max");
      form.dispatchEvent(new Event("input", { bubbles: true }));
      const maxOk = await submit();
      setBoundary("min");
      form.elements.DistTemp.value = "1,5";
      form.dispatchEvent(new Event("input", { bubbles: true }));
      const commaOk = await submit();
      const commaBody = window.__numericRequests.at(-1).body;
      const commaSent = commaBody.some(entry => entry[0] === "DistTemp" && entry[1] === "1.5");
      const invalid = ["", "garbage", "NaN", "Inf", "1e999", "1e-40", "-1", "151"];
      const beforeInvalid = window.__numericRequests.length;
      for (const value of invalid) {
        setBoundary("min");
        form.elements.DistTemp.value = value;
        form.dispatchEvent(new Event("input", { bubbles: true }));
        await submit();
      }
      const invalidBlocked = window.__numericRequests.length === beforeInvalid;
      setBoundary("min");
      form.dispatchEvent(new Event("input", { bubbles: true }));
      window.__numericStatus = 400;
      const bad400 = await submit();
      const dirty400 = form.dataset.dirty === "true";
      window.__numericStatus = 503;
      const bad503 = await submit();
      const dirty503 = form.dataset.dirty === "true";
      return {
        count: window.__numericRequests.length, minOk, maxOk, commaOk, commaSent,
        invalidBlocked, bad400, bad503, dirty400, dirty503
      };
    });
    const state = await requestState();
    if (result.minOk !== false || result.maxOk !== false || result.commaOk !== false || !result.commaSent ||
        !result.invalidBlocked || result.bad400 !== false || result.bad503 !== false ||
        !result.dirty400 || !result.dirty503 || !state.errorVisible) {
      throw new Error("setup contract mismatch: " + JSON.stringify({ result, state }));
    }
  }

  async function testPowerPage(file) {
    await installRecorder("/command", "text");
    const result = await page.evaluate(async () => {
      const input = document.getElementById("Voltage");
      for (const value of ["0", "230", "1,5"]) {
        input.value = value;
        if (!(await sendvoltage())) throw new Error("valid power rejected: " + value);
      }
      const normalized = window.__numericRequests.at(-1).body === "voltage=1.5";
      const beforeInvalid = window.__numericRequests.length;
      for (const value of ["", "garbage", "NaN", "Inf", "1e999", "1e-40", "-1", "231"]) {
        input.value = value;
        await sendvoltage();
      }
      const invalidBlocked = window.__numericRequests.length === beforeInvalid;
      input.value = "1";
      window.__numericStatus = 400;
      const bad400 = await sendvoltage();
      window.__numericStatus = 503;
      const bad503 = await sendvoltage();
      window.__numericResponseText = "OK";
      window.__numericStatus = 400;
      const contradictory400 = await sendvoltage();
      window.__numericStatus = 503;
      const contradictory503 = await sendvoltage();
      return { normalized, invalidBlocked, bad400, bad503, contradictory400, contradictory503 };
    });
    const state = await requestState();
    if (!result.normalized || !result.invalidBlocked || result.bad400 !== false ||
        result.bad503 !== false || result.contradictory400 !== false ||
        result.contradictory503 !== false || !state.errorVisible) {
      throw new Error(file + " power contract mismatch: " + JSON.stringify({ result, state }));
    }
  }

  async function testIndexRate() {
    const result = await page.evaluate(async () => {
      window.__numericStatus = 200;
      const input = document.getElementById("pumpspeed");
      const before = window.__numericRequests.length;
      input.value = "0";
      await sendpumpspeed();
      input.value = "1,5";
      const ok = await sendpumpspeed();
      return {
        ok, delta: window.__numericRequests.length - before,
        body: window.__numericRequests.at(-1).body
      };
    });
    if (!result.ok || result.delta !== 1 || result.body !== "pumpspeed=1.5") {
      throw new Error("index pumpspeed mismatch: " + JSON.stringify(result));
    }
  }

  async function testWaterPwm(file) {
    await installRecorder("/command", "text");
    const result = await page.evaluate(async () => {
      const text = document.getElementById("PWMt");
      for (const value of ["0", "1023"]) {
        text.value = value;
        await changetxtpwm();
      }
      const boundsSent = window.__numericRequests.length === 2 &&
        window.__numericRequests[0].body === "watert=0" &&
        window.__numericRequests[1].body === "watert=1023";
      const before = window.__numericRequests.length;
      for (const value of ["", "garbage", "NaN", "Inf", "1e40", "-1", "1024", "1.5", "1,0"]) {
        text.value = value;
        await changetxtpwm();
      }
      return { boundsSent, invalidBlocked: window.__numericRequests.length === before };
    });
    if (!result.boundsSent || !result.invalidBlocked) {
      throw new Error(file + " PWM contract mismatch: " + JSON.stringify(result));
    }
  }

  async function testNbkRate() {
    const result = await page.evaluate(async () => {
      window.__numericStatus = 200;
      const input = document.getElementById("Set_speed");
      for (const value of ["0.001", "7999.999", "1,5"]) {
        input.value = value;
        await sendSpeed();
      }
      const normalized = window.__numericRequests.at(-1).body === "pnbk=1.5";
      const before = window.__numericRequests.length;
      for (const value of ["", "garbage", "NaN", "Inf", "1e-40", "0", "8000", "9000"]) {
        input.value = value;
        await sendSpeed();
      }
      return { normalized, invalidBlocked: window.__numericRequests.length === before };
    });
    if (!result.normalized || !result.invalidBlocked) {
      throw new Error("NBK rate mismatch: " + JSON.stringify(result));
    }
  }

  async function testProgram() {
    await installRecorder("/program", "program");
    const result = await page.evaluate(async () => {
      const form = document.getElementById("mainform");
      const volume = document.getElementById("vless");
      for (const value of ["0.001", "10000", "1,5"]) {
        volume.value = value;
        window.__numericStatus = 202;
        await SamovarApp.postProgram(form);
      }
      const last = window.__numericRequests.at(-1);
      const keys = last.body.map(entry => entry[0]);
      const allowlist = keys.every(key => ["WProgram", "vless", "Descr"].includes(key)) &&
        keys.includes("WProgram") && keys.includes("vless") &&
        last.body.some(entry => entry[0] === "vless" && entry[1] === "1.5");
      const before = window.__numericRequests.length;
      for (const value of ["", "garbage", "NaN", "Inf", "1e999", "1e-40", "0", "10000.1"]) {
        volume.value = value;
        await SamovarApp.postProgram(form);
      }
      const invalidBlocked = window.__numericRequests.length === before;
      volume.value = "1";
      window.__numericStatus = 400;
      const bad400 = await SamovarApp.postProgram(form);
      window.__numericStatus = 503;
      const bad503 = await SamovarApp.postProgram(form);
      const heater = document.getElementById("heaterMaxPower");
      return {
        allowlist, invalidBlocked, bad400: bad400.ok, bad503: bad503.ok,
        heaterValue: heater.value, heaterDisabled: heater.disabled
      };
    });
    const state = await requestState();
    if (!result.allowlist || !result.invalidBlocked || result.bad400 || result.bad503 ||
        result.heaterValue !== "4840" || result.heaterDisabled || !state.errorVisible) {
      throw new Error("program contract mismatch: " + JSON.stringify({ result, state }));
    }
  }

  async function testInvalidProgramHeater() {
    scenario = "program-invalid-heater";
    await page.goto(baseUrl + "/program_invalid.htm", { waitUntil: "load" });
    await page.waitForTimeout(100);
    const state = await page.evaluate(() => {
      const heater = document.getElementById("heaterMaxPower");
      const error = document.getElementById("request_error");
      return {
        value: heater.value,
        disabled: heater.disabled,
        errorVisible: !!error && getComputedStyle(error).display !== "none" && error.textContent.trim() !== "",
        resultsVisible: getComputedStyle(document.getElementById("columnParamsResults")).display !== "none"
      };
    });
    if (state.value !== "" || !state.disabled || !state.errorVisible || state.resultsVisible) {
      throw new Error("invalid heater did not fail closed: " + JSON.stringify(state));
    }
  }

  async function testCalibration() {
    await installRecorder("/calibrate", "calibrate");
    const result = await page.evaluate(async () => {
      const input = document.getElementById("kstepperspd");
      for (const value of ["1", "8000"]) {
        calibrationRunning = false;
        window.__numericStatus = 202;
        input.value = value;
        await calibrate();
      }
      const startMin = window.__numericRequests[0].url;
      const startMax = window.__numericRequests[1].url;
      const exactStart = startMin.includes("pump=local") && startMin.includes("stpstep=1") &&
        startMin.includes("start=1") && !startMin.includes("finish") &&
        startMax.includes("stpstep=8000") && startMax.includes("start=1");
      const before = window.__numericRequests.length;
      for (const value of ["", "garbage", "NaN", "Inf", "1e40", "0", "8001", "1.5", "1,0"]) {
        calibrationRunning = false;
        input.value = value;
        await calibrate();
      }
      const invalidBlocked = window.__numericRequests.length === before;
      calibrationRunning = false;
      input.value = "100";
      window.__numericStatus = 400;
      const bad400 = await calibrate();
      const state400 = calibrationRunning;
      const error400 = (() => {
        const node = document.getElementById("request_error");
        return !!node && getComputedStyle(node).display !== "none";
      })();
      window.__numericStatus = 503;
      const bad503 = await calibrate();
      const state503 = calibrationRunning;
      const error503 = (() => {
        const node = document.getElementById("request_error");
        return !!node && getComputedStyle(node).display !== "none";
      })();
      window.__numericStatus = 202;
      calibrationRunning = true;
      await calibrate();
      const finishUrl = window.__numericRequests.at(-1).url;
      calibrationRunning = false;
      calibrationPump = '';
      input.value = "250";
      window.__numericDelayMs = 80;
      const beforeConcurrent = window.__numericRequests.length;
      const firstStart = calibrate();
      const duringStart = {
        buttonDisabled: document.getElementById("calibrateid").disabled,
        pumpDisabled: document.getElementById("pump_type").disabled,
        speedDisabled: input.disabled
      };
      const duplicateStart = await calibrate();
      const firstStartResult = await firstStart;
      window.__numericDelayMs = 0;
      return {
        exactStart, invalidBlocked, bad400, bad503, state400, state503, error400, error503,
        exactFinish: finishUrl.includes("finish=1") && !finishUrl.includes("stpstep") && !finishUrl.includes("start"),
        operationRequests: window.__numericOperationRequests.slice(),
        calibratedValue: document.getElementById("stepperstepml").value,
        concurrentStartSerialized: firstStartResult === true && duplicateStart === false &&
          window.__numericRequests.length === beforeConcurrent + 1,
        duringStart
      };
    });
    if (!result.exactStart || !result.invalidBlocked || result.bad400 !== false ||
        result.bad503 !== false || result.state400 || result.state503 ||
        !result.error400 || !result.error503 || !result.exactFinish ||
        result.operationRequests.length !== 4 ||
        !result.operationRequests.every(url => url === "/ajax?operationId=901") ||
        result.calibratedValue !== "11100" ||
        !result.concurrentStartSerialized || !result.duringStart.buttonDisabled ||
        !result.duringStart.pumpDisabled || !result.duringStart.speedDisabled) {
      throw new Error("calibration contract mismatch: " + JSON.stringify(result));
    }
  }

  async function testHydratedCalibration() {
    scenario = "calibrate-server-hydrated";
    await page.goto(baseUrl + "/calibrate_running.htm", { waitUntil: "load" });
    await installRecorder("/calibrate", "calibrate");
    const result = await page.evaluate(async () => {
      const button = document.getElementById("calibrateid");
      const pump = document.getElementById("pump_type");
      const speed = document.getElementById("kstepperspd");
      const hydrated = calibrationRunning && calibrationPump === "i2c" &&
        button.value === "Зафиксировать 100 мл" && button.disabled === false &&
        pump.value === "i2c" && pump.disabled && speed.disabled;
      pump.value = "local";
      onPumpTypeChange();
      const lockedToServerPump = pump.value === "i2c";
      window.__numericDelayMs = 80;
      const firstFinish = calibrate();
      const duringFinish = button.disabled && pump.disabled && speed.disabled;
      const duplicateFinish = await calibrate();
      const firstFinishResult = await firstFinish;
      const finishUrl = window.__numericRequests[0] && window.__numericRequests[0].url;
      return {
        hydrated, lockedToServerPump, duringFinish, duplicateFinish, firstFinishResult,
        requestCount: window.__numericRequests.length,
        operationRequests: window.__numericOperationRequests.slice(),
        exactFinish: finishUrl === "/calibrate?pump=i2c&finish=1",
        finished: !calibrationRunning && calibrationPump === "" &&
          button.value === "Начать калибровку" && !button.disabled &&
          !pump.disabled && !speed.disabled,
        calibratedValue: document.getElementById("stepperstepml").value
      };
    });
    if (!result.hydrated || !result.lockedToServerPump || !result.duringFinish ||
        result.duplicateFinish !== false || result.firstFinishResult !== true ||
        result.requestCount !== 1 || result.operationRequests.length !== 1 ||
        result.operationRequests[0] !== "/ajax?operationId=901" ||
        !result.exactFinish || !result.finished || result.calibratedValue !== "10000") {
      throw new Error("hydrated calibration contract mismatch: " + JSON.stringify(result));
    }
  }

  async function testI2cStepper() {
    await installRecorder("/i2cstepper", "json");
    const result = await page.evaluate(async fixture => {
      function setFields(value) {
        ["pumpMlHour", "pumpPauseSec", "fillingMl", "fillingMlHour"].forEach(id => {
          document.getElementById(id).value = String(value);
        });
        document.getElementById("stepsPerMl").value = String(value === 0 ? 1 : value);
        document.getElementById("pumpMode").value = "3";
        document.getElementById("pump_relayMask").value = "0";
        markDirty("pump");
      }
      function mutationRequests() {
        return window.__numericRequests.filter(request => request.url.includes("&cmd="));
      }
      function readbackCount(device) {
        return window.__numericRequests.filter(
          request => request.url === "/i2cstepper?device=" + device
        ).length;
      }
      async function waitMutationCount(count) {
        const deadline = Date.now() + 1000;
        while (mutationRequests().length < count && Date.now() < deadline) {
          await new Promise(resolve => setTimeout(resolve, 10));
        }
      }
      async function waitDeviceIdle(device, timeoutMs) {
        const deadline = Date.now() + (timeoutMs || 1000);
        while (deviceActionInFlight(device) && Date.now() < deadline) {
          await new Promise(resolve => setTimeout(resolve, 10));
        }
        return !deviceActionInFlight(device);
      }
      setFields(0);
      let expected = mutationRequests().length + 1;
      sendDevice("pump", "apply");
      await waitMutationCount(expected);
      await waitDeviceIdle("pump");
      setFields(65535);
      expected++;
      sendDevice("pump", "apply");
      await waitMutationCount(expected);
      await waitDeviceIdle("pump");
      expected++;
      sendDevice("pump", "stop");
      await waitMutationCount(expected);
      await waitDeviceIdle("pump");
      const stop = mutationRequests().at(-1).url;
      expected++;
      sendDevice("pump", "calfinish");
      await waitMutationCount(expected);
      await waitDeviceIdle("pump");
      const finish = mutationRequests().at(-1).url;
      const exactStop = stop === "/i2cstepper?device=pump&cmd=stop";
      const exactFinish = finish === "/i2cstepper?device=pump&cmd=calfinish";
      const initialOperationContract = window.__numericOperationRequests.length === 4 &&
        window.__numericOperationRequests.every(url => url === "/ajax?operationId=901") &&
        readbackCount("pump") === 4;
      const beforeInvalid = mutationRequests().length;
      setFields(1);
      document.getElementById("stepsPerMl").value = "";
      const invalidReturn = sendDevice("pump", "apply");
      const invalidBlocked = mutationRequests().length === beforeInvalid && invalidReturn === false &&
        !actionInFlight("pump", "apply");
      setFields(100);
      window.__numericStatus = 400;
      expected = mutationRequests().length + 1;
      sendDevice("pump", "apply");
      await waitMutationCount(expected);
      await waitDeviceIdle("pump");
      const dirty400 = dirtyDevices.pump && document.getElementById("pump_panel").style.display === "block";
      window.__numericStatus = 503;
      expected++;
      sendDevice("pump", "apply");
      await waitMutationCount(expected);
      await waitDeviceIdle("pump");
      const dirty503 = dirtyDevices.pump && document.getElementById("pump_panel").style.display === "block";
      const httpErrorsVisible = (() => {
        const node = document.getElementById("request_error");
        return !!node && getComputedStyle(node).display !== "none" && node.textContent.trim() !== "";
      })();

      window.__numericStatus = 202;
      window.__numericDelayMs = 80;
      setFields(222);
      const beforeSerialized = mutationRequests().length;
      const beforeSerializedOperations = window.__numericOperationRequests.length;
      const beforePumpReadbacks = readbackCount("pump");
      const beforeMixerReadbacks = readbackCount("mixer");
      const pumpAccepted = sendDevice("pump", "apply");
      const pumpSaveBlocked = sendDevice("pump", "save") === false;
      const pumpRelayBlocked = toggleRelay("pump", 1) === false;
      const mixerParallel = sendDevice("mixer", "apply");
      const pumpButtonsLocked = [
        "pump_apply", "pump_run_toggle", "pump_save", "pump_calstart",
        "pump_calfinish", "pumpRelay1", "pumpRelay2", "pumpRelay3", "pumpRelay4"
      ].every(id => document.getElementById(id).disabled);
      renderPolledDevice("pump", Object.assign({}, fixture, {
        pumpMlHour: 100, fillingMl: 100, fillingMlHour: 100,
        stepsPerMl: 100, relayMask: 0
      }));
      const staleDuringRequestPreserved = dirtyDevices.pump &&
        document.getElementById("pumpMlHour").value === "222" &&
        document.getElementById("pump_relayMask").value === "0";
      await waitDeviceIdle("pump");
      await waitDeviceIdle("mixer");
      const perDeviceSerialized = pumpAccepted && pumpSaveBlocked && pumpRelayBlocked &&
        mixerParallel && mutationRequests().length === beforeSerialized + 2 &&
        window.__numericOperationRequests.length === beforeSerializedOperations + 2 &&
        readbackCount("pump") === beforePumpReadbacks + 1 &&
        readbackCount("mixer") === beforeMixerReadbacks + 1;
      renderPolledDevice("pump", Object.assign({}, fixture, {
        pumpMlHour: 100, fillingMl: 100, fillingMlHour: 100,
        stepsPerMl: 100, relayMask: 0
      }));
      const staleAfterAcceptPreserved = dirtyDevices.pump &&
        document.getElementById("pumpMlHour").value === "222" &&
        document.getElementById("pump_relayMask").value === "0";
      renderPolledDevice("pump", Object.assign({}, fixture, {
        mode: 3, pumpMlHour: 222, pumpPauseSec: 222, fillingMl: 222,
        fillingMlHour: 222, stepsPerMl: 222, relayMask: 0,
        optionFlags: 0, sensorFlags: 0
      }));
      const matchingPollCleared = !dirtyDevices.pump && pendingDeviceConfig.pump === null;

      setFields(333);
      window.__numericDelayMs = 0;
      sendDevice("pump", "apply");
      await waitDeviceIdle("pump");
      document.getElementById("fillingMl").value = "444";
      document.getElementById("fillingMl").dispatchEvent(new Event("input", { bubbles: true }));
      renderPolledDevice("pump", Object.assign({}, fixture, {
        mode: 3, pumpMlHour: 333, pumpPauseSec: 333, fillingMl: 333,
        fillingMlHour: 333, stepsPerMl: 333, relayMask: 0,
        optionFlags: 0, sensorFlags: 0
      }));
      const editAfterAcceptPreserved = dirtyDevices.pump && pendingDeviceConfig.pump === null &&
        document.getElementById("fillingMl").value === "444";

      setFields(444);
      sendDevice("pump", "calstart");
      await waitDeviceIdle("pump");
      renderPolledDevice("pump", Object.assign({}, fixture, {
        mode: 3, pumpMlHour: 100, pumpPauseSec: 10, fillingMl: 100,
        fillingMlHour: 444, stepsPerMl: 444, relayMask: 0,
        optionFlags: 0, sensorFlags: 0
      }));
      const partialCalstartPreserved = dirtyDevices.pump && pendingDeviceConfig.pump === null &&
        document.getElementById("pumpPauseSec").value === "444";

      const relayAccepted = toggleRelay("pump", 1);
      await waitDeviceIdle("pump");
      renderPolledDevice("pump", Object.assign({}, fixture, {
        mode: 3, pumpMlHour: 100, pumpPauseSec: 10, fillingMl: 100,
        fillingMlHour: 444, stepsPerMl: 444, relayMask: 1,
        optionFlags: 0, sensorFlags: 0
      }));
      const applyAfterRelay = deviceUrl("pump", "apply");
      const authoritativeRelayPreserved = relayAccepted && dirtyDevices.pump &&
        document.getElementById("pumpPauseSec").value === "444" &&
        document.getElementById("pump_relayMask").value === "1" &&
        document.getElementById("pumpRelay1").classList.contains("state-on") &&
        new URLSearchParams(applyAfterRelay.split("?")[1]).get("relayMask") === "1";

      SamovarApp.clearRequestError();
      i2cRequestErrorOwner = null;
      window.__numericPlans = [
        { status: 400, delayMs: 20 },
        { status: 202, delayMs: 80 }
      ];
      const pumpErrorStarted = sendDevice("pump", "apply");
      const mixerSuccessStarted = sendDevice("mixer", "apply");
      await waitDeviceIdle("pump");
      await waitDeviceIdle("mixer");
      const mixedErrorNode = document.getElementById("request_error");
      const mixedErrorPreserved = pumpErrorStarted && mixerSuccessStarted &&
        i2cRequestErrorOwner === "pump" && mixedErrorNode &&
        getComputedStyle(mixedErrorNode).display !== "none" &&
        mixedErrorNode.textContent.includes("HTTP 400");

      const recordedFetch = window.fetch;
      window.fetch = function(url, options) {
        const raw = typeof url === "string" ? url : url.url;
        if (!raw.startsWith("/i2cstepper?device=pump&cmd=apply")) {
          return recordedFetch(url, options);
        }
        return Promise.resolve({
          ok: true,
          json: function() {
            return new Promise(function(resolve, reject) {
              options.signal.addEventListener("abort", function() {
                reject(new DOMException("body timeout", "AbortError"));
              }, { once: true });
            });
          }
        });
      };
      setFields(555);
      const timeoutStartedAt = Date.now();
      const hangingBodyAccepted = sendDevice("pump", "apply");
      const bodyTimeoutReleased = await waitDeviceIdle("pump", 5500);
      const timeoutElapsed = Date.now() - timeoutStartedAt;
      const bodyTimeoutError = document.getElementById("request_error");
      const bodyTimeoutHandled = hangingBodyAccepted && bodyTimeoutReleased &&
        timeoutElapsed >= 3500 && timeoutElapsed < 5500 &&
        !deviceActionInFlight("pump") && bodyTimeoutError &&
        getComputedStyle(bodyTimeoutError).display !== "none";
      return {
        exactStop, exactFinish, initialOperationContract, invalidBlocked,
        dirty400, dirty503, httpErrorsVisible,
        pumpButtonsLocked, staleDuringRequestPreserved, perDeviceSerialized,
        staleAfterAcceptPreserved, matchingPollCleared, editAfterAcceptPreserved,
        partialCalstartPreserved, authoritativeRelayPreserved, mixedErrorPreserved,
        bodyTimeoutHandled
      };
    }, i2cFixtures.pump);
    const state = await requestState();
    if (!result.exactStop || !result.exactFinish || !result.initialOperationContract ||
        !result.invalidBlocked ||
        !result.dirty400 || !result.dirty503 || !result.pumpButtonsLocked ||
        !result.staleDuringRequestPreserved || !result.perDeviceSerialized ||
        !result.staleAfterAcceptPreserved || !result.matchingPollCleared ||
        !result.editAfterAcceptPreserved || !result.partialCalstartPreserved ||
        !result.authoritativeRelayPreserved || !result.mixedErrorPreserved ||
        !result.bodyTimeoutHandled || !result.httpErrorsVisible) {
      throw new Error("I2CStepper contract mismatch: " + JSON.stringify({ result, state }));
    }
  }

  const testedContracts = new Set();
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const theme of themes) {
      await setOriginTheme(theme);
      for (const file of pages) {
        scenario = viewport.name + "/" + theme + "/" + file;
        await page.goto(baseUrl + "/" + file, { waitUntil: "load" });
        if (file === "program.htm") await page.waitForTimeout(100);
        if (file === "i2cstepper.htm") await stopI2cPolling();
        const appliedTheme = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
        if (appliedTheme !== theme) throw new Error(scenario + " theme=" + appliedTheme);
        await verifySharedValidator(scenario);
        covered.push(scenario);

        if (testedContracts.has(file)) continue;
        testedContracts.add(file);
        if (file === "setup.htm") await testSetup();
        else if (["index.htm", "beer.htm", "bk.htm", "distiller.htm", "nbk.htm"].includes(file)) {
          await testPowerPage(file);
          if (file === "index.htm") await testIndexRate();
          if (file === "beer.htm" || file === "bk.htm") await testWaterPwm(file);
          if (file === "nbk.htm") await testNbkRate();
        } else if (file === "program.htm") await testProgram();
        else if (file === "calibrate.htm") await testCalibration();
        else if (file === "i2cstepper.htm") await testI2cStepper();
      }
    }
  }

  await testInvalidProgramHeater();
  await testHydratedCalibration();
  await page.unrouteAll({ behavior: "ignoreErrors" });
  if (covered.length !== 36) throw new Error("expected 36 page checks, got " + covered.length);
  if (lifecycleEvents.length) throw new Error(lifecycleEvents.join("\n"));
  if (consoleProblems.length) throw new Error(consoleProblems.join("\n"));
  return { covered: covered.length, pageContracts: testedContracts.size };
}'''


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def render_site(target: Path, color_tokens: dict[str, str] | None = None) -> None:
    shutil.copytree(DATA, target, dirs_exist_ok=True)
    color_tokens = color_tokens or {}
    replacements = {
        "pwr_unit": "V",
        "pwr_unit_v_only": "block",
        "HeaterMaxPower": "230.000000000",
        "HeaterR": "10.000000000",
        "StepperStep": "100",
        "StepperStepMl": "100",
        "StepperStepMlI2C": "100",
        "CalibrationRunning": "0",
        "CalibrationPump": "local",
        "I2CPumpTab": "inline-block",
        "I2CStepperTab": "inline-block",
        "btn_list": '""',
        "WProgram": "",
        "Descr": "",
        "ColDiam": "2.0",
        "ColHeight": "1.0",
        "PackDens": "80",
        "v": "test",
    }
    empty_markers = {
        "RECT", "DIST", "BEER", "BK", "NBK", "SUVID", "LUA_MODE",
        "Checked", "FLChecked", "UASChecked", "UASHeadsChecked", "CPBuzz",
        "CUBuzz", "CUBBuzz", "UseWS", "UseST", "ChckPwr", "IgnFL",
    }
    address_tokens = {"SteamAddr", "PipeAddr", "WaterAddr", "TankAddr", "ACPAddr"}
    token_pattern = re.compile(r"%([A-Za-z0-9_.]+)%")

    def replace_token(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in replacements:
            return replacements[name]
        if name in address_tokens:
            return '<option value="-1" selected>-</option>'
        if name in empty_markers or name.startswith(("ColDiam_", "ColHeight_")):
            return ""
        if name.endswith("Color"):
            return color_tokens.get(name, "#000000")
        return "0"

    for path in target.glob("*.htm"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        path.write_text(token_pattern.sub(replace_token, text), encoding="utf-8")

    program = target / "program.htm"
    invalid = target / "program_invalid.htm"
    invalid.write_text(
        program.read_text(encoding="utf-8").replace(
            "var heaterResistance = Number('10.000000000');",
            "var heaterResistance = Number('NaN');",
            1,
        ),
        encoding="utf-8",
    )
    calibrate = target / "calibrate.htm"
    running = target / "calibrate_running.htm"
    running.write_text(
        calibrate.read_text(encoding="utf-8")
        .replace("Number('0') === 1", "Number('1') === 1", 1)
        .replace("calibrationRunning ? 'local' : ''", "calibrationRunning ? 'i2c' : ''", 1),
        encoding="utf-8",
    )


def run_cli(cli: str, session: str, arguments: list[str], cwd: Path, timeout: int, check: bool = True) -> int:
    result = subprocess.run(
        [cli, f"-s={session}", *arguments],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if check and (result.returncode != 0 or "### Error" in result.stdout):
        raise RuntimeError(f"playwright-cli {' '.join(arguments[:1])} failed")
    return result.returncode


def cleanup(cli: str, session: str, server: http.server.ThreadingHTTPServer, thread: threading.Thread) -> list[str]:
    errors = []
    try:
        if run_cli(cli, session, ["close"], ROOT, 30, check=False) != 0:
            errors.append("playwright-cli close failed")
    except (OSError, subprocess.TimeoutExpired) as error:
        errors.append(f"playwright-cli close failed: {error}")
    try:
        server.shutdown()
        server.server_close()
    except OSError as error:
        errors.append(f"HTTP server cleanup failed: {error}")
    thread.join(timeout=5)
    if thread.is_alive():
        errors.append("HTTP server thread did not stop")
    return errors


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the numeric input browser gate", file=sys.stderr)
        return 2

    primary_error = None
    cleanup_errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="samovar-numeric-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-numeric-ui-{os.getpid()}"
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
            run_cli(cli, session, ["run-code", code], temp, 240)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Numeric input UI browser gate failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Numeric input UI browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Numeric input UI browser gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
