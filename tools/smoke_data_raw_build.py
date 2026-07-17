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
from build_web_assets import COMPRESS, SOURCE, TARGET, canonical_gzip, check_no_placeholders


def main() -> int:
    errors: list[str] = []

    if not SOURCE.is_dir():
        print(f" - нет каталога {SOURCE.name}/ - источник обязан существовать")
        return 1

    sources = {p.name for p in SOURCE.iterdir() if p.is_file()}
    built = {p.name for p in TARGET.iterdir() if p.is_file()}

    # Ожидаемый состав сборки: сжимаемые уезжают только как .gz, остальное - как есть.
    expected = {f"{n}.gz" if n in COMPRESS else n for n in sources}
    for extra in sorted(built - expected):
        if extra in COMPRESS:
            continue  # про протёкшее сырьё скажет проверка ниже, и конкретнее
        errors.append(f"data/{extra}: в сборке есть, а build_web_assets.py такого не делает")
    for missing in sorted(expected - built):
        errors.append(f"data/{missing}: источник есть, а в сборке нет - забыли пересобрать?")

    for name in sorted(sources):
        source = (SOURCE / name).read_bytes()
        if name in COMPRESS:
            error = check_no_placeholders(name, source)
            if error:
                errors.append(error)
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
