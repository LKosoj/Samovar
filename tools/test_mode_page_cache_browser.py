#!/usr/bin/env python3
"""Браузерный контракт кэша страниц режимов: сверка по ETag и кнопка «Назад» после смены режима."""

import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler
from test_numeric_input_ui_browser import cleanup, render_site, run_cli


class ModePageHandler(QuietHandler):
    """Отдаёт /index.htm как плата: ETag, no-cache, 304. Смена режима меняет содержимое и ETag."""

    # Плата отвечает по HTTP/1.1: на HTTP/1.0 Chromium не сверяет страницу по ETag.
    protocol_version = "HTTP/1.1"
    variant = "rect"
    fullResponses = 0
    notModified = 0

    def do_GET(self):
        cls = ModePageHandler
        path = self.path.split("?", 1)[0]
        if path == "/__stats":
            self.send_body(200, json.dumps({"full": cls.fullResponses, "notModified": cls.notModified}).encode())
            return
        if path == "/__switch_mode":
            cls.variant = "beer"
            self.send_body(200, b"{}")
            return
        if path == "/index.htm":
            etag = f'"{cls.variant}"'
            if self.headers.get("If-None-Match") == etag:
                cls.notModified += 1
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            cls.fullResponses += 1
            page = Path(self.directory, "index.htm").read_text(encoding="utf-8")
            marker = f'<meta name="test-page" content="{cls.variant}"></head>'
            self.send_body(200, page.replace("</head>", marker, 1).encode("utf-8"), etag, "text/html; charset=utf-8")
            return
        super().do_GET()

    def send_body(self, code, body, etag=None, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if etag:
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


# page.route здесь нельзя: Playwright с перехватом запросов отключает кэш браузера.
BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  function expect(value, message) { if (!value) throw new Error(message); }
  const stats = () => page.evaluate(() => fetch("/__stats").then(response => response.json()));
  const shownPage = () => page.evaluate(() => document.querySelector('meta[name="test-page"]').content);

  await page.goto(baseUrl + "/index.htm", {waitUntil: "load"});
  expect(await shownPage() === "rect", "first open must show the current mode");
  // Браузер дописывает кэш уже после загрузки: без паузы следующий переход его не застанет.
  await page.waitForTimeout(500);
  const first = await stats();
  expect(first.full === 1 && first.notModified === 0, "first open must load the whole page");

  await page.goto(baseUrl + "/chart.htm", {waitUntil: "load"});
  await page.goto(baseUrl + "/index.htm", {waitUntil: "load"});
  await page.waitForTimeout(500);
  const second = await stats();
  expect(second.full === 1 && second.notModified === 1, "second open must use the browser copy after a 304");

  await page.goto(baseUrl + "/chart.htm", {waitUntil: "load"});
  await page.evaluate(() => fetch("/__switch_mode"));
  await page.goBack({waitUntil: "load"});
  await page.waitForFunction(() => {
    const meta = document.querySelector('meta[name="test-page"]');
    return meta && meta.content === "beer";
  }, null, {timeout: 5000}).catch(() => { throw new Error("Back kept the page of the old mode"); });

  const afterBack = await stats();
  expect(afterBack.full === 2, "changed mode must load the new page once");
  await page.waitForTimeout(700);
  const settled = await stats();
  expect(settled.full === afterBack.full && settled.notModified === afterBack.notModified,
    "page must not reload in a loop after Back");
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the mode page cache browser gate")
        return 2

    cleanup_errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="samovar-mode-page-cache-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(ModePageHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-mode-page-cache-{os.getpid()}"
        try:
            open_args = ["open"]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                config = temp / "playwright.json"
                config.write_text(
                    json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}),
                    encoding="utf-8",
                )
                open_args.append(f"--config={config}")
            run_cli(cli, session, open_args, temp, 30)
            code = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
            run_cli(cli, session, ["run-code", code], temp, 60)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)
    if cleanup_errors:
        raise RuntimeError("; ".join(cleanup_errors))
    print("Mode page cache browser contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
