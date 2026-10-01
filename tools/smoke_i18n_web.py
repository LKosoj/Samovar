#!/usr/bin/env python3
"""Перевод веб-интерфейса при сборке: tools/web_i18n.py и режимы build_web_assets.py.

Синтетика во временном каталоге: сборщик получает подменённые SOURCE, TARGET,
I18N_TARGET, DICTIONARIES_DIR и COMPRESS, поэтому реальные data/ и data_raw/ не
трогаются. Каждый случай проверяется минимум на двух значениях (одной константой два
ожидания разом не удовлетворить), а ошибки сверяются по ТЕКСТУ.

Отдельно - реальные словари i18n/web/*.json: перевод data_raw/ собирается без
недостающих сегментов, лишних записей нет, набор языков совпадает с lang_*.h, а JS
(.js и <script>) исходного и переведённых текстов проходит `node --check`. Нет node -
падение, а не пропуск: без него синтаксис переведённого JS не проверяется вовсе.
"""
import contextlib
import gzip
import io
import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_web_assets as bwa
import web_i18n
from smoke_u03_contrast import canonical_gzip

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
# Запрещённые символы записаны здесь явно, а не берутся из модуля: иначе мутация модуля
# меняла бы и ожидание теста.
FORBIDDEN_CHARS = "<>\"'`{}\\\n\r"
EMPTY = web_i18n.Dictionary("xx", "Xx", {}, {})


def fail(message: str) -> None:
    errors.append(message)


def eq(label: str, got, want) -> None:
    if got != want:
        fail(f"{label}: ожидалось {want!r}, получено {got!r}")


def has(label: str, haystack: str, needle: str) -> None:
    if needle not in haystack:
        fail(f"{label}: в тексте нет {needle!r}; текст: {haystack[:300]!r}")


def lacks(label: str, haystack: str, needle: str) -> None:
    if needle in haystack:
        fail(f"{label}: в тексте не должно быть {needle!r}; текст: {haystack[:300]!r}")


def found(name: str, text: str) -> list:
    """Сегменты, которые сборка считает переводимыми (пустой словарь - все 'missing')."""
    result = web_i18n.translate_sources({name: text}, EMPTY)
    return [segment for _, _, segment in result.missing]


def translate(name: str, text: str, segments: dict, replace: dict | None = None):
    dictionary = web_i18n.Dictionary("xx", "Xx", replace or {}, segments)
    return web_i18n.translate_sources({name: text}, dictionary)


# ---------------------------------------------------------------- сегменты

def check_segment_boundaries() -> None:
    for char in FORBIDDEN_CHARS:
        if char == "\r":
            continue  # \r в середине сегмента без \n не встречается; запрет \r - только в переводах
        for left, right in (("Привет", "мир"), ("Один", "Два")):
            eq(f"граница {char!r} {left}", found("a.txt", f"{left}{char}{right}"), [left, right])
    for text, want in (
        ("Привет, мир!", ["Привет, мир"]),
        ("(Тест)", ["Тест"]),
        ("Нагрев... готово.", ["Нагрев... готово"]),
        ("12 мин", ["мин"]),
        ("${x} мин", ["мин"]),
        ("${t} сек осталось", ["сек осталось"]),
        ("Вт&nbsp;час", ["Вт&nbsp;час"]),
        ("Вт&nbsp;", ["Вт"]),
        ("&nbsp;Кол", ["Кол"]),
        ("я", ["я"]),
        (" Я ", ["Я"]),
        ("Тревога|Предупреждение", ["Тревога|Предупреждение"]),
        ("x Да|Нет y", ["Да|Нет"]),
        ("ёж-Ёлка", ["ёж-Ёлка"]),
    ):
        eq(f"сегменты {text!r}", found("a.txt", text), want)
    eq("только латиница", found("a.txt", "Hello 12 %d"), [])


def check_exclusions() -> None:
    # CSS
    for text in ("/* Комментарий */ a{}", "a{} /* Другой\nмногострочный */"):
        eq(f"css комментарий {text!r}", found("a.css", text), [])
    eq("css не комментарий", found("a.css", 'a:after{content:"Да"}'), ["Да"])
    eq("css не комментарий 2", found("a.css", 'b:after{content:"Нет"} /* Ок */'), ["Нет"])
    eq("css граница зоны", found("a.css", "Пример/* c */мир"), ["Пример", "мир"])
    eq("css граница зоны 2", found("a.css", "Один/* c */Два"), ["Один", "Два"])
    # JS: исключается только комментарий с начала строки
    eq("js строка", found("a.js", "// Комментарий\nx()"), [])
    eq("js строка с отступом", found("a.js", "x();\n\t  // Другой\n"), [])
    eq("js блок", found("a.js", "/* Блок\nещё Строка */\nx()"), [])
    eq("js хвостовой //", found("a.js", "x(); // Хвост"), ["Хвост"])
    eq("js хвостовой // 2", found("a.js", "y = 1; // Ещё один"), ["Ещё один"])
    eq("js блок в середине", found("a.js", 'a = "Текст"; /* Блок */'), ["Текст", "Блок"])
    # HTML
    for text in ("<!-- Комментарий -->", "<p>x</p><!-- Два\nстроки -->"):
        eq(f"html комментарий {text!r}", found("a.htm", text), [])
    eq("html в комментарии script", found("a.htm", "<!-- <script> Комм </script> -->\n<p>Да</p>"), ["Да"])
    eq("html style", found("a.htm", "<style>/* Цвет */ a{}</style>"), [])
    eq("html style правило", found("a.htm", '<style>a:after{content:"Тут"}</style>'), ["Тут"])
    eq("html script //", found("a.htm", "<script>\n// Комм\nx();</script>"), [])
    eq("html script хвостовой", found("a.htm", "<script>\nx(); // Хвост\n</script>"), ["Хвост"])
    eq("html script SCRIPT", found("a.htm", "<SCRIPT >\n// Комм\n</SCRIPT>"), [])
    eq("html script module", found("a.htm", '<script type="module">\n// Комм\n</script>'), [])
    eq("html script json", found("a.htm", '<script type="application/json">{"a":"Привет"}</script>'), ["Привет"])
    eq("html script json 2", found("a.htm", "<script type='application/json'>\n// Заметка\n</script>"), ["Заметка"])
    eq("html script template", found("a.htm", '<script type="text/template">\n// Шаблон\n</script>'), ["Шаблон"])
    eq(
        "html <!-- внутри script",
        found("a.htm", '<script>\nvar s = "<!--";\nvar t = "Текст";\n</script>\n<p>Конец</p>'),
        ["Текст", "Конец"],
    )
    eq("html <!-- внутри script 2", found("a.htm", '<script>x="<!--"; y="Раз"</script>Два'), ["Раз", "Два"])
    eq("html граница", found("a.htm", "Привет<!-- x -->мир"), ["Привет", "мир"])
    eq("html атрибут", found("a.htm", '<input title="Подсказка">'), ["Подсказка"])
    # lua и txt: переводится всё
    eq("lua комментарий", found("a.lua", "-- Комментарий\nx = 1"), ["Комментарий"])
    eq("lua комментарий 2", found("a.lua", "x = 1 -- Хвост"), ["Хвост"])
    eq("txt комментарий //", found("a.txt", "// Строка"), ["Строка"])
    eq("txt комментарий /* */", found("a.txt", "/* Блок */"), ["Блок"])
    # незакрытые зоны - ошибка, а не молчаливый пропуск
    for name, text, what in (
        ("a.css", "a{} /* Незакрытый", "незакрытый CSS-комментарий"),
        ("a.css", "/* Раз */ b{} /* Два", "незакрытый CSS-комментарий"),
        ("a.js", "x();\n/* Незакрытый\nещё", "незакрытый блочный комментарий JS"),
        ("a.htm", "<p>Да</p><!-- Незакрытый", "незакрытый <!--"),
        ("a.htm", "<p>Да</p><script>x()", "незакрытый <!--, <script> или <style>"),
        ("a.htm", "<style>a{}", "незакрытый <!--, <script> или <style>"),
    ):
        result = web_i18n.translate_sources({name: text}, EMPTY)
        has(f"незакрытая зона {text!r}", "\n".join(result.errors), what)
        has(f"незакрытая зона {text!r} называет файл", "\n".join(result.errors), name)


