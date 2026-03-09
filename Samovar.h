#ifndef __SAMOVAR_H_
#define __SAMOVAR_H_

#define CONFIG_ASYNC_TCP_RUNNING_CORE 1      // force async_tcp task to be on same core as Arduino app (default is any core)
#define CONFIG_ASYNC_TCP_STACK_SIZE 4096     // reduce the stack size (default is 16K)

#ifndef ESP32
#error This code is designed to run on ESP32 platform, not Arduino nor ESP8266! Please check your Tools->Board setting.
#endif

#define SAMOVAR_VERSION F("6.27")

//#define __SAMOVAR_DEBUG

// Дефолтное значение для I2C шагов/мл (внешний насос)
#ifndef I2C_STEPPER_STEP_ML_DEFAULT
#define I2C_STEPPER_STEP_ML_DEFAULT 16000
#endif

#include <OneWire.h>
#include <DallasTemperature.h>
#include <ESPAsyncWebServer.h>
#include <ESP32Servo.h>
#include <PID_v1.h>
#include <PID_AutoTune_v0.h>
#include <iarduino_I2C_connect.h>
#include <GyverEncoder.h>
#include <GyverButton.h>
#include <ESPmDNS.h>
#include <LiquidMenu.h>

//определение поддерживаемых плат
#define DEVKIT 1
#define LILYGO 2
#define ESP32S3 3


#define BitIsSet(reg, bit) ((reg & (1<<bit)) != 0)

#ifdef __SAMOVAR_DEBUG
#ifndef USE_WEB_SERIAL
//#define USE_WEB_SERIAL                      //использовать библиотеку WebSerial для отладки
#endif
#endif

#define WRITE_PROGNUM_IN_LOG                 // писать в лог номер текущей строки программы

#include "Samovar_ini.h"

#include "user_config_override.h"

#ifndef USE_BODY_TEMP_AUTOSET
#define USE_BODY_TEMP_AUTOSET
#endif

#if ( defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3) )
//https://esp32.jgarrettcorbin.com/
//Если используется SDK >= 3 версии, отключаем использование OTA
#undef USE_UPDATE_OTA
#endif

#include "Samovar_pin.h"


#ifdef USE_PRESSURE_1WIRE
#undef USE_PRESSURE_XGZ
#endif

#ifdef USE_PRESSURE_MPX
#undef USE_PRESSURE_XGZ
#undef USE_PRESSURE_1WIRE
#endif

#ifndef SAM_NO_BEER_PRG
#define SAM_BEER_PRG
#endif

#ifdef USE_WEB_SERIAL
#include <WebSerial.h>
#endif

#ifdef USE_WATER_PUMP
#undef USE_WATER_VALVE
#endif

#ifdef BLYNK_SAMOVAR_TOOL
#ifndef SAMOVAR_USE_BLYNK
#define SAMOVAR_USE_BLYNK
#endif
#endif

#ifdef SAMOVAR_USE_SEM_AVR
#ifndef SAMOVAR_USE_RMVK
#define SAMOVAR_USE_RMVK
#endif
#endif

#ifndef USE_HEAD_LEVEL_SENSOR
#ifndef IGNORE_HEAD_LEVEL_SENSOR_SETTING
#define IGNORE_HEAD_LEVEL_SENSOR_SETTING
#endif
#endif

SemaphoreHandle_t xSemaphore = NULL;
SemaphoreHandle_t xMsgSemaphore = NULL;
StaticSemaphore_t xMsgSemaphoreBuffer;

SemaphoreHandle_t xI2CSemaphore = NULL;
StaticSemaphore_t xI2CSemaphoreBuffer;

#ifdef USE_BMP280_ALT
#undef USE_BMP180
#undef USE_BME280
#undef USE_BME680
#ifndef USE_BMP280
#define USE_BMP280
#endif
#endif

#define PWR_FACTOR 1

#ifdef SAMOVAR_USE_RMVK
#undef PWR_FACTOR
#define PWR_FACTOR 2
#ifndef SAMOVAR_USE_POWER
#define SAMOVAR_USE_POWER
#endif
#endif

#ifdef __cplusplus
extern "C" {
#endif

uint8_t temprature_sens_read();

#ifdef __cplusplus
}
#endif

uint8_t temprature_sens_read();

//#define __SAMOVAR_NOT_USE_WDT

//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------

