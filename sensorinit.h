void clok();
void clok1();
void getjson (void);
void append_data();

//**************************************************************************************************************
// Функции для работы с сенсорами
//**************************************************************************************************************

void printAddress(DeviceAddress deviceAddress);
void reset_sensor_counter(void);

//***************************************************************************************************************
// считываем параметры с датчика BME680
//***************************************************************************************************************
void IRAM_ATTR BME_getvalue(bool fl){
  if (!bmefound) {
    bme_temp = -1;
    bme_pressure = -1;
    return;
  }
  // Tell BME680 to begin measurement.
  unsigned long bmeEndTime = bme.beginReading();

  if (!bme.endReading()) {
    return;
  }

    bme_temp = bme.temperature;
    vTaskDelay(2);
    bme_pressure = bme.pressure / 100.0 * 0.75;
    vTaskDelay(2);
    bme_humidity = bme.humidity;
    vTaskDelay(2); 
}

//***************************************************************************************************************
// считываем температуры с датчиков DS18B20
//***************************************************************************************************************
void IRAM_ATTR DS_getvalue(void){
  float ss, ps, ws, ts;
  ss = sensors.getTempC(SteamSensor.Sensor);                   // считываем температуру с датчика 0
  vTaskDelay(80);
  ps = sensors.getTempC(PipeSensor.Sensor);                     // считываем температуру с датчика 1
  vTaskDelay(80);
  ws = sensors.getTempC(WaterSensor.Sensor);                   // считываем температуру с датчика 2
  vTaskDelay(80);
  ts = sensors.getTempC(TankSensor.Sensor);                     // считываем температуру с датчика 3
  vTaskDelay(80);

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

void IRAM_ATTR triggerGetTempSensor(void){
      clok();
      DS_getvalue();
}

void IRAM_ATTR triggerGetSensor(void){
      clok1();
      if (startval > 0) {
          append_data();              //Записываем данные;
      }
}

void sensor_init(void){
  Serial.println("Pressure sensor initialization");
  writeString("Bme680 init...     ", 3);
  delay(1000);

  if (!bme.begin()) {
    writeString("Bme680 not found     ", 3);
    bmefound = false;
    //Serial.println(F("Could not find a valid BME680 sensor, check wiring!"));
  }

  // Set up oversampling and filter initialization
  bme.setTemperatureOversampling(BME680_OS_8X);
  bme.setHumidityOversampling(BME680_OS_2X);
  bme.setPressureOversampling(BME680_OS_4X);
  bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
    
  writeString("DS1820 init...     ", 3);
  sensors.begin();                                                        // стартуем датчики температуры
  delay(4000);
  writeString("Found " + (String)sensors.getDeviceCount() + "         ", 4);
  //delay(1000);
                                                                          // определяем устройства на шине
  Serial.print("Locating DS18B20...");
  Serial.print("Found ");
  Serial.print(sensors.getDeviceCount(), DEC);
  Serial.println(" devices.");
 
  // Инициализируем датчики температуры
  
  if (!sensors.getAddress(SteamSensor.Sensor, 0))
   { Serial.println("Unable to find address for Device 0"); }             // если адрес датчика 0 не найден
  if (!sensors.getAddress(PipeSensor.Sensor, 1))
   { Serial.println("Unable to find address for Device 1"); }             // если адрес датчика 1 не найден
  if (!sensors.getAddress(WaterSensor.Sensor, 2))
   { Serial.println("Unable to find address for Device 2"); }             // если адрес датчика 2 не найден
  if (!sensors.getAddress(TankSensor.Sensor, 3))
   { Serial.println("Unable to find address for Device 3"); }             // если адрес датчика 3 не найден

  sensors.setWaitForConversion(false);                                    // работаем в асинхронном режиме
  sensors.requestTemperatures();

#ifdef __SAMOVAR_DEBUG
  Serial.print("SteamSensor Address: ");                                  // пишем адрес датчика 0
  printAddress(SteamSensor.Sensor);
  Serial.println();
  Serial.print("PipeSensor Address: ");                                   // пишем адрес датчика 1
  printAddress(PipeSensor.Sensor);
  Serial.println();
  Serial.print("WaterSensor Address: ");                                  // пишем адрес датчика 2
  printAddress(WaterSensor.Sensor);
  Serial.println();
  Serial.print("TankSensor Address: ");                                  // пишем адрес датчика 3
  printAddress(TankSensor.Sensor);
  Serial.println(); 
#endif
 
 sensors.setResolution(SteamSensor.Sensor, 12);                                 // устанавливаем разрешение для датчика 0
 sensors.setResolution(PipeSensor.Sensor, 12);                                  // устанавливаем разрешение для датчика 1
 sensors.setResolution(WaterSensor.Sensor, 12);                                 // устанавливаем разрешение для датчика 2
 sensors.setResolution(TankSensor.Sensor, 12);                                  // устанавливаем разрешение для датчика 3
 
#ifdef __SAMOVAR_DEBUG
 Serial.print("SteamSensor Resolution: ");                               // пишем разрешение для датчика 0
 Serial.print(sensors.getResolution(SteamSensor.Sensor), DEC); 
 Serial.println();
 Serial.print("PipeSensor Resolution: ");                                // пишем разрешение для датчика 1
 Serial.print(sensors.getResolution(PipeSensor.Sensor), DEC); 
 Serial.println();
 Serial.print("WaterSensor Resolution: ");                               // пишем разрешение для датчика 2
 Serial.print(sensors.getResolution(WaterSensor.Sensor), DEC); 
 Serial.println();
 Serial.print("TankSensor Resolution: ");                                // пишем разрешение для датчика 3
 Serial.print(sensors.getResolution(TankSensor.Sensor), DEC); 
 Serial.println();
#endif

 //Для шагового двигателя устанавливаем режим работы - следовать до позиции
 stepper.setRunMode(FOLLOW_POS);
 // установка макс. скорости в шагах/сек
 stepper.setMaxSpeed(0);
 //Драйвер выключится по достижении позиции
 stepper.autoPower(true);
 stepper.setAcceleration(500);

 set_program("H;450;0.1;1;0;0\nP;120;0;0;0;0;\nB;5000;0.75;2;0;0\nB;5000;0.75;3;0;0\nB;5000;0.75;4;0;0\nB;5000;0.75;5;0;0\nB;5000;0.75;6;0;0\nB;5000;0.75;7;0;0\nB;5000;0.75;8;0;0\nB;5000;0.75;9;0;0\nB;5000;0.75;10;0;0\n");

 reset_sensor_counter();

#ifdef SAMOVAR_USE_POWER
 Serial2.begin(38400, SERIAL_8N1, RXD2, TXD2);
 Serial2.setRxBufferSize(20);
#endif
}

void printAddress(DeviceAddress deviceAddress)                          // функция печати адреса DS18B20
{ 
  for (uint8_t i = 0; i < 8; i++)
    { 
      if (deviceAddress[i] < 16) Serial.print("0");                     // вставляем незначащие нули
      Serial.print(deviceAddress[i], HEX); 
    }
}

//Обнуляем все счетчики
void reset_sensor_counter(void){
  stepper.setSpeed(-1);
  stepper.setMaxSpeed(-1);
  stepper.brake();
  stepper.disable();
  stepper.setCurrent(0);
  stepper.setTarget(0);
  set_capacity(0);
  
  ProgramNum = 0;
  SteamSensor.BodyTemp = 0;
  PipeSensor.BodyTemp = 0;
  WaterSensor.BodyTemp = 0;
  TankSensor.BodyTemp = 0;
  ActualVolumePerHour = 0;
  startval = 0;
  WthdrwlProgress = 0;
  PauseOn = false;
  program_Wait = false;

  if (fileToAppend) {
    fileToAppend.close();
  }

  BME_getvalue(false);
  start_pressure = bme_pressure;
  get_Samovar_Status();
}

String inline format_float(float v, int d){
  char outstr[15];
  return (String)dtostrf(v,1, d, outstr);
}
