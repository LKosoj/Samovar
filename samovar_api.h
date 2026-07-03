#pragma once

#include "Samovar.h"
#include "samovar_command_queue.h"

class AsyncWiFiManager;

// Core runtime and messaging
void writeString(String Str, uint8_t num);
void WriteConsoleLog(String StringLogMsg);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void stopService(void);
void startService(void);
void send_ajax_json(AsyncWebServerRequest *request);
void apply_config_runtime();
void read_config();
void saveConfigCallback();
void configModeCallback(AsyncWiFiManager *myWiFiManager);

// NVS/profile and filesystem
bool profile_exists();
bool recover_pending_nvs_compaction();
void set_current_profile_mode(SAMOVAR_MODE mode);
void set_default_setup_profile();
void load_profile_nvs();
void migrate_from_eeprom();
void print_nvs_stats(const char* context);
void save_profile_nvs();
void save_profile();
void FS_init(void);
bool create_data();
String append_data();
bool request_data_log_close();
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
void switch_samovar_mode(SAMOVAR_MODE requestedMode);
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
String get_web_file(String fn, get_web_type type);
void get_web_interface();
String http_sync_request_get(String url);
String http_sync_request_post(String url, String body, String ContentType);

// Generic parsing and formatting
uint8_t getDelimCount(const String& data, char separator);
String getValue(const String& data, char separator, int index);
inline String format_float(float v, int d);

// Rectification and shared process helpers
void withdrawal(void);
void run_program(uint8_t num);
void set_program(String WProgram);
String get_program(uint8_t s);
void pump_calibrate(int stpspeed);
void pause_withdrawal(bool Pause);
String get_Samovar_Status();
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
void set_power(bool On, bool enqueueResetCommand = true);
void set_current_power(float Volt);
void set_power_mode(String Mode);
void check_power_error();
void get_current_power();
float get_steam_alcohol(float t);
float get_alcohol(float t);
void set_boiling();
bool check_boiling();
void start_self_test(void);
void stop_self_test(void);
void request_emergency_stop(const String& reason);
void perform_emergency_stop();
bool process_sensor_failed(const char* modeName, const char* sensorName);
inline bool samovar_process_active();
inline bool sensor_configured(const DSSensor& sensor);
inline bool sensor_reading_valid(const DSSensor& sensor);
inline bool sensor_valid(const DSSensor& sensor);
inline bool optional_sensor_failed(const DSSensor& sensor);
inline bool sensor_temp_at_least(const DSSensor& sensor, float temp);
unsigned int hexToDec(String hexString);
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
void set_dist_program(String WProgram);
String get_dist_program();
void resetTimePredictor();
void updateTimePredictor();
float get_dist_remaining_time();
float get_dist_predicted_total_time();

void beer_proc();
void beer_finish();
void check_alarm_beer();
void run_beer_program(uint8_t num);
void set_beer_program(String WProgram);
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
void nbk_finish();
void nbk_emergency_finish();
void check_alarm_nbk();
bool check_nbk_critical_alarms();
void run_nbk_program(uint8_t num);
void set_nbk_program(String WProgram);
String get_nbk_program();
float fromPower(float value);

// Sensors and hardware
void load_default_program_for_mode();
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

#ifdef USE_LUA
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
