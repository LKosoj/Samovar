#ifdef USE_BME680
  Adafruit_BME680 bme; // I2C
#endif

#ifdef USE_BMP180
Adafruit_BMP085_Unified bme; // I2C
#endif

#ifdef USE_BMP280
Adafruit_BMP280 bme; // I2C
#endif

void clok();
void clok1();
void getjson (void);
void append_data();
void stopService(void);
void startService(void);

//**************************************************************************************************************
// Функции для работы с сенсорами
//**************************************************************************************************************

void printAddress(DeviceAddress deviceAddress);
void reset_sensor_counter(void);

//***************************************************************************************************************
// считываем параметры с датчика BME680
//***************************************************************************************************************
void IRAM_ATTR BME_getvalue(bool fl) {
  //bme_pressure = 767;
  //bme_temp = 25;
  //return;
  
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
  vTaskDelay(5);
  bme_pressure = bme.pressure / 100 * 0.75;
  vTaskDelay(5);
  //bme_humidity = bme.humidity;
  //vTaskDelay(5);

  //filtered_val += (val - filtered_val) * 0.01;
#endif

#ifdef USE_BMP180
  sensors_event_t event;
  bme.getEvent(&event);
  if (event.pressure){
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
  static float ss, ps, ws, ts;
  ss = sensors.getTempC(SteamSensor.Sensor);                   // считываем температуру с датчика 0
  vTaskDelay(10);
  ps = sensors.getTempC(PipeSensor.Sensor);                     // считываем температуру с датчика 1
  vTaskDelay(10);
  ws = sensors.getTempC(WaterSensor.Sensor);                   // считываем температуру с датчика 2
  vTaskDelay(10);
  ts = sensors.getTempC(TankSensor.Sensor);                     // считываем температуру с датчика 3
  vTaskDelay(10);

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

void IRAM_ATTR triggerGetTempSensor(void) {
  clok();
  DS_getvalue();
}

void IRAM_ATTR triggerGetSensor(void) {
  clok1();
  if (startval > 0) {
    append_data();              //Записываем данные;
  }
}

void sensor_init(void) {
  Serial.println("Pressure sensor initialization");
  writeString((String)BME_STRING + " init...     ", 3);
  delay(1000);

  if (!bme.begin()) {
    writeString((String)BME_STRING + " not found     ", 3);
    Serial.println((String)BME_STRING + " not found");
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
  sensors.begin();                                                        // стартуем датчики температуры
  delay(4000);
  // определяем устройства на шине
#ifdef __SAMOVAR_DEBUG
  Serial.print("Locating DS18B20...");
  Serial.print("Found ");
  Serial.print(sensors.getDeviceCount(), DEC);
  Serial.println(" devices.");
#endif

  // Инициализируем датчики температуры

  if (!sensors.getAddress(SteamSensor.Sensor, 0))
  {
    Serial.println("Unable to find address for Device 0");  // если адрес датчика 0 не найден
  }
  if (!sensors.getAddress(PipeSensor.Sensor, 1))
  {
    Serial.println("Unable to find address for Device 1");  // если адрес датчика 1 не найден
  }
  if (!sensors.getAddress(WaterSensor.Sensor, 2))
  {
    Serial.println("Unable to find address for Device 2");  // если адрес датчика 2 не найден
  }
  if (!sensors.getAddress(TankSensor.Sensor, 3))
  {
    Serial.println("Unable to find address for Device 3");  // если адрес датчика 3 не найден
  }

  writeString("Found " + (String)sensors.getDeviceCount() + "         ", 4);

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
  stepper.setMaxSpeed(STEPPER_MAX_SPEED);
  stepper.setSpeed(0);
  //Драйвер выключится по достижении позиции
  stepper.autoPower(true);
  //stepper.setAcceleration(500);

#ifdef USE_WATERSENSOR
  //Настраиваем датчик потока
  pinMode(WATERSENSOR_PIN, INPUT);
  digitalWrite(WATERSENSOR_PIN, HIGH);
#endif

//  set_program("H;3;1;1;0;160\nB;5;2;1;0;160\nH;6;3;1;0;160\n");
  set_program("H;450;0.1;1;0;160\nB;450;1;1;0;160\nH;450;0.1;1;0;160\n");

  reset_sensor_counter();

#ifdef SAMOVAR_USE_POWER
  Serial2.begin(38400, SERIAL_8N1, RXD2, TXD2);
  Serial2.setRxBufferSize(20);
#endif
}

void printAddress(DeviceAddress deviceAddress)                        // функция печати адреса DS18B20
{
  for (uint8_t i = 0; i < 8; i++)
  {
    if (deviceAddress[i] < 16) Serial.print("0");                     // вставляем незначащие нули
    Serial.print(deviceAddress[i], HEX);
  }
}

//Обнуляем все счетчики
void reset_sensor_counter(void) {
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
  WthdrwlProgress = 0;
  PauseOn = false;
  program_Wait = false;
  SteamSensor.Start_Pressure = 0;
  SteamSensor.BodyTemp = 0;

  if (fileToAppend) {
    fileToAppend.close();
  }

  bme_pressure = 0;
  BME_getvalue(false);
  start_pressure = bme_pressure;
  get_Samovar_Status();

  WFtotalMilliLitres = 0;
}

String inline format_float(float v, int d) {
  char outstr[15];
  return (String)dtostrf(v, 1, d, outstr);
}
