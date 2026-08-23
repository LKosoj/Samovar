#!/usr/bin/env python3
"""WP10 п.23: замки в Samovar.ino обязаны быть мьютексами, а не двоичными семафорами.

У двоичного семафора (xSemaphoreCreateBinary*) нет владельца - любая задача может
"отдать" замок, который взяла другая, и защита молча перестаёт работать. У мьютекса
(xSemaphoreCreateMutex*) есть владелец и наследование приоритета (низкоприоритетная
задача-держатель не виснет вытесненной, пока её ждёт высокоприоритетная).

Двоичный семафор создаётся уже ВЗЯТЫМ, поэтому старый код был обязан сразу отдать
его через xSemaphoreGive(), чтобы замок стал свободным. Мьютекс создаётся уже
СВОБОДНЫМ - лишний Give сразу после создания был бы отпусканием невзятого мьютекса
(ошибочный вызов, симптом недоделанной миграции). Тест проверяет оба факта на
РЕАЛЬНОМ исходнике Samovar.ino, а не на копии кода.
"""
import re
import sys
from pathlib import Path

from smoke_helpers import strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
SAMOVAR_INO = ROOT / "Samovar.ino"

# Все замки, которые создаются в Samovar.ino (StaticSemaphore_t-хендлы из Samovar.h).
LOCK_HANDLES = [
    "xRuntimeStateSemaphore",
    "xPendingCommandSemaphore",
    "xLogFileSemaphore",
    "xLuaSemaphore",
    "xI2CSemaphore",
    "xMsgSemaphore",
]

errors: list[str] = []

raw_text = SAMOVAR_INO.read_text(encoding="utf-8")
text = strip_cpp_comments(raw_text)
lines = text.splitlines()

CREATE_RE = re.compile(
    r"(\w+)\s*=\s*xSemaphoreCreate(Binary|Mutex)Static\s*\(\s*&(\w+)\s*\)\s*;"
)

found_handles: set[str] = set()

for index, line in enumerate(lines):
    match = CREATE_RE.search(line)
    if not match:
        continue
    handle, kind, buffer_name = match.groups()
    if handle not in LOCK_HANDLES:
        continue
    found_handles.add(handle)

    # ---- 1. обязан быть мьютекс, не двоичный семафор -------------------------
    if kind != "Mutex":
        errors.append(
            f"Samovar.ino: {handle} создаётся как xSemaphoreCreate{kind}Static "
            f"(строка исходника ~{index + 1}) - это двоичный семафор без владельца "
            f"и без наследования приоритета, нужен xSemaphoreCreateMutexStatic"
        )
        continue

    # ---- 2. мьютекс создаётся уже свободным - лишний Give рядом - ошибка ----
    # Смотрим несколько строк вперёд (в пределах той же логической группы
    # инициализации, до первой пустой строки или следующего присваивания
    # хендла) - именно там раньше стоял обязательный для binary-семафора Give.
    window: list[str] = []
    for follow in lines[index + 1: index + 6]:
        if follow.strip() == "" or CREATE_RE.search(follow):
            break
        window.append(follow)
    give_re = re.compile(r"xSemaphoreGive\s*\(\s*" + handle + r"\s*\)\s*;")
    for follow in window:
        if give_re.search(follow):
            errors.append(
                f"Samovar.ino: {handle} - лишний xSemaphoreGive() сразу после "
                f"xSemaphoreCreateMutexStatic() (строка исходника ~{index + 1}); "
                f"мьютекс уже создаётся свободным, такой Give - отпускание "
                f"невзятого мьютекса"
            )

missing = [handle for handle in LOCK_HANDLES if handle not in found_handles]
if missing:
    errors.append(
        "Samovar.ino: не найдено место создания для замков: " + ", ".join(missing)
    )

if errors:
    print("Lock binary-to-mutex smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    f"Lock binary-to-mutex smoke check passed: {len(found_handles)} замков в "
    "Samovar.ino - все мьютексы, лишних Give после создания нет"
)
