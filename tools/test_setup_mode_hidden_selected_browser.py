#!/usr/bin/env python3
"""[WP17 п.45, З2] Настоящая браузерная проверка "hidden selected" на /setup.htm.

Контекст: WebServer.ino::setupKeyProcessor() для СОХРАНЁННОГО, но ставшего
недоступным в этой сборке режима (см. mode_registry.h::mode_available_in_build)
отдаёт на <option> сразу ДВЕ пометки - "hidden" (не показывать в списке выбора)
и "selected" (остаётся текущим значением формы) - вместо просто "hidden".
Иначе ни один <option> не был бы selected, браузер сам выбрал бы первый пункт
списка ("Ректификация"), и сохранение ЛЮБОЙ другой настройки (форма /setup.htm
отправляется целиком через FormData) молча подменило бы режим пользователя.

Эта комбинация атрибутов раньше не проверялась в НАСТОЯЩЕМ браузере (только
текстовыми smoke-тестами на исходнике C++, см. tools/smoke_mode_build_availability.py).
Тест сам подставляет %NBK%/%RECT%/... токены (место шаблонизатора ESP32) в
data_raw/setup.htm под сценарий "сохранён NBK, недоступен в этой сборке" и
проверяет в Chromium:
  a) значение формы (#mode.value) равно недоступному режиму (NBK, "4"), а не
     первому пункту списка;
  b) недоступный <option> реально hidden (не показывается в раскрытом списке);
  c) при реальной отправке формы (submitSetupForm -> fetch('/save', ...FormData))
     в POST-запросе уходит именно "mode=4", а не "mode=0".
"""
import functools
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web_assets import resolve_includes

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"

# Сценарий: SamSetup.Mode == NBK (value=4), НБК недоступен в этой сборке (нет
# регулятора мощности) -> setupKeyProcessor() отдаёт NBK "hidden selected",
# остальные шесть режимов доступны и не текущие -> "".
MODE_TOKENS = {
    "RECT": "", "DIST": "", "BEER": "", "BK": "",
    "NBK": "hidden selected",
    "SUVID": "", "LUA_MODE": "",
}
# Тот же набор дефолтов, что render_site() (tools/test_numeric_input_ui_browser.py)
# использует для остальных полей setup.htm - здесь не импортируется напрямую (та
# функция - общий разделяемый хелпер для многих тестов, трогать/расширять её под
# один сценарий рискованно), а переносится узким подмножеством, нужным именно
# setup.htm.
REPLACEMENTS = {
    "HeaterR": "10.000000000", "StepperStepMl": "100", "StepperStepMlI2C": "100",
    "I2CPumpTab": "inline-block", "PackDens": "80",
    "WProgram": "", "Descr": "", "blynkauth": "", "tgtoken": "", "tgchatid": "",
    "videourl": "",
}
EMPTY_MARKERS = {
    "Checked", "FLChecked", "UASChecked", "UASDetectorChecked", "CPBuzz",
    "CUBuzz", "CUBBuzz", "UseWS", "UseST", "ChckPwr", "IgnFL",
}
ADDRESS_TOKENS = {"SteamAddr", "PipeAddr", "WaterAddr", "TankAddr", "ACPAddr"}
TOKEN_PATTERN = re.compile(r"%([A-Za-z0-9_.]+)%")


def replace_token(match: "re.Match[str]") -> str:
    name = match.group(1)
    if name in MODE_TOKENS:
        return MODE_TOKENS[name]
    if name in REPLACEMENTS:
        return REPLACEMENTS[name]
    if name in ADDRESS_TOKENS:
        return '<option value="-1" selected>-</option>'
    if name in EMPTY_MARKERS or name.startswith(("ColDiam_", "ColHeight_")):
        return ""
    if name.endswith("Color"):
        return "#000000"
    return "0"


BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const errors = [];
  const saveRequests = [];

  page.on("console", message => {
    if (message.type() === "error") errors.push("console: " + message.text());
  });
  page.on("pageerror", error => errors.push("pageerror: " + error.message));
  page.on("request", request => {
    if (request.method() === "POST" && request.url().includes("/save")) saveRequests.push(request);
  });

  await page.route("**/save", async route => {
    await route.fulfill({
      status: 202, contentType: "application/json",
      body: JSON.stringify({ operationId: 1, state: "queued", error: "none" })
    });
  });
  await page.route("**/ajax?operationId=*", route => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ operationId: 1, state: "succeeded", error: "none" })
  }));

  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });

  // Прочие числовые поля формы заполнены "нулевым" заглушечным дефолтом рендера этого
  // теста (не настоящей ESP32) - часть из них вне допустимого validateNumericFields()
  // диапазона (например DistTemp min=30) и блокировали бы submitSetupForm() ДО того, как
  // дело дойдёт до проверяемой (c). Тот же приём, что и prepareSetup() в
  // tools/test_profile_operation_ui_browser.py - выставляем каждому полю его rule.min,
  // КРОМЕ "mode": это ровно то значение, которое проверяет тест, его трогать нельзя.
  await page.evaluate(() => {
    const form = document.getElementById("setupform");
    setupNumericSchema.forEach(rule => {
      if (rule.name === "mode") return;
      const input = form.elements[rule.name];
      if (!input) return;
      const value = rule.min !== undefined ? rule.min : (rule.exclusiveMin !== undefined ? rule.exclusiveMin + 1 : 0);
      if (input.tagName === "SELECT" && !Array.from(input.options).some(option => option.value === String(value))) {
        input.add(new Option(String(value), String(value)));
      }
      input.value = String(value);
    });
  });

  // --- (a) значение формы - недоступный сохранённый режим, а не первый пункт списка ---
  const selectValue = await page.evaluate(() => document.getElementById("mode").value);
  if (selectValue !== "4") {
    throw new Error("expected #mode.value == '4' (NBK, сохранён, недоступен), got " + JSON.stringify(selectValue));
  }

  // --- (b) недоступный пункт скрыт в раскрытом списке, доступные - нет ---
  const optionState = await page.evaluate(() => {
    const options = Array.from(document.querySelectorAll("#mode option"));
    return options.map(o => ({ value: o.value, hidden: o.hidden, selected: o.selected }));
  });
  const nbkOption = optionState.find(o => o.value === "4");
  if (!nbkOption || !nbkOption.hidden || !nbkOption.selected) {
    throw new Error("NBK option must be hidden AND selected, got " + JSON.stringify(nbkOption));
  }
  const rectOption = optionState.find(o => o.value === "0");
  if (!rectOption || rectOption.hidden) {
    throw new Error("Rectification option must stay visible, got " + JSON.stringify(rectOption));
  }
  if (optionState.some(o => o.value !== "4" && o.selected)) {
    throw new Error("only the saved NBK option must be selected: " + JSON.stringify(optionState));
  }

  // --- (c) реальная отправка формы уходит с mode=4, а не mode=0 ---
  await page.evaluate(() => document.getElementById("save").click());
  for (let i = 0; i < 100 && saveRequests.length === 0; i++) {
    await page.waitForTimeout(50);
  }
  if (saveRequests.length === 0) throw new Error("form submit did not reach /save within 5s; console/pageerrors so far: " + JSON.stringify(errors) + "; url=" + page.url());
  const body = saveRequests[0].postData() || "";
  const modeMatch = body.match(/name="mode"\r?\n\r?\n(\d+)/);
  if (!modeMatch) throw new Error("mode field not found in submitted FormData body: " + body);
  if (modeMatch[1] !== "4") {
    throw new Error("submitted mode must stay '4' (NBK), got '" + modeMatch[1] + "' - hidden option was silently swapped for the first list item");
  }

  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { selectValue, nbkOption, submittedMode: modeMatch[1] };
}'''


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_head(self):
        path = self.translate_path(self.path)
        if path.endswith(".htm") and os.path.isfile(path):
            try:
                resolved = resolve_includes(os.path.basename(path), Path(path).read_bytes())
            except ValueError as exc:
                self.send_error(500, str(exc))
                return None
            data = TOKEN_PATTERN.sub(replace_token, resolved.decode("utf-8", errors="ignore")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return io.BytesIO(data)
        return super().send_head()


def run_cli(cli, session, arguments, cwd, timeout, check=True):
    result = subprocess.run(
        [cli, f"-s={session}", *arguments],
        cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False, timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if check and (result.returncode != 0 or "### Error" in result.stdout):
        raise RuntimeError(f"playwright-cli {' '.join(arguments[:1])} failed")
    return result.returncode


def cleanup_resources(cli, session, server, thread):
    errors = []
    try:
        try:
            if run_cli(cli, session, ["close"], ROOT, 30, check=False) != 0:
                errors.append("playwright-cli close failed")
        except (OSError, subprocess.TimeoutExpired) as error:
            errors.append(f"playwright-cli close failed: {error}")
    finally:
        try:
            server.shutdown()
        except Exception as error:
            errors.append(f"HTTP server shutdown failed: {error}")
        try:
            server.server_close()
        except Exception as error:
            errors.append(f"HTTP server close failed: {error}")
        thread.join(timeout=5)
        if thread.is_alive():
            errors.append("HTTP server thread did not stop")
    return errors


def main():
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    handler = functools.partial(QuietHandler, directory=str(DATA))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = f"samovar-setup-mode-hidden-{os.getpid()}"
    primary_error = None
    cleanup_errors = []

    try:
        with tempfile.TemporaryDirectory(prefix="samovar-setup-mode-hidden-browser-") as temp_dir:
            open_args = ["open"]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                config = Path(temp_dir) / "playwright.json"
                config.write_text(json.dumps({
                    "browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}
                }), encoding="utf-8")
                open_args.append(f"--config={config}")

            run_cli(cli, session, open_args, temp_dir, 30)
            base_url = f"http://127.0.0.1:{server.server_port}"
            browser_test = BROWSER_TEST.replace("__BASE_URL__", json.dumps(base_url))
            run_cli(cli, session, ["run-code", browser_test], temp_dir, 180)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        primary_error = str(error)
    finally:
        cleanup_errors = cleanup_resources(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Setup mode hidden-selected browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Setup mode hidden-selected browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Setup mode hidden-selected browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
