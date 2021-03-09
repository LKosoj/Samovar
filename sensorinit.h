#include <Arduino.h>
#include <DallasTemperature.h>
#include "Samovar.h"

#ifdef USE_BME680
#define BME_STRING "BME680"
#include <Adafruit_BME680.h>
Adafruit_BME680 bme; // I2C
#endif

#ifdef USE_BMP180
#include <Adafruit_BMP085_U.h>
#define BME_STRING "BMP180"
Adafruit_BMP085_Unified bme; // I2C
#endif

#ifdef USE_BMP280
#include <Adafruit_BMP280.h>
#define BME_STRING "BMP280"
Adafruit_BMP280 bme; // I2C
#endif

void clok();
void clok1();
void getjson (void);
void append_data();
void stopService(void);
void startService(void);
void CopyDSAddress(uint8_t* DevSAddress, uint8_t* DevTAddress);
String getDSAddress(DeviceAddress deviceAddress);

//**************************************************************************************************************
// Функции для работы с сенсорами
//**************************************************************************************************************

void printAddress(DeviceAddress deviceAddress);
void reset_sensor_counter(void);

//***************************************************************************************************************
// считываем параметры с датчика BME680
//***************************************************************************************************************
void IRAM_ATTR BME_getvalue(bool fl) {
  if (!bmefound) {
    bme_temp = -1;
    bme_pressure = -1;
    return;
  }

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
    float temperature;
    bme.getTemperature(&temperature);
    bme_temp = temperature;
  }
#endif

#ifdef USE_BMP280
  bme_temp = bme.readTemperature();
  bme_pressure = bme.readPressure() / 100 * 0.75;
#endif

}

//***************************************************************************************************************
// считываем температуры с датчиков DS18B20
//***************************************************************************************************************
void IRAM_ATTR DS_getvalue(void) {
  //return;
  float ss, ps, ws, ts;
  ss = sensors.getTempC(SteamSensor.Sensor);                   // считываем температуру с датчика 0
  ps = sensors.getTempC(PipeSensor.Sensor);                     // считываем температуру с датчика 1
  ws = sensors.getTempC(WaterSensor.Sensor);                   // считываем температуру с датчика 2
  ts = sensors.getTempC(TankSensor.Sensor);                     // считываем температуру с датчика 3

  //return;
  sensors.requestTemperatures();

  if (ss != -127) {
    SteamSensor.avgTemp = ss + SamSetup.DeltaSteamTemp;
  }
  if (ps != -127) {
    PipeSensor.avgTemp = ps + SamSetup.DeltaPipeTemp;
  }
  if (ws != -127) {
    WaterSensor.avgTemp = ws + SamSetup.DeltaWaterTemp;
  }
  if (ts != -127) {
    TankSensor.avgTemp = ts + SamSetup.DeltaTankTemp;
  }
}

