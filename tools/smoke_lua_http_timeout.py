#!/usr/bin/env python3
"""T17 п.14: http_sync_request_custom() (WebServer.ino) - синхронный HTTP-запрос,
которым пользуется обёртка http_request() из Lua (lua.h). Он выполняется на стеке
Lua-задачи do_lua_script() ПОД xLuaSemaphore - пока запрос висит, весь Lua (оба
скрипта, периодический прогон) заблокирован. Старый таймаут 4 с (+1 с запаса до
разрыва TCP) при пропаже интернета держал лок непропорционально долго. Решение -
сократить до 2 с. Смежные http_sync_request_get()/post() (загрузка веб-интерфейса)
намеренно НЕ трогаются - у них свои, более длинные таймауты.

Тест пинит константы текстово на РЕАЛЬНОМ исходнике: без компиляции, как и другие
структурные smoke-пины проекта (например smoke_lua_type_script_lock.py).
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

web_text = (ROOT / "WebServer.ino").read_text(encoding="utf-8")

try:
    custom_body = extract_function_body(
        web_text,
        "String http_sync_request_custom(const String& method, const String& url, "
        "const String& body, const String& contentType)",
    )
except ValueError as error:
    custom_body = ""
    errors.append(str(error))

if custom_body:
    if "const uint32_t timeoutMs = 2000;" not in custom_body:
        errors.append(
            "http_sync_request_custom(): timeoutMs должен быть 2000 (2 секунды)"
        )
    if "request.setTimeout(2);" not in custom_body:
        errors.append(
            "http_sync_request_custom(): request.setTimeout(...) должен быть 2 "
            "(секунды, внутренний таймаут по отсутствию активности)"
        )
    # Старые значения (4000 / setTimeout(3)) не должны просто переехать в
    # комментарий или другое место того же тела - явная проверка отсутствия.
    if "timeoutMs = 4000" in custom_body:
        errors.append("http_sync_request_custom(): остался старый таймаут 4000 мс")
    if "setTimeout(3)" in custom_body:
        errors.append("http_sync_request_custom(): остался старый setTimeout(3)")

# Соседние http_sync_request_get/post не должны быть тронуты этой правкой - у
# них другие, более длинные таймауты (загрузка веб-интерфейса, не Lua).
try:
    get_body = extract_function_body(
        web_text, "String http_sync_request_get(String url)"
    )
    if "timeoutMs = 2000" in get_body or "setTimeout(2)" in get_body:
        errors.append(
            "http_sync_request_get() не должен получить укороченный Lua-таймаут"
        )
except ValueError as error:
    errors.append(str(error))

if errors:
    print("Lua http_request timeout smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    "Lua http_request timeout smoke check passed: http_sync_request_custom() "
    "ограничен 2 секундами, http_sync_request_get() не тронут"
)
