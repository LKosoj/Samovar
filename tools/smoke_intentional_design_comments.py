#!/usr/bin/env python3
"""[T19 п.18-19] Три места в прошивке принимают риск сознательно (решение владельца),
а не по недосмотру. Правок логики здесь нет и не будет - только комментарии, которые
фиксируют это решение прямо в коде, чтобы следующий разработчик не "починил" то, что
уже осознанно оставлено как есть.

Тест пинит СОГЛАСИЕ (наличие честной формулировки на месте), а не поведение - код,
который эти комментарии описывают, здесь не выполняется. Образец паттерна -
tools/smoke_fs_editor_hygiene.py (require_token по сырому тексту файла).

Три места:
  1. write_state_snapshot() (FS.ino) - неатомарная запись /state.csv: снимок пишется
     раз в 30 секунд, его потеря не опаснее самого сбоя питания, а временный файл с
     переименованием удвоил бы износ флеша и время такта.
  2. GET-обработчик /lua (WebServer.ino) - имя файла (param->value(), уходит в
     queue_pending_string) намеренно не ограничивается по составу/расширению.
  3. get_lua_script() (lua.h) - readString() читает файл целиком в ОЗУ; запрос
     заведомо большого файла может уронить контроллер по нехватке памяти, ограничение
     размера сознательно не введено.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, text: str, token: str) -> None:
    if token not in text:
        errors.append(f"{name} missing token: {token}")


def require_token_between(name: str, text: str, anchor: str, token: str, *, window: int = 600) -> None:
    idx = text.find(anchor)
    if idx < 0:
        errors.append(f"{name}: anchor not found: {anchor}")
        return
    start = max(0, idx - window)
    segment = text[start:idx]
    if token not in segment:
        errors.append(f"{name}: comment missing right before {anchor!r}: {token!r}")


fs = read_text("FS.ino")
web = read_text("WebServer.ino")
lua = read_text("lua.h")

# --- 1. FS.ino: write_state_snapshot() - неатомарная запись /state.csv осознанна -------
if fs:
    require_token_between(
        "FS.ino write_state_snapshot",
        fs,
        "bool write_state_snapshot() {",
        "осознанное решение владельца",
    )
    require_token_between(
        "FS.ino write_state_snapshot",
        fs,
        "bool write_state_snapshot() {",
        "STATE_SNAPSHOT_PERIOD_S",
    )
    require_token_between(
        "FS.ino write_state_snapshot",
        fs,
        "bool write_state_snapshot() {",
        "не опаснее самого сбоя",
    )

# --- 2. WebServer.ino: GET /lua - имя файла намеренно не ограничивается ----------------
if web:
    require_token_between(
        "WebServer.ino /lua GET handler",
        web,
        "queue_pending_string(pending_lua_file_flag, pending_lua_file, param->value())",
        "намеренно не ограничивается",
    )
    require_token_between(
        "WebServer.ino /lua GET handler",
        web,
        "queue_pending_string(pending_lua_file_flag, pending_lua_file, param->value())",
        "осознанный выбор владельца",
    )

# --- 3. lua.h: get_lua_script() - readString() целиком в ОЗУ, честная оговорка ----------
if lua:
    require_token_between(
        "lua.h get_lua_script",
        lua,
        "s = f.readString();",
        "readString() читает файл целиком в ОЗУ",
    )
    require_token_between(
        "lua.h get_lua_script",
        lua,
        "s = f.readString();",
        "уронить контроллер по нехватке памяти",
    )
    require_token_between(
        "lua.h get_lua_script",
        lua,
        "s = f.readString();",
        "сознательно не введено",
    )

if errors:
    print("intentional design comments smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("intentional design comments smoke passed")
