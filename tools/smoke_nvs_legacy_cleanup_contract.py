#!/usr/bin/env python3
"""Очистка legacy-данных NVS обязана зеркалить путь их чтения.

Списки ключей и неймспейсов живут в двух местах: в цепочке чтения
(load_legacy_profile_namespace / legacy_profile_namespace_by_mode) и в таблицах
стирания. Разойдутся — очистка молча оставит мусор в NVS, и заметить это можно
будет только по исчерпанию 20-килобайтного раздела. Тест сверяет два места
исходника друг с другом, своей копии списков не держит.
"""

import re
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_source(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"файл отсутствует: {name}")
        return ""
    return strip_cpp_comments(path.read_text(encoding="utf-8", errors="ignore"))


def array_literals(source: str, name: str) -> set[str]:
    match = re.search(rf"{name}\[\]\s*=\s*\{{(.*?)\}};", source, re.S)
    if not match:
        errors.append(f"таблица {name}[] не найдена в NVS_Manager.ino")
        return set()
    return set(re.findall(r'"([^"]+)"', match.group(1)))


nvs_source = read_source("NVS_Manager.ino")
samovar_source = read_source("Samovar.ino")
api_source = read_source("samovar_api.h")

if nvs_source:
    # Ключи: что читаем из legacy-неймспейса, то и обязаны стереть.
    try:
        reader_body = extract_function_body(
            nvs_source, "static ProfileLoadResult load_legacy_profile_namespace("
        )
    except ValueError as exc:
        errors.append(str(exc))
        reader_body = ""

    read_keys = set(re.findall(r'nvs_read_\w+\(handle,\s*"([^"]+)"', reader_body))
    erased_keys = array_literals(nvs_source, "SAMOVAR_LEGACY_PROFILE_KEYS")
    if not read_keys:
        errors.append("не найдено ни одного nvs_read_* в load_legacy_profile_namespace()")
    elif erased_keys:
        never_erased = read_keys - erased_keys
        if never_erased:
            errors.append(
                "ключи читаются миграцией, но не стираются: "
                + ", ".join(sorted(never_erased))
            )
        stale = erased_keys - read_keys
        if stale:
            errors.append(
                "ключи стираются, но миграция их больше не читает: "
                + ", ".join(sorted(stale))
            )

    # Неймспейсы: каждый по-режимный источник миграции обязан быть вычищен.
    try:
        switch_body = extract_function_body(
            nvs_source, "static const char* legacy_profile_namespace_by_mode(uint8_t mode)"
        )
    except ValueError as exc:
        errors.append(str(exc))
        switch_body = ""

    read_namespaces = set(re.findall(r'return\s+"([^"]+)";', switch_body))
    erased_namespaces = array_literals(nvs_source, "SAMOVAR_LEGACY_MODE_NAMESPACES")
    if not read_namespaces:
        errors.append("не найдено ни одного неймспейса в legacy_profile_namespace_by_mode()")
    elif erased_namespaces and read_namespaces != erased_namespaces:
        errors.append(
            "таблица очистки разошлась с legacy_profile_namespace_by_mode(): "
            f"читаются {sorted(read_namespaces)}, стираются {sorted(erased_namespaces)}"
        )

    # sam_cfg смешанный: там же лежит новый блоб, стирать его целиком нельзя.
    try:
        cleanup_body = extract_function_body(
            nvs_source, "void clear_migrated_legacy_profile_data()"
        )
    except ValueError as exc:
        errors.append(str(exc))
        cleanup_body = ""

    if cleanup_body:
        if "nvs_erase_all" in cleanup_body:
            erase_all_section = cleanup_body[cleanup_body.find("nvs_erase_all") :]
            if "SAMOVAR_PROFILE_NAMESPACE" in erase_all_section:
                errors.append(
                    "nvs_erase_all() применяется к SAMOVAR_PROFILE_NAMESPACE — "
                    "стёр бы новый профиль вместе с legacy-ключами"
                )
        if "SAMOVAR_PROFILE_KEY" in cleanup_body:
            errors.append("очистка трогает SAMOVAR_PROFILE_KEY — это новый профиль")
        if "NVS_READONLY" not in cleanup_body:
            errors.append(
                "нет пробы NVS_READONLY перед nvs_open(..., NVS_READWRITE, ...) — "
                "открытие на запись создаёт отсутствующий неймспейс"
            )

if api_source and "void clear_migrated_legacy_profile_data();" not in api_source:
    errors.append("в samovar_api.h нет прототипа clear_migrated_legacy_profile_data()")

# Порядок: стирание строго после подтверждённой записи нового профиля.
if samovar_source:
    try:
        setup_body = extract_function_body(samovar_source, "void setup()")
    except ValueError as exc:
        errors.append(str(exc))
        setup_body = ""

    if setup_body:
        save_at = setup_body.find("save_profile_nvs(startupProfile)")
        cleanup_at = setup_body.find("clear_migrated_legacy_profile_data()")
        if save_at < 0:
            errors.append("setup() больше не вызывает save_profile_nvs(startupProfile)")
        elif cleanup_at < 0:
            errors.append("setup() не вызывает clear_migrated_legacy_profile_data()")
        elif cleanup_at < save_at:
            errors.append(
                "clear_migrated_legacy_profile_data() вызывается до save_profile_nvs(): "
                "стирать можно только после подтверждённой записи нового профиля"
            )
        if "migratedFromLegacy" not in setup_body:
            errors.append("setup() потерял условие migratedFromLegacy для очистки")

if errors:
    print("NVS legacy cleanup contract smoke failed:")
    for error in errors:
        print(f" - {error}")
    raise SystemExit(1)

print("NVS legacy cleanup contract smoke passed")