//**************************************************************************************************************
// Режимы работы регулятора напряжения
#define POWER_WORK_MODE F("0")
#define POWER_SPEED_MODE F("1")
#define POWER_SLEEP_MODE F("2")
#define POWER_ERROR_MODE F("3")
//**************************************************************************************************************

#ifdef SAMOVAR_USE_SEM_AVR
#undef PWR_FACTOR
#define PWR_FACTOR 20
#define PWR_MSG F("Мощность")
#define PWR_TYPE F("P")
#define PWR_SIGN F("Вт")

SemaphoreHandle_t xSemaphoreAVR = NULL;
StaticSemaphore_t xSemaphoreBufferAVR;

#ifndef RMVK_DEFAULT_READ_TIMEOUT
#define RMVK_DEFAULT_READ_TIMEOUT 1100 // Таймаут по умолчанию (мс)
#endif
#ifndef RMVK_READ_DELAY
#define RMVK_READ_DELAY 300 // Задержка между запросами (мс)
#endif

#else
#ifdef SAMOVAR_USE_POWER
#define PWR_MSG F("Напряжение")
#define PWR_TYPE F("V")
#define PWR_SIGN F("В")
#else
#define PWR_MSG ""
#define PWR_TYPE ""
#endif
#endif

#ifndef SAMOVAR_USE_POWER_START_TIME
#define SAMOVAR_USE_POWER_START_TIME 2000
#endif

#ifndef LUA_BEER
#define LUA_BEER ""
#endif

#ifndef LUA_DIST
#define LUA_DIST ""
#endif

#ifndef LUA_BK
#define LUA_BK ""
#endif

#ifndef LUA_NBK
#define LUA_NBK ""
#endif

#ifndef LUA_RECT
#define LUA_RECT ""
#endif

#define USE_LittleFS

// Флаг USE_CRASH_HANDLER теперь берется из user_config_override.h

#ifdef USE_LittleFS
//#pragma message ("USE LITTLEFS")
#ifdef ESP_ARDUINO_VERSION
#include <LittleFS.h>
#define SPIFFS LittleFS
#else
#include <LITTLEFS.h>
#define SPIFFS LITTLEFS
#endif
#else
#pragma message ("USE SPIFFS")
#include <SPIFFS.h>
#endif

#include <FS.h>
#include <errno.h>
#include <stdlib.h>

#include "state/config_types.h"
#include "state/runtime_types.h"

void writeString(String Str, uint8_t num);
void WriteConsoleLog(String StringLogMsg);

// Ограничение длины входной строки программ перед парсингом
#ifndef MAX_PROGRAM_INPUT_LEN
#define MAX_PROGRAM_INPUT_LEN 1024
#endif

template <size_t N>
inline void copyStringSafe(char (&dst)[N], const String& src) {
  size_t n = src.length();
  if (n >= N) n = N - 1;
  if (n > 0) {
    memcpy(dst, src.c_str(), n);
  }
  dst[n] = '\0';
}

inline bool parseLongSafe(const char* token, long& out) {
  if (!token || token[0] == '\0') return false;
  errno = 0;
  char* end = nullptr;
  long value = strtol(token, &end, 10);
  if (errno != 0 || end == token || *end != '\0') return false;
  out = value;
  return true;
}

inline bool parseFloatSafe(const char* token, float& out) {
  if (!token || token[0] == '\0') return false;
  errno = 0;
  char* end = nullptr;
  float value = strtof(token, &end);
  if (errno != 0 || end == token || *end != '\0') return false;
  out = value;
  return true;
}

//**************************************************************************************************************
// Описание переменных
//**************************************************************************************************************

//**************************************************************************************************************
// Переменные для меню
uint8_t multiplier = 1;

extern char tst[20];
char ipst[16] = "000.000.000.000";
char welcomeStrArr1[20];
char welcomeStrArr2[20];
char welcomeStrArr3[20];
char welcomeStrArr4[20];
char* welcomeStr1 = (char*)welcomeStrArr1;
char* welcomeStr2 = (char*)welcomeStrArr2;
char* welcomeStr3 = (char*)welcomeStrArr3;
char* welcomeStr4 = (char*)welcomeStrArr4;

extern char* timestr;
char* ipstr = (char*)ipst;
char startval_text_val[20];
char* startval_text = (char*)startval_text_val;
char* power_text_ptr = (char*)"ON";
char* calibrate_text_ptr = (char*)"Start";
char* pause_text_ptr = (char*)"Pause";
String StrCrt;
String Crt;
uint8_t CurMin, OldMin;

//**************************************************************************************************************

