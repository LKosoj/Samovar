#!/usr/bin/env python3
"""Контракт для include-механизма tools/build_web_assets.py.

(a) В собранном data/ не должно остаться нерезолвленных <!--#include-->.
    Если такой маркер попадёт в <script>, браузер по правилу Annex B молча
    трактует его как JS-комментарий и вырезает код без единой ошибки сборки
    (см. tools/build_web_assets.py) - тест должен ловить это явно.
(b) Каждый файл в data_raw/partials/ обязан использоваться хотя бы одним
    <!--#include-->, иначе это мёртвый партиал, который никто не заметит.
"""
import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web_assets import INCLUDE_RE, PARTIALS_DIR, SOURCE, TARGET


def check_built_has_no_unresolved_includes(errors: list[str]) -> None:
    for path in sorted(p for p in TARGET.iterdir() if p.is_file()):
        if path.name.endswith(".gz"):
            try:
                data = gzip.decompress(path.read_bytes())
            except OSError as exc:
                errors.append(f"data/{path.name}: не удалось распаковать gzip: {exc}")
                continue
        else:
            data = path.read_bytes()
        if INCLUDE_RE.search(data):
            errors.append(
                f"data/{path.name}: остался нерезолвленный <!--#include--> в собранном образе"
            )


def check_every_partial_is_used(errors: list[str]) -> None:
    if not PARTIALS_DIR.is_dir():
        errors.append("data_raw/partials/ отсутствует")
        return
    partials = sorted(p.name for p in PARTIALS_DIR.iterdir() if p.is_file())
    if not partials:
        errors.append("data_raw/partials/ пуст - нечего проверять")
        return

    referenced: set[str] = set()
    # include может встретиться и у потребителя верхнего уровня, и внутри другого партиала.
    candidates = [p for p in SOURCE.iterdir() if p.is_file()]
    candidates += [p for p in PARTIALS_DIR.iterdir() if p.is_file()]
    for path in candidates:
        for match in INCLUDE_RE.finditer(path.read_bytes()):
            referenced.add(match.group(1).decode("ascii"))

    for name in partials:
        if name not in referenced:
            errors.append(f"data_raw/partials/{name}: не используется ни одним <!--#include-->")


def main() -> int:
    errors: list[str] = []
    if not TARGET.is_dir():
        errors.append("data/ отсутствует - нужен прогон tools/build_web_assets.py")
    else:
        check_built_has_no_unresolved_includes(errors)
    check_every_partial_is_used(errors)

    if errors:
        print("Web includes contract failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("Web includes contract smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
