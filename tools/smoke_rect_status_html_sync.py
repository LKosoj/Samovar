#!/usr/bin/env python3
"""Сверяет числа статусов ректификации, захардкоженные в data_raw/index.htm,
с реальными константами SAMOVAR_STATUS_RECT_ACCEL/SAMOVAR_STATUS_RECT_STABILIZING
из Samovar.h (пункт Б6: предупреждение о нестабильной колонне при раннем
старте отбора, confirmRectStart()).

Копии не связаны компилятором - index.htm отдаётся браузеру статикой, шаблонизатор
AsyncWebServer его для этих чисел не трогает. Если в перечисление статусов
(Samovar.h) вставят новый статус посередине и остальные значения сдвинутся,
числа в index.htm молча разъедутся с прошивкой, и предупреждение начнёт
срабатывать не в те моменты (или перестанет вовсе) - ни один другой тест
этого не заметит, потому что index.htm не подключён ни к какой сборке C++.

Значения вычисляются НЕЗАВИСИМО из обоих файлов (не копируются друг у друга
и не хардкодятся в тесте вручную) и сравниваются между собой. Комментарии
вырезаются ДО поиска (strip_cpp_comments) - иначе закомментированная строка
со старым числом молча прошла бы проверку.

data_raw/index.htm этим тестом только ЧИТАЕТСЯ, не редактируется.
"""
import re
import sys
from pathlib import Path

from smoke_helpers import strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]

# (имя константы в Samovar.h, имя JS-переменной в index.htm)
PAIRS = [
    ("SAMOVAR_STATUS_RECT_ACCEL", "RECT_STATUS_ACCEL"),
    ("SAMOVAR_STATUS_RECT_STABILIZING", "RECT_STATUS_STABILIZING"),
]


def extract_single(pattern: str, text: str, label: str) -> int:
    matches = re.findall(pattern, text)
    if len(matches) != 1:
        raise AssertionError(f"{label}: ожидалось ровно одно совпадение, найдено {len(matches)}")
    return int(matches[0])


def main() -> int:
    samovar_h = strip_cpp_comments((ROOT / "Samovar.h").read_text(encoding="utf-8"))
    index_htm = strip_cpp_comments((ROOT / "data_raw" / "index.htm").read_text(encoding="utf-8"))

    errors: list[str] = []
    for cpp_name, js_name in PAIRS:
        try:
            cpp_value = extract_single(
                rf"constexpr\s+int16_t\s+{re.escape(cpp_name)}\s*=\s*(\d+)\s*;",
                samovar_h,
                f"Samovar.h::{cpp_name}",
            )
        except AssertionError as exc:
            errors.append(str(exc))
            continue
        try:
            js_value = extract_single(
                rf"\bvar\s+{re.escape(js_name)}\s*=\s*(\d+)\s*;",
                index_htm,
                f"index.htm::{js_name}",
            )
        except AssertionError as exc:
            errors.append(str(exc))
            continue

        if cpp_value != js_value:
            errors.append(
                f"{cpp_name} = {cpp_value} в Samovar.h, а {js_name} = {js_value} в "
                "data_raw/index.htm - числа разъехались, confirmRectStart() будет "
                "сверяться не с теми статусами"
            )

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(f"OK: {len(PAIRS)} статус(а/ов) ректификации совпадают в Samovar.h и data_raw/index.htm")
    print("rect status html sync smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
