#!/usr/bin/env python3
"""[T26.2] Браузерная проверка единого маркера "устарело" на /index.htm.

Контекст: до этой правки applyStaleVisuals() в app.js гасил (opacity=0.4)
только перечисленные в staleReadingIds элементы, а index.htm перечислял там
только температуры - объём, скорость, давление и, главное, состояние нагрева
(кнопка power) НЕ гасли при обрыве связи. Пользователь видел старую надпись
кнопки ("Выключить нагрев") как будто она всё ещё актуальна, жал её вслепую -
и вместе с T26.1 (power=1 всегда, без учёта реального состояния) это могло
включить нагрев вместо выключения.

Правка (T26.2): index.htm теперь отдаёт staleReadingIds: ['Main'] - общий
контейнер вкладки (id="Main", открывается в partials/main_status_header.htm,
закрывается прямо в index.htm перед #Prog), который уже оборачивает ВСЕ
динамические показания вкладки, включая кнопку нагрева.

Этот тест гоняет НАСТОЯЩИЙ index.htm в Chromium через реальный цикл
SamovarApp.startTelemetryPage -> pollAjax -> fetch('/ajax') (не вызывает
SamovarApp.setConnectionError() напрямую) и проверяет:
  a) пока связь жива - #Main не приглушен, кнопка показывает актуальное
     состояние нагрева;
  b) после нескольких подряд неудачных /ajax (моделируем обрывом сети через
     route.abort, как реальный fetch()) #Main гаснет (opacity '0.4'), а
     кнопка нагрева и температура ЗАСТЫВАЮТ на последнем известном значении
     (не обнуляются и не обновляются "в слепую");
  c) после восстановления связи #Main возвращает непрозрачность, а кнопка
     нагрева обновляется на актуальное (новое) состояние.
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
from test_numeric_input_ui_browser import QuietHandler, render_site, run_cli

ROOT = Path(__file__).resolve().parents[1]

# Та же фикстура, что уже проверена реальным рендером index.htm в
# tools/test_runtime_event_ui_browser.py (кейс mode_index) - переиспользуем
# её без изменений (кроме PowerOn), чтобы не гадать заново, какие поля
# renderTelemetry() требует, и не словить исключение рендера на посторонней
# для этого теста причине.
FIXTURE_ON = r'''{
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
    PowerOn: 1, StepperStepMl: 111,
    heaterAlarmLatched: 0, latestMessageSequence: 0
  }'''
# Тот же снимок, но нагрев уже выключен - именно это должна показать кнопка
# ПОСЛЕ восстановления связи (доказывает, что после реконнекта состояние не
# "залипает" на старом, а честно обновляется).
FIXTURE_RECOVERED = FIXTURE_ON.replace("PowerOn: 1", "PowerOn: 0")

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const errors = [];
  page.on('console', message => {
    // net::ERR_FAILED - это собственный лог Chrome о сети, вызванный НАШИМ ЖЕ
    // route.abort('failed') (мы намеренно моделируем обрыв связи ниже) - это не
    // баг страницы, отфильтровываем только его, остальные console error ловим.
    if (message.type() === 'error' && !message.text().includes('net::ERR_FAILED')) {
      errors.push('console: ' + message.text());
    }
  });
  page.on('pageerror', error => errors.push('pageerror: ' + error.message));

  // window.Audio заменяем на безобидную заглушку (тот же приём, что и
  // tools/test_runtime_event_ui_browser.py::testModePage): реальный
  // конструктор Audio() не нужен для проверки, а setConnectionOk() после
  // восстановления связи дергает playSound(false), который его создаёт.
  await page.addInitScript(() => {
    window.Audio = function () {
      this.loop = false;
      this.preload = '';
      this.autoplay = false;
      this.play = function () { return Promise.resolve(); };
      this.pause = function () {};
    };
  });

  const fixtureOn = __FIXTURE_ON__;
  const fixtureRecovered = __FIXTURE_RECOVERED__;
  let phase = 'online';
  await page.route('**/ajax*', async route => {
    if (phase === 'offline') {
      await route.abort('failed');
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(phase === 'recovered' ? fixtureRecovered : fixtureOn)
    });
  });

  await page.goto(baseUrl + '/index.htm', { waitUntil: 'load' });
  await page.waitForFunction(() => {
    const status = document.getElementById('Status');
    return status && status.textContent === 'Готов';
  }, null, { timeout: 10000 });

  // --- (a) связь жива - #Main не приглушен, кнопка показывает "нагрев ВКЛ" ---
  const before = await page.evaluate(() => ({
    mainOpacity: document.getElementById('Main').style.opacity,
    powerLabel: document.getElementById('power').value,
    steamTemp: document.getElementById('SteamTemp').innerHTML
  }));
  if (before.mainOpacity !== '') {
    throw new Error('#Main must not be dimmed while online, got opacity=' + JSON.stringify(before.mainOpacity));
  }
  if (before.powerLabel !== 'Выключить нагрев') {
    throw new Error('expected power button to show heating ON label while online, got ' + JSON.stringify(before.powerLabel));
  }

  // --- (b) обрыв связи через реальный /ajax (не через SamovarApp.setConnectionError()
  // напрямую) - offlineThreshold=3 в index.htm означает 4 подряд неудачных опроса
  // (offlineCounter 0->1->2->3, 4-й уже не проходит "< threshold") плюс technical
  // 100ms задержка внутри самого setConnectionError() до применения приглушения.
  // Опрос идёт раз в 2с (startPollLoop), так что ждём щедро.
  phase = 'offline';
  await page.waitForFunction(() => document.getElementById('Main').style.opacity === '0.4', null, { timeout: 25000 });

  const during = await page.evaluate(() => ({
    mainOpacity: document.getElementById('Main').style.opacity,
    powerLabel: document.getElementById('power').value,
    steamTemp: document.getElementById('SteamTemp').innerHTML,
    status: document.getElementById('Status').textContent
  }));
  if (during.powerLabel !== before.powerLabel) {
    throw new Error('power button must stay on its last-known label while offline (not blank/reset), got ' + JSON.stringify(during.powerLabel));
  }
  if (during.steamTemp !== before.steamTemp) {
    throw new Error('SteamTemp must stay on its last-known value while offline, got ' + JSON.stringify(during.steamTemp));
  }
  if (during.status !== 'Готов') {
    throw new Error('Status text must stay on its last-known value while offline, got ' + JSON.stringify(during.status));
  }

  // --- (c) связь восстановлена - #Main возвращает непрозрачность, кнопка
  // обновляется на актуальное (новое) состояние, а не остаётся "залипшей" ---
  phase = 'recovered';
  await page.waitForFunction(() => document.getElementById('Main').style.opacity === '', null, { timeout: 15000 });
  await page.waitForFunction(() => document.getElementById('power').value === 'Включить нагрев', null, { timeout: 10000 });

  const after = await page.evaluate(() => ({
    mainOpacity: document.getElementById('Main').style.opacity,
    powerLabel: document.getElementById('power').value
  }));
  if (after.mainOpacity !== '') {
    throw new Error('#Main must reset opacity after reconnect, got ' + JSON.stringify(after.mainOpacity));
  }
  if (after.powerLabel !== 'Включить нагрев') {
    throw new Error('power button must reflect the fresh (recovered) heating-OFF state, got ' + JSON.stringify(after.powerLabel));
  }

  if (errors.length > 0) throw new Error(errors.join('\n'));
  return { before, during, after };
}'''


def main():
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    cleanup_errors = []
    with tempfile.TemporaryDirectory(prefix="samovar-stale-telemetry-dimming-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-stale-telemetry-dimming-{os.getpid()}"

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
                .replace("__FIXTURE_ON__", FIXTURE_ON)
                .replace("__FIXTURE_RECOVERED__", FIXTURE_RECOVERED)
            )
            run_cli(cli, session, ["run-code", browser_test], temp, 90)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            try:
                if run_cli(cli, session, ["close"], ROOT, 30, check=False) != 0:
                    cleanup_errors.append("playwright-cli close failed")
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup_errors.append(f"playwright-cli close failed: {error}")
            try:
                server.shutdown()
            except Exception as error:
                cleanup_errors.append(f"HTTP server shutdown failed: {error}")
            try:
                server.server_close()
            except Exception as error:
                cleanup_errors.append(f"HTTP server close failed: {error}")
            thread.join(timeout=5)
            if thread.is_alive():
                cleanup_errors.append("HTTP server thread did not stop")

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Stale telemetry dimming browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Stale telemetry dimming browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Stale telemetry dimming browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
