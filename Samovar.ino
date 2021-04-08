//**************************************************************************************************************
// Подключение библиотек
//**************************************************************************************************************

#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_Sensor.h>
#include <ArduinoJson.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <ESPmDNS.h>
#include <Update.h>
#include <LiquidMenu.h>
#include <EEPROM.h>
#include <SPIFFS.h>
#include <SPIFFSEditor.h>
#include <ESPAsyncWiFiManager.h>


#define DRIVER_STEP_TIME 1
#include <GyverEncoder.h>

#include <GyverStepper.h>
#include <GyverButton.h>

#include <ESP32Servo.h>

#include "Samovar.h"

#ifdef USE_BME680
#include <Adafruit_BME680.h>
#endif

#ifdef USE_BMP180
#include <Adafruit_BMP085_U.h>
#endif

#ifdef USE_BMP280
#include <Adafruit_BMP280.h>
#endif

#ifdef USE_BME280
#include <Adafruit_BME280.h>
#endif

#include "font.h"
#include "logic.h"

#ifdef USE_UPDATE_OTA
#include <ArduinoOTA.h>
#endif

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial
//#define BLYNK_TIMEOUT_MS 888
//#define BLYNK_HEARTBEAT 17

#include <BlynkSimpleEsp32.h>
#endif

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#include "distiller.h"
#include "beer.h"

//**************************************************************************************************************
// Инициализация сенсоров и функции работы с сенсорами
//**************************************************************************************************************
#include "sensorinit.h"

hw_timer_t * timer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;

void setupMenu();
void WebServerInit(void);
void encoder_getvalue();
void menu_calibrate();
void set_body_temp();
String millis2time();
String CurrentTime(void);
void distiller_finish();
void beer_finish();
void change_samovar_mode();

#ifdef USE_WEB_SERIAL
void recvMsg(uint8_t *data, size_t len) {
  WebSerial.println("Received Data...");
  String d = "";
  for (int i = 0; i < len; i++) {
    d += char(data[i]);
  }
  WebSerial.println(d);
}
#endif

void stopService(void) {
  timerAlarmDisable(timer);
}

void startService(void) {
  timerAlarmWrite(timer, stepper.stepTime, true);
  timerAlarmEnable(timer);
}

void IRAM_ATTR StepperTicker(void) {
  portENTER_CRITICAL_ISR(&timerMux);
  StepperMoving = stepper.quicktick();
  portEXIT_CRITICAL_ISR(&timerMux);
}

#ifdef USE_WATERSENSOR
void IRAM_ATTR WFpulseCounter() {
  WFpulseCount++;
}
#endif

#ifdef USE_HEAD_LEVEL_SENSOR
void IRAM_ATTR isrWHLS_TICK() {
  whls.tick();
}
#endif

void IRAM_ATTR isrBTN_TICK() {
  btn.tick();
}

void IRAM_ATTR isrENC_TICK() {
  encoder.tick();  // отработка в прерывании
}

//Запускаем таск для получения точного времени из интернет и записи в лог
void IRAM_ATTR triggerGetClock(void * parameter) {
  while (true) {
    if (WiFi.status() == WL_CONNECTED) clok1();
#ifdef SAMOVAR_USE_BLYNK
    if (!Blynk.connected() && WiFi.status() == WL_CONNECTED) {
      Blynk.connect(BLYNK_TIMEOUT_MS);
    }
#endif
    vTaskDelay(10000);
  }
}

