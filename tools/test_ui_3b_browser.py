#!/usr/bin/env python3
"""Browser contract for static bootstrap Task 3B pages."""
import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const requests = [];
  const commands = [];
  const programs = [];
  const i2c = [];
  const consoleProblems = [];
  let plan = {kind: 'success', index: 0, path: '/distiller.htm'};
  const base = (index, path) => ({
    mode:index ? 4 : 1, version:index ? 'two' : 'one', powerUnit:index ? 'P' : 'V',
    program:path === '/nbk.htm' ? (index ? 'T;86;400' : 'T;85;300') : path === '/bk.htm' ? (index ? 'T;86;0;0;0' : 'T;85;0;0;0') : (index ? 'T;86;0;0' : 'T;85;0;0'),
    description:index ? 'Второе описание' : 'Первое описание',
    luaButtonList:index ? 'two|Lua two' : 'one|Lua one',
    steamColor:index ? '#101010' : '#111111', pipeColor:index ? '#202020' : '#222222', waterColor:index ? '#303030' : '#333333', tankColor:index ? '#404040' : '#444444', acpColor:index ? '#505050' : '#555555',
    steamVisible:true, pipeVisible:true, waterVisible:true, tankVisible:true, pressureVisible:true, programNumberVisible:true,
    i2cStepperVisible:!!index, i2cPumpVisible:!!index, beerBrewOrder:'allinone', pwmLow:index ? 200 : 100,
    pwmValue:index ? 400 : 300, nbkDp:index ? 1.5 : 0.7, columnDiameter:2, columnHeight:1.5, packDensity:80,
    heaterResistance:10, mainsVoltage:220, heaterMaxPower:4840, stepperMaxSpeed:1000, stepperStepsPerMl:100,
    i2cStepperStepsPerMl:100, calibrationRunning:false, calibrationPump:'local', cheesePhSlope:1, cheesePhOffset:0,
    cheeseCoolingScheme:'pump'
  });
  page.on('console', message => {
    if (['warning', 'error'].includes(message.type()) || message.text().includes('UI update error')) consoleProblems.push(message.text());
  });
  page.on('pageerror', error => consoleProblems.push(error.message));
  await page.route('**/ui-bootstrap', route => {
    requests.push('bootstrap');
    if (plan.kind === 'status') return route.fulfill({status:503, contentType:'text/plain', body:'BUSY'});
    return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(base(plan.index, plan.path))});
  });
  const telemetry = {
    version:'telemetry', crnt_tm:'12:00', stm:'00:01', SteamTemp:78.1, PipeTemp:77.9, WaterTemp:20.2, TankTemp:32.3, ACPTemp:31.8,
    bme_pressure:760, start_pressure:760, Status:'Работа', WFtotalMl:0, WFflowRate:0, alc:10, stm_alc:20,
    RowPredictionAvailable:false, TimeRemaining:0, RowTotalTime:0, ProcessPredictionAvailable:false, TotalTime:0,
    RowPredictionReason:0, ProcessPredictionReason:0, current_power_volt:0, target_power_volt:0, current_power_mode:'0', current_power_p:0,
    bme_temp:24, heap:200000, rssi:-50, fr_bt:300000, UseBBuzzer:false, Lstatus:'', wp_spd:0,
    i2c_pump_present:0, i2c_pump_running:0, i2c_pump_remaining_ml:0, i2c_pump_speed:0, PowerOn:0,
    heaterAlarmLatched:0, heaterAlarmReason:'', latestMessageSequence:0, events:[],
    BoilingEvidence:0, BoilingPrecisionSensorConfigured:false, bk_water_auto:false, bk_steam_setpoint:0,
    prvl:0, ISspd:0
  };
  await page.route('**/ajax*', route => { requests.push('ajax'); return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(telemetry)}); });
  await page.route('**/command', route => { commands.push(route.request().postData() || ''); return route.fulfill({status:200, body:'OK'}); });
  await page.route('**/program', route => { programs.push(route.request().postData() || ''); return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({ok:true,err:'',program:''})}); });
  await page.route('**/i2cpump*', route => { i2c.push(route.request().url()); return route.fulfill({status:200, body:'OK'}); });
  function expect(value, message) { if (!value) throw new Error(message); }
  async function open(path, nextPlan) {
    const before = requests.length;
    const bootstrapBefore = requests.filter(value => value === 'bootstrap').length;
    const commandBefore = commands.length;
    const programBefore = programs.length;
    const i2cBefore = i2c.length;
    plan = {...nextPlan, path};
    await page.goto(baseUrl + path, {waitUntil:'load'});
    await page.waitForFunction(() => document.getElementById('WProgram'));
    expect(requests.filter(value => value === 'bootstrap').length === bootstrapBefore + 1,
      path + ' did not issue exactly one bootstrap request');
    if (nextPlan.kind === 'status') {
      await page.waitForFunction(() => document.getElementById('request_error').style.display !== 'none');
      expect(await page.evaluate(() => document.body.inert), path + ' did not lock after bootstrap failure');
      expect(requests.slice(before).indexOf('ajax') === -1, path + ' started ajax after bootstrap failure');
      const errors = await page.evaluate(async () => {
        window.confirm = () => true;
        const check = async fn => { try { return {value:await fn()}; } catch (e) { return {error:String(e.message || e)}; } };
        return {
          command:await check(() => SamovarApp.sendCommand('power=1')),
          program:await check(() => SamovarApp.postProgram(document.forms.mainform)),
          clear:await check(() => SamovarApp.clearProgram()),
          i2c:await check(() => SamovarApp.stopI2cPump())
        };
      });
      expect(errors.command.error.includes('Начальные данные'), path + ' did not block command after bootstrap failure');
      expect(errors.program.error.includes('Начальные данные'), path + ' did not block program after bootstrap failure');
      expect(errors.clear.value === false && errors.i2c.value === false,
        path + ' did not reject clear/i2c after bootstrap failure');
      expect((await page.locator('#request_error').textContent()).includes('Начальные данные'),
        path + ' did not show the blocked-action error');
      expect(commands.length === commandBefore && programs.length === programBefore && i2c.length === i2cBefore,
        path + ' sent a blocked request');
      return;
    }
    await page.waitForFunction(() => document.body.inert === false && document.getElementById('Descr').value !== '');
    const current = requests.slice(before);
    expect(current[0] === 'bootstrap' && current.indexOf('ajax') !== -1,
      path + ' did not start telemetry after bootstrap');
  }
  async function assertBootstrap(path, index) {
    const expected = base(index, path);
    const program = await page.locator('#WProgram').inputValue();
    expect(program.trim() === expected.program,
      path + ' program missing: expected ' + JSON.stringify(expected.program) + ', got ' + JSON.stringify(program));
    expect(await page.locator('#Descr').inputValue() === expected.description, path + ' description missing');
    expect(await page.locator('input[type="button"][value="' + (index ? 'Lua two' : 'Lua one') + '"]').count() === 1,
      path + ' Lua buttons missing');
    expect(await page.locator('#i2cStepperTab').isHidden() === !expected.i2cStepperVisible,
      path + ' I2C stepper visibility missing');
    expect(await page.locator('#i2cPumpTab').isHidden() === !expected.i2cPumpVisible,
      path + ' I2C pump visibility missing');
    const colorIds = path === '/nbk.htm' ? ['SteamTemp', 'BragaTemp', 'WaterTemp', 'TankTemp', 'ACPTemp'] : ['SteamTemp', 'PipeTemp', 'WaterTemp', 'TankTemp', 'ACPTemp'];
    const colors = await page.evaluate(ids => ids.map(id => {
      const style = getComputedStyle(document.getElementById(id).parentElement);
      return [style.color, style.textDecorationColor];
    }), colorIds);
    const expectedColors = await page.evaluate(expectedColors => expectedColors.map(color => {
      const probe = document.createElement('span'); probe.style.color = color; return probe.style.color;
    }), [expected.steamColor, expected.pipeColor, expected.waterColor, expected.tankColor, expected.acpColor]);
    expect(colors.every((value, index) =>
      value[0] === expectedColors[index] && value[1] === expectedColors[index]),
      path + ' sensor colors missing');
    await page.setViewportSize({width:390,height:844});
    expect(!await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), path + ' overflows on mobile');
  }
  async function assertBkPwm(index) {
    const expected = base(index, '/bk.htm');
    expect(await page.locator('#PWM').getAttribute('min') === String(expected.pwmLow), 'BK pwm minimum missing for dataset ' + index);
    expect(await page.locator('#PWM').inputValue() === String(expected.pwmValue), 'BK pwm value missing for dataset ' + index);
  }
  async function assertNbk(index) {
    const expected = base(index, '/nbk.htm');
    expect((await page.locator('#nbkDpLabel').textContent()).includes(String(expected.nbkDp)), 'NBK step missing for dataset ' + index);
    expect((await page.locator('#pmmn').getAttribute('title')).includes(String(expected.nbkDp)), 'NBK title missing for dataset ' + index);
  }
  await open('/distiller.htm', {kind:'success', index:0});
  await assertBootstrap('/distiller.htm', 0);
  await open('/distiller.htm', {kind:'success', index:1});
  await assertBootstrap('/distiller.htm', 1);
  await open('/bk.htm', {kind:'success', index:0});
  await assertBootstrap('/bk.htm', 0);
  await assertBkPwm(0);
  await open('/bk.htm', {kind:'success', index:1});
  await assertBootstrap('/bk.htm', 1);
  await assertBkPwm(1);
  expect(!(await page.locator('#i2cPumpTab').isHidden()), 'BK I2C pump should be visible');
  await open('/nbk.htm', {kind:'success', index:0});
  await assertBootstrap('/nbk.htm', 0);
  await assertNbk(0);
  await open('/nbk.htm', {kind:'success', index:1});
  await assertBootstrap('/nbk.htm', 1);
  await assertNbk(1);
  expect(consoleProblems.length === 0, 'console/page errors before failure case: ' + consoleProblems.join('; '));
  await open('/distiller.htm', {kind:'status', index:0});
  await open('/bk.htm', {kind:'status', index:0});
  await open('/nbk.htm', {kind:'status', index:0});
  expect(commands.length === 0, 'command reached server after bootstrap failure');
  expect(!consoleProblems.some(message => message.includes('UI update error')),
    'telemetry emitted UI update error: ' + consoleProblems.join('; '));
  return 'ok';
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for Task 3B browser gate")
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-ui-3b-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-ui-3b-{os.getpid()}"
        opened = False
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser":{"browserName":"chromium","launchOptions":{"chromiumSandbox":False}}}), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            opened = True
            code = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
            run_cli(cli, session, ["run-code", code], temp, 60)
        finally:
            if opened:
                run_cli(cli, session, ["close"], temp, 30, check=False)
            server.shutdown(); server.server_close(); thread.join(timeout=5)
    print("Task 3B browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
