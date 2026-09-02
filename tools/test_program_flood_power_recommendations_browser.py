#!/usr/bin/env python3
"""Браузерная проверка В2: applyRecommendedSpeeds() и уставка предзахлёба (program.htm).

Решение владельца: уставка (floodPowerW) идёт на ПЕРВУЮ строку блока
предзахлёба (тип 'C'), остальные строки 'C' того же блока получают 0 -
"не мешать автоматике" (alarm.h сама подкручивает регулятор по ходу отбора).
Блок - это подряд идущие строки типа 'C'; любая другая строка между ними
начинает новый блок.

smoke_program_ux.py пинит только порядок двух строк в исходнике функции -
он не прогоняет через неё ни одной программы со строками 'C'. Этот тест
реально строит DOM-программу (через calc_program(), ту же функцию, что
"Загрузить шаблон"/live-пересчёт использует для отрисовки редактора) и
проверяет получившиеся значения поля мощности (pvolt) построчно.

Проверяются краевые случаи:
- программа НАЧИНАЕТСЯ со строки 'C' (сценарий 1, строка 0);
- блоков 'C' несколько (сценарий 1: три блока, разделённые H/B/T);
- подряд идущие 'C' - как 2, так и 3 в ряд (сценарий 1, строки 0-1 и 3-5);
- строка 'C' идёт последней - и как одиночная (сценарий 2a), и как хвост
  многострочного блока (сценарий 2b).

Регулятор в тестовом харнессе - вольты (pwr_unit='V' в render_site), ТЭН
R=10 Ом, сеть 230 В -> heaterMaxPower = round(230*230/10) = 5290 Вт. Ожидаемые
вольты посчитаны независимо в Node по документированной формуле
wattsToProgramVolts(W) = round(230*sqrt(W/5290)), без обращения к коду
страницы:
  floodPowerW=3000   -> 173 В
  headsPowerW=1800   -> 134 В
  workingPowerW=2500 -> 158 В
  tailsPowerW=2000   -> 141 В
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

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  await page.goto(baseUrl + "/program.htm", { waitUntil: "load" });
  await page.waitForTimeout(400);

  const result = await page.evaluate(() => {
    function paramsFor(diam) {
      const k = (diam * diam) / 4;
      return {
        floodPowerW: 3000 * k,
        workingPowerW: 2500 * k,
        maxFlowMlH: 1000 * k,
        theoreticalPlates: 20,
        headsFlowMlH: 100 * k,
        bodyFlowMinMlH: 200 * k,
        bodyFlowMaxMlH: 400 * k,
        bodyEndFlowMlH: 300 * k,
        tailsFlowMlH: 150 * k,
        headsPowerW: 1800 * k,
        bodyEndPowerW: 2200 * k,
        tailsPowerW: 2000 * k,
        headsSpeedClamped: false,
        bodySpeedClamped: false
      };
    }
    function pvoltValues(count) {
      const out = [];
      for (let i = 0; i < count; i++) {
        const el = document.getElementById('pvolt' + i);
        out.push(el ? el.value : null);
      }
      return out;
    }
    function runScenario(rows) {
      // applyRecommendedSpeeds() САМО перестраивает DOM из unscaledProgramBody
      // (см. её первые строки: "if (unscaledProgramBody) { WProgram1.value = ...;
      // calc_program(); }") - если задать программу напрямую через WProgram1 и
      // вызвать calc_program() здесь, функция тут же затрёт её этим же кодом,
      // используя СВОЙ unscaledProgramBody (унаследованный от шаблона по
      // умолчанию, загруженного на window.onload) вместо нашей программы.
      // rememberUnscaledProgram() - тот же вызов, что использует загрузка
      // шаблона (getProgramFromFile()) перед кнопкой "Применить рекомендации".
      rememberUnscaledProgram(rows.join('\n'), 'V');
      columnParams = paramsFor(2);
      columnRecommendationsApplied = false;
      const applied = applyRecommendedSpeeds({ silent: true });
      return { applied: applied, powers: pvoltValues(rows.length) };
    }

    // Три блока 'C' (A: 2 подряд, B: 3 подряд, C: одиночный), разделённые
    // H/B/T; программа начинается со строки 'C'.
    const scenario1 = runScenario([
      "0;50;0;C;0",
      "0;50;0;C;0",
      "0;50;0;H;0",
      "0;50;0;C;0",
      "0;50;0;C;0",
      "0;50;0;C;0",
      "0;50;0;B;0",
      "0;50;0;C;0",
      "0;50;0;T;0"
    ]);

    // Строка 'C' - последняя в программе, одиночная (не часть блока >1).
    const scenario2a = runScenario([
      "0;50;0;H;0",
      "0;50;0;C;0"
    ]);

    // Строка 'C' - последняя в программе, хвост двустрочного блока.
    const scenario2b = runScenario([
      "0;50;0;H;0",
      "0;50;0;C;0",
      "0;50;0;C;0"
    ]);

    return { scenario1: scenario1, scenario2a: scenario2a, scenario2b: scenario2b };
  });

  const expected1 = ["173", "0", "134", "173", "0", "0", "158", "173", "141"];
  if (result.scenario1.applied !== true || JSON.stringify(result.scenario1.powers) !== JSON.stringify(expected1)) {
    throw new Error("multi-block/consecutive C rows got wrong power setpoints: " +
      JSON.stringify({ applied: result.scenario1.applied, got: result.scenario1.powers, expected: expected1 }));
  }

  const expected2a = ["134", "173"];
  if (result.scenario2a.applied !== true || JSON.stringify(result.scenario2a.powers) !== JSON.stringify(expected2a)) {
    throw new Error("standalone trailing C row must get the full flood setpoint, not 0: " +
      JSON.stringify({ applied: result.scenario2a.applied, got: result.scenario2a.powers, expected: expected2a }));
  }

  const expected2b = ["134", "173", "0"];
  if (result.scenario2b.applied !== true || JSON.stringify(result.scenario2b.powers) !== JSON.stringify(expected2b)) {
    throw new Error("trailing 2-row C block must keep 0 on its last (second) row: " +
      JSON.stringify({ applied: result.scenario2b.applied, got: result.scenario2b.powers, expected: expected2b }));
  }

  return result;
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-program-flood-power-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"pfp{os.getpid()}"

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
            print(f"Program flood power recommendations browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Program flood power recommendations browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Program flood power recommendations browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
