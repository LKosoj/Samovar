#ifndef __SAMOVAR_S_I_H_
#define __SAMOVAR_S_I_H_
#include <Arduino.h>
#include <DallasTemperature.h>
#include "Samovar.h"
#include "pumppwm.h"

#ifdef USE_LUA
#include "lua.h"
#endif
// Функция загрузки программы по умолчанию для текущего режима
void load_default_program_for_mode() {
  if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
    set_beer_program("M;45;0;0^-1^2^2;0\nP;45;1;0^-1^2^3;0\nP;60;1;0^-1^2^3;0\nW;0;0;0^-1^2^3;0\nB;0;1;0^-1^2^3;0\nC;30;0;0^-1^2^3;0\n");
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    set_dist_program("A;80.00;1;0\nS;0.50;2;0\nS;0.30;3;0\n");
  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
    set_nbk_program(NBK_DEFAULT_PROGRAM);
  } else {
    set_program("H;450;0.1;1;0;45\nB;450;1;1;0;45\nH;450;0.1;1;0;45\n");
  }
}

#ifdef USE_BME680
#define BME_STRING "BME680"
#include <Adafruit_BME680.h>
Adafruit_BME680 bme;  // I2C
#endif

#ifdef USE_BMP180
#include <Adafruit_BMP085_U.h>
#define BME_STRING "BMP180"
Adafruit_BMP085_Unified bme;  // I2C
#endif

#ifdef USE_BMP280
#include <Adafruit_BMP280.h>
#define BME_STRING "BMP280"
Adafruit_BMP280 bme;  // I2C
#endif

#ifdef USE_BME280
#include <Adafruit_BME280.h>
#define BME_STRING "BME280"
Adafruit_BME280 bme;  // I2C
#endif

String get_Samovar_Status();
void set_power(bool On);
void clok();
void clok1();
void getjson(void);
String append_data();
void stopService(void);
void startService(void);
void CopyDSAddress(const uint8_t* DevSAddress, uint8_t* DevTAddress);
void set_beer_program(String WProgram);
void set_program(String WProgram);
void set_dist_program(String WProgram);
void set_nbk_program(String WProgram);
String getDSAddress(DeviceAddress deviceAddress);
void setupOpenLog(void);
void createFile(char* fileName);
void set_capacity(uint8_t cap);
void init_pump_pwm(uint8_t pin, int freq);
void set_pump_pwm(float duty);

//**************************************************************************************************************
// Функции для работы с сенсорами
//**************************************************************************************************************

void printAddress(DeviceAddress deviceAddress);
void reset_sensor_counter(void);

//***************************************************************************************************************
// считываем параметры с датчика BME680
//***************************************************************************************************************
void BME_getvalue(bool fl) {
  if (!bmefound) {
    bme_temp = -1;
    bme_pressure = -1;
    return;
  }
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(50 / portTICK_RATE_MS)) == pdTRUE) {
#ifdef USE_BME680
    // Tell BME680 to begin measurement.
    if (bme.beginReading() == 0) {
      return;
    }

    if (!bme.endReading()) {
      return;
    }

    bme_temp = bme.temperature;
    bme_pressure = bme.pressure / 100 * 0.75;
    //bme_humidity = bme.humidity;

    //filtered_val += (val - filtered_val) * 0.01;
#endif

#ifdef USE_BMP180
    sensors_event_t event;
    bme.getEvent(&event);
    if (event.pressure) {
      bme_pressure = event.pressure * 0.75;
      float temp;
      bme.getTemperature(&temp);
      bme_temp = temp;
    }
#endif

#ifdef USE_BMP280
    bme_temp = bme.readTemperature();
    bme_pressure = bme.readPressure() / 100 * 0.75;
#endif

#ifdef USE_BME280
    bme_temp = bme.readTemperature();
    bme_pressure = bme.readPressure() / 100 * 0.75;
#endif
    xSemaphoreGive(xI2CSemaphore);
  }
}

