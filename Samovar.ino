// copy to /Users/user/Library/Arduino15/packages/esp32/hardware/esp32/3.x.x/tools/partitions/samovar.csv
// add to /Users/user/Library/Arduino15/packages/esp32/hardware/esp32/3.x.x/boards.txt
// esp32.menu.PartitionScheme.samovar=Samovar
// esp32.menu.PartitionScheme.samovar.build.partitions=samovar
// esp32.menu.PartitionScheme.samovar.upload.maximum_size=1638400

//**************************************************************************************************************
// Подключение библиотек
//**************************************************************************************************************

//#define Serial2 Serial

#define CONFIG_ASYNC_TCP_RUNNING_CORE 1      // force async_tcp task to be on same core as Arduino app (default is any core)
#define CONFIG_ASYNC_TCP_STACK_SIZE 4096     // reduce the stack size (default is 16K)

#undef CONFIG_BT_ENABLED
#include <Arduino.h>

#include <esp_wifi.h>

#if defined(ARDUINO_ESP32S3_DEV)
#else
#include "esp32/rom/rtc.h"
#endif

#include <driver/touch_sensor.h>
#include <esp32-hal-cpu.h>
#include <esp_heap_caps.h>
#include <esp_heap_caps_init.h>

#if defined(ARDUINO_ESP32S3_DEV)
//
#else
#include <driver/dac.h>
#endif

#include "esp_log.h"

#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_Sensor.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <ESPmDNS.h>
#include <Update.h>
//#include <ESPping.h>

#include <LiquidMenu.h>

#include <EEPROM.h>
#include <Preferences.h>

#include <GyverEncoder.h>

#include <GyverButton.h>

#include <GyverPID.h>

//#include <mString.h>

#include <PID_v1.h>
#include <PID_AutoTune_v0.h>

#include <ESP32Servo.h>

#include <iarduino_I2C_connect.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/process_common.h"
#include "app/status_text.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "modes/rect/rect_runtime.h"
#include "impurity_detector.h"
#include "support/safe_parse.h"
#include "support/process_math.h"
#include "crash_handler.h"

#ifndef __SAMOVAR_DEBUG
#define ARDUINOTRACE_ENABLE 0  // Disable all traces
#endif
#include <ArduinoTrace.h>

#ifdef __SAMOVAR_NOT_USE_WDT
#include "soc/rtc_wdt.h"
#include <esp_task_wdt.h>
#endif

#ifdef USE_LUA
#include "lua.h"
#endif

#include <NTPClient.h>
WiFiUDP ntpUDP;
NTPClient NTP(ntpUDP, "ru.pool.ntp.org");

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

#ifdef USE_BME680
#include <Adafruit_BME680.h>
#endif

#ifdef USE_BMP180
#include <Adafruit_BMP085_U.h>
#endif

#ifdef USE_BMP280
#include <Adafruit_BMP280.h>
#endif
#ifdef USE_BME280
#include <Adafruit_BME280.h>
#endif

#ifdef USE_PRESSURE_XGZ
#include <XGZP6897D.h>
XGZP6897D pressure_sensor(USE_PRESSURE_XGZ);
#endif


#include "mod_rmvk.h"

//#include "font.h"

#ifdef USE_UPDATE_OTA
#include <ArduinoOTA.h>
#endif

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial
//#define BLYNK_TIMEOUT_MS 888
//#define BLYNK_HEARTBEAT 17

#include <BlynkSimpleEsp32.h>

#endif

#if defined(SAMOVAR_USE_BLYNK) || defined(USE_TELEGRAM)
#include <simple_queue.h>
SimpleStringQueue msg_q(5, 200);
#endif

#ifdef USE_TELEGRAM
#include <UrlEncode.h>
#endif

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#include "distiller.h"
#include "beer.h"
#include "BK.h"
#include "nbk.h"
#include "SPIFFSEditor.h"

#include "I2CStepper.h"

//#include <HTTPClient.h>
//HTTPClient client;

