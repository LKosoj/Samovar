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
  - T17 п.3 (2026-08-24): вызов load_lua_script() убран из commit_profile_operation()
    (у неё необратимые эффекты NVS/program_commit, а ретраить нужно только Lua-
    перезагрузку) и перенесён в switch_samovar_mode() (mode_switch.h), где он
    исполняется ПОСЛЕ commit_profile_operation() - лок к этому моменту уже
    отпущен (commit_profile_operation() успевает вернуться), так что риск
    рекурсивного захвата тот же самый, только проверяется теперь между двумя
    функциями, а не двумя токенами внутри одной.

T30a (2026-08-24): commit_profile_operation() ждала xLuaSemaphore БЕСКОНЕЧНО
(lua_state_lock(portMAX_DELAY)) прямо в loop() (ядро 1) - тот же лок до ~40 с
подряд держит do_lua_script() при периодическом прогоне (два чанка под одним
захватом, LUA_CHUNK_TIMEOUT_MS=20000 каждый). Значит сохранение настроек через
веб во время работы Lua-автоматики подвешивало loop() до 40 с и делало
невозможным сторож loop() с порогом 10 с (T30).

Решение - тот же приём, что уже применён в load_lua_script() (см. факты выше):
ждать лок максимум pdMS_TO_TICKS(300), и при неудаче НЕ терять заявку, а
отложить её. commit_profile_operation() к этому моменту уже необратимо применила
ВСЁ остальное (NVS, SamSetup, режим, программу, метаданные) - откладывается
СТРОГО имя lua-скрипта (lua_type_script_pending = true). load_lua_script()
(её switch_samovar_mode() зовёт сразу следующим тактом и повторяет, пока
операция не завершится - luaReloadAttempts) применяет отложенное имя ПЕРВЫМ
делом, под тем же локом, ДО чтения lua_type_script - иначе прочитала бы ещё
старое имя. Операция не может "зависнуть навсегда": switch_samovar_mode() не
станет terminal, пока load_lua_script() не подтвердит успех (или не исчерпает
свой собственный, уже существовавший до T30a, предел попыток).

Заодно (та же функция, тот же заход) исправлены ещё 2 portMAX_DELAY,
достижимых из loop() тем же путём (through load_lua_script()/beer.h):
  - lua.h load_lua_script(): runtime_state_lock(portMAX_DELAY) сразу после
    lua_state_lock() - RUNTIME_STATE (LOCK_ORDER 100, самый внутренний замок)
    берётся здесь только для короткого копирования String; таймаут заменён на
    дефолтные pdMS_TO_TICKS(50), как и везде в lua.h для этого замка. Отказ
    возвращает false (как и занятый xLuaSemaphore чуть выше) - лок Lua при
    этом корректно отпускается, заявка не теряется (caller повторит попытку).
  - lua.h request_beer_lua_stop(): тот же RUNTIME_STATE, вызывается из
    beer.h при смене строки программы (достижимо из loop()). Обработка отказа
    уже была написана правильно (return false, runtime_state_unlock(locked)) -
    менялся только таймаут.

Тест проверяет эти инварианты структурно на РЕАЛЬНОМ исходнике (часть 1) и
поведенчески - реальными извлечёнными телами в g++-харнессе (часть 2).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
    strip_cpp_comments,
)

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

samovar_raw = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
lua_raw = (ROOT / "lua.h").read_text(encoding="utf-8")
samovar_text = strip_cpp_comments(samovar_raw)
lua_text = strip_cpp_comments(lua_raw)
webserver_text = strip_cpp_comments((ROOT / "WebServer.ino").read_text(encoding="utf-8"))
mode_switch_text = strip_cpp_comments((ROOT / "mode_switch.h").read_text(encoding="utf-8"))


def function_body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError:
        return ""


# ==== ЧАСТЬ 1: структурные проверки на РЕАЛЬНОМ исходнике =====================

