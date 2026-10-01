#!/usr/bin/env python3
"""Перевод веб-интерфейса при сборке: чистая логика без ввода-вывода сборщика.

Исходный язык - русский, он остаётся в data_raw/. Для остальных языков словарь
i18n/web/<lang>.json подставляет перевод вместо СЕГМЕНТОВ: кусков текста от первой
до последней кириллической буквы, не пересекающих символы `< > " ' ` { } \\` и
перевод строки. Нет перевода сегмента - ошибка сборки, никакого отката на русский.

Не переводятся комментарии: HTML `<!-- -->`, CSS `/* */` (в .css и в <style>), в JS
(.js и <script>) - только начинающиеся с начала строки. В .lua и .txt переводится
всё: их читает и правит пользователь.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SEGMENT_RE = re.compile(r"[А-Яа-яЁё](?:[^<>\"'`{}\n\\]*[А-Яа-яЁё])?")
CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
FORBIDDEN = "<>\"'`{}\\\n\r"
LANG_RE = re.compile(r"[a-z]{2,3}")

TEXT_KINDS = {".htm": "html", ".js": "js", ".css": "css", ".lua": "plain", ".txt": "plain"}
BINARY_EXT = (".png", ".gif", ".mp3", ".ico")
UNTRANSLATED = ("version.txt",)

CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
JS_COMMENT_RE = re.compile(r"^[ \t]*(?://[^\n]*|/\*.*?\*/)", re.M | re.S)
HTML_TOKEN_RE = re.compile(r"<!--.*?-->|<(script|style)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)
HTML_OPEN_RE = re.compile(r"<!--|<(?:script|style)\b", re.I)
TYPE_RE = re.compile(r"""\btype\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
JS_TYPES = ("", "text/javascript", "application/javascript", "module")

NAME_RE = re.compile(r"%[A-Za-z_][A-Za-z0-9_.]*%")
PRINTF_RE = re.compile(
    r"%[-+#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|z|j|t)?[diuoxXfFeEgGaAcspn]"
)


class I18nError(ValueError):
    pass


@dataclass
class Dictionary:
    lang: str
    language_name: str
    replace: dict
    segments: dict


@dataclass
class Translation:
    """Итог перевода набора файлов одним словарём."""

    files: dict = field(default_factory=dict)  # имя -> переведённый текст
    missing: list = field(default_factory=list)  # (файл, строка, сегмент) по порядку
    used: set = field(default_factory=set)  # сегменты, найденные в словаре
    replace_hits: dict = field(default_factory=dict)  # ключ replace -> число замен
    errors: list = field(default_factory=list)


def file_kind(name: str) -> str:
    """html/js/css/plain - переводимые, binary, untranslated; иначе ошибка сборки."""
    if name in UNTRANSLATED:
        return "untranslated"
    suffix = Path(name).suffix.lower()
    if suffix in BINARY_EXT:
        return "binary"
    if suffix in TEXT_KINDS:
        return TEXT_KINDS[suffix]
    raise I18nError(f"{name}: неизвестное расширение, не ясно, переводить ли файл")


def i18n_name(name: str, lang: str) -> str:
    """Суффикс языка перед ПЕРВОЙ точкой: a.b.js -> a.en.b.js."""
    dot = name.find(".")
    if dot < 0:
        raise ValueError(f"{name}: в имени нет точки, суффикс языка вставлять некуда")
    return f"{name[:dot]}.{lang}{name[dot:]}"


# ---------------------------------------------------------------- словари

def discover_languages(directory: Path) -> list:
    if not directory.is_dir():
        return []
    languages = []
    for path in sorted(directory.glob("*.json")):
        if not LANG_RE.fullmatch(path.stem):
            raise I18nError(
                f"{path.name}: имя словаря должно быть кодом языка из 2-3 строчных латинских букв"
            )
        languages.append(path.stem)
    return languages


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise I18nError(f"повторяющийся ключ JSON: {key!r}")
        result[key] = value
    return result


