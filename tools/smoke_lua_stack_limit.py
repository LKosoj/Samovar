#!/usr/bin/env python3
"""Понижен предел стека Lua (LUAI_MAXSTACK, luaconf.h) - было 1 000 000 в
ветке #if LUAI_IS32INT (актуальной и на ESP32, и на хосте: LUAI_IS32INT =
((UINT_MAX >> 30) >= 3), а int 32-битный и там, и там). 1 000 000 слотов - это
до 8 МБ Lua-стека; рекурсивный (не хвостовой) пользовательский Lua-скрипт на
ESP32 исчерпывал реальную кучу контроллера задолго до этого предела и ронял
прошивку по нехватке памяти, а не получал штатную ошибку Lua. Новое значение -
6000, обёрнуто в #ifndef, чтобы его можно было переопределить флагом сборки.

По образцу smoke_lua_stack_restore.py:
1) Текстовая проверка #ifndef/#define в ветке #if LUAI_IS32INT.
2) Поведенческая: компилирует РЕАЛЬНЫЙ вендорный Lua 5.4 (файлы .c из
   libraries/ESP-Arduino-Lua/src/lua) с РЕАЛЬНЫМ luaconf.h и гоняет
   бесконечно рекурсивную (не хвостовую - "1 + f(n+1)", не "return f(n+1)")
   Lua-функцию через lua_pcall (luaL_dostring). Ожидаем контролируемую ошибку
   с текстом "stack overflow", а не падение процесса.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LUA_DIR = ROOT / "libraries/ESP-Arduino-Lua/src/lua"
LUACONF_PATH = LUA_DIR / "luaconf.h"

HARNESS = r'''
#include <iostream>
#include <string>

extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}

int main() {
  lua_State* L = luaL_newstate();
  if (!L) {
    std::cerr << "FAIL: luaL_newstate failed\n";
    return 1;
  }
  luaL_openlibs(L);

  // "1 + f(n + 1)" - НЕ хвостовой вызов, каждый уровень рекурсии держит свой
  // кадр на стеке Lua (в отличие от "return f(n + 1)", который переиспользует
  // текущий кадр и никогда не переполнится).
  const char* script =
      "local function f(n) return 1 + f(n + 1) end\n"
      "return f(1)\n";

  const int rc = luaL_dostring(L, script);
  if (rc == 0) {
    std::cerr << "FAIL: infinite non-tail Lua recursion did not raise an error\n";
    lua_close(L);
    return 1;
  }
  const char* message = lua_tostring(L, -1);
  const std::string text = message ? message : "";
  if (text.find("stack overflow") == std::string::npos) {
    std::cerr << "FAIL: expected \"stack overflow\" in the error, got: " << text << "\n";
    lua_close(L);
    return 1;
  }
  lua_pop(L, 1);
  lua_close(L);
  std::cout << "Lua stack limit smoke check passed: " << text << "\n";
  return 0;
}
'''


def check_text(errors: list[str]) -> None:
    source = LUACONF_PATH.read_text(encoding="utf-8")
    match = re.search(r"#if LUAI_IS32INT\r?\n(.*?)\r?\n#else", source, re.S)
    if not match:
        errors.append("luaconf.h: ветка #if LUAI_IS32INT не найдена")
        return
    branch = match.group(1)
    if "#ifndef LUAI_MAXSTACK" not in branch or "#endif" not in branch:
        errors.append(
            "luaconf.h: LUAI_MAXSTACK в ветке #if LUAI_IS32INT должен быть "
            "обёрнут в #ifndef/#endif, чтобы его можно было переопределить "
            "флагом сборки"
        )
    value_match = re.search(r"#define\s+LUAI_MAXSTACK\s+(\d+)", branch)
    if not value_match:
        errors.append("luaconf.h: #define LUAI_MAXSTACK не найден в ветке #if LUAI_IS32INT")
    elif value_match.group(1) != "6000":
        errors.append(
            f"luaconf.h: LUAI_MAXSTACK в ветке #if LUAI_IS32INT = "
            f"{value_match.group(1)}, ожидалось 6000"
        )


def compile_and_run() -> int:
    sources = sorted(p for p in LUA_DIR.glob("*.c") if p.name not in {"lua.c", "luac.c"})
    with tempfile.TemporaryDirectory(prefix="samovar-lua-stack-limit-") as temp_dir:
        temp = Path(temp_dir)
        objects = []
        for source in sources:
            object_path = temp / f"{source.stem}.o"
            result = subprocess.run(
                ["gcc", "-std=c11", "-O0", "-I", str(LUA_DIR), "-c", str(source), "-o", str(object_path)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                sys.stdout.write(result.stdout)
                sys.stderr.write(result.stderr)
                return result.returncode
            objects.append(object_path)

        harness_path = temp / "lua_stack_limit_test.cpp"
        harness_path.write_text(HARNESS, encoding="utf-8")
        binary = temp / "lua_stack_limit_test"
        result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(LUA_DIR), str(harness_path),
                *[str(p) for p in objects], "-lm", "-ldl", "-o", str(binary),
            ],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode

        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False, timeout=15
        )
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    errors: list[str] = []
    check_text(errors)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return compile_and_run()


if __name__ == "__main__":
    raise SystemExit(main())
