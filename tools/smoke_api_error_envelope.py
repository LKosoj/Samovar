#!/usr/bin/env python3
"""Единый конверт ошибок API: экранирование на сервере и разбор на клиенте.

Сервер отдаёт ошибки конвертом {"error": <код>, "field": <имя|null>, "message": <текст>}:
error - для машины, message - для человека, field - чтобы подсветить поле в форме.

Здесь проверяются два независимых свойства.

1. build_error_envelope() экранирует и field, и message. Оба приходят из запроса: имя
   параметра вида a"b раньше склеивалось в JSON как есть и рвало ответ, после чего клиент
   получал исключение разбора вместо внятной ошибки. Тест компилирует настоящее тело
   функции и разбирает её вывод настоящим JSON-парсером.

2. responseErrorText() рисует конверт и старый формат ОДИНАКОВО. Это то свойство, которое
   делает переезд эндпоинтов безопасным: пока часть маршрутов отвечает по-старому
   ({"error": "Invalid device", "code": "invalid_argument"}), а часть уже конвертом,
   пользователь обязан видеть один и тот же текст. Тест гоняет настоящий data/app.js.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
WEBSERVER = ROOT / "WebServer.ino"
APP_JS = ROOT / "data_raw" / "app.js"
STRING_UTILS = ROOT / "string_utils.h"

CPP_HARNESS = r"""
#include <string>
#include <cstdio>

// Минимальный двойник Arduino String: нужен только конкат и доступ к символам.
class String {
 public:
  String() {}
  String(const char* s) : v(s ? s : "") {}
  String(char c) : v(1, c) {}
  void reserve(unsigned int) {}
  unsigned int length() const { return (unsigned int)v.size(); }
  char charAt(unsigned int i) const { return v[i]; }
  String& operator+=(const String& o) { v += o.v; return *this; }
  String& operator+=(const char* s) { v += s; return *this; }
  String& operator+=(char c) { v += c; return *this; }
  const char* c_str() const { return v.c_str(); }
  std::string v;
};

__STRING_UTILS__

__ENVELOPE__

