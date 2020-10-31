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
void BME_getvalue(bool fl){
  ClosedCube_BME680_Status status = bme680.readStatus();
//  Serial.print("status: (");
//  Serial.print(status.newDataFlag);
//  Serial.print(",");
//  Serial.print(status.measuringStatusFlag);
//  Serial.print(",");
//  Serial.print(status.gasMeasuringStatusFlag);
//  Serial.print(",");
//  Serial.print(status.gasMeasurementIndex);
//  Serial.println(") (newDataFlag,StatusFlag,GasFlag,GasIndex)");

  if (status.newDataFlag || fl) {
    bme_temp = bme680.readTemperature();
    bme_pressure = bme680.readPressure() * 0.75;
    bme_humidity = bme680.readHumidity();
    bme680.setForcedMode();
  }  
}

//***************************************************************************************************************
// считываем температуры с датчиков DS18B20
//***************************************************************************************************************
void DS_getvalue(void){
  float ss, ps, ws, ts;
  ss = sensors.getTempC(SteamSensor.Sensor);                   // считываем температуру с датчика 0
  vTaskDelay(100);
  ps = sensors.getTempC(PipeSensor.Sensor);                     // считываем температуру с датчика 1
  vTaskDelay(100);
  ws = sensors.getTempC(WaterSensor.Sensor);                   // считываем температуру с датчика 2
  vTaskDelay(100);
  ts = sensors.getTempC(TankSensor.Sensor);                     // считываем температуру с датчика 3
  vTaskDelay(100);

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
  if (ws != -127) {
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

  bme680.init(0x77); // I2C address: 0x76 or 0x77
  bme680.reset();
  bme680.setGasOff();
  // oversampling: humidity = x1, temperature = x1, pressure = x2
  bme680.setOversampling(BME680_OVERSAMPLING_X1, BME680_OVERSAMPLING_X1, BME680_OVERSAMPLING_X2);
  bme680.setIIRFilter(BME680_FILTER_3);
  bme680.setForcedMode();
  
  writeString("DS1820 init...     ", 3);
  sensors.begin();                                                        // стартуем датчики температуры
  delay(3000);
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
 stepper.setAcceleration(0);

 reset_sensor_counter(); 
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

  //bme.performReading();
  //start_pressure = bme.pressure * 0.0075;
  start_pressure = 0;

  if (fileToAppend) {
    fileToAppend.close();
  }
  current_v_m_count = 0;
  ActualVolumePerHour = 0;
  for (int i=0;i++;i<21) LiquidVolume[i] = 0;
  LiquidVolumeAll = 0;
  startval = 0;
  WthdrwlProgress = 0;
  SteamSensor.avgTempAccumulator=0;
  PipeSensor.avgTempAccumulator=0;
  WaterSensor.avgTempAccumulator=0;
  TankSensor.avgTempAccumulator=0;
  SteamSensor.avgTempReadings=0;
  PipeSensor.avgTempReadings=0;
  WaterSensor.avgTempReadings=0;
  TankSensor.avgTempReadings=0;
  get_Samovar_Status();
  PauseOn = false;

  
  for (int i=0;i++;i<4)
    for (int j=0;j++;j<80000)
      TempArray[i][j] = 0;
}

String inline format_float(float v, int d){
  char outstr[15];
  return (String)dtostrf(v,1, d, outstr);
}
