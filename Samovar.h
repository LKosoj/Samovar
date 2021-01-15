#include "Samovar_ini.h"

#ifdef __cplusplus
extern "C" {
#endif

uint8_t temprature_sens_read();

#ifdef __cplusplus
}
#endif

uint8_t temprature_sens_read();

#define SAMOVAR_VERSION "1.5"
#define __SAMOVAR_DEBUG

#define SAMOVAR_USE_BLYNK                   //использовать Blynk в проекте
#define SAMOVAR_USE_POWER                   //использовать регулятор напряжения в проекте
#define USE_WATERSENSOR                     //использовать датчик потока воды охлаждения. Если используется - в случае отсутствия воды в течении заданного времени Самовар отключит нагрев колонны

//#define USE_UPDATE_OTA                      //использовать ArduinoOTA для обновления через WI-FI. Удобно при отладке, при работе создает лишнюю нагрузку на ESP32
#define USE_PRESSURE_CORRECT                // использовать корректировку температуры отбора тела при изменении давления

#define SAMOVAR_LOG_PERIOD 3                // периодичность записи данных о температуре в файл (раз в три секунды, оптимально с точки зрения объема файла)
#define TIMEZONE 3                          // таймзона того места, где будет применяться устройство

#define EEPROM_SIZE 512

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
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для шагового двигателя
#define STEPPER_STEP 26
#define STEPPER_DIR 32
#define STEPPER_EN 33
#define STEPPER_STEPS 200 //количество шагов, 200 x 16
#define STEPPER_STEP_ML 2004 //количество шагов на 1 мл жидкости для драйвера с шагами 1/2
#define VOLUME_MAX_SPEED 2.0
#define STEPPER_MAX_SPEED 10000
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для релейного модуля
#define RELE_CHANNEL1 2             //используется для пускателя, который включает нагреватель
#define RELE_CHANNEL2 34            //используется для клапана, открывающего/закрывающего воду охлаждения
#define RELE_CHANNEL3 14
#define RELE_CHANNEL4 13
//**************************************************************************************************************

//**************************************************************************************************************
// Пин для DS1820
#define ONE_WIRE_BUS 5
//**************************************************************************************************************

//**************************************************************************************************************
// Пины для сервопривода
#define SERVO_PIN 25
//Максимальный угол сервопривода
#define SERVO_ANGLE 180
// Количество емкостей. (0 используется всегда). Для расчета позиции серво считаем угол поворота между емкостями
// равным 180 / CAPACITY_NUM
#define CAPACITY_NUM 10
//Корректировка для угла поворота. Мой сервопривод встает не ровно.
int8_t servoDelta[11] = {0, -2, -3, -4, -3, -2, 0, 0, 0, 0, -2};
//**************************************************************************************************************

//**************************************************************************************************************
// Пины кнопки - не обязательно, но удобно
#define BTN_PIN 39
#define USE_BTN
//**************************************************************************************************************

//**************************************************************************************************************
// Пины сенсора охлаждения воды - используется для отключения нагрева в случае отсутствия охлаждения. Не обязательно, но безопасно
#define WATERSENSOR_PIN 36
#define WF_CALIBRATION 98 //Значение на датчике F=98*Q(L/min)
#define WF_ALARM_COUNT 20 //Секунд до отключения нагрева, если в течении этого времени не будет подана вода охлаждения
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
// Настройки предельных значений для контроля автоматики
//**************************************************************************************************************
//Температура воды, при достижении которой будет оповещен оператор
#define ALARM_WATER_TEMP 70
//Максимальное значение температуры воды, при котором выключится питание
#define MAX_WATER_TEMP 90
//Максимальное значение температуры пара, при котором выключится питание
#define MAX_STEAM_TEMP 99.8
//Значение температуры датчика пара, при котором колонна перейдет из режима разгона в рабочий режим
#define CHANGE_POWER_MODE_STEAM_TEMP 76.5
//Значение температуры датчика в кубе, при котором откроется клапан подачи воды
#define OPEN_VALVE_TANK_TEMP 59.5
//**************************************************************************************************************

//**************************************************************************************************************
// Режимы работы регулятора напряжения
#define POWER_WORK_MODE "0"
#define POWER_SPEED_MODE "1"
#define POWER_SLEEP_MODE "2"
//**************************************************************************************************************

void writeString(String Str, byte num);

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
String StrCrt, Crt;
byte CurMin, OldMin;

//**************************************************************************************************************