int main() {
  // Разделитель, которого не может быть в JSON-выводе: печатаем несколько случаев разом.
  printf("%s\n", build_error_envelope("invalid_argument", "device", "Invalid device").c_str());
  printf("%s\n", build_error_envelope("not_allowed", "a\"b", "Invalid a\"b").c_str());
  printf("%s\n", build_error_envelope("busy", nullptr, "BUSY").c_str());
  printf("%s\n", build_error_envelope("busy", "", "BUSY").c_str());
  printf("%s\n", build_error_envelope("bad", "x\\y", "back\\slash and \"quote\"").c_str());
  printf("%s\n", build_error_envelope("bad", "nl", "line1\nline2\ttab").c_str());
  return 0;
}
"""

JS_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const appSource = fs.readFileSync(process.argv[2], "utf8");

const failures = [];
function check(cond, msg) { if (!cond) failures.push(msg); }

function makeElement() {
  const el = { style: {}, value: "", textContent: "", innerHTML: "", _attrs: {} };
  el.setAttribute = function (n, v) { el._attrs[n] = v; };
  el.getAttribute = function (n) {
    return Object.prototype.hasOwnProperty.call(el._attrs, n) ? el._attrs[n] : null;
  };
  el.hasAttribute = function (n) { return Object.prototype.hasOwnProperty.call(el._attrs, n); };
  return el;
}

function loadApp(fetchImpl) {
  const elements = {};
  const store = {};
  const env = {
    window: {},
    // sendCommand пишет сообщение в ленту, а та - в историю; без хранилища падает разбор.
    localStorage: {
      getItem: function (k) {
        return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
      },
      setItem: function (k, v) { store[k] = String(v); },
      removeItem: function (k) { delete store[k]; },
    },
    document: {
      getElementById: function (id) {
        if (!elements[id]) elements[id] = makeElement();
        return elements[id];
      },
      createElement: function () { return makeElement(); },
      querySelector: function () { return null; },
      documentElement: {},
      body: makeElement(),
      addEventListener: function () {},
    },
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    AbortController: AbortController,
    // Сообщение уровня "авария" дёргает сирену - в харнессе она немая.
    Audio: function () {
      return { play: function () { return Promise.resolve(); }, pause: function () {}, loop: false };
    },
    fetch: fetchImpl || function () { throw new Error("fetch must not be called here"); },
  };
  env.document.body.insertBefore = function () {};
  env.document.body.appendChild = function () {};
  const context = vm.createContext(env);
  vm.runInContext(appSource, context, { filename: "app.js" });
  return { app: context.window.SamovarApp, elements: elements };
}

function jsonResponse(status, body, statusText) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    statusText: statusText || "",
    headers: { get: function (n) {
      return n.toLowerCase() === "content-type" ? "application/json" : null;
    } },
    json: async function () { return body; },
    text: async function () { return JSON.stringify(body); },
  };
}

function textResponse(status, body) {
  return {
    ok: false, status: status, statusText: "",
    headers: { get: function () { return "text/plain"; } },
    json: async function () { throw new Error("not json"); },
    text: async function () { return body; },
  };
}

(async function () {
  const app = loadApp().app;

  // Свойство, ради которого всё затевалось: две формы одного и того же отказа обязаны
  // дать пользователю один и тот же текст, иначе на середине переезда UI поедет.
  const legacy = await app.responseErrorText(
    jsonResponse(400, { error: "Invalid device", code: "invalid_argument" }), "Ошибка");
  const envelope = await app.responseErrorText(
    jsonResponse(400, { error: "invalid_argument", field: "device", message: "Invalid device" }),
    "Ошибка");
  check(legacy === envelope,
    "старый формат и конверт должны рисоваться одинаково: " +
    JSON.stringify(legacy) + " != " + JSON.stringify(envelope));
  check(/Invalid device/.test(envelope),
    "конверт обязан показать человеческий message, а не только код: " + envelope);
  check(/invalid_argument/.test(envelope),
    "конверт обязан показать машинный код в скобках: " + envelope);

  // Машинный код не должен подменять собой текст.
  const codeOnly = await app.responseErrorText(
    jsonResponse(400, { error: "not_allowed", field: null, message: "Поле не принимается" }), "");
  check(/Поле не принимается/.test(codeOnly), "message должен попасть в текст: " + codeOnly);

  // Ответ /program сознательно оставлен со своей формой {ok, err, program}.
  const program = await app.responseErrorText(
    jsonResponse(400, { ok: false, err: "Синтаксис строки 3" }), "");
  check(/Синтаксис строки 3/.test(program), "форма {ok, err} должна продолжать работать: " + program);

  // Простой текст (часть маршрутов ещё на text/plain).
  const plain = await app.responseErrorText(textResponse(400, "Invalid request: argument"), "");
  check(/Invalid request: argument/.test(plain), "text/plain должен работать: " + plain);

  // Дубля кода быть не должно, если текст и код совпали.
  const same = await app.responseErrorText(
    jsonResponse(503, { error: "busy", field: null, message: "busy" }), "");
  check((same.match(/busy/g) || []).length === 1, "код не должен дублировать текст: " + same);

  // --- /command: токенный протокол ------------------------------------------------
  // Клиент обязан достать токен из конверта и выбрать по нему текст и уровень ровно так
  // же, как раньше выбирал по телу ответа. Иначе штатный отказ (занято/нагрев выключен)
  // перестанет отличаться от аварии связи и полезет в UI как критическая ошибка.
  function commandResponse(status, contentType, body) {
    return {
      ok: status >= 200 && status < 300,
      status: status,
      statusText: "",
      headers: { get: function (n) {
        return n.toLowerCase() === "content-type" ? contentType : null;
      } },
      text: async function () { return body; },
    };
  }

  // Наблюдаем за тем, что реально увидит пользователь: showRequestError кладёт чистый
  // textContent без метки времени, поэтому два прогона сравнимы побайтно (лента сообщений
  // штампует время и для сравнения не годится).
  async function runCommand(resp) {
    const fresh = loadApp(function () { return Promise.resolve(resp); });
    const ok = await fresh.app.sendCommand("stop");
    const box = fresh.elements.request_error;
    return { ok: ok, shown: box ? box.textContent : "" };
  }

  const busyEnvelope = await runCommand(commandResponse(
    503, "application/json", '{"error":"BUSY","field":null,"message":"BUSY"}'));
  const busyLegacy = await runCommand(commandResponse(503, "text/plain", "BUSY"));
  check(JSON.stringify(busyEnvelope) === JSON.stringify(busyLegacy),
    "/command: конверт и старый токен должны обрабатываться одинаково: " +
    JSON.stringify(busyEnvelope) + " != " + JSON.stringify(busyLegacy));
  check(busyEnvelope.ok === false, "/command: BUSY обязан вернуть false");
  check(/занято/i.test(busyEnvelope.shown),
    "/command: BUSY обязан дать штатный текст по токену, а не сырой HTTP: " +
    JSON.stringify(busyEnvelope.shown));
  check(!/HTTP/.test(busyEnvelope.shown),
    "/command: штатный отказ не должен выглядеть как авария связи: " +
    JSON.stringify(busyEnvelope.shown));

  const powerOff = await runCommand(commandResponse(
    409, "application/json", '{"error":"POWER_OFF","field":null,"message":"POWER_OFF"}'));
  check(/нагрев выключен/i.test(powerOff.shown),
    "/command: POWER_OFF обязан распознаваться из конверта: " + JSON.stringify(powerOff.shown));

  // Сервер сегодня кладёт в error и message один и тот же токен, поэтому фикстура с
  // совпадающими полями пройдёт и у клиента, который берёт токен из message. Разводим поля,
  // чтобы закрепить саму развилку: токен - из error, человеческий текст - из message. Иначе
  // первый же сервер, который начнёт слать в message настоящий текст, молча потеряет токен.
  const busySplit = await runCommand(commandResponse(
    503, "application/json",
    '{"error":"BUSY","field":null,"message":"Идёт калибровка насоса"}'));
  check(busySplit.ok === false,
    "/command: BUSY обязан вернуть false и при несовпадении error/message");
  check(/команда не принята/i.test(busySplit.shown),
    "/command: токен обязан браться из error, а не из message: " +
    JSON.stringify(busySplit.shown));

  const okResp = await runCommand(commandResponse(200, "text/plain", "OK"));
  check(okResp.ok === true, "/command: успех обязан остаться успехом: " + JSON.stringify(okResp));

  // Битый JSON не должен ронять разбор - должен деградировать в обычную HTTP-ошибку.
  const broken = await runCommand(commandResponse(500, "application/json", '{"error":'));
  check(broken.ok === false, "/command: битый JSON обязан дать отказ, а не исключение");

  if (failures.length) {
    for (const f of failures) console.log("FAIL: " + f);
    process.exit(1);
  }
  console.log("js ok");
})();
"""