/** Task handle for the  value read task */
TaskHandle_t SysTickerTask1 = NULL;
TaskHandle_t GetClockTask1 = NULL;
TaskHandle_t GetBMPTask = NULL;

// Переменные для управления пищалкой в основном цикле
volatile bool buzzer_active = false;     // Флаг активности пищалки
volatile uint8_t buzzer_beep_count = 0;  // Счетчик пищаний
volatile unsigned long buzzer_next_time = 0; // Время следующего изменения состояния
volatile bool buzzer_state = false;      // Текущее состояние пищалки (вкл/выкл)

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


#define DRIVER_STEP_TIME 4

#ifdef USE_STEPPER_ACCELERATION
#define GS_FAST_PROFILE 10
#else
#define GS_NO_ACCEL
#endif

#include <GyverStepper2.h>
GStepper2< STEPPER2WIRE> stepper(STEPPER_STEPS, STEPPER_STEP, STEPPER_DIR, STEPPER_EN);

iarduino_I2C_connect I2C2;

File fileToAppend;

#ifdef SERVO_PIN
Servo servo;  // create servo object to control a servo
#endif

#ifdef BTN_PIN
GButton btn(BTN_PIN);
#endif

#ifdef ALARM_BTN_PIN
GButton alarm_btn(ALARM_BTN_PIN);
#endif

#ifdef COLUMN_WETTING
#ifndef USE_HEAD_LEVEL_SENSOR
#undef COLUMN_WETTING
#endif
#endif

#ifdef USE_EXPANDER
#include <PCF8575.h>
PCF8575 expander(&Wire, USE_EXPANDER, LCD_SDA, LCD_SCL);
#endif

#ifdef USE_ANALOG_EXPANDER
#include "PCF8591.h"
PCF8591 analog_expander(&Wire, USE_ANALOG_EXPANDER, LCD_SDA, LCD_SCL);
#endif

double Input, Output, Setpoint;
double Kp, Ki, Kd;

//Relay relay(RELAY_PIN, RELAY_PERIOD);
PID heaterPID(&Input, &Output, &Setpoint, Kp, Ki, Kd, DIRECT);
int periodInSeconds = 6;

uint8_t ATuneModeRemember = 2;
double aTuneStep = 50;
double aTuneNoise = 1;
unsigned int aTuneLookBack = 9;
boolean tuning = false;

PID_ATune aTune(&Input, &Output);

#ifdef WHLS_HIGH_PULL
#ifndef USE_HEAD_LEVEL_SENSOR
#define USE_HEAD_LEVEL_SENSOR
#endif
#endif

#ifdef USE_HEAD_LEVEL_SENSOR
GButton whls(WHEAD_LEVEL_SENSOR_PIN);
#endif

GButton nbkls(LUA_PIN);

LiquidMenu main_menu1(lcd);

#ifdef USE_WEB_SERIAL
//WebSerialClass WebSerial;
#endif

// Wi-Fi креды (легковесная настройка без WiFiManager)
bool load_wifi_credentials(char *ssid, size_t ssid_len, char *pass, size_t pass_len);
String get_wifi_ssid();
void save_wifi_credentials(const char *ssid, const char *pass);
void clear_wifi_credentials();

volatile SamovarCommands sam_command_sync;                    // переменная для передачи команд между процессами

volatile SAMOVAR_MODE Samovar_Mode;
volatile SAMOVAR_MODE Samovar_CR_Mode;

volatile MESSAGE_TYPE msg_type;

SetupEEPROM SamSetup;
ImpurityDetector impurityDetector;

DSSensor SteamSensor;                                          //сенсор температуры пара вверху колонны
DSSensor PipeSensor;                                           //сенсор температуры в царге на 2/3 высоты
DSSensor WaterSensor;                                          //сенсор температуры охлаждающей воды или флегмы
DSSensor TankSensor;                                           //сенсор температуры в кубе
DSSensor ACPSensor;                                            //сенсор температуры в ТСА

WProgram program[30];                                          //массив строк для записи программы отбора.