//Запускаем таск для получения температур и различных проверок
void IRAM_ATTR triggerSysTicker(void * parameter) {
  byte CurMinST, OldMinST;
  byte tcntST = 0;
  unsigned long oldTime;                                          // Предыдущее время в милисекундах

  while (true) {
    CurMinST = (millis() / 1000 );

    // раз в секунду обновляем время на дисплее, запрашиваем значения давления, напряжения и датчика потока
    if (OldMinST != CurMinST) {

#ifdef SAMOVAR_USE_POWER
      get_current_power();
#endif

      clok();

      DS_getvalue();
      vTaskDelay(10);

      Crt = CurrentTime();
      StrCrt = Crt.substring(6) + "   " + millis2time();
      StrCrt.toCharArray(tst, 20);

      if (startval > 0) {
        tcntST++;
        if (tcntST == SamSetup.LogPeriod) {
          tcntST = 0;
          append_data();              //Записываем данные;
        }
      }

      //проверка параметров работы колонны на критичность и аварийное выключение нагрева, в случае необходимости
      if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
        check_alarm();
      } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
        check_alarm_distiller();
      } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
        check_alarm_beer();
        WFpulseCount = 100;
      }

      vTaskDelay(10);

      //Считаем прогресс отбора для текущей строки программы и время до конца завершения строки и всего отбора
      if (TargetStepps > 0) {
        //считаем прогресс
        float wp = (float)CurrrentStepps / (float)TargetStepps;

        //считаем время для текущей строки программы
        WthdrwTime = program[ProgramNum].Time * (1 - wp);
        //суммируем время текущей строки программы и всех следующих за ней
        WthdrwTimeAll = WthdrwTime;

        for (int i = ProgramNum + 1; i < ProgramLen; i++) {
          WthdrwTimeAll += program[i].Time;
        }
        WthdrwTimeS = (String)((unsigned int)WthdrwTime) + ":" + (String)((unsigned int)((WthdrwTime - (unsigned int)(WthdrwTime)) * 60));
        WthdrwTimeAllS = (String)((unsigned int)WthdrwTimeAll) + ":" + (String)((unsigned int)((WthdrwTimeAll - (unsigned int)(WthdrwTimeAll)) * 60));

        //прогресс переводим в проценты
        WthdrwlProgress = wp * 100;
      } else {
        WthdrwlProgress = 0;
        WthdrwTimeS = "";
        WthdrwTimeAllS = "";
      }
      vTaskDelay(10);

#ifdef USE_WATERSENSOR

      if (WFpulseCount < 11) WFpulseCount = 0;
      WFflowRate = ((1000.0 / (millis() - oldTime)) * WFpulseCount) / WF_CALIBRATION;
      WFflowMilliLitres = WFflowRate * 100 / 6;
      WFtotalMilliLitres += WFflowMilliLitres;
      
      if (TankSensor.avgTemp > OPEN_VALVE_TANK_TEMP && PowerOn && WFpulseCount == 0) {
        WFAlarmCount ++;
      } else {
        WFAlarmCount = 0;
      }

      WFpulseCount = 0;
      oldTime = millis();
      vTaskDelay(10);
#endif

      //Проверяем, что температурные датчики считывают температуру без проблем, если есть проблемы - пишем оператору
      if (SteamSensor.ErrCount > 10){
        SteamSensor.ErrCount = - 110;
        Msg = "Alarm! Steam sensor error!";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Alarm! {DEVICE_NAME} Steam sensor error!");
#endif        
      }
      if (PipeSensor.ErrCount > 10){
        PipeSensor.ErrCount = - 110;
        Msg = "Alarm! Pipe sensor error!";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Alarm! {DEVICE_NAME} Pipe sensor error!");
#endif        
      }
      if (WaterSensor.ErrCount > 10){
        WaterSensor.ErrCount = - 110;
        Msg = "Alarm! Water sensor error!";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Alarm! {DEVICE_NAME} Water sensor error!");
#endif        
      }
      if (TankSensor.ErrCount > 10){
        TankSensor.ErrCount = - 110;
        Msg = "Alarm! Tank sensor error!";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Alarm! {DEVICE_NAME} Tank sensor error!");
#endif        
      }

      OldMinST = CurMinST;
    }
    vTaskDelay(10);
  }
}