/** Task handle for the  value read task */
TaskHandle_t StepperTickerTask1 = NULL;

Ticker SensorTicker;
Ticker SensorTempTicker;

AsyncWebServer server(80);

AsyncWebSocket ws("/ws");
AsyncEventSource events("/events");

Adafruit_BME680 bme; // I2C
//ClosedCube_BME680 bme680;

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLUMNS, LCD_ROWS);

Encoder encoder(ENC_CLK, ENC_DT, ENC_SW, TYPE2);
GStepper< STEPPER2WIRE> stepper(STEPPER_STEPS, STEPPER_STEP, STEPPER_DIR, STEPPER_EN);

File fileToAppend;
Servo servo;  // create servo object to control a servo

GButton btn(BTN_PIN);

LiquidMenu main_menu1(lcd);


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
};

struct DSSensor {
  DeviceAddress Sensor;                                          //адрес датчика температуры
  float Temp;                                                    //температура с датчика
  float avgTemp;                                                 //средняя температура
  float SetTemp;                                                 //уставка по температуре, при достижении которой требуется реакция
  float BodyTemp;                                                //температура, с которой начался отбор тела
  uint16_t Delay;                                                //время задержки включения насоса в секундах
  float PrevTemp;                                                //Предыдущая температура
  float Start_Pressure;                                          //Стартовое давление при начале отбора
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

WProgram program[CAPACITY_NUM * 2];                             //массив строк для записи программы отбора. Не больше чем CAPACITY_NUM * 2

enum SamovarCommands {SAMOVAR_NONE, SAMOVAR_START, SAMOVAR_POWER, SAMOVAR_RESET, CALIBRATE_START, CALIBRATE_STOP, SAMOVAR_PAUSE, SAMOVAR_CONTINUE};
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
volatile bool bmefound = true;
//volatile float samovar_temp;                                  // Температура ESP32
volatile float bme_temp;                                        // Температура BME
volatile float start_pressure;                                  // Давление BME стартовое
volatile float bme_pressure;                                    // Давление BME
volatile float bme_prev_pressure;                               // Давление BME предыдущее значение
volatile float bme_humidity;                                    // Влажность
volatile float bme_altitude;                                    // Высота
volatile float bme_gas;                                         // Газ
String SamovarStatus;                                           // Текущий статус работы Самовара строкой
volatile int8_t SamovarStatusInt;                               // Текущий статус работы Самовара числом
volatile byte capacity_num;                                     // Текущая позиция емкости для отбора

volatile byte ProgramNum;                                       // Текущая программа отбора
volatile byte ProgramLen;                                       // Количество строк программы отбора
volatile byte startval = 0;                                     // Признак идущего отбора
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
unsigned long begintime;                                        // Время начала отбора
unsigned long endtime;                                          // Время завершения отбора
unsigned long t_min;                                            // Время для паузы в секундах с момента старта ESP32. Это накладывает определенные ограничения на время отбора - оно не должно быть больше двух суток
unsigned long alarm_t_min;                                      // Время для паузы в секундах для событий безопасности с момента старта ESP32. Это накладывает определенные ограничения на время отбора - оно не должно быть больше двух суток
volatile uint16_t WFpulseCount = 0;                             // Счетчик для датчика потока
uint16_t WFflowMilliLitres = 0;                                 // Переменная для учета расхода воды
uint16_t WFtotalMilliLitres = 0;                                // Переменная для учета расхода воды
float WFflowRate;                                               // Переменная для учета расхода воды
int WFAlarmCount;                                               // Переменная, считающая, сколько секунд не было подачи воды
unsigned long oldTime;                                          // Предыдущее время в милисекундах
bool valve_status;                                              // Состояние клапана подачи воды
uint16_t acceleration_temp;                                     // Счетчик для определения завершения разгона колонны
float WthdrwTimeAll;                                            // Оставшееся время отбора
float WthdrwTime;                                               // Время отбора текущей строки программы
String WthdrwTimeAllS;                                          // Оставшееся время отбора строкой
String WthdrwTimeS;                                             // Время отбора текущей строки программы строкой
String jsonstr;                                                 // Строка, содержащая json ответ для страницы

#ifdef SAMOVAR_USE_POWER
String current_power_mode;                                      // Режим работы регулятора напряжения
float current_power_volt;                                       // Текущее напряжение регулятора
float target_power_volt;                                        // Заданное напряжение регулятора
String serial_str;                                              // Срока для чтения UART
#endif