//**************************************************************************************************************
const char* host = SAMOVAR_HOST;
// Константа испарения: ~4.8 мл/ч на 1 Вт мощности (для спирта 96%)
const float EVAPORATION_FACTOR = 4.8f;
//**************************************************************************************************************
uint8_t DScnt = 0;
uint8_t STcnt = 0;                                              // Счетчик для записи текущего статуса
//uint8_t tcnt = 0;
bool bmefound = true;
volatile bool PowerOn = false;                                  // Индикатор включенного питания
volatile bool PauseOn = false;                                  // Индикатор постановки отбора на паузу
volatile bool StepperMoving = false;                            // Индикатор движущегося шагового двигателя
volatile bool program_Pause;                                    // Признак, что запущена программа паузы
volatile bool program_Wait;                                     // Признак, что программа ожидает возврата колонны в заданные параметры
volatile bool heater_state;                                     // Статус нагрева при затирке
volatile bool loop_lua_fl = false;                              // Запускать lua скрипт в цикле
volatile bool show_lua_script = false;                          // Показывать выполняемый lua скрипт в логе и в Serial
volatile bool is_self_test;                                     // Находимся в режиме самотестирования
volatile bool SetScriptOff;                                     // Признак остановки Lua скрипта
bool boil_started;                                              // Флаг, определяющий, что кипение началось
bool valve_status;                                              // Состояние клапана подачи воды
bool pump_started;                                              // Признак стартовавшего насоса
bool msgfl;                                                     // Флаг для одноразовых сообщений
bool mixer_status;                                              // Статус работы мешалки
bool alarm_event;                                               // Признак срабатывания кнопки тревоги
bool acceleration_heater;                                       // Признак включенного разгонного тэна
bool send_mqtt;                                                 // Отправлять данные в облако
bool is_reboot = false;                                         // Признак перезагрузки
bool lcd_found = false;                                         // Признак наличия дисплея
bool wetting_autostart = false;                                 // Автостарт голов после смачивания
bool reg_online = false;                                        // Признак наличия связи с регулятором напряжения
volatile bool ota_running = false;                              // Флаг активного OTA обновления
unsigned long last_reg_online = 0;                              // Время последней связи с регулятором напряжения

//volatile float samovar_temp;                                  // Температура ESP32
volatile float bme_temp;                                        // Температура BME
volatile float start_pressure;                                  // Давление BME стартовое
volatile float bme_pressure;                                    // Давление BME
volatile float bme_prev_pressure;                               // Давление BME предыдущее значение
//float bme_humidity;                                           // Влажность
//float bme_altitude;                                           // Высота
//float bme_gas;                                                // Газ
String SamovarStatus;                                           // Текущий статус работы Самовара строкой
volatile int16_t SamovarStatusInt;                              // Текущий статус работы Самовара числом
volatile uint8_t capacity_num;                                  // Текущая позиция емкости для отбора

