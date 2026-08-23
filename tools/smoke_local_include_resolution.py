#!/usr/bin/env python3
"""Заголовок, которого нет в репозитории, должен ловиться статической проверкой.

Глубокий анализ глушит категорию missingInclude (заголовки платформы лежат вне
репозитория, путей -I у джобы нет), поэтому полезную половину проверяет
tools/check_local_includes.py. Этот тест следит, чтобы она реально работала и
была подключена к анализу, а не просто лежала в каталоге.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_cppcheck_baseline
import run_cppcheck
from check_local_includes import ExternalHeadersError, check_includes, load_external_headers

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = {"driver/uart.h": "ESP-IDF"}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text, encoding="utf-8")


def main() -> int:
    errors: list[str] = []

    # 1. Настоящее дерево прошивки разрешимо целиком.
    problems = check_includes(ROOT)
    if problems:
        fail(errors, "рабочее дерево должно быть чистым, а найдено: " + "; ".join(problems))

    # 2. Манифест внешних заголовков валиден и отсортирован.
    try:
        headers = load_external_headers()
    except ExternalHeadersError as error:
        headers = {}
        fail(errors, f"tools/external_headers.json не читается: {error}")
    if headers and list(headers) != sorted(headers):
        fail(errors, "внешние заголовки должны быть отсортированы")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # 3. Битый локальный include - находка. Ровно этот случай терялся,
        #    пока missingInclude был просто заглушён.
        write(root, "app.ino", '#include "there_is_no_such_header.h"\nvoid setup() {}\n')
        found = check_includes(root, EXTERNAL)
        if not any("there_is_no_such_header.h" in item for item in found):
            fail(errors, "несуществующий локальный заголовок обязан быть находкой")
        if not any("app.ino:1:" in item for item in found):
            fail(errors, "находка должна указывать файл и строку")

        # 4. Существующий сосед и заявленный внешний - не находки.
        write(root, "app.ino", '#include "helper.h"\n#include "driver/uart.h"\n')
        write(root, "helper.h", "#pragma once\n")
        if check_includes(root, EXTERNAL):
            fail(errors, "разрешимый сосед и заявленный внешний заголовок не должны быть находками")

        # 5. Системные include в угловых скобках проверку не касаются.
        write(root, "app.ino", "#include <Arduino.h>\n#include <math.h>\n")
        if check_includes(root, EXTERNAL):
            fail(errors, "угловые скобки - зона компилятора, а не этой проверки")

        # 6. Закомментированный include не должен требовать файла:
        #    иначе проверка начнёт врать на закомментированном коде.
        write(root, "app.ino",
              '// #include "old_header.h"\n'
              '/* #include "another.h" */\n'
              '/*\n#include "block_commented.h"\n*/\n')
        commented = check_includes(root, EXTERNAL)
        if commented:
            fail(errors, "закомментированные include не должны считаться находками: " + "; ".join(commented))

        # 7. Протухший список внешних заголовков: файл появился в репозитории,
        #    а запись осталась - такой include молча перестал бы проверяться.
        write(root, "app.ino", '#include "driver/uart.h"\n')
        (root / "driver").mkdir()
        (root / "driver" / "uart.h").write_text("#pragma once\n", encoding="utf-8")
        stale = check_includes(root, EXTERNAL)
        if not any("больше не внешний" in item for item in stale):
            fail(errors, "заявленный внешним заголовок, лежащий в репозитории, обязан быть находкой")

    # 8. Проверка подключена к глубокому анализу не на словах: гоняем сам
    #    run_cppcheck.main() на дереве с битым include и требуем отказ ДО запуска
    #    cppcheck. Проверка "в файле есть слово check_includes" таким не была бы:
    #    строка импорта осталась бы на месте и после отключения вызова.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "app.ino").write_text('#include "no_such_header.h"\n', encoding="utf-8")
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps({"inventory": ["app.ino"], "excluded": {}}), encoding="utf-8"
        )
        with (
            patch.object(run_cppcheck, "ROOT", root),
            patch.object(run_cppcheck, "MANIFEST_PATH", manifest_path),
            patch.object(run_cppcheck.subprocess, "run") as process,
            patch.object(sys, "argv", ["run_cppcheck.py", "--timeout", "10"]),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            returncode = run_cppcheck.main()
        if returncode != 1:
            fail(errors, f"анализ обязан отказать на неразрешимом include, а вернул {returncode}")
        if process.called:
            fail(errors, "cppcheck не должен запускаться, если include не разрешаются")
        if "no_such_header.h" not in stderr.getvalue():
            fail(errors, "отказ должен называть проблемный заголовок")

    # 9. Расширенный анализ (джоба static-analysis-force) собирает команду сам и
    #    run_cppcheck.main() не зовёт - значит он наследует заглушённый missingInclude
    #    и обязан звать замену самостоятельно. Слепое пятно теста иначе в точности
    #    повторило бы слепое пятно проверки.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "app.ino").write_text('#include "no_such_header.h"\n', encoding="utf-8")
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps({"inventory": ["app.ino"], "excluded": {}}), encoding="utf-8"
        )
        with (
            patch.object(check_cppcheck_baseline, "ROOT", root),
            patch.object(check_cppcheck_baseline, "MANIFEST_PATH", manifest_path),
            patch.object(check_cppcheck_baseline.cppcheck_tool.subprocess, "run") as process,
            patch.object(sys, "argv", ["check_cppcheck_baseline.py", "--timeout", "10"]),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            returncode = check_cppcheck_baseline.main()
        if returncode != 1:
            fail(errors, f"расширенный анализ обязан отказать на неразрешимом include, а вернул {returncode}")
        if process.called:
            fail(errors, "cppcheck --force не должен запускаться, если include не разрешаются")
        if "no_such_header.h" not in stderr.getvalue():
            fail(errors, "отказ расширенного анализа должен называть проблемный заголовок")

    source = (ROOT / "tools" / "run_cppcheck.py").read_text(encoding="utf-8")
    if "--suppress=missingInclude" in source and "check_local_includes" not in source:
        fail(errors, "глушить missingInclude можно только вместе со ссылкой на замену")

    # 10. Заявленные внешние заголовки действительно кем-то включаются:
    #    список не должен копить мусор.
    if headers:
        used: set[str] = set()
        for path in ROOT.iterdir():
            if path.is_file() and path.suffix in (".h", ".ino"):
                text = path.read_text(encoding="utf-8", errors="replace")
                used.update(name for name in headers if f'"{name}"' in text)
        unused = sorted(set(headers) - used)
        if unused:
            fail(errors, "внешние заголовки заявлены, но никем не включаются: " + ", ".join(unused))

    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    if errors:
        return 1
    print("local include resolution smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
