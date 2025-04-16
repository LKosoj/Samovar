#ifndef __SAMOVAR_H_
#define __SAMOVAR_H_

#ifndef ESP32
#error This code is designed to run on ESP32 platform, not Arduino nor ESP8266! Please check your Tools->Board setting.
#endif

#define SAMOVAR_VERSION F("6.23")

//#define __SAMOVAR_DEBUG

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

static SemaphoreHandle_t xSemaphore = NULL;
static SemaphoreHandle_t xMsgSemaphore = NULL;
static StaticSemaphore_t xMsgSemaphoreBuffer;

static SemaphoreHandle_t xI2CSemaphore = NULL;
static StaticSemaphore_t xI2CSemaphoreBuffer;

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

static SemaphoreHandle_t xSemaphoreAVR = NULL;
static StaticSemaphore_t xSemaphoreBufferAVR;

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

void writeString(String Str, uint8_t num);
void WriteConsoleLog(String StringLogMsg);

//**************************************************************************************************************
// Описание переменных
//**************************************************************************************************************

//**************************************************************************************************************
// Переменные для меню
static uint8_t multiplier = 1;

static char tst[20] = "00:00:00   00:00:00";
static char ipst[16] = "000.000.000.000";
static char welcomeStrArr1[20];
static char welcomeStrArr2[20];
static char welcomeStrArr3[20];
static char welcomeStrArr4[20];
static char* welcomeStr1 = (char*)welcomeStrArr1;
static char* welcomeStr2 = (char*)welcomeStrArr2;
static char* welcomeStr3 = (char*)welcomeStrArr3;
static char* welcomeStr4 = (char*)welcomeStrArr4;

static char* timestr = (char*)tst;
static char* ipstr = (char*)ipst;
static char startval_text_val[20];
static char* startval_text = (char*)startval_text_val;
static char* power_text_ptr = (char*)"ON";
static char* calibrate_text_ptr = (char*)"Start";
static char* pause_text_ptr = (char*)"Pause";
static String StrCrt;
static String Crt;
static uint8_t CurMin, OldMin;

//**************************************************************************************************************

/** Task handle for the  value read task */
static TaskHandle_t SysTickerButton = NULL;
static TaskHandle_t SysTickerTask1 = NULL;
static TaskHandle_t GetClockTask1 = NULL;
static TaskHandle_t BuzzerTask = NULL;
static TaskHandle_t GetBMPTask = NULL;
static volatile bool BuzzerTaskFl;

#ifdef SAMOVAR_USE_POWER
static TaskHandle_t PowerStatusTask = NULL;
#endif

static AsyncWebServer server(80);

static AsyncWebSocket ws("/ws");
static AsyncEventSource events("/events");

static OneWire oneWire(ONE_WIRE_BUS);
static DallasTemperature sensors(&oneWire);
static DeviceAddress DSAddr[6];

static LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLUMNS, LCD_ROWS);

static Encoder encoder(ENC_CLK, ENC_DT, ENC_SW, TYPE2);


#define DRIVER_STEP_TIME 4

#ifdef USE_STEPPER_ACCELERATION
#define GS_FAST_PROFILE 10
#else
#define GS_NO_ACCEL
#endif

#include <GyverStepper2.h>
#include <DNSServer.h>
static GStepper2< STEPPER2WIRE> stepper(STEPPER_STEPS, STEPPER_STEP, STEPPER_DIR, STEPPER_EN);

static iarduino_I2C_connect I2C2;

static File fileToAppend;

#ifdef SERVO_PIN
static Servo servo;  // create servo object to control a servo
#endif

#ifdef BTN_PIN
static GButton btn(BTN_PIN);
#endif

#ifdef ALARM_BTN_PIN
static GButton alarm_btn(ALARM_BTN_PIN);
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

static double Input, Output, Setpoint;
static double Kp, Ki, Kd;

//Relay relay(RELAY_PIN, RELAY_PERIOD);
static PID heaterPID(&Input, &Output, &Setpoint, Kp, Ki, Kd, DIRECT);
static int periodInSeconds = 6;

