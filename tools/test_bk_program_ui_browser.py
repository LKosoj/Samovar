#!/usr/bin/env python3
"""[Задача 9c] Браузерная проверка вкладки "Программа" на bk.htm.

Контекст: bk.htm и distiller.htm теперь используют ОБЩИЙ партиал
data_raw/partials/program_table_dist.htm для таблицы программы. Число колонок
задаёт переменная PROGRAM_STEAM_COLUMN, которую страница объявляет ДО
<!--#include-->: false - 4 колонки (дистилляция), true - 5-я колонка "Т пара"
(БК, уставка охлаждения дефлегматора). Плюс на bk.htm добавлен бейдж "Вода:
авто/вручную" и кнопка "Автомат" (шлёт /command waterauto=1), а также
подсказка про необходимость ШИМ-насоса, когда поле wp_spd вовсе отсутствует
в /ajax (сборка без USE_WATER_PUMP).

Тест гоняет НАСТОЯЩИЕ distiller.htm и bk.htm в Chromium через playwright-cli
и проверяет:
  1. distiller.htm - 4 колонки (нет psteam0, нет заголовка "Т пара"),
     сериализация строки в WProgram по-прежнему из 4 полей.
  2. bk.htm - 5 колонок (есть psteam0 со значением из файла, есть заголовок
     "Т пара"), сериализация строки в WProgram из 5 полей.
  3. Бейдж/кнопка "Автомат": авто-режим показывает уставку, ручной режим с
     PowerOn=1 и uставкой>0 показывает кнопку, ручной режим без права на
     авто (уставка=0) кнопку прячет; клик по кнопке шлёт ровно "waterauto=1"
     и корректно показывает текст отказа NOT_RUNNING через COMMAND_TOKENS.
  4. Подсказка про насос: без wp_spd в /ajax скрыт блок управления водой и
     показана подсказка; с wp_spd - наоборот.
"""
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_numeric_input_ui_browser import QuietHandler, cleanup, render_site, run_cli

ROOT = Path(__file__).resolve().parents[1]

