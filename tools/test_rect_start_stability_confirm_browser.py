#!/usr/bin/env python3
"""[Б6.2] Браузерная проверка предупреждения при старте отбора до стабилизации колонны.

Кнопка "Начать отбор" (index.htm, #start) раньше спрашивала подтверждение только
если отбор уже идёт ("Перейти к следующей программе?"). Теперь она дополнительно
предупреждает на ПЕРВОМ старте, если нагрев включён, а колонна ещё в разгоне
(SamovarStatusInt 50) или стабилизируется (51) - отбор по непрогретой колонне даёт
мутный продукт и сбивает разделение фракций. Жёсткого запрета нет - решение
владельца: только предупреждение с возможностью продолжить.

Тест перехватывает не диалоги Playwright, а переопределяет window.confirm внутри
страницы (тот же приём, что в test_mode_logic_ui_browser.py) - так надёжнее ловится
факт вызова confirm() и его текст, а возвращаемое значение полностью управляемо.

Шесть сценариев:
  1. нагрев включён, статус 50 (разгон), отбор не идёт -> confirm() вызван один раз
     с текстом про нестабильный режим; ответ "нет" -> команда start=1 не отправлена.
  2. то же со статусом 51 (стабилизация).
  3. нагрев включён, статус 52 (стабильна) -> confirm() не вызывается, команда уходит.
  4. нагрев выключен, статус 50 -> confirm() не вызывается; клиент НЕ гейтит саму
     команду по HeaterPowerOn, поэтому POST start=1 всё равно уходит на сервер -
     в реальности сервер ответил бы 409 POWER_OFF (WebServer.ino: action=="start"
     проверяет PowerOn), но этот мок безусловно отвечает 200 OK, так что здесь
     проверяется именно факт отправки, а не серверный отказ.
  5. регресс старого поведения: отбор уже идёт (WthdrwlStatus > 0), статус 50 ->
     confirm() вызывается один раз именно с текстом "Перейти к следующей программе?".
  6. [владелец Б6: предупреждение, а не запрет] разгон (50), нагрев включён, отбор не
     идёт, оператор СОГЛАШАЕТСЯ с предупреждением -> confirm() вызван один раз, и
     команда start=1 всё же отправляется. Без этого сценария заглушка, которая
     показывает предупреждение и после любого ответа всё равно блокирует старт,
     осталась бы незамеченной - все проверки "отказался" (1, 2) совпали бы с её
     поведением.
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
from test_numeric_input_ui_browser import (
    QuietHandler,
    cleanup,
    render_site,
    run_cli,
)

ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const failures = [];
  function expect(condition, message) { if (!condition) failures.push(message); }

  await page.addInitScript(() => {
    window.__confirmMessages = [];
    window.__confirmResult = true;
    window.confirm = function (message) {
      window.__confirmMessages.push(message);
      return window.__confirmResult;
    };
  });

  let currentFixture = null;
  await page.route("**/ajax*", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(currentFixture),
  }));
  const commandPosts = [];
  await page.route("**/command", route => {
    const request = route.request();
    if (request.method() === "POST") commandPosts.push(request.postData() || "");
    return route.fulfill({ status: 200, contentType: "text/plain", body: "OK" });
  });

  const BASE_TELEMETRY = {
    version: 'test', crnt_tm: '12:00:00', stm: '00:01:00', SteamTemp: 78.1,
    PipeTemp: 77.9, WaterTemp: 20.2, TankTemp: 82.3, ACPTemp: 40.1,
    bme_pressure: 760, start_pressure: 759.5, prvl: 1.2, VolumeAll: 0,
    ActualVolumePerHour: 0, WthdrwlProgress: 0, CurrrentSpeed: 0,
    CurrrentStepps: 0, TargetStepps: 0, WthdrwlStatus: 0, ProgramNum: 0,
    DetectorTrend: 0, DetectorStatus: 0, useautospeed: false,
    current_power_volt: 0, target_power_volt: 0, current_power_mode: '0',
    current_power_p: 0, WFtotalMl: 0, WFflowRate: 0, bme_temp: 24,
    heap: 200000, rssi: -50, fr_bt: 300000, UseBBuzzer: false, PauseOn: 0,
    PrgType: '', Status: 'Работа', Lstatus: '', TimeRemaining: 0, TotalTime: 0,
    alc: 0, stm_alc: 0, ISspd: 0, wp_spd: 0, i2c_pump_present: 0,
    i2c_pump_running: 0, i2c_pump_remaining_ml: 0, i2c_pump_speed: 0,
    PowerOn: 1, StepperStepMl: 111,
    heaterAlarmLatched: 0, heaterAlarmReason: '', latestMessageSequence: 0,
  };

  async function runScenario({ powerOn, status, withdrawalActive, confirmResult }) {
    currentFixture = {
      ...BASE_TELEMETRY,
      PowerOn: powerOn ? 1 : 0,
      SamovarStatusInt: status,
      WthdrwlStatus: withdrawalActive ? 1 : 0,
    };
    await page.goto(baseUrl + "/index.htm", { waitUntil: "load" });
    await page.waitForFunction(() => window.RectStatusInt !== null);
    await page.evaluate(result => { window.__confirmResult = result; }, confirmResult);
    const before = commandPosts.length;
    await page.locator("#start").click();
    const confirms = await page.evaluate(() => window.__confirmMessages.slice());
    const sent = commandPosts.length > before &&
      commandPosts[commandPosts.length - 1].includes("start=1");
    return { confirms, sent };
  }

  // 1. Разгон (50), нагрев включён, отбор не идёт, пользователь отвечает "нет".
  {
    const result = await runScenario({
      powerOn: true, status: 50, withdrawalActive: false, confirmResult: false,
    });
    expect(result.confirms.length === 1,
      "accel (50): confirm must be called exactly once, got " + JSON.stringify(result.confirms));
    expect(result.confirms[0] && result.confirms[0].includes("не вышла на стабильный режим"),
      "accel (50): unexpected confirm text: " + JSON.stringify(result.confirms));
    expect(!result.sent, "accel (50): start=1 must NOT be sent when user declines the warning");
  }

  // 2. Стабилизация (51), та же логика.
  {
    const result = await runScenario({
      powerOn: true, status: 51, withdrawalActive: false, confirmResult: false,
    });
    expect(result.confirms.length === 1,
      "stabilizing (51): confirm must be called exactly once, got " + JSON.stringify(result.confirms));
    expect(result.confirms[0] && result.confirms[0].includes("не вышла на стабильный режим"),
      "stabilizing (51): unexpected confirm text: " + JSON.stringify(result.confirms));
    expect(!result.sent, "stabilizing (51): start=1 must NOT be sent when user declines the warning");
  }

  // 3. Колонна стабильна (52) - предупреждать не о чем, confirm не вызывается.
  {
    const result = await runScenario({
      powerOn: true, status: 52, withdrawalActive: false, confirmResult: false,
    });
    expect(result.confirms.length === 0,
      "stable (52): confirm must NOT be called, got " + JSON.stringify(result.confirms));
    expect(result.sent, "stable (52): start=1 must be sent without any confirmation");
  }

  // 4. Нагрев выключен - предупреждать не о чем, но клиент не гейтит саму команду по
  //    HeaterPowerOn: POST start=1 всё равно уходит (в реальности сервер ответил бы
  //    409 POWER_OFF, но этот мок безусловно отвечает 200 OK, поэтому здесь проверяем
  //    именно факт отправки, а не серверный отказ).
  {
    const result = await runScenario({
      powerOn: false, status: 50, withdrawalActive: false, confirmResult: false,
    });
    expect(result.confirms.length === 0,
      "heater off: confirm must NOT be called, got " + JSON.stringify(result.confirms));
    expect(result.sent,
      "heater off: start=1 must still be sent by the client (no client-side HeaterPowerOn gate)");
  }

  // 6. [Б6] Разгон (50), нагрев включён, отбор не идёт, оператор СОГЛАШАЕТСЯ с
  //    предупреждением - владелец требовал именно предупреждение с подтверждением,
  //    а не запрет, поэтому старт обязан пройти, если ответ "да".
  {
    const result = await runScenario({
      powerOn: true, status: 50, withdrawalActive: false, confirmResult: true,
    });
    expect(result.confirms.length === 1,
      "accel (50) confirmed: confirm must be called exactly once, got " + JSON.stringify(result.confirms));
    expect(result.confirms[0] && result.confirms[0].includes("не вышла на стабильный режим"),
      "accel (50) confirmed: unexpected confirm text: " + JSON.stringify(result.confirms));
    expect(result.sent,
      "accel (50) confirmed: start=1 MUST be sent once the operator accepts the warning");
  }

  // 5. Регресс: отбор уже идёт - старое поведение и текст должны остаться без изменений.
  {
    const result = await runScenario({
      powerOn: true, status: 50, withdrawalActive: true, confirmResult: true,
    });
    expect(result.confirms.length === 1,
      "withdrawal active: confirm must be called exactly once, got " + JSON.stringify(result.confirms));
    expect(result.confirms[0] === "Перейти к следующей программе?",
      "withdrawal active: confirm text regressed: " + JSON.stringify(result.confirms));
    expect(result.sent, "withdrawal active: start=1 must be sent once user confirms");
  }

  if (failures.length > 0) {
    throw new Error(failures.join("\n"));
  }
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-rect-start-confirm-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-rect-start-confirm-{os.getpid()}"

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
            browser_test = BROWSER_TEST.replace("__BASE_URL__", json.dumps(base_url))
            run_cli(cli, session, ["run-code", browser_test], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Rect start stability confirm browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Rect start stability confirm browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Rect start stability confirm browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
