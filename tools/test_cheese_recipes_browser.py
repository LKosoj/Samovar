#!/usr/bin/env python3
"""S5: CheeseXML catalogue, local import, conversion preview and one apply."""

import functools
import http.server
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_XML = ROOT / "tools/fixtures/cheese_recipes_s5.xml"
FIXTURE_JSON = json.loads((ROOT / "tools/fixtures/cheese_recipes_s5.json").read_text(encoding="utf-8"))
FIXTURE_JSON["content"] = {"xml": FIXTURE_XML.read_text(encoding="utf-8")}
TOKEN = "0123456789abcdef0123456789abcdef"

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__, recipe = __RECIPE__, xmlPath = __XML_PATH__, badXmlPath = __BAD_XML_PATH__, maxXmlPath = __MAX_XML_PATH__, overXmlPath = __OVER_XML_PATH__, token = __TOKEN__;
  const apiRequests = [], programPosts = [], commands = [], errors = [];
  let i2cMixer = false;
  const expect = (condition, message) => { if (!condition) throw new Error(message); };
  await page.addInitScript(() => Object.defineProperty(navigator, 'language', {configurable:true, get:() => 'en-US'}));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/cheese-recipes-bootstrap', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({mode:7,i2cMixer:i2cMixer,blynkToken:token})
  }));
  await page.route('https://www.samovar-tool.ru/cheesexml/v1/**', route => {
    const request = route.request(), url = request.url();
    const catalogStyle = page.url().includes('?lang=en') ? 'acid_set.unknown_style' : 'acid_set.adygei';
    apiRequests.push({url:request.url(), authorization:request.headers().authorization || ''});
    if (url.includes('/recipes/filters')) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({family:['acid_set','hard'],style:['acid_set.adygei','hard.cheddar'],country:['RU','GB'],species:['bos_taurus','capra_hircus'],difficulty:['1','4']})});
    if (/\/me\/recipes\?/.test(url)) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({page:1,perPage:10,total:1,items:[{id:17,slug:'s5-fixture',name:'Тестовый сыр',catalog:'user',visibility:'private',revision:1,family:'acid_set',style:catalogStyle,country:'RU'}]})});
    if (url.includes('/me/recipes/17')) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(recipe)});
    if (/\/recipes\?/.test(url)) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({page:Number((url.match(/[?&]page=(\d+)/)||[])[1]||1),perPage:10,total:21,items:[{id:17,slug:'s5-fixture',name:'Тестовый сыр',catalog:url.includes('catalog=user')?'user':'main',visibility:'public',revision:1,family:'acid_set',style:catalogStyle,country:'RU'}]})});
    if (url.includes('/recipes/s5-fixture')) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(recipe)});
    return route.fulfill({status:404,contentType:'application/json',body:'{"message":"not found"}'});
  });
  await page.route('**/program', async route => {
    programPosts.push({data:route.request().postData(), headers:route.request().headers()});
    return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({ok:true,operationId:7,state:'queued'})});
  });
  await page.route('**/command*', route => { commands.push(route.request().url()); return route.fulfill({status:200,body:'OK'}); });

  await page.emulateMedia({colorScheme:'dark'});
  await page.goto(baseUrl + '/cheese-recipes.htm', {waitUntil:'load'});
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(await page.locator('html').getAttribute('data-theme') === null, 'automatic dark theme must remain inherited from the system');
  expect((await page.locator('#themeToggle').getAttribute('aria-pressed')) === 'true', 'automatic dark theme was not reflected by the standard toggle');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--bg-page').trim()) === '#16130f', 'system dark palette was not applied');
  await page.evaluate(() => localStorage.setItem('theme', 'light'));
  await page.reload({waitUntil:'load'});
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(await page.locator('html').getAttribute('data-theme') === 'light', 'saved light theme was not restored');
  await page.locator('#themeToggle').click();
  expect(await page.locator('html').getAttribute('data-theme') === 'dark', 'standard theme toggle did not enable dark theme');
  expect(await page.evaluate(() => localStorage.getItem('theme')) === 'dark', 'selected dark theme was not saved');
  await page.reload({waitUntil:'load'});
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(await page.locator('html').getAttribute('data-theme') === 'dark', 'saved dark theme was not restored after reload');
  await page.evaluate(() => localStorage.removeItem('theme'));
  await page.emulateMedia({colorScheme:'light'});
  await page.reload({waitUntil:'load'});
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(await page.locator('html').getAttribute('data-theme') === null, 'automatic light theme must remain inherited from the system');
  expect((await page.locator('#themeToggle').getAttribute('aria-pressed')) === 'false', 'automatic light theme was not reflected by the standard toggle');
  const initialCatalogRequest = apiRequests.find(request => request.url.includes('/recipes?catalog=main'));
  expect(initialCatalogRequest.url.includes('page=1&perPage=10'), 'main catalogue URL differs from OpenAPI: ' + initialCatalogRequest.url);
  expect(initialCatalogRequest.url.includes('lang=ru'), 'Russian is not the default language: ' + initialCatalogRequest.url);
  expect(!initialCatalogRequest.authorization, 'public catalogue received Authorization');
  await page.waitForFunction(() => document.querySelectorAll('#recipeFamily option').length === 3);
  expect((await page.locator('#recipeFamily option').allTextContents()).join('|') === 'Все семейства|Кислотный|Твёрдый', 'family filter values were not localized');
  expect((await page.locator('#recipeCountry option').allTextContents()).join('|') === 'Все страны|Россия|Великобритания', 'country filter values were not localized');
  expect((await page.locator('#recipeSpecies option').allTextContents()).join('|') === 'Любое молоко|Коровье молоко|Козье молоко', 'milk filter values were not localized');
  expect(await page.locator('#recipeList small').textContent() === 'Кислотный · Адыгейский · Россия', 'raw catalogue metadata was not localized to Russian');

  await page.locator('#recipeQuery').fill('сыр');
  await page.locator('#recipeFamily').selectOption('acid_set');
  await page.locator('#recipeStyle').selectOption('acid_set.adygei');
  await page.locator('#recipeCountry').selectOption('RU');
  await page.locator('#recipeSpecies').selectOption('bos_taurus');
  await page.locator('#recipeDifficulty').selectOption('4');
  await page.locator('#recipeSearch button').click();
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(apiRequests.at(-1).url.includes('catalog=main') && apiRequests.at(-1).url.includes('q=%D1%81%D1%8B%D1%80') && apiRequests.at(-1).url.includes('family=acid_set') && apiRequests.at(-1).url.includes('style=acid_set.adygei') && apiRequests.at(-1).url.includes('country=RU') && apiRequests.at(-1).url.includes('species=bos_taurus') && apiRequests.at(-1).url.includes('difficulty=4'), 'public search filters missing: ' + apiRequests.at(-1).url);
  await page.locator('#recipeNext').click();
  await page.waitForFunction(() => document.getElementById('recipePage').textContent.startsWith('2 /'));
  expect(apiRequests.at(-1).url.includes('page=2'), 'pagination did not request page 2');

  await page.locator('[data-catalog="user"]').click();
  await page.waitForFunction(() => document.getElementById('recipePage').textContent.startsWith('1 /'));
  expect(apiRequests.at(-1).url.includes('catalog=user'), 'user catalogue missing');
  expect(!(await page.locator('#recipeFamily').isDisabled()), 'public filters stayed disabled for user catalogue');
  await page.locator('[data-catalog="my"]').click();
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  const myRequest = apiRequests.at(-1);
  expect(myRequest.url.includes('/me/recipes?page=1&perPage=10') && !myRequest.url.includes('q='), 'my URL differs from OpenAPI: ' + myRequest.url);
  expect(myRequest.authorization === 'Bearer ' + token, 'my request has no Blynk Bearer token');
  expect(await page.locator('#recipeFamily').isDisabled() && await page.locator('#recipeDifficulty').isDisabled(), 'unsupported public filters are enabled for Mine');
  expect(!myRequest.url.includes(token), 'token leaked into URL');
  expect(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0), 'token or state was persisted');
  expect(!(await page.locator('body').textContent()).includes(token), 'token rendered into DOM');
  await page.locator('#recipeList button').click();
  await page.waitForFunction(() => document.getElementById('recipeName').textContent === 'Тестовый сыр');
  expect(apiRequests.at(-1).url.includes('/me/recipes/17') && apiRequests.at(-1).authorization === 'Bearer ' + token, 'owned recipe detail differs from OpenAPI');
  await page.locator('#convertRecipe').click();
  expect(!(await page.locator('#applyRecipe').isDisabled()), 'API content.xml recipe did not produce an applicable program');
  const jsonProgram = await page.locator('#programPreview').inputValue();

  await page.locator('#recipeFile').setInputFiles(xmlPath);
  await page.waitForFunction(() => document.getElementById('recipeName').textContent === 'Тестовый сыр');
  await page.locator('#convertRecipe').click();
  const expected = 'H;32;60;1;0^0^0^0;0\nW;0;30;1;0^0^0^0;0\nN;32;60;6.4;0^0^0^0;0\nW;0;30;2;0^0^0^0;0\nN;32;20;6.35;0^0^0^0;0\nF;32;20;2.5;0^0^0^0;0\nW;0;30;4;0^0^0^0;0\nP;32;3;63;0^0^0^0;0\nP;38;30;90;0^0^0^0;0\nW;0;30;6;0^0^0^0;0\n';
  expect(await page.locator('#programPreview').inputValue() === expected, 'local XML conversion differs: ' + await page.locator('#programPreview').inputValue());
  const warnings = await page.locator('#recipeWarnings').textContent();
  expect(warnings.includes('удерживается 30 с') && warnings.includes('исключены из программы') && warnings.includes('ручное действие'), 'required warnings missing: ' + warnings);
  expect(warnings.includes('Этапы созревания и упаковки исключены'), 'aging process step was not reported as excluded: ' + warnings);
  expect(!expected.includes(';12;') && !expected.includes('6.5'), 'aging step or cut-step pH leaked into the program');

  const xmlProgram = await page.locator('#programPreview').inputValue();
  expect(jsonProgram === xmlProgram, 'JSON and XML do not use one normalized conversion');

  // Оборудование: дозатор по шагам + лира по I2C режут и мешают, нарезка/осаживание/вымешивание по расписанию.
  expect(await page.locator('#doserStepsRow').isHidden() && await page.locator('#mixerDeviceRow').isHidden() && await page.locator('#cutMinutesRow').isHidden(), 'equipment detail fields are visible before a device is chosen');
  expect(await page.locator('#mixerDevice').inputValue() === '1', 'relay must be the default stirrer connection without an I2C mixer');
  await page.locator('#doserMode').selectOption('1');
  expect(!(await page.locator('#doserStepsRow').isHidden()), 'steps-per-feed field did not appear');
  await page.locator('#doserSteps').fill('200');
  await page.locator('#mixerKind').selectOption('2');
  await page.locator('#mixerDevice').selectOption('2');
  expect(!(await page.locator('#mixerRpmRow').isHidden()) && !(await page.locator('#cutMinutesRow').isHidden()), 'RPM or lyre cutting time field did not appear');
  await page.locator('#mixerRpm').fill('90');
  await page.locator('#cutMinutes').fill('1.5');
  await page.locator('#cutMinutes').dispatchEvent('change');
  const equipped = 'H;32;60;1;0^0^0^0;0\nD;200;10;0;2^90^0^0;3\nN;32;60;6.4;0^0^0^0;0\nD;200;10;0;2^90^0^0;3\nN;32;20;6.35;0^0^0^0;0\nF;32;20;2.5;0^0^0^0;0\nM;0;1.5;0;2^90^0^0;0\nP;32;5;65;0^0^0^0;0\nM;0;1.5;0;2^90^0^0;0\nP;32;3;63;0^0^0^0;0\nP;38;30;90;2^90^120^480;0\nW;0;30;6;0^0^0^0;0\n';
  expect(await page.locator('#programPreview').inputValue() === equipped, 'doser + lyre conversion differs: ' + await page.locator('#programPreview').inputValue());
  const equippedWarnings = await page.locator('#recipeWarnings').textContent();
  expect(equippedWarnings.includes('Загрузите дозатор по порядку: 1) Закваска, 1 DCU; 2) Фермент, 2 ml.'), 'feeder loading memo missing: ' + equippedWarnings);
  expect(!(await page.locator('#applyRecipe').isDisabled()), 'equipped conversion is not applicable');
  await page.locator('#doserSteps').fill('0');
  await page.locator('#doserSteps').dispatchEvent('change');
  expect(await page.locator('#applyRecipe').isDisabled() && (await page.locator('#recipeWarnings').textContent()).includes('Число шагов'), 'invalid steps-per-feed was accepted');
  await page.locator('#doserMode').selectOption('0');
  await page.locator('#mixerKind').selectOption('1');
  await page.locator('#mixerDevice').selectOption('1');
  await page.locator('#mixerDevice').dispatchEvent('change');
  const relay = 'H;32;60;1;0^0^0^0;0\nW;0;30;1;1^0^0^0;0\nN;32;60;6.4;0^0^0^0;0\nW;0;30;2;1^0^0^0;0\nN;32;20;6.35;0^0^0^0;0\nF;32;20;2.5;0^0^0^0;0\nW;0;30;4;0^0^0^0;0\nP;32;3;63;0^0^0^0;0\nP;38;30;90;1^0^120^480;0\nW;0;30;6;0^0^0^0;0\n';
  expect(await page.locator('#programPreview').inputValue() === relay, 'plain relay stirrer conversion differs: ' + await page.locator('#programPreview').inputValue());
  await page.locator('#mixerKind').selectOption('0');
  await page.locator('#mixerKind').dispatchEvent('change');
  expect(await page.locator('#programPreview').inputValue() === expected, 'resetting equipment did not restore the manual conversion');

  await page.locator('#applyRecipe').click();
  await page.waitForFunction(() => document.getElementById('recipeStatus').textContent.includes('Запуск не выполнялся'));
  expect(programPosts.length === 1, 'apply did not make exactly one /program POST');
  expect(programPosts[0].data.includes('WProgram') && programPosts[0].data.includes('F;32;20;2.5'), 'program payload missing converted rows');
  expect(!programPosts[0].headers.authorization, 'Blynk token sent to local /program');
  expect(commands.length === 0, 'recipe page started or commanded the device');

  await page.locator('#recipeFile').setInputFiles(maxXmlPath);
  await page.locator('#convertRecipe').click();
  expect((await page.locator('#programPreview').inputValue()).trim().split('\n').length === 30,
    '30-step CheeseXML recipe was not converted completely');
  expect(!(await page.locator('#applyRecipe').isDisabled()), '30-step CheeseXML recipe was rejected');
  await page.locator('#recipeFile').setInputFiles(overXmlPath);
  await page.locator('#convertRecipe').click();
  expect(await page.locator('#applyRecipe').isDisabled(), '31-step CheeseXML recipe was accepted');
  expect((await page.locator('#recipeWarnings').textContent()).includes('30'), '31-step CheeseXML warning reports the wrong limit');

  await page.locator('#recipeFile').setInputFiles(badXmlPath);
  await page.waitForFunction(() => document.getElementById('recipeStatus').textContent.includes('1.x'));
  expect(programPosts.length === 1, 'invalid XML triggered another /program POST');
  i2cMixer = true;
  await page.goto(baseUrl + '/cheese-recipes.htm?lang=en', {waitUntil:'load'});
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(await page.locator('html').getAttribute('lang') === 'en', 'explicit English query did not select English UI');
  expect(await page.locator('#mixerDevice').inputValue() === '2', 'bootstrap i2cMixer did not preselect the I2C connection');
  expect(await page.locator('#equipment-title').textContent() === 'Equipment' && (await page.locator('#mixerKind option').allTextContents()).join('|') === 'none|stirrer (stirring only)|lyre (stirring and cutting)', 'equipment block was not localized');
  const englishCatalogRequest = [...apiRequests].reverse().find(request => request.url.includes('/recipes?catalog=main'));
  expect(englishCatalogRequest.url.includes('lang=en'), 'explicit English language was not sent to the API');
  expect(await page.locator('.recipes-page h1').textContent() === 'Cheese recipes', 'English page heading was not localized');
  expect(await page.locator('#themeToggle').count() === 1, 'standard theme toggle is missing');
  const englishMeta = await page.locator('#recipeList small').textContent();
  expect(englishMeta === 'Acid-set · Unknown Style · Russia', 'unknown catalogue style was not converted to readable text: ' + englishMeta);
  await page.locator('#recipeList button').click();
  await page.waitForFunction(() => document.getElementById('recipeName').textContent === 'Тестовый сыр');
  await page.locator('#convertRecipe').click();
  expect((await page.locator('#recipeWarnings').textContent()).includes('Aging stages are excluded'), 'English conversion warning was not localized');
  await page.locator('#recipeFile').setInputFiles(badXmlPath);
  await page.waitForFunction(() => document.getElementById('recipeStatus').textContent.includes('Only CheeseXML 1.x is supported.'));
  expect(errors.length === 0, 'console/page errors: ' + errors.join('; '));
  return 'ok';
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the CheeseXML browser gate")
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-cheese-recipes-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        browser_xml = temp / "cheesexml.xml"
        shutil.copy2(FIXTURE_XML, browser_xml)
        bad_xml = temp / "unsupported.xml"
        bad_xml.write_text('<CHEESEXML version="2.00"/>', encoding="utf-8")
        fixture_xml = FIXTURE_XML.read_text(encoding="utf-8")
        def limit_xml(count: int) -> str:
            steps = "".join(
                f'<STEP n="{index}" phase="forming" code="press"><NAME><T xml:lang="ru">Шаг {index}</T></NAME><PARAMS><TIME value="30" unit="min"/></PARAMS></STEP>'
                for index in range(1, count + 1)
            )
            return re.sub(r"<PROCESS>[\s\S]*?</PROCESS>", f"<PROCESS>{steps}</PROCESS>", fixture_xml)
        max_xml = temp / "thirty.xml"
        max_xml.write_text(limit_xml(30), encoding="utf-8")
        over_xml = temp / "thirty-one.xml"
        over_xml.write_text(limit_xml(31), encoding="utf-8")
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site))
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-cheese-recipes-{os.getpid()}"
        opened = False
        error = None
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            opened = True
            code = (BROWSER_TEST
                .replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
                .replace("__RECIPE__", json.dumps(FIXTURE_JSON, ensure_ascii=False))
                .replace("__XML_PATH__", json.dumps(str(browser_xml)))
                .replace("__BAD_XML_PATH__", json.dumps(str(bad_xml)))
                .replace("__MAX_XML_PATH__", json.dumps(str(max_xml)))
                .replace("__OVER_XML_PATH__", json.dumps(str(over_xml)))
                .replace("__TOKEN__", json.dumps(TOKEN)))
            run_cli(cli, session, ["run-code", code], temp, 60)
        except (OSError, RuntimeError) as caught:
            error = str(caught)
        finally:
            if opened:
                run_cli(cli, session, ["close"], temp, 30, check=False)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    if error:
        print("CheeseXML browser gate failed: " + error)
        return 1
    print("CheeseXML browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