void sensor_init(void) {
#ifdef __SAMOVAR_DEBUG
  Serial.println("Pressure sensor initialization");
#endif
  writeString((String)BME_STRING + " init...     ", 3);
  delay(1000);

  if (!bme.begin()) {
    writeString((String)BME_STRING + " not found     ", 3);
#ifdef __SAMOVAR_DEBUG
    Serial.println((String)BME_STRING + " not found");
#endif
    bmefound = false;
    //Serial.println(F("Could not find a valid BME680 sensor, check wiring!"));
  } else {
#ifdef USE_BME680
    // Set up oversampling and filter initialization
    bme.setTemperatureOversampling(BME680_OS_8X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
#endif
  }

  writeString("DS1820 init...     ", 3);
  sensors.begin();                          // стартуем датчики температуры
  delay(800);
  int dc =0;
  while(sensors.getDeviceCount() == 0) {
    delay(800);
    dc++;
    if (dc > 10) break;
  }

  for(int i=0;i!=sensors.getDeviceCount();i++) {
    sensors.getAddress(DSAddr[i], i);
  }

  // определяем устройства на шине
#ifdef __SAMOVAR_DEBUG
  Serial.print("Locating DS18B20...");
  Serial.print("Found ");
  Serial.print(sensors.getDeviceCount(), DEC);
  Serial.println(" devices.");
#endif

  // // Инициализируем датчики температуры
  // CopyDSAddress(DSAddr[0], SteamSensor.Sensor);
  // CopyDSAddress(DSAddr[1], PipeSensor.Sensor);
  // CopyDSAddress(DSAddr[2], WaterSensor.Sensor);
  // CopyDSAddress(DSAddr[3], TankSensor.Sensor);

  writeString("Found " + (String)sensors.getDeviceCount() + "         ", 4);

#ifdef __SAMOVAR_DEBUG
  Serial.print("1 Sensor Address: ");                                  // пишем адрес датчика 0
  printAddress(DSAddr[0]);
  Serial.println();
  Serial.print("2 Sensor Address: ");                                   // пишем адрес датчика 1
  printAddress(DSAddr[1]);
  Serial.println();
  Serial.print("3 Sensor Address: ");                                  // пишем адрес датчика 2
  printAddress(DSAddr[2]);
  Serial.println();
  Serial.print("4 Sensor Address: ");                                  // пишем адрес датчика 3
  printAddress(DSAddr[3]);
  Serial.println();
#endif

  sensors.setResolution(DSAddr[0], 12);                                 // устанавливаем разрешение для датчика 0
  sensors.setResolution(DSAddr[1], 12);                                  // устанавливаем разрешение для датчика 1
  sensors.setResolution(DSAddr[2], 12);                                 // устанавливаем разрешение для датчика 2
  sensors.setResolution(DSAddr[3], 12);                                  // устанавливаем разрешение для датчика 3

  sensors.setWaitForConversion(false);                                    // работаем в асинхронном режиме
  sensors.requestTemperatures();
  delay(750);

#ifdef __SAMOVAR_DEBUG
  Serial.print("1 Sensor Resolution: ");                               // пишем разрешение для датчика 0
  Serial.print(sensors.getResolution(DSAddr[0]), DEC);
  Serial.println();
  Serial.print("2 Sensor Resolution: ");                                // пишем разрешение для датчика 1
  Serial.print(sensors.getResolution(DSAddr[1]), DEC);
  Serial.println();
  Serial.print("3 Sensor Resolution: ");                               // пишем разрешение для датчика 2
  Serial.print(sensors.getResolution(DSAddr[2]), DEC);
  Serial.println();
  Serial.print("4 Sensor Resolution: ");                                // пишем разрешение для датчика 3
  Serial.print(sensors.getResolution(DSAddr[3]), DEC);
  Serial.println();
#endif

  //Для шагового двигателя устанавливаем режим работы - следовать до позиции
  stepper.setRunMode(FOLLOW_POS);
  // установка макс. скорости в шагах/сек
  stepper.setMaxSpeed(STEPPER_MAX_SPEED);
  stepper.setSpeed(0);
  //Драйвер выключится по достижении позиции
  stepper.autoPower(true);

#ifdef USE_WATERSENSOR
  //Настраиваем датчик потока
  pinMode(WATERSENSOR_PIN, INPUT);
  digitalWrite(WATERSENSOR_PIN, HIGH);
#endif

  //  set_program("H;3;1;1;0;45\nB;5;2;1;0;45\nH;6;3;1;0;45\n");
  set_program("H;450;0.1;1;0;45\nB;450;1;1;0;45\nH;450;0.1;1;0;45\n");

  reset_sensor_counter();

#ifdef SAMOVAR_USE_POWER
  Serial2.begin(38400, SERIAL_8N1, RXD2, TXD2);
  Serial2.setRxBufferSize(20);
#endif
}

//Обнуляем все счетчики
void IRAM_ATTR reset_sensor_counter(void) {
#ifdef SAMOVAR_USE_POWER
  set_power_mode(POWER_SLEEP_MODE);
#endif

  stopService();
  stepper.setMaxSpeed(-1);
  stepper.setSpeed(-1);
  stepper.brake();
  stepper.disable();
  stepper.setCurrent(0);
  stepper.setTarget(0);
  set_capacity(0);
  alarm_h_min = 0;
  alarm_t_min = 0;

  ProgramNum = 0;
  SteamSensor.BodyTemp = 0;
  PipeSensor.BodyTemp = 0;
  WaterSensor.BodyTemp = 0;
  TankSensor.BodyTemp = 0;
  ActualVolumePerHour = 0;
  startval = 0;
  PauseOn = false;
  program_Wait = false;
  SteamSensor.Start_Pressure = 0;
  SteamSensor.BodyTemp = 0;
  WFtotalMilliLitres = 0;
  WthdrwlProgress = 0;
  TargetStepps = 0;
  Msg = "";  

  if (fileToAppend) {
    fileToAppend.close();
  }

  bme_pressure = 0;
  BME_getvalue(false);
  start_pressure = bme_pressure;
  get_Samovar_Status();
}

String inline format_float(float v, int d) {
  char outstr[15];
  return (String)dtostrf(v, 1, d, outstr);
}

void printAddress(DeviceAddress deviceAddress)                        // функция печати адреса DS18B20
{
  Serial.print(getDSAddress(deviceAddress));
}

String getDSAddress(DeviceAddress deviceAddress){
  String dsaddr;
    for (uint8_t j = 0; j < 8; j++)
    {
      if (deviceAddress[j] < 16) dsaddr += "0";
      dsaddr += String(deviceAddress[j], HEX);
    }
  return dsaddr;  
}

String get_DSAddressList(String Address){
  String s = "<option value='-1'>NONE</option>";
  String dsaddr = "";
  for (int i = 0;i!=sensors.getDeviceCount();i++){
    dsaddr = getDSAddress(DSAddr[i]);
    s += "<option value='" + String(i) + "'";
    if (Address == dsaddr) s = s + " " + "selected";
    s = s + ">" + dsaddr + "</option>";
  }
  return s;
}

void IRAM_ATTR CopyDSAddress(uint8_t* DevSAddress, uint8_t* DevTAddress){
  for (int dsj=0 ; dsj<8 ; dsj++ )
  {
   DevTAddress[dsj] = DevSAddress[dsj] ;
  }
}