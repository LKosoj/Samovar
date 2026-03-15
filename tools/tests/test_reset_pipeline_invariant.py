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
CONFIG_APPLY_HEADER = ROOT / "app" / "config_apply.h"
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


def check_static_pipeline() -> None:
    print("=" * 72)
    print("Reset pipeline invariant test")
    print("=" * 72)

    routes_setup = extract_function(
        read_text(ROUTES_SETUP_HEADER),
        "void handleSaveProcessSettings(AsyncWebServerRequest *request)",
    )
    samovar_reset = extract_function(read_text(MENU_ACTIONS_HEADER), "void samovar_reset()")
    reset_sensor_counter = extract_function(
        read_text(SENSOR_SCAN_HEADER),
        "void reset_sensor_counter(void)",
    )
    change_mode = extract_function(read_text(PAGE_ASSETS_HEADER), "void change_samovar_mode()")
    read_config = extract_function(read_text(CONFIG_APPLY_HEADER), "void read_config()")
    save_profile = extract_function(read_text(NVS_PROFILES_HEADER), "void save_profile_nvs()")
    load_profile = extract_function(read_text(NVS_PROFILES_HEADER), "void load_profile_nvs()")

    print("\n[1] Verifying explicit web mode-switch reset order...")
    for required in [
        "distiller_finish();",
        "beer_finish();",
        "bk_finish();",
        "nbk_finish();",
        "set_power(false);",
        "SetScriptOff = true;",
        "loop_lua_fl = false;",
        "delay(100);",
    ]:
        assert_contains(routes_setup, required, "handleSaveProcessSettings")
    assert_ordered(
        routes_setup,
        [
            "if (PowerOn) {",
            "#ifdef USE_LUA",
            "if (loop_lua_fl) {",
            "SetScriptOff = true;",
            "loop_lua_fl = false;",
            "delay(100);",
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
    print("    ✓ Active mode shutdown, Lua stop gate, reset, profile reload and route rebinding are explicit")

    print("\n[2] Verifying samovar_reset() UI stage...")
    assert_ordered(
        samovar_reset,
        [
            "power_text_ptr = (char *)menu_text_power_on;",
            "reset_focus();",
            "set_menu_screen(3);",
            "reset_sensor_counter();",
            "sam_command_sync = SAMOVAR_NONE;",
        ],
        "samovar_reset",
    )
    print("    ✓ Menu/UI reset delegates runtime cleanup and clears command queue")

    print("\n[3] Verifying reset_sensor_counter() runtime cleanup set...")
    for required in [
        "sam_command_sync = SAMOVAR_NONE;",
        "stopService();",
        "stepper.setMaxSpeed(0);",
        "stepper.brake();",
        "stepper.disable();",
        "stepper.setCurrent(0);",
        "stepper.setTarget(0);",
        "set_capacity(0);",
        "SamovarStatusInt = SAMOVAR_STATUS_OFF;",
        "startval = SAMOVAR_STARTVAL_RECT_IDLE;",
        "PauseOn = false;",
        "program_Wait = false;",
        "TargetStepps = 0;",
        "I2CPumpTargetSteps = 0;",
        "I2CPumpTargetMl = 0;",
        "I2CPumpCmdSpeed = 0;",
        "I2CPumpCalibrating = false;",
        "is_self_test = false;",
        "fileToAppend.close();",
        "set_power(false);",
        "get_Samovar_Status();",
        "power_err_cnt = 0;",
        'Lua_status = "";',
    ]:
        assert_contains(reset_sensor_counter, required, "reset_sensor_counter")
    assert_ordered(
        reset_sensor_counter,
        [
            "sam_command_sync = SAMOVAR_NONE;",
            "stopService();",
            "stepper.setMaxSpeed(0);",
            "set_capacity(0);",
            "SamovarStatusInt = SAMOVAR_STATUS_OFF;",
            "startval = SAMOVAR_STARTVAL_RECT_IDLE;",
            "TargetStepps = 0;",
            "I2CPumpTargetSteps = 0;",
            "I2CPumpTargetMl = 0;",
            "I2CPumpCmdSpeed = 0;",
            "I2CPumpCalibrating = false;",
            "is_self_test = false;",
            "set_power(false);",
            "sam_command_sync = SAMOVAR_NONE;",
            "get_Samovar_Status();",
        ],
        "reset_sensor_counter",
    )
    print("    ✓ Runtime reset covers power, stepper, I2C pump, counters, self-test and Lua status string")

    print("\n[4] Verifying route rebinding and profile sequence...")
    assert_ordered(
        change_mode,
        [
            "if (indexHandler) {",
            "server.removeHandler(indexHandler);",
            "indexHandler = nullptr;",
            'server.serveStatic("/index.htm", SPIFFS, "/',
            "Samovar_CR_Mode = Samovar_Mode;",
        ],
        "change_samovar_mode",
    )
    assert_contains(change_mode, "Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;", "change_samovar_mode")
    assert_ordered(
        save_profile,
        [
            'prefs.putUShort("Mode", SamSetup.Mode);',
            "prefs.end();",
            "write_last_mode_meta((uint8_t)SamSetup.Mode);",
        ],
        "save_profile_nvs",
    )
    assert_ordered(
        load_profile,
        [
            "uint8_t lastMode = read_last_mode_meta();",
            "Samovar_CR_Mode = (SAMOVAR_MODE)lastMode;",
            'SamSetup.Mode = prefs.getUShort("Mode", 0);',
        ],
        "load_profile_nvs",
    )
    assert_ordered(
        read_config,
        [
            "load_profile_nvs();",
            "Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;",
        ],
        "read_config",
    )
    print("    ✓ Profile namespace/mode metadata and route rebinding order are explicit")


def build_harness() -> str:
    mode_enum = state_inventory.parse_enum("SAMOVAR_MODE")
    command_enum = state_inventory.parse_enum("SamovarCommands")
    startval_codes = state_inventory.parse_startval_codes()

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

         private:
          std::string value_;
        }};

        using SAMOVAR_MODE = int;

        static constexpr int SAMOVAR_RECTIFICATION_MODE = {mode_enum["SAMOVAR_RECTIFICATION_MODE"]};
        static constexpr int SAMOVAR_DISTILLATION_MODE = {mode_enum["SAMOVAR_DISTILLATION_MODE"]};
        static constexpr int SAMOVAR_BEER_MODE = {mode_enum["SAMOVAR_BEER_MODE"]};
        static constexpr int SAMOVAR_BK_MODE = {mode_enum["SAMOVAR_BK_MODE"]};
        static constexpr int SAMOVAR_NBK_MODE = {mode_enum["SAMOVAR_NBK_MODE"]};
        static constexpr int SAMOVAR_STARTVAL_RECT_IDLE = {startval_codes["SAMOVAR_STARTVAL_RECT_IDLE"]};
        static constexpr int SAMOVAR_NONE = {command_enum["SAMOVAR_NONE"]};
        static constexpr int SAMOVAR_COMMAND_NONE = {command_enum["SAMOVAR_NONE"]};
        static constexpr int SAMOVAR_COMMAND_RESET = {command_enum["SAMOVAR_RESET"]};
        static constexpr int SAMOVAR_STATUS_OFF = 0;
        static constexpr int SAMOVAR_STATUS_DISTILLATION = 1000;
        static constexpr int SAMOVAR_STATUS_BEER = 2000;
        static constexpr int SAMOVAR_STATUS_BK = 3000;
        static constexpr int SAMOVAR_STATUS_NBK = 4000;
        static constexpr int SAMOVAR_BUSY = 77;
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
          std::vector<std::string> removed_targets;
          int serve_calls = 0;
          int remove_calls = 0;

          MockHandler& serveStatic(const char* uri, int, const char* target) {{
            serve_calls++;
            handlers.push_back({{uri == nullptr ? "" : uri, target == nullptr ? "" : target, "", 0}});
            return handlers.back();
          }}

          void removeHandler(MockHandler* handler) {{
            remove_calls++;
            removed_targets.push_back(handler == nullptr ? "<null>" : handler->target);
          }}

          void reset_all() {{
            handlers.clear();
            removed_targets.clear();
            serve_calls = 0;
            remove_calls = 0;
          }}

          void reset_metrics() {{
            removed_targets.clear();
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
        int SamovarStatusInt = 0;
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
        int last_capacity = -1;
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
        int load_default_program_calls = 0;
        int save_profile_calls = 0;
        int load_profile_calls = 0;
        int get_lua_mode_name_calls = 0;
        int load_lua_script_calls = 0;
        int delay_calls = 0;

        void stopService() {{
          stop_service_calls++;
        }}

        void set_capacity(int cap) {{
          set_capacity_calls++;
          last_capacity = cap;
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

        void load_default_program_for_mode() {{
          load_default_program_calls++;
        }}

        void save_profile_nvs() {{
          save_profile_calls++;
        }}

        void load_profile_nvs() {{
          load_profile_calls++;
        }}

        String get_lua_mode_name(bool filename = true) {{
          (void)filename;
          get_lua_mode_name_calls++;
          switch (Samovar_CR_Mode) {{
            case SAMOVAR_BEER_MODE:
              return "beer";
            case SAMOVAR_DISTILLATION_MODE:
              return "dist";
            case SAMOVAR_BK_MODE:
              return "bk";
            case SAMOVAR_NBK_MODE:
              return "nbk";
            default:
              return "rect";
          }}
        }}

        void load_lua_script() {{
          load_lua_script_calls++;
        }}

        void delay(int) {{
          delay_calls++;
        }}

        {reset_sensor_counter}

        {samovar_reset}

        {change_mode}

        {handle_save_process}

        void reset_metrics() {{
          stop_service_calls = 0;
          set_capacity_calls = 0;
          last_capacity = -1;
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
          load_default_program_calls = 0;
          save_profile_calls = 0;
          load_profile_calls = 0;
          get_lua_mode_name_calls = 0;
          load_lua_script_calls = 0;
          delay_calls = 0;
          server.reset_metrics();
        }}

        void bootstrap_mode(SAMOVAR_MODE mode, const char* route_target) {{
          server.reset_all();
          MockHandler& handler = server.serveStatic("/index.htm", SPIFFS, route_target);
          indexHandler = &handler;
          SamSetup.Mode = mode;
          Samovar_Mode = mode;
          Samovar_CR_Mode = mode;
          reset_metrics();
        }}

        void contaminate_runtime(int status) {{
          PowerOn = true;
          PauseOn = true;
          wetting_autostart = true;
          program_Wait = true;
          boil_started = true;
          is_self_test = true;
          I2CPumpCalibrating = true;
          loop_lua_fl = true;
          SetScriptOff = false;

          sam_command_sync = SAMOVAR_BUSY;
          SamovarStatusInt = status;
          startval = status;
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
          std::strncpy(startval_text_val, "stale", sizeof(startval_text_val));
          power_text_ptr = nullptr;
        }}

        bool assert_common_reset(const char* scenario, int expected_mode, const char* expected_target) {{
          if (SamSetup.Mode != expected_mode || Samovar_Mode != expected_mode || Samovar_CR_Mode != expected_mode) {{
            std::cerr << scenario << ": mode sync mismatch" << std::endl;
            return false;
          }}
          if (SamovarStatusInt != 0 || startval != SAMOVAR_STARTVAL_RECT_IDLE || PauseOn || program_Wait) {{
            std::cerr << scenario << ": status flags were not reset" << std::endl;
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
          if (PowerOn || sam_command_sync != SAMOVAR_NONE) {{
            std::cerr << scenario << ": power or command queue remained active" << std::endl;
            return false;
          }}
          if (stepper.max_speed != 0 || stepper.current != 0 || stepper.target != 0 || stepper.brake_calls == 0 || stepper.disable_calls == 0) {{
            std::cerr << scenario << ": stepper was not fully reset" << std::endl;
            return false;
          }}
          if (Lua_status == "busy" || !SetScriptOff || loop_lua_fl) {{
            std::cerr << scenario << ": lua state was not reset" << std::endl;
            return false;
          }}
          if (indexHandler == nullptr || indexHandler->target != expected_target) {{
            std::cerr << scenario << ": wrong active index handler target" << std::endl;
            return false;
          }}
          if (indexHandler->cache != "no-cache, no-store, must-revalidate" || indexHandler->template_processor_calls != 1) {{
            std::cerr << scenario << ": handler cache or template setup mismatch" << std::endl;
            return false;
          }}
          if (server.remove_calls != 1 || server.serve_calls != 1) {{
            std::cerr << scenario << ": handler replacement count mismatch" << std::endl;
            return false;
          }}
          if (stop_service_calls == 0 || set_capacity_calls == 0 || get_status_calls == 0 || fileToAppend.close_calls != 1) {{
            std::cerr << scenario << ": reset pipeline was incomplete" << std::endl;
            return false;
          }}
          if (load_default_program_calls != 1 || save_profile_calls != 1 || load_profile_calls != 1 || load_lua_script_calls != 1 || get_lua_mode_name_calls != 1) {{
            std::cerr << scenario << ": reload pipeline was incomplete" << std::endl;
            return false;
          }}
          if (reset_focus_calls == 0 || last_menu_screen != 3) {{
            std::cerr << scenario << ": menu reset side effects missing" << std::endl;
            return false;
          }}
          return true;
        }}

        bool run_switch(const char* scenario, int current_status, int next_mode, const char* next_target, int expected_finisher_id) {{
          reset_metrics();
          contaminate_runtime(current_status);

          MockRequest request;
          request.args["mode"] = std::to_string(next_mode);
          handleSaveProcessSettings(&request);

          if (!assert_common_reset(scenario, next_mode, next_target)) {{
            return false;
          }}

          int finisher_calls[4] = {{
            distiller_finish_calls,
            beer_finish_calls,
            bk_finish_calls,
            nbk_finish_calls,
          }};
          for (int index = 0; index < 4; ++index) {{
            const int expected = expected_finisher_id == index ? 1 : 0;
            if (finisher_calls[index] != expected) {{
              std::cerr << scenario << ": finisher selection mismatch" << std::endl;
              return false;
            }}
          }}

          std::cout << scenario << "|ok|target=" << next_target << "|save_load=1/1|route_rebind=1/1" << std::endl;
          return true;
        }}

        int main() {{
          bootstrap_mode(SAMOVAR_DISTILLATION_MODE, "/distiller.htm");
          if (!run_switch("dist_to_beer", 1000, SAMOVAR_BEER_MODE, "/beer.htm", 0)) {{
            return 1;
          }}
          if (!run_switch("beer_to_bk", 2000, SAMOVAR_BK_MODE, "/bk.htm", 1)) {{
            return 1;
          }}
          if (!run_switch("bk_to_nbk", 3000, SAMOVAR_NBK_MODE, "/nbk.htm", 2)) {{
            return 1;
          }}
          if (!run_switch("nbk_to_rect", 4000, SAMOVAR_RECTIFICATION_MODE, "/index.htm", 3)) {{
            return 1;
          }}
          if (!run_switch("rect_to_dist", 50, SAMOVAR_DISTILLATION_MODE, "/distiller.htm", -1)) {{
            return 1;
          }}
          if (set_power_false_calls != 2) {{
            std::cerr << "rect_to_dist: expected two power-off calls (generic branch + reset), got " << set_power_false_calls << std::endl;
            return 1;
          }}

          reset_metrics();
          MockRequest same_mode_request;
          same_mode_request.args["mode"] = std::to_string(SAMOVAR_DISTILLATION_MODE);
          handleSaveProcessSettings(&same_mode_request);
          if (server.remove_calls != 0 || server.serve_calls != 0 || Samovar_Mode != SAMOVAR_DISTILLATION_MODE) {{
            std::cerr << "same_mode_noop: mode switch mutated route/runtime on noop" << std::endl;
            return 1;
          }}
          std::cout << "same_mode_noop|ok|route_unchanged=1" << std::endl;
          std::cout << "reset_pipeline_invariant|ok" << std::endl;
          return 0;
        }}
        """
    )


def run_cpp_harness() -> None:
    compiler = shutil.which("g++") or shutil.which("c++")
    require(compiler is not None, "C++ compiler is required for reset pipeline harness test")

    print("\n[5] Compiling and running sequential reset harness...")
    harness = build_harness()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        harness_path = tmp_path / "reset_pipeline_harness.cpp"
        binary_path = tmp_path / "reset_pipeline_harness"
        harness_path.write_text(harness, encoding="utf-8")

        compile_result = subprocess.run(
            [compiler, "-std=c++17", str(harness_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        require(
            compile_result.returncode == 0,
            compile_result.stderr or compile_result.stdout or "reset harness compile failed",
        )
        print("    ✓ Harness compiled")

        run_result = subprocess.run(
            [str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        require(
            run_result.returncode == 0,
            run_result.stderr or run_result.stdout or "reset harness failed",
        )
        for line in run_result.stdout.splitlines():
            print(f"    {line}")


def main() -> int:
    check_static_pipeline()
    run_cpp_harness()
    print("\n" + "=" * 72)
    print("Reset pipeline invariant: PASS")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
