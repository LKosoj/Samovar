#!/usr/bin/env python3
"""Сборка data/ из data_raw/.

data_raw/ - источник: файлы в том виде, в каком их правит человек.
data/ - образ файловой системы устройства: то, что реально уезжает в LittleFS.

Бесшаблонные файлы уезжают только в сжатом виде: сырых версий в data/ нет,
их место занимает .gz. Экономия около 105 КБ SPIFFS. Отдавать их умеет и
serveStatic (AsyncStaticWebHandler._tryGzipFirst), и AsyncFileResponse - он сам
подставит .gz, если сырого файла на диске не окажется.

Почему не сжимаем всё: AsyncFileResponse обнуляет шаблонизатор для gzip-ответа
(WebResponses.cpp, `_callback = nullptr`). Страница со сжатыми %ПЛЕЙСХОЛДЕРАМИ%
приедет с неподставленными значениями и БЕЗ ошибки. Отсюда COMPRESS - явный
список имён, а не маска по расширению, плюс проверка на плейсхолдеры перед
сжатием: список смертен, проверка - нет.
"""
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_u03_contrast import canonical_gzip

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data_raw"
TARGET = ROOT / "data"
PARTIALS_DIR = SOURCE / "partials"
# Замороженный старый интерфейс (страницы режимов + их style.css). Живёт в подкаталоге,
# у него свои partials; на устройство уезжает в /legacy/ целиком сжатым - шаблонов там нет.
LEGACY_SOURCE = SOURCE / "legacy"
LEGACY_PARTIALS_DIR = LEGACY_SOURCE / "partials"

# Файлы, которые уезжают на устройство только сжатыми. Шаблонов в них нет и быть
# не должно - см. check_no_placeholders().
COMPRESS = (
    "app.js", "chart.js", "edit.htm", "i2cstepper.htm", "brewxml.htm", "style.css",
    "index.htm", "beer.htm", "cheese.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "chart.htm", "program.htm", "calibrate.htm", "calibrate_ph.htm",
)

PLACEHOLDER = re.compile(r"%[A-Za-z_][A-Za-z0-9_.]*%")
INCLUDE_RE = re.compile(rb"<!--#include\s+([A-Za-z0-9_.-]+)\s*-->")


def check_no_placeholders(name: str, data: bytes) -> str | None:
    found = sorted(set(PLACEHOLDER.findall(data.decode("utf-8", errors="ignore"))))
    if not found:
        return None
    return (
        f"{name}: сжатие сломает шаблонизатор, найдены плейсхолдеры "
        f"{', '.join(found)} - файл нельзя держать в COMPRESS"
    )


def resolve_includes(
    name: str, data: bytes, seen: tuple[str, ...] = (), partials_dir: Path = PARTIALS_DIR
) -> bytes:
    """Разворачивает <!--#include partial.htm--> рекурсивно, до подстановки."""

    def repl(match: re.Match) -> bytes:
        partial_name = match.group(1).decode("ascii")
        if partial_name in seen:
            raise ValueError(f"{name}: циклический include {' -> '.join(seen)} -> {partial_name}")
        partial_path = partials_dir / partial_name
        if not partial_path.is_file():
            raise ValueError(f"{name}: partial не найден: {partials_dir.name}/{partial_name}")
        return resolve_includes(
            partial_name, partial_path.read_bytes(), seen + (partial_name,), partials_dir
        )

    return INCLUDE_RE.sub(repl, data)


def check_no_unresolved_includes(name: str, data: bytes) -> str | None:
    if INCLUDE_RE.search(data):
        return f"{name}: остался нерезолвленный <!--#include--> после сборки"
    return None


def build(target: Path) -> list[str]:
    errors: list[str] = []
    for source in sorted(SOURCE.iterdir()):
        if not source.is_file():
            continue
        data = source.read_bytes()
        try:
            data = resolve_includes(source.name, data)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        error = check_no_unresolved_includes(source.name, data)
        if error:
            errors.append(error)
            continue
        if source.name != "setup.htm":
            error = check_no_placeholders(source.name, data)
            if error:
                errors.append(error)
                continue
        if source.name in COMPRESS:
            (target / f"{source.name}.gz").write_bytes(canonical_gzip(data))
        else:
            (target / source.name).write_bytes(data)
    missing = sorted(set(COMPRESS) - {p.name for p in SOURCE.iterdir()})
    if missing:
        errors.append(f"в data_raw/ нет файлов из COMPRESS: {', '.join(missing)}")
    errors.extend(build_legacy(target))
    return errors


def build_legacy(target: Path) -> list[str]:
    """data_raw/legacy/ -> data/legacy/: всё сжатое, includes из legacy/partials."""
    errors: list[str] = []
    if not LEGACY_SOURCE.is_dir():
        return errors
    legacy_target = target / "legacy"
    legacy_target.mkdir(parents=True, exist_ok=True)
    for source in sorted(LEGACY_SOURCE.iterdir()):
        if not source.is_file():
            continue
        name = f"legacy/{source.name}"
        try:
            data = resolve_includes(name, source.read_bytes(), partials_dir=LEGACY_PARTIALS_DIR)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        error = check_no_unresolved_includes(name, data) or check_no_placeholders(name, data)
        if error:
            errors.append(error)
            continue
        (legacy_target / f"{source.name}.gz").write_bytes(canonical_gzip(data))
    return errors


def main() -> int:
    if not SOURCE.is_dir():
        print(f"нет каталога {SOURCE}")
        return 1

    staging = TARGET.with_name("data.tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    errors = build(staging)
    if errors:
        shutil.rmtree(staging, ignore_errors=True)
        print("сборка data/ не выполнена:")
        for error in errors:
            print(f" - {error}")
        return 1

    shutil.rmtree(TARGET, ignore_errors=True)
    staging.rename(TARGET)

    files = sorted(p for p in TARGET.rglob("*") if p.is_file())
    total = sum(len(p.read_bytes()) for p in files)
    print(f"data/ собрана из data_raw/: {len(files)} файлов, {total} байт")
    return 0


if __name__ == "__main__":
    sys.exit(main())
