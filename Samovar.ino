//**************************************************************************************************************
// Подключение библиотек
//**************************************************************************************************************

#include <Arduino.h>

#ifdef ESP_ARDUINO_VERSION
#include "esp32/rom/rtc.h"
#include <driver/touch_sensor.h>
#else
#include <soc/touch_channel.h>
#include "rom/rtc.h"
#endif

#include "soc/rtc_wdt.h"
#include <esp_task_wdt.h>
#include <driver/dac.h>

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
#include <ESPAsyncWiFiManager.h>

#define DRIVER_STEP_TIME 1
#include <GyverEncoder.h>

#include <GyverStepper.h>
#include <GyverButton.h>

#include <GyverPID.h>

#include <PID_v1.h>
#include <PID_AutoTune_v0.h>

#include <ESP32Servo.h>

#include "Samovar.h"

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

#include <SPIFFSEditor.h>

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

#include "mod_rmvk.h"
#include "font.h"
#include "logic.h"
#include "openlog.h"

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
#include "BK.h"

//**************************************************************************************************************
// Инициализация сенсоров и функции работы с сенсорами
//**************************************************************************************************************
#include "sensorinit.h"

void taskButton(void *pvParameters);
SemaphoreHandle_t btnSemaphore;

hw_timer_t *timer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;

//flag for saving data
bool shouldSaveWiFiConfig = false;

void setupMenu();
void WebServerInit(void);
void encoder_getvalue();
void menu_calibrate();
void set_body_temp();
String millis2time();
String CurrentTime(bool Year);
void distiller_finish();
void beer_finish();
void change_samovar_mode();
void saveConfigCallback();
void configModeCallback(AsyncWiFiManager *myWiFiManager);
String verbose_print_reset_reason(RESET_REASON reason);

#ifdef USE_WEB_SERIAL
void recvMsg(uint8_t *data, size_t len) {
  WebSerial.println("Received Data...");
  String d = "";
  d = "";
  for (int i = 0; i < len; i++) {
    d += char(data[i]);
  }
  String Var, Val;
  Var = "";
  Val = "";
  Var = getValue(d, '=', 0);
  Val = getValue(d, '=', 1);
  Var.trim();
  Val.trim();
  if (Val != "") {
    WebSerial.print(Var);
    WebSerial.print(" = ");
    if (Var == "WFpulseCount") {
      WFpulseCount = (byte)Val.toInt();
      WebSerial.println(WFpulseCount);
    } else if (Var == "pump_started") {
      pump_started = Val.toInt();
      WebSerial.println(pump_started);
    } else if (Var == "valve_status") {
      valve_status = Val.toInt();
      WebSerial.println(valve_status);
    } else if (Var == "SamSetup.Mode") {
      SamSetup.Mode = Val.toInt();
      WebSerial.println(SamSetup.Mode);
    } else if (Var == "Samovar_Mode") {
      Samovar_Mode = (SAMOVAR_MODE)Val.toInt();
      WebSerial.println(Samovar_Mode);
    } else if (Var == "Samovar_CR_Mode") {
      Samovar_CR_Mode = (SAMOVAR_MODE)Val.toInt();
      WebSerial.println(Samovar_CR_Mode);
    } else if (Var != "") {
    }
  } else if (d == "print") {
    WebSerial.println("_______________________________________________");
    WebSerial.print("WFpulseCount = ");
    WebSerial.println(WFpulseCount);
    WebSerial.print("pump_started = ");
    WebSerial.println(pump_started);
    WebSerial.print("valve_status = ");
    WebSerial.println(valve_status);
    WebSerial.print("SamSetup.Mode = ");
    WebSerial.println(SamSetup.Mode);
    WebSerial.print("Samovar_Mode = ");
    WebSerial.println(Samovar_Mode);
    WebSerial.print("Samovar_CR_Mode = ");
    WebSerial.println(Samovar_CR_Mode);
    WebSerial.println("_______________________________________________");
  } else
    WebSerial.print("echo ");
    WebSerial.println(d);
}
#endif

void stopService(void) {
  timerAlarmDisable(timer);
}