volatile uint8_t prev_ProgramNum;                               // Пердыдущая программа отбора
volatile uint8_t ProgramNum;                                    // Текущая программа отбора
volatile uint8_t ProgramLen;                                    // Количество строк программы отбора
volatile uint8_t WthdrwlProgress;                               // Прогресс текущего отбора
volatile int16_t startval = 0;                                  // Признак идущего отбора
volatile int currentstepcnt = 0;                                // Текущее количество шагов шагового двигателя
volatile unsigned long prev_time_ms;                            // Предыдущее время
volatile float ActualVolumePerHour;                             // Скорость отбора в литрах в моменте
volatile uint16_t CurrrentStepperSpeed;                         // Скорость шагового двигателя
volatile uint16_t I2CStepperSpeed;                              // Скорость шагового двигателя
volatile uint16_t I2CPumpCmdSpeed;                               // Скорость внешнего I2C насоса (шаг/сек)
volatile uint32_t I2CPumpTargetSteps;                            // Целевые шаги внешнего I2C насоса
volatile float I2CPumpTargetMl;                                  // Целевой объем внешнего I2C насоса, мл
volatile bool I2CPumpCalibrating;                                // Флаг калибровки внешнего I2C насоса
volatile unsigned int CurrrentStepps;                           // Количество пройденных степпером шагов
volatile unsigned int TargetStepps;                             // Количество шагов до нужного объема
String program_Wait_Type;                                       // Тип ожидания
unsigned long begintime;                                        // Время начала отбора
//unsigned long endtime;                                          // Время завершения отбора
unsigned long t_min;                                            // Время для паузы в секундах с момента старта ESP32
unsigned long alarm_t_min;                                      // Время для паузы в секундах для событий безопасности с момента старта ESP32
unsigned long alarm_h_min;                                      // Время для паузы в секундах для событий безопасности с момента старта ESP32
float d_s_temp_prev;                                            // Температура для определения начала кипения в режиме дистилляции
float d_s_temp_finish;                                          // Температура для определения завершения дистилляции
unsigned long d_s_time_min;                                     // Время для определения завершения дистилляции
float boil_temp;                                                // Температура куба, при которой началось кипение
float b_t_temp_prev;                                            // Температура для определения начала кипения
unsigned long b_t_time_min;                                     // Время для определения начала кипения
unsigned long b_t_time_delay;                                   // Задержка начала определения кипения
float alcohol_s;                                                // Спиртуозность, которая была при начале кипения
volatile uint16_t WFpulseCount = 0;                             // Счетчик для датчика потока
volatile uint16_t WFflowMilliLitres = 0;                        // Переменная для учета расхода воды
volatile uint32_t WFtotalMilliLitres = 0;                       // Переменная для учета расхода воды
volatile float WFflowRate;                                      // Переменная для учета расхода воды
volatile int WFAlarmCount;                                      // Переменная, считающая, сколько секунд не было подачи воды
uint16_t acceleration_temp;                                     // Счетчик для определения завершения разгона колонны
volatile float WthdrwTimeAll;                                   // Оставшееся время отбора
volatile float WthdrwTime;                                      // Время отбора текущей строки программы
String WthdrwTimeAllS;                                          // Оставшееся время отбора строкой
String WthdrwTimeS;                                             // Время отбора текущей строки программы строкой
String jsonstr;                                                 // Строка, содержащая json ответ для страницы
String Msg;                                                     // Строка для сообщений в web-интерфейсе
String LogMsg;                                                  // Строка для вывода лога в javascript console
uint8_t msg_level;                                              // Уровень сообщения - см. enum MESSAGE_TYPE
int bk_pwm;                                                     // Значение PWM насоса при работе с БК
uint32_t chipId = 0;                                            // Идентификатор ESP32
//String vr;                                                      // Причина перезагрузки ESP32
String SessionDescription;                                      // Описание параметров работы в свободном формате для сохранения в облаке
volatile float test_num_val;                                    // Тестовое численное значение
float pressure_value;                                           // Давление от датчика давления
float old_pressure_value ;                                      // старое давление для усреднения
bool use_pressure_sensor;                                       // Использовать датчик давления (по результатам инициализации)

// Переменные для расширенного логирования и анализа (п. 5)
volatile float BoilerVolume = 30.0f;     // Объем залитого сырья, л (дефолт 30л)
volatile float CurrentHeatLoss = 0;      // Вычисленные теплопотери, Вт
volatile float CalculatedTargetFR = 0;    // Текущее целевое ФЧ
unsigned long heatStartMillis = 0;        // Время старта замера (при 40°C)
float heatStartTemp = 0;                  // Температура старта замера
bool heatLossCalculated = false;          // Флаг завершения расчета

String test_str_val;                                            // Тестовое строковое значение
String Lua_status;                                              // Статус Lua
uint32_t total_byte;                                            // Доступно байт на файловой системе
uint32_t used_byte;                                             // Использовано байт на файловой системе
uint8_t use_I2C_dev;                                            // Использовать Nano, подключенную по I2C для управления шаговым двигателем мешалки и насосом (основное назначение - пиво)
uint16_t water_pump_speed;                                      // Скорость насоса

String current_power_mode;                                      // Режим работы регулятора напряжения
volatile float target_power_volt = 0;                           // Заданное напряжение регулятора
volatile float current_power_volt = 0;                          // Текущее напряжение регулятора
unsigned long alarm_c_min;                                      // Время для ожидания возврата к заданному напряжению-1 Вольт для режима предзахлеба в секундах с момента старта ESP32
unsigned long alarm_c_low_min;                                  // Время для ожидания возврата к заданному напряжению-1 Вольт для режима предзахлеба в секундах с момента старта ESP32

#ifdef SAMOVAR_USE_POWER
volatile float prev_target_power_volt;                          // Предыдущее заданное напряжение регулятора
volatile uint16_t current_power_p;                              // Расчитанная мощность на регуляторе напряжения
uint8_t power_err_cnt;                                          // Счетчик ошибок по напряжению/мощности
#define TIME_C 4                                                // Время ожидания в минутах для программы режима предзахлеба
#endif

#ifdef USE_WATER_PUMP
uint8_t wp_count;                                               // Переменная для расчета времени работы насоса на повышенной мощности при старте
#endif

// Глобальная функция остановки процесса
void stop_process(String reason);

#ifdef USE_MQTT
void MqttSendMsg(const String &Str, const char *chart, int version = 3);
#endif

#endif
