#ifndef __SAMOVAR_RUNTIME_TASKS_H_
#define __SAMOVAR_RUNTIME_TASKS_H_

#include "modes/bk/bk_alarm.h"
#include "modes/beer/beer_runtime.h"
#include "modes/dist/dist_alarm.h"
#include "modes/dist/dist_runtime.h"
#include "modes/nbk/nbk_alarm.h"

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
  portENTER_CRITICAL_ISR(&waterPulseMux);
  WFpulseCount++;
  portEXIT_CRITICAL_ISR(&waterPulseMux);
}
#endif

#ifdef USE_HEAD_LEVEL_SENSOR
void IRAM_ATTR isrWHLS_TICK() {
  whls.tick();
}
#endif

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
            // Для ректификации используем температуру пара, для дистилляции - температуру куба
            s += format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2);
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
            // event_code: 0=норм, 1=пауза
            // event_code используется только для критических событий
            uint8_t eventCode = program_Wait ? 1 : 0;
            s += ","; s += String(eventCode); // 18: event_code
            s += ","; s += String(SamSetup.PackDens); // 19: packing_density
            s += ","; s += format_float(SamSetup.ColHeight, 2); // 20: col_height
            s += ","; s += format_float(SamSetup.ColDiam, 1);   // 21: col_diameter
            s += ","; s += format_float(CurrentHeatLoss, 0);    // 22: heat_loss

            // Тип программы: H=головы, B=тело, C=предзахлеб, T=хвосты, P=пауза, пусто=нет программы
            String programType = "";
            if (ProgramNum < 30 && program[ProgramNum].WType.length() > 0) {
              programType = program[ProgramNum].WType.substring(0, 1); // Берем первый символ
            }
            s += ","; s += programType; // 23: program_type

            // Режим работы: 0=ректификация, 1=дистилляция, 2=пиво, 3=БК, 4=НБК, 5=сувид, 6=Lua
            s += ","; s += String((int)Samovar_Mode); // 24: mode

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

      uint16_t waterPulses = 0;
      portENTER_CRITICAL(&waterPulseMux);
      waterPulses = WFpulseCount;
      WFpulseCount = 0;
      portEXIT_CRITICAL(&waterPulseMux);

      if (waterPulses < 3) waterPulses = 0;
      WFflowRate = ((1000.0 / (millis() - oldTime)) * waterPulses) / WF_CALIBRATION;
      WFflowMilliLitres = WFflowRate * 100 / 6;
      WFtotalMilliLitres += WFflowMilliLitres;

      if (TankSensor.avgTemp > (OPEN_VALVE_TANK_TEMP + 2) && PowerOn && waterPulses == 0 && !SamSetup.UseWS) {
        WFAlarmCount++;
      } else {
        WFAlarmCount = 0;
      }

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

#endif
