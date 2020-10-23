#include "Samovar_ini.h"
#define SAMOVAR_VERSION "1.0"
#define __SAMOVAR_DEBUG

#define SAMOVAR_USE_BLYNK                   //использовать Blynk в проекте

#define SAMOVAR_LOG_PERIOD 3                // периодичность записи данных о температуре в файл
#define TIMEZONE 3                          // таймзона того места, где будет применяться устройство
#define EEPROM_SIZE 1024

//**************************************************************************************************************
// Распиновка
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для BME 680
//#define BME_SCK 22   //SCL
//#define BME_MISO --  //SDO
//#define BME_MOSI 21  //SDA
//#define BME_CS --    //CS
#define SEALEVELPRESSURE_HPA (1013.25)
#define USE_BME_680
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для Encoder
#define ENC_CLK 19 //S2
#define ENC_DT 18  //S1
#define ENC_SW 23  //KEY
#define USE_ENCODER
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для шагового двигателя
#define STEPPER_STEP 26
#define STEPPER_DIR 32
#define STEPPER_EN 33
#define STEPPER_STEPS 200 //количество шагов, 200 x 16
#define HEAD_INITIAL_SPEED 0.350 //Cкорость, от которой дальше считается скорость отбора
#define STEPPER_STEP_ML 10 //количество шагов на 1 мл жидкости
#define VOLUME_MAX_SPEED 2.5
#define STEPPER_MAX_SPEED 3000
#define USE_STEPPER
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для релейного модуля
#define RELE_CHANNEL1 2 //13
#define RELE_CHANNEL2 12
#define RELE_CHANNEL3 14
#define RELE_CHANNEL4 3
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для DS1820
#define ONE_WIRE_BUS 5
#define TEMP_AVG_READING 30  //Должно быть кратно 2, отвечает за усреднение показателей температуры.
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для сервопривода
#define SERVO_PIN 25
//**************************************************************************************************************

//**************************************************************************************************************
// Пины кнопки
#define BTN_PIN 34
#define USE_BTN
//**************************************************************************************************************

//**************************************************************************************************************
// Пины сенсора охлаждения воды
#define WATERSENSOR_PIN 35
#define USE_WATERSENSOR
//**************************************************************************************************************

//**************************************************************************************************************
// Установки для экрана: пины, адрес, количество колонок и строк
#define LCD_SDA 21
#define LCD_SCL 22
#define LCD_ADDRESS 0x27
#define LCD_COLUMNS 20
#define LCD_ROWS 4


void writeString(String Str, byte num);

//**************************************************************************************************************
// Описание переменных
//**************************************************************************************************************

//**************************************************************************************************************
// Переменные для меню
byte multiplier = 1;

char tst[20]="00:00:00   00:00:00";
char ipst[16]="000.000.000.000";
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
char* startval_text;
char* power_text_ptr = (char*)"ON";
char* calibrate_text_ptr = (char*)"Start";
String StrCrt, Crt, OldCrt;

//**************************************************************************************************************

/** Task handle for the  value read task */
TaskHandle_t StepperTickerTask1 = NULL;

Ticker SensorTicker;

float TempArray[3][80000];                        //массив для сохранения данных о температуре

AsyncWebServer server(80);

AsyncWebSocket ws("/ws");
AsyncEventSource events("/events");


//EspHtmlTemplateProcessor templateProcessor(&server);


//Adafruit_BME680 bme(BME_CS, BME_MOSI, BME_MISO,  BME_SCK);
Adafruit_BME680 bme; // I2C

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLUMNS, LCD_ROWS); 

Encoder encoder(ENC_CLK, ENC_DT, ENC_SW, TYPE2);
GStepper< STEPPER2WIRE> stepper(STEPPER_STEPS, STEPPER_STEP, STEPPER_DIR, STEPPER_EN);

File fileToAppend;
byte countToAppend;
//String sys_info_str;

#ifdef USE_VOLUME_METER
//GyverPID regulator(0.1, 0.05, 0.01, 20000);
#endif

struct SetupEEPROM{
  byte flag;                                                   //Флаг для записи в память
  float DeltaSteamTemp;                                        //Корректировка температурного датчика
  float DeltaPipeTemp;                                         //Корректировка температурного датчика
  float DeltaWaterTemp;                                        //Корректировка температурного датчика
  float DeltaTankTemp;                                         //Корректировка температурного датчика
  int StepperStepMl;                                           //Количество шагов шагового двигателя на мл. жидкости
  float LiquidRateHead;                                        //Скорость отбора голов
  float LiquidRateBody;                                        //Скорость отбора тела
  int HeadVolume;                                              //Объем для отбора голов
  int BodyVolume;                                              //Объем для отбора тела
  float SetSteamTemp;                                          //Уставка температурного датчика
  float SetPipeTemp;                                           //Уставка температурного датчика
  float SetWaterTemp;                                          //Уставка температурного датчика
  float SetTankTemp;                                           //Уставка температурного датчика
};