# ---- 1. запись в commit_profile_operation() ограничена по времени и не теряет
#         заявку при занятом локе -------------------------------------------
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
            "lua_state_lock(pdMS_TO_TICKS(300))",
            "if (luaTypeLocked) {",
            "lua_type_script = get_lua_mode_name();",
            "lua_state_unlock(true);",
            "} else {",
            "lua_type_script_pending = true;",
        ],
        errors,
    )
    if "lua_state_lock(portMAX_DELAY)" in commit_body:
        errors.append(
            "T30a: commit_profile_operation() снова ждёт xLuaSemaphore "
            "portMAX_DELAY - loop() (ядро 1) может зависнуть на ~40 с, пока "
            "do_lua_script() держит лок в периодическом прогоне"
        )
    if "load_lua_script(" in commit_body:
        errors.append(
            "Samovar.ino: commit_profile_operation() больше не должна звать "
            "load_lua_script() - у коммита необратимые эффекты (NVS, "
            "program_commit()), а ретраить нужно только Lua-перезагрузку "
            "(см. switch_samovar_mode())"
        )

# ---- 1b. load_lua_script() применяет отложенную заявку ПЕРВЫМ делом, до чтения
#          lua_type_script, и не бесконечно ждёт RUNTIME_STATE следом ----------
load_body = function_body(lua_text, "bool load_lua_script() {")
if not load_body:
    errors.append("lua.h: load_lua_script() не найдена")
else:
    require_ordered_tokens(
        # Токен "typeScriptLocked = lua_state_lock(pdMS_TO_TICKS(300))" (а не
        # просто "lua_state_lock(pdMS_TO_TICKS(300))") - иначе он совпал бы ещё
        # и со ВТОРЫМ, не связанным с T30a вызовом lua_state_lock() ниже по
        # той же функции (bool lua_locked = ...), и при мутации первого
        # найденный "проскочил" бы на второй, дав неверную диагностику.
        "load_lua_script",
        load_body,
        [
            "if (lua_type_script_pending) {",
            "typeScriptLocked = lua_state_lock(pdMS_TO_TICKS(300))",
            "return false;",
            "lua_type_script = get_lua_mode_name();",
            "lua_type_script_pending = false;",
            "lua_state_unlock(true);",
            # После применения заявки функция обязана ЕЩЁ читать lua_type_script -
            # иначе флаг проверяется зря (get_lua_script(lua_type_script) - основной
            # потребитель свежего имени).
            "get_lua_script(lua_type_script)",
            "runtime_state_lock()",
        ],
        errors,
    )
    if "portMAX_DELAY" in load_body:
        errors.append(
            "T30a: load_lua_script() снова содержит portMAX_DELAY - RUNTIME_STATE "
            "берётся здесь уже под xLuaSemaphore, вызывается из loop() через "
            "switch_samovar_mode()/tick_apply_pending_lua_commands()"
        )

# ---- 1c. request_beer_lua_stop() (beer.h зовёт из loop()) тоже не ждёт вечно --
beer_stop_body = function_body(
    lua_text, "inline ActuatorCommandResult request_beer_lua_stop(uint32_t ticket) {"
)
if not beer_stop_body:
    errors.append("lua.h: request_beer_lua_stop() не найдена")
else:
    if "portMAX_DELAY" in beer_stop_body:
        errors.append(
            "T30a: request_beer_lua_stop() снова содержит portMAX_DELAY - вызывается "
            "из beer.h при смене строки программы, достижимо из loop()"
        )
    if "runtime_state_lock()" not in beer_stop_body:
        errors.append(
            "lua.h: request_beer_lua_stop() должна ждать RUNTIME_STATE ограниченно "
            "(дефолт runtime_state_lock() - pdMS_TO_TICKS(50), как и везде в файле)"
        )
    # [Дефект 2] Занятый лок и чужой тикет - РАЗНЫЕ исходы: занятый лок не
    # должен обрываться так же, как настоящая ошибка согласования тикета -
    # caller (beer.h) иначе аварийно прерывает варку из-за временной помехи.
    require_ordered_tokens(
        "request_beer_lua_stop",
        beer_stop_body,
        [
            "bool locked = runtime_state_lock();",
            "if (!locked) return ACTUATOR_COMMAND_PENDING;",
            "if (ticket != lua_beer_job_ticket) {",
            "return ACTUATOR_COMMAND_FAILED;",
            "return ACTUATOR_COMMAND_APPLIED;",
        ],
        errors,
    )

