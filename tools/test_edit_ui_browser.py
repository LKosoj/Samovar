#!/usr/bin/env python3
"""Браузерный гейт edit.htm: панель не перекрывает дерево, список/сохранение
ходят в /edit, Ace 1.44.0 указан в разметке.
"""
import base64
import functools
import gzip
import hashlib
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
  const aceIntegrity = __ACE_INTEGRITY__;
  const gzipFixturePath = __GZIP_FIXTURE_PATH__;
  const errors = [];
  const passed = [];
  const editLog = [];
  let uploadedGzip = null;
  const uploadedBodies = [];
  let scenario = "setup";

  await page.route(/\/edit\.htm$/, async route => {
    const response = await route.fetch();
    const body = (await response.text()).replace(
      /integrity="sha384-[^"]+"/g,
      'integrity="' + aceIntegrity + '"'
    );
    await route.fulfill({ response: response, body: body });
  });

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
    const requestUrl = req.url();
    const queryAt = requestUrl.indexOf("?");
    const search = queryAt === -1 ? "" : requestUrl.slice(queryAt);
    const editMatch = /(?:\?|&)edit=([^&]*)/.exec(search);
    editLog.push({
      method: req.method(),
      search: search,
      hasList: /(?:\?|&)list=/.test(search),
      edit: editMatch ? decodeURIComponent(editMatch[1]) : null,
    });
    if (req.method() === "GET" && /(?:\?|&)list=/.test(search)) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { type: "file", name: "/index.htm", size: 1200 },
          { type: "file", name: "/index.htm.gz", size: 96 },
          { type: "file", name: "/app.js", size: 4096 },
          { type: "file", name: "/logo.png", size: 800 }
        ])
      });
    }
    if (req.method() === "GET" && editMatch) {
      if (decodeURIComponent(editMatch[1]) === "/index.htm.gz") {
        return route.fulfill({
          status: 200,
          contentType: "application/octet-stream",
          path: gzipFixturePath
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: "contents-of-" + decodeURIComponent(editMatch[1])
      });
    }
    if (req.method() === "GET" && /(?:\?|&)download=/.test(search)) {
      return route.fulfill({ status: 200, body: "download" });
    }
    if (req.method() === "POST") {
      const body = req.postDataBuffer();
      function findBytes(bytes, needle, from) {
        for (let i = from || 0; i <= bytes.length - needle.length; i++) {
          if (needle.every((value, offset) => bytes[i + offset] === value)) return i;
        }
        return -1;
      }
      const start = findBytes(body, [13, 10, 13, 10], 0) + 4;
      const end = findBytes(body, [13, 10, 45, 45], start);
      uploadedGzip = body.subarray(start, end);
      uploadedBodies.push(uploadedGzip);
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
    const aceScripts = page.locator("script[src*='ace/1.44.0']");
    if (await aceScripts.count() !== 2) throw new Error(name + " Ace 1.44.0 script tags missing");
    for (let i = 0; i < 2; i++) {
      const script = aceScripts.nth(i);
      if (!(await script.getAttribute("integrity") || "").startsWith("sha384-")) {
        throw new Error(name + " Ace script has no SHA-384 integrity check");
      }
      if (await script.getAttribute("crossorigin") !== "anonymous") {
        throw new Error(name + " Ace script has no anonymous CORS mode");
      }
    }
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
  const lightColors = await page.evaluate(() => ({
    page: getComputedStyle(document.body).backgroundColor,
    button: getComputedStyle(document.getElementById("btn-save")).backgroundColor
  }));
  if (lightColors.page !== "rgb(243, 239, 233)" || lightColors.button !== "rgb(163, 86, 26)") {
    throw new Error("editor light palette does not match the main UI: " + JSON.stringify(lightColors));
  }
  await page.locator("#themeToggle").click();
  const darkPage = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  if (darkPage !== "rgb(22, 19, 15)") {
    throw new Error("editor dark palette does not match the main UI: " + darkPage);
  }
  await page.locator("#themeToggle").click();
  passed.push("shared palette");
  const listed = await page.locator("#tree li").count();
  if (listed !== 4) throw new Error("file list count=" + listed);

  await page.locator("#tree li").filter({ hasText: "index.htm.gz" }).click();
  await page.waitForFunction(() => window.samovarAce &&
    window.samovarAce.getValue() === "<h1>gzip source</h1>\n");
  await page.evaluate(() => window.samovarAce.setValue("<h1>gzip changed</h1>\n"));
  await page.locator("#btn-save").click();
  for (let i = 0; i < 40 && !uploadedGzip; i++) await page.waitForTimeout(50);
  if (!uploadedGzip || uploadedGzip[0] !== 0x1f || uploadedGzip[1] !== 0x8b) {
    throw new Error("saved .gz payload is not gzip");
  }
  const savedText = await page.evaluate(async bytes => {
    const stream = new Blob([new Uint8Array(bytes)]).stream()
      .pipeThrough(new DecompressionStream("gzip"));
    return await new Response(stream).text();
  }, Array.from(uploadedGzip));
  if (savedText !== "<h1>gzip changed</h1>\n") {
    throw new Error("saved gzip text mismatch: " + savedText);
  }
  passed.push("gzip round trip");

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
  const plainBody = uploadedBodies[uploadedBodies.length - 1];
  if (plainBody[0] === 0x1f && plainBody[1] === 0x8b) {
    throw new Error("plain app.js was unexpectedly saved as gzip");
  }
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
    gzip_fixture = work / "index.htm.gz"
    gzip_fixture.write_bytes(gzip.compress(b"<h1>gzip source</h1>\n", mtime=0))
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
      .replace("__GZIP_FIXTURE_PATH__", json.dumps(str(gzip_fixture)))
      .replace(
        "__ACE_INTEGRITY__",
        json.dumps(
          "sha384-" + base64.b64encode(
            hashlib.sha384(ACE_MOCK.encode("utf-8")).digest()
          ).decode("ascii")
        ),
      )
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
