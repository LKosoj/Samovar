#!/usr/bin/env python3
"""Проверка разрешимости заголовков, включённых через #include "...".

Зачем отдельная проверка. Глубокий статический анализ (tools/run_cppcheck.py)
глушит категорию missingInclude: заголовки платформы (ESP-IDF/Arduino) лежат вне
репозитория, путей -I этому запуску никто не передаёт, и категория гарантированно
находит один и тот же "заголовок не найден" на каждом прогоне. Но вместе с шумом
глушится и полезная часть: #include "moya_novaya_shtuka.h" на файл, которого в
репозитории нет, тоже перестаёт быть находкой.

Компилятор такой include поймает - но только если файл попадает в сборку. Заголовок,
включаемый под #ifdef, который не взведён ни в одном из окружений platformio.ini,
не увидит ни одна из семи сборок. Эта проверка смотрит текст, а не сборку, поэтому
видит и такие случаи.

Внешние заголовки заявляются в tools/external_headers.json с причиной - список
маленький и меняется только при появлении новой зависимости.

Границы защиты: список ловит дрейф (файл появился в репозитории, а запись осталась;
запись есть, а заголовок никто не включает), но не проверяет правдивость причины.
Заглушить настоящую поломку, вписав сломанный заголовок во внешние, технически возможно -
барьером тут служит только чтение диффа external_headers.json на код-ревью, файл для
того и держится маленьким.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Единственная в проекте реализация вырезания комментариев (сохраняет переносы
# строк, поэтому номера строк в сообщениях остаются настоящими). Модуль чистый,
# без зависимостей, поэтому годится и для инструмента CI, а не только для тестов.
from runner_utils import SOURCE_SUFFIXES  # noqa: E402
from smoke_helpers import strip_cpp_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_PATH = Path(__file__).resolve().parent / "external_headers.json"
# [ \t]* перед кавычкой, а не [ \t]+: #include"file.h" без пробела - валидный
# синтаксис препроцессора, и такая директива обязана проверяться наравне с обычной.
INCLUDE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"', re.MULTILINE)


class ExternalHeadersError(ValueError):
    pass


def load_external_headers(path: Path = EXTERNAL_PATH) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExternalHeadersError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict) or set(data) != {"headers"}:
        raise ExternalHeadersError("manifest must contain exactly one key: 'headers'")
    headers = data["headers"]
    if not isinstance(headers, dict) or not all(
        isinstance(name, str) and isinstance(reason, str) and reason.strip()
        for name, reason in headers.items()
    ):
        raise ExternalHeadersError("'headers' must map header names to non-empty reasons")
    if list(headers) != sorted(headers):
        raise ExternalHeadersError("'headers' keys must be sorted")
    return headers


def root_sources(root: Path = ROOT) -> list[Path]:
    return sorted(
        path for path in root.iterdir()
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    )


def check_includes(root: Path = ROOT, external: dict[str, str] | None = None) -> list[str]:
    """Возвращает список сообщений об ошибках; пустой список - всё разрешимо."""
    headers = load_external_headers() if external is None else external
    problems: list[str] = []

    # Заявленный внешним заголовок, который на самом деле лежит в репозитории, -
    # протухший список: такой include перестал бы проверяться молча.
    for name in sorted(headers):
        if (root / name).exists():
            problems.append(
                f"tools/external_headers.json: '{name}' есть в репозитории, "
                "он больше не внешний - удалите запись"
            )

    for source in root_sources(root):
        # Комментарии убираем: закомментированный include файла не требует,
        # а многострочный /* ... */ вокруг него regex сам по себе не заметил бы.
        text = strip_cpp_comments(source.read_text(encoding="utf-8", errors="replace"))
        for match in INCLUDE_RE.finditer(text):
            target = match.group(1)
            if target in headers:
                continue
            if (source.parent / target).exists():
                continue
            line = text.count("\n", 0, match.start()) + 1
            problems.append(
                f'{source.name}:{line}: #include "{target}" не разрешается: '
                "файла нет в репозитории и он не заявлен в tools/external_headers.json"
            )
    return problems


def main() -> int:
    try:
        problems = check_includes()
    except ExternalHeadersError as error:
        print(f"external headers manifest error: {error}", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"local include check failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("local include check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
