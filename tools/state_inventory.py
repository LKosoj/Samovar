from __future__ import annotations

import argparse
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DELIVERY_DIR = ROOT / "docs" / "result" / "delivery"
STATE_CODES_DOC = DELIVERY_DIR / "state_codes_inventory.md"
GREP_LOG_DOC = DELIVERY_DIR / "state_inventory_grep_log.md"
RUNTIME_TYPES = ROOT / "state" / "runtime_types.h"
STATUS_CODES = ROOT / "src" / "core" / "state" / "status_codes.h"
MODE_CODES = ROOT / "src" / "core" / "state" / "mode_codes.h"

SOURCE_SUFFIXES = {".h", ".cpp", ".ino"}
KEY_VARIABLES = (
    "SamovarStatusInt",
    "sam_command_sync",
    "Samovar_Mode",
    "Samovar_CR_Mode",
    "startval",
)
RELATED_FLAGS = (
    "PowerOn",
    "PauseOn",
    "program_Wait",
    "program_Pause",
    "stepper.getState()",
    "wetting_autostart",
    "boil_started",
)
STATUS_MEANINGS = {
    0: "Выключено/сброшено.",
    10: "Ректификация: активная строка программы отбора.",
    15: "Ректификация: пауза по таймеру программы.",
    20: "Ректификация: программа завершена.",
    30: "Калибровка насоса/шаговика.",
    40: "Ручная пауза отбора.",
    50: "Разгон колонны.",
    51: "Разгон завершён, идёт стабилизация/работа на себя.",
    52: "Стабилизация завершена, колонна работает на себя стабильно.",
    1000: "Режим дистилляции активен.",
    2000: "Режим пива активен.",
    3000: "Режим БК активен.",
    4000: "Режим НБК активен.",
}
STARTVAL_MEANINGS = {
    0: "Останов/idle; для rect также разгон до старта программы.",
    1: "Ректификация: активная строка программы.",
    2: "Ректификация: программа завершена, ожидается финальный переход.",
    3: "Ректификация: останов после завершения/ручного завершения.",
    100: "Режим калибровки.",
    1000: "Стартовый маркер входа в дистилляцию.",
    2000: "Стартовый маркер входа в пиво до запуска первой строки.",
    2001: "Пиво: разогрев до температуры засыпи солода.",
    2002: "Пиво: ожидание засыпи солода.",
    3000: "Стартовый маркер входа в БК.",
    4000: "Стартовый маркер входа в НБК до запуска первой строки.",
    4001: "НБК: первая программа запущена, stage-текст уже активен.",
}
COMMAND_MEANINGS = {
    "SAMOVAR_NONE": "Нет ожидающей команды.",
    "SAMOVAR_START": "Старт/следующая программа ректификации.",
    "SAMOVAR_POWER": "Переключение питания или завершение текущего режима.",
    "SAMOVAR_RESET": "Полный reset-пайплайн.",
    "CALIBRATE_START": "Старт калибровки насоса.",
    "CALIBRATE_STOP": "Останов калибровки насоса.",
    "SAMOVAR_PAUSE": "Пауза отбора.",
    "SAMOVAR_CONTINUE": "Продолжить отбор и сбросить program_Wait.",
    "SAMOVAR_SETBODYTEMP": "Зафиксировать температуру тела.",
    "SAMOVAR_DISTILLATION": "Переключить/запустить режим дистилляции.",
    "SAMOVAR_BEER": "Переключить/запустить режим пива.",
    "SAMOVAR_BEER_NEXT": "Следующая строка программы пива.",
    "SAMOVAR_BK": "Переключить/запустить режим БК.",
    "SAMOVAR_NBK": "Переключить/запустить режим НБК.",
    "SAMOVAR_SELF_TEST": "Запустить self-test.",
    "SAMOVAR_DIST_NEXT": "Следующая строка программы дистилляции.",
    "SAMOVAR_NBK_NEXT": "Следующая строка программы НБК.",
}
MODE_MEANINGS = {
    "SAMOVAR_RECTIFICATION_MODE": "Ректификация.",
    "SAMOVAR_DISTILLATION_MODE": "Дистилляция.",
    "SAMOVAR_BEER_MODE": "Пиво.",
    "SAMOVAR_BK_MODE": "Бражная колонна.",
    "SAMOVAR_NBK_MODE": "НБК.",
    "SAMOVAR_SUVID_MODE": "Су-вид.",
    "SAMOVAR_LUA_MODE": "Lua-режим.",
}
FLAG_MEANINGS = {
    "PowerOn": "Главный флаг питания: меняет трактовку почти всех status/startval и маршрутизацию команд.",
    "PauseOn": "Переводит rect в статус 40 и переключает web/menu pause/continue.",
    "program_Wait": "Различает статусы 10 и 15; сбрасывается при continue/manual resume.",
    "program_Pause": "Меняет поведение кнопки/оркестрации для rect-паузы программы.",
    "stepper.getState()": "Отделяет разгон/stabilization rect от активного отбора.",
    "wetting_autostart": "Связывает rect 51 -> 52 с автозапуском голов после смачивания.",
    "boil_started": "Уточняет внутреннюю фазу rect при статусе 51.",
}
OWNER_NOTES = {
    "mode runtime": "modes/*",
    "web routes": "ui/web/*",
    "menu actions": "ui/menu/*",
    "Lua": "ui/lua/*",
    "loop/orchestration": "app/*, io/*, Samovar.ino",
    "storage/profile": "storage/*",
    "external control": "Blynk.ino",
    "other": "прочие файлы",
}
DIRECT_OPERATORS = {"=", "==", "!="}
NUMERIC_PATTERN_TEMPLATE = r"\b{variable}\b\s*(==|!=|<=|>=|=|<|>)\s*(-?\d+)"
REVERSED_NUMERIC_PATTERN_TEMPLATE = r"(-?\d+)\s*(==|!=|<=|>=|<|>)\s*\b{variable}\b"
ENUM_PATTERN_TEMPLATE = r"enum\s+{name}\s*\{{(?P<body>.*?)\}};"
STATUS_CODE_PATTERN = re.compile(r"static constexpr int16_t (SAMOVAR_STATUS_[A-Z0-9_]+) = (-?\d+);")
STARTVAL_CODE_PATTERN = re.compile(r"static constexpr int16_t (SAMOVAR_STARTVAL_[A-Z0-9_]+) = (-?\d+);")


