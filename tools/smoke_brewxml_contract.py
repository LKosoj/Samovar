#!/usr/bin/env python3
"""[Пиво 02.09 D10] Текстовый пин ключевых контрактов data_raw/brewxml.htm
(пакет D: импорт рецепта BeerXML/BrewMate). Поведенческие проверки (суммы
времени, реальный DOM) - в браузерном tools/test_brewxml_recipe_browser.py;
здесь фиксируется, что нужные конструкции физически присутствуют в
исходнике, а старые/опасные - нет.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web_assets import COMPRESS

ROOT = Path(__file__).resolve().parents[1]
BREWXML_PAGE = ROOT / "data_raw" / "brewxml.htm"

errors = []

brewxml = BREWXML_PAGE.read_text(encoding="utf-8")

# D1: выбор рецепта при нескольких RECIPE в файле.
if 'id="recipe-select"' not in brewxml:
    errors.append("brewxml.htm: recipe-select control is missing")
if 'id="recipe-select-row"' not in brewxml:
    errors.append("brewxml.htm: recipe-select-row wrapper is missing")
if "function presentRecipe(" not in brewxml or "function selectRecipe(" not in brewxml:
    errors.append("brewxml.htm: presentRecipe/selectRecipe are missing")

# D2: в кипячение попадают только Boil/First Wort хмели.
if 'use === "boil" || use === "first wort"' not in brewxml:
    errors.append("brewxml.htm: boil hop USE filter (Boil/First Wort) is missing")

# D3: одинаковое TIME схлопывается в одну строку B (нет отдельной ветки на "<= 0").
if "if (t === lastTime) continue;" not in brewxml:
    errors.append("brewxml.htm: duplicate-TIME collapse (lastTime) is missing")
if '"B;0.00;1;1^-1^2^3;0\\n"' in brewxml:
    errors.append("brewxml.htm: stray single-minute B row (old TIME==BOIL_TIME bug) is back")

# D4: температура первой строки M - из рецепта (INFUSE_TEMP/STEP_TEMP), не хардкод.
# [ревью 02.09] typeof MASH[0].INFUSE_TEMP !== "undefined" ловит только отсутствие ключа,
# а пустой <INFUSE_TEMP></INFUSE_TEMP> парсится в {} (ключ есть, значения нет) и уводил
# мимо STEP_TEMP - теперь обе температуры идут через одну цепочку get_object_value.
if "get_object_value(MASH[0].INFUSE_TEMP)" not in brewxml or "get_object_value(MASH[0].STEP_TEMP)" not in brewxml:
    errors.append("brewxml.htm: mash-derived first M temperature is missing")
if "typeof MASH[0].INFUSE_TEMP" in brewxml:
    errors.append("brewxml.htm: old typeof-based INFUSE_TEMP check (misses empty tag) is back")
if 'program = "M;45.00;0;1^-1^2^3;0\\n";' in brewxml:
    errors.append("brewxml.htm: hardcoded 45.00 first M line is back")

# [ревью 02.09, п.1] хмель без TIME (NaN) или с TIME > BOIL_TIME не должен сдвигать bth
# для последующих строк B - невалидные хмели пропускаются без изменения счётчика.
if "!Number.isFinite(t) || t > bth" not in brewxml:
    errors.append("brewxml.htm: guard against non-finite/out-of-range hop TIME in the B-row loop is missing")

# [ревью 02.09, п.3] R.FERMENTABLES без защиты - рецепт без узла FERMENTABLES падал с TypeError,
# в отличие от HOPS/YEASTS/MISCS (D7).
if "R.FERMENTABLES &&" not in brewxml:
    errors.append("brewxml.htm: safe recipe access missing: R.FERMENTABLES &&")

# [ревью 02.09, п.4] PRIMARY_TEMP/FERMENTABLE_TIME - тот же класс XSS, что закрыт в D9 для NOTES.
if 'PRIMARY_TEMP").innerHTML' in brewxml:
    errors.append('brewxml.htm: PRIMARY_TEMP must not be set via innerHTML')
if 'FERMENTABLE_TIME").innerHTML' in brewxml:
    errors.append('brewxml.htm: FERMENTABLE_TIME must not be set via innerHTML')

# D5: мешалка выключена на строках C/F.
if ';0;0^0^0^0;0\\nF;' not in brewxml and '";0;0^0^0^0;0\\nF;"' not in brewxml:
    if 'C;" + pt + ";0;0^0^0^0;0\\nF;"' not in brewxml:
        errors.append("brewxml.htm: C/F rows must keep the mixer off (0^0^0^0)")

# D6: семантика строки программы проверяется общим правилом SamovarApp.beerRowTypeOk.
if "SamovarApp.initTheme(" not in brewxml or "SamovarApp.toggleTheme(" not in brewxml:
    errors.append("brewxml.htm: theme must use SamovarApp.initTheme/toggleTheme")
if 'id="themeToggle"' not in brewxml:
    errors.append("brewxml.htm: theme toggle is missing")

if "SamovarApp.beerRowTypeOk(" not in brewxml:
    errors.append("brewxml.htm: validateBeerProgramText does not call SamovarApp.beerRowTypeOk")
if "SamovarApp.beerRowTypeOk(" not in brewxml:
    errors.append("brewxml.htm: validateBeerProgramText does not call SamovarApp.beerRowTypeOk")
if "SamovarApp.buildBeerMashStageLines(" not in brewxml:
    errors.append("brewxml.htm: mash program must be built via SamovarApp.buildBeerMashStageLines")
if "SamovarApp.currentBeerBrewOrderId(" not in brewxml:
    errors.append("brewxml.htm: mash program must use the brew order from settings")
if 'id="BeerBrewOrder"' in brewxml:
    errors.append("brewxml.htm: brew order select must stay on setup.htm, not per recipe")
if 'id="mash-order-hints"' not in brewxml:
    errors.append("brewxml.htm: mash-order-hints is missing")

# D7: неполные рецепты не роняют разбор с TypeError - безопасные обращения и явная ошибка MASH.
for token in ("R.STYLE && R.STYLE.NAME", "R.HOPS && R.HOPS.HOP", "R.YEASTS && R.YEASTS.YEAST", "R.MISCS && R.MISCS.MISC"):
    if token not in brewxml:
        errors.append(f"brewxml.htm: safe recipe access missing: {token}")
if "в рецепте нет шагов затирания" not in brewxml:
    errors.append("brewxml.htm: missing-MASH error message is missing")
if "xmlSyntaxError" not in brewxml:
    errors.append("brewxml.htm: xmlSyntaxError marker (formatRecipeErrorMessage) is missing")

# Страница без шаблонов: иначе gzip на устройстве отдаст сырые %ПЛЕЙСХОЛДЕРЫ%.
if "%IsBeerMode%" in brewxml or "%v%" in brewxml:
    errors.append("brewxml.htm: template placeholders came back - файл нельзя сжимать")
if "dataset.isBeerMode" in brewxml or "data-is-beer-mode" in brewxml:
    errors.append("brewxml.htm: beer-mode gate came back")
if "brewxml.htm" not in COMPRESS:
    errors.append("brewxml.htm: должен быть в COMPRESS (tools/build_web_assets.py)")

if 'NOTES").textContent' not in brewxml and 'setSpec("NOTES"' not in brewxml:
    errors.append('brewxml.htm: NOTES must be set via textContent/setSpec')
if 'NOTES").innerHTML' in brewxml:
    errors.append('brewxml.htm: NOTES must not be set via innerHTML')

if "function formatAmount(" not in brewxml:
    errors.append("brewxml.htm: formatAmount is missing")
if "function mapBrewMateHopUse(" not in brewxml:
    errors.append("brewxml.htm: BrewMate hop USE mapping is missing")
if "PRIMARY_AGE" not in brewxml:
    errors.append("brewxml.htm: PRIMARY_AGE (BeerXML fermentation days) is missing")
if 'id="IBU"' not in brewxml or 'id="OG"' not in brewxml:
    errors.append("brewxml.htm: recipe OG/IBU fields are missing")
if "ingDetail" not in brewxml:
    errors.append("brewxml.htm: ingredient detail column is missing")
if 'get_object_value(misc.TYPE) == "Flavor"' in brewxml:
    errors.append("brewxml.htm: old Flavor/Fining-only misc filter is back")

if errors:
    print("brewxml.htm contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("brewxml.htm contract smoke check passed")
