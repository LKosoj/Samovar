#!/usr/bin/env python3
"""Browser checks for physical sensor assignment and the separate device-test page."""
import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from test_numeric_input_ui_browser import render_site
from test_profile_operation_ui_browser import QuietHandler, cleanup, run_cli

ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const base = __BASE_URL__;
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  let sensorPending = true, sensorFailure = false;
  let temperatures = [21.25, 37.75];
  await page.route('**/sensor-temperatures*', async route => {
    if (sensorFailure) return route.fulfill({status: 503, body: 'BUSY'});
    if (route.request().url().includes('refresh=')) sensorPending = true;
    const pending = sensorPending;
    sensorPending = false;
    await route.fulfill({json: {pending, sensors: [
      {address: '28aa001122334455', temperature: temperatures[0]},
      {address: '28bb001122334466', temperature: temperatures[1]}
    ]}});
  });
  await page.route('**/i2cstepper*', route => route.fulfill({json: {devices: [], selected: null, scanning: 0}}));
  let state = {active: false, device: 0, waterPump: true, capacity: true};
  let posts = [], commandFailure = false;
  await page.route('**/device-test', async route => {
    if (route.request().method() === 'POST') {
      const device = route.request().postDataJSON().device;
      posts.push(device);
      if (commandFailure) return route.fulfill({status: 409, body: 'BUSY'});
      state.active = device !== 'stop';
      state.device = {valve: 1, waterPump: 2, stepper: 3, capacity: 4}[device] || 0;
      return route.fulfill({status: 202, body: 'QUEUED'});
    }
    return route.fulfill({json: state});
  });
  await page.goto(base + '/setup.htm');
  await page.waitForFunction(() => document.getElementById('sensorTemperaturesStatus').textContent.includes('Показания без поправок'));
  if (!(await page.locator('#SteamAddr option[value="0"]').textContent()).includes('21.25')) {
    throw new Error('physical address must show its own temperature');
  }
  const initial = await page.locator('#PipeAddr option[value="1"]').textContent();
  if (!initial.includes('37.75')) throw new Error('physical address must show its own temperature');
  await page.evaluate(() => {
    document.getElementById('SteamAddr').value = '1';
    document.getElementById('Kp').value = '2.75';
    document.getElementById('setupform').dataset.dirty = 'true';
  });
  temperatures = [29.5, 43.125];
  await page.evaluate(() => refreshSensorTemperatures());
  const refreshed = await page.evaluate(() => ({
    first: document.querySelector('#SteamAddr option[value="0"]').textContent,
    second: document.querySelector('#SteamAddr option[value="1"]').textContent,
    selected: document.getElementById('SteamAddr').value,
    kp: document.getElementById('Kp').value,
    dirty: document.getElementById('setupform').dataset.dirty
  }));
  if (!refreshed.first.includes('29.50') || !refreshed.second.includes('43.13') ||
      refreshed.selected !== '1' || refreshed.kp !== '2.75' || refreshed.dirty !== 'true') {
    throw new Error('physical sensor refresh must preserve each address and unsaved settings: ' + JSON.stringify(refreshed));
  }
  temperatures = [null, 18.5];
  await page.evaluate(() => refreshSensorTemperatures());
  if (!(await page.locator('#SteamAddr option[value="0"]').textContent()).includes('нет показаний')) {
    throw new Error('invalid physical readings must be explicit');
  }
  sensorFailure = true;
  await page.evaluate(() => refreshSensorTemperatures());
  if (!(await page.locator('#sensorTemperaturesStatus').textContent()).includes('HTTP 503') ||
      await page.locator('#refreshSensorTemperaturesButton').isDisabled()) {
    throw new Error('sensor refresh failure must be visible and retryable');
  }
  sensorFailure = false;
  temperatures = [29.5, 43.125];
  await page.evaluate(() => refreshSensorTemperatures());
  await page.locator('[onclick*="openTab(event, \'Temp\')"]').click();
  await page.setViewportSize({width: 390, height: 844});
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) {
    throw new Error('physical sensor addresses and readings overflow the mobile viewport');
  }
  await page.screenshot({path: __ARTIFACT_DIR__ + '/setup-sensors-mobile.png', fullPage: true});
  await page.locator('[onclick*="openTab(event, \'Beer\')"]').click();
  const beerText = await page.locator('#Beer').innerText();
  for (const explanation of ['ПИД-регулятор', 'реакция на отклонение', 'устранение длительного недогрева', 'торможение нагрева']) {
    if (!beerText.includes(explanation)) throw new Error('missing heating explanation: ' + explanation);
  }
  for (const viewport of [{width: 1440, height: 900}, {width: 390, height: 844}]) {
    await page.setViewportSize(viewport);
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) {
      throw new Error('PID explanations overflow viewport ' + viewport.width);
    }
  }
  await page.screenshot({path: __ARTIFACT_DIR__ + '/setup-pid-mobile.png', fullPage: true});
  await page.evaluate(() => { document.getElementById('setupform').dataset.dirty = 'false'; });
  await page.goto(base + '/device-test.htm');
  await page.waitForFunction(() => !document.querySelector('[data-test-device="valve"]').disabled);
  for (const device of ['valve', 'waterPump', 'stepper', 'capacity']) {
    await page.locator('[data-test-device="' + device + '"]').click();
    await page.waitForFunction(() => document.getElementById('testStatus').textContent.includes('Выполняется:'));
    if (posts.at(-1) !== device) throw new Error('button must send its own device: ' + device);
    if (await page.locator('[data-test-device]:enabled').count() !== 0) throw new Error('another device can start during a test');
    await page.locator('#testStop').click();
    await page.waitForFunction(() => !document.querySelector('[data-test-device="valve"]').disabled);
    if (posts.at(-1) !== 'stop') throw new Error('stop must send the existing stop action');
  }
  commandFailure = true;
  await page.locator('[data-test-device="valve"]').click();
  await page.waitForFunction(() => document.getElementById('testStatus').textContent.includes('Идёт процесс'));
  await page.evaluate(() => pollDeviceTest());
  if (!(await page.locator('#testStatus').innerText()).includes('Идёт процесс')) {
    throw new Error('polling must preserve a rejected command explanation');
  }
  state.waterPump = false; state.capacity = false;
  await page.evaluate(() => pollDeviceTest());
  if (await page.locator('[data-test-device="waterPump"]').isVisible() ||
      await page.locator('[data-test-device="capacity"]').isVisible()) {
    throw new Error('unsupported physical devices must not be offered');
  }
  state.waterPump = true; state.capacity = true;
  await page.evaluate(() => pollDeviceTest());
  await page.evaluate(() => { testError = ''; });
  await page.evaluate(() => pollDeviceTest());
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height: 900});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) {
      throw new Error('device interface overflows viewport ' + width);
    }
    await page.screenshot({path: __ARTIFACT_DIR__ + '/device-test-' + width + '.png', fullPage: true});
  }
  if (errors.length) throw new Error('page errors: ' + JSON.stringify(errors));
  return 'device setup browser checks passed';
}'''


def main():
    cli = shutil.which('playwright-cli')
    if not cli:
        raise RuntimeError('playwright-cli is required')
    artifacts = Path('/tmp/samovar-device-setup-browser')
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='samovar-device-setup-ui-') as directory:
        temp = Path(directory)
        site = temp / 'site'
        render_site(site)
        setup_path = site / 'setup.htm'
        original_setup = setup_path.read_text()
        setup = original_setup.replace('<option value="-1" selected>-</option>',
            '<option value="-1">NONE</option><option value="0" selected>28aa001122334455</option><option value="1">28bb001122334466</option>')
        setup_path.write_text(setup)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f'samovar-device-setup-{os.getpid()}'
        config = temp / 'playwright.json'
        config.write_text(json.dumps({'browser': {'browserName': 'chromium', 'launchOptions': {'chromiumSandbox': False}}}))
        code = BROWSER_TEST.replace('__BASE_URL__', json.dumps(f'http://127.0.0.1:{server.server_port}'))
        code = code.replace('__ARTIFACT_DIR__', json.dumps(str(artifacts)))
        try:
            run_cli(cli, session, ['open', f'--config={config}'], temp, 30)
            run_cli(cli, session, ['run-code', code], temp, 120)
            # A real source mutation must fail on the address-specific reading assertion.
            mutated = setup.replace('sensor.temperature.toFixed(2)', '(25).toFixed(2)')
            if mutated == setup:
                raise AssertionError('physical temperature mutation anchor missing')
            setup_path.write_text(mutated)
            try:
                run_cli(cli, session, ['run-code', code], temp, 120)
            except RuntimeError as error:
                if 'physical address must show its own temperature' not in str(error).split('### Ran Playwright code', 1)[0]:
                    raise
            else:
                raise AssertionError('physical temperature UI mutation was not rejected')
        finally:
            problems = cleanup(cli, session, server, thread)
            if problems:
                raise RuntimeError('; '.join(problems))
    print(f'Device setup browser checks passed; screenshots: {artifacts}')


if __name__ == '__main__':
    main()
