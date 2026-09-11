#!/usr/bin/env python3
"""R1: штатный dist.lua не переключает ёмкости по недоступной спиртуозности."""
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "data_raw/dist.lua"
LUA_DIR = ROOT / "libraries/ESP-Arduino-Lua/src/lua"

HARNESS = r'''
#include <cstdlib>
#include <iostream>
#include <map>
#include <string>

extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}

struct State {
  double alcohol = 0, alcoholStart = 0, boilTemp = 85, tankTemp = 85;
  double powerOn = 1, targetPower = 150;
  int capacity = 0, warnings = 0, warningPriority = -1;
  std::map<std::string, std::string> objects;
} state;

static double number(const char* name) {
  const std::string key(name);
  if (key == "alcohol") return state.alcohol;
  if (key == "alcohol_s") return state.alcoholStart;
  if (key == "boil_temp") return state.boilTemp;
  if (key == "TankTemp") return state.tankTemp;
  if (key == "PowerOn") return state.powerOn;
  if (key == "target_power_volt") return state.targetPower;
  if (key == "capacity_num") return state.capacity;
  return 0;
}

static int get_number(lua_State* L) {
  lua_pushnumber(L, number(luaL_checkstring(L, 1)));
  return 1;
}

static int get_object(lua_State* L) {
  const char* key = luaL_checkstring(L, 1);
  const auto found = state.objects.find(key);
  std::string value = found == state.objects.end() ? "" : found->second;
  if (lua_gettop(L) == 2 && std::string(luaL_checkstring(L, 2)) == "NUMERIC" && value.empty()) {
    value = "0";
  }
  lua_pushstring(L, value.c_str());
  return 1;
}

static int set_object(lua_State* L) {
  const char* key = luaL_checkstring(L, 1);
  const char* value = luaL_tolstring(L, 2, nullptr);
  state.objects[key] = value;
  lua_pop(L, 1);
  return 0;
}

static int set_capacity(lua_State* L) {
  state.capacity = static_cast<int>(luaL_checkinteger(L, 1));
  return 0;
}

static int send_message(lua_State* L) {
  const char* message = luaL_checkstring(L, 1);
  if (std::string(message).find("Спиртуозность недоступна") != std::string::npos) {
    ++state.warnings;
    state.warningPriority = static_cast<int>(luaL_checkinteger(L, 2));
  }
  return 0;
}

static int set_power(lua_State* L) {
  state.powerOn = luaL_checknumber(L, 1);
  return 0;
}

static int set_current_power(lua_State* L) {
  state.targetPower = luaL_checknumber(L, 1);
  return 0;
}

static int ignore(lua_State* L) {
  (void)L;
  return 0;
}

static void register_callbacks(lua_State* L) {
  lua_register(L, "getNumVariable", get_number);
  lua_register(L, "getObject", get_object);
  lua_register(L, "setObject", set_object);
  lua_register(L, "setCapacity", set_capacity);
  lua_register(L, "sendMsg", send_message);
  lua_register(L, "setPower", set_power);
  lua_register(L, "setCurrentPower", set_current_power);
  lua_register(L, "setLuaStatus", ignore);
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << "\n";
    ++failures;
  }
}

static bool tick(lua_State* L, const char* path) {
  if (luaL_dofile(L, path) == LUA_OK) return true;
  std::cerr << "FAIL: dist.lua runtime error: " << lua_tostring(L, -1) << "\n";
  lua_pop(L, 1);
  ++failures;
  return false;
}

static void reset(double alcohol, double alcoholStart, int capacity, double tankTemp = 85) {
  state = State();
  state.alcohol = alcohol;
  state.alcoholStart = alcoholStart;
  state.capacity = capacity;
  state.tankTemp = tankTemp;
  state.objects["sg"] = "1";
  state.objects["gb"] = "1";
}

static void test_alcohol_mode(lua_State* L, const char* path) {
  reset(40, 50, 0);
  check(tick(L, path), "invalid-state flag must read numeric default");
  check(state.capacity == 0, "40 percent retains capacity 0");
  state.alcohol = 20;
  tick(L, path);
  check(state.capacity == 1, "20 percent switches capacity 0 to 1");

  reset(-1, 50, 0);
  tick(L, path);
  tick(L, path);
  check(state.capacity == 0, "invalid current keeps capacity");
  check(state.warnings == 1, "invalid current warns once per episode");
  check(state.warningPriority == 1, "invalid current warning has warning priority");
  state.alcohol = 20;
  tick(L, path);
  check(state.capacity == 1, "valid current recovers alcohol switching");
  state.alcohol = -1;
  tick(L, path);
  tick(L, path);
  check(state.capacity == 1, "second invalid episode keeps capacity");
  check(state.warnings == 2, "valid reading resets invalid-warning episode");

  reset(20, -1, 0);
  tick(L, path);
  tick(L, path);
  check(state.capacity == 0, "invalid initial alcohol keeps capacity");
  check(state.warnings == 1, "invalid initial alcohol warns once");

  reset(0, 50, 0);
  tick(L, path);
  check(state.capacity == 1, "real zero alcohol remains valid");
  check(state.warnings == 0, "real zero alcohol does not warn");

  reset(0, 0, 0);
  tick(L, path);
  check(state.capacity == 1, "real zero initial alcohol remains valid");
  check(state.warnings == 0, "real zero initial alcohol does not warn");
}

static void test_temperature_mode(lua_State* L, const char* path) {
  reset(-1, -1, 0, 89);
  tick(L, path);
  check(state.capacity == 1, "temperature mode remains independent of alcohol");
  check(state.warnings == 0, "temperature mode does not warn about alcohol");
}

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  lua_State* L = luaL_newstate();
  if (L == nullptr) return 2;
  luaL_openlibs(L);
  register_callbacks(L);
  test_alcohol_mode(L, argv[1]);
  lua_close(L);

  L = luaL_newstate();
  if (L == nullptr) return 2;
  luaL_openlibs(L);
  register_callbacks(L);
  test_temperature_mode(L, argv[2]);
  lua_close(L);
  return failures == 0 ? 0 : 1;
}
'''