void startService(void) {
//  timerAlarmDisable(timer);
  timerAlarmWrite(timer, stepper.stepTime, true);
  timerAlarmEnable(timer);
}

void ICACHE_RAM_ATTR StepperTicker(void) {
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
  //  portBASE_TYPE xTaskWoken;
  // Прерывание по кнопке, отпускаем семафор
  //  xSemaphoreGiveFromISR( btnSemaphore, &xTaskWoken );
  xSemaphoreGiveFromISR(btnSemaphore, NULL);
  //  if ( xTaskWoken == pdTRUE) {
  //    taskYIELD();
  //  }
}

void IRAM_ATTR taskButton(void *pvParameters) {
  // Создаем семафор
  btnSemaphore = xSemaphoreCreateBinary();
  // Сразу "берем" семафор чтобы не было первого ложного срабатывания кнопки
  xSemaphoreTake(btnSemaphore, 100);
#ifdef BTN_PIN
  btn.setType(LOW_PULL);
  btn.setTickMode(MANUAL);
  btn.setDebounce(30);
  attachInterrupt(BTN_PIN, isrBTN_TICK, CHANGE);
#endif

  //  //вешаем прерывание на изменения по ногам энкодера
  attachInterrupt(ENC_CLK, isrBTN_TICK, CHANGE);
  attachInterrupt(ENC_DT, isrBTN_TICK, CHANGE);
  attachInterrupt(ENC_SW, isrBTN_TICK, CHANGE);

  while (true) {
    xSemaphoreTake(btnSemaphore, portMAX_DELAY);
    // Отключаем прерывание для устранения повторного срабатывания прерывания во время обработки
#ifdef BTN_PIN
    detachInterrupt(BTN_PIN);
#endif
    detachInterrupt(ENC_CLK);
    detachInterrupt(ENC_DT);
    detachInterrupt(ENC_SW);
    encoder.tick();
#ifdef BTN_PIN
    btn.tick();
    attachInterrupt(BTN_PIN, isrBTN_TICK, CHANGE);
#endif
    attachInterrupt(ENC_CLK, isrBTN_TICK, CHANGE);
    attachInterrupt(ENC_DT, isrBTN_TICK, CHANGE);
    attachInterrupt(ENC_SW, isrBTN_TICK, CHANGE);
    //vTaskDelay(100);
  }
}

//Запускаем таск для получения точного времени из интернет
void IRAM_ATTR triggerGetClock(void *parameter) {
  while (true) {
    if (WiFi.status() == WL_CONNECTED) clok1();
    else {
      WiFi.disconnect();
      WiFi.reconnect();
    }
#ifdef SAMOVAR_USE_BLYNK
    if (!Blynk.connected() && WiFi.status() == WL_CONNECTED) {
      Blynk.connect(BLYNK_TIMEOUT_MS);
    }
#endif
    vTaskDelay(10000);
  }
}

