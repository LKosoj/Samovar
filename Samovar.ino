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
  esp_log_level_set("i2c.master", ESP_LOG_NONE);
  pinMode(0, INPUT);
  vTaskDelay(600 / portTICK_PERIOD_MS);
  if (digitalRead(0) == LOW) {
    WiFi.mode(WIFI_STA);  // cannot erase if not in STA mode !
    WiFi.persistent(true);
    WiFi.disconnect(true, true);
    WiFi.persistent(false);
  }
#ifdef __SAMOVAR_NOT_USE_WDT
  esp_task_wdt_init(1, false);
  esp_task_wdt_init(2, false);
  rtc_wdt_protect_off();
  rtc_wdt_disable();
  disableCore0WDT();
  disableCore1WDT();
#endif
  heap_caps_enable_nonos_stack_heaps();

  vTaskDelay(500 / portTICK_PERIOD_MS);
  Serial.begin(115200);

#ifdef __SAMOVAR_DEBUG
  esp_log_level_set("*", ESP_LOG_VERBOSE);
  Serial.println("Using ESP object:");
  Serial.println(ESP.getSdkVersion());

  Serial.println("Using lower level function:");
  Serial.println(esp_get_idf_version());
#endif

  //vr = verbose_print_reset_reason(rtc_get_reset_reason(0));
  //vr = vr + ";" + verbose_print_reset_reason(rtc_get_reset_reason(1));

  //delay(2000);
  //  dac_output_disable(DAC_CHANNEL_1);
  //  dac_output_disable(DAC_CHANNEL_2);
  //  touch_pad_isr_deregister();
  //  touch_pad_deinit();
#if defined(ARDUINO_ESP32S3_DEV)
#else
  touch_pad_intr_disable();
#endif

  xMsgSemaphore = xSemaphoreCreateBinaryStatic(&xMsgSemaphoreBuffer);
  xSemaphoreGive(xMsgSemaphore);

  xI2CSemaphore = xSemaphoreCreateBinaryStatic(&xI2CSemaphoreBuffer);
  xSemaphoreGive(xI2CSemaphore);

  WiFi.mode(WIFI_STA);  // explicitly set mode, esp defaults to STA+AP
  // НЕ используем WiFi.disconnect(true) здесь, так как это может очистить сохраненные креденшалы
  // Вместо этого просто отключаемся без очистки сохраненных данных
  WiFi.disconnect(false);
  delay(50);
  WiFi.setSleep(false);
  WiFi.setHostname(host);
  WiFi.setAutoReconnect(true);

  Wire.begin(LCD_SDA, LCD_SCL);
  //Wire.begin();

  lcd_found = (check_I2C_device(LCD_ADDRESS) == LCD_ADDRESS);

  stepper.disable();

  WFtotalMilliLitres = 0;

  // Configure the Prescaler at 80 the quarter of the ESP32 is cadence at 80Mhz
  // 80000000 / 80 = 1000000 tics / seconde
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timer = timerBegin(1000000);
  timerAttachInterrupt(timer, &StepperTicker);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timer = timerBegin(2, 80, true);
  timerAttachInterrupt(timer, &StepperTicker, true);
#endif

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

#ifdef SERVO_PIN
  servo.setPeriodHertz(50);  // standard 50 hz servo
  // Частоты 500 и 2500 - подобраны для моего серво-привода. Возможно, для других частоты могут отличаться
  // 544 и 2400 - стандартные частоты
  servo.attach(SERVO_PIN, 500, 2500);  // attaches the servo
#endif

  //Читаем сохраненную конфигурацию
  //read_config();

  // Инициализация кнопок и энкодера (обработка в loop())
#ifdef BTN_PIN
  btn.setType(LOW_PULL);
  btn.setTickMode(AUTO);
  btn.setDebounce(30);
#endif

#ifdef ALARM_BTN_PIN
  alarm_btn.setType(HIGH_PULL);
  alarm_btn.setTickMode(AUTO);
  alarm_btn.setDebounce(30);