def compile_and_run(source: str, label: str) -> tuple[int, str]:
    temperature_source = source.replace("use_temp = 0", "use_temp = 1", 1)
    if temperature_source == source:
        return 1, "FAIL: temperature-mode configuration anchor not found\n"
    with tempfile.TemporaryDirectory(prefix="samovar-dist-lua-") as directory:
        temp = Path(directory)
        alcohol_script = temp / "dist.lua"
        temperature_script = temp / "dist-temp.lua"
        harness_path = temp / "harness.cpp"
        binary = temp / "harness"
        alcohol_script.write_text(source, encoding="utf-8")
        temperature_script.write_text(temperature_source, encoding="utf-8")
        harness_path.write_text(HARNESS, encoding="utf-8")
        objects = []
        for lua_source in sorted(LUA_DIR.glob("*.c")):
            if lua_source.name in {"lua.c", "luac.c"}:
                continue
            object_path = temp / f"{lua_source.stem}.o"
            compiled = subprocess.run(
                ["gcc", "-std=c11", "-O0", "-I", str(LUA_DIR), "-c", str(lua_source), "-o", str(object_path)],
                capture_output=True, text=True, check=False,
            )
            if compiled.returncode:
                return compiled.returncode, compiled.stdout + compiled.stderr
            objects.append(object_path)
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(LUA_DIR), str(harness_path), *map(str, objects), "-lm", "-ldl", "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if compiled.returncode:
            return compiled.returncode, "COMPILE FAIL:\n" + compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary), str(alcohol_script), str(temperature_script)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def require_failure(source: str, label: str, expected: str) -> bool:
    result, output = compile_and_run(source, label)
    if result == 0 or expected not in output or "COMPILE FAIL:" in output:
        print(f"FAIL: {label} mutation was not meaningfully rejected:\n{output}", file=sys.stderr)
        return False
    print(f"{label} mutation rejected:\n{output}", end="")
    return True


def main() -> int:
    source = SCRIPT.read_text(encoding="utf-8")
    result, output = compile_and_run(source, "baseline")
    sys.stdout.write(output)
    if result:
        return result
    mutant = source.replace("if alcohol >= 0 and alcohol_s >= 0 then", "if true then", 1)
    if mutant == source:
        print("FAIL: invalid-alcohol guard mutation anchor not found", file=sys.stderr)
        return 1
    if not require_failure(mutant, "invalid-alcohol guard", "FAIL: invalid current keeps capacity"):
        return 1
    warning_mutant = source.replace(
        'sendMsg("Спиртуозность недоступна: переключение емкости отложено", 1)',
        'sendMsg("Спиртуозность недоступна: переключение емкости отложено", 2)',
        1,
    )
    if warning_mutant == source:
        print("FAIL: warning-priority mutation anchor not found", file=sys.stderr)
        return 1
    if not require_failure(warning_mutant, "warning priority", "FAIL: invalid current warning has warning priority"):
        return 1
    numeric_default_mutant = source.replace(
        'getObject("alcohol_invalid", "NUMERIC")',
        'getObject("alcohol_invalid")',
        1,
    )
    if numeric_default_mutant == source:
        print("FAIL: numeric-default mutation anchor not found", file=sys.stderr)
        return 1
    if not require_failure(numeric_default_mutant, "numeric default", "FAIL: invalid-state flag must read numeric default"):
        return 1
    print("dist.lua unavailable alcohol smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