//***************************************************************************************************************
// считываем параметры с датчика XGZP6897D или MPX5010D
//***************************************************************************************************************
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX)
void pressure_sensor_get() {
  if (!use_pressure_sensor) {
    pressure_value = -1;
    return;
  }
  float t;
#ifdef USE_PRESSURE_XGZ
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(30 / portTICK_RATE_MS)) == pdTRUE) {
    pressure_sensor.readSensor(t, pressure_value);
    xSemaphoreGive(xI2CSemaphore);
  }
  pressure_value = pressure_value / 133.32; //переводим паскали в мм. рт. столба
  pressure_value = (old_pressure_value + pressure_value) / 2;
  old_pressure_value = pressure_value;
#elif defined(USE_PRESSURE_MPX)
  pressure_value = (analogRead(LUA_PIN) - 36.7) / 12;
  pressure_value = (old_pressure_value + pressure_value) / 2;
  old_pressure_value = pressure_value;
#else
  pressure_value = -1;
#endif
}
#endif

//***************************************************************************************************************
// считываем температуры с датчиков DS18B20
//***************************************************************************************************************
void DS_getvalue(void) {

  //  SteamSensor.avgTemp += 0.1;
  //  PipeSensor.avgTemp = 50;
  //  WaterSensor.avgTemp += 0.1;
  //  if (WaterSensor.avgTemp > 4) WaterSensor.avgTemp = 25;
  //  if (SteamSensor.avgTemp < 20) SteamSensor.avgTemp = 20;
  //  else {
  //    if (!boil_started)SteamSensor.avgTemp += 1;
  //    else SteamSensor.avgTemp += 0.001;
  //  }
  //  if (TankSensor.avgTemp < 85) TankSensor.avgTemp = 85;
  //  else {
  //    if (!boil_started)TankSensor.avgTemp += 0.2;
  //    else TankSensor.avgTemp += 0.001;
  //  }
  //
  //    SteamSensor.avgTemp += SamSetup.DeltaSteamTemp;
  //    PipeSensor.avgTemp += SamSetup.DeltaPipeTemp;
  //    WaterSensor.avgTemp += SamSetup.DeltaWaterTemp;
  //    TankSensor.avgTemp += SamSetup.DeltaTankTemp;
  //    ACPSensor.avgTemp += SamSetup.DeltaACPTemp;
  //
  //  return;

  float ss, ps, ws, ts, acp;
  float correctT = 0;

  // Считаем корректировку температуры от атмосферного давления.
  // ВАЖНО: применять только если включена настройка "Учитывать атмосферное давление".
  if (SamSetup.UsePreccureCorrect && bme_pressure > 0 && PowerOn) {
    correctT = (760 - bme_pressure) * 0.037;
  }

  ss = correctT + sensors.getTempC(SteamSensor.Sensor);  // считываем температуру с датчика 0
  ps = correctT + sensors.getTempC(PipeSensor.Sensor);   // считываем температуру с датчика 1
  ws = sensors.getTempC(WaterSensor.Sensor);  // считываем температуру с датчика 2
  ts = correctT + sensors.getTempC(TankSensor.Sensor);   // считываем температуру с датчика 3
  acp = sensors.getTempC(ACPSensor.Sensor);   // считываем температуру с датчика 4

#ifdef USE_PRESSURE_1WIRE
  float pv;
  uint8_t p_addr[8] = USE_PRESSURE_1WIRE;
  pv = sensors.getTempC(p_addr);   // считываем давление с расширителя по 1Wire
  if (pv > -120) {
    pressure_value = pv;
    use_pressure_sensor = true;
  } else {
    //pressure_value = -1;
    //use_pressure_sensor = false;
  }

#endif

  //    float randNumber;
  //    randNumber = random(100) / float(500);
  //    if (TankSensor.avgTemp < 87) TankSensor.avgTemp = 89;
  //    if (WaterSensor.avgTemp < 47) WaterSensor.avgTemp = 49;
  //    static float coef = 0;
  //    coef = heater_state ? 0.1 + randNumber : -0.1 - randNumber;
  //    //if (coef > 0.5) coef = 0.5;
  //    //if (coef < -0.5) coef = -0.5;
  //    ts = TankSensor.avgTemp + coef;
  //    ws = WaterSensor.avgTemp + coef;

  sensors.requestTemperatures();

  if (ss > -10) {
    SteamSensor.avgTemp = ss + SamSetup.DeltaSteamTemp;
    SteamSensor.PrevTemp = SteamSensor.avgTemp;
    SteamSensor.ErrCount = 0;
  } else {
    if (SteamSensor.PrevTemp > 0) SteamSensor.ErrCount++;
  }
  if (ps > -10) {
    PipeSensor.avgTemp = ps + SamSetup.DeltaPipeTemp;
    PipeSensor.PrevTemp = PipeSensor.avgTemp;
    PipeSensor.ErrCount = 0;
  } else {
    if (PipeSensor.PrevTemp > 0) PipeSensor.ErrCount++;
  }
  if (ws > -10) {
    WaterSensor.avgTemp = ws + SamSetup.DeltaWaterTemp;
    WaterSensor.PrevTemp = WaterSensor.avgTemp;
    WaterSensor.ErrCount = 0;
  } else {
    if (WaterSensor.PrevTemp > 0) WaterSensor.ErrCount++;
  }
  if (ts > -10) {
    TankSensor.avgTemp = ts + SamSetup.DeltaTankTemp;
    TankSensor.PrevTemp = TankSensor.avgTemp;
    TankSensor.ErrCount = 0;
  } else {
    if (TankSensor.PrevTemp > 0) TankSensor.ErrCount++;
  }
  if (acp > -10) {
    ACPSensor.avgTemp = acp + SamSetup.DeltaACPTemp;
    ACPSensor.PrevTemp = ACPSensor.avgTemp;
    ACPSensor.ErrCount = 0;
  } else {
    if (ACPSensor.PrevTemp > 0) ACPSensor.ErrCount++;
  }

#ifdef __SAMOVAR_DEBUG1
  SteamSensor.avgTemp = SamSetup.DeltaSteamTemp;
  PipeSensor.avgTemp = SamSetup.DeltaPipeTemp;
  WaterSensor.avgTemp = SamSetup.DeltaWaterTemp;
  TankSensor.avgTemp = SamSetup.DeltaTankTemp;
  ACPSensor.avgTemp = SamSetup.DeltaACPTemp;
#endif
}

