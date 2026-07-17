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

from test_numeric_input_ui_browser import render_site


ROOT = Path(__file__).resolve().parents[1]

SCENARIOS = (
    "i2c/present-0-1",
    "i2c/lifecycle",
    "i2c/failed-command",
    "i2c/failed-device",
    "i2c/failed-refresh",
    "i2c/timeout",
    "i2c/network",
    "i2c/expired",
    "i2c/malformed",
    "i2c/double-click-dirty-preservation",
    "i2c/relay-start-stop",
    "calibration/local-start-finish",
    "calibration/i2c-start-finish",
    "calibration/i2c-persist-failed",
    "calibration/i2c-readback-failed",
)

BROWSER_HELPER = r'''(() => {
  const mixerFixture = {
    present: 1, caps: 25, status: 0, error: 0, remaining: 0, currentSpeed: 0,
    mode: 1, optionFlags: 0, sensorFlags: 0, relayMask: 0,
    mixerRpm: 120, mixerRunSec: 30, mixerPauseSec: 10,
    pumpMlHour: 0, pumpPauseSec: 0, fillingMl: 0, fillingMlHour: 0,
    stepsPerMl: 100
  };
  const pumpFixture = {
    present: 1, caps: 30, status: 0, error: 0, remaining: 0, currentSpeed: 0,
    mode: 3, optionFlags: 0, sensorFlags: 0, relayMask: 0,
    mixerRpm: 0, mixerRunSec: 0, mixerPauseSec: 0,
    pumpMlHour: 100, pumpPauseSec: 10, fillingMl: 100, fillingMlHour: 100,
    stepsPerMl: 100
  };
  const nativeFetch = window.fetch.bind(window);
  const realNow = Date.now.bind(Date);
  const realSetTimeout = window.setTimeout.bind(window);
  const realClearTimeout = window.clearTimeout.bind(window);
  let state = null;

  function accepted(id) {
    return { status: 202, body: { operationId: id, state: "queued", error: "none" } };
  }

  function terminal(id, operationState, error) {
    return { status: 200, body: { operationId: id, state: operationState, error } };
  }

  function makeResponse(plan, fallbackBody) {
    if (plan.network) throw new TypeError(plan.network);
    if (plan.rawBody !== undefined) {
      return new Response(plan.rawBody, {
        status: plan.status === undefined ? 200 : plan.status,
        headers: { "Content-Type": plan.contentType || "application/json" }
      });
    }
    return new Response(JSON.stringify(
      plan.body === undefined ? fallbackBody : plan.body
    ), {
      status: plan.status === undefined ? 200 : plan.status,
      headers: { "Content-Type": plan.contentType || "application/json" }
    });
  }

  async function maybeHold(plan) {
    if (!plan.hold) return;
    await new Promise(resolve => { state.release = resolve; });
    state.release = null;
  }

  function install(settings) {
    Date.now = realNow;
    window.setTimeout = realSetTimeout;
    window.clearTimeout = realClearTimeout;
    const config = Object.assign({
      fastClock: true,
      mixerStatus: mixerFixture,
      pumpStatus: pumpFixture
    }, settings || {});
    if (config.fastClock !== false) {
      let fakeNow = 0;
      Date.now = () => fakeNow;
      window.setTimeout = (callback, delay, ...args) =>
        realSetTimeout(() => {
          fakeNow += Number(delay) || 0;
          callback(...args);
        }, delay >= 500 ? 2 : Math.min(Number(delay) || 0, 2));
      window.clearTimeout = id => realClearTimeout(id);
    }

    state = {
      trace: { requests: [], mutations: [], lookups: [], reads: [], unexpected: [] },
      mutationPlans: (config.mutations || []).slice(),
      lookupPlans: (config.lookups || []).slice(),
      repeatLookup: config.repeatLookup || null,
      statusReadPlans: (config.statusReads || []).slice(),
      status: {
        mixer: Object.assign({}, config.mixerStatus),
        pump: Object.assign({}, config.pumpStatus)
      },
      confirmed: Object.assign({
        localStepsPerMl: 123,
        i2cStepsPerMl: 456
      }, config.confirmed || {}),
      release: null
    };

    window.fetch = async (url, options) => {
      const request = url instanceof Request ? url : null;
      const parsedUrl = new URL(request ? request.url : String(url), location.origin);
      const raw = parsedUrl.origin === location.origin
        ? parsedUrl.pathname + parsedUrl.search
        : parsedUrl.href;
      const optionMethod = options && options.method !== undefined
        ? options.method
        : undefined;
      const method = String(
        optionMethod !== undefined ? optionMethod : (request ? request.method : "GET")
      ).toUpperCase();
      state.trace.requests.push({ method, url: raw });
      if (raw.startsWith("/ajax?operationId=")) {
        state.trace.lookups.push(raw);
        const plan = state.lookupPlans.length
          ? state.lookupPlans.shift()
          : state.repeatLookup;
        if (!plan) throw new Error("Missing operation lookup plan for " + raw);
        await maybeHold(plan);
        return makeResponse(plan, {});
      }

      const mutation = raw.startsWith("/calibrate?") ||
        (raw.startsWith("/i2cstepper?") &&
          new URL(raw, location.origin).searchParams.has("cmd"));
      if (mutation) {
        state.trace.mutations.push(raw);
        const plan = state.mutationPlans.shift();
        if (!plan) throw new Error("Missing mutation plan for " + raw);
        await maybeHold(plan);
        return makeResponse(plan, {
          operationId: plan.id || 1,
          state: "queued",
          error: "none"
        });
      }

      if (raw === "/i2cstepper?device=mixer" || raw === "/i2cstepper?device=pump") {
        const device = raw.endsWith("mixer") ? "mixer" : "pump";
        state.trace.reads.push(raw);
        const plan = state.statusReadPlans.length
          ? state.statusReadPlans.shift()
          : { status: 200, body: state.status[device] };
        return makeResponse(plan, state.status[device]);
      }
      if (raw === "/ajax?messageCursor=0") {
        state.trace.reads.push(raw);
        return makeResponse({
          status: 200,
          body: { StepperStepMl: state.confirmed.localStepsPerMl }
        }, {});
      }

      state.trace.unexpected.push(raw);
      return nativeFetch(url, options);
    };
  }

  function trace() {
    return {
      requests: state.trace.requests.map(request => Object.assign({}, request)),
      mutations: state.trace.mutations.slice(),
      lookups: state.trace.lookups.slice(),
      reads: state.trace.reads.slice(),
      unexpected: state.trace.unexpected.slice(),
      remainingMutations: state.mutationPlans.length,
      remainingLookups: state.lookupPlans.length,
      remainingStatusReads: state.statusReadPlans.length
    };
  }

  function assertTrace(name, value, mutationCount, lookupCount) {
    const invalidRequests = value.requests.filter(request =>
      request.method !== "GET" ||
      !(
        request.url === "/ajax?messageCursor=0" ||
        /^\/ajax\?operationId=\d+$/.test(request.url) ||
        request.url.startsWith("/calibrate?") ||
        request.url.startsWith("/i2cstepper?")
      ) ||
      /^\/(?:i2cpump|lua)(?:[/?]|$)/.test(request.url)
    );
    if (value.mutations.length !== mutationCount ||
        (lookupCount !== null && value.lookups.length !== lookupCount) ||
        value.requests.length !== value.mutations.length +
          value.lookups.length + value.reads.length ||
        invalidRequests.length !== 0 ||
        value.remainingMutations !== 0 || value.remainingLookups !== 0 ||
        value.remainingStatusReads !== 0 ||
        value.unexpected.length !== 0 ||
        value.lookups.some(url => !/^\/ajax\?operationId=\d+$/.test(url))) {
      throw new Error(name + " request trace mismatch: " + JSON.stringify(value));
    }
  }

  async function waitDeviceIdle() {
    const deadline = realNow() + 2000;
    while (deviceActionInFlight("pump") && realNow() < deadline) {
      await new Promise(resolve => realSetTimeout(resolve, 2));
    }
    return !deviceActionInFlight("pump");
  }

  async function runPumpApply(value) {
    SamovarApp.clearRequestError();
    i2cRequestErrorOwner = null;
    document.getElementById("pumpMode").value = "3";
    for (const id of [
      "pumpMlHour", "pumpPauseSec", "fillingMl", "fillingMlHour", "stepsPerMl"
    ]) {
      document.getElementById(id).value = String(value);
    }
    markDirty("pump");
    const started = sendDevice("pump", "apply");
    const idle = await waitDeviceIdle();
    const error = document.getElementById("request_error");
    return {
      started,
      idle,
      dirty: dirtyDevices.pump,
      value: document.getElementById("fillingMl").value,
      error: error ? error.textContent : ""
    };
  }

  async function runPresenceScenario() {
    const name = "i2c/present-0-1";
    const actionIds = [
      "mixer_apply", "mixer_run_toggle", "mixer_save",
      "mixerRelay1", "mixerRelay2", "mixerRelay3", "mixerRelay4",
      "pump_apply", "pump_run_toggle", "pump_save",
      "pump_calstart", "pump_calfinish",
      "pumpRelay1", "pumpRelay2", "pumpRelay3", "pumpRelay4"
    ];
    const expectedReads = [
      "/i2cstepper?device=mixer", "/i2cstepper?device=pump"
    ];

    install({
      mixerStatus: Object.assign({}, mixerFixture, { present: 0, caps: 0 }),
      pumpStatus: Object.assign({}, pumpFixture, { present: 0, caps: 0 })
    });
    await Promise.all([loadDevice("mixer"), loadDevice("pump")]);
    actionIds.forEach(id => document.getElementById(id).click());
    const absentTrace = trace();
    assertTrace(name + "/absent", absentTrace, 0, 0);
    const absent = {
      mixerPanel: document.getElementById("mixer_panel").style.display,
      mixerMissing: document.getElementById("mixer_missing").style.display,
      pumpPanel: document.getElementById("pump_panel").style.display,
      pumpMissing: document.getElementById("pump_missing").style.display,
      mixerState: Object.assign({}, deviceState.mixer),
      pumpState: Object.assign({}, deviceState.pump),
      caps: Object.assign({}, deviceCaps),
      actionsDisabled: actionIds.every(id => document.getElementById(id).disabled)
    };
    if (absent.mixerPanel !== "none" || absent.mixerMissing !== "block" ||
        absent.pumpPanel !== "none" || absent.pumpMissing !== "block" ||
        absent.mixerState.present || absent.mixerState.supported ||
        absent.pumpState.present || absent.pumpState.supported ||
        absent.caps.mixer !== 0 || absent.caps.pump !== 0 ||
        !absent.actionsDisabled ||
        JSON.stringify(absentTrace.reads) !== JSON.stringify(expectedReads)) {
      throw new Error(name + " absent mismatch: " + JSON.stringify({
        absent, absentTrace
      }));
    }

    install();
    await Promise.all([loadDevice("mixer"), loadDevice("pump")]);
    const restoredTrace = trace();
    assertTrace(name + "/restored", restoredTrace, 0, 0);
    const restored = {
      mixerPanel: document.getElementById("mixer_panel").style.display,
      mixerMissing: document.getElementById("mixer_missing").style.display,
      pumpPanel: document.getElementById("pump_panel").style.display,
      pumpMissing: document.getElementById("pump_missing").style.display,
      mixerState: Object.assign({}, deviceState.mixer),
      pumpState: Object.assign({}, deviceState.pump),
      actionsEnabled: actionIds.every(id => !document.getElementById(id).disabled)
    };
    if (restored.mixerPanel !== "block" || restored.mixerMissing !== "none" ||
        restored.pumpPanel !== "block" || restored.pumpMissing !== "none" ||
        !restored.mixerState.present || !restored.mixerState.supported ||
        !restored.pumpState.present || !restored.pumpState.supported ||
        !restored.actionsEnabled ||
        JSON.stringify(restoredTrace.reads) !== JSON.stringify(expectedReads)) {
      throw new Error(name + " restoration mismatch: " + JSON.stringify({
        restored, restoredTrace
      }));
    }
    return [name];
  }

  async function runCoreScenarios() {
    const covered = [];
    let name = "i2c/lifecycle";
    install({
      mutations: [accepted(101)],
      lookups: [
        terminal(101, "queued", "none"),
        terminal(101, "running", "none"),
        terminal(101, "succeeded", "none")
      ],
      pumpStatus: Object.assign({}, pumpFixture, {
        mode: 3, pumpMlHour: 100, pumpPauseSec: 100,
        fillingMl: 100, fillingMlHour: 100, stepsPerMl: 100
      })
    });
    const lifecycle = await runPumpApply(100);
    const lifecycleTrace = trace();
    assertTrace(name, lifecycleTrace, 1, 3);
    if (!lifecycle.started || !lifecycle.idle || lifecycle.dirty || lifecycle.error.trim()) {
      throw new Error(name + " state mismatch: " + JSON.stringify(lifecycle));
    }
    covered.push(name);

    for (const failure of [
      ["command", "i2c_command_failed", 111],
      ["device", "i2c_device_error", 112],
      ["refresh", "i2c_refresh_failed", 113]
    ]) {
      name = "i2c/failed-" + failure[0];
      install({
        mutations: [accepted(failure[2])],
        lookups: [terminal(failure[2], "failed", failure[1])]
      });
      const failed = await runPumpApply(failure[2]);
      const failedTrace = trace();
      assertTrace(name, failedTrace, 1, 1);
      if (!failed.started || !failed.idle || !failed.dirty ||
          failed.value !== String(failure[2]) || !failed.error.includes(failure[1])) {
        throw new Error(name + " state mismatch: " + JSON.stringify(failed));
      }
      covered.push(name);
    }
    return covered;
  }

  async function runWaiterScenarios() {
    const covered = [];
    const failures = [
      {
        name: "timeout", id: 120,
        repeatLookup: terminal(120, "running", "none"),
        expected: "45 секунд", minLookups: 2
      },
      {
        name: "network", id: 121,
        lookups: [{ network: "offline" }],
        expected: "Ошибка сети", minLookups: 1
      },
      {
        name: "expired", id: 122,
        lookups: [{ status: 404, body: { error: "operation_not_found" } }],
        expected: "HTTP 404", minLookups: 1
      },
      {
        name: "malformed", id: 123,
        lookups: [{ status: 200, rawBody: "{" }],
        expected: "Некорректный JSON-ответ /ajax", minLookups: 1
      }
    ];
    for (const failure of failures) {
      const name = "i2c/" + failure.name;
      install({
        mutations: [accepted(failure.id)],
        lookups: failure.lookups || [],
        repeatLookup: failure.repeatLookup || null
      });
      const failed = await runPumpApply(failure.id);
      const failedTrace = trace();
      assertTrace(name, failedTrace, 1, failure.repeatLookup ? null : 1);
      if (!failed.started || !failed.idle || !failed.dirty ||
          !failed.error.includes(failure.expected) ||
          failedTrace.lookups.length < failure.minLookups) {
        throw new Error(name + " mismatch: " + JSON.stringify({ failed, failedTrace }));
      }
      covered.push(name);
    }
    return covered;
  }

  async function runControlScenarios() {
    const covered = [];
    let name = "i2c/double-click-dirty-preservation";
    install({
      fastClock: false,
      mutations: [Object.assign(accepted(140), { hold: true })],
      lookups: [terminal(140, "succeeded", "none")],
      pumpStatus: Object.assign({}, pumpFixture, {
        mode: 3, pumpMlHour: 321, pumpPauseSec: 321,
        fillingMl: 321, fillingMlHour: 321, stepsPerMl: 321
      })
    });
    for (const id of [
      "pumpMlHour", "pumpPauseSec", "fillingMl", "fillingMlHour", "stepsPerMl"
    ]) {
      document.getElementById(id).value = "321";
    }
    document.getElementById("pumpMode").value = "3";
    markDirty("pump");
    document.getElementById("pump_apply").click();
    document.getElementById("pump_apply").click();
    const releaseDeadline = realNow() + 2000;
    while (!state.release && realNow() < releaseDeadline) {
      await new Promise(resolve => realSetTimeout(resolve, 2));
    }
    if (!state.release) throw new Error(name + " mutation did not enter in-flight state");
    const pending = {
      disabled: document.getElementById("pump_apply").disabled,
      mutations: state.trace.mutations.length
    };
    const input = document.getElementById("fillingMl");
    input.value = "322";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    state.release();
    const idle = await waitDeviceIdle();
    const preserved = {
      idle,
      dirty: dirtyDevices.pump,
      value: input.value,
      disabled: document.getElementById("pump_apply").disabled
    };
    const doubleTrace = trace();
    assertTrace(name, doubleTrace, 1, 1);
    if (!pending.disabled || pending.mutations !== 1 || !preserved.idle ||
        !preserved.dirty || preserved.value !== "322" || preserved.disabled) {
      throw new Error(name + " mismatch: " + JSON.stringify({ pending, preserved }));
    }
    covered.push(name);

    name = "i2c/relay-start-stop";
    install({
      mutations: [accepted(151), accepted(152), accepted(153)],
      lookups: [
        terminal(151, "succeeded", "none"),
        terminal(152, "succeeded", "none"),
        terminal(153, "succeeded", "none")
      ]
    });
    document.getElementById("pumpMode").value = "3";
    for (const id of [
      "pumpMlHour", "pumpPauseSec", "fillingMl", "fillingMlHour", "stepsPerMl"
    ]) {
      document.getElementById(id).value = "100";
    }
    const relay = toggleRelay("pump", 1);
    const relayIdle = await waitDeviceIdle();
    toggleDevice("pump");
    const startIdle = await waitDeviceIdle();
    document.getElementById("pump_panel").dataset.status = "1";
    toggleDevice("pump");
    const stopIdle = await waitDeviceIdle();
    const controlTrace = trace();
    assertTrace(name, controlTrace, 3, 3);
    const commands = controlTrace.mutations.map(raw =>
      new URL(raw, "http://samovar.invalid").searchParams.get("cmd")
    );
    if (!relay || !relayIdle || !startIdle || !stopIdle ||
        JSON.stringify(commands) !== JSON.stringify(["relay", "start", "stop"]) ||
        controlTrace.mutations[0] !==
          "/i2cstepper?device=pump&cmd=relay&relay=1&state=1" ||
        controlTrace.mutations[2] !== "/i2cstepper?device=pump&cmd=stop") {
      throw new Error(name + " mismatch: " + JSON.stringify({
        relay, relayIdle, startIdle, stopIdle, controlTrace
      }));
    }
    covered.push(name);
    return covered;
  }

  async function runCalibrationPair(pump, speed, ids, confirmed) {
    install({
      mutations: [accepted(ids[0]), accepted(ids[1])],
      lookups: [
        terminal(ids[0], "queued", "none"),
        terminal(ids[0], "running", "none"),
        terminal(ids[0], "succeeded", "none"),
        terminal(ids[1], "succeeded", "none")
      ],
      confirmed,
      pumpStatus: Object.assign({}, pumpFixture, {
        stepsPerMl: confirmed.i2cStepsPerMl
      })
    });
    document.getElementById("pump_type").value = pump;
    onPumpTypeChange();
    document.getElementById("kstepperspd").value = String(speed);
    const started = await calibrate();
    const during = {
      running: calibrationRunning,
      pump: calibrationPump,
      pumpDisabled: document.getElementById("pump_type").disabled,
      speedDisabled: document.getElementById("kstepperspd").disabled
    };
    const finished = await calibrate();
    return {
      started,
      finished,
      during,
      running: calibrationRunning,
      pump: calibrationPump,
      value: document.getElementById("stepperstepml").value
    };
  }

  async function runCalibration(mode) {
    const local = mode === "local";
    const name = local
      ? "calibration/local-start-finish"
      : "calibration/i2c-start-finish";
    const result = await runCalibrationPair(
      mode,
      local ? 200 : 250,
      local ? [201, 202] : [211, 212],
      { localStepsPerMl: 123, i2cStepsPerMl: 456 }
    );
    const value = trace();
    assertTrace(name, value, 2, 4);
    const otherMode = local ? "i2c" : "local";
    document.getElementById("pump_type").value = otherMode;
    onPumpTypeChange();
    const otherValue = document.getElementById("stepperstepml").value;
    document.getElementById("pump_type").value = mode;
    onPumpTypeChange();
    const restoredValue = document.getElementById("stepperstepml").value;
    const caches = {
      local: stepperStepMlLocal,
      i2c: stepperStepMlI2C
    };
    const expectedRead = local ? ["/ajax?messageCursor=0"] : ["/i2cstepper?device=pump"];
    const expectedStart = local
      ? "/calibrate?pump=local&stpstep=200&start=1"
      : "/calibrate?pump=i2c&stpstep=250&start=1";
    const expectedFinish = local
      ? "/calibrate?pump=local&finish=1"
      : "/calibrate?pump=i2c&finish=1";
    if (!result.started || !result.finished || !result.during.running ||
        result.during.pump !== mode || !result.during.pumpDisabled ||
        !result.during.speedDisabled || result.running || result.pump ||
        result.value !== (local ? "12300" : "45600") ||
        otherValue !== "100" || restoredValue !== result.value ||
        caches.local !== (local ? 12300 : 100) ||
        caches.i2c !== (local ? 100 : 45600) ||
        value.mutations[0] !== expectedStart || value.mutations[1] !== expectedFinish ||
        JSON.stringify(value.reads) !== JSON.stringify(expectedRead)) {
      throw new Error(name + " mismatch: " + JSON.stringify({
        result, value, otherValue, restoredValue, caches
      }));
    }
    return [name];
  }

  async function runPersistFailure() {
    const name = "calibration/i2c-persist-failed";
    install({
      mutations: [accepted(220)],
      lookups: [terminal(220, "failed", "profile_persist_failed")]
    });
    const before = {
      running: calibrationRunning,
      pump: calibrationPump,
      selected: document.getElementById("pump_type").value,
      value: document.getElementById("stepperstepml").value,
      localCache: stepperStepMlLocal,
      i2cCache: stepperStepMlI2C
    };
    const result = await calibrate();
    const error = document.getElementById("request_error");
    const value = trace();
    const after = {
      running: calibrationRunning,
      pump: calibrationPump,
      selected: document.getElementById("pump_type").value,
      value: document.getElementById("stepperstepml").value,
      localCache: stepperStepMlLocal,
      i2cCache: stepperStepMlI2C
    };
    assertTrace(name, value, 1, 1);
    if (result || !calibrationRunning || calibrationPump !== "i2c" ||
        document.getElementById("calibrateid").disabled ||
        !document.getElementById("pump_type").disabled ||
        !document.getElementById("kstepperspd").disabled ||
        !error || !error.textContent.includes("profile_persist_failed") ||
        value.reads.length !== 0 ||
        JSON.stringify(after) !== JSON.stringify(before) ||
        value.mutations[0] !== "/calibrate?pump=i2c&finish=1") {
      throw new Error(name + " mismatch: " + JSON.stringify({
        result,
        running: calibrationRunning,
        pump: calibrationPump,
        error: error ? error.textContent : "",
        value,
        before,
        after
      }));
    }
    return [name];
  }

  async function runReadbackFailure() {
    const name = "calibration/i2c-readback-failed";
    install({
      mutations: [accepted(230)],
      lookups: [terminal(230, "succeeded", "none")],
      statusReads: [{
        status: 503,
        body: { error: "i2c_status_unavailable" }
      }]
    });
    const before = {
      value: document.getElementById("stepperstepml").value,
      localCache: stepperStepMlLocal,
      i2cCache: stepperStepMlI2C
    };
    const result = await calibrate();
    const error = document.getElementById("request_error");
    const after = {
      value: document.getElementById("stepperstepml").value,
      localCache: stepperStepMlLocal,
      i2cCache: stepperStepMlI2C
    };
    const value = trace();
    assertTrace(name, value, 1, 1);
    if (result || calibrationRunning || calibrationPump ||
        document.getElementById("calibrateid").disabled ||
        document.getElementById("calibrateid").value !== "Начать калибровку" ||
        document.getElementById("pump_type").disabled ||
        document.getElementById("kstepperspd").disabled ||
        !error || getComputedStyle(error).display === "none" ||
        !error.textContent.includes("Калибровка завершена") ||
        JSON.stringify(after) !== JSON.stringify(before) ||
        JSON.stringify(value.reads) !==
          JSON.stringify(["/i2cstepper?device=pump"]) ||
        value.mutations[0] !== "/calibrate?pump=i2c&finish=1") {
      throw new Error(name + " mismatch: " + JSON.stringify({
        result,
        running: calibrationRunning,
        pump: calibrationPump,
        button: document.getElementById("calibrateid").value,
        error: error ? error.textContent : "",
        before,
        after,
        value
      }));
    }
    return [name];
  }

  window.__a02 = {
    runPresenceScenario,
    runCoreScenarios,
    runWaiterScenarios,
    runControlScenarios,
    runCalibration,
    runPersistFailure,
    runReadbackFailure
  };
})();'''

