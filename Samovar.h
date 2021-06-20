#ifndef SAMOVAR_H
#define SAMOVAR_H

#ifndef ESP32
#error This code is designed to run on ESP32 platform, not Arduino nor ESP8266! Please check your Tools->Board setting.
#endif

#define SAMOVAR_VERSION "2.07"
//#define __SAMOVAR_DEBUG

#include "Samovar_ini.h"

#ifdef __SAMOVAR_DEBUG
#ifndef USE_WEB_SERIAL
#define USE_WEB_SERIAL                      //использовать библиотеку WebSerial для отладки
#endif
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

#ifdef SAMOVAR_USE_RMVK
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

#define __SAMOVAR_NOT_USE_WDT

//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------

#define EEPROM_SIZE 512

//**************************************************************************************************************
// Распиновка
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для BME680, BMP180, BMP280
//#define BME_SCK 22   //SCL
//#define BME_MISO --  //SDO
//#define BME_MOSI 21  //SDA
//#define BME_CS --    //CS
//#define SEALEVELPRESSURE_HPA (1013.25)
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для Encoder
#ifndef ENC_CLK
#define ENC_CLK 19 //S2
#endif
#ifndef ENC_DT
#define ENC_DT 18  //S1
#endif
#ifndef ENC_SW
#define ENC_SW 23  //KEY
#endif
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для шагового двигателя
#ifndef STEPPER_STEP
#define STEPPER_STEP 26
#endif
#ifndef STEPPER_DIR
#define STEPPER_DIR 32
#endif
#ifndef STEPPER_EN
#define STEPPER_EN 33
#endif
#define STEPPER_STEPS 400 //количество шагов, 200 x MS
#define STEPPER_STEP_ML 1020 //количество шагов на 1 мл жидкости для драйвера с шагами 1/2
#define STEPPER_MAX_SPEED 8000
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для релейного модуля
#ifndef RELE_CHANNEL1
#define RELE_CHANNEL1 2             //используется для пускателя, который включает нагреватель
#endif
#ifndef RELE_CHANNEL2
#define RELE_CHANNEL2 15 //было 34  //в режиме "Пиво" используется для включения мешалки
#endif
#ifndef RELE_CHANNEL3
#define RELE_CHANNEL3 14            //используется для клапана, открывающего/закрывающего воду охлаждения
#endif
#ifndef RELE_CHANNEL4
#define RELE_CHANNEL4 13            //если не используется регулятор с управлением, выход используется для управления разгоном
#endif
//**************************************************************************************************************

//**************************************************************************************************************
// Пин для DS1820
#ifndef ONE_WIRE_BUS
#define ONE_WIRE_BUS 5
#endif
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для сервопривода
#ifndef SERVO_PIN
#define SERVO_PIN 25
#endif
//Максимальный угол сервопривода
#define SERVO_ANGLE 180
// Количество емкостей. (0 используется всегда). Для расчета позиции серво считаем угол поворота между емкостями
// равным 180 / CAPACITY_NUM
#define CAPACITY_NUM 10
//**************************************************************************************************************

//**************************************************************************************************************
// Пины кнопки - не обязательно, но удобно
#ifndef BTN_PIN
#define BTN_PIN 39
#endif
//**************************************************************************************************************

//**************************************************************************************************************
// Пины сенсора охлаждения воды - используется для отключения нагрева в случае отсутствия охлаждения. Не обязательно, но безопасно
#ifndef WATERSENSOR_PIN
#define WATERSENSOR_PIN 36
#endif
#ifndef WF_CALIBRATION
#define WF_CALIBRATION 98 //Значение на датчике F=98*Q(L/min)
#endif
#define WF_ALARM_COUNT 20 //Секунд до отключения нагрева, если в течении этого времени не будет подана вода охлаждения
//**************************************************************************************************************