struct DSSensor{
DeviceAddress Sensor;                                          //адрес датчика температуры
float Temp;                                                    //температура с датчика
float avgTempAccumulator;                                      //аккумулятор температуры для расчета среднего
byte avgTempReadings;                                          //счетчик для расчета среднего
float avgTemp;                                                 //средняя температура
float SetTemp;                                                 //уставка по температуре, при достижении которой требуется реакция
};

SetupEEPROM SamSetup;

DSSensor SteamSensor;                                           // сенсор температуры пара вверху колонны
DSSensor PipeSensor;                                            // сенсор температуры в царге на 2/3 высоты
DSSensor WaterSensor;                                           // сенсор температуры охлаждающей воды или флегмы
DSSensor TankSensor;                                            // сенсор температуры в кубе

enum SamovarCommands {SAMOVAR_NONE, SAMOVAR_START, SAMOVAR_POWER, SAMOVAR_RESET, CALIBRATE_START, CALIBRATE_STOP, SAMOVAR_MANUAL, SAMOVAR_PAUSE, SAMOVAR_CONTINUE};
volatile SamovarCommands sam_command_sync;                      // переменная для передачи команд между процессами

//**************************************************************************************************************
// Параметры подключения к WIFI
const char* host = SAMOVAR_HOST;
const char* ssid = SAMOVAR_SSID;
const char* password = SAMOVAR_PASSWORD;
// You should get Auth Token in the Blynk App.
// Go to the Project Settings (nut icon).
char auth[] = SAMOVAR_AUTH;
//**************************************************************************************************************

//**************************************************************************************************************
volatile bool bmefound = false;
//volatile float samovar_temp;                                    // Температура ESP32
volatile float bme_temp;                                        // Температура BME
volatile float start_pressure;                                  // Давление BME стартовое
volatile float bme_pressure;                                    // Давление BME
volatile float bme_humidity;                                    // Влажность
volatile float bme_altitude;                                    // Высота
volatile float bme_gas;                                         // Газы
String crnt_time;                                               // Текущее время (строка)
String SamovarStatus;                                           // Текущий статус работы Самовара
volatile int SamovarStatusInt;                                  // Текущий статус работы Самовара

volatile byte startval = 0;                                     // Признак идущего отбора
volatile int Delay1 = 30;                                       // временная задержка включения клапана по температуре на 2/3 колонны (в секундах)
volatile int Delay2 = 30;                                       // временная задержка включения клапана по температуре вверху колонны (в секундах)
volatile float LiquidVolume[20];                                // Объем жидкости с момента начала отбора
volatile float LiquidVolumeTarget[20];                          // Целевой объем жидкости
volatile float LiquidVolumeAll = 0;                             // Общий объем жидкости
volatile int currentvolume = 0;                                 // Текущий отбираемый объем
volatile int currentstepcnt = 0;                                // Текущее количество шагов шагового двигателя
volatile int current_v_m_count = 0;                             // Счетчик отбора
volatile unsigned long prev_time_ms;                            // Предыдущее время
volatile float ActualVolumePerHour;                             // Скорость отбора в литрах в моменте
volatile int CurrrentStepperSpeed;                              // Скорость шагового двигателя
volatile float ManualLiquidRate;                                // Скорость отбора в ручном режиме
volatile int ManualVolume;                                      // Объем отбора в ручном режиме
volatile unsigned int CurrrentStepps;                           // Количество пройденных степпером шагов
volatile unsigned int TargetStepps;                             // Количество шагов до нужного объема
volatile unsigned int WthdrwlProgress;                          // Прогресс текущего отбора
volatile bool PowerOn = false;                                  // Индикатор включенного питания
volatile bool PauseOn = false;                                   // Индикатор постановки отбора на паузу
volatile bool FullAuto = true;                                  // Индикатор полностью автоматического процесса (нужно для отладки)
volatile bool StepperMoving = false;                            // Индикатор движущегося шагового двигателя
volatile int RemainingDistance;                                 // Расстояние, оставшееся до цели (сколько еще надо сделать шагов, чтобы закончить отбор)
unsigned long begintime;                                        // Время начала отбора
unsigned long endtime;                                          // Время завершения отбора

String jsonstr;                                                 // Строка, содержащая json ответ для страницы
