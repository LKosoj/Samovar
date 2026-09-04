#!/usr/bin/env python3
"""Браузерный гейт edit.htm: панель не перекрывает дерево, список/сохранение
ходят в /edit, Ace 1.44.0 указан в разметке.
"""
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from test_i2c_pump_ui_browser import QuietHandler, cleanup_resources, run_cli

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"

ACE_MOCK = (
    "window.ace={require:function(){},edit:function(){var c={},v='';"
    "var ed={setOptions:function(){},getSession:function(){return{"
    "setMode:function(){},setUseSoftTabs:function(){},setTabSize:function(){},"
    "getUndoManager:function(){return{undo:function(){},redo:function(){}};}}},"
    "setTheme:function(){},setValue:function(x){v=x;},getValue:function(){return v;},"
    "clearSelection:function(){},setHighlightActiveLine:function(){},"
    "setShowPrintMargin:function(){},on:function(){},"
    "commands:{addCommand:function(cmd){c[cmd.name]=cmd;}},"
    "execCommand:function(n){if(c[n])c[n].exec(ed);}};"
    "return ed;}};"
)

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const aceMock = __ACE_MOCK__;
  const errors = [];
  const passed = [];
  const editLog = [];
  let scenario = "setup";

  page.on("console", message => {
    if (message.type() === "error") errors.push(scenario + " console: " + message.text());
  });
  page.on("pageerror", error => errors.push(scenario + " pageerror: " + error.message));

  await page.route(/ace(\.min)?\.js|ext-language_tools|cdnjs\.cloudflare\.com\/ajax\/libs\/ace/, route => {
    return route.fulfill({
      status: 200,
      contentType: "application/javascript; charset=utf-8",
      body: aceMock
    });
  });

  await page.route(/\/edit(\?|$)/, async route => {
    const req = route.request();
    const url = new URL(req.url());
    editLog.push({
      method: req.method(),
      search: url.search,
      hasList: url.searchParams.has("list"),
      edit: url.searchParams.get("edit"),
    });
    if (req.method() === "GET" && url.searchParams.has("list")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { type: "file", name: "/index.htm", size: 1200 },
          { type: "file", name: "/app.js", size: 4096 },
          { type: "file", name: "/logo.png", size: 800 }
        ])
      });
    }
    if (req.method() === "GET" && url.searchParams.has("edit")) {
      return route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: "contents-of-" + url.searchParams.get("edit")
      });
    }
    if (req.method() === "GET" && url.searchParams.has("download")) {
      return route.fulfill({ status: 200, body: "download" });
    }
    return route.fulfill({ status: 200, contentType: "text/plain", body: req.method() + " ok" });
  });

  function overlap(a, b) {
    if (!a || !b) return false;
    return a.x < b.x + b.width && a.x + a.width > b.x &&
      a.y < b.y + b.height && a.y + a.height > b.y;
  }

  async function checkLayout(name, width, height) {
    scenario = name;
    await page.setViewportSize({ width: width, height: height });
    await page.goto(baseUrl + "/edit.htm", { waitUntil: "load" });
    await page.locator("#tree li").first().waitFor({ timeout: 5000 });
    const aceSrc = await page.locator("script[src*='ace/1.44.0']").count();
    if (aceSrc < 1) throw new Error(name + " Ace 1.44.0 script tag missing");
    const labels = await page.locator("#uploader").innerText();
    for (const word of ["Обновить", "Загрузить", "Создать", "Сохранить"]) {
      if (labels.indexOf(word) === -1) throw new Error(name + " missing button: " + word);
    }
    const treeBox = await page.locator("#tree").boundingBox();
    for (const id of ["btn-refresh", "btn-upload", "btn-create", "btn-save", "upload-path", "themeToggle"]) {
      const box = await page.locator("#" + id).boundingBox();
      if (!box || box.width <= 0 || box.height <= 0) {
        throw new Error(name + " " + id + " is not visible");
      }
      if (overlap(box, treeBox)) throw new Error(name + " " + id + " overlaps the file tree");
    }
    passed.push(name + " layout");
  }

  await checkLayout("desktop", 1440, 900);
  const listed = await page.locator("#tree li").count();
  if (listed !== 3) throw new Error("file list count=" + listed);

  await page.locator("#tree li").filter({ hasText: "app.js" }).click();
  await page.waitForFunction(() => {
    const el = document.getElementById("editor-filename");
    return el && el.value.indexOf("app.js") !== -1;
  });
  if (!editLog.some(item => item.edit && String(item.edit).indexOf("app.js") !== -1)) {
    throw new Error("clicking app.js did not request /edit?edit=");
  }
  passed.push("open file");

  const beforeSave = editLog.filter(item => item.method === "POST").length;
  await page.locator("#btn-save").click();
  for (let i = 0; i < 40 && editLog.filter(item => item.method === "POST").length <= beforeSave; i++) {
    await page.waitForTimeout(50);
  }
  const afterSave = editLog.filter(item => item.method === "POST").length;
  if (afterSave <= beforeSave) throw new Error("Save did not POST /edit");
  passed.push("save");

  await page.locator("#upload-path").fill("/foo.lua");
  const beforePut = editLog.filter(item => item.method === "PUT").length;
  await page.locator("#btn-create").click();
  for (let i = 0; i < 40 && editLog.filter(item => item.method === "PUT").length <= beforePut; i++) {
    await page.waitForTimeout(50);
  }
  const afterPut = editLog.filter(item => item.method === "PUT").length;
  if (afterPut <= beforePut) throw new Error("Create did not PUT /edit");
  passed.push("create");

  await checkLayout("mobile", 390, 844);

  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { passed: passed };
}'''


def main():
  cli = shutil.which("playwright-cli")
  if not cli:
    print("playwright-cli is required for the edit.htm browser gate", file=sys.stderr)
    return 2

  handler = functools.partial(QuietHandler, directory=str(DATA))
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  session = f"ed{os.getpid()}"
  primary_error = None
  cleanup_errors = []

  try:
    work = Path("/tmp/samovar-edit-pw")
    work.mkdir(parents=True, exist_ok=True)
    open_args = ["open"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
      config = work / "playwright.json"
      config.write_text(json.dumps({
        "browser": {
          "browserName": "chromium",
          "launchOptions": {"chromiumSandbox": False},
        }
      }), encoding="utf-8")
      open_args.append(f"--config={config}")

    run_cli(cli, session, open_args, str(work), 30)
    base_url = f"http://127.0.0.1:{server.server_port}"
    browser_test = (
      BROWSER_TEST
      .replace("__BASE_URL__", json.dumps(base_url))
      .replace("__ACE_MOCK__", json.dumps(ACE_MOCK))
    )
    run_cli(cli, session, ["run-code", browser_test], str(work), 120)
  except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
    primary_error = str(error)
  finally:
    cleanup_errors = cleanup_resources(cli, session, server, thread)

  if primary_error or cleanup_errors:
    if primary_error:
      print(f"edit.htm browser gate failed: {primary_error}", file=sys.stderr)
    for error in cleanup_errors:
      print(f"edit.htm browser cleanup failed: {error}", file=sys.stderr)
    return 1

  print("edit.htm browser gate passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
