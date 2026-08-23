#!/usr/bin/env python3
"""[П26] Поведенческая проверка предела хранилища setObject/getObject (lua.h).

Раньше luaObj (SimpleMap<String,String>) рос без предела - clear() не звался
нигде, число ключей ничем не ограничено. Берёт РЕАЛЬНОЕ тело
lua_wrapper_set_object()/load_lua_script() из lua.h (через extract_function_body
- без переписывания логики) и исполняет его в g++-харнессе с НАСТОЯЩИМ
libraries/SimpleMap/src/SimpleMap.h (та же структура данных, что и в прошивке -
has()/size()/put()/clear() не мокаются).

Проверяемое поведение:
1. Хранилище заполнено до LUA_OBJECT_STORE_MAX_KEYS - добавление НОВОГО ключа
   даёт luaL_error, значение в хранилище не появляется.
2. Обновление УЖЕ существующего ключа при заполненном хранилище лимит не
   расходует и проходит без ошибки (has() отличает "ключа нет" от "значение -
   пустая строка", чего get() не умеет).
3. Смена РЕЖИМНОГО скрипта (lua_type_script другой) в load_lua_script()
   очищает хранилище.
4. Перезагрузка ТОГО ЖЕ САМОГО скрипта (lua_type_script не менялся - например,
   редактирование через веб) хранилище НЕ трогает: rectificat.lua держит там
   total_volume/tank_filled, dist.lua - sg/gb, и это состояние прогона нельзя
   терять при простом релоаде.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SIMPLEMAP_INCLUDE_DIR = ROOT / "libraries/SimpleMap/src"

SIGNATURES = [
    "static int lua_wrapper_set_object(lua_State *lua_state)",
    "void load_lua_script()",
]

HARNESS_TEMPLATE = r'''
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

using TickType_t = int;
constexpr TickType_t portMAX_DELAY = -1;
constexpr int portTICK_PERIOD_MS = 1;

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  size_t length() const { return value_.length(); }
  const char* c_str() const { return value_.c_str(); }
  void clear() { value_.clear(); }
  String operator+(const String& other) const { return String((value_ + other.value_).c_str()); }
  bool operator==(const String& other) const { return value_ == other.value_; }
  bool operator!=(const String& other) const { return value_ != other.value_; }
  bool operator>(const String& other) const { return value_ > other.value_; }

  std::string value_;
};
static String operator+(const char* lhs, const String& rhs) { return String(lhs) + rhs; }

#include "SimpleMap.h"

struct lua_State;  // opaque - тело lua_wrapper_set_object трогает его только
                    // через lua_to_string_arg/lua_reject_state_mutation ниже,
                    // напрямую с Lua C API не работает.
static void vTaskDelay(int) {}

static bool mutationAllowed = true;
static bool lua_state_mutation_allowed() { return mutationAllowed; }
static int rejectCalls = 0;
static int lua_reject_state_mutation(lua_State*) {
  rejectCalls++;
  return -1;
}

static std::string argVar, argVal;
static String lua_to_string_arg(lua_State*, int index) {
  return String((index == 1 ? argVar : argVal).c_str());
}

static int luaLErrorCalls = 0;
static std::string luaLErrorMessage;
static int luaL_error(lua_State*, const char* fmt, ...) {
  luaLErrorCalls++;
  char buffer[256];
  va_list args;
  va_start(args, fmt);
  vsnprintf(buffer, sizeof(buffer), fmt, args);
  va_end(args);
  luaLErrorMessage = buffer;
  return -1;
}

// [П26] предел числа РАЗНЫХ ключей - объявлен в lua.h на уровне файла (не
// внутри какой-либо функции), поэтому extract_function_body его не
// захватывает; переобъявляем здесь тем же значением (проверяется в main()
// против реального #define в lua.h).
#ifndef LUA_OBJECT_STORE_MAX_KEYS
#define LUA_OBJECT_STORE_MAX_KEYS 32
#endif

static int compareStrings(String& a, String& b) {
  if (a == b) return 0;
  else if (a > b) return 1;
  else return -1;
}
static SimpleMap<String, String>* luaObj = new SimpleMap<String, String>(compareStrings);

// --- зависимости load_lua_script() (компиляция/чтение скриптов с SPIFFS) ---
static bool lua_boot_init_ready = true;
static bool lua_coroutine_watchdog_ready = true;
static bool lua_runtime_ready = false;
static uint8_t lua_periodic_failure_count_script1 = 0;  // трогается load_lua_script() (П30), не предмет этого теста
static uint8_t lua_periodic_failure_count_script2 = 0;
static bool lua_script1_disabled = false;
static String lua_type_script;
static String script1, script2;
static int script1_ref = 7;
static int script2_ref = 7;
static String lua_script_list_cache;
static std::vector<std::string> consoleLog;
static void WriteConsoleLog(const String& message) { consoleLog.push_back(message.value_); }
static const char* F(const char* text) { return text; }
static bool lua_state_lock(TickType_t) { return true; }
static void lua_state_unlock(bool) {}
static bool runtime_state_lock(TickType_t) { return true; }
static void runtime_state_unlock(bool) {}
static std::string getScriptStub, getScriptListStub, compileErrorStub;
static String get_lua_script(String) { return String(getScriptStub.c_str()); }
static String get_lua_script_list() { return String(getScriptListStub.c_str()); }
static String lua_compile_chunk_locked(const String&, const char*, int&) {
  return String(compileErrorStub.c_str());
}

@FUNCTIONS@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  mutationAllowed = true;
  rejectCalls = 0;
  luaLErrorCalls = 0;
  luaLErrorMessage.clear();
  argVar.clear();
  argVal.clear();
  luaObj->clear();
  lua_periodic_failure_count_script1 = 0;
  lua_periodic_failure_count_script2 = 0;
  lua_script1_disabled = false;
  lua_type_script = String("");
  consoleLog.clear();
}

static void fill_object_store(int count) {
  for (int i = 0; i < count; i++) {
    argVar = "key" + std::to_string(i);
    argVal = "value" + std::to_string(i);
    lua_wrapper_set_object(nullptr);
  }
}

static void test_new_key_over_limit_is_rejected() {
  reset_fixture();
  fill_object_store(LUA_OBJECT_STORE_MAX_KEYS);
  check(luaObj->size() == LUA_OBJECT_STORE_MAX_KEYS, "fixture must fill the store to exactly the limit");
  argVar = "brand-new-key";
  argVal = "x";
  const int rc = lua_wrapper_set_object(nullptr);
  check(rc == -1 && luaLErrorCalls == 1, "a new key over the limit must raise a Lua error");
  check(!luaObj->has(String("brand-new-key")), "a rejected new key must not appear in the store");
  check(luaObj->size() == LUA_OBJECT_STORE_MAX_KEYS, "a rejected new key must not change the store size");
}

static void test_updating_existing_key_at_limit_succeeds() {
  reset_fixture();
  fill_object_store(LUA_OBJECT_STORE_MAX_KEYS);
  argVar = "key0";
  argVal = "updated-value";
  const int rc = lua_wrapper_set_object(nullptr);
  check(rc == 0 && luaLErrorCalls == 0, "updating an existing key at a full store must not error");
  check(luaObj->get(String("key0")) == String("updated-value"),
        "updating an existing key at a full store must actually store the new value");
  check(luaObj->size() == LUA_OBJECT_STORE_MAX_KEYS, "updating an existing key must not grow the store");
}

static void test_mode_script_change_clears_store() {
  reset_fixture();
  lua_type_script = String("rectificat.lua");
  load_lua_script();  // первая загрузка режима - lua_last_loaded_type_script ещё пуст
  argVar = "total_volume";
  argVal = "12.5";
  lua_wrapper_set_object(nullptr);
  check(luaObj->has(String("total_volume")), "fixture must actually store the key before switching modes");

  lua_type_script = String("dist.lua");
  load_lua_script();
  check(!luaObj->has(String("total_volume")),
        "switching the mode script (different lua_type_script) must clear the object store");
}

static void test_same_script_reload_keeps_store() {
  reset_fixture();
  lua_type_script = String("rectificat.lua");
  load_lua_script();
  argVar = "tank_filled";
  argVal = "1";
  lua_wrapper_set_object(nullptr);
  check(luaObj->has(String("tank_filled")), "fixture must actually store the key before reloading");

  load_lua_script();  // lua_type_script не менялся - как при "Reload" через веб
  check(luaObj->has(String("tank_filled")),
        "reloading the SAME mode script must keep object-store state (rectificat.lua/dist.lua rely on this)");
}

int main() {
  test_new_key_over_limit_is_rejected();
  test_updating_existing_key_at_limit_succeeds();
  test_mode_script_change_clears_store();
  test_same_script_reload_keeps_store();
  return failures == 0 ? 0 : 1;
}
'''


def production_object_store_limit(source: str) -> int:
    import re
    match = re.search(r"#define LUA_OBJECT_STORE_MAX_KEYS\s+(\d+)", source)
    if not match:
        raise ValueError("LUA_OBJECT_STORE_MAX_KEYS #define not found in lua.h")
    return int(match.group(1))


def build_harness(source: str) -> str:
    # Харнесс переобъявляет лимит со значением 32 (см. шаблон выше) - сверяем
    # его с реальным значением из lua.h, чтобы тест не тестировал устаревшее
    # число незаметно для читающего.
    limit = production_object_store_limit(source)
    if limit != 32:
        raise ValueError(
            f"LUA_OBJECT_STORE_MAX_KEYS changed to {limit} in lua.h - "
            "update the hardcoded value in this harness's test scenarios"
        )
    definitions = []
    for signature in SIGNATURES:
        body = extract_function_body(source, signature)
        definitions.append(f"{signature} {{\n{body}\n}}")
    return HARNESS_TEMPLATE.replace("@FUNCTIONS@", "\n\n".join(definitions))


def compile_and_run(harness: str, label: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-lua-object-store-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "lua_object_store_test.cpp"
        binary = temp / "lua_object_store_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             f"-I{SIMPLEMAP_INCLUDE_DIR}", str(source), "-o", str(binary)],
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
        print(f"FAIL: {expected} mutation survived", file=sys.stderr)
        sys.stderr.write(output)
        return False
    return True


def main() -> int:
    lua = (ROOT / "lua.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(lua)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    code, _ = compile_and_run(harness, "Lua object store limit")
    if code:
        return 1
    mutations = [
        (
            "if (luaObj->has(Var) || luaObj->size() < LUA_OBJECT_STORE_MAX_KEYS) {",
            "if (true || luaObj->size() < LUA_OBJECT_STORE_MAX_KEYS) {",
            "a new key over the limit must raise a Lua error",
        ),
        (
            "if (lua_last_loaded_type_script != lua_type_script) {",
            "if (false && lua_last_loaded_type_script != lua_type_script) {",
            "switching the mode script (different lua_type_script) must clear the object store",
        ),
    ]
    for old, new, expected in mutations:
        if not require_mutation(harness, old, new, expected):
            return 1
    print("Lua object store limit mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