@dataclass(frozen=True)
class Occurrence:
    path: str
    line_no: int
    owner: str
    text: str


@dataclass(frozen=True)
class RangeOccurrence:
    value: int
    operator: str
    occurrence: Occurrence


def owner_for_path(path: str) -> str:
    if path.startswith("modes/"):
        return "mode runtime"
    if path.startswith("ui/web/"):
        return "web routes"
    if path.startswith("ui/menu/"):
        return "menu actions"
    if path.startswith("ui/lua/"):
        return "Lua"
    if path.startswith("app/") or path.startswith("io/") or path == "Samovar.ino":
        return "loop/orchestration"
    if path.startswith("storage/"):
        return "storage/profile"
    if path == "Blynk.ino":
        return "external control"
    return "other"


def tracked_source_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--", "*.h", "*.cpp", "*.ino"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    files = []
    for raw_path in result.stdout.splitlines():
        if not raw_path:
            continue
        path = ROOT / raw_path
        if path.suffix in SOURCE_SUFFIXES:
            files.append(path)
    return sorted(files)


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def find_occurrences(files: list[Path], needle: str) -> list[Occurrence]:
    if "." in needle or "(" in needle:
        pattern = re.compile(re.escape(needle))
    else:
        pattern = re.compile(rf"\b{re.escape(needle)}\b")
    matches = []
    for path in files:
        relative_path = path.relative_to(ROOT).as_posix()
        owner = owner_for_path(relative_path)
        for line_no, line in enumerate(read_lines(path), start=1):
            if pattern.search(line):
                matches.append(
                    Occurrence(
                        path=relative_path,
                        line_no=line_no,
                        owner=owner,
                        text=line.strip(),
                    )
                )
    return matches


def find_variable_token_occurrences(files: list[Path], variable: str, token: str) -> list[Occurrence]:
    pattern = re.compile(
        rf"(\b{re.escape(variable)}\b.*\b{re.escape(token)}\b)|(\b{re.escape(token)}\b.*\b{re.escape(variable)}\b)"
    )
    matches = []
    for path in files:
        relative_path = path.relative_to(ROOT).as_posix()
        owner = owner_for_path(relative_path)
        for line_no, line in enumerate(read_lines(path), start=1):
            if pattern.search(line):
                matches.append(
                    Occurrence(
                        path=relative_path,
                        line_no=line_no,
                        owner=owner,
                        text=line.strip(),
                    )
                )
    return matches


