#!/usr/bin/env python3
"""Браузерный контракт режимного слота общей шапки."""

import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler
from test_numeric_input_ui_browser import UI_BOOTSTRAP_FIXTURE, cleanup, render_site, run_cli


ROOT = Path(__file__).resolve().parents[1]


class DelayedBootstrapHandler(QuietHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] == "/ui-bootstrap":
            time.sleep(0.3)
            body = json.dumps({**UI_BOOTSTRAP_FIXTURE, "mode": 0}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const defaults = __BOOTSTRAP_FIXTURE__;
  let mode = 0;
  const targets = {
    0: {href: "/program.htm", label: "Расчёт"},
    2: {href: "/brewxml.htm", label: "Рецепты"},
    7: {href: "/cheese-recipes.htm", label: "Рецепты"}
  };
  const commonPages = ["chart.htm", "setup.htm", "i2cstepper.htm", "calibrate.htm", "calibrate_ph.htm"];
  function expect(value, message) { if (!value) throw new Error(message); }
  function requestPath(url) {
    const scheme = url.indexOf("://");
    const start = scheme < 0 ? 0 : url.indexOf("/", scheme + 3);
    return (start < 0 ? "/" : url.slice(start)).split("?")[0];
  }
  const requests = [];
  const responses = [];
  const problems = [];
  page.on("request", request => requests.push(requestPath(request.url())));
  page.on("response", response => responses.push(requestPath(response.url())));
  page.on("console", message => {
    if (message.type() === "error" || message.type() === "warning") problems.push(message.type() + ": " + message.text());
  });
  page.on("pageerror", error => problems.push("pageerror: " + error.message));
  await page.route("**/cheese-recipes-bootstrap", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({mode: mode, i2cMixer: false, blynkToken: ""})
  }));
  await page.route("**/data.csv", route => route.fulfill({status: 200, contentType: "text/csv", body: ""}));
  await page.route("**/i2cstepper?address=2", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({
      devices: [{address: 2, present: true}],
      selected: {address: 2, present: true, capabilities: 0, config: {relayMask: 0},
        motion: {}, status: {flags: 0, currentSpeedStepsPerSec: 0, remainingSteps: 0}}
    })
  }));
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({
      version:"test", crnt_tm:"12:00", stm:"00:00", SteamTemp:0, PipeTemp:0, WaterTemp:0,
      TankTemp:0, ACPTemp:0, VolumeAll:0, ActualVolumePerHour:0, WthdrwlProgress:0,
      bme_temp:0, heap:0, rssi:0, fr_bt:0, UseBBuzzer:false, PowerOn:0, PrgType:"",
      Status:"", heaterAlarmLatched:0, heaterAlarmReason:"", latestMessageSequence:0,
      CheesePhRaw:0, CheesePhRawValid:0, CheesePh:0, CheesePhValid:0
    })
  }));
  await page.route("https://www.samovar-tool.ru/cheesexml/v1/**", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({items: [], total: 0, filters: {}})
  }));

  async function expectSlot(pageName, currentMode) {
    const target = targets[currentMode] || null;
    const before = requests.length;
    await page.goto(baseUrl + "/" + pageName, {waitUntil: "load"});
    await page.waitForFunction(expected => {
      const slot = document.querySelector("[data-mode-navigation-slot]");
      return slot && slot.hidden === !expected;
    }, !!target);
    const actual = await page.evaluate(() => {
      const slot = document.querySelector("[data-mode-navigation-slot]");
      return {hidden: slot.hidden, href: slot.getAttribute("href"), label: slot.textContent, current: slot.getAttribute("aria-current")};
    });
    const ownRequests = requests.slice(before);
    expect(actual.hidden === !target, pageName + " visibility for mode " + currentMode);
    const bootstrapPath = pageName === "cheese-recipes.htm" ? "/cheese-recipes-bootstrap" : "/ui-bootstrap";
    expect(ownRequests.filter(path => path === bootstrapPath).length === 1,
      pageName + " bootstrap request count for mode " + currentMode);
    expect(ownRequests.filter(path => path === "/ui-bootstrap" || path === "/cheese-recipes-bootstrap").length === 1,
      pageName + " issued an additional bootstrap request for mode " + currentMode);
    if (!target) {
      expect(actual.current === null, pageName + " hidden slot keeps aria-current for mode " + currentMode);
      return;
    }
    expect(actual.href === target.href && actual.label === target.label,
      pageName + " target for mode " + currentMode + ": " + JSON.stringify(actual));
    expect(actual.current === (pageName === target.href.slice(1) ? "page" : null),
      pageName + " current-link state for mode " + currentMode);
    expect(pageName === target.href.slice(1) || ownRequests.filter(path => path === target.href).length === 0,
      pageName + " navigation slot issued a request for mode " + currentMode);
  }

  mode = 0;
  const delayedLoad = page.goto(baseUrl + "/chart.htm", {waitUntil: "domcontentloaded"});
  for (let attempts = 0; !requests.includes("/ui-bootstrap") && attempts < 100; attempts++) await page.waitForTimeout(10);
  expect(requests.includes("/ui-bootstrap") && !responses.includes("/ui-bootstrap"),
    "bootstrap response was not delayed");
  const initialChrome = await page.evaluate(() => {
    const slot = document.querySelector("[data-mode-navigation-slot]");
    const brand = document.querySelector(".brand");
    const modeLink = Array.from(document.querySelectorAll(".page-nav .nav-link"))
      .find(link => link.textContent === "Режим");
    return {
      slotHidden: slot.hidden,
      slotHref: slot.getAttribute("href"),
      brandHref: brand.getAttribute("href"),
      brandOnclick: brand.getAttribute("onclick"),
      modeHref: modeLink && modeLink.getAttribute("href"),
      modeOnclick: modeLink && modeLink.getAttribute("onclick")
    };
  });
  expect(initialChrome.slotHidden && initialChrome.slotHref === null,
    "mode navigation slot is available before bootstrap");
  expect(initialChrome.brandHref === "/" && typeof initialChrome.brandOnclick === "string" &&
    initialChrome.brandOnclick.includes("SamovarApp.confirmLeave()"),
    "brand navigation contract changed");
  expect(initialChrome.modeHref === "/" && typeof initialChrome.modeOnclick === "string" &&
    initialChrome.modeOnclick.includes("SamovarApp.confirmLeave()"),
    "mode navigation contract changed");
  await delayedLoad;
  await page.waitForFunction(() => {
    const slot = document.querySelector("[data-mode-navigation-slot]");
    return slot && !slot.hidden && slot.getAttribute("href") === "/program.htm";
  });
  await page.route("**/ui-bootstrap", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({...defaults, mode: mode})
  }));
  for (mode = 0; mode <= 7; mode++) {
    for (const pageName of commonPages) await expectSlot(pageName, mode);

    await page.goto(baseUrl + "/index.htm", {waitUntil: "load"});
    await page.waitForFunction(expected => {
      const tab = document.querySelector("[data-rectification-navigation]");
      return tab && tab.hidden === !expected;
    }, mode === 0);
    const indexState = await page.evaluate(() => ({
      calculationHidden: document.querySelector("[data-rectification-navigation]").hidden,
      otherTabsVisible: ["Ректификация", "Программа", "Дополнительно"].every(label =>
        Array.from(document.querySelectorAll(".tablinks")).some(tab => tab.value === label && !tab.hidden))
    }));
    expect(indexState.calculationHidden === (mode !== 0), "index calculation visibility for mode " + mode);
    expect(indexState.otherTabsVisible, "index changed unrelated tabs for mode " + mode);

    await expectSlot("cheese-recipes.htm", mode);
  }
  mode = 2;
  await page.goto(baseUrl + "/beer.htm", {waitUntil: "load"});
  await page.waitForFunction(() => document.getElementById("beerRecipesTab"));
  let beforeNavigation = requests.length;
  await Promise.all([
    page.waitForURL("**/brewxml.htm"),
    page.locator("#beerRecipesTab").click()
  ]);
  expect(requestPath(page.url()) === "/brewxml.htm", "beer recipes tab target");
  let navigationRequests = requests.slice(beforeNavigation);
  expect(navigationRequests.filter(path => path === "/brewxml.htm").length === 1,
    "beer recipes tab issued an additional navigation request");
  expect(navigationRequests.filter(path => path === "/ui-bootstrap").length <= 1,
    "beer recipes tab issued an additional bootstrap request");

  await page.goto(baseUrl + "/i2cstepper.htm", {waitUntil: "load"});
  await page.waitForFunction(() => {
    const slot = document.querySelector("[data-mode-navigation-slot]");
    return slot && !slot.hidden && slot.getAttribute("href") === "/brewxml.htm";
  });
  beforeNavigation = requests.length;
  await Promise.all([
    page.waitForURL("**/brewxml.htm"),
    page.locator("[data-mode-navigation-slot]").click()
  ]);
  expect(requestPath(page.url()) === "/brewxml.htm", "I2CStepper recipes slot target");
  navigationRequests = requests.slice(beforeNavigation);
  expect(navigationRequests.filter(path => path === "/brewxml.htm").length === 1,
    "I2CStepper recipes slot issued an additional navigation request");
  expect(navigationRequests.filter(path => path === "/ui-bootstrap").length <= 1,
    "I2CStepper recipes slot issued an additional bootstrap request");

  mode = 7;
  await page.goto(baseUrl + "/cheese-recipes.htm", {waitUntil: "load"});
  await page.waitForFunction(() => {
    const slot = document.querySelector("[data-mode-navigation-slot]");
    return slot && slot.getAttribute("aria-current") === "page";
  });
  expect(problems.length === 0, "browser errors: " + problems.join(" | "));
  return "ok";
}'''


def main() -> int:
    partial = (ROOT / "data_raw" / "partials" / "ui_page_header.htm").read_text(encoding="utf-8")
    if 'data-mode-navigation-slot hidden' not in partial:
        raise AssertionError("mode navigation slot must be hidden before bootstrap")

    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the mode navigation browser gate")
        return 2

    cleanup_errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="samovar-mode-navigation-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(DelayedBootstrapHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-mode-navigation-{os.getpid()}"
        try:
            open_args = ["open"]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                config = temp / "playwright.json"
                config.write_text(json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
                open_args.append(f"--config={config}")
            run_cli(cli, session, open_args, temp, 30)
            code = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
            code = code.replace("__BOOTSTRAP_FIXTURE__", json.dumps(UI_BOOTSTRAP_FIXTURE))
            run_cli(cli, session, ["run-code", code], temp, 120)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)
    if cleanup_errors:
        raise RuntimeError("; ".join(cleanup_errors))
    print("Mode navigation browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