SETUP_BROWSER = r'''async page => {
  page.__a02Problems = [];
  page.__a02Scenario = "setup";
  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error") {
      page.__a02Problems.push(
        page.__a02Scenario + " console " + message.type() + ": " + message.text()
      );
    }
  });
  page.on("pageerror", error => {
    page.__a02Problems.push(page.__a02Scenario + " pageerror: " + error.message);
  });
  const mixer = {
    present: 1, caps: 25, status: 0, error: 0, remaining: 0, currentSpeed: 0,
    mode: 1, optionFlags: 0, sensorFlags: 0, relayMask: 0,
    mixerRpm: 120, mixerRunSec: 30, mixerPauseSec: 10,
    pumpMlHour: 0, pumpPauseSec: 0, fillingMl: 0, fillingMlHour: 0,
    stepsPerMl: 100
  };
  const pump = {
    present: 1, caps: 30, status: 0, error: 0, remaining: 0, currentSpeed: 0,
    mode: 3, optionFlags: 0, sensorFlags: 0, relayMask: 0,
    mixerRpm: 0, mixerRunSec: 0, mixerPauseSec: 0,
    pumpMlHour: 100, pumpPauseSec: 10, fillingMl: 100, fillingMlHour: 100,
    stepsPerMl: 100
  };
  await page.route("**/i2cstepper?*", async route => {
    const url = route.request().url();
    const fixture = url.includes("device=mixer") ? mixer : pump;
    await route.fulfill({
      status: url.includes("cmd=") ? 599 : 200,
      contentType: "application/json",
      body: JSON.stringify(fixture)
    });
  });
  await page.route("**/ajax?messageCursor=*", async route => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ StepperStepMl: 123 })
    });
  });
  await page.route("**/calibrate?*", async route => {
    await route.fulfill({
      status: 599,
      contentType: "text/plain",
      body: "unexpected mutation leak"
    });
  });
  await page.addInitScript({ path: __HELPER_PATH__ });
  return "ready";
}'''

