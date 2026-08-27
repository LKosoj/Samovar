#!/usr/bin/env python3
"""П52/П55 (WP23): setup.htm не должен молча терять несохранённые правки и не должен
молчать при загрузке файла настроек.

Проверяет:
 - dataset.dirty формы взводится при правке и снимается только настоящим сохранением;
 - window 'beforeunload' гасится (preventDefault) пока форма "грязная", и не гасится
   на чистой форме - это тот же самый признак, что уже считает существующий код
   (form.dataset.dirty), не второй, дублирующий;
 - три внутренние кнопки перехода (На главную/Редактор/Калибровка насоса) на "грязной"
   форме спрашивают confirm() и не уходят со страницы при отказе - и уходят при подтверждении
   или когда форма чистая (confirm вообще не вызывается);
 - loadFile() показывает результат через SamovarApp.showRequestError и для успеха, и для
   ошибки (битый JSON, не-объект, поле вне диапазона), а не молчит.
"""
import functools
import http.server
import io
import json
import os
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

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const errors = [];
  const passed = [];

  page.on("console", message => {
    if (message.type() === "error") errors.push("console: " + message.text());
  });
  page.on("pageerror", error => errors.push("pageerror: " + error.message));

  // Кнопка "На главную" (см. checkGuardedButton ниже) реально уводит на
  // index.htm - там app.js сразу (без задержки) начинает опрашивать /ajax
  // (см. startPollLoop). Этот тест проверяет только confirmLeaveIfDirty(), а
  // не телеметрию index.htm, но без мока запрос 404-ит и браузер сам пишет
  // "Failed to load resource" в консоль как ошибку - отдаём минимально
  // валидную заглушку, чтобы не путать эту тестируемую здесь функциональность
  // с посторонним шумом.
  await page.route("**/ajax*", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      version: "test", crnt_tm: "12:00:00", Status: "Готов", PowerOn: 0,
      heaterAlarmLatched: 0, heaterAlarmReason: '', latestMessageSequence: 0
    })
  }));

  // ВНИМАНИЕ: этот код исполняется в Node-окружении playwright-cli (снаружи
  // page.evaluate), а не в браузере - там нет глобального setTimeout
  // (проверено эмпирически: "setTimeout is not defined"), поэтому паузы
  // делаем через page.waitForTimeout(), которая живёт на самом page.
  async function waitForUrlIncludes(fragment, timeoutMs) {
    const start = Date.now();
    while (!page.url().includes(fragment)) {
      if (Date.now() - start > timeoutMs) return false;
      await page.waitForTimeout(50);
    }
    return true;
  }

  // loadFile() (см. setup.htm) читает файл через FileReader асинхронно и
  // вызывает SamovarApp.showRequestError() только внутри reader.onload, уже
  // ПОСЛЕ того, как сам loadFile() синхронно вернул управление. Опрос "текст
  // в #request_error непустой и виден" без привязки к КОНКРЕТНОМУ вызову -
  // настоящая гонка (не выдуманная): под нагрузкой первый же опрос может
  // застать ещё не обновившийся текст ПРЕДЫДУЩЕГО loadFile(), а не текст,
  // который вот-вот выставит текущий. SamovarApp уже считает ревизию
  // (currentRequestErrorRevision(), см. app.js) на каждый show/clear -
  // ждём именно её изменения относительно снимка, снятого непосредственно
  // перед вызовом loadFile() (см. каждый вызов ниже), а не просто "что-то
  // появилось". Опрос с паузой между итерациями - это только частота
  // проверки состояния, а не сама синхронизация (само условие - событие
  // "ревизия изменилась", не "прошло N миллисекунд").
  async function waitForRequestError(previousRevision, timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const state = await page.evaluate(() => {
        const el = document.getElementById("request_error");
        return el
          ? {
              text: el.textContent,
              visible: getComputedStyle(el).display !== "none",
              revision: SamovarApp.currentRequestErrorRevision(),
            }
          : null;
      });
      if (state && state.revision !== previousRevision && state.visible && state.text) return state;
      await page.waitForTimeout(20);
    }
    throw new Error("request_error did not change (revision " + previousRevision + ") within " + timeoutMs + "ms");
  }

  await page.setViewportSize({ width: 1440, height: 900 });

  // ---------- П52: dirty-флаг и beforeunload ----------
  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });

  const initialDirty = await page.evaluate(() => document.getElementById("setupform").dataset.dirty);
  if (initialDirty !== "false") throw new Error("form starts dirty=" + initialDirty);

  const preventedClean = await page.evaluate(() => {
    const ev = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(ev);
    return ev.defaultPrevented;
  });
  if (preventedClean) throw new Error("beforeunload guarded on a clean form");
  passed.push("clean form does not guard beforeunload");

  await page.evaluate(() => {
    const input = document.getElementById("DistTemp");
    input.value = "77";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const dirtyAfterEdit = await page.evaluate(() => document.getElementById("setupform").dataset.dirty);
  if (dirtyAfterEdit !== "true") throw new Error("editing a field did not set dataset.dirty");

  const preventedDirty = await page.evaluate(() => {
    const ev = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(ev);
    return ev.defaultPrevented;
  });
  if (!preventedDirty) throw new Error("beforeunload NOT guarded on a dirty form - this is the regression П52 must catch");
  passed.push("dirty form guards beforeunload (preventDefault)");

  // ---------- П52: внутренние кнопки перехода ----------
  async function checkGuardedButton(buttonId, targetFragment, revealTabId) {
    // Перед первым вызовом форма setup.htm ещё "грязная" после проверки
    // preventedDirty выше (та проверка нарочно её не сбрасывает - dirty
    // должен сохраняться, это и проверяется). Сбрасываем здесь же, иначе вот
    // этот page.goto ниже - реальная навигация с текущей (грязной) страницы -
    // сам напорется на нативный beforeunload и зависнет на незакрытом диалоге
    // ещё до того, как дойдёт до кнопок, которые эта функция должна проверять.
    await page.evaluate(() => {
      const existingForm = document.getElementById("setupform");
      if (existingForm) existingForm.dataset.dirty = "false";
    });
    // Свежая "грязная" форма, отказ в confirm() -> остаёмся на странице.
    await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
    await page.evaluate(() => {
      const input = document.getElementById("DistTemp");
      input.value = "77";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    if (revealTabId) {
      await page.evaluate(id => { document.getElementById(id).style.display = "block"; }, revealTabId);
    }
    await page.evaluate(id => {
      window.__confirmCalls = 0;
      window.confirm = function () { window.__confirmCalls++; return false; };
      document.getElementById(id).click();
    }, buttonId);
    const callsAfterCancel = await page.evaluate(() => window.__confirmCalls);
    if (callsAfterCancel !== 1) throw new Error(buttonId + ": confirm() was not called on a dirty form (calls=" + callsAfterCancel + ")");
    if (page.url().includes(targetFragment)) throw new Error(buttonId + ": navigated away despite confirm() cancel");

    // Тот же "грязный" confirm(), но подтверждаем -> должны уйти.
    // Нативный beforeunload-диалог (WP23) уже отдельно проверен выше
    // (preventedDirty) - он не имеет отношения к этому шагу: тут проверяется
    // именно confirmLeaveIfDirty() (app-level confirm). Реальная навигация
    // после accept всё равно триггерит нативный beforeunload, а он будет
    // смотреть на dataset.dirty - без сброса тест зависнет на втором, уже не
    // относящемся к этой проверке незакрытом диалоге.
    await page.evaluate(id => {
      window.__confirmCalls = 0;
      window.confirm = function () {
        window.__confirmCalls++;
        document.getElementById("setupform").dataset.dirty = "false";
        return true;
      };
      document.getElementById(id).click();
    }, buttonId);
    const navigatedAccept = await waitForUrlIncludes(targetFragment, 5000);
    if (!navigatedAccept) throw new Error(buttonId + ": did not navigate to " + targetFragment + " after confirm() accept");

    // Чистая форма -> confirm() вообще не должен вызываться.
    await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
    if (revealTabId) {
      await page.evaluate(id => { document.getElementById(id).style.display = "block"; }, revealTabId);
    }
    // На чистой форме confirmLeaveIfDirty() не вызывает confirm() вовсе и сразу
    // делает real-навигацию - значит window.__confirmCalls нужно прочитать
    // ПРЯМО в этом же evaluate (синхронно после click(), до навигации), а не
    // отдельным evaluate() после ожидания перехода: та навигация уже реальна,
    // и второй evaluate может выполниться уже на новой странице, где
    // window.__confirmCalls никогда не объявлялась (undefined !== 0 - ложный
    // сигнал "confirm() был вызван", хотя на самом деле это просто чтение не
    // того документа).
    const callsClean = await page.evaluate(id => {
      window.__confirmCalls = 0;
      window.confirm = function () { window.__confirmCalls++; return false; };
      document.getElementById(id).click();
      return window.__confirmCalls;
    }, buttonId);
    const navigatedClean = await waitForUrlIncludes(targetFragment, 5000);
    if (!navigatedClean) throw new Error(buttonId + ": clean form did not navigate to " + targetFragment);
    if (callsClean !== 0) throw new Error(buttonId + ": clean form still called confirm()");
  }

  await checkGuardedButton("return", "index.htm", null);
  passed.push("#return (На главную) guarded by confirmLeaveIfDirty");
  await checkGuardedButton("edit", "/edit", null);
  passed.push("#edit (Редактор) guarded by confirmLeaveIfDirty");
  await checkGuardedButton("setstvolume", "calibrate.htm", "Pump");
  passed.push("#setstvolume (Калибровка насоса) guarded by confirmLeaveIfDirty");

  // ---------- П55: loadFile показывает результат ----------
  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });

  const badJsonRevision = await page.evaluate(() => {
    const revision = SamovarApp.currentRequestErrorRevision();
    const file = new File(["not json"], "bad.txt", { type: "text/plain" });
    loadFile(file);
    return revision;
  });
  const badJsonState = await waitForRequestError(badJsonRevision, 3000);
  if (!/JSON|формат/i.test(badJsonState.text)) {
    throw new Error("bad JSON did not produce a readable error: " + badJsonState.text);
  }
  passed.push("loadFile reports unreadable/invalid JSON via showRequestError");

  const arrayRevision = await page.evaluate(() => {
    const revision = SamovarApp.currentRequestErrorRevision();
    const file = new File(["[1,2,3]"], "array.txt", { type: "text/plain" });
    loadFile(file);
    return revision;
  });
  const arrayState = await waitForRequestError(arrayRevision, 3000);
  if (!/формат/i.test(arrayState.text)) {
    throw new Error("non-object JSON did not produce a format error: " + arrayState.text);
  }
  passed.push("loadFile rejects non-object JSON via showRequestError");

  const outOfRangeRevision = await page.evaluate(() => {
    const revision = SamovarApp.currentRequestErrorRevision();
    const file = new File([JSON.stringify({ DistTemp: "999" })], "outofrange.txt", { type: "text/plain" });
    loadFile(file);
    return revision;
  });
  const outOfRangeState = await waitForRequestError(outOfRangeRevision, 3000);
  // T35 п.4а: с этой правки validateNumericInput() называет поле человеческой
  // подписью из DOM (см. fieldLabelFromDom в app.js), а не техническим именем
  // "DistTemp" - раньше здесь проверялось ровно наоборот. Проверка не ослаблена:
  // по-прежнему требует, чтобы конкретное поле было названо в тексте ошибки, и
  // дополнительно теперь требует ОТСУТСТВИЯ технического имени - это то самое
  // поведение, ради которого писалась правка.
  if (!/Ректификация/.test(outOfRangeState.text)) {
    throw new Error("out-of-range field was not named by its human label in the error: " + outOfRangeState.text);
  }
  if (/DistTemp/.test(outOfRangeState.text)) {
    throw new Error("out-of-range error must not leak the technical field name: " + outOfRangeState.text);
  }
  const distTempApplied = await page.evaluate(() => document.getElementById("DistTemp").value);
  if (distTempApplied !== "999") throw new Error("out-of-range value was not mapped into the form field");
  passed.push("loadFile reports the specific out-of-range field via showRequestError");

  const okRevision = await page.evaluate(() => {
    const revision = SamovarApp.currentRequestErrorRevision();
    const file = new File([JSON.stringify({ DistTemp: "80" })], "good.txt", { type: "text/plain" });
    loadFile(file);
    return revision;
  });
  const okState = await waitForRequestError(okRevision, 3000);
  if (!/загружен/i.test(okState.text) || !/Сохранить/.test(okState.text)) {
    throw new Error("success path did not explain that Save is still required: " + okState.text);
  }
  const distTempOk = await page.evaluate(() => document.getElementById("DistTemp").value);
  if (distTempOk !== "80") throw new Error("valid value was not mapped into the form field");
  passed.push("loadFile reports success and reminds to press Save");

  // ---------- T35 п.4б: showSetupSaveError переключает вкладку на ту, где
  // находится ошибочное поле, и не молчит, когда /save отвечает 400 ----------

  // showSetupSaveError() (см. setup.htm) - глобальная function-декларация в
  // обычном (не module, без "use strict") <script>, поэтому доступна как
  // window.showSetupSaveError - вызываем её напрямую с настоящим Response, тем
  // же приёмом, что и loadFile() выше, а не гоняем весь /save по сети: тут
  // проверяется именно эта функция, а не серверная часть (она уже отдельно
  // запинена server-side smoke-тестом на WebServer.ino).
  //
  // Предыдущий шаг (loadFile с валидным DistTemp) помечает форму "грязной"
  // (markSetupDirty) - обычная навигация page.goto ниже иначе напорется на
  // нативный beforeunload-диалог и зависнет (см. тот же приём в
  // checkGuardedButton выше).
  await page.evaluate(() => {
    const f = document.getElementById("setupform");
    if (f) f.dataset.dirty = "false";
  });
  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });

  const fieldErrorResult = await page.evaluate(async () => {
    const form = document.getElementById("setupform");
    const revisionBefore = SamovarApp.currentRequestErrorRevision();
    const body = JSON.stringify({
      error: "range", field: "NbkDelta", message: "Invalid NbkDelta", fields: ["NbkDelta"]
    });
    const response = new Response(body, { status: 400, headers: { "Content-Type": "application/json" } });
    await showSetupSaveError(form, response);
    function tabLinkFor(name) {
      const links = document.getElementsByClassName("tablinks");
      for (let i = 0; i < links.length; i++) {
        const onclick = links[i].getAttribute("onclick") || "";
        if (onclick.indexOf("'" + name + "'") !== -1) return links[i];
      }
      return null;
    }
    const nbkLink = tabLinkFor("NBK");
    const mainLink = tabLinkFor("Main");
    return {
      revisionBefore: revisionBefore,
      nbkDisplay: document.getElementById("NBK").style.display,
      nbkAriaHidden: document.getElementById("NBK").getAttribute("aria-hidden"),
      mainDisplay: document.getElementById("Main").style.display,
      mainAriaHidden: document.getElementById("Main").getAttribute("aria-hidden"),
      nbkLinkActive: !!nbkLink && nbkLink.className.indexOf("active") !== -1,
      nbkLinkPressed: nbkLink && nbkLink.getAttribute("aria-pressed"),
      mainLinkActive: !!mainLink && mainLink.className.indexOf("active") !== -1,
      mainLinkPressed: mainLink && mainLink.getAttribute("aria-pressed"),
      activeElementId: document.activeElement && document.activeElement.id,
    };
  });
  if (fieldErrorResult.nbkDisplay !== "block" || fieldErrorResult.nbkAriaHidden !== "false") {
    throw new Error("showSetupSaveError(field=NbkDelta) did not reveal the NBK tab: " + JSON.stringify(fieldErrorResult));
  }
  if (fieldErrorResult.mainDisplay === "block" || fieldErrorResult.mainAriaHidden === "false") {
    throw new Error("showSetupSaveError(field=NbkDelta) left the previously active Main tab visible: " + JSON.stringify(fieldErrorResult));
  }
  if (!fieldErrorResult.nbkLinkActive || fieldErrorResult.nbkLinkPressed !== "true") {
    throw new Error("showSetupSaveError(field=NbkDelta) did not highlight the NBK tab button: " + JSON.stringify(fieldErrorResult));
  }
  if (fieldErrorResult.mainLinkActive || fieldErrorResult.mainLinkPressed !== "false") {
    throw new Error("showSetupSaveError(field=NbkDelta) left the Main tab button highlighted: " + JSON.stringify(fieldErrorResult));
  }
  if (fieldErrorResult.activeElementId !== "NbkDelta") {
    throw new Error("showSetupSaveError(field=NbkDelta) did not focus the erroring field: " + JSON.stringify(fieldErrorResult));
  }
  const fieldErrorState = await waitForRequestError(fieldErrorResult.revisionBefore, 3000);
  if (fieldErrorState.text.indexOf("NbkDelta") !== -1) {
    throw new Error("save error message must show the human label, not the technical field name: " + fieldErrorState.text);
  }
  if (!/Дельта/.test(fieldErrorState.text)) {
    throw new Error("save error message did not name the field by its human label: " + fieldErrorState.text);
  }
  passed.push("showSetupSaveError switches to the erroring field's tab, highlights it and shows a human label");

  // Структурная ошибка (нет body.field - например "занято"/недоступен режим) -
  // поведение обязано остаться прежним: без переключения вкладки, просто текст
  // ошибки. Свежая страница -> активна Main (см. style="display: block;" по
  // умолчанию), проверяем, что она НЕ переключилась на NBK.
  await page.evaluate(() => {
    const f = document.getElementById("setupform");
    if (f) f.dataset.dirty = "false";
  });
  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
  const structuralErrorResult = await page.evaluate(async () => {
    const form = document.getElementById("setupform");
    const revisionBefore = SamovarApp.currentRequestErrorRevision();
    const body = JSON.stringify({ error: "busy", message: "Занято другой операцией" });
    const response = new Response(body, { status: 400, headers: { "Content-Type": "application/json" } });
    await showSetupSaveError(form, response);
    return {
      revisionBefore: revisionBefore,
      mainDisplay: document.getElementById("Main").style.display,
      nbkDisplay: document.getElementById("NBK").style.display,
    };
  });
  if (structuralErrorResult.mainDisplay !== "block" || structuralErrorResult.nbkDisplay === "block") {
    throw new Error("a structural error (no field) must not switch tabs: " + JSON.stringify(structuralErrorResult));
  }
  const structuralErrorState = await waitForRequestError(structuralErrorResult.revisionBefore, 3000);
  if (!/Занято другой операцией/.test(structuralErrorState.text)) {
    throw new Error("structural error text was not shown unchanged: " + structuralErrorState.text);
  }
  passed.push("showSetupSaveError leaves tab switching untouched for structural errors (no field)");

  // Обычное переключение по клику не должно было сломаться - openTab(evt, ...)
  // с настоящим evt (currentTarget) обязан работать так же, как раньше.
  await page.evaluate(() => {
    const f = document.getElementById("setupform");
    if (f) f.dataset.dirty = "false";
  });
  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
  const clickResult = await page.evaluate(() => {
    const links = document.getElementsByClassName("tablinks");
    let tempLink = null;
    for (let i = 0; i < links.length; i++) {
      if ((links[i].getAttribute("onclick") || "").indexOf("'Temp'") !== -1) { tempLink = links[i]; break; }
    }
    tempLink.click();
    return {
      tempDisplay: document.getElementById("Temp").style.display,
      mainDisplay: document.getElementById("Main").style.display,
      tempLinkActive: tempLink.className.indexOf("active") !== -1,
      tempLinkPressed: tempLink.getAttribute("aria-pressed"),
    };
  });
  if (clickResult.tempDisplay !== "block" || clickResult.mainDisplay === "block") {
    throw new Error("a normal click on a tab button no longer switches tabs (regression): " + JSON.stringify(clickResult));
  }
  if (!clickResult.tempLinkActive || clickResult.tempLinkPressed !== "true") {
    throw new Error("a normal click on a tab button no longer highlights it (regression): " + JSON.stringify(clickResult));
  }
  passed.push("normal click-driven tab switching still works (no regression from evt==null handling)");

  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { passed: passed };
}'''


class QuietHandler(http.server.SimpleHTTPRequestHandler):
  def log_message(self, format, *args):
    pass

  def send_head(self):
    # "/edit" в реальной прошивке отдаёт SPIFFSEditor.h (см. FS.ino) - отдельный
    # обработчик, не файл из data_raw. Этот тест проверяет только то, что
    # confirmLeaveIfDirty() пускает/не пускает на эту навигацию (см. WP52),
    # а не содержимое редактора - поэтому здесь достаточно отдать безобидную
    # заглушку 200, чтобы реальный переход не сыпал 404 console error'ами,
    # которых тест (справедливо) не ожидает ни от одной другой страницы.
    if self.path == "/edit" or self.path.startswith("/edit?"):
      data = b"<!doctype html><title>edit stub</title>"
      self.send_response(200)
      self.send_header("Content-type", "text/html; charset=utf-8")
      self.send_header("Content-Length", str(len(data)))
      self.end_headers()
      return io.BytesIO(data)
    path = self.translate_path(self.path)
    if path.endswith(".htm") and os.path.isfile(path):
      try:
        data = resolve_includes(os.path.basename(path), Path(path).read_bytes())
      except ValueError as exc:
        self.send_error(500, str(exc))
        return None
      self.send_response(200)
      self.send_header("Content-type", "text/html; charset=utf-8")
      self.send_header("Content-Length", str(len(data)))
      self.end_headers()
      return io.BytesIO(data)
    return super().send_head()


def run_cli(cli, session, arguments, cwd, timeout, check=True):
  result = subprocess.run(
    [cli, f"-s={session}", *arguments],
    cwd=cwd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    check=False,
    timeout=timeout,
  )
  if result.stdout:
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
  if check:
    command = arguments[0] if arguments else ""

    def has_marker(marker):
      # Настоящие заголовки playwright-cli ("### Error"/"### Modal state"/
      # "### Result") печатаются ТОЛЬКО в начале строки. Тот же текст может
      # случайно оказаться внутри блока "### Ran Playwright code" - туда CLI
      # эхом печатает наш же исполненный JS, включая комментарии. Проверка
      # substring без привязки к началу строки однажды поймала свой же
      # комментарий как признак заблокировавшего скрипт диалога.
      return result.stdout.startswith(marker) or ("\n" + marker) in result.stdout

    if result.returncode != 0:
      raise RuntimeError(f"playwright-cli {command} failed (exit {result.returncode})")
    if has_marker("### Error"):
      raise RuntimeError(f"playwright-cli {command} failed: '### Error' marker in output")
    if has_marker("### Modal state"):
      raise RuntimeError(
        f"playwright-cli {command} failed: '### Modal state' marker in output "
        "(a dialog blocked the script and was never handled)"
      )
    if command == "run-code" and not has_marker("### Result"):
      raise RuntimeError(f"playwright-cli {command} failed: '### Result' marker missing from output")
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
  session = f"samovar-setup-guards-{os.getpid()}"
  primary_error = None
  cleanup_errors = []

  try:
    with tempfile.TemporaryDirectory(prefix="samovar-setup-guards-browser-") as temp_dir:
      open_args = ["open"]
      if hasattr(os, "geteuid") and os.geteuid() == 0:
        config = Path(temp_dir) / "playwright.json"
        config.write_text(json.dumps({
          "browser": {
            "browserName": "chromium",
            "launchOptions": {"chromiumSandbox": False},
          }
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
      print(f"Setup guards UI browser contract failed: {primary_error}", file=sys.stderr)
    for error in cleanup_errors:
      print(f"Setup guards UI browser cleanup failed: {error}", file=sys.stderr)
    return 1

  print("Setup guards UI browser contract passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
