#!/usr/bin/env python3
"""Мультиязычность прошивки: проверка TR(KEY, "русский") и файлов lang_<код>.h.

Что проверяется:
  1. Каждый строковый литерал с кириллицей в корневых *.h/*.ino обёрнут в
     TR(KEY, "..."), либо на его строке стоит комментарий `i18n-keep: <причина>`
     (строки-протоколы, которые сравниваются с внешними данными).
  2. Один KEY - один текст, один текст в одном файле - один KEY.
  3. Каждый неисходный lang_<код>.h полон (ключи TR == ключи файла), без
     кириллицы, с теми же printf-спецификаторами в том же порядке и не длиннее
     русского в байтах (буферы рассчитаны на русский).
  4. i18n.h реально собирается g++ и ведёт себя как заявлено (умолчание, язык,
     нет перевода - ошибка, нет файла языка - ошибка).

Режимы: без аргументов - самотесты и реальный репозиторий; --self-test - только
самотесты и компиляция; --dump - JSON {KEY: русский текст} в stdout.

Свой сканер C++ нужен потому, что strip_cpp_comments не понимает raw-строки
R"lua(...)lua" (lua.h): он принял бы их содержимое за код.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_local_includes import root_sources  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

CYRILLIC_RE = re.compile("[\u0400-\u04FF]")
KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*")
LANG_FILE_RE = re.compile(r"lang_([a-z][a-z0-9_]*)\.h")
SKIP_NAMES = {"i18n.h", "user_config_override.h"}
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NUMBER_RE = re.compile(r"\.?[0-9](?:[eEpP][+-]|[0-9A-Za-z_.]|'[0-9A-Za-z_])*")
RAW_OPEN_RE = re.compile(r'"([^()\\\s]{0,16})\(')
RAW_PREFIXES = {"R", "LR", "uR", "UR", "u8R"}
KEEP_RE = re.compile(r"i18n-keep:[ \t]*(.*)")
PRINTF_RE = re.compile(
    r"%(?:%|[-+#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|z|j|t|L)?[diouxXeEfFgGaAcspn])"
)
MAX_ERRORS = 50


class Tok(NamedTuple):
    kind: str  # ident punct num str raw chr comment
    val: str
    line: int
    end: int
    pp: str | None
    pos: int


class Err(NamedTuple):
    kind: str  # bare | form | conflict
    msg: str


# --------------------------------------------------------------------------- C-литералы

SIMPLE_ESCAPES = {
    "n": 10, "t": 9, "r": 13, "\\": 92, '"': 34, "'": 39, "?": 63,
    "a": 7, "b": 8, "f": 12, "v": 11,
}


def decode_c_literal(body: str) -> bytes:
    """Содержимое C-литерала (без кавычек) -> байты. Неизвестный escape - ValueError."""
    out = bytearray()
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c != "\\":
            out += c.encode("utf-8")
            i += 1
            continue
        i += 1
        if i >= n:
            raise ValueError("обрывается на обратной косой черте")
        c = body[i]
        if c in SIMPLE_ESCAPES:
            out.append(SIMPLE_ESCAPES[c])
            i += 1
        elif c in "01234567":
            j = i
            while j < n and j - i < 3 and body[j] in "01234567":
                j += 1
            value = int(body[i:j], 8)
            if value > 255:
                raise ValueError(f"восьмеричный escape больше байта: \\{body[i:j]}")
            out.append(value)
            i = j
        elif c == "x":
            j = i + 1
            while j < n and body[j] in "0123456789abcdefABCDEF":
                j += 1
            if j == i + 1:
                raise ValueError("\\x без цифр")
            value = int(body[i + 1:j], 16)
            if value > 255:
                raise ValueError(f"\\x больше байта: {body[i:j]}")
            out.append(value)
            i = j
        elif c in "uU":
            width = 4 if c == "u" else 8
            digits = body[i + 1:i + 1 + width]
            if len(digits) != width or any(d not in "0123456789abcdefABCDEF" for d in digits):
                raise ValueError(f"\\{c} требует {width} hex-цифр")
            out += chr(int(digits, 16)).encode("utf-8")
            i += 1 + width
        else:
            raise ValueError(f"неизвестный escape \\{c}")
    return bytes(out)


def decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- сканер C++

def tokenize(text: str) -> list[Tok]:
    toks: list[Tok] = []
    i = 0
    n = len(text)
    line = 1
    pp: str | None = None
    line_start = True

    def emit(kind: str, val: str, start: int, line_no: int) -> None:
        toks.append(Tok(kind, val, line_no, line_no + val.count("\n"), pp, start))

    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            pp = None
            line_start = True
            continue
        if c == "\\" and text[i + 1:i + 2] == "\n":
            line += 1
            i += 2
            continue
        if c == "\\" and text[i + 1:i + 3] == "\r\n":
            line += 1
            i += 3
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            emit("comment", text[i:j], i, line)
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            end = n if j < 0 else j + 2
            val = text[i:end]
            emit("comment", val, i, line)
            line += val.count("\n")
            i = end
            continue
        if c == "#" and line_start:
            m = re.match(r"[ \t]*([A-Za-z_]+)", text[i + 1:])
            pp = m.group(1) if m else ""
            emit("punct", "#", i, line)
            line_start = False
            i += 1
            continue
        line_start = False
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 3 if text.startswith("\r\n", j + 1) else 2
                elif text[j] in '"\n':
                    break
                else:
                    j += 1
            end = min(j + 1, n) if j < n and text[j] == '"' else min(j, n)
            val = text[i:end]
            emit("str", val, i, line)
            line += val.count("\n")
            i = end
            continue
        if c == "'":
            j = i + 1
            while j < n and text[j] not in "'\n":
                j += 2 if text[j] == "\\" else 1
            if j < n and text[j] == "'":
                emit("chr", text[i:j + 1], i, line)
                i = j + 1
            else:
                # одиночный апостроф (например, #error don't) - не литерал
                emit("punct", "'", i, line)
                i += 1
            continue
        if c.isascii() and (c.isalpha() or c == "_"):
            m = IDENT_RE.match(text, i)
            word = m.group(0)
            after = m.end()
            if word in RAW_PREFIXES and text[after:after + 1] == '"':
                opener = RAW_OPEN_RE.match(text, after)
                if opener:
                    close = ")" + opener.group(1) + '"'
                    j = text.find(close, opener.end())
                    end = n if j < 0 else j + len(close)
                    val = text[i:end]
                    emit("raw", val, i, line)
                    line += val.count("\n")
                    i = end
                    continue
            emit("ident", word, i, line)
            i = after
            continue
        if ord(c) > 127:
            # не-ASCII вне строк и комментариев: слово целиком (кириллицу ловит scan_text)
            j = i
            while j < n and (ord(text[j]) > 127 or text[j] == "_" or (text[j].isascii() and text[j].isalnum())):
                j += 1
            emit("word", text[i:j], i, line)
            i = j
            continue
        if c in "0123456789" or (c == "." and text[i + 1:i + 2] in tuple("0123456789")):
            m = NUMBER_RE.match(text, i)
            emit("num", m.group(0), i, line)
            i = m.end()
            continue
        two = text[i:i + 2]
        if two in ("->", "::"):
            emit("punct", two, i, line)
            i += 2
            continue
        emit("punct", c, i, line)
        i += 1
    return toks


def literal_has_cyrillic(tok: Tok) -> bool:
    if CYRILLIC_RE.search(tok.val):
        return True
    if tok.kind == "str":
        try:
            return bool(CYRILLIC_RE.search(decode_text(decode_c_literal(tok.val[1:-1]))))
        except ValueError:
            return False
    return False


def keep_reason_on_lines(comments: list[Tok], first: int, last: int) -> tuple[bool, bool]:
    """(есть маркер i18n-keep:, у него есть причина) среди комментариев на строках first..last."""
    found = False
    for comment in comments:
        if comment.end < first or comment.line > last:
            continue
        m = KEEP_RE.search(comment.val)
        if not m:
            continue
        found = True
        reason = m.group(1)
        if comment.val.startswith("/*"):
            reason = reason.split("*/")[0]
        if reason.strip():
            return True, True
    return found, False


def scan_text(name: str, text: str) -> tuple[list[Err], list[tuple[str, bytes, int]]]:
    """Ошибки файла и найденные TR-вызовы [(KEY, bytes, строка)]."""
    toks = tokenize(text)
    comments = [t for t in toks if t.kind == "comment"]
    sig = [t for t in toks if t.kind != "comment"]
    errors: list[Err] = []
    calls: list[tuple[str, bytes, int]] = []
    covered: set[int] = set()

    def form(tok: Tok, msg: str) -> None:
        errors.append(Err("form", f"{name}:{tok.line}: TR: {msg}"))

    for i, tok in enumerate(sig):
        if tok.kind != "ident" or tok.val != "TR":
            continue
        if i > 0 and sig[i - 1].kind == "punct" and sig[i - 1].val in (".", "->", "::"):
            continue
        if tok.pp in ("ifdef", "ifndef", "undef", "if", "elif"):
            continue  # проверка наличия макроса TR, а не его вызов
        if tok.pp == "define":
            form(tok, "использование внутри #define не поддерживается (разверните макрос или пометьте i18n-keep)")
            continue
        nxt = sig[i + 1:i + 5]
        if not nxt or nxt[0].val != "(" or nxt[0].kind != "punct":
            form(tok, "ожидалась '(' сразу после TR")
            continue
        if len(nxt) < 2 or nxt[1].kind != "ident" or not KEY_RE.fullmatch(nxt[1].val):
            got = nxt[1].val if len(nxt) > 1 else "ничего"
            form(tok, f"первый аргумент - ключ вида [A-Z][A-Z0-9_]*, найдено: {got}")
            continue
        key = nxt[1].val
        if len(nxt) < 3 or nxt[2].val != "," or nxt[2].kind != "punct":
            form(tok, f"после ключа {key} ожидалась ','")
            continue
        j = i + 4
        literals: list[Tok] = []
        while j < len(sig) and sig[j].kind == "str":
            literals.append(sig[j])
            j += 1
        if not literals:
            got = sig[j].kind if j < len(sig) else "конец файла"
            hint = " (raw-строки в TR не поддерживаются)" if got == "raw" else ""
            form(tok, f"второй аргумент {key} - один или несколько строковых литералов, найдено: {got}{hint}")
            continue
        if j >= len(sig) or sig[j].val != ")" or sig[j].kind != "punct":
            got = sig[j].val if j < len(sig) else "конец файла"
            form(tok, f"после литералов {key} ожидалась ')' (только литералы, без выражений), найдено: {got}")
            continue
        try:
            data = b"".join(decode_c_literal(lit.val[1:-1]) for lit in literals)
        except ValueError as error:
            form(tok, f"{key}: {error}")
            continue
        for lit in literals:
            covered.add(lit.pos)
        calls.append((key, data, tok.line))

    reported_words: set[int] = set()
    for tok in sig:
        if tok.kind == "word":
            if not CYRILLIC_RE.search(tok.val) or tok.line in reported_words:
                continue
            reported_words.add(tok.line)
        elif tok.kind not in ("str", "raw", "chr") or tok.pos in covered:
            continue
        elif not literal_has_cyrillic(tok):
            continue
        first = tok.end if tok.kind == "raw" else tok.line
        found, has_reason = keep_reason_on_lines(comments, first, tok.end)
        if has_reason:
            continue
        suffix = ": маркер i18n-keep без причины" if found else ""
        errors.append(Err("bare", f"{name}:{tok.line}: кириллица вне TR{suffix}"))
    return errors, calls


def firmware_files(root: Path) -> list[Path]:
    return [
        p for p in root_sources(root)
        if p.name not in SKIP_NAMES and not LANG_FILE_RE.fullmatch(p.name)
    ]


def scan_firmware(root: Path) -> tuple[dict[str, tuple[bytes, str]], list[Err]]:
    """Ключи {KEY: (bytes, 'файл:строка')} и ошибки сканирования всех файлов."""
    keys: dict[str, tuple[bytes, str]] = {}
    errors: list[Err] = []
    for path in firmware_files(root):
        file_errors, calls = scan_text(path.name, path.read_bytes().decode("utf-8", errors="replace"))
        errors += file_errors
        by_text: dict[bytes, tuple[str, int]] = {}
        for key, data, line in calls:
            loc = f"{path.name}:{line}"
            if key in keys and keys[key][0] != data:
                errors.append(Err(
                    "conflict",
                    f"ключ {key}: разные тексты: {keys[key][1]} «{decode_text(keys[key][0])}» "
                    f"и {loc} «{decode_text(data)}»",
                ))
            else:
                keys.setdefault(key, (data, loc))
            if data in by_text and by_text[data][0] != key:
                errors.append(Err(
                    "conflict",
                    f"{path.name}: один текст «{decode_text(data)}» под разными ключами: "
                    f"{by_text[data][0]} (строка {by_text[data][1]}) и {key} (строка {line})",
                ))
            else:
                by_text.setdefault(data, (key, line))
    return keys, errors


# --------------------------------------------------------------------------- lang-файлы

LIT = r'"(?:[^"\\\n]|\\.)*"'
LIT_RE = re.compile(LIT)
LANG_NAME_RE = re.compile(rf"#define[ \t]+SAMOVAR_LANG_NAME[ \t]+({LIT}(?:[ \t]+{LIT})*)[ \t]*")
LANG_SOURCE_RE = re.compile(r"#define[ \t]+SAMOVAR_LANG_SOURCE[ \t]+\S+[ \t]*")
LANG_KEY_RE = re.compile(rf"#define[ \t]+LANG_([A-Z][A-Z0-9_]*)[ \t]+({LIT}(?:[ \t]+{LIT})*)[ \t]*")
LANG_PRAGMA_RE = re.compile(r"#pragma[ \t]+once[ \t]*")


class LangFile(NamedTuple):
    name: str
    code: str
    lang_name: str | None
    source: bool
    keys: dict[str, tuple[bytes, int]]
    errors: list[str]


def decode_literals(value: str) -> bytes:
    return b"".join(decode_c_literal(m.group(0)[1:-1]) for m in LIT_RE.finditer(value))


def parse_lang(path: Path) -> LangFile:
    name = path.name
    code = LANG_FILE_RE.fullmatch(name).group(1)
    errors: list[str] = []
    lang_name: str | None = None
    source = False
    keys: dict[str, tuple[bytes, int]] = {}
    for number, raw_line in enumerate(path.read_bytes().decode("utf-8", errors="replace").split("\n"), 1):
        line = raw_line.rstrip("\r")
        where = f"{name}:{number}"
        if not line.strip() or line.lstrip().startswith("//") or LANG_PRAGMA_RE.fullmatch(line):
            continue
        m = LANG_NAME_RE.fullmatch(line)
        if m:
            if lang_name is not None:
                errors.append(f"{where}: SAMOVAR_LANG_NAME определён дважды")
            try:
                lang_name = decode_text(decode_literals(m.group(1)))
            except ValueError as error:
                errors.append(f"{where}: {error}")
            continue
        if LANG_SOURCE_RE.fullmatch(line):
            if source:
                errors.append(f"{where}: SAMOVAR_LANG_SOURCE определён дважды")
            source = True
            continue
        m = LANG_KEY_RE.fullmatch(line)
        if m:
            key = m.group(1)
            if key in keys:
                errors.append(f"{where}: дубль ключа {key} (первый раз на строке {keys[key][1]})")
                continue
            try:
                keys[key] = (decode_literals(m.group(2)), number)
            except ValueError as error:
                errors.append(f"{where}: {key}: {error}")
            continue
        errors.append(
            f"{where}: недопустимая строка (разрешены пустые строки, // комментарии, #pragma once, "
            f"#define SAMOVAR_LANG_NAME \"...\", #define SAMOVAR_LANG_SOURCE <v>, "
            f"#define LANG_<KEY> \"...\"): {line.strip()[:60]}"
        )
    if lang_name is None or not lang_name.strip():
        errors.append(f"{name}: нет непустого #define SAMOVAR_LANG_NAME \"...\"")
    return LangFile(name, code, lang_name, source, keys, errors)


def lang_files(root: Path) -> list[LangFile]:
    return [
        parse_lang(p) for p in sorted(root.iterdir())
        if p.is_file() and LANG_FILE_RE.fullmatch(p.name)
    ]


def printf_specs(data: bytes) -> list[str]:
    specs = PRINTF_RE.findall(decode_text(data))
    return [s for s in specs if s != "%%"]


def check_langs(root: Path, keys: dict[str, tuple[bytes, str]]) -> list[str]:
    errors: list[str] = []
    langs = lang_files(root)
    for lang in langs:
        errors += lang.errors
    sources = [lang for lang in langs if lang.source]
    ru = next((lang for lang in langs if lang.code == "ru"), None)
    if ru is None:
        errors.append("нет lang_ru.h (исходный язык)")
    elif not ru.source:
        errors.append("lang_ru.h: нет #define SAMOVAR_LANG_SOURCE (русский - исходный язык)")
    for lang in sources:
        if lang.code != "ru":
            errors.append(f"{lang.name}: SAMOVAR_LANG_SOURCE допустим только в lang_ru.h")
    if ru is not None and ru.keys:
        errors.append(f"lang_ru.h: исходный язык не содержит ключей LANG_* (найдено {len(ru.keys)})")
    for lang in langs:
        if lang.source:
            continue
        for key, (ru_text, ru_loc) in sorted(keys.items()):
            if key not in lang.keys:
                errors.append(f"{lang.name}: нет перевода для {key} («{decode_text(ru_text)}», {ru_loc})")
        for key, (text, number) in sorted(lang.keys.items()):
            where = f"{lang.name}:{number}"
            if key not in keys:
                errors.append(f"{where}: лишний ключ {key}: в коде нет TR({key}, ...)")
                continue
            ru_text = keys[key][0]
            if CYRILLIC_RE.search(decode_text(text)):
                errors.append(f"{where}: {key}: в переводе кириллица")
            if printf_specs(ru_text) != printf_specs(text):
                errors.append(
                    f"{where}: {key}: printf-спецификаторы {printf_specs(text)} "
                    f"не совпадают с русскими {printf_specs(ru_text)}"
                )
            if len(text) > len(ru_text):
                errors.append(
                    f"{where}: {key}: перевод длиннее русского ({len(text)} > {len(ru_text)} байт)"
                )
    return errors


# --------------------------------------------------------------------------- компиляция i18n.h

PRELUDE = (
    '#include "@ROOT@/i18n.h"\n'
    "constexpr bool streq(const char* a, const char* b) { return *a == *b && (*a == 0 || streq(a + 1, b + 1)); }\n"
)


def gpp(root: Path, body: str, defines: list[str], include: Path | None) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "t.cpp"
        source.write_text(PRELUDE.replace("@ROOT@", root.as_posix()) + body, encoding="utf-8")
        cmd = ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only"]
        cmd += [f"-D{d}" for d in defines]
        if include is not None:
            cmd += ["-I", str(include)]
        cmd.append(str(source))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stderr


def error_head(stderr: str) -> str:
    lines = [line for line in stderr.splitlines() if "error" in line]
    return " | ".join(line.strip()[:200] for line in lines[:2]) or stderr.strip()[:200]


def compile_checks(root: Path) -> list[str]:
    errors: list[str] = []

    def must_pass(label: str, body: str, defines: list[str], include: Path | None = None) -> None:
        code, stderr = gpp(root, body, defines, include)
        if code != 0:
            errors.append(f"компиляция [{label}]: {error_head(stderr)}")

    def must_fail(label: str, body: str, defines: list[str], needle: str, include: Path | None = None) -> None:
        code, stderr = gpp(root, body, defines, include)
        if code == 0:
            errors.append(f"компиляция [{label}]: ожидалась ошибка с «{needle}», но код собрался")
        elif needle not in stderr:
            errors.append(f"компиляция [{label}]: ошибка есть, но без «{needle}»: {error_head(stderr)}")

    source_body = (
        'static_assert(streq(TR(K_YES, "Да"), "Да"), "TR должен вернуть русский текст");\n'
        'static_assert(streq(TR(K_NO, "Нет"), "Нет"), "TR должен вернуть русский текст (второй ключ)");\n'
        'static_assert(streq("[" TR(K_YES, "Да") "]", "[Да]"), "TR должен склеиваться с литералами");\n'
        'static_assert(streq(SAMOVAR_LANG_CODE, "ru"), "код языка");\n'
        'static_assert(streq(SAMOVAR_LANG_NAME, "Русский"), "имя языка");\n'
    )
    must_pass("умолчание (язык не задан)", source_body, [])
    must_pass("язык ru явно", source_body, ["SAMOVAR_LANG=ru"])

    with tempfile.TemporaryDirectory() as tmp:
        extra = Path(tmp)
        (extra / "lang_zz.h").write_text(
            '#define SAMOVAR_LANG_NAME "Zed"\n#define LANG_K_YES "Yes"\n#define LANG_K_NO "No"\n',
            encoding="utf-8",
        )
        (extra / "lang_zy.h").write_text(
            '#define SAMOVAR_LANG_NAME "Y"\n#define LANG_K_YES "Yes"\n', encoding="utf-8"
        )
        (extra / "lang_zw.h").write_text('#define LANG_K_YES "Yes"\n', encoding="utf-8")
        (extra / "lang_zx.h").write_text(
            '#define SAMOVAR_LANG_NAME "X"\n#define SAMOVAR_LANG_SOURCE 1\n', encoding="utf-8"
        )
        zz_body = (
            'static_assert(streq(TR(K_YES, "Да"), "Yes"), "zz: TR должен вернуть перевод Yes");\n'
            'static_assert(streq(TR(K_NO, "Нет"), "No"), "zz: TR должен вернуть перевод No");\n'
            'static_assert(streq("[" TR(K_YES, "Да") "]", "[Yes]"), "zz: TR должен склеиваться");\n'
            'static_assert(streq(SAMOVAR_LANG_CODE, "zz"), "zz: код языка");\n'
            'static_assert(streq(SAMOVAR_LANG_NAME, "Zed"), "zz: имя языка");\n'
        )
        must_pass("язык zz: перевод, код, имя", zz_body, ["SAMOVAR_LANG=zz"], extra)
        must_pass(
            "нет перевода: контроль (ключ есть)",
            'static_assert(sizeof(TR(K_YES, "Да")) > 0, "");\n', ["SAMOVAR_LANG=zz"], extra,
        )
        must_fail(
            "нет перевода для ключа",
            'static_assert(sizeof(TR(K_NO, "Нет")) > 0, "");\n', ["SAMOVAR_LANG=zy"], "LANG_K_NO", extra,
        )
        must_fail(
            "нет SAMOVAR_LANG_NAME",
            'static_assert(sizeof(TR(K_YES, "Да")) > 0, "");\n', ["SAMOVAR_LANG=zw"],
            "SAMOVAR_LANG_NAME", extra,
        )
        must_pass(
            "неисходный файл с SOURCE: TR даёт русский",
            'static_assert(streq(TR(K_YES, "Да"), "Да"), "SOURCE: TR должен вернуть русский");\n',
            ["SAMOVAR_LANG=zx"], extra,
        )
    must_fail("несуществующий язык", 'static_assert(true, "");\n', ["SAMOVAR_LANG=xx"], "lang_xx.h")

    for lang in lang_files(root):
        if lang.source:
            continue
        must_pass(
            f"реальный lang_{lang.code}.h: код и имя",
            f'static_assert(streq(SAMOVAR_LANG_CODE, "{lang.code}"), "код языка");\n'
            "static_assert(sizeof(SAMOVAR_LANG_NAME) > 1, \"имя языка\");\n",
            [f"SAMOVAR_LANG={lang.code}"],
        )
    return errors


SAMOVAR_INI_INCLUDE = '#include "Samovar_ini.h"'
I18N_INCLUDE = '#include "i18n.h"'


def samovar_override_checks(samovar_h: str) -> list[str]:
    """Язык из user_config_override.h должен доходить до i18n.h.

    Из Samovar.h берётся кусок от #include "Samovar_ini.h" до #include "i18n.h" включительно
    (блок подключения override лежит внутри него, если порядок верный) и компилируется g++ с
    заглушкой Samovar_ini.h и настоящим i18n.h.
    """
    start = samovar_h.find(SAMOVAR_INI_INCLUDE)
    end = samovar_h.find(I18N_INCLUDE)
    if start < 0 or end < 0 or end < start:
        return [f"Samovar.h: не найдены подряд {SAMOVAR_INI_INCLUDE} и {I18N_INCLUDE}"]
    fragment = samovar_h[start:end + len(I18N_INCLUDE)] + "\n"
    errors: list[str] = []
    for code, name in (("zz", "Zed"), ("zy", "Why")):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "Samovar_ini.h").write_text("#pragma once\n", encoding="utf-8")
            (work / "user_config_override.h").write_text(f"#define SAMOVAR_LANG {code}\n", encoding="utf-8")
            (work / f"lang_{code}.h").write_text(f'#define SAMOVAR_LANG_NAME "{name}"\n', encoding="utf-8")
            for name_ in ("i18n.h", "lang_ru.h"):
                shutil.copyfile(ROOT / name_, work / name_)
            (work / "t.cpp").write_text(
                fragment
                + "constexpr bool streq(const char* a, const char* b) { return *a == *b && (*a == 0 || streq(a + 1, b + 1)); }\n"
                + f'static_assert(streq(SAMOVAR_LANG_CODE, "{code}"), '
                + '"Samovar.h: i18n.h должен подключаться после user_config_override.h, '
                + f'иначе SAMOVAR_LANG {code} из override не подействует");\n',
                encoding="utf-8",
            )
            proc = subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", str(work / "t.cpp")],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                errors.append(f"override языка {code}: {error_head(proc.stderr)}")
    return errors


# --------------------------------------------------------------------------- вывод

def format_errors(errors: list[str]) -> str:
    shown = errors[:MAX_ERRORS]
    text = "\n".join(shown)
    if len(errors) > MAX_ERRORS:
        text += f"\nи ещё {len(errors) - MAX_ERRORS}"
    return text


def run_repository(root: Path) -> list[str]:
    keys, scan_errors = scan_firmware(root)
    return [e.msg for e in scan_errors] + check_langs(root, keys)


def dump(root: Path, out, err) -> int:
    keys, scan_errors = scan_firmware(root)
    problems = [e.msg for e in scan_errors if e.kind != "bare"]
    json.dump({k: decode_text(v[0]) for k, v in keys.items()}, out, sort_keys=True, ensure_ascii=False)
    out.write("\n")
    if problems:
        err.write(format_errors(problems) + "\n")
        return 1
    return 0


# --------------------------------------------------------------------------- самотесты

class SelfTest:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            self.failures.append(f"{name}: {detail}" if detail else name)

    def equal(self, name: str, got, want) -> None:
        self.check(name, got == want, f"получено {got!r}, ожидалось {want!r}")

    def contains(self, name: str, items: list[str], needle: str) -> None:
        self.check(name, any(needle in item for item in items), f"нет «{needle}» среди {items!r}")


def make_root(tmp: str, files: dict[str, str | bytes]) -> Path:
    root = Path(tmp)
    for name, content in files.items():
        data = content.encode("utf-8") if isinstance(content, str) else content
        (root / name).write_bytes(data)
    return root


def scan_one(text: str | bytes, name: str = "a.h") -> tuple[dict[str, str], list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, {name: text})
        keys, errors = scan_firmware(root)
        return {k: decode_text(v[0]) for k, v in keys.items()}, [e.msg for e in errors]


def selftest_scanner(t: SelfTest) -> None:
    keys, errs = scan_one('void f() { puts(TR(A_ONE,\n  "При"\n  "вет")); }\n')
    t.equal("многострочный TR: ключ", keys, {"A_ONE": "Привет"})
    t.equal("многострочный TR: без ошибок", errs, [])

    keys, errs = scan_one('void f() { s = String(F(TR(A_TWO, "Да"))); }\n')
    t.equal("F(TR()): ключ", keys, {"A_TWO": "Да"})
    t.equal("F(TR()): без ошибок", errs, [])

    keys, errs = scan_one('// Привет\n/* Жук\n Жук */ int x;\nint y; // "Нет"\n')
    t.equal("кириллица в комментариях", errs, [])

    _, errs = scan_one('int a;\nint b;\nint c;\nconst char* s = "Нет";\n')
    t.equal("голая строка: номер строки", errs, ["a.h:4: кириллица вне TR"])

    _, errs = scan_one('const char* s = "Нет"; // i18n-keep: протокол с JS\n')
    t.equal("маркер с причиной", errs, [])
    _, errs = scan_one('const char* s = "Нет"; /* i18n-keep: протокол */\n')
    t.equal("блочный маркер с причиной", errs, [])
    _, errs = scan_one('const char* s = "Нет"; // i18n-keep:\n')
    t.equal("маркер без причины", errs, ["a.h:1: кириллица вне TR: маркер i18n-keep без причины"])
    _, errs = scan_one('const char* s = "Нет"; /* i18n-keep:   */\n')
    t.equal("блочный маркер без причины", errs, ["a.h:1: кириллица вне TR: маркер i18n-keep без причины"])
    _, errs = scan_one('const char* s = "Нет";\n// i18n-keep: причина на соседней строке\n')
    t.equal("маркер на соседней строке не считается", errs, ["a.h:1: кириллица вне TR"])
    _, errs = scan_one('// i18n-keep: выше\nconst char* s = "Нет";\n')
    t.equal("маркер строкой выше не считается", errs, ["a.h:2: кириллица вне TR"])

    _, errs = scan_one('const char* a = "a\\"b"; const char* s = "Ж";\n')
    t.equal("экранированная кавычка не сбивает сканер", errs, ["a.h:1: кириллица вне TR"])
    _, errs = scan_one('char q = \'"\'; const char* s = "Ж";\n')
    t.equal("символ '\"' не открывает строку", errs, ["a.h:1: кириллица вне TR"])
    _, errs = scan_one('char q = \'\\\'\'; const char* s = "Ж";\n')
    t.equal("символ '\\'' не ломает сканер", errs, ["a.h:1: кириллица вне TR"])
    _, errs = scan_one('#error don\'t\nconst char* s = "Ж";\n')
    t.equal("#error don't: апостроф не открывает литерал", errs, ["a.h:2: кириллица вне TR"])
    _, errs = scan_one('int x = 1\'000\'000; const char* s = "Ж";\n')
    t.equal("разделитель разрядов 1'000", errs, ["a.h:1: кириллица вне TR"])
    _, errs = scan_one('char c = \'Ж\';\n')
    t.equal("кириллица в символьном литерале", errs, ["a.h:1: кириллица вне TR"])

    raw = 'const char* s = R"lua(x = "a" // not a comment\n  y = "b")lua";\nconst char* t = "Ж";\n'
    _, errs = scan_one(raw)
    t.equal("raw с \" и // внутри + следующая голая строка", errs, ["a.h:3: кириллица вне TR"])
    raw_cyr = 'int a;\nconst char* s = R"lua(\nпривет\n)lua"; // i18n-keep: скрипт\n'
    _, errs = scan_one(raw_cyr)
    t.equal("raw с кириллицей: маркер на закрывающей строке", errs, [])
    raw_cyr_open = 'int a;\nconst char* s = R"lua( // i18n-keep: скрипт\nпривет\n)lua";\n'
    _, errs = scan_one(raw_cyr_open)
    t.equal("raw с кириллицей: маркер только на открывающей строке не считается", errs,
            ["a.h:2: кириллица вне TR"])
    _, errs = scan_one('const char* s = R"x(\nпривет\n)x";\n')
    t.equal("raw с кириллицей без маркера", errs, ["a.h:1: кириллица вне TR"])

    crlf = 'void f() { puts(TR(A_ONE,\r\n  "При"\r\n  "вет"));\r\n  s = "Ж"; }\r\n'
    keys, errs = scan_one(crlf.encode("utf-8"))
    t.equal("CRLF: ключ", keys, {"A_ONE": "Привет"})
    t.equal("CRLF: номер строки", errs, ["a.h:4: кириллица вне TR"])

    keys, errs = scan_one('s = TR(A_ESC, "a\\n\\t\\"\\x41\\101\\u0416");\n')
    t.equal("escape-последовательности", keys, {"A_ESC": 'a\n\t"AAЖ'})
    t.equal("escape: без ошибок", errs, [])

    # кириллица вне строк и комментариев: ошибка с номером строки, а не traceback
    for source, want in [
        ('int a;\n#error Нужен ESP32\n', ["a.h:2: кириллица вне TR"]),
        ('int a;\nint x = Ж;\n', ["a.h:2: кириллица вне TR"]),
        ('int a;\nint x = Ж + Я; int Жук;\n', ["a.h:2: кириллица вне TR"]),
        ('int x = ²; // не кириллица\n', []),
        ('int Ж; // i18n-keep: идентификатор\n', []),
    ]:
        _, errs = scan_one(source)
        t.equal(f"кириллица вне литералов {source!r}", errs, want)

    # строка с продолжением через обратную косую + CRLF не закрывается раньше времени
    crlf_cont = 'const char* a = "x\\\r\n y";\r\nconst char* s = "Ж";\r\n'
    _, errs = scan_one(crlf_cont.encode("utf-8"))
    t.equal("CRLF: продолжение строки в литерале, номер строки", errs, ["a.h:3: кириллица вне TR"])
    _, errs = scan_one('int a;\r\nconst char* s = "x\\\r\nЖ";\r\nint b;\r\n'.encode("utf-8"))
    t.equal("CRLF: кириллица после продолжения остаётся внутри литерала", errs, ["a.h:2: кириллица вне TR"])
    _, errs = scan_one(crlf_cont.replace("\r\n", "\n").encode("utf-8"))
    t.equal("LF: продолжение строки в литерале, номер строки", errs, ["a.h:3: кириллица вне TR"])

    # конфликты ключей и текстов
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, {"a.h": 'x = TR(K_A, "Да");\n', "b.h": '\ny = TR(K_A, "Нет");\n'})
        _, errors = scan_firmware(root)
        msgs = [e.msg for e in errors]
        t.check("один KEY - два текста", len(msgs) == 1 and "a.h:1" in msgs[0] and "b.h:2" in msgs[0]
                and "Да" in msgs[0] and "Нет" in msgs[0], repr(msgs))
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, {"a.h": 'x = TR(K_A, "Да");\n', "b.h": 'y = TR(K_A, "Д" "а");\n', "c.h": 'z = TR(K_B, "Да");\n'})
        _, errors = scan_firmware(root)
        msgs = [e.msg for e in errors]
        t.equal("тот же KEY и текст в двух файлах, тот же текст под другим ключом в другом файле: ошибок нет",
                [m for m in msgs if "разными ключами" in m], [])
    _, errs = scan_one('x = TR(K_A, "Да");\n\ny = TR(K_B, "Да");\n')
    t.check("один текст в файле под двумя ключами",
            len(errs) == 1 and "K_A" in errs[0] and "K_B" in errs[0] and "a.h" in errs[0], repr(errs))

    # формы TR
    forms = [
        ('x = TR(a_b, "x");\n', "первый аргумент - ключ"),
        ('x = TR(K_A);\n', "ожидалась ','"),
        ('x = TR(K_A, y);\n', "строковых литералов, найдено: ident"),
        ('x = TR(K_A, "a" + "b");\n', "ожидалась ')'"),
        ('x = TR(K_A, R"(x)");\n', "raw-строки в TR не поддерживаются"),
        ('x = TR;\n', "ожидалась '('"),
        ('#define M TR(K_D, "Yes")\n', "#define"),
        ('x = TR(K_A, "\\q");\n', "неизвестный escape"),
    ]
    for source, needle in forms:
        _, errs = scan_one(source)
        t.check(f"форма TR {source.strip()!r}", len(errs) == 1 and needle in errs[0] and errs[0].startswith("a.h:1: TR:"),
                repr(errs))
    # директива #define обрывается концом строки, продолжение через обратную косую её продолжает
    keys, errs = scan_one('#define A 1\nx = TR(K_A, "Да");\n')
    t.check("после #define TR вне макроса разбирается как обычно", keys == {"K_A": "Да"} and errs == [], repr((keys, errs)))
    for eol in ("\n", "\r\n"):
        _, errs = scan_one(f'#define M \\{eol} TR(K_A,"x"){eol}'.encode("utf-8"))
        t.check(f"TR в продолжении #define ({eol!r})",
                len(errs) == 1 and errs[0].startswith("a.h:2: TR:") and "#define" in errs[0], repr(errs))
    # проверка наличия макроса - не вызов
    for directive in ("#ifndef TR", "#ifdef TR", "#undef TR", "#if defined(TR)", "#if !defined(TR)",
                      "#elif defined(TR)"):
        keys, errs = scan_one(f"{directive}\n#endif\n")
        t.check(f"{directive}: не вызов TR", keys == {} and errs == [], repr((keys, errs)))
    _, errs = scan_one("#ifdef TR\n#endif\nx = TR;\n")
    t.check("TR после #ifdef TR проверяется", len(errs) == 1 and errs[0].startswith("a.h:3: TR:"), repr(errs))
    keys, errs = scan_one('x = o.TR(1); y = p->TR(2); z = ns::TR(3);\n')
    t.check("TR как член/пространство имён пропускается", keys == {} and errs == [], repr((keys, errs)))

    # пропуск служебных файлов
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, {
            "i18n.h": 's = "Ж";\n', "user_config_override.h": 's = "Ж";\n', "lang_en.h": 's = "Ж";\n',
            "b.ino": 'int x;\n',
        })
        keys, errors = scan_firmware(root)
        t.check("служебные файлы не сканируются", errors == [], repr(errors))

    # ограничение вывода
    text = format_errors([f"e{i}" for i in range(60)])
    t.check("вывод ограничен 50 + «и ещё N»", text.splitlines()[-1] == "и ещё 10" and len(text.splitlines()) == 51, text)
    t.equal("короткий вывод без хвоста", format_errors(["a", "b"]), "a\nb")

    # --dump
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, {"a.h": 'x = TR(K_B, "Жук"); y = "Ж";\n', "b.h": 'z = TR(K_A, "Да");\n'})
        out, err = io.StringIO(), io.StringIO()
        code = dump(root, out, err)
        t.equal("--dump: код", code, 0)
        t.equal("--dump: вывод", out.getvalue(), '{"K_A": "Да", "K_B": "Жук"}\n')
        t.equal("--dump: литерал вне TR игнорируется", err.getvalue(), "")
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, {"a.h": 'x = TR(K_A, "Да");\n', "b.h": 'x = TR(K_A, "Нет");\n'})
        out, err = io.StringIO(), io.StringIO()
        t.equal("--dump: конфликт ключей даёт код 1", dump(root, out, err), 1)
        t.check("--dump: конфликт в stderr", "K_A" in err.getvalue(), err.getvalue())
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, {"a.h": "int x;\n"})
        out, err = io.StringIO(), io.StringIO()
        t.equal("--dump: пустой репозиторий, код", dump(root, out, err), 0)
        t.equal("--dump: пустой репозиторий, вывод", out.getvalue(), "{}\n")


LANG_RU_OK = '#pragma once\n#define SAMOVAR_LANG_NAME "Русский"\n#define SAMOVAR_LANG_SOURCE 1\n'
KEYS = {
    "K_YES": ("Да".encode(), "a.h:1"),
    "K_VAL": ("Значение %d из %s".encode(), "a.h:2"),
    "K_PCT": ("Скидка 50%% сегодня".encode(), "a.h:3"),
    "K_OF": ("50% от суммы".encode(), "a.h:4"),
}
EN_OK = (
    '#pragma once\n// комментарий\n#define SAMOVAR_LANG_NAME "English"\n'
    '#define LANG_K_YES "Yes"\n#define LANG_K_VAL "Value %d of %s"\n'
    '#define LANG_K_PCT "Sale 50%% today"\n#define LANG_K_OF "50% of sum"\n'
)


def lang_errors(files: dict[str, str], keys=KEYS) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        return check_langs(make_root(tmp, files), keys)


def selftest_langs(t: SelfTest) -> None:
    t.equal("lang: корректный набор", lang_errors({"lang_ru.h": LANG_RU_OK, "lang_en.h": EN_OK}), [])

    def one(name: str, en: str, needle: str, ru: str = LANG_RU_OK, files: dict[str, str] | None = None) -> None:
        errs = lang_errors(files if files is not None else {"lang_ru.h": ru, "lang_en.h": en})
        t.check(f"lang: {name}", len(errs) == 1 and needle in errs[0], repr(errs))

    one("нет ключа", EN_OK.replace('#define LANG_K_YES "Yes"\n', ""), "нет перевода для K_YES")
    one("лишний ключ", EN_OK + '#define LANG_K_EXTRA "x"\n', "лишний ключ K_EXTRA")
    one("кириллица в переводе", EN_OK.replace('"Yes"', '"Дa"'), "K_YES: в переводе кириллица")
    one("порядок %d/%s", EN_OK.replace('"Value %d of %s"', '"Value %s of %d"'), "K_VAL: printf-спецификаторы")
    one("потерян %d", EN_OK.replace('"Value %d of %s"', '"Value of %s"'), "K_VAL: printf-спецификаторы")
    one("%% в переводе не спецификатор", EN_OK.replace('"Sale 50%% today"', '"Sale 50%% %d"'), "K_PCT: printf-спецификаторы")
    one("длиннее русского", EN_OK.replace('"Yes"', '"Yeah!"'), "K_YES: перевод длиннее русского (5 > 4")
    t.equal("lang: граница равенства (Да=4 байта, Yeah=4)",
            lang_errors({"lang_ru.h": LANG_RU_OK, "lang_en.h": EN_OK.replace('"Yes"', '"Yeah"')}), [])
    one("SOURCE в неисходном", EN_OK + "#define SAMOVAR_LANG_SOURCE 1\n", "SAMOVAR_LANG_SOURCE допустим только в lang_ru.h")
    one("нет NAME", EN_OK.replace('#define SAMOVAR_LANG_NAME "English"\n', ""), "нет непустого #define SAMOVAR_LANG_NAME")
    one("пустой NAME", EN_OK.replace('"English"', '"  "'), "нет непустого #define SAMOVAR_LANG_NAME")
    one("неожиданная строка", EN_OK + "int x = 1;\n", "en.h:8: недопустимая строка")
    one("дубль ключа", EN_OK + '#define LANG_K_YES "Yes"\n', "дубль ключа K_YES")
    one("дубль NAME", EN_OK + '#define SAMOVAR_LANG_NAME "E"\n', "SAMOVAR_LANG_NAME определён дважды")
    t.equal("lang: склеенные литералы в переводе",
            lang_errors({"lang_ru.h": LANG_RU_OK, "lang_en.h": EN_OK.replace('"Yes"', '"Y" "e" "s"')}), [])
    errs = lang_errors({"lang_ru.h": LANG_RU_OK + '#define LANG_K_YES "Да"\n', "lang_en.h": EN_OK})
    t.check("lang: ключи в lang_ru.h", len(errs) == 1 and "исходный язык не содержит ключей" in errs[0], repr(errs))
    errs = lang_errors({"lang_en.h": EN_OK})
    t.check("lang: нет lang_ru.h", errs == ["нет lang_ru.h (исходный язык)"], repr(errs))
    errs = lang_errors({"lang_ru.h": LANG_RU_OK.replace("#define SAMOVAR_LANG_SOURCE 1\n", "")}, keys={})
    t.check("lang: у lang_ru.h нет SOURCE", errs == ["lang_ru.h: нет #define SAMOVAR_LANG_SOURCE (русский - исходный язык)"],
            repr(errs))
    errs = lang_errors({"lang_ru.h": LANG_RU_OK, "lang_en.h": EN_OK, "lang_de.h": EN_OK.replace("English", "Deutsch")})
    t.equal("lang: два неисходных языка", errs, [])
    errs = lang_errors({"lang_ru.h": LANG_RU_OK, "lang_en.h": EN_OK, "lang_de.h": EN_OK.replace("English", "Deutsch").replace('"Yes"', '"Ja!!!"')})
    t.check("lang: ошибка только в одном из языков", len(errs) == 1 and errs[0].startswith("lang_de.h"), repr(errs))
    t.equal("lang: без неисходных языков ошибок нет", lang_errors({"lang_ru.h": LANG_RU_OK}), [])
    errs = lang_errors({"lang_ru.h": LANG_RU_OK, "lang_en.h": EN_OK.replace("\n", "\r\n")})
    t.equal("lang: CRLF в lang-файле", errs, [])


def selftest_printf(t: SelfTest) -> None:
    t.equal("printf: разбор", printf_specs(b"%d %5.1f %s %lu %-3d %%"), ["%d", "%5.1f", "%s", "%lu", "%-3d"])
    t.equal("printf: «50% of» не спецификатор", printf_specs(b"50% of"), [])
    t.equal("printf: '*'", printf_specs(b"%*d %.*f"), ["%*d", "%.*f"])


# Последнее поле - подстроки, которые должны встретиться вместе в ОДНОМ сообщении: текст причины
# (assert-а или stderr g++), а не метка проверки; метка нужна лишь чтобы отличить мутации с
# одинаковой причиной.
MUTATIONS = [
    ("TR всегда русский (LANG_##key -> ru)", "#define TR(key, ru) LANG_##key", "#define TR(key, ru) ru",
     ("TR должен вернуть перевод",)),
    ("убрано умолчание языка", "#ifndef SAMOVAR_LANG\n#define SAMOVAR_LANG ru\n#endif\n", "",
     ("умолчание", "lang_SAMOVAR_LANG.h: No such file")),
    ("убран уровень косвенности", "#include SAMOVAR_I18N_HEADER(SAMOVAR_LANG)", "#include SAMOVAR_I18N_HEADER_(SAMOVAR_LANG)",
     ("язык zz", "lang_SAMOVAR_LANG.h: No such file")),
    ("убрана проверка имени языка", '#error lang file must define SAMOVAR_LANG_NAME\n', "",
     ("ожидалась ошибка с «SAMOVAR_LANG_NAME», но код собрался",)),
    ("SOURCE больше не выбирает исходный язык", "#ifdef SAMOVAR_LANG_SOURCE\n#define TR(key, ru) ru", "#if 0\n#define TR(key, ru) ru",
     ("error", "LANG_K_YES")),
]


def selftest_i18n_mutations(t: SelfTest) -> None:
    original = (ROOT / "i18n.h").read_bytes().decode("utf-8")
    for name, old, new, needle in MUTATIONS:
        if original.count(old) != 1:
            t.check(f"мутация «{name}»", False, "фрагмент не найден в i18n.h ровно один раз")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ROOT.glob("lang_*.h"):
                shutil.copyfile(path, root / path.name)
            (root / "i18n.h").write_bytes(original.replace(old, new).encode("utf-8"))
            errors = compile_checks(root)
        t.check(f"мутация «{name}» ловится", any(all(n in e for n in needle) for e in errors),
                f"ожидалось {needle!r} в одном сообщении, получено {errors!r}")


def selftest_override_order(t: SelfTest) -> None:
    original = (ROOT / "Samovar.h").read_bytes().decode("utf-8")
    t.equal("Samovar.h: язык из override доходит до i18n.h", samovar_override_checks(original), [])
    block = '#if __has_include("user_config_override.h")'
    if original.count(I18N_INCLUDE + "\n") != 1 or original.count(block) != 1:
        t.check("мутация порядка include", False, "не найден i18n.h или блок override в Samovar.h")
        return
    moved = original.replace(I18N_INCLUDE + "\n", "", 1).replace(block, I18N_INCLUDE + "\n" + block, 1)
    errs = samovar_override_checks(moved)
    t.check("мутация: i18n.h выше override ловится",
            any("i18n.h должен подключаться после user_config_override.h" in e for e in errs), repr(errs))


def run_self_tests() -> list[str]:
    t = SelfTest()
    selftest_scanner(t)
    selftest_printf(t)
    selftest_langs(t)
    t.failures += compile_checks(ROOT)
    selftest_i18n_mutations(t)
    selftest_override_order(t)
    return t.failures


def main(argv: list[str]) -> int:
    if argv == ["--dump"]:
        return dump(ROOT, sys.stdout, sys.stderr)
    if argv not in ([], ["--self-test"]):
        print("usage: smoke_i18n_firmware.py [--self-test | --dump]", file=sys.stderr)
        return 2
    problems = run_self_tests()
    if argv == []:
        problems += run_repository(ROOT)
    if problems:
        print(f"FAIL smoke_i18n_firmware: {len(problems)} ошибок")
        print(format_errors(problems))
        return 1
    print("OK smoke_i18n_firmware")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
