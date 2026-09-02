#!/usr/bin/env python3
"""[T34.1] Браузерная проверка: поле "процент" в таблице программы (program.htm)
больше не портит значение, пока пользователь его печатает, но всё ещё
пересчитывает сводку "вживую" (на каждое нажатие клавиши), а поле "скорость"
(типичный "тяжёлый" в остальном ввод) больше НЕ пересчитывает сводку на
каждое нажатие - только когда пользователь заканчивает ввод (событие change).

Контекст бага (SOLUTIONS_2026-08-24.md, Уровень 4, пункт 1): все поля таблицы
программы были на oninput, а set_num() безусловно обрезал значение поля
"процент" по первой точке/запятой на КАЖДЫЙ вызов. Если пользователь печатал
"12.5" посимвольно, после ввода "12." пересчёт уже успевал стереть точку -
поле становилось "12", и следующая цифра "5" дописывалась в конец, давая
испорченные "125" вместо "12.5".

Правка: set_num() больше вообще не трогает и не обрезает поле "процент" -
обрезка дробной части вынесена в отдельную функцию truncatePercentField(),
навешанную на onchange САМОГО поля, поэтому она срабатывает только когда
пользователь закончил печатать и увёл фокус, а не на каждый пересчёт
set_num() для любой строки таблицы. Поле "процент" держит oninput (это же
событие требует существующий tools/test_numeric_input_ui_browser.py - сводка
должна обновляться мгновенно), поле "скорость" переведено на onchange
(сводка обновляется только при уходе фокуса, а не на каждый символ).

Тест гоняет НАСТОЯЩИЙ program.htm в Chromium через playwright-cli.
"""
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
from test_stale_telemetry_dimming_browser import FIXTURE_ON
import functools

ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const fixture = __FIXTURE__;
  await page.route("**/ajax*", async route => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixture) });
  });
  await page.goto(baseUrl + "/program.htm", { waitUntil: "load" });
  await page.waitForTimeout(100);

  const result = await page.evaluate(() => {
    // --- (1) "процент": печатаем "12.5" по одному символу через реальные
    // события input и проверяем, что значение поля НЕ обрезается посимвольно
    // (старый баг: после "12." пересчёт стирал точку раньше, чем допечатана "5").
    const percent = document.getElementById("percent0");
    percent.focus();
    percent.value = "";
    const typed = [];
    for (const ch of "12.5") {
      percent.value = percent.value + ch;
      percent.dispatchEvent(new Event("input", { bubbles: true }));
      typed.push(percent.value);
    }
    // Сводка должна успеть пересчитаться "вживую" - если бы percent молча
    // потерял oninput, WProgram1 (сырой textarea) не подхватил бы "12.5".
    const rawWhileTyping = document.getElementById("WProgram1").value;

    // Уводим фокус - должно сработать onchange и ОБРЕЗАТЬ дробную часть.
    const otherField = document.getElementById("speed0");
    otherField.focus();
    percent.dispatchEvent(new Event("change", { bubbles: true }));
    const afterBlur = percent.value;

    // --- (2) "скорость": больше не пересчитывает сводку на каждое нажатие ---
    const speed = document.getElementById("speed0");
    speed.focus();
    const rawBefore = document.getElementById("WProgram1").value;
    const originalSpeed = speed.value;
    speed.value = "12345";
    speed.dispatchEvent(new Event("input", { bubbles: true }));
    const rawAfterInput = document.getElementById("WProgram1").value;
    speed.dispatchEvent(new Event("change", { bubbles: true }));
    const rawAfterChange = document.getElementById("WProgram1").value;

    return {
      typed,
      rawWhileTyping,
      afterBlur,
      rawBefore,
      originalSpeed,
      rawAfterInput,
      rawAfterChange
    };
  });

  if (JSON.stringify(result.typed) !== JSON.stringify(["1", "12", "12.", "12.5"])) {
    throw new Error("percent field value corrupted mid-typing: " + JSON.stringify(result.typed));
  }
  if (!result.rawWhileTyping.includes("12.5")) {
    throw new Error("percent input did not recalc live (WProgram1 missing 12.5): " + JSON.stringify(result.rawWhileTyping));
  }
  if (result.afterBlur !== "12") {
    throw new Error("percent field must be truncated to '12' after losing focus, got " + JSON.stringify(result.afterBlur));
  }
  if (result.rawAfterInput !== result.rawBefore) {
    throw new Error("speed field must NOT recalc on bare input event, but WProgram1 changed: " +
      JSON.stringify({ before: result.rawBefore, afterInput: result.rawAfterInput }));
  }
  if (!result.rawAfterChange.includes("12345") || result.rawAfterChange === result.rawAfterInput) {
    throw new Error("speed field must recalc on change event: " + JSON.stringify(result.rawAfterChange));
  }

  return result;
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-program-percent-input-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-program-percent-input-{os.getpid()}"

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
                .replace("__FIXTURE__", FIXTURE_ON)
            )
            run_cli(cli, session, ["run-code", browser_test], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Program percent-input browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Program percent-input browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Program percent-input browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
