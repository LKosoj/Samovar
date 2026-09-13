#!/usr/bin/env python3
"""S5: CheeseXML catalogue, local import, conversion preview and one apply."""

import functools
import http.server
import json
import os
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
  const baseUrl = __BASE_URL__, recipe = __RECIPE__, xmlPath = __XML_PATH__, badXmlPath = __BAD_XML_PATH__, token = __TOKEN__;
  const apiRequests = [], programPosts = [], commands = [], errors = [];
  const expect = (condition, message) => { if (!condition) throw new Error(message); };
  await page.addInitScript(() => Object.defineProperty(navigator, 'language', {configurable:true, get:() => new URL(location.href).searchParams.get('lang') === 'en' ? 'en-US' : 'ru-RU'}));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/cheese-recipes-bootstrap', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({mode:7,blynkToken:token})
  }));
  await page.route('https://www.samovar-tool.ru/cheesexml/v1/**', route => {
    const request = route.request(), url = request.url();
    const catalogStyle = page.url().includes('?lang=en') ? 'acid_set.unknown_style' : 'acid_set.adygei';
    apiRequests.push({url:request.url(), authorization:request.headers().authorization || ''});
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

  await page.goto(baseUrl + '/cheese-recipes.htm', {waitUntil:'load'});
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(apiRequests[0].url.includes('/recipes?catalog=main&page=1&perPage=10'), 'main catalogue URL differs from OpenAPI: ' + apiRequests[0].url);
  expect(!apiRequests[0].authorization, 'public catalogue received Authorization');
  expect(await page.locator('#recipeList small').textContent() === 'Кислотный · Адыгейский · Россия', 'raw catalogue metadata was not localized to Russian');

  await page.locator('#recipeQuery').fill('сыр');
  await page.locator('#recipeSearch button').click();
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(apiRequests.at(-1).url.includes('catalog=main') && apiRequests.at(-1).url.includes('q=%D1%81%D1%8B%D1%80'), 'public search query missing');
  await page.locator('#recipeNext').click();
  await page.waitForFunction(() => document.getElementById('recipePage').textContent.startsWith('2 /'));
  expect(apiRequests.at(-1).url.includes('page=2'), 'pagination did not request page 2');

  await page.locator('[data-catalog="user"]').click();
  await page.waitForFunction(() => document.getElementById('recipePage').textContent.startsWith('1 /'));
  expect(apiRequests.at(-1).url.includes('catalog=user'), 'user catalogue missing');
  await page.locator('[data-catalog="my"]').click();
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  const myRequest = apiRequests.at(-1);
  expect(myRequest.url.includes('/me/recipes?page=1&perPage=10') && !myRequest.url.includes('q='), 'my URL differs from OpenAPI: ' + myRequest.url);
  expect(myRequest.authorization === 'Bearer ' + token, 'my request has no Blynk Bearer token');
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
  const expected = 'H;32;60;1;0^0^0^0;0\nN;32;60;6.4;0^0^0^0;0\nN;32;20;6.35;0^0^0^0;0\nF;32;20;2.5;0^0^0^0;0\nW;0;30;6;0^0^0^0;0\n';
  expect(await page.locator('#programPreview').inputValue() === expected, 'local XML conversion differs: ' + await page.locator('#programPreview').inputValue());
  const warnings = await page.locator('#recipeWarnings').textContent();
  expect(warnings.includes('удерживается 30 с') && warnings.includes('исключены из программы') && warnings.includes('ручное действие'), 'required warnings missing: ' + warnings);

  const xmlProgram = await page.locator('#programPreview').inputValue();
  expect(jsonProgram === xmlProgram, 'JSON and XML do not use one normalized conversion');

  await page.locator('#applyRecipe').click();
  await page.waitForFunction(() => document.getElementById('recipeStatus').textContent.includes('Запуск не выполнялся'));
  expect(programPosts.length === 1, 'apply did not make exactly one /program POST');
  expect(programPosts[0].data.includes('WProgram') && programPosts[0].data.includes('F;32;20;2.5'), 'program payload missing converted rows');
  expect(!programPosts[0].headers.authorization, 'Blynk token sent to local /program');
  expect(commands.length === 0, 'recipe page started or commanded the device');
  await page.locator('#recipeFile').setInputFiles(badXmlPath);
  await page.waitForFunction(() => document.getElementById('recipeStatus').textContent.includes('1.x'));
  expect(programPosts.length === 1, 'invalid XML triggered another /program POST');
  await page.goto(baseUrl + '/cheese-recipes.htm?lang=en', {waitUntil:'load'});
  await page.waitForFunction(() => document.querySelectorAll('#recipeList button').length === 1);
  expect(await page.locator('html').getAttribute('lang') === 'en', 'English browser language did not select English UI');
  expect(await page.locator('.recipes-page h1').textContent() === 'Cheese recipes', 'English page heading was not localized');
  expect(await page.locator('[data-theme-choice="light"]').getAttribute('title') === 'Light theme', 'English theme title was not localized');
  const englishMeta = await page.locator('#recipeList small').textContent();
  expect(englishMeta === 'Acid-set · Russia' && !englishMeta.includes('unknown_style'), 'unknown catalogue style leaked: ' + englishMeta);
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
