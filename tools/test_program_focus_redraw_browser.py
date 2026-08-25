#!/usr/bin/env python3
"""[T34.2] Браузерная проверка отложенной перерисовки таблицы программы на
/index.htm.

Контекст бага (SOLUTIONS_2026-08-24.md, Уровень 4, пункт 2): renderTelemetry()
на каждое изменение ProgramNum (номер текущей строки программы на устройстве)
безусловно вызывал getProgram() - полную пересборку #prg (снос всех <input>
и создание новых через addLine()). Если пользователь в этот момент правил
ячейку таблицы (например Мощность/Скорость строки), правка терялась и/или
прыгал курсор, потому что сам DOM-элемент поля уничтожался.

Правка: если в момент срабатывания фокус находится внутри #prg, перерисовка
откладывается (programRedrawPending = true) и показывается индикатор
"данные обновились" (#progStaleBadge, тот же приём переиспользован из
staleReadingIds - серый/предупреждающий текст через SamovarApp.cssVar).
Как только фокус уходит из #prg (событие focusout), откладывавшаяся
перерисовка выполняется и индикатор гаснет.

Тест гоняет НАСТОЯЩИЙ index.htm в Chromium через playwright-cli:
  a) пока фокус внутри таблицы и ProgramNum на устройстве меняется -
     несохранённое значение поля НЕ стирается, индикатор появляется;
  b) как только фокус покидает таблицу - перерисовка происходит (поле
     возвращается к настоящему значению из WProgram), индикатор гаснет.
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
from test_stale_telemetry_dimming_browser import FIXTURE_ON

ROOT = Path(__file__).resolve().parents[1]

# ProgramNum:1 вместо ProgramNum:0 у FIXTURE_ON, чтобы во время теста ровно
# один раз сработал переход current_progNum(0) -> new_progNum(1).
FIXTURE_NEXT_STEP = FIXTURE_ON.replace("ProgramNum: 0", "ProgramNum: 1")

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const fixtureStart = __FIXTURE_START__;
  const fixtureNext = __FIXTURE_NEXT__;
  let phase = "start";
  await page.route("**/ajax*", async route => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(phase === "next" ? fixtureNext : fixtureStart)
    });
  });

  await page.goto(baseUrl + "/index.htm", { waitUntil: "load" });
  await page.waitForFunction(() => {
    const status = document.getElementById("Status");
    return status && status.textContent === "Готов";
  }, null, { timeout: 10000 });

  // Кладём в программу одну строку и рисуем её вручную (WProgram - не
  // телеметрийное поле, оно не приходит через /ajax) - так у нас появляется
  // редактируемая ячейка pvolume0 со известным исходным значением "100".
  await page.evaluate(() => {
    document.getElementById("WProgram").value = "H;100;500;0;0;30";
    getProgram();
  });

  // Вкладка "Программа" по умолчанию скрыта (aria-hidden="true") - без
  // реального клика по табу элементы внутри неё нефокусируемы (.focus() на
  // скрытом элементе тихо ничего не делает), проверено эмпирически.
  await page.click("input.tablinks[value=\"Программа\"]");

  const beforeEdit = await page.evaluate(() => document.getElementById("pvolume0").value);
  if (beforeEdit !== "100") {
    throw new Error("initial program row not rendered as expected, pvolume0=" + JSON.stringify(beforeEdit));
  }

  // --- (a) фокус внутри таблицы, ProgramNum на устройстве меняется ---
  await page.evaluate(() => {
    const field = document.getElementById("pvolume0");
    field.focus();
    field.value = "999"; // несохранённая правка пользователя
  });
  phase = "next";
  await page.waitForFunction(() => {
    const badge = document.getElementById("progStaleBadge");
    return badge && badge.style.display !== "none";
  }, null, { timeout: 20000 });

  const during = await page.evaluate(() => ({
    value: document.getElementById("pvolume0").value,
    badgeDisplay: document.getElementById("progStaleBadge").style.display,
    focused: document.activeElement && document.activeElement.id
  }));
  if (during.value !== "999") {
    throw new Error("unsaved edit was wiped while field still focused, pvolume0=" + JSON.stringify(during.value));
  }
  if (during.focused !== "pvolume0") {
    throw new Error("focus unexpectedly moved away from pvolume0: " + JSON.stringify(during.focused));
  }

  // --- (b) фокус уходит из таблицы - перерисовка должна произойти ---
  await page.evaluate(() => document.getElementById("pvolume0").blur());
  await page.waitForFunction(() => {
    const badge = document.getElementById("progStaleBadge");
    return badge && badge.style.display === "none";
  }, null, { timeout: 5000 });

  const after = await page.evaluate(() => ({
    value: document.getElementById("pvolume0") ? document.getElementById("pvolume0").value : null,
    badgeDisplay: document.getElementById("progStaleBadge").style.display
  }));
  if (after.value !== "100") {
    throw new Error("table was not redrawn from source WProgram after focus left, pvolume0=" + JSON.stringify(after.value));
  }

  return { beforeEdit, during, after };
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-program-focus-redraw-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-program-focus-redraw-{os.getpid()}"

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
                .replace("__FIXTURE_START__", FIXTURE_ON)
                .replace("__FIXTURE_NEXT__", FIXTURE_NEXT_STEP)
            )
            run_cli(cli, session, ["run-code", browser_test], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Program focus-redraw browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Program focus-redraw browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Program focus-redraw browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