# Общая часть телеметрии. bk_water_auto/bk_steam_setpoint/wp_spd добавляются
# по сценарию через ajaxOverride (см. BROWSER_TEST) - как и в прошивке, эти
# поля со значением по умолчанию не считаются "всегда присутствующими"
# (wp_spd вовсе отсутствует в сборках без USE_WATER_PUMP).
FIXTURE_BASE = r'''{
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
    alc: 0, stm_alc: 0, ISspd: 0, i2c_pump_present: 0,
    i2c_pump_running: 0, i2c_pump_remaining_ml: 0, i2c_pump_speed: 0,
    PowerOn: 0, StepperStepMl: 111,
    heaterAlarmLatched: 0, heaterAlarmReason: '', latestMessageSequence: 0
  }'''

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const fixtureBase = __FIXTURE_BASE__;
  const errors = [];
  let ajaxOverride = {};
  let commandPosts = [];
  let commandResponse = { status: 200, contentType: 'text/plain', body: 'OK' };

  function fail(message) { errors.push(message); }

  page.on('console', message => {
    // 409 (Conflict) - наш же намеренный ответ /command в сценарии NOT_RUNNING
    // ниже (Chrome логирует отказ сетевого запроса как console error) - не баг.
    if (message.type() === 'error' && !message.text().includes('409 (Conflict)')) {
      fail('console: ' + message.text());
    }
  });
  page.on('pageerror', error => fail('pageerror: ' + error.message));

  await page.route('**/ajax*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(Object.assign({}, fixtureBase, ajaxOverride))
  }));
  await page.route('**/command', route => {
    const request = route.request();
    if (request.method() === 'POST') commandPosts.push(request.postData() || '');
    return route.fulfill(commandResponse);
  });

  // --- 1. distiller.htm: 4 колонки, без "Т пара" ---
  await page.goto(baseUrl + '/distiller.htm', { waitUntil: 'load' });
  await page.waitForFunction(() => document.getElementById('Status') &&
    document.getElementById('Status').textContent === 'Готов', null, { timeout: 10000 });
  await page.click('input.tablinks[value="Программа"]');
  await page.evaluate(() => {
    document.getElementById('WProgram').value = 'T;90;1;0';
    var prg = document.getElementById('prg');
    while (prg.firstChild) prg.removeChild(prg.firstChild);
    getProgram();
  });
  const distCheck = await page.evaluate(() => ({
    hasSteamInput: document.getElementById('psteam0') !== null,
    hasSteamHeader: document.getElementById('distiller-program-col-steam') !== null
  }));
  if (distCheck.hasSteamInput) fail('distiller.htm неожиданно создал psteam0 (5-я колонка)');
  if (distCheck.hasSteamHeader) fail('distiller.htm неожиданно показал заголовок "Т пара"');

  await page.evaluate(() => {
    document.getElementById('ppower0').value = '123';
    calc_program();
  });
  const distProgram = await page.evaluate(() => document.getElementById('WProgram').value.trim());
  if (distProgram !== 'T;90;1;123') {
    fail('distiller.htm сериализовал строку не из 4 полей: ' + JSON.stringify(distProgram));
  }

  // --- 2. bk.htm: 5 колонок, есть "Т пара" ---
  ajaxOverride = { wp_spd: 0, bk_water_auto: false, bk_steam_setpoint: 0 };
  await page.goto(baseUrl + '/bk.htm', { waitUntil: 'load' });
  await page.waitForFunction(() => document.getElementById('Status') &&
    document.getElementById('Status').textContent === 'Готов', null, { timeout: 10000 });
  await page.click('input.tablinks[value="Программа"]');

  const pumpCheck = await page.evaluate(() => ({
    waterH2Display: getComputedStyle(document.getElementById('WaterH2')).display,
    noPumpHintDisplay: getComputedStyle(document.getElementById('noPumpHint')).display
  }));
  if (pumpCheck.waterH2Display === 'none') fail('bk.htm скрыл WaterH2 при наличии wp_spd');
  if (pumpCheck.noPumpHintDisplay !== 'none') fail('bk.htm показал noPumpHint при наличии wp_spd');

  await page.evaluate(() => {
    document.getElementById('WProgram').value = 'T;93;1;190;70';
    var prg = document.getElementById('prg');
    while (prg.firstChild) prg.removeChild(prg.firstChild);
    getProgram();
  });
  const bkCheck = await page.evaluate(() => {
    const steam = document.getElementById('psteam0');
    return {
      steamValue: steam ? steam.value : null,
      hasSteamHeader: document.getElementById('distiller-program-col-steam') !== null
    };
  });
  if (bkCheck.steamValue !== '70') fail('bk.htm не создал psteam0 со значением из файла: ' + JSON.stringify(bkCheck.steamValue));
  if (!bkCheck.hasSteamHeader) fail('bk.htm не показал заголовок "Т пара"');

  await page.evaluate(() => {
    document.getElementById('psteam0').value = '65';
    calc_program();
  });
  const bkProgram = await page.evaluate(() => document.getElementById('WProgram').value.trim());
  if (bkProgram !== 'T;93;1;190;65') {
    fail('bk.htm сериализовал строку не из 5 полей: ' + JSON.stringify(bkProgram));
  }

  // Бейдж/кнопка "Автомат" живут на вкладке "Режим БК" (WaterH2) - клик по
  // кнопке ниже требует реальной видимости элемента, а не только computed style.
  await page.click('input.tablinks[value="Режим БК"]');

  // --- 3a. Бейдж "авто" ---
  ajaxOverride = { wp_spd: 0, bk_water_auto: true, bk_steam_setpoint: 78 };
  await page.waitForFunction(() =>
    document.getElementById('waterAutoBadge').textContent === 'Вода: авто 78,0 °C',
    null, { timeout: 8000 });
  const autoBtnDisplay = await page.evaluate(() =>
    getComputedStyle(document.getElementById('waterAutoBtn')).display);
  if (autoBtnDisplay !== 'none') fail('кнопка "Автомат" видна в авто-режиме');

  // --- 3b. Ручной режим, кнопка доступна (PowerOn=1, уставка>0) ---
  ajaxOverride = { wp_spd: 0, bk_water_auto: false, bk_steam_setpoint: 70, PowerOn: 1 };
  await page.waitForFunction(() =>
    document.getElementById('waterAutoBadge').textContent === 'Вода: вручную' &&
    getComputedStyle(document.getElementById('waterAutoBtn')).display !== 'none',
    null, { timeout: 8000 });

  commandResponse = { status: 409, contentType: 'application/json', body: JSON.stringify({ error: 'NOT_RUNNING' }) };
  await page.locator('#waterAutoBtn').click();
  await page.waitForFunction(() => {
    const list = document.getElementById('messages');
    return list && list.textContent.includes('Программа БК не выполняется.');
  }, null, { timeout: 5000 });
  if (commandPosts.length !== 1 || commandPosts[0] !== 'waterauto=1') {
    fail('клик "Автомат" отправил не "waterauto=1": ' + JSON.stringify(commandPosts));
  }

  // --- 3c. Ручной режим, кнопка недоступна (уставка=0) ---
  ajaxOverride = { wp_spd: 0, bk_water_auto: false, bk_steam_setpoint: 0, PowerOn: 1 };
  await page.waitForFunction(() =>
    document.getElementById('waterAutoBadge').textContent === 'Вода: вручную' &&
    getComputedStyle(document.getElementById('waterAutoBtn')).display === 'none',
    null, { timeout: 8000 });

  // --- 4. Нет насоса: wp_spd отсутствует ---
  ajaxOverride = { bk_water_auto: false, bk_steam_setpoint: 0 };
  await page.waitForFunction(() =>
    getComputedStyle(document.getElementById('noPumpHint')).display !== 'none' &&
    getComputedStyle(document.getElementById('WaterH2')).display === 'none',
    null, { timeout: 8000 });

  if (errors.length) throw new Error(errors.join('; '));
  return 'ok';
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the bk program UI browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-bk-program-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-bk-program-ui-{os.getpid()}"

        cleanup_errors = []
        try:
            open_args = ["open"]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                config = temp / "playwright.json"
                config.write_text(json.dumps({
                    "browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}
                }), encoding="utf-8")
                open_args.append(f"--config={config}")

            run_cli(cli, session, open_args, temp, 30)
            base_url = f"http://127.0.0.1:{server.server_port}"
            browser_test = (
                BROWSER_TEST
                .replace("__BASE_URL__", json.dumps(base_url))
                .replace("__FIXTURE_BASE__", FIXTURE_BASE)
            )
            run_cli(cli, session, ["run-code", browser_test], temp, 90)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"bk program UI browser gate failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"bk program UI browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("bk program UI browser gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
