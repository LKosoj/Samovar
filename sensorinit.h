void clok();
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
void BME_getvalue(void){
  if (!bmefound) {
    bme_pressure = (float)random(76000,77000)/100;
    return;
  }
  bme_temp = bme.temperature;
  bme_pressure = bme.pressure * 0.0075;
  bme_humidity = bme.humidity;
  bme_gas = bme.gas_resistance / 1000.0;
  bme_altitude = bme.readAltitude(SEALEVELPRESSURE_HPA);
}

//***************************************************************************************************************
// считываем температуры с датчиков DS18B20
//***************************************************************************************************************
void DS_getvalue(void){
  sensors.requestTemperatures();                               // запрашиваем температуру у всех датчиков
  float ss, ps, ws, ts;
  ss = sensors.getTempC(SteamSensor.Sensor);                   // считываем температуру с датчика 0
  ps = sensors.getTempC(PipeSensor.Sensor);                     // считываем температуру с датчика 1
  ws = sensors.getTempC(WaterSensor.Sensor);                   // считываем температуру с датчика 2
  ts = sensors.getTempC(TankSensor.Sensor);                     // считываем температуру с датчика 3

  ss = (float)random(7600,8000)/100;
  ps = (float)random(7500,7800)/100;
  ws = (float)random(5000,5500)/100;
  ts = (float)random(8500,9000)/100;
  
  if (ss != -127) {
    SteamSensor.Temp = ss + SamSetup.DeltaSteamTemp;
    SteamSensor.avgTempAccumulator += SteamSensor.Temp;
    SteamSensor.avgTempReadings+=1;
    SteamSensor.avgTemp = SteamSensor.avgTempAccumulator / SteamSensor.avgTempReadings;
    if (SteamSensor.avgTempReadings >= TEMP_AVG_READING) {
        SteamSensor.avgTempAccumulator /= 2;
        SteamSensor.avgTempReadings /= 2;
      }
  }
  if (ps != -127) {
    PipeSensor.Temp = ps + SamSetup.DeltaPipeTemp;
    PipeSensor.avgTempAccumulator += PipeSensor.Temp;
    PipeSensor.avgTempReadings+=1;
    PipeSensor.avgTemp = PipeSensor.avgTempAccumulator / PipeSensor.avgTempReadings;
    if (PipeSensor.avgTempReadings >= TEMP_AVG_READING) {
        PipeSensor.avgTempAccumulator /= 2;
        PipeSensor.avgTempReadings /= 2;
      }
  }
  if (ws != -127) {
    WaterSensor.Temp = ws + SamSetup.DeltaWaterTemp;
    WaterSensor.avgTemp = WaterSensor.Temp;
/*    
    WaterSensor.avgTempAccumulator += WaterSensor.Temp;
    WaterSensor.avgTempReadings+=1;
    WaterSensor.avgTemp = WaterSensor.avgTempAccumulator / WaterSensor.avgTempReadings;
    if (WaterSensor.avgTempReadings >= TEMP_AVG_READING) {
        WaterSensor.avgTempAccumulator /= 2;
        WaterSensor.avgTempReadings /= 2;
      }
*/
  }
  if (ws != -127) {
    TankSensor.Temp = ts + SamSetup.DeltaTankTemp;
    TankSensor.avgTemp = TankSensor.Temp;
/*    
     
    TankSensor.avgTempAccumulator += TankSensor.Temp;
    TankSensor.avgTempReadings+=1;
    TankSensor.avgTemp = TankSensor.avgTempAccumulator / TankSensor.avgTempReadings;
    if (TankSensor.avgTempReadings >= TEMP_AVG_READING) {
        TankSensor.avgTempAccumulator /= 2;
        TankSensor.avgTempReadings /= 2;
      }
*/
  }
}

void triggerGetSensor(void){
      BME_getvalue();
      DS_getvalue();
      clok();
      vTaskDelay(10);

      if (startval > 0) {
        countToAppend++;
        if (countToAppend > SAMOVAR_LOG_PERIOD){
          append_data();              //Записываем данные;
          countToAppend = 0;
        }
      }
      vTaskDelay(10);
}

void sensor_init(void){
  Serial.println("Pressure sensor initialization");
  writeString("Bme680 init...     ", 3);
  delay(1000);


  if (!bme.begin()) {
    Serial.println("Could not find a valid BME680 sensor, check wiring!");
    writeString("Bme680 not found", 4);
    delay(2000);
    bmefound = false;
  }
  else {
    writeString("Successful       ", 4);
    delay(1000);
  }

  writeString("DS1820 init...     ", 3);
  delay(1000);
  sensors.begin();                                                        // стартуем датчики температуры
  delay(1000);
  writeString("Found " + (String)sensors.getDeviceCount() + "         ", 4);
  delay(1000);

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
  stepper.disable();
  stepper.setCurrent(0);
  stepper.setTarget(0);
  
  BME_getvalue();
  start_pressure = bme_pressure;

  if (fileToAppend) {
    fileToAppend.close();
  }
  current_v_m_count = 0;
  //ActualVolumePerHour = get_liguid_rate_by_step(CurrrentStepperSpeed);
  for (int i=0;i++;i<21) LiquidVolume[i] = 0;
  LiquidVolumeAll = 0;
  startval = 0;
  WthdrwlProgress = 0;
  countToAppend = 0;
  SteamSensor.avgTempAccumulator=0;
  PipeSensor.avgTempAccumulator=0;
  WaterSensor.avgTempAccumulator=0;
  TankSensor.avgTempAccumulator=0;
  SteamSensor.avgTempReadings=0;
  PipeSensor.avgTempReadings=0;
  WaterSensor.avgTempReadings=0;
  TankSensor.avgTempReadings=0;
  SteamSensor.avgTemp=-127;
  PipeSensor.avgTemp=-127;
  WaterSensor.avgTemp=-127;
  TankSensor.avgTemp=-127;
  SteamSensor.Temp=-127;
  PipeSensor.Temp=-127;
  WaterSensor.Temp=-127;
  TankSensor.Temp=-127;
  get_Samovar_Status();
  PauseOn = false;

  
  for (int i=0;i++;i<4)
    for (int j=0;j++;j<80000)
      TempArray[i][j] = 0;
}

String format_float(float v, int d){
  char outstr[15];
  return (String)dtostrf(v,1, d, outstr);
}