//**************************************************************************************************************
//Если не задана целевая температура воды - определяем ее
#ifndef TARGET_WATER_TEMP
#define TARGET_WATER_TEMP 50
#endif
//**************************************************************************************************************

//**************************************************************************************************************
// Пины сенсора уровня флегмы в узле отбора - используется для уменьшения нагрева при начале захлебывания колонны. Не обязательно, но безопасно
#ifndef WHEAD_LEVEL_SENSOR_PIN
#define WHEAD_LEVEL_SENSOR_PIN 27
#endif
#define WHLS_ALARM_TIME 3 //Секунд, через сколько сработает тревога по уровню флегмы
//**************************************************************************************************************

//**************************************************************************************************************
// Установки для экрана: пины, адрес, количество колонок и строк
#define LCD_SDA 21
#define LCD_SCL 22
#define LCD_ADDRESS 0x27
#define LCD_COLUMNS 20
#define LCD_ROWS 4
//**************************************************************************************************************

//**************************************************************************************************************
// Пины UART2 для взаимодействия с регулятором напряжения
#define RXD2 16
#define TXD2 17
//**************************************************************************************************************

//**************************************************************************************************************
// Пин для управления насосом по ШИМ
#ifndef WATER_PUMP_PIN
#define WATER_PUMP_PIN 4
#endif
//**************************************************************************************************************

//**************************************************************************************************************
// Пин для Buzzer
#define BZZ_PIN 12
//**************************************************************************************************************



//**************************************************************************************************************
// Режимы работы регулятора напряжения
#define POWER_WORK_MODE "0"
#define POWER_SPEED_MODE "1"
#define POWER_SLEEP_MODE "2"
//**************************************************************************************************************

#include "user_config_override.h"

void writeString(String Str, byte num);
void WriteConsoleLog(String StringLogMsg);

//**************************************************************************************************************
// Описание переменных
//**************************************************************************************************************

//**************************************************************************************************************
// Переменные для меню
byte multiplier = 1;

char tst[20] = "00:00:00   00:00:00";
char ipst[16] = "000.000.000.000";
char welcomeStrArr1[20];
char welcomeStrArr2[20];
char welcomeStrArr3[20];
char welcomeStrArr4[20];
char* welcomeStr1 = (char*)welcomeStrArr1;
char* welcomeStr2 = (char*)welcomeStrArr2;
char* welcomeStr3 = (char*)welcomeStrArr3;
char* welcomeStr4 = (char*)welcomeStrArr4;

char* timestr = (char*)tst;
char* ipstr = (char*)ipst;
char startval_text_val[20];
char* startval_text = (char*)startval_text_val;
char* power_text_ptr = (char*)"ON";
char* calibrate_text_ptr = (char*)"Start";
char* pause_text_ptr = (char*)"Pause";
String StrCrt;
String Crt;
byte CurMin, OldMin;

//**************************************************************************************************************

/** Task handle for the  value read task */
TaskHandle_t SysTickerTask1 = NULL;
TaskHandle_t GetClockTask1 = NULL;
TaskHandle_t BuzzerTask = NULL;
volatile bool BuzzerTaskFl;

#ifdef SAMOVAR_USE_POWER
#ifndef SAMOVAR_USE_RMVK
TaskHandle_t PowerStatusTask = NULL;
#endif
#endif

#ifdef SAMOVAR_USE_RMVK
TaskHandle_t RMVKStatusTask = NULL;
#endif

AsyncWebServer server(80);

AsyncWebSocket ws("/ws");
AsyncEventSource events("/events");

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
DeviceAddress DSAddr[5];

LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLUMNS, LCD_ROWS);

Encoder encoder(ENC_CLK, ENC_DT, ENC_SW, TYPE2);

GStepper< STEPPER2WIRE> stepper(STEPPER_STEPS, STEPPER_STEP, STEPPER_DIR, STEPPER_EN);

File fileToAppend;