void scan_ds_adress() {
  sensors.begin();  // стартуем датчики температуры

  uint8_t dc = 0;

  while (sensors.getAddress(DSAddr[dc], dc)) {
    sensors.setResolution(DSAddr[dc], 12);  // устанавливаем разрешение для датчика
    dc++;
    if (dc > 5) break;
  }

  DScnt = dc;

  // определяем устройства на шине
#ifdef __SAMOVAR_DEBUG
  Serial.print("Locating DS18B20...");
  Serial.print("Found ");
  Serial.print(DScnt, DEC);
  Serial.println(" devices.");
#endif

#ifdef __SAMOVAR_DEBUG
  Serial.print("1 Sensor Address: ");  // пишем адрес датчика 0
  printAddress(DSAddr[0]);
  Serial.println();
  Serial.print("2 Sensor Address: ");  // пишем адрес датчика 1
  printAddress(DSAddr[1]);
  Serial.println();
  Serial.print("3 Sensor Address: ");  // пишем адрес датчика 2
  printAddress(DSAddr[2]);
  Serial.println();
  Serial.print("4 Sensor Address: ");  // пишем адрес датчика 3
  printAddress(DSAddr[3]);
  Serial.println();
  Serial.print("5 Sensor Address: ");  // пишем адрес датчика 4
  printAddress(DSAddr[4]);
  Serial.println();
  Serial.print("6 Sensor Address: ");  // пишем адрес датчика 5
  printAddress(DSAddr[5]);
  Serial.println();
#endif

  sensors.setWaitForConversion(false);  // работаем в асинхронном режиме
  sensors.requestTemperatures();
  //delay(750);

#ifdef __SAMOVAR_DEBUG
  Serial.print("1 Sensor Resolution: ");  // пишем разрешение для датчика 0
  Serial.print(sensors.getResolution(DSAddr[0]), DEC);
  Serial.println();
  Serial.print("2 Sensor Resolution: ");  // пишем разрешение для датчика 1
  Serial.print(sensors.getResolution(DSAddr[1]), DEC);
  Serial.println();
  Serial.print("3 Sensor Resolution: ");  // пишем разрешение для датчика 2
  Serial.print(sensors.getResolution(DSAddr[2]), DEC);
  Serial.println();
  Serial.print("4 Sensor Resolution: ");  // пишем разрешение для датчика 3
  Serial.print(sensors.getResolution(DSAddr[3]), DEC);
  Serial.println();
  Serial.print("5 Sensor Resolution: ");  // пишем разрешение для датчика 3
  Serial.print(sensors.getResolution(DSAddr[4]), DEC);
  Serial.println();
#endif
}