def collect_numeric_matches(files: list[Path], variable: str) -> tuple[dict[int, list[Occurrence]], list[RangeOccurrence]]:
    direct_values: dict[int, list[Occurrence]] = defaultdict(list)
    range_values: list[RangeOccurrence] = []
    forward = re.compile(NUMERIC_PATTERN_TEMPLATE.format(variable=re.escape(variable)))
    reversed_pattern = re.compile(REVERSED_NUMERIC_PATTERN_TEMPLATE.format(variable=re.escape(variable)))
    for path in files:
        relative_path = path.relative_to(ROOT).as_posix()
        owner = owner_for_path(relative_path)
        for line_no, line in enumerate(read_lines(path), start=1):
            occurrence = Occurrence(
                path=relative_path,
                line_no=line_no,
                owner=owner,
                text=line.strip(),
            )
            for match in forward.finditer(line):
                operator = match.group(1)
                value = int(match.group(2))
                if operator in DIRECT_OPERATORS:
                    direct_values[value].append(occurrence)
                else:
                    range_values.append(RangeOccurrence(value=value, operator=operator, occurrence=occurrence))
            for match in reversed_pattern.finditer(line):
                value = int(match.group(1))
                operator = match.group(2)
                if operator in DIRECT_OPERATORS:
                    direct_values[value].append(occurrence)
                else:
                    range_values.append(RangeOccurrence(value=value, operator=operator, occurrence=occurrence))
    return dict(sorted(direct_values.items())), range_values


def parse_enum(enum_name: str) -> dict[str, int]:
    body = None
    source = None
    for path in (STATUS_CODES, MODE_CODES, RUNTIME_TYPES):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        match = re.search(ENUM_PATTERN_TEMPLATE.format(name=re.escape(enum_name)), text, re.DOTALL)
        if match is not None:
            body = match.group("body")
            source = path
            break
    if body is None or source is None:
        raise ValueError(f"Enum {enum_name} not found in {STATUS_CODES}, {MODE_CODES} or {RUNTIME_TYPES}")
    values: dict[str, int] = {}
    next_value = 0
    for raw_item in body.split(","):
        item = raw_item.strip()
        if not item:
            continue
        item = re.sub(r"//.*", "", item).strip()
        if not item:
            continue
        if "=" in item:
            name, raw_value = [part.strip() for part in item.split("=", 1)]
            next_value = int(raw_value, 0)
        else:
            name = item
        values[name] = next_value
        next_value += 1
    return values


def parse_status_codes() -> dict[str, int]:
    text = STATUS_CODES.read_text(encoding="utf-8")
    values = {name: int(raw_value) for name, raw_value in STATUS_CODE_PATTERN.findall(text)}
    if not values:
        raise ValueError(f"Status codes not found in {STATUS_CODES}")
    return values


def parse_startval_codes() -> dict[str, int]:
    text = MODE_CODES.read_text(encoding="utf-8")
    values = {name: int(raw_value) for name, raw_value in STARTVAL_CODE_PATTERN.findall(text)}
    if not values:
        raise ValueError(f"Startval codes not found in {MODE_CODES}")
    return values


def dedupe_occurrences(occurrences: list[Occurrence]) -> list[Occurrence]:
    seen = set()
    unique = []
    for occurrence in occurrences:
        key = (occurrence.path, occurrence.line_no)
        if key in seen:
            continue
        seen.add(key)
        unique.append(occurrence)
    return unique


def format_refs(occurrences: list[Occurrence]) -> str:
    grouped: dict[str, list[int]] = defaultdict(list)
    for occurrence in dedupe_occurrences(occurrences):
        grouped[occurrence.path].append(occurrence.line_no)
    chunks = []
    for path in sorted(grouped):
        line_list = ",".join(str(line) for line in sorted(set(grouped[path])))
        chunks.append(f"`{path}:{line_list}`")
    return "; ".join(chunks) if chunks else "—"


def format_owners(occurrences: list[Occurrence]) -> str:
    owners = sorted({occurrence.owner for occurrence in occurrences})
    return ", ".join(owners) if owners else "—"