//Запускаем таск для получения температур и различных проверок
void IRAM_ATTR triggerSysTicker(void *parameter) {
  byte CurMinST = 0;
  byte OldMinST = 0;
  byte tcntST = 0;
  unsigned long oldTime = 0;  // Предыдущее время в милисекундах

  while (true) {
    CurMinST = (millis() / 1000);

    // раз в секунду обновляем время на дисплее, запрашиваем значения давления, напряжения и датчика потока
    if (OldMinST != CurMinST) {

#ifdef SAMOVAR_USE_POWER
      get_current_power();
#endif

      clok();

      DS_getvalue();
      vTaskDelay(10);

      Crt = CurrentTime(false);
      StrCrt = Crt.substring(6) + "   " + millis2time();
      StrCrt.toCharArray(tst, 20);

      if (startval != 0) {
        tcntST++;
        if (tcntST == SamSetup.LogPeriod) {
          tcntST = 0;
          String s = append_data();  //Записываем данные в память ESP32;
          if (s != "") {
            s += ",";
            s += format_float(ACPSensor.avgTemp, 3);
            s += ",";
            s += format_float(ActualVolumePerHour, 3);
            s += ",";
            s += (String)target_power_volt;
            s += ",";
            s += format_float(WFflowRate, 2);
#ifdef USE_OPENLOG 
            appendOLFile(s);
#endif
#ifdef USE_MQTT
            MqttSendMsg(s, "log");
#endif  
          }
        }
      }

      //проверка параметров работы колонны на критичность и аварийное выключение нагрева, в случае необходимости
      if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
        check_alarm();
      } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
        check_alarm_distiller();
      } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
        check_alarm_bk();
      } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
        check_alarm_beer();
        WFpulseCount = 100;
      }

      vTaskDelay(10);

      //Считаем прогресс для текущей строки программы и время до конца завершения строки и всего отбора (режим пива)
      if (Samovar_Mode == SAMOVAR_BEER_MODE) {
        float wp;
        if (program[ProgramNum].Time > 0 && begintime > 0) {
          wp = float(millis() - begintime) / 1000 / 60 / program[ProgramNum].Time;
        } else
          wp = 0;
        //прогресс переводим в проценты
        WthdrwlProgress = wp * 100;
        WthdrwTime = program[ProgramNum].Time * (1 - wp);

        WthdrwTimeAll = WthdrwTime;
        for (int i = ProgramNum + 1; i < ProgramLen; i++) {
          WthdrwTimeAll += program[i].Time;
        }

        String h, m;
        int hi, mi;
        hi = WthdrwTime / 60;
        mi = WthdrwTime - hi * 60;
        if (hi < 10) h = "0";
        else
          h = "";
        h += (String)hi;
        if (mi < 10) m = "0";
        else
          m = "";
        m += (String)mi;
        WthdrwTimeS = h + ":" + m;

        hi = WthdrwTimeAll / 60;
        mi = WthdrwTimeAll - hi * 60;
        if (hi < 10) h = "0";
        else
          h = "";
        h += (String)hi;
        if (mi < 10) m = "0";
        else
          m = "";
        m += (String)mi;
        WthdrwTimeAllS = h + ":" + m;

      } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
        
      }
      //Считаем прогресс отбора для текущей строки программы и время до конца завершения строки и всего отбора (режим ректификации)
      else if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE && (TargetStepps > 0 || program[ProgramNum].WType == "P")) {
        //считаем прогресс
        float wp;

        //считаем время для текущей строки программы
        if (program[ProgramNum].WType == "P") {
          WthdrwTime = (t_min - millis()) / (float)1000 / 60 / 60;
          if (WthdrwTime > program[ProgramNum].Time) WthdrwTime = program[ProgramNum].Time;
          wp = 1 - (WthdrwTime / program[ProgramNum].Time);
        } else {
          wp = (float)CurrrentStepps / (float)TargetStepps;
          WthdrwTime = program[ProgramNum].Time * (1 - wp);
        }

        //суммируем время текущей строки программы и всех следующих за ней
        WthdrwTimeAll = WthdrwTime;

        for (int i = ProgramNum + 1; i < ProgramLen; i++) {
          WthdrwTimeAll += program[i].Time;
        }

        String h, m;
        unsigned int mi;
        if (WthdrwTime < 10) h = "0";
        else
          h = "";
        h += (String)((unsigned int)WthdrwTime);
        mi = (unsigned int)((WthdrwTime - (unsigned int)(WthdrwTime)) * 60);
        if (mi < 10) m = "0";
        else
          m = "";
        m += (String)mi;

        WthdrwTimeS = h + ":" + m;

        if (WthdrwTimeAll < 10) h = "0";
        else
          h = "";
        h += (String)((unsigned int)WthdrwTimeAll);
        mi = (unsigned int)((WthdrwTimeAll - (unsigned int)(WthdrwTimeAll)) * 60);
        if (mi < 10) m = "0";
        else
          m = "";
        m += (String)mi;
        WthdrwTimeAllS = h + ":" + m;

        //прогресс переводим в проценты
        WthdrwlProgress = wp * 100;
      } else {
        WthdrwlProgress = 0;
        WthdrwTimeS = "";
        WthdrwTimeAllS = "";
      }


      vTaskDelay(10);

