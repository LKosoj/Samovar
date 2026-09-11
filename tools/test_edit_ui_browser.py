#!/usr/bin/env python3
"""Браузерный гейт edit.htm: панель не перекрывает дерево, список/сохранение
ходят в /edit, Ace 1.44.0 указан в разметке.
"""
import base64
import contextlib
import functools
import gzip
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import tempfile
from pathlib import Path

from test_i2c_pump_ui_browser import QuietHandler, cleanup_resources, run_cli

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"

ACE_MOCK = (
    "window.ace={require:function(){},edit:function(){var c={},v='',ls=[];"
    "var ed={setOptions:function(){},getSession:function(){return{"
    "setMode:function(){},setUseSoftTabs:function(){},setTabSize:function(){},"
    "getUndoManager:function(){return{undo:function(){},redo:function(){}};}}},"
    "setTheme:function(){},setValue:function(x){v=x;ls.forEach(function(f){f();});},getValue:function(){return v;},"
    "clearSelection:function(){},setHighlightActiveLine:function(){},"
    "setShowPrintMargin:function(){},on:function(n,f){if(n==='change')ls.push(f);},"
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
  const uploadResponse = "UPLOADED, LUA RELOAD NOT QUEUED: /index.htm.gz";
  let postOutcome = { status: 200, body: uploadResponse };
  let deferredGetA = null;
  let deferredGetB = null;
  let ignoreExpectedHttp500 = false;
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
    if (message.type() === "error" &&
        !(ignoreExpectedHttp500 && message.text().includes("500"))) {
      errors.push(scenario + " console: " + message.text());
    }
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
      const editPath = decodeURIComponent(editMatch[1]);
      if (editPath === "/late-a.lua" || editPath === "/late-b.lua") {
        return new Promise(resolve => {
          const finish = async () => {
            await route.fulfill({ status: 200, contentType: "text/plain", body: "contents-of-" + editPath });
            resolve();
          };
          if (editPath === "/late-a.lua") deferredGetA = finish;
          else deferredGetB = finish;
        });
      }
      if (editPath === "/server-error.lua") {
        return route.fulfill({ status: 500, contentType: "text/plain", body: "read failed" });
      }
      if (editPath === "/index.htm.gz") {
        return route.fulfill({
          status: 200,
          contentType: "application/octet-stream",
          path: gzipFixturePath
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: "contents-of-" + editPath
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
    return route.fulfill({
      status: req.method() === "POST" ? postOutcome.status : 200,
      contentType: "text/plain",
      body: req.method() === "POST" ? postOutcome.body : req.method() + " ok"
    });
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
  await page.waitForFunction(() => document.getElementById("status").textContent ===
    "Сохранено; Lua не применён: /index.htm.gz");
  if (await page.locator("#status").getAttribute("class")) {
    throw new Error("saved file with rejected Lua reload was shown as fully applied");
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
  await page.waitForFunction(() => document.getElementById("btn-save").dataset.dirty === "0" &&
    document.getElementById("status").textContent.indexOf("Сохранено") === 0);
  passed.push("save");

  await page.evaluate(() => window.samovarAce.setValue("dirty A"));
  if (await page.locator("#btn-save").getAttribute("data-dirty") !== "1") {
    throw new Error("fixture did not mark dirty A");
  }
  const filenameBeforeCancel = await page.locator("#editor-filename").inputValue();
  await page.evaluate(() => { window.confirm = confirm = () => false; });
  await page.locator("#tree li").filter({ hasText: "index.htm" }).first().click();
  await page.waitForTimeout(100);
  if (await page.locator("#editor-filename").inputValue() !== filenameBeforeCancel ||
      await page.evaluate(() => window.samovarAce.getValue()) !== "dirty A") {
    throw new Error("tree Cancel must preserve dirty A buffer and filename: " + JSON.stringify({
      before: filenameBeforeCancel, after: await page.locator("#editor-filename").inputValue(),
      text: await page.evaluate(() => window.samovarAce.getValue())
    }));
  }
  await page.evaluate(() => { window.confirm = confirm = () => true; });
  await page.locator("#tree li").filter({ hasText: "index.htm" }).first().click();
  await page.waitForFunction(() => document.getElementById("editor-filename").value === "/index.htm");
  if (await page.evaluate(() => window.samovarAce.getValue()) !== "contents-of-/index.htm") {
    throw new Error("tree OK did not load B");
  }
  await page.evaluate(() => window.samovarAce.setValue("dirty B"));
  await page.evaluate(() => { window.confirm = confirm = () => false; });
  await page.locator("#tree li").filter({ hasText: "app.js" }).click({ button: "right" });
  await page.locator(".cm li").first().click();
  await page.waitForTimeout(100);
  if (await page.evaluate(() => window.samovarAce.getValue()) !== "dirty B") {
    throw new Error("context-menu Cancel must preserve dirty buffer");
  }
  await page.evaluate(() => { window.confirm = confirm = () => true; });
  await page.locator("#tree li").filter({ hasText: "app.js" }).click({ button: "right" });
  await page.locator(".cm li").first().click();
  await page.waitForFunction(() => document.getElementById("editor-filename").value === "/app.js");
  passed.push("dirty tree/context Cancel and OK");

  await page.evaluate(() => window.samovarAce.setValue("dirty create"));
  await page.locator("#upload-path").fill("/cancel.lua");
  const putsBeforeCancel = editLog.filter(item => item.method === "PUT").length;
  await page.evaluate(() => { window.confirm = confirm = () => false; });
  await page.locator("#btn-create").click();
  await page.waitForTimeout(100);
  if (editLog.filter(item => item.method === "PUT").length !== putsBeforeCancel ||
      await page.evaluate(() => window.samovarAce.getValue()) !== "dirty create") {
    throw new Error("create Cancel must not PUT or clear dirty buffer");
  }
  passed.push("dirty create Cancel");

  await page.evaluate(() => { window.confirm = confirm = () => true; });


  await page.locator("#upload-path").fill("/foo.lua");
  const beforePut = editLog.filter(item => item.method === "PUT").length;
  await page.locator("#btn-create").click();
  for (let i = 0; i < 40 && editLog.filter(item => item.method === "PUT").length <= beforePut; i++) {
    await page.waitForTimeout(50);
  }
  const afterPut = editLog.filter(item => item.method === "PUT").length;
  if (afterPut <= beforePut) throw new Error("Create did not PUT /edit");
  await page.waitForFunction(() => document.getElementById("editor-filename").value === "/foo.lua");
  passed.push("create");

  await checkLayout("mobile", 390, 844);

  await page.evaluate(() => window.samovarAce.loadUrl("/stable.lua", true));
  try {
    await page.waitForFunction(() => document.getElementById("editor-filename").value === "/stable.lua");
  } catch (error) {
    throw new Error("stable GET did not complete: " + JSON.stringify(await page.evaluate(() => ({
      filename: document.getElementById("editor-filename").value,
      text: window.samovarAce.getValue()
    }))));
  }
  await page.evaluate(() => {
    window.samovarAce.loadUrl("/late-a.lua", true);
    window.samovarAce.loadUrl("/late-b.lua", true);
  });
  for (let i = 0; i < 40 && !deferredGetA; i++) await page.waitForTimeout(25);
  if (!deferredGetA) throw new Error("fixture did not defer GET A");
  await deferredGetA();
  for (let i = 0; i < 40 && !deferredGetB; i++) await page.waitForTimeout(25);
  if (!deferredGetB) throw new Error("fixture did not queue GET B after A");
  if (await page.locator("#editor-filename").inputValue() !== "/stable.lua" ||
      await page.evaluate(() => window.samovarAce.getValue()) !== "contents-of-/stable.lua") {
    throw new Error("late GET A must not overwrite current buffer and filename");
  }
  await deferredGetB();
  await page.waitForFunction(() => document.getElementById("editor-filename").value === "/late-b.lua");
  const beforeGetError = {
    filename: await page.locator("#editor-filename").inputValue(),
    text: await page.evaluate(() => window.samovarAce.getValue())
  };
  ignoreExpectedHttp500 = true;
  await page.evaluate(() => window.samovarAce.loadUrl("/server-error.lua", true));
  await page.waitForTimeout(100);
  if (await page.locator("#editor-filename").inputValue() !== beforeGetError.filename ||
      await page.evaluate(() => window.samovarAce.getValue()) !== beforeGetError.text) {
    throw new Error("GET 500 must preserve current buffer and filename");
  }
  if (await page.locator("#status").textContent() !== "Ошибка 500: read failed") {
    throw new Error("GET 500 must show the read error");
  }
  passed.push("deferred GET and GET 500 preserve editor state");

  async function saveWithOutcome(value, status, body) {
    const before = editLog.filter(item => item.method === "POST").length;
    postOutcome = { status: status, body: body };
    await page.evaluate(text => window.samovarAce.setValue(text), value);
    await page.locator("#btn-save").click();
    for (let i = 0; i < 40 && editLog.filter(item => item.method === "POST").length === before; i++) {
      await page.waitForTimeout(25);
    }
    if (editLog.filter(item => item.method === "POST").length !== before + 1) {
      throw new Error("save fixture did not receive exactly one POST");
    }
  }
  await saveWithOutcome("full response", 200, "UPLOADED: /late-b.lua");
  await page.waitForFunction(() => document.getElementById("status").textContent === "Сохранено: /late-b.lua");
  if (await page.locator("#status").getAttribute("class") !== "ok" ||
      await page.locator("#btn-save").getAttribute("data-dirty") !== "0") {
    throw new Error("full 200 POST must confirm save and clear dirty state");
  }
  await saveWithOutcome("reload rejected", 200, "UPLOADED, LUA RELOAD NOT QUEUED: /late-b.lua");
  await page.waitForFunction(() => document.getElementById("status").textContent ===
    "Сохранено; Lua не применён: /late-b.lua");
  if (await page.locator("#status").getAttribute("class") ||
      await page.locator("#btn-save").getAttribute("data-dirty") !== "0") {
    throw new Error("reload-rejected 200 POST must keep neutral status and clear dirty state");
  }
  await saveWithOutcome("write failure", 500, "write failed");
  await page.waitForFunction(() => document.getElementById("status").textContent === "Ошибка 500: write failed");
  if (await page.locator("#status").getAttribute("class") !== "err" ||
      await page.locator("#btn-save").getAttribute("data-dirty") !== "1") {
    throw new Error("500 POST must preserve dirty state and show the write error");
  }
  passed.push("POST 200 full, 200 reload rejection, and 500 write error");

  await page.evaluate(() => window.samovarAce.loadUrl("/cleanup.lua", true));
  await page.waitForFunction(() => document.getElementById("editor-filename").value === "/cleanup.lua");

  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { passed: passed };
}'''


def run_browser(cli, session, browser_test, work, timeout):
  captured = io.StringIO()
  try:
    with contextlib.redirect_stdout(captured):
      run_cli(cli, session, ["run-code", browser_test], str(work), timeout)
  except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
    output = captured.getvalue()
    print(output, end="")
    return 1, output or str(error)
  print(captured.getvalue(), end="")
  return 0, ""


def error_sections(output):
  lines = output.splitlines()
  sections = []
  index = 0
  while index < len(lines):
    if lines[index] != "### Error":
      index += 1
      continue
    index += 1
    section = []
    while index < len(lines) and not lines[index].startswith("### "):
      section.append(lines[index])
      index += 1
    sections.append("\n".join(section))
  return "\n".join(sections)


def main():
  cli = shutil.which("playwright-cli")
  if not cli:
    print("playwright-cli is required for the edit.htm browser gate", file=sys.stderr)
    return 2

  primary_error = None
  cleanup_errors = []

  with tempfile.TemporaryDirectory(prefix="samovar-edit-pw-") as temp_dir:
    work = Path(temp_dir)
    site = work / "site"
    site.mkdir()
    shutil.copy2(DATA / "edit.htm", site / "edit.htm")
    shutil.copy2(DATA / "app.js", site / "app.js")
    handler = functools.partial(QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = f"ed{os.getpid()}"
    try:
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
      code, output = run_browser(cli, session, browser_test, work, 120)
      if code:
        raise RuntimeError(output)
      source = (site / "edit.htm").read_text(encoding="utf-8")
      mutations = (
        ("dirty navigation confirmation", "if (!confirmed && !editor.confirmDiscard()) return;",
         "if (false) return;", "tree Cancel must preserve dirty A buffer and filename"),
        ("late GET generation", "if (generation !== loadGeneration) return;",
         "if (false) return;", "late GET A must not overwrite current buffer and filename"),
        ("GET 500 preservation", "if (status != 200) {\n        setStatus(describeHttpError(status, responseText), \"err\");\n        return;\n      }\n      ge(\"preview\")",
         "if (false) {\n        setStatus(describeHttpError(status, responseText), \"err\");\n        return;\n      }\n      ge(\"preview\")",
         "GET 500 must preserve current buffer and filename"),
      )
      for label, old, new, expected in mutations:
        mutated = source.replace(old, new, 1)
        if mutated == source:
          raise RuntimeError(f"{label}: mutation anchor not found")
        (site / "edit.htm").write_text(mutated, encoding="utf-8")
        mutant_session = f"{session}-mutant"
        run_cli(cli, mutant_session, open_args, str(work), 30)
        code, output = run_browser(cli, mutant_session, browser_test, work, 120)
        run_cli(cli, mutant_session, ["close"], str(work), 30, check=False)
        if code == 0 or expected not in error_sections(output):
          raise RuntimeError(f"{label}: mutation did not produce expected assert: {expected}\n{output}")
      (site / "edit.htm").write_text(source, encoding="utf-8")
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
