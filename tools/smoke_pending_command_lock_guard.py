#!/usr/bin/env python3
"""Замок отложенных команд берётся только через RAII-страж.

Раньше в 40 местах замок брали и отпускали вручную: bool locked = ...; ... ;
pending_command_unlock(locked). Любой новый ранний return между этими строками
оставлял замок захваченным навсегда - самовар переставал принимать команды.
PendingCommandLockGuard отпускает замок в деструкторе, поэтому забыть нельзя.

Тест следит, чтобы ручной способ не вернулся обратно.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

GUARD_HOME = "runtime_helpers.h"
SKIP_PREFIXES = ("lib", ".pio", ".git", "tools", "data", "doc", "pro_mini", "libraries", "ai_docs")
SOURCE_SUFFIXES = {".ino", ".h", ".cpp"}


def source_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        if path.relative_to(ROOT).as_posix().startswith(SKIP_PREFIXES):
            continue
        files.append(path)
    return files


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


helpers = read(ROOT / GUARD_HOME)

# ---- 1. страж определён и устроен правильно ---------------------------------
for token in [
    "struct PendingCommandLockGuard {",
    "explicit PendingCommandLockGuard(TickType_t timeout = pdMS_TO_TICKS(50))",
    ": acquired(pending_command_lock(timeout)) {}",
    "~PendingCommandLockGuard() { pending_command_unlock(acquired); }",
    "PendingCommandLockGuard(const PendingCommandLockGuard&) = delete;",
    "PendingCommandLockGuard& operator=(const PendingCommandLockGuard&) = delete;",
    "explicit operator bool() const { return acquired; }",
]:
    if token not in helpers:
        errors.append(f"{GUARD_HOME}: нет обязательной части стража: {token}")

release_match = re.search(
    r"void\s+release\s*\(\)\s*\{(.*?)\}", helpers, re.DOTALL
)
if release_match is None:
    errors.append(f"{GUARD_HOME}: у стража нет release() для досрочного освобождения")
else:
    body = release_match.group(1)
    if "pending_command_unlock(acquired)" not in body:
        errors.append(f"{GUARD_HOME}: release() не отпускает замок")
    if "acquired = false" not in body:
        errors.append(
            f"{GUARD_HOME}: release() не сбрасывает acquired - деструктор отпустит замок повторно"
        )

# ---- 2. ручные вызовы остались только внутри стража -------------------------
manual_call = re.compile(r"(?<![\w])pending_command_(lock|unlock)\s*\(")
guard_home_allowed = {
    "inline bool pending_command_lock(TickType_t timeout = pdMS_TO_TICKS(50)) {",
    "inline void pending_command_unlock(bool locked) {",
    ": acquired(pending_command_lock(timeout)) {}",
    "~PendingCommandLockGuard() { pending_command_unlock(acquired); }",
    "pending_command_unlock(acquired);",
}
guard_users: list[str] = []
for path in source_files():
    relative = path.relative_to(ROOT).as_posix()
    lines = read(path).splitlines()
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        code = line.split("//", 1)[0] if not stripped.startswith("*") else ""
        if manual_call.search(code):
            if relative == GUARD_HOME and stripped in guard_home_allowed:
                continue
            errors.append(
                f"{relative}:{number}: замок берут вручную - используйте "
                f"PendingCommandLockGuard: {stripped}"
            )
        if re.search(r"(?<![\w])PendingCommandLockGuard\s+\w+", code) and "struct" not in code:
            guard_users.append(f"{relative}:{number}")
            if re.match(r"^\s*static\s", line):
                errors.append(
                    f"{relative}:{number}: страж объявлен static - замок останется "
                    f"захваченным после выхода из функции"
                )

# ---- 3. страж виден всем, кто им пользуется ---------------------------------
users_by_file = {place.split(":")[0] for place in guard_users}
for relative in sorted(users_by_file):
    if relative == GUARD_HOME:
        continue
    text = read(ROOT / relative)
    if '#include "runtime_helpers.h"' not in text:
        # .ino-файлы Arduino склеивает, но заголовки обязаны включать явно
        if relative.endswith(".h"):
            errors.append(f"{relative}: использует страж, но не включает runtime_helpers.h")

if not guard_users:
    errors.append("PendingCommandLockGuard нигде не используется")

if errors:
    print("Pending command lock guard smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    f"Pending command lock guard smoke check passed: "
    f"{len(guard_users)} захватов через страж в {len(users_by_file)} файлах, "
    f"ручных вызовов вне {GUARD_HOME} нет"
)