def check_translation() -> None:
    result = translate("a.htm", '<p>Один</p>\n<!-- Комм -->\n<p>Два, три</p>', {"Один": "One", "Два, три": "Two, three"})
    eq("перевод", result.files["a.htm"], "<p>One</p>\n<!-- Комм -->\n<p>Two, three</p>")
    eq("перевод: нет ошибок", (result.errors, result.missing), ([], []))
    eq("used", result.used, {"Один", "Два, три"})
    result = translate("a.js", 'x = "Да"; // Хвост\n// Комм', {"Да": "Yes", "Хвост": "Tail"})
    eq("перевод js", result.files["a.js"], 'x = "Yes"; // Tail\n// Комм')
    # недостающие сегменты - с файлом и строкой
    result = translate("b.txt", "Один\nДва\nОдин\nТри", {"Один": "One"})
    eq("missing", result.missing, [("b.txt", 2, "Два"), ("b.txt", 4, "Три")])
    result = translate("c.htm", "<p>\n\n<b>Пять</b>\n<i>Шесть</i>", {})
    eq("missing 2", result.missing, [("c.htm", 3, "Пять"), ("c.htm", 4, "Шесть")])
    # кириллица вне А-Яа-яЁё (например, і) не переводится словарём - остаётся и ломает сборку
    result = translate("e.txt", "і", {"Прив": "x"})
    has("остаточная кириллица", "\n".join(result.errors), "осталась кириллица")
    has("остаточная кириллица: файл", "\n".join(result.errors), "e.txt:1")
    result = translate("e.txt", "\nї", {})
    has("остаточная кириллица 2", "\n".join(result.errors), "e.txt:2")
    # неизвестное расширение
    result = web_i18n.translate_sources({"a.xyz": "Да"}, EMPTY)
    has("неизвестное расширение", "\n".join(result.errors), "неизвестное расширение")
    result = web_i18n.translate_sources({"a.png": b"\x89PNG", "version.txt": "7.00\nДа"}, EMPTY)
    eq("бинарные и version.txt не переводятся", (result.files, result.missing, result.errors), ({}, [], []))


def check_replace() -> None:
    result = translate("a.htm", '<html lang="ru">Да', {"Да": "Yes"}, {'lang="ru"': 'lang="en"'})
    eq("replace", result.files["a.htm"], '<html lang="en">Yes')
    result = translate("a.js", "f('ru-RU'); g('ru-RU')", {}, {"ru-RU": "en-US"})
    eq("replace 2", (result.files["a.js"], result.replace_hits), ("f('en-US'); g('en-US')", {"ru-RU": 2}))
    # ни одного попадания - ошибка сборки
    for key in ("lang=\"ru\"", "toLocale"):
        result = translate("a.txt", "Да", {"Да": "Yes"}, {key: "x"})
        has(f"replace без попаданий {key}", "\n".join(result.errors), f"replace {key!r}: ни разу не нашлось")
    # попадания суммируются по всем файлам языка
    dictionary = web_i18n.Dictionary("xx", "Xx", {"@@": "##"}, {})
    result = web_i18n.translate_sources({"a.txt": "a@@", "b.txt": "b@@c@@"}, dictionary)
    eq("replace по файлам", (result.replace_hits, result.errors), ({"@@": 3}, []))
    # порядок: последовательно, по списку словаря
    result = translate("a.txt", "aabb", {}, {"aa": "b", "bb": "c"})
    eq("порядок replace", result.files["a.txt"], "cb")
    result = translate("a.txt", "xyz", {}, {"y": "z", "z": "q"})
    eq("порядок replace 2", result.files["a.txt"], "xqq")
    # replace идёт ДО поиска сегментов: ключ словаря - уже после замены
    result = translate("a.txt", "Привет 5 мир", {"Привет 7 мир": "Hello 7"}, {"5": "7"})
    eq("replace до сегментов", (result.files["a.txt"], result.missing), ("Hello 7", []))
    result = translate("a.txt", "Скорость 1 ед", {"Скорость 2 ед": "Speed 2"}, {"1": "2"})
    eq("replace до сегментов 2", (result.files["a.txt"], result.missing), ("Speed 2", []))


# ---------------------------------------------------------------- словари