#ifdef USE_WATERSENSOR

      if (WFpulseCount < 3) WFpulseCount = 0;
      WFflowRate = ((1000.0 / (millis() - oldTime)) * WFpulseCount) / WF_CALIBRATION;
      WFflowMilliLitres = WFflowRate * 100 / 6;
      WFtotalMilliLitres += WFflowMilliLitres;

      if (TankSensor.avgTemp > (OPEN_VALVE_TANK_TEMP + 2) && PowerOn && WFpulseCount == 0) {
        WFAlarmCount++;
      } else {
        WFAlarmCount = 0;
      }

      WFpulseCount = 0;
      oldTime = millis();
      vTaskDelay(10);
#endif

      //Проверяем, что температурные датчики считывают температуру без проблем, если есть проблемы - пишем оператору
      if (SteamSensor.ErrCount > 10) {
        SteamSensor.ErrCount = -110;
        PrepareMsg("Ошибка датчика температуры пара!");
#ifdef SAMOVAR_USE_BLYNK
        //Если используется Blynk - пишем оператору
        Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
      }
      if (PipeSensor.ErrCount > 10) {
        PipeSensor.ErrCount = -110;
        PrepareMsg("Ошибка датчика температуры царги!");
#ifdef SAMOVAR_USE_BLYNK
        //Если используется Blynk - пишем оператору
        Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
      }
      if (WaterSensor.ErrCount > 10) {
        WaterSensor.ErrCount = -110;
        PrepareMsg("Ошибка датчика температуры воды!");
#ifdef SAMOVAR_USE_BLYNK
        //Если используется Blynk - пишем оператору
        Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
      }
      if (TankSensor.ErrCount > 10) {
        TankSensor.ErrCount = -110;
        PrepareMsg("Ошибка датчика температуры куба!");
#ifdef SAMOVAR_USE_BLYNK
        //Если используется Blynk - пишем оператору
        Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
      }
      if (ACPSensor.ErrCount > 10) {
        ACPSensor.ErrCount = -110;
        PrepareMsg("Ошибка датчика температуры в ТСА!");
#ifdef SAMOVAR_USE_BLYNK
        //Если используется Blynk - пишем оператору
        Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
      }

      OldMinST = CurMinST;
    }
    vTaskDelay(10);
  }
}