void setup() {
  WiFi.mode(WIFI_STA); // explicitly set mode, esp defaults to STA+AP
  WiFi.setHostname(host);
  WiFi.setAutoReconnect(true);

  Serial.begin(115200);
  Wire.begin();

  stepper.disable();

  // Configure the Prescaler at 80 the quarter of the ESP32 is cadence at 80Mhz
  // 80000000 / 80 = 1000000 tics / seconde
  timer = timerBegin(2, 80, true);
  timerAttachInterrupt(timer, &StepperTicker, true);

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);
  servo.setPeriodHertz(50);    // standard 50 hz servo
  // Частоты 500 и 2500 - подобраны для моего серво-привода. Возможно, для других частоты могут отличаться
  // 544 и 2400 - стандартные частоты
  servo.attach(SERVO_PIN, 500, 2500); // attaches the servo

  //Читаем сохраненную конфигурацию
  read_config();

  encoder.tick();  // отработка нажатия
  btn.tick();  // отработка нажатия
  //Если при старте нажата кнопка энкодера или кнопка - сохраненные параметры сбрасываются на параметры по умолчанию
  if (encoder.isHold() || btn.isHold()) {
    SamSetup.flag = 255;
  }

  if (SamSetup.flag > 250) {
    SamSetup.flag = 1;
    SamSetup.DeltaSteamTemp = 0.1;
    SamSetup.DeltaPipeTemp = 1;
    SamSetup.DeltaWaterTemp = 0;
    SamSetup.DeltaTankTemp = 0;
    SamSetup.SetSteamTemp = 0;
    SamSetup.SetPipeTemp = 0;
    SamSetup.SetWaterTemp = 0;
    SamSetup.SetTankTemp = 0;
    SamSetup.StepperStepMl = STEPPER_STEP_ML;
    SamSetup.UsePreccureCorrect = true;
    SamSetup.SteamDelay = 20;
    SamSetup.PipeDelay = 20;
    SamSetup.WaterDelay = 20;
    SamSetup.TankDelay = 20;
    SamSetup.HeaterResistant = 15.2;
    SamSetup.LogPeriod = 3;
    SamSetup.TimeZone = 3;
    char str1[] = "blue\0";
    memcpy(str1, SamSetup.SteamColor, sizeof(str1));
    char str2[] = "darkmagenta\0";
    memcpy(str2, SamSetup.PipeColor, sizeof(str2));
    char str3[] = "cornflowerblue\0";
    memcpy(str3, SamSetup.WaterColor, sizeof(str3));
    char str4[] = "crimson\0";
    memcpy(str4, SamSetup.TankColor, sizeof(str4));
    SamSetup.blynkauth[0] = '\0';
    SamSetup.videourl[0] = '\0';
    EEPROM.put(0, SamSetup);
    EEPROM.commit();
    read_config();
  }

  //Инициализируем ноги для реле
  pinMode(RELE_CHANNEL1, OUTPUT);
  digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
  pinMode(RELE_CHANNEL2, OUTPUT);
  digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  pinMode(RELE_CHANNEL3, OUTPUT);
  digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  pinMode(RELE_CHANNEL4, OUTPUT);
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#ifdef USE_WATER_VALVE
  pinMode(WATER_PUMP_PIN, OUTPUT);
  digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