#ifdef SERVO_PIN
Servo servo;  // create servo object to control a servo
#endif

GButton btn(BTN_PIN);
//GyverRelay regulator(REVERSE);

double Input, Output, Setpoint;
double Kp, Ki, Kd;

//Relay relay(RELAY_PIN, RELAY_PERIOD);
PID heaterPID(&Input, &Output, &Setpoint, Kp, Ki, Kd, DIRECT);
int periodInSeconds = 6;

byte ATuneModeRemember = 2;
double aTuneStep = 50;
double aTuneNoise = 1;
unsigned int aTuneLookBack = 9;
boolean tuning = false;

PID_ATune aTune(&Input, &Output);


#ifdef USE_HEAD_LEVEL_SENSOR
GButton whls(WHEAD_LEVEL_SENSOR_PIN);
#endif

LiquidMenu main_menu1(lcd);

#ifdef USE_WEB_SERIAL
//WebSerialClass WebSerial;
#endif

DNSServer dns;

enum SamovarCommands {SAMOVAR_NONE, SAMOVAR_START, SAMOVAR_POWER, SAMOVAR_RESET, CALIBRATE_START, CALIBRATE_STOP, SAMOVAR_PAUSE, SAMOVAR_CONTINUE, SAMOVAR_SETBODYTEMP, SAMOVAR_DISTILLATION, SAMOVAR_BEER, SAMOVAR_BEER_NEXT};
volatile SamovarCommands sam_command_sync;                      // переменная для передачи команд между процессами

enum SAMOVAR_MODE {SAMOVAR_RECTIFICATION_MODE, SAMOVAR_DISTILLATION_MODE, SAMOVAR_BEER_MODE, SAMOVAR_SUVID};
volatile SAMOVAR_MODE Samovar_Mode;

struct SetupEEPROM {
  byte flag;                                                   //Флаг для записи в память
  float DeltaSteamTemp;                                        //Корректировка температурного датчика
  float DeltaPipeTemp;                                         //Корректировка температурного датчика
  float DeltaWaterTemp;                                        //Корректировка температурного датчика
  float DeltaTankTemp;                                         //Корректировка температурного датчика
  int StepperStepMl;                                           //Количество шагов шагового двигателя на мл. жидкости
  float SetSteamTemp;                                          //Уставка температурного датчика
  float SetPipeTemp;                                           //Уставка температурного датчика
  float SetWaterTemp;                                          //Уставка температурного датчика
  float SetTankTemp;                                           //Уставка температурного датчика
  bool UsePreccureCorrect;                                     //Использовать корректировку температуры отбора тела при изменении давления
  uint16_t SteamDelay;                                         //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  uint16_t PipeDelay;                                          //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  uint16_t WaterDelay;                                         //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  uint16_t TankDelay;                                          //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  byte TimeZone;                                               //Таймзона того места, где будет применяться устройство
  float HeaterResistant;                                       //Сопротивление тэна для расчета мощности
  byte LogPeriod;                                              //Периодичность записи данных о температуре в файл (раз в три секунды, оптимально с точки зрения объема файла). Если прогнозируемое время работы Самовара больше суток - лучше период установить раз в 5-10 секунд.
  char SteamColor[20];                                         //Цвета температур в интерфейсе
  char PipeColor[20];
  char WaterColor[20];
  char TankColor[20];
  bool rele1;                                                  //Уровни для реле
  bool rele2;
  bool rele3;
  bool rele4;
  byte SteamAdress[8];                                          //адреса датчиков температуры
  byte PipeAdress[8];
  byte WaterAdress[8];
  byte TankAdress[8];
  bool useautospeed;                                            //Настройка для использования автокорректировки скорости
  byte autospeed;                                               //Процент изменения скорости
  char blynkauth[33];
  char videourl[120];                                           //URL для потокового видео с камеры
  float DistTemp;                                               //Температура, при которой завершится дистилляция
  int Mode;                                                     //Режим работы Самовара
  byte ACPAdress[8];                                            //адрес датчиков температуры
  char ACPColor[20];                                            //Цвет температуры в интерфейсе
  float DeltaACPTemp;                                           //Корректировка температурного датчика
  float SetACPTemp;                                             //Уставка температурного датчика
  uint16_t ACPDelay;                                            //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  float Kp;                                                     //Коэффициенты для PID-регулятора нагрева
  float Ki;
  float Kd;
  float StbVoltage;                                             //Напряжение регулятора в режиме поддержания температуры
};

