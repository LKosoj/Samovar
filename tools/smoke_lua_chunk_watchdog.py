#!/usr/bin/env python3
"""[P8] Поведенческая проверка watchdog'а зависших Lua-чанков (lua.h).

Берёт РЕАЛЬНЫЕ тела lua_timeout_hook/lua_install_timeout_hook_locked/
lua_remove_timeout_hook_locked/lua_report_timeout_if_fired из lua.h (через
source_slice - без переписывания логики) и исполняет их с настоящим lua_State
из вендорной Lua 5.4 (libraries/ESP-Arduino-Lua/src/lua), как это делает
smoke_lua_a07.py. Компилируется дважды с разными значениями LUA_CHUNK_TIMEOUT_MS
(через переопределение макроса ДО вставки блока - реальный код в lua.h защищён
#ifndef ровно для такого переопределения), чтобы убедиться, что константа
реально влияет на момент срабатывания, а не захардкожена где-то ещё.

Проверяемое поведение:
- "while true do end" - watchdog обязан прервать выполнение (luaL_error -> longjmp),
  luaTimeoutFired становится true, pcall возвращает ошибку.
- "return 1" - выполняется штатно, luaTimeoutFired остаётся false.
- lua_report_timeout_if_fired шлёт SendMsg только когда таймаут реально сработал,
  и сбрасывает luaTimeoutFired после отчёта.
- Меньший LUA_CHUNK_TIMEOUT_MS приводит к более раннему обрыву, чем больший -
  подтверждает, что константа не игнорируется.

[P8 finding 3] lua_sethook ставится только на главный lua_State - код внутри
coroutine.resume исполняется в СВОЁМ lua_State и хуком главного не покрыт.
Проверяем реальный текст lua_wrapper_arm_coroutine_watchdog/
LUA_COROUTINE_WATCHDOG_PRELUDE/lua_install_coroutine_watchdog_locked (тем же
source_slice механизмом) на настоящем vendor Lua 5.4:
- (a) "while true do end" внутри coroutine.resume() прерывается по таймауту
  (resume возвращает false + "chunk timeout", а не виснет навсегда).
- (b) то же самое для coroutine.wrap() - обёрнутая функция кидает Lua-ошибку
  "chunk timeout" (pcall вокруг вызова обёрнутой функции ловит её).
- (c) обычная корутина (yield/resume с возвратом значений, через оба API)
  работает штатно и возвращает ПРАВИЛЬНЫЕ значения - подмена не сломала
  семантику coroutine.create/wrap/resume.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LUA_DIR = ROOT / "libraries/ESP-Arduino-Lua/src/lua"


def source_slice(source: str, start_token: str, end_token: str) -> str:
    start = source.find(start_token)
    end = source.find(end_token, start)
    if start < 0 or end < 0:
        raise ValueError(f"source slice not found: {start_token} .. {end_token}")
    return source[start:end]


HARNESS_TEMPLATE = r'''
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iostream>

extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}

@TIMEOUT_OVERRIDE@

#include "safety_transition.h"

enum { ALARM_MSG = 0 };
static int sendMsgCalls = 0;
static void SendMsg(const char* m, int type) {
  (void)m;
  (void)type;
  sendMsgCalls++;
}

static const std::chrono::steady_clock::time_point samovarTestStart =
    std::chrono::steady_clock::now();
static uint32_t millis() {
  return (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::steady_clock::now() - samovarTestStart)
      .count();
}

struct FakeLuaWrapper {
  lua_State* state = nullptr;
  lua_State* GetState() { return state; }
};
static FakeLuaWrapper lua;

@WATCHDOG_BLOCK@

@COROUTINE_WATCHDOG_BLOCK@

static int failures = 0;
static void check(bool cond, const char* msg) {
  if (!cond) {
    std::cerr << "FAIL: " << msg << "\n";
    failures++;
  }
}

// Без автоматического report() внутри - иначе luaTimeoutFired было бы уже
// сброшено к моменту проверки (см. реальные lua_exec_locked/lua_exec_chunk_locked
// в lua.h - там report идёт отдельным шагом ПОСЛЕ pcall/remove).
static int run_chunk_no_report(lua_State* L, const char* code, uint32_t* elapsedMsOut) {
  luaL_loadstring(L, code);
  lua_install_timeout_hook_locked();
  const uint32_t startMs = millis();
  const int rc = lua_pcall(L, 0, 0, 0);
  if (elapsedMsOut) *elapsedMsOut = millis() - startMs;
  lua_remove_timeout_hook_locked();
  return rc;
}

// Читает глобальную строку/булево/число и снимает со стека - маленький хелпер,
// чтобы не повторять lua_getglobal/lua_pop в каждой проверке ниже.
static bool global_bool(lua_State* L, const char* name) {
  lua_getglobal(L, name);
  const bool value = lua_toboolean(L, -1) != 0;
  lua_pop(L, 1);
  return value;
}

static double global_number(lua_State* L, const char* name) {
  lua_getglobal(L, name);
  const double value = lua_tonumber(L, -1);
  lua_pop(L, 1);
  return value;
}

static std::string global_string(lua_State* L, const char* name) {
  lua_getglobal(L, name);
  const char* text = lua_tostring(L, -1);
  std::string value = text ? text : "";
  lua_pop(L, 1);
  return value;
}

// [P8 finding 3] luaHookDeadlineMs общий для главного lua_State и для
// корутин. Если корутина потратила ВЕСЬ бюджет времени чанка на спин, любой
// Lua-код на главном состоянии, исполняющийся ПОСЛЕ возврата из неё (в т.ч.
// код внутри объемлющего pcall()), тоже может упереться в уже истёкший
// дедлайн - и это ожидаемо: у чанка ОДНО общее окно времени, а не "корутина
// отдельно, всё остальное бесплатно". Поэтому "chunk timeout" может быть
// поймана ЛИБО внутренним pcall() самого скрипта (тогда okGlobal/errGlobal
// содержат результат), ЛИБО долетает до верхнеуровневого pcall (C++) - оба
// исхода доказывают, что бесконечный цикл был прерван, а не завис навсегда.
static void check_coroutine_watchdog_tripped(
    lua_State* L, int rc, const char* okGlobal, const char* errGlobal, const char* label) {
  if (rc != LUA_OK) {
    const char* topError = lua_tostring(L, -1);
    const std::string topErrorStr = topError ? topError : "";
    lua_pop(L, 1);
    const std::string msg = std::string(label) +
        ": escaped to the top-level pcall without mentioning chunk timeout: " + topErrorStr;
    check(topErrorStr.find("chunk timeout") != std::string::npos, msg.c_str());
    return;
  }
  const std::string okMsg = std::string(label) +
      ": inner call did not report failure for a watchdog-tripped coroutine "
      "(infinite loop inside the coroutine was NOT interrupted)";
  check(!global_bool(L, okGlobal), okMsg.c_str());
  const std::string errMsg = std::string(label) + ": inner error did not mention chunk timeout";
  check(global_string(L, errGlobal).find("chunk timeout") != std::string::npos, errMsg.c_str());
}

int main() {
  // [P8 finding 3] Реальная прошивка (см. linit.c ниже) coroutine НЕ грузит -
  // прелюдия обязана деградировать без краша именно в этой конфигурации.
  // Проверяем это ДО того, как ниже открываем coroutine вручную для остальных
  // проверок этого файла.
  {
    lua_State* prodLikeL = luaL_newstate();
    check(prodLikeL != nullptr, "luaL_newstate failed (prod-like state)");
    if (prodLikeL) {
      luaL_openlibs(prodLikeL);
      lua.state = prodLikeL;
      lua_install_coroutine_watchdog_locked();  // coroutine == nil здесь - не должно падать
      if (luaL_dostring(prodLikeL, "return 1") != LUA_OK) {
        check(false, "a trivial script failed after installing the coroutine watchdog "
                     "without the coroutine library (prelude must degrade silently)");
      } else {
        check(lua_tointeger(prodLikeL, -1) == 1,
              "a trivial script returned a wrong value after installing the coroutine watchdog");
        lua_pop(prodLikeL, 1);
      }
      lua_close(prodLikeL);
    }
  }

  lua_State* L = luaL_newstate();
  check(L != nullptr, "luaL_newstate failed");
  if (!L) return 1;
  luaL_openlibs(L);
  // [P8 finding 3] ВАЖНО: реальный linit.c этого вендорного дерева (см.
  // libraries/ESP-Arduino-Lua/src/lua/linit.c) держит coroutine/io/os/debug/
  // package ЗАКОММЕНТИРОВАННЫМИ - luaL_openlibs() их не грузит, и
  // LuaWrapper::LuaWrapper() тоже не открывает coroutine напрямую. То есть в
  // текущей прошивке global `coroutine` в Lua-скриптах равен nil, и описанный
  // сценарий (зависание внутри coroutine.resume) сегодня НЕ достижим из
  // пользовательского Lua. Открываем библиотеку явно здесь, чтобы всё же
  // проверить сам механизм подмены (защита рассчитана на будущее/другие сборки,
  // где coroutine включат) - luaL_dostring прелюдии в проде на это не полагается
  // и деградирует молча, если coroutine отсутствует (см. отдельную проверку ниже).
  luaopen_coroutine(L);
  lua_setglobal(L, "coroutine");
  lua.state = L;
  // Устанавливается один раз при инициализации, как в реальном lua_init() -
  // до любых пользовательских скриптов.
  lua_install_coroutine_watchdog_locked();

  uint32_t elapsedTripMs = 0;
  const int rcLoop = run_chunk_no_report(L, "while true do end", &elapsedTripMs);
  check(rcLoop != LUA_OK, "infinite loop chunk did not return an error from pcall");
  check(luaTimeoutFired == true, "luaTimeoutFired was not set after a real timeout");
  sendMsgCalls = 0;
  lua_report_timeout_if_fired();
  check(sendMsgCalls == 1, "lua_report_timeout_if_fired did not SendMsg after a real timeout");
  check(luaTimeoutFired == false, "lua_report_timeout_if_fired did not reset luaTimeoutFired");

  uint32_t elapsedOkMs = 0;
  const int rcOk = run_chunk_no_report(L, "return 1", &elapsedOkMs);
  check(rcOk == LUA_OK, "trivial chunk unexpectedly failed");
  check(luaTimeoutFired == false, "luaTimeoutFired set for a chunk that did not time out");
  sendMsgCalls = 0;
  lua_report_timeout_if_fired();
  check(sendMsgCalls == 0, "lua_report_timeout_if_fired sent a message despite no timeout");

  // [P8 finding 3] lua_newthread (lstate.c) копирует hook/hookmask/
  // basehookcount у СОЗДАЮЩЕГО состояния в момент создания нити. Если
  // создавать корутину ПРЯМО ВНУТРИ уже хукнутого run_chunk_no_report, она
  // получит хук "бесплатно" через это наследование - и тест ничего не скажет
  // о работе самой подмены (armCoroutineWatchdog при resume/wrap). Поэтому
  // создаём обе корутины ЗАРАНЕЕ, простым luaL_dostring БЕЗ активного хука на
  // L (главный lua_State к этому моменту хук уже снял - см.
  // lua_remove_timeout_hook_locked в конце run_chunk_no_report выше), и лишь
  // потом резюмируем их внутри отдельного, свежехукнутого чанка - как это
  // бывает в реальности (объект-корутина пережил создавший его чанк).
  check(lua_gethookmask(L) == 0, "main L still has a hook installed before pre-creating coroutines");
  if (luaL_dostring(L,
          "_G.persistent_co = coroutine.create(function() while true do end end)\n"
          "_G.persistent_wrap = coroutine.wrap(function() while true do end end)\n") != LUA_OK) {
    check(false, "failed to pre-create persistent coroutines outside any hook window");
  }

  // (a) [P8 finding 3] `while true do end` внутри coroutine.resume() обязан
  // прерываться по тому же таймауту, что и главный lua_State - иначе watchdog
  // не покрывает корутины вовсе (подтверждено экспериментом ревьюера).
  luaTimeoutFired = false;
  uint32_t elapsedCoroResumeMs = 0;
  const int rcCoroResume = run_chunk_no_report(
      L,
      "local ok, err = coroutine.resume(_G.persistent_co)\n"
      "_G.coro_resume_ok = ok\n"
      "_G.coro_resume_err = tostring(err)\n",
      &elapsedCoroResumeMs);
  check_coroutine_watchdog_tripped(
      L, rcCoroResume, "coro_resume_ok", "coro_resume_err", "coroutine.resume(infinite loop)");

  // (b) то же самое через coroutine.wrap() - обёрнутая функция обязана кинуть
  // Lua-ошибку "chunk timeout" (перехватывается pcall'ом вокруг её вызова).
  luaTimeoutFired = false;
  uint32_t elapsedCoroWrapMs = 0;
  const int rcCoroWrap = run_chunk_no_report(
      L,
      "local ok, err = pcall(_G.persistent_wrap)\n"
      "_G.coro_wrap_ok = ok\n"
      "_G.coro_wrap_err = tostring(err)\n",
      &elapsedCoroWrapMs);
  check_coroutine_watchdog_tripped(
      L, rcCoroWrap, "coro_wrap_ok", "coro_wrap_err", "coroutine.wrap(infinite loop)");

  // (c) Обычная корутина (yield/resume с возвратом значений) через ОБА API -
  // подмена create/wrap/resume не должна ломать штатную семантику.
  const int rcCoroNormal = run_chunk_no_report(
      L,
      "local co = coroutine.create(function(a, b)\n"
      "  local c = coroutine.yield(a + b)\n"
      "  return c * 2\n"
      "end)\n"
      "local ok1, v1 = coroutine.resume(co, 2, 3)\n"
      "local ok2, v2 = coroutine.resume(co, 10)\n"
      "_G.coro_normal_ok1, _G.coro_normal_v1 = ok1, v1\n"
      "_G.coro_normal_ok2, _G.coro_normal_v2 = ok2, v2\n"
      "local f = coroutine.wrap(function(a, b)\n"
      "  local c = coroutine.yield(a + b)\n"
      "  return c * 2\n"
      "end)\n"
      "_G.coro_wrap_v1 = f(4, 5)\n"
      "_G.coro_wrap_v2 = f(100)\n",
      nullptr);
  check(rcCoroNormal == LUA_OK, "normal yield/resume coroutine script unexpectedly failed");
  check(global_bool(L, "coro_normal_ok1"), "coroutine.resume() first call did not succeed");
  check(global_number(L, "coro_normal_v1") == 5, "coroutine.resume() first call returned a wrong value");
  check(global_bool(L, "coro_normal_ok2"), "coroutine.resume() second call did not succeed");
  check(global_number(L, "coro_normal_v2") == 20, "coroutine.resume() second call returned a wrong value");
  check(global_number(L, "coro_wrap_v1") == 9, "coroutine.wrap() first call returned a wrong value");
  check(global_number(L, "coro_wrap_v2") == 200, "coroutine.wrap() second call returned a wrong value");

  lua_close(L);
  if (failures != 0) return 1;
  std::cout << "elapsed_trip_ms=" << elapsedTripMs << "\n";
  std::cout << "elapsed_coro_resume_ms=" << elapsedCoroResumeMs << "\n";
  std::cout << "elapsed_coro_wrap_ms=" << elapsedCoroWrapMs << "\n";
  return 0;
}
'''


def build_harness(watchdog_block: str, coroutine_watchdog_block: str, timeout_ms: int, instructions: int) -> str:
    override = (
        f"#define LUA_CHUNK_TIMEOUT_MS {timeout_ms}\n"
        f"#define LUA_CHUNK_TIMEOUT_INSTRUCTIONS {instructions}\n"
    )
    harness = HARNESS_TEMPLATE.replace("@TIMEOUT_OVERRIDE@", override)
    harness = harness.replace("@WATCHDOG_BLOCK@", watchdog_block)
    harness = harness.replace("@COROUTINE_WATCHDOG_BLOCK@", coroutine_watchdog_block)
    return harness


def compile_lua_objects(temp: Path) -> list[Path]:
    sources = sorted(
        path for path in LUA_DIR.glob("*.c") if path.name not in {"lua.c", "luac.c"}
    )
    objects: list[Path] = []
    for source in sources:
        object_path = temp / f"{source.stem}.o"
        result = subprocess.run(
            ["gcc", "-std=c11", "-O0", "-I", str(LUA_DIR), "-c", str(source), "-o", str(object_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise SystemExit(result.returncode)
        objects.append(object_path)
    return objects


def compile_and_run(temp: Path, name: str, harness: str, objects: list[Path]) -> tuple[int, str, str]:
    source_file = temp / f"{name}.cpp"
    binary = temp / name
    source_file.write_text(harness, encoding="utf-8")
    compile_result = subprocess.run(
        [
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-I", str(LUA_DIR), "-I", str(ROOT), str(source_file),
            *[str(path) for path in objects], "-lm", "-ldl", "-o", str(binary),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if compile_result.returncode != 0:
        return compile_result.returncode, compile_result.stdout, compile_result.stderr
    # [P8 finding 3] Таймаут на сам запуск: если арминг корутинного watchdog'а
    # сломан (например, мутационной проверкой), `while true do end` внутри
    # coroutine.resume/wrap виснет НАВСЕГДА (кооперативная Lua VM, обрыва по
    # ОС нет) - без этого таймаута сломанная мутация повесила бы сам тест-раннер
    # вместо того, чтобы аккуратно вернуть red.
    try:
        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False, timeout=15
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = (error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or ""))
        stderr += "\nTIMEOUT: binary did not return within 15s (coroutine watchdog likely not armed)"
        return 124, stdout, stderr
    return run_result.returncode, run_result.stdout, run_result.stderr


def parse_metric(stdout: str, key: str) -> int:
    prefix = f"{key}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return int(line.split("=", 1)[1])
    raise ValueError(f"{key} not found in output: {stdout!r}")


def main() -> int:
    lua_source = (ROOT / "lua.h").read_text(encoding="utf-8")
    try:
        watchdog_block = source_slice(
            lua_source, "#ifndef LUA_CHUNK_TIMEOUT_MS", "inline String lua_exec_locked"
        )
        # [P8 finding 3] Реальный код подмены coroutine.create/wrap/resume -
        # отдельный слайс, т.к. лежит рядом с lua_install_constants_locked (после
        # lua_exec_chunk_locked), а не в первом watchdog-блоке.
        coroutine_watchdog_block = source_slice(
            lua_source, "static int lua_wrapper_arm_coroutine_watchdog", "inline void check_alarm_lua()"
        )
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-lua-watchdog-") as temp_dir:
        temp = Path(temp_dir)
        objects = compile_lua_objects(temp)

        # Два разных значения таймаута - убеждаемся, что константа реально
        # управляет моментом обрыва, а не захардкожена в другом месте.
        small_ms, small_instr = 60, 20
        large_ms, large_instr = 400, 20

        rc_small, out_small, err_small = compile_and_run(
            temp, "watchdog_small",
            build_harness(watchdog_block, coroutine_watchdog_block, small_ms, small_instr), objects
        )
        sys.stdout.write(out_small)
        sys.stderr.write(err_small)
        if rc_small != 0:
            return rc_small

        rc_large, out_large, err_large = compile_and_run(
            temp, "watchdog_large",
            build_harness(watchdog_block, coroutine_watchdog_block, large_ms, large_instr), objects
        )
        sys.stdout.write(out_large)
        sys.stderr.write(err_large)
        if rc_large != 0:
            return rc_large

        elapsed_small = parse_metric(out_small, "elapsed_trip_ms")
        elapsed_large = parse_metric(out_large, "elapsed_trip_ms")

        # Обрыв не может произойти раньше настроенного порога, и должен произойти
        # заметно раньше для меньшего порога, чем для большего (с запасом на джиттер).
        if not (small_ms <= elapsed_small < small_ms + 300):
            print(
                f"FAIL: small-timeout trip took {elapsed_small}ms, expected close to {small_ms}ms",
                file=sys.stderr,
            )
            return 1
        if not (large_ms <= elapsed_large < large_ms + 300):
            print(
                f"FAIL: large-timeout trip took {elapsed_large}ms, expected close to {large_ms}ms",
                file=sys.stderr,
            )
            return 1
        if not (elapsed_small < elapsed_large):
            print(
                f"FAIL: LUA_CHUNK_TIMEOUT_MS override had no effect on trip timing "
                f"(small={elapsed_small}ms, large={elapsed_large}ms)",
                file=sys.stderr,
            )
            return 1

        # [P8 finding 3] Тот же порог обязан обрывать и `while true do end`
        # ВНУТРИ coroutine.resume()/coroutine.wrap() - не только на главном
        # lua_State. Проверяем для ОБОИХ вариантов таймаута (small/large), той
        # же логикой границ, что и для верхнеуровневого случая выше.
        for label, out, bound_ms in (("small", out_small, small_ms), ("large", out_large, large_ms)):
            for metric in ("elapsed_coro_resume_ms", "elapsed_coro_wrap_ms"):
                elapsed = parse_metric(out, metric)
                if not (bound_ms <= elapsed < bound_ms + 300):
                    print(
                        f"FAIL: {metric} ({label}) took {elapsed}ms, expected close to {bound_ms}ms - "
                        "coroutine watchdog is not bounding coroutine.resume()/wrap()",
                        file=sys.stderr,
                    )
                    return 1

    print("Lua chunk watchdog smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
