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


ROUTES_SETUP_HEADER = ROOT / "ui" / "web" / "routes_setup.h"
PAGE_ASSETS_HEADER = ROOT / "ui" / "web" / "page_assets.h"
SENSOR_SCAN_HEADER = ROOT / "io" / "sensor_scan.h"
MENU_ACTIONS_HEADER = ROOT / "ui" / "menu" / "actions.h"
DEFAULT_PROGRAMS_HEADER = ROOT / "app" / "default_programs.h"
LUA_RUNTIME_HEADER = ROOT / "ui" / "lua" / "runtime.h"
NVS_PROFILES_HEADER = ROOT / "storage" / "nvs_profiles.h"


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
                return text[match.start():index + 1]

    raise AssertionError(f"Function body end not found: {signature}")


def assert_contains(body: str, fragment: str, label: str) -> None:
    require(fragment in body, f"{label}: missing fragment `{fragment}`")


def assert_ordered(body: str, fragments: list[str], label: str) -> None:
    position = 0
    for fragment in fragments:
        index = body.find(fragment, position)
        require(index != -1, f"{label}: missing or out-of-order fragment `{fragment}`")
        position = index + len(fragment)


def check_static_contracts() -> None:
    print("=" * 72)
    print("Mode switching behavior harness")
    print("=" * 72)

    handle_save_process = extract_function(
        read_text(ROUTES_SETUP_HEADER),
        "void handleSaveProcessSettings(AsyncWebServerRequest *request)",
    )
    change_mode = extract_function(read_text(PAGE_ASSETS_HEADER), "void change_samovar_mode()")
    load_default_program = extract_function(
        read_text(DEFAULT_PROGRAMS_HEADER),
        "void load_default_program_for_mode()",
    )
    get_lua_mode_name = extract_function(
        read_text(LUA_RUNTIME_HEADER),
        "String get_lua_mode_name(bool filename)",
    )

    print("\n[1] Verifying static mode-switch contract...")
    assert_ordered(
        handle_save_process,
        [
            "samovar_reset();",
            "SamSetup.Mode = nextMode;",
            "Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;",
            "Samovar_CR_Mode = Samovar_Mode;",
            "load_default_program_for_mode();",
            "save_profile_nvs();",
            "load_profile_nvs();",
            "lua_type_script = get_lua_mode_name(true);",
            "load_lua_script();",
            "change_samovar_mode();",
        ],
        "handleSaveProcessSettings",
    )
    assert_contains(
        handle_save_process,
        "if (SamSetup.Mode == nextMode) {",
        "handleSaveProcessSettings",
    )
    print("    ✓ handleSaveProcessSettings resets runtime, reloads defaults and rebinds routes")

    assert_contains(
        load_default_program,
        "if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE)",
        "load_default_program_for_mode",
    )
    for fragment in [
        'set_beer_program("',
        "Samovar_Mode == SAMOVAR_DISTILLATION_MODE",
        'set_dist_program("',
        "Samovar_Mode == SAMOVAR_NBK_MODE",
        "set_nbk_program(NBK_DEFAULT_PROGRAM);",
        'set_program("',
    ]:
        assert_contains(load_default_program, fragment, "load_default_program_for_mode")
    print("    ✓ load_default_program_for_mode selects beer/suvid, dist, nbk and rect families")

    for fragment in [
        "if (Samovar_Mode == SAMOVAR_BEER_MODE)",
        '"/beer.htm"',
        "Samovar_Mode == SAMOVAR_DISTILLATION_MODE",
        '"/distiller.htm"',
        "Samovar_Mode == SAMOVAR_BK_MODE",
        '"/bk.htm"',
        "Samovar_Mode == SAMOVAR_NBK_MODE",
        '"/nbk.htm"',
        "Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;",
    ]:
        assert_contains(change_mode, fragment, "change_samovar_mode")
    print("    ✓ change_samovar_mode exposes dedicated pages and rect fallback runtime")

    for fragment in [
        "Samovar_CR_Mode == SAMOVAR_BEER_MODE",
        '"/beer"',
        "Samovar_CR_Mode == SAMOVAR_DISTILLATION_MODE",
        '"/dist"',
        "Samovar_CR_Mode == SAMOVAR_BK_MODE",
        '"/bk"',
        "Samovar_CR_Mode == SAMOVAR_NBK_MODE",
        '"/nbk"',
        '"/rectificat"',
    ]:
        assert_contains(get_lua_mode_name, fragment, "get_lua_mode_name")
    print("    ✓ get_lua_mode_name keeps beer/dist/bk/nbk branches and rect fallback")