#endif

  //Если при старте нажата кнопка - Самовар запустится в режиме AP
  bool wifiAP = false;
#ifdef BTN_PIN
  btn.tick();  // отработка нажатия
  if (btn.isPress()) {
    wifiAP = true;
    vTaskDelay(2000);
  }
#endif

  //Читаем сохраненную конфигурацию
  
  // Сначала мигрируем старые настройки из EEPROM (если они есть)
  //reset_migration_flag(); // ТОЛЬКО ДЛЯ ТЕСТА! Удалить после проверки!
  migrate_from_eeprom();
  
  // Затем загружаем из NVS
  read_config();
  
  Serial.print("NVS: Configuration loaded. Flag = ");
  Serial.println(SamSetup.flag);

  // Если NVS пустой (flag > 250), инициализируем дефолтными значениями
  if (SamSetup.flag > 250) {
    Serial.println("NVS is empty. Initializing with default values...");
    SamSetup.flag = 2;
    SamSetup.DeltaSteamTemp = 0.1;
    SamSetup.DeltaPipeTemp = 0.2;
    SamSetup.DeltaWaterTemp = 0;
    SamSetup.DeltaTankTemp = 0;
    SamSetup.DeltaACPTemp = 0;
    SamSetup.SetSteamTemp = 0;
    SamSetup.SetPipeTemp = 0;
    SamSetup.SetWaterTemp = 0;
    SamSetup.SetTankTemp = 0;
    SamSetup.SetACPTemp = 0;
    SamSetup.StepperStepMl = STEPPER_STEP_ML;
    SamSetup.StepperStepMlI2C = I2C_STEPPER_STEP_ML_DEFAULT;
    SamSetup.UsePreccureCorrect = true;
    SamSetup.SteamDelay = 20;
    SamSetup.PipeDelay = 20;
    SamSetup.WaterDelay = 20;
    SamSetup.TankDelay = 20;
    SamSetup.ACPDelay = 20;
    SamSetup.HeaterResistant = 15.2;
    SamSetup.LogPeriod = 3;
    SamSetup.TimeZone = 3;
    SamSetup.blynkauth[0] = '\0';
    SamSetup.videourl[0] = '\0';
    SamSetup.UseWS = 1;
    SamSetup.ColDiam = 2.0f;
    SamSetup.ColHeight = 0.5f;
    SamSetup.PackDens = 80;
    save_profile();
    Serial.println("Default values saved to NVS");
  }

  //Инициализируем ноги для реле
  pinMode(RELE_CHANNEL1, OUTPUT);
  digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
  pinMode(RELE_CHANNEL2, OUTPUT);
  digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  pinMode(RELE_CHANNEL3, OUTPUT);
  digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  pinMode(RELE_CHANNEL4, OUTPUT);
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);

#ifdef USE_WATER_VALVE
  pinMode(WATER_PUMP_PIN, OUTPUT);
  digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
#endif

  //Инициализируем ногу для пищалки
  pinMode(BZZ_PIN, OUTPUT);
  digitalWrite(BZZ_PIN, LOW);

#ifdef USE_PRESSURE_MPX
  //Инициализируем ногу для датчика давления MPX5010D
  pinMode(LUA_PIN, INPUT);
