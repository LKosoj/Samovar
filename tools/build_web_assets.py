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

Языки: data/ - русский (исходный), data_i18n/ - те же текстовые файлы для каждого
языка из i18n/web/*.json с суффиксом языка в имени (index.en.htm.gz). Перевод
подставляется после разворачивания include и ДО сжатия, см. tools/web_i18n.py.
`--image <lang> --out <dir>` собирает полный образ ФС для языка, `--missing <lang>`
печатает заготовку словаря из ещё не переведённых сегментов.
"""
import argparse
import json
import re
import shutil
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_i18n
from smoke_u03_contrast import canonical_gzip

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data_raw"
TARGET = ROOT / "data"
I18N_TARGET = ROOT / "data_i18n"
DICTIONARIES_DIR = ROOT / "i18n" / "web"
PARTIALS_DIR = SOURCE / "partials"

# Файлы, которые уезжают на устройство только сжатыми. Шаблонов в них нет и быть
# не должно - см. check_no_placeholders().
COMPRESS = (
    "app.js", "chart.js", "edit.htm", "i2cstepper.htm", "brewxml.htm", "style.css",
    "index.htm", "beer.htm", "cheese.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "chart.htm", "program.htm", "cheese-recipes.htm", "calibrate.htm", "calibrate_ph.htm",
)

PLACEHOLDER = re.compile(r"%[A-Za-z_][A-Za-z0-9_.]*%")
INCLUDE_RE = re.compile(rb"<!--#include\s+([A-Za-z0-9_.-]+)\s*-->")
# Метка против устаревшего app.js в кэше браузера: в data_raw стоит "app.js?v=build",
# при сборке туда подставляется версия из version.txt - вручную поднимать не нужно.
APP_JS_VERSION_RE = re.compile(rb"app\.js\?v=[\w.\-]+")


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


def stamp_app_version(name: str, data: bytes, version: bytes) -> bytes:
    """Подставляет версию из version.txt в метку app.js?v= страниц .htm."""
    version = version.strip()
    if not version or not name.endswith(".htm"):
        return data
    return APP_JS_VERSION_RE.sub(b"app.js?v=" + version, data)


def check_no_unresolved_includes(name: str, data: bytes) -> str | None:
    if INCLUDE_RE.search(data):
        return f"{name}: остался нерезолвленный <!--#include--> после сборки"
    return None


ERROR_LIMIT = 200


def load_sources() -> tuple[dict[str, bytes], list[str]]:
    """Файлы data_raw/ после разворачивания include, в порядке имён."""
    errors: list[str] = []
    sources: dict[str, bytes] = {}
    for source in sorted(SOURCE.iterdir()):
        if not source.is_file():
            continue
        data = source.read_bytes()
        try:
            data = resolve_includes(source.name, data, partials_dir=PARTIALS_DIR)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        error = check_no_unresolved_includes(source.name, data)
        if error:
            errors.append(error)
            continue
        try:
            web_i18n.file_kind(source.name)
        except web_i18n.I18nError as exc:
            errors.append(str(exc))
            continue
        sources[source.name] = data
    version = sources.get("version.txt", b"")
    for name, data in sources.items():
        sources[name] = stamp_app_version(name, data, version)
    missing = sorted(set(COMPRESS) - {p.name for p in SOURCE.iterdir()})
    if missing:
        errors.append(f"в data_raw/ нет файлов из COMPRESS: {', '.join(missing)}")
    return sources, errors


def render(name: str, data: bytes, lang: str | None = None) -> tuple[str, bytes]:
    """Имя и содержимое файла в образе. lang - суффикс языка для data_i18n/."""
    out_name = web_i18n.i18n_name(name, lang) if lang else name
    if name in COMPRESS:
        return f"{out_name}.gz", canonical_gzip(data)
    return out_name, data


def placeholder_errors(files: dict[str, bytes], prefix: str = "") -> list[str]:
    errors = []
    for name, data in files.items():
        if name == "setup.htm":
            continue
        error = check_no_placeholders(name, data)
        if error:
            errors.append(prefix + error)
    return errors


def load_dictionaries(languages: list[str]) -> tuple[dict, list[str]]:
    dictionaries, errors = {}, []
    for lang in languages:
        try:
            dictionaries[lang] = web_i18n.load_dictionary(DICTIONARIES_DIR / f"{lang}.json")
        except web_i18n.I18nError as exc:
            errors.append(str(exc))
    return dictionaries, errors


def translation_errors(lang: str, result: web_i18n.Translation) -> list[str]:
    errors = [f"[{lang}] {error}" for error in result.errors]
    seen = set()
    for name, line, segment in result.missing:
        if (name, segment) in seen:
            continue
        seen.add((name, segment))
        errors.append(f"[{lang}] {name}:{line}: нет перевода «{segment}»")
    return errors


def translated_files(sources: dict[str, bytes], dictionary: web_i18n.Dictionary):
    """(Translation, {имя: bytes}) - переведённые файлы с проверкой плейсхолдеров."""
    result = web_i18n.translate_sources(sources, dictionary)
    encoded = {name: text.encode("utf-8") for name, text in result.files.items()}
    result.errors.extend(placeholder_errors(encoded))
    return result, encoded


def write_files(target: Path, files: dict[str, bytes], file_mode: int) -> None:
    for name, data in files.items():
        output = target / name
        output.write_bytes(data)
        output.chmod(file_mode)


def make_staging(target: Path, mode: int | None) -> tuple[Path, int]:
    staging = target.with_name(target.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    if mode is not None:
        staging.chmod(mode)
    else:
        mode = stat.S_IMODE(staging.stat().st_mode)
    return staging, mode


def report_errors(title: str, errors: list[str], hint: bool) -> None:
    print(title)
    for error in errors[:ERROR_LIMIT]:
        print(f" - {error}")
    if len(errors) > ERROR_LIMIT:
        print(f" ... и ещё {len(errors) - ERROR_LIMIT}")
    if hint:
        print("полный список недостающих сегментов: build_web_assets.py --missing <язык>")


def version_marker(version: bytes, lang: str) -> bytes:
    """Содержимое version.txt в образе, как пишет прошивка (web_version_marker + "\\n").

    ru - файл как есть. Иначе "<версия>:<код>": без кода язык образа и ожидаемый
    маркер расходятся, и устройство сразу перекачивает интерфейс целиком. Версию
    нормализуем так же, как normalize_web_if_version_string: обрезка пробелов и \\r.
    """
    if lang == "ru":
        return version
    text = version.decode("utf-8").replace("\r", "").strip(" \t\n\r\f\v")
    return f"{text}:{lang}\n".encode("utf-8")


def build_image(sources, lang: str, dictionary, errors: list[str]) -> dict[str, bytes]:
    """Полный образ ФС для языка: обычные имена и бинарные общие, version.txt с маркером языка."""
    files: dict[str, bytes] = {}
    if lang != "ru" and "version.txt" not in sources:
        errors.append("в data_raw/ нет version.txt: образу не из чего собрать маркер версии")
    if dictionary is None:
        texts = {n: d for n, d in sources.items() if web_i18n.file_kind(n) not in ("binary", "untranslated")}
        errors.extend(placeholder_errors(texts))
        translated = texts
    else:
        result, translated = translated_files(sources, dictionary)
        errors.extend(translation_errors(lang, result))
    for name, data in sources.items():
        name_out, content = render(name, translated.get(name, data))
        if name == "version.txt":
            content = version_marker(content, lang)
        files[name_out] = content
    return files


def build_default() -> int:
    directory_mode = stat.S_IMODE(TARGET.stat().st_mode) if TARGET.is_dir() else None
    i18n_mode = stat.S_IMODE(I18N_TARGET.stat().st_mode) if I18N_TARGET.is_dir() else None

    sources, errors = load_sources()
    try:
        languages = web_i18n.discover_languages(DICTIONARIES_DIR)
    except web_i18n.I18nError as exc:
        languages = []
        errors.append(str(exc))
    dictionaries, dictionary_errors = load_dictionaries(languages)
    errors.extend(dictionary_errors)

    ru_files: dict[str, bytes] = {}
    i18n_files: dict[str, dict[str, bytes]] = {}
    if not errors:
        errors.extend(placeholder_errors(sources))
    if not errors:
        for name, data in sources.items():
            out_name, content = render(name, data)
            ru_files[out_name] = content
        for lang, dictionary in dictionaries.items():
            result, translated = translated_files(sources, dictionary)
            errors.extend(translation_errors(lang, result))
            if not errors:
                i18n_files[lang] = dict(
                    render(name, translated[name], lang) for name in translated
                )
    if errors:
        report_errors("сборка data/ не выполнена:", errors, hint=bool(dictionaries))
        return 1

    # Любая ошибка выше - до этой точки: цели не тронуты, staging ещё не создан.
    # Исключение при записи тоже не оставляет ни staging, ни частичных целей.
    staging = i18n_staging = None
    try:
        staging, directory_mode = make_staging(TARGET, directory_mode)
        write_files(staging, ru_files, directory_mode & 0o666)
        if i18n_files:
            i18n_staging, i18n_mode = make_staging(
                I18N_TARGET, i18n_mode if i18n_mode is not None else directory_mode
            )
            for files in i18n_files.values():
                write_files(i18n_staging, files, i18n_mode & 0o666)

        shutil.rmtree(TARGET, ignore_errors=True)
        staging.rename(TARGET)
        shutil.rmtree(I18N_TARGET, ignore_errors=True)
        if i18n_staging is not None:
            i18n_staging.rename(I18N_TARGET)
    finally:
        for leftover in (staging, i18n_staging):
            if leftover is not None:
                shutil.rmtree(leftover, ignore_errors=True)

    files = sorted(p for p in TARGET.rglob("*") if p.is_file())
    total = sum(len(p.read_bytes()) for p in files)
    print(f"data/ собрана из data_raw/: {len(files)} файлов, {total} байт")
    if i18n_files:
        count = sum(len(f) for f in i18n_files.values())
        print(f"data_i18n/: языки {', '.join(i18n_files)}, {count} файлов")
    return 0


def check_image_out(out: Path) -> str | None:
    out = out.resolve()
    root = ROOT.resolve()
    if out == root or root in out.parents or out in root.parents:
        return f"--out {out}: нельзя собирать образ внутри проекта {root}, поверх него или его родителя"
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        return f"--out {out}: каталог уже существует и не пуст, образ в него не пишется (укажите новый или пустой каталог)"
    if out.with_name(out.name + ".tmp").exists():
        return f"--out {out}: рядом лежит {out.name}.tmp, его не удаляю (уберите его сами или укажите другой каталог)"
    return None


def build_image_command(lang: str, out: Path) -> int:
    problem = check_image_out(out)
    if problem:
        print(problem)
        return 1
    sources, errors = load_sources()
    dictionary = None
    if lang != "ru":
        path = DICTIONARIES_DIR / f"{lang}.json"
        if not path.is_file():
            errors.append(f"нет словаря для языка {lang}: ожидался {path}")
        else:
            try:
                dictionary = web_i18n.load_dictionary(path)
            except web_i18n.I18nError as exc:
                errors.append(str(exc))
    files: dict[str, bytes] = {}
    if not errors:
        files = build_image(sources, lang, dictionary, errors)
    if errors:
        report_errors(f"образ {lang} не собран:", errors, hint=dictionary is not None)
        return 1
    out = out.resolve()
    problem = check_image_out(out)  # повторно: за время сборки каталог мог измениться
    if problem:
        print(problem)
        return 1
    staging = None
    try:
        staging, mode = make_staging(out, None)
        write_files(staging, files, mode & 0o666)
        if out.is_dir():
            out.rmdir()  # только пустой: непустой отвергнут в check_image_out
        staging.rename(out)
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    print(f"образ {lang} собран в {out}: {len(files)} файлов")
    return 0


def missing_command(lang: str) -> int:
    if lang == "ru" or not web_i18n.LANG_RE.fullmatch(lang):
        print(f"{lang}: нужен код неисходного языка из 2-3 строчных латинских букв")
        return 1
    sources, errors = load_sources()
    path = DICTIONARIES_DIR / f"{lang}.json"
    if path.is_file():
        try:
            dictionary = web_i18n.load_dictionary(path)
        except web_i18n.I18nError as exc:
            print(exc, file=sys.stderr)
            return 1
    else:
        dictionary = web_i18n.Dictionary(lang, "", {}, {})
    result = web_i18n.translate_sources(sources, dictionary, strict=False)
    errors.extend(result.errors)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    segments = dict.fromkeys(segment for _, _, segment in result.missing)
    print(json.dumps({"segments": {s: "" for s in segments}}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сборка data/ и data_i18n/ из data_raw/")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--image", metavar="LANG", help="полный образ ФС для языка (нужен --out)")
    group.add_argument("--missing", metavar="LANG", help="заготовка словаря из непереведённых сегментов")
    parser.add_argument("--out", type=Path, help="каталог для --image")
    args = parser.parse_args(argv)
    if bool(args.image) != bool(args.out):
        parser.error("--image и --out нужны вместе")

    if not SOURCE.is_dir():
        print(f"нет каталога {SOURCE}")
        return 1
    if args.image:
        return build_image_command(args.image, args.out)
    if args.missing:
        return missing_command(args.missing)
    return build_default()


if __name__ == "__main__":
    sys.exit(main())