void sensor_init(void) {
#ifdef __SAMOVAR_DEBUG
  Serial.println("Pressure sensor initialization");
#endif
#ifdef BME_STRING
  writeString((String)BME_STRING + " init...     ", 3);
  delay(800);

#ifdef USE_BMP280_ALT
  if (!bme.begin(BMP280_ADDRESS_ALT, BMP280_CHIPID)) {
#else
#ifdef USE_BMP180
  if (!bme.begin(BMP085_MODE_STANDARD)) {
#else
  if (!bme.begin()) {
#endif
#endif
    writeString((String)BME_STRING + " not found     ", 3);
#ifdef __SAMOVAR_DEBUG
    Serial.println((String)BME_STRING + " not found");
#endif
    bmefound = false;
    //Serial.println(F("Could not find a valid BME680 sensor, check wiring!"));
  } else {
#ifdef USE_BME680
    // Set up oversampling and filter initialization
    bme.setTemperatureOversampling(BME680_OS_2X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
#endif

#ifdef USE_BMP280_1
    bme.setSampling(Adafruit_BMP280::MODE_FORCED,     /* Operating Mode. */
                    Adafruit_BMP280::SAMPLING_X1,     /* Temp. oversampling */
                    Adafruit_BMP280::SAMPLING_X4,     /* Pressure oversampling */
                    Adafruit_BMP280::FILTER_X2,       /* Filtering. */
                    Adafruit_BMP280::STANDBY_MS_500); /* Standby time. */

#endif
#ifdef USE_BME280_1
    bme.setSampling(Adafruit_BME280::MODE_FORCED,
                    Adafruit_BME280::SAMPLING_X1,  // temperature
                    Adafruit_BME280::SAMPLING_X4,  // pressure
                    Adafruit_BME280::SAMPLING_X1,  // humidity
                    Adafruit_BME280::FILTER_OFF);

#endif
  }
#else
  bmefound = false;
#endif

  writeString("DS1820 init...     ", 3);
  scan_ds_adress();
  writeString("Found " + (String)DScnt + "         ", 4);

  //Для шагового двигателя устанавливаем режим работы - следовать до позиции
  //  stepper.setRunMode(FOLLOW_POS);
  // установка макс. скорости в шагах/сек
  stepper.setMaxSpeed(STEPPER_MAX_SPEED);
  //stepper.setSpeed(0);
  //Драйвер выключится по достижении позиции
  stepper.autoPower(true);
#ifdef STEPPER_REVERSE
  stepper.reverse(true);
#endif

#ifdef USE_WATERSENSOR
  //Настраиваем датчик потока
  pinMode(WATERSENSOR_PIN, INPUT);
#endif

  // Загружаем программу по умолчанию для текущего режима
  load_default_program_for_mode();

#ifdef SAMOVAR_USE_SEM_AVR
  //Если SEM_AVR иницииурем порт
#ifdef __SAMOVAR_DEBUG
  Serial.println("Init SEM_AVR");
#endif
  xSemaphoreAVR = xSemaphoreCreateBinaryStatic(&xSemaphoreBufferAVR);
  xSemaphoreGive(xSemaphoreAVR);
  Serial2.setTimeout(500);
  //Serial2.setRxBufferSize(12);
  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2);
#define USE_SERIAL
#endif


#ifdef SAMOVAR_USE_RMVK
#ifndef USE_SERIAL
#ifdef __SAMOVAR_DEBUG
  Serial.println("Init RMVK");
#endif
  //Иначе работаем с RMVK
  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2);
  Serial2.end();
  RMVK_init();
#define USE_SERIAL
#endif
#endif

#ifdef SAMOVAR_USE_POWER
#ifndef USE_SERIAL
#ifdef __SAMOVAR_DEBUG
  Serial.println("Init KVIC");
#endif
  Serial2.setTimeout(300);
  Serial2.setRxBufferSize(0);
#ifdef KVIC_USE_9600
  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2);
#else
  Serial2.begin(38400, SERIAL_8N1, RXD2, TXD2);
#endif

#define USE_SERIAL
#endif
#endif


#ifdef USE_WATER_PUMP
  init_pump_pwm(WATER_PUMP_PIN, PUMP_PWM_FREQ);
  set_pump_pwm(0);
#endif

  use_pressure_sensor = false;
#ifdef USE_PRESSURE_XGZ
#ifdef __SAMOVAR_DEBUG
  Serial.println("Init pressure sensor");
#endif

  if (!pressure_sensor.begin())  // initialize and check the device
  {
    use_pressure_sensor = false;
#ifdef __SAMOVAR_DEBUG
    Serial.println("Device not responding.");
#endif
  } else use_pressure_sensor = true;

#endif

#ifdef USE_PRESSURE_MPX
  use_pressure_sensor = true;
#endif

#ifdef USE_PRESSURE_1WIRE
  use_pressure_sensor = true;
#endif

  reset_sensor_counter();
  //  regulator.hysteresis = 0.3;
  //  regulator.k = 0.3;
  //  regulator.dT = 4000;    //система инерционная, считаем скорость раз в четыре секунды
  //  regulator.setLimits(0, WindowSize);
  //  regulator.setDirection(REVERSE);
  heaterPID.SetSampleTime(1000);
  heaterPID.SetOutputLimits(0, 100);
  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
}