void setup() {
#ifdef __SAMOVAR_NOT_USE_WDT
  esp_task_wdt_init(1, false);
  esp_task_wdt_init(2, false);
  rtc_wdt_protect_off();
  rtc_wdt_disable();
  disableCore0WDT();
  disableCore1WDT();
#endif

  Serial.begin(115200);
  delay(1000);
  vr = verbose_print_reset_reason(rtc_get_reset_reason(0));
  vr = vr + ";" + verbose_print_reset_reason(rtc_get_reset_reason(1));
  
  //delay(2000);
  //dac_output_disable(DAC_CHANNEL_1);
  //dac_output_disable(DAC_CHANNEL_2);
  //touch_pad_isr_deregister();
  //touch_pad_deinit();
  touch_pad_intr_disable();

  WiFi.mode(WIFI_STA);  // explicitly set mode, esp defaults to STA+AP
  WiFi.setSleep(false);
  WiFi.setHostname(host);
  WiFi.setAutoReconnect(true);

  Wire.begin();

  stepper.disable();

  WFtotalMilliLitres = 0;


  // Configure the Prescaler at 80 the quarter of the ESP32 is cadence at 80Mhz
  // 80000000 / 80 = 1000000 tics / seconde
  timer = timerBegin(2, 80, true);
  timerAttachInterrupt(timer, &StepperTicker, true);

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

#ifdef SERVO_PIN
  servo.setPeriodHertz(50);  // standard 50 hz servo
  // Частоты 500 и 2500 - подобраны для моего серво-привода. Возможно, для других частоты могут отличаться
  // 544 и 2400 - стандартные частоты
  servo.attach(SERVO_PIN, 500, 2500);  // attaches the servo
#endif

  //Читаем сохраненную конфигурацию
  read_config();

  //Запускаем таск для обработки нажатия кнопки и энкодера
  xTaskCreatePinnedToCore(
    taskButton,      /* Function to implement the task */
    "taskButton",    /* Name of the task */
    4000,            /* Stack size in words */
    NULL,            /* Task input parameter */
    1,               /* Priority of the task */
    &SysTickerTask1, /* Task handle. */
    1);              /* Core where the task should run */


  encoder.tick();  // отработка нажатия
#ifdef BTN_PIN
  btn.tick();      // отработка нажатия
#endif
  //Если при старте нажата кнопка энкодера или кнопка - сохраненные параметры сбрасываются на параметры по умолчанию
  if (encoder.isPress()
#ifdef BTN_PIN
      || btn.isPress()
#endif
     ) {
    SamSetup.flag = 255;
  }

  if (SamSetup.flag > 250) {
    SamSetup.flag = 2;
    SamSetup.DeltaSteamTemp = 0.1;
    SamSetup.DeltaPipeTemp = 0.2;
    SamSetup.DeltaWaterTemp = 0;
    SamSetup.DeltaTankTemp = 0;
    SamSetup.DeltaACPTemp = 0;
    SamSetup.SetSteamTemp = 0;
    SamSetup.SetPipeTemp = 0;
    SamSetup.SetWaterTemp = 0;
    SamSetup.SetTankTemp = 0;
    SamSetup.SetACPTemp = 0;
    SamSetup.StepperStepMl = STEPPER_STEP_ML;
    SamSetup.UsePreccureCorrect = true;
    SamSetup.SteamDelay = 20;
    SamSetup.PipeDelay = 20;
    SamSetup.WaterDelay = 20;
    SamSetup.TankDelay = 20;
    SamSetup.ACPDelay = 20;
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
    char str5[] = "grey\0";
    memcpy(str5, SamSetup.ACPColor, sizeof(str5));
    SamSetup.blynkauth[0] = '\0';
    SamSetup.videourl[0] = '\0';
    save_profile();
    read_config();
  }

#ifdef USE_WATER_VALVE
  pinMode(WATER_PUMP_PIN, OUTPUT);
  digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
#endif

  //Инициализируем ногу для пищалки
  pinMode(BZZ_PIN, OUTPUT);
  digitalWrite(BZZ_PIN, LOW);

  //Настраиваем меню
  Serial.println(F("Samovar started"));
  setupMenu();
  writeString("      Samovar ", 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  //delay(2000);
  writeString("Connecting to WI-FI", 3);

  Serial.print("Reset reason: ");
  Serial.println(vr);
  for(int i=0; i<17; i=i+8) {
    chipId |= ((ESP.getEfuseMac() >> (40 - i)) & 0xff) << i;
  }
  //uint8_t *MAC = ESP.getEfuseMac();
  //Serial.printf("%02x%02x%02x%02x%02x%02x\n", MAC[5], MAC[4], MAC[3], MAC[2], MAC[1], MAC[0]); 
  
  Serial.printf("ESP32 Chip model = %s Rev %d\n", ESP.getChipModel(), ESP.getChipRevision());
  //Serial.printf("This chip has %d cores\n", ESP.getChipCores());
  Serial.print("Chip ID: "); Serial.println(chipId);
  
  //Подключаемся к WI-FI
  AsyncWiFiManagerParameter custom_blynk_token("blynk", "blynk token", SamSetup.blynkauth, 33, "blynk token");
  AsyncWiFiManager wifiManager(&server, &dns);
  wifiManager.setConfigPortalTimeout(180);
  wifiManager.setSaveConfigCallback(saveConfigCallback);
  wifiManager.setAPCallback(configModeCallback);
  wifiManager.setDebugOutput(false);
  wifiManager.addParameter(&custom_blynk_token);
  wifiManager.autoConnect("Samovar");

  //wifiManager.resetSettings();

  if (shouldSaveWiFiConfig) {
    if (strlen(custom_blynk_token.getValue()) == 33) {
      strcpy(SamSetup.blynkauth, custom_blynk_token.getValue());
      save_profile();
    }
  }

  Serial.print(F("Connected to "));
  Serial.println(WiFi.SSID());
  Serial.print(F("IP address: "));
  String StIP = WiFi.localIP().toString();
  StIP.toCharArray(ipst, 16);

  Serial.println(StIP);

  if (!MDNS.begin(host)) {  //http://samovar.local
    Serial.println("Error setting up MDNS responder!");
  } else {
#ifdef __SAMOVAR_DEBUG
    Serial.println("mDNS responder started");
#endif
  }

  //connectWiFi();
  writeString("Connected", 4);

#ifdef SAMOVAR_USE_BLYNK
  //Blynk.begin(auth, ssid, password);
  writeString("Connecting to Blynk ", 3);
  writeString("               ", 4);
#ifdef __SAMOVAR_DEBUG
  Serial.println("Connecting to Blynk");
#endif
#ifdef BLYNK_SAMOVAR_TOOL
  Blynk.config(SamSetup.blynkauth, BLYNK_SAMOVAR_TOOL, 8080);
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
    else if (error == OTA_BEGIN_ERROR)
      events.send("Begin Failed", "ota");
    else if (error == OTA_CONNECT_ERROR)
      events.send("Connect Failed", "ota");
    else if (error == OTA_RECEIVE_ERROR)
      events.send("Recieve Failed", "ota");
    else if (error == OTA_END_ERROR)
      events.send("End Failed", "ota");
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
#ifdef WHLS_HIGH_PULL
  whls.setType(HIGH_PULL);
#else
  whls.setType(LOW_PULL);
#endif
  
  whls.setDebounce(50);  //игнорируем дребезг
  whls.setTickMode(MANUAL);
  whls.setTimeout(WHLS_ALARM_TIME * 1000);  //время, через которое сработает тревога по уровню флегмы
  //вешаем прерывание на изменение датчика уровня флегмы
  attachInterrupt(WHEAD_LEVEL_SENSOR_PIN, isrWHLS_TICK, CHANGE);
#endif

  //Запускаем таск для получения температур и различных проверок
  xTaskCreatePinnedToCore(
    triggerSysTicker, /* Function to implement the task */
    "SysTicker",      /* Name of the task */
    4000,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &SysTickerTask1,  /* Task handle. */
    1);               /* Core where the task should run */

  //Запускаем таск для получения точного времени и записи в лог
  xTaskCreatePinnedToCore(
    triggerGetClock,  /* Function to implement the task */
    "GetClockTicker", /* Name of the task */
    4000,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &GetClockTask1,   /* Task handle. */
    0);               /* Core where the task should run */

  writeString("      Samovar     ", 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  writeString("                  ", 3);
  writeString("      Started     ", 4);
  Serial.println("Samovar ready");
  //Serial.print("Size = ");
  //Serial.println(sizeof(SamSetup));


#ifdef SAMOVAR_USE_POWER
  //Запускаем таск считывания параметров регулятора
  xTaskCreatePinnedToCore(
    triggerPowerStatus, /* Function to implement the task */
    "PowerStatusTask",  /* Name of the task */
    3000,               /* Stack size in words */
    NULL,               /* Task input parameter */
    1,                  /* Priority of the task */
    &PowerStatusTask,   /* Task handle. */
    1);                 /* Core where the task should run */
  //На всякий случай пошлем команду выключения питания на UART
  set_power_mode(POWER_SLEEP_MODE);
#endif

  //write reset reason
  if (!SPIFFS.exists("/resetreason.css")) {
    File f = SPIFFS.open("/resetreason.css", FILE_WRITE);
    f.close();
  }
  File f1 = SPIFFS.open("/resetreason.css", FILE_APPEND);
  f1.println(vr);
  f1.close();
  vr.replace(",",";");
  
#ifdef USE_MQTT
  initMqtt();
  while (!mqttClient.connected()) delay(50);
#endif  
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

#ifdef BTN_PIN
  //обработка нажатий кнопки и разное поведение в зависимости от режима работы
  btn.tick();
  if (btn.isPress()) {
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      //если выключен - включаем
      if (!PowerOn) {
        set_power(true);
      } else if (startval == 0 && SamovarStatusInt < 1000) {
        //если включен и программа отбора не работает - запускаем программу
        menu_samovar_start();
      } else if (startval != 0 && !program_Pause && SamovarStatusInt < 1000) {
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
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      //если дистилляция включаем или выключаем
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_DISTILLATION;
      } else
        distiller_finish();
    } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
      //если дистилляция включаем или выключаем
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_BK;
      } else
        bk_finish();
    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      //если пиво включаем или двигаем программу
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_BEER;
      } else
        run_beer_program(ProgramNum + 1);
    }
  }