def write_dictionary_text(directory: Path, lang: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{lang}.json"
    path.write_text(text, encoding="utf-8")
    return path


def load_error(directory: Path, lang: str, text: str) -> str:
    path = write_dictionary_text(directory, lang, text)
    try:
        web_i18n.load_dictionary(path)
    except web_i18n.I18nError as exc:
        return str(exc)
    return ""


def dictionary_json(segments=None, replace=None, name="English") -> str:
    return json.dumps(
        {"language_name": name, "replace": replace or {}, "segments": segments or {}}, ensure_ascii=False
    )


def check_dictionary_errors() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        d = Path(temporary)
        ok = write_dictionary_text(
            d, "en", dictionary_json({"Темп %d %s сек": "Temp %d %s sec", "Нагрев %POWER% Вт": "Heat %POWER% W", "Доля в % от нормы": "Share in % of norm"}, {"ru-RU": "en-US"})
        )
        loaded = web_i18n.load_dictionary(ok)
        eq("словарь загружается", (loaded.lang, loaded.language_name, loaded.replace), ("en", "English", {"ru-RU": "en-US"}))
        eq("словарь: сегменты", sorted(loaded.segments), ["Доля в % от нормы", "Нагрев %POWER% Вт", "Темп %d %s сек"])
        eq("язык de", web_i18n.load_dictionary(write_dictionary_text(d, "de", dictionary_json({"Да": "Ja"}))).lang, "de")

        cases = [
            ("en", '{"language_name":"E","replace":{},"segments":{"Да":"Yes","Да":"No"}}', "повторяющийся ключ JSON"),
            ("en", '{"language_name":"E","replace":{"a":"b","a":"c"},"segments":{}}', "повторяющийся ключ JSON"),
            ("en", '{"language_name":"E","replace":{}}', "на верхнем уровне должны быть ровно"),
            ("en", '{"language_name":"E","replace":{},"segments":{},"extra":1}', "на верхнем уровне должны быть ровно"),
            ("en", "[]", "на верхнем уровне должны быть ровно"),
            ("en", "{", "не читается"),
            ("en", dictionary_json(name=""), "language_name должен быть непустой строкой"),
            ("en", '{"language_name":5,"replace":{},"segments":{}}', "language_name должен быть непустой строкой"),
            ("en", '{"language_name":"E","replace":[],"segments":{}}', "replace должен быть объектом"),
            ("en", '{"language_name":"E","replace":{},"segments":[]}', "segments должен быть объектом"),
            ("en", dictionary_json({"Да": ""}), "значение должно быть непустой строкой"),
            ("en", dictionary_json({"Да": 5}), "значение должно быть непустой строкой"),
            ("en", dictionary_json({"Да": "Да!"}), "в значении осталась кириллица"),
            ("en", dictionary_json({"Нет": "Нет"}), "в значении осталась кириллица"),
            ("en", dictionary_json({" Да": "Yes"}), "ключ не является сегментом"),
            ("en", dictionary_json({"Да!": "Yes"}), "ключ не является сегментом"),
            ("en", dictionary_json({"Да\nНет": "Yes"}), "ключ не является сегментом"),
            ("en", dictionary_json({"Да": "Yes"}, {"": "x"}), "replace: пустой ключ"),
            ("en", dictionary_json({"Да": "Yes"}, {"ру": "x"}), "кириллица в ключе"),
            ("en", dictionary_json({"Да": "Yes"}, {"a": ""}), "значение должно быть непустой строкой"),
            ("en", dictionary_json({"Да": "Yes"}, {"a": "б"}), "в значении осталась кириллица"),
            ("en", dictionary_json({"Темп %d сек": "Temp sec"}), "не совпадают printf-спецификаторы"),
            ("en", dictionary_json({"Темп сек": "Temp %d sec"}), "не совпадают printf-спецификаторы"),
            ("en", dictionary_json({"Тест %s %d сек": "Test %d %s sec"}), "не совпадают printf-спецификаторы"),
            ("en", dictionary_json({"Тест %.1f сек": "Test %.2f sec"}), "не совпадают printf-спецификаторы"),
            ("en", dictionary_json({"Нагрев %POWER% Вт": "Heat %POW% W"}), "не совпадают плейсхолдеры"),
            ("en", dictionary_json({"Нагрев %POWER% Вт": "Heat W"}), "не совпадают плейсхолдеры"),
            ("en", dictionary_json({"Заряд 50% ок": "Charge 50 ok"}), "не совпадает число символов '%'"),
            ("en", dictionary_json({"Заряд ок": "Charge 50% ok"}), "не совпадает число символов '%'"),
            ("ru", dictionary_json(), "русский - исходный язык"),
            ("EN", dictionary_json(), "имя словаря должно быть кодом языка"),
            ("english", dictionary_json(), "имя словаря должно быть кодом языка"),
        ]
        for char in FORBIDDEN_CHARS:
            cases.append(("en", dictionary_json({"Да": f"a{char}b"}), "запрещённые символы"))
        for lang, text, want in cases:
            has(f"словарь {lang} {text[:70]!r}", load_error(d, lang, text), want)
        # replace правит код страниц: кавычки и прочие символы кода в значении допустимы.
        for value in ('lang="en"', "get('lang') === 'ru' ? 'ru' : 'en'"):
            eq(f"replace со значением {value!r}",
               load_error(d, "en", dictionary_json({"Да": "ok"}, {"key": value})), "")

        # каталог: коды языков
        for stem in ("EN", "english", "e", "en1"):
            sub = d / f"bad_{stem}"
            write_dictionary_text(sub, stem, dictionary_json())
            try:
                web_i18n.discover_languages(sub)
                fail(f"discover_languages принял {stem}.json")
            except web_i18n.I18nError as exc:
                has(f"discover {stem}", str(exc), "кодом языка")
        good = d / "good"
        write_dictionary_text(good, "fr", dictionary_json())
        write_dictionary_text(good, "deu", dictionary_json())
        (good / "notes.txt").write_text("не словарь", encoding="utf-8")
        eq("discover", web_i18n.discover_languages(good), ["deu", "fr"])
        eq("discover: нет каталога", web_i18n.discover_languages(d / "нет"), [])


def check_names() -> None:
    for name, lang, want in (
        ("index.htm", "en", "index.en.htm"),
        ("a.b.js", "en", "a.en.b.js"),
        ("program_bk.txt", "de", "program_bk.de.txt"),
        ("cheese-recipes.htm", "en", "cheese-recipes.en.htm"),
        ("x.min.css", "fr", "x.fr.min.css"),
    ):
        eq(f"i18n_name {name}", web_i18n.i18n_name(name, lang), want)
    for name in ("Makefile", "noext"):
        try:
            web_i18n.i18n_name(name, "en")
            fail(f"i18n_name({name}) должен падать")
        except ValueError as exc:
            has(f"i18n_name {name}", str(exc), "нет точки")
    for name, want in (
        ("a.htm", "html"), ("a.js", "js"), ("a.css", "css"), ("a.lua", "plain"), ("a.txt", "plain"),
        ("a.png", "binary"), ("a.gif", "binary"), ("a.mp3", "binary"), ("a.ico", "binary"),
        ("version.txt", "untranslated"),
    ):
        eq(f"file_kind {name}", web_i18n.file_kind(name), want)
    for name in ("a.xyz", "a.json", "noext"):
        try:
            web_i18n.file_kind(name)
            fail(f"file_kind({name}) должен падать")
        except web_i18n.I18nError as exc:
            has(f"file_kind {name}", str(exc), "неизвестное расширение")
    # таблица: два языка, точное равенство ожидаемому множеству (суффикс перед ПЕРВОЙ точкой)
    names = ("index.htm", "a.b.js", "program_bk.txt", "cheese-recipes.htm", "x.min.css")
    want = {
        "en": {"index.en.htm", "a.en.b.js", "program_bk.en.txt", "cheese-recipes.en.htm", "x.en.min.css"},
        "de": {"index.de.htm", "a.de.b.js", "program_bk.de.txt", "cheese-recipes.de.htm", "x.de.min.css"},
    }
    for lang, expected in want.items():
        eq(f"i18n_name таблица {lang}", {web_i18n.i18n_name(n, lang) for n in names}, expected)
    # реальные файлы проекта: точные ожидаемые имена
    real = {p.name for p in bwa.SOURCE.iterdir() if p.is_file()}
    for name, expected in (("program_bk.txt", "program_bk.en.txt"), ("index.htm", "index.en.htm"),
                           ("style.css", "style.en.css"), ("cheese-recipes.htm", "cheese-recipes.en.htm")):
        if name in real:
            eq(f"реальное имя {name}", web_i18n.i18n_name(name, "en"), expected)


# ---------------------------------------------------------------- сборщик

class Env:
    """Временная раскладка с подменой путей сборщика."""

    NAMES = ("ROOT", "SOURCE", "PARTIALS_DIR", "TARGET", "I18N_TARGET", "DICTIONARIES_DIR", "COMPRESS")

    def __init__(self, compress=("page.htm",)):
        self.compress = compress

    def __enter__(self):
        self.saved = {n: getattr(bwa, n) for n in self.NAMES}
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "proj"
        self.source = self.root / "data_raw"
        self.partials = self.source / "partials"
        self.partials.mkdir(parents=True)
        self.target = self.root / "data"
        self.i18n = self.root / "data_i18n"
        self.dicts = self.root / "i18n" / "web"
        for name, value in (
            ("ROOT", self.root), ("SOURCE", self.source), ("PARTIALS_DIR", self.partials),
            ("TARGET", self.target), ("I18N_TARGET", self.i18n), ("DICTIONARIES_DIR", self.dicts),
            ("COMPRESS", self.compress),
        ):
            setattr(bwa, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(bwa, name, value)
        self.temporary.cleanup()

    def put(self, name: str, content, partial: bool = False) -> None:
        path = (self.partials if partial else self.source) / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))

    def dictionary(self, lang: str, segments: dict, replace=None) -> None:
        write_dictionary_text(self.dicts, lang, dictionary_json(segments, replace, name=lang.upper()))

    def run(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = bwa.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def snapshot(self, directory: Path):
        if not directory.exists():
            return None
        return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file()}