SemaphoreHandle_t xSemaphore = NULL;
SemaphoreHandle_t xMsgSemaphore = NULL;
StaticSemaphore_t xMsgSemaphoreBuffer;

SemaphoreHandle_t xI2CSemaphore = NULL;
StaticSemaphore_t xI2CSemaphoreBuffer;

#ifdef SAMOVAR_USE_SEM_AVR
SemaphoreHandle_t xSemaphoreAVR = NULL;
StaticSemaphore_t xSemaphoreBufferAVR;
#endif

uint8_t multiplier = 1;

char ipst[16] = "000.000.000.000";
char welcomeStrArr1[20];
char welcomeStrArr2[20];
char welcomeStrArr3[20];
char welcomeStrArr4[20];
char* welcomeStr1 = (char*)welcomeStrArr1;
char* welcomeStr2 = (char*)welcomeStrArr2;
char* welcomeStr3 = (char*)welcomeStrArr3;
char* welcomeStr4 = (char*)welcomeStrArr4;

char* ipstr = (char*)ipst;
char startval_text_val[20];
char* startval_text = (char*)startval_text_val;
char* power_text_ptr = (char*)"ON";
char* calibrate_text_ptr = (char*)"Start";
char* pause_text_ptr = (char*)"Pause";
String StrCrt;
String Crt;
uint8_t CurMin, OldMin;

TaskHandle_t SysTickerTask1 = NULL;
TaskHandle_t GetClockTask1 = NULL;
TaskHandle_t GetBMPTask = NULL;

volatile bool buzzer_active = false;
volatile uint8_t buzzer_beep_count = 0;
volatile unsigned long buzzer_next_time = 0;
volatile bool buzzer_state = false;

#ifdef SAMOVAR_USE_POWER
TaskHandle_t PowerStatusTask = NULL;
#endif

AsyncWebServer server(80);
AsyncEventSource events("/events");

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
DeviceAddress DSAddr[6];

LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLUMNS, LCD_ROWS);

Encoder encoder(ENC_CLK, ENC_DT, ENC_SW, TYPE2);

GStepper2< STEPPER2WIRE> stepper(STEPPER_STEPS, STEPPER_STEP, STEPPER_DIR, STEPPER_EN);

iarduino_I2C_connect I2C2;

File fileToAppend;

#ifdef SERVO_PIN
Servo servo;
#endif

#ifdef BTN_PIN
GButton btn(BTN_PIN);
#endif

#ifdef ALARM_BTN_PIN
GButton alarm_btn(ALARM_BTN_PIN);
#endif

#ifdef USE_EXPANDER
PCF8575 expander(&Wire, USE_EXPANDER, LCD_SDA, LCD_SCL);
#endif

#ifdef USE_ANALOG_EXPANDER
PCF8591 analog_expander(&Wire, USE_ANALOG_EXPANDER, LCD_SDA, LCD_SCL);
#endif

double Input, Output, Setpoint;
double Kp, Ki, Kd;

PID heaterPID(&Input, &Output, &Setpoint, Kp, Ki, Kd, DIRECT);
int periodInSeconds = 6;

uint8_t ATuneModeRemember = 2;
double aTuneStep = 50;
double aTuneNoise = 1;
unsigned int aTuneLookBack = 9;
boolean tuning = false;

PID_ATune aTune(&Input, &Output);

#ifdef USE_HEAD_LEVEL_SENSOR
GButton whls(WHEAD_LEVEL_SENSOR_PIN);
#endif

GButton nbkls(LUA_PIN);

LiquidMenu main_menu1(lcd);

volatile SamovarCommands sam_command_sync;

volatile SAMOVAR_MODE Samovar_Mode;
volatile SAMOVAR_MODE Samovar_CR_Mode;

volatile MESSAGE_TYPE msg_type;

SetupEEPROM SamSetup;
ImpurityDetector impurityDetector;

DSSensor SteamSensor;
DSSensor PipeSensor;
DSSensor WaterSensor;
DSSensor TankSensor;
DSSensor ACPSensor;

WProgram program[30];

const char* host = SAMOVAR_HOST;
const float EVAPORATION_FACTOR = 4.8f;

