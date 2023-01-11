//TODO
//
//При старте колонны до стабилизации реализовать выход на предзахлеб (если установлен датчик флегмы) для смачивания насадки (дополнительная опция)
//Убрать из сохранения настроек калибровку насоса
//**************************************************************************************************************
// Подключение библиотек
//**************************************************************************************************************

//#define Serial2 Serial

#undef CONFIG_BT_ENABLED
#include <Arduino.h>

//#ifdef ESP_ARDUINO_VERSION
#include "esp32/rom/rtc.h"
#include <driver/touch_sensor.h>
//#pragma message ("NEW SDK")
//#else
//#include <soc/touch_channel.h>
//#include "rom/rtc.h"
//#pragma message ("OLD SDK")
//#endif

#include <driver/dac.h>

#include <Wire.h>
//#include <SPI.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_Sensor.h>
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

//#include <mString.h>

#include <PID_v1.h>
#include <PID_AutoTune_v0.h>

#include <ESP32Servo.h>

#include "Samovar.h"

#ifndef __SAMOVAR_DEBUG
#define ARDUINOTRACE_ENABLE 0  // Disable all traces
#endif
#include <ArduinoTrace.h>

#ifdef __SAMOVAR_NOT_USE_WDT
#include "soc/rtc_wdt.h"
#include <esp_task_wdt.h>
#endif

#include <iarduino_I2C_connect.h>
iarduino_I2C_connect I2CC;

#ifdef USE_EXPANDER
#include <PCF8575.h>
PCF8575 expander(&Wire, USE_EXPANDER, LCD_SDA, LCD_SCL);
#endif

#ifdef USE_ANALOG_EXPANDER
#include "PCF8591.h"
PCF8591 analog_expander(&Wire, USE_ANALOG_EXPANDER, LCD_SDA, LCD_SCL);
#endif

#ifdef USE_LUA
#include "lua.h"
#endif

#include <ESPNtpClient.h>

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

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

#ifdef USE_UPDATE_OTA
#include <ArduinoOTA.h>
#endif

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial
//#define BLYNK_TIMEOUT_MS 888
//#define BLYNK_HEARTBEAT 17

#include <BlynkSimpleEsp32.h>
#include <cppQueue.h>

cppQueue  msg_q(150, 5, FIFO);
#endif

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#include "distiller.h"
#include "beer.h"
#include "BK.h"
#include "SPIFFSEditor.h"

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
void distiller_finish();
void beer_finish();
void change_samovar_mode();
void saveConfigCallback();
void configModeCallback(AsyncWiFiManager *myWiFiManager);
String verbose_print_reset_reason(RESET_REASON reason);
void set_alarm();
void menu_switch_focus();

#ifdef __SAMOVAR_DEBUG
//LOG_LOCAL_LEVEL ESP_LOG_VERBOSE
//CORE_DEBUG_LEVEL ARDUHAL_LOG_LEVEL_VERBOSE
#endif

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
    } else if (Var != "") {
    }
  } else if (d == "print") {
    WebSerial.println("_______________________________________________");
    WebSerial.print("WFpulseCount = ");
    WebSerial.println(WFpulseCount);
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

#ifdef ALARM_BTN_PIN
  alarm_btn.setType(HIGH_PULL);
  alarm_btn.setTickMode(MANUAL);
  alarm_btn.setDebounce(30);
  attachInterrupt(ALARM_BTN_PIN, isrBTN_TICK, CHANGE);
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
#ifdef ALARM_BTN_PIN
    detachInterrupt(ALARM_BTN_PIN);
#endif
    detachInterrupt(ENC_CLK);
    detachInterrupt(ENC_DT);
    detachInterrupt(ENC_SW);
    encoder.tick();
#ifdef BTN_PIN
    btn.tick();
    attachInterrupt(BTN_PIN, isrBTN_TICK, CHANGE);
#endif
#ifdef ALARM_BTN_PIN
    alarm_btn.tick();
    attachInterrupt(ALARM_BTN_PIN, isrBTN_TICK, CHANGE);
#endif
    attachInterrupt(ENC_CLK, isrBTN_TICK, CHANGE);
    attachInterrupt(ENC_DT, isrBTN_TICK, CHANGE);
    attachInterrupt(ENC_SW, isrBTN_TICK, CHANGE);
    //vTaskDelay(100/portTICK_PERIOD_MS);
  }
}

