#!/usr/bin/env python3
"""Статическая проверка: библиотека Blynk не потокобезопасна, а её дёргают из
задачи GetClockTicker (triggerGetClock), из tick_blynk() (loop(), core 1),
из apply_config_runtime() (setup() и рантайм-применение профиля) и из колбэка
ArduinoOTA.onStart. Общий xBlynkSemaphore/BlynkLockGuard (runtime_helpers.h)
должен покрывать КАЖДОЕ обращение к Blynk во всех четырёх местах - иначе
гонка, которую фикс должен был закрыть, возвращается тихо, без единого
предупреждения компилятора.

Тест вытаскивает РЕАЛЬНЫЕ тела этих четырёх мест из Samovar.ino и проверяет
вложенность скобок: каждое вхождение "Blynk." обязано находиться внутри
области видимости, где уже объявлен BlynkLockGuard (тот же приём, что и в
tools/smoke_lock_order.py - учёт глубины { } с пропуском строковых/
символьных литералов). setup() из проверки сознательно исключён - Blynk.config/
Blynk.connect там выполняются до старта задач, когда конкурировать ещё некому
(см. комментарий в Samovar.ino рядом с этими вызовами).

Тест обязан падать, если кто-то добавит в любое из четырёх мест голый
вызов Blynk.* мимо BlynkLockGuard - тем самым проверяется мутацией ниже.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

FUNCTIONS = {
    "triggerGetClock (задача GetClockTicker)": "void triggerGetClock(void *parameter)",
    "tick_blynk": "static void tick_blynk()",
    "apply_config_runtime": "void apply_config_runtime()",
    "ArduinoOTA.onStart callback": "ArduinoOTA.onStart([]() {",
}

GUARD_TOKEN = "BlynkLockGuard"
CALL_TOKEN = "Blynk."


def _is_word_boundary_before(text: str, index: int) -> bool:
    if index == 0:
        return True
    previous = text[index - 1]
    return not (previous.isalnum() or previous == "_")


def find_unprotected_calls(body: str) -> list[tuple[int, str]]:
    """Возвращает [(строка, фрагмент)] для "Blynk.", встреченных вне области
    видимости уже объявленного BlynkLockGuard."""
    depth = 0
    guard_depths: list[int] = []
    problems: list[tuple[int, str]] = []
    in_string = False
    in_char = False
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if in_char:
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                in_char = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "'":
            in_char = True
            i += 1
            continue
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth -= 1
            guard_depths = [g for g in guard_depths if g <= depth]
            i += 1
            continue
        if body.startswith(GUARD_TOKEN, i) and _is_word_boundary_before(body, i):
            guard_depths.append(depth)
            i += len(GUARD_TOKEN)
            continue
        if body.startswith(CALL_TOKEN, i) and _is_word_boundary_before(body, i):
            if not guard_depths:
                line_no = body.count("\n", 0, i) + 1
                snippet = body[i:i + 40].splitlines()[0].strip()
                problems.append((line_no, snippet))
            i += len(CALL_TOKEN)
            continue
        i += 1
    return problems


def check_source(source: str, label: str, signature: str, errors: list[str]) -> str:
    try:
        body = extract_function_body(source, signature)
    except ValueError as error:
        errors.append(f"{label}: {error}")
        return ""
    if CALL_TOKEN not in body:
        errors.append(f"{label}: 'Blynk.' не найден в теле - проверять нечего, сигнатура протухла?")
        return body
    for line_no, snippet in find_unprotected_calls(body):
        errors.append(
            f"{label}: строка {line_no} тела: '{snippet}' - обращение к Blynk вне BlynkLockGuard"
        )
    return body


def main() -> int:
    source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    errors: list[str] = []
    bodies: dict[str, str] = {}
    for label, signature in FUNCTIONS.items():
        bodies[label] = check_source(source, label, signature, errors)
    if errors:
        print("Blynk lock coverage smoke check failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    # Мутация: в теле tick_blynk() вырезаем объявление BlynkLockGuard, оставляя
    # голый Blynk.run() - имитация "кто-то убрал лок". Сканер обязан это поймать.
    tick_blynk_body = bodies["tick_blynk"]
    guard_line = "BlynkLockGuard blynkLock(pdMS_TO_TICKS(20));"
    if guard_line not in tick_blynk_body:
        print(f"FAIL: mutation anchor missing in tick_blynk(): {guard_line!r}", file=sys.stderr)
        return 1
    mutated = tick_blynk_body.replace(guard_line, "", 1)
    mutated_problems = find_unprotected_calls(mutated)
    if not mutated_problems:
        print("FAIL: removing BlynkLockGuard from tick_blynk() was not detected (mutation survived)",
              file=sys.stderr)
        return 1

    print(
        f"Blynk lock coverage smoke check passed: {len(FUNCTIONS)} функции проверены, "
        f"мутация (снятие BlynkLockGuard) поймана"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