#endif


  //Настраиваем меню
  Serial.println(F("Samovar started"));
  setupMenu();
  writeString("      Samovar ", 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  //delay(2000);
  writeString("Connecting to WI-FI", 3);

  //Подключаемся к WI-FI
  AsyncWiFiManagerParameter custom_blynk_token("blynk", "blynk token", SamSetup.blynkauth, 33, "blynk token");
  AsyncWiFiManager wifiManager(&server, &dns);
  wifiManager.setAPCallback(configModeCallback);
  wifiManager.setDebugOutput(false);
  wifiManager.addParameter(&custom_blynk_token);
  wifiManager.autoConnect("Samovar");

  //wifiManager.resetSettings();

  strcpy(SamSetup.blynkauth, custom_blynk_token.getValue());

  Serial.print(F("Connected to "));
  Serial.println(WiFi.SSID());
  Serial.print(F("IP address: "));
  String StIP = WiFi.localIP().toString();
  StIP.toCharArray(ipst, 16);

  Serial.println(StIP);

  if (!MDNS.begin(host)) { //http://samovar.local
    Serial.println("Error setting up MDNS responder!");
  } else {
#ifdef __SAMOVAR_DEBUG
    Serial.println("mDNS responder started");
#endif
  }

  //connectWiFi();
  writeString("Connected", 4);

  btn.setType(LOW_PULL);
  btn.setTickMode(MANUAL);
  btn.setTimeout(500);
  attachInterrupt(BTN_PIN, isrBTN_TICK, CHANGE);

#ifdef SAMOVAR_USE_BLYNK
  //Blynk.begin(auth, ssid, password);
  writeString("Connecting to Blynk ", 3);
  writeString("               ", 4);
#ifdef __SAMOVAR_DEBUG
  Serial.println("Connecting to Blynk");
#endif
#ifdef BLYNK_SAMOVAR_TOOL
  Blynk.config(SamSetup.blynkauth, "samovar-tool.ru", 8080);
#else
  Blynk.config(SamSetup.blynkauth);
#endif
  Blynk.connect(BLYNK_TIMEOUT_MS);
  Blynk.notify("{DEVICE_NAME} started");
#ifdef __SAMOVAR_DEBUG
  Serial.println("Blynk started");
#endif
#endif


#ifdef USE_UPDATE_OTA
  //Send OTA events to the browser
  ArduinoOTA.onStart([]() {
    events.send("Update Start", "ota");
  });
  ArduinoOTA.onEnd([]() {
    events.send("Update End", "ota");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    char p[32];
    sprintf(p, "Progress: %u%%\n", (progress / (total / 100)));
    events.send(p, "ota");
  });
  ArduinoOTA.onError([](ota_error_t error) {
    if (error == OTA_AUTH_ERROR) events.send("Auth Failed", "ota");
    else if (error == OTA_BEGIN_ERROR) events.send("Begin Failed", "ota");
    else if (error == OTA_CONNECT_ERROR) events.send("Connect Failed", "ota");
    else if (error == OTA_RECEIVE_ERROR) events.send("Recieve Failed", "ota");
    else if (error == OTA_END_ERROR) events.send("End Failed", "ota");
  });
  ArduinoOTA.setHostname(SAMOVAR_HOST);
  ArduinoOTA.begin();
#endif

  sensor_init();

  samovar_reset();

  WebServerInit();
#ifdef USE_WEB_SERIAL
  WebSerial.begin(&server);
  WebSerial.msgCallback(recvMsg);
#endif

#ifdef USE_WATERSENSOR
  //вешаем прерывание на изменения датчика потока воды
  attachInterrupt(WATERSENSOR_PIN, WFpulseCounter, FALLING);
#endif

#ifdef USE_HEAD_LEVEL_SENSOR
  //Задаем параметры для сенсора уровня флегмы
  whls.setType(LOW_PULL);
  whls.setDebounce(50); //игнорируем дребезг
  whls.setTickMode(MANUAL);
  whls.setTimeout(WHLS_ALARM_TIME * 1000); //время, через которое сработает тревога по уровню флегмы
  //вешаем прерывание на изменение датчика уровня флегмы
  attachInterrupt(WHEAD_LEVEL_SENSOR_PIN, isrWHLS_TICK, CHANGE);
#endif

  //вешаем прерывание на изменения по ногам энкодера
  attachInterrupt(ENC_CLK, isrENC_TICK, CHANGE);
  attachInterrupt(ENC_DT, isrENC_TICK, CHANGE);
  attachInterrupt(ENC_SW, isrENC_TICK, CHANGE);

  //disableCore0WDT();
  //disableCore1WDT();

  //Запускаем таск для получения температур и различных проверок
  xTaskCreatePinnedToCore(
    triggerSysTicker, /* Function to implement the task */
    "SysTicker", /* Name of the task */
    4000,  /* Stack size in words */
    NULL,  /* Task input parameter */
    1,  /* Priority of the task */
    &SysTickerTask1,  /* Task handle. */
    1); /* Core where the task should run */

  //Запускаем таск для получения точного времени и записи в лог
  xTaskCreatePinnedToCore(
    triggerGetClock, /* Function to implement the task */
    "GetClockTicker", /* Name of the task */
    4000,  /* Stack size in words */
    NULL,  /* Task input parameter */
    0,  /* Priority of the task */
    &GetClockTask1,  /* Task handle. */
    0); /* Core where the task should run */

  writeString("      Samovar     ", 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  writeString("                  ", 3);
  writeString("      Started     ", 4);
  Serial.println("Samovar ready");
  //Serial.print("Size = ");
  //Serial.println(sizeof(SamSetup));
}

void loop() {

#ifdef USE_UPDATE_OTA
  ArduinoOTA.handle();
#endif

  //Проверим, что не потеряли коннект с WiFI. Если потеряли - подключаемся. Энкодеру придется подождать.
  //if (WiFi.status() != WL_CONNECTED) connectWiFi();
#ifdef SAMOVAR_USE_BLYNK
  if (Blynk.connected()) {
    Blynk.run();
  }
#endif

  ws.cleanupClients();

  if (sam_command_sync != SAMOVAR_NONE) {
    switch (sam_command_sync) {
      case SAMOVAR_START:
        Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
        menu_samovar_start();
        break;
      case SAMOVAR_POWER:
        set_power(!PowerOn);
        if (SamovarStatusInt == 1000) distiller_finish();
        if (SamovarStatusInt == 2000) beer_finish();
        break;
      case SAMOVAR_RESET:
        samovar_reset();
        break;
      case CALIBRATE_START:
        pump_calibrate(CurrrentStepperSpeed);
        break;
      case CALIBRATE_STOP:
        pump_calibrate(0);
        break;
      case SAMOVAR_PAUSE:
        pause_withdrawal(true);
        break;
      case SAMOVAR_CONTINUE:
        pause_withdrawal(false);
        break;
      case SAMOVAR_SETBODYTEMP:
        set_body_temp();
        break;
      case SAMOVAR_DISTILLATION:
        Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
        SamovarStatusInt = 1000;
        startval = 1000;
        break;
      case SAMOVAR_BEER:
        Samovar_Mode = SAMOVAR_BEER_MODE;
        SamovarStatusInt = 2000;
        startval = 2000;
        break;
    }
    sam_command_sync = SAMOVAR_NONE;
  }

  if (SamovarStatusInt > 0 && SamovarStatusInt < 1000) {
    withdrawal();     //функция расчета отбора
  } else if (SamovarStatusInt == 1000) {
    distiller_proc(); //функция для проведения дистилляции
  } else if (SamovarStatusInt == 2000) {
    beer_proc();      //функция для проведения затирания
  }

  encoder_getvalue();

  //обработка нажатий кнопки и разное поведение в зависимости от режима работы
  if (btn.isPress()) {
    //если выключен - включаем
    if (!PowerOn) {
      set_power(true);
    } else if (startval == 0 && SamovarStatusInt < 1000) {
      //если включен и программа отбора не работает - запускаем программу
      menu_samovar_start();
    } else if (startval != 0 && !program_Pause  && SamovarStatusInt < 1000) {
      //если выполняется программа, и программа - не пауза, ставим на паузу или снимаем с паузы
      pause_withdrawal(!PauseOn);
    } else if (startval != 0 && program_Pause && SamovarStatusInt < 1000) {
      //если выполняется программа, и программа - пауза, переходим к следующей программе
      menu_samovar_start();
    }
    //Выход из режима калибровки - нажатие на кнопку.
    if (startval == 100) {
      startval = 0;
      menu_calibrate();
      main_menu1.switch_focus();
    }
  }
}

void getjson (void) {

  DynamicJsonDocument jsondoc(1500);

  jsondoc["bme_temp"] = bme_temp;
  jsondoc["bme_pressure"] = format_float(bme_pressure, 3);
  jsondoc["start_pressure"] = format_float(start_pressure, 3);
  jsondoc["crnt_tm"] = Crt;
  jsondoc["stm"] = millis2time();
  jsondoc["SteamTemp"] = format_float(SteamSensor.avgTemp, 3);
  jsondoc["PipeTemp"] = format_float(PipeSensor.avgTemp, 3);
  jsondoc["WaterTemp"] = format_float(WaterSensor.avgTemp, 3);
  jsondoc["TankTemp"] = format_float(TankSensor.avgTemp, 3);
  jsondoc["version"] = SAMOVAR_VERSION;
  jsondoc["VolumeAll"] = get_liquid_volume();
  jsondoc["currentvolume"] = currentvolume;
  jsondoc["ActualVolumePerHour"] = ActualVolumePerHour;
  jsondoc["PowerOn"] = (byte)PowerOn;
  jsondoc["PauseOn"] = (byte)PauseOn;
  jsondoc["WthdrwlProgress"] = WthdrwlProgress;
  jsondoc["TargetStepps"] = stepper.getTarget();
  jsondoc["CurrrentStepps"] = stepper.getCurrent();
  jsondoc["WthdrwlStatus"] = startval;
  jsondoc["CurrrentSpeed"] = stepper.getSpeed() * (byte)stepper.getState();
  vTaskDelay(10);
  jsondoc["StepperStepMl"] = SamSetup.StepperStepMl;
  jsondoc["Status"] = get_Samovar_Status();
  jsondoc["BodyTemp_Steam"] = format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3);
  jsondoc["BodyTemp_Pipe"] = format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3);

  if (Msg != "") {
    jsondoc["Msg"] = Msg;
    Msg = "";
  }