//Запускаем таск для получения точного времени из интернет
void IRAM_ATTR triggerGetClock(void *parameter) {
  String qMsg;
  while (true) {
    {
      if (WiFi.status() == WL_CONNECTED) {
      }
      else {
        WiFi.disconnect();
        WiFi.reconnect();
      }
    }

#ifdef SAMOVAR_USE_BLYNK
    {
      if (!Blynk.connected() && WiFi.status() == WL_CONNECTED && SamSetup.blynkauth[0] != 0) {
        Blynk.connect(BLYNK_TIMEOUT_MS);
        vTaskDelay(50 / portTICK_PERIOD_MS);
      } else {
        if (!msg_q.isEmpty()) {
          if ( xSemaphoreTake( xMsgSemaphore, ( TickType_t ) (50 / portTICK_RATE_MS)) == pdTRUE) {
            char c[150];
            msg_q.pop(&c);
            qMsg = c;
            Blynk.notify(qMsg);
            xSemaphoreGive(xMsgSemaphore);
          }
        }
      }
    }
#endif

#ifdef USE_MQTT
    {
      if (!mqttClient.connected() && WiFi.status() == WL_CONNECTED) {
        connectToMqtt();
      }
    }
#endif
    {
      BME_getvalue(false);

      vTaskDelay(5600 / portTICK_PERIOD_MS);
    }
  }
}

//Запускаем таск для чтения давления
//void IRAM_ATTR triggerGetBMP(void *parameter) {
//  while (true) {
//    BME_getvalue(false);
//    vTaskDelay(5600 / portTICK_PERIOD_MS);
//  }
//}

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

      //            Serial.print("SysTickerButton = ");
      //            Serial.println(uxTaskGetStackHighWaterMark(SysTickerButton));
      //            Serial.print("PowerStatusTask = ");
      //            Serial.println(uxTaskGetStackHighWaterMark(PowerStatusTask));
      //            Serial.print("SysTickerTask1 = ");
      //            Serial.println(uxTaskGetStackHighWaterMark(SysTickerTask1));
      //            Serial.print("GetClockTask1 = ");
      //            Serial.println(uxTaskGetStackHighWaterMark(GetClockTask1));
      //            Serial.print("BuzzerTask = ");
      //            Serial.println(uxTaskGetStackHighWaterMark(BuzzerTask));
      //            Serial.print("DoLuaScriptTask = ");
      //            Serial.println(uxTaskGetStackHighWaterMark(DoLuaScriptTask));
      //            Serial.println("--------------------------------------------");

#ifdef USE_LUA
      //если установлена переменная запуска в цикле lua_script, запускаем
      if (btn_script.length() > 0) {
        String sr;
        if (show_lua_script) {
          WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
          WriteConsoleLog(btn_script);
          WriteConsoleLog(F("--END LUA SCRIPT--"));
        }
        sr = lua.Lua_dostring(&btn_script);
        sr.trim();
        if (sr != "") WriteConsoleLog("ERR in BTN_SCRIPT " + sr);
        btn_script = "";
      }
      if (loop_lua_fl) {
        start_lua_script();
      }
#endif


#ifdef SAMOVAR_USE_POWER
      get_current_power();
