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
  2. вложенность через ЛЮБОЕ число уровней вызова - если под замком вызвана функция,
     которая сама берёт замок напрямую или вызывает (вглубь, рекурсивно) что-то, что
     его берёт. Обход графа вызовов защищён от циклов (каждая функция разворачивается
     не больше раза на цепочку) и ограничен явной глубиной MAX_CALL_DEPTH - предел не
     молчаливый: если обход в него упёрся, это печатается в конце отчёта отдельной
     строкой с именами функций, которые стоит проверить дополнительно вручную.
Известные (проверенные) вложенности перечислены в комментарии "Известные вложенности"
в runtime_helpers.h - это документация для человека, а не то, что ограничивает обход.
"""
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

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


def strip_string_literals(source: str) -> str:
    """Опустошает "..." и '...', сохраняя кавычки и номера строк.

    Скобки внутри литералов (Samovar.ino печатает JSON символами '{' и '}')
    сбивали подсчёт глубины, и посреди функции глубина падала до нуля. Тогда
    следующий `if (...) {` парсер принимал за определение функции с именем "if",
    приписывал ей замки из тела этого if, а CALL_RE видел `if(` как вызов - и
    любая функция с условием оказывалась "вызывающей" псевдофункцию if. Отсюда
    брались все ложные нарушения порядка замков.
    """
    result: list[str] = []
    index = 0
    quote = ""
    escaped = False
    while index < len(source):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                result.append(char)
                quote = ""
            elif char == "\n":
                # незакрытый литерал не должен проглотить остаток файла
                result.append(char)
                quote = ""
            index += 1
            continue
        if char in "\"'":
            quote = char
        result.append(char)
        index += 1
    return "".join(result)


code_cache: dict[Path, list[str]] = {}


def read_code_lines(path: Path) -> list[str]:
    """Строки без комментариев и без содержимого литералов - для подсчёта
    скобок, имён функций и вызовов. Номера строк сохраняются."""
    if path not in code_cache:
        code_cache[path] = strip_string_literals(strip_cpp_comments(read(path))).splitlines()
    return code_cache[path]


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
# `if (!locked)` - ветка, куда попадают ИМЕННО при неудачном захвате: внутри неё
# замок не держится, хотя выше по тексту стоит строка с lock(). Без этого любой
# SendMsg в обработчике отказа выглядел как вызов под замком.
NEGATED_FLAG_RE = re.compile(r"if\s*\(\s*!\s*(\w+)\s*\)")


def branch_exits_after(lines: list[str], index: int, depth: int) -> bool:
    """True, если ветка после строки index завершается выходом, не дойдя до её конца."""
    current = depth
    for position in range(index + 1, len(lines)):
        line = lines[position]
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        # Закрывающие скобки в начале строки завершают ветку ДО того, как ниже
        # встретится выход из соседней ветки. У `} else {` баланс строки нулевой,
        # и без этой поправки continue/return из else-ветки считался выходом из
        # ветки с unlock: замок оставался "удерживаемым" до конца функции и давал
        # ложные нарушения порядка на всём, что вызывалось дальше.
        leading = len(stripped) - len(stripped.lstrip("}"))
        if current - leading < depth:
            return False
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
            match = pattern.search(line)
            if match:
                # `bool locked = runtime_state_lock(...)` - имя флага нужно, чтобы
                # ниже узнать ветку `if (!locked)`, где замок как раз НЕ взят.
                flag = re.search(r"(\w+)\s*=[^=]*$", line[:match.start()])
                takes.append((tag, "manual", flag.group(1) if flag else None))
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
# Управляющие конструкции - не функции: `if (...) {` не должен попадать в граф
# вызовов как вызываемое имя, иначе замки из его тела расползаются по всему коду.
CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch", "do", "else", "return", "sizeof"}


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
    if match is None or match.group(1) in CONTROL_KEYWORDS:
        return None
    return match.group(1)


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
    lines = read_code_lines(path)
    for name, start, end in parse_functions(lines):
        tags = set()
        for line in lines[start:end + 1]:
            for tag, _kind, _guard in line_events(line)[0]:
                tags.add(tag)
        if tags:
            direct_tags.setdefault(name, set()).update(tags)

# граф вызовов: функция -> имена функций, вызванных в её теле (по всем файлам сразу;
# короткие имена без учёта перегрузок/пространств имён - ложные срабатывания только
# расширяют проверку лишними связями, а не пропускают настоящие)
call_graph: dict[str, set[str]] = {}
for path in source_files():
    lines = read_code_lines(path)
    for name, start, end in parse_functions(lines):
        callees: set[str] = set()
        for line in lines[start:end + 1]:
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            for callee in CALL_RE.findall(line):
                if callee != name:
                    callees.add(callee)
        if callees:
            call_graph.setdefault(name, set()).update(callees)

# Обход графа вызовов вглубь: не только тело функции и не только один уровень вызова.
# Предел явный (не молчаливый) - если обход в него упёрся, это фиксируется в
# depth_limit_hit и печатается отдельной строкой в конце отчёта.
MAX_CALL_DEPTH = 6
depth_limit_hit: set[str] = set()
reachable_cache: dict[str, set[str]] = {}


def reachable_tags(start: str) -> set[str]:
    """Все теги, достижимые из start по call_graph: свои прямые захваты плюс захваты
    всех вызываемых (рекурсивно, вглубь) функций. visited защищает от зацикливания на
    рекурсии/циклах вызовов - каждая функция разворачивается не больше одного раза."""
    if start in reachable_cache:
        return reachable_cache[start]
    tags: set[str] = set(direct_tags.get(start, ()))
    visited = {start}
    frontier = [(callee, 1) for callee in call_graph.get(start, ())]
    while frontier:
        name, depth = frontier.pop()
        if name in visited:
            continue
        visited.add(name)
        tags.update(direct_tags.get(name, ()))
        if depth >= MAX_CALL_DEPTH:
            if call_graph.get(name):
                depth_limit_hit.add(start)
            continue
        for callee in call_graph.get(name, ()):
            if callee not in visited:
                frontier.append((callee, depth + 1))
    reachable_cache[start] = tags
    return tags

# ---- 4. сам анализ вложенности ---------------------------------------------
observed: dict[tuple[str, str], set[str]] = {}
for path in source_files():
    lines = read_code_lines(path)
    depth = 0
    held: list[tuple[str, int, str, str | None]] = []  # тег, глубина захвата, вид, имя стража
    suppressions: list[tuple[str, int]] = []  # тег, глубина ветки "замок не взят"
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
        new_depth = depth + line.count("{") - line.count("}")
        suppressions = [item for item in suppressions if depth >= item[1]]
        negated = NEGATED_FLAG_RE.search(line)
        if negated:
            for held_tag, _held_depth, _held_kind, flag_name in held:
                if flag_name is not None and flag_name == negated.group(1):
                    suppressions.append((held_tag, new_depth if "{" in line else depth + 1))
        muted = {tag for tag, _depth in suppressions}
        effective = [item for item in held if item[0] not in muted]
        for tag, _kind, _guard in takes:
            for held_tag, _held_depth, _held_kind, _held_name in effective:
                if held_tag != tag:
                    observed.setdefault((held_tag, tag), set()).add(where)
        if effective:
            for callee in CALL_RE.findall(line):
                for tag in reachable_tags(callee):
                    for held_tag, _held_depth, _held_kind, _held_name in effective:
                        if held_tag != tag:
                            observed.setdefault((held_tag, tag), set()).add(f"{where} через {callee}()")
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
                else:
                    # unlock в ветке, которая тут же выходит: для ОСТАЛЬНЫХ путей
                    # функции замок ещё держится, но до конца этой ветки он уже
                    # отпущен - иначе строки после unlock и до return считались бы
                    # выполняемыми под замком.
                    suppressions.append((tag, new_depth))
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

if depth_limit_hit:
    print(
        f"Обход графа вызовов упёрся в предел глубины ({MAX_CALL_DEPTH} уровней) для: "
        f"{', '.join(sorted(depth_limit_hit))} - дальше по цепочке не развернуто, "
        "проверьте эти функции дополнительно вручную."
    )

# ---- 5. отдельная проверка: спинлок configMux (T29) -------------------------
# НЕ участвует в иерархии LOCK_ORDER выше и не переиспользует её код: configMux
# - это portMUX_TYPE (спинлок FreeRTOS: отключает прерывания/планировщик на
# ядре), а не SemaphoreHandle_t/мьютекс, ранжирование мьютексов на спинлоки не
# распространяется. Проверяем независимо:
#   (а) каждая известная точка чтения/записи SamSetup/program[] обёрнута РОВНО
#       в portENTER_CRITICAL(&configMux)/portEXIT_CRITICAL(&configMux), без
#       лишнего кода между скобкой и целью;
#   (б) ни в одной critical section с &configMux по всему дереву исходников
#       нет запрещённой операции (String, SPIFFS, NVS, delay/vTaskDelay, Wire,
#       WiFi, xSemaphoreTake, malloc/new) - спинлок глушит прерывания, любая
#       блокирующая или аллоцирующая операция внутри - путь к зависанию.

CONFIGMUX_ENTER = "portENTER_CRITICAL(&configMux);"
CONFIGMUX_EXIT = "portEXIT_CRITICAL(&configMux);"

# (файл, сигнатура функции, обёрнутая целевая строка)
CONFIGMUX_SITES = [
    ("Samovar.ino", "static OperationError commit_profile_operation()",
     "SamSetup = active_profile_operation.settings;"),
    ("Samovar.ino", "static void setup_connect_wifi_and_notify()",
     "SamSetup = profileCandidate;"),
    ("WebServer.ino", "void handleSave(AsyncWebServerRequest *request)",
     "SetupEEPROM staged = SamSetup;"),
    ("beer.h", "void FinishAutoTune()",
     "SamSetup = profileCandidate;"),
    ("logic.h", "PumpCalibrationResult pump_calibrate(int stpspeed)",
     "SamSetup = profileCandidate;"),
    ("Menu.ino", "void setup_go_back()",
     "SamSetup = menuSetupCandidate;"),
    ("program_io.h",
     "inline String program_serialize_rows(uint8_t start, uint8_t end, ProgramRowSerializer serializer)",
     "memcpy(snapshot, program, sizeof(snapshot));"),
]

# здесь под спинлок обёрнуто ВСЁ тело целиком - разрывать нельзя, иначе новое
# число строк (ProgramLen) может оказаться в паре со старым содержимым program[].
WHOLE_BODY_CONFIGMUX_SITES = [
    ("program_io.h", "inline void program_commit(const ProgramDraft& draft)"),
    ("program_io.h", "inline void program_clear()"),
]


def extract_last_function_body(source: str, signature: str) -> str:
    """extract_function_body берёт ПЕРВОЕ вхождение сигнатуры в тексте - для
    функций с forward-декларацией (например commit_profile_operation()) это
    декларация, а не определение. rfind находит настоящее определение, не
    ломая случаи без декларации (там rfind и find совпадают)."""
    start = source.rfind(signature)
    if start < 0:
        raise ValueError(f"function not found: {signature}")
    return extract_function_body(source[start:], signature)


def check_configmux_wrapped(where: str, body: str, target: str) -> list[str]:
    found: list[str] = []
    idx = body.find(target)
    if idx < 0:
        return [f"{where}: не найдена целевая строка {target!r}"]
    before, after = body[:idx], body[idx + len(target):]
    enter_pos = before.rfind(CONFIGMUX_ENTER)
    if enter_pos < 0:
        found.append(f"{where}: {target!r} не обёрнута {CONFIGMUX_ENTER}")
    else:
        gap = before[enter_pos + len(CONFIGMUX_ENTER):].strip()
        if gap:
            found.append(f"{where}: между {CONFIGMUX_ENTER} и {target!r} лишний код: {gap!r}")
    exit_pos = after.find(CONFIGMUX_EXIT)
    if exit_pos < 0:
        found.append(f"{where}: {target!r} не обёрнута {CONFIGMUX_EXIT}")
    else:
        gap = after[:exit_pos].strip()
        if gap:
            found.append(f"{where}: между {target!r} и {CONFIGMUX_EXIT} лишний код: {gap!r}")
    return found


def check_configmux() -> list[str]:
    found: list[str] = []

    for filename, signature, target in CONFIGMUX_SITES:
        path = ROOT / filename
        if not path.exists():
            found.append(f"{filename}: файл не найден")
            continue
        try:
            body = extract_last_function_body(read(path), signature)
        except ValueError as exc:
            found.append(f"{filename}: {exc}")
            continue
        found.extend(check_configmux_wrapped(f"{filename}::{signature}", body, target))

    for filename, signature in WHOLE_BODY_CONFIGMUX_SITES:
        path = ROOT / filename
        if not path.exists():
            found.append(f"{filename}: файл не найден")
            continue
        try:
            body = extract_last_function_body(read(path), signature).strip()
        except ValueError as exc:
            found.append(f"{filename}: {exc}")
            continue
        if not body.startswith(CONFIGMUX_ENTER):
            found.append(f"{filename}::{signature}: тело должно начинаться с {CONFIGMUX_ENTER}")
        if not body.endswith(CONFIGMUX_EXIT):
            found.append(f"{filename}::{signature}: тело должно заканчиваться {CONFIGMUX_EXIT}")

    region_re = re.compile(re.escape(CONFIGMUX_ENTER) + r"(.*?)" + re.escape(CONFIGMUX_EXIT), re.S)
    forbidden_in_configmux = [
        (re.compile(r"\bString\b"), "String (аллокация)"),
        (re.compile(r"\bSPIFFS\b"), "SPIFFS"),
        (re.compile(r"\bPreferences\b|\bnvs_"), "NVS/Preferences"),
        (re.compile(r"\bvTaskDelay\s*\("), "vTaskDelay"),
        (re.compile(r"\bdelay\s*\("), "delay"),
        (re.compile(r"\bWire\."), "Wire (I2C)"),
        (re.compile(r"\bWiFi\."), "WiFi"),
        (re.compile(r"\bxSemaphoreTake\s*\("), "xSemaphoreTake"),
        (re.compile(r"\bmalloc\s*\(|\bnew\s+"), "malloc/new"),
    ]

    region_total = 0
    for path in source_files():
        text = strip_cpp_comments(read(path))
        for match in region_re.finditer(text):
            region_total += 1
            region = match.group(1)
            where = f"{path.relative_to(ROOT)}"
            for pattern, label in forbidden_in_configmux:
                if pattern.search(region):
                    found.append(
                        f"{where}: внутри critical section &configMux найдена запрещённая "
                        f"операция ({label}): {region.strip()!r}"
                    )

    expected_regions = len(CONFIGMUX_SITES) + len(WHOLE_BODY_CONFIGMUX_SITES)
    if region_total != expected_regions:
        found.append(
            f"найдено {region_total} critical section(s) с &configMux в исходниках, а в "
            f"CONFIGMUX_SITES/WHOLE_BODY_CONFIGMUX_SITES описано {expected_regions} - список "
            "известных точек в smoke_lock_order.py разошёлся с кодом"
        )

    return found


errors.extend(check_configmux())

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
