//**************************************************************************************************************
// Подключение библиотек
//**************************************************************************************************************

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
#include <Ticker.h>
#include <SPIFFS.h>
#include <SPIFFSEditor.h>

#define DRIVER_STEP_TIME 1

#include "GyverEncoder.h"
#include "GyverStepper.h"
#include "GyverButton.h"

#include <ESP32Servo.h>

#include "Samovar.h"

#ifdef USE_BME680
#include "Adafruit_BME680.h"
#define BME_STRING "BME680"
#endif

#ifdef USE_BMP180
#include "Adafruit_BMP085_U.h"
#define BME_STRING "BMP180"
#endif

#ifdef USE_BMP280
#include "Adafruit_BMP280.h"
#define BME_STRING "BMP280"
#endif

#include "font.h"
#include "logic.h"

#ifdef USE_UPDATE_OTA
#include <ArduinoOTA.h>
#endif

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial
#define BLYNK_TIMEOUT_MS 888
#define BLYNK_HEARTBEAT 17

#include <BlynkSimpleEsp32.h>
#endif

//**************************************************************************************************************
// Инициализация сенсоров и функции работы с сенсорами
//**************************************************************************************************************
#include "sensorinit.h"

hw_timer_t * timer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;

void setupMenu();
void connectWiFi();
void WebServerInit(void);
void encoder_getvalue();
void menu_calibrate();
String millis2time();


#ifdef USE_WEB_SERIAL
void recvMsg(uint8_t *data, size_t len){
  WebSerial.println("Received Data...");
  String d = "";
  for(int i=0; i < len; i++){
    d += char(data[i]);
  }
  WebSerial.println(d);
}
#endif

void stopService(void)
{
  timerAlarmDisable(timer);
}

void startService(void)
{
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
void IRAM_ATTR isrWHLS_TICK(){
  whls.tick();
}
#endif

void IRAM_ATTR isrBTN_TICK(){
  btn.tick();
}

void IRAM_ATTR isrENC_TICK() {
  encoder.tick();  // отработка в прерывании
}

void setup() {

  Serial.begin(115200);
  Wire.begin();

  stepper.disable();

  // Configure the Prescaler at 80 the quarter of the ESP32 is cadence at 80Mhz
  // 80000000 / 80 = 1000000 tics / seconde
  timer = timerBegin(2, 80, true);
  timerAttachInterrupt(timer, &StepperTicker, true);

  ESP32PWM::allocateTimer(3);
  servo.setPeriodHertz(50);    // standard 50 hz servo
  // Частоты 500 и 2500 - подобраны для моего серво-привода. Возможно, для других частоты могут отличаться
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

  //Настраиваем меню
  Serial.println("Samovar started");
  setupMenu();
  writeString("      Samovar ", 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  //delay(2000);
  writeString("Connecting to WI-FI", 3);

  //Подключаемся к WI-FI
  connectWiFi();
  writeString("Connected", 4);

#ifdef SAMOVAR_USE_BLYNK
  //Blynk.begin(auth, ssid, password);
  writeString("Connecting to Blynk ", 3);
  writeString("               ", 4);
  Serial.println("Connecting to Blynk");
  Blynk.config(auth);
  Blynk.connect(BLYNK_TIMEOUT_MS);
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

  StepperTickerTask1 = NULL;

  // Start update of environment data every SAMOVAR_LOG_PERIOD second
  SensorTicker.attach(SamSetup.LogPeriod, triggerGetSensor);
  // Start update of environment data every 1 second
  SensorTempTicker.attach(1, triggerGetTempSensor);

  writeString("                  ", 3);
  writeString("      Started     ", 4);

  btn.setType(LOW_PULL);
  btn.setTickMode(MANUAL);
  btn.setTimeout(500);
  attachInterrupt(BTN_PIN, isrBTN_TICK, CHANGE);
}

void loop() {
#ifdef USE_UPDATE_OTA
  ArduinoOTA.handle();
#endif

  //Проверим, что не потеряли коннект с WiFI. Если потеряли - подключаемся. Энкодеру придется подождать.
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
#ifdef SAMOVAR_USE_BLYNK
  if(Blynk.connected()){
    Blynk.run();
  }
#endif

  ws.cleanupClients();

  if (sam_command_sync != SAMOVAR_NONE) {
    switch (sam_command_sync) {
      case SAMOVAR_START:
        menu_samovar_start();
        break;
      case SAMOVAR_POWER:
        set_power(!PowerOn);
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
    }
    sam_command_sync = SAMOVAR_NONE;
  }

  if (startval > 0) {
    withdrawal();     //функция расчета отбора
  }

  encoder_getvalue();

  //обработка нажатий кнопки и разное поведение в зависимости от режима работы
  if (btn.isPress()) {
    //если выключен - включаем
    if (!PowerOn) {
      set_power(true);
    } else if (startval == 0) {
      //если включен и программа отбора не работает - запускаем программу
      menu_samovar_start();
    } else if (startval != 0 && !program_Pause) {
      //если выполняется программа, и программа - не пауза, ставим на паузу или снимаем с паузы
      pause_withdrawal(!PauseOn);
    } else if (startval != 0 && program_Pause) {
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

  DynamicJsonDocument jsondoc(1200);

  jsondoc["bme_temp"] = bme_temp;
  jsondoc["bme_pressure"] = format_float(bme_pressure, 3);
  jsondoc["start_pressure"] = format_float(start_pressure, 3);
  //jsondoc["bme_humidity"] = bme_humidity;
  //jsondoc["bme_altitude"] = bme_altitude;
  //jsondoc["bme_gas"] = bme_gas;
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
  jsondoc["BodyTemp"] = format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3);
  jsondoc["BodyTemp_St"] = format_float(SteamSensor.BodyTemp, 3);

  if (Msg != "") {
    jsondoc["Msg"] = Msg;
    Msg = "";
  }
  //  jsondoc["WthdrwTime"] = WthdrwTimeS;
  //  jsondoc["WthdrwTimeAll"] = WthdrwTimeAllS;

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

void connectWiFi() {
  WiFi.setAutoReconnect(true);
  // Connect to WiFi network
  WiFi.begin(ssid, password);
  WiFi.setHostname(host);
  Serial.println("");

  // Wait for connection
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }
  Serial.println("");
  Serial.print("Connected to ");
  Serial.println(ssid);
  Serial.print("IP address: ");
  String StIP = WiFi.localIP().toString();
  StIP.toCharArray(ipst, 16);

  Serial.println(StIP);

  /*use mdns for host name resolution*/
  if (!MDNS.begin(host)) { //http://samovar.local
    Serial.println("Error setting up MDNS responder!");
  } else {
    Serial.println("mDNS responder started");
  }
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
}