#endif

      DS_getvalue();
      vTaskDelay(10 / portTICK_PERIOD_MS);

      Crt = NTP.getTimeDateString(false);
      StrCrt = Crt.substring(6) + "   " + NTP.getUptimeString();
      StrCrt.toCharArray(tst, 20);

      if (startval != 0) {
        tcntST++;
        if (tcntST >= SamSetup.LogPeriod) {
          tcntST = 0;
          String s = append_data();  //Записываем данные в память ESP32;
          if (s != "") {
            s += ",";
            s += format_float(ACPSensor.avgTemp, 3);
            s += ",";
            s += format_float(ActualVolumePerHour, 3);
            s += ",";
            s += (String)current_power_volt;
            s += ",";
            s += format_float(WFflowRate, 2);
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

      vTaskDelay(10 / portTICK_PERIOD_MS);

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


      vTaskDelay(10 / portTICK_PERIOD_MS);

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
      vTaskDelay(10 / portTICK_PERIOD_MS);
#endif

      //Проверяем, что температурные датчики считывают температуру без проблем, если есть проблемы - пишем оператору
      if (SteamSensor.ErrCount > 10) {
        SteamSensor.ErrCount = -110;
        SendMsg(F("Ошибка датчика температуры пара!"), ALARM_MSG);
      }
      if (PipeSensor.ErrCount > 10) {
        PipeSensor.ErrCount = -110;
        SendMsg(F("Ошибка датчика температуры царги!"), ALARM_MSG);
      }
      if (WaterSensor.ErrCount > 10) {
        WaterSensor.ErrCount = -110;
        SendMsg(F("Ошибка датчика температуры воды!"), ALARM_MSG);
      }
      if (TankSensor.ErrCount > 10) {
        TankSensor.ErrCount = -110;
        SendMsg(F("Ошибка датчика температуры куба!"), ALARM_MSG);
      }
      if (ACPSensor.ErrCount > 10) {
        ACPSensor.ErrCount = -110;
        SendMsg(F("Ошибка датчика температуры в ТСА!"), ALARM_MSG);
      }

      OldMinST = CurMinST;
    }
    vTaskDelay(10 / portTICK_PERIOD_MS);
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
  delay(2000);

  Serial.begin(115200);
#ifdef __SAMOVAR_DEBUG
  esp_log_level_set("*", ESP_LOG_VERBOSE);
  Serial.println("Using ESP object:");
  Serial.println(ESP.getSdkVersion());

  Serial.println("Using lower level function:");
  Serial.println(esp_get_idf_version());
#endif

  //vr = verbose_print_reset_reason(rtc_get_reset_reason(0));
  //vr = vr + ";" + verbose_print_reset_reason(rtc_get_reset_reason(1));

  //delay(2000);
//  dac_output_disable(DAC_CHANNEL_1);
//  dac_output_disable(DAC_CHANNEL_2);
//  touch_pad_isr_deregister();
//  touch_pad_deinit();
  touch_pad_intr_disable();

  xMsgSemaphore = xSemaphoreCreateBinaryStatic(&xMsgSemaphoreBuffer);
  xSemaphoreGive(xMsgSemaphore);

  xI2CSemaphore = xSemaphoreCreateBinaryStatic(&xI2CSemaphoreBuffer);
  xSemaphoreGive(xI2CSemaphore);

  WiFi.mode(WIFI_STA);  // explicitly set mode, esp defaults to STA+AP
  WiFi.setSleep(false);
  WiFi.setHostname(host);
  WiFi.setAutoReconnect(true);

  Wire.begin(LCD_SDA, LCD_SCL);
  //Wire.begin();

  stepper.disable();

  WFtotalMilliLitres = 0;

  // Configure the Prescaler at 80 the quarter of the ESP32 is cadence at 80Mhz
  // 80000000 / 80 = 1000000 tics / seconde
  timer = timerBegin(3, 80, true);
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
  //read_config();

  //Запускаем таск для обработки нажатия кнопки и энкодера
  xTaskCreatePinnedToCore(
    taskButton,      /* Function to implement the task */
    "taskButton",    /* Name of the task */
    950,            /* Stack size in words */
    NULL,            /* Task input parameter */
    1,               /* Priority of the task */
    &SysTickerButton, /* Task handle. */
    1);              /* Core where the task should run */


  //Если при старте нажата кнопка энкодера или кнопка - сохраненные параметры сбрасываются на параметры по умолчанию
#ifdef BTN_PIN
  btn.tick();      // отработка нажатия
  if (btn.isPress()) {
    SamSetup.flag = 255;
    Serial.println("Reset configuration");
  }
#endif

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
    SamSetup.blynkauth[0] = '\0';
    SamSetup.videourl[0] = '\0';
    save_profile();
  }

  //Читаем сохраненную конфигурацию
  read_config();

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

  //Инициализируем ногу для пищалки
  pinMode(BZZ_PIN, OUTPUT);
  digitalWrite(BZZ_PIN, LOW);

  //Настраиваем меню
  Serial.println(F("Samovar started"));
  setupMenu();
  writeString("      Samovar ", 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  //delay(2000);
  writeString(F("Connecting to WI-FI"), 3);

  //Serial.print("Reset reason: ");
  //Serial.println(vr);
  for (int i = 0; i < 17; i = i + 8) {
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

  if (shouldSaveWiFiConfig) {
    if (strlen(custom_blynk_token.getValue()) == 33) {
      strcpy(SamSetup.blynkauth, custom_blynk_token.getValue());
      save_profile();
    }
  }

  encoder.tick();  // отработка нажатия
  if (encoder.isPress()) wifiManager.resetSettings();

  Serial.print(F("Connected to "));
  Serial.println(WiFi.SSID());
  Serial.print(F("IP address: "));
  String StIP = WiFi.localIP().toString();
  StIP.toCharArray(ipst, 16);

  Serial.println(StIP);

  if (!MDNS.begin(host)) {  //http://samovar.local
    Serial.println(F("Error setting up MDNS responder!"));
  } else {
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("mDNS responder started"));
#endif
  }

  //connectWiFi();
  writeString(F("Connected"), 4);

#ifdef SAMOVAR_USE_BLYNK
  if (SamSetup.blynkauth[0] != 0) {
    //Blynk.begin(auth, ssid, password);
    writeString(F("Connecting to Blynk "), 3);
    writeString("               ", 4);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Connecting to Blynk"));
#endif
#ifdef BLYNK_SAMOVAR_TOOL
    Blynk.config(SamSetup.blynkauth, BLYNK_SAMOVAR_TOOL, 8080);
#else
    Blynk.config(SamSetup.blynkauth);
#endif
    Blynk.connect(BLYNK_TIMEOUT_MS);
    Blynk.notify("{DEVICE_NAME} started");
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Blynk started"));
#endif
  }
#endif


#ifdef USE_UPDATE_OTA
  //Send OTA events to the browser
  ArduinoOTA.onStart([]() {
    events.send(("Update Start"), "ota");
  });
  ArduinoOTA.onEnd([]() {
    events.send(("Update End"), "ota");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    char p[32];
    sprintf(p, "Progress: %u%%\n", (progress / (total / 100)));
    events.send(p, "ota");
  });
  ArduinoOTA.onError([](ota_error_t error) {
    if (error == OTA_AUTH_ERROR) events.send("Auth Failed", "ota");
    else if (error == OTA_BEGIN_ERROR)
      events.send(("Begin Failed"), "ota");
    else if (error == OTA_CONNECT_ERROR)
      events.send(("Connect Failed"), "ota");
    else if (error == OTA_RECEIVE_ERROR)
      events.send(("Recieve Failed"), "ota");
    else if (error == OTA_END_ERROR)
      events.send(("End Failed"), "ota");
  });
  ArduinoOTA.setHostname(SAMOVAR_HOST);
  ArduinoOTA.begin();
#endif

  alarm_event = false;

  sensor_init();

  samovar_reset();

  WebServerInit();

#ifdef SAMOVAR_USE_POWER
  //Запускаем таск считывания параметров регулятора
  xTaskCreatePinnedToCore(
    triggerPowerStatus, /* Function to implement the task */
    "PowerStatusTask",  /* Name of the task */
    2000,               /* Stack size in words */
    NULL,               /* Task input parameter */
    1,                  /* Priority of the task */
    &PowerStatusTask,   /* Task handle. */
    0);                 /* Core where the task should run */
  //На всякий случай пошлем команду выключения питания на UART
  set_power_mode(POWER_SLEEP_MODE);
#endif

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

#ifdef USE_MQTT
  initMqtt();
  delay(500);
#endif

  //WiFi.hostByName(ntpServerName, timeServerIP);

  //Запускаем таск для получения температур и различных проверок
  xTaskCreatePinnedToCore(
    triggerSysTicker, /* Function to implement the task */
    "SysTicker",      /* Name of the task */
    2700,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &SysTickerTask1,  /* Task handle. */
    0);               /* Core where the task should run */

  //Запускаем таск для получения точного времени и записи в лог
  xTaskCreatePinnedToCore(
    triggerGetClock,    /* Function to implement the task */
    "GetClockTicker",   /* Name of the task */
    3200,               /* Stack size in words */
    NULL,               /* Task input parameter */
    1,                  /* Priority of the task */
    &GetClockTask1,     /* Task handle. */
    1);                 /* Core where the task should run */

  //  //Запускаем таск для чтения давления
  //  xTaskCreatePinnedToCore(
  //    triggerGetBMP,      /* Function to implement the task */
  //    "GetBMPTicker",     /* Name of the task */
  //    1400,               /* Stack size in words */
  //    NULL,               /* Task input parameter */
  //    1,                  /* Priority of the task */
  //    &GetBMPTask,        /* Task handle. */
  //    0);                 /* Core where the task should run */

  //  //write reset reason
  //  if (!SPIFFS.exists("/resetreason.css")) {
  //    File f = SPIFFS.open("/resetreason.css", FILE_WRITE);
  //    f.close();
  //  }
  //  File f1 = SPIFFS.open("/resetreason.css", FILE_APPEND);
  //  f1.println(vr);
  //  f1.close();
  //  vr.replace(",",";");

  NTP.setTimeZoneOffset(-SamSetup.TimeZone * 3600, 0);
  NTP.begin ();

#ifdef USE_LUA
  lua_init();
#endif

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

  ::ws.cleanupClients();

#ifdef ALARM_BTN_PIN
  alarm_btn.tick();      // отработка нажатия аварийной кнопки
  if (alarm_btn.isPress()) {
    set_alarm();
  }
#endif

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
        menu_switch_focus();
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
        if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
          SamovarStatusInt = 50;
        }
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
      case SAMOVAR_SELF_TEST:
        start_self_test();
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
  vTaskDelay(5 / portTICK_PERIOD_MS);
}

