#!/usr/bin/env python3
"""Регресс-проверка [П4]: единственный источник таблицы "режим -> команда".

mode_registry.h хранит таблицу powerOnCommand/startCommand только один раз
(mode_power_on_command(mode) / mode_start_command(mode)). Раньше четыре точки
входа (Menu.ino menu_get_power, Blynk.ino BLYNK_WRITE(V4)/BLYNK_WRITE(V12),
lua.h lua_wrapper_set_power/lua_wrapper_set_next_program) дублировали эту
таблицу рукописным if/else по Samovar_Mode. Тест вытаскивает РЕАЛЬНЫЕ тела
этих функций и проверяет:
  1. каждое тело вызывает mode_power_on_command(...) или mode_start_command(...);
  2. в теле нет рукописных литералов команд конкретных режимов;
  3. в lua_wrapper_set_next_program гвард "if (!PowerOn) return 0;" стоит
     раньше вызова mode_start_command(...) - иначе Lua-скрипт без активной
     сессии мог бы принудительно переключить Samovar_Mode (см. mode_registry.h
     mode_apply_power_on_command);
  4. сама карта "режим -> (powerOnCommand, startCommand)" в mode_registry.h
     совпадает с ожидаемой. После [П4] одна строка таблицы управляет сразу
     четырьмя точками входа (веб, Blynk, меню, Lua), поэтому случайная правка
     строки меняет поведение всех четырёх разом и без этого пина осталась бы
     незамеченной. Значения зафиксированы по состоянию на [П4]; менять их
     можно только вместе с этим списком.
"""
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

# Рукописные литералы конкретных команд, которые дублируют таблицу реестра.
# SAMOVAR_POWER, SAMOVAR_START и SAMOVAR_NONE сюда намеренно не входят - они
# остаются в теле законно (SAMOVAR_POWER - для ветки выключения/дефолта,
# SAMOVAR_NONE - сентинел "команду ставить не надо").
FORBIDDEN_COMMANDS = [
    "SAMOVAR_BEER_NEXT",
    "SAMOVAR_DIST_NEXT",
    "SAMOVAR_NBK_NEXT",
    "SAMOVAR_BEER",
    "SAMOVAR_BK",
    "SAMOVAR_NBK",
    "SAMOVAR_DISTILLATION",
]

REGISTRY_CALLS = ("mode_power_on_command(", "mode_start_command(")


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def check_body(label: str, body: str) -> None:
    if not body:
        return
    if not any(call in body for call in REGISTRY_CALLS):
        errors.append(
            f"{label} does not call mode_power_on_command()/mode_start_command() "
            "- looks like the registry lookup was removed"
        )
    for token in FORBIDDEN_COMMANDS:
        # Границы слова, а не голая подстрока: "SAMOVAR_BEER" не должен
        # ложно сработать на "SAMOVAR_BEER_NEXT" (тот проверяется отдельным
        # токеном) и не должен сработать на легитимный enum режима вида
        # "SAMOVAR_BEER_MODE".
        if re.search(r"\b" + re.escape(token) + r"\b", body):
            errors.append(f"{label} contains hand-written command literal: {token}")


menu_source = strip_cpp_comments(read_text("Menu.ino"))
blynk_source = strip_cpp_comments(read_text("Blynk.ino"))
lua_source = strip_cpp_comments(read_text("lua.h"))

targets = [
    ("menu_get_power", menu_source, "void menu_get_power()"),
    ("BLYNK_WRITE(V4)", blynk_source, "BLYNK_WRITE(V4)"),
    ("BLYNK_WRITE(V12)", blynk_source, "BLYNK_WRITE(V12)"),
    (
        "lua_wrapper_set_power",
        lua_source,
        "static int lua_wrapper_set_power(lua_State *lua_state)",
    ),
    (
        "lua_wrapper_set_next_program",
        lua_source,
        "static int lua_wrapper_set_next_program(lua_State *lua_state)",
    ),
]

bodies: dict[str, str] = {}
for label, source, signature in targets:
    if not source:
        continue
    try:
        body = extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        continue
    bodies[label] = body
    check_body(label, body)

next_program_body = bodies.get("lua_wrapper_set_next_program", "")
if next_program_body:
    require_ordered_tokens(
        "lua_wrapper_set_next_program: PowerOn guard must precede registry lookup",
        next_program_body,
        ["if (!PowerOn) return 0;", "mode_start_command("],
        errors,
    )

# [П4] Пин самой карты режимов: пары (powerOnCommand, startCommand) по порядку строк.
EXPECTED_MODE_COMMANDS = [
    ("SAMOVAR_RECTIFICATION_MODE", "SAMOVAR_POWER", "SAMOVAR_START"),
    ("SAMOVAR_DISTILLATION_MODE", "SAMOVAR_DISTILLATION", "SAMOVAR_DIST_NEXT"),
    ("SAMOVAR_BEER_MODE", "SAMOVAR_BEER", "SAMOVAR_BEER_NEXT"),
    # У БК startCommand=SAMOVAR_NONE намеренно: SAMOVAR_START - команда ректификации.
    ("SAMOVAR_BK_MODE", "SAMOVAR_BK", "SAMOVAR_NONE"),
    ("SAMOVAR_NBK_MODE", "SAMOVAR_NBK", "SAMOVAR_NBK_NEXT"),
    ("SAMOVAR_SUVID_MODE", "SAMOVAR_POWER", "SAMOVAR_START"),
    ("SAMOVAR_LUA_MODE", "SAMOVAR_POWER", "SAMOVAR_START"),
]

registry_source = strip_cpp_comments(read_text("mode_registry.h"))
if registry_source:
    try:
        table_body = extract_function_body(
            registry_source, "inline const ModeOps* mode_registry_table(size_t& count)"
        )
    except ValueError as exc:
        errors.append(str(exc))
        table_body = ""
    if table_body:
        rows = re.findall(r"\{\s*(SAMOVAR_[A-Z_]+_MODE)\s*,([^{}]*)\}", table_body)
        if len(rows) != len(EXPECTED_MODE_COMMANDS):
            errors.append(
                f"mode_registry table has {len(rows)} rows, expected "
                f"{len(EXPECTED_MODE_COMMANDS)}"
            )
        for (mode, rest), (expected_mode, expected_power_on, expected_start) in zip(
            rows, EXPECTED_MODE_COMMANDS
        ):
            if mode != expected_mode:
                errors.append(f"mode_registry row order changed: {mode} != {expected_mode}")
                continue
            fields = [field.strip() for field in rest.split(",")]
            # Поля строки после mode: activeStatus, startvalRangeLow, startvalRangeHigh,
            # statusRangeLow, statusRangeHigh, pagePath, powerOnCommand, startCommand,
            # alarm, finish, status. [T40 А3] Добавились statusRangeLow/High - сдвинули
            # powerOnCommand/startCommand с 4/5 на 6/7.
            if len(fields) < 9:
                errors.append(f"mode_registry row for {mode} has too few fields")
                continue
            power_on, start = fields[6], fields[7]
            if power_on != expected_power_on or start != expected_start:
                errors.append(
                    f"mode_registry command map changed for {mode}: "
                    f"({power_on}, {start}) != ({expected_power_on}, {expected_start})"
                )

if errors:
    print("Mode command table single-source smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Mode command table single-source smoke check passed")
