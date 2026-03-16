#!/usr/bin/env python3

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import state_inventory  # noqa: E402


RUNTIME_HEADER = ROOT / "ui" / "lua" / "runtime.h"
VARIABLES_HEADER = ROOT / "ui" / "lua" / "bindings_variables.h"
ROUTES_SETUP_HEADER = ROOT / "ui" / "web" / "routes_setup.h"
ORCHESTRATION_HEADER = ROOT / "app" / "orchestration.h"
SAMOVAR_INO = ROOT / "Samovar.ino"
GLOBALS_HEADER = ROOT / "state" / "globals.h"
MODE_OWNERSHIP_HEADER = ROOT / "src" / "core" / "state" / "mode_ownership.h"
MODE_CODES_HEADER = ROOT / "src" / "core" / "state" / "mode_codes.h"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_function(text: str, signature: str) -> str:
    pattern = re.compile(rf"(?:inline\s+)?{re.escape(signature)}\s*\{{", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Function signature not found: {signature}")

    brace_start = text.find("{", match.start())
    if brace_start == -1:
        raise AssertionError(f"Function body start not found: {signature}")

    depth = 0
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[match.start() : index + 1]

    raise AssertionError(f"Function body end not found: {signature}")


def assert_contains(body: str, fragment: str, label: str) -> None:
    require(fragment in body, f"{label}: missing fragment `{fragment}`")


def assert_ordered(body: str, fragments: list[str], label: str) -> None:
    position = 0
    for fragment in fragments:
        index = body.find(fragment, position)
        require(index != -1, f"{label}: missing or out-of-order fragment `{fragment}`")
        position = index + len(fragment)


def run_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    output = result.stdout
    if result.stderr:
        output += ("\n" if output and not output.endswith("\n") else "") + result.stderr
    return output


def check_static_contracts() -> None:
    print("=" * 72)
    print("Lua mode selection integration")
    print("=" * 72)

    runtime_text = read_text(RUNTIME_HEADER)
    routes_text = read_text(ROUTES_SETUP_HEADER)
    variables_text = read_text(VARIABLES_HEADER)
    orchestration_text = read_text(ORCHESTRATION_HEADER)
    globals_text = read_text(GLOBALS_HEADER)
    samovar_text = read_text(SAMOVAR_INO)

    get_lua_mode_name = extract_function(runtime_text, "String get_lua_mode_name(bool filename)")
    handle_save_process = extract_function(
        routes_text,
        "void handleSaveProcessSettings(AsyncWebServerRequest *request)",
    )
    set_num_variable = extract_function(
        variables_text,
        "static int lua_wrapper_set_num_variable(lua_State *lua_state)",
    )
    get_num_variable = extract_function(
        variables_text,
        "static int lua_wrapper_get_num_variable(lua_State *lua_state)",
    )

    print("\n[1] Verifying static Lua mode-selection contract...")
    assert_contains(
        get_lua_mode_name,
        "switch (mode_lua_owner(Samovar_CR_Mode))",
        "get_lua_mode_name",
    )
    for fragment in [
        "case SAMOVAR_BEER_MODE:",
        'fl = filename ? "/beer" + String(LUA_BEER) + ".lua" : "beer";',
        "case SAMOVAR_DISTILLATION_MODE:",
        'fl = filename ? "/dist" + String(LUA_DIST) + ".lua" : "dist";',
        "case SAMOVAR_BK_MODE:",
        'fl = filename ? "/bk" + String(LUA_BK) + ".lua" : "bk";',
        "case SAMOVAR_NBK_MODE:",
        'fl = filename ? "/nbk" + String(LUA_NBK) + ".lua" : "nbk";',
        "case SAMOVAR_RECTIFICATION_MODE:",
        "case SAMOVAR_SUVID_MODE:",
        "case SAMOVAR_LUA_MODE:",
        'fl = filename ? "/rectificat" + String(LUA_RECT) + ".lua" : "rect";',
    ]:
        assert_contains(get_lua_mode_name, fragment, "get_lua_mode_name")
    print("    ✓ get_lua_mode_name maps every runtime mode to an explicit Lua family")

    for fragment in [
        'Var == "SamSetup_Mode"',
        'Var == "Samovar_Mode"',
        'Var == "Samovar_CR_Mode"',
    ]:
        assert_contains(set_num_variable, fragment, "lua_wrapper_set_num_variable")
        assert_contains(get_num_variable, fragment, "lua_wrapper_get_num_variable")
    print("    ✓ Lua numeric bindings expose SamSetup_Mode, Samovar_Mode and Samovar_CR_Mode")

    require("#ifdef USE_LUA" in handle_save_process, "handleSaveProcessSettings: missing USE_LUA guard")
    assert_ordered(
        handle_save_process,
        [
            "save_profile_nvs();",
            "load_profile_nvs();",
            "#ifdef USE_LUA",
            "lua_type_script = get_lua_mode_name(true);",
            "load_lua_script();",
            "#endif",
            "change_samovar_mode();",
        ],
        "handleSaveProcessSettings",
    )
    print("    ✓ setup/save mode switching reloads Lua under USE_LUA before route rebinding")

    require(
        re.search(
            r'#ifdef USE_LUA\s+#include "ui/lua/runtime.h"\s+#endif',
            orchestration_text,
            re.MULTILINE,
        )
        is not None,
        "app/orchestration.h: runtime include must stay under USE_LUA",
    )
    require(
        re.search(
            r"#ifdef USE_LUA.*extern String lua_type_script;.*extern volatile bool lua_finished;.*#endif",
            globals_text,
            re.DOTALL,
        )
        is not None,
        "state/globals.h: Lua globals must stay under USE_LUA",
    )
    require(
        re.search(
            r"#ifdef USE_LUA.*String lua_type_script;.*volatile bool lua_finished = false;.*#endif",
            samovar_text,
            re.DOTALL,
        )
        is not None,
        "Samovar.ino: Lua runtime globals must stay under USE_LUA",
    )
    print("    ✓ USE_LUA guards isolate runtime include and globals from non-Lua builds")


def build_harness() -> str:
    mode_enum = state_inventory.parse_enum("SAMOVAR_MODE")

    get_lua_mode_name = extract_function(
        read_text(RUNTIME_HEADER),
        "String get_lua_mode_name(bool filename)",
    )
    mode_lua_owner = extract_function(
        read_text(MODE_OWNERSHIP_HEADER),
        "SAMOVAR_MODE mode_lua_owner(SAMOVAR_MODE mode)",
    )
    set_num_variable = extract_function(
        read_text(VARIABLES_HEADER),
        "static int lua_wrapper_set_num_variable(lua_State *lua_state)",
    )
    get_num_variable = extract_function(
        read_text(VARIABLES_HEADER),
        "static int lua_wrapper_get_num_variable(lua_State *lua_state)",
    )

    cases = textwrap.indent(
        "\n".join(
            f'  verify_mode("{name}", {name}, "{family}", "{filename}");'
            for name, family, filename in [
                ("SAMOVAR_RECTIFICATION_MODE", "rect", "/rectificat.lua"),
                ("SAMOVAR_DISTILLATION_MODE", "dist", "/dist.lua"),
                ("SAMOVAR_BEER_MODE", "beer", "/beer.lua"),
                ("SAMOVAR_BK_MODE", "bk", "/bk.lua"),
                ("SAMOVAR_NBK_MODE", "nbk", "/nbk.lua"),
                ("SAMOVAR_SUVID_MODE", "rect", "/rectificat.lua"),
                ("SAMOVAR_LUA_MODE", "rect", "/rectificat.lua"),
            ]
        ),
        "  ",
    )

    return textwrap.dedent(
        f"""
        #include <cstdint>
        #include <ctime>
        #include <cstdio>
        #include <cstring>
        #include <iostream>
        #include <sstream>
        #include <string>
        #include <vector>

        #define USE_LUA
        #define LUA_BEER ""
        #define LUA_DIST ""
        #define LUA_BK ""
        #define LUA_NBK ""
        #define LUA_RECT ""

        using byte = unsigned char;
        using lua_Number = double;

        #include "{MODE_CODES_HEADER.as_posix()}"

        class String {{
         public:
          String() = default;
          String(const char* text) : value_(text == nullptr ? "" : text) {{}}
          String(const std::string& text) : value_(text) {{}}
          String(int number) : value_(std::to_string(number)) {{}}
          String(float number) : value_(format_number(number)) {{}}
          String(double number) : value_(format_number(number)) {{}}
          String(bool value) : value_(value ? "1" : "0") {{}}
          String(const String&) = default;
          String& operator=(const String&) = default;

          String& operator=(const char* text) {{
            value_ = text == nullptr ? "" : text;
            return *this;
          }}

          std::size_t length() const {{
            return value_.length();
          }}

          const char* c_str() const {{
            return value_.c_str();
          }}

          friend bool operator==(const String& left, const char* right) {{
            return left.value_ == (right == nullptr ? "" : right);
          }}

          friend bool operator!=(const String& left, const char* right) {{
            return !(left == right);
          }}

          friend String operator+(const String& left, const String& right) {{
            return String(left.value_ + right.value_);
          }}

          friend String operator+(const String& left, const char* right) {{
            return String(left.value_ + (right == nullptr ? "" : right));
          }}

          friend String operator+(const char* left, const String& right) {{
            return String(std::string(left == nullptr ? "" : left) + right.value_);
          }}

          std::string str() const {{
            return value_;
          }}

         private:
          static std::string format_number(double value) {{
            std::ostringstream stream;
            stream << value;
            return stream.str();
          }}

          std::string value_;
        }};

        struct LuaValue {{
          enum Type {{
            kNumber,
            kString,
            kFunctionTostring,
          }} type = kNumber;
          double number = 0;
          std::string string;
        }};

        struct lua_State {{
          std::vector<LuaValue> stack;
        }};

        static constexpr int portTICK_PERIOD_MS = 1;

        struct ProgramLine {{
          float Volume = 0;
          float Speed = 0;
          float Temp = 0;
          float Power = 0;
          float Time = 0;
          int capacity_num = 0;
        }};

        struct SensorState {{
          float avgTemp = 0;
        }};

        struct SamSetupStruct {{
          int Mode = 0;
          int TimeZone = 0;
        }};

        static byte WFpulseCount = 0;
        static bool pump_started = false;
        static bool valve_status = false;
        static SamSetupStruct SamSetup;
        static volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
        static volatile SAMOVAR_MODE Samovar_CR_Mode = SAMOVAR_RECTIFICATION_MODE;
        static uint16_t acceleration_temp = 0;
        static SensorState SteamSensor;
        static float boil_temp = 0;
        static SensorState PipeSensor;
        static SensorState WaterSensor;
        static SensorState TankSensor;
        static SensorState ACPSensor;
        static bool loop_lua_fl = false;
        static bool SetScriptOff = false;
        static bool show_lua_script = false;
        static float test_num_val = 0;
        static float WFtotalMilliLitres = 0;
        static float WFflowRate = 0;
        static ProgramLine program[1];
        static int ProgramNum = 0;
        static int capacity_num = 0;
        static float target_power_volt = 0;
        static bool PowerOn = false;
        static float alcohol_s = 0;
        static uint16_t water_pump_speed = 0;
        static float pressure_value = 0;
        static bool PauseOn = false;
        static bool program_Wait = false;
        static std::vector<std::string> console_log;

        static void vTaskDelay(int) {{}}

        static void WriteConsoleLog(const String& value) {{
          console_log.push_back(value.str());
        }}

        static float get_alcohol(float) {{
          return 0;
        }}

        static int year(long) {{
          return 2026;
        }}

        static int month(long) {{
          return 3;
        }}

        static int day(long) {{
          return 16;
        }}

        static int hour(long) {{
          return 12;
        }}

        static int minute(long) {{
          return 34;
        }}

        static int second(long) {{
          return 56;
        }}

        static int resolve_index(lua_State* lua_state, int index) {{
          int resolved = index > 0 ? index - 1 : static_cast<int>(lua_state->stack.size()) + index;
          if (resolved < 0 || resolved >= static_cast<int>(lua_state->stack.size())) {{
            std::cerr << "lua index out of range: " << index << std::endl;
            std::exit(1);
          }}
          return resolved;
        }}

        static double luaL_checknumber(lua_State* lua_state, int index) {{
          return lua_state->stack[resolve_index(lua_state, index)].number;
        }}

        static void lua_getglobal(lua_State* lua_state, const char* name) {{
          LuaValue value;
          if (std::strcmp(name, "tostring") == 0) {{
            value.type = LuaValue::kFunctionTostring;
          }} else {{
            value.type = LuaValue::kString;
            value.string = name == nullptr ? "" : name;
          }}
          lua_state->stack.push_back(value);
        }}

        static void lua_pushvalue(lua_State* lua_state, int index) {{
          lua_state->stack.push_back(lua_state->stack[resolve_index(lua_state, index)]);
        }}

        static std::string to_string_value(const LuaValue& value) {{
          if (value.type == LuaValue::kString) {{
            return value.string;
          }}
          std::ostringstream stream;
          stream << value.number;
          return stream.str();
        }}

        static void lua_call(lua_State* lua_state, int nargs, int) {{
          int function_index = static_cast<int>(lua_state->stack.size()) - nargs - 1;
          if (function_index < 0) {{
            std::cerr << "lua_call stack underflow" << std::endl;
            std::exit(1);
          }}
          LuaValue function = lua_state->stack[function_index];
          std::vector<LuaValue> args(
              lua_state->stack.begin() + function_index + 1,
              lua_state->stack.end());
          lua_state->stack.erase(lua_state->stack.begin() + function_index, lua_state->stack.end());

          LuaValue result;
          if (function.type == LuaValue::kFunctionTostring) {{
            result.type = LuaValue::kString;
            result.string = args.empty() ? "" : to_string_value(args.front());
          }} else {{
            std::cerr << "unsupported lua function call" << std::endl;
            std::exit(1);
          }}
          lua_state->stack.push_back(result);
        }}

        static const char* lua_tolstring(lua_State* lua_state, int index, size_t* length) {{
          LuaValue& value = lua_state->stack[resolve_index(lua_state, index)];
          if (value.type != LuaValue::kString) {{
            value.string = to_string_value(value);
            value.type = LuaValue::kString;
          }}
          if (length) {{
            *length = value.string.size();
          }}
          return value.string.c_str();
        }}

        static void lua_pop(lua_State* lua_state, int count) {{
          while (count-- > 0 && !lua_state->stack.empty()) {{
            lua_state->stack.pop_back();
          }}
        }}

        static void lua_pushnumber(lua_State* lua_state, lua_Number value) {{
          LuaValue result;
          result.type = LuaValue::kNumber;
          result.number = value;
          lua_state->stack.push_back(result);
        }}

        {mode_lua_owner}

        {get_lua_mode_name}

        {set_num_variable}

        {get_num_variable}

        static double call_get_num(const char* name) {{
          lua_State state;
          LuaValue value;
          value.type = LuaValue::kString;
          value.string = name;
          state.stack.push_back(value);
          int result = lua_wrapper_get_num_variable(&state);
          if (result != 1 || state.stack.empty()) {{
            std::cerr << "lua_wrapper_get_num_variable failed for " << name << std::endl;
            std::exit(1);
          }}
          return state.stack.back().number;
        }}

        static void call_set_num(const char* name, double value) {{
          lua_State state;
          LuaValue variable_name;
          variable_name.type = LuaValue::kString;
          variable_name.string = name;
          state.stack.push_back(variable_name);

          LuaValue number;
          number.type = LuaValue::kNumber;
          number.number = value;
          state.stack.push_back(number);

          int result = lua_wrapper_set_num_variable(&state);
          if (result != 0) {{
            std::cerr << "lua_wrapper_set_num_variable returned unexpected result for " << name << std::endl;
            std::exit(1);
          }}
        }}

        static void require_bool(bool condition, const std::string& message) {{
          if (!condition) {{
            std::cerr << message << std::endl;
            std::exit(1);
          }}
        }}

        static void verify_mode(const char* mode_name, SAMOVAR_MODE mode, const char* expected_family, const char* expected_filename) {{
          call_set_num("SamSetup_Mode", static_cast<int>(mode));
          call_set_num("Samovar_Mode", static_cast<int>(mode));
          call_set_num("Samovar_CR_Mode", static_cast<int>(mode));

          require_bool(
              static_cast<int>(call_get_num("SamSetup_Mode")) == static_cast<int>(mode),
              std::string("SamSetup_Mode roundtrip failed for ") + mode_name
          );
          require_bool(
              static_cast<int>(call_get_num("Samovar_Mode")) == static_cast<int>(mode),
              std::string("Samovar_Mode roundtrip failed for ") + mode_name
          );
          require_bool(
              static_cast<int>(call_get_num("Samovar_CR_Mode")) == static_cast<int>(mode),
              std::string("Samovar_CR_Mode roundtrip failed for ") + mode_name
          );

          String family = get_lua_mode_name(false);
          String filename = get_lua_mode_name(true);
          require_bool(family == expected_family, std::string("family mismatch for ") + mode_name);
          require_bool(filename == expected_filename, std::string("filename mismatch for ") + mode_name);

          std::cout
              << mode_name
              << "|ok|numeric=" << static_cast<int>(mode)
              << "|family=" << family.c_str()
              << "|filename=" << filename.c_str()
              << "|samovar_mode=" << static_cast<int>(call_get_num("Samovar_Mode"))
              << "|samovar_cr_mode=" << static_cast<int>(call_get_num("Samovar_CR_Mode"))
              << "|setup_mode=" << static_cast<int>(call_get_num("SamSetup_Mode"))
              << std::endl;
        }}

        int main() {{
          require_bool(SAMOVAR_RECTIFICATION_MODE == {mode_enum["SAMOVAR_RECTIFICATION_MODE"]}, "rect mode baseline changed");
          require_bool(SAMOVAR_DISTILLATION_MODE == {mode_enum["SAMOVAR_DISTILLATION_MODE"]}, "dist mode baseline changed");
          require_bool(SAMOVAR_BEER_MODE == {mode_enum["SAMOVAR_BEER_MODE"]}, "beer mode baseline changed");
          require_bool(SAMOVAR_BK_MODE == {mode_enum["SAMOVAR_BK_MODE"]}, "bk mode baseline changed");
          require_bool(SAMOVAR_NBK_MODE == {mode_enum["SAMOVAR_NBK_MODE"]}, "nbk mode baseline changed");
          require_bool(SAMOVAR_SUVID_MODE == {mode_enum["SAMOVAR_SUVID_MODE"]}, "suvid mode baseline changed");
          require_bool(SAMOVAR_LUA_MODE == {mode_enum["SAMOVAR_LUA_MODE"]}, "lua mode baseline changed");

          std::cout << "Lua runtime mode-selection matrix" << std::endl;
        {cases}
          std::cout << "lua_mode_selection|ok" << std::endl;
          return 0;
        }}
        """
    )


def run_harness() -> None:
    compiler = shutil.which("g++") or shutil.which("c++")
    require(compiler is not None, "C++ compiler is required for Lua mode-selection harness")

    harness = build_harness()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        harness_path = tmp_path / "lua_mode_selection_harness.cpp"
        binary_path = tmp_path / "lua_mode_selection_harness"
        harness_path.write_text(harness, encoding="utf-8")

        compile_result = subprocess.run(
            [compiler, "-std=c++17", str(harness_path), "-o", str(binary_path)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        require(
            compile_result.returncode == 0,
            compile_result.stderr or compile_result.stdout,
        )

        run_result = subprocess.run(
            [str(binary_path)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        require(
            run_result.returncode == 0,
            run_result.stderr or run_result.stdout,
        )
        print(run_result.stdout.rstrip())
        require(
            "lua_mode_selection|ok" in run_result.stdout,
            "Harness summary missing `lua_mode_selection|ok`",
        )


def run_existing_lua_tests() -> None:
    print("\n[2] Running existing Lua unit suites...")
    output = run_command(
        [
            "python3",
            "-m",
            "unittest",
            "tests.test_ui_lua_runtime",
            "tests.test_ui_lua_bindings_variables",
            "tests.test_ui_lua_bindings_process",
        ]
    )
    print(output.rstrip())
    require("OK" in output, "Lua unittest suite did not finish successfully")
    print("    ✓ existing Lua runtime/bindings suites passed")


def main() -> int:
    check_static_contracts()
    run_existing_lua_tests()
    print("\n[3] Running extracted C++ harness...")
    run_harness()
    print("\nLua mode selection: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