void getjson(void) {
  jsonstr = "{";
  jsonstr += "\"bme_temp\":";  jsonstr += format_float(bme_temp, 3);
  jsonstr += ",";
  jsonstr += "\"bme_pressure\":";  jsonstr += format_float(bme_pressure, 3);
  jsonstr += ",";
  jsonstr += "\"start_pressure\":"; jsonstr += format_float(start_pressure, 3);
  jsonstr += ",";
  jsonstr += "\"crnt_tm\":\""; jsonstr += Crt; jsonstr += "\"";
  jsonstr += ",";
  jsonstr += "\"stm\":\""; jsonstr += (String)NTP.getUptimeString(); jsonstr += "\"";
  jsonstr += ",";
  jsonstr += "\"SteamTemp\":"; jsonstr += format_float(SteamSensor.avgTemp, 3);
  jsonstr += ",";
  jsonstr += "\"PipeTemp\":"; jsonstr += format_float(PipeSensor.avgTemp, 3);
  jsonstr += ",";
  jsonstr += "\"WaterTemp\":"; jsonstr += format_float(WaterSensor.avgTemp, 3);
  jsonstr += ",";
  jsonstr += "\"TankTemp\":"; jsonstr += format_float(TankSensor.avgTemp, 3);
  jsonstr += ",";
  jsonstr += "\"ACPTemp\":"; jsonstr += format_float(ACPSensor.avgTemp, 3);
  jsonstr += ",";
  jsonstr += "\"version\":"; jsonstr += (String)SAMOVAR_VERSION;
  jsonstr += ",";
  jsonstr += "\"VolumeAll\":"; jsonstr += (String)get_liquid_volume();
  jsonstr += ",";
  jsonstr += "\"currentvolume\":"; jsonstr += (String)currentvolume;
  jsonstr += ",";
  jsonstr += "\"ActualVolumePerHour\":"; jsonstr += format_float(ActualVolumePerHour, 3);
  jsonstr += ",";
  jsonstr += "\"PowerOn\":"; jsonstr += (String)PowerOn;
  jsonstr += ",";
  jsonstr += "\"PauseOn\":"; jsonstr += (String)PauseOn;
  jsonstr += ",";
  jsonstr += "\"WthdrwlProgress\":"; jsonstr += (String)WthdrwlProgress;
  jsonstr += ",";
  jsonstr += "\"TargetStepps\":"; jsonstr += (String)stepper.getTarget();
  jsonstr += ",";
  jsonstr += "\"CurrrentStepps\":"; jsonstr += (String)stepper.getCurrent();
  jsonstr += ",";
  jsonstr += "\"WthdrwlStatus\":"; jsonstr += (String)startval;
  jsonstr += ",";
  jsonstr += "\"CurrrentSpeed\":"; jsonstr += (String)(round(stepper.getSpeed() * (byte)stepper.getState()));
  jsonstr += ",";
  jsonstr += "\"UseBBuzzer\":"; jsonstr += (String)SamSetup.UseBBuzzer;
  jsonstr += ",";

  vTaskDelay(10 / portTICK_PERIOD_MS);

  jsonstr += "\"StepperStepMl\":"; jsonstr += (String)SamSetup.StepperStepMl;
  jsonstr += ",";
  jsonstr += "\"BodyTemp_Steam\":"; jsonstr += format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3);
  jsonstr += ",";
  jsonstr += "\"BodyTemp_Pipe\":"; jsonstr += format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3);;
  jsonstr += ",";
  jsonstr += "\"mixer\":"; jsonstr += (String)mixer_status;
  jsonstr += ",";


  jsonstr += "\"heap\":"; jsonstr += ESP.getFreeHeap();
  jsonstr += ",";
  jsonstr += "\"rssi\":"; jsonstr += WiFi.RSSI();
  jsonstr += ",";
  //Системные параметры: totalBytes = 1507328; usedBytes = 278528; Free Heap = 127688; BME t = 27.81; RSSI = -66

  if (Msg != "") {
    jsonstr += "\"Msg\":\""; jsonstr += Msg; jsonstr += "\"";
    jsonstr += ",";
    jsonstr += "\"msglvl\":"; jsonstr += (String)msg_level;
    jsonstr += ",";
    Msg = "";
    msg_level = NONE_MSG;
  }
  if (LogMsg != "") {
    jsonstr += "\"LogMsg\":\""; jsonstr += LogMsg; jsonstr += "\"";
    jsonstr += ",";
    LogMsg = "";
  }