def run_cpp(errors):
    source = WEBSERVER.read_text(encoding="utf-8", errors="ignore")
    try:
        body = extract_function_body(
            source,
            "static String build_error_envelope(const char *code, const char *field, const String& message)",
        )
    except Exception as exc:
        errors.append(f"WebServer.ino: не найдено тело build_error_envelope(): {exc}")
        return

    utils = STRING_UTILS.read_text(encoding="utf-8", errors="ignore")
    try:
        json_body = extract_function_body(utils, "inline String toJsonString(const String& s)")
    except Exception as exc:
        errors.append(f"string_utils.h: не найдено тело toJsonString(): {exc}")
        return

    program = CPP_HARNESS.replace(
        "__STRING_UTILS__",
        "static String toJsonString(const String& s) {\n" + json_body + "\n}",
    ).replace(
        "__ENVELOPE__",
        "static String build_error_envelope(const char *code, const char *field, "
        "const String& message) {\n" + body + "\n}",
    )

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "envelope.cpp"
        exe = Path(tmp) / "envelope"
        src.write_text(program, encoding="utf-8")
        compile_proc = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(src)],
            capture_output=True, text=True,
        )
        if compile_proc.returncode != 0:
            errors.append("build_error_envelope() не компилируется:\n" + compile_proc.stderr)
            return
        run_proc = subprocess.run([str(exe)], capture_output=True, text=True)
        if run_proc.returncode != 0:
            errors.append("харнесс build_error_envelope() упал:\n" + run_proc.stderr)
            return

    lines = run_proc.stdout.strip("\n").split("\n")
    if len(lines) != 6:
        errors.append(f"ожидалось 6 конвертов, получено {len(lines)}: {lines}")
        return

    # Разбираем настоящим парсером: если экранирование сломано, тут будет исключение,
    # ровно как у клиента в resp.json().
    parsed = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"конверт не разбирается как JSON ({exc}): {line}")
            return

    for obj in parsed:
        for key in ("error", "field", "message"):
            if key not in obj:
                errors.append(f"в конверте нет ключа {key}: {obj}")

    if parsed[0] != {"error": "invalid_argument", "field": "device", "message": "Invalid device"}:
        errors.append(f"обычный случай собран неверно: {parsed[0]}")
    if parsed[1] != {"error": "not_allowed", "field": 'a"b', "message": 'Invalid a"b'}:
        errors.append(
            "кавычка в имени поля обязана экранироваться, иначе ответ рвётся: "
            f"{parsed[1]}"
        )
    if parsed[2]["field"] is not None:
        errors.append(f"отсутствующее поле обязано быть null, а не строкой: {parsed[2]}")
    if parsed[3]["field"] is not None:
        errors.append(f"пустое имя поля обязано быть null, а не пустой строкой: {parsed[3]}")
    if parsed[4] != {"error": "bad", "field": "x\\y", "message": 'back\\slash and "quote"'}:
        errors.append(f"обратный слэш собран неверно: {parsed[4]}")
    if parsed[5]["message"] != "line1\nline2\ttab":
        errors.append(f"перевод строки/таб собраны неверно: {parsed[5]}")