#endif

  if (sam_command_sync != SAMOVAR_NONE) {
    switch (sam_command_sync) {
      case SAMOVAR_START:
        Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
        menu_samovar_start();
        break;
      case SAMOVAR_POWER:
        if (SamovarStatusInt == 1000) distiller_finish();
        else if (SamovarStatusInt == 2000)
          beer_finish();
        else if (SamovarStatusInt == 3000)
          bk_finish();
        else
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
      case SAMOVAR_BEER_NEXT:
        run_beer_program(ProgramNum + 1);
        break;
      case SAMOVAR_BK:
        Samovar_Mode = SAMOVAR_BK_MODE;
        SamovarStatusInt = 3000;
        startval = 3000;
        break;
      case SAMOVAR_NONE:
        break;
    }
    if (sam_command_sync != SAMOVAR_RESET) {
      sam_command_sync = SAMOVAR_NONE;
    }
  }

  if (SamovarStatusInt > 0 && SamovarStatusInt < 1000) {
    withdrawal();  //функция расчета отбора
  } else if (SamovarStatusInt == 1000) {
    distiller_proc();  //функция для проведения дистилляции
  } else if (SamovarStatusInt == 3000) {
    bk_proc();  //функция для работы с БК
  } else if (SamovarStatusInt == 2000 && startval == 2000) {
    beer_proc();  //функция для проведения затирания
  }

  encoder_getvalue();
  
  set_buzzer(false);
}