#endif

  //Настраиваем меню
  Serial.println(F("Samovar started"));
  setupMenu();
  writeString(F("      Samovar "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  //delay(2000);
  writeString(F("Connecting to WI-FI"), 3);

  //Serial.print("Reset reason: ");
  //Serial.println(vr);
  for (uint8_t i = 0; i < 17; i = i + 8) {
    chipId |= ((ESP.getEfuseMac() >> (40 - i)) & 0xff) << i;
  }
  //uint8_t *MAC = ESP.getEfuseMac();
  //Serial.printf("%02x%02x%02x%02x%02x%02x\n", MAC[5], MAC[4], MAC[3], MAC[2], MAC[1], MAC[0]);

  Serial.printf("ESP32 Chip model = %s Rev %d\n", ESP.getChipModel(), ESP.getChipRevision());
  //Serial.printf("This chip has %d cores\n", ESP.getChipCores());
  Serial.print("Chip ID: ");
  Serial.println(chipId);

  String StIP;
  //esp_wifi_set_ps( WIFI_PS_NONE );

  auto start_ap = [&]() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("Samovar"); // Без пароля для удобства подключения к странице настройки WiFi
    StIP = WiFi.softAPIP().toString();
    Serial.println(F("Started as WiFi AP"));
  };

  if (!wifiAP) {
    // пытаемся подключиться через WiFi.begin() без параметров - ESP32 автоматически использует сохраненные креденшалы, если они есть
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);  // Отключаемся, но не очищаем сохраненные креденшалы
    
    Serial.println(F("Attempting to connect to saved WiFi..."));
    WiFi.begin();  // Пытаемся подключиться к сохраненной сети

    uint32_t startMs = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - startMs) < 15000) {
      delay(250);
      Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
      StIP = WiFi.localIP().toString();
      Serial.print(F("Connected to "));
      Serial.print(WiFi.SSID());
      Serial.print(F(" - IP: "));
      Serial.println(StIP);
    } else {
      Serial.println(F("Failed to connect to saved WiFi. Starting AP mode..."));
      wifiAP = true;
      start_ap();
    }
  } else {
    start_ap();
  }

  Serial.print(F("IP address: "));
  copyStringSafe(ipst, StIP);

  Serial.println(StIP);

  if (!MDNS.begin(host)) {  //http://samovar.local
    Serial.println(F("Error setting up MDNS responder!"));
  } else {
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("mDNS responder started"));
#endif
  }

  //connectWiFi();
  writeString(F("Connected"), 4);

#ifdef SAMOVAR_USE_BLYNK
  if (SamSetup.blynkauth[0] != 0 && !wifiAP) {
    //Blynk.begin(auth, ssid, password);
    writeString(F("Connecting to Blynk "), 3);
    writeString(F("               "), 4);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Connecting to Blynk"));
#endif
#ifdef BLYNK_SAMOVAR_TOOL
    Blynk.config(SamSetup.blynkauth, BLYNK_SAMOVAR_TOOL, 8080);
#else
    Blynk.config(SamSetup.blynkauth);
#endif
    Blynk.connect(BLYNK_TIMEOUT_MS);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Blynk started"));
#endif
  }
#endif

#ifdef USE_TELEGRAM
  if (WiFi.status() == WL_CONNECTED && SamSetup.tg_token[0] != 0 && SamSetup.tg_chat_id[0] != 0) {
    vTaskDelay(5 / portTICK_PERIOD_MS);
    http_sync_request_get(String("http://212.237.16.93/bot") + SamSetup.tg_token + "/sendMessage?chat_id=" + SamSetup.tg_chat_id + "&text=" + urlEncode("Самовар готов к работе; IP=http://" + StIP));
  } else if (SamSetup.tg_chat_id[0] != 0) {
    Serial.println(F("Проблема с покдлючением к интернету."));
  }
#endif