def _placeholder_parity(segment: str, translation: str) -> list:
    problems = []
    if sorted(NAME_RE.findall(segment)) != sorted(NAME_RE.findall(translation)):
        problems.append("не совпадают плейсхолдеры %ИМЯ%")
    if segment.count("%") != translation.count("%"):
        problems.append("не совпадает число символов '%'")
    if PRINTF_RE.findall(NAME_RE.sub("", segment)) != PRINTF_RE.findall(NAME_RE.sub("", translation)):
        problems.append("не совпадают printf-спецификаторы")
    return problems


def _bad_value(value) -> str | None:
    if not isinstance(value, str) or not value:
        return "значение должно быть непустой строкой"
    bad = sorted({c for c in value if c in FORBIDDEN})
    if bad:
        return "запрещённые символы " + " ".join(repr(c) for c in bad)
    if CYRILLIC_RE.search(value):
        return "в значении осталась кириллица"
    return None


def load_dictionary(path: Path) -> Dictionary:
    lang = path.stem
    where = path.name
    errors: list = []
    if lang == "ru":
        raise I18nError(f"{where}: русский - исходный язык, словарь для него не нужен")
    if not LANG_RE.fullmatch(lang):
        raise I18nError(f"{where}: имя словаря должно быть кодом языка из 2-3 строчных латинских букв")
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except (OSError, ValueError) as exc:
        raise I18nError(f"{where}: не читается: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"language_name", "replace", "segments"}:
        raise I18nError(f"{where}: на верхнем уровне должны быть ровно language_name, replace, segments")
    name = data["language_name"]
    if not isinstance(name, str) or not name.strip():
        errors.append("language_name должен быть непустой строкой")
    for part in ("replace", "segments"):
        if not isinstance(data[part], dict):
            errors.append(f"{part} должен быть объектом")
    if errors:
        raise I18nError(f"{where}: " + "; ".join(errors))
    for key, value in data["replace"].items():
        if not key:
            errors.append("replace: пустой ключ")
        elif CYRILLIC_RE.search(key):
            errors.append(f"replace: кириллица в ключе {key!r}")
        # replace правит код страниц (атрибуты, вызовы), поэтому кавычки в значении допустимы.
        if not isinstance(value, str) or not value:
            errors.append(f"replace[{key!r}]: значение должно быть непустой строкой")
        elif CYRILLIC_RE.search(value):
            errors.append(f"replace[{key!r}]: в значении осталась кириллица")
    for key, value in data["segments"].items():
        if not SEGMENT_RE.fullmatch(key):
            errors.append(f"segments: ключ не является сегментом: {key!r}")
            continue
        problem = _bad_value(value)
        if problem:
            errors.append(f"segments[{key!r}]: {problem}")
            continue
        for parity in _placeholder_parity(key, value):
            errors.append(f"segments[{key!r}]: {parity}")
    if errors:
        raise I18nError(f"{where}: " + "; ".join(errors))
    return Dictionary(lang, name, dict(data["replace"]), dict(data["segments"]))


# ---------------------------------------------------------------- зоны

def _css_regions(text: str, base: int, what: str) -> list:
    regions = []
    pos = 0
    for match in CSS_COMMENT_RE.finditer(text):
        regions.append((base + pos, text[pos:match.start()], True))
        regions.append((base + match.start(), match.group(), False))
        pos = match.end()
    tail = text[pos:]
    if "/*" in tail:
        raise I18nError(f"{what}: незакрытый CSS-комментарий")
    regions.append((base + pos, tail, True))
    return regions


def _js_regions(text: str, base: int, what: str) -> list:
    regions = []
    pos = 0
    for match in JS_COMMENT_RE.finditer(text):
        regions.append((base + pos, text[pos:match.start()], True))
        regions.append((base + match.start(), match.group(), False))
        pos = match.end()
    tail = text[pos:]
    if re.search(r"^[ \t]*/\*", tail, re.M):
        raise I18nError(f"{what}: незакрытый блочный комментарий JS")
    regions.append((base + pos, tail, True))
    return regions


def _script_type(open_tag: str) -> str:
    match = TYPE_RE.search(open_tag)
    if not match:
        return ""
    return next(g for g in match.groups() if g is not None).strip().lower()


def _html_regions(text: str, what: str) -> list:
    regions = []
    pos = 0

    def plain(start: int, end: int) -> None:
        chunk = text[start:end]
        if HTML_OPEN_RE.search(chunk):
            raise I18nError(f"{what}: незакрытый <!--, <script> или <style>")
        regions.append((start, chunk, True))

    for match in HTML_TOKEN_RE.finditer(text):
        plain(pos, match.start())
        pos = match.end()
        tag = match.group(1)
        if tag is None:
            regions.append((match.start(), match.group(), False))
            continue
        body_start, body_end = match.start(2), match.end(2)
        regions.append((match.start(), text[match.start():body_start], True))
        body = text[body_start:body_end]
        if tag.lower() == "style":
            regions.extend(_css_regions(body, body_start, what))
        elif _script_type(text[match.start():body_start]) in JS_TYPES:
            regions.extend(_js_regions(body, body_start, what))
        else:
            regions.append((body_start, body, True))
        regions.append((body_end, text[body_end:match.end()], True))
    plain(pos, len(text))
    return regions


def regions(kind: str, text: str, what: str = "") -> list:
    """Разбивает текст на (смещение, кусок, переводимый_ли)."""
    if kind == "plain":
        return [(0, text, True)]
    if kind == "css":
        return _css_regions(text, 0, what)
    if kind == "js":
        return _js_regions(text, 0, what)
    if kind == "html":
        return _html_regions(text, what)
    raise I18nError(f"{what}: {kind!r} не текстовый файл")


def script_bodies(text: str) -> list:
    """(тело, module) каждого <script> с JS-типом: для проверки синтаксиса node."""
    bodies = []
    for match in HTML_TOKEN_RE.finditer(text):
        if match.group(1) and match.group(1).lower() == "script":
            script_type = _script_type(text[match.start():match.start(2)])
            if script_type in JS_TYPES:
                bodies.append((match.group(2), script_type == "module"))
    return bodies


# ---------------------------------------------------------------- перевод

def translate_text(
    name: str, text: str, dictionary: Dictionary, result: Translation, strict: bool = True
) -> str:
    """Переводит один файл (текст после include), накапливая итог в result.

    strict=False не проверяет остаточную кириллицу (режим --missing: словарь неполный)."""
    kind = file_kind(name)
    for key, value in dictionary.replace.items():
        result.replace_hits[key] = result.replace_hits.get(key, 0) + text.count(key)
        text = text.replace(key, value)
    try:
        pieces = regions(kind, text, name)
    except I18nError as exc:
        result.errors.append(str(exc))
        return text
    out = []
    for offset, chunk, translatable in pieces:
        if not translatable:
            out.append(chunk)
            continue
        missing_before = len(result.missing)

        def substitute(match: re.Match) -> str:
            segment = match.group()
            translation = dictionary.segments.get(segment)
            if translation is None:
                line = text.count("\n", 0, offset + match.start()) + 1
                result.missing.append((name, line, segment))
                return segment
            result.used.add(segment)
            return translation

        done = SEGMENT_RE.sub(substitute, chunk)
        if strict and len(result.missing) == missing_before:
            leftover = CYRILLIC_RE.search(done)
            if leftover:
                line = text.count("\n", 0, offset) + done.count("\n", 0, leftover.start()) + 1
                result.errors.append(
                    f"{name}:{line}: после перевода осталась кириллица {leftover.group()!r}"
                )
        out.append(done)
    return "".join(out)


def translate_sources(sources: dict, dictionary: Dictionary, strict: bool = True) -> Translation:
    """sources: имя -> bytes/str после include. Берёт только переводимые текстовые файлы.

    strict=False (режим --missing) не проверяет остаточную кириллицу и replace-хиты."""
    result = Translation()
    for name, data in sources.items():
        try:
            kind = file_kind(name)
        except I18nError as exc:
            result.errors.append(str(exc))
            continue
        if kind in ("binary", "untranslated"):
            continue
        if isinstance(data, bytes):
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                result.errors.append(f"{name}: не UTF-8: {exc}")
                continue
        result.files[name] = translate_text(name, data, dictionary, result, strict)
    for key in dictionary.replace:
        if strict and result.replace_hits.get(key, 0) == 0:
            result.errors.append(f"replace {key!r}: ни разу не нашлось в файлах")
    return result