#ifdef SAMOVAR_USE_POWER
  jsonstr += "\"current_power_volt\":"; jsonstr += format_float(current_power_volt, 1);
  jsonstr += ",";
  jsonstr += "\"target_power_volt\":"; jsonstr += format_float(target_power_volt, 1);
  jsonstr += ",";
  jsonstr += "\"current_power_mode\":\""; jsonstr += current_power_mode; jsonstr += "\"";
  jsonstr += ",";
  jsonstr += "\"current_power_p\":"; jsonstr += (String)current_power_p;
  jsonstr += ",";
#endif

#ifdef USE_WATERSENSOR
  jsonstr += "\"WFflowRate\":"; jsonstr += format_float(WFflowRate, 2);
  jsonstr += ",";
  jsonstr += "\"WFtotalMl\":"; jsonstr += (String)WFtotalMilliLitres;
  jsonstr += ",";
#endif

  jsonstr += "\"Status\":\""; jsonstr += get_Samovar_Status() + "\"";
  jsonstr += ",";
  jsonstr += "\"Lstatus\":\""; jsonstr += Lua_status + "\"";
  jsonstr += "}";

}

void configModeCallback(AsyncWiFiManager *myWiFiManager) {
  Serial.println(F("Entered config WiFi"));
  Serial.print(F("SSID "));
  Serial.println(myWiFiManager->getConfigPortalSSID());
  Serial.print(F("IP: "));
  Serial.println(WiFi.softAPIP());
  writeString(F("Entered config WiFi "), 1);
  writeString(F("SSID: Samovar       "), 2);
  writeString(F("IP:                 "), 3);
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

  if (isnan(SamSetup.SetWaterTemp) || SamSetup.SetWaterTemp == 0) SamSetup.SetWaterTemp = TARGET_WATER_TEMP;

  //  pump_regulator.Kp = SamSetup.Kp;
  //  pump_regulator.Ki = SamSetup.Ki;
  //  pump_regulator.Kd = SamSetup.Kd;

#ifdef USE_WATER_PUMP
  pump_regulator.setpoint = SamSetup.SetWaterTemp;         // сообщаем регулятору температуру, которую он должен поддерживать
#endif

}