def basic_env(env: Env) -> None:
    env.put("page.htm", "<p>Один</p>\n<!--#include part.htm-->\n<p>Три</p>")
    env.put("part.htm", "<b>Два</b>\n<i>Новый</i>", partial=True)
    env.put("app.js", "x = 'Текст';\n// Комментарий\n")
    env.put("notes.txt", "Заметка")
    env.put("logo.png", b"\x89PNG\x00\xd0\x96")
    env.put("version.txt", "7.00\n")


BASIC_EN = {"Один": "One", "Два": "Two", "Новый": "Fresh", "Три": "Three", "Текст": "Text", "Заметка": "Note"}


def check_default_build() -> None:
    with Env(compress=("page.htm", "app.js")) as env:
        basic_env(env)
        # недостающие сегменты: файл и строка после include
        env.dictionary("en", {k: v for k, v in BASIC_EN.items() if k != "Новый"})
        before = env.snapshot(env.target)
        code, out, _ = env.run()
        eq("missing: код", code, 1)
        has("missing: файл и строка после include", out, "[en] page.htm:3: нет перевода «Новый»")
        has("missing: подсказка", out, "--missing <язык>")
        eq("missing: data/ не создана", (before, env.target.exists(), env.i18n.exists()), (None, False, False))
        env.dictionary("en", {k: v for k, v in BASIC_EN.items() if k != "Три"})
        code, out, _ = env.run()
        has("missing 2: строка", out, "[en] page.htm:4: нет перевода «Три»")

        # успешная сборка: перевод после include и ДО сжатия
        env.dictionary("en", BASIC_EN)
        code, out, _ = env.run()
        eq("сборка: код", code, 0)
        eq("data_i18n: состав", sorted(p.name for p in env.i18n.iterdir()),
           ["app.en.js.gz", "notes.en.txt", "page.en.htm.gz"])
        eq("data: состав", sorted(p.name for p in env.target.iterdir()),
           ["app.js.gz", "logo.png", "notes.txt", "page.htm.gz", "version.txt"])
        en_page = "<p>One</p>\n<b>Two</b>\n<i>Fresh</i>\n<p>Three</p>"
        eq("перевод после include", gzip.decompress((env.i18n / "page.en.htm.gz").read_bytes()).decode(), en_page)
        eq("gzip == canonical_gzip перевода", (env.i18n / "page.en.htm.gz").read_bytes(),
           canonical_gzip(en_page.encode()))
        eq("перевод js до сжатия", gzip.decompress((env.i18n / "app.en.js.gz").read_bytes()).decode(),
           "x = 'Text';\n// Комментарий\n")
        eq("txt без сжатия", (env.i18n / "notes.en.txt").read_text(encoding="utf-8"), "Note")
        eq("русский без изменений", gzip.decompress((env.target / "page.htm.gz").read_bytes()).decode(),
           "<p>Один</p>\n<b>Два</b>\n<i>Новый</i>\n<p>Три</p>")
        eq("version.txt общий", (env.target / "version.txt").read_text(), "7.00\n")

        # второй язык, второй набор значений
        env.dictionary("de", {"Один": "Eins", "Два": "Zwei", "Новый": "Neu", "Три": "Drei", "Текст": "Text", "Заметка": "Notiz"})
        code, out, _ = env.run()
        eq("два языка: код", code, 0)
        eq("два языка: состав", sorted(p.name for p in env.i18n.iterdir()),
           ["app.de.js.gz", "app.en.js.gz", "notes.de.txt", "notes.en.txt", "page.de.htm.gz", "page.en.htm.gz"])
        eq("de перевод", (env.i18n / "notes.de.txt").read_text(encoding="utf-8"), "Notiz")

        # ошибка в одном языке не трогает ни data/, ни data_i18n/
        env.dictionary("de", {"Один": "Eins"})
        data_before, i18n_before = env.snapshot(env.target), env.snapshot(env.i18n)
        code, out, _ = env.run()
        eq("ошибка de: код", code, 1)
        has("ошибка de сгруппирована по языку", out, "[de] page.htm:3: нет перевода «Новый»")
        lacks("en без ошибок", out, "[en]")
        eq("ошибка: цели не тронуты", (env.snapshot(env.target), env.snapshot(env.i18n)), (data_before, i18n_before))
        leftovers = sorted(p.name for p in env.root.iterdir() if p.name.endswith(".tmp"))
        eq("ошибка: staging убран", leftovers, [])

        # исключение ПОСЛЕ начала записи: ни staging, ни частичных целей, прежние каталоги целы побайтно
        env.dictionary("de", {"Один": "Eins", "Два": "Zwei", "Новый": "Neu", "Три": "Drei", "Текст": "Text", "Заметка": "Notiz"})
        env.run()
        env.put("notes.txt", "Другая заметка")
        env.dictionary("en", {**BASIC_EN, "Другая заметка": "Other note"})
        env.dictionary("de", {"Один": "Eins", "Два": "Zwei", "Новый": "Neu", "Три": "Drei", "Текст": "Text", "Другая заметка": "Andere"})
        data_before, i18n_before = env.snapshot(env.target), env.snapshot(env.i18n)
        original_write = bwa.write_files
        for fail_on in (1, 2, 3):  # 1 - при записи data/, 2 и 3 - на файлах data_i18n/
            calls = []

            def broken_write(target, files, mode, _calls=calls, _on=fail_on):
                _calls.append(target.name)
                original_write(target, files, mode)
                if len(_calls) == _on:
                    raise OSError(f"диск переполнен ({_on})")

            bwa.write_files = broken_write
            try:
                env.run()
                fail(f"запись {fail_on}: исключение не дошло до вызывающего")
            except OSError as exc:
                has(f"запись {fail_on}: исключение", str(exc), "диск переполнен")
            finally:
                bwa.write_files = original_write
            leftovers = sorted(p.name for p in env.root.iterdir() if p.name.endswith(".tmp"))
            eq(f"запись {fail_on}: staging убран", leftovers, [])
            eq(f"запись {fail_on}: прежние data/ и data_i18n/ целы",
               (env.snapshot(env.target), env.snapshot(env.i18n)), (data_before, i18n_before))
        eq("запись: писали именно staging", calls[0], "data.tmp")
        env.put("notes.txt", "Заметка")
        env.dictionary("de", {"Один": "Eins", "Два": "Zwei", "Новый": "Neu", "Три": "Drei", "Текст": "Text", "Заметка": "Notiz"})
        env.dictionary("en", BASIC_EN)

        # нет словарей: data_i18n/ удаляется и не создаётся
        (env.dicts / "de.json").unlink()
        (env.dicts / "en.json").unlink()
        code, _, _ = env.run()
        eq("без словарей: код", code, 0)
        eq("без словарей: data_i18n/ нет", env.i18n.exists(), False)
        shutil.rmtree(env.target)
        code, _, _ = env.run()
        eq("без словарей: чистый старт", (code, env.i18n.exists(), env.target.is_dir()), (0, False, True))


