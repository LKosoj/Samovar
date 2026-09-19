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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web_assets import resolve_includes


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"

UI_BOOTSTRAP_FIXTURE = {
    "mode": 0,
    "version": "test",
    "powerUnit": "V",
    "program": "",
    "description": "",
    "luaButtonList": "",
    "steamColor": "#000000",
    "pipeColor": "#000000",
    "waterColor": "#000000",
    "tankColor": "#000000",
    "acpColor": "#000000",
    "steamVisible": True,
    "pipeVisible": True,
    "waterVisible": True,
    "tankVisible": True,
    "pressureVisible": True,
    "programNumberVisible": True,
    "i2cStepperVisible": True,
    "i2cPumpVisible": True,
    "beerBrewOrder": "allinone",
    "pwmLow": 0,
    "pwmValue": 0,
    "nbkDp": 0,
    "columnDiameter": 2,
    "columnHeight": 1,
    "packDensity": 80,
    "heaterResistance": 10,
    "mainsVoltage": 230,
    "heaterMaxPower": 230,
    "stepperMaxSpeed": 1000,
    "stepperStepsPerMl": 100,
    "i2cSteppers": [{"address": 2, "present": True}, *({} for _ in range(9))],
    "calibrationRunning": False,
    "processRunning": False,
    "calibrationPump": "local",
    "cheesePhSlope": 1,
    "cheesePhOffset": 0, "cheeseCoolingScheme": "pump",
    "cheesePhAvailable": True, "cheesePhAds1115Address": 0,
}

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
    i2c_pump_speed: 0, PowerOn: 0, StepperStepMl: 111,
    heaterAlarmLatched: 0, heaterAlarmReason: '', latestMessageSequence: 0,
    BeerBrewOrder: "allinone"
  };
  const columnFixture = {
    floodPowerW: 3000, workingPowerW: 2500, maxFlowMlH: 1000,
    theoreticalPlates: 20, headsFlowMlH: 100, bodyFlowMinMlH: 200,
    bodyFlowMaxMlH: 400, bodyEndFlowMlH: 300, tailsFlowMlH: 150,
    headsPowerW: 1800, bodyEndPowerW: 2200, tailsPowerW: 2000,
    headsSpeedClamped: false, bodySpeedClamped: false
  };
  const i2cDevice = {
    address: 2, present: true, capabilities: 12,
    config: {relayMask: 0, stepsPerMl: 43200}, motion: {speedStepsPerSec: 1200, targetSteps: 100},
    status: {flags: 0, currentSpeedStepsPerSec: 0, remainingSteps: 0}
  };
  const i2cPayload = {devices:[i2cDevice], selected:i2cDevice};
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
  // program.htm (T3) при каждой загрузке дергает /cheese-recipes-bootstrap для карточки
  // "Рецепты пива с сайта"; эти тесты её не касаются - отдаём mode:1, чтобы карточка
  // осталась скрытой и не было 404 в консоли.
  await page.route("**/cheese-recipes-bootstrap", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({mode: 1})
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
  await page.route("**/i2cstepper?address=2", route => fulfillI2cRoute(route, i2cPayload));

  async function stopI2cPolling() {
    try {
      await page.waitForFunction(() =>
        typeof refreshTimer !== "undefined" && selected && selected.present &&
        document.getElementById("panel").hidden === false
      );
    } catch (error) {
      throw new Error("selected I2C startup " + JSON.stringify(await page.evaluate(() => ({
        selectedAddress:typeof selectedAddress === "undefined" ? null : selectedAddress,
        devices:typeof devices === "undefined" ? null : devices,
        selected:typeof selected === "undefined" ? null : selected,
        panel:document.getElementById("panel")?.hidden,
        error:document.getElementById("request_error")?.textContent || ""
      }))));
    }
    await page.evaluate(() => {
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = 0;
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
      const packDensityControl = form.elements.PackDens;
      const packDensityRangeOk = packDensityControl.min === "0" && packDensityControl.max === "100";
      const packDensityMinValue = packDensityControl.value;
      form.dispatchEvent(new Event("input", { bubbles: true }));
      const minOk = await submit();
      const packDensityZeroSent = window.__numericRequests.at(-1).body.some(
        entry => entry[0] === "PackDens" && entry[1] === "0"
      );
      setBoundary("max");
      form.dispatchEvent(new Event("input", { bubbles: true }));
      const maxOk = await submit();
      setBoundary("min");
      form.elements.DistTemp.value = "30,5";
      form.dispatchEvent(new Event("input", { bubbles: true }));
      const commaOk = await submit();
      const commaBody = window.__numericRequests.at(-1).body;
      const commaSent = commaBody.some(entry => entry[0] === "DistTemp" && entry[1] === "30.5");
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
      // Оставленный "грязным" (dirty) после намеренно проваленных сохранений
      // выше form.dataset - это и есть проверяемое поведение (см. dirty400/
      // dirty503 в assert ниже). Но если его не сбросить сейчас, следующий
      // page.goto() в главном цикле теста наткнётся на нативный диалог
      // beforeunload (см. setup.htm) и тест зависнет на незакрытом диалоге.
      // Сама проверка WP23 (что beforeunload вообще срабатывает) - в
      // test_setup_guards_browser.py, здесь её ослаблять не нужно.
      form.dataset.dirty = "false";
      return {
        count: window.__numericRequests.length, minOk, maxOk, commaOk, commaSent,
        invalidBlocked, bad400, bad503, dirty400, dirty503,
        packDensityRangeOk, packDensityMinValue, packDensityZeroSent
      };
    });
    const state = await requestState();
    if (result.minOk !== false || result.maxOk !== false || result.commaOk !== false || !result.commaSent ||
        !result.invalidBlocked || result.bad400 !== false || result.bad503 !== false ||
        !result.dirty400 || !result.dirty503 || !result.packDensityRangeOk ||
        result.packDensityMinValue !== "0" || !result.packDensityZeroSent || !state.errorVisible) {
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
      const summaryText = id => document.getElementById(id).textContent.trim();
      const initialSummary = {
        headsAs: summaryText("summaryHeadsAs"),
        headsVolume: summaryText("summaryHeadsVolume"),
        headsTime: summaryText("summaryHeadsTime"),
        headsDistribution: summaryText("summaryHeadsDistribution"),
        bodyAs: summaryText("summaryBodyAs"),
        bodyVolume: summaryText("summaryBodyVolume"),
        bodyTime: summaryText("summaryBodyTime"),
        bodyDistribution: summaryText("summaryBodyDistribution"),
        tailsAs: summaryText("summaryTailsAs"),
        tailsVolume: summaryText("summaryTailsVolume"),
        tailsTime: summaryText("summaryTailsTime"),
        tailsDistribution: summaryText("summaryTailsDistribution"),
        totalVolume: summaryText("summaryTotalVolume"),
        totalTime: summaryText("summaryTotalTime"),
        pauseTime: summaryText("summaryPauseTime"),
        valid: !programerr
      };
      const firstHeadsPercent = document.getElementById("percent0");
      firstHeadsPercent.value = "20";
      firstHeadsPercent.dispatchEvent(new Event("input", { bubbles: true }));
      const headsShort = {
        distribution: summaryText("summaryHeadsDistribution"),
        volume: summaryText("summaryHeadsVolume"),
        invalid: programerr,
        error: programErrorMessage
      };
      const firstBodyRow = Array.from(document.querySelectorAll(".prgline")).find(row => {
        const type = row.querySelector('select[name^="ptype"]');
        return type && type.value === "B";
      });
      const firstBodyPercent = firstBodyRow.querySelector('input[name^="percent"]');
      firstBodyPercent.value = String(Number(firstBodyPercent.value) + 5);
      firstBodyPercent.dispatchEvent(new Event("input", { bubbles: true }));
      const bothInvalid = {
        bodyDistribution: summaryText("summaryBodyDistribution"),
        error: programErrorMessage
      };
      firstHeadsPercent.value = "30";
      firstHeadsPercent.dispatchEvent(new Event("input", { bubbles: true }));
      firstBodyPercent.value = String(Number(firstBodyPercent.value) - 5);
      firstBodyPercent.dispatchEvent(new Event("input", { bubbles: true }));
      const restored = !programerr;
      const headsAsInput = document.getElementById("vlhp");
      headsAsInput.value = "9";
      headsAsInput.dispatchEvent(new Event("input", { bubbles: true }));
      const immediateHeadsUpdate = {
        percent: summaryText("summaryHeadsAs"),
        volume: summaryText("summaryHeadsVolume")
      };
      headsAsInput.value = "8";
      headsAsInput.dispatchEvent(new Event("input", { bubbles: true }));
      // Объём сырца нужен только калькулятору страницы: в /program он не уходит,
      // но кнопка «Установить» (set_program) с негодным объёмом запрос не шлёт.
      window.__numericStatus = 202;
      await SamovarApp.postProgram(form);
      const last = window.__numericRequests.at(-1);
      const keys = last.body.map(entry => entry[0]);
      const allowlist = keys.every(key => ["WProgram", "Descr"].includes(key)) &&
        keys.includes("WProgram");
      const before = window.__numericRequests.length;
      for (const value of ["", "garbage", "NaN", "Inf", "1e999", "1e-40", "0", "10000.1"]) {
        volume.value = value;
        await set_program();
      }
      const invalidBlocked = window.__numericRequests.length === before;
      volume.value = "1";
      // [T27.3] Байтовый лимит Descr на клиенте: <textarea maxlength='250'> считает
      // СИМВОЛЫ, а кириллица в UTF-8 - 2 байта на символ, поэтому 250 введённых
      // символов браузер пропускает, а сервер (web_program(), String::length() в
      // Arduino - это байты) отбивает как 500 байт. postProgram() должен сам
      // посчитать РЕАЛЬНЫЕ байты (TextEncoder) и не пустить запрос на сервер.
      // program.htm - тестовая страница без поля Descr (в отличие от index/beer/
      // distiller/nbk.htm), поэтому поле создаётся здесь же, как numeric-browser-probe.
      let descrField = form.querySelector('[name="Descr"]');
      const descrCreated = !descrField;
      if (!descrField) {
        descrField = document.createElement("textarea");
        descrField.name = "Descr";
        form.appendChild(descrField);
      }
      descrField.value = "И".repeat(130); // 130 символов = 260 байт UTF-8 - за лимитом 250 байт
      const beforeDescr = window.__numericRequests.length;
      window.__numericStatus = 202;
      const descrOverflowResult = await SamovarApp.postProgram(form);
      const descrBlocked = window.__numericRequests.length === beforeDescr && descrOverflowResult.ok === false;
      const descrErrorText = document.getElementById("request_error").textContent;
      descrField.value = "И".repeat(125); // 125 символов = 250 байт - ровно на границе, разрешено
      const descrWithinLimitResult = await SamovarApp.postProgram(form);
      const descrWithinLimitSent = window.__numericRequests.length === beforeDescr + 1 &&
        descrWithinLimitResult.ok === true;
      if (descrCreated) descrField.remove();
      window.__numericStatus = 400;
      const bad400 = await SamovarApp.postProgram(form);
      window.__numericStatus = 503;
      const bad503 = await SamovarApp.postProgram(form);
      const heater = document.getElementById("heaterMaxPower");
      return {
        initialSummary, headsShort, bothInvalid, restored, immediateHeadsUpdate,
        allowlist, invalidBlocked, bad400: bad400.ok, bad503: bad503.ok,
        descrBlocked, descrErrorText, descrWithinLimitSent,
        heaterValue: heater.value, heaterDisabled: heater.disabled
      };
    });
    const state = await requestState();
    // Времена посчитаны по исходным скоростям шаблона. Рекомендации колонны
    // применяются только по явному нажатию кнопки и не меняют загруженную
    // программу автоматически.
    // \u00a0 - неразрывный пробел: сводка склеивает число с единицей именно им,
    // иначе на телефоне "мин" уезжает на следующую строку.
    const expectedSummary = {
      headsAs: "8%", headsVolume: "354\u00a0мл", headsTime: "2\u00a0ч\u00a054\u00a0мин",
      headsDistribution: "По строкам: 100% — распределено полностью",
      bodyAs: "87%", bodyVolume: "3855\u00a0мл", bodyTime: "4\u00a0ч\u00a002\u00a0мин",
      bodyDistribution: "По строкам B+C: 100% — распределено полностью",
      tailsAs: "5%", tailsVolume: "88\u00a0мл", tailsTime: "0\u00a0ч\u00a039\u00a0мин",
      tailsDistribution: "По строкам: 20% — информационно",
      totalVolume: "4297\u00a0мл", totalTime: "7\u00a0ч\u00a047\u00a0мин", pauseTime: "0\u00a0ч\u00a011\u00a0мин",
      valid: true
    };
    if (JSON.stringify(result.initialSummary) !== JSON.stringify(expectedSummary) ||
        result.headsShort.distribution !== "По строкам: 90% — не хватает 10%" ||
        result.headsShort.volume !== "319\u00a0мл" || !result.headsShort.invalid ||
        !result.headsShort.error.includes("Головы: 90% — не хватает 10%") ||
        result.bothInvalid.bodyDistribution !== "По строкам B+C: 105% — превышение на 5%" ||
        !result.bothInvalid.error.includes("Головы: 90% — не хватает 10%") ||
        !result.bothInvalid.error.includes("Тело B+C: 105% — превышение на 5%") ||
        !result.restored || result.immediateHeadsUpdate.percent !== "9%" ||
        result.immediateHeadsUpdate.volume !== "400\u00a0мл" ||
        !result.allowlist || !result.invalidBlocked || result.bad400 || result.bad503 ||
        !result.descrBlocked || !result.descrErrorText.includes("250") || !result.descrWithinLimitSent ||
        result.heaterValue !== "5290" || result.heaterDisabled || !state.errorVisible) {
      throw new Error("program contract mismatch: " + JSON.stringify({ result, state }));
    }
  }

  async function testInvalidProgramHeater() {
    scenario = "program-invalid-heater";
    const bootstrapPattern = "**/ui-bootstrap";
    await page.route(bootstrapPattern, async route => {
      const response = await route.fetch();
      const body = await response.json();
      body.heaterResistance = 1;
      await route.fulfill({response, json:body});
    });
    await page.goto(baseUrl + "/program.htm", { waitUntil: "load" });
    await page.waitForFunction(() => document.body.inert === false);
    await page.unroute(bootstrapPattern);
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
      input.value = "250";
      window.__numericDelayMs = 80;
      const beforeConcurrent = window.__numericRequests.length;
      const firstStart = calibrate();
      const duringStart = {
        buttonDisabled: document.getElementById("calibrateid").disabled,
        speedDisabled: input.disabled,
        saveDisabled: document.getElementById("save").disabled
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
        !result.duringStart.saveDisabled || !result.duringStart.speedDisabled) {
      throw new Error("calibration contract mismatch: " + JSON.stringify(result));
    }
  }

  async function testHydratedCalibration() {
    scenario = "calibrate-server-hydrated";
    const bootstrapPattern = "**/ui-bootstrap";
    await page.route(bootstrapPattern, async route => {
      const response = await route.fetch();
      const body = await response.json();
      body.calibrationRunning = true;
      await route.fulfill({response, json:body});
    });
    await page.goto(baseUrl + "/calibrate.htm", { waitUntil: "load" });
    await page.waitForFunction(() => document.body.inert === false);
    await page.unroute(bootstrapPattern);
    await installRecorder("/calibrate", "calibrate");
    const result = await page.evaluate(async () => {
      const button = document.getElementById("calibrateid");
      const speed = document.getElementById("kstepperspd");
      const save = document.getElementById("save");
      const hydrated = calibrationRunning && externalAddress === 0 && localStepsPerMl === 100 &&
        button.value === "Зафиксировать 100 мл" && button.disabled === false &&
        save.disabled && speed.disabled;
      window.__numericDelayMs = 80;
      const firstFinish = calibrate();
      const duringFinish = button.disabled && save.disabled && speed.disabled;
      const duplicateFinish = await calibrate();
      const firstFinishResult = await firstFinish;
      const finishUrl = window.__numericRequests[0] && window.__numericRequests[0].url;
      return {
        hydrated, duringFinish, duplicateFinish, firstFinishResult,
        requestCount: window.__numericRequests.length,
        operationRequests: window.__numericOperationRequests.slice(),
        exactFinish: finishUrl === "/calibrate?pump=local&finish=1",
        finished: !calibrationRunning && externalAddress === 0 &&
          button.value === "Начать калибровку" && !button.disabled &&
          !save.disabled && !speed.disabled,
        calibratedValue: document.getElementById("stepperstepml").value
      };
    });
    if (!result.hydrated || !result.duringFinish ||
        result.duplicateFinish !== false || result.firstFinishResult !== true ||
        result.requestCount !== 1 || result.operationRequests.length !== 1 ||
        result.operationRequests[0] !== "/ajax?operationId=901" ||
        !result.exactFinish || !result.finished || result.calibratedValue !== "11100") {
      throw new Error("hydrated calibration contract mismatch: " + JSON.stringify(result));
    }
  }

  async function testExternalCalibration() {
    scenario = "calibrate-external-address";
    await page.goto(baseUrl + "/calibrate.htm?address=2", { waitUntil: "load" });
    await page.waitForFunction(() => externalAddress === 2 && externalStepsPerMl === 43200);
    const result = await page.evaluate(() => ({
      title:document.getElementById("title").textContent,
      address:externalAddress, steps:externalStepsPerMl,
      displayed:document.getElementById("stepperstepml").value,
      save:document.getElementById("save"),
      returnUrl:String(document.getElementById("return").onclick)
    }));
    if (result.title !== "Калибровка внешнего I2C-насоса" || result.address !== 2 ||
        result.steps !== 43200 || result.displayed !== "43200" || result.save !== null ||
        !result.returnUrl.includes("/i2cstepper.htm?address=' + externalAddress")) {
      throw new Error("external calibration address contract mismatch: " + JSON.stringify(result));
    }
  }

  async function testI2cStepper() {
    await installRecorder("/i2cstepper", "json");
    const result = await page.evaluate(async () => {
      const speed = document.getElementById("speedStepsPerSec");
      const target = document.getElementById("targetSteps");
      const operationalOnly = !document.getElementById("newAddress") &&
        !document.getElementById("stepsPerMl") && !document.getElementById("pump_type");
      speed.value = "18000";
      target.value = "2147483647";
      const first = command("start", commandValues());
      const concurrentStop = await command("stop");
      const firstResult = await first;
      const mutations = () => window.__numericRequests.filter(request => request.url.includes("&cmd=") || request.url.includes("?address=2&cmd="));
      const startUrl = mutations()[0] && mutations()[0].url;
      const relayResult = await command("relay", {relay: 1, state: 1});
      const relayUrl = mutations().at(-1).url;
      window.__numericStatus = 400;
      const failedStop = await command("stop");
      const error = document.getElementById("request_error");
      return {
        operationalOnly, firstResult, concurrentStop, relayResult, failedStop,
        startUrl, relayUrl, operationRequests:window.__numericOperationRequests.slice(),
        released:!commandInFlight,
        errorVisible:!!error && getComputedStyle(error).display !== "none" && error.textContent.trim() !== "",
        bounds:speed.min === "1" && speed.max === "18000" && target.min === "1" && target.max === "2147483647",
        calibrationUrl:String(document.getElementById("calibrate").getAttribute("onclick") || "")
      };
    });
    if (!result.operationalOnly || !result.firstResult || result.concurrentStop !== false ||
        !result.relayResult || result.failedStop !== false || !result.released || !result.errorVisible ||
        !result.bounds || result.startUrl !== "/i2cstepper?address=2&cmd=start&speedStepsPerSec=18000&targetSteps=2147483647" ||
        result.relayUrl !== "/i2cstepper?address=2&cmd=relay&relay=1&state=1" ||
        result.operationRequests.length !== 2 || !result.operationRequests.every(url => url === "/ajax?operationId=901") ||
        !result.calibrationUrl.includes("/calibrate.htm?address=' + selectedAddress")) {
      throw new Error("selected I2CStepper contract mismatch: " + JSON.stringify(result));
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
        if (["index.htm", "beer.htm", "bk.htm", "distiller.htm", "nbk.htm"].includes(file)) {
          await page.waitForFunction(() =>
            document.body.inert === false && document.querySelector("#prg").children.length > 0
          );
        }
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
  await testExternalCalibration();
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
    (target / "ui-bootstrap").write_text(
        json.dumps(UI_BOOTSTRAP_FIXTURE), encoding="utf-8"
    )
    color_tokens = color_tokens or {}
    replacements = {
        "pwr_unit": "V",
        "HeaterMaxPower": "230.000000000",
        "HeaterR": "10.000000000",
        "MainsVoltage": "230.00",
        "StepperStep": "100",
        "StepperStepMl": "100",
        "CalibrationRunning": "0",
        "btn_list": '""',
        "WProgram": "",
        "Descr": "",
        "ColDiam": "2.0",
        "ColHeight": "1.0",
        "PackDens": "80",
        "v": "test",
        "BeerBrewOrderId": "allinone",
    }
    empty_markers = {
        "RECT", "DIST", "BEER", "BK", "NBK", "SUVID", "LUA_MODE",
        "Checked", "FLChecked", "UASChecked", "UASDetectorChecked", "CPBuzz",
        "CUBuzz", "CUBBuzz", "UseWS", "UseST", "ChckPwr", "IgnFL",
    }
    address_tokens = {"SteamAddr", "PipeAddr", "WaterAddr", "TankAddr", "ACPAddr"}
    token_pattern = re.compile(r"%([A-Za-z0-9_.]+)%")

    def replace_token(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in replacements:
            return replacements[name]
        if name == "BeerBrewOrder_0":
            return "selected"
        if name.startswith("BeerBrewOrder_"):
            return ""
        if name in address_tokens:
            return '<option value="-1" selected>-</option>'
        if name in empty_markers or name.startswith(("ColDiam_", "ColHeight_")):
            return ""
        if name.endswith("Color"):
            return color_tokens.get(name, "#000000")
        return "0"

    for path in target.glob("*.htm"):
        # Разворачиваем <!--#include--> той же функцией, что использует сама сборка,
        # ДО подстановки %ПЛЕЙСХОЛДЕРОВ% - иначе served-копия покажет браузеру голый
        # HTML-комментарий вместо разметки/JS партиала.
        resolved = resolve_includes(path.name, path.read_bytes()).decode("utf-8", errors="ignore")
        rendered = token_pattern.sub(replace_token, resolved).replace("%%", "%")
        path.write_text(rendered, encoding="utf-8")

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
    if check:
        command = arguments[0] if arguments else ""

        def has_marker(marker):
            # Настоящие заголовки playwright-cli ("### Error"/"### Modal state"/
            # "### Result") печатаются ТОЛЬКО в начале строки. Тот же текст может
            # случайно оказаться внутри блока "### Ran Playwright code" - туда CLI
            # эхом печатает наш же исполненный JS, включая комментарии. Проверка
            # substring без привязки к началу строки однажды поймала свой же
            # комментарий как признак заблокировавшего скрипт диалога.
            return result.stdout.startswith(marker) or ("\n" + marker) in result.stdout

        if result.returncode != 0:
            raise RuntimeError(f"playwright-cli {command} failed (exit {result.returncode})")
        if has_marker("### Error"):
            raise RuntimeError(f"playwright-cli {command} failed: '### Error' marker in output")
        if has_marker("### Modal state"):
            raise RuntimeError(
                f"playwright-cli {command} failed: '### Modal state' marker in output "
                "(a dialog blocked the script and was never handled)"
            )
        if command == "run-code" and not has_marker("### Result"):
            raise RuntimeError(f"playwright-cli {command} failed: '### Result' marker missing from output")
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
