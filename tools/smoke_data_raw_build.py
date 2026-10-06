#!/usr/bin/env python3
"""data/ обязана быть ровно тем, что build_web_assets.py делает из data_raw/.

Правка сырого файла без пересборки - самый тихий способ обмануть всех: тесты читают
источник и зеленеют, а на устройство уезжает старый образ. Тест пинит СОГЛАСИЕ
источника со сборкой, а не конкретные байты: список файлов и содержимое можно менять
свободно, нельзя только разъехаться.

Отдельно проверяем, что сжатое не обзавелось шаблонами: gzip-ответ обнуляет
шаблонизатор молча (WebResponses.cpp), поэтому %ПЛЕЙСХОЛДЕР% в сжатом файле - это
страница, которая приедет с неподставленными значениями и без ошибки.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_i18n
from build_web_assets import (
    COMPRESS,
    DICTIONARIES_DIR,
    I18N_TARGET,
    SOURCE,
    TARGET,
    canonical_gzip,
    check_no_placeholders,
    render,
    resolve_includes,
    stamp_app_version,
)

GZIP_PAGES = (
    "index.htm", "beer.htm", "cheese.htm", "distiller.htm", "bk.htm",
    "nbk.htm", "chart.htm", "program.htm", "cheese-recipes.htm", "calibrate.htm",
    "calibrate_ph.htm",
)


def check_i18n_build(sources: dict[str, bytes], errors: list[str]) -> None:
    """data_i18n/ обязана быть ровно тем, что сборка делает из data_raw/ и словарей."""
    languages = web_i18n.discover_languages(DICTIONARIES_DIR)
    if not languages:
        if I18N_TARGET.exists():
            errors.append("data_i18n/: словарей нет, а каталог есть - его быть не должно")
        return
    if not I18N_TARGET.is_dir():
        errors.append("data_i18n/: словари есть, а каталога нет - нужен прогон tools/build_web_assets.py")
        return
    built = {p.name for p in I18N_TARGET.iterdir() if p.is_file()}
    expected: dict[str, tuple[str, bytes]] = {}
    for lang in languages:
        dictionary = web_i18n.load_dictionary(DICTIONARIES_DIR / f"{lang}.json")
        result = web_i18n.translate_sources(sources, dictionary)
        if result.errors or result.missing:
            errors.append(f"data_i18n/{lang}: перевод data_raw/ не собирается словарём {lang}.json")
            continue
        for name, text in result.files.items():
            out_name, content = render(name, text.encode("utf-8"), lang)
            expected[out_name] = (name, content)
    for extra in sorted(built - set(expected)):
        errors.append(f"data_i18n/{extra}: в сборке есть, а сборщик такого не делает")
    for missing in sorted(set(expected) - built):
        errors.append(f"data_i18n/{missing}: должен быть в сборке - забыли пересобрать?")
    for out_name, (name, content) in sorted(expected.items()):
        path = I18N_TARGET / out_name
        if path.exists() and path.read_bytes() != content:
            errors.append(
                f"data_i18n/{out_name} разъехался с data_raw/{name} и словарём - "
                "нужен прогон tools/build_web_assets.py"
            )


def main() -> int:
    errors: list[str] = []

    if not SOURCE.is_dir():
        print(f" - нет каталога {SOURCE.name}/ - источник обязан существовать")
        return 1

    sources = {p.name for p in SOURCE.iterdir() if p.is_file()}
    version = (SOURCE / "version.txt").read_bytes() if "version.txt" in sources else b""
    built = {p.name for p in TARGET.iterdir() if p.is_file()}

    for name in GZIP_PAGES:
        if name not in COMPRESS:
            errors.append(f"data_raw/{name}: рабочая страница не добавлена в COMPRESS")
        if (TARGET / name).exists():
            errors.append(f"data/{name}: рабочая страница должна уезжать только как .gz")
        if not (TARGET / f"{name}.gz").exists():
            errors.append(f"data/{name}.gz: нет сжатой рабочей страницы")

    # Ожидаемый состав сборки: сжимаемые уезжают только как .gz, остальное - как есть.
    expected = {f"{n}.gz" if n in COMPRESS else n for n in sources}
    for extra in sorted(built - expected):
        if extra in COMPRESS:
            continue  # про протёкшее сырьё скажет проверка ниже, и конкретнее
        errors.append(f"data/{extra}: в сборке есть, а build_web_assets.py такого не делает")
    for missing in sorted(expected - built):
        errors.append(f"data/{missing}: источник есть, а в сборке нет - забыли пересобрать?")

    for name in sorted(sources):
        try:
            source = stamp_app_version(name, resolve_includes(name, (SOURCE / name).read_bytes()), version)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if name != "setup.htm":
            error = check_no_placeholders(name, source)
            if error:
                errors.append(error)
        if name in COMPRESS:
            gz = TARGET / f"{name}.gz"
            if gz.exists() and gz.read_bytes() != canonical_gzip(source):
                errors.append(
                    f"data/{name}.gz разъехался с data_raw/{name} - "
                    "нужен прогон tools/build_web_assets.py"
                )
            if (TARGET / name).exists():
                errors.append(
                    f"data/{name}: сырой файл не должен уезжать на устройство, "
                    "он занимает место рядом со своим .gz"
                )
        else:
            copied = TARGET / name
            if copied.exists() and copied.read_bytes() != source:
                errors.append(f"data/{name} разъехался с data_raw/{name}")

    resolved = {}
    for name in sorted(sources):
        try:
            resolved[name] = stamp_app_version(name, resolve_includes(name, (SOURCE / name).read_bytes()), version)
        except ValueError:
            pass  # про сломанный include уже сказано выше
    check_i18n_build(resolved, errors)

    if errors:
        print("data/ не соответствует data_raw/:")
        for error in errors:
            print(f" - {error}")
        return 1
    print(f"data_raw -> data build smoke passed: {len(sources)} источников, "
          f"{len(COMPRESS)} сжатых")
    return 0


if __name__ == "__main__":
    sys.exit(main())