struct DSSensor {
  DeviceAddress Sensor;                                          //адрес датчика температуры
  //  float Temp;                                                    //температура с датчика
  float avgTemp;                                                 //средняя температура с датчика
  float SetTemp;                                                 //уставка по температуре, при достижении которой требуется реакция
  float BodyTemp;                                                //температура, с которой начался отбор тела
  uint16_t Delay;                                                //Время задержки включения насоса в секундах при выходе температуры за значение уставки
  float PrevTemp;                                                //Предыдущая температура
  float Start_Pressure;                                          //Стартовое давление при начале отбора
  int ErrCount;                                                  //Счетчик ошибок для оповещения о не возможности провести чтение с датчика
};

struct WProgram {
  String WType;                                                   //тип отбора - головы или тело
  uint16_t Volume;                                                //объем отбора в мл
  float Speed;                                                    //скорость отбора в л/ч
  byte capacity_num;                                              //номер емкости для отбора
  float Temp;                                                     //температура, при которой отбирается эта часть погона. 0 - определяется автоматически
  int Power;                                                      //напряжение, при которой отбирается эта часть погона.
  float Time;                                                     //время, необходимое для отбора программы
};

SetupEEPROM SamSetup;

DSSensor SteamSensor;                                           //сенсор температуры пара вверху колонны
DSSensor PipeSensor;                                            //сенсор температуры в царге на 2/3 высоты
DSSensor WaterSensor;                                           //сенсор температуры охлаждающей воды или флегмы
DSSensor TankSensor;                                            //сенсор температуры в кубе
DSSensor ACPSensor;                                             //сенсор температуры в ТСА

WProgram program[CAPACITY_NUM * 2];                             //массив строк для записи программы отбора. Не больше чем CAPACITY_NUM * 2

//**************************************************************************************************************
const char* host = SAMOVAR_HOST;
//**************************************************************************************************************

//**************************************************************************************************************
byte DScnt = 0;
byte tcnt = 0;
bool bmefound = true;
float SSPrevTemp;
float PSPrevTemp;
float WSPrevTemp;
float TSPrevTemp;

//volatile float samovar_temp;                                  // Температура ESP32
volatile float bme_temp;                                        // Температура BME
volatile float start_pressure;                                  // Давление BME стартовое
volatile float bme_pressure;                                    // Давление BME
volatile float bme_prev_pressure;                               // Давление BME предыдущее значение
float bme_humidity;                                             // Влажность
float bme_altitude;                                             // Высота
float bme_gas;                                                  // Газ
String SamovarStatus;                                           // Текущий статус работы Самовара строкой
volatile int16_t SamovarStatusInt;                              // Текущий статус работы Самовара числом
volatile byte capacity_num;                                     // Текущая позиция емкости для отбора