def render_variable_value_table(
    variable: str,
    meanings: dict[int, str],
    values_to_occurrences: dict[int, list[Occurrence]],
    tokens_by_value: dict[int, str],
) -> str:
    lines = [
        "| Число | Токен | Смысл | Владельцы | Где используется |",
        "| --- | --- | --- | --- | --- |",
    ]
    for value in meanings:
        occurrences = values_to_occurrences.get(value, [])
        token = tokens_by_value.get(value)
        if token is None:
            raise ValueError(f"{variable}: missing token for value {value}")
        lines.append(
            f"| `{value}` | `{token}` | {meanings[value]} | {format_owners(occurrences)} | {format_refs(occurrences)} |"
        )
    missing = [value for value in values_to_occurrences if value not in meanings]
    if missing:
        raise ValueError(f"{variable}: missing meaning for values {missing}")
    return "\n".join(lines)


def render_range_table(range_occurrences: list[RangeOccurrence]) -> str:
    if not range_occurrences:
        return "_Raw numeric range-comparisons по этой переменной не найдены; оставшаяся семантика вынесена в именованные helper-предикаты в state headers._"
    lines = [
        "| Граница | Оператор | Владельцы | Где используется |",
        "| --- | --- | --- | --- |",
    ]
    grouped: dict[tuple[int, str], list[Occurrence]] = defaultdict(list)
    for item in range_occurrences:
        grouped[(item.value, item.operator)].append(item.occurrence)
    for value, operator in sorted(grouped):
        occurrences = grouped[(value, operator)]
        lines.append(
            f"| `{value}` | `{operator}` | {format_owners(occurrences)} | {format_refs(occurrences)} |"
        )
    return "\n".join(lines)


def render_enum_table(
    enum_values: dict[str, int],
    meanings: dict[str, str],
    token_occurrences: dict[str, list[Occurrence]],
) -> str:
    lines = [
        "| Число | Токен | Смысл | Владельцы | Где используется |",
        "| --- | --- | --- | --- | --- |",
    ]
    for token, value in enum_values.items():
        occurrences = token_occurrences.get(token, [])
        meaning = meanings.get(token)
        if meaning is None:
            raise ValueError(f"Missing meaning for {token}")
        lines.append(
            f"| `{value}` | `{token}` | {meaning} | {format_owners(occurrences)} | {format_refs(occurrences)} |"
        )
    return "\n".join(lines)


def render_flag_table(flag_occurrences: dict[str, list[Occurrence]]) -> str:
    lines = [
        "| Флаг | Роль в state-модели | Владельцы | Где используется |",
        "| --- | --- | --- | --- |",
    ]
    for flag in RELATED_FLAGS:
        occurrences = flag_occurrences.get(flag, [])
        lines.append(
            f"| `{flag}` | {FLAG_MEANINGS[flag]} | {format_owners(occurrences)} | {format_refs(occurrences)} |"
        )
    return "\n".join(lines)


def render_owner_summary(all_occurrences: dict[str, list[Occurrence]]) -> str:
    grouped: dict[str, set[str]] = defaultdict(set)
    for occurrences in all_occurrences.values():
        for occurrence in occurrences:
            grouped[occurrence.owner].add(occurrence.path)
    lines = []
    for owner in (
        "mode runtime",
        "web routes",
        "menu actions",
        "Lua",
        "loop/orchestration",
        "storage/profile",
        "external control",
        "other",
    ):
        paths = ", ".join(f"`{path}`" for path in sorted(grouped.get(owner, set())))
        if not paths:
            paths = "—"
        lines.append(f"- `{owner}` ({OWNER_NOTES[owner]}): {paths}")
    return "\n".join(lines)


def render_grep_section(title: str, occurrences: list[Occurrence]) -> str:
    lines = [f"## {title}", ""]
    if not occurrences:
        lines.append("_Совпадения не найдены._")
        return "\n".join(lines)
    lines.append("```text")
    for occurrence in occurrences:
        lines.append(f"{occurrence.path}:{occurrence.line_no}: {occurrence.text}")
    lines.append("```")
    return "\n".join(lines)