static uint8_t ATuneModeRemember = 2;
static double aTuneStep = 50;
static double aTuneNoise = 1;
static unsigned int aTuneLookBack = 9;
static boolean tuning = false;

static PID_ATune aTune(&Input, &Output);

#ifdef WHLS_HIGH_PULL
#ifndef USE_HEAD_LEVEL_SENSOR
#define USE_HEAD_LEVEL_SENSOR
#endif
#endif

#ifdef USE_HEAD_LEVEL_SENSOR
static GButton whls(WHEAD_LEVEL_SENSOR_PIN);
#endif

static GButton nbkls(LUA_PIN);

static LiquidMenu main_menu1(lcd);

#ifdef USE_WEB_SERIAL
//WebSerialClass WebSerial;
#endif

static DNSServer dns;

enum SamovarCommands {SAMOVAR_NONE, SAMOVAR_START, SAMOVAR_POWER, SAMOVAR_RESET, CALIBRATE_START, CALIBRATE_STOP, SAMOVAR_PAUSE, SAMOVAR_CONTINUE, SAMOVAR_SETBODYTEMP, SAMOVAR_DISTILLATION, SAMOVAR_BEER, SAMOVAR_BEER_NEXT, SAMOVAR_BK, SAMOVAR_NBK, SAMOVAR_SELF_TEST, SAMOVAR_DIST_NEXT, SAMOVAR_NBK_NEXT};
static volatile SamovarCommands sam_command_sync;                    // переменная для передачи команд между процессами

enum SAMOVAR_MODE {SAMOVAR_RECTIFICATION_MODE, SAMOVAR_DISTILLATION_MODE, SAMOVAR_BEER_MODE, SAMOVAR_BK_MODE, SAMOVAR_NBK_MODE, SAMOVAR_SUVID_MODE, SAMOVAR_LUA_MODE};
static volatile SAMOVAR_MODE Samovar_Mode;
static volatile SAMOVAR_MODE Samovar_CR_Mode;

enum MESSAGE_TYPE {ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, NONE_MSG = 100};
static volatile MESSAGE_TYPE msg_type;

enum get_web_type {GET_CONTENT, SAVE_FILE_OVERRIDE, SAVE_FILE_IF_NOT_EXIST};