//Обнуляем все счетчики
void reset_sensor_counter(void) {
  sam_command_sync = SAMOVAR_NONE;
  stopService();
  stepper.setMaxSpeed(0);
  //stepper.setSpeed(0);
  stepper.brake();
  stepper.disable();
  stepper.setCurrent(0);
  stepper.setTarget(0);
  set_capacity(0);
  alarm_h_min = 0;
  alarm_t_min = 0;
  t_min = 0;
  b_t_temp_prev = 0;
  b_t_time_min = 0;
  b_t_time_delay = 0;
#ifdef SAMOVAR_USE_POWER
  alarm_c_min = 0;
  alarm_c_low_min = 0;
  prev_target_power_volt = 0;
#endif
  d_s_time_min = 0;
  d_s_temp_finish = 0;
  wetting_autostart = false;

  current_power_volt = 0.0;
  target_power_volt = 0.0;
  pressure_value = 0.0;
  old_pressure_value = 0.0;

  ProgramNum = 0;
  SteamSensor.BodyTemp = 0;
  PipeSensor.BodyTemp = 0;
  WaterSensor.BodyTemp = 0;
  TankSensor.BodyTemp = 0;
  ACPSensor.BodyTemp = 0;
  SteamSensor.PrevTemp = 0;
  PipeSensor.PrevTemp = 0;
  WaterSensor.PrevTemp = 0;
  TankSensor.PrevTemp = 0;
  ACPSensor.PrevTemp = 0;


  ActualVolumePerHour = 0;
  SamovarStatusInt = 0;
  startval = 0;
  PauseOn = false;
  program_Wait = false;
  SteamSensor.Start_Pressure = 0;
  WthdrwlProgress = 0;
  TargetStepps = 0;
  I2CPumpTargetSteps = 0;
  I2CPumpTargetMl = 0;
  I2CPumpCmdSpeed = 0;
  I2CPumpCalibrating = false;

  begintime = 0;

  d_s_temp_prev = 0;
  is_self_test = false;

  if (fileToAppend) {
    fileToAppend.close();
  }

  if (bme_pressure < 100) BME_getvalue(false);
  start_pressure = bme_pressure;

  boil_started = false;
  boil_temp = 0;
  alcohol_s = 0;
  b_t_time_delay = 0;

  if (xSemaphore != NULL) xSemaphoreGive(xSemaphore);
#ifdef SAMOVAR_USE_SEM_AVR
  if (xSemaphoreAVR != NULL) xSemaphoreGive(xSemaphoreAVR);
#endif

  set_power(false);
  sam_command_sync = SAMOVAR_NONE;
  get_Samovar_Status();

  bk_pwm = PWM_LOW_VALUE * 40;

#ifdef SAMOVAR_USE_POWER
  power_err_cnt = 0;
#endif

#ifdef USE_LUA
  Lua_status = "";
#endif
}

