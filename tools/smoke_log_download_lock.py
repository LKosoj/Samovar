#!/usr/bin/env python3
"""[T19 п.23] get_data_log() (WebServer.ino) отдаёт /getlog и /getoldlog по HTTP.
Раньше файл открывался (request->beginResponse) без какой-либо синхронизации с
append_data()/ротацией лога - скачивание могло начаться ровно в момент, когда файл
переименовывается/усекается, и получить пустой или битый ответ.

Теперь перед открытием файла берётся log_file_lock() (без аргумента - используется
дефолтный таймаут pdMS_TO_TICKS(50) из runtime_helpers.h); при отказе - 503 BUSY, как и
для уже существующей проверки schedule_log_flush_if_needed(). Лок отпускается
log_file_unlock(true) на ВСЕХ путях выхода после захвата (включая ветку "файл не
найден").

Честная граница (тоже пинуется этим тестом как комментарий в коде): AsyncFileResponse
открывает файл и читает его размер синхронно внутри beginResponse(), а отдаёт
содержимое уже АСИНХРОННО, после возврата из get_data_log(). Лок защищает только
момент открытия (совпадение с ротацией), а не всю передачу - держать лок на всю
передачу заблокировало бы штатную запись показаний на секунды. Это осознанный размен,
а не недосмотр.

Тело функции вытаскивается через extract_function_body (образец -
tools/smoke_data_log_ownership.py) и проверяется require_ordered_tokens: лок берётся
раньше beginResponse(), есть ветка 503 при отказе взять лок, unlock есть и на ветке
"файл не найден", и на успешной ветке.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

SIGNATURE = "void get_data_log(AsyncWebServerRequest *request, String fn) {"

source = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
try:
    body = extract_function_body(source, SIGNATURE, strip_comments=False)
except ValueError as exc:
    errors.append(f"WebServer.ino: {exc}")
    body = ""

if body:
    require_ordered_tokens(
        "get_data_log: лок берётся до beginResponse() и отпускается на всех путях выхода",
        body,
        [
            "bool locked = log_file_lock();",
            "if (!locked) {",
            'request->send(503, "text/plain", "BUSY");',
            'if (!SPIFFS.exists("/" + fn)) {',
            "log_file_unlock(true);",
            'request->send(400, "text/plain", "Log file not found: " + fn);',
            "AsyncWebServerResponse *response = request->beginResponse(SPIFFS,",
            "log_file_unlock(true);",
        ],
        errors,
    )

    # Честная граница обязана быть в коде текстом, а не только "в голове разработчика" -
    # иначе следующий, кто удлинит окно лока "на всю передачу", не будет знать, что это
    # уже обсуждённый и отклонённый вариант.
    if "асинхронно" not in body or "beginResponse" not in body.split("Честная граница", 1)[-1][:400]:
        errors.append(
            "get_data_log: пропала честная оговорка про асинхронную отдачу файла после "
            "beginResponse() - лок защищает только момент открытия, не всю передачу"
        )

if errors:
    print("log download lock smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("log download lock smoke passed")
