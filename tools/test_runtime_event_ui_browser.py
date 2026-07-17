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

from test_numeric_input_ui_browser import QuietHandler, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]

CASE_NAMES = (
    "validation_transport",
    "validation_schema",
    "validation_commit",
    "gap",
    "reload",
    "wrap",
    "reboot_discontinuity",
    "reboot_collision",
    "long_log",
    "in_flight",
    "mode_index",
    "mode_beer",
    "mode_distiller",
    "mode_bk",
    "mode_nbk",
    "chart",
)

HARNESS_HTML = r'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script>
    window.__audioPlayCount = 0;
    window.__audioPauseCount = 0;
    window.Audio = function () {
      this.loop = false;
      this.preload = '';
      this.autoplay = false;
      this.play = function () {
        window.__audioPlayCount++;
        return Promise.resolve();
      };
      this.pause = function () { window.__audioPauseCount++; };
    };
  </script>
  <script src="app.js"></script>
</head>
<body>
  <div id="connection_indicator"></div>
  <div id="messagesBox" style="display:none"><div id="messages"></div></div>
  <div id="historyBox" style="display:none"><div id="historyList"></div></div>
  <script>SamovarApp.init({ threshold: 1000 });</script>
</body>
</html>
'''

INDEPENDENT_CONTEXT_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const delayMs = __DELAY_MS__;
  const trace = [];
  const problems = [];
  page.on('console', message => {
    if (message.type() === 'warning' || message.type() === 'error') {
      problems.push('console ' + message.type() + ': ' + message.text());
    }
  });
  page.on('pageerror', error => problems.push('pageerror: ' + error.message));
  const handler = route => {
    const requestUrl = route.request().url();
    const match = /\/ajax\?messageCursor=(\d+)$/.exec(requestUrl);
    if (!match) {
      throw new Error('invalid telemetry request: ' + requestUrl);
    }
    const cursor = Number(match[1]);
    trace.push(cursor);
    let event = {};
    if (cursor === 0) event = { Msg: 'first-message', msglvl: 2, messageSequence: 1 };
    else if (cursor === 1) event = { LogMsg: 'second-log', messageSequence: 2 };
    else if (cursor === 2) event = { Msg: 'third-message', msglvl: 1, messageSequence: 3 };
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(Object.assign({ crnt_tm: '12:00:00' }, event))
    });
  };
  await page.route('**/ajax*', handler);
  await page.goto(baseUrl + '/event_harness.htm', { waitUntil: 'load' });
  const browserCalls = await page.evaluate(async interval => {
    window.__independentCalls = [];
    for (let i = 0; i < 4; i++) {
      await SamovarApp.pollAjax(function () {}, {
        message: (text, level) => window.__independentCalls.push({ type: 'message', text, level }),
        log: text => window.__independentCalls.push({ type: 'log', text }),
        connection: function () {}
      });
      if (i !== 3) await new Promise(resolve => setTimeout(resolve, interval));
    }
    return window.__independentCalls;
  }, delayMs);
  const events = browserCalls.map(call => call.text);
  if (JSON.stringify(trace) !== JSON.stringify([0, 1, 2, 3])) {
    throw new Error('independent cursor trace: ' + JSON.stringify(trace));
  }
  if (JSON.stringify(events) !== JSON.stringify([
    'first-message', 'second-log', 'third-message'
  ])) {
    throw new Error('independent event order/uniqueness: ' + JSON.stringify(events));
  }
  if (problems.length) throw new Error(problems.join('\n'));
  return { trace, events };
}'''

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const gapWarning = 'Пропущены сообщения: обнаружен разрыв последовательности.';
  const fixture = {
    version: 'test', crnt_tm: '12:00:00', stm: '00:01:00', SteamTemp: 78.1,
    PipeTemp: 77.9, WaterTemp: 20.2, TankTemp: 82.3, ACPTemp: 40.1,
    bme_pressure: 760, start_pressure: 759.5, prvl: 1.2, VolumeAll: 0,
    ActualVolumePerHour: 0, WthdrwlProgress: 0, CurrrentSpeed: 0,
    CurrrentStepps: 0, TargetStepps: 0, WthdrwlStatus: 0, ProgramNum: 0,
    DetectorTrend: 0, DetectorStatus: 0, useautospeed: false,
    current_power_volt: 0, target_power_volt: 0, current_power_mode: '0',
    current_power_p: 0, WFtotalMl: 0, WFflowRate: 0, bme_temp: 24,
    heap: 200000, rssi: -50, fr_bt: 300000, UseBBuzzer: false, PauseOn: 0,
    PrgType: '', Status: 'Готов', Lstatus: '', TimeRemaining: 0, TotalTime: 0,
    alc: 0, stm_alc: 0, ISspd: 0, wp_spd: 0, i2c_pump_present: 0,
    i2c_pump_running: 0, i2c_pump_remaining_ml: 0, i2c_pump_speed: 0,
    PowerOn: 0, StepperStepMl: 111
  };
  const columnFixture = {
    floodPowerW: 3000, workingPowerW: 2500, maxFlowMlH: 1000,
    theoreticalPlates: 20, headsFlowMlH: 100, bodyFlowMinMlH: 200,
    bodyFlowMaxMlH: 400, bodyEndFlowMlH: 300, tailsFlowMlH: 150,
    headsPowerW: 1800, bodyEndPowerW: 2200, tailsPowerW: 2000
  };
  const problems = [];

  function expect(condition, message) {
    if (!condition) throw new Error(message);
  }

  function cursorFrom(url) {
    const prefix = baseUrl + '/ajax?messageCursor=';
    expect(url.startsWith(prefix), 'unexpected telemetry request: ' + url);
    const raw = url.slice(prefix.length);
    expect(/^\d+$/.test(raw), 'messageCursor is not decimal: ' + raw);
    return Number(raw);
  }

  function withEvent(event) {
    return Object.assign({}, fixture, event || {});
  }

  function trackPage(current, label, expectedConsole) {
    current.__runtimeEventLabel = label;
    current.__runtimeEventExpectedConsole = (expectedConsole || []).slice();
    if (!current.__runtimeEventTracked) {
      current.__runtimeEventTracked = true;
      current.on('pageerror', error => problems.push(
        current.__runtimeEventLabel + ' pageerror: ' + error.message
      ));
      current.on('console', message => {
        if (message.type() === 'warning' || message.type() === 'error') {
          const expected = current.__runtimeEventExpectedConsole.shift();
          if (expected && expected.type === message.type() && expected.text === message.text()) {
            return;
          }
          problems.push(current.__runtimeEventLabel + ' console ' +
            message.type() + ': ' + message.text());
        }
      });
    }
    return current;
  }

  async function newPage(label, expectedConsole) {
    return trackPage(page, label, expectedConsole);
  }

  async function routeTelemetry(current, responder) {
    const state = { trace: [], active: 0, maxActive: 0, count: 0 };
    const handler = async route => {
      const cursor = cursorFrom(route.request().url());
      state.trace.push(cursor);
      state.count++;
      state.active++;
      state.maxActive = Math.max(state.maxActive, state.active);
      try {
        await responder(route, cursor, state.count - 1);
      } finally {
        state.active--;
      }
    };
    await current.route('**/ajax*', handler);
    return state;
  }

  async function fulfillJson(route, body, status, delayMs) {
    if (delayMs) await page.waitForTimeout(delayMs);
    await route.fulfill({
      status: status === undefined ? 200 : status,
      contentType: 'application/json',
      body: typeof body === 'string' ? body : JSON.stringify(body)
    });
  }

  async function openHarness(current) {
    await current.goto(baseUrl + '/event_harness.htm', { waitUntil: 'load' });
    await current.waitForFunction(() => window.SamovarApp && SamovarApp.pollAjax);
  }

  async function pollWithSinks(current, config) {
    const configs = Array.isArray(config) ? config : [config || {}];
    return await current.evaluate(async settingsList => {
      window.__eventCalls = window.__eventCalls || [];
      const outcomes = [];
      for (const settings of settingsList) {
        const outcome = { result: null, rejection: null, calls: [] };
        const record = function (call) {
          outcome.calls.push(call);
          window.__eventCalls.push(call);
        };
        const nativeFetch = window.fetch;
        if (settings.transport === 'abort') {
          window.fetch = function () {
            return Promise.reject(new DOMException('planned network abort', 'AbortError'));
          };
        } else if (settings.transport === 'timeout') {
          window.fetch = function (url, options) {
            return new Promise(function (resolve, reject) {
              const abort = function () {
                reject(new DOMException('planned timeout', 'AbortError'));
              };
              if (options.signal.aborted) abort();
              else options.signal.addEventListener('abort', abort, { once: true });
            });
          };
        }
        const sinks = {
          message: function (text, level) {
            record({ type: 'message', text: text, level: level });
            if (settings.throwSink === 'message') throw new Error('planned message sink failure');
          },
          log: function (text, telemetry) {
            record({
              type: 'log', text: text, sequence: telemetry && telemetry.messageSequence
            });
            if (settings.throwSink === 'log') throw new Error('planned log sink failure');
          },
          connection: function (hasError) {
            record({ type: 'connection', error: hasError });
          }
        };
        try {
          outcome.result = await SamovarApp.pollAjax(function (telemetry) {
            record({ type: 'render', sequence: telemetry.messageSequence || 0 });
            if (settings.throwRender) throw new Error('planned renderer failure');
          }, sinks);
        } catch (error) {
          outcome.rejection = String(error);
        } finally {
          window.fetch = nativeFetch;
        }
        outcomes.push(outcome);
      }
      return outcomes;
    }, configs);
  }

  async function testValidationTransport() {
    const current = await newPage('validation-transport', [
      {
        type: 'error',
        text: 'Failed to load resource: the server responded with a status of 400 (Bad Request)'
      },
      {
        type: 'error',
        text: 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)'
      }
    ]);
    const plans = [
      { body: withEvent({ Msg: 'before-pause', msglvl: 2, messageSequence: 1 }) },
      { status: 400, body: { error: 'bad cursor' } },
      { status: 503, body: { error: 'busy' } },
      { raw: '{' },
      { body: withEvent({ Msg: 'after-reconnect', msglvl: 2, messageSequence: 2 }) },
      { body: withEvent({}) }
    ];
    const state = await routeTelemetry(current, async (route, cursor, index) => {
      const plan = plans[index];
      expect(!!plan, 'missing response plan at request ' + index);
      if (plan.raw !== undefined) {
        await fulfillJson(route, plan.raw, 200);
      } else {
        await fulfillJson(route, plan.body, plan.status);
      }
    });
    await openHarness(current);

    const outcomes = await pollWithSinks(current, [
      {}, { transport: 'abort' }, {}, {}, {}, { transport: 'timeout' }, {}, {}
    ]);
    expect(JSON.stringify(state.trace) === JSON.stringify([0, 1, 1, 1, 1, 2]),
      'transport failure/recovery cursor trace: ' + JSON.stringify(state.trace));
    const expected = [
      {
        result: true, rejection: null, calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 1 },
          { type: 'message', text: 'before-pause', level: 2 }
        ]
      },
      { result: false, rejection: null, calls: [{ type: 'connection', error: true }] },
      { result: false, rejection: null, calls: [{ type: 'connection', error: true }] },
      { result: false, rejection: null, calls: [{ type: 'connection', error: true }] },
      { result: false, rejection: null, calls: [{ type: 'connection', error: true }] },
      { result: false, rejection: null, calls: [{ type: 'connection', error: true }] },
      {
        result: true, rejection: null, calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 2 },
          { type: 'message', text: 'after-reconnect', level: 2 }
        ]
      },
      {
        result: true, rejection: null, calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 0 }
        ]
      }
    ];
    expect(JSON.stringify(outcomes) === JSON.stringify(expected),
      'transport exact outcomes: ' + JSON.stringify(outcomes));
    expect(current.__runtimeEventExpectedConsole.length === 0,
      'missing expected transport console errors: ' +
        JSON.stringify(current.__runtimeEventExpectedConsole));
  }

  async function testValidationSchema() {
    const current = await newPage('validation-schema');
    const malformed = [
      withEvent({ Msg: 'missing-sequence', msglvl: 2 }),
      withEvent({ Msg: 42, msglvl: 2, messageSequence: 1 }),
      withEvent({ Msg: 'bad-level', msglvl: 256, messageSequence: 1 }),
      withEvent({ LogMsg: 42, messageSequence: 1 }),
      withEvent({ Msg: 'both', msglvl: 2, LogMsg: 'both', messageSequence: 1 }),
      withEvent({ messageSequence: 1 })
    ];
    const state = await routeTelemetry(current, async (route, cursor, index) => {
      const body = malformed[index];
      expect(!!body, 'missing response plan at request ' + index);
      await fulfillJson(route, body);
    });
    await openHarness(current);

    const outcomes = await pollWithSinks(current, malformed.map(() => ({})));
    expect(JSON.stringify(state.trace) === JSON.stringify([0, 0, 0, 0, 0, 0]),
      'schema validation cursor trace: ' + JSON.stringify(state.trace));
    const invalidOutcome = {
      result: false,
      rejection: null,
      calls: [{
        type: 'message',
        text: 'Ошибка обновления интерфейса: Некорректный контракт runtime-сообщения.',
        level: 1
      }]
    };
    const expected = malformed.map(() => invalidOutcome);
    expect(JSON.stringify(outcomes) === JSON.stringify(expected),
      'schema exact outcomes: ' + JSON.stringify(outcomes));
  }

  async function testValidationCommitOrder() {
    const current = await newPage('validation-commit');
    const plans = [
      { body: withEvent({ Msg: 'render-retry', msglvl: 2, messageSequence: 1 }) },
      { body: withEvent({ Msg: 'sink-retry', msglvl: 2, messageSequence: 1 }) },
      { body: withEvent({ Msg: 'accepted-message', msglvl: 2, messageSequence: 1 }) },
      { body: withEvent({ LogMsg: 'log-retry', messageSequence: 2 }) },
      { body: withEvent({ LogMsg: 'accepted-log', messageSequence: 2 }) },
      { body: withEvent({}) }
    ];
    const state = await routeTelemetry(current, async (route, cursor, index) => {
      const plan = plans[index];
      expect(!!plan, 'missing response plan at request ' + index);
      if (plan.raw !== undefined) {
        await fulfillJson(route, plan.raw, 200);
      } else {
        await fulfillJson(route, plan.body, plan.status);
      }
    });
    await openHarness(current);

    const outcomes = await pollWithSinks(current, [
      { throwRender: true },
      { throwSink: 'message' },
      {},
      { throwSink: 'log' },
      {},
      {}
    ]);
    expect(JSON.stringify(state.trace) === JSON.stringify([
      0, 0, 0, 1, 1, 2
    ]), 'failure/retry cursor trace: ' + JSON.stringify(state.trace));
    const expected = [
      {
        result: false, rejection: null, calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 1 },
          {
            type: 'message',
            text: 'Ошибка обновления интерфейса: planned renderer failure',
            level: 1
          }
        ]
      },
      {
        result: null, rejection: 'Error: planned message sink failure', calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 1 },
          { type: 'message', text: 'sink-retry', level: 2 },
          {
            type: 'message',
            text: 'Ошибка обновления интерфейса: planned message sink failure',
            level: 1
          }
        ]
      },
      {
        result: true, rejection: null, calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 1 },
          { type: 'message', text: 'accepted-message', level: 2 }
        ]
      },
      {
        result: false, rejection: null, calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 2 },
          { type: 'log', text: 'log-retry', sequence: 2 },
          {
            type: 'message',
            text: 'Ошибка обновления интерфейса: planned log sink failure',
            level: 1
          }
        ]
      },
      {
        result: true, rejection: null, calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 2 },
          { type: 'log', text: 'accepted-log', sequence: 2 }
        ]
      },
      {
        result: true, rejection: null, calls: [
          { type: 'connection', error: false },
          { type: 'render', sequence: 0 }
        ]
      }
    ];
    expect(JSON.stringify(outcomes) === JSON.stringify(expected),
      'commit exact outcomes: ' + JSON.stringify(outcomes));
  }

  async function testGapAndWarningPresentation() {
    const current = await newPage('gap');
    const state = await routeTelemetry(current, async (route, cursor) => {
      if (cursor === 0) {
        await fulfillJson(route, withEvent({ Msg: 'before-gap', msglvl: 2, messageSequence: 1 }));
      } else if (cursor === 1) {
        await fulfillJson(route, withEvent({ Msg: 'after-gap', msglvl: 2, messageSequence: 4 }));
      } else {
        await fulfillJson(route, withEvent({}));
      }
    });
    await openHarness(current);
    await current.evaluate(async () => {
      await SamovarApp.pollAjax(function () {});
      await SamovarApp.pollAjax(function () {});
      await SamovarApp.pollAjax(function () {});
    });
    expect(JSON.stringify(state.trace) === JSON.stringify([0, 1, 4]),
      'gap cursor trace: ' + JSON.stringify(state.trace));
    const presentation = await current.evaluate(warning => ({
      warningCount: Array.from(document.querySelectorAll('#messages .message_1'))
        .filter(node => node.textContent.includes(warning)).length,
      retainedCount: Array.from(document.querySelectorAll('#messages .message_2'))
        .filter(node => node.textContent.includes('after-gap')).length,
      orderedText: document.getElementById('messages').textContent,
      audioPlayCount: window.__audioPlayCount
    }), gapWarning);
    expect(presentation.warningCount === 1,
      'gap warning text/level count: ' + JSON.stringify(presentation));
    expect(presentation.retainedCount === 1,
      'retained event missing after gap: ' + JSON.stringify(presentation));
    expect(presentation.orderedText.indexOf(gapWarning) < presentation.orderedText.indexOf('after-gap'),
      'gap warning must precede retained event');
    expect(presentation.audioPlayCount === 0, 'gap warning triggered alarm audio');
  }

  async function testReload() {
    const reloadPage = await newPage('reload');
    const reloadState = await routeTelemetry(reloadPage, async (route, cursor) => {
      await fulfillJson(route, withEvent(cursor === 0
        ? { Msg: 'reload-event', msglvl: 2, messageSequence: 1 }
        : {}));
    });
    await openHarness(reloadPage);
    await pollWithSinks(reloadPage, {});
    await pollWithSinks(reloadPage, {});
    await reloadPage.reload({ waitUntil: 'load' });
    await pollWithSinks(reloadPage, {});
    expect(JSON.stringify(reloadState.trace) === JSON.stringify([0, 1, 0]),
      'reload must reset module-local cursor: ' + JSON.stringify(reloadState.trace));
  }

  async function testWrap() {
    const wrapPage = await newPage('wrap');
    let wrapRequest = 0;
    const wrapState = await routeTelemetry(wrapPage, async route => {
      const event = wrapRequest++ === 0
        ? { Msg: 'max-sequence', msglvl: 2, messageSequence: 4294967295 }
        : { Msg: 'wrapped-sequence', msglvl: 2, messageSequence: 1 };
      await fulfillJson(route, withEvent(event));
    });
    await openHarness(wrapPage);
    await wrapPage.evaluate(async () => {
      await SamovarApp.pollAjax(function () {});
      await SamovarApp.pollAjax(function () {});
    });
    const wrapWarning = await wrapPage.evaluate(warning =>
      document.getElementById('messages').textContent.includes(warning), gapWarning);
    expect(JSON.stringify(wrapState.trace) === JSON.stringify([0, 4294967295]),
      'wrap cursor trace: ' + JSON.stringify(wrapState.trace));
    expect(!wrapWarning, 'UINT32 wrap produced a false gap warning');
  }

  async function testRebootDiscontinuity() {
    const discontinuityPage = await newPage('reboot/discontinuity');
    const responses = [
      { Msg: 'old-1', msglvl: 2, messageSequence: 1 },
      { Msg: 'old-2', msglvl: 2, messageSequence: 2 },
      { Msg: 'old-3', msglvl: 2, messageSequence: 3 },
      { Msg: 'new-boot-1', msglvl: 2, messageSequence: 1 }
    ];
    const discontinuityState = await routeTelemetry(discontinuityPage, async (route, cursor, index) => {
      await fulfillJson(route, withEvent(responses[index] || {}));
    });
    await openHarness(discontinuityPage);
    for (let i = 0; i < responses.length; i++) {
      await discontinuityPage.evaluate(async () => SamovarApp.pollAjax(function () {}));
    }
    const discontinuity = await discontinuityPage.evaluate(warning => ({
      warningCount: Array.from(document.querySelectorAll('#messages .message_1'))
        .filter(node => node.textContent.includes(warning)).length,
      rebootEventCount: Array.from(document.querySelectorAll('#messages .message_2'))
        .filter(node => node.textContent.includes('new-boot-1')).length
    }), gapWarning);
    expect(JSON.stringify(discontinuityState.trace) === JSON.stringify([0, 1, 2, 3]),
      'detectable reboot cursor trace: ' + JSON.stringify(discontinuityState.trace));
    expect(discontinuity.warningCount === 1 && discontinuity.rebootEventCount === 1,
      'detectable reboot warning/event: ' + JSON.stringify(discontinuity));
  }

  async function testRebootCollision() {
    const collisionPage = await newPage('reboot/collision');
    let collisionRequest = 0;
    const collisionState = await routeTelemetry(collisionPage, async route => {
      const event = collisionRequest++ === 0
        ? { Msg: 'old-before-collision', msglvl: 2, messageSequence: 1 }
        : { Msg: 'new-boot-collision', msglvl: 2, messageSequence: 2 };
      await fulfillJson(route, withEvent(event));
    });
    await openHarness(collisionPage);
    await collisionPage.evaluate(async () => {
      await SamovarApp.pollAjax(function () {});
      await SamovarApp.pollAjax(function () {});
    });
    const collision = await collisionPage.evaluate(warning => ({
      hasWarning: document.getElementById('messages').textContent.includes(warning),
      eventCount: Array.from(document.querySelectorAll('#messages .message_2'))
        .filter(node => node.textContent.includes('new-boot-collision')).length
    }), gapWarning);
    expect(JSON.stringify(collisionState.trace) === JSON.stringify([0, 1]),
      'reboot collision cursor trace: ' + JSON.stringify(collisionState.trace));
    expect(!collision.hasWarning && collision.eventCount === 1,
      'reboot sequence collision must retain the documented no-warning limitation');
  }

  async function testLongConsoleEvent() {
    const current = await newPage('long-log');
    const longLog = 'L'.repeat(8691);
    const state = await routeTelemetry(current, async (route, cursor) => {
      await fulfillJson(route, withEvent(cursor === 0
        ? { LogMsg: longLog, messageSequence: 1 }
        : {}));
    });
    await openHarness(current);
    await pollWithSinks(current, {});
    await pollWithSinks(current, {});
    const logState = await current.evaluate(expected => {
      const logs = (window.__eventCalls || [])
        .filter(call => call.type === 'log').map(call => call.text);
      return {
        count: logs.length,
        exact: logs.length === 1 && logs[0] === expected,
        byteLength: logs.length === 1 ? new TextEncoder().encode(logs[0]).length : -1
      };
    }, longLog);
    expect(logState.count === 1, 'long console event count: ' + logState.count);
    expect(logState.exact, 'long console event was truncated or changed');
    expect(logState.byteLength === 8691,
      'long console event byte length changed');
    expect(JSON.stringify(state.trace) === JSON.stringify([0, 1]),
      'long console cursor trace: ' + JSON.stringify(state.trace));
  }

  async function testSingleInFlight() {
    const current = await newPage('in-flight');
    const state = await routeTelemetry(current, async (route, cursor) => {
      await fulfillJson(route, withEvent(cursor === 0
        ? { Msg: 'single-event', msglvl: 2, messageSequence: 1 }
        : {}), 200, 250);
    });
    await openHarness(current);
    await current.evaluate(async () => {
      window.__eventCalls = [];
      const sinks = {
        message: text => window.__eventCalls.push(text),
        log: text => window.__eventCalls.push(text),
        connection: function () {}
      };
      await Promise.all([
        SamovarApp.pollAjax(function () {}, sinks),
        SamovarApp.pollAjax(function () {}, sinks),
        SamovarApp.pollAjax(function () {}, sinks)
      ]);
      await SamovarApp.pollAjax(function () {}, sinks);
    });
    const delivered = await current.evaluate(() => window.__eventCalls);
    expect(state.maxActive === 1, 'concurrent telemetry requests: ' + state.maxActive);
    expect(JSON.stringify(state.trace) === JSON.stringify([0, 1]),
      'in-flight guard request trace: ' + JSON.stringify(state.trace));
    expect(JSON.stringify(delivered) === JSON.stringify(['single-event']),
      'one request delivered more than one event: ' + JSON.stringify(delivered));
  }

  async function installModeRoutes(current, messageText, logText) {
    const state = await routeTelemetry(current, async (route, cursor) => {
      let event = {};
      if (cursor === 0) {
        event = {
          Msg: messageText,
          msglvl: 0,
          messageSequence: 1,
          UseBBuzzer: true
        };
      }
      else if (cursor === 1) {
        event = { LogMsg: logText, messageSequence: 2, UseBBuzzer: true };
      }
      await fulfillJson(route, withEvent(event));
    });
    await current.route('**/ajax_col_params?*', route => fulfillJson(route, columnFixture));
    return state;
  }

  async function testModePage(file) {
    const current = await newPage('mode/' + file);
    await current.addInitScript(() => {
      window.__modeLogs = [];
      window.__modeAudioPlayCount = 0;
      window.__modeAudioPauseCount = 0;
      const nativeLog = console.log.bind(console);
      console.log = function () {
        window.__modeLogs.push(Array.from(arguments));
        nativeLog.apply(console, arguments);
      };
      window.Audio = function () {
        this.play = function () {
          window.__modeAudioPlayCount++;
          return Promise.resolve();
        };
        this.pause = function () { window.__modeAudioPauseCount++; };
      };
    });
    const messageText = 'message-' + file;
    const logText = 'log-' + file;
    const state = await installModeRoutes(current, messageText, logText);
    await current.goto(baseUrl + '/' + file, { waitUntil: 'load' });
    await current.waitForFunction(expected => {
      const node = document.getElementById('messages');
      return node && node.textContent.includes(expected);
    }, messageText, { timeout: 10000 });
    await current.waitForFunction(expected =>
      (window.__modeLogs || []).some(args => args[0] === '12:00:00; ' + expected),
      logText,
      { timeout: 5000 }
    );
    const result = await current.evaluate(values => {
      const history = JSON.parse(localStorage.getItem('samovarHistoryV2') || '[]');
      return {
        messageCount: Array.from(document.querySelectorAll('#messages .message_0'))
          .filter(node => node.textContent.includes(values.messageText)).length,
        logCount: (window.__modeLogs || [])
          .filter(args => args[0] === '12:00:00; ' + values.logText).length,
        updateErrors: (window.__modeLogs || [])
          .filter(args => args[0] === 'UI update error:').length,
        audioPlayCount: window.__modeAudioPlayCount,
        audioPauseCount: window.__modeAudioPauseCount,
        history: history
      };
    }, { messageText, logText });
    expect(JSON.stringify(state.trace) === JSON.stringify([0, 1]),
      file + ' MESSAGE/CONSOLE cursor trace: ' + JSON.stringify(state.trace));
    expect(result.messageCount === 1 && result.logCount === 1 && result.updateErrors === 0 &&
      result.audioPlayCount === 1 && result.audioPauseCount === 0 &&
      result.history.length === 1 && result.history[0].msg === messageText &&
      result.history[0].cssClass === 'message_0',
      file + ' default sinks/duplicates: ' + JSON.stringify(result));
    const lifecycle = await current.evaluate(expectedMessage => {
      SamovarApp.showHistory();
      const historyVisible = document.getElementById('historyBox').style.display === 'block';
      const historyText = document.getElementById('historyList').textContent;
      SamovarApp.clearHistory();
      const historyRawAfterClear = localStorage.getItem('samovarHistoryV2');
      const historyTextAfterClear = document.getElementById('historyList').textContent;
      SamovarApp.clearMessages();
      const messagesHidden = document.getElementById('messagesBox').style.display === 'none';
      SamovarApp.addMessage('post-clear-marker', 2);
      const messagesTextAfterRepopulate = document.getElementById('messages').textContent;
      return {
        historyVisible: historyVisible,
        historyContainsMessage: historyText.includes(expectedMessage),
        historyRawAfterClear: historyRawAfterClear,
        historyTextAfterClear: historyTextAfterClear,
        messagesHidden: messagesHidden,
        repopulatedOnlyWithMarker: messagesTextAfterRepopulate.includes('post-clear-marker') &&
          !messagesTextAfterRepopulate.includes(expectedMessage),
        audioPlayCount: window.__modeAudioPlayCount,
        audioPauseCount: window.__modeAudioPauseCount
      };
    }, messageText);
    expect(lifecycle.historyVisible && lifecycle.historyContainsMessage &&
      lifecycle.historyRawAfterClear === '[]' && lifecycle.historyTextAfterClear === '' &&
      lifecycle.messagesHidden && lifecycle.repopulatedOnlyWithMarker &&
      lifecycle.audioPlayCount === 1 && lifecycle.audioPauseCount === 1,
      file + ' clear/history/sound lifecycle: ' + JSON.stringify(lifecycle));
  }

  async function testChartUsesSharedLifecycleAndSharedSinks() {
    const current = await newPage('chart');
    let releaseWrappers;
    const wrappersReady = new Promise(resolve => { releaseWrappers = resolve; });
    await current.addInitScript(() => {
      window.__chartLogs = [];
      const nativeLog = console.log.bind(console);
      console.log = function () {
        window.__chartLogs.push(Array.from(arguments));
        nativeLog.apply(console, arguments);
      };
      window.Audio = function () {
        this.play = function () { return Promise.resolve(); };
        this.pause = function () {};
      };
    });
    const state = await routeTelemetry(current, async (route, cursor) => {
      if (cursor === 0) await wrappersReady;
      let event = {};
      if (cursor === 0) {
        event = {
          Msg: 'chart-message', msglvl: 2, messageSequence: 1, crnt_tm: '12:00:01'
        };
      } else if (cursor === 1) {
        event = { LogMsg: 'chart-log', messageSequence: 2, crnt_tm: '12:00:02' };
      }
      await fulfillJson(route, withEvent(event), 200, 2250);
    });
    await current.route('**/data.csv', route => route.fulfill({
      status: 200, contentType: 'text/csv', body: ''
    }));
    await current.goto(baseUrl + '/chart.htm', { waitUntil: 'load' });
    await current.waitForFunction(() => chart && typeof chart.appendAjaxPoint === 'function');
    await current.evaluate(() => {
      window.__chartRendererCalls = [];
      window.__chartAppendCalls = [];
      const nativeRendererAppend = window.appendChartPoint;
      window.appendChartPoint = function (telemetry) {
        window.__chartRendererCalls.push({
          crnt_tm: telemetry.crnt_tm,
          messageSequence: telemetry.messageSequence
        });
        return nativeRendererAppend(telemetry);
      };
      const nativeAppend = chart.appendAjaxPoint.bind(chart);
      chart.appendAjaxPoint = function (telemetry) {
        window.__chartAppendCalls.push({
          crnt_tm: telemetry.crnt_tm,
          messageSequence: telemetry.messageSequence
        });
        return nativeAppend(telemetry);
      };
    });
    releaseWrappers();
    await current.waitForFunction(
      () => window.__chartRendererCalls &&
        window.__chartRendererCalls.some(call => call.messageSequence === 2) &&
        (window.__chartLogs || []).some(args => args[0] === '12:00:02; chart-log'),
      null,
      { timeout: 12000 }
    );
    const chartState = await current.evaluate(() => ({
        rendererCalls: window.__chartRendererCalls.slice(),
        appendCalls: window.__chartAppendCalls.slice(),
        messageCount: Array.from(document.querySelectorAll('#messages .message_2'))
          .filter(node => node.textContent.includes('chart-message')).length,
        sharedQueueCount: document.querySelectorAll(
          '#messages > .message_0, #messages > .message_1, #messages > .message_2'
        ).length,
        logCount: (window.__chartLogs || [])
          .filter(args => args[0] === '12:00:02; chart-log').length,
        sharedHistory: localStorage.getItem('samovarHistoryV2')
      }));
    expect(JSON.stringify(state.trace) === JSON.stringify([0, 1]),
      'chart cursor trace: ' + JSON.stringify(state.trace));
    expect(state.maxActive === 1, 'chart concurrent telemetry requests: ' + state.maxActive);
    expect(JSON.stringify(chartState.rendererCalls) === JSON.stringify([
      { crnt_tm: '12:00:01', messageSequence: 1 },
      { crnt_tm: '12:00:02', messageSequence: 2 }
    ]), 'chart renderer calls: ' + JSON.stringify(chartState.rendererCalls));
    expect(JSON.stringify(chartState.appendCalls) === JSON.stringify([
      { crnt_tm: '12:00:01', messageSequence: 1 }
    ]), 'chart append calls: ' + JSON.stringify(chartState.appendCalls));
    expect(chartState.messageCount === 1 && chartState.sharedQueueCount === 1,
      'chart shared message sink: ' + JSON.stringify(chartState));
    expect(chartState.logCount === 1, 'chart shared log sink: ' + JSON.stringify(chartState));
    expect(chartState.sharedHistory === null,
      'chart message leaked into shared app history: ' + chartState.sharedHistory);
  }

  const selectedCase = __CASE_NAME__;
  const cases = {
    validation_transport: testValidationTransport,
    validation_schema: testValidationSchema,
    validation_commit: testValidationCommitOrder,
    gap: testGapAndWarningPresentation,
    reload: testReload,
    wrap: testWrap,
    reboot_discontinuity: testRebootDiscontinuity,
    reboot_collision: testRebootCollision,
    long_log: testLongConsoleEvent,
    in_flight: testSingleInFlight,
    mode_index: function () { return testModePage('index.htm'); },
    mode_beer: function () { return testModePage('beer.htm'); },
    mode_distiller: function () { return testModePage('distiller.htm'); },
    mode_bk: function () { return testModePage('bk.htm'); },
    mode_nbk: function () { return testModePage('nbk.htm'); },
    chart: testChartUsesSharedLifecycleAndSharedSinks
  };
  expect(Object.prototype.hasOwnProperty.call(cases, selectedCase),
    'unknown runtime event browser case: ' + selectedCase);
  await cases[selectedCase]();
  if (problems.length) throw new Error(problems.join('\n'));
  return { case: selectedCase, status: 'passed' };
}'''


COMMON_BROWSER_FUNCTIONS = (
    "expect",
    "cursorFrom",
    "withEvent",
    "trackPage",
    "newPage",
    "routeTelemetry",
    "fulfillJson",
)

CASE_BROWSER_FUNCTIONS = {
    "validation_transport": ("openHarness", "pollWithSinks", "testValidationTransport"),
    "validation_schema": ("openHarness", "pollWithSinks", "testValidationSchema"),
    "validation_commit": ("openHarness", "pollWithSinks", "testValidationCommitOrder"),
    "gap": ("openHarness", "testGapAndWarningPresentation"),
    "reload": ("openHarness", "pollWithSinks", "testReload"),
    "wrap": ("openHarness", "testWrap"),
    "reboot_discontinuity": ("openHarness", "testRebootDiscontinuity"),
    "reboot_collision": ("openHarness", "testRebootCollision"),
    "long_log": ("openHarness", "pollWithSinks", "testLongConsoleEvent"),
    "in_flight": ("openHarness", "testSingleInFlight"),
    "mode_index": ("installModeRoutes", "testModePage"),
    "mode_beer": ("installModeRoutes", "testModePage"),
    "mode_distiller": ("installModeRoutes", "testModePage"),
    "mode_bk": ("installModeRoutes", "testModePage"),
    "mode_nbk": ("installModeRoutes", "testModePage"),
    "chart": ("testChartUsesSharedLifecycleAndSharedSinks",),
}

CASE_BROWSER_CALLS = {
    "validation_transport": "await testValidationTransport();",
    "validation_schema": "await testValidationSchema();",
    "validation_commit": "await testValidationCommitOrder();",
    "gap": "await testGapAndWarningPresentation();",
    "reload": "await testReload();",
    "wrap": "await testWrap();",
    "reboot_discontinuity": "await testRebootDiscontinuity();",
    "reboot_collision": "await testRebootCollision();",
    "long_log": "await testLongConsoleEvent();",
    "in_flight": "await testSingleInFlight();",
    "mode_index": "await testModePage('index.htm');",
    "mode_beer": "await testModePage('beer.htm');",
    "mode_distiller": "await testModePage('distiller.htm');",
    "mode_bk": "await testModePage('bk.htm');",
    "mode_nbk": "await testModePage('nbk.htm');",
    "chart": "await testChartUsesSharedLifecycleAndSharedSinks();",
}


def browser_function_source(name: str) -> str:
    markers = (f"\n  function {name}(", f"\n  async function {name}(")
    starts = [BROWSER_TEST.find(marker) for marker in markers]
    starts = [start for start in starts if start >= 0]
    if not starts:
        raise RuntimeError(f"runtime event browser function is missing: {name}")
    start = min(starts) + 1
    ends = [
        BROWSER_TEST.find(marker, start + 1)
        for marker in ("\n  function ", "\n  async function ", "\n  const selectedCase")
    ]
    ends = [end for end in ends if end >= 0]
    if not ends:
        raise RuntimeError(f"runtime event browser function end is missing: {name}")
    return BROWSER_TEST[start:min(ends)]


def browser_case_source(case: str, base_url: str) -> str:
    header_end = BROWSER_TEST.index("\n  function expect")
    parts = [BROWSER_TEST[:header_end]]
    for name in COMMON_BROWSER_FUNCTIONS + CASE_BROWSER_FUNCTIONS[case]:
        parts.append(browser_function_source(name))
    parts.extend((
        "\n  " + CASE_BROWSER_CALLS[case],
        "\n  if (problems.length) throw new Error(problems.join('\\n'));",
        "\n  return { case: " + json.dumps(case) + ", status: 'passed' };",
        "\n}",
    ))
    return "\n".join(parts).replace("__BASE_URL__", base_url)


def run_cli_capture(
    cli: str,
    session: str,
    arguments: list[str],
    cwd: Path,
    timeout: int,
) -> str:
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
    if result.returncode != 0 or "### Error" in result.stdout:
        raise RuntimeError(f"playwright-cli {' '.join(arguments[:1])} failed")
    return result.stdout


def parse_cli_result(output: str) -> object:
    marker = "### Result\n"
    if marker not in output:
        raise RuntimeError("playwright-cli result payload is missing")
    payload = output.split(marker, 1)[1].splitlines()[0]
    return json.loads(payload)


def cleanup(
    cli: str,
    sessions: list[str],
    server: http.server.ThreadingHTTPServer,
    thread: threading.Thread,
) -> list[str]:
    errors = []
    for session in sessions:
        try:
            if run_cli(cli, session, ["close"], ROOT, 30, check=False) != 0:
                errors.append(f"playwright-cli close failed: {session}")
        except (OSError, subprocess.TimeoutExpired) as error:
            errors.append(f"playwright-cli close failed for {session}: {error}")
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
        print("playwright-cli is required for the runtime event browser gate", file=sys.stderr)
        return 2

    primary_error = None
    cleanup_errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="samovar-runtime-event-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        (site / "event_harness.htm").write_text(HARNESS_HTML, encoding="utf-8")
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session_prefix = f"samovar-runtime-event-ui-{os.getpid()}"
        client_sessions = [
            session_prefix + "-client-a",
            session_prefix + "-client-b",
        ]
        case_sessions = {
            case: session_prefix + "-" + case.replace("_", "-")
            for case in CASE_NAMES
        }
        sessions = client_sessions + list(case_sessions.values())
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
            base_url_text = f"http://127.0.0.1:{server.server_port}"
            base_url = json.dumps(base_url_text)
            case_urls = {}
            for case in CASE_NAMES:
                filename = "runtime-event-" + case.replace("_", "-") + ".js"
                (site / filename).write_text(
                    browser_case_source(case, base_url), encoding="utf-8"
                )
                case_urls[case] = json.dumps(f"{base_url_text}/{filename}")
            independent_results = []
            for client_name, session, delay_ms in zip(
                ("client-a", "client-b"), client_sessions, (15, 40), strict=True
            ):
                try:
                    run_cli(cli, session, open_args, temp, 30)
                    code = INDEPENDENT_CONTEXT_TEST.replace("__BASE_URL__", base_url).replace(
                        "__DELAY_MS__", str(delay_ms)
                    )
                    output = run_cli_capture(cli, session, ["run-code", code], temp, 60)
                    independent_results.append(parse_cli_result(output))
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                    raise RuntimeError(f"independent/{client_name}: {error}") from error
                finally:
                    run_cli(cli, session, ["close"], temp, 30, check=False)
            if independent_results[0] != independent_results[1]:
                raise RuntimeError(
                    "independent browser contexts received different event streams: "
                    + repr(independent_results)
                )

            for case in CASE_NAMES:
                session = case_sessions[case]
                try:
                    run_cli(cli, session, open_args, temp, 30)
                    code = (
                        "async page => {"
                        f"const response=await page.request.get({case_urls[case]});"
                        "if(!response.ok())throw new Error('runtime case fetch failed: '+response.status());"
                        "const source=await response.text();"
                        "const test=eval(source);"
                        "return await test(page);"
                        "}"
                    )
                    output = run_cli_capture(cli, session, ["run-code", code], temp, 90)
                    result = parse_cli_result(output)
                    if result != {"case": case, "status": "passed"}:
                        raise RuntimeError(f"unexpected result: {result!r}")
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                    raise RuntimeError(f"{case}: {error}") from error
                finally:
                    run_cli(cli, session, ["close"], temp, 30, check=False)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, sessions, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Runtime event UI browser gate failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Runtime event UI browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Runtime event UI browser gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