#ifdef USE_UPDATE_OTA
  //Send OTA events to the browser
  ArduinoOTA.onStart([]() {
    ota_running = true;  // Устанавливаем флаг активного OTA обновления
    String type;
    if (ArduinoOTA.getCommand() == U_FLASH)
      type = "Sketch";
    else {  // U_SPIFFS
      type = "Filesystem";
      SPIFFS.end();
    }
    type = type + " update start";
    events.send(type.c_str(), "ota");
    
    // Отключаем другие сервисы для освобождения ресурсов
#ifdef SAMOVAR_USE_BLYNK
    if (Blynk.connected()) {
      Blynk.disconnect();
    }
#endif
#ifdef USE_MQTT
    if (mqttClient.connected()) {
      mqttClient.disconnect();
    }
#endif
  });
  ArduinoOTA.onEnd([]() {
    ota_running = false;  // Сбрасываем флаг после завершения
    events.send(("Update End"), "ota");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    char p[32];
    const uint32_t percent = (total > 0) ? (progress * 100U) / total : 0U;
    strcpy(p, "Progress: ");
    ultoa(percent, p + strlen(p), 10);
    strcat(p, "%\n");
    events.send(p, "ota");
    yield();  // Даем возможность другим задачам выполниться
  });
  ArduinoOTA.onError([](ota_error_t error) {
    ota_running = false;  // Сбрасываем флаг при ошибке
    if (error == OTA_AUTH_ERROR) events.send("Auth Failed", "ota");
    else if (error == OTA_BEGIN_ERROR)
      events.send(("Begin Failed"), "ota");
    else if (error == OTA_CONNECT_ERROR)
      events.send(("Connect Failed"), "ota");
    else if (error == OTA_RECEIVE_ERROR)
      events.send(("Recieve Failed"), "ota");
    else if (error == OTA_END_ERROR)
      events.send(("End Failed"), "ota");
  });
  ArduinoOTA.setHostname(SAMOVAR_HOST);
  // Увеличиваем таймауты для более стабильной передачи
  ArduinoOTA.setTimeout(30000);  // 30 секунд на операцию (по умолчанию 10)
  ArduinoOTA.begin();
#endif

  alarm_event = false;

  sensor_init();

  startService();
  samovar_reset();

  WebServerInit();
  
#ifdef USE_CRASH_HANDLER
  // Инициализация обработчика сбоев (после инициализации файловой системы)
  init_crash_handler();
#endif

#ifdef SAMOVAR_USE_POWER
  //Запускаем таск считывания параметров регулятора
  xTaskCreatePinnedToCore(
    triggerPowerStatus, /* Function to implement the task */
    "PowerStatusTask",  /* Name of the task */
    1800,               /* Stack size in words */
    NULL,               /* Task input parameter */
    1,                  /* Priority of the task */
    &PowerStatusTask,   /* Task handle. */
    0);                 /* Core where the task should run */
  //На всякий случай пошлем команду выключения питания на UART
  set_power_mode(POWER_SLEEP_MODE);
#endif

#ifdef USE_WEB_SERIAL
  WebSerial.begin(&server);
  WebSerial.onMessage(recvMsg);
#endif

#ifdef USE_WATERSENSOR
  //вешаем прерывание на изменения датчика потока воды
  attachInterrupt(WATERSENSOR_PIN, WFpulseCounter, FALLING);
#endif

#ifdef USE_HEAD_LEVEL_SENSOR
  //Задаем параметры для сенсора уровня флегмы
#ifdef WHLS_HIGH_PULL
  whls.setType(HIGH_PULL);
#else
  whls.setType(LOW_PULL);
#endif

  whls.setDebounce(50);  //игнорируем дребезг
  whls.setTickMode(MANUAL);
  whls.setTimeout(WHLS_ALARM_TIME * 1000);  //время, через которое сработает тревога по уровню флегмы
  //вешаем прерывание на изменение датчика уровня флегмы
  attachInterrupt(WHEAD_LEVEL_SENSOR_PIN, isrWHLS_TICK, CHANGE);
#endif

#ifdef USE_MQTT
  if (!wifiAP) {
    initMqtt();
    vTaskDelay(500);
  }