def build_inventory() -> dict[str, object]:
    files = tracked_source_files()
    status_tokens = parse_status_codes()
    start_tokens = parse_startval_codes()
    status_values = defaultdict(list)
    for token, value in status_tokens.items():
        status_values[value].extend(find_occurrences(files, token))
    status_values = dict(sorted(status_values.items()))
    _, status_ranges = collect_numeric_matches(files, "SamovarStatusInt")
    start_values = defaultdict(list)
    for token, value in start_tokens.items():
        start_values[value].extend(find_occurrences(files, token))
    start_values = dict(sorted(start_values.items()))
    _, start_ranges = collect_numeric_matches(files, "startval")
    command_enum = parse_enum("SamovarCommands")
    mode_enum = parse_enum("SAMOVAR_MODE")

    all_occurrences = {variable: find_occurrences(files, variable) for variable in KEY_VARIABLES}
    flag_occurrences = {flag: find_occurrences(files, flag) for flag in RELATED_FLAGS}
    command_token_occurrences = {token: find_occurrences(files, token) for token in command_enum}
    mode_token_occurrences = {token: find_occurrences(files, token) for token in mode_enum}
    mode_variable_occurrences = {
        "Samovar_Mode": {
            token: find_variable_token_occurrences(files, "Samovar_Mode", token)
            for token in mode_enum
        },
        "Samovar_CR_Mode": {
            token: find_variable_token_occurrences(files, "Samovar_CR_Mode", token)
            for token in mode_enum
        },
    }

    return {
        "files": [path.relative_to(ROOT).as_posix() for path in files],
        "all_occurrences": all_occurrences,
        "status_tokens": status_tokens,
        "status_values": status_values,
        "status_ranges": status_ranges,
        "start_tokens": start_tokens,
        "start_values": start_values,
        "start_ranges": start_ranges,
        "command_enum": command_enum,
        "mode_enum": mode_enum,
        "command_token_occurrences": command_token_occurrences,
        "mode_token_occurrences": mode_token_occurrences,
        "mode_variable_occurrences": mode_variable_occurrences,
        "flag_occurrences": flag_occurrences,
    }