struct SetupEEPROM {
  uint8_t flag;                                                //Флаг для записи в память
  float DeltaSteamTemp;                                        //Корректировка температурного датчика
  float DeltaPipeTemp;                                         //Корректировка температурного датчика
  float DeltaWaterTemp;                                        //Корректировка температурного датчика
  float DeltaTankTemp;                                         //Корректировка температурного датчика
  uint16_t StepperStepMl;                                      //Количество шагов шагового двигателя на мл. жидкости
  float SetSteamTemp;                                          //Уставка температурного датчика
  float SetPipeTemp;                                           //Уставка температурного датчика
  float SetWaterTemp;                                          //Уставка температурного датчика
  float SetTankTemp;                                           //Уставка температурного датчика
  bool UsePreccureCorrect;                                     //Использовать корректировку температуры отбора тела при изменении давления
  uint16_t SteamDelay;                                         //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  uint16_t PipeDelay;                                          //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  uint16_t WaterDelay;                                         //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  uint16_t TankDelay;                                          //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  uint8_t TimeZone;                                            //Таймзона того места, где будет применяться устройство
  float HeaterResistant;                                       //Сопротивление тэна для расчета мощности
  uint8_t LogPeriod;                                           //Периодичность записи данных о температуре в файл (раз в три секунды, оптимально с точки зрения объема файла). Если прогнозируемое время работы Самовара больше суток - лучше период установить раз в 5-10 секунд.
  char SteamColor[20];                                         //Цвета температур в интерфейсе
  char PipeColor[20];
  char WaterColor[20];
  char TankColor[20];
  bool rele1;                                                  //Уровни для реле
  bool rele2;
  bool rele3;
  bool rele4;
  uint8_t SteamAdress[8];                                      //адреса датчиков температуры
  uint8_t PipeAdress[8];
  uint8_t WaterAdress[8];
  uint8_t TankAdress[8];
  bool useautospeed;                                           //Настройка для использования автокорректировки скорости
  uint8_t autospeed;                                           //Процент изменения скорости
  char blynkauth[33];
  char videourl[120];                                          //URL для потокового видео с камеры
  float DistTemp;                                              //Температура, при которой завершится дистилляция
  int Mode;                                                    //Режим работы Самовара
  uint8_t ACPAdress[8];                                        //адрес датчиков температуры
  char ACPColor[20];                                           //Цвет температуры в интерфейсе
  float DeltaACPTemp;                                          //Корректировка температурного датчика
  float SetACPTemp;                                            //Уставка температурного датчика
  uint16_t ACPDelay;                                           //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  float Kp;                                                    //Коэффициенты для PID-регулятора нагрева
  float Ki;
  float Kd;
  float StbVoltage;                                            //Напряжение регулятора в режиме поддержания температуры
  bool useautopowerdown;                                       //Настройка для использования автокорректировки подводимой мощности
  bool ChangeProgramBuzzer;                                    //Настройка для использования пищалки при смене программы
  bool UseBuzzer;                                              //Настройка для использования пищалки
  bool CheckPower;                                             //Параметр для контроля работы регулятора напряжения (если он подключен)
  bool UseBBuzzer;                                             //Настройка для использования пищалки в браузере
  bool UseWS;                                                  //Настройка использования датчика протока воды
  float BVolt;                                                 //Напряжение/мощность в режиме кипения
  bool UseST;                                                  //Настройка использования разгонного тэна в режиме кипения
  uint8_t DistTimeF;                                           //Время в минутах для контроля завершения процесса дистилляции
  bool UseHLS;                                                 //Использовать датчик флегмы
  float MaxPressureValue;                                      //Максимальное давление, при котором сработает аварийный режим
  char tg_token[50];                                           //Токен Телеграм-бота
  char  tg_chat_id[14];                                        //Идентификатор чата Телеграм
  //Serial.println(sizeof(SamSetup));
};

struct DSSensor {
  DeviceAddress Sensor;                                        //адрес датчика температуры
  float avgTemp;                                               //средняя температура с датчика
  float SetTemp;                                               //уставка по температуре, при достижении которой требуется реакция
  float BodyTemp;                                              //температура, с которой начался отбор тела
  uint16_t Delay;                                              //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  float PrevTemp;                                              //Предыдущая температура
  float Start_Pressure;                                        //Стартовое давление при начале отбора
  int ErrCount;                                                //Счетчик ошибок для оповещения о не возможности провести чтение с датчика
  float LogPrevTemp;                                           //Хранение предыдущей температуры для записи лога
  float StartProgTemp;                                         //Хранение температуры, которая была на начало строки программы
};

struct WProgram {
  String WType;                                                //тип отбора - головы или тело
  uint16_t Volume;                                             //объем отбора в мл
  float Speed;                                                 //скорость отбора в л/ч
  uint8_t capacity_num;                                        //номер емкости для отбора
  float Temp;                                                  //температура, при которой отбирается эта часть погона. 0 - определяется автоматически
  uint16_t Power;                                              //напряжение, при которой отбирается эта часть погона.
  uint8_t TempSensor;                                          //температурный сенсор, используемый в программе Пиво для контроля нагрева
  float Time;                                                  //время, необходимое для отбора программы
};

static SetupEEPROM SamSetup;

static DSSensor SteamSensor;                                          //сенсор температуры пара вверху колонны
static DSSensor PipeSensor;                                           //сенсор температуры в царге на 2/3 высоты
static DSSensor WaterSensor;                                          //сенсор температуры охлаждающей воды или флегмы
static DSSensor TankSensor;                                           //сенсор температуры в кубе
static DSSensor ACPSensor;                                            //сенсор температуры в ТСА