I2C_PREPARE = r'''async page => {
  page.__a02Scenario = "i2c/load";
  await page.goto(__BASE_URL__ + "/i2cstepper.htm", { waitUntil: "load" });
  await page.waitForFunction(() =>
    typeof pollInFlight !== "undefined" && !pollInFlight &&
    document.getElementById("pump_panel").style.display === "block"
  );
  await page.evaluate(() => {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
    scheduleNextPoll = function() {};
  });
  return "ready";
}'''

GROUP_CALLS = (
    ("i2c/presence", "runPresenceScenario"),
    ("i2c/core", "runCoreScenarios"),
    ("i2c/waiter-errors", "runWaiterScenarios"),
    ("i2c/controls", "runControlScenarios"),
)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def run_cli(cli, session, arguments, cwd, timeout, check=True):
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
        raise RuntimeError(
            f"playwright-cli {' '.join(arguments[:1])} failed "
            f"(exit {result.returncode}, output={result.stdout!r})"
        )
    return result.returncode


def cleanup(cli, session, server, thread):
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


def group_code(name, method):
    return (
        "async page => {"
        f"page.__a02Scenario={json.dumps(name)};"
        f"return await page.evaluate(() => window.__a02.{method}());"
        "}"
    )


def calibration_code(base_url, name, page_name, method, argument=None):
    call = f"window.__a02.{method}()"
    if argument is not None:
        call = f"window.__a02.{method}({json.dumps(argument)})"
    return (
        "async page => {"
        f"page.__a02Scenario={json.dumps(name)};"
        f"await page.goto({json.dumps(base_url + '/' + page_name)},"
        "{waitUntil:'load'});"
        "await page.waitForFunction(() => typeof calibrate === 'function' && "
        "window.__a02);"
        f"return await page.evaluate(() => {call});"
        "}"
    )


