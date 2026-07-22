#pragma once

#include "Samovar.h"
#include "samovar_command_queue.h"
#include "operation_store.h"

class AsyncWiFiManager;
struct ProgramDraft;
extern volatile bool mode_switch_barrier_active;
extern OperationStore operationStore;

enum ModeSwitchResult : uint8_t {
  MODE_SWITCH_PENDING = 0,
  MODE_SWITCH_SUCCEEDED,
  MODE_SWITCH_FAILED,
};

enum PersistResult : uint8_t {
  PERSIST_OK = 0,
  PERSIST_OPEN_FAILED,
  PERSIST_WRITE_FAILED,
  PERSIST_SHORT_WRITE,
  PERSIST_REOPEN_FAILED,
  PERSIST_STORED_SIZE_MISMATCH,
  PERSIST_READ_FAILED,
  PERSIST_SHORT_READ,
  PERSIST_READBACK_MAGIC,
  PERSIST_READBACK_VERSION,
  PERSIST_READBACK_PAYLOAD_SIZE,
  PERSIST_READBACK_CRC,
  PERSIST_READBACK_PAYLOAD_ENCODING,
  PERSIST_READBACK_MISMATCH,
};

enum ProfileLoadResult : uint8_t {
  PROFILE_LOAD_OK = 0,
  PROFILE_LOAD_NOT_FOUND,
  PROFILE_LOAD_OPEN_FAILED,
  PROFILE_LOAD_STORED_SIZE_MISMATCH,
  PROFILE_LOAD_READ_FAILED,
  PROFILE_LOAD_SHORT_READ,
  PROFILE_LOAD_MAGIC,
  PROFILE_LOAD_VERSION,
  PROFILE_LOAD_PAYLOAD_SIZE,
  PROFILE_LOAD_CRC,
  PROFILE_LOAD_PAYLOAD_ENCODING,
  PROFILE_LOAD_LEGACY_INVALID,
  PROFILE_LOAD_EEPROM_OPEN_FAILED,
};

enum FsInitResult : uint8_t {
  FS_INIT_OK = 0,
  FS_INIT_MOUNT_FAILED,
  FS_INIT_FORMATTED,
};

enum PumpCalibrationResult : uint8_t {
  PUMP_CALIBRATION_OK = 0,
  PUMP_CALIBRATION_INVALID_STATE,
  PUMP_CALIBRATION_INVALID_RESULT,
  PUMP_CALIBRATION_PROFILE_PERSIST_FAILED,
};

// Core runtime and messaging
void writeString(String Str, uint8_t num);
void WriteConsoleLog(String StringLogMsg);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void stopService(void);
void startService(void);
void send_ajax_json(AsyncWebServerRequest *request);
void apply_config_runtime();
void saveConfigCallback();
void configModeCallback(AsyncWiFiManager *myWiFiManager);

// NVS/profile and filesystem
void set_default_setup_profile(SetupEEPROM& candidate);
ProfileLoadResult load_profile_nvs(SetupEEPROM& candidate);
ProfileLoadResult migrate_from_eeprom(SetupEEPROM& candidate);
PersistResult save_profile_nvs(const SetupEEPROM& candidate);
const char* persist_result_code(PersistResult result);
const char* profile_load_result_code(ProfileLoadResult result);
void print_nvs_stats(const char* context);
void clear_migrated_legacy_profile_data();
FsInitResult FS_init(void);
void FS_register_web_handlers(void);
bool create_data();
String append_data();
bool request_data_log_close();
bool data_log_close_pending();
void process_pending_data_log_ops();
String formatBytes(size_t bytes);
bool exists(String path);

// Menu and local controls
void setupMenu();
void encoder_getvalue();
void menu_calibrate();
void menu_reset_wifi();
void menu_switch_focus();
void menu_samovar_start();
void samovar_reset();
void set_menu_screen(uint8_t param);