#endif

  //WiFi.hostByName(ntpServerName, timeServerIP);

  //Запускаем таск для получения температур и различных проверок
  xTaskCreatePinnedToCore(
    triggerSysTicker, /* Function to implement the task */
    "SysTicker",      /* Name of the task */
    3200,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &SysTickerTask1,  /* Task handle. */
    0);               /* Core where the task should run */

  //Запускаем таск для получения точного времени и записи в лог
  xTaskCreatePinnedToCore(
    triggerGetClock,  /* Function to implement the task */
    "GetClockTicker", /* Name of the task */
    3400,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &GetClockTask1,   /* Task handle. */
    1);               /* Core where the task should run */

  //  //Запускаем таск для чтения давления
  //  xTaskCreatePinnedToCore(
  //    triggerGetBMP,      /* Function to implement the task */
  //    "GetBMPTicker",     /* Name of the task */
  //    1400,               /* Stack size in words */
  //    NULL,               /* Task input parameter */
  //    1,                  /* Priority of the task */
  //    &GetBMPTask,        /* Task handle. */
  //    0);                 /* Core where the task should run */

  //  //write reset reason
  //  if (!SPIFFS.exists("/resetreason.css")) {
  //    File f = SPIFFS.open("/resetreason.css", FILE_WRITE);
  //    f.close();
  //  }
  //  File f1 = SPIFFS.open("/resetreason.css", FILE_APPEND);
  //  f1.println(vr);
  //  f1.close();
  //  vr.replace(",",";");

  NTP.setTimeOffset(SamSetup.TimeZone * 3600);
  NTP.setUpdateInterval(1800000);//30 min
  NTP.begin(); 
  delay(100);
  // Принудительная синхронизация при старте с повторными попытками
  if (WiFi.status() == WL_CONNECTED) {
    int attempts = 0;
    while (!NTP.forceUpdate() && attempts < 2) {
      delay(500);
      attempts++;
    }
  }

#ifdef USE_LUA
  lua_init();
#endif

  writeString(F("      Samovar     "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  writeString(F("                  "), 3);
  writeString(F("      Started     "), 4);
  
  get_task_stack_usage();
  Serial.println("Samovar ready");
  
  use_I2C_dev = 0;

  if (check_I2C_device(1) == 1) {
    use_I2C_dev = 1;
    Serial.println("I2C Stepper as Mixer");
  }
  if (check_I2C_device(2) == 2) {
    use_I2C_dev = 2;
    Serial.println("I2C Stepper as Pump");
  }
  used_byte = SPIFFS.usedBytes();
  // verbose_print_reset_reason(); // Удалено, так как используется crash_handler
  //Serial.println(sizeof(SamSetup));

  SamovarStatus.reserve(80);
}

void loop() {
  // Проверка переполнения стека
  if (uxTaskGetStackHighWaterMark(NULL) < 325) {
    SendMsg("Стек переполнился. Перезагрузка", ALARM_MSG);
    vTaskDelay(5000);
    ESP.restart();
  }
  //пересчитаем время работы таймера для шагового двигателя
#ifdef USE_STEPPER_ACCELERATION
  portENTER_CRITICAL_ISR(&timerMux);
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timerAlarm(timer, stepper.getPeriod(), true, 0);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timerAlarmWrite(timer, stepper.getPeriod(), true);
#endif
  portEXIT_CRITICAL_ISR(&timerMux);
#endif  //USE_STEPPER_ACCELERATION

#ifdef USE_UPDATE_OTA
  ArduinoOTA.handle();
  // Во время OTA даем больше времени на обработку и чаще вызываем yield
  if (ota_running) {
    yield();
    delay(1);  // Небольшая задержка для стабильности передачи
  }
#endif

#ifdef SAMOVAR_USE_BLYNK
  // Отключаем Blynk во время OTA для освобождения ресурсов
  if (!ota_running && Blynk.connected()) {
    Blynk.run();
  }
#endif

  // Обработка кнопок и энкодера
#ifdef ALARM_BTN_PIN
  alarm_btn.tick();  // отработка нажатия аварийной кнопки
  if (alarm_btn.isPress()) {
    set_alarm();
  }
#endif

#ifdef BTN_PIN
  //обработка нажатий кнопки и разное поведение в зависимости от режима работы
  btn.tick();
  if (btn.isPress()) {
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      //если выключен - включаем
      if (!PowerOn) {
        set_power(true);
      } else if (startval == 0 && SamovarStatusInt < 1000) {
        //если включен и программа отбора не работает - запускаем программу
        menu_samovar_start();
      } else if (startval != 0 && !program_Pause && SamovarStatusInt < 1000) {
        //если выполняется программа, и программа - не пауза, ставим на паузу или снимаем с паузы
        pause_withdrawal(!PauseOn);
      } else if (startval != 0 && program_Pause && SamovarStatusInt < 1000) {
        //если выполняется программа, и программа - пауза, переходим к следующей программе
        menu_samovar_start();
      }
      //Выход из режима калибровки - нажатие на кнопку.
      if (startval == 100) {
        startval = 0;
        menu_calibrate();
        menu_switch_focus();
      }
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      //если дистилляция включаем или выключаем
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_DISTILLATION;
      } else
        distiller_finish();
    } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
      //если дистилляция включаем или выключаем
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_BK;
      } else
        bk_finish();
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      //если НБК включаем или выключаем
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_NBK;
      } else
        nbk_finish();
    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      //если пиво включаем или двигаем программу
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_BEER;
      } else
        run_beer_program(ProgramNum + 1);
    }
  }