def build_harness() -> str:
    mode_enum = state_inventory.parse_enum("SAMOVAR_MODE")
    command_enum = state_inventory.parse_enum("SamovarCommands")
    startval_codes = state_inventory.parse_startval_codes()
    status_codes = state_inventory.parse_status_codes()

    reset_sensor_counter = extract_function(
        read_text(SENSOR_SCAN_HEADER),
        "void reset_sensor_counter(void)",
    )
    samovar_reset = extract_function(read_text(MENU_ACTIONS_HEADER), "void samovar_reset()")
    change_mode = extract_function(read_text(PAGE_ASSETS_HEADER), "void change_samovar_mode()")
    handle_save_process = extract_function(
        read_text(ROUTES_SETUP_HEADER),
        "void handleSaveProcessSettings(AsyncWebServerRequest *request)",
    )
    load_default_program = extract_function(
        read_text(DEFAULT_PROGRAMS_HEADER),
        "void load_default_program_for_mode()",
    )
    get_lua_mode_name = extract_function(
        read_text(LUA_RUNTIME_HEADER),
        "String get_lua_mode_name(bool filename)",
    )
    profile_namespace_by_mode = extract_function(
        read_text(NVS_PROFILES_HEADER),
        "const char* profile_namespace_by_mode(int mode)",
    )

    return textwrap.dedent(
        f"""
        #include <cstdint>
        #include <cstring>
        #include <deque>
        #include <iostream>
        #include <map>
        #include <string>
        #include <vector>

        #define SAMOVAR_USE_POWER
        #define USE_LUA
        #define LUA_BEER ""
        #define LUA_DIST ""
        #define LUA_BK ""
        #define LUA_NBK ""
        #define LUA_RECT ""
        #define NBK_DEFAULT_PROGRAM "NBK_DEFAULT_PROGRAM"

        using uint8_t = std::uint8_t;
        using SemaphoreHandle_t = int;

        static constexpr int portTICK_PERIOD_MS = 1;

        class String {{
         public:
          String() = default;
          String(const char* text) : value_(text == nullptr ? "" : text) {{}}
          String(const std::string& text) : value_(text) {{}}
          String(int number) : value_(std::to_string(number)) {{}}
          String(const String&) = default;
          String& operator=(const String&) = default;

          String& operator=(const char* text) {{
            value_ = text == nullptr ? "" : text;
            return *this;
          }}

          int toInt() const {{
            return value_.empty() ? 0 : std::stoi(value_);
          }}

          const char* c_str() const {{
            return value_.c_str();
          }}

          bool operator==(const char* other) const {{
            return value_ == (other == nullptr ? "" : other);
          }}

          bool operator!=(const char* other) const {{
            return !(*this == other);
          }}

          friend String operator+(const String& left, const String& right) {{
            return String(left.value_ + right.value_);
          }}

          friend String operator+(const String& left, const char* right) {{
            return String(left.value_ + (right == nullptr ? "" : right));
          }}

          friend String operator+(const char* left, const String& right) {{
            return String((left == nullptr ? "" : left) + right.value_);
          }}

         private:
          std::string value_;
        }};

        using SAMOVAR_MODE = int;

        static constexpr int SAMOVAR_RECTIFICATION_MODE = {mode_enum["SAMOVAR_RECTIFICATION_MODE"]};
        static constexpr int SAMOVAR_DISTILLATION_MODE = {mode_enum["SAMOVAR_DISTILLATION_MODE"]};
        static constexpr int SAMOVAR_BEER_MODE = {mode_enum["SAMOVAR_BEER_MODE"]};
        static constexpr int SAMOVAR_BK_MODE = {mode_enum["SAMOVAR_BK_MODE"]};
        static constexpr int SAMOVAR_NBK_MODE = {mode_enum["SAMOVAR_NBK_MODE"]};
        static constexpr int SAMOVAR_SUVID_MODE = {mode_enum["SAMOVAR_SUVID_MODE"]};
        static constexpr int SAMOVAR_LUA_MODE = {mode_enum["SAMOVAR_LUA_MODE"]};

        static constexpr int SAMOVAR_STATUS_OFF = {status_codes["SAMOVAR_STATUS_OFF"]};
        static constexpr int SAMOVAR_STATUS_RECTIFICATION_WARMUP = {status_codes["SAMOVAR_STATUS_RECTIFICATION_WARMUP"]};
        static constexpr int SAMOVAR_STATUS_DISTILLATION = {status_codes["SAMOVAR_STATUS_DISTILLATION"]};
        static constexpr int SAMOVAR_STATUS_BEER = {status_codes["SAMOVAR_STATUS_BEER"]};
        static constexpr int SAMOVAR_STATUS_BK = {status_codes["SAMOVAR_STATUS_BK"]};
        static constexpr int SAMOVAR_STATUS_NBK = {status_codes["SAMOVAR_STATUS_NBK"]};

        static constexpr int SAMOVAR_STARTVAL_RECT_IDLE = {startval_codes["SAMOVAR_STARTVAL_RECT_IDLE"]};
        static constexpr int SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING = {startval_codes["SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING"]};
        static constexpr int SAMOVAR_STARTVAL_BEER_ENTRY = {startval_codes["SAMOVAR_STARTVAL_BEER_ENTRY"]};
        static constexpr int SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING = {startval_codes["SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING"]};

        static constexpr int SAMOVAR_NONE = {command_enum["SAMOVAR_NONE"]};
        static constexpr int SAMOVAR_START = {command_enum["SAMOVAR_START"]};

        static constexpr int PWM_LOW_VALUE = 1;

        struct MockRequest {{
          std::map<std::string, std::string> args;

          bool hasArg(const char* name) const {{
            return args.find(name == nullptr ? "" : name) != args.end();
          }}

          String arg(const char* name) const {{
            auto it = args.find(name == nullptr ? "" : name);
            return it == args.end() ? String("") : String(it->second);
          }}
        }};

        using AsyncWebServerRequest = MockRequest;

        struct MockHandler {{
          std::string uri;
          std::string target;
          std::string cache;
          int template_processor_calls = 0;

          template <typename T>
          MockHandler& setTemplateProcessor(T) {{
            template_processor_calls++;
            return *this;
          }}

          MockHandler& setCacheControl(const char* value) {{
            cache = value == nullptr ? "" : value;
            return *this;
          }}
        }};

        using AsyncStaticWebHandler = MockHandler;

        struct MockServer {{
          std::deque<MockHandler> handlers;
          int serve_calls = 0;
          int remove_calls = 0;

          MockHandler& serveStatic(const char* uri, int, const char* target) {{
            serve_calls++;
            handlers.push_back({{uri == nullptr ? "" : uri, target == nullptr ? "" : target, "", 0}});
            return handlers.back();
          }}

          void removeHandler(MockHandler*) {{
            remove_calls++;
          }}

          void reset() {{
            handlers.clear();
            serve_calls = 0;
            remove_calls = 0;
          }}
        }};

        struct MockStepper {{
          int max_speed = -1;
          int current = -1;
          int target = -1;
          int brake_calls = 0;
          int disable_calls = 0;

          void setMaxSpeed(int value) {{
            max_speed = value;
          }}

          void brake() {{
            brake_calls++;
          }}

          void disable() {{
            disable_calls++;
          }}

          void setCurrent(int value) {{
            current = value;
          }}

          void setTarget(int value) {{
            target = value;
          }}
        }};

        struct MockFile {{
          bool open = false;
          int close_calls = 0;

          explicit operator bool() const {{
            return open;
          }}

          void close() {{
            open = false;
            close_calls++;
          }}
        }};

        struct SensorState {{
          float BodyTemp = 1.0f;
          float PrevTemp = 2.0f;
          float Start_Pressure = 3.0f;
        }};

        struct SamSetupStruct {{
          int Mode = SAMOVAR_RECTIFICATION_MODE;
        }};

        enum FinishKind {{
          FINISH_GENERIC = 0,
          FINISH_DIST = 1,
          FINISH_BEER = 2,
          FINISH_BK = 3,
          FINISH_NBK = 4
        }};

        struct ModeSourceCase {{
          const char* name;
          int saved_mode;
          int runtime_mode;
          int status;
          const char* route_target;
          FinishKind finish_kind;
        }};

        struct ModeTargetCase {{
          const char* name;
          int requested_mode;
          int expected_runtime_mode;
          const char* expected_route_target;
          const char* expected_program_family;
          const char* expected_lua_file;
          const char* expected_profile_namespace;
        }};

        MockServer server;
        MockHandler* indexHandler = nullptr;
        int SPIFFS = 0;

        String indexKeyProcessor(const String& key) {{
          return key;
        }}

        SamSetupStruct SamSetup;
        volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
        volatile SAMOVAR_MODE Samovar_CR_Mode = SAMOVAR_RECTIFICATION_MODE;

        bool PowerOn = false;
        bool PauseOn = false;
        bool wetting_autostart = false;
        bool program_Wait = false;
        bool boil_started = false;
        bool is_self_test = false;
        bool I2CPumpCalibrating = false;
        bool loop_lua_fl = false;
        bool SetScriptOff = false;

        int sam_command_sync = SAMOVAR_NONE;
        int SamovarStatusInt = SAMOVAR_STATUS_OFF;
        int startval = SAMOVAR_STARTVAL_RECT_IDLE;
        int ProgramNum = 0;
        int WthdrwlProgress = 0;
        int TargetStepps = 0;
        int I2CPumpTargetSteps = 0;
        float I2CPumpTargetMl = 0.0f;
        int I2CPumpCmdSpeed = 0;
        int t_min = 0;
        int alarm_h_min = 0;
        int alarm_t_min = 0;
        int alarm_c_min = 0;
        int alarm_c_low_min = 0;
        int d_s_time_min = 0;
        int b_t_time_min = 0;
        int b_t_time_delay = 0;
        int bk_pwm = 0;
        int power_err_cnt = 0;

        float b_t_temp_prev = 0.0f;
        float prev_target_power_volt = 0.0f;
        float d_s_temp_finish = 0.0f;
        float current_power_volt = 0.0f;
        float target_power_volt = 0.0f;
        float pressure_value = 0.0f;
        float old_pressure_value = 0.0f;
        float ActualVolumePerHour = 0.0f;
        float d_s_temp_prev = 0.0f;
        float bme_pressure = 760.0f;
        float start_pressure = 0.0f;
        float boil_temp = 0.0f;
        float alcohol_s = 0.0f;

        unsigned long begintime = 0;

        SensorState SteamSensor;
        SensorState PipeSensor;
        SensorState WaterSensor;
        SensorState TankSensor;
        SensorState ACPSensor;

        MockStepper stepper;
        MockFile fileToAppend;

        SemaphoreHandle_t xSemaphore = 1;

        String Lua_status = "";
        String lua_type_script = "";

        char startval_text_val[20] = "stale";
        char* power_text_ptr = nullptr;
        static const char menu_text_stopped_padded[] = "Stoped             ";
        static const char menu_text_power_on[] = "ON";

        int stop_service_calls = 0;
        int set_capacity_calls = 0;
        int set_power_calls = 0;
        int set_power_false_calls = 0;
        int get_status_calls = 0;
        int bme_getvalue_calls = 0;
        int semaphore_give_calls = 0;
        int reset_focus_calls = 0;
        int last_menu_screen = -1;
        int distiller_finish_calls = 0;
        int beer_finish_calls = 0;
        int bk_finish_calls = 0;
        int nbk_finish_calls = 0;
        int load_lua_script_calls = 0;
        int delay_calls = 0;
        int set_program_calls = 0;
        int set_beer_program_calls = 0;
        int set_dist_program_calls = 0;
        int set_nbk_program_calls = 0;
        int save_profile_calls = 0;
        int load_profile_calls = 0;
        int last_saved_mode_meta = SAMOVAR_RECTIFICATION_MODE;

        std::string last_program_family = "stale";
        std::string last_program_payload = "stale";
        std::string last_save_namespace = "stale";
        std::string last_load_namespace = "stale";

        void stopService() {{
          stop_service_calls++;
        }}

        void set_capacity(int) {{
          set_capacity_calls++;
        }}

        void set_power(bool on) {{
          set_power_calls++;
          PowerOn = on;
          if (!on) {{
            set_power_false_calls++;
          }}
        }}

        void get_Samovar_Status() {{
          get_status_calls++;
        }}

        void BME_getvalue(bool) {{
          bme_getvalue_calls++;
          bme_pressure = 761.0f;
        }}

        void xSemaphoreGive(SemaphoreHandle_t) {{
          semaphore_give_calls++;
        }}

        void reset_focus() {{
          reset_focus_calls++;
        }}

        void set_menu_screen(uint8_t screen) {{
          last_menu_screen = screen;
        }}

        void distiller_finish() {{
          distiller_finish_calls++;
        }}

        void beer_finish() {{
          beer_finish_calls++;
        }}

        void bk_finish() {{
          bk_finish_calls++;
        }}

        void nbk_finish() {{
          nbk_finish_calls++;
        }}

        void set_program(String value) {{
          set_program_calls++;
          last_program_family = "rect";
          last_program_payload = value.c_str();
        }}

        void set_beer_program(String value) {{
          set_beer_program_calls++;
          last_program_family = "beer";
          last_program_payload = value.c_str();
        }}

        void set_dist_program(String value) {{
          set_dist_program_calls++;
          last_program_family = "dist";
          last_program_payload = value.c_str();
        }}

        void set_nbk_program(const char* value) {{
          set_nbk_program_calls++;
          last_program_family = "nbk";
          last_program_payload = value == nullptr ? "" : value;
        }}

        {profile_namespace_by_mode}

        void save_profile_nvs() {{
          save_profile_calls++;
          last_saved_mode_meta = SamSetup.Mode;
          last_save_namespace = profile_namespace_by_mode(SamSetup.Mode);
        }}

        void load_profile_nvs() {{
          load_profile_calls++;
          Samovar_CR_Mode = (SAMOVAR_MODE)last_saved_mode_meta;
          SamSetup.Mode = last_saved_mode_meta;
          last_load_namespace = profile_namespace_by_mode(last_saved_mode_meta);
        }}

        {get_lua_mode_name}

        void load_lua_script() {{
          load_lua_script_calls++;
        }}

        void delay(int) {{
          delay_calls++;
        }}

        {load_default_program}

        {reset_sensor_counter}

        {samovar_reset}

        {change_mode}

        {handle_save_process}

        void reset_counters() {{
          stop_service_calls = 0;
          set_capacity_calls = 0;
          set_power_calls = 0;
          set_power_false_calls = 0;
          get_status_calls = 0;
          bme_getvalue_calls = 0;
          semaphore_give_calls = 0;
          reset_focus_calls = 0;
          last_menu_screen = -1;
          distiller_finish_calls = 0;
          beer_finish_calls = 0;
          bk_finish_calls = 0;
          nbk_finish_calls = 0;
          load_lua_script_calls = 0;
          delay_calls = 0;
          set_program_calls = 0;
          set_beer_program_calls = 0;
          set_dist_program_calls = 0;
          set_nbk_program_calls = 0;
          save_profile_calls = 0;
          load_profile_calls = 0;
        }}

        void bootstrap_handler(const char* target) {{
          server.reset();
          MockHandler& handler = server.serveStatic("/index.htm", SPIFFS, target);
          handler.setTemplateProcessor(indexKeyProcessor).setCacheControl("no-cache, no-store, must-revalidate");
          indexHandler = &handler;
        }}

        void seed_stale_runtime(const ModeSourceCase& source) {{
          reset_counters();
          bootstrap_handler(source.route_target);

          SamSetup.Mode = source.saved_mode;
          Samovar_Mode = source.runtime_mode;
          Samovar_CR_Mode = source.runtime_mode;
          last_saved_mode_meta = source.saved_mode;

          PowerOn = true;
          PauseOn = true;
          wetting_autostart = true;
          program_Wait = true;
          boil_started = true;
          is_self_test = true;
          I2CPumpCalibrating = true;
          loop_lua_fl = true;
          SetScriptOff = false;

          sam_command_sync = SAMOVAR_START;
          SamovarStatusInt = source.status;
          startval = SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING;
          ProgramNum = 5;
          WthdrwlProgress = 88;
          TargetStepps = 99;
          I2CPumpTargetSteps = 111;
          I2CPumpTargetMl = 22.5f;
          I2CPumpCmdSpeed = 123;
          t_min = 7;
          alarm_h_min = 1;
          alarm_t_min = 2;
          alarm_c_min = 3;
          alarm_c_low_min = 4;
          d_s_time_min = 5;
          b_t_time_min = 6;
          b_t_time_delay = 7;
          bk_pwm = 77;
          power_err_cnt = 9;

          b_t_temp_prev = 1.5f;
          prev_target_power_volt = 2.5f;
          d_s_temp_finish = 3.5f;
          current_power_volt = 4.5f;
          target_power_volt = 5.5f;
          pressure_value = 6.5f;
          old_pressure_value = 7.5f;
          ActualVolumePerHour = 8.5f;
          d_s_temp_prev = 9.5f;
          bme_pressure = 760.0f;
          start_pressure = 0.0f;
          boil_temp = 10.5f;
          alcohol_s = 11.5f;
          begintime = 12;

          SteamSensor = SensorState();
          PipeSensor = SensorState();
          WaterSensor = SensorState();
          TankSensor = SensorState();
          ACPSensor = SensorState();

          stepper = MockStepper();
          fileToAppend = MockFile{{true, 0}};
          Lua_status = "busy";
          lua_type_script = "stale";
          last_program_family = "stale";
          last_program_payload = "stale";
          last_save_namespace = "stale";
          last_load_namespace = "stale";
          std::strncpy(startval_text_val, "stale", sizeof(startval_text_val));
          power_text_ptr = nullptr;
        }}

        bool assert_common_reset(const char* scenario, const ModeTargetCase& target) {{
          if (SamSetup.Mode != target.requested_mode) {{
            std::cerr << scenario << ": saved mode mismatch" << std::endl;
            return false;
          }}
          if (Samovar_Mode != target.expected_runtime_mode || Samovar_CR_Mode != target.expected_runtime_mode) {{
            std::cerr << scenario << ": runtime mode mismatch" << std::endl;
            return false;
          }}
          if (SamovarStatusInt != SAMOVAR_STATUS_OFF || startval != SAMOVAR_STARTVAL_RECT_IDLE) {{
            std::cerr << scenario << ": status/startval were not reset" << std::endl;
            return false;
          }}
          if (PowerOn || PauseOn || program_Wait || sam_command_sync != SAMOVAR_NONE) {{
            std::cerr << scenario << ": power/flags/command queue leaked across mode switch" << std::endl;
            return false;
          }}
          if (ProgramNum != 0 || WthdrwlProgress != 0 || TargetStepps != 0) {{
            std::cerr << scenario << ": program counters were not reset" << std::endl;
            return false;
          }}
          if (I2CPumpTargetSteps != 0 || I2CPumpTargetMl != 0.0f || I2CPumpCmdSpeed != 0 || I2CPumpCalibrating) {{
            std::cerr << scenario << ": i2c pump state leaked across mode switch" << std::endl;
            return false;
          }}
          if (stepper.max_speed != 0 || stepper.current != 0 || stepper.target != 0 || stepper.brake_calls == 0 || stepper.disable_calls == 0) {{
            std::cerr << scenario << ": stepper reset was incomplete" << std::endl;
            return false;
          }}
          if (Lua_status != "" || !SetScriptOff || loop_lua_fl) {{
            std::cerr << scenario << ": lua reset was incomplete" << std::endl;
            return false;
          }}
          if (std::string(lua_type_script.c_str()) != target.expected_lua_file || load_lua_script_calls != 1) {{
            std::cerr << scenario << ": lua runtime initialization mismatch" << std::endl;
            return false;
          }}
          if (last_program_family != target.expected_program_family) {{
            std::cerr << scenario << ": default program family mismatch" << std::endl;
            return false;
          }}
          if (last_save_namespace != target.expected_profile_namespace || last_load_namespace != target.expected_profile_namespace) {{
            std::cerr << scenario << ": profile namespace mismatch" << std::endl;
            return false;
          }}
          if (indexHandler == nullptr || indexHandler->target != target.expected_route_target) {{
            std::cerr << scenario << ": route rebinding mismatch" << std::endl;
            return false;
          }}
          if (indexHandler->cache != "no-cache, no-store, must-revalidate" || indexHandler->template_processor_calls != 1) {{
            std::cerr << scenario << ": route handler setup mismatch" << std::endl;
            return false;
          }}
          if (server.remove_calls != 1 || server.serve_calls != 2) {{
            std::cerr << scenario << ": handler replacement count mismatch" << std::endl;
            return false;
          }}
          if (stop_service_calls == 0 || set_capacity_calls == 0 || get_status_calls == 0 || fileToAppend.close_calls != 1) {{
            std::cerr << scenario << ": reset pipeline was incomplete" << std::endl;
            return false;
          }}
          if (save_profile_calls != 1 || load_profile_calls != 1) {{
            std::cerr << scenario << ": profile save/load sequence mismatch" << std::endl;
            return false;
          }}
          if (reset_focus_calls == 0 || last_menu_screen != 3) {{
            std::cerr << scenario << ": menu reset side effects missing" << std::endl;
            return false;
          }}
          if (set_program_calls + set_beer_program_calls + set_dist_program_calls + set_nbk_program_calls != 1) {{
            std::cerr << scenario << ": expected exactly one default program initializer" << std::endl;
            return false;
          }}
          return true;
        }}

        bool assert_finish_selection(const char* scenario, FinishKind finish_kind) {{
          int expected_dist = finish_kind == FINISH_DIST ? 1 : 0;
          int expected_beer = finish_kind == FINISH_BEER ? 1 : 0;
          int expected_bk = finish_kind == FINISH_BK ? 1 : 0;
          int expected_nbk = finish_kind == FINISH_NBK ? 1 : 0;
          int expected_power_false = finish_kind == FINISH_GENERIC ? 2 : 1;
          if (distiller_finish_calls != expected_dist || beer_finish_calls != expected_beer ||
              bk_finish_calls != expected_bk || nbk_finish_calls != expected_nbk) {{
            std::cerr << scenario << ": wrong finisher selection" << std::endl;
            return false;
          }}
          if (set_power_false_calls != expected_power_false) {{
            std::cerr << scenario << ": wrong power-off count" << std::endl;
            return false;
          }}
          return true;
        }}

        bool run_switch(const ModeSourceCase& source, const ModeTargetCase& target) {{
          seed_stale_runtime(source);

          MockRequest request;
          request.args["mode"] = std::to_string(target.requested_mode);
          handleSaveProcessSettings(&request);

          std::string scenario = std::string(source.name) + "_to_" + target.name;
          if (!assert_common_reset(scenario.c_str(), target)) {{
            return false;
          }}
          if (!assert_finish_selection(scenario.c_str(), source.finish_kind)) {{
            return false;
          }}

          std::cout << scenario
                    << "|ok|saved=" << SamSetup.Mode
                    << "|runtime=" << Samovar_Mode
                    << "|route=" << indexHandler->target
                    << "|program=" << last_program_family
                    << "|lua=" << lua_type_script.c_str()
                    << "|ns=" << last_load_namespace
                    << std::endl;
          return true;
        }}

        int main() {{
          const ModeSourceCase sources[] = {{
            {{"rect", SAMOVAR_RECTIFICATION_MODE, SAMOVAR_RECTIFICATION_MODE, SAMOVAR_STATUS_RECTIFICATION_WARMUP, "/index.htm", FINISH_GENERIC}},
            {{"dist", SAMOVAR_DISTILLATION_MODE, SAMOVAR_DISTILLATION_MODE, SAMOVAR_STATUS_DISTILLATION, "/distiller.htm", FINISH_DIST}},
            {{"beer", SAMOVAR_BEER_MODE, SAMOVAR_BEER_MODE, SAMOVAR_STATUS_BEER, "/beer.htm", FINISH_BEER}},
            {{"bk", SAMOVAR_BK_MODE, SAMOVAR_BK_MODE, SAMOVAR_STATUS_BK, "/bk.htm", FINISH_BK}},
            {{"nbk", SAMOVAR_NBK_MODE, SAMOVAR_NBK_MODE, SAMOVAR_STATUS_NBK, "/nbk.htm", FINISH_NBK}},
            {{"suvid", SAMOVAR_SUVID_MODE, SAMOVAR_RECTIFICATION_MODE, SAMOVAR_STATUS_RECTIFICATION_WARMUP, "/index.htm", FINISH_GENERIC}},
            {{"lua", SAMOVAR_LUA_MODE, SAMOVAR_RECTIFICATION_MODE, SAMOVAR_STATUS_RECTIFICATION_WARMUP, "/index.htm", FINISH_GENERIC}},
          }};

          const ModeTargetCase targets[] = {{
            {{"rect", SAMOVAR_RECTIFICATION_MODE, SAMOVAR_RECTIFICATION_MODE, "/index.htm", "rect", "/rectificat.lua", "sam_rect"}},
            {{"dist", SAMOVAR_DISTILLATION_MODE, SAMOVAR_DISTILLATION_MODE, "/distiller.htm", "dist", "/dist.lua", "sam_dist"}},
            {{"beer", SAMOVAR_BEER_MODE, SAMOVAR_BEER_MODE, "/beer.htm", "beer", "/beer.lua", "sam_beer"}},
            {{"bk", SAMOVAR_BK_MODE, SAMOVAR_BK_MODE, "/bk.htm", "rect", "/bk.lua", "sam_bk"}},
            {{"nbk", SAMOVAR_NBK_MODE, SAMOVAR_NBK_MODE, "/nbk.htm", "nbk", "/nbk.lua", "sam_nbk"}},
            {{"suvid", SAMOVAR_SUVID_MODE, SAMOVAR_RECTIFICATION_MODE, "/index.htm", "beer", "/rectificat.lua", "sam_suvid"}},
            {{"lua", SAMOVAR_LUA_MODE, SAMOVAR_RECTIFICATION_MODE, "/index.htm", "rect", "/rectificat.lua", "sam_lua"}},
          }};

          for (const auto& source : sources) {{
            for (const auto& target : targets) {{
              if (source.saved_mode == target.requested_mode) {{
                continue;
              }}
              if (!run_switch(source, target)) {{
                return 1;
              }}
            }}
          }}

          std::cout << "mode_switching_behavior|ok" << std::endl;
          return 0;
        }}
        """
    )


def run_harness() -> str:
    compiler = shutil.which("g++") or shutil.which("c++")
    require(compiler is not None, "C++ compiler is required for mode switching harness test")

    print("\n[2] Compiling and running mode-switch matrix harness...")
    harness = build_harness()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        harness_path = tmp_path / "mode_switching_behavior_harness.cpp"
        binary_path = tmp_path / "mode_switching_behavior_harness"
        harness_path.write_text(harness, encoding="utf-8")

        compile_result = subprocess.run(
            [compiler, "-std=c++17", str(harness_path), "-o", str(binary_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        require(
            compile_result.returncode == 0,
            compile_result.stderr or compile_result.stdout or "Harness compilation failed",
        )
        print("    ✓ Harness compiled")

        run_result = subprocess.run(
            [str(binary_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        require(
            run_result.returncode == 0,
            run_result.stderr or run_result.stdout or "Harness execution failed",
        )
        for line in run_result.stdout.strip().splitlines():
            print(f"    {line}")
        return run_result.stdout


def main() -> None:
    check_static_contracts()
    run_harness()
    print("\n" + "=" * 72)
    print("Mode switching behavior: PASS")
    print("=" * 72)


if __name__ == "__main__":
    main()