uint8_t DScnt = 0;
uint8_t STcnt = 0;
bool bmefound = true;
volatile bool PowerOn = false;
volatile bool PauseOn = false;
volatile bool StepperMoving = false;
volatile bool program_Pause;
volatile bool program_Wait;
volatile bool heater_state;
volatile bool loop_lua_fl = false;
volatile bool show_lua_script = false;
volatile bool is_self_test;
volatile bool SetScriptOff;
bool boil_started;
bool valve_status;
bool pump_started;
bool msgfl;
bool mixer_status;
bool alarm_event;
bool acceleration_heater;
bool send_mqtt;
bool is_reboot = false;
bool lcd_found = false;
bool wetting_autostart = false;
bool reg_online = false;
volatile bool ota_running = false;
unsigned long last_reg_online = 0;

volatile float bme_temp;
volatile float start_pressure;
volatile float bme_pressure;
volatile float bme_prev_pressure;
String SamovarStatus;
volatile int16_t SamovarStatusInt;
volatile uint8_t capacity_num;

volatile uint8_t prev_ProgramNum;
volatile uint8_t ProgramNum;
volatile uint8_t ProgramLen;
volatile uint8_t WthdrwlProgress;
volatile int16_t startval = 0;
volatile int currentstepcnt = 0;
volatile unsigned long prev_time_ms;
volatile float ActualVolumePerHour;
volatile uint16_t CurrrentStepperSpeed;
volatile uint16_t I2CStepperSpeed;
volatile uint16_t I2CPumpCmdSpeed;
volatile uint32_t I2CPumpTargetSteps;
volatile float I2CPumpTargetMl;
volatile bool I2CPumpCalibrating;
volatile unsigned int CurrrentStepps;
volatile unsigned int TargetStepps;
String program_Wait_Type;
unsigned long begintime;
unsigned long t_min;
unsigned long alarm_t_min;
unsigned long alarm_h_min;
float d_s_temp_prev;
float d_s_temp_finish;
unsigned long d_s_time_min;
float boil_temp;
float b_t_temp_prev;
unsigned long b_t_time_min;
unsigned long b_t_time_delay;
float alcohol_s;
volatile uint16_t WFpulseCount = 0;
volatile uint16_t WFflowMilliLitres = 0;
volatile uint32_t WFtotalMilliLitres = 0;
volatile float WFflowRate;
volatile int WFAlarmCount;
uint16_t acceleration_temp;
volatile float WthdrwTimeAll;
volatile float WthdrwTime;
String WthdrwTimeAllS;
String WthdrwTimeS;
String jsonstr;
String Msg;
String LogMsg;
uint8_t msg_level;
int bk_pwm;
uint32_t chipId = 0;
String SessionDescription;
volatile float test_num_val;
float pressure_value;
float old_pressure_value;
bool use_pressure_sensor;

volatile float BoilerVolume = 30.0f;
volatile float CurrentHeatLoss = 0;
volatile float CalculatedTargetFR = 0;
unsigned long heatStartMillis = 0;
float heatStartTemp = 0;
bool heatLossCalculated = false;

String test_str_val;
String Lua_status;
uint32_t total_byte;
uint32_t used_byte;
uint8_t use_I2C_dev;
uint16_t water_pump_speed;

String current_power_mode;
volatile float target_power_volt = 0;
volatile float current_power_volt = 0;
unsigned long alarm_c_min;
unsigned long alarm_c_low_min;

#ifdef SAMOVAR_USE_POWER
volatile float prev_target_power_volt;
volatile uint16_t current_power_p;
uint8_t power_err_cnt;
#endif

#ifdef USE_WATER_PUMP
uint8_t wp_count;
#endif

//**************************************************************************************************************
// Инициализация сенсоров и функции работы с сенсорами
//**************************************************************************************************************
#include "sensorinit.h"

// Единственные определения буфера времени для LCD (см. extern в Samovar.h)
char tst[20] = "00:00:00   00:00:00";
char* timestr = (char*)tst;

