#!/usr/bin/env python3
"""Каталог рецептов пива на data_raw/brewxml.htm и прямое применение выбранного XML.

По образцу tools/test_cheese_recipes_browser.py (навигация/маршруты каталога)
и tools/test_brewxml_recipe_browser.py (loadBeerXML/window.program). Проверяет:
- карточку "Рецепты пива с сайта" скрытой при mode != 2 и без запросов к сайту;
- вкладку "Мои" без токена - статус noToken и без запроса;
- нормальный путь: поиск/фильтр семейства (подписи с сервера), вкладка "Мои" с
  Bearer-токеном, выбор рецепта -> тот же get_brew_info (window.program совпадает
  с локальным импортом того же файла), #recipeSource показывает источник.
"""
import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accessibility_ui_browser import QuietHandler, render_site, run_cli
from test_numeric_input_ui_browser import UI_BOOTSTRAP_FIXTURE

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_XML = (ROOT / "Тестовые рецепты пива/Sample Blonde Ale 20240421.xml").read_text(encoding="utf-8")
TOKEN = "0123456789abcdef0123456789abcdef"

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__, token = __TOKEN__, xml = __XML__, uiBootstrap = __UI_BOOTSTRAP__;
  const apiRequests = [], errors = [];
  const expect = (condition, message) => { if (!condition) throw new Error(message); };
  let bootstrapMode = 2, bootstrapToken = token, bootstrapFailure = false, filtersFailure = false, expectedRequestError = false;
  page.on('console', message => {
    if (message.type() !== 'error') return;
    if (expectedRequestError && message.text().includes('503')) return;
    errors.push(message.text());
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/ui-bootstrap', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(uiBootstrap)
  }));
  await page.route('**/cheese-recipes-bootstrap', route => route.fulfill({
    status: bootstrapFailure ? 503 : 200, contentType: 'application/json', body: JSON.stringify(
      bootstrapFailure ? {message: 'bootstrap unavailable'} : {mode: bootstrapMode, blynkToken: bootstrapToken}
    )
  }));
  await page.route('**/ajax?messageCursor=*', route => route.fulfill({status: 200, contentType: 'application/json', body: '{}'}));
  await page.route('https://www.samovar-tool.ru/beerxml/v1/**', route => {
    const request = route.request(), url = request.url();
    apiRequests.push({url, authorization: request.headers().authorization || ''});
    if (url.includes('/recipes/filters')) {
      if (filtersFailure) return route.fulfill({status:503, contentType:'application/json', body:'{"message":"filters unavailable"}'});
      const en = url.includes('lang=en');
      return route.fulfill({status:200, contentType:'application/json', body: JSON.stringify({
        families: [{code:'pale', label: en ? 'Pale Ale' : 'Светлый эль'}, {code:'ipa', label: en ? 'IPA' : 'ИПА'}]
      })});
    }
    if (/\/recipes\/sample-blonde-ale\/beerxml/.test(url)) {
      return route.fulfill({status:200, contentType:'application/xml', body: xml});
    }
    if (/\/recipes\?/.test(url)) {
      const item = {slug:'sample-blonde-ale', name:'Sample Blonde Ale', kind:'beer', family:'pale', style:{name:'Blonde Ale', type:'Ale'}, abv:5.5, catalog: url.includes('catalog=my') ? 'my' : (url.includes('catalog=user') ? 'user' : 'main')};
      return route.fulfill({status:200, contentType:'application/json', body: JSON.stringify({page:1, perPage:10, total:1, items:[item]})});
    }
    return route.fulfill({status:404, contentType:'application/json', body:'{"message":"not found"}'});
  });

  // Явный вход из режима пива ведёт на страницу рецептов и уважает confirmLeave().
  await page.goto(baseUrl + '/beer.htm', {waitUntil:'load'});
  await page.waitForFunction(() => document.body.inert === false);
  await page.evaluate(() => {
    SamovarApp.markProgramDirty();
    window.confirm = () => false;
  });
  await page.locator('#beerRecipesTab').click();
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => location.pathname) === '/beer.htm', 'Beer recipes entry ignored cancelled confirmLeave()');
  await page.evaluate(() => { window.confirm = () => true; });
  await Promise.all([
    page.waitForURL('**/brewxml.htm'),
    page.locator('#beerRecipesTab').click()
  ]);
  expect(await page.evaluate(() => location.pathname) === '/brewxml.htm', 'Beer recipes entry did not open brewxml.htm');
  await page.waitForFunction(() => document.getElementById('beerRecipesCard').hidden === false && document.querySelectorAll('#beerRecipeList button').length === 1);
  apiRequests.length = 0;

  // 1) mode != 2 - карточка остаётся скрытой, к сайту нет ни одного запроса
  bootstrapMode = 7;
  await page.goto(baseUrl + '/brewxml.htm', {waitUntil:'load'});
  await page.waitForTimeout(200);
  expect(await page.locator('#beerRecipesCard').isHidden(), 'card must stay hidden when mode != 2');
  expect(apiRequests.length === 0, 'no requests to beerxml.v1 must be made when mode != 2: ' + apiRequests.length);

  // 2) Ошибка фильтров остаётся видимой и не запускает каталог без фильтров.
  bootstrapMode = 2; bootstrapToken = token; filtersFailure = true;
  const beforeFiltersFailure = apiRequests.length;
  expectedRequestError = true;
  await page.goto(baseUrl + '/brewxml.htm', {waitUntil:'load'});
  await page.waitForFunction(() => document.getElementById('beerRecipeStatus').textContent.includes('filters unavailable'));
  expectedRequestError = false;
  const filtersFailureRequests = apiRequests.slice(beforeFiltersFailure);
  expect(filtersFailureRequests.filter(entry => entry.url.includes('/recipes/filters')).length === 1, 'filters failure did not request filters exactly once');
  expect(!filtersFailureRequests.some(entry => /\/recipes\?/.test(entry.url)), 'catalog loaded after filters failure');

  // 3) Сбой начальных данных показывается штатной плашкой и не открывает каталог/навигацию.
  filtersFailure = false; bootstrapFailure = true;
  const beforeBootstrapFailure = apiRequests.length;
  expectedRequestError = true;
  await page.goto(baseUrl + '/brewxml.htm', {waitUntil:'load'});
  await page.waitForFunction(() => {
    const error = document.getElementById('request_error');
    const slot = document.querySelector('[data-mode-navigation-slot]');
    return error && error.textContent.includes('bootstrap unavailable') && slot.hidden;
  });
  expectedRequestError = false;
  expect(await page.locator('#beerRecipesCard').isHidden(), 'card opened after bootstrap failure');
  expect(apiRequests.length === beforeBootstrapFailure, 'API was called after bootstrap failure');
  bootstrapFailure = false;

  // 4) mode == 2, но токен не задан - вкладка "Мои" показывает noToken и не делает запрос
  bootstrapMode = 2; bootstrapToken = '';
  await page.goto(baseUrl + '/brewxml.htm?lang=ru', {waitUntil:'load'});
  await page.waitForFunction(() => document.getElementById('beerRecipesCard').hidden === false && document.querySelectorAll('#beerRecipeList button').length === 1);
  const beforeMineRequests = apiRequests.length;
  await page.locator('[data-beer-catalog="my"]').click();
  await page.waitForFunction(() => document.getElementById('beerRecipeStatus').textContent.includes('токен'));
  expect(apiRequests.length === beforeMineRequests, 'Mine tab without a token must not call the API');

  // 5) обычный путь: main -> поиск/фильтр -> "Мои" (Bearer) -> выбор рецепта -> brewxml.htm
  bootstrapMode = 2; bootstrapToken = token;
  await page.goto(baseUrl + '/brewxml.htm?lang=ru', {waitUntil:'load'});
  await page.waitForFunction(() => document.getElementById('beerRecipesCard').hidden === false && document.querySelectorAll('#beerRecipeList button').length === 1);
  await page.waitForFunction(() => document.querySelectorAll('#beerRecipeFamily option').length === 3);
  expect((await page.locator('#beerRecipeFamily option').allTextContents()).join('|') === 'Все семейства|Светлый эль|ИПА', 'family filter labels were not taken from the server');

  await page.locator('#beerRecipeQuery').fill('блонд');
  await page.locator('#beerRecipeFamily').selectOption('pale');
  await page.locator('#beerRecipeFind').click();
  await page.waitForFunction(() => document.querySelectorAll('#beerRecipeList button').length === 1);
  const searchRequest = apiRequests.at(-1);
  expect(searchRequest.url.includes('catalog=main') && searchRequest.url.includes('family=pale') && searchRequest.url.includes('lang=ru'), 'search/filter params missing: ' + searchRequest.url);
  expect(!searchRequest.authorization, 'public catalogue must not send Authorization: ' + searchRequest.authorization);

  // Enter в поле поиска обязан искать так же, как кнопка "Найти" (см. T3-firmware.md) -
  // без keydown-слушателя на странице (запрещён tools/smoke_accessibility_ui.py), через
  // нативное событие search у input[type=search].
  // Список рецептов и до, и после поиска состоит из одного и того же элемента (мок всегда
  // отдаёт 1 запись) - ждать через #beerRecipeList тут бессмысленно, условие уже истинно.
  // Ждём сам факт нового запроса к API.
  const beforeEnterRequests = apiRequests.length;
  await page.locator('#beerRecipeQuery').fill('айпа');
  await page.locator('#beerRecipeQuery').press('Enter');
  for (let i = 0; i < 50 && apiRequests.length === beforeEnterRequests; i++) await page.waitForTimeout(20);
  expect(apiRequests.length > beforeEnterRequests, 'Enter in the search field must trigger a new request');
  const enterRequest = apiRequests.at(-1);
  expect(enterRequest.url.includes('catalog=main') && enterRequest.url.includes('family=pale'), 'Enter search did not keep the active filters: ' + enterRequest.url);

  await page.locator('[data-beer-catalog="my"]').click();
  await page.waitForFunction(() => document.querySelectorAll('#beerRecipeList button').length === 1);
  const myRequest = apiRequests.at(-1);
  expect(myRequest.url.includes('catalog=my'), 'Mine tab must request catalog=my: ' + myRequest.url);
  expect(myRequest.authorization === 'Bearer ' + token, 'Mine tab must send the Blynk Bearer token');

  await page.locator('#beerRecipeList button').click();
  const beerxmlRequest = apiRequests.find(entry => /\/recipes\/sample-blonde-ale\/beerxml/.test(entry.url));
  expect(!!beerxmlRequest, 'no request for recipes/{slug}/beerxml was made');
  expect(beerxmlRequest.authorization === 'Bearer ' + token, 'beerxml download must send Bearer token from the Mine tab');
  await page.waitForFunction(() => document.getElementById('NAME').textContent === 'Sample Blonde Ale');
  expect(await page.locator('#recipeSource').textContent() === 'Источник: Sample Blonde Ale', 'recipe source label was not shown');
  expect(await page.evaluate(() => location.pathname) === '/brewxml.htm', 'catalogue selection must stay on brewxml.htm');

  const catalogueProgram = await page.evaluate(() => window.program);
  const localProgram = await page.evaluate(async (xmlText) => {
    window.alert = function () {};
    return await new Promise(resolve => {
      loadBeerXML(new File([xmlText], 'x.xml'));
      setTimeout(() => resolve(window.program), 60);
    });
  }, xml);
  expect(catalogueProgram === localProgram, 'catalogue import must reuse the same converter as a local BeerXML file');

  const englishRequestStart = apiRequests.length;
  await page.goto(baseUrl + '/brewxml.htm?lang=en', {waitUntil:'load'});
  await page.waitForFunction(() => document.getElementById('beerRecipesCard').hidden === false && document.querySelectorAll('#beerRecipeList button').length === 1);
  expect(await page.locator('#beerRecipesTitle').textContent() === 'Beer recipes from the site', 'English catalogue title was not applied');
  expect(await page.locator('[data-beer-catalog="main"]').textContent() === 'Main', 'English catalogue tab was not applied');
  expect(await page.locator('#beerRecipeFind').textContent() === 'Search', 'English catalogue search label was not applied');
  const englishCatalogRequest = apiRequests.slice(englishRequestStart).find(entry => /\/recipes\?/.test(entry.url));
  expect(!!englishCatalogRequest && englishCatalogRequest.url.includes('lang=en'), 'English catalogue request is missing lang=en');

  expect(errors.length === 0, 'console/page errors: ' + errors.join('; '));
  return 'ok';
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the beer recipes catalogue browser gate")
        return 1
    with tempfile.TemporaryDirectory(prefix="samovar-beer-recipes-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site))
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-beer-recipes-{os.getpid()}"
        opened = False
        error = None
        try:
            config = temp / "playwright.json"
            config.write_text(json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            opened = True
            code = (BROWSER_TEST
                .replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
                .replace("__TOKEN__", json.dumps(TOKEN))
                .replace("__XML__", json.dumps(FIXTURE_XML, ensure_ascii=False))
                .replace("__UI_BOOTSTRAP__", json.dumps(UI_BOOTSTRAP_FIXTURE)))
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
        print("Beer recipes catalogue browser gate failed: " + error)
        return 1
    print("Beer recipes catalogue browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
