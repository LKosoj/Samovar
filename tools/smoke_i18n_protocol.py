#!/usr/bin/env python3
"""Протокол Blynk не зависит от языка прошивки (PIN_SPEC.md §2, §4, §6).

Сервер Blynk, сайт, плагин журналов и приложения не разбирают переводимый текст:
  1. Заголовок уровня V26/push: русская сборка шлёт «Тревога! »/«Предупреждение! »
     (их понимают и старые версии приложений), любой другой язык - ровно «⛔ »/«⚠ ».
  2. V21 «<подпись><текущее> <подпись><цель>»: потребители берут первое число,
     поэтому в подписях цифр нет ни в одном языке.
  3. События для журнала сайта несут метку перед «|»: @H1 (хмель), @L1;n=..[;v=..]
     (старт строки, ёмкость), @W1;v=...... (объём браги, мл). Метка строится в коде,
     а не в переводе: перевод не должен содержать «|» и «@».
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smoke_helpers import I18N_INCLUDE, extract_function_body  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFINE_RE = re.compile(r'^#define LANG_([A-Z][A-Z0-9_]*) "((?:[^"\\]|\\.)*)"', re.M)
LEVEL_HEADERS = {"MAIN_V26_ALARM_HEADER": "⛔ ", "MAIN_V26_WARNING_HEADER": "⚠ "}
V21_KEYS = ("BLYNK_V21_CURRENT", "BLYNK_V21_TARGET")
TAGGED_TEXT_KEYS = ("BEER_ADD_HOPS", "LOGIC_PROG_LINE_START", "LOGIC_PROG_LINE_START_LUA",
                    "LOGIC_TAKEOFF_TO_CONTAINER", "NBK_WASH_PROCESSED", "NBK_UNIT_L_SP")


def language_files() -> dict[str, dict[str, str]]:
    result = {}
    for path in sorted(ROOT.glob("lang_*.h")):
        code = path.stem[len("lang_"):]
        if code == "ru":
            continue
        result[code] = {key: value for key, value in DEFINE_RE.findall(path.read_text(encoding="utf-8"))}
    return result


def source_texts() -> dict[str, str]:
    dump = subprocess.run([sys.executable, str(ROOT / "tools" / "smoke_i18n_firmware.py"), "--dump"],
                          check=True, capture_output=True, text=True)
    return json.loads(dump.stdout)


def contract_errors(source: dict[str, str], languages: dict[str, dict[str, str]]) -> list[str]:
    errors = []
    if source.get("MAIN_V26_ALARM_HEADER") != "Тревога! " or source.get("MAIN_V26_WARNING_HEADER") != "Предупреждение! ":
        errors.append("русский заголовок уровня V26 изменился: старые версии приложений перестанут узнавать тревогу")
    for code, table in languages.items():
        for key, marker in LEVEL_HEADERS.items():
            if table.get(key) != marker:
                errors.append(f"lang_{code}.h: LANG_{key} должен быть ровно {marker!r}, а не {table.get(key)!r}")
    for key in V21_KEYS:
        for code, text in [("ru", source.get(key))] + [(c, t.get(key)) for c, t in languages.items()]:
            if text is None or re.search(r"\d", text):
                errors.append(f"{code}: подпись V21 {key} = {text!r} пуста или содержит цифру")
    for key in TAGGED_TEXT_KEYS:
        for code, text in [("ru", source.get(key))] + [(c, t.get(key)) for c, t in languages.items()]:
            if text is None or "|" in text or "@" in text:
                errors.append(f"{code}: текст {key} = {text!r} отсутствует или содержит служебные «|»/«@»")
    return errors


HARNESS = r'''
@I18N_INCLUDE@
#include <cstdint>
#include <iostream>
#include <string>
using String = std::string;
inline void append_fixed_hex(String& out, uint32_t value, uint8_t width) { @HEX@ }
inline String program_line_start_tag(uint8_t num) { @TAG@ }
int main() {
  String vessel = program_line_start_tag(2) + ";v=";
  append_fixed_hex(vessel, 11, 2);
  std::cout << program_line_start_tag(2) << "\n" << program_line_start_tag(15) << "\n" << vessel << "\n";
  String wash;
  append_fixed_hex(wash, 1234567, 6);
  std::cout << wash << "\n";
}
'''


def tag_errors() -> list[str]:
    string_utils = (ROOT / "string_utils.h").read_text(encoding="utf-8")
    logic = (ROOT / "logic.h").read_text(encoding="utf-8")
    harness = (HARNESS.replace("@I18N_INCLUDE@", I18N_INCLUDE)
               .replace("@HEX@", extract_function_body(string_utils, "inline void append_fixed_hex(String& out, uint32_t value, uint8_t width)"))
               .replace("@TAG@", extract_function_body(logic, "inline String program_line_start_tag(uint8_t num)")))
    with tempfile.TemporaryDirectory() as tmp:
        cpp = Path(tmp) / "tag.cpp"
        exe = Path(tmp) / "tag"
        cpp.write_text(harness, encoding="utf-8")
        build = subprocess.run(["g++", "-std=c++17", "-Wall", "-Werror", str(cpp), "-o", str(exe)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            return ["харнесс метки @L1 не собрался:\n" + build.stderr]
        out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split("\n")
    errors = []
    expected = ["@L1;n=03", "@L1;n=10", "@L1;n=03;v=0B", "12D687"]
    if out[:4] != expected:
        errors.append(f"метки @L1/@W1 построены неверно: {out[:4]} вместо {expected}")
    errors += token_errors()
    return errors


def token_errors() -> list[str]:
    errors = []
    beer = extract_function_body((ROOT / "beer.h").read_text(encoding="utf-8"), "void beer_stage_tick()")
    if 'SendMsg(String("@H1|") + TR(BEER_ADD_HOPS, "Засыпьте хмель!"), NOTIFY_MSG);' not in beer:
        errors.append("beer.h: сообщение о хмеле потеряло метку @H1")
    logic = (ROOT / "logic.h").read_text(encoding="utf-8")
    run = extract_function_body(logic, "void run_program(uint8_t num)")
    for token in ('SendMsg(program_line_start_tag(num) + "|" + TR(LOGIC_PROG_LINE_START_LUA,',
                  "String p_tag = program_line_start_tag(num);",
                  'p_tag += ";v=";\n    append_fixed_hex(p_tag, program[num].capacity_num, 2);',
                  'p_s = p_tag + "|" + p_s;'):
        if token not in run:
            errors.append(f"logic.h run_program: нет {token!r}")
    nbk = (ROOT / "nbk.h").read_bytes().decode("utf-8")
    for token in ('String summary = "@W1;v=";',
                  "append_fixed_hex(summary, washMl > 0xFFFFFFUL ? 0xFFFFFFUL : washMl, 6);",
                  'summary += "|";\n    summary += TR(NBK_WASH_PROCESSED,'):
        if token not in nbk:
            errors.append(f"nbk.h: нет {token!r}")
    return errors


def self_test() -> list[str]:
    errors = []
    good_source = {"MAIN_V26_ALARM_HEADER": "Тревога! ", "MAIN_V26_WARNING_HEADER": "Предупреждение! ",
                   "BLYNK_V21_CURRENT": "Тек:", "BLYNK_V21_TARGET": " Цель:"}
    good_source.update({key: "текст" for key in TAGGED_TEXT_KEYS})
    good_en = dict(LEVEL_HEADERS, BLYNK_V21_CURRENT="Cur:", BLYNK_V21_TARGET=" Set:",
                   **{key: "text" for key in TAGGED_TEXT_KEYS})
    cases = [
        ("исправный набор", good_source, {"en": good_en}, 0),
        ("перевод заголовка словом", good_source, {"en": dict(good_en, MAIN_V26_ALARM_HEADER="Alarm! ")}, 1),
        ("нет заголовка предупреждения", good_source, {"de": {k: v for k, v in good_en.items() if k != "MAIN_V26_WARNING_HEADER"}}, 1),
        ("цифра в подписи V21", good_source, {"en": dict(good_en, BLYNK_V21_TARGET=" Set2:")}, 1),
        ("цифра в русской подписи V21", dict(good_source, BLYNK_V21_CURRENT="Т1:"), {"en": good_en}, 1),
        ("русский заголовок сменили", dict(good_source, MAIN_V26_ALARM_HEADER="⛔ "), {"en": good_en}, 1),
        ("разделитель в переводе", good_source, {"en": dict(good_en, BEER_ADD_HOPS="|Add hops!")}, 1),
    ]
    for name, source, languages, count in cases:
        got = contract_errors(source, languages)
        if len(got) != count:
            errors.append(f"самотест «{name}»: ожидалось ошибок {count}, получено {got}")
    return errors


def main() -> int:
    errors = self_test()
    errors += contract_errors(source_texts(), language_files())
    errors += tag_errors()
    if errors:
        print("i18n protocol smoke failed:")
        for error in errors:
            print(" -", error)
        return 1
    print("i18n protocol smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
