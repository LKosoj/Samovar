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

HARNESS = r'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="app.js"></script>
</head>
<body>
  <button id="themeToggle" title="Переключить тему">☾</button>
  <div id="connection_indicator"></div>
  <div id="GreenT"></div><div id="RedT" style="visibility:hidden;position:fixed"></div>
  <div id="messagesBox" style="display:none"><div id="messages"></div></div>
  <div id="historyBox" style="display:none"><div id="historyList"></div></div>
</body>
</html>'''

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const artifactDir = __ARTIFACT_DIR__;
  const modePages = ['index.htm', 'beer.htm', 'distiller.htm', 'bk.htm', 'nbk.htm'];
  const pages = modePages.concat(['chart.htm']);
  const viewports = [
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'mobile', width: 390, height: 844 }
  ];
  const themeCases = [
    { name: 'saved-light-system-light', saved: 'light', system: 'light' },
    { name: 'saved-light-system-dark', saved: 'light', system: 'dark' },
    { name: 'saved-dark-system-light', saved: 'dark', system: 'light' },
    { name: 'saved-dark-system-dark', saved: 'dark', system: 'dark' },
    { name: 'implicit-system-light', saved: null, system: 'light' },
    { name: 'implicit-system-dark', saved: null, system: 'dark' }
  ];
  const fixture = {
    version: 'test', crnt_tm: '12:00:00', stm: '00:01:00', SteamTemp: 78.123,
    PipeTemp: 77.912, WaterTemp: 20.234, TankTemp: 82.345, ACPTemp: 40.456,
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
  const mutationRequests = [];
  let ajaxRequests = [];
  let csvRequests = [];
  let scenario = 'bootstrap';

  function expect(condition, message) {
    if (!condition) throw new Error(message);
  }

  function track(current, label, expectedPageErrors) {
    current.__u06Label = label;
    current.__u06ExpectedPageErrors = (expectedPageErrors || []).slice();
    if (current.__u06Tracked) return current;
    current.__u06Tracked = true;
    current.on('console', message => {
      if (message.type() === 'warning' || message.type() === 'error') {
        problems.push(current.__u06Label + ' console ' + message.type() + ': ' + message.text());
      }
    });
    current.on('pageerror', error => {
      const expected = current.__u06ExpectedPageErrors.shift();
      if (expected && error.message.includes(expected)) return;
      problems.push(current.__u06Label + ' pageerror: ' + error.message);
    });
    current.on('request', request => {
      const requestUrl = request.url();
      const mutationPaths = ['/command', '/program', '/save', '/i2cpump', '/i2cstepper'];
      if (mutationPaths.some(path =>
          requestUrl === baseUrl + path || requestUrl.startsWith(baseUrl + path + '?'))) {
        mutationRequests.push({ label: current.__u06Label, method: request.method(), url: request.url() });
      }
    });
    return current;
  }

  async function installInstrumentation(current) {
    await current.addInitScript(() => {
      window.__u06Trace = [];
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
      const nativeFetch = window.fetch.bind(window);
      window.fetch = function (input, options) {
        const url = typeof input === 'string' ? input : input.url;
        if (String(url).startsWith('/ajax?messageCursor=')) {
          window.__u06Trace.push({ type: 'fetch', url: String(url) });
        }
        return nativeFetch(input, options);
      };
      const nativeSetAttribute = Element.prototype.setAttribute;
      Element.prototype.setAttribute = function (name, value) {
        const result = nativeSetAttribute.call(this, name, value);
        if (this === document.documentElement && name === 'data-theme') {
          window.__u06Trace.push({
            type: 'theme-apply', readyState: document.readyState,
            hasToggle: !!document.getElementById('themeToggle'), attribute: String(value)
          });
        }
        return result;
      };
      const nativeRemoveAttribute = Element.prototype.removeAttribute;
      Element.prototype.removeAttribute = function (name) {
        const result = nativeRemoveAttribute.call(this, name);
        if (this === document.documentElement && name === 'data-theme') {
          window.__u06Trace.push({
            type: 'theme-apply', readyState: document.readyState,
            hasToggle: !!document.getElementById('themeToggle'), attribute: null
          });
        }
        return result;
      };
      Object.defineProperty(window, 'SamovarApp', {
        configurable: true,
        get: function () { return undefined; },
        set: function (app) {
          const nativeStart = app.startTelemetryPage;
          app.startTelemetryPage = function (renderFn, options) {
            window.__u06Trace.push({
              type: 'start',
              options: Object.assign({}, options || {}, { onReady: !!(options && options.onReady) })
            });
            const wrapped = Object.assign({}, options || {});
            if (typeof wrapped.onReady === 'function') {
              const ready = wrapped.onReady;
              wrapped.onReady = function () {
                window.__u06Trace.push({ type: 'ready' });
                return ready();
              };
            }
            const result = nativeStart.call(app, function (data) {
              window.__u06Trace.push({ type: 'render', time: data.crnt_tm || '' });
              return renderFn(data);
            }, wrapped);
            window.__u06Trace.push({ type: 'start-return' });
            return result;
          };
          Object.defineProperty(window, 'SamovarApp', {
            configurable: true, enumerable: true, writable: true, value: app
          });
        }
      });
    });
  }

  async function installRoutes(current) {
    await current.route('**/ajax?messageCursor=*', route => {
      ajaxRequests.push({ label: current.__u06Label, url: route.request().url() });
      return route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(fixture)
      });
    });
    await current.route('**/ajax_col_params?*', route => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(columnFixture)
    }));
    await current.route('**/data.csv', route => {
      csvRequests.push({ label: current.__u06Label, url: route.request().url() });
      return route.fulfill({
        status: 200, contentType: 'text/csv',
        body: 'Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\n'
      });
    });
  }

  async function setThemeStorage(current, saved) {
    await current.goto(baseUrl + '/app.js', { waitUntil: 'load' });
    await current.evaluate(value => {
      localStorage.clear();
      if (value !== null) localStorage.setItem('theme', value);
    }, saved);
  }

  function expectedTheme(file, saved, system) {
    const chart = file === 'chart.htm';
    const effective = saved || system;
    return {
      attribute: saved || (chart ? null : system),
      glyph: effective === 'dark' ? '☼' : '☾',
      title: chart
        ? (effective === 'dark' ? 'Светлая тема' : 'Тёмная тема')
        : 'Переключить тему'
    };
  }

  track(page, 'matrix');
  await installInstrumentation(page);
  await installRoutes(page);
  let matrixCount = 0;
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const themeCase of themeCases) {
      await page.emulateMedia({ colorScheme: themeCase.system });
      for (const file of pages) {
        scenario = viewport.name + '/' + themeCase.name + '/' + file;
        page.__u06Label = scenario;
        await setThemeStorage(page, themeCase.saved);
        const ajaxStart = ajaxRequests.length;
        const csvStart = csvRequests.length;
        await page.goto(baseUrl + '/' + file, { waitUntil: 'load' });
        await page.waitForFunction(() =>
          document.getElementById('SteamTemp') && document.getElementById('SteamTemp').textContent !== '',
          null, { timeout: 5000 }
        );
        const state = await page.evaluate(() => ({
          attribute: document.documentElement.getAttribute('data-theme'),
          glyph: document.getElementById('themeToggle').textContent,
          title: document.getElementById('themeToggle').title,
          steam: document.getElementById('SteamTemp').textContent,
          trace: window.__u06Trace.slice()
        }));
        const expected = expectedTheme(file, themeCase.saved, themeCase.system);
        expect(state.attribute === expected.attribute && state.glyph === expected.glyph &&
          state.title === expected.title,
          scenario + ' theme mismatch: ' + JSON.stringify(state));
        const expectedPrecision = file === 'nbk.htm' ? '78.1' : '78.123';
        expect(state.steam === expectedPrecision,
          scenario + ' telemetry precision mismatch: ' + state.steam);
        expect(ajaxRequests.length - ajaxStart === 1,
          scenario + ' initial telemetry request count: ' + (ajaxRequests.length - ajaxStart));
        expect(csvRequests.length - csvStart === (file === 'chart.htm' ? 1 : 0),
          scenario + ' CSV request count: ' + (csvRequests.length - csvStart));

        const themes = state.trace.filter(item => item.type === 'theme-apply');
        const starts = state.trace.filter(item => item.type === 'start');
        const tags = state.trace.map(item => item.type);
        expect(starts.length === 1, scenario + ' lifecycle starts: ' + JSON.stringify(state.trace));
        const options = starts[0].options;
        expect(options.storeMessageHistory === (file !== 'chart.htm') &&
          options.dynamicThemeTitle === (file === 'chart.htm') &&
          options.implicitSystemTheme === (file === 'chart.htm'),
          scenario + ' lifecycle policy mismatch: ' + JSON.stringify(options));
        expect(options.threshold === (file === 'nbk.htm' ? 4 : (file === 'chart.htm' ? 1 : 3)),
          scenario + ' threshold mismatch: ' + options.threshold);
        if (file === 'chart.htm') {
          expect(themes.length === 2 && themes[0].readyState === 'loading' &&
            !themes[0].hasToggle && themes[1].hasToggle,
            scenario + ' parse/DCL theme trace: ' + JSON.stringify(themes));
          expect(tags.indexOf('theme-apply') < tags.indexOf('start') &&
            tags.indexOf('start') < tags.lastIndexOf('theme-apply') &&
            tags.lastIndexOf('theme-apply') < tags.indexOf('ready') &&
            tags.indexOf('ready') < tags.indexOf('fetch') &&
            tags.indexOf('fetch') < tags.indexOf('render'),
            scenario + ' chart startup order: ' + JSON.stringify(tags));
        } else {
          expect(themes.length === 1 && themes[0].hasToggle,
            scenario + ' mode theme count: ' + JSON.stringify(themes));
          expect(tags.indexOf('start') < tags.indexOf('theme-apply') &&
            tags.indexOf('theme-apply') < tags.indexOf('ready') &&
            tags.indexOf('ready') < tags.indexOf('fetch') &&
            tags.indexOf('fetch') < tags.indexOf('render'),
            scenario + ' mode startup order: ' + JSON.stringify(tags));
        }
        if (themeCase.name === 'saved-light-system-light' ||
            themeCase.name === 'saved-dark-system-dark') {
          await page.evaluate(() => new Promise(resolve =>
            requestAnimationFrame(() => requestAnimationFrame(resolve))
          ));
          await page.screenshot({
            path: artifactDir + '/' + file.replace('.htm', '') + '-' + viewport.name + '-' +
              themeCase.saved + '.png',
            fullPage: true
          });
        }
        matrixCount++;
      }
    }
  }
  expect(matrixCount === 72, 'expected 72 page/theme/viewport matrix cases, got ' + matrixCount);

  async function verifyToggle(file, saved, system, next) {
    scenario = 'toggle/' + file + '/' + String(saved) + '/' + system;
    page.__u06Label = scenario;
    await page.emulateMedia({ colorScheme: system });
    await setThemeStorage(page, saved);
    await page.goto(baseUrl + '/' + file, { waitUntil: 'load' });
    await page.waitForFunction(() =>
      document.getElementById('SteamTemp') && document.getElementById('SteamTemp').textContent !== ''
    );
    await page.click('#themeToggle');
    let state = await page.evaluate(() => ({
      attribute: document.documentElement.getAttribute('data-theme'),
      saved: localStorage.getItem('theme'),
      glyph: document.getElementById('themeToggle').textContent,
      title: document.getElementById('themeToggle').title
    }));
    expect(state.attribute === next && state.saved === next,
      scenario + ' toggle mismatch: ' + JSON.stringify(state));
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() =>
      document.getElementById('SteamTemp') && document.getElementById('SteamTemp').textContent !== ''
    );
    state = await page.evaluate(() => ({
      attribute: document.documentElement.getAttribute('data-theme'),
      saved: localStorage.getItem('theme')
    }));
    expect(state.attribute === next && state.saved === next,
      scenario + ' reload mismatch: ' + JSON.stringify(state));
  }

  await verifyToggle('chart.htm', null, 'light', 'dark');
  await verifyToggle('chart.htm', null, 'dark', 'light');
  await verifyToggle('chart.htm', 'light', 'dark', 'dark');
  await verifyToggle('chart.htm', 'dark', 'light', 'light');
  await verifyToggle('index.htm', null, 'light', 'dark');
  await verifyToggle('index.htm', null, 'dark', 'light');
  await verifyToggle('index.htm', 'light', 'dark', 'dark');
  await verifyToggle('index.htm', 'dark', 'light', 'light');

  async function faultPage(label, file, getDenied, setDenied, system, clickToggle) {
    const current = await page.context().newPage();
    track(current, label, file === 'index.htm' && getDenied
      ? ['theme get denied']
      : (file === 'index.htm' && setDenied ? ['theme set denied'] : []));
    await current.addInitScript(config => {
      window.Audio = function () {
        this.play = function () { return Promise.resolve(); };
        this.pause = function () {};
      };
      const nativeGet = Storage.prototype.getItem;
      const nativeSet = Storage.prototype.setItem;
      Storage.prototype.getItem = function (key) {
        if (config.getDenied && key === 'theme') throw new Error('theme get denied');
        return nativeGet.call(this, key);
      };
      Storage.prototype.setItem = function (key, value) {
        if (config.setDenied && key === 'theme') throw new Error('theme set denied');
        return nativeSet.call(this, key, value);
      };
    }, { getDenied, setDenied });
    await installRoutes(current);
    await current.emulateMedia({ colorScheme: system });
    await current.goto(baseUrl + '/app.js', { waitUntil: 'load' });
    await current.evaluate(() => localStorage.clear());
    await current.goto(baseUrl + '/' + file, { waitUntil: 'load' });
    if (file === 'chart.htm') {
      await current.waitForFunction(() => document.getElementById('SteamTemp').textContent !== '');
    } else if (!getDenied) {
      await current.waitForFunction(() => document.getElementById('SteamTemp').textContent !== '');
    }
    const before = await current.evaluate(() => ({
      attribute: document.documentElement.getAttribute('data-theme'),
      glyph: document.getElementById('themeToggle').textContent,
      title: document.getElementById('themeToggle').title
    }));
    if (clickToggle) {
      await current.click('#themeToggle');
      await current.waitForTimeout(25);
    }
    const after = await current.evaluate(() => ({
      attribute: document.documentElement.getAttribute('data-theme'),
      glyph: document.getElementById('themeToggle').textContent,
      title: document.getElementById('themeToggle').title
    }));
    let afterReload = null;
    let reloadStorage = null;
    if (file === 'chart.htm' && clickToggle) {
      await current.reload({ waitUntil: 'load' });
      await current.waitForFunction(() =>
        document.getElementById('SteamTemp').textContent !== ''
      );
      afterReload = await current.evaluate(() => ({
        attribute: document.documentElement.getAttribute('data-theme'),
        glyph: document.getElementById('themeToggle').textContent,
        title: document.getElementById('themeToggle').title
      }));
      reloadStorage = await current.evaluate(() => {
        const state = { get: null, set: null };
        try { state.get = localStorage.getItem('theme'); }
        catch (error) { state.get = error.message; }
        try { localStorage.setItem('theme', 'probe'); }
        catch (error) { state.set = error.message; }
        return state;
      });
    }
    const expectedErrorsRemaining = current.__u06ExpectedPageErrors.length;
    await current.close();
    expect(expectedErrorsRemaining === 0, label + ' missing expected pageerror');
    return { before, after, afterReload, reloadStorage };
  }

  for (const system of ['light', 'dark']) {
    const implicitGlyph = system === 'dark' ? '☼' : '☾';
    const implicitTitle = system === 'dark' ? 'Светлая тема' : 'Тёмная тема';
    let fault = await faultPage('fault/chart-get-' + system, 'chart.htm', true, false, system, false);
    expect(fault.before.attribute === null && fault.before.glyph === implicitGlyph,
      'chart get-denied implicit mismatch/' + system + ': ' + JSON.stringify(fault));
    fault = await faultPage('fault/chart-set-' + system, 'chart.htm', false, true, system, true);
    expect(fault.before.attribute === null &&
      fault.after.attribute === (system === 'dark' ? 'light' : 'dark'),
      'chart set-denied current DOM mismatch/' + system + ': ' + JSON.stringify(fault));
    expect(fault.afterReload.attribute === null &&
      fault.afterReload.glyph === implicitGlyph && fault.afterReload.title === implicitTitle &&
      fault.reloadStorage.get === null && fault.reloadStorage.set === 'theme set denied',
      'chart set-denied reload mismatch/' + system + ': ' + JSON.stringify(fault));
    fault = await faultPage('fault/chart-both-' + system, 'chart.htm', true, true, system, true);
    expect(fault.before.attribute === null &&
      fault.after.attribute === (system === 'dark' ? 'light' : 'dark'),
      'chart combined storage-denied mismatch/' + system + ': ' + JSON.stringify(fault));
    expect(fault.afterReload.attribute === null &&
      fault.afterReload.glyph === implicitGlyph && fault.afterReload.title === implicitTitle &&
      fault.reloadStorage.get === 'theme get denied' &&
      fault.reloadStorage.set === 'theme set denied',
      'chart combined storage-denied reload mismatch/' + system + ': ' + JSON.stringify(fault));
  }
  const modeGetFault = await faultPage(
    'fault/mode-get', 'index.htm', true, false, 'dark', false
  );
  expect(modeGetFault.before.attribute === null,
    'mode get-denied must fail loud without implicit substitution: ' + JSON.stringify(modeGetFault));
  const modeSetFault = await faultPage(
    'fault/mode-set', 'index.htm', false, true, 'light', true
  );
  expect(modeSetFault.before.attribute === 'light' && modeSetFault.after.attribute === 'light',
    'mode set-denied changed DOM theme: ' + JSON.stringify(modeSetFault));

  async function openHarness(label) {
    const current = await page.context().newPage();
    track(current, label);
    await installInstrumentation(current);
    await installRoutes(current);
    await current.goto(baseUrl + '/harness.htm', { waitUntil: 'load' });
    await current.evaluate(() => localStorage.clear());
    return current;
  }

  const validationPage = await openHarness('validation');
  const validation = await validationPage.evaluate(() => {
    const result = {};
    try {
      SamovarApp.startTelemetryPage(function () {}, { unknown: true });
    } catch (error) { result.unknown = error.message; }
    document.getElementById('connection_indicator').remove();
    try {
      SamovarApp.startTelemetryPage(function () {}, {
        threshold: 3, storeMessageHistory: true,
        dynamicThemeTitle: false, implicitSystemTheme: false
      });
    } catch (error) { result.missing = error.message; }
    return result;
  });
  expect(validation.unknown.includes('Неизвестная опция telemetry lifecycle') &&
    validation.missing.includes('#connection_indicator'),
    'fail-loud lifecycle validation mismatch: ' + JSON.stringify(validation));
  await validationPage.close();

  const connectionPage = await openHarness('connection-chart');
  const connection = await connectionPage.evaluate(async () => {
    window.__removed = [];
    window.__pause = true;
    SamovarApp.startTelemetryPage(function () {}, {
      threshold: 1,
      connectionIds: { online: 'GreenT', offline: 'RedT' },
      storeMessageHistory: false,
      dynamicThemeTitle: true,
      implicitSystemTheme: true,
      onLastMessageRemoved: function (remainingCount) {
        window.__removed.push(remainingCount);
        if (remainingCount === 0) window.__pause = false;
      }
    });
    await new Promise(resolve => setTimeout(resolve, 25));
    function state() {
      return {
        green: document.getElementById('GreenT').style.cssText,
        red: document.getElementById('RedT').style.cssText,
        messages: document.querySelectorAll(
          '#messages > .message_0, #messages > .message_1, #messages > .message_2'
        ).length,
        play: window.__audioPlayCount,
        pause: window.__audioPauseCount
      };
    }
    SamovarApp.setConnectionError();
    const first = state();
    SamovarApp.setConnectionError();
    await new Promise(resolve => setTimeout(resolve, 125));
    const second = state();
    SamovarApp.setConnectionError();
    SamovarApp.setConnectionError();
    await new Promise(resolve => setTimeout(resolve, 125));
    const repeated = state();
    SamovarApp.setConnectionOk();
    const recovered = state();

    SamovarApp.clearMessages();
    window.__removed = [];
    window.__pause = true;
    SamovarApp.addMessage('first', 2);
    SamovarApp.addMessage('second', 2);
    SamovarApp.removeLastMessage();
    const afterTwoToOne = { removed: window.__removed.slice(), pause: window.__pause };
    SamovarApp.removeLastMessage();
    const afterOneToZero = { removed: window.__removed.slice(), pause: window.__pause };
    SamovarApp.removeLastMessage();
    const afterEmpty = { removed: window.__removed.slice(), pause: window.__pause };
    window.__pause = true;
    SamovarApp.addMessage('clear-only', 2);
    SamovarApp.clearMessages();
    const afterClear = { removed: window.__removed.slice(), pause: window.__pause };
    let duplicate = '';
    try {
      SamovarApp.startTelemetryPage(function () {}, {
        threshold: 1, connectionIds: { online: 'GreenT', offline: 'RedT' },
        storeMessageHistory: false, dynamicThemeTitle: true, implicitSystemTheme: true
      });
    } catch (error) { duplicate = error.message; }
    return {
      first, second, repeated, recovered, afterTwoToOne, afterOneToZero,
      afterEmpty, afterClear, duplicate,
      history: localStorage.getItem('samovarHistoryV2')
    };
  });
  expect(connection.first.messages === 0 && connection.first.red.includes('hidden'),
    'chart first connection failure mismatch: ' + JSON.stringify(connection.first));
  expect(connection.second.messages === 1 && connection.second.green.includes('hidden') &&
    connection.second.red === '' && connection.second.play === 1,
    'chart second connection failure mismatch: ' + JSON.stringify(connection.second));
  expect(connection.repeated.messages === 1 && connection.repeated.play === 1,
    'chart repeated offline failure duplicated alarm: ' + JSON.stringify(connection.repeated));
  expect(connection.recovered.green === '' && connection.recovered.red.includes('hidden') &&
    connection.recovered.pause === connection.repeated.pause,
    'chart recovery changed alarm audio/visibility: ' + JSON.stringify(connection.recovered));
  expect(JSON.stringify(connection.afterTwoToOne) === JSON.stringify({ removed: [1], pause: true }) &&
    JSON.stringify(connection.afterOneToZero) === JSON.stringify({ removed: [1, 0], pause: false }) &&
    JSON.stringify(connection.afterEmpty) === JSON.stringify({ removed: [1, 0], pause: false }) &&
    JSON.stringify(connection.afterClear) === JSON.stringify({ removed: [1, 0], pause: true }),
    'message removal/clear callback parity: ' + JSON.stringify(connection));
  expect(connection.history === null && connection.duplicate.includes('уже запущен'),
    'chart history/duplicate contract mismatch: ' + JSON.stringify(connection));
  await connectionPage.close();

  const modeConnectionPage = await openHarness('connection-mode');
  const modeConnection = await modeConnectionPage.evaluate(async () => {
    SamovarApp.startTelemetryPage(function () {}, {
      threshold: 3, storeMessageHistory: true,
      dynamicThemeTitle: false, implicitSystemTheme: false
    });
    await new Promise(resolve => setTimeout(resolve, 25));
    SamovarApp.setConnectionError();
    SamovarApp.setConnectionError();
    SamovarApp.setConnectionError();
    const before = document.getElementById('connection_indicator').innerHTML;
    SamovarApp.setConnectionError();
    const after = document.getElementById('connection_indicator').innerHTML;
    return { before, after };
  });
  expect(modeConnection.before.includes('Green.png') && modeConnection.after.includes('Red_light.gif'),
    'mode threshold parity mismatch: ' + JSON.stringify(modeConnection));
  await modeConnectionPage.close();

  const pollPage = await openHarness('polling');
  const polling = await pollPage.evaluate(async () => {
    const nativeSetTimeout = window.setTimeout.bind(window);
    const loopTimers = [];
    const requests = [];
    const logs = [];
    const plans = [
      { kind: 'deferred', body: { crnt_tm: '12:00:00' } },
      { kind: 'http' },
      { kind: 'malformed' },
      { kind: 'reject' },
      { kind: 'timeout' },
      { kind: 'json', body: { crnt_tm: '12:00:01', Msg: 'first', msglvl: 2, messageSequence: 1 } },
      { kind: 'json', body: { crnt_tm: '12:00:02', Msg: 'third', msglvl: 1, messageSequence: 3 } },
      { kind: 'json', body: { crnt_tm: '12:00:03', LogMsg: 'fourth-log', messageSequence: 4 } },
      { kind: 'json', body: { crnt_tm: '12:00:04' } }
    ];
    let active = 0;
    let maxActive = 0;
    let releaseFirst;
    window.setTimeout = function (fn, delay) {
      if (delay === 2000) {
        loopTimers.push(fn);
        return 100000 + loopTimers.length;
      }
      if (delay === 4000) return nativeSetTimeout(fn, 20);
      return nativeSetTimeout(fn, delay);
    };
    const nativeLog = console.log.bind(console);
    console.log = function () {
      logs.push(Array.from(arguments));
      nativeLog.apply(console, arguments);
    };
    window.fetch = function (url, options) {
      const plan = plans.shift();
      if (!plan) return Promise.reject(new Error('missing fetch plan'));
      requests.push(String(url));
      active++;
      maxActive = Math.max(maxActive, active);
      function finish(response) {
        active--;
        return response;
      }
      if (plan.kind === 'deferred') {
        return new Promise(resolve => {
          releaseFirst = function () {
            resolve(finish(new Response(JSON.stringify(plan.body), {
              status: 200, headers: { 'Content-Type': 'application/json' }
            })));
          };
        });
      }
      if (plan.kind === 'http') {
        return Promise.resolve(finish(new Response('{}', {
          status: 503, headers: { 'Content-Type': 'application/json' }
        })));
      }
      if (plan.kind === 'malformed') {
        return Promise.resolve(finish(new Response('{', {
          status: 200, headers: { 'Content-Type': 'application/json' }
        })));
      }
      if (plan.kind === 'reject') {
        active--;
        return Promise.reject(new Error('planned transport rejection'));
      }
      if (plan.kind === 'timeout') {
        return new Promise((resolve, reject) => {
          options.signal.addEventListener('abort', function () {
            active--;
            reject(new DOMException('planned timeout', 'AbortError'));
          }, { once: true });
        });
      }
      return Promise.resolve(finish(new Response(JSON.stringify(plan.body), {
        status: 200, headers: { 'Content-Type': 'application/json' }
      })));
    };

    const renders = [];
    SamovarApp.startTelemetryPage(data => renders.push(data.crnt_tm), {
      threshold: 100, storeMessageHistory: true,
      dynamicThemeTitle: false, implicitSystemTheme: false
    });
    await Promise.resolve();
    const concurrentResult = await SamovarApp.pollAjax(function () {});
    const noTimerWhilePending = loopTimers.length === 0;
    releaseFirst();
    while (loopTimers.length === 0) await new Promise(resolve => nativeSetTimeout(resolve, 0));
    async function next() {
      const timer = loopTimers.shift();
      if (!timer) throw new Error('missing lifecycle timer');
      await timer();
      while (loopTimers.length === 0) await new Promise(resolve => nativeSetTimeout(resolve, 0));
    }
    for (let index = 1; index < 9; index++) await next();
    return {
      concurrentResult, noTimerWhilePending, requests, renders, maxActive,
      loopTimers: loopTimers.length,
      messages: document.getElementById('messages').textContent,
      history: JSON.parse(localStorage.getItem('samovarHistoryV2') || '[]'),
      logCount: logs.filter(args => args[0] === '12:00:03; fourth-log').length
    };
  });
  expect(polling.concurrentResult === false && polling.noTimerWhilePending &&
    polling.maxActive === 1 && polling.loopTimers === 1,
    'non-overlapping lifecycle mismatch: ' + JSON.stringify(polling));
  expect(JSON.stringify(polling.requests) === JSON.stringify([
    '/ajax?messageCursor=0', '/ajax?messageCursor=0', '/ajax?messageCursor=0',
    '/ajax?messageCursor=0', '/ajax?messageCursor=0', '/ajax?messageCursor=0',
    '/ajax?messageCursor=1', '/ajax?messageCursor=3', '/ajax?messageCursor=4'
  ]), 'failure/recovery cursor trace: ' + JSON.stringify(polling.requests));
  expect(JSON.stringify(polling.renders) === JSON.stringify([
    '12:00:00', '12:00:01', '12:00:02', '12:00:03', '12:00:04'
  ]), 'render success trace: ' + JSON.stringify(polling.renders));
  expect(polling.messages.includes('first') && polling.messages.includes('third') &&
    polling.messages.includes('Пропущены сообщения') && polling.logCount === 1 &&
    polling.history.length === 3,
    'event/gap/log/history contract mismatch: ' + JSON.stringify(polling));
  await pollPage.close();

  scenario = 'chart-refresh-throttle';
  page.__u06Label = scenario;
  await setThemeStorage(page, 'light');
  await page.goto(baseUrl + '/chart.htm', { waitUntil: 'load' });
  await page.waitForFunction(() => window.chart && document.querySelector('.chart-status'));
  const chartBehavior = await page.evaluate(data => {
    const refresh = [];
    const nativeRefresh = chart.setAutoRefresh.bind(chart);
    chart.setAutoRefresh = function (enabled) {
      refresh.push(enabled);
      return nativeRefresh(enabled);
    };
    document.getElementById('refresh').checked = false;
    refresh_chart();
    const appends = [];
    const nativeAppend = chart.appendAjaxPoint.bind(chart);
    chart.appendAjaxPoint = function (value) {
      appends.push(value.crnt_tm);
      return nativeAppend(value);
    };
    const nativeNow = Date.now;
    let now = 20000;
    Date.now = function () { return now; };
    chartLastAppendMs = 0;
    renderTelemetry(Object.assign({}, data, { crnt_tm: '12:01:00' }));
    renderTelemetry(Object.assign({}, data, { crnt_tm: '12:01:01' }));
    now = 35000;
    renderTelemetry(Object.assign({}, data, { crnt_tm: '12:01:15' }));
    Date.now = nativeNow;
    return { refresh, appends };
  }, fixture);
  expect(JSON.stringify(chartBehavior.refresh) === JSON.stringify([false]) &&
    JSON.stringify(chartBehavior.appends) === JSON.stringify(['12:01:00', '12:01:15']),
    'chart refresh/throttle mismatch: ' + JSON.stringify(chartBehavior));

  const csvErrorPage = await page.context().newPage();
  track(csvErrorPage, 'chart-csv-error');
  await csvErrorPage.addInitScript(() => {
    window.Audio = function () {
      this.play = function () { return Promise.resolve(); };
      this.pause = function () {};
    };
    const nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, options) {
      const url = typeof input === 'string' ? input : input.url;
      if (String(url) === 'data.csv') return Promise.reject(new Error('planned CSV failure'));
      return nativeFetch(input, options);
    };
  });
  await installRoutes(csvErrorPage);
  await csvErrorPage.goto(baseUrl + '/chart.htm', { waitUntil: 'load' });
  await csvErrorPage.waitForFunction(() =>
    document.querySelector('.chart-status-error') &&
    document.querySelector('.chart-status-error').textContent.includes('planned CSV failure')
  );
  await csvErrorPage.close();

  expect(mutationRequests.length === 0,
    'startup/controller introduced mutation requests: ' + JSON.stringify(mutationRequests));
  if (problems.length) throw new Error(problems.join('\n'));
  return {
    matrixCount,
    toggleCases: 8,
    storageFaultCases: 8,
    screenshots: 24,
    pollingRequests: polling.requests.length
  };
}'''


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def run_cli(cli: str, session: str, arguments: list[str], cwd: Path, timeout: int,
            check: bool = True) -> int:
    result = subprocess.run(
        [cli, f"-s={session}", *arguments], cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False, timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if check and (result.returncode != 0 or "### Error" in result.stdout):
        raise RuntimeError(f"playwright-cli {' '.join(arguments[:1])} failed")
    return result.returncode


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the shared controller browser gate", file=sys.stderr)
        return 2
    version = subprocess.run([cli, "--version"], capture_output=True, text=True).stdout.strip()
    if version != "0.1.17":
        print(f"playwright-cli 0.1.17 is required, got {version or 'unknown'}", file=sys.stderr)
        return 2

    primary_error = None
    cleanup_errors: list[str] = []
    artifact_dir = Path(f"/tmp/samovar-u06-browser-artifacts-{os.getpid()}")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="samovar-shared-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        (site / "harness.htm").write_text(HARNESS, encoding="utf-8")
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-shared-ui-{os.getpid()}"
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({
                "browser": {
                    "browserName": "chromium",
                    "launchOptions": {"chromiumSandbox": False},
                }
            }), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            browser_test = (BROWSER_TEST
                .replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
                .replace("__ARTIFACT_DIR__", json.dumps(str(artifact_dir))))
            run_cli(cli, session, ["run-code", browser_test], temp, 180)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            try:
                if run_cli(cli, session, ["close"], temp, 30, check=False) != 0:
                    cleanup_errors.append("playwright-cli close failed")
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup_errors.append(f"playwright-cli close failed: {error}")
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if thread.is_alive():
                cleanup_errors.append("HTTP server thread did not stop")

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Shared UI controller browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Shared UI controller browser cleanup failed: {error}", file=sys.stderr)
        return 1
    print(f"Shared UI controller browser contract passed; artifacts: {artifact_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