#endif

  if (sam_command_sync != SAMOVAR_NONE) {
    switch (sam_command_sync) {
      case SAMOVAR_START:
        Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
        menu_samovar_start();
        break;
      case SAMOVAR_POWER:
        if (SamovarStatusInt == 1000) distiller_finish();
        else if (SamovarStatusInt == 2000)
          beer_finish();
        else if (SamovarStatusInt == 3000)
          bk_finish();
        else if (SamovarStatusInt == 4000)
          nbk_finish();
        else
          set_power(!PowerOn);
        if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
          SamovarStatusInt = 50;
        }
        break;
      case SAMOVAR_RESET:
        samovar_reset();
        break;
      case CALIBRATE_START:
        pump_calibrate(CurrrentStepperSpeed);
        break;
      case CALIBRATE_STOP:
        pump_calibrate(0);
        break;
      case SAMOVAR_PAUSE:
        pause_withdrawal(true);
        break;
      case SAMOVAR_CONTINUE:
        pause_withdrawal(false);
        t_min = 0;
        program_Wait = false;
        detector_on_manual_resume();
        break;
      case SAMOVAR_SETBODYTEMP:
        set_body_temp();
        break;
      case SAMOVAR_DISTILLATION:
        Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
        SamovarStatusInt = 1000;
        startval = 1000;
        break;
      case SAMOVAR_BEER:
        Samovar_Mode = SAMOVAR_BEER_MODE;
        SamovarStatusInt = 2000;
        startval = 2000;
        break;
      case SAMOVAR_BEER_NEXT:
        run_beer_program(ProgramNum + 1);
        break;
      case SAMOVAR_DIST_NEXT:
        run_dist_program(ProgramNum + 1);
        break;
      case SAMOVAR_BK:
        Samovar_Mode = SAMOVAR_BK_MODE;
        SamovarStatusInt = 3000;
        startval = 3000;
        break;
      case SAMOVAR_NBK:
        Samovar_Mode = SAMOVAR_NBK_MODE;
        SamovarStatusInt = 4000;
        startval = 4000;
        break;
      case SAMOVAR_NBK_NEXT:
        run_nbk_program(ProgramNum + 1);
        break;
      case SAMOVAR_SELF_TEST:
        start_self_test();
        break;
      case SAMOVAR_NONE:
        break;
    }
    if (sam_command_sync != SAMOVAR_RESET) {
      sam_command_sync = SAMOVAR_NONE;
    }
  }

  if (SamovarStatusInt > 0 && SamovarStatusInt < 1000) {
    withdrawal();  //функция расчета отбора
  } else if (SamovarStatusInt == 1000) {
    distiller_proc();  //функция для проведения дистилляции
  } else if (SamovarStatusInt == 3000) {
    bk_proc();  //функция для работы с БК
  } else if (SamovarStatusInt == 4000) {
    nbk_proc();  //функция для работы с НБК
  } else if (SamovarStatusInt == 2000 && startval == 2000) {
    beer_proc();  //функция для проведения затирания
  }

  // Обработка энкодера
  encoder.tick();
  encoder_getvalue();

  process_buzzer();
  vTaskDelay(5 / portTICK_PERIOD_MS);
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
