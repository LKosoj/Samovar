#!/usr/bin/env python3
"""Active program Lua file is recompiled only after a successful /edit upload."""

import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "inline bool reload_program_lua_job(const String& changedFile)"

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>

#define F(value) value
constexpr int LUA_NOREF = -2;
constexpr int LUA_REFNIL = -1;
static int pdMS_TO_TICKS(int value) { return value; }

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  size_t length() const { return value_.length(); }
  char charAt(size_t index) const { return value_.at(index); }
  void remove(size_t index, size_t count = std::string::npos) { value_.erase(index, count); }
  const char* c_str() const { return value_.c_str(); }
  bool operator==(const String& other) const { return value_ == other.value_; }
  bool operator!=(const String& other) const { return value_ != other.value_; }
  friend String operator+(const char* left, const String& right) {
    return String((std::string(left) + right.value_).c_str());
  }
  friend String operator+(const String& left, const char* right) {
    return String((left.value_ + std::string(right)).c_str());
  }
  friend String operator+(const String& left, const String& right) {
    return String((left.value_ + right.value_).c_str());
  }
 private:
  std::string value_;
};

enum LuaBeerJobResult : uint8_t {
  LUA_BEER_JOB_IDLE = 0,
  LUA_BEER_JOB_RUNNING,
  LUA_BEER_JOB_FAILED_RUNTIME,
};

static bool runtimeLockAvailable = true;
static bool luaLockAvailable = true;
static bool lua_program_job = true;
static String lua_program_script_name("stage.lua");
static String lua_program_script_text("old body");
static int lua_program_script_ref = 17;
static LuaBeerJobResult lua_beer_job_result = LUA_BEER_JOB_RUNNING;
static String storedScript("new body");
static int readCount = 0;
static int compileCount = 0;
static int unrefOldCount = 0;

static bool runtime_state_lock(int = 50) { return runtimeLockAvailable; }
static void runtime_state_unlock(bool) {}
static bool lua_state_lock(int) { return luaLockAvailable; }
static void lua_state_unlock(bool) {}
static String get_lua_script(String) { readCount++; return storedScript; }
static void WriteConsoleLog(String) {}
static void lua_unref_chunk_locked(int& ref) {
  if (ref == 17) unrefOldCount++;
  ref = LUA_NOREF;
}
static String lua_compile_chunk_locked(const String& script, const char*, int& ref) {
  compileCount++;
  if (script == String("bad")) {
    ref = LUA_NOREF;
    return String("compile failed");
  }
  ref = 29;
  return String();
}

@FUNCTION@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset() {
  runtimeLockAvailable = true;
  luaLockAvailable = true;
  lua_program_job = true;
  lua_program_script_name = String("stage.lua");
  lua_program_script_text = String("old body");
  lua_program_script_ref = 17;
  lua_beer_job_result = LUA_BEER_JOB_RUNNING;
  storedScript = String("new body");
  readCount = 0;
  compileCount = 0;
  unrefOldCount = 0;
}

int main() {
  reset();
  check(reload_program_lua_job(String("/other.lua")),
        "unselected Lua upload must be accepted without touching the active job");
  check(readCount == 0 && compileCount == 0 && lua_program_script_ref == 17,
        "unselected Lua upload must not read, compile, or replace the active program chunk");

  reset();
  check(reload_program_lua_job(String("/stage.lua")),
        "selected Lua upload must be processed");
  check(readCount == 1 && compileCount == 1,
        "selected Lua upload must read and compile exactly once");
  check(lua_program_script_ref == 29 && lua_program_script_text == String("new body") &&
            unrefOldCount == 1,
        "successful compile must atomically replace the old active chunk and its source");

  reset();
  storedScript = String("bad");
  check(reload_program_lua_job(String("stage.lua")),
        "compile error is a handled upload result, not a lock retry");
  check(lua_program_script_ref == LUA_NOREF && unrefOldCount == 1,
        "compile error must invalidate the old chunk so it cannot run as a fallback");
  check(lua_beer_job_result == LUA_BEER_JOB_FAILED_RUNTIME,
        "compile error must fail the active program Lua job");

  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(source: str, label: str, show: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-lua-program-reload-") as temp_dir:
        cpp = Path(temp_dir) / "test.cpp"
        binary = Path(temp_dir) / "test"
        cpp.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            output = compiled.stdout + compiled.stderr
            if show:
                sys.stderr.write(f"[{label}] compile failed:\n{output}")
            return compiled.returncode, output
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        output = ran.stdout + ran.stderr
        if show:
            sys.stdout.write(ran.stdout)
            sys.stderr.write(ran.stderr)
        return ran.returncode, output


def main() -> int:
    lua = (ROOT / "lua.h").read_text(encoding="utf-8")
    editor = (ROOT / "SPIFFSEditor.h").read_text(encoding="utf-8")
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    body = extract_function_body(lua, SIGNATURE)
    errors: list[str] = []
    require_ordered_tokens(
        "selected program Lua reload",
        body,
        [
            "if (selectedFile != fileName) return true;",
            "const String script = get_lua_script(fileName);",
            "lua_compile_chunk_locked",
            "lua_program_script_ref = newRef;",
            "lua_program_script_text = script;",
        ],
        errors,
    )
    require_ordered_tokens(
        "failed compile disables old program chunk",
        body,
        [
            "compileError.length() == 0",
            "lua_program_script_ref = LUA_NOREF;",
            "lua_beer_job_result = LUA_BEER_JOB_FAILED_RUNTIME;",
            "lua_unref_chunk_locked(oldRef);",
        ],
        errors,
    )
    if "pending_lua_reload_file = p;" not in editor:
        errors.append("/edit final upload does not queue the changed Lua filename")
    if "reload_program_lua_job(changedLuaFile)" not in samovar:
        errors.append("main loop does not apply the queued program Lua reload")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = HARNESS.replace("@FUNCTION@", f"{SIGNATURE} {{\n{body}\n}}")
    code, _ = compile_and_run(harness, "program Lua reload")
    if code:
        return 1

    mutations = [
        (
            "if (selectedFile != fileName) return true;",
            "if (false) return true;",
            "unselected Lua upload must not read, compile, or replace the active program chunk",
        ),
        (
            "lua_program_script_ref = newRef;",
            "lua_program_script_ref = oldRef;",
            "successful compile must atomically replace the old active chunk and its source",
        ),
        (
            "lua_program_script_ref = LUA_NOREF;",
            "lua_program_script_ref = oldRef;",
            "compile error must invalidate the old chunk so it cannot run as a fallback",
        ),
    ]
    for old, new, expected in mutations:
        mutant = harness.replace(old, new, 1)
        mutant_code, output = compile_and_run(mutant, expected, False)
        if mutant_code == 0 or expected not in output:
            print(f"FAIL: mutation survived: {expected}", file=sys.stderr)
            sys.stderr.write(output)
            return 1

    print("Lua program reload smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