def main():
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the A-02 browser gate", file=sys.stderr)
        return 2

    primary_error = None
    cleanup_errors = []
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-operation-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        helper = temp / "browser-helper.js"
        helper.write_text(BROWSER_HELPER, encoding="utf-8")

        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        session = f"samovar-i2c-operation-ui-{os.getpid()}"
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
            setup = SETUP_BROWSER.replace("__HELPER_PATH__", json.dumps(str(helper)))
            run_cli(cli, session, ["run-code", setup], temp, 30)
            prepare = I2C_PREPARE.replace("__BASE_URL__", json.dumps(base_url))
            run_cli(cli, session, ["run-code", prepare], temp, 30)
            for name, method in GROUP_CALLS:
                run_cli(cli, session, ["run-code", group_code(name, method)], temp, 30)
            for name, page_name, method, argument in (
                ("calibration/local", "calibrate.htm", "runCalibration", "local"),
                ("calibration/i2c", "calibrate.htm", "runCalibration", "i2c"),
                (
                    "calibration/persist-failed",
                    "calibrate_running.htm",
                    "runPersistFailure",
                    None,
                ),
                (
                    "calibration/readback-failed",
                    "calibrate_running.htm",
                    "runReadbackFailure",
                    None,
                ),
            ):
                run_cli(
                    cli,
                    session,
                    [
                        "run-code",
                        calibration_code(
                            base_url, name, page_name, method, argument
                        ),
                    ],
                    temp,
                    30,
                )
            final_check = (
                "async page => {"
                "const problems=page.__a02Problems || [];"
                "if(problems.length) throw new Error(problems.join('\\n'));"
                f"return {{scenarios:{json.dumps(list(SCENARIOS))},"
                "consoleAndPageErrors:0};"
                "}"
            )
            run_cli(cli, session, ["run-code", final_check], temp, 30)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"A-02 I2C operation browser gate failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"A-02 I2C operation browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print(f"A-02 I2C operation browser gate passed ({len(SCENARIOS)} scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
