#!/usr/bin/env python3
"""Проверяет, что замки берутся в порядке, объявленном в runtime_helpers.h.

Взаимная блокировка возникает, когда одна задача держит замок A и ждёт B, а
вторая держит B и ждёт A. Единственная защита - глобальный порядок: если два
замка нужны одновременно, их всегда берут в одном и том же порядке.

Таблица LOCK_ORDER в runtime_helpers.h - единственный источник правды, тест
читает ранги оттуда. Здесь ничего не дублируется.

Глубина анализа (сознательное ограничение, не молчаливое):
  1. вложенность внутри одной функции - точно, с учётом областей видимости
     RAII-стражей и глубины скобок для ручных lock/unlock;
  2. вложенность через ОДИН уровень вызова - если под замком вызвана функция,
     которая сама берёт замок напрямую.
Цепочки вызовов длиннее одного уровня тест не разворачивает: транзитивное
замыкание в этом проекте протекает через крупные функции и даёт ложные пары.
Такие места перечислены в комментарии "Известные вложенности" в runtime_helpers.h.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

SKIP_PREFIXES = ("lib", ".pio", ".git", "tools", "data", "doc", "pro_mini", "libraries", "ai_docs")
SOURCE_SUFFIXES = {".ino", ".h", ".cpp"}

LOCK_ORDER_RE = re.compile(
    r"//\s*LOCK_ORDER:\s*(\d+)\s+([A-Z_0-9]+)\s+(\w+)\s+(.+?)\s*$", re.MULTILINE
)


def source_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(SKIP_PREFIXES):
            continue
        files.append(path)
    return files


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


helpers_text = read(ROOT / "runtime_helpers.h")

# ---- 1. таблица иерархии ----------------------------------------------------
rank_by_tag: dict[str, int] = {}
tag_by_handle: dict[str, str] = {}
for match in LOCK_ORDER_RE.finditer(helpers_text):
    rank, tag, handle, _description = match.groups()
    if tag in rank_by_tag:
        errors.append(f"LOCK_ORDER: тег {tag} объявлен дважды")
    if int(rank) in rank_by_tag.values():
        errors.append(f"LOCK_ORDER: ранг {rank} занят дважды (тег {tag})")
    rank_by_tag[tag] = int(rank)
    tag_by_handle[handle] = tag

if len(rank_by_tag) < 2:
    print("Lock order smoke check failed:")
    print(" - таблица LOCK_ORDER в runtime_helpers.h не найдена или пуста")
    sys.exit(1)

# ---- 2. ни один семафор не остался вне таблицы ------------------------------
declared_handles: dict[str, str] = {}
for path in source_files():
    for line_number, line in enumerate(read(path).splitlines(), start=1):
        match = re.search(r"SemaphoreHandle_t\s+(\w+)", line)
        if match and not match.group(1).endswith("Buffer"):
            declared_handles.setdefault(match.group(1), f"{path.relative_to(ROOT)}:{line_number}")

for handle, where in sorted(declared_handles.items()):
    if handle not in tag_by_handle:
        errors.append(
            f"семафор {handle} ({where}) не описан в таблице LOCK_ORDER в runtime_helpers.h"
        )

# ---- 3. точки захвата: обёртки, стражи, прямые xSemaphoreTake ---------------
wrapper_tags: dict[str, str] = {}
guard_tags: dict[str, str] = {}
for path in source_files():
    text = read(path)
    # обёртка вида: inline bool <имя>(TickType_t ...) { return <handle> && xSemaphoreTake(<handle>
    for match in re.finditer(
        r"inline\s+bool\s+(\w+)\s*\([^{;]*\)\s*\{\s*return\s+(\w+)\s*&&\s*xSemaphoreTake\s*\(\s*\2",
        text,
    ):
        name, handle = match.groups()
        if handle in tag_by_handle:
            wrapper_tags[name] = tag_by_handle[handle]
    # RAII-страж: struct <имя>Guard { ... } - тег по обёртке или по хендлу в теле
    for match in re.finditer(r"struct\s+(\w*LockGuard)\s*\{", text):
        name = match.group(1)
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth > 0:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        body = text[start:index]
        tag = None
        for wrapper, wrapper_tag in wrapper_tags.items():
            if re.search(r"(?<![\w])" + wrapper + r"\s*\(", body):
                tag = wrapper_tag
        for handle, handle_tag in tag_by_handle.items():
            if re.search(r"xSemaphoreTake\s*\(\s*" + handle + r"\b", body):
                tag = handle_tag
        if tag is None:
            errors.append(f"страж {name} не привязан ни к одному замку из LOCK_ORDER")
        else:
            guard_tags[name] = tag

for tag in sorted(rank_by_tag):
    known = tag in wrapper_tags.values() or tag in guard_tags.values()
    if not known:
        handles = [h for h, t in tag_by_handle.items() if t == tag]
        raw_used = any(
            re.search(r"xSemaphoreTake\s*\(\s*" + h + r"\b", read(p))
            for h in handles
            for p in source_files()
        )
        if not raw_used:
            errors.append(f"тег {tag} объявлен в LOCK_ORDER, но нигде не захватывается")

TAKE_PATTERNS = [(re.compile(r"(?<![\w])" + name + r"\s*\("), tag)
                 for name, tag in wrapper_tags.items()]
GIVE_PATTERNS = [(re.compile(r"(?<![\w])" + name.replace("_lock", "_unlock") + r"\s*\("), tag)
                 for name, tag in wrapper_tags.items() if name.endswith("_lock")]
GUARD_PATTERNS = [(re.compile(r"(?<![\w])" + name + r"\s+(\w+)"), tag)
                  for name, tag in guard_tags.items()]
RELEASE_RE = re.compile(r"(?<![\w])(\w+)\.release\s*\(\)")
DEFINITION_RE = re.compile(r"^\s*(inline\s+)?(bool|void)\s+\w+_(un)?lock\s*\(")
CALL_RE = re.compile(r"(?<![\w])(\w+)\s*\(")


EXIT_RE = re.compile(r"^\s*(return|break|continue|goto)\b")


def branch_exits_after(lines: list[str], index: int, depth: int) -> bool:
    """True, если ветка после строки index завершается выходом, не дойдя до её конца."""
    current = depth
    for position in range(index + 1, len(lines)):
        line = lines[position]
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if EXIT_RE.match(line) and current >= depth:
            return True
        current += line.count("{") - line.count("}")
        if current < depth:
            return False
    return False


def line_events(line: str) -> tuple[list[tuple[str, str, str | None]], list[str]]:
    """(захваты, освобождения) в одной строке. Захват: (тег, вид, имя стража)."""
    takes: list[tuple[str, str, str | None]] = []
    gives: list[str] = []
    stripped = line.strip()
    if stripped.startswith("//") or stripped.startswith("*"):
        return takes, gives
    if not DEFINITION_RE.match(line):
        for pattern, tag in TAKE_PATTERNS:
            if pattern.search(line):
                takes.append((tag, "manual", None))
        for pattern, tag in GIVE_PATTERNS:
            if pattern.search(line):
                gives.append(tag)
    compact = line.replace(" ", "")
    for handle, tag in tag_by_handle.items():
        if re.search(r"xSemaphoreTake\(" + handle + r"(?![\w])", compact):
            takes.append((tag, "manual", None))
        if re.search(r"xSemaphoreGive\(" + handle + r"(?![\w])", compact):
            gives.append(tag)
    for pattern, tag in GUARD_PATTERNS:
        match = pattern.search(line)
        if match and "struct" not in line:
            takes.append((tag, "guard", match.group(1)))
    return takes, gives


# функция -> замки, которые она берёт напрямую (для одного уровня вызовов)
def function_name_before_brace(chunk: str) -> str | None:
    """Имя функции = идентификатор перед скобкой, которая закрывается у '{'."""
    brace = chunk.rfind("{")
    if brace == -1:
        return None
    index = brace - 1
    while index >= 0 and chunk[index] in " \t":
        index -= 1
    if index < 0 or chunk[index] != ")":
        return None
    depth = 0
    while index >= 0:
        if chunk[index] == ")":
            depth += 1
        elif chunk[index] == "(":
            depth -= 1
            if depth == 0:
                break
        index -= 1
    if index < 0:
        return None
    match = re.search(r"(\w+)\s*$", chunk[:index])
    return match.group(1) if match else None


def parse_functions(lines: list[str]) -> list[tuple[str, int, int]]:
    found = []
    depth = 0
    head = None
    head_line = 0
    for index, line in enumerate(lines):
        if depth == 0 and "{" in line:
            chunk = " ".join(lines[max(0, index - 4):index + 1])
            head = function_name_before_brace(chunk)
            head_line = index
        previous = depth
        depth += line.count("{") - line.count("}")
        if previous > 0 and depth <= 0 and head is not None:
            found.append((head, head_line, index))
            head = None
            depth = 0
    return found


direct_tags: dict[str, set[str]] = {}
for path in source_files():
    lines = read(path).splitlines()
    for name, start, end in parse_functions(lines):
        tags = set()
        for line in lines[start:end + 1]:
            for tag, _kind, _guard in line_events(line)[0]:
                tags.add(tag)
        if tags:
            direct_tags.setdefault(name, set()).update(tags)

# ---- 4. сам анализ вложенности ---------------------------------------------
observed: dict[tuple[str, str], set[str]] = {}
for path in source_files():
    lines = read(path).splitlines()
    depth = 0
    held: list[tuple[str, int, str, str | None]] = []  # тег, глубина захвата, вид, имя стража
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            depth += line.count("{") - line.count("}")
            continue
        takes, gives = line_events(line)
        release = RELEASE_RE.search(line)
        if release:
            for tag, _held_depth, _kind, guard_name in held:
                if guard_name == release.group(1):
                    gives.append(tag)
                    break
        where = f"{path.relative_to(ROOT)}:{index + 1}"
        for tag, _kind, _guard in takes:
            for held_tag, _held_depth, _held_kind, _held_name in held:
                if held_tag != tag:
                    observed.setdefault((held_tag, tag), set()).add(where)
        if held:
            for callee in CALL_RE.findall(line):
                for tag in direct_tags.get(callee, ()):
                    for held_tag, _held_depth, _held_kind, _held_name in held:
                        if held_tag != tag:
                            observed.setdefault((held_tag, tag), set()).add(f"{where} через {callee}()")
        new_depth = depth + line.count("{") - line.count("}")
        for tag, kind, guard_name in takes:
            held.append((tag, new_depth if kind == "guard" else depth, kind, guard_name))
        # unlock снимает удержание, если после него код продолжается. unlock
        # внутри ветки, за которым идёт return/break, - это аварийный выход из
        # одного пути, а не конец критической секции для всей функции.
        for tag in gives:
            for position in range(len(held) - 1, -1, -1):
                if held[position][0] != tag:
                    continue
                if depth <= held[position][1] or not branch_exits_after(lines, index, new_depth):
                    held.pop(position)
                break
        depth = new_depth
        held = [item for item in held if not (item[2] == "guard" and depth < item[1])]
        if depth <= 0:
            held = []

for (outer, inner), places in sorted(observed.items()):
    if outer not in rank_by_tag or inner not in rank_by_tag:
        continue
    if rank_by_tag[outer] >= rank_by_tag[inner]:
        errors.append(
            f"нарушен порядок замков: {outer} (ранг {rank_by_tag[outer]}) держится, "
            f"внутри берут {inner} (ранг {rank_by_tag[inner]}); по таблице LOCK_ORDER "
            f"{inner} должен браться раньше. Места: {', '.join(sorted(places))}"
        )

if errors:
    print("Lock order smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    f"Lock order smoke check passed: {len(rank_by_tag)} замков в иерархии, "
    f"{len(observed)} вложенных пар, все сверху вниз "
    f"(анализ: внутри функции + один уровень вызовов)"
)
for (outer, inner), places in sorted(observed.items()):
    print(f"  {outer} > {inner}: {', '.join(sorted(places))}")