def check_limit_and_groups() -> None:
    with Env() as env:
        env.put("page.htm", "".join(f"<p>Слово{chr(0x410 + i % 32)}{chr(0x430 + i // 32)}</p>\n" for i in range(300)))
        env.dictionary("en", {"Привет": "Hi"})
        code, out, _ = env.run()
        eq("лимит: код", code, 1)
        has("лимит: хвост", out, "... и ещё")
        has("лимит: подсказка --missing", out, "--missing <язык>")
        if out.count("\n") > 210:
            fail(f"вывод ошибок не ограничен: {out.count(chr(10))} строк")


def check_placeholders() -> None:
    with Env(compress=("page.htm",)) as env:
        # шаблон допустим только в setup.htm; перевод не должен породить плейсхолдер в другом файле
        env.put("page.htm", "<p>Кx</p>")
        env.put("setup.htm", "<p>%NAME% Да</p>")
        env.dictionary("en", {"К": "K", "Да": "Yes"}, {"x": "%ABC%"})
        code, out, _ = env.run()
        eq("плейсхолдер в переводе: код", code, 1)
        has("плейсхолдер в переводе: текст", out, "page.htm: сжатие сломает шаблонизатор, найдены плейсхолдеры %ABC%")
        env.dictionary("en", {"К": "K", "Да": "Yes"}, {"x": "!"})
        code, out, _ = env.run()
        eq("setup.htm с плейсхолдером допустим", code, 0)
        eq("setup.htm переведён", (env.i18n / "setup.en.htm").read_text(encoding="utf-8"), "<p>%NAME% Yes</p>")
        # исходный русский текст с плейсхолдером в сжимаемом файле - ошибка и без словарей
        shutil.rmtree(env.dicts)
        env.put("page.htm", "<p>Да %Q%</p>")
        code, out, _ = env.run()
        eq("плейсхолдер в источнике: код", code, 1)
        has("плейсхолдер в источнике: текст", out, "найдены плейсхолдеры %Q%")


def check_unknown_and_binary() -> None:
    with Env() as env:
        basic_env(env)
        env.put("data.bin", b"\x00")
        code, out, _ = env.run()
        eq("неизвестное расширение: код", code, 1)
        has("неизвестное расширение: текст", out, "data.bin: неизвестное расширение")
        eq("неизвестное расширение: ничего не создано", (env.target.exists(), env.i18n.exists()), (False, False))
        (env.source / "data.bin").unlink()
        env.put("movie.mp3", b"ID3")
        env.dictionary("en", BASIC_EN)
        code, _, _ = env.run()
        eq("бинарные: код", code, 0)
        names = sorted(p.name for p in env.i18n.iterdir())
        for banned in ("logo.png", "logo.en.png", "movie.mp3", "movie.en.mp3", "version.txt", "version.en.txt"):
            if banned in names:
                fail(f"в data_i18n/ попал {banned}")
        eq("бинарные в data/", (env.target / "movie.mp3").read_bytes(), b"ID3")


