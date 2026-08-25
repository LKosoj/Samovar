#!/usr/bin/env python3
"""[T28a] heater_state (Samovar.h) обязан иметь единственную точку записи -
set_heater_state_flag(bool) в beer.h. До T28a heater_state писался напрямую
в 8 местах (mode_switch.h: stop_local_mode_actuators(); beer.h: beer_finish(),
beer_stage_tick() ветка 'B', set_heater_state(float,float), set_heater_regulator(),
setHeaterPosition(); suvid.h: check_alarm_suvid() ветка !PowerOn) - ни одно из
них не было "владельцем". Этот тест статически проверяет, что ни один
корневой .h/.ino файл не присваивает heater_state напрямую (heater_state = ...)
нигде, КРОМЕ тела set_heater_state_flag() в beer.h - только читает heater_state
или вызывает set_heater_state_flag().

Порядок проверки одного файла:
  1. strip_cpp_comments() ДО поиска - иначе закомментированная строка (например,
     упоминание heater_state в doc-комментарии) либо ложно валит тест, либо
     прячет реальное нарушение под комментарием.
  2. strip_cpp_literals() ДО поиска - строковые литералы (например, экспорт в
     Lua в lua.h: `"heater_state = " + String(heater_state)`) содержат текст
     "heater_state = ", который иначе ложно сработал бы как присваивание.
  3. Тело владельца (beer.h: set_heater_state_flag) вырезается по границам
     фигурных скобок (символы тела заменяются пробелами, переводы строк
     сохраняются, чтобы не съезжала нумерация строк) и исключается из
     проверки - это единственное разрешённое присваивание флага.
  4. Регулярное выражение heater_state\\s*=(?![=!<>]) отсекает сравнения
     (==, !=) - присваиванием считается только голое "=".

Использование:
  python3 smoke_heater_state_single_writer.py
"""
import os
import re
import sys
from pathlib import Path

from smoke_helpers import strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

OWNER_FILE = "beer.h"
OWNER_SIGNATURE = "void set_heater_state_flag(bool state) {"

ASSIGNMENT_RE = re.compile(r"heater_state\s*(?:[|&^+-]|<<|>>)?=(?![=!<>])")


def strip_cpp_literals(source: str) -> str:
    """Заменяет содержимое строковых/символьных литералов пробелами (и \\n внутри
    литерала - на \\n, чтобы не съезжала нумерация строк), сохраняя структуру кода."""
    result: list[str] = []
    index = 0
    quote = ""
    escaped = False
    while index < len(source):
        char = source[index]
        if quote:
            result.append("\n" if char == "\n" else " ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in ('"', "'"):
            quote = char
            result.append(" ")
        else:
            result.append(char)
        index += 1
    return "".join(result)


def find_owner_body_span(source: str) -> tuple[int, int]:
    start = source.find(OWNER_SIGNATURE)
    if start < 0:
        raise ValueError(f"owner function not found: {OWNER_SIGNATURE}")
    if source.find(OWNER_SIGNATURE, start + 1) >= 0:
        raise ValueError(f"owner function signature is not unique: {OWNER_SIGNATURE}")
    brace = source.find("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return brace, index + 1
    raise ValueError("owner function body is not closed")


def blank_but_keep_newlines(text: str) -> str:
    return "".join(ch if ch == "\n" else " " for ch in text)


def root_source_files() -> list[str]:
    names = [name for name in os.listdir(ROOT) if name.endswith(".h") or name.endswith(".ino")]
    return sorted(names)


def scan_file(name: str) -> list[str]:
    raw = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
    clean = strip_cpp_literals(strip_cpp_comments(raw))

    if name == OWNER_FILE:
        owner_start, owner_end = find_owner_body_span(clean)
        clean = clean[:owner_start] + blank_but_keep_newlines(clean[owner_start:owner_end]) + clean[owner_end:]

    violations = []
    lines = clean.splitlines()
    for match in ASSIGNMENT_RE.finditer(clean):
        line_no = clean.count("\n", 0, match.start()) + 1
        line_text = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""
        violations.append(f"{name}:{line_no}: {line_text}")
    return violations


def main() -> int:
    if not (ROOT / OWNER_FILE).exists():
        print(f"heater_state single-writer smoke failed: owner file not found: {OWNER_FILE}")
        return 1

    violations: list[str] = []
    try:
        for name in root_source_files():
            violations.extend(scan_file(name))
    except ValueError as exc:
        print(f"heater_state single-writer smoke failed: {exc}")
        return 1

    if violations:
        print("heater_state single-writer smoke failed:")
        print("heater_state обязан писаться только через set_heater_state_flag() (beer.h),")
        print("найдены прямые присваивания вне владельца:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print("heater_state single-writer smoke passed (0 direct assignments outside owner)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
