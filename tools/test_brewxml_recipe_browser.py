#!/usr/bin/env python3
"""[Пиво 02.09 D10] Браузерная проверка импорта рецепта (data_raw/brewxml.htm).

Контекст (PLAN_D.md): brewxml.htm получил разбор нескольких RECIPE (D0/D1),
фильтр хмеля по USE (D2), схлопывание одинаковых TIME без лишней "B;0.00;1"
(D3), температуру первой строки M из рецепта (D4), мешалку выключенной на
C/F (D5), семантическую проверку строки программы через общую
SamovarApp.beerRowTypeOk (D6), безопасный разбор неполных рецептов (D7)
и textContent вместо innerHTML для NOTES (D9). Страница без шаблонов:
кнопка установки программы всегда доступна.

Тест гоняет НАСТОЯЩИЙ brewxml.htm в Chromium через playwright-cli и вызывает
loadBeerXML() напрямую с синтетическим File - так же, как реальный
onchange="loadBeerXML(this.files[0])". Часть фикстур - настоящие файлы из
"Тестовые рецепты пива/" (числа в ожиданиях посчитаны независимо от кода,
см. таблицу в PLAN_D.md), часть - минимальные синтетические XML для краевых
случаев (нет HOPS, нет MASH, NOTES с HTML).

Значения M-строки (D4) для реальных файлов - НЕ "68.90"/"65.00": get_object_value
округляет decimalAdjust'ом ЧИСЛО (68.9 -> 68.9, 65 -> 65), а не форматирует
строку с фиксированной точностью - хвостовые нули JS отбрасывает при
приведении числа к строке. Это существующее поведение (та же функция уже
форматирует STEP_TEMP температурных пауз), тест фиксирует его как есть.

BrewMate-фикстуру (windows-1251) сюда сознательно не берём: File([jsString])
кодирует ЛЮБОЙ переданный текст в UTF-8, а get_brewmate_info() читает файл
явно как windows-1251 (loadBeerXML) - кириллица после такого round-trip
превращается в мусор. Для проверки "два источника температуры затирания"
(D4) взяты два РАЗНЫХ BeerXML-файла (Diogenes 68.9 и Sample Blonde Ale 65).
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
RECIPES_DIR = ROOT / "Тестовые рецепты пива"

TWO_RECIPES = (RECIPES_DIR / "two_recipes.xml").read_text(encoding="utf-8")
NEIPA = (RECIPES_DIR / "AvgPerfectNortheastIPANEIPA.xml").read_text(encoding="utf-8")
DIOGENES = (RECIPES_DIR / "Diogenes Chocolate Cherry Stout 20240421.xml").read_text(encoding="utf-8")
SAMPLE_BLONDE = (RECIPES_DIR / "Sample Blonde Ale 20240421.xml").read_text(encoding="utf-8")

NO_HOPS = """<?xml version="1.0" encoding="UTF-8"?>
<RECIPES>
<RECIPE>
<NAME>Без хмеля</NAME>
<BOIL_TIME>45</BOIL_TIME>
<FERMENTABLES><FERMENTABLE><NAME>Солод</NAME><AMOUNT>5</AMOUNT></FERMENTABLE></FERMENTABLES>
<MASH><MASH_STEPS><MASH_STEP><NAME>Шаг</NAME><STEP_TEMP>65</STEP_TEMP><STEP_TIME>60</STEP_TIME></MASH_STEP></MASH_STEPS></MASH>
</RECIPE>
</RECIPES>
"""

NO_MASH = """<?xml version="1.0" encoding="UTF-8"?>
<RECIPES>
<RECIPE>
<NAME>Без затирания</NAME>
<BOIL_TIME>45</BOIL_TIME>
<FERMENTABLES><FERMENTABLE><NAME>Солод</NAME><AMOUNT>5</AMOUNT></FERMENTABLE></FERMENTABLES>
<HOPS><HOP><NAME>Хмель</NAME><USE>Boil</USE><TIME>30</TIME><AMOUNT>20</AMOUNT></HOP></HOPS>
</RECIPE>
</RECIPES>
"""

NOTES_XSS = """<?xml version="1.0" encoding="UTF-8"?>
<RECIPES>
<RECIPE>
<NAME>NotesTest</NAME>
<BOIL_TIME>30</BOIL_TIME>
<NOTES>&lt;img src=x onerror=window.__pwned=true&gt;</NOTES>
<FERMENTABLES><FERMENTABLE><NAME>Солод</NAME><AMOUNT>5</AMOUNT></FERMENTABLE></FERMENTABLES>
<MASH><MASH_STEPS><MASH_STEP><NAME>Шаг</NAME><STEP_TEMP>65</STEP_TEMP><STEP_TIME>60</STEP_TIME></MASH_STEP></MASH_STEPS></MASH>
</RECIPE>
</RECIPES>
"""

# [ревью 02.09, п.1] хмель без TIME (t = NaN) не должен сдвигать bth для последующих строк B.
# Порядок хмелей в файле [без TIME, 30, 10] при BOIL_TIME=60: хмель без TIME пропускается,
# оракул независимо от кода: 30, 20, 10 (сумма 60).
HOPS_NO_TIME_EDGE = """<?xml version="1.0" encoding="UTF-8"?>
<RECIPES>
<RECIPE>
<NAME>ХмельБезTIME</NAME>
<BOIL_TIME>60</BOIL_TIME>
<FERMENTABLES><FERMENTABLE><NAME>Солод</NAME><AMOUNT>5</AMOUNT></FERMENTABLE></FERMENTABLES>
<HOPS>
<HOP><NAME>БезTIME</NAME><USE>Boil</USE><AMOUNT>10</AMOUNT></HOP>
<HOP><NAME>Тридцать</NAME><USE>Boil</USE><TIME>30</TIME><AMOUNT>15</AMOUNT></HOP>
<HOP><NAME>Десять</NAME><USE>Boil</USE><TIME>10</TIME><AMOUNT>5</AMOUNT></HOP>
</HOPS>
<MASH><MASH_STEPS><MASH_STEP><NAME>Шаг</NAME><STEP_TEMP>65</STEP_TEMP><STEP_TIME>60</STEP_TIME></MASH_STEP></MASH_STEPS></MASH>
</RECIPE>
</RECIPES>
"""

# [ревью 02.09, п.1] хмель с TIME > BOIL_TIME (после фильтра USE такое не ожидается, но не
# должно портить bth, если случилось) - оракул: одна строка B;60, без "90" в программе.
HOPS_OVER_BOIL_TIME = """<?xml version="1.0" encoding="UTF-8"?>
<RECIPES>
<RECIPE>
<NAME>ХмельБольшеBOIL</NAME>
<BOIL_TIME>60</BOIL_TIME>
<FERMENTABLES><FERMENTABLE><NAME>Солод</NAME><AMOUNT>5</AMOUNT></FERMENTABLE></FERMENTABLES>
<HOPS><HOP><NAME>Девяносто</NAME><USE>Boil</USE><TIME>90</TIME><AMOUNT>20</AMOUNT></HOP></HOPS>
<MASH><MASH_STEPS><MASH_STEP><NAME>Шаг</NAME><STEP_TEMP>65</STEP_TEMP><STEP_TIME>60</STEP_TIME></MASH_STEP></MASH_STEPS></MASH>
</RECIPE>
</RECIPES>
"""

# [ревью 02.09, п.2] пустой <INFUSE_TEMP></INFUSE_TEMP> парсится в {} (ключ есть, значения
# нет) - должен уступать STEP_TEMP, а не хардкоду 45.
EMPTY_INFUSE_TEMP = """<?xml version="1.0" encoding="UTF-8"?>
<RECIPES>
<RECIPE>
<NAME>ПустойInfuse</NAME>
<BOIL_TIME>60</BOIL_TIME>
<FERMENTABLES><FERMENTABLE><NAME>Солод</NAME><AMOUNT>5</AMOUNT></FERMENTABLE></FERMENTABLES>
<HOPS><HOP><NAME>Хмель</NAME><USE>Boil</USE><TIME>30</TIME><AMOUNT>20</AMOUNT></HOP></HOPS>
<MASH><MASH_STEPS><MASH_STEP><NAME>Шаг</NAME><INFUSE_TEMP></INFUSE_TEMP><STEP_TEMP>65.5</STEP_TEMP><STEP_TIME>60</STEP_TIME></MASH_STEP></MASH_STEPS></MASH>
</RECIPE>
</RECIPES>
"""

# [ревью 02.09, п.3] рецепт без узла FERMENTABLES - раньше падал с TypeError на
# R.FERMENTABLES.FERMENTABLE (в отличие от HOPS/YEASTS/MISCS из D7).
NO_FERMENTABLES = """<?xml version="1.0" encoding="UTF-8"?>
<RECIPES>
<RECIPE>
<NAME>БезСолода</NAME>
<BOIL_TIME>60</BOIL_TIME>
<HOPS><HOP><NAME>Хмель</NAME><USE>Boil</USE><TIME>30</TIME><AMOUNT>20</AMOUNT></HOP></HOPS>
<MASH><MASH_STEPS><MASH_STEP><NAME>Шаг</NAME><STEP_TEMP>65</STEP_TEMP><STEP_TIME>60</STEP_TIME></MASH_STEP></MASH_STEPS></MASH>
</RECIPE>
</RECIPES>
"""

# [ревью 02.09, п.4] PRIMARY_TEMP/FERMENTABLE_TIME шли через innerHTML - тот же класс XSS,
# что закрыт в D9 для NOTES.
PRIMARY_TEMP_XSS = """<?xml version="1.0" encoding="UTF-8"?>
<RECIPES>
<RECIPE>
<NAME>PrimXSS</NAME>
<BOIL_TIME>30</BOIL_TIME>
<PRIMARY_TEMP>&lt;img src=x onerror=window.__pwnedPrimary=true&gt;</PRIMARY_TEMP>
<FERMENTABLES><FERMENTABLE><NAME>Солод</NAME><AMOUNT>5</AMOUNT></FERMENTABLE></FERMENTABLES>
<HOPS><HOP><NAME>Хмель</NAME><USE>Boil</USE><TIME>15</TIME><AMOUNT>10</AMOUNT></HOP></HOPS>
<MASH><MASH_STEPS><MASH_STEP><NAME>Шаг</NAME><STEP_TEMP>65</STEP_TEMP><STEP_TIME>60</STEP_TIME></MASH_STEP></MASH_STEPS></MASH>
</RECIPE>
</RECIPES>
"""

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const fixtures = __FIXTURES__;
  const errors = [];
  page.on("pageerror", error => errors.push("pageerror: " + error.message));

  await page.goto(baseUrl + "/brewxml.htm", { waitUntil: "load" });
  await page.waitForTimeout(100);

  const setprogram = await page.evaluate(() => ({
    disabled: document.getElementById("setprogram").disabled,
    beerModeAttr: document.body.getAttribute("data-is-beer-mode")
  }));
  if (setprogram.disabled) throw new Error("brewxml.htm: setprogram must stay enabled: " + JSON.stringify(setprogram));
  if (setprogram.beerModeAttr !== null) throw new Error("brewxml.htm: data-is-beer-mode must not be on <body>: " + JSON.stringify(setprogram));

  const results = await page.evaluate(async (f) => {
    function loadOnce(text, name) {
      return new Promise(resolve => {
        loadBeerXML(new File([text], name));
        setTimeout(() => resolve(), 60);
      });
    }
    const out = {};

    // 1) [D0/D1] несколько RECIPE -> select с двумя пунктами, смена значения меняет NAME/program
    await loadOnce(f.twoRecipes, "two_recipes.xml");
    const row = document.getElementById("recipe-select-row");
    const select = document.getElementById("recipe-select");
    out.selectVisible = row.style.display !== "none";
    out.optionCount = select.options.length;
    out.firstName = document.getElementById("NAME").textContent;
    const firstProgram = window.program;
    select.value = "1";
    select.dispatchEvent(new Event("change"));
    await new Promise(r => setTimeout(r, 30));
    out.secondName = document.getElementById("NAME").textContent;
    out.secondProgram = window.program;
    out.programChanged = window.program !== firstProgram;

    // 2) [D2/D3] NEIPA: только Boil-хмель, схлопнутые одинаковые TIME
    await loadOnce(f.neipa, "neipa.xml");
    out.neipaIsProgram = window.is_program;
    out.neipaProgram = window.program;
    // [D1] после файла с одним рецептом список выбора снова скрыт и пуст
    out.selectHiddenAfterSingle = row.style.display === "none";
    out.optionCountAfterSingle = select.options.length;

    // 3) [D7] рецепт без HOPS - валиден, одна строка B на весь BOIL_TIME
    await loadOnce(f.noHops, "no_hops.xml");
    out.noHopsIsProgram = window.is_program;
    out.noHopsProgram = window.program;

    // 4) [D7] рецепт без MASH - явная ошибка без слова "повреждён"
    await loadOnce(f.noMash, "no_mash.xml");
    out.noMashIsProgram = window.is_program;
    out.noMashError = (document.getElementById("request_error") || {}).textContent || "";

    SamovarApp.clearRequestError();

    // 5) [D9] NOTES не исполняет вложенный HTML
    await loadOnce(f.notesXss, "notes_xss.xml");
    const notesEl = document.getElementById("NOTES");
    out.notesChildren = notesEl.children.length;
    out.notesText = notesEl.textContent;
    out.pwned = window.__pwned === true;

    // 6) [D4] температура первой строки M - из рецепта, два источника
    await loadOnce(f.diogenes, "diogenes.xml");
    out.diogenesFirstLine = window.program.split("\n")[0];
    await loadOnce(f.sampleBlonde, "sample_blonde.xml");
    out.sampleBlondeFirstLine = window.program.split("\n")[0];
    out.blondeIbu = document.getElementById("IBU").textContent;
    out.blondeOg = document.getElementById("OG").textContent;
    out.blondeFermTime = document.getElementById("FERMENTABLE_TIME").textContent;
    out.blondeIngr = document.getElementById("ingredients").textContent;
    out.blondeEquip = document.getElementById("EQUIPMENT").textContent;

    // 7) [D5] мешалка выключена на C/F
    const progLines = window.program.trim().split("\n");
    out.cLine = progLines.find(l => l[0] === "C") || "";
    out.fLine = progLines.find(l => l[0] === "F") || "";

    // 8) [D6] семантика строки: температура на "M"/"B" не по правилам типа
    out.errM = validateBeerProgramText("M;68.00;5;1^-1^2^3;0");
    out.errB = validateBeerProgramText("B;68.00;10;1^-1^2^3;0");

    // 9) [ревью п.1, случай а] хмель без TIME не сдвигает bth для последующих строк B
    await loadOnce(f.hopsNoTimeEdge, "hops_no_time.xml");
    out.noTimeHopIsProgram = window.is_program;
    out.noTimeHopProgram = window.program;

    // 10) [ревью п.1, случай б] хмель с TIME > BOIL_TIME не сдвигает bth и не попадает в B
    await loadOnce(f.hopsOverBoil, "hops_over_boil.xml");
    out.overBoilProgram = window.program;

    // 11) [ревью п.2] пустой INFUSE_TEMP уступает STEP_TEMP, а не хардкоду 45
    await loadOnce(f.emptyInfuse, "empty_infuse.xml");
    out.emptyInfuseFirstLine = window.program.split("\n")[0];

    // 12) [ревью п.3] рецепт без FERMENTABLES не падает с TypeError
    await loadOnce(f.noFermentables, "no_fermentables.xml");
    out.noFermIsProgram = window.is_program;
    out.noFermError = (document.getElementById("request_error") || {}).textContent || "";

    // 13) [ревью п.4] PRIMARY_TEMP не исполняет вложенный HTML
    await loadOnce(f.primaryTempXss, "primary_temp_xss.xml");
    const primaryEl = document.getElementById("PRIMARY_TEMP");
    out.primaryTempChildren = primaryEl.children.length;
    out.primaryTempText = primaryEl.textContent;
    out.primaryPwned = window.__pwnedPrimary === true;
    SamovarApp.clearRequestError();

    const brewmateXml = `<?xml version="1.0"?><recipe><namerecipe>Тест BrewMate</namerecipe><style>IPA</style><part>20</part><timeboil>60</timeboil><timebro>14</timebro><tempbro>18</tempbro><np>1.055</np><ibu>40</ibu><abv>5.8</abv><yeast>US-05</yeast><grains><grain><grainname>Пилснер</grainname><grainkg>5</grainkg></grain></grains><hops><hop><hopname>Cascade</hopname><hopgr>20</hopgr><hoptime>60</hoptime><hopalpha>6.5</hopalpha><hopuse>Кипячение</hopuse></hop><hop><hopname>Citra</hopname><hopgr>30</hopgr><hoptime>30</hoptime><hopalpha>12</hopalpha><hopuse>сухое охмеление</hopuse></hop></hops><zatirs><zatir><zatirgr>65</zatirgr><zatirtime>60</zatirtime></zatir></zatirs></recipe>`;
    get_brewmate_info(brewmateXml);
    out.bmName = document.getElementById("NAME").textContent;
    out.bmIbu = document.getElementById("IBU").textContent;
    out.bmFerm = document.getElementById("FERMENTABLE_TIME").textContent;
    out.bmOg = document.getElementById("OG").textContent;
    out.bmIngr = document.getElementById("ingredients").textContent;
    out.bmProgram = window.program;
    out.bmIsProgram = window.is_program;

    return out;
  }, fixtures);

  // ---------- assert: 1) выбор рецепта ----------
  if (!results.selectVisible || results.optionCount !== 2) {
    throw new Error("recipe-select-row must be visible with 2 options for two_recipes.xml: " + JSON.stringify(results));
  }
  if (results.firstName !== "Sample Blonde Ale" || results.secondName !== "Avg. Perfect Northeast IPA (NEIPA)") {
    throw new Error("recipe select did not switch NAME correctly: " + JSON.stringify({ first: results.firstName, second: results.secondName }));
  }
  if (!results.programChanged) throw new Error("selecting the second RECIPE must rebuild program");

  // ---------- assert: 2) NEIPA ----------
  if (!results.neipaIsProgram) throw new Error("NEIPA recipe must produce a valid program");
  if (!results.selectHiddenAfterSingle || results.optionCountAfterSingle !== 0) {
    throw new Error("recipe-select-row must be hidden and empty after loading a single-RECIPE file: " +
      JSON.stringify({ hidden: results.selectHiddenAfterSingle, options: results.optionCountAfterSingle }));
  }
  const neipaBTimes = results.neipaProgram.split("\n")
    .filter(l => l[0] === "B")
    .map(l => Number(l.split(";")[2]));
  const neipaSum = neipaBTimes.reduce((a, b) => a + b, 0);
  if (neipaSum !== 60) throw new Error("NEIPA: sum of B rows must equal BOIL_TIME=60, got " + neipaSum + " (" + JSON.stringify(neipaBTimes) + ")");
  if (neipaBTimes.some(t => t > 60)) throw new Error("NEIPA: a B row exceeds BOIL_TIME: " + JSON.stringify(neipaBTimes));
  if (results.neipaProgram.includes("10080") || results.neipaProgram.includes("4320")) {
    throw new Error("NEIPA: Dry Hop timing leaked into the program: " + results.neipaProgram);
  }

  // ---------- assert: 3) без HOPS ----------
  if (!results.noHopsIsProgram) throw new Error("recipe without HOPS must still produce a valid program: " + results.noHopsProgram);
  const noHopsBRows = results.noHopsProgram.split("\n").filter(l => l[0] === "B");
  if (noHopsBRows.length !== 1 || noHopsBRows[0] !== "B;0.00;45;1^-1^2^3;0") {
    throw new Error("recipe without HOPS must give exactly one B row spanning BOIL_TIME: " + JSON.stringify(noHopsBRows));
  }

  // ---------- assert: 4) без MASH ----------
  if (results.noMashIsProgram) throw new Error("recipe without MASH must not become a program");
  if (!results.noMashError.includes("нет шагов затирания")) {
    throw new Error("recipe without MASH must report the missing mash steps: " + results.noMashError);
  }
  if (results.noMashError.includes("повреждён")) {
    throw new Error("recipe without MASH is not a corrupted file - message must not say so: " + results.noMashError);
  }

  // ---------- assert: 5) NOTES ----------
  if (results.notesChildren !== 0) throw new Error("NOTES must not parse nested markup into elements: " + results.notesChildren);
  if (results.pwned) throw new Error("NOTES onerror must not execute");
  if (!results.notesText.includes("<img")) throw new Error("NOTES must keep the markup as plain text: " + results.notesText);

  // ---------- assert: 6) температура первой строки M ----------
  if (results.diogenesFirstLine !== "M;68.9;0;1^-1^2^3;0") {
    throw new Error("Diogenes first M line must use recipe STEP_TEMP 68.9: " + results.diogenesFirstLine);
  }
  if (results.sampleBlondeFirstLine !== "M;65;0;1^-1^2^3;0") {
    throw new Error("Sample Blonde Ale first M line must use recipe STEP_TEMP 65: " + results.sampleBlondeFirstLine);
  }

  // ---------- assert: 7) мешалка на C/F ----------
  if (!results.cLine.endsWith(";0^0^0^0;0") || !results.fLine.endsWith(";0^0^0^0;0")) {
    throw new Error("C/F rows must keep the mixer off (0^0^0^0): " + JSON.stringify({ c: results.cLine, f: results.fLine }));
  }

  // ---------- assert: 8) семантика строки ----------
  if (!results.errM || !results.errM.includes("шаг 1")) {
    throw new Error("validateBeerProgramText must reject M row with non-zero time: " + JSON.stringify(results.errM));
  }
  if (!results.errB || !results.errB.includes("шаг 1")) {
    throw new Error("validateBeerProgramText must reject B row with non-zero temp: " + JSON.stringify(results.errB));
  }

  // ---------- assert: 9) хмель без TIME не сдвигает bth ----------
  if (!results.noTimeHopIsProgram) throw new Error("hop without TIME must still produce a valid program: " + results.noTimeHopProgram);
  const noTimeBTimes = results.noTimeHopProgram.split("\n").filter(l => l[0] === "B").map(l => Number(l.split(";")[2]));
  const noTimeSum = noTimeBTimes.reduce((a, b) => a + b, 0);
  if (noTimeSum !== 60) throw new Error("hop without TIME: sum of B rows must equal BOIL_TIME=60, got " + noTimeSum + " (" + JSON.stringify(noTimeBTimes) + ")");
  if (JSON.stringify(noTimeBTimes) !== JSON.stringify([30, 20, 10])) {
    throw new Error("hop without TIME must not shift bth: expected [30,20,10], got " + JSON.stringify(noTimeBTimes));
  }

  // ---------- assert: 10) хмель с TIME > BOIL_TIME не сдвигает bth ----------
  const overBoilBTimes = results.overBoilProgram.split("\n").filter(l => l[0] === "B").map(l => Number(l.split(";")[2]));
  const overBoilSum = overBoilBTimes.reduce((a, b) => a + b, 0);
  if (overBoilSum !== 60) throw new Error("hop with TIME>BOIL_TIME: sum of B rows must equal BOIL_TIME=60, got " + overBoilSum + " (" + JSON.stringify(overBoilBTimes) + ")");
  if (results.overBoilProgram.split("\n").some(l => l[0] === "B" && l.split(";")[2] === "90")) {
    throw new Error("hop with TIME>BOIL_TIME must not leak into a B row: " + results.overBoilProgram);
  }

  // ---------- assert: 11) пустой INFUSE_TEMP уступает STEP_TEMP ----------
  if (results.emptyInfuseFirstLine !== "M;65.5;0;1^-1^2^3;0") {
    throw new Error("empty INFUSE_TEMP must fall back to STEP_TEMP=65.5: " + results.emptyInfuseFirstLine);
  }

  // ---------- assert: 12) рецепт без FERMENTABLES ----------
  if (!results.noFermIsProgram) throw new Error("recipe without FERMENTABLES must still produce a valid program: " + results.noFermError);
  if (results.noFermError) throw new Error("recipe without FERMENTABLES must not raise an error: " + results.noFermError);

  // ---------- assert: 13) PRIMARY_TEMP ----------
  if (results.primaryTempChildren !== 0) throw new Error("PRIMARY_TEMP must not parse nested markup into elements: " + results.primaryTempChildren);
  if (results.primaryPwned) throw new Error("PRIMARY_TEMP onerror must not execute");
  if (!results.primaryTempText.includes("<img")) throw new Error("PRIMARY_TEMP must keep the markup as plain text: " + results.primaryTempText);

  if (results.blondeIbu !== "19.8") throw new Error("Sample Blonde IBU must be 19.8: " + results.blondeIbu);
  if (results.blondeOg !== "1.044") throw new Error("Sample Blonde OG must be 1.044: " + results.blondeOg);
  if (results.blondeFermTime !== "14 дней") throw new Error("Sample Blonde fermentation time must come from PRIMARY_AGE: " + results.blondeFermTime);
  if (!results.blondeIngr.includes("Servomyces")) throw new Error("misc TYPE=Other must be listed: " + results.blondeIngr);
  if (!results.blondeIngr.includes("Кипячение") || !results.blondeIngr.includes("Сухое охмеление")) {
    throw new Error("hop USE must be shown: " + results.blondeIngr);
  }
  if (!results.blondeIngr.includes("5 г") && !results.blondeIngr.includes("5.0 г")) {
    throw new Error("hop AMOUNT 0.005 kg must display as grams: " + results.blondeIngr);
  }
  if (results.blondeEquip !== "Grainfather") throw new Error("equipment name missing: " + results.blondeEquip);

  if (!results.bmIsProgram) throw new Error("BrewMate recipe must produce a program");
  if (results.bmName !== "Тест BrewMate") throw new Error("BrewMate NAME mismatch: " + results.bmName);
  if (results.bmIbu !== "40") throw new Error("BrewMate IBU mismatch: " + results.bmIbu);
  if (results.bmFerm !== "14 дней") throw new Error("BrewMate timebro must fill fermentation days: " + results.bmFerm);
  if (results.bmOg !== "1.055") throw new Error("BrewMate np/OG mismatch: " + results.bmOg);
  if (!results.bmIngr.includes("20 г") || !results.bmIngr.includes("Cascade")) {
    throw new Error("BrewMate hopgr is grams: " + results.bmIngr);
  }
  if (!results.bmIngr.includes("Сухое охмеление") || !results.bmIngr.includes("Кипячение")) {
    throw new Error("BrewMate hopuse must be mapped: " + results.bmIngr);
  }
  const bmB = results.bmProgram.split("\n").filter(l => l[0] === "B").map(l => Number(l.split(";")[2]));
  if (JSON.stringify(bmB) !== JSON.stringify([60])) {
    throw new Error("BrewMate dry hop must not create a boil split: " + JSON.stringify(bmB) + " program=" + results.bmProgram);
  }

  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { results, setprogram };
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-brewxml-recipe-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)

        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-brewxml-recipe-{os.getpid()}"

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
            fixtures = {
                "twoRecipes": TWO_RECIPES,
                "neipa": NEIPA,
                "diogenes": DIOGENES,
                "sampleBlonde": SAMPLE_BLONDE,
                "noHops": NO_HOPS,
                "noMash": NO_MASH,
                "notesXss": NOTES_XSS,
                "hopsNoTimeEdge": HOPS_NO_TIME_EDGE,
                "hopsOverBoil": HOPS_OVER_BOIL_TIME,
                "emptyInfuse": EMPTY_INFUSE_TEMP,
                "noFermentables": NO_FERMENTABLES,
                "primaryTempXss": PRIMARY_TEMP_XSS,
            }
            browser_test = (
                BROWSER_TEST
                .replace("__BASE_URL__", json.dumps(base_url))
                .replace("__FIXTURES__", json.dumps(fixtures))
            )
            run_cli(cli, session, ["run-code", browser_test], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"brewxml.htm recipe import browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"brewxml.htm recipe import browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("brewxml.htm recipe import browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