volatile byte prev_ProgramNum;                                  // Пердыдущая программа отбора
volatile byte ProgramNum;                                       // Текущая программа отбора
volatile byte ProgramLen;                                       // Количество строк программы отбора
volatile int16_t startval = 0;                                  // Признак идущего отбора
volatile uint16_t Delay1 = 30;                                  // временная задержка отбора для стабилизации колонны по температуре на 2/3 колонны (в секундах)
volatile uint16_t Delay2 = 30;                                  // временная задержка отбора для стабилизации колонны по температуре вверху колонны (в секундах)
volatile int currentvolume = 0;                                 // Текущий отбираемый объем
volatile int currentstepcnt = 0;                                // Текущее количество шагов шагового двигателя
volatile unsigned long prev_time_ms;                            // Предыдущее время
volatile float ActualVolumePerHour;                             // Скорость отбора в литрах в моменте
volatile uint16_t CurrrentStepperSpeed;                         // Скорость шагового двигателя
volatile unsigned int CurrrentStepps;                           // Количество пройденных степпером шагов
volatile unsigned int TargetStepps;                             // Количество шагов до нужного объема
volatile unsigned int WthdrwlProgress;                          // Прогресс текущего отбора
volatile bool PowerOn = false;                                  // Индикатор включенного питания
volatile bool PauseOn = false;                                  // Индикатор постановки отбора на паузу
volatile bool StepperMoving = false;                            // Индикатор движущегося шагового двигателя
volatile bool program_Pause;                                    // Признак, что запущена программа паузы
volatile bool program_Wait;                                     // Признак, что программа ожидает возврата колонны в заданные параметры
String program_Wait_Type;                                       // Тип ожидания
unsigned long begintime;                                        // Время начала отбора
unsigned long endtime;                                          // Время завершения отбора
unsigned long t_min;                                            // Время для паузы в секундах с момента старта ESP32. Это накладывает определенные ограничения на время отбора - оно не должно быть больше двух суток
unsigned long alarm_t_min;                                      // Время для паузы в секундах для событий безопасности с момента старта ESP32. Это накладывает определенные ограничения на время отбора - оно не должно быть больше двух суток
unsigned long alarm_h_min;                                      // Время для паузы в секундах для событий безопасности с момента старта ESP32. Это накладывает определенные ограничения на время отбора - оно не должно быть больше двух суток
volatile uint16_t WFpulseCount = 0;                             // Счетчик для датчика потока
volatile uint16_t WFflowMilliLitres = 0;                        // Переменная для учета расхода воды
volatile uint16_t WFtotalMilliLitres = 0;                       // Переменная для учета расхода воды
volatile float WFflowRate;                                      // Переменная для учета расхода воды
int WFAlarmCount;                                               // Переменная, считающая, сколько секунд не было подачи воды
bool valve_status;                                              // Состояние клапана подачи воды
uint16_t acceleration_temp;                                     // Счетчик для определения завершения разгона колонны
volatile float WthdrwTimeAll;                                   // Оставшееся время отбора
volatile float WthdrwTime;                                      // Время отбора текущей строки программы
String WthdrwTimeAllS;                                          // Оставшееся время отбора строкой
String WthdrwTimeS;                                             // Время отбора текущей строки программы строкой
String jsonstr;                                                 // Строка, содержащая json ответ для страницы
String Msg;                                                     // Строка для сообщений в web-интерфейсе
String LogMsg;                                                  // Строка для вывода лога в javascript console
bool pump_started;                                              // Признак стартовавшего насоса
bool setautospeed;                                              // Признак для однократного снижения скорости насоса при паузе
volatile bool heater_state;                                     // Статус нагрева при затирке
bool msgfl;                                                     // Флаг для одноразовых сообщений
String ofl;                                                     // Openlog filename
bool mixer_status;                                              // Статус работы мешалки

String current_power_mode;                                      // Режим работы регулятора напряжения
#ifdef SAMOVAR_USE_POWER
volatile float current_power_volt;                              // Текущее напряжение регулятора
volatile float target_power_volt;                               // Заданное напряжение регулятора
volatile float prev_target_power_volt;                          // Предыдущее заданное напряжение регулятора
volatile uint16_t current_power_p;                              // Расчитанная мощность на регуляторе напряжения
#endif

#ifdef USE_WATER_PUMP
byte wp_count;                                                  // Переменная для расчета времени работы насоса на повышенной мощности при старте
#endif
#endif
