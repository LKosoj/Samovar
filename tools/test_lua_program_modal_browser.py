#!/usr/bin/env python3
"""Browser check for the shared Lua program-row modal in five sequential modes."""

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
from test_bk_program_ui_browser import FIXTURE_BASE
from test_numeric_input_ui_browser import QuietHandler, cleanup, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const fixture = __FIXTURE_BASE__;
  const problems = [];
  const requests = [];
  function check(condition, message) { if (!condition) problems.push(message); }

  page.on('request', request => requests.push(request.url()));
  page.on('pageerror', error => problems.push('pageerror: ' + error.message));
  page.on('console', message => {
    if (message.type() === 'error') problems.push('console: ' + message.text());
  });
  await page.route('**/ajax*', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(fixture)
  }));
  await page.route(url => url.pathname === '/edit' && url.searchParams.get('list') === '/', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      { type: 'file', name: '/job.lua' },
      { type: 'file', name: '/stage.lua' },
      { type: 'file', name: '/btn_beer_button1.lua' },
      { type: 'file', name: '/script.lua' },
      { type: 'file', name: '/notes.txt' },
      { type: 'dir', name: '/folder.lua' }
    ])
  }));

  async function openMode(path, program, fieldSelector, cheese) {
    await page.goto(baseUrl + path, { waitUntil: 'load' });
    await page.waitForFunction(() => document.getElementById('Status') !== null,
      null, { timeout: 10000 });
    const tab = page.locator('input.tablinks[value="Программа"]');
    if (await tab.count()) await tab.click();
    await page.evaluate(({program, cheese}) => {
      document.getElementById('WProgram').value = program + '\n';
      if (cheese) {
        renderProgram(program + '\n');
      } else {
        const rows = document.getElementById('prg');
        while (rows.firstChild) rows.removeChild(rows.firstChild);
        getProgram();
      }
    }, {program, cheese});
    await page.locator(fieldSelector).dispatchEvent('focus');
    await page.waitForTimeout(200);
    const opened = await page.evaluate(() => {
      const popup = document.getElementById('lua-program-popup');
      return popup && getComputedStyle(popup).display !== 'none';
    });
    if (!opened) {
      throw new Error('Lua modal did not open on ' + path + '; field=' + fieldSelector +
        '; edit requests=' + JSON.stringify(requests.filter(url => url.includes('/edit'))));
    }
  }

  async function saveModal(timeout, fileName) {
    await page.locator('#lua-program-timeout').fill(String(timeout));
    await page.locator('#lua-program-file').selectOption(fileName);
    const saved = await page.evaluate(() => SamovarApp.saveLuaProgramModal());
    check(saved === true, 'модальное окно не сохранило корректные значения');
    await page.waitForFunction(() =>
      getComputedStyle(document.getElementById('lua-program-popup')).display === 'none');
  }

  async function checkModalButtons(selector, label) {
    const buttons = page.locator(selector + ' .popup__button');
    check(await buttons.count() === 2, label + ': ожидались две кнопки');
    const styles = await buttons.evaluateAll(elements => elements.map(element => ({
      height: element.getBoundingClientRect().height,
      primary: element.classList.contains('primary'),
      secondary: element.classList.contains('secondary')
    })));
    check(styles.every(style => style.height >= 44), label + ': кнопки ниже 44 px');
    check(styles.filter(style => style.primary).length === 1, label + ': нет основной кнопки');
    check(styles.filter(style => style.secondary).length === 1, label + ': нет вторичной кнопки');
  }

  await openMode('/index.htm', 'L;1;job.lua;0;0;0', '#pspeed0', false);
  await checkModalButtons('#lua-program-popup', 'Lua-модалка');
  const files = await page.locator('#lua-program-file option').allTextContents();
  check(JSON.stringify(files) === JSON.stringify(['job.lua', 'stage.lua']),
    'список должен содержать только Lua-файлы: ' + JSON.stringify(files));
  check(await page.locator('#lua-program-timeout').inputValue() === '1',
    'ректификация не показала тайм-аут из строки');

  await page.getByRole('button', {name: 'Добавить параметр'}).click();
  let blankSaved = await page.evaluate(() => SamovarApp.saveLuaProgramModal());
  check(blankSaved === false, 'пустой параметр был принят без явного ""');
  check(await page.locator('#lua-program-popup').isVisible(),
    'окно закрылось после отказа по пустому параметру');
  await page.locator('.lua-program-argument input').fill('""');
  await page.getByRole('button', {name: 'Добавить параметр'}).click();
  await page.locator('.lua-program-argument input').nth(1).fill('alpha');
  await saveModal(12, 'stage.lua');
  check((await page.locator('#pspeed0').inputValue()) === 'stage.lua^""^alpha',
    'единое текстовое поле не получило имя файла и параметры');
  check((await page.locator('#WProgram').inputValue()).trim() ===
      'L;12;stage.lua^""^alpha;0;0;0',
    'ректификация сериализовала Lua-строку неверно');

  const cases = [
    ['/distiller.htm', 'L;2;0;job.lua', '#ppower0', 22, 'L;22;0;stage.lua'],
    ['/bk.htm', 'L;3;0;job.lua;0', '#ppower0', 23, 'L;23;0;stage.lua;0'],
    ['/beer.htm', 'L;0;4;job.lua;0', '#pmixer0', 24, 'L;0;24;stage.lua;0']
  ];
  for (const [path, program, selector, timeout, expected] of cases) {
    await openMode(path, program, selector, false);
    await saveModal(timeout, 'stage.lua');
    check((await page.locator('#WProgram').inputValue()).trim() === expected,
      path + ' сериализовал Lua-строку неверно: ' +
        JSON.stringify((await page.locator('#WProgram').inputValue()).trim()));
  }

  await page.evaluate(() => {
    const mixer = document.getElementById('pmixer0');
    mixer.value = '1^0^10^5';
    SamovarApp.openDeviceScheduleModal(mixer);
  });
  await checkModalButtons('#popup', 'Модалка мешалки');
  await page.evaluate(() => SamovarApp.closeDeviceScheduleModal());

  await openMode('/cheese.htm', 'L;0;5;0;job.lua;0', '.cheese-lua-call', true);
  await saveModal(25, 'stage.lua');
  const cheeseProgram = await page.evaluate(() => serializeCheeseRows().trim());
  check(cheeseProgram === 'L;0;25;0;stage.lua;0',
    'сыр сериализовал Lua-строку неверно: ' + JSON.stringify(cheeseProgram));

  if (problems.length) throw new Error(problems.join('; '));
  return 'ok';
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the Lua program modal browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-lua-program-modal-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-lua-program-modal-{os.getpid()}"
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
            browser_test = (
                BROWSER_TEST
                .replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
                .replace("__FIXTURE_BASE__", FIXTURE_BASE)
            )
            run_cli(cli, session, ["run-code", browser_test], temp, 90)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Lua program modal browser gate failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Lua program modal browser cleanup failed: {error}", file=sys.stderr)
        return 1
    print("Lua program modal browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