void SendMsg(const String m, MESSAGE_TYPE msg_type) {
  String MsgPl;
#ifdef USE_MQTT
  MsgPl = m;
  MsgPl.replace(",", ";");
  MqttSendMsg(MsgPl + "," + msg_type, "msg");
#endif
#ifdef SAMOVAR_USE_BLYNK
  switch (msg_type) {
    case 0 : MsgPl = F("Тревога! "); break;
    case 1 : MsgPl = F("Предупреждение! "); break;
    case 2 : MsgPl = ""; break;
    default : MsgPl = "";
  }
  if ( xSemaphoreTake( xMsgSemaphore, ( TickType_t ) (50 / portTICK_RATE_MS)) == pdTRUE) {
    MsgPl += "{DEVICE_NAME} - " + m;
    msg_q.push(MsgPl.c_str());
    xSemaphoreGive(xMsgSemaphore);
  }
#endif

  if (Msg != "") {
    Msg += "; ";
    if (msg_level > msg_type) msg_level = msg_type;
  } else msg_level = msg_type;

  Msg += m;

  if (Msg.length() > 250) {
    Msg = m;
    msg_level = msg_type;
  }
}

void WriteConsoleLog(String StringLogMsg) {
  StringLogMsg.replace("\"", "'");
  StringLogMsg.replace("\r", "^");
  StringLogMsg.replace("\n", " ");
  if (LogMsg != "") {
    LogMsg = LogMsg + "; " + StringLogMsg;
  } else LogMsg = StringLogMsg;

  if (LogMsg.length() > 250) {
    LogMsg = StringLogMsg;
  }

#ifdef USE_WEB_SERIAL
  WebSerial.println(StringLogMsg);
#else
  Serial.println(StringLogMsg);
#endif
}

//String verbose_print_reset_reason(RESET_REASON reason)
//{
//  String s;
//  switch (reason)
//  {
//    case 1  : s = "Vbat power on reset";break;
//    case 3  : s = "Software reset digital core";break;
//    case 4  : s = "Legacy watch dog reset digital core";break;
//    case 5  : s = "Deep Sleep reset digital core";break;
//    case 6  : s = "Reset by SLC module, reset digital core";break;
//    case 7  : s = "Timer Group0 Watch dog reset digital core";break;
//    case 8  : s = "Timer Group1 Watch dog reset digital core";break;
//    case 9  : s = "RTC Watch dog Reset digital core";break;
//    case 10 : s = "Instrusion tested to reset CPU";break;
//    case 11 : s = "Time Group reset CPU";break;
//    case 12 : s = "Software reset CPU";break;
//    case 13 : s = "RTC Watch dog Reset CPU";break;
//    case 14 : s = "for APP CPU, reseted by PRO CPU";break;
//    case 15 : s = "Reset when the vdd voltage is not stable";break;
//    case 16 : s = "RTC Watch dog reset digital core and rtc module";break;
//    default : s = "NO_MEAN";
//  }
//  return s;
//}