inline String format_float(float v, int d) {
  char outstr[15];
  dtostrf(v, 1, d, outstr);
  return outstr;
}

void printAddress(DeviceAddress deviceAddress)  // функция печати адреса DS18B20
{
  Serial.print(getDSAddress(deviceAddress));
}

String getDSAddress(DeviceAddress deviceAddress) {
  String dsaddr;
  for (uint8_t j = 0; j < 8; j++) {
    if (deviceAddress[j] < 16) dsaddr += "0";
    dsaddr += String(deviceAddress[j], HEX);
  }
  return dsaddr;
}

String get_DSAddressList(String Address) {
  String s = "<option value='-1'>NONE</option>";
  String dsaddr = "";
  for (uint8_t i = 0; i != DScnt; i++) {
    dsaddr = getDSAddress(DSAddr[i]);
    s += "<option value='" + String(i) + "'";
    if (Address == dsaddr) s = s + " " + "selected";
    s = s + ">" + dsaddr + "</option>";
  }
  return s;
}

void CopyDSAddress(const uint8_t* DevSAddress, uint8_t* DevTAddress) {
  for (uint8_t dsj = 0; dsj < 8; dsj++) {
    DevTAddress[dsj] = DevSAddress[dsj];
  }
}
#endif

#ifndef GET_TASK_STACK_USAGE_DEFINED
#define GET_TASK_STACK_USAGE_DEFINED

// Функция для вывода статистики использования стека задачами FreeRTOS
// Помогает оптимизировать размеры стеков и выявлять проблемы переполнения
void get_task_stack_usage() {

  // Выводим статистику использования стека задачами
  Serial.println(F("=== Task Stack Usage ==="));
  Serial.printf("SysTicker:        %u words free (of 3200)\n", uxTaskGetStackHighWaterMark(SysTickerTask1));
  Serial.printf("GetClock:         %u words free (of 3400)\n", uxTaskGetStackHighWaterMark(GetClockTask1));
#ifdef USE_LUA
  if (DoLuaScriptTask) {
    Serial.printf("LuaScript:        %u words free (of 5900)\n", uxTaskGetStackHighWaterMark(DoLuaScriptTask));
  }
#endif
#ifdef SAMOVAR_USE_POWER
  Serial.printf("PowerStatus:      %u words free (of 1800)\n", uxTaskGetStackHighWaterMark(PowerStatusTask));
#endif
  Serial.println(F("========================"));
}

#endif // GET_TASK_STACK_USAGE_DEFINED