#ifdef SAMOVAR_USE_POWER
  jsondoc["current_power_volt"] = format_float(current_power_volt, 1);
  jsondoc["target_power_volt"] = format_float(target_power_volt, 1);
  jsondoc["current_power_mode"] = current_power_mode;
  jsondoc["current_power_p"] = current_power_p;
#endif

#ifdef USE_WATERSENSOR
  jsondoc["WFflowRate"] = format_float(WFflowRate, 2);
  jsondoc["WFtotalMl"] = WFtotalMilliLitres;
#endif

  jsonstr = "";
  serializeJson(jsondoc, jsonstr);
}

void configModeCallback (AsyncWiFiManager *myWiFiManager) {
  Serial.println(F("Entered config WiFi"));
  Serial.print(F("SSID "));
  Serial.println(myWiFiManager->getConfigPortalSSID());
  Serial.print(F("IP: "));
  Serial.println(WiFi.softAPIP());
  writeString("Entered config WiFi ", 1);
  writeString("SSID: Samovar       ", 2);
  writeString("IP:                 ", 3);
  writeString(WiFi.softAPIP().toString(), 4);
}

void read_config() {
  EEPROM.begin(EEPROM_SIZE);
  EEPROM.get(0, SamSetup);
  SteamSensor.SetTemp = SamSetup.SetSteamTemp;
  PipeSensor.SetTemp = SamSetup.SetPipeTemp;
  WaterSensor.SetTemp = SamSetup.SetWaterTemp;
  TankSensor.SetTemp = SamSetup.SetTankTemp;
  SteamSensor.Delay = SamSetup.SteamDelay;
  PipeSensor.Delay = SamSetup.PipeDelay;
  WaterSensor.Delay = SamSetup.WaterDelay;
  TankSensor.Delay = SamSetup.TankDelay;
  if (SamSetup.HeaterResistant == 0) SamSetup.HeaterResistant = 10;
  if (SamSetup.LogPeriod == 0) SamSetup.LogPeriod = 3;
  if (SamSetup.autospeed >= 100) SamSetup.autospeed = 0;
  CopyDSAddress(SamSetup.SteamAdress, SteamSensor.Sensor);
  CopyDSAddress(SamSetup.PipeAdress, PipeSensor.Sensor);
  CopyDSAddress(SamSetup.WaterAdress, WaterSensor.Sensor);
  CopyDSAddress(SamSetup.TankAdress, TankSensor.Sensor);

  if (SamSetup.Mode > 3) SamSetup.Mode = 0;
  Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;

  if (SamSetup.videourl[0] == 255) SamSetup.videourl[0] = '\0';
#ifdef SAMOVAR_USE_BLYNK
  if ((String)SamSetup.videourl != "") Blynk.setProperty(V20, "url", (String)SamSetup.videourl);
#endif
}
