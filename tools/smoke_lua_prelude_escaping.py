#!/usr/bin/env python3
"""[П29] Прелюдия переменных (get_global_variables() в lua.h) склеивает
значения из внешних/пользовательских источников прямо в ТЕКСТ Lua-кода, а не
передаёт их как настоящие Lua-строки. Без экранирования кавычка или перевод
строки в test_str_val (пишется скриптом через setStrVariable) ломают
компиляцию ВСЕХ кнопочных скриптов до перезагрузки; NaN-температура датчика
превращается в String(float) в текст "nan" - это имя неопределённой Lua-
глобали (компиляция пройдёт, значение станет nil без ошибки), и скрипт
падает позже и в другом месте.

Проверяем РЕАЛЬНЫЕ тела lua_escape_prelude_string/lua_prelude_number (через
extract_function_body - без переписывания логики), компилируя и исполняя
получившуюся строку прелюдии настоящим вендорным Lua 5.4 (как smoke_lua_a07.py
и smoke_lua_chunk_watchdog.py):
- test_str_val с кавычкой, обратным слешем и переводом строки - компиляция
  проходит, значение читается ДОСЛОВНО (без потери/искажения символов).
- SteamTemp = NaN/+Inf/-Inf остаётся ЧИСЛОМ (lua_isnumber), а не nil.
- Обычное конечное значение температуры проходит как обычное число.

Плюс текстовая проверка (require_token), что get_global_variables() в lua.h
реально зовёт эти хелперы в нужных местах - т.е. что хелперы не просто
существуют, а подключены к прелюдии.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
LUA_DIR = ROOT / "libraries/ESP-Arduino-Lua/src/lua"

lua_text_raw = (ROOT / "lua.h").read_text(encoding="utf-8")
lua_text = strip_cpp_comments(lua_text_raw)

errors: list[str] = []

try:
    global_vars_body = extract_function_body(lua_text, "String get_global_variables()")
except ValueError as exc:
    errors.append(str(exc))
    global_vars_body = ""

for token in [
    'lua_escape_prelude_string(test_str_val)',
    'lua_prelude_number(SteamSensor.avgTemp)',
    'lua_prelude_number(PipeSensor.avgTemp)',
    'lua_prelude_number(WaterSensor.avgTemp)',
    'lua_prelude_number(TankSensor.avgTemp)',
    'lua_prelude_number(ACPSensor.avgTemp)',
]:
    if token not in global_vars_body:
        errors.append(f"get_global_variables() does not use: {token}")

if errors:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    sys.exit(1)

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

class String : public std::string {
 public:
  using std::string::operator=;
  String() = default;
  String(const char* value) : std::string(value ? value : "") {}
  String(const std::string& value) : std::string(value) {}
  explicit String(float value) : std::string(std::to_string(value)) {}
  void reserve(size_t n) { std::string::reserve(n); }
};

using std::isnan;
using std::isinf;

String operator+(const char* left, const String& right) {
  return String(std::string(left ? left : "") + right);
}
String operator+(const String& left, const char* right) {
  return String(static_cast<const std::string&>(left) + (right ? right : ""));
}

// Реализация String(float) как у Arduino WString: обычное текстовое
// представление (в т.ч. "nan"/"inf" для не-конечных значений) - именно тот
// путь, который lua_prelude_number обязан обходить.
String string_from_float(float value) {
  char buf[64];
  snprintf(buf, sizeof(buf), "%.2f", value);
  return String(buf);
}

extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}

@ESCAPE_BLOCK@

@NUMBER_BLOCK@

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

  // (a) test_str_val с кавычкой, обратным слешем и переводом строки -
  // ровно то, что реально приходит из setStrVariable('test_str_val', ...).
  const String raw = String("He said \"hi\"\\nline2\r\nend");
  String prelude = "test_str_val = \"" + lua_escape_prelude_string(raw) + "\"\r\n";
  const int loadRc = luaL_loadstring(L, prelude.c_str());
  if (loadRc != LUA_OK) {
    const char* err = lua_tostring(L, -1);
    std::cerr << "prelude did not compile: " << (err ? err : "?") << "\n";
    check(false, "prelude with quote/backslash/newline in test_str_val failed to compile");
  } else {
    check(lua_pcall(L, 0, 0, 0) == LUA_OK, "prelude with escaped test_str_val failed to run");
    lua_getglobal(L, "test_str_val");
    const char* readBack = lua_tostring(L, -1);
    check(readBack != nullptr, "test_str_val global was not a string after prelude");
    check(readBack != nullptr && raw == String(readBack),
          "test_str_val round-trip lost or mangled special characters");
    lua_pop(L, 1);
  }

  // (b) NaN/+-Inf температура обязана остаться Lua-числом (не именем
  // неопределённой глобали -> nil).
  struct Case { const char* label; float value; bool expectFinite; };
  const Case cases[] = {
      {"NaN", NAN, false},
      {"+Inf", INFINITY, false},
      {"-Inf", -INFINITY, false},
      {"finite", 42.5f, true},
  };
  for (const Case& c : cases) {
    String line = "SteamTemp = " + lua_prelude_number(c.value) + "\r\n";
    const int rc = luaL_loadstring(L, line.c_str());
    std::string label = std::string("SteamTemp prelude line for ") + c.label;
    if (rc != LUA_OK) {
      check(false, (label + " did not compile").c_str());
      continue;
    }
    check(lua_pcall(L, 0, 0, 0) == LUA_OK, (label + " failed to run").c_str());
    lua_getglobal(L, "SteamTemp");
    check(lua_isnumber(L, -1) != 0, (label + " left SteamTemp as nil/non-number").c_str());
    if (lua_isnumber(L, -1)) {
      const double value = lua_tonumber(L, -1);
      if (c.expectFinite) {
        check(std::fabs(value - c.value) < 0.01, (label + " lost precision").c_str());
      } else if (std::isnan(c.value)) {
        check(std::isnan(value), (label + " did not produce a real NaN").c_str());
      } else {
        check(std::isinf(value) && ((value > 0) == (c.value > 0)),
              (label + " did not produce a real signed Inf").c_str());
      }
    }
    lua_pop(L, 1);
  }

  // (c) Демонстрация БЕЗ хелпера: String(float) на NaN дало бы текст "nan" -
  // непроверяемое имя, читающееся как nil, а НЕ как ошибка компиляции.
  {
    String badLine = "SteamTemp = " + string_from_float(NAN) + "\r\n";
    check(luaL_loadstring(L, badLine.c_str()) == LUA_OK,
          "sanity: unescaped String(NaN) line was expected to compile (as an undefined-global read)");
    lua_pcall(L, 0, 0, 0);
    lua_getglobal(L, "SteamTemp");
    check(lua_isnil(L, -1),
          "sanity: unescaped String(NaN) line was expected to read back as nil, contradicting the exploit description");
    lua_pop(L, 1);
  }

  lua_close(L);
  if (failures != 0) return 1;
  std::cout << "Lua prelude escaping smoke check passed\n";
  return 0;
}
'''


def main() -> int:
    try:
        escape_block = (
            "inline String lua_escape_prelude_string(const String& value) {\n"
            + extract_function_body(lua_text_raw, "inline String lua_escape_prelude_string(const String& value)")
            + "\n}\n"
        )
        number_block = (
            "inline String lua_prelude_number(float value) {\n"
            + extract_function_body(lua_text_raw, "inline String lua_prelude_number(float value)")
            + "\n}\n"
        )
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = HARNESS_TEMPLATE.replace("@ESCAPE_BLOCK@", escape_block)
    harness = harness.replace("@NUMBER_BLOCK@", number_block)

    sources = sorted(p for p in LUA_DIR.glob("*.c") if p.name not in {"lua.c", "luac.c"})
    with tempfile.TemporaryDirectory(prefix="samovar-lua-prelude-") as temp_dir:
        temp = Path(temp_dir)
        harness_path = temp / "lua_prelude_test.cpp"
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

        binary = temp / "lua_prelude_test"
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
