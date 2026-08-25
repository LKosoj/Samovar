#!/usr/bin/env python3
"""[T34.7] Браузерная проверка валидации загружаемых файлов программы
(program.htm, loadFile) и рецепта (brewxml.htm, loadBeerXML).

Контекст бага (SOLUTIONS_2026-08-24.md, Уровень 4, пункт 7): оба обработчика
раньше принимали содержимое файла без какой-либо проверки структуры - битый
или чужой файл молча становился программой с мусорными значениями (в т.ч.
буквальной строкой "Нет в рецепте", попадающей в числовое поле, или NaN).

Правка: validateProgramFileText() (program.htm) и validateBeerProgramText()
+ проверка parsererror/обязательных узлов (brewxml.htm) отклоняют файл ДО
того, как он попадёт в WProgram1/program, и показывают причину через
SamovarApp.showRequestError() (переиспользован существующий #request_error,
никакого нового механизма показа ошибок не заведено).

Тест гоняет НАСТОЯЩИЕ program.htm и brewxml.htm в Chromium через
playwright-cli и вызывает loadFile()/loadBeerXML() напрямую с синтетическим
File - так же, как это делает реальный `onchange="loadFile(this.files[0])"`
(файл передаётся в обработчик уже как File, без анализа самого <input>).
Валидная строка программы для program.htm - тот же формат/значения, что и
фикстура program.txt в tools/test_accessibility_ui_browser.py ("0;1;100;H;0",
без завершающего перевода строки - он разбирается calc_program() отдельной
пустой строкой и не имеет отношения к проверке валидатора). Для brewxml.htm
переиспользован реальный BeerXML "Тестовые рецепты пива/Sample Blonde Ale
20240421.xml" (чистый ASCII, без BrewMate-ветки/windows-1251, так что
раунд-трип через JS-строку/Blob(UTF-8)/FileReader(UTF-8) не искажает контент).
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
VALID_RECIPE = (ROOT / "Тестовые рецепты пива" / "Sample Blonde Ale 20240421.xml").read_text(
    encoding="ascii"
)

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const validRecipe = __VALID_RECIPE__;
  const errors = [];
  page.on("pageerror", error => errors.push("pageerror: " + error.message));

  // ---------- program.htm: loadFile() ----------
  await page.goto(baseUrl + "/program.htm", { waitUntil: "load" });
  await page.waitForTimeout(100);

  const programCases = await page.evaluate(async (validText) => {
    function loadOnce(text, name) {
      return new Promise(resolve => {
        loadFile(new File([text], name));
        setTimeout(() => resolve(), 50);
      });
    }
    // #request_error создаётся ЛЕНИВО (requestErrorElement() в app.js) - на
    // самой первой проверке его в DOM ещё может не быть, поэтому получаем
    // заново при каждом чтении, а не один раз в начале.
    function errorState() {
      const el = document.getElementById("request_error");
      return { shown: !!el && el.style.display === "block", text: el ? el.textContent : "" };
    }
    const wp1 = document.getElementById("WProgram1");
    const out = {};

    // На старте program.htm сам пытается подтянуть /ajax_col_params, которого
    // на голом статическом тестовом сервере нет - баннер #request_error уже
    // занят посторонней ошибкой (HTTP 404). Сбрасываем её тем же существующим
    // SamovarApp.clearRequestError(), чтобы проверять именно валидатор файла,
    // а не то, что баннер вообще когда-либо был скрыт с начала загрузки страницы.
    SamovarApp.clearRequestError();

    // валидный файл - принимается, ошибка не показывается
    await loadOnce(validText, "program.txt");
    out.valid = { value: wp1.value, errorShown: errorState().shown };

    const beforeInvalid = wp1.value;

    await loadOnce("1;2;3\n", "bad_fields.txt");
    out.badFieldCount = { error: errorState().text, valueUnchanged: wp1.value === beforeInvalid };

    await loadOnce("11;100;20;H;30\n", "bad_capacity.txt");
    out.badCapacity = { error: errorState().text, valueUnchanged: wp1.value === beforeInvalid };

    await loadOnce("0;100;20;Z;30\n", "bad_type.txt");
    out.badType = { error: errorState().text, valueUnchanged: wp1.value === beforeInvalid };

    await loadOnce("0;9000;20;H;30\n", "bad_speed.txt");
    out.badSpeed = { error: errorState().text, valueUnchanged: wp1.value === beforeInvalid };

    const manyLines = Array.from({ length: 21 }, () => "0;1;10;H;0").join("\n") + "\n";
    await loadOnce(manyLines, "too_many.txt");
    out.tooManyRows = { error: errorState().text, valueUnchanged: wp1.value === beforeInvalid };

    return out;
  }, "0;1;100;H;0");

  if (programCases.valid.errorShown || programCases.valid.value !== "0;1;100;H;0") {
    throw new Error("program.htm rejected a valid file: " + JSON.stringify(programCases.valid));
  }
  if (!programCases.badFieldCount.error.includes("5 полей") || !programCases.badFieldCount.valueUnchanged) {
    throw new Error("program.htm did not reject bad field count: " + JSON.stringify(programCases.badFieldCount));
  }
  if (!programCases.badCapacity.error.includes("ёмкости") || !programCases.badCapacity.valueUnchanged) {
    throw new Error("program.htm did not reject bad capacity: " + JSON.stringify(programCases.badCapacity));
  }
  if (!programCases.badType.error.includes("тип") || !programCases.badType.valueUnchanged) {
    throw new Error("program.htm did not reject bad type: " + JSON.stringify(programCases.badType));
  }
  if (!programCases.badSpeed.error.includes("корост") || !programCases.badSpeed.valueUnchanged) {
    throw new Error("program.htm did not reject out-of-range speed: " + JSON.stringify(programCases.badSpeed));
  }
  if (!programCases.tooManyRows.error.includes("максимум 20") || !programCases.tooManyRows.valueUnchanged) {
    throw new Error("program.htm did not reject too many rows: " + JSON.stringify(programCases.tooManyRows));
  }

  // ---------- brewxml.htm: loadBeerXML() ----------
  await page.goto(baseUrl + "/brewxml.htm", { waitUntil: "load" });
  await page.waitForTimeout(100);

  const brewCases = await page.evaluate(async (validXml) => {
    function loadOnce(text, name) {
      return new Promise(resolve => {
        loadBeerXML(new File([text], name));
        setTimeout(() => resolve(), 50);
      });
    }
    function errorState() {
      const el = document.getElementById("request_error");
      return { shown: !!el && el.style.display === "block", text: el ? el.textContent : "" };
    }
    const out = {};

    SamovarApp.clearRequestError();
    await loadOnce(validXml, "recipe.xml");
    out.valid = {
      isProgram: window.is_program,
      errorShown: errorState().shown,
      name: document.getElementById("NAME").textContent
    };

    await loadOnce("this is not xml at all <<<", "garbage.xml");
    out.notXml = { isProgram: window.is_program, error: errorState().text };

    await loadOnce("<recipes><item>hi</item></recipes>", "wrong_structure.xml");
    out.wrongStructure = { isProgram: window.is_program, error: errorState().text };

    return out;
  }, validRecipe);

  if (!brewCases.valid.isProgram || brewCases.valid.errorShown || !brewCases.valid.name) {
    throw new Error("brewxml.htm rejected a valid recipe: " + JSON.stringify(brewCases.valid));
  }
  if (brewCases.notXml.isProgram || !brewCases.notXml.error.includes("повреждён")) {
    throw new Error("brewxml.htm did not reject non-XML content: " + JSON.stringify(brewCases.notXml));
  }
  if (brewCases.wrongStructure.isProgram || !brewCases.wrongStructure.error.includes("RECIPES")) {
    throw new Error("brewxml.htm did not reject XML missing RECIPES/RECIPE: " + JSON.stringify(brewCases.wrongStructure));
  }

  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { programCases, brewCases };
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-program-file-validation-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-program-file-validation-{os.getpid()}"

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
                .replace("__VALID_RECIPE__", json.dumps(VALID_RECIPE))
            )
            run_cli(cli, session, ["run-code", browser_test], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Program/recipe file validation browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Program/recipe file validation browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Program/recipe file validation browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
