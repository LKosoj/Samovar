from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


MENU_INPUT_HEADER = Path("ui/menu/input.h")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


class MenuIntegrationBehaviorTest(unittest.TestCase):
    def test_real_menu_headers_work_together_via_display_harness(self) -> None:
        compiler = shutil.which("g++") or shutil.which("c++")
        self.assertIsNotNone(
            compiler,
            "C++ compiler is required for menu integration harness test",
        )
        self.assertTrue(MENU_INPUT_HEADER.exists(), "ui/menu/input.h must exist")

        repo_root = Path.cwd()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            include_root = tmp_path / "include"
            harness_path = tmp_path / "menu_integration_harness.cpp"
            binary_path = tmp_path / "menu_integration_harness"

            _write_file(
                include_root / "Arduino.h",
                """
                #pragma once

                #include <cstdint>
                #include <cstdio>
                #include <cstring>
                #include <string>
                #include <utility>

                using boolean = bool;
                using byte = unsigned char;
                using TickType_t = int;
                using SemaphoreHandle_t = int;
                using StaticSemaphore_t = int;
                using TaskHandle_t = int;

                #ifndef PROGMEM
                #define PROGMEM
                #endif

                static constexpr int pdTRUE = 1;
                static constexpr int portTICK_RATE_MS = 1;
                static constexpr int portTICK_PERIOD_MS = 1;

                class String {
                 public:
                  String() = default;
                  String(const char* text) : value_(text == nullptr ? "" : text) {}
                  String(char* text) : value_(text == nullptr ? "" : text) {}
                  String(const std::string& text) : value_(text) {}
                  String(int number) : value_(std::to_string(number)) {}
                  String(unsigned long number) : value_(std::to_string(number)) {}
                  String(float number) : value_(std::to_string(number)) {}
                  String(const String&) = default;
                  String& operator=(const String&) = default;

                  String& operator=(const char* text) {
                    value_ = text == nullptr ? "" : text;
                    return *this;
                  }

                  const char* c_str() const {
                    return value_.c_str();
                  }

                  void replace(const char* from, const char* to) {
                    if (from == nullptr || to == nullptr || *from == '\\0') {
                      return;
                    }

                    std::string::size_type pos = 0;
                    const std::string needle(from);
                    const std::string repl(to);
                    while ((pos = value_.find(needle, pos)) != std::string::npos) {
                      value_.replace(pos, needle.size(), repl);
                      pos += repl.size();
                    }
                  }

                  friend String operator+(const String& left, const String& right) {
                    return String(left.value_ + right.value_);
                  }

                 private:
                  std::string value_;
                };

                struct MockEsp {
                  int restart_calls = 0;

                  void restart() {
                    restart_calls++;
                  }
                };

                extern MockEsp ESP;

                unsigned long millis();
                void delay(unsigned long milliseconds);
                void vTaskDelay(TickType_t ticks);
                int xSemaphoreTake(SemaphoreHandle_t semaphore, TickType_t timeout);
                void xSemaphoreGive(SemaphoreHandle_t semaphore);
                """,
            )

            _write_file(
                include_root / "LiquidMenu.h",
                """
                #pragma once

                #include <cstddef>
                #include <map>
                #include <vector>

                class LiquidLine {
                 public:
                  template <typename... Args>
                  LiquidLine(int, int, Args&&...) {}

                  void attach_function(int slot, void (*fn)()) {
                    functions_[slot] = fn;
                  }

                  void set_decimalPlaces(int value) {
                    decimal_places = value;
                  }

                  void set_asProgmem(int value) {
                    progmem_slot = value;
                  }

                  bool has_function(int slot) const {
                    return functions_.find(slot) != functions_.end();
                  }

                  void call(int slot) const {
                    auto iterator = functions_.find(slot);
                    if (iterator != functions_.end()) {
                      iterator->second();
                    }
                  }

                  void reset() {
                    functions_.clear();
                    decimal_places = -1;
                    progmem_slot = 0;
                  }

                  int decimal_places = -1;
                  int progmem_slot = 0;

                 private:
                  std::map<int, void (*)()> functions_;
                };

                class LiquidScreen {
                 public:
                  template <typename... Lines>
                  explicit LiquidScreen(Lines&... lines) : lines{{&lines...}} {}

                  void hide(bool value) {
                    hidden = value;
                  }

                  bool hidden = false;
                  std::vector<LiquidLine*> lines;
                };

                class LiquidMenu {
                 public:
                  template <typename Lcd>
                  explicit LiquidMenu(Lcd&) {}

                  void add_screen(LiquidScreen& screen) {
                    screens.push_back(&screen);
                    if (current_screen == nullptr) {
                      current_screen = &screen;
                      current_screen_index = 0;
                    }
                  }

                  void change_screen(LiquidScreen* screen) {
                    current_screen = screen;
                    for (std::size_t index = 0; index < screens.size(); ++index) {
                      if (screens[index] == screen) {
                        current_screen_index = index;
                        break;
                      }
                    }
                    focus_slot = 0;
                  }

                  void previous_screen() {
                    navigate(-1);
                  }

                  void next_screen() {
                    navigate(1);
                  }

                  void switch_focus() {
                    if (current_screen == nullptr) {
                      return;
                    }
                    const std::size_t line_count = current_screen->lines.size();
                    focus_slot = (focus_slot + 1) % (line_count + 1);
                  }

                  bool is_callable(int slot) const {
                    if (current_screen == nullptr || focus_slot == 0) {
                      return false;
                    }
                    return current_screen->lines[focus_slot - 1]->has_function(slot);
                  }

                  void call_function(int slot) {
                    if (current_screen == nullptr || focus_slot == 0) {
                      return;
                    }
                    current_screen->lines[focus_slot - 1]->call(slot);
                  }

                  void update() {
                    update_calls++;
                  }

                  void softUpdate() {
                    soft_update_calls++;
                  }

                  void reset() {
                    screens.clear();
                    current_screen = nullptr;
                    current_screen_index = 0;
                    focus_slot = 0;
                    update_calls = 0;
                    soft_update_calls = 0;
                  }

                  std::vector<LiquidScreen*> screens;
                  LiquidScreen* current_screen = nullptr;
                  std::size_t current_screen_index = 0;
                  std::size_t focus_slot = 0;
                  int update_calls = 0;
                  int soft_update_calls = 0;

                 private:
                  void navigate(int direction) {
                    if (screens.empty()) {
                      return;
                    }

                    int index = static_cast<int>(current_screen_index);
                    for (std::size_t step = 0; step < screens.size(); ++step) {
                      index += direction;
                      if (index < 0) {
                        index = static_cast<int>(screens.size()) - 1;
                      } else if (index >= static_cast<int>(screens.size())) {
                        index = 0;
                      }

                      if (!screens[static_cast<std::size_t>(index)]->hidden) {
                        current_screen_index = static_cast<std::size_t>(index);
                        current_screen = screens[current_screen_index];
                        focus_slot = 0;
                        return;
                      }
                    }
                  }
                };
                """,
            )

            _write_file(
                include_root / "Samovar.h",
                """
                #pragma once

                static constexpr int LCD_COLUMNS = 20;
                static constexpr int LCD_ROWS = 4;
                static constexpr int STEPPER_MAX_SPEED = 120;
                static constexpr int CAPACITY_NUM = 3;
                static constexpr const char* SAMOVAR_VERSION = "test";

                enum SAMOVAR_MODE {
                  SAMOVAR_RECTIFICATION_MODE = 0,
                  SAMOVAR_BEER_MODE = 1,
                  SAMOVAR_DISTILLATION_MODE = 2,
                  SAMOVAR_BK_MODE = 3,
                  SAMOVAR_NBK_MODE = 4,
                  SAMOVAR_SUVID_MODE = 5,
                  SAMOVAR_LUA_MODE = 6,
                };

                enum SamovarCommands {
                  SAMOVAR_NONE = 0,
                  SAMOVAR_POWER = 1,
                  SAMOVAR_BEER = 2,
                  SAMOVAR_DISTILLATION = 3,
                  SAMOVAR_BK = 4,
                  SAMOVAR_NBK = 5,
                };
                """,
            )

            _write_file(
                include_root / "state/globals.h",
                """
                #pragma once

                #include "Arduino.h"
                #include "LiquidMenu.h"
                #include "Samovar.h"

                struct DSSensor {
                  float avgTemp = 0.0f;
                };

                struct WProgram {
                  float WType = 0.0f;
                  float Volume = 0.0f;
                  float Speed = 0.0f;
                  int capacity_num = 0;
                  float Temp = 0.0f;
                  float Power = 0.0f;
                };

                struct SetupEEPROM {
                  float DeltaSteamTemp = 10.0f;
                  float DeltaPipeTemp = 20.0f;
                  float DeltaWaterTemp = 30.0f;
                  float DeltaTankTemp = 40.0f;
                  float SetSteamTemp = 50.0f;
                  float SetPipeTemp = 60.0f;
                  float SetWaterTemp = 70.0f;
                  float SetTankTemp = 80.0f;
                  int StepperStepMl = 5;
                  String TimeZone = String("UTC+3");
                };

                struct MockLcd {
                  int init_calls = 0;
                  int begin_calls = 0;
                  int backlight_calls = 0;
                  int clear_calls = 0;

                  void init() {
                    init_calls++;
                  }

                  void begin(int, int) {
                    begin_calls++;
                  }

                  void backlight() {
                    backlight_calls++;
                  }

                  void clear() {
                    clear_calls++;
                  }

                  void reset() {
                    init_calls = 0;
                    begin_calls = 0;
                    backlight_calls = 0;
                    clear_calls = 0;
                  }
                };

                struct Encoder {
                  bool right = false;
                  bool left = false;
                  bool right_hold = false;
                  bool left_hold = false;
                  bool click = false;

                  bool isRight() {
                    const bool value = right;
                    right = false;
                    return value;
                  }

                  bool isLeft() {
                    const bool value = left;
                    left = false;
                    return value;
                  }

                  bool isRightH() {
                    const bool value = right_hold;
                    right_hold = false;
                    return value;
                  }

                  bool isLeftH() {
                    const bool value = left_hold;
                    left_hold = false;
                    return value;
                  }

                  bool isClick() {
                    const bool value = click;
                    click = false;
                    return value;
                  }

                  void reset() {
                    right = false;
                    left = false;
                    right_hold = false;
                    left_hold = false;
                    click = false;
                  }
                };

                struct MockStepper {
                  int speed = 100;

                  int getSpeed() const {
                    return speed;
                  }
                };

                extern SemaphoreHandle_t xI2CSemaphore;
                extern uint8_t multiplier;
                extern char tst[20];
                extern char ipst[16];
                extern char welcomeStrArr1[20];
                extern char welcomeStrArr2[20];
                extern char welcomeStrArr3[20];
                extern char welcomeStrArr4[20];
                extern char* welcomeStr1;
                extern char* welcomeStr2;
                extern char* welcomeStr3;
                extern char* welcomeStr4;
                extern char* timestr;
                extern char* ipstr;
                extern char startval_text_val[20];
                extern char* power_text_ptr;
                extern char* calibrate_text_ptr;
                extern char* pause_text_ptr;
                extern uint8_t CurMin;
                extern uint8_t OldMin;
                extern MockLcd lcd;
                extern Encoder encoder;
                extern MockStepper stepper;
                extern LiquidMenu main_menu1;
                extern volatile SamovarCommands sam_command_sync;
                extern volatile SAMOVAR_MODE Samovar_Mode;
                extern SetupEEPROM SamSetup;
                extern DSSensor SteamSensor;
                extern DSSensor PipeSensor;
                extern DSSensor WaterSensor;
                extern DSSensor TankSensor;
                extern WProgram program[30];
                extern volatile bool PowerOn;
                extern volatile bool PauseOn;
                extern volatile bool StepperMoving;
                extern volatile bool program_Wait;
                extern volatile float bme_pressure;
                extern volatile uint8_t ProgramNum;
                extern volatile uint8_t ProgramLen;
                extern volatile uint8_t WthdrwlProgress;
                extern volatile int16_t startval;
                extern volatile float ActualVolumePerHour;
                extern unsigned long t_min;
                extern String SessionDescription;
                extern uint32_t chipId;
                """,
            )

            _write_file(
                include_root / "support/safe_parse.h",
                """
                #pragma once

                #include <cstdio>

                #include "Arduino.h"

                template <std::size_t N>
                inline void copyStringSafe(char (&dst)[N], const String& src) {
                  std::snprintf(dst, N, "%s", src.c_str());
                }
                """,
            )

            _write_file(
                include_root / "io/actuators.h",
                """
                #pragma once

                #include "state/globals.h"

                extern int read_config_calls;
                extern int pump_calibrate_calls;
                extern int last_pump_calibrate_speed;
                extern int set_pump_speed_calls;
                extern float last_set_pump_speed;
                extern bool last_set_pump_force;

                inline void read_config() {
                  read_config_calls++;
                }

                inline void pump_calibrate(int speed) {
                  pump_calibrate_calls++;
                  last_pump_calibrate_speed = speed;
                  stepper.speed = speed;
                  StepperMoving = speed > 0;
                }

                inline void set_pump_speed(float speed, bool force) {
                  set_pump_speed_calls++;
                  last_set_pump_speed = speed;
                  last_set_pump_force = force;
                }
                """,
            )

            _write_file(
                include_root / "io/sensor_scan.h",
                """
                #pragma once

                extern int reset_sensor_counter_calls;

                inline void reset_sensor_counter() {
                  reset_sensor_counter_calls++;
                }
                """,
            )

            _write_file(
                include_root / "modes/rect/rect_program_codec.h",
                """
                #pragma once

                #include "Arduino.h"

                inline String get_program(int) {
                  return String("program");
                }
                """,
            )

            _write_file(
                include_root / "modes/rect/rect_runtime.h",
                """
                #pragma once

                #include "state/globals.h"

                extern int pause_withdrawal_calls;
                extern bool last_pause_withdrawal_arg;
                extern int run_program_calls;
                extern int last_run_program;

                inline void pause_withdrawal(bool pause) {
                  pause_withdrawal_calls++;
                  last_pause_withdrawal_arg = pause;
                  PauseOn = pause;
                }

                inline void run_program(uint8_t num) {
                  run_program_calls++;
                  last_run_program = num;
                }
                """,
            )

            _write_file(
                include_root / "storage/nvs_profiles.h",
                """
                #pragma once

                extern int save_profile_nvs_calls;

                inline void save_profile_nvs() {
                  save_profile_nvs_calls++;
                }
                """,
            )

            _write_file(
                include_root / "storage/nvs_wifi.h",
                """
                #pragma once

                extern int clear_wifi_credentials_calls;

                inline void clear_wifi_credentials() {
                  clear_wifi_credentials_calls++;
                }
                """,
            )

            _write_file(
                include_root / "storage/session_logs.h",
                """
                #pragma once

                extern int create_data_calls;

                inline void create_data() {
                  create_data_calls++;
                }
                """,
            )

            _write_file(
                include_root / "support/process_math.h",
                """
                #pragma once

                extern float last_speed_rate_input;

                inline float get_speed_from_rate(float volume_per_hour) {
                  last_speed_rate_input = volume_per_hour;
                  return volume_per_hour * 10.0f;
                }
                """,
            )

            harness_path.write_text(
                textwrap.dedent(
                    """
                    #include <cstdint>
                    #include <cstring>
                    #include <iomanip>
                    #include <iostream>

                    #include "ui/menu/input.h"

                    MockEsp ESP;

                    SemaphoreHandle_t xI2CSemaphore = 1;
                    uint8_t multiplier = 1;
                    char tst[20];
                    char ipst[16];
                    char welcomeStrArr1[20];
                    char welcomeStrArr2[20];
                    char welcomeStrArr3[20];
                    char welcomeStrArr4[20];
                    char* welcomeStr1 = welcomeStrArr1;
                    char* welcomeStr2 = welcomeStrArr2;
                    char* welcomeStr3 = welcomeStrArr3;
                    char* welcomeStr4 = welcomeStrArr4;
                    char* timestr = tst;
                    char* ipstr = ipst;
                    char startval_text_val[20];
                    char* power_text_ptr = nullptr;
                    char* calibrate_text_ptr = nullptr;
                    char* pause_text_ptr = nullptr;
                    uint8_t CurMin = 0;
                    uint8_t OldMin = 0;
                    MockLcd lcd;
                    Encoder encoder;
                    MockStepper stepper;
                    LiquidMenu main_menu1(lcd);
                    volatile SamovarCommands sam_command_sync = SAMOVAR_NONE;
                    volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
                    SetupEEPROM SamSetup;
                    DSSensor SteamSensor;
                    DSSensor PipeSensor;
                    DSSensor WaterSensor;
                    DSSensor TankSensor;
                    WProgram program[30];
                    volatile bool PowerOn = false;
                    volatile bool PauseOn = false;
                    volatile bool StepperMoving = false;
                    volatile bool program_Wait = true;
                    volatile float bme_pressure = 760.0f;
                    volatile uint8_t ProgramNum = 0;
                    volatile uint8_t ProgramLen = 3;
                    volatile uint8_t WthdrwlProgress = 0;
                    volatile int16_t startval = 0;
                    volatile float ActualVolumePerHour = 1.23f;
                    unsigned long t_min = 7;
                    String SessionDescription("session");
                    uint32_t chipId = 42;

                    unsigned long fake_millis = 0;
                    unsigned long delay_ms_total = 0;
                    int vtask_delay_ticks = 0;
                    int x_semaphore_take_calls = 0;
                    int x_semaphore_give_calls = 0;
                    int read_config_calls = 0;
                    int save_profile_nvs_calls = 0;
                    int pause_withdrawal_calls = 0;
                    bool last_pause_withdrawal_arg = false;
                    int pump_calibrate_calls = 0;
                    int last_pump_calibrate_speed = -1;
                    int set_pump_speed_calls = 0;
                    float last_set_pump_speed = -1.0f;
                    bool last_set_pump_force = false;
                    float last_speed_rate_input = -1.0f;
                    int run_program_calls = 0;
                    int last_run_program = -1;
                    int create_data_calls = 0;
                    int reset_sensor_counter_calls = 0;
                    int clear_wifi_credentials_calls = 0;
                    int detector_resume_calls = 0;

                    unsigned long millis() {
                      return fake_millis;
                    }

                    void delay(unsigned long milliseconds) {
                      delay_ms_total += milliseconds;
                    }

                    void vTaskDelay(TickType_t ticks) {
                      vtask_delay_ticks += ticks;
                    }

                    int xSemaphoreTake(SemaphoreHandle_t, TickType_t) {
                      x_semaphore_take_calls++;
                      return pdTRUE;
                    }

                    void xSemaphoreGive(SemaphoreHandle_t) {
                      x_semaphore_give_calls++;
                    }

                    void detector_on_manual_resume() {
                      detector_resume_calls++;
                    }

                    static void reset_line(LiquidLine& line) {
                      line.reset();
                    }

                    static void reset_screen(LiquidScreen& screen) {
                      screen.hide(false);
                    }

                    static void reset_state() {
                      fake_millis = 0;
                      delay_ms_total = 0;
                      vtask_delay_ticks = 0;
                      x_semaphore_take_calls = 0;
                      x_semaphore_give_calls = 0;
                      read_config_calls = 0;
                      save_profile_nvs_calls = 0;
                      pause_withdrawal_calls = 0;
                      last_pause_withdrawal_arg = false;
                      pump_calibrate_calls = 0;
                      last_pump_calibrate_speed = -1;
                      set_pump_speed_calls = 0;
                      last_set_pump_speed = -1.0f;
                      last_set_pump_force = false;
                      last_speed_rate_input = -1.0f;
                      run_program_calls = 0;
                      last_run_program = -1;
                      create_data_calls = 0;
                      reset_sensor_counter_calls = 0;
                      clear_wifi_credentials_calls = 0;
                      detector_resume_calls = 0;

                      multiplier = 1;
                      std::snprintf(tst, sizeof(tst), "%s", "00:00");
                      std::snprintf(ipst, sizeof(ipst), "%s", "192.168.0.10");
                      std::snprintf(welcomeStrArr1, sizeof(welcomeStrArr1), "%s", "Line1");
                      std::snprintf(welcomeStrArr2, sizeof(welcomeStrArr2), "%s", "Line2");
                      std::snprintf(welcomeStrArr3, sizeof(welcomeStrArr3), "%s", "Line3");
                      std::snprintf(welcomeStrArr4, sizeof(welcomeStrArr4), "%s", "Line4");
                      std::snprintf(startval_text_val, sizeof(startval_text_val), "%s", "Boot");

                      welcomeStr1 = welcomeStrArr1;
                      welcomeStr2 = welcomeStrArr2;
                      welcomeStr3 = welcomeStrArr3;
                      welcomeStr4 = welcomeStrArr4;
                      timestr = tst;
                      ipstr = ipst;
                      power_text_ptr = (char*)menu_text_stopped;
                      calibrate_text_ptr = (char*)menu_text_stop;
                      pause_text_ptr = (char*)menu_text_pause;

                      CurMin = 0;
                      OldMin = 0;
                      lcd.reset();
                      encoder.reset();
                      stepper = MockStepper();
                      main_menu1.reset();
                      ESP = MockEsp();

                      sam_command_sync = SAMOVAR_NONE;
                      Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
                      SamSetup = SetupEEPROM();
                      SteamSensor.avgTemp = 78.12f;
                      PipeSensor.avgTemp = 70.34f;
                      WaterSensor.avgTemp = 18.56f;
                      TankSensor.avgTemp = 65.78f;

                      for (auto& program_entry : program) {
                        program_entry = WProgram();
                      }
                      program[0].WType = 1.0f;
                      program[0].Volume = 10.0f;
                      program[0].Speed = 1.5f;
                      program[0].capacity_num = 2;
                      program[0].Temp = 92.0f;
                      program[0].Power = 1400.0f;

                      PowerOn = false;
                      PauseOn = false;
                      StepperMoving = false;
                      program_Wait = true;
                      bme_pressure = 760.0f;
                      ProgramNum = 0;
                      ProgramLen = 3;
                      WthdrwlProgress = 7;
                      startval = 0;
                      ActualVolumePerHour = 1.23f;
                      t_min = 7;

                      reset_line(lql_back_line);
                      reset_line(lql_time);
                      reset_line(welcome_line1);
                      reset_line(welcome_line2);
                      reset_line(welcome_line3);
                      reset_line(welcome_line4);
                      reset_line(lql_steam_temp);
                      reset_line(lql_pipe_temp);
                      reset_line(lql_water_temp);
                      reset_line(lql_tank_temp);
                      reset_line(lql_atm);
                      reset_line(lql_w_progress);
                      reset_line(lql_start);
                      reset_line(lql_pump_speed);
                      reset_line(lql_pause);
                      reset_line(lql_reset);
                      reset_line(lql_get_power);
                      reset_line(lql_setup);
                      reset_line(lql_ip);
                      reset_line(lql_setup_steam_temp);
                      reset_line(lql_setup_pipe_temp);
                      reset_line(lql_setup_water_temp);
                      reset_line(lql_setup_tank_temp);
                      reset_line(lql_setup_set_steam_temp);
                      reset_line(lql_setup_set_pipe_temp);
                      reset_line(lql_setup_set_water_temp);
                      reset_line(lql_setup_set_tank_temp);
                      reset_line(lql_setup_stepper_stepper_step_ml);
                      reset_line(lql_setup_stepper_calibrate);
                      reset_line(lql_setup_stepper_program);
                      reset_line(lql_setup_program_WType);
                      reset_line(lql_setup_program_Volume);
                      reset_line(lql_setup_program_Speed);
                      reset_line(lql_setup_program_capacity_num);
                      reset_line(lql_setup_program_Temp);
                      reset_line(lql_setup_program_Power);
                      reset_line(lql_setup_program_reset_wifi);
                      reset_line(lql_setup_program_back_line);

                      reset_screen(welcome_screen);
                      reset_screen(main_screen);
                      reset_screen(main_screen1);
                      reset_screen(main_screen2);
                      reset_screen(main_screen4);
                      reset_screen(main_screen5);
                      reset_screen(setup_temp_screen);
                      reset_screen(setup_set_temp_screen);
                      reset_screen(setup_stepper_settings);
                      reset_screen(setup_back_screen);
                      reset_screen(setup_program_settings);
                      reset_screen(setup_program_back);
                    }

                    static void advance_time() {
                      fake_millis += 1000;
                    }

                    static void press_right() {
                      advance_time();
                      encoder.right = true;
                      encoder_getvalue();
                    }

                    static void press_left() {
                      advance_time();
                      encoder.left = true;
                      encoder_getvalue();
                    }

                    static void press_click() {
                      advance_time();
                      encoder.click = true;
                      encoder_getvalue();
                    }

                    static void press_right_hold() {
                      advance_time();
                      encoder.right_hold = true;
                      encoder_getvalue();
                    }

                    static void focus_line(std::size_t line_number) {
                      while (main_menu1.focus_slot != line_number) {
                        press_click();
                      }
                    }

                    static bool verify_mode_power_cycle(SAMOVAR_MODE mode, SamovarCommands expected_command) {
                      reset_state();
                      setupMenu();
                      Samovar_Mode = mode;
                      change_screen(&main_screen4);
                      focus_line(1);
                      press_right();
                      const bool start_ok =
                        sam_command_sync == expected_command &&
                        main_menu1.current_screen == &main_screen &&
                        main_screen.hidden == false &&
                        main_screen1.hidden == false &&
                        main_screen4.hidden == false;

                      change_screen(&main_screen4);
                      PowerOn = true;
                      focus_line(1);
                      press_right();
                      const bool stop_ok =
                        sam_command_sync == SAMOVAR_NONE &&
                        main_menu1.current_screen == &main_screen &&
                        std::strcmp(get_power_text(), menu_text_power_on) == 0 &&
                        reset_sensor_counter_calls == 1;

                      return start_ok && stop_ok;
                    }

                    static void invoke_start_line() {
                      focus_line(1);
                      press_right();
                    }

                    int main() {
                      std::cout << std::fixed << std::setprecision(2);

                      reset_state();
                      setupMenu();
                      std::cout
                        << "bootstrap|"
                        << main_menu1.screens.size() << "|"
                        << (main_menu1.screens[0] == &welcome_screen) << "|"
                        << (main_menu1.screens[11] == &setup_program_back) << "|"
                        << welcome_screen.hidden << "|"
                        << (main_menu1.current_screen == &welcome_screen) << "|"
                        << lcd.init_calls << "|"
                        << lcd.begin_calls << "|"
                        << lcd.backlight_calls << "|"
                        << lcd.clear_calls << "|"
                        << lql_pump_speed.decimal_places << "|"
                        << lql_get_power.progmem_slot << "|"
                        << main_menu1.update_calls << "\\n";

                      reset_state();
                      power_text_ptr = (char*)menu_text_power_on;
                      pause_text_ptr = (char*)menu_text_continue;
                      copyStringSafe(startval_text_val, String("Prg No 2"));
                      writeString(String("Warm1"), 1);
                      writeString(String("Warm4"), 4);
                      writeString(String("tick"), 0);
                      std::cout
                        << "render|"
                        << get_welcomeStr1() << "|"
                        << get_welcomeStr4() << "|"
                        << get_startval_text() << "|"
                        << get_pause_text() << "|"
                        << get_power_text() << "|"
                        << main_menu1.update_calls << "|"
                        << main_menu1.soft_update_calls << "\\n";

                      reset_state();
                      setupMenu();
                      press_right();
                      const bool nav_to_main = main_menu1.current_screen == &main_screen;
                      press_right();
                      const bool nav_to_main1 = main_menu1.current_screen == &main_screen1;
                      press_click();
                      const bool focus_main1_line1 = main_menu1.focus_slot == 1;
                      press_left();
                      const bool nav_back_to_main = main_menu1.current_screen == &main_screen;
                      std::cout
                        << "nav|"
                        << nav_to_main << "|"
                        << nav_to_main1 << "|"
                        << focus_main1_line1 << "|"
                        << nav_back_to_main << "\\n";

                      reset_state();
                      setupMenu();
                      change_screen(&main_screen4);
                      press_click();
                      press_click();
                      const float steam_before = SamSetup.DeltaSteamTemp;
                      press_right();
                      const bool setup_opened = main_menu1.current_screen == &setup_temp_screen;
                      press_click();
                      press_right_hold();
                      std::cout
                        << "setup_adjust|"
                        << setup_opened << "|"
                        << steam_before << "|"
                        << SamSetup.DeltaSteamTemp << "|"
                        << main_menu1.focus_slot << "\\n";

                      std::cout << "power_rect|" << verify_mode_power_cycle(SAMOVAR_RECTIFICATION_MODE, SAMOVAR_POWER) << "\\n";
                      std::cout << "power_beer|" << verify_mode_power_cycle(SAMOVAR_BEER_MODE, SAMOVAR_BEER) << "\\n";
                      std::cout << "power_dist|" << verify_mode_power_cycle(SAMOVAR_DISTILLATION_MODE, SAMOVAR_DISTILLATION) << "\\n";
                      std::cout << "power_bk|" << verify_mode_power_cycle(SAMOVAR_BK_MODE, SAMOVAR_BK) << "\\n";
                      std::cout << "power_nbk|" << verify_mode_power_cycle(SAMOVAR_NBK_MODE, SAMOVAR_NBK) << "\\n";
                      std::cout << "power_suvid|" << verify_mode_power_cycle(SAMOVAR_SUVID_MODE, SAMOVAR_POWER) << "\\n";
                      std::cout << "power_lua|" << verify_mode_power_cycle(SAMOVAR_LUA_MODE, SAMOVAR_POWER) << "\\n";

                      reset_state();
                      setupMenu();
                      Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
                      PowerOn = true;
                      ProgramLen = 2;
                      change_screen(&main_screen2);

                      invoke_start_line();
                      const bool start_first_ok =
                        startval == 1 &&
                        ProgramNum == 0 &&
                        run_program_calls == 1 &&
                        last_run_program == 0 &&
                        create_data_calls == 1 &&
                        std::strcmp(get_startval_text(), menu_text_program_number_first) == 0;

                      invoke_start_line();
                      const bool start_second_ok =
                        startval == 1 &&
                        ProgramNum == 1 &&
                        run_program_calls == 2 &&
                        last_run_program == 1 &&
                        std::strcmp(get_startval_text(), "Prg No 2") == 0;

                      invoke_start_line();
                      const bool start_finish_ok =
                        startval == 2 &&
                        run_program_calls == 3 &&
                        last_run_program == CAPACITY_NUM * 2 &&
                        std::strcmp(get_startval_text(), menu_text_program_finish) == 0;

                      invoke_start_line();
                      const bool start_stop_ok =
                        startval == 3 &&
                        run_program_calls == 4 &&
                        last_run_program == CAPACITY_NUM * 2 &&
                        reset_sensor_counter_calls == 1 &&
                        std::strcmp(get_startval_text(), menu_text_stopped) == 0;

                      focus_line(3);
                      press_right();
                      const bool pause_ok =
                        PauseOn &&
                        std::strcmp(get_pause_text(), menu_text_continue) == 0 &&
                        pause_withdrawal_calls == 1 &&
                        last_pause_withdrawal_arg == true;

                      press_right();
                      const bool resume_ok =
                        !PauseOn &&
                        std::strcmp(get_pause_text(), menu_text_pause) == 0 &&
                        pause_withdrawal_calls == 2 &&
                        last_pause_withdrawal_arg == false &&
                        detector_resume_calls == 1 &&
                        t_min == 0 &&
                        !program_Wait;

                      std::cout
                        << "rect_cycle|"
                        << start_first_ok << "|"
                        << start_second_ok << "|"
                        << start_finish_ok << "|"
                        << start_stop_ok << "|"
                        << pause_ok << "|"
                        << resume_ok << "\\n";

                      return 0;
                    }
                    """
                ),
                encoding="utf-8",
            )

            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-I",
                    str(include_root),
                    "-I",
                    str(repo_root),
                    str(harness_path),
                    "-o",
                    str(binary_path),
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                compile_result.returncode,
                0,
                msg=compile_result.stderr or compile_result.stdout,
            )

            run_result = subprocess.run(
                [str(binary_path)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                run_result.returncode,
                0,
                msg=run_result.stderr or run_result.stdout,
            )

        output_map = {}
        for line in run_result.stdout.strip().splitlines():
            parts = line.split("|")
            output_map[parts[0]] = parts[1:]

        self.assertEqual(
            output_map["bootstrap"],
            ["12", "1", "1", "1", "1", "1", "1", "1", "1", "2", "1", "1"],
        )
        self.assertEqual(
            output_map["render"],
            ["Warm1", "Warm4", "Prg No 2", "Continue", "ON", "1", "3"],
        )
        self.assertEqual(output_map["nav"], ["1", "1", "1", "1"])
        self.assertEqual(output_map["setup_adjust"], ["1", "10.00", "10.10", "1"])

        for scenario in [
            "power_rect",
            "power_beer",
            "power_dist",
            "power_bk",
            "power_nbk",
            "power_suvid",
            "power_lua",
        ]:
            with self.subTest(scenario=scenario):
                self.assertEqual(output_map[scenario], ["1"])

        self.assertEqual(output_map["rect_cycle"], ["1", "1", "1", "1", "1", "1"])


if __name__ == "__main__":
    unittest.main()