void getjson(void) {

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
  jsondoc["ACPTemp"] = format_float(ACPSensor.avgTemp, 3);
  jsondoc["version"] = SAMOVAR_VERSION;
  jsondoc["VolumeAll"] = get_liquid_volume();
  jsondoc["currentvolume"] = currentvolume;
  jsondoc["ActualVolumePerHour"] = format_float(ActualVolumePerHour, 3);
  jsondoc["PowerOn"] = (byte)PowerOn;
  jsondoc["PauseOn"] = (byte)PauseOn;
  jsondoc["WthdrwlProgress"] = WthdrwlProgress;
  jsondoc["TargetStepps"] = stepper.getTarget();
  jsondoc["CurrrentStepps"] = stepper.getCurrent();
  jsondoc["WthdrwlStatus"] = startval;
  jsondoc["CurrrentSpeed"] = round(stepper.getSpeed() * (byte)stepper.getState());
  vTaskDelay(10);
  jsondoc["StepperStepMl"] = SamSetup.StepperStepMl;
  jsondoc["Status"] = get_Samovar_Status();
  jsondoc["BodyTemp_Steam"] = format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3);
  jsondoc["BodyTemp_Pipe"] = format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3);
  jsondoc["mixer"] = mixer_status;

  if (esp32_temp > 85) {
    PrepareMsg("Высокая температура ESP32");
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Внимание! {DEVICE_NAME} - " + Msg);
#endif
  }
  if (Msg != "") {
#ifdef USE_MQTT
     String MsgPl;
     MsgPl = Msg;
     MsgPl.replace(",",";");
     MqttSendMsg(MsgPl + ",0", "msg");
#endif  
    jsondoc["Msg"] = Msg;
    Msg = "";
  }
  if (LogMsg != "") {
    jsondoc["LogMsg"] = LogMsg;
    LogMsg = "";
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

void configModeCallback(AsyncWiFiManager *myWiFiManager) {
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

void saveConfigCallback() {
  shouldSaveWiFiConfig = true;
}

void read_config() {
  EEPROM.begin(EEPROM_SIZE);
  EEPROM.get(0, SamSetup);
  SteamSensor.SetTemp = SamSetup.SetSteamTemp;
  PipeSensor.SetTemp = SamSetup.SetPipeTemp;
  WaterSensor.SetTemp = SamSetup.SetWaterTemp;
  TankSensor.SetTemp = SamSetup.SetTankTemp;
  ACPSensor.SetTemp = SamSetup.SetACPTemp;
  SteamSensor.Delay = SamSetup.SteamDelay;
  PipeSensor.Delay = SamSetup.PipeDelay;
  WaterSensor.Delay = SamSetup.WaterDelay;
  TankSensor.Delay = SamSetup.TankDelay;
  ACPSensor.Delay = SamSetup.ACPDelay;
  if (SamSetup.HeaterResistant == 0) SamSetup.HeaterResistant = 10;
  if (SamSetup.LogPeriod == 0) SamSetup.LogPeriod = 3;
  if (SamSetup.autospeed >= 100) SamSetup.autospeed = 0;
  CopyDSAddress(SamSetup.SteamAdress, SteamSensor.Sensor);
  CopyDSAddress(SamSetup.PipeAdress, PipeSensor.Sensor);
  CopyDSAddress(SamSetup.WaterAdress, WaterSensor.Sensor);
  CopyDSAddress(SamSetup.TankAdress, TankSensor.Sensor);
  CopyDSAddress(SamSetup.ACPAdress, ACPSensor.Sensor);

  if (SamSetup.Mode > 4) SamSetup.Mode = 0;
  Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;

  if (SamSetup.videourl[0] == 255) SamSetup.videourl[0] = '\0';
#ifdef SAMOVAR_USE_BLYNK
  if ((String)SamSetup.videourl != "") Blynk.setProperty(V20, "url", (String)SamSetup.videourl);
  Blynk.virtualWrite(V15, ipst);
#endif

  if (isnan(SamSetup.Kp)) {
    SamSetup.Kp = 150;
  }
  if (isnan(SamSetup.Ki)) {
    SamSetup.Ki = 1.4;
  }
  if (isnan(SamSetup.Kd)) {
    SamSetup.Kd = 1.4;
  }
  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  if (isnan(SamSetup.StbVoltage)) {
    SamSetup.StbVoltage = 100;
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

  //  pump_regulator.Kp = SamSetup.Kp;
  //  pump_regulator.Ki = SamSetup.Ki;
  //  pump_regulator.Kd = SamSetup.Kd;
}

void PrepareMsg(String m){
  if (Msg!=""){
    Msg += "; ";
  }
  if (Msg.length() > 250) Msg = "";
  Msg += m;
}

void WriteConsoleLog(String StringLogMsg) {
  LogMsg = LogMsg + "\n" + StringLogMsg;
#ifdef __SAMOVAR_DEBUG
  //Serial.println(StringLogMsg);
#endif
#ifdef USE_WEB_SERIAL
  WebSerial.println(StringLogMsg);
#endif
}

String verbose_print_reset_reason(RESET_REASON reason)
{
  String s;
  switch ( reason)
  {
    case 1  : s = "Vbat power on reset";break;
    case 3  : s = "Software reset digital core";break;
    case 4  : s = "Legacy watch dog reset digital core";break;
    case 5  : s = "Deep Sleep reset digital core";break;
    case 6  : s = "Reset by SLC module, reset digital core";break;
    case 7  : s = "Timer Group0 Watch dog reset digital core";break;
    case 8  : s = "Timer Group1 Watch dog reset digital core";break;
    case 9  : s = "RTC Watch dog Reset digital core";break;
    case 10 : s = "Instrusion tested to reset CPU";break;
    case 11 : s = "Time Group reset CPU";break;
    case 12 : s = "Software reset CPU";break;
    case 13 : s = "RTC Watch dog Reset CPU";break;
    case 14 : s = "for APP CPU, reseted by PRO CPU";break;
    case 15 : s = "Reset when the vdd voltage is not stable";break;
    case 16 : s = "RTC Watch dog reset digital core and rtc module";break;
    default : s = "NO_MEAN";
  }
  return s;
}