static WProgram program[30];                                          //массив строк для записи программы отбора.

//**************************************************************************************************************
static const char* host = SAMOVAR_HOST;

//**************************************************************************************************************
static uint8_t DScnt = 0;
static uint8_t STcnt = 0;                                              // Счетчик для записи текущего статуса
//uint8_t tcnt = 0;
static bool bmefound = true;
static volatile bool PowerOn = false;                                  // Индикатор включенного питания
static volatile bool PauseOn = false;                                  // Индикатор постановки отбора на паузу
static volatile bool StepperMoving = false;                            // Индикатор движущегося шагового двигателя
static volatile bool program_Pause;                                    // Признак, что запущена программа паузы
static volatile bool program_Wait;                                     // Признак, что программа ожидает возврата колонны в заданные параметры
static volatile bool heater_state;                                     // Статус нагрева при затирке
static volatile bool loop_lua_fl;                                      // Запускать lua скрипт в цикле
static volatile bool show_lua_script;                                  // Показывать выполняемый lua скрипт в логе и в Serial
static volatile bool is_self_test;                                     // Находимся в режиме самотестирования
static volatile bool SetScriptOff;                                     // Признак остановки Lua скрипта
static bool boil_started;                                              // Флаг, определяющий, что кипение началось
static bool valve_status;                                              // Состояние клапана подачи воды
static bool pump_started;                                              // Признак стартовавшего насоса
static bool setautospeed;                                              // Признак для однократного снижения скорости насоса при паузе
static bool msgfl;                                                     // Флаг для одноразовых сообщений
static bool mixer_status;                                              // Статус работы мешалки
static bool alarm_event;                                               // Признак срабатывания кнопки тревоги
static bool acceleration_heater;                                       // Признак включенного разгонного тэна
static bool send_mqtt;                                                 // Отправлять данные в облако
static bool is_reboot = false;                                         // Признак перезагрузки

//volatile float samovar_temp;                                  // Температура ESP32
static volatile float bme_temp;                                        // Температура BME
static volatile float start_pressure;                                  // Давление BME стартовое
static volatile float bme_pressure;                                    // Давление BME
static volatile float bme_prev_pressure;                               // Давление BME предыдущее значение
//float bme_humidity;                                           // Влажность
//float bme_altitude;                                           // Высота
//float bme_gas;                                                // Газ
static String SamovarStatus;                                           // Текущий статус работы Самовара строкой
static volatile int16_t SamovarStatusInt;                              // Текущий статус работы Самовара числом
static volatile uint8_t capacity_num;                                  // Текущая позиция емкости для отбора