def check_permissions() -> None:
    with Env() as env:
        basic_env(env)
        env.dictionary("en", BASIC_EN)
        for target_mode, file_mode in ((0o2775, 0o664), (0o2750, 0o640)):
            for path in (env.target, env.i18n):
                shutil.rmtree(path, ignore_errors=True)
                path.mkdir()
            env.target.chmod(target_mode)
            env.i18n.chmod(target_mode)
            code, _, _ = env.run()
            eq(f"права {target_mode:o}: код", code, 0)
            for directory in (env.target, env.i18n):
                eq(f"права каталога {directory.name} {target_mode:o}", stat.S_IMODE(directory.stat().st_mode), target_mode)
                wrong = sorted(
                    p.name for p in directory.iterdir() if stat.S_IMODE(p.stat().st_mode) != file_mode
                )
                eq(f"права файлов {directory.name} {target_mode:o}", wrong, [])
        # data_i18n/ не было, data/ уже есть - права берутся от data/
        shutil.rmtree(env.i18n)
        env.target.chmod(0o2750)
        code, _, _ = env.run()
        eq("права нового data_i18n/", (code, stat.S_IMODE(env.i18n.stat().st_mode)), (0, 0o2750))


def check_image() -> None:
    with Env(compress=("page.htm", "app.js")) as env:
        basic_env(env)
        env.dictionary("en", BASIC_EN)
        env.run()
        out = env.root.parent / "image_en"
        code, text, _ = env.run("--image", "en", "--out", str(out))
        eq("image en: код", code, 0)
        eq("image en: имена", sorted(p.name for p in out.iterdir()),
           ["app.js.gz", "logo.png", "notes.txt", "page.htm.gz", "version.txt"])
        eq("image en: перевод", gzip.decompress((out / "page.htm.gz").read_bytes()).decode(),
           "<p>One</p>\n<b>Two</b>\n<i>Fresh</i>\n<p>Three</p>")
        eq("image en: txt", (out / "notes.txt").read_text(encoding="utf-8"), "Note")
        eq("image en: бинарный как есть", (out / "logo.png").read_bytes(), env.source.joinpath("logo.png").read_bytes())
        eq("image en: version с маркером языка", (out / "version.txt").read_bytes(), b"7.00:en\n")
        eq("image en == data_i18n (после снятия суффикса)",
           (out / "page.htm.gz").read_bytes(), (env.i18n / "page.en.htm.gz").read_bytes())
        # ru - побайтно как data/
        out_ru = env.root.parent / "nested" / "image_ru"
        code, _, _ = env.run("--image", "ru", "--out", str(out_ru))
        eq("image ru: код", code, 0)
        eq("image ru == data/", env.snapshot(out_ru), env.snapshot(env.target))
        eq("image ru: version без маркера", (out_ru / "version.txt").read_bytes(), b"7.00\n")
        eq("data/ version без маркера", (env.target / "version.txt").read_bytes(), b"7.00\n")
        eq("data_i18n/ без version.txt", (env.i18n / "version.txt").exists(), False)
        # второй язык: код берётся из аргумента, а не зашит; версия нормализуется как в прошивке
        env.dictionary("xx", BASIC_EN)
        env.put("version.txt", " 7.01 \r\n")
        out_xx = env.root.parent / "image_xx"
        code, _, _ = env.run("--image", "xx", "--out", str(out_xx))
        eq("image xx: код", code, 0)
        eq("image xx: version", (out_xx / "version.txt").read_bytes(), b"7.01:xx\n")
        out_en2 = env.root.parent / "image_en2"
        env.run("--image", "en", "--out", str(out_en2))
        eq("image en после нормализации: version", (out_en2 / "version.txt").read_bytes(), b"7.01:en\n")
        env.put("version.txt", "7.00\n")
        (env.source / "version.txt").unlink()
        out_nv = env.root.parent / "image_nover"
        code, text, _ = env.run("--image", "en", "--out", str(out_nv))
        eq("image без version.txt: код", code, 1)
        has("image без version.txt: текст", text, "нет version.txt")
        eq("image без version.txt: каталога нет", out_nv.exists(), False)
        env.put("version.txt", "7.00\n")
        # язык без словаря - ошибка, каталог не создаётся
        out_de = env.root.parent / "image_de"
        code, text, _ = env.run("--image", "de", "--out", str(out_de))
        eq("image без словаря: код", code, 1)
        has("image без словаря: текст", text, "нет словаря для языка de")
        eq("image без словаря: каталога нет", out_de.exists(), False)
        # неполный словарь не затирает прежний образ
        env.dictionary("fr", {"Один": "Un"})
        out_fr = env.root.parent / "image_fr"
        code, text, _ = env.run("--image", "fr", "--out", str(out_fr))
        eq("image неполный: код", code, 1)
        has("image неполный: текст", text, "нет перевода")
        eq("image неполный: каталога нет", out_fr.exists(), False)
        eq("image неполный: staging убран", out_fr.with_name("image_fr.tmp").exists(), False)
        # --out: несуществующий и пустой принимаются, непустой отвергается и остаётся цел
        out_empty = env.root.parent / "image_empty"
        out_empty.mkdir()
        code, _, _ = env.run("--image", "en", "--out", str(out_empty))
        eq("--out пустой: код", code, 0)
        eq("--out пустой: образ", (out_empty / "page.htm.gz").is_file(), True)
        for label, keep in (("файл", "keep.txt"), ("подкаталог", "sub/deep.txt")):
            busy = env.root.parent / f"image_busy_{label}"
            (busy / keep).parent.mkdir(parents=True)
            (busy / keep).write_text("чужой файл", encoding="utf-8")
            code, text, _ = env.run("--image", "en", "--out", str(busy))
            eq(f"--out непустой ({label}): код", code, 1)
            has(f"--out непустой ({label}): текст", text, "каталог уже существует и не пуст")
            eq(f"--out непустой ({label}): файл цел", (busy / keep).read_text(encoding="utf-8"), "чужой файл")
            eq(f"--out непустой ({label}): образ не записан", (busy / "page.htm.gz").exists(), False)
        out_file = env.root.parent / "image_is_file"
        out_file.write_text("файл", encoding="utf-8")
        code, text, _ = env.run("--image", "en", "--out", str(out_file))
        eq("--out файл: код", code, 1)
        eq("--out файл: цел", out_file.read_text(encoding="utf-8"), "файл")
        # чужой <out>.tmp рядом не удаляется
        out_tmp = env.root.parent / "image_sib"
        (env.root.parent / "image_sib.tmp").mkdir()
        (env.root.parent / "image_sib.tmp" / "mine.txt").write_text("мой", encoding="utf-8")
        code, text, _ = env.run("--image", "en", "--out", str(out_tmp))
        eq("--out рядом чужой .tmp: код", code, 1)
        eq("--out рядом чужой .tmp: цел",
           (env.root.parent / "image_sib.tmp" / "mine.txt").read_text(encoding="utf-8"), "мой")
        # защита --out: внутри проекта, сам проект и его родитель отвергаются, каталог не тронут
        for name in ("tools", ".git", "data_raw/partials"):
            (env.root / name).mkdir(parents=True, exist_ok=True)
            (env.root / name / "keep.txt").write_text("мой файл", encoding="utf-8")
        env.target.mkdir(exist_ok=True)
        (env.target / "keep.txt").write_text("мой файл", encoding="utf-8")
        for label, bad in (
            ("data", env.target), ("tools", env.root / "tools"), (".git", env.root / ".git"),
            ("data_raw", env.source), ("data_raw/partials", env.partials), ("новый внутри проекта", env.root / "new_out"),
            ("ROOT", env.root), ("родитель ROOT", env.root.parent), ("корень ФС", Path("/")),
        ):
            before = env.snapshot(bad) if bad.is_dir() and bad != Path("/") else None
            code, text, _ = env.run("--image", "ru", "--out", str(bad))
            eq(f"--out {label}: код", code, 1)
            has(f"--out {label}: текст", text, "нельзя собирать образ внутри проекта")
            if bad != Path("/") and bad != env.root.parent:
                eq(f"--out {label}: каталог не тронут", env.snapshot(bad), before)
        eq("--out внутри проекта: файлы целы",
           [(env.root / n / "keep.txt").read_text(encoding="utf-8") for n in ("tools", ".git", "data_raw/partials")],
           ["мой файл"] * 3)
        eq("--out data: не создан new_out", (env.root / "new_out").exists(), False)
        eq("--out SOURCE: источник цел", (env.source / "page.htm").is_file(), True)
        # вне проекта (временный каталог) - можно
        for tail in ("image_outside", "nested/deeper"):
            outside = env.root.parent / tail
            code, text, _ = env.run("--image", "ru", "--out", str(outside))
            eq(f"--out вне проекта {tail}: код", code, 0)
            eq(f"--out вне проекта {tail}: образ", (outside / "page.htm.gz").is_file(), True)
        # аргументы
        eq("--image без --out", env.run("--image", "en")[0], 2)
        eq("--out без --image", env.run("--out", str(out))[0], 2)
        eq("--image и --missing вместе", env.run("--image", "en", "--out", str(out), "--missing", "en")[0], 2)


