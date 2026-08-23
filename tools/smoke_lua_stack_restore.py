#!/usr/bin/env python3
"""[П27] Поведенческая проверка: lua_exec_locked (lua.h) обязан восстанавливать
высоту стека Lua после lua.Lua_dostring - вендорная LuaWrapper::Lua_dostring
делает luaL_dostring (=> lua_pcall(..., LUA_MULTRET, ...)), и без явного
lua_settop возвращённые чанком значения оставались бы на стеке навсегда,
на каждый вызов run_lua_string/периодического чанка.

Берёт РЕАЛЬНОЕ тело lua_exec_locked (вместе с timeout-hook инфраструктурой,
от которой оно зависит) через срез текста lua.h - без переписывания логики -
и гоняет его с настоящим вендорным Lua 5.4 (как smoke_lua_chunk_watchdog.py и
smoke_lua_a07.py). Проверяемое поведение: серия вызовов чанка `return 1,2,3`
не увеличивает lua_gettop; чанк с ошибкой компиляции тоже не оставляет мусора
на стеке.
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
#include <cstdint>
#include <iostream>
#include <string>

class String : public std::string {
 public:
  using std::string::operator=;
  String() = default;
  String(const char* value) : std::string(value ? value : "") {}
  String(const std::string& value) : std::string(value) {}
};

String operator+(const char* left, const String& right) {
  return String(std::string(left ? left : "") + right);
}
String operator+(const String& left, const char* right) {
  return String(static_cast<const std::string&>(left) + (right ? right : ""));
}

extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}

#include "safety_transition.h"

enum { ALARM_MSG = 0 };
static int sendMsgCalls = 0;
static void SendMsg(const char* m, int type) {
  (void)m;
  (void)type;
  sendMsgCalls++;
}

static uint32_t fakeMillis = 0;
static uint32_t millis() { return fakeMillis; }

// Минимальная замена вендорной LuaWrapper: под тестом функция lua_exec_locked
// (реальное тело, вставлено ниже), а не сама Lua_dostring - поэтому здесь
// достаточно воспроизвести её контракт (luaL_dostring + текст ошибки).
struct FakeLuaWrapper {
  lua_State* state = nullptr;
  lua_State* GetState() { return state; }
  String Lua_dostring(const String* script) {
    String result;
    if (luaL_dostring(state, script->c_str())) {
      result = String("# lua error:\n") + lua_tostring(state, -1);
      lua_pop(state, 1);
    }
    return result;
  }
};
static FakeLuaWrapper lua;

@EXEC_LOCKED_BLOCK@

static int failures = 0;
static void check(bool cond, const char* msg) {
  if (!cond) {
    std::cerr << "FAIL: " << msg << "\n";
    failures++;
  }
}

int main() {
  lua_State* L = luaL_newstate();
  check(L != nullptr, "luaL_newstate failed");
  if (!L) return 1;
  luaL_openlibs(L);
  lua.state = L;

  const int base = lua_gettop(L);
  for (int i = 0; i < 5; i++) {
    String script = "return 1,2,3";
    String result = lua_exec_locked(script);
    check(result.length() == 0, "lua_exec_locked reported an error for a trivial multi-return chunk");
    check(lua_gettop(L) == base, "lua_exec_locked leaked return values on the Lua stack");
  }

  String bad = "return (";
  String badResult = lua_exec_locked(bad);
  check(badResult.length() > 0, "lua_exec_locked did not report a compile error for a broken chunk");
  check(lua_gettop(L) == base, "lua_exec_locked leaked stack on a compile-error chunk");

  lua_close(L);
  if (failures != 0) return 1;
  std::cout << "Lua exec_locked stack restore smoke check passed\n";
  return 0;
}
'''


def main() -> int:
    lua_source = (ROOT / "lua.h").read_text(encoding="utf-8")
    try:
        exec_locked_block = source_slice(
            lua_source, "#ifndef LUA_CHUNK_TIMEOUT_MS", "inline String lua_exec(String& script"
        )
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = HARNESS_TEMPLATE.replace("@EXEC_LOCKED_BLOCK@", exec_locked_block)

    sources = sorted(p for p in LUA_DIR.glob("*.c") if p.name not in {"lua.c", "luac.c"})
    with tempfile.TemporaryDirectory(prefix="samovar-lua-stack-") as temp_dir:
        temp = Path(temp_dir)
        harness_path = temp / "lua_exec_stack_test.cpp"
        harness_path.write_text(harness, encoding="utf-8")
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

        binary = temp / "lua_exec_stack_test"
        result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(LUA_DIR), "-I", str(ROOT), str(harness_path),
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


if __name__ == "__main__":
    raise SystemExit(main())
