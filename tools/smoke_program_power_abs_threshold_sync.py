#!/usr/bin/env python3
"""Сверяет числа, захардкоженные в data_raw/program.htm::programPowerAbsThreshold(),
с реальной константой PROGRAM_POWER_ABS_THRESHOLD (обе ветки #ifdef
SAMOVAR_USE_SEM_AVR) из program_types.h (пункт Б7: первая строка программы
ректификации обязана задавать АБСОЛЮТНУЮ мощность/напряжение выше этого порога).

Копии не связаны компилятором - program.htm отдаётся браузеру статикой,
шаблонизатор AsyncWebServer числа в JS не трогает. Если порог в прошивке
поменяют (например, подрегулируют 400 Вт для SEM_AVR под новую версию
регулятора), а про браузер забудут - валидация первой строки в браузере и
в прошивке начнёт расходиться: либо браузер пропустит программу, которую
прошивка на старте отвергнет как "не абсолютная мощность" (при этом форма
перед этим сохранится без единой ошибки), либо наоборот потребует от
пользователя завышенное значение. Ни один другой тест этого не заметит,
потому что program.htm не подключён ни к какой сборке C++.

Значения вычисляются НЕЗАВИСИМО из обоих файлов (не копируются друг у друга
и не хардкодятся в тесте вручную) и сравниваются между собой. Комментарии
вырезаются ДО поиска (strip_cpp_comments) - иначе закомментированная строка
со старым числом молча прошла бы проверку; кроме того, числа 400 и 40 сами
по себе упоминаются прозой в комментарии над функцией в program.htm - тело
функции достаётся через extract_function_body (поиск по точной сигнатуре и
парность скобок), а не текстовым поиском чисел по всему файлу, так что этот
комментарий не может ни подменить, ни задвоить совпадение.

data_raw/program.htm и program_types.h этим тестом только ЧИТАЮТСЯ, не
редактируются.
"""
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

THRESHOLD_MARKER = "PROGRAM_POWER_ABS_THRESHOLD"
SEM_IFDEF = "#ifdef SAMOVAR_USE_SEM_AVR"
JS_FUNC_SIGNATURE = "function programPowerAbsThreshold(unit) {"


def parse_cpp_thresholds(types_source: str) -> tuple[float, float]:
    """Возвращает (порог_SEM_AVR, порог_остальных) из program_types.h."""
    stripped = strip_cpp_comments(types_source)
    first = stripped.find(THRESHOLD_MARKER)
    if first < 0:
        raise ValueError(f"constant not found: {THRESHOLD_MARKER}")
    ifdef_idx = stripped.rfind(SEM_IFDEF, 0, first)
    if ifdef_idx < 0:
        raise ValueError(f"enclosing {SEM_IFDEF} not found before threshold constant")
    endif_idx = stripped.find("#endif", first)
    if endif_idx < 0:
        raise ValueError("closing #endif for threshold constant not found")
    block = stripped[ifdef_idx:endif_idx]

    else_idx = block.find("#else")
    if else_idx < 0:
        raise ValueError("#else branch of threshold constant not found")
    sem_block = block[:else_idx]
    default_block = block[else_idx:]

    def extract_value(text: str) -> float:
        match = re.search(rf"{THRESHOLD_MARKER}\s*=\s*([0-9.]+)f?\s*;", text)
        if not match:
            raise ValueError(f"threshold value not found in block: {text!r}")
        return float(match.group(1))

    return extract_value(sem_block), extract_value(default_block)


def parse_js_thresholds(program_htm_source: str) -> tuple[float, float]:
    """Возвращает (порог для unit "P", порог для остальных unit) из тела
    programPowerAbsThreshold() в program.htm."""
    body = extract_function_body(program_htm_source, JS_FUNC_SIGNATURE)
    match = re.search(
        r'unit\s*===\s*"P"\s*\?\s*([0-9.]+)\s*:\s*([0-9.]+)', body
    )
    if not match:
        raise ValueError(f"threshold ternary not found in function body: {body!r}")
    return float(match.group(1)), float(match.group(2))


def main() -> int:
    types_source = (ROOT / "program_types.h").read_text(encoding="utf-8")
    program_htm = (ROOT / "data_raw" / "program.htm").read_text(encoding="utf-8")

    errors: list[str] = []
    try:
        sem_cpp, default_cpp = parse_cpp_thresholds(types_source)
    except ValueError as exc:
        print(f"FAIL: program_types.h: {exc}", file=sys.stderr)
        return 1
    try:
        sem_js, default_js = parse_js_thresholds(program_htm)
    except ValueError as exc:
        print(f"FAIL: data_raw/program.htm: {exc}", file=sys.stderr)
        return 1

    if sem_cpp != sem_js:
        errors.append(
            f"SEM_AVR: PROGRAM_POWER_ABS_THRESHOLD = {sem_cpp} в program_types.h, "
            f"а programPowerAbsThreshold(\"P\") = {sem_js} в data_raw/program.htm - "
            "числа разъехались"
        )
    if default_cpp != default_js:
        errors.append(
            f"KVIC/RMVK: PROGRAM_POWER_ABS_THRESHOLD = {default_cpp} в program_types.h, "
            f"а programPowerAbsThreshold(\"V\") = {default_js} в data_raw/program.htm - "
            "числа разъехались"
        )

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(
        "OK: пороги PROGRAM_POWER_ABS_THRESHOLD совпадают в program_types.h и "
        f"data_raw/program.htm (SEM_AVR: {sem_cpp}, KVIC/RMVK: {default_cpp})"
    )
    print("program power abs threshold sync smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