def check_missing_mode() -> None:
    with Env(compress=()) as env:
        env.put("a.htm", "<p>Бета</p><p>Альфа</p>")
        env.put("b.txt", "Гамма\nБета\nДельта")
        code, out, _ = env.run("--missing", "en")
        eq("--missing: код", code, 0)
        data = json.loads(out)
        eq("--missing: порядок первого вхождения", list(data["segments"]), ["Бета", "Альфа", "Гамма", "Дельта"])
        eq("--missing: пустые значения", set(data["segments"].values()), {""})
        eq("--missing: ключи верхнего уровня", list(data), ["segments"])
        env.dictionary("en", {"Альфа": "Alpha", "Гамма": "Gamma"})
        code, out, _ = env.run("--missing", "en")
        eq("--missing с частичным словарём", list(json.loads(out)["segments"]), ["Бета", "Дельта"])
        env.dictionary("en", {"Бета": "B", "Альфа": "A", "Гамма": "G", "Дельта": "D"})
        code, out, _ = env.run("--missing", "en")
        eq("--missing полный словарь", (code, json.loads(out)["segments"]), (0, {}))
        eq("--missing ru", env.run("--missing", "ru")[0], 1)
        eq("--missing не создаёт каталоги", (env.target.exists(), env.i18n.exists()), (False, False))
        env.put("c.css", "a{} /* Незакрытый")
        code, _, err = env.run("--missing", "en")
        eq("--missing: незакрытая зона", code, 1)
        has("--missing: незакрытая зона, текст", err, "c.css: незакрытый CSS-комментарий")
        (env.source / "c.css").unlink()
        # ошибки другого рода не теряются; кириллица и replace-хиты в --missing не проверяются
        env.put("d.htm", "<p>Бета</p><!-- Незакрытый")
        code, _, err = env.run("--missing", "en")
        eq("--missing: незакрытый HTML-комментарий", code, 1)
        has("--missing: незакрытый HTML-комментарий, текст", err, "d.htm")
        (env.source / "d.htm").unlink()
        env.put("e.txt", b"\xff\xfe")
        code, _, err = env.run("--missing", "en")
        eq("--missing: не UTF-8", code, 1)
        has("--missing: не UTF-8, текст", err, "e.txt: не UTF-8")
        (env.source / "e.txt").unlink()
        env.dictionary("en", {"Бета": "B"}, {"ru-RU": "en-US"})
        code, out, err = env.run("--missing", "en")
        eq("--missing: replace без хитов не ошибка", (code, err), (0, ""))
        eq("--missing: replace без хитов, сегменты", list(json.loads(out)["segments"]), ["Альфа", "Гамма", "Дельта"])


# ---------------------------------------------------------------- реальные словари и node

def lang_headers() -> tuple[dict, set]:
    """(код -> имя) неисходных языков прошивки по lang_*.h и коды исходных."""
    langs, source = {}, set()
    for path in sorted(ROOT.glob("lang_*.h")):
        code = path.stem[len("lang_"):]
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*#\s*define\s+SAMOVAR_LANG_SOURCE\b", text, re.M):
            source.add(code)
            continue
        match = re.search(r'^\s*#\s*define\s+SAMOVAR_LANG_NAME\s+"([^"]*)"', text, re.M)
        langs[code] = match.group(1) if match else None
    return langs, source


def node_check(code: str, module: bool = False) -> str:
    """Пустая строка - синтаксис верен, иначе вывод node."""
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / ("check.mjs" if module else "check.js")
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            return "node не найден: без него синтаксис переведённого JS не проверить"
    return proc.stderr.strip() if proc.returncode else ""


def js_pieces(files: dict) -> list:
    pieces = []
    for name, text in sorted(files.items()):
        kind = web_i18n.file_kind(name)
        if kind == "js":
            pieces.append((name, text, False))
        elif kind == "html":
            for index, (body, is_module) in enumerate(web_i18n.script_bodies(text)):
                pieces.append((f"{name}#script{index}", body, is_module))
    return pieces