def run_js(errors):
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(JS_HARNESS, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(harness), str(APP_JS)], capture_output=True, text=True,
        )
        if proc.returncode != 0:
            errors.append("разбор ошибок на клиенте:\n" + proc.stdout + proc.stderr)


def check_no_unescaped_names(errors):
    """Имя параметра из запроса не должно склеиваться в JSON голой конкатенацией."""
    source = WEBSERVER.read_text(encoding="utf-8", errors="ignore")
    # Ловим любую форму, включая тернарник `json += field ? field : "request";` - именно так
    # дыра и выглядела, и проверка на голое `json += field;` прошла бы мимо неё.
    for match in re.finditer(r'json\s*\+=\s*([^;\n]+);', source):
        expr = match.group(1)
        if "toJsonString" in expr:
            continue
        # Вырезаем строковые литералы: сам конверт печатает ключ ",\"field\":" - это данные,
        # а не подстановка имени поля.
        expr = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expr)
        if re.search(r'\bfield\b|\bmessage\b|->name\(\)', expr):
            line = source[: match.start()].count("\n") + 1
            errors.append(
                f"WebServer.ino:{line}: текст из запроса кладётся в JSON без toJsonString() "
                f"(`json += {expr.strip()};`) - параметр с кавычкой порвёт ответ"
            )


def check_single_envelope_builder(errors):
    """Конверт должен собираться в одном месте.

    Переезд на конверт чуть не прошёл мимо /ajax_col_params: тот уже отдавал
    application/json, поэтому поиск по "text/plain" его не нашёл, и маршрут остался на
    старой форме {"error": "...", "code": "..."}. Инвариант ловит это по существу: любая
    ручная сборка тела ошибки, кроме самой build_error_envelope, - это новый формат.
    """
    source = WEBSERVER.read_text(encoding="utf-8", errors="ignore")
    builder = source.find("static String build_error_envelope")
    for match in re.finditer(r'"\{\\"error\\"', source):
        # Единственное законное вхождение - внутри самой build_error_envelope.
        if builder != -1 and builder < match.start() < builder + 700:
            continue
        line = source[: match.start()].count("\n") + 1
        errors.append(
            f"WebServer.ino:{line}: тело ошибки собирается вручную мимо "
            "build_error_envelope() - это четвёртый формат вместо единого конверта"
        )
    if re.search(r'\\"code\\"\s*:', source):
        line = source[: re.search(r'\\"code\\"\s*:', source).start()].count("\n") + 1
        errors.append(
            f"WebServer.ino:{line}: остался старый ключ \"code\" - в конверте машинный "
            "код лежит в \"error\", а \"code\" читают только legacy-ответы"
        )


def main() -> int:
    errors = []
    for path in (WEBSERVER, APP_JS, STRING_UTILS):
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)} не найден")
    if errors:
        print("api error envelope smoke failed:")
        for e in errors:
            print(f" - {e}")
        return 1

    run_cpp(errors)
    run_js(errors)
    check_no_unescaped_names(errors)
    check_single_envelope_builder(errors)

    if errors:
        print("api error envelope smoke failed:")
        for e in errors:
            print(f" - {e}")
        return 1
    print("api error envelope smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
