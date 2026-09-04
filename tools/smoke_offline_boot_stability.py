#!/usr/bin/env python3
"""Загрузка без интернета: не перезагружаться по кругу и не стирать настройки WiFi.

Жалобы с форума на 6.26/6.27:
  - без интернета устройство уходило в ребут каждые ~20 секунд. Лог начинался с
    "Timeout: readyState never reached 1", дальше Guru Meditation (InstrFetchProhibited).
    Причина: WebServerInit() безусловно звал get_web_interface(), объект asyncHTTPrequest
    жил на стеке, а отменить начатый lwIP-DNS нельзя - колбэк приходил в память
    уже разрушенного объекта;
  - "не запоминает сеть, поднимается AP": настройки WiFi стирались сами на старте -
    GPIO0 опрашивался без подтяжки, а кнопка энкодера сбрасывала их от короткого нажатия.

Тест статический: поведение зависит от железа и сети, воспроизвести его в харнессе
нельзя, поэтому пинится согласие в коде.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

errors: list[str] = []


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.exists():
        errors.append(f"{relative}: файл не найден")
        return ""
    return strip_cpp_comments(path.read_text(encoding="utf-8", errors="ignore"))


def body(source: str, signature: str, name: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as error:
        errors.append(f"{name}: {error}")
        return ""


web_server = read("WebServer.ino")
samovar = read("Samovar.ino")
async_http = read("libraries/asyncHTTPrequest/src/asyncHTTPrequest.cpp")

# 1. Загрузка интерфейса только при живом подключении к сети и до
# запуска датчиков/веб-сервера: открытые файлы LittleFS мешают обновлению.
web_server_init = body(web_server, "void WebServerInit(void)", "WebServerInit")
setup = body(samovar, "void setup()", "setup")
if setup:
    require_ordered_tokens(
        "setup",
        setup,
        [
            "setup_connect_wifi_and_notify();",
            "WiFi.status() == WL_CONNECTED",
            "get_web_interface();",
            "sensor_init();",
            "startService();",
            "WebServerInit();",
        ],
        errors,
    )
    if setup.count("get_web_interface()") != 1:
        errors.append("setup: get_web_interface() должен вызываться ровно один раз")
if web_server_init and "get_web_interface()" in web_server_init:
    errors.append("WebServerInit: обновление UI должно завершиться до запуска веб-сервера")

# 2. Объект запроса общий и долгоживущий, доступ к нему сериализован.
if web_server and "static asyncHTTPrequest sharedHttpRequest;" not in web_server:
    errors.append("WebServer.ino: нет долгоживущего объекта sharedHttpRequest")

for signature, name in (
    ("String http_sync_request_get(String url)", "http_sync_request_get"),
    ("static bool http_sync_download_file(const String& url, const String& path)",
     "http_sync_download_file"),
):
    request_body = body(web_server, signature, name)
    if not request_body:
        continue
    if "asyncHTTPrequest request;" in request_body:
        errors.append(f"{name}: объект запроса снова создаётся на стеке - DNS-колбэк придёт в мёртвую память")
    require_ordered_tokens(
        name,
        request_body,
        ["HttpRequestLockGuard lockGuard;", "lockGuard.acquired", "asyncHTTPrequest& request = sharedHttpRequest;"],
        errors,
    )

# 3. abort() при пустом клиенте обязан отпустить мьютекс.
abort_body = body(async_http, "void    asyncHTTPrequest::abort()", "asyncHTTPrequest::abort")
if abort_body:
    require_ordered_tokens(
        "asyncHTTPrequest::abort",
        abort_body,
        ["_seize;", "if(! _client){", "_release;", "return;", "_client->abort();", "_release;"],
        errors,
    )

# 4. Стирание настроек WiFi - только по удержанию.
if samovar:
    if "pinMode(0, INPUT_PULLUP);" not in samovar:
        errors.append("Samovar.ino: GPIO0 опрашивается без внутренней подтяжки")
    require_ordered_tokens(
        "Samovar.ino GPIO0",
        samovar,
        [
            "pinMode(0, INPUT_PULLUP);",
            "if (digitalRead(0) == LOW) {",
            "while (digitalRead(0) == LOW && millis() - wifiResetHoldStart < 2000)",
            "if (digitalRead(0) == LOW) {",
            "WiFi.disconnect(true, true);",
        ],
        errors,
    )
    require_ordered_tokens(
        "Samovar.ino encoder",
        samovar,
        [
            "if (encoder.isPress()) {",
            "while (encoder.isHold() && millis() - encoderHoldStart < 2000)",
            "encoder.tick();",
            "if (encoder.isHold()) {",
            "wifiManager.resetSettings();",
        ],
        errors,
    )


def main() -> int:
    if errors:
        print("offline boot stability smoke failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1
    print("offline boot stability smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
