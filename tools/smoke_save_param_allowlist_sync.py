#!/usr/bin/env python3
"""Регресс-проверка [П9]: allowlist /save не может рассинхронизироваться с формой.

Раньше handleSave() применял настройки по цепочке `if (name == "...")`, а
save_param_name_allowed() держала ОТДЕЛЬНЫЙ захардкоженный список из 76 имён.
Списки разъехались: SuvidHoldMinutes был в применении и в форме #setupform
(data_raw/setup.htm), но не было в allowlist - сохранение настроек ломалось
целиком на первом же параметре формы (handleSave отвечает 400 not_allowed).

Починка сделала save_param_name_allowed() и применение в handleSave() общими
потребителями одних и тех же таблиц (kSaveU16Fields, kSaveFloatFields, ...) и
двух массивов имён (kSaveMiscStringNames, kSaveSpecialNames). Этот тест не
проверяет конкретные поля (это делает smoke_handle_save_staging.py и соседи) -
он проверяет ИНВАРИАНТ: каждое имя из формы #setupform допустимо в коде, и
в save_param_name_allowed не осталось ни одного захардкоженного литерала.
"""
import re
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def form_field_names(setup_html: str) -> set[str]:
    """Имена, которые браузер реально положит в FormData #setupform.

    input/select/textarea/button с любым type, кроме 'button' (такие кнопки
    не отправляются вместе с формой).
    """
    form_match = re.search(r"<form[^>]*id=['\"]setupform['\"].*?</form>", setup_html, re.S)
    if not form_match:
        errors.append("data_raw/setup.htm: #setupform not found")
        return set()
    form = form_match.group(0)
    names: set[str] = set()
    for tag_match in re.finditer(r"<(input|select|textarea|button)\b([^>]*)>", form, re.I):
        attrs = tag_match.group(2)
        type_match = re.search(r"type=['\"]([^'\"]+)['\"]", attrs, re.I)
        type_value = type_match.group(1).lower() if type_match else None
        if type_value == "button":
            continue
        name_match = re.search(r"name=['\"]([^'\"]+)['\"]", attrs, re.I)
        if name_match:
            names.add(name_match.group(1))
    return names


def allowed_code_names(web_source_stripped: str) -> tuple[set[str], str]:
    """Множество имён, допустимых save_param_name_allowed(), и тело самой функции.

    Область поиска - от объявления первой таблицы (struct SaveFloatField) до
    конца тела save_param_name_allowed включительно: там и только там лежат
    строковые литералы имён параметров (имена полей формы), которые составляют
    источник истины для allowlist.
    """
    start = web_source_stripped.find("struct SaveFloatField")
    if start < 0:
        errors.append("WebServer.ino: SaveFloatField table declaration not found")
        return set(), ""
    signature = "static bool save_param_name_allowed(const String& name) {"
    try:
        allowlist_body, end = extract_braced_block_after(web_source_stripped, signature, start)
    except ValueError as exc:
        errors.append(str(exc))
        return set(), ""
    region = web_source_stripped[start:end]
    names = set(re.findall(r'"([A-Za-z0-9_]+)"', region))
    return names, allowlist_body


setup_text = read_text("data_raw/setup.htm")
web_text = strip_cpp_comments(read_text("WebServer.ino"))

if setup_text and web_text:
    form_names = form_field_names(setup_text)
    code_names, allowlist_body = allowed_code_names(web_text)

    missing = sorted(form_names - code_names)
    if missing:
        errors.append(
            "names present in #setupform but not accepted by save_param_name_allowed "
            f"(save is broken for these fields): {', '.join(missing)}"
        )

    if allowlist_body and re.search(r'name\s*==\s*"', allowlist_body):
        errors.append(
            "save_param_name_allowed hardcodes a literal name == \"...\" comparison "
            "again - the whole point of the shared tables is that it doesn't"
        )

if errors:
    print("save param allowlist sync smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("save param allowlist sync smoke passed")
