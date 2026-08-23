#!/usr/bin/env python3
"""WP10 п.31: имя текущего Lua-скрипта (lua_type_script, String) не должно читаться
или писаться без защиты между задачами.

Факты, установленные до правки (python-поиском по всему репозиторию, см. отчёт):
  - lua_type_script объявлена в lua.h как обычная String (не под примитивом
    ОС) - присваивание пересоздаёт буфер: старый освобождается, новый выделяется.
  - Пишет её код, который выполняется в задаче loop() (Arduino loopTask):
    commit_profile_operation() в Samovar.ino, вызывается только из
    process_profile_operation(), которая вызывается только из loop().
  - Читает её без своей копии задача do_lua_script() (lua.h) - отдельная
    FreeRTOS-задача, созданная xTaskCreatePinnedToCore(do_lua_script, ...) - в
    двух WriteConsoleLog при периодическом прогоне скриптов.
  - Единственный ДРУГОЙ писатель - lua_init() (lua.h): пишет lua_type_script
    ДО создания задачи do_lua_script(), то есть до того как читатель вообще
    начинает существовать - гонки там нет структурно, чинить нечего.
  - Минимальное решение: защитить write в Samovar.ino существующим замком Lua
    (xLuaSemaphore/lua_state_lock) - do_lua_script() уже читает поле внутри
    lua_state_lock(portMAX_DELAY)/lua_state_unlock() при периодическом прогоне,
    так что оборачивание записи тем же замком закрывает гонку без новой
    примитивной синхронизации. load_lua_script() сама берёт lua_state_lock
    внутри себя - значит запись обязана ОТПУСТИТЬ лок ДО вызова
    load_lua_script(), иначе это рекурсивный захват того же (нерекурсивного)
    мьютекса и мгновенный deadlock.

Тест проверяет эти инварианты структурно на РЕАЛЬНОМ исходнике.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

samovar_text = strip_cpp_comments((ROOT / "Samovar.ino").read_text(encoding="utf-8"))
lua_text = strip_cpp_comments((ROOT / "lua.h").read_text(encoding="utf-8"))


def function_body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError:
        return ""


# ---- 1. запись в commit_profile_operation() защищена и не создаёт рекурсии ----
commit_body = function_body(
    samovar_text, "static OperationError commit_profile_operation() {"
)
if not commit_body:
    errors.append("Samovar.ino: commit_profile_operation() не найдена")
else:
    require_ordered_tokens(
        "commit_profile_operation",
        commit_body,
        [
            "lua_state_lock(portMAX_DELAY)",
            "lua_type_script = get_lua_mode_name();",
            "lua_state_unlock(",
            # unlock обязан идти РАНЬШЕ load_lua_script(): она сама берёт
            # lua_state_lock, повторный захват того же мьютекса той же задачей -
            # мгновенный deadlock (мьютекс не рекурсивен).
            "load_lua_script();",
        ],
        errors,
    )

# ---- 2. do_lua_script() читает lua_type_script только под lua_state_lock -----
do_lua_script_body = function_body(lua_text, "void do_lua_script(void *parameter)")
if not do_lua_script_body:
    errors.append("lua.h: do_lua_script() не найдена")
else:
    # Периодический прогон: lua_locked берётся один раз на весь блок и
    # отпускается в конце - оба чтения lua_type_script (в WriteConsoleLog)
    # обязаны лежать между этими двумя точками.
    lock_index = do_lua_script_body.find("lua_state_lock(portMAX_DELAY)")
    read_indices = []
    offset = 0
    while True:
        index = do_lua_script_body.find("lua_type_script", offset)
        if index < 0:
            break
        read_indices.append(index)
        offset = index + len("lua_type_script")
    unlock_index = do_lua_script_body.find(
        "lua_state_unlock(lua_locked)",
        max(read_indices, default=0),
    )
    if lock_index < 0 or not read_indices or unlock_index < 0:
        errors.append(
            "lua.h: do_lua_script() - не нашли ожидаемую структуру "
            "lock/read(lua_type_script)/unlock в периодическом прогоне"
        )
    else:
        for read_index in read_indices:
            if not (lock_index < read_index < unlock_index):
                errors.append(
                    f"lua.h: do_lua_script() читает lua_type_script (смещение "
                    f"{read_index} в теле функции) вне окна "
                    f"lua_state_lock(...)/lua_state_unlock(...) - гонка с "
                    f"писателем в loop()"
                )

# ---- 3. lua_init(): первичная запись до создания задачи-читателя -------------
# Эта запись структурно безопасна без замка: задача do_lua_script() ещё не
# существует. Тест это фиксирует, чтобы будущий рефакторинг не переставил
# xTaskCreatePinnedToCore(do_lua_script, ...) выше записи.
lua_init_body = function_body(lua_text, "void lua_init()")
if not lua_init_body:
    errors.append("lua.h: lua_init() не найдена")
else:
    require_ordered_tokens(
        "lua_init",
        lua_init_body,
        [
            "lua_type_script = get_lua_mode_name();",
            "xTaskCreatePinnedToCore(",
            "do_lua_script,",
        ],
        errors,
    )

if errors:
    print("lua_type_script race smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    "lua_type_script race smoke check passed: запись в commit_profile_operation() "
    "под lua_state_lock без рекурсии, оба чтения в do_lua_script() внутри лока, "
    "первичная запись в lua_init() доказуемо до создания задачи-читателя"
)