# ---- 1d. load_lua_script() теперь ретраится в switch_samovar_mode(), ПОСЛЕ --
#          коммита - лок к этому моменту уже отпущен commit_profile_operation()
switch_body = function_body(
    mode_switch_text, "ModeSwitchResult switch_samovar_mode(SAMOVAR_MODE requestedMode)"
)
if not switch_body:
    errors.append("mode_switch.h: switch_samovar_mode() не найдена")
else:
    require_ordered_tokens(
        "switch_samovar_mode",
        switch_body,
        [
            "commit_profile_operation()",
            "load_lua_script()",
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
        offset = index + len("lua_type_script")
        # [Дефект 1] "lua_type_script" - префикс другого идентификатора,
        # lua_type_script_pending (страховка do_lua_script(), проверка 2b ниже).
        # Она законно читается ДО лока (volatile bool, а не String) - не считать
        # её чтением самой lua_type_script, иначе тест ложно падает на 2b.
        following = do_lua_script_body[offset:offset + 1]
        if following.isalnum() or following == "_":
            continue
        read_indices.append(index)
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

# ---- 2b. [Дефект 1] do_lua_script() страхует зависшую заявку commit_profile_
#          operation(), если switch_samovar_mode() исчерпал все 10 попыток
#          load_lua_script() при занятом локе - каждый оборот while(1) видит
#          lua_type_script_pending и просит loop() перечитать скрипт ЦЕЛИКОМ
#          через pending_lua_reload_flag, а не присваивает lua_type_script
#          напрямую (иначе имя обновилось бы, а script2/script2_ref остались
#          бы от старого режима - несогласованное состояние хуже исходного
#          зависания).
if not do_lua_script_body:
    errors.append("lua.h: do_lua_script() не найдена (см. проверку 2 выше)")
else:
    require_ordered_tokens(
        "do_lua_script stuck-flag guard",
        do_lua_script_body,
        [
            "while (1) {",
            "if (lua_type_script_pending) {",
            "pending_lua_reload_flag = true;",
        ],
        errors,
    )
    guard_block = None
    try:
        guard_block, _ = extract_braced_block_after(
            do_lua_script_body, "if (lua_type_script_pending) {", 0
        )
    except ValueError:
        errors.append(
            "lua.h: do_lua_script() - не удалось извлечь блок "
            "if (lua_type_script_pending) { ... } для проверки страховки Дефекта 1"
        )
    if guard_block is not None:
        if "lua_type_script =" in guard_block or "lua_type_script=" in guard_block:
            errors.append(
                "[Дефект 1] do_lua_script() не должна присваивать lua_type_script "
                "напрямую - это обновило бы только имя для лога, а script2/"
                "script2_ref (реально исполняемый код) остались бы от старого "
                "режима; правильно - попросить loop() перечитать скрипт целиком "
                "через pending_lua_reload_flag"
            )
        if "pending_lua_reload_flag = true;" not in guard_block:
            errors.append(
                "[Дефект 1] do_lua_script() обязана взводить pending_lua_reload_flag, "
                "когда замечает зависшую заявку lua_type_script_pending - иначе имя "
                "режима может навсегда разойтись с фактически выполняемым скриптом, "
                "если switch_samovar_mode() исчерпал все свои 10 попыток при занятом локе"
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
    print("lua_type_script race smoke check (Part 1, structural) failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    "lua_type_script race smoke check (Part 1, structural) passed: запись в "
    "commit_profile_operation() ограничена по времени и не теряет заявку, "
    "load_lua_script()/request_beer_lua_stop() не ждут RUNTIME_STATE вечно, "
    "request_beer_lua_stop() различает занятый лок (ACTUATOR_COMMAND_PENDING) "
    "и чужой тикет (ACTUATOR_COMMAND_FAILED), оба чтения в do_lua_script() "
    "внутри лока, do_lua_script() страхует зависшую заявку через "
    "pending_lua_reload_flag (не трогая lua_type_script напрямую), первичная "
    "запись в lua_init() доказуемо до создания задачи-читателя"
)


# ==== ЧАСТЬ 2: поведенческая проверка - РЕАЛЬНЫЕ извлечённые тела в g++ =======
#
# commit_profile_operation() целиком слишком связана окружением (NVS-запись,
# program_commit(), portENTER_CRITICAL(&configMux), apply_config_runtime(),
# apply_setup_sensor_fields() и т.д. - десятки внешних функций/глобалов), чтобы
# компилировать её целиком в отрыве от прошивки. Но именно МЕХАНИЗМ T30a - блок
# "if (modeChange) { ... }" вокруг lua_state_lock/lua_type_script - извлекается
# как самостоятельный фрагмент РЕАЛЬНОГО текста (extract_braced_block_after,
# тот же приём, что source_slice в smoke_lua_chunk_watchdog.py) и компилируется
# с лёгкими моками замка/String - без переписывания логики. То же для блока
# отложенной заявки в load_lua_script().

commit_body_raw = extract_function_body(
    samovar_raw, "static OperationError commit_profile_operation() {", strip_comments=False
)
ifdef_offset = commit_body_raw.find("#ifdef USE_LUA")
if ifdef_offset < 0:
    print("FAIL: Samovar.ino: #ifdef USE_LUA не найден в commit_profile_operation()")
    sys.exit(1)
commit_lua_block, _ = extract_braced_block_after(
    commit_body_raw, "if (modeChange) {", ifdef_offset
)

load_body_raw = extract_function_body(lua_raw, "bool load_lua_script() {", strip_comments=False)
flush_block, _ = extract_braced_block_after(
    load_body_raw, "if (lua_type_script_pending) {", 0
)

# [Дефект 1] do_lua_script() - страховка зависшей заявки: РЕАЛЬНЫЙ блок из тела
# задачи (см. проверку 2b в Части 1 выше), тем же приёмом extract_braced_block_after.
do_lua_script_raw_body = extract_function_body(
    lua_raw, "void do_lua_script(void *parameter) {", strip_comments=False
)
guard_block_raw, _ = extract_braced_block_after(
    do_lua_script_raw_body, "if (lua_type_script_pending) {", 0
)

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

using TickType_t = int;
constexpr TickType_t portMAX_DELAY = -1;
static TickType_t pdMS_TO_TICKS(int value) { return value; }

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const String& other) = default;
  String& operator=(const String& other) = default;
  bool operator==(const String& other) const { return value_ == other.value_; }
  bool operator!=(const String& other) const { return value_ != other.value_; }
  std::string value_;
};
static const char* F(const char* text) { return text; }
static int writeConsoleLogCalls = 0;
static void WriteConsoleLog(const String&) { writeConsoleLogCalls++; }

// --- состояние под проверкой (ровно то, что объявлено в lua.h) -------------
static String lua_type_script;
static bool lua_type_script_pending = false;
// [Дефект 1] тот же флаг, которым SPIFFSEditor.h и tick_apply_pending_lua_
// commands() (Samovar.ino) уже договариваются о перезагрузке скрипта.
static bool pending_lua_reload_flag = false;

// --- мок замка xLuaSemaphore/lua_state_lock - фиксирует КАЖДЫЙ вызов и его
// таймаут: mutation-тест ниже проверяет, что таймаут никогда не portMAX_DELAY --
static bool lockAvailable = true;
static int lockCalls = 0;
static TickType_t lastLockTimeout = 0;
static int unlockCalls = 0;
static bool lua_state_lock(TickType_t timeout) {
  lockCalls++;
  lastLockTimeout = timeout;
  return lockAvailable;
}
static void lua_state_unlock(bool locked) { if (locked) unlockCalls++; }

static std::string modeNameStub = "dist.lua";
static String get_lua_mode_name() { return String(modeNameStub.c_str()); }

// --- блок А: РЕАЛЬНЫЙ текст из commit_profile_operation() (Samovar.ino) -----
static void run_commit_lua_block() {
@COMMIT_BLOCK@
}

// --- блок Б: РЕАЛЬНЫЙ текст верхушки load_lua_script() (lua.h) -------------
// extract_braced_block_after() возвращает содержимое МЕЖДУ фигурными скобками
// "if (lua_type_script_pending) {" ... "}", без самого условия - поэтому
// условие оборачивается здесь вручную (оно же отдельно зафиксировано
// структурной проверкой в Части 1 - require_ordered_tokens убеждается, что
// "if (lua_type_script_pending) {" в реальном исходнике непосредственно
// предшествует этому же извлечённому блоку). return false внутри блока - это
// return false самой load_lua_script(); чтобы это скомпилировалось как есть
// (без переписывания), обёртка тоже bool, и "true" в конце соответствует
// тому, что реальная функция идёт дальше и в итоге возвращает true при успехе.
static bool run_load_flush_block() {
  if (lua_type_script_pending) {
@FLUSH_BLOCK@
  }
  return true;
}

// --- блок В: РЕАЛЬНЫЙ текст страховки в do_lua_script() (lua.h) ------------
// Каждый оборот while(1) do_lua_script() замечает зависшую заявку и просит
// loop() перечитать скрипт целиком через pending_lua_reload_flag - НЕ трогая
// lua_type_script напрямую (см. комментарий [Дефект 1] в самом lua.h).
static void run_stuck_flag_guard_block() {
  if (lua_type_script_pending) {
@GUARD_BLOCK@
  }
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset() {
  lua_type_script = String("old.lua");
  lua_type_script_pending = false;
  pending_lua_reload_flag = false;
  lockAvailable = true;
  lockCalls = 0;
  lastLockTimeout = -999;
  unlockCalls = 0;
  writeConsoleLogCalls = 0;
  modeNameStub = "dist.lua";
}

// commit_profile_operation(): лок занят - НЕ блокируется (одна попытка, конечный
// таймаут), запись НЕ теряется (флаг), lua_type_script не тронута наполовину.
static void test_commit_busy_lock_defers_without_blocking() {
  reset();
  lockAvailable = false;
  run_commit_lua_block();
  check(lockCalls == 1, "commit: занятый лок должен пробоваться РОВНО один раз - не цикл ожидания");
  check(lastLockTimeout != portMAX_DELAY, "commit: таймаут лока не должен быть portMAX_DELAY (бесконечное ожидание в loop())");
  check(lastLockTimeout >= 0, "commit: таймаут лока обязан быть конечным неотрицательным числом тиков");
  check(lua_type_script == String("old.lua"), "commit: занятый лок не должен трогать lua_type_script (нельзя завершить присваивание наполовину)");
  check(lua_type_script_pending, "commit: занятый лок обязан отложить заявку (lua_type_script_pending), а не потерять её");
  check(unlockCalls == 0, "commit: лок не был взят - отпускать нечего");
}

// commit_profile_operation(): лок свободен - поведение как раньше, синхронно.
static void test_commit_free_lock_applies_immediately() {
  reset();
  lockAvailable = true;
  run_commit_lua_block();
  check(lockCalls == 1, "commit: свободный лок - одна попытка");
  check(lastLockTimeout != portMAX_DELAY, "commit: таймаут лока не должен быть portMAX_DELAY даже при свободном локе");
  check(lua_type_script == String("dist.lua"), "commit: свободный лок обязан применить новое имя немедленно (быстрый путь не должен был сломаться)");
  check(!lua_type_script_pending, "commit: свободный лок не должен откладывать заявку");
  check(unlockCalls == 1, "commit: взятый лок обязан быть отпущен");
}

// load_lua_script(): отложенная заявка + занятый лок - заявка НЕ теряется,
// функция возвращает false (сигнал "попробуй ещё раз позже", как и для
// собственного занятого lua_state_lock чуть ниже по функции).
static void test_flush_busy_lock_preserves_pending_request() {
  reset();
  lua_type_script_pending = true;
  lockAvailable = false;
  bool result = run_load_flush_block();
  check(!result, "load_lua_script: занятый лок на флаше заявки обязан вернуть false (повтор на следующем такте)");
  check(lastLockTimeout != portMAX_DELAY, "load_lua_script: таймаут лока на флаше заявки не должен быть portMAX_DELAY (loop() может дойти сюда через switch_samovar_mode())");
  check(lua_type_script == String("old.lua"), "load_lua_script: занятый лок не должен успеть переписать lua_type_script наполовину");
  check(lua_type_script_pending, "load_lua_script: занятый лок обязан СОХРАНИТЬ заявку, а не потерять её");
}

// load_lua_script(): отложенная заявка + свободный лок - применяется ПЕРЕД
// дальнейшим чтением lua_type_script (что и требуется - иначе get_lua_script
// прочитала бы старое имя).
static void test_flush_free_lock_applies_before_continuing() {
  reset();
  lua_type_script_pending = true;
  lockAvailable = true;
  bool result = run_load_flush_block();
  check(result, "load_lua_script: свободный лок должен позволить функции продолжить (не вернуть false)");
  check(lastLockTimeout != portMAX_DELAY, "load_lua_script: таймаут лока на флаше заявки не должен быть portMAX_DELAY даже при свободном локе");
  check(lua_type_script == String("dist.lua"), "load_lua_script: свободный лок обязан применить отложенное имя ДО дальнейшего чтения lua_type_script");
  check(!lua_type_script_pending, "load_lua_script: применённая заявка обязана сброситься - иначе повторный флаш будет повторяться бесконечно");
}

// load_lua_script(): заявки не было - блок вообще не должен трогать замок.
static void test_flush_noop_when_nothing_pending() {
  reset();
  lua_type_script_pending = false;
  lockAvailable = true;
  bool result = run_load_flush_block();
  check(result, "load_lua_script: без заявки функция обязана продолжить как обычно");
  check(lockCalls == 0, "load_lua_script: без заявки блок не должен даже пробовать взять лок");
  check(lua_type_script == String("old.lua"), "load_lua_script: без заявки lua_type_script не должна меняться этим блоком");
}

// [Дефект 1] do_lua_script(): заявка зависла (например, switch_samovar_mode()
// исчерпал все 10 попыток при занятом локе) - оборот while(1) обязан взвести
// pending_lua_reload_flag и НЕ трогать lua_type_script напрямую (иначе имя
// обновилось бы раньше самого скрипта - несогласованное состояние).
static void test_guard_stuck_flag_requests_reload_without_touching_name() {
  reset();
  lua_type_script_pending = true;
  run_stuck_flag_guard_block();
  check(pending_lua_reload_flag, "do_lua_script: зависшая заявка обязана взвести pending_lua_reload_flag");
  check(lua_type_script == String("old.lua"), "do_lua_script: заявка не должна присваивать lua_type_script напрямую - это рассинхронизирует имя со script2/script2_ref");
}

// do_lua_script(): заявки нет - блок вообще не должен трогать флаг перезагрузки.
static void test_guard_noop_when_nothing_pending() {
  reset();
  lua_type_script_pending = false;
  run_stuck_flag_guard_block();
  check(!pending_lua_reload_flag, "do_lua_script: без заявки блок не должен взводить pending_lua_reload_flag");
}

int main() {
  test_commit_busy_lock_defers_without_blocking();
  test_commit_free_lock_applies_immediately();
  test_flush_busy_lock_preserves_pending_request();
  test_flush_free_lock_applies_before_continuing();
  test_flush_noop_when_nothing_pending();
  test_guard_stuck_flag_requests_reload_without_touching_name();
  test_guard_noop_when_nothing_pending();
  return failures == 0 ? 0 : 1;
}
'''


def build_harness() -> str:
    harness = HARNESS_TEMPLATE.replace("@COMMIT_BLOCK@", commit_lua_block)
    harness = harness.replace("@FLUSH_BLOCK@", flush_block)
    harness = harness.replace("@GUARD_BLOCK@", guard_block_raw)
    return harness


def compile_and_run(harness: str, label: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-lua-type-script-lock-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "lua_type_script_lock_test.cpp"
        binary = temp / "lua_type_script_lock_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            output = compiled.stdout + compiled.stderr
            if show_output:
                sys.stderr.write(f"[{label}] compile failed:\n{output}")
            return compiled.returncode, output
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        output = ran.stdout + ran.stderr
        if show_output:
            sys.stdout.write(ran.stdout)
            sys.stderr.write(ran.stderr)
        return ran.returncode, output


def require_mutation(harness: str, old: str, new: str, expected: str) -> bool:
    mutant = harness.replace(old, new, 1)
    if mutant == harness:
        print(f"FAIL: cannot construct mutation for {expected}", file=sys.stderr)
        return False
    code, output = compile_and_run(mutant, expected, False)
    if code == 0 or expected not in output:
        print(f"FAIL: mutation survived ({expected}):", file=sys.stderr)
        sys.stderr.write(output)
        return False
    return True


def main() -> int:
    harness = build_harness()
    code, _ = compile_and_run(harness, "T30a lua_type_script lock behavioural")
    if code:
        return 1

    mutations = [
        # Возврат portMAX_DELAY в блок commit_profile_operation() - именно та
        # мутация, которую явно требует ТЗ T30a.
        (
            "bool luaTypeLocked = lua_state_lock(pdMS_TO_TICKS(300));",
            "bool luaTypeLocked = lua_state_lock(portMAX_DELAY);",
            "commit: таймаут лока не должен быть portMAX_DELAY",
        ),
        # Возврат portMAX_DELAY в блок флаша заявки load_lua_script().
        (
            "bool typeScriptLocked = lua_state_lock(pdMS_TO_TICKS(300));",
            "bool typeScriptLocked = lua_state_lock(portMAX_DELAY);",
            "load_lua_script: таймаут лока на флаше заявки не должен быть portMAX_DELAY",
        ),
        # Занятый лок в commit молча дропает заявку (else-ветка убрана) -
        # заявка теряется, коммит "завершается наполовину" без следа.
        (
            "    } else {\n      lua_type_script_pending = true;\n    }",
            "    }",
            "commit: занятый лок обязан отложить заявку",
        ),
        # load_lua_script() не сбрасывает флаг после успешного флаша -
        # заявка применяется, но бесконечно повторяется (лишние локи каждый вызов).
        (
            "    lua_type_script = get_lua_mode_name();\n    lua_type_script_pending = false;\n    lua_state_unlock(true);",
            "    lua_type_script = get_lua_mode_name();\n    lua_state_unlock(true);",
            "load_lua_script: применённая заявка обязана сброситься",
        ),
        # [Дефект 1] МУТАЦИЯ: убрать разбор зависшей заявки в do_lua_script() -
        # тест обязан упасть, иначе страховка молча выключена. "old" привязан к
        # уникальной сигнатуре run_stuck_flag_guard_block() - то же самое условие
        # "if (lua_type_script_pending) {" встречается в харнессе ещё раз, в
        # run_load_flush_block(), и .replace(..., 1) взял бы не ту функцию.
        (
            "static void run_stuck_flag_guard_block() {\n  if (lua_type_script_pending) {",
            "static void run_stuck_flag_guard_block() {\n  if (false) {",
            "do_lua_script: зависшая заявка обязана взвести pending_lua_reload_flag",
        ),
    ]
    for old, new, expected in mutations:
        if not require_mutation(harness, old, new, expected):
            return 1
    print(
        "lua_type_script race smoke check (Part 2, behavioural) passed: занятый "
        "лок не блокирует, заявка не теряется, отложенное имя применяется до "
        "дальнейшего чтения, зависшая заявка в do_lua_script() взводит "
        "pending_lua_reload_flag, не трогая lua_type_script; все 5 мутаций "
        "(включая возврат portMAX_DELAY и отключение страховки Дефекта 1) отклонены"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