hw_timer_t *timer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;
portMUX_TYPE waterPulseMux = portMUX_INITIALIZER_UNLOCKED;

// WiFiManager отключен: флагов сохранения через портал больше нет

void load_profile_nvs();
void migrate_from_eeprom();
// void reset_migration_flag(); // Только для тестирования миграции

void setupMenu();
void WebServerInit(void);
void encoder_getvalue();
void menu_calibrate();
void distiller_finish();
void beer_finish();
void change_samovar_mode();
void samovar_reset();
// WiFiManager отключен
void verbose_print_reset_reason();
void menu_switch_focus();
float get_steam_alcohol(float t);
float get_alcohol(float t);
void startService(void);
String http_sync_request_get(String url);

#include "app/messages.h"
#include "app/config_apply.h"
#include "app/loop_dispatch.h"
#include "app/orchestration.h"
#include "app/runtime_tasks.h"
#include "ui/web/ajax_snapshot.h"

#ifdef __SAMOVAR_DEBUG
//LOG_LOCAL_LEVEL ESP_LOG_VERBOSE
//CORE_DEBUG_LEVEL ARDUHAL_LOG_LEVEL_VERBOSE
#endif

#ifdef USE_WEB_SERIAL
void recvMsg(uint8_t *data, size_t len) {
  WebSerial.println("Received Data...");
  String d = "";
  d = "";
  for (int i = 0; i < len; i++) {
    d += char(data[i]);
  }
  String Var, Val;
  Var = "";
  Val = "";
  Var = getValue(d, '=', 0);
  Val = getValue(d, '=', 1);
  Var.trim();
  Val.trim();
  if (Val.length() > 0) {
    WebSerial.print(Var);
    WebSerial.print(" = ");
    if (Var == "WFpulseCount") {
      WFpulseCount = (uint8_t)Val.toInt();
      WebSerial.println(WFpulseCount);
    } else if (Var.length() > 0) {
    }
  } else if (d == "print") {
    WebSerial.println("_______________________________________________");
    WebSerial.print("WFpulseCount = ");
    WebSerial.println(WFpulseCount);
    WebSerial.println("_______________________________________________");
  } else
    WebSerial.print("echo ");
  WebSerial.println(d);
}
#endif

void setup() {
  samovar_app_setup();
}

void loop() {
  samovar_app_loop();
}

// WiFiManager отключен: configModeCallback/saveConfigCallback больше не используются

void verbose_print_reset_reason()
{
  esp_reset_reason_t reason = esp_reset_reason();
  switch (reason)
  {
    case 1  : SamovarStatus = "Vbat power on reset"; break;
    case 3  : SamovarStatus = "Software reset digital core"; break;
    case 4  : SamovarStatus = "Legacy watch dog reset digital core"; break;
    case 5  : SamovarStatus = "Deep Sleep reset digital core"; break;
    case 6  : SamovarStatus = "Reset by SLC module, reset digital core"; break;
    case 7  : SamovarStatus = "Timer Group0 Watch dog reset digital core"; break;
    case 8  : SamovarStatus = "Timer Group1 Watch dog reset digital core"; break;
    case 9  : SamovarStatus = "RTC Watch dog Reset digital core"; break;
    case 10 : SamovarStatus = "Instrusion tested to reset CPU"; break;
    case 11 : SamovarStatus = "Time Group reset CPU"; break;
    case 12 : SamovarStatus = "Software reset CPU"; break;
    case 13 : SamovarStatus = "RTC Watch dog Reset CPU"; break;
    case 14 : SamovarStatus = "for APP CPU, reseted by PRO CPU"; break;
    case 15 : SamovarStatus = "Reset when the vdd voltage is not stable"; break;
    case 16 : SamovarStatus = "RTC Watch dog reset digital core and rtc module"; break;
    default : SamovarStatus = "NO_MEAN";
  }
  if (reason != 0) {
    SamovarStatus = "Причина последней перезагрузки: " + SamovarStatus;
    Serial.println(SamovarStatus);
    SendMsg(SamovarStatus, NOTIFY_MSG);
    SamovarStatus.clear();
  }
}