static volatile uint8_t prev_ProgramNum;                               // Пердыдущая программа отбора
static volatile uint8_t ProgramNum;                                    // Текущая программа отбора
static volatile uint8_t ProgramLen;                                    // Количество строк программы отбора
static volatile uint8_t WthdrwlProgress;                               // Прогресс текущего отбора
static volatile int16_t startval = 0;                                  // Признак идущего отбора
static volatile int currentstepcnt = 0;                                // Текущее количество шагов шагового двигателя
static volatile unsigned long prev_time_ms;                            // Предыдущее время
static volatile float ActualVolumePerHour;                             // Скорость отбора в литрах в моменте
static volatile uint16_t CurrrentStepperSpeed;                         // Скорость шагового двигателя
static volatile uint16_t I2CStepperSpeed;                              // Скорость шагового двигателя
static volatile unsigned int CurrrentStepps;                           // Количество пройденных степпером шагов
static volatile unsigned int TargetStepps;                             // Количество шагов до нужного объема
static String program_Wait_Type;                                       // Тип ожидания
static unsigned long begintime;                                        // Время начала отбора
//unsigned long endtime;                                          // Время завершения отбора
static unsigned long t_min;                                            // Время для паузы в секундах с момента старта ESP32
static unsigned long alarm_t_min;                                      // Время для паузы в секундах для событий безопасности с момента старта ESP32
static unsigned long alarm_h_min;                                      // Время для паузы в секундах для событий безопасности с момента старта ESP32
static float d_s_temp_prev;                                            // Температура для определения начала кипения в режиме дистилляции
static float d_s_temp_finish;                                          // Температура для определения завершения дистилляции
static unsigned long d_s_time_min;                                     // Время для определения завершения дистилляции
static float boil_temp;                                                // Температура куба, при которой началось кипение
static float b_t_temp_prev;                                            // Температура для определения начала кипения
static unsigned long b_t_time_min;                                     // Время для определения начала кипения
static unsigned long b_t_time_delay;                                   // Задержка начала определения кипения
static float alcohol_s;                                                // Спиртуозность, которая была при начале кипения
static volatile uint16_t WFpulseCount = 0;                             // Счетчик для датчика потока
static volatile uint16_t WFflowMilliLitres = 0;                        // Переменная для учета расхода воды
static volatile uint16_t WFtotalMilliLitres = 0;                       // Переменная для учета расхода воды
static volatile float WFflowRate;                                      // Переменная для учета расхода воды
static volatile int WFAlarmCount;                                      // Переменная, считающая, сколько секунд не было подачи воды
static uint16_t acceleration_temp;                                     // Счетчик для определения завершения разгона колонны
static volatile float WthdrwTimeAll;                                   // Оставшееся время отбора
static volatile float WthdrwTime;                                      // Время отбора текущей строки программы
static String WthdrwTimeAllS;                                          // Оставшееся время отбора строкой
static String WthdrwTimeS;                                             // Время отбора текущей строки программы строкой
static String jsonstr;                                                 // Строка, содержащая json ответ для страницы
static String Msg;                                                     // Строка для сообщений в web-интерфейсе
static String LogMsg;                                                  // Строка для вывода лога в javascript console
static uint8_t msg_level;                                              // Уровень сообщения - см. enum MESSAGE_TYPE
static int bk_pwm;                                                     // Значение PWM насоса при работе с БК
static uint32_t chipId = 0;                                            // Идентификатор ESP32
//String vr;                                                      // Причина перезагрузки ESP32
static String SessionDescription;                                      // Описание параметров работы в свободном формате для сохранения в облаке
static volatile float test_num_val;                                    // Тестовое численное значение
static float pressure_value;                                           // Давление от датчика давления
static bool use_pressure_sensor;                                       // Использовать датчик давления (по результатам инициализации)
static String test_str_val;                                            // Тестовое строковое значение
static String Lua_status;                                              // Статус Lua
static uint32_t total_byte;                                            // Доступно байт на файловой системе
static uint32_t used_byte;                                             // Использовано байт на файловой системе
static uint8_t use_I2C_dev;                                            // Использовать Nano, подключенную по I2C для управления шаговым двигателем мешалки и насосом (основное назначение - пиво)
static uint16_t water_pump_speed;                                      // Скорость насоса

static String current_power_mode;                                      // Режим работы регулятора напряжения
static volatile float target_power_volt = 0;                           // Заданное напряжение регулятора
static volatile float current_power_volt = 0;                          // Текущее напряжение регулятора
static unsigned long alarm_c_min;                                      // Время для ожидания возврата к заданному напряжению-1 Вольт для режима предзахлеба в секундах с момента старта ESP32
static unsigned long alarm_c_low_min;                                  // Время для ожидания возврата к заданному напряжению-1 Вольт для режима предзахлеба в секундах с момента старта ESP32

#ifdef SAMOVAR_USE_POWER
static volatile float prev_target_power_volt;                          // Предыдущее заданное напряжение регулятора
static volatile uint16_t current_power_p;                              // Расчитанная мощность на регуляторе напряжения
static uint8_t power_err_cnt;                                          // Счетчик ошибок по напряжению/мощности
#define TIME_C 4                                                // Время ожидания в минутах для программы режима предзахлеба
#endif

#ifdef USE_WATER_PUMP
static uint8_t wp_count;                                               // Переменная для расчета времени работы насоса на повышенной мощности при старте
#endif

#endif