// Web API
void WebServerInit(void);
void change_samovar_mode();
bool mode_switch_in_progress();
ModeSwitchResult switch_samovar_mode(SAMOVAR_MODE requestedMode);
void send_index_template_response(AsyncWebServerRequest *request, const char *spiffsPath, const char *cacheControl);
void send_mode_specific_htm(AsyncWebServerRequest *request, const char *spiffsPath, SAMOVAR_MODE requiredMode);
String indexKeyProcessor(const String &var);
String indexKeyProcessorWithSnapshots(const String &var, const String &description, const String &luaButtonList);
bool copy_lua_button_list_cache(String &buttonList);
String setupKeyProcessor(const String &var);
String calibrateKeyProcessor(const String &var);
void web_command(AsyncWebServerRequest *request);
void handleSave(AsyncWebServerRequest *request);
void web_program(AsyncWebServerRequest *request);
void calibrate_command(AsyncWebServerRequest *request);
void get_data_log(AsyncWebServerRequest *request, String fn);
String http_sync_request_get(String url);
String http_sync_request_post(String url, String body, String ContentType);
String get_web_file(String fn, get_web_type type);
void get_web_interface();

// Generic parsing and formatting
uint8_t getDelimCount(const String& data, char separator);
String getValue(const String& data, char separator, int index);
inline String format_float(float v, int d);

// Rectification and shared process helpers
void withdrawal(void);
void run_program(uint8_t num);
ProgramParseResult set_program(const String& WProgram);
String get_program(uint8_t s);
PumpCalibrationResult pump_calibrate(int stpspeed);
void pause_withdrawal(bool Pause);
String get_Samovar_Status();
String tick_status_fsm();
String get_distiller_status_text();
String get_beer_status_text();
String get_bk_status_text();
String get_nbk_status_text();
int get_liquid_volume();
float get_liquid_volume_by_step(float StepCount);
float get_liquid_rate_by_step(int StepperSpeed);
float get_speed_from_rate(float volume_per_hour);
float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure);
void set_body_temp();
void set_capacity(uint8_t cap);
void next_capacity(void);
void check_alarm();
void open_valve(bool Val, bool msg);
void process_buzzer();
void set_buzzer(bool fl);
void set_alarm();
inline void set_power(bool On, bool enqueueResetCommand = true);
inline bool emergency_trip_heater_outputs_locked();
inline void force_heater_output_off_locked(bool requestSleep);
inline bool heater_safety_latched();
inline bool heater_power_on();
inline bool heater_enable_outputs(uint8_t outputs);
inline void notify_power_worker();
inline void set_power_worker_ready(bool ready);
inline void tick_power_transition();
inline bool power_transition_active();
inline bool power_transition_start_pending();
inline bool safety_owner_generation_acquire(uint64_t& generation);
inline bool safety_owner_generation_valid(uint64_t generation);
inline void safety_owner_generation_release(uint64_t generation);
inline void process_pending_power_request();
inline void cancel_invalid_mode_heating_session();
inline bool mode_heating_start_active();
inline void mode_cancel_process_start(const String& message);
inline void mode_warn_log_close_failed();
inline void set_current_power(float Volt);
inline void set_power_mode(String Mode);
void check_power_error();
void get_current_power();
float get_steam_alcohol(float t);
float get_alcohol(float t);
void set_boiling();
bool check_boiling();
inline bool self_test_active();
inline void start_self_test(void);
inline void tick_self_test(void);
inline void stop_self_test(void);
inline void request_emergency_stop(const String& reason);
inline void perform_emergency_stop();
#ifdef USE_LUA
inline bool request_lua_mode_stop();
inline bool lua_mode_owner_idle();
#endif
bool process_sensor_failed(const char* modeName, const char* sensorName);
inline bool samovar_process_active();
inline bool sensor_configured(const DSSensor& sensor);
inline bool sensor_reading_valid(const DSSensor& sensor);
inline bool sensor_valid(const DSSensor& sensor);
inline bool optional_sensor_failed(const DSSensor& sensor);
inline bool sensor_temp_at_least(const DSSensor& sensor, float temp);
#ifdef COLUMN_WETTING
bool column_wetting();
#endif

// Detector and heat-loss helpers
void init_impurity_detector();
void reset_heat_loss_calculation();
void reset_impurity_detector();
void detector_on_program_start(ProgramType wtype);
void detector_on_auto_resume();
void detector_on_manual_resume();
void process_impurity_detector();
void update_heat_loss_calculation();
void stop_process(String reason);