def check_node() -> None:
    eq("node: верный JS", node_check("const x = 1;\nfunction f() { return x; }"), "")
    if not node_check("function (", False):
        fail("node --check не заметил битый JS: проверка синтаксиса ничего не доказывает")
    eq("node: module", node_check("import x from './a.js'; export const y = x;", module=True), "")
    if not node_check("import x from './a.js'; export const y = ;", module=True):
        fail("node --check не заметил битый module: проверка модулей ничего не доказывает")
    # скрипты синтетической страницы: тип тега доходит до node
    page = '<script>\nx = 1;\n</script><script type="application/json">{"a": "я"}</script><script type="module">export const z = 1;</script>'
    eq("script_bodies", web_i18n.script_bodies(page), [("\nx = 1;\n", False), ("export const z = 1;", True)])
    eq("script_bodies: без скриптов", web_i18n.script_bodies("<p>x</p><!-- <script>y</script> -->"), [])
    good = {"p.htm": "<script type=\"module\">import x from './a.js';</script>"}
    bad = {"p.htm": "<script type=\"module\">import x from './a.js'; const = ;</script>"}
    plain = {"p.htm": "<script>import x from './a.js';</script>"}
    eq("js_pieces: module", [m for _, _, m in js_pieces(good)], [True])
    eq("js_pieces: обычный", [m for _, _, m in js_pieces(plain)], [False])
    eq("module-скрипт: верный проходит", [node_check(b, m) for _, b, m in js_pieces(good)], [""])
    if not node_check(*js_pieces(bad)[0][1:]):
        fail("битый module-скрипт страницы не пойман")


def contract_errors(segments: dict, lang_header: str) -> list[str]:
    """Переводы, от которых зависит логика страниц, а не только текст.

    «Продолжение через» ищут index.htm и chart.htm в статусе прошивки (includes), поэтому
    перевод обязан входить в LANG_LOGIC_RESUME_IN своего lang_<код>.h. Класс «А-Яа-яЁё» в
    app.js (errorEnvelopeText) отличает фразу прошивки от кода ошибки: фраза содержит
    пробел, код (BUSY, BAD_REQUEST) - нет, поэтому перевод - ровно один пробел.
    """
    problems = []
    match = re.search(r'^\s*#\s*define\s+LANG_LOGIC_RESUME_IN\s+"((?:[^"\\]|\\.)*)"', lang_header, re.M)
    resume = segments.get("Продолжение через")
    if match is None:
        problems.append("lang_*.h: нет LANG_LOGIC_RESUME_IN")
    elif not resume or resume not in match.group(1):
        problems.append(f"«Продолжение через» = {resume!r} не входит в LANG_LOGIC_RESUME_IN {match.group(1)!r}")
    if segments.get("А-Яа-яЁё") != " ":
        problems.append(f"«А-Яа-яЁё» = {segments.get('А-Яа-яЁё')!r}, ожидался один пробел")
    return problems


def check_contract() -> None:
    header = '#define LANG_LOGIC_RESUME_IN ". Continuing in "\n'
    good = {"Продолжение через": "Continuing in", "А-Яа-яЁё": " "}
    eq("связки: верный словарь", contract_errors(good, header), [])
    eq("связки: другой язык", contract_errors({"Продолжение через": "Weiter in", "А-Яа-яЁё": " "},
                                              '#define LANG_LOGIC_RESUME_IN ". Weiter in "\n'), [])
    eq("связки: перевод разошёлся с прошивкой",
       contract_errors({**good, "Продолжение через": "Resuming in"}, header),
       ["«Продолжение через» = 'Resuming in' не входит в LANG_LOGIC_RESUME_IN '. Continuing in '"])
    eq("связки: класс букв переведён буквами",
       contract_errors({**good, "А-Яа-яЁё": "A-Za-z"}, header),
       ["«А-Яа-яЁё» = 'A-Za-z', ожидался один пробел"])
    eq("связки: нет ключа в lang_*.h", contract_errors(good, ""), ["lang_*.h: нет LANG_LOGIC_RESUME_IN"])


def check_real() -> None:
    real_dicts = bwa.DICTIONARIES_DIR
    sources, source_errors = bwa.load_sources()
    for error in source_errors:
        fail(f"data_raw: {error}")
    # исходный русский текст: JS должен быть синтаксически верен
    for name, body, module in js_pieces({n: d.decode("utf-8") for n, d in sources.items() if web_i18n.file_kind(n) in ("js", "html")}):
        message = node_check(body, module)
        if message:
            fail(f"{name} (ru): node --check: {message[:300]}")
    languages = web_i18n.discover_languages(real_dicts)
    headers, _ = lang_headers()
    eq("языки веба == lang_*.h без исходного", languages, sorted(headers))
    for lang in languages:
        dictionary = web_i18n.load_dictionary(real_dicts / f"{lang}.json")
        eq(f"{lang}: language_name == SAMOVAR_LANG_NAME", dictionary.language_name, headers.get(lang))
        for problem in contract_errors(dictionary.segments, (ROOT / f"lang_{lang}.h").read_text(encoding="utf-8")):
            fail(f"{lang}: {problem}")
        result = web_i18n.translate_sources(sources, dictionary)
        for error in result.errors[:20]:
            fail(f"{lang}: {error}")
        for name, line, segment in result.missing[:20]:
            fail(f"{lang}: {name}:{line}: нет перевода «{segment}»")
        extra = sorted(set(dictionary.segments) - result.used)
        if extra:
            fail(f"{lang}: лишние записи словаря ({len(extra)}): {extra[:5]}")
        for name in result.files:
            eq(f"{lang}: реальный суффикс {name}", web_i18n.i18n_name(name, lang).count(f".{lang}."), 1)
        for name, body, module in js_pieces(result.files):
            message = node_check(body, module)
            if message:
                fail(f"{name} ({lang}): node --check: {message[:300]}")


def main() -> int:
    checks = (
        check_segment_boundaries, check_exclusions, check_translation, check_replace,
        check_dictionary_errors, check_names, check_default_build, check_limit_and_groups,
        check_placeholders, check_unknown_and_binary, check_permissions, check_image,
        check_missing_mode, check_node, check_contract, check_real,
    )
    for check in checks:
        try:
            check()
        except Exception as exc:  # падение проверки - тоже падение теста, с именем проверки
            fail(f"{check.__name__}: исключение {type(exc).__name__}: {exc}")
    if errors:
        print("i18n web smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("i18n web smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
