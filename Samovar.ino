//TODO
//
//Проверить на С подъем напряжения
//Перейти на GyverPID

// copy to /Users/user/Library/Arduino15/packages/esp32/hardware/esp32/3.x.x/tools/partitions/samovar.csv
// add to /Users/user/Library/Arduino15/packages/esp32/hardware/esp32/3.x.x/boards.txt
// esp32.menu.PartitionScheme.samovar=Samovar
// esp32.menu.PartitionScheme.samovar.build.partitions=samovar
// esp32.menu.PartitionScheme.samovar.upload.maximum_size=1638400

//**************************************************************************************************************
// Подключение библиотек
//**************************************************************************************************************

//#define Serial2 Serial

#define CONFIG_ASYNC_TCP_RUNNING_CORE 1      // force async_tcp task to be on same core as Arduino app (default is any core)
#define CONFIG_ASYNC_TCP_STACK_SIZE 4096     // reduce the stack size (default is 16K)

#undef CONFIG_BT_ENABLED
#include <Arduino.h>

#include <esp_wifi.h>

#if defined(ARDUINO_ESP32S3_DEV)
#else
#include "esp32/rom/rtc.h"
#endif

#include <driver/touch_sensor.h>
#include <esp32-hal-cpu.h>
#include <esp_heap_caps.h>
#include <esp_heap_caps_init.h>

#if defined(ARDUINO_ESP32S3_DEV)
//
#else
#include <driver/dac.h>
#endif

#include "esp_log.h"

#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_Sensor.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <ESPmDNS.h>
#include <Update.h>
//#include <ESPping.h>

#include <LiquidMenu.h>

#include <EEPROM.h>
#include <Preferences.h>

#include <GyverEncoder.h>

#include <GyverButton.h>

#include <GyverPID.h>

//#include <mString.h>

#include <PID_v1.h>
#include <PID_AutoTune_v0.h>

#include <ESP32Servo.h>

#include <iarduino_I2C_connect.h>

#include "Samovar.h"

#ifndef __SAMOVAR_DEBUG
#define ARDUINOTRACE_ENABLE 0  // Disable all traces
#endif
#include <ArduinoTrace.h>

#ifdef __SAMOVAR_NOT_USE_WDT
#include "soc/rtc_wdt.h"
#include <esp_task_wdt.h>
#endif

#ifdef USE_LUA
#include "lua.h"
#endif

#include <NTPClient.h>
WiFiUDP ntpUDP;
NTPClient NTP(ntpUDP, "ru.pool.ntp.org");

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

#ifdef USE_PRESSURE_XGZ
#include <XGZP6897D.h>
XGZP6897D pressure_sensor(USE_PRESSURE_XGZ);
#endif


#include "mod_rmvk.h"

//#include "font.h"
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

#if defined(SAMOVAR_USE_BLYNK) || defined(USE_TELEGRAM)
#include <simple_queue.h>
SimpleStringQueue msg_q(5, 200);
#endif

#ifdef USE_TELEGRAM
#include <UrlEncode.h>
#endif

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#include "distiller.h"
#include "beer.h"
#include "BK.h"
#include "nbk.h"
#include "SPIFFSEditor.h"

#include "I2CStepper.h"

//#include <HTTPClient.h>
//HTTPClient client;
//**************************************************************************************************************
// Инициализация сенсоров и функции работы с сенсорами
//**************************************************************************************************************
#include "sensorinit.h"

// Единственные определения буфера времени для LCD (см. extern в Samovar.h)
char tst[20] = "00:00:00   00:00:00";
char* timestr = (char*)tst;

void taskButton(void *pvParameters);
SemaphoreHandle_t btnSemaphore;

hw_timer_t *timer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;

// WiFiManager отключен: флагов сохранения через портал больше нет

void load_profile_nvs();
void migrate_from_eeprom();
// void reset_migration_flag(); // Только для тестирования миграции