def render_state_codes_inventory(inventory: dict[str, object]) -> str:
    files = inventory["files"]
    status_values = inventory["status_values"]
    start_values = inventory["start_values"]
    command_enum = inventory["command_enum"]
    mode_enum = inventory["mode_enum"]
    command_token_occurrences = inventory["command_token_occurrences"]
    mode_variable_occurrences = inventory["mode_variable_occurrences"]
    flag_occurrences = inventory["flag_occurrences"]
    all_occurrences = inventory["all_occurrences"]
    status_ranges = inventory["status_ranges"]
    start_ranges = inventory["start_ranges"]
    status_tokens_by_value = {value: token for token, value in inventory["status_tokens"].items()}
    start_tokens_by_value = {value: token for token, value in inventory["start_tokens"].items()}

    parts = [
        "# Шаг 2.1. Инвентаризация state-кодов Samovar",
        "",
        "## Scope",
        "",
        f"- Просканировано `*.h/*.cpp/*.ino`: `{len(files)}` файлов из git-дерева.",
        "- Source of truth для status/command: `src/core/state/status_codes.h`.",
        "- Source of truth для mode/startval: `src/core/state/mode_codes.h`.",
        "- Source of truth для runtime-диспетча и входа в режимы: `app/loop_dispatch.h`, `app/orchestration.h`.",
        "- Source of truth для текстовой интерпретации статусов: `app/status_text.h`.",
        "",
        "## Владельцы",
        "",
        render_owner_summary(all_occurrences),
        "",
        "## SamovarStatusInt",
        "",
        render_variable_value_table("SamovarStatusInt", STATUS_MEANINGS, status_values, status_tokens_by_value),
        "",
        "### SamovarStatusInt: диапазонные и compound-предикаты",
        "",
        render_range_table(status_ranges),
        "",
        "## startval",
        "",
        render_variable_value_table("startval", STARTVAL_MEANINGS, start_values, start_tokens_by_value),
        "",
        "### startval: диапазонные и compound-предикаты",
        "",
        render_range_table(start_ranges),
        "",
        "## sam_command_sync",
        "",
        render_enum_table(command_enum, COMMAND_MEANINGS, command_token_occurrences),
        "",
        "## Samovar_Mode",
        "",
        render_enum_table(mode_enum, MODE_MEANINGS, mode_variable_occurrences["Samovar_Mode"]),
        "",
        "## Samovar_CR_Mode",
        "",
        "Samovar_CR_Mode использует тот же enum `SAMOVAR_MODE`, но применяется как канонический режим для web-страницы, Lua-family и NVS-profile namespace.",
        "",
        render_enum_table(mode_enum, MODE_MEANINGS, mode_variable_occurrences["Samovar_CR_Mode"]),
        "",
        "### Прямые точки использования Samovar_CR_Mode",
        "",
        "| Переменная | Владельцы | Где используется |",
        "| --- | --- | --- |",
        f"| `Samovar_CR_Mode` | {format_owners(all_occurrences['Samovar_CR_Mode'])} | {format_refs(all_occurrences['Samovar_CR_Mode'])} |",
        "",
        "## Связанные флаги",
        "",
        render_flag_table(flag_occurrences),
        "",
        "## Helper-предикаты state semantics",
        "",
        "- `samovar_status_is_rectification(status)` — именует rect-family диапазон `status > OFF && status < DISTILLATION` для runtime dispatch и menu/orchestration.",
        "- `samovar_status_allows_rectification_withdrawal(status)` — заменяет повторяющиеся проверки статусов `RUN/WAIT/PAUSE` в rect runtime и UI snapshot/status text.",
        "- `samovar_status_has_rectification_program_progress(status)` — именует более узкую rect-semantics `RUN/WAIT` там, где pause не должна считаться активным прогрессом программы.",
        "- `startval_is_rect_program_state(value)` — именует rect program-state диапазон `1..3` для внешнего контроля/Blynk.",
        "- `startval_is_active_non_calibration(value)` — именует запрет калибровки во всех активных state, кроме отдельного calibration-state.",
        "- `startval_is_beer_program_started(value)` — именует границу между beer entry и уже идущими beer steps.",
        "",
        "## Примечания по baseline",
        "",
        "- `50/51/52` существуют только в rect-runtime и появляются не отдельной командой, а через сочетание `PowerOn`, `startval == SAMOVAR_STARTVAL_RECT_IDLE`, `stepper.getState()`, температур и стабилизации.",
        "- `2000/2001/2002` описывают lifecycle режима пива: вход в режим -> разогрев до засыпи -> ожидание засыпи.",
        "- `4000/4001` описывают lifecycle НБК: вход в режим -> запуск первой программы; при этом `SamovarStatusInt` остаётся `4000`, а деталь фазы хранится в `startval`.",
    ]
    return "\n".join(parts).rstrip() + "\n"


def render_state_inventory_grep_log(inventory: dict[str, object]) -> str:
    sections = [
        "# Grep baseline: state inventory",
        "",
        "Поиск выполнен по всем git-tracked `*.h/*.cpp/*.ino` файлам. Ниже сохранены все прямые вхождения ключевых state-переменных и связанных флагов.",
        "",
    ]
    all_occurrences = inventory["all_occurrences"]
    for variable in KEY_VARIABLES:
        sections.append(render_grep_section(variable, all_occurrences[variable]))
        sections.append("")

    sections.append("# Related Flags")
    sections.append("")
    flag_occurrences = inventory["flag_occurrences"]
    for flag in RELATED_FLAGS:
        sections.append(render_grep_section(flag, flag_occurrences[flag]))
        sections.append("")

    sections.append("# Enum Tokens")
    sections.append("")
    command_enum = inventory["command_enum"]
    for token in command_enum:
        sections.append(render_grep_section(token, inventory["command_token_occurrences"][token]))
        sections.append("")
    mode_enum = inventory["mode_enum"]
    for token in mode_enum:
        sections.append(render_grep_section(token, inventory["mode_token_occurrences"][token]))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def write_docs() -> None:
    inventory = build_inventory()
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_CODES_DOC.write_text(render_state_codes_inventory(inventory), encoding="utf-8")
    GREP_LOG_DOC.write_text(render_state_inventory_grep_log(inventory), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate state inventory delivery docs.")
    parser.add_argument("--write", action="store_true", help="Write delivery docs to docs/result/delivery")
    args = parser.parse_args()
    if args.write:
        write_docs()
        return
    inventory = build_inventory()
    print(render_state_codes_inventory(inventory), end="")


if __name__ == "__main__":
    main()