// Mode programs
void distiller_proc();
void distiller_finish();
void check_alarm_distiller();
void run_dist_program(uint8_t num);
ProgramParseResult set_dist_program(const String& WProgram);
String get_dist_program();
void resetTimePredictor();
void updateTimePredictor();
float get_dist_remaining_time();
float get_dist_predicted_total_time();

void beer_proc();
void beer_finish();
void beer_stage_tick();
void beer_check_cooling_limits();
void run_beer_program(uint8_t num);
ProgramParseResult set_beer_program(const String& WProgram);
String get_beer_program();
void check_mixer_state();
void set_mixer_state(bool state, bool dir);
void set_mixer(bool On);
void set_heater_state(float setpoint, float temp);
void set_heater(double dutyCycle);
#ifdef SAMOVAR_USE_POWER
inline void set_heater_regulator(double dutyCycle);
#endif
void setHeaterPosition(bool state);
void StartAutoTune();
void FinishAutoTune();
void HopStepperStep();

void bk_proc();
void bk_finish();
void check_alarm_bk();
void set_water_temp(float duty);

void nbk_proc();
inline void nbk_finish();
inline void nbk_emergency_finish();
inline void tick_nbk_transition();
inline void cancel_nbk_transition();
inline bool nbk_transition_blocks_process();
inline bool nbk_transition_active();
void check_alarm_nbk();
bool check_nbk_critical_alarms();
void run_nbk_program(uint8_t num);
ProgramParseResult set_nbk_program(const String& WProgram);
String get_nbk_program();
float fromPower(float value);

inline void check_alarm_suvid();
inline float suvid_target_temp();

// Sensors and hardware
ProgramParseResult prepare_default_program_for_mode(SAMOVAR_MODE mode, ProgramDraft& draft);
ProgramParseResult load_default_program_for_mode(SAMOVAR_MODE mode);
void BME_getvalue(bool fl);
void pressure_sensor_get();
void DS_getvalue(void);
void scan_ds_adress();
void sensor_init(void);
void reset_sensor_counter(void);
void printAddress(DeviceAddress deviceAddress);
String getDSAddress(DeviceAddress deviceAddress);
String get_DSAddressList(String Address);
void CopyDSAddress(const uint8_t* DevSAddress, uint8_t* DevTAddress);
void get_task_stack_usage();
void init_pump_pwm(uint8_t pin, int freq);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void set_pump_speed(float pumpspeed, bool continue_process);

// I2C stepper
inline void detect_i2c_steppers();
inline float i2c_stepper_steps_from_rate(float volume_per_hour);
inline bool set_stepper_by_time(uint16_t spd, uint8_t direction, uint16_t time);
inline bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
inline uint16_t get_stepper_speed(void);
inline uint32_t get_stepper_status(void);
inline bool set_mixer_pump_target(uint8_t on);
inline uint8_t get_mixer_pump_status(void);
inline uint8_t get_i2c_rele_state(uint8_t r);
inline bool set_i2c_rele_state(uint8_t r, bool s);
inline float i2c_get_liquid_volume_by_step(int stepCount);
inline float i2c_get_liquid_rate_by_step(int stepperSpeed);
inline float i2c_get_speed_from_rate(float volume_per_hour);
inline float i2c_get_liquid_volume();

enum LuaModeTarget : uint8_t {
  LUA_MODE_TARGET_SETUP = 0,
  LUA_MODE_TARGET_ACTIVE,
  LUA_MODE_TARGET_CONTROL,
};

#ifdef USE_LUA
bool set_lua_mode_value(LuaModeTarget target, int32_t value);
void lua_init();
String get_lua_script_list();
String get_lua_script(String fn);
bool run_lua_script(String fn);
String run_lua_string(String lstr);
void load_lua_script();
void do_lua_script(void *parameter);
bool start_lua_script();
String get_global_variables();
String get_lua_mode_name(bool filename = true);
#endif

#ifdef USE_MQTT
void MqttSendMsg(const String &Str, const char *chart, int version = 3);
#endif

#include "mode_registry.h"
