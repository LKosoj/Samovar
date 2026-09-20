#!/usr/bin/env python3
"""Playwright gate for the address-based I2CStepper v3 web UI."""

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

from test_numeric_input_ui_browser import UI_BOOTSTRAP_FIXTURE, render_site


ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def run_cli(cli, session, arguments, cwd):
    result = subprocess.run(
        [cli, f"-s={session}", *arguments], cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30, check=False,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode or result.stdout.startswith("### Error") or "\n### Error" in result.stdout:
        raise RuntimeError("playwright-cli " + arguments[0] + " failed:\n" + result.stdout)


SETUP = r'''async page => {
  const bootstrap = __BOOTSTRAP__;
  const makeDevice = (address, present, filling) => ({
    present, address, everPresent: present, capabilities: filling ? 12 : 9,
    config: {address, mode: filling ? 3 : 1, optionFlags:0, sensorFlags:0, relayMask:0,
      mixerRpm:120, mixerRunSec:30, mixerPauseSec:10, pumpMlHour:100,
      pumpPauseSec:5, fillingMl:100, fillingMlHour:100, stepsPerMl:160},
    motion: {mode:filling ? 3 : 1, direction:0, speedStepsPerSec:100, targetSteps:1000},
    status: {mode:filling ? 3 : 1, flags:0, result:0, error:0, stopReason:0,
      generation:1, currentSpeedStepsPerSec:0, remainingSteps:0}
  });
  const s = page.__v3 = {
    devices: Array.from({length:10}, (_, index) => makeDevice(index + 1, index === 1, index === 1)),
    requests: [], mutations: [], calibrationSteps: 321
  };
  page.on('console', message => {
    if (message.type() === 'error' && !message.text().includes('Failed to load resource')) {
      s.consoleError = message.text();
    }
  });
  page.on('request', request => {
    const url = request.url();
    if (url.includes('/i2cstepper?') || url.includes('/calibrate?')) s.requests.push(url);
  });
  await page.route('**/ui-bootstrap', route => route.fulfill({
    status:200, contentType:'application/json',
    body:JSON.stringify({...bootstrap, i2cStepperVisible:true, i2cPumpVisible:true,
      i2cSteppers:s.devices, processRunning:false, calibrationRunning:false})
  }));
  s.selected = s.devices[1];
  async function routeStatus() {
    await page.route('**/i2cstepper?*', route => route.fulfill({
      status:200, contentType:'application/json',
      body:JSON.stringify({scanning:0, selected:s.selected, devices:s.devices})
    }));
  }
  await routeStatus();
  await page.route('**/ajax?operationId=*', route => route.fulfill({
    status:200, contentType:'application/json', body:'{"operationId":1,"state":"succeeded","error":"none"}'
  }));
  await page.route('**/calibrate?*', route => {
    return route.fulfill({status:202, contentType:'application/json',
      body:'{"operationId":1,"state":"queued","error":"none"}'});
  });
  await page.route('**/ajax?messageCursor=*', route => route.fulfill({
    status:200, contentType:'application/json', body:'{"StepperStepMl":100}'
  }));
}'''


CHECK_SELECTION = r'''async page => {
  const base = __BASE__;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  async function open(address) {
    await page.goto(base + '/i2cstepper.htm?address=' + address, {waitUntil:'load'});
    await page.waitForFunction(() => typeof selected !== 'undefined' && document.getElementById('panel'));
    await page.waitForTimeout(20);
  }

  await open(2);
  let view = await page.evaluate(() => ({panel:document.getElementById('panel').hidden,
    title:document.getElementById('title').textContent, selector:document.getElementById('selectorRow').hidden}));
  check(!view.panel, 'selected present address must render #panel');
  check(view.title.includes('адрес 2'), 'panel must render selected address');
  check(view.selector, 'selector must stay hidden for one present device');
  check(s.requests.some(url => url.includes('/i2cstepper?address=2')), 'status request must carry selected address');
  await page.waitForTimeout(2100);
  check(s.requests.filter(url => url.includes('/i2cstepper?address=2')).length >= 2,
    'current polling must keep the chosen address');

  s.devices[2] = {
    ...s.devices[1], address:3, present:true,
    config:{...s.devices[1].config, address:3, mode:1},
    motion:{...s.devices[1].motion, mode:1}, status:{...s.devices[1].status, mode:1}
  };
  await open(2);
  view = await page.evaluate(() => ({selector:document.getElementById('selectorRow').hidden}));
  check(!view.selector, 'selector must render for two present devices');
  s.selected = s.devices[2];
  await page.evaluate(() => { document.getElementById('selector').value = '3'; window.choose(); });
  await page.waitForURL('**/i2cstepper.htm?address=3');
  await page.waitForTimeout(20);
  view = await page.evaluate(() => ({title:document.getElementById('title').textContent}));
  check(view.title.includes('адрес 3'), 'selector must keep the explicitly chosen address');

  s.devices[1].present = false;
  s.selected = s.devices[1];
  await open(2);
  view = await page.evaluate(() => ({panel:document.getElementById('panel').hidden,
    missing:document.getElementById('missing').textContent}));
  check(view.panel, 'lost selected address must hide panel');
  check(view.missing.includes('не выбрано автоматически'), 'lost selected address must not fail over');
  return 'selection';
}'''


CHECK_ACTIONS = r'''async page => {
  const base = __BASE__;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  async function open(address) {
    await page.goto(base + '/i2cstepper.htm?address=' + address, {waitUntil:'load'});
    await page.waitForFunction(() => typeof selected !== 'undefined' && document.getElementById('panel'));
  }

  await open(2);
  const beforeCommands = s.requests.length;
  async function acceptCommand(call) {
    await page.unroute('**/i2cstepper?*');
    await page.route('**/i2cstepper?*', route => {
      const url = route.request().url();
      if (!url.includes('cmd=save') && url.includes('newAddress=')) {
        return route.fulfill({status:400, contentType:'application/json', body:'{"error":"newAddress"}'});
      }
      return route.fulfill({status:202, contentType:'application/json',
        body:'{"operationId":1,"state":"queued","error":"none"}'});
    });
    await call();
    await page.unroute('**/i2cstepper?*');
    await routeStatus();
    await page.evaluate(() => refresh());
  }
  await acceptCommand(() => page.evaluate(() => {
    document.getElementById('speed').value = '1.5';
    document.getElementById('volume').value = '250';
    return window.startWithSpeed();
  }));
  await acceptCommand(() => page.evaluate(() => window.command('relay', {relay:1, state:1})));
  await acceptCommand(() => page.evaluate(() => window.command('stop')));
  const mutations = s.requests.slice(beforeCommands).filter(url =>
    url.includes('/i2cstepper?') && /[?&]cmd=(speed|relay|stop)(?:&|$)/.test(url));
  check(mutations.length === 3 && mutations.every(url => /[?&]address=2(?:&|$)/.test(url)),
    'all commands must carry address=2: ' + JSON.stringify(mutations));
  const start = mutations.find(url => /[?&]cmd=speed(?:&|$)/.test(url));
  check(start && !start.includes('newAddress='), 'start must omit newAddress');
  check(mutations.every(url => !url.includes('newAddress=')),
    'operational commands must omit address configuration');
  check(mutations.some(url => /cmd=speed/.test(url) && /value=1500(?:&|$)/.test(url) && /volume=250(?:&|$)/.test(url)),
    'start must carry speed in ml/h and volume in ml');
  const operationView = await page.evaluate(() => ({save:document.getElementById('newAddress'), mode:document.getElementById('mode'),
    speedMax:document.getElementById('speed').max}));
  check(!operationView.save && !operationView.mode, 'operational page must not render Nano configuration controls');
  check(operationView.speedMax === '65.535', 'pump speed input must be in litres per hour');

  await page.unroute('**/i2cstepper?*');
  await routeStatus();
  await page.goto(base + '/calibrate.htm?address=2', {waitUntil:'load'});
  await page.waitForFunction(() => typeof calibrate === 'function' && document.body.inert === false);
  let view = await page.evaluate(() => ({title:document.getElementById('title').textContent,
    save:Boolean(document.getElementById('save'))}));
  check(view.title === 'Калибровка внешнего I2C-насоса', 'external title mismatch');
  check(!view.save, 'external calibration must not render the local save button');
  await page.evaluate(() => { document.getElementById('kstepperspd').value = '200'; });
  const beforeCalibration = s.requests.length;
  await page.unroute('**/i2cstepper?*');
  await page.route('**/i2cstepper?*', route => route.fulfill({status:202,
    contentType:'application/json', body:'{"operationId":1,"state":"queued","error":"none"}'}));
  await page.evaluate(async () => { await calibrate(); });
  await page.unroute('**/i2cstepper?*');
  s.selected.config.stepsPerMl = s.calibrationSteps;
  await routeStatus();
  await page.evaluate(async () => { await calibrate(); });
  const calibration = s.requests.slice(beforeCalibration).filter(url => url.includes('/calibrate?'));
  check(calibration[0].endsWith('/calibrate?address=2&stpstep=200&start=1'), 'external start must be addressed');
  check(calibration[1].endsWith('/calibrate?address=2&finish=1'), 'external finish must be addressed');
  view = await page.evaluate(() => ({steps:document.getElementById('stepperstepml').value}));
  check(view.steps === '321', 'external finish must show Nano readback');
  check(!s.consoleError, s.consoleError || 'console error');
  return {requests:s.requests.length, mutations:mutations.length + calibration.length};
}'''


CHECK_SETUP_SAVE = r'''async page => {
  const base = __BASE__;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  // Плавный разгон (2) включён вместе с обратным направлением (4): снять должны только свой бит.
  s.selected.config.optionFlags = 6;
  await page.goto(base + '/setup.htm', {waitUntil:'load'});
  await page.waitForFunction(() => typeof saveSetupI2c === 'function' && document.getElementById('i2c-panel'));
  await page.waitForTimeout(20);
  await page.evaluate(() => SamovarApp.openTab(null, 'I2CStepper'));
  let view = await page.evaluate(() => ({tab:document.getElementById('i2cStepperSetupTab').hidden,
    panel:document.getElementById('i2c-panel').hidden,
    selector:document.getElementById('i2c-selectorRow').hidden,
    operationalSave:document.getElementById('newAddress')}));
  check(!view.tab && !view.panel, 'setup must show settings for the selected Nano');
  check(view.selector, 'setup selector must stay hidden for one Nano');
  check(!view.operationalSave, 'setup must not depend on the operational-page form');
  check(await page.isChecked('#i2c-smoothStart'), 'smooth start checkbox must reflect optionFlags bit 2');
  await page.click('label[for="i2c-smoothStart"]');
  check(!await page.isChecked('#i2c-smoothStart'), 'label click must toggle the smooth start checkbox');
  await page.unroute('**/i2cstepper?*');
  let saved = '';
  await page.route('**/i2cstepper?*', route => {
    const url = route.request().url();
    if (url.includes('cmd=save')) {
      saved = url;
      return route.fulfill({status:202, contentType:'application/json',
        body:'{"operationId":1,"state":"queued","error":"none"}'});
    }
    return route.fulfill({status:200, contentType:'application/json',
      body:JSON.stringify({selected:s.selected, devices:s.devices})});
  });
  await page.evaluate(async () => { await saveSetupI2c(); });
  check(saved.includes('address=2') && saved.includes('cmd=save'),
    'setup save must target the selected address: ' + saved);
  check(saved.includes('newAddress=2') && saved.includes('stepsPerMl=160'),
    'setup save must send Nano configuration: ' + saved);
  check(/[?&]optionFlags=4(?:&|$)/.test(saved),
    'unchecked smooth start must clear only its own optionFlags bit: ' + saved);
  check(saved.includes('generation=1'),
    'setup save must carry the config generation the form was filled from: ' + saved);
  check(!s.consoleError, s.consoleError || 'console error');
  return 'setup-save';
}'''


CHECK_SETUP_SCAN = r'''async page => {
  const base = __BASE__;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  s.devices.forEach(device => { device.present = false; device.everPresent = false; });
  s.selected = s.devices[0];
  await page.unroute('**/i2cstepper?*');
  let scanStarted = false;
  let scanPolls = 0;
  await page.route('**/i2cstepper?*', route => {
    const requestUrl = route.request().url();
    if (requestUrl.includes('cmd=scan')) {
      scanStarted = true;
      return route.fulfill({status:202, contentType:'application/json',
        body:'{"operationId":1,"state":"queued","error":"none"}'});
    }
    let scanning = 0;
    if (scanStarted) {
      scanPolls++;
      scanning = scanPolls < 2 ? 1 : 0;
      if (!scanning) {
        s.devices[1].present = true;
        s.devices[1].everPresent = true;
      }
    }
    const addressMatch = requestUrl.match(/[?&]address=(\d+)/);
    const address = addressMatch ? Number(addressMatch[1]) : 1;
    const selected = s.devices[address - 1] || s.devices[0];
    return route.fulfill({status:200, contentType:'application/json',
      body:JSON.stringify({scanning, selected, devices:s.devices})});
  });
  await page.goto(base + '/setup.htm', {waitUntil:'load'});
  await page.waitForFunction(() => typeof rescanSetupI2c === 'function' &&
    document.getElementById('i2c-missing').textContent === 'I2CStepper не найден.');
  await page.evaluate(() => SamovarApp.openTab(null, 'I2CStepper'));
  let view = await page.evaluate(() => ({
    tab:document.getElementById('i2cStepperSetupTab').hidden,
    button:document.getElementById('i2c-scan').textContent,
    missing:document.getElementById('i2c-missing').textContent
  }));
  check(!view.tab, 'I2CStepper tab must remain visible without devices');
  check(view.button === 'Пересканировать I2C-устройства', 'manual scan button is missing');
  check(view.missing === 'I2CStepper не найден.', 'missing-device text is unclear');
  await page.locator('#i2c-scan').click();
  await page.waitForFunction(() => document.getElementById('i2c-panel').hidden === false);
  view = await page.evaluate(() => ({
    address:setupI2cAddress,
    button:document.getElementById('i2c-scan').textContent,
    disabled:document.getElementById('i2c-scan').disabled
  }));
  check(scanStarted && scanPolls >= 2, 'manual scan was not polled to completion');
  check(view.address === 2, 'first device found by manual scan was not opened');
  check(!view.disabled && view.button === 'Пересканировать I2C-устройства',
    'scan button did not return to idle state');
  check(s.requests.some(url => url.includes('cmd=scan')), 'scan request was not sent');
  check(!s.consoleError, s.consoleError || 'console error');
  return 'setup-scan';
}'''


def main():
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-v3-browser-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-i2c-v3-{os.getpid()}"
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser": {"browserName": "chromium",
                "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp)
            def body(script):
                return script[len("async page => {"):-1]

            def scenario_code(check):
                return "async page => { await page.unroute('**/*');" + body(SETUP).replace(
                    "__BOOTSTRAP__", json.dumps(UI_BOOTSTRAP_FIXTURE)) + body(check).replace(
                        "__BASE__", json.dumps(f"http://127.0.0.1:{server.server_port}")) + "}"

            for check in (CHECK_SELECTION, CHECK_ACTIONS, CHECK_SETUP_SAVE, CHECK_SETUP_SCAN):
                run_cli(cli, session, ["run-code", scenario_code(check)], temp)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            print("I2C v3 browser gate failed: " + str(error), file=sys.stderr)
            return 1
        finally:
            subprocess.run([cli, f"-s={session}", "close"], cwd=temp, capture_output=True, text=True)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    print("I2C v3 browser gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
