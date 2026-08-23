#!/usr/bin/env python3
"""
Пин мёртвой условной компиляции (WP11, пункт 42).

Четыре флага ниже управляют кодом, который сегодня не участвует ни в одной
сборке: ни один из 7 окружений platformio.ini их не определяет, и нигде в
исходниках нет "живого" (не закомментированного) #define для них. Флаги
подробно описаны прямо в Samovar.h рядом с местом их использования — см.
блоки "--- Отключённая подсистема: ... ---".

Смысл этого теста — не в самом факте "код мёртв" (это осознанное решение,
см. Samovar.h), а в том, чтобы будущее включение флага (в platformio.ini,
Samovar_ini.h, user_config_override.h или прямо в Samovar.h) не прошло
незамеченным: как только флаг где-то реально определится, тест покраснеет
и потребует осознанного решения, а не тихого "само включилось".

Список имён флагов ниже — это то самое, что пинится; сами факты "определён
или нет" тест каждый раз вычисляет заново по реальным файлам репозитория.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEAD_FLAGS = [
    "USE_CRASH_HANDLER",
    "USE_WATER_VALVE",
    "COLUMN_WETTING",
    "USE_STEPPER_ACCELERATION",
]

# Источники, где флаг мог бы стать "живым" #define (не считая platformio.ini,
# который разбирается отдельно ниже).
DEFINE_SOURCE_FILES = [
    "Samovar.h",
    "Samovar_ini.h",
    "user_config_override.h",
]

errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def active_define_lines(text: str, flag: str) -> list[str]:
    """Строки вида '#define FLAG...', не закомментированные через // или ;."""
    hits = []
    pattern = re.compile(rf"^\s*#\s*define\s+{re.escape(flag)}\b")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith(";"):
            continue
        if pattern.match(line):
            hits.append(line.strip())
    return hits


def parse_environments(ini_text: str) -> dict[str, str]:
    """env name -> сырой текст секции (без заголовка [env:...])."""
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in ini_text.splitlines():
        header = re.match(r"^\[env:([A-Za-z0-9_]+)\]\s*$", line.strip())
        if header:
            if current is not None:
                sections[current] = "\n".join(buf)
            current = header.group(1)
            buf = []
            continue
        if re.match(r"^\[[^\]]+\]\s*$", line.strip()):
            if current is not None:
                sections[current] = "\n".join(buf)
            current = None
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf)
    return sections


def effective_text(name: str, sections: dict[str, str], seen: set[str] | None = None) -> str:
    """Текст секции + текст родителя(ей) по extends (для поиска -D в build_flags)."""
    if seen is None:
        seen = set()
    if name in seen or name not in sections:
        return ""
    seen.add(name)
    text = sections[name]
    parts = [text]
    for m in re.finditer(r"^\s*extends\s*=\s*env:([A-Za-z0-9_]+)", text, re.MULTILINE):
        parts.append(effective_text(m.group(1), sections, seen))
    return "\n".join(parts)


EXPECTED_ENVIRONMENTS = [
    "Samovar",
    "Samovar_s3",
    "Samovar_no_power",
    "Samovar_rmvk",
    "Samovar_sem",
    "Samovar_lua_mqtt",
    "Samovar_alarm_button",
]

ini_text = read_text("platformio.ini")
sections = parse_environments(ini_text) if ini_text else {}

if ini_text:
    missing_envs = [e for e in EXPECTED_ENVIRONMENTS if e not in sections]
    extra_envs = [e for e in sections if e not in EXPECTED_ENVIRONMENTS]
    if missing_envs:
        errors.append(
            "platformio.ini: ожидаемые окружения не найдены (проверь список EXPECTED_ENVIRONMENTS "
            "в этом тесте, если окружение переименовали намеренно): " + ", ".join(missing_envs)
        )
    if extra_envs:
        errors.append(
            "platformio.ini: обнаружены НОВЫЕ окружения, не учтённые этим тестом "
            "(добавь их в EXPECTED_ENVIRONMENTS и перепроверь список DEAD_FLAGS): " + ", ".join(extra_envs)
        )

    for flag in DEAD_FLAGS:
        define_token = re.compile(rf"-D{re.escape(flag)}(=|\b)")
        offenders = []
        for env_name in sorted(sections):
            text = effective_text(env_name, sections)
            if define_token.search(text):
                offenders.append(env_name)
        if offenders:
            errors.append(
                f"{flag} определён через -D в build_flags окружений: {', '.join(offenders)} "
                "— подсистема больше не мёртвый код, обнови Samovar.h и этот тест"
            )

# Источники вне platformio.ini, где флаг мог бы стать "живым" #define.
for flag in DEAD_FLAGS:
    live_hits = []
    for source in DEFINE_SOURCE_FILES:
        text = read_text(source)
        if not text:
            continue
        hits = active_define_lines(text, flag)
        if hits:
            live_hits.append(f"{source}: {hits[0]}")
    if live_hits:
        errors.append(
            f"{flag} стал живым #define вне platformio.ini: " + "; ".join(live_hits) +
            " — подсистема больше не мёртвый код, обнови Samovar.h и этот тест"
        )

if errors:
    print("dead config flags smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    "dead config flags smoke passed: "
    f"{len(DEAD_FLAGS)} флагов ({', '.join(DEAD_FLAGS)}) по-прежнему не определены "
    f"ни в одном из {len(EXPECTED_ENVIRONMENTS)} окружений platformio.ini и нигде в исходниках"
)