void setupMenu();
void WebServerInit(void);
void encoder_getvalue();
void menu_calibrate();
void set_body_temp();
void distiller_finish();
void beer_finish();
void change_samovar_mode();
// WiFiManager отключен
void verbose_print_reset_reason();
void set_alarm();
void menu_switch_focus();
float get_steam_alcohol(float t);
float get_alcohol(float t);
void startService(void);
String http_sync_request_get(String url);

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
  if (Val.length() > 0) {
    WebSerial.print(Var);
    WebSerial.print(" = ");
    if (Var == "WFpulseCount") {
      WFpulseCount = (uint8_t)Val.toInt();
      WebSerial.println(WFpulseCount);
    } else if (Var.length() > 0) {
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
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  //timerEnd(timer);
  timerWrite(timer, 0);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timerAlarmDisable(timer);
#endif
}

void startService(void) {
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timerAlarm(timer, stepper.getPeriod(), true, 0);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timerAlarmWrite(timer, stepper.getPeriod(), true);
  timerAlarmEnable(timer);
#endif
}

void IRAM_ATTR StepperTicker(void) {
  portENTER_CRITICAL_ISR(&timerMux);
  StepperMoving = stepper.tickManual();
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
  BaseType_t xHigherPriorityTaskWoken = pdFALSE;
  xSemaphoreGiveFromISR(btnSemaphore, &xHigherPriorityTaskWoken);
  // Если семафор разбудил задачу с более высоким приоритетом - переключиться на неё
  portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
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
void triggerGetClock(void *parameter) {
  String qMsg;
  int counter = 0;
  while (true) {
    // Пропускаем все активности во время OTA обновления (кроме проверки WiFi)
    if (ota_running) {
      vTaskDelay(200 / portTICK_PERIOD_MS);  // Увеличиваем задержку во время OTA
      continue;
    }
    
    counter++;
    if (counter > 30) {
      NTP.update();
      counter = 0;
    }
    {
      static unsigned long wifiReconnectTimer = 0;
      if (WiFi.status() != WL_CONNECTED) {
          // попытки переподключиться к WiFi раз в 20 секунд, если не сработала автоматическая попытка переподключиться
          // Но не во время OTA обновления
          if (!ota_running && millis() - wifiReconnectTimer >= 20000) {
            WriteConsoleLog(F("WiFi.reconnect..."));
            WiFi.reconnect();
            wifiReconnectTimer = millis();
          }
      } else {
        wifiReconnectTimer = millis();
      }
    }

    // Пропускаем переподключения во время OTA обновления
    if (!ota_running) {
      // Проверка и переподключение Blynk
#ifdef SAMOVAR_USE_BLYNK
      if (!Blynk.connected() && WiFi.status() == WL_CONNECTED && SamSetup.blynkauth[0] != 0) {
        Blynk.connect(BLYNK_TIMEOUT_MS);
        vTaskDelay(50 / portTICK_PERIOD_MS);
      }
#endif

      // Проверка и переподключение MQTT
#ifdef USE_MQTT
      if (!mqttClient.connected() && WiFi.status() == WL_CONNECTED) {
        connectToMqtt();
      }
#endif
    } else {
      // Во время OTA увеличиваем задержку для освобождения ресурсов
      vTaskDelay(100 / portTICK_PERIOD_MS);
    }

    // Обработка сообщений из очереди: отправка во все включенные сервисы одновременно
    // Пропускаем отправку сообщений во время OTA для освобождения ресурсов
    if (!msg_q.isEmpty() && WiFi.status() == WL_CONNECTED && !ota_running) {
      vTaskDelay(5 / portTICK_PERIOD_MS);
      if (xSemaphoreTake(xMsgSemaphore, (TickType_t)(50 / portTICK_RATE_MS)) == pdTRUE) {
        char c[200];
        msg_q.pop(c);
        qMsg = c;
        
        // Отправка в Telegram (если включен и настроен)
#ifdef USE_TELEGRAM
        if (SamSetup.tg_token[0] != 0 && SamSetup.tg_chat_id[0] != 0) {
          http_sync_request_get(String("http://212.237.16.93/bot") + SamSetup.tg_token + "/sendMessage?chat_id=" + SamSetup.tg_chat_id + "&text=" + urlEncode(qMsg));
        }
#endif

        // Отправка в Blynk (если включен, подключен и настроен)
#ifdef SAMOVAR_USE_BLYNK
        if (Blynk.connected() && SamSetup.blynkauth[0] != 0) {
          Blynk.virtualWrite(V26, qMsg);
        }
#endif

        xSemaphoreGive(xMsgSemaphore);
      }
    }
#ifdef USE_TELEGRAM
    else if (SamSetup.tg_chat_id[0] != 0 && WiFi.status() != WL_CONNECTED) {
      Serial.println(F("Проблема с покдлючением к интернету."));
    }
    vTaskDelay(5 / portTICK_PERIOD_MS);
#endif
    {
      vTaskDelay(500 / portTICK_PERIOD_MS);
      BME_getvalue(false);
#if !(defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX))
      vTaskDelay(500 / portTICK_PERIOD_MS);
#else
      vTaskDelay(400 / portTICK_PERIOD_MS);
      pressure_sensor_get();
#endif
      vTaskDelay(3000 / portTICK_PERIOD_MS);
    }
  }
}

//Запускаем таск для получения температур и различных проверок
void triggerSysTicker(void *parameter) {
  uint8_t CurMinST = 0;
  uint8_t OldMinST = 0;
  uint8_t tcntST = 0;
  unsigned long oldTime = 0;  // Предыдущее время в милисекундах

  while (true) {
    CurMinST = (millis() / 1000);

#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX) || defined(USE_PRESSURE_1WIRE)
    //Проверим, что давление не вышло за пределы, если вышло - авария
    if (SamSetup.MaxPressureValue > 0 && pressure_value >= SamSetup.MaxPressureValue) {
      SendMsg("Превышено предельное давление!", ALARM_MSG);
      set_alarm();
    }
#endif

    // раз в секунду обновляем время на дисплее, запрашиваем значения давления, напряжения и датчика потока
    if (OldMinST != CurMinST) {
#ifdef __SAMOVAR_DEBUG1
      Serial.println(F("--------------------------------------------"));
      Serial.print(F("SysTickerButton = "));
      Serial.println(uxTaskGetStackHighWaterMark(SysTickerButton));
      Serial.print(F("PowerStatusTask = "));
      Serial.println(uxTaskGetStackHighWaterMark(PowerStatusTask));
      Serial.print(F("SysTickerTask1 = "));
      Serial.println(uxTaskGetStackHighWaterMark(SysTickerTask1));
      Serial.print(F("GetClockTask1 = "));
      Serial.println(uxTaskGetStackHighWaterMark(GetClockTask1));
      Serial.print(F("DoLuaScriptTask = "));
      Serial.println(uxTaskGetStackHighWaterMark(DoLuaScriptTask));
      Serial.println(F("--------------------------------------------"));
#endif
#ifdef USE_LUA
      //если установлена переменная btn_script, запускаем
      if (btn_script.length() > 0) {
        String sr;
        if (show_lua_script) {
          WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
          WriteConsoleLog(btn_script);
          WriteConsoleLog(F("--END LUA SCRIPT--"));
        }
        sr = lua.Lua_dostring(&btn_script);
        sr.trim();
        if (sr.length() > 0) WriteConsoleLog("ERR in BTN_SCRIPT " + sr);
        btn_script = "";
      }

      //если установлена переменная запуска в цикле lua_script, запускаем
      if (loop_lua_fl) {
        start_lua_script();
      }
#endif


#ifdef SAMOVAR_USE_POWER
      get_current_power();
#endif
      
      // Авто-расчет теплопотерь при нагреве (п. 5)
      update_heat_loss_calculation();

      DS_getvalue();
      vTaskDelay(5 / portTICK_PERIOD_MS);

      Crt = NTP.getFormattedDate();
      //StrCrt = Crt.substring(6) + "   " + NTP.getUptimeString();
      StrCrt = NTP.getFormattedTime() + "     " + NTP.getFormattedTime((unsigned long)(millis() / 1000));
      snprintf(tst, sizeof(tst), "%s   %s",
               NTP.getFormattedTime().c_str(),
               NTP.getFormattedTime((unsigned long)(millis() / 1000)).c_str());

      if (startval != 0) {
        tcntST++;
        if (tcntST >= SamSetup.LogPeriod) {
          tcntST = 0;
          String s = append_data();  //Записываем данные в память ESP32;
          if (s.length() > 0) {
            s += ",";
            s += format_float(ACPSensor.avgTemp, 3);
            s += ",";
            s += format_float(ActualVolumePerHour, 3);
            s += ",";
            s += (String)current_power_volt;
            s += ",";
            s += format_float(WFflowRate, 2);

            s += ",";
            s += format_float(get_alcohol(TankSensor.avgTemp), 2);
            s += ",";
            s += format_float(get_steam_alcohol(TankSensor.avgTemp), 2);
            s += ",";
            s += format_float(pressure_value, 2);

            // ПУНКТ 5: Расширенное логирование v.4
            // Расчет ФЧ (целевого)
            float vaporSpeed = 0;
#ifdef SAMOVAR_USE_POWER
            float netPower = (float)current_power_p - CurrentHeatLoss;
            if (netPower < 0) netPower = 0;
            // Скорость испарения мл/час (используем константу из column_math.h)
            vaporSpeed = netPower * EVAPORATION_FACTOR; 
#endif
            if (ActualVolumePerHour > 0.001f) {
              CalculatedTargetFR = (vaporSpeed / (ActualVolumePerHour * 1000.0f)) - 1.0f;
            } else {
              CalculatedTargetFR = 0;
            }
            if (CalculatedTargetFR < 0) CalculatedTargetFR = 0;

            s += ","; s += format_float(CalculatedTargetFR, 2); // 14: target_fr
            s += ","; s += format_float(CalculatedTargetFR, 2); // 15: actual_fr (в данной системе они совпадают)
            s += ","; s += format_float(impurityDetector.currentTrend, 3); // 16: temp_delta
            s += ","; s += String(impurityDetector.detectorStatus); // 17: alarm_state
            s += ","; s += String(prev_ProgramNum != ProgramNum ? 2 : (program_Wait ? 1 : 0)); // 18: event_code
            s += ","; s += String(SamSetup.PackDens); // 19: packing_density
            s += ","; s += format_float(SamSetup.ColHeight, 2); // 20: col_height
            s += ","; s += format_float(SamSetup.ColDiam, 1);   // 21: col_diameter
            s += ","; s += format_float(CurrentHeatLoss, 0);    // 22: heat_loss

#ifdef USE_MQTT
            MqttSendMsg(s, "log", 4);
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
      } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
        check_alarm_nbk();
      } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
        check_alarm_beer();
        WFpulseCount = 100;
      }

      vTaskDelay(5 / portTICK_PERIOD_MS);

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
        for (uint8_t i = ProgramNum + 1; i < ProgramLen; i++) {
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

      } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {

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

        for (uint8_t i = ProgramNum + 1; i < ProgramLen; i++) {
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


      vTaskDelay(5 / portTICK_PERIOD_MS);

#ifdef USE_WATERSENSOR

      if (WFpulseCount < 3) WFpulseCount = 0;
      WFflowRate = ((1000.0 / (millis() - oldTime)) * WFpulseCount) / WF_CALIBRATION;
      WFflowMilliLitres = WFflowRate * 100 / 6;
      WFtotalMilliLitres += WFflowMilliLitres;

      if (TankSensor.avgTemp > (OPEN_VALVE_TANK_TEMP + 2) && PowerOn && WFpulseCount == 0 && !SamSetup.UseWS) {
        WFAlarmCount++;
      } else {
        WFAlarmCount = 0;
      }

      WFpulseCount = 0;
      oldTime = millis();
      vTaskDelay(5 / portTICK_PERIOD_MS);
#endif

      //Проверяем, что температурные датчики считывают температуру без проблем, если есть проблемы - пишем оператору
      if (SteamSensor.ErrCount > 10) {
        SteamSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры пара!"), ALARM_MSG);
      }
      if (PipeSensor.ErrCount > 10) {
        PipeSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры царги!"), ALARM_MSG);
      }
      if (WaterSensor.ErrCount > 10) {
        WaterSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры воды!"), ALARM_MSG);
      }
      if (TankSensor.ErrCount > 10) {
        TankSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры куба!"), ALARM_MSG);
      }
      if (ACPSensor.ErrCount > 10) {
        ACPSensor.ErrCount = -110;
        SendMsg(("Ошибка датчика температуры в ТСА!"), ALARM_MSG);
      }

      OldMinST = CurMinST;
    }
    vTaskDelay(5 / portTICK_PERIOD_MS);
  }
}

void setup() {
  esp_log_level_set("i2c.master", ESP_LOG_NONE);
  pinMode(0, INPUT);
  vTaskDelay(600 / portTICK_PERIOD_MS);
  if (digitalRead(0) == LOW) {
    WiFi.mode(WIFI_STA);  // cannot erase if not in STA mode !
    WiFi.persistent(true);
    WiFi.disconnect(true, true);
    WiFi.persistent(false);
  }
#ifdef __SAMOVAR_NOT_USE_WDT
  esp_task_wdt_init(1, false);
  esp_task_wdt_init(2, false);
  rtc_wdt_protect_off();
  rtc_wdt_disable();
  disableCore0WDT();
  disableCore1WDT();
#endif
  heap_caps_enable_nonos_stack_heaps();

  vTaskDelay(500 / portTICK_PERIOD_MS);
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
#if defined(ARDUINO_ESP32S3_DEV)
#else
  touch_pad_intr_disable();
#endif

  xMsgSemaphore = xSemaphoreCreateBinaryStatic(&xMsgSemaphoreBuffer);
  xSemaphoreGive(xMsgSemaphore);

  xI2CSemaphore = xSemaphoreCreateBinaryStatic(&xI2CSemaphoreBuffer);
  xSemaphoreGive(xI2CSemaphore);

  WiFi.mode(WIFI_STA);  // explicitly set mode, esp defaults to STA+AP
  WiFi.disconnect(true);
  delay(50);
  WiFi.setSleep(false);
  WiFi.setHostname(host);
  WiFi.setAutoReconnect(true);

  Wire.begin(LCD_SDA, LCD_SCL);
  //Wire.begin();

  lcd_found = (check_I2C_device(LCD_ADDRESS) == LCD_ADDRESS);

  stepper.disable();

  WFtotalMilliLitres = 0;

  // Configure the Prescaler at 80 the quarter of the ESP32 is cadence at 80Mhz
  // 80000000 / 80 = 1000000 tics / seconde
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timer = timerBegin(1000000);
  timerAttachInterrupt(timer, &StepperTicker);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timer = timerBegin(2, 80, true);
  timerAttachInterrupt(timer, &StepperTicker, true);
#endif

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
    taskButton,       /* Function to implement the task */
    "taskButton",     /* Name of the task */
    1450,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &SysTickerButton, /* Task handle. */
    1);               /* Core where the task should run */


  //Если при старте нажата кнопка - Самовар запустится в режиме AP
  bool wifiAP = false;
#ifdef BTN_PIN
  btn.tick();  // отработка нажатия
  if (btn.isPress()) {
    wifiAP = true;
    vTaskDelay(2000);
  }
#endif

  //Читаем сохраненную конфигурацию
  
  // Сначала мигрируем старые настройки из EEPROM (если они есть)
  //reset_migration_flag(); // ТОЛЬКО ДЛЯ ТЕСТА! Удалить после проверки!
  migrate_from_eeprom();
  
  // Затем загружаем из NVS
  read_config();
  
  Serial.print("NVS: Configuration loaded. Flag = ");
  Serial.println(SamSetup.flag);

  // Если NVS пустой (flag > 250), инициализируем дефолтными значениями
  if (SamSetup.flag > 250) {
    Serial.println("NVS is empty. Initializing with default values...");
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
    SamSetup.UseWS = 1;
    SamSetup.ColDiam = 2.0f;
    SamSetup.ColHeight = 0.5f;
    SamSetup.PackDens = 80;
    save_profile();
    Serial.println("Default values saved to NVS");
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

  //Инициализируем ногу для пищалки
  pinMode(BZZ_PIN, OUTPUT);
  digitalWrite(BZZ_PIN, LOW);

#ifdef USE_PRESSURE_MPX
  //Инициализируем ногу для датчика давления MPX5010D
  pinMode(LUA_PIN, INPUT);
#endif

  //Настраиваем меню
  Serial.println(F("Samovar started"));
  setupMenu();
  writeString(F("      Samovar "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  //delay(2000);
  writeString(F("Connecting to WI-FI"), 3);

  //Serial.print("Reset reason: ");
  //Serial.println(vr);
  for (uint8_t i = 0; i < 17; i = i + 8) {
    chipId |= ((ESP.getEfuseMac() >> (40 - i)) & 0xff) << i;
  }
  //uint8_t *MAC = ESP.getEfuseMac();
  //Serial.printf("%02x%02x%02x%02x%02x%02x\n", MAC[5], MAC[4], MAC[3], MAC[2], MAC[1], MAC[0]);

  Serial.printf("ESP32 Chip model = %s Rev %d\n", ESP.getChipModel(), ESP.getChipRevision());
  //Serial.printf("This chip has %d cores\n", ESP.getChipCores());
  Serial.print("Chip ID: ");
  Serial.println(chipId);

  String StIP;
  //esp_wifi_set_ps( WIFI_PS_NONE );

  auto start_ap = [&]() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("Samovar"); // Без пароля для удобства подключения к странице настройки WiFi
    StIP = WiFi.softAPIP().toString();
    Serial.println(F("Started as WiFi AP"));
  };

  if (!wifiAP) {
    char ssid[64];
    char pass[64];
    bool hasCreds = load_wifi_credentials(ssid, sizeof(ssid), pass, sizeof(pass));

    if (hasCreds) {
      WiFi.mode(WIFI_STA);
      WiFi.begin(ssid, pass);
      Serial.print(F("Connecting to SSID: "));
      Serial.println(ssid);

      uint32_t startMs = millis();
      while (WiFi.status() != WL_CONNECTED && (millis() - startMs) < 15000) {
        delay(250);
      }
    }

    if (WiFi.status() == WL_CONNECTED) {
      StIP = WiFi.localIP().toString();
      Serial.print(F("Connected to "));
      Serial.println(WiFi.SSID());
    } else {
      wifiAP = true;
      start_ap();
    }
  } else {
    start_ap();
  }

  Serial.print(F("IP address: "));
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
  if (SamSetup.blynkauth[0] != 0 && !wifiAP) {
    //Blynk.begin(auth, ssid, password);
    writeString(F("Connecting to Blynk "), 3);
    writeString(F("               "), 4);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Connecting to Blynk"));
#endif
#ifdef BLYNK_SAMOVAR_TOOL
    Blynk.config(SamSetup.blynkauth, BLYNK_SAMOVAR_TOOL, 8080);
#else
    Blynk.config(SamSetup.blynkauth);
#endif
    Blynk.connect(BLYNK_TIMEOUT_MS);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Blynk started"));
#endif
  }
#endif

#ifdef USE_TELEGRAM
  if (WiFi.status() == WL_CONNECTED && SamSetup.tg_token[0] != 0 && SamSetup.tg_chat_id[0] != 0) {
    vTaskDelay(5 / portTICK_PERIOD_MS);
    http_sync_request_get(String("http://212.237.16.93/bot") + SamSetup.tg_token + "/sendMessage?chat_id=" + SamSetup.tg_chat_id + "&text=" + urlEncode("Самовар готов к работе; IP=http://" + StIP));
  } else if (SamSetup.tg_chat_id[0] != 0) {
    Serial.println(F("Проблема с покдлючением к интернету."));
  }
#endif

#ifdef USE_UPDATE_OTA
  //Send OTA events to the browser
  ArduinoOTA.onStart([]() {
    ota_running = true;  // Устанавливаем флаг активного OTA обновления
    String type;
    if (ArduinoOTA.getCommand() == U_FLASH)
      type = "Sketch";
    else {  // U_SPIFFS
      type = "Filesystem";
      SPIFFS.end();
    }
    type = type + " update start";
    events.send(type.c_str(), "ota");
    
    // Отключаем другие сервисы для освобождения ресурсов
#ifdef SAMOVAR_USE_BLYNK
    if (Blynk.connected()) {
      Blynk.disconnect();
    }
#endif
#ifdef USE_MQTT
    if (mqttClient.connected()) {
      mqttClient.disconnect();
    }
#endif
  });
  ArduinoOTA.onEnd([]() {
    ota_running = false;  // Сбрасываем флаг после завершения
    events.send(("Update End"), "ota");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    char p[32];
    sprintf(p, "Progress: %u%%\n", (progress / (total / 100)));
    events.send(p, "ota");
    yield();  // Даем возможность другим задачам выполниться
  });
  ArduinoOTA.onError([](ota_error_t error) {
    ota_running = false;  // Сбрасываем флаг при ошибке
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
  // Увеличиваем таймауты для более стабильной передачи
  ArduinoOTA.setTimeout(30000);  // 30 секунд на операцию (по умолчанию 10)
  ArduinoOTA.begin();
#endif

  alarm_event = false;

  sensor_init();

  startService();
  samovar_reset();

  WebServerInit();

#ifdef SAMOVAR_USE_POWER
  //Запускаем таск считывания параметров регулятора
  xTaskCreatePinnedToCore(
    triggerPowerStatus, /* Function to implement the task */
    "PowerStatusTask",  /* Name of the task */
    1800,               /* Stack size in words */
    NULL,               /* Task input parameter */
    1,                  /* Priority of the task */
    &PowerStatusTask,   /* Task handle. */
    0);                 /* Core where the task should run */
  //На всякий случай пошлем команду выключения питания на UART
  set_power_mode(POWER_SLEEP_MODE);
#endif

#ifdef USE_WEB_SERIAL
  WebSerial.begin(&server);
  WebSerial.onMessage(recvMsg);
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
  if (!wifiAP) {
    initMqtt();
    vTaskDelay(500);
  }
#endif

  //WiFi.hostByName(ntpServerName, timeServerIP);

  //Запускаем таск для получения температур и различных проверок
  xTaskCreatePinnedToCore(
    triggerSysTicker, /* Function to implement the task */
    "SysTicker",      /* Name of the task */
    3200,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &SysTickerTask1,  /* Task handle. */
    0);               /* Core where the task should run */

  //Запускаем таск для получения точного времени и записи в лог
  xTaskCreatePinnedToCore(
    triggerGetClock,  /* Function to implement the task */
    "GetClockTicker", /* Name of the task */
    3400,             /* Stack size in words */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &GetClockTask1,   /* Task handle. */
    1);               /* Core where the task should run */

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

  NTP.setTimeOffset(SamSetup.TimeZone * 3600);
  NTP.setUpdateInterval(1800000);//30 min
  NTP.begin(); 
  delay(100);
  // Принудительная синхронизация при старте с повторными попытками
  if (WiFi.status() == WL_CONNECTED) {
    int attempts = 0;
    while (!NTP.forceUpdate() && attempts < 2) {
      delay(500);
      attempts++;
    }
  }

#ifdef USE_LUA
  lua_init();
#endif

  writeString(F("      Samovar     "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  writeString(F("                  "), 3);
  writeString(F("      Started     "), 4);
  
  get_task_stack_usage();
  Serial.println("Samovar ready");
  
  use_I2C_dev = 0;

  if (check_I2C_device(1) == 1) {
    use_I2C_dev = 1;
    Serial.println("I2C Stepper as Mixer");
  }
  if (check_I2C_device(2) == 2) {
    use_I2C_dev = 2;
    Serial.println("I2C Stepper as Pump");
  }
  used_byte = SPIFFS.usedBytes();
  verbose_print_reset_reason();
  //Serial.println(sizeof(SamSetup));

  SamovarStatus.reserve(80);
}

void loop() {
  // Проверка переполнения стека
  if (uxTaskGetStackHighWaterMark(NULL) < 325) {
    SendMsg("Стек переполнился. Перезагрузка", ALARM_MSG);
    vTaskDelay(5000);
    ESP.restart();
  }
  //пересчитаем время работы таймера для шагового двигателя
#ifdef USE_STEPPER_ACCELERATION
  portENTER_CRITICAL_ISR(&timerMux);
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timerAlarm(timer, stepper.getPeriod(), true, 0);
#else  // ESP_ARDUINO_VERSION_MAJOR >= 3
  timerAlarmWrite(timer, stepper.getPeriod(), true);
#endif
  portEXIT_CRITICAL_ISR(&timerMux);
#endif  //USE_STEPPER_ACCELERATION

#ifdef USE_UPDATE_OTA
  ArduinoOTA.handle();
  // Во время OTA даем больше времени на обработку и чаще вызываем yield
  if (ota_running) {
    yield();
    delay(1);  // Небольшая задержка для стабильности передачи
  }
#endif

#ifdef SAMOVAR_USE_BLYNK
  // Отключаем Blynk во время OTA для освобождения ресурсов
  if (!ota_running && Blynk.connected()) {
    Blynk.run();
  }
#endif

  // Очистка WebSocket клиентов (реже во время OTA)
  if (!ota_running) {
    ::ws.cleanupClients();
  } else {
    // Во время OTA очищаем реже, чтобы не занимать ресурсы
    static unsigned long lastCleanup = 0;
    if (millis() - lastCleanup > 5000) {  // Раз в 5 секунд вместо каждого цикла
      ::ws.cleanupClients();
      lastCleanup = millis();
    }
  }

#ifdef ALARM_BTN_PIN
  alarm_btn.tick();  // отработка нажатия аварийной кнопки
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
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      //если НБК включаем или выключаем
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_NBK;
      } else
        nbk_finish();
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
        else if (SamovarStatusInt == 4000)
          nbk_finish();
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
        t_min = 0;
        program_Wait = false;
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
      case SAMOVAR_DIST_NEXT:
        run_dist_program(ProgramNum + 1);
        break;
      case SAMOVAR_BK:
        Samovar_Mode = SAMOVAR_BK_MODE;
        SamovarStatusInt = 3000;
        startval = 3000;
        break;
      case SAMOVAR_NBK:
        Samovar_Mode = SAMOVAR_NBK_MODE;
        SamovarStatusInt = 4000;
        startval = 4000;
        break;
      case SAMOVAR_NBK_NEXT:
        run_nbk_program(ProgramNum + 1);
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
  } else if (SamovarStatusInt == 4000) {
    nbk_proc();  //функция для работы с НБК
  } else if (SamovarStatusInt == 2000 && startval == 2000) {
    beer_proc();  //функция для проведения затирания
  }

  encoder_getvalue();

  process_buzzer();
  vTaskDelay(5 / portTICK_PERIOD_MS);
}

void getjson(void) {
  jsonstr.clear();
  jsonstr.concat("{");
  jsonstr.concat("\"bme_temp\":");
  jsonstr.concat(format_float(bme_temp, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"bme_pressure\":");
  jsonstr.concat(format_float(bme_pressure, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"start_pressure\":");
  jsonstr.concat(format_float(start_pressure, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"crnt_tm\":\"");
  jsonstr.concat(Crt);
  jsonstr.concat("\"");
  jsonstr.concat(",");
  jsonstr.concat("\"stm\":\"");
  jsonstr.concat(NTP.getFormattedTime((unsigned long)(millis() / 1000)));
  jsonstr.concat("\"");
  jsonstr.concat(",");
  jsonstr.concat("\"SteamTemp\":");
  jsonstr.concat(format_float(SteamSensor.avgTemp, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"PipeTemp\":");
  jsonstr.concat(format_float(PipeSensor.avgTemp, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"WaterTemp\":");
  jsonstr.concat(format_float(WaterSensor.avgTemp, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"TankTemp\":");
  jsonstr.concat(format_float(TankSensor.avgTemp, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"ACPTemp\":");
  jsonstr.concat(format_float(ACPSensor.avgTemp, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"DetectorTrend\":");
  jsonstr.concat(format_float(impurityDetector.currentTrend, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"DetectorStatus\":");
  jsonstr.concat(impurityDetector.detectorStatus);
  jsonstr.concat(",");
  jsonstr.concat("\"useautospeed\":");
  jsonstr.concat(SamSetup.useautospeed);
  jsonstr.concat(",");
  jsonstr.concat("\"version\":\"");
  jsonstr.concat(SAMOVAR_VERSION);
  jsonstr.concat("\"");
  jsonstr.concat(",");
  jsonstr.concat("\"VolumeAll\":");
  jsonstr.concat(get_liquid_volume());
  jsonstr.concat(",");
  jsonstr.concat("\"ActualVolumePerHour\":");
  jsonstr.concat(format_float(ActualVolumePerHour, 3));
  jsonstr.concat(",");
  jsonstr.concat("\"PowerOn\":");
  jsonstr.concat(PowerOn);
  jsonstr.concat(",");
  jsonstr.concat("\"PauseOn\":");
  jsonstr.concat(PauseOn);
  jsonstr.concat(",");
  jsonstr.concat("\"WthdrwlProgress\":");
  jsonstr.concat(WthdrwlProgress);
  jsonstr.concat(",");
  jsonstr.concat("\"TargetStepps\":");
  jsonstr.concat(stepper.getTarget());
  jsonstr.concat(",");
  jsonstr.concat("\"CurrrentStepps\":");
  jsonstr.concat(stepper.getCurrent());
  jsonstr.concat(",");
  jsonstr.concat("\"WthdrwlStatus\":");
  jsonstr.concat(startval);
  jsonstr.concat(",");
  jsonstr.concat("\"CurrrentSpeed\":");
  jsonstr.concat(round(stepper.getSpeed() * (uint8_t)stepper.getState()));
  jsonstr.concat(",");
  jsonstr.concat("\"UseBBuzzer\":");
  jsonstr.concat(SamSetup.UseBBuzzer);
  jsonstr.concat(",");

  vTaskDelay(2 / portTICK_PERIOD_MS);

  jsonstr.concat("\"StepperStepMl\":");
  jsonstr.concat(SamSetup.StepperStepMl);
  jsonstr.concat(",");
  jsonstr.concat("\"BodyTemp_Steam\":");
  jsonstr.concat(format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3));
  jsonstr.concat(",");
  jsonstr.concat("\"BodyTemp_Pipe\":");
  jsonstr.concat(format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3));
  jsonstr.concat(",");
  jsonstr.concat("\"mixer\":");
  jsonstr.concat(mixer_status);
  jsonstr.concat(",");
  jsonstr.concat("\"ISspd\":");
  jsonstr.concat(format_float(i2c_get_liquid_rate_by_step(get_stepper_speed()), 3));
  jsonstr.concat(",");


  jsonstr.concat("\"heap\":");
  jsonstr.concat(ESP.getFreeHeap());
  jsonstr.concat(",");
  jsonstr.concat("\"rssi\":");
  jsonstr.concat(WiFi.RSSI());
  jsonstr.concat(",");
  jsonstr.concat("\"fr_bt\":");
  jsonstr.concat(total_byte - used_byte);
  jsonstr.concat(",");
  //Системные параметры: totalBytes = 1507328; usedBytes = 278528; Free Heap = 127688; BME t = 27.81; RSSI = -66

  String pt = "";
  if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) &&
      (SamovarStatusInt == 10 || SamovarStatusInt == 15 || (SamovarStatusInt == 2000 && PowerOn))) {
    pt = program[ProgramNum].WType;
  }
  jsonstr.concat("\"PrgType\":\"");
  jsonstr.concat(pt);
  jsonstr.concat("\"");
  jsonstr.concat(",");

  if (Msg.length() > 0) {
    jsonstr.concat("\"Msg\":\"");
    jsonstr.concat(Msg);
    jsonstr.concat("\"");
    jsonstr.concat(",");
    jsonstr.concat("\"msglvl\":");
    jsonstr.concat(msg_level);
    jsonstr.concat(",");
    Msg = "";
    msg_level = NONE_MSG;
  }
  if (LogMsg.length() > 0) {
    jsonstr.concat("\"LogMsg\":\"");
    jsonstr.concat(LogMsg);
    jsonstr.concat("\"");
    jsonstr.concat(",");
    LogMsg = "";
  }

#ifdef SAMOVAR_USE_POWER
  jsonstr.concat("\"current_power_volt\":");
  jsonstr.concat(format_float(current_power_volt, 1));
  jsonstr.concat(",");
  jsonstr.concat("\"target_power_volt\":");
  jsonstr.concat(format_float(target_power_volt, 1));
  jsonstr.concat(",");
  jsonstr.concat("\"current_power_mode\":\"");
  jsonstr.concat(current_power_mode);
  jsonstr.concat("\"");
  jsonstr.concat(",");
  jsonstr.concat("\"current_power_p\":");
  jsonstr.concat(current_power_p);
  jsonstr.concat(",");
#else
  jsonstr.concat("\"current_power_volt\":");
  jsonstr.concat(0);
  jsonstr.concat(",");
  jsonstr.concat("\"target_power_volt\":");
  jsonstr.concat(0);
  jsonstr.concat(",");
  jsonstr.concat("\"current_power_mode\":\"");
  jsonstr.concat(0);
  jsonstr.concat("\"");
  jsonstr.concat(",");
  jsonstr.concat("\"current_power_p\":");
  jsonstr.concat(0);
  jsonstr.concat(",");

#endif

#ifdef USE_WATER_PUMP
  jsonstr.concat("\"wp_spd\":");
  jsonstr.concat(water_pump_speed);
  jsonstr.concat(",");
#endif

#ifdef USE_WATERSENSOR
  jsonstr.concat("\"WFflowRate\":");
  jsonstr.concat(format_float(WFflowRate, 2));
  jsonstr.concat(",");
  jsonstr.concat("\"WFtotalMl\":");
  jsonstr.concat(WFtotalMilliLitres);
  jsonstr.concat(",");
#endif

#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined(USE_PRESSURE_MPX)
  jsonstr.concat("\"prvl\":");
  jsonstr.concat(format_float(pressure_value, 2));
  jsonstr.concat(",");
#endif

  if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BK_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
    jsonstr.concat("\"alc\":");
    jsonstr.concat(format_float(get_alcohol(TankSensor.avgTemp), 2));
    jsonstr.concat(",");
    jsonstr.concat("\"stm_alc\":");
    jsonstr.concat(format_float(get_steam_alcohol(TankSensor.avgTemp), 2));
    jsonstr.concat(",");
  }

  // Добавляем информацию о прогнозе времени
  if (PowerOn && Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    jsonstr.concat("\"TimeRemaining\":");
    jsonstr.concat(String(int(timePredictor.remainingTime)));
    jsonstr.concat(",");
    jsonstr.concat("\"TotalTime\":");
    jsonstr.concat(String(int(timePredictor.predictedTotalTime)));
    jsonstr.concat(",");
  }

  jsonstr.concat("\"Status\":\"");
  jsonstr.concat(get_Samovar_Status());
  jsonstr.concat("\"");
  jsonstr.concat(",");
  jsonstr.concat("\"Lstatus\":\"");
  jsonstr.concat(Lua_status);
  jsonstr.concat("\"");
  jsonstr.concat("}");

#ifdef USE_MQTT
  //  MqttSendMsg(jsonstr, "getI");
#endif

}

// WiFiManager отключен: configModeCallback/saveConfigCallback больше не используются

void read_config() {
  load_profile_nvs();
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
  if (strlen(SamSetup.videourl) > 0) Blynk.setProperty(V20, "url", (String)SamSetup.videourl);
  Blynk.virtualWrite(V15, ipst);
#else
  SamSetup.blynkauth[0] = '\0';
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

  if (isnan(SamSetup.UseWS)) {
    SamSetup.UseWS = true;
  }

  if (isnan(SamSetup.UseST)) {
    SamSetup.UseST = true;
  }

  if (isnan(SamSetup.BVolt)) {
    SamSetup.BVolt = 230;
  }

  if (isnan(SamSetup.SetWaterTemp) || SamSetup.SetWaterTemp == 0) SamSetup.SetWaterTemp = TARGET_WATER_TEMP;
  if (isnan(SamSetup.SetACPTemp) || SamSetup.SetACPTemp == 0) SamSetup.SetACPTemp = 43;
  if (isnan(SamSetup.DistTimeF)) {
    SamSetup.DistTimeF = 16;
  }

  if (isnan(SamSetup.DistTimeF)) {
    SamSetup.DistTimeF = 16;
  }
  if (isnan(SamSetup.MaxPressureValue)) {
    SamSetup.MaxPressureValue = 0;
  }


#ifdef USE_HEAD_LEVEL_SENSOR
  if (isnan(SamSetup.UseHLS)) {
    SamSetup.UseHLS = true;
  }
#endif


  //  pump_regulator.Kp = SamSetup.Kp;
  //  pump_regulator.Ki = SamSetup.Ki;
  //  pump_regulator.Kd = SamSetup.Kd;

#ifdef USE_WATER_PUMP
  pump_regulator.setpoint = SamSetup.SetWaterTemp;  // сообщаем регулятору температуру, которую он должен поддерживать
#endif

#ifdef IGNORE_HEAD_LEVEL_SENSOR_SETTING
  SamSetup.UseHLS = true;
#endif

#ifdef USE_TELEGRAM
  if (SamSetup.tg_token[0] == 255) {
    SamSetup.tg_token[0] = '\0';
  }
  if (SamSetup.tg_chat_id[0] == 255) {
    SamSetup.tg_chat_id[0] = '\0';
  }
#else
  SamSetup.tg_token[0] = '\0';
  SamSetup.tg_chat_id[0] = '\0';
#endif
  //Инициализация детектора примесей
  init_impurity_detector();
}

void SendMsg(const String& m, MESSAGE_TYPE msg_type) {
  if (m.length() < 5) return;
  String MsgPl;
#ifdef USE_MQTT
  MsgPl = m;
  MsgPl.replace(",", ";");
  MqttSendMsg(MsgPl + "," + msg_type, "msg");
#endif
#ifdef USE_TELEGRAM
  switch (msg_type) {
    case 0: MsgPl = F("*Тревога!*\n"); break;
    case 1: MsgPl = F("*Предупреждение!*\n"); break;
    case 2: MsgPl = ""; break;
    default: MsgPl = "";
  }
  MsgPl += " Самовар - " + m;
  if (xSemaphoreTake(xMsgSemaphore, (TickType_t)(50 / portTICK_RATE_MS)) == pdTRUE) {
    msg_q.push(MsgPl.c_str());
    xSemaphoreGive(xMsgSemaphore);
  }
#endif

  if (Msg.length() > 0) {
    Msg += "; ";
    if (msg_level > msg_type) msg_level = msg_type;
  } else msg_level = msg_type;

  Msg += m;

  if (Msg.length() > 250) {
    Msg = m;
    msg_level = msg_type;
  }
  Msg.clear();
}

void WriteConsoleLog(String StringLogMsg) {

  for (size_t i = 0; i < StringLogMsg.length(); i++) {
    if (StringLogMsg[i] == '"') StringLogMsg[i] = '\'';
    else if (StringLogMsg[i] == '\r') StringLogMsg[i] = '^';
    else if (StringLogMsg[i] == '\n') StringLogMsg[i] = ' ';
  }
  if (LogMsg.length() > 0) {
    LogMsg = LogMsg + "; " + StringLogMsg;
  } else LogMsg = StringLogMsg;

  if (LogMsg.length() > 10000) {
    LogMsg = StringLogMsg;
  }

#ifdef USE_WEB_SERIAL
  WebSerial.println(StringLogMsg);
  Serial.println(StringLogMsg);
#else
  Serial.println(StringLogMsg);
#endif
}

void verbose_print_reset_reason()
{
  esp_reset_reason_t reason = esp_reset_reason();
  switch (reason)
  {
    case 1  : SamovarStatus = "Vbat power on reset"; break;
    case 3  : SamovarStatus = "Software reset digital core"; break;
    case 4  : SamovarStatus = "Legacy watch dog reset digital core"; break;
    case 5  : SamovarStatus = "Deep Sleep reset digital core"; break;
    case 6  : SamovarStatus = "Reset by SLC module, reset digital core"; break;
    case 7  : SamovarStatus = "Timer Group0 Watch dog reset digital core"; break;
    case 8  : SamovarStatus = "Timer Group1 Watch dog reset digital core"; break;
    case 9  : SamovarStatus = "RTC Watch dog Reset digital core"; break;
    case 10 : SamovarStatus = "Instrusion tested to reset CPU"; break;
    case 11 : SamovarStatus = "Time Group reset CPU"; break;
    case 12 : SamovarStatus = "Software reset CPU"; break;
    case 13 : SamovarStatus = "RTC Watch dog Reset CPU"; break;
    case 14 : SamovarStatus = "for APP CPU, reseted by PRO CPU"; break;
    case 15 : SamovarStatus = "Reset when the vdd voltage is not stable"; break;
    case 16 : SamovarStatus = "RTC Watch dog reset digital core and rtc module"; break;
    default : SamovarStatus = "NO_MEAN";
  }
  if (reason != 0) {
    SamovarStatus = "Причина последней перезагрузки: " + SamovarStatus;
    Serial.println(SamovarStatus);
    SendMsg(SamovarStatus, NOTIFY_MSG);
    SamovarStatus.clear();
  }
}
